"""Standard HTTP routes that invoke registered MCP tools.

These endpoints reuse the existing FastMCP tool registry (no duplicated Data360
logic). Clients POST JSON arguments once and receive JSON — no SSE session.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastmcp.exceptions import NotFoundError, ToolError, ValidationError
from pydantic import ValidationError as PydanticValidationError

from data360.mcp_server import mcp

_logger = logging.getLogger(__name__)

# Standard HTTP route prefix for tool list and tool invocation.
TOOLS_HTTP_PREFIX = "/api/v1/tools"

tools_http_router = APIRouter()


def serialize_tool_result(result: Any) -> Any:
    """Turn a FastMCP ToolResult into a JSON-serializable payload."""
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured

    content = getattr(result, "content", None) or []
    texts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            texts.append(text)

    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except (json.JSONDecodeError, TypeError):
            return {"result": texts[0]}

    if texts:
        parsed: list[Any] = []
        for text in texts:
            try:
                parsed.append(json.loads(text))
            except (json.JSONDecodeError, TypeError):
                parsed.append(text)
        return {"result": parsed}

    return {}


def _parse_tool_arguments(
    body_bytes: bytes,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    if not body_bytes:
        return {}, None
    try:
        parsed_body = json.loads(body_bytes)
    except json.JSONDecodeError:
        return None, JSONResponse(
            status_code=400,
            content={"error": "Request body must be JSON."},
        )
    if not isinstance(parsed_body, dict):
        return None, JSONResponse(
            status_code=400,
            content={"error": "Request body must be a JSON object."},
        )
    return parsed_body, None


def _tool_error_text(result: Any) -> str:
    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            return text
    return "Tool execution failed."


@tools_http_router.get(TOOLS_HTTP_PREFIX)
async def list_tools_http() -> dict[str, list[str]]:
    """Standard HTTP route: list registered MCP tool names."""
    tools = await mcp.list_tools()
    return {"tools": [t.name for t in tools]}


@tools_http_router.post(f"{TOOLS_HTTP_PREFIX}/{{tool_name}}")
async def call_tool_http(tool_name: str, request: Request) -> JSONResponse:
    """Standard HTTP route: invoke one registered MCP tool and return JSON."""
    arguments, error_response = _parse_tool_arguments(await request.body())
    if error_response is not None:
        return error_response

    try:
        result = await mcp.call_tool(tool_name, arguments or {})
    except NotFoundError:
        return JSONResponse(
            status_code=404,
            content={"error": f"Unknown tool: {tool_name}"},
        )
    except Exception as exc:
        if isinstance(exc, (ToolError, ValidationError, PydanticValidationError)):
            return JSONResponse(status_code=400, content={"error": str(exc)})
        _logger.exception("Standard HTTP tool call failed: %s", tool_name)
        return JSONResponse(
            status_code=500,
            content={"error": "Tool execution failed due to an internal error."},
        )

    if getattr(result, "is_error", False):
        return JSONResponse(
            status_code=400,
            content={"error": _tool_error_text(result)},
        )
    return JSONResponse(content=serialize_tool_result(result))
