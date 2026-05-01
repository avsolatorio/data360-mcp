"""Local web UI for the Data360 MCP agent (LangGraph stream events over SSE).

Run from the data360-mcp repository root (see demo_web README)::

    uv run uvicorn demo_web.server:app --app-dir examples/agents/langchain-graph --port 8844

Open http://127.0.0.1:8844/ — environment variables may come from a ``.env`` file
at the repository root or in the current working directory (see ``_bootstrap_env``).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from urllib.parse import ParseResult, urlparse

import httpx
from data360_mcp_agent import (
    aiter_data360_mcp_agent_events,
    create_data360_mcp_agent,
    run_k360_query,
)
from data360_mcp_agent.integration import get_agent_recursion_limit
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _monorepo_root() -> Path | None:
    """Locate ``data360-mcp`` repo root (directory that contains ``packages/data360-mcp-agent``)."""
    for d in Path(__file__).resolve().parents:
        if (d / "packages" / "data360-mcp-agent").is_dir():
            return d
    return None


def _bootstrap_env() -> None:
    """Load ``.env`` from repo root, then cwd (cwd wins on duplicate keys)."""
    root = _monorepo_root()
    if root is not None:
        load_dotenv(root / ".env")
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file() and (root is None or cwd_env.resolve() != (root / ".env").resolve()):
        load_dotenv(cwd_env, override=True)


_bootstrap_env()

_agent_lock = asyncio.Lock()


class _AgentCache:
    """Module-level cache (avoids ``global`` for ruff PLW0603)."""

    graph: CompiledStateGraph | None = None


_cache = _AgentCache()


async def _get_agent():
    """Lazy-compile agent so import-time errors only happen on first use."""
    async with _agent_lock:
        if _cache.graph is None:
            _cache.graph = await create_data360_mcp_agent(llm_streaming=True)
        return _cache.graph


class StreamBody(BaseModel):
    query: str = Field(..., min_length=1)


class K360Body(BaseModel):
    query: str = Field(..., min_length=1)
    context: list[str] = Field(default_factory=list)
    show_tool_details: bool = False
    narrative_streaming: bool = True


def _json_line(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str)
    except TypeError:
        return json.dumps({"repr": repr(obj)})


def _tool_message_to_dict(msg: ToolMessage) -> Any:
    """Parse MCP / tool JSON from a ``ToolMessage`` body."""
    raw = msg.content
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"content": raw, "tool_name": msg.name}
    if isinstance(raw, list):
        for block in raw:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return {"content": raw}
    return {"content": raw, "tool_name": msg.name}


def _stringify_message_content(content: Any) -> str:
    """Flatten LangChain message content blocks to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts).strip()
    return str(content)


def _chat_model_output_for_wire(output: Any) -> dict[str, Any]:
    """Serialize ``AIMessage`` from ``on_chat_model_end`` for the browser."""
    if isinstance(output, AIMessage):
        tc = getattr(output, "tool_calls", None) or []
        return {
            "content": _stringify_message_content(output.content),
            "has_tool_calls": bool(tc),
            "tool_calls": tc,
        }

    model_dump = getattr(output, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
            if isinstance(dumped, dict):
                tc = dumped.get("tool_calls") or []
                return {
                    "content": _stringify_message_content(dumped.get("content")),
                    "has_tool_calls": bool(tc),
                    "tool_calls": tc,
                }
        except Exception:
            pass

    return {
        "content": "",
        "has_tool_calls": False,
        "tool_calls": [],
    }


def _normalize_tool_output_for_wire(output: Any) -> Any:
    """Convert LangChain ``ToolMessage`` (and similar) into JSON-safe structures.

    Raw ``astream_events`` uses ``json.dumps(..., default=str)`` which turns
    ``ToolMessage`` into an unusable repr string — the browser never sees ``url``.
    """
    if output is None:
        return None
    if isinstance(output, ToolMessage):
        return _tool_message_to_dict(output)

    model_dump = getattr(output, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump()
        except Exception:
            pass

    if isinstance(output, dict):
        return output

    return output


def _normalize_stream_event_for_wire(ev: Any) -> Any:
    """Copy v2 stream dicts; normalize tool + chat-model payloads for JSON over SSE."""
    if not isinstance(ev, dict):
        return ev
    ev_out = dict(ev)
    evt = ev_out.get("event")
    if evt == "on_tool_end":
        data = dict(ev_out.get("data") or {})
        if "output" in data:
            data["output"] = _normalize_tool_output_for_wire(data["output"])
        ev_out["data"] = data
        return ev_out
    if evt == "on_chat_model_end":
        data = dict(ev_out.get("data") or {})
        if "output" in data:
            data["output"] = _chat_model_output_for_wire(data["output"])
        ev_out["data"] = data
        return ev_out
    return ev_out


async def _sse_events(query: str) -> AsyncIterator[str]:
    agent = await _get_agent()
    messages = {"messages": [HumanMessage(content=query)]}
    cfg = cast(
        RunnableConfig,
        {"recursion_limit": get_agent_recursion_limit()},
    )
    try:
        async for ev in aiter_data360_mcp_agent_events(
            agent,
            messages,
            config=cfg,
            version="v2",
        ):
            safe = _normalize_stream_event_for_wire(ev)
            yield f"data: {_json_line(safe)}\n\n"
    except Exception as exc:
        logger.exception("Stream failed")
        err_payload = {"error": True, "message": str(exc)}
        yield f"data: {_json_line(err_payload)}\n\n"
    yield "data: [DONE]\n\n"


app = FastAPI(title="Data360 MCP agent demo UI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _default_scheme_port(parsed: ParseResult) -> tuple[str, int]:
    scheme = parsed.scheme or "http"
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, port


def _host_is_safe_for_demo(hostname: str) -> bool:
    """Allow loopback / private LAN hosts for the viz-spec proxy (demo SSRF guard)."""
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(hostname)
        return bool(ip.is_loopback or ip.is_private or ip.is_link_local)
    except ValueError:
        return False


def _viz_spec_fetch_allowed(url: str) -> bool:
    """Permit only static Vega JSON paths on the same host/port as ``DATA360_MCP_URL``."""
    mcp_raw = os.getenv("DATA360_MCP_URL", "").strip()
    if not mcp_raw:
        return False
    target = urlparse(url)
    base = urlparse(mcp_raw)
    th = target.hostname or ""
    bh = base.hostname or ""
    path_ok = (
        target.scheme in {"http", "https"}
        and "/static/viz_specs/" in target.path
        and target.path.endswith("_vega.json")
        and bool(th and _host_is_safe_for_demo(th))
    )
    if not path_ok:
        return False
    _, t_port = _default_scheme_port(target)
    _, b_port = _default_scheme_port(base)
    if t_port != b_port:
        return False
    if th == bh:
        return True
    loop = frozenset({"localhost", "127.0.0.1"})
    return th in loop and bh in loop


@app.get("/api/fetch-viz-spec")
async def fetch_viz_spec(url: str = Query(..., min_length=12)) -> JSONResponse:
    """Server-side fetch of ``…/static/viz_specs/*.json`` so the browser avoids CORS."""
    if not _viz_spec_fetch_allowed(url):
        raise HTTPException(
            status_code=400,
            detail=(
                "URL must point to …/static/viz_specs/*_vega.json on the same host/port "
                "as DATA360_MCP_URL (localhost/127.0.0.1/private IP only)."
            ),
        )
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    try:
        spec = resp.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from MCP: {exc}") from exc
    return JSONResponse(spec)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/stream")
async def stream(body: StreamBody) -> StreamingResponse:
    if not os.getenv("DATA360_MCP_URL", "").strip():
        raise HTTPException(
            status_code=503,
            detail="DATA360_MCP_URL is not set",
        )
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not set",
        )
    return StreamingResponse(
        _sse_events(body.query.strip()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/k360-query")
async def k360_query(body: K360Body) -> JSONResponse:
    """Run staged K360 flow and return structured envelope for UI demos."""
    if not os.getenv("DATA360_MCP_URL", "").strip():
        raise HTTPException(
            status_code=503,
            detail="DATA360_MCP_URL is not set",
        )
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not set",
        )
    out = await run_k360_query(
        body.query.strip(),
        context=body.context,
        use_mcp_prompts=True,
        emit_tool_details=body.show_tool_details,
        narrative_streaming=body.narrative_streaming,
    )
    if out.get("error"):
        logger.error(
            "K360 query failed: query=%r error=%s error_type=%s",
            body.query.strip(),
            out.get("error"),
            out.get("error_type"),
        )
        if out.get("error_details"):
            logger.error("K360 error details:\n%s", out.get("error_details"))
    return JSONResponse(out)


@app.post("/api/k360-query/stream")
async def k360_query_stream(body: K360Body) -> StreamingResponse:
    """Stream staged K360 progress events and final payload over SSE."""
    if not os.getenv("DATA360_MCP_URL", "").strip():
        raise HTTPException(
            status_code=503,
            detail="DATA360_MCP_URL is not set",
        )
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not set",
        )

    async def event_stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def stage_hook(payload: dict[str, Any]) -> None:
            if payload.get("stage") == "narrative_chunk":
                await queue.put(
                    {
                        "type": "narrative_chunk",
                        "chunk": ((payload.get("details") or {}).get("chunk", "")),
                    }
                )
                return
            await queue.put({"type": "stage", **payload})

        async def run_query() -> dict[str, Any]:
            return await run_k360_query(
                body.query.strip(),
                context=body.context,
                use_mcp_prompts=True,
                emit_tool_details=body.show_tool_details,
                narrative_streaming=body.narrative_streaming,
                stage_hook=stage_hook,
            )

        task = asyncio.create_task(run_query())
        try:
            while not task.done():
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=0.2)
                    yield f"data: {json.dumps(evt, default=str)}\n\n"
                except TimeoutError:
                    continue
            while not queue.empty():
                evt = queue.get_nowait()
                yield f"data: {json.dumps(evt, default=str)}\n\n"
            out = await task
            if out.get("error"):
                logger.error(
                    "K360 query failed: query=%r error=%s error_type=%s",
                    body.query.strip(),
                    out.get("error"),
                    out.get("error_type"),
                )
                if out.get("error_details"):
                    logger.error("K360 error details:\n%s", out.get("error_details"))
            yield f"data: {json.dumps({'type': 'final', 'payload': out}, default=str)}\n\n"
        except Exception as exc:
            logger.exception("K360 stream failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, default=str)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")
