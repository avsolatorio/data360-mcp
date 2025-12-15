from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPError(Exception):
    code: str
    message: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    retryable: bool | None = None
    cause: BaseException | None = None

    def __post_init__(self):
        if self.message is None:
            self.message = _DEFAULT_MESSAGES.get(self.code, "Something went wrong.")

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class Data360MCPLibraryError(MCPError):
    """Error raised by the Data360 MCP library."""


_DEFAULT_MESSAGES = {
    "tool:bad_request": "The request couldn't be processed. Please check your input and try again.",
    "tool:unauthorized": "You need to sign in to continue.",
    "tool:forbidden": "You don't have access to perform this action.",
    "tool:not_found": "The requested resource was not found.",
    "tool:rate_limited": "Too many requests. Please try again later.",
    "transport:offline": "Network issue. Please check your connection and try again.",
}


def data360_mcp_library_error(
    code: str, message: str | None = None, **data: Any
) -> Data360MCPLibraryError:
    if message is None:
        message = _DEFAULT_MESSAGES.get(code, "Something went wrong.")
    return Data360MCPLibraryError(
        code=code,
        message=message,
        **data,
    )
