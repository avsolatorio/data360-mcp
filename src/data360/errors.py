"""Centralized error management for the Data360 MCP server.

Provides a unified error hierarchy for consistent, LLM-actionable error messages.
Follows the pattern from https://github.com/avsolatorio/data-ai-chatbot/blob/dev/backend/app/core/errors.py

Error codes follow the format: "<type>:<context>" (e.g. "http_error:search", "timeout:metadata").
"""

import logging
from typing import Any

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message registry - maps error codes to user/LLM-friendly messages
# ---------------------------------------------------------------------------
_ERROR_MESSAGES: dict[str, str] = {
    # HTTP / network errors
    "http_error:search": "The search request failed with an HTTP error. Please try again.",
    "http_error:dataset": "The dataset search request failed with an HTTP error. Please try again.",
    "http_error:metadata": "Failed to fetch metadata due to an HTTP error. Verify the indicator_id and database_id are correct.",
    "http_error:disaggregation": "Failed to fetch disaggregation options due to an HTTP error. Verify the indicator_id and database_id are correct.",
    "http_error:data": "Failed to fetch data due to an HTTP error. Verify the indicator_id, database_id, and filters are correct.",
    # Timeouts
    "timeout:search": "The search request timed out. Please try again.",
    "timeout:dataset": "The dataset search request timed out. Please try again.",
    "timeout:metadata": "The metadata request timed out. Please try again.",
    "timeout:disaggregation": "The disaggregation request timed out. Please try again.",
    "timeout:data": "The data request timed out. Please try again.",
    # Request errors (connection issues, DNS, etc.)
    "request_error:search": "A network error occurred during search. Check connectivity and try again.",
    "request_error:dataset": "A network error occurred searching datasets. Check connectivity and try again.",
    "request_error:metadata": "A network error occurred fetching metadata. Check connectivity and try again.",
    "request_error:disaggregation": "A network error occurred fetching disaggregation options. Check connectivity and try again.",
    "request_error:data": "A network error occurred fetching data. Check connectivity and try again.",
    # Parse errors
    "parse_error:search": "Failed to parse the search API response. The upstream API may be returning unexpected data.",
    "parse_error:dataset": "Failed to parse the dataset search response.",
    "parse_error:metadata": "Failed to parse the metadata API response.",
    "parse_error:disaggregation": "Failed to parse the disaggregation API response.",
    "parse_error:data": "Failed to parse the data API response.",
    # Validation errors
    "validation_error:search": "Invalid search parameters. Please check your query and filters.",
    "validation_error:dataset": "Invalid dataset search parameters.",
    "validation_error:metadata": "Invalid metadata request parameters. Check the indicator_id and database_id.",
    "validation_error:data": "Invalid data request parameters. Check the indicator_id, database_id, and filters.",
    "validation_error:api_response": "The API response failed validation. The data format may have changed.",
    # Not found
    "not_found:indicator": "No indicators found matching your query. Try broadening your search terms.",
    "not_found:metadata": "No metadata found for the specified indicator. Verify the indicator_id is correct.",
    # Unexpected
    "unexpected:search": "An unexpected error occurred during search.",
    "unexpected:dataset": "An unexpected error occurred searching datasets.",
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
        log_level: logging level used when this error is constructed. Subclasses
            may override (e.g. NotFoundError uses WARNING).
    """

    log_level: int = logging.ERROR

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
        exc_info = (
            (type(original_error), original_error, original_error.__traceback__)
            if original_error is not None
            else None
        )
        _logger.log(
            self.log_level,
            "[%s] %s",
            self.error_code,
            self.detail,
            exc_info=exc_info,
        )

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

        # Sanitize response text - avoid leaking WAF HTML into error messages
        sanitized_response = self._sanitize_error_response(response_text, status_code)
        detail = f"HTTP {status_code}: {sanitized_response}"

        super().__init__(
            error_code=f"http_error:{context}",
            detail=detail,
            original_error=original_error,
        )

    @staticmethod
    def _sanitize_error_response(response_text: str, status_code: int) -> str:
        """Sanitize error responses to avoid leaking HTML/WAF content.

        Args:
            response_text: Raw response body from the backend
            status_code: HTTP status code

        Returns:
            Clean, user-friendly error message
        """
        # Empty or whitespace-only response
        if not response_text or not response_text.strip():
            return _get_status_message(status_code)

        # If response looks like HTML (WAF error pages), don't include it
        # Check both raw and after stripping common whitespace/newlines
        text_to_check = response_text.lstrip()
        if text_to_check.startswith(
            ("<html", "<!DOCTYPE", "<HTML", "<!doctype", "<!Doctype")
        ):
            return _get_status_message(status_code)

        # For JSON error responses, try to extract the error message
        if text_to_check.startswith("{"):
            try:
                import json

                error_data = json.loads(response_text)
                # Common error message fields
                for key in ["error", "message", "detail", "error_description", "code"]:
                    if key in error_data:
                        msg = error_data[key]
                        # Skip if the JSON error field itself contains HTML
                        msg_str = str(msg)
                        if msg_str.lstrip().startswith(
                            ("<html", "<!DOCTYPE", "<HTML", "<!doctype")
                        ):
                            return _get_status_message(status_code)
                        # Limit length to avoid verbose error dumps
                        return (
                            msg_str[:200]
                            if len(msg_str) <= 200
                            else msg_str[:200] + "..."
                        )
            except Exception:
                pass  # Fall through to default message

        # Check if response contains HTML tags anywhere (not just at start)
        # Common WAF patterns: <html, <body, <head, <title
        lower_text = response_text.lower()
        if any(
            tag in lower_text
            for tag in ["<html", "<body", "<head", "<title", "<!doctype"]
        ):
            return _get_status_message(status_code)

        # For other responses, truncate and sanitize
        # Remove excessive whitespace and newlines
        cleaned = " ".join(response_text.split())
        if len(cleaned) > 200:
            return cleaned[:200] + "..."

        return cleaned if cleaned else _get_status_message(status_code)


def _get_status_message(status_code: int) -> str:
    """Get a user-friendly message for common HTTP status codes."""
    status_messages = {
        400: "Bad Request - Invalid parameters",
        401: "Unauthorized - Authentication required",
        403: "Forbidden - Access denied",
        404: "Not Found - Resource does not exist",
        408: "Request Timeout - Session expired",
        413: "Payload Too Large - Request exceeds size limit",
        429: "Too Many Requests - Rate limit exceeded",
        500: "Internal Server Error - Backend service error",
        502: "Bad Gateway - Backend service unavailable",
        503: "Service Unavailable - Backend temporarily down",
        504: "Gateway Timeout - Backend did not respond in time",
    }
    return status_messages.get(
        status_code, f"The request failed with status {status_code}"
    )


class Data360TimeoutError(Data360MCPError):
    """Timeout errors when calling the Data360 API."""

    def __init__(
        self,
        context: str,
        original_error: Exception | None = None,
    ):
        detail = _ERROR_MESSAGES.get(
            f"timeout:{context}", f"Request timed out: {context}"
        )
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

    log_level: int = logging.WARNING

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
# Helper to convert exceptions into Data360MCPError
# ---------------------------------------------------------------------------
def classify_error(exc: Exception, context: str) -> Data360MCPError:
    """Convert an exception into the appropriate Data360MCPError subclass.

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
        return Data360TimeoutError(context=context, original_error=exc)
    elif isinstance(exc, httpx.RequestError):
        return RequestError(context=context, original_error=exc)
    else:
        return Data360MCPError(
            error_code=f"unexpected:{context}",
            detail=f"Unexpected error: {str(exc)}",
            original_error=exc,
        )
