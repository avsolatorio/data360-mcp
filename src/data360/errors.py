"""Centralized error management for the Data360 MCP server.

Provides a unified error hierarchy for consistent, LLM-actionable error messages.
Follows the pattern from https://github.com/avsolatorio/data-ai-chatbot/blob/dev/backend/app/core/errors.py

Error codes follow the format: "<type>:<context>" (e.g. "http_error:search", "timeout:metadata").
"""

from typing import Any


# ---------------------------------------------------------------------------
# Message registry - maps error codes to user/LLM-friendly messages
# ---------------------------------------------------------------------------
_ERROR_MESSAGES: dict[str, str] = {
    # HTTP / network errors
    "http_error:search": "The search request failed with an HTTP error. Please try again.",
    "http_error:metadata": "Failed to fetch metadata due to an HTTP error. Verify the indicator_id and database_id are correct.",
    "http_error:disaggregation": "Failed to fetch disaggregation options due to an HTTP error. Verify the indicator_id and database_id are correct.",
    "http_error:data": "Failed to fetch data due to an HTTP error. Verify the indicator_id, database_id, and filters are correct.",
    # Timeouts
    "timeout:search": "The search request timed out. Please try again.",
    "timeout:metadata": "The metadata request timed out. Please try again.",
    "timeout:disaggregation": "The disaggregation request timed out. Please try again.",
    "timeout:data": "The data request timed out. Please try again.",
    # Request errors (connection issues, DNS, etc.)
    "request_error:search": "A network error occurred during search. Check connectivity and try again.",
    "request_error:metadata": "A network error occurred fetching metadata. Check connectivity and try again.",
    "request_error:disaggregation": "A network error occurred fetching disaggregation options. Check connectivity and try again.",
    "request_error:data": "A network error occurred fetching data. Check connectivity and try again.",
    # Parse errors
    "parse_error:search": "Failed to parse the search API response. The upstream API may be returning unexpected data.",
    "parse_error:metadata": "Failed to parse the metadata API response.",
    "parse_error:disaggregation": "Failed to parse the disaggregation API response.",
    "parse_error:data": "Failed to parse the data API response.",
    # Validation errors
    "validation_error:search": "Invalid search parameters. Please check your query and filters.",
    "validation_error:metadata": "Invalid metadata request parameters. Check the indicator_id and database_id.",
    "validation_error:data": "Invalid data request parameters. Check the indicator_id, database_id, and filters.",
    "validation_error:api_response": "The API response failed validation. The data format may have changed.",
    # Not found
    "not_found:indicator": "No indicators found matching your query. Try broadening your search terms.",
    "not_found:metadata": "No metadata found for the specified indicator. Verify the indicator_id is correct.",
    # Unexpected
    "unexpected:search": "An unexpected error occurred during search.",
    "unexpected:metadata": "An unexpected error occurred fetching metadata.",
    "unexpected:disaggregation": "An unexpected error occurred fetching disaggregation options.",
    "unexpected:data": "An unexpected error occurred fetching data.",
}


class Data360MCPError(Exception):
    """Base exception for all Data360 MCP errors.

    Attributes:
        error_code: Structured code like "http_error:search".
        detail: Human/LLM-readable error message.
        original_error: The original exception that caused this error, if any.
    """

    def __init__(
        self,
        error_code: str,
        detail: str | None = None,
        original_error: Exception | None = None,
    ):
        self.error_code = error_code
        self.detail = detail or self._get_message(error_code)
        self.original_error = original_error
        super().__init__(self.detail)

    def _get_message(self, error_code: str) -> str:
        return _ERROR_MESSAGES.get(
            error_code, "Something went wrong. Please try again."
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize error for structured responses."""
        result: dict[str, Any] = {
            "error_code": self.error_code,
            "detail": self.detail,
        }
        if self.original_error:
            result["original_error"] = str(self.original_error)
        return result


class APIError(Data360MCPError):
    """HTTP errors from the Data360 API (4xx, 5xx responses)."""

    def __init__(
        self,
        context: str,
        status_code: int,
        response_text: str = "",
        original_error: Exception | None = None,
    ):
        self.status_code = status_code
        self.response_text = response_text
        detail = f"HTTP error {status_code}: {response_text}"
        super().__init__(
            error_code=f"http_error:{context}",
            detail=detail,
            original_error=original_error,
        )


class TimeoutError(Data360MCPError):
    """Timeout errors when calling the Data360 API."""

    def __init__(
        self,
        context: str,
        original_error: Exception | None = None,
    ):
        detail = _ERROR_MESSAGES.get(f"timeout:{context}", f"Request timed out: {context}")
        super().__init__(
            error_code=f"timeout:{context}",
            detail=detail,
            original_error=original_error,
        )


class RequestError(Data360MCPError):
    """Network-level errors (DNS, connection refused, etc.)."""

    def __init__(
        self,
        context: str,
        original_error: Exception | None = None,
    ):
        detail = _ERROR_MESSAGES.get(
            f"request_error:{context}", f"Request error: {context}"
        )
        super().__init__(
            error_code=f"request_error:{context}",
            detail=detail,
            original_error=original_error,
        )


class ParseError(Data360MCPError):
    """JSON parsing or response validation errors."""

    def __init__(
        self,
        context: str,
        detail: str | None = None,
        original_error: Exception | None = None,
    ):
        detail = detail or _ERROR_MESSAGES.get(
            f"parse_error:{context}", f"Failed to parse response: {context}"
        )
        super().__init__(
            error_code=f"parse_error:{context}",
            detail=detail,
            original_error=original_error,
        )


class ValidationError(Data360MCPError):
    """Invalid input parameters or failed response validation."""

    def __init__(
        self,
        context: str,
        detail: str | None = None,
        original_error: Exception | None = None,
    ):
        detail = detail or _ERROR_MESSAGES.get(
            f"validation_error:{context}", f"Validation error: {context}"
        )
        super().__init__(
            error_code=f"validation_error:{context}",
            detail=detail,
            original_error=original_error,
        )


class NotFoundError(Data360MCPError):
    """Resource not found errors."""

    def __init__(
        self,
        context: str,
        detail: str | None = None,
        original_error: Exception | None = None,
    ):
        detail = detail or _ERROR_MESSAGES.get(
            f"not_found:{context}", f"Not found: {context}"
        )
        super().__init__(
            error_code=f"not_found:{context}",
            detail=detail,
            original_error=original_error,
        )


# ---------------------------------------------------------------------------
# Helper to convert httpx exceptions into Data360MCPError
# ---------------------------------------------------------------------------
def from_httpx_error(exc: Exception, context: str) -> Data360MCPError:
    """Convert an httpx exception into the appropriate Data360MCPError subclass.

    Args:
        exc: The original httpx exception.
        context: The operation context (e.g. "search", "metadata", "data").

    Returns:
        The appropriate Data360MCPError subclass instance.
    """
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        return APIError(
            context=context,
            status_code=exc.response.status_code,
            response_text=exc.response.text,
            original_error=exc,
        )
    elif isinstance(exc, httpx.TimeoutException):
        return TimeoutError(context=context, original_error=exc)
    elif isinstance(exc, httpx.RequestError):
        return RequestError(context=context, original_error=exc)
    else:
        return Data360MCPError(
            error_code=f"unexpected:{context}",
            detail=f"Unexpected error: {str(exc)}",
            original_error=exc,
        )
