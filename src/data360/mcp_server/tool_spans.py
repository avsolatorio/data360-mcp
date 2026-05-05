"""OpenTelemetry parent spans for each MCP tool invocation (nests httpx child spans)."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, cast

from opentelemetry import trace

_tracer = trace.get_tracer("data360.mcp.tools")


def instrument_mcp_tool(fn: Callable[..., Any], *, tool_name: str) -> Callable[..., Any]:
    """Wrap a tool function so each call runs under ``mcp.tool.<name>`` span."""
    if inspect.iscoroutinefunction(fn):
        fn_async = cast("Callable[..., Any]", fn)

        @functools.wraps(fn_async)
        async def _async_impl(*args: Any, **kwargs: Any) -> Any:
            with _tracer.start_as_current_span(
                f"mcp.tool.{tool_name}",
                attributes={"mcp.tool.name": tool_name},
            ):
                return await fn_async(*args, **kwargs)

        return _async_impl

    fn_sync = cast("Callable[..., Any]", fn)

    @functools.wraps(fn_sync)
    def _sync_impl(*args: Any, **kwargs: Any) -> Any:
        with _tracer.start_as_current_span(
            f"mcp.tool.{tool_name}",
            attributes={"mcp.tool.name": tool_name},
        ):
            return fn_sync(*args, **kwargs)

    return _sync_impl
