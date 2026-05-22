"""Tests for data360.errors module."""

import logging

import httpx
import pytest

from data360.errors import (
    APIError,
    Data360MCPError,
    Data360TimeoutError,
    NotFoundError,
    ParseError,
    RequestError,
    ValidationError,
    classify_error,
)


@pytest.fixture(autouse=True)
def suppress_error_logs(caplog):
    """Suppress data360.errors log output for all tests unless explicitly asserted."""
    with caplog.at_level(logging.CRITICAL, logger="data360.errors"):
        yield


class TestData360MCPError:
    """Tests for the base error class."""

    def test_uses_registry_message(self):
        """Known error codes should use messages from the registry."""
        err = Data360MCPError(error_code="timeout:search")
        assert "timed out" in err.detail.lower()

    def test_uses_fallback_message(self):
        """Unknown error codes should use the default fallback message."""
        err = Data360MCPError(error_code="unknown:foo")
        assert err.detail == "Something went wrong. Please try again."

    def test_custom_detail_overrides_registry(self):
        """An explicit detail should override the registry message."""
        err = Data360MCPError(error_code="timeout:search", detail="Custom message")
        assert err.detail == "Custom message"

    def test_original_error_preserved(self):
        """The original exception should be accessible."""
        original = ValueError("original")
        err = Data360MCPError(error_code="unexpected:test", original_error=original)
        assert err.original_error is original

    def test_to_dict(self):
        """to_dict should return a structured dict."""
        original = ValueError("boom")
        err = Data360MCPError(
            error_code="http_error:search",
            detail="HTTP error 500",
            original_error=original,
        )
        d = err.to_dict()
        assert d["error_code"] == "http_error:search"
        assert d["detail"] == "HTTP error 500"
        assert d["original_error"] == "boom"

    def test_to_dict_without_original(self):
        """to_dict without original_error should not include it."""
        err = Data360MCPError(error_code="unexpected:test")
        d = err.to_dict()
        assert "original_error" not in d


class TestSubclasses:
    """Tests for specific error subclasses."""

    def test_api_error(self):
        err = APIError(context="search", status_code=500, response_text="Internal Server Error")
        assert err.status_code == 500
        assert "HTTP 500: Internal Server Error" in err.detail
        assert err.error_code == "http_error:search"

    def test_data360_timeout_error(self):
        err = Data360TimeoutError(context="metadata")
        assert err.error_code == "timeout:metadata"
        assert "timed out" in err.detail.lower()

    def test_request_error(self):
        err = RequestError(context="data")
        assert err.error_code == "request_error:data"
        assert "network error" in err.detail.lower()

    def test_parse_error_default_message(self):
        err = ParseError(context="search")
        assert err.error_code == "parse_error:search"
        assert "parse" in err.detail.lower()

    def test_parse_error_custom_detail(self):
        err = ParseError(context="search", detail="Custom parse error")
        assert err.detail == "Custom parse error"

    def test_validation_error(self):
        err = ValidationError(context="data")
        assert err.error_code == "validation_error:data"

    def test_not_found_error(self):
        err = NotFoundError(context="indicator")
        assert err.error_code == "not_found:indicator"
        assert "not found" in err.detail.lower() or "no indicators" in err.detail.lower()


class TestClassifyError:
    """Tests for the classify_error helper."""

    def test_http_status_error(self):
        """httpx.HTTPStatusError should map to APIError."""
        request = httpx.Request("GET", "http://example.com")
        response = httpx.Response(status_code=404, text="Not Found", request=request)
        exc = httpx.HTTPStatusError("Not Found", request=request, response=response)

        result = classify_error(exc, context="search")

        assert isinstance(result, APIError)
        assert result.status_code == 404
        assert result.error_code == "http_error:search"

    def test_timeout_exception(self):
        """httpx.TimeoutException should map to Data360TimeoutError."""
        exc = httpx.ReadTimeout("read timed out")

        result = classify_error(exc, context="metadata")

        assert isinstance(result, Data360TimeoutError)
        assert result.error_code == "timeout:metadata"

    def test_request_error(self):
        """httpx.RequestError (e.g. ConnectError) should map to RequestError."""
        exc = httpx.ConnectError("Connection refused")

        result = classify_error(exc, context="data")

        assert isinstance(result, RequestError)
        assert result.error_code == "request_error:data"

    def test_non_httpx_exception(self):
        """Non-httpx exceptions should map to generic Data360MCPError."""
        exc = KeyError("missing_key")

        result = classify_error(exc, context="disaggregation")

        assert isinstance(result, Data360MCPError)
        assert result.error_code == "unexpected:disaggregation"
        assert result.original_error is exc

    def test_all_subclasses_inherit_base(self):
        """All error subclasses should be instances of Data360MCPError."""
        errors = [
            APIError(context="test", status_code=500),
            Data360TimeoutError(context="test"),
            RequestError(context="test"),
            ParseError(context="test"),
            ValidationError(context="test"),
            NotFoundError(context="test"),
        ]
        for err in errors:
            assert isinstance(err, Data360MCPError), (
                f"{type(err).__name__} is not a Data360MCPError"
            )


class TestLogging:
    """Tests for the automatic logging behaviour in Data360MCPError.__init__."""

    def test_logs_on_construction(self, caplog):
        """Constructing any Data360MCPError should emit a log record."""
        with caplog.at_level(logging.ERROR, logger="data360.errors"):
            Data360MCPError(error_code="timeout:search")
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.ERROR
        assert "timeout:search" in record.message

    def test_not_found_logs_at_warning(self, caplog):
        """NotFoundError should log at WARNING, not ERROR."""
        with caplog.at_level(logging.WARNING, logger="data360.errors"):
            NotFoundError(context="indicator")
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING

    def test_traceback_captured_for_raised_exception(self, caplog):
        """When original_error was raised, exc_info should include a traceback."""
        try:
            raise ValueError("boom")
        except ValueError as exc:
            original = exc

        with caplog.at_level(logging.ERROR, logger="data360.errors"):
            Data360MCPError(
                error_code="unexpected:test", original_error=original
            )

        assert len(caplog.records) == 1
        record = caplog.records[0]
        # exc_info is a (type, value, traceback) tuple; traceback must be non-None
        assert record.exc_info is not None
        assert record.exc_info[2] is not None, "Expected a real traceback"

    def test_no_exc_info_without_original_error(self, caplog):
        """When no original_error is provided, exc_info should be None."""
        with caplog.at_level(logging.ERROR, logger="data360.errors"):
            Data360MCPError(error_code="unexpected:test")
        assert len(caplog.records) == 1
        assert caplog.records[0].exc_info is None
