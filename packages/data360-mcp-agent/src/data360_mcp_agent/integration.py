"""LangChain + LangGraph client for a running Data360 MCP server (PyPI: ``data360-mcp-agent``).

This package is **separate** from the MCP server implementation. Point it at any
Data360 MCP HTTP endpoint via ``DATA360_MCP_URL``. System instructions load from
MCP resources (``data360://system-prompt``, ``data360://context``; optional
``data360://agent-recipe``, alias ``AGENT_RECIPE_URI`` in this package).

Use :func:`create_data360_mcp_agent` for a compiled graph, or :mod:`data360_mcp_agent.plugin`
for a LangGraph ``add_node``-friendly callable.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from mcp.shared.exceptions import McpError

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)

SERVER_NAME = "data360"
SYSTEM_PROMPT_URI = "data360://system-prompt"
CONTEXT_URI = "data360://context"
AGENT_RECIPE_URI = "data360://agent-recipe"
DEFAULT_RECURSION_LIMIT = 50
_TOOL_DESC_PREVIEW_LEN = 280


@dataclass
class _McpCacheState:
    """TTL-backed cache for MCP tools and composed resource bodies."""

    tools: list | None = None
    resource_body: str | None = None
    fetched_at_monotonic: float = 0.0
    #: Text from MCP ``prompts/get`` ``gate_classifier`` when MCP prompts are enabled.
    mcp_gate_system_prompt: str | None = None
    #: Set by :func:`create_data360_gated_langgraph_node` when using MCP prompts without env.
    fetch_mcp_gate_prompt_requested: bool = False


_cache = _McpCacheState()
_cache_lock = asyncio.Lock()


def _cache_ttl_seconds() -> float:
    raw = os.getenv("DATA360_MCP_CACHE_TTL", "3600")
    try:
        return max(60.0, float(raw))
    except ValueError:
        return 3600.0


def _mcp_url() -> str:
    url = os.getenv("DATA360_MCP_URL", "").strip().rstrip("/")
    if not url:
        msg = (
            "DATA360_MCP_URL is not set. Example: "
            "http://127.0.0.1:8000/mcp (see MCP_PORT when using ./run_server.sh)"
        )
        raise RuntimeError(msg)
    return url


def _flatten_exceptions(exc: BaseException) -> list[BaseException]:
    """Flatten ExceptionGroup / TaskGroup trees for reliable ``except`` handling."""
    if isinstance(exc, BaseExceptionGroup):
        out: list[BaseException] = []
        for item in exc.exceptions:
            out.extend(_flatten_exceptions(item))
        return out
    return [exc]


def _first_mcp_session_terminated(exc: BaseException) -> McpError | None:
    """Detect client-synthesized ``Session terminated`` (HTTP 404 on streamable POST)."""
    for sub in _flatten_exceptions(exc):
        if isinstance(sub, McpError) and sub.error.message == "Session terminated":
            return sub
    return None


def _raise_mcp_connect_help(url: str, cause: BaseException) -> None:
    msg = (
        "Could not complete MCP `initialize` against the Data360 server. "
        "The MCP Python streamable-HTTP client maps **HTTP 404** on the POST "
        "to `McpError: Session terminated` (see `mcp/client/streamable_http.py`). "
        "Typical causes: wrong `DATA360_MCP_URL` (this repo serves MCP at "
        "**/mcp**), a reverse proxy stripping the path, nothing listening on "
        "that host/port, or (on the server) an invalid/expired `mcp-session-id` "
        "header vs the server's session. "
        f"Current DATA360_MCP_URL={url!r}. "
        "If you start the ASGI app with `./run_server.sh`, default port is "
        "MCP_PORT (often 8000); `poe serve` / `python -m data360.mcp_server` "
        "may use another port — the URL must match the process you actually run."
    )
    raise RuntimeError(msg) from cause


def _mcp_transport() -> str:
    transport = os.getenv("DATA360_MCP_TRANSPORT", "streamable_http").strip()
    return transport or "streamable_http"


def _recursion_limit() -> int:
    raw = os.getenv("DATA360_AGENT_RECURSION_LIMIT")
    if raw is None or raw == "":
        return DEFAULT_RECURSION_LIMIT
    try:
        return max(4, int(raw))
    except ValueError:
        return DEFAULT_RECURSION_LIMIT


def get_agent_recursion_limit() -> int:
    """Environment-driven recursion limit for agent graphs (tool-call depth)."""
    return _recursion_limit()


def _extra_resource_uris() -> list[str]:
    raw = os.getenv("DATA360_AGENT_EXTRA_RESOURCES", "")
    return [u.strip() for u in raw.split(",") if u.strip()]


def _use_mcp_gate_reform_prompts() -> bool:
    """When true, gate/reform use MCP ``gate_classifier`` / ``thematic_to_data`` (see README)."""
    raw = os.getenv("DATA360_AGENT_USE_MCP_PROMPTS", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _message_content_as_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text", "")))
            else:
                chunks.append(str(block))
        return "".join(chunks).strip()
    return str(content or "").strip()


def _join_prompt_messages(messages: Sequence[Any]) -> str:
    parts = [_message_content_as_text(m) for m in messages]
    return "\n\n".join(p for p in parts if p)


async def _client_get_prompt_messages(
    client: Any,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> list[Any]:
    """Compat wrapper for ``MultiServerMCPClient.get_prompt`` signature drift.

    Some adapter versions expect:
    - ``get_prompt(server_name, name, arguments=...)``
    Others expect:
    - ``get_prompt(name, arguments=...)``
    """
    args = arguments or {}
    call_patterns = (
        lambda: client.get_prompt(server_name=SERVER_NAME, prompt_name=name, arguments=args),
        lambda: client.get_prompt(server_name=SERVER_NAME, name=name, arguments=args),
        lambda: client.get_prompt(SERVER_NAME, name, arguments=args),
        lambda: client.get_prompt(SERVER_NAME, name, args),
        lambda: client.get_prompt(name, arguments=args),
        lambda: client.get_prompt(name, args),
    )
    last_error: TypeError | None = None
    for call in call_patterns:
        try:
            return await call()
        except TypeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    msg = "Could not fetch MCP prompt messages"
    raise RuntimeError(msg)


async def _cache_gate_classifier_prompt(client: Any) -> None:
    fetch_gate = (
        _use_mcp_gate_reform_prompts() or _cache.fetch_mcp_gate_prompt_requested
    )
    if not fetch_gate:
        return
    try:
        gate_msgs = await _client_get_prompt_messages(client, "gate_classifier", {})
        joined = _join_prompt_messages(gate_msgs)
        if joined:
            _cache.mcp_gate_system_prompt = joined
            logger.info(
                "[%s] Cached MCP gate_classifier prompt (%d chars)",
                SERVER_NAME,
                len(joined),
            )
        else:
            logger.warning(
                "[%s] gate_classifier prompt returned empty; using embedded gate text",
                SERVER_NAME,
            )
    except BaseException as exc:
        logger.warning(
            "[%s] Could not fetch gate_classifier MCP prompt (%s); using embedded gate text",
            SERVER_NAME,
            exc,
        )


def _include_tool_catalog() -> bool:
    flag = os.getenv("DATA360_AGENT_INCLUDE_TOOL_CATALOG", "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def _default_llm_streaming(explicit: bool | None) -> bool:
    """Resolve streaming flag: explicit arg wins, then ``DATA360_AGENT_LLM_STREAMING``."""
    if explicit is not None:
        return explicit
    raw = os.getenv("DATA360_AGENT_LLM_STREAMING", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _streamable_connection_config() -> dict[str, Any]:
    """Build MultiServerMCPClient connection dict for the Data360 server."""
    cfg: dict[str, Any] = {
        "url": _mcp_url(),
        "transport": _mcp_transport(),
    }
    # LangChain passes this to MCP streamable HTTP client; optional tuning for proxies/stateless.
    if os.getenv(
        "DATA360_MCP_STREAMABLE_TERMINATE_ON_CLOSE", "true"
    ).strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        cfg["terminate_on_close"] = False
    return cfg


def _make_client() -> MultiServerMCPClient:
    connections: dict[str, Any] = {SERVER_NAME: _streamable_connection_config()}
    return MultiServerMCPClient(cast(Any, connections))


def _blob_to_text(blob: Any) -> str:
    return blob.as_string()


def _compact_tool_catalog(tools: list) -> str:
    lines: list[str] = []
    for t in tools:
        name = getattr(t, "name", "")
        desc = getattr(t, "description", None) or ""
        lim = _TOOL_DESC_PREVIEW_LEN
        short = desc[:lim] + ("…" if len(desc) > lim else "")
        lines.append(f"- `{name}`: {short}")
    return "## Registered tools (summary)\n" + "\n".join(lines)


async def _refresh_cache_locked() -> None:
    """Fetch tools and MCP resources into module-level caches."""
    client = _make_client()
    url = _mcp_url()
    try:
        tools = await client.get_tools(server_name=SERVER_NAME)

        uris = [SYSTEM_PROMPT_URI, CONTEXT_URI]
        for uri in _extra_resource_uris():
            if uri not in uris:
                uris.append(uri)

        blobs = await client.get_resources(server_name=SERVER_NAME, uris=uris)
    except BaseException as exc:
        mcp_exc = _first_mcp_session_terminated(exc)
        if mcp_exc is not None:
            _raise_mcp_connect_help(url, mcp_exc)
        raise
    by_uri: dict[str, str] = {}
    for blob in blobs:
        md = getattr(blob, "metadata", None) or {}
        uri = md.get("uri", "")
        if uri:
            by_uri[uri] = _blob_to_text(blob)

    system = by_uri.get(SYSTEM_PROMPT_URI, "").strip()
    context = by_uri.get(CONTEXT_URI, "").strip()
    if not system:
        logger.warning(
            "[%s] %s missing or empty; agent may lack server workflow guidance.",
            SERVER_NAME,
            SYSTEM_PROMPT_URI,
        )

    parts: list[str] = []
    if system:
        parts.append(system)
    if context:
        parts.append("### Runtime Context\n" + context)

    extra_blocks: list[str] = []
    for uri in _extra_resource_uris():
        if uri in by_uri and uri not in (SYSTEM_PROMPT_URI, CONTEXT_URI):
            extra_blocks.append(f"#### {uri}\n{by_uri[uri]}")
    if extra_blocks:
        parts.append("## Additional MCP resources\n\n" + "\n\n".join(extra_blocks))

    body = "\n\n".join(parts)
    _cache.tools = tools
    _cache.resource_body = body
    _cache.mcp_gate_system_prompt = None
    await _cache_gate_classifier_prompt(client)

    _cache.fetched_at_monotonic = time.monotonic()
    logger.info(
        "[%s] Refreshed cache — %d tool(s), resource body length=%d chars",
        SERVER_NAME,
        len(tools),
        len(body),
    )


async def _ensure_cache() -> tuple[list, str]:
    """Return (tools, resource_body_without_tool_catalog)."""
    now = time.monotonic()
    if (
        _cache.tools is not None
        and _cache.resource_body is not None
        and (now - _cache.fetched_at_monotonic) < _cache_ttl_seconds()
    ):
        return _cache.tools, _cache.resource_body

    async with _cache_lock:
        now = time.monotonic()
        if (
            _cache.tools is not None
            and _cache.resource_body is not None
            and (now - _cache.fetched_at_monotonic) < _cache_ttl_seconds()
        ):
            return _cache.tools, _cache.resource_body
        await _refresh_cache_locked()
        if _cache.tools is None or _cache.resource_body is None:
            msg = "MCP cache refresh failed"
            raise RuntimeError(msg)
        return _cache.tools, _cache.resource_body


def _compose_system_prompt(tools: list, resource_body: str) -> str:
    if _include_tool_catalog():
        return resource_body + "\n\n" + _compact_tool_catalog(tools)
    return resource_body


def _resolve_llm(
    model_name: str | None,
    llm: BaseChatModel | None,
    *,
    llm_streaming: bool | None = None,
) -> BaseChatModel:
    if llm is not None:
        return llm
    try:
        mod = importlib.import_module("services.ai_service")
        get_llm_for_model = getattr(mod, "get_llm_for_model")
        resolved, _ = get_llm_for_model(model_name)
        return resolved
    except ImportError:
        logger.debug("services.ai_service not available; using ChatOpenAI fallback.")

    if not os.getenv("OPENAI_API_KEY"):
        msg = (
            "Pass llm=..., set OPENAI_API_KEY for the default ChatOpenAI, "
            "or provide services.ai_service.get_llm_for_model integration."
        )
        raise RuntimeError(msg)
    model = model_name or os.getenv("DATA360_AGENT_MODEL", "gpt-4.1-mini")
    stream = _default_llm_streaming(llm_streaming)
    return ChatOpenAI(model=model, temperature=0, streaming=stream)


def _extract_tool_result(msg: ToolMessage) -> Any:
    """Parse the content of a ToolMessage into structured JSON data.

    Handles three content shapes returned by langchain-mcp-adapters:
    1. A plain JSON string  →  parse it.
    2. A list of MCP content blocks  →  parse each block's ``text`` field.
    3. Already-parsed data  →  return as-is.
    """
    content = msg.content

    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return content

    if isinstance(content, list):
        parsed_items = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_val = item.get("text", "")
                try:
                    parsed_items.append(json.loads(text_val))
                except (json.JSONDecodeError, ValueError):
                    parsed_items.append(text_val)
            else:
                parsed_items.append(item)
        return parsed_items[0] if len(parsed_items) == 1 else parsed_items

    return content


def _final_text_from_ai_message(msg: AIMessage) -> str | None:
    """Normalize AIMessage.content to a string for API responses."""
    content = msg.content
    if not content:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text", "")))
            else:
                chunks.append(str(block))
        text = "".join(chunks).strip()
        return text or None
    return str(content)


def _collect_agent_results(messages: list) -> dict[str, Any]:
    """Walk the agent message list and separate tool interactions from the final answer."""
    tool_calls: list[dict[str, Any]] = []
    final_answer: str | None = None

    pending: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tid = tc.get("id")
                if tid is None:
                    continue
                pending[tid] = {
                    "tool_name": tc["name"],
                    "tool_args": tc.get("args", {}),
                }

    for msg in messages:
        if isinstance(msg, ToolMessage):
            call_info = pending.pop(msg.tool_call_id, {})
            tool_calls.append(
                {
                    "tool_name": call_info.get("tool_name", msg.name),
                    "tool_args": call_info.get("tool_args", {}),
                    "tool_result": _extract_tool_result(msg),
                }
            )

    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            final_answer = _final_text_from_ai_message(msg)
            break

    return {
        "tool_calls": tool_calls,
        "answer": final_answer,
    }


async def list_mcp_tools() -> list[dict[str, Any]]:
    """Connect to the MCP server and return available tools with metadata."""
    tools, _ = await _ensure_cache()
    return [
        {
            "name": t.name,
            "description": t.description or "",
        }
        for t in tools
    ]


async def fetch_mcp_prompt_messages(
    name: str,
    arguments: dict[str, Any] | None = None,
) -> list[Any]:
    """Return LangChain messages from a Data360 MCP prompt (e.g. ``country_data``)."""
    client = _make_client()
    return await _client_get_prompt_messages(client, name, arguments)


async def create_data360_mcp_agent(
    llm: BaseChatModel | None = None,
    model_name: str | None = None,
    *,
    llm_streaming: bool | None = None,
) -> CompiledStateGraph:
    """Compile the Data360 MCP-backed agent once.

    Reuse with ``await agent.ainvoke({"messages": [...]}, config=...)``. Plug the same
    graph into LangGraph as a subgraph node, or call it from a supervisor/router.

    For **token-level** events from :func:`langgraph.graph.state.CompiledStateGraph.astream_events`,
    pass ``llm_streaming=True`` (or set env ``DATA360_AGENT_LLM_STREAMING``) when using the
    default ``ChatOpenAI``. Inject your own ``llm`` with ``streaming=True`` for other providers.

    Raises:
        RuntimeError: If MCP URL is missing, tools are unavailable, or no LLM can be resolved.
    """
    tools, resource_body = await _ensure_cache()
    if not tools:
        msg = "No tools available from MCP server."
        raise RuntimeError(msg)
    llm_resolved = _resolve_llm(model_name, llm, llm_streaming=llm_streaming)
    system_prompt = _compose_system_prompt(tools, resource_body)
    return create_agent(llm_resolved, tools, system_prompt=system_prompt)


async def run_agent_query(
    query: str,
    model_name: str | None = None,
    *,
    llm: BaseChatModel | None = None,
    mcp_prompt_name: str | None = None,
    mcp_prompt_arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a ReAct agent that can call multiple Data360 MCP tools to answer a query.

    System instructions are built from MCP resources plus an optional compact tool
    summary. When ``mcp_prompt_name`` is set, server prompt messages (e.g.
    ``country_data``) are inserted before the user query.

    Returns a dict with:
        tool_calls: list of {tool_name, tool_args, tool_result} for every tool invocation
        answer: final LLM summary (str or None)
        error: error message (str or None)
    """
    try:
        agent = await create_data360_mcp_agent(llm=llm, model_name=model_name)
    except RuntimeError as exc:
        return {"tool_calls": [], "answer": None, "error": str(exc)}

    prompt_messages: list = []
    if mcp_prompt_name:
        prompt_messages = await fetch_mcp_prompt_messages(
            mcp_prompt_name,
            mcp_prompt_arguments,
        )

    invoke_messages = [*prompt_messages, HumanMessage(content=query)]

    logger.info("[MCP] Running agent query (model=%s): %s", model_name, query[:120])

    result = await agent.ainvoke(
        {"messages": invoke_messages},
        config={"recursion_limit": _recursion_limit()},
    )

    collected = _collect_agent_results(result["messages"])

    logger.info(
        "[MCP] Agent completed — %d tool call(s), answer length=%d",
        len(collected["tool_calls"]),
        len(collected["answer"] or ""),
    )

    return {
        "tool_calls": collected["tool_calls"],
        "answer": collected["answer"],
        "error": None,
    }


def use_mcp_prompts_from_env() -> bool:
    """True when ``DATA360_AGENT_USE_MCP_PROMPTS`` requests MCP gate/reform prompt text."""
    return _use_mcp_gate_reform_prompts()


async def prepare_cache_for_mcp_gate_prompts(enabled: bool) -> None:
    """Before :func:`create_data360_mcp_agent` in a gated factory: request gate prefetch and optionally expire cache TTL."""
    async with _cache_lock:
        _cache.fetch_mcp_gate_prompt_requested = enabled
        if enabled:
            _cache.fetched_at_monotonic = 0.0


async def release_mcp_gate_prompt_preparation() -> None:
    """Clear the gated-node gate-prefetch flag after the agent graph is compiled."""
    async with _cache_lock:
        _cache.fetch_mcp_gate_prompt_requested = False


def get_cached_mcp_gate_system_prompt() -> str | None:
    """Last fetched ``gate_classifier`` body from MCP (after cache refresh)."""
    return _cache.mcp_gate_system_prompt


__all__ = [
    "AGENT_RECIPE_URI",
    "CONTEXT_URI",
    "SERVER_NAME",
    "SYSTEM_PROMPT_URI",
    "create_data360_mcp_agent",
    "fetch_mcp_prompt_messages",
    "get_agent_recursion_limit",
    "list_mcp_tools",
    "run_agent_query",
    "use_mcp_prompts_from_env",
    "prepare_cache_for_mcp_gate_prompts",
    "release_mcp_gate_prompt_preparation",
    "get_cached_mcp_gate_system_prompt",
]
