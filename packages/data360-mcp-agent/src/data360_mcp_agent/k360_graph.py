"""Staged K360 pipeline for Data360 MCP agent hosts.

Flow:
    Gate -> Rewriter -> Compile (tool loop) -> Narrative
"""

from __future__ import annotations

import json
import logging
import os
import re
import traceback
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from data360_mcp_agent.gate import (
    Data360ReformulationResult,
    build_augmented_messages,
    classify_data360_relevance,
    reformulate_for_data360,
)
from data360_mcp_agent.integration import (
    _collect_agent_results,
    _resolve_llm,
    create_data360_mcp_agent,
    fetch_mcp_prompt_messages,
    get_agent_recursion_limit,
    get_cached_mcp_gate_system_prompt,
    prepare_cache_for_mcp_gate_prompts,
    release_mcp_gate_prompt_preparation,
)

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


class K360State(TypedDict, total=False):
    query: str
    context: list[str]
    gate: dict[str, Any]
    rewrite: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    compile_answer: str | None
    content_packet: dict[str, Any]
    narrative: str
    error: str | None


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _json_safe_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=True)


def _accumulate_geo_codes(geographies: set[str], value: Any) -> None:
    """Add geography codes from a tool arg (comma/semicolon-separated string or list of strings)."""
    if isinstance(value, str):
        for part in re.split(r"[,;]", value):
            c = part.strip()
            if c:
                geographies.add(c)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                for part in re.split(r"[,;]", item):
                    c = part.strip()
                    if c:
                        geographies.add(c)


def _content_packet_from_tool_calls(
    query: str,
    rewrite: Data360ReformulationResult | None,
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    indicators: list[dict[str, str]] = []
    indicator_seen: set[tuple[str, str]] = set()
    geographies: set[str] = set()
    sources: set[str] = set()
    viz_assets: list[dict[str, str]] = []
    observations: list[str] = []
    years: list[int] = []
    tool_trace: list[dict[str, Any]] = []

    for call in tool_calls:
        tool_name = str(call.get("tool_name", ""))
        tool_args = call.get("tool_args", {}) or {}
        tool_result = call.get("tool_result")
        tool_trace.append(
            {
                "tool_name": tool_name,
                "tool_input": tool_args,
                "tool_output": tool_result,
            }
        )

        db_id = str(tool_args.get("database_id", "")).strip()
        ind_id = str(tool_args.get("indicator_id", "")).strip()
        if db_id and ind_id and (db_id, ind_id) not in indicator_seen:
            indicator_seen.add((db_id, ind_id))
            indicators.append({"database_id": db_id, "indicator_id": ind_id})
        if db_id:
            sources.add(db_id)

        filters = tool_args.get("disaggregation_filters")
        if isinstance(filters, dict):
            _accumulate_geo_codes(geographies, filters.get("REF_AREA"))
        _accumulate_geo_codes(geographies, tool_args.get("country_code"))

        start_year = tool_args.get("start_year")
        end_year = tool_args.get("end_year")
        for y in (start_year, end_year):
            if isinstance(y, int):
                years.append(y)

        if isinstance(tool_result, dict):
            maybe_url = tool_result.get("url")
            if isinstance(maybe_url, str) and maybe_url:
                viz_assets.append(
                    {
                        "url": maybe_url,
                        "chart_type": str(tool_args.get("chart_type", "")).strip()
                        or "auto",
                    }
                )
            if tool_name == "data360_get_data":
                data = tool_result.get("data")
                if isinstance(data, list):
                    observations.append(f"Fetched {len(data)} row(s) from get_data.")

    time_range: dict[str, int] = {}
    if years:
        time_range = {"start_year": min(years), "end_year": max(years)}

    return {
        "query_focus": (rewrite.data_question if rewrite else query).strip(),
        "selected_indicators": indicators,
        "geographies": sorted(geographies),
        "time_range": time_range,
        "key_observations": observations[:6],
        "sources": sorted(sources),
        "viz_assets": viz_assets,
        "data_gaps": [],
        "tool_trace": tool_trace,
    }


def _should_include_claim_tags() -> bool:
    return _env_truthy("DATA360_K360_CLAIM_TAGS", default=False)


def _normalize_narrative_sections(text: str) -> str:
    """Normalize common LLM section variants to vercel-style labels."""
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        replaced = line
        for label in ("Data", "Analysis", "Note", "Sources"):
            marker = f"- **{label}:**"
            if stripped.startswith(marker):
                idx = line.find(marker)
                if idx >= 0:
                    replaced = line[:idx] + f"**{label}:**" + line[idx + len(marker) :]
                break
        out.append(replaced)
    return "\n".join(out)


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _is_relevant(state: K360State) -> str:
    gate = state.get("gate", {})
    if gate.get("relevant") is True:
        return "relevant"
    return "not_relevant"


def _is_explicit_data_question(text: str) -> bool:
    t = text.lower().strip()
    if not t:
        return False
    has_country_like = bool(
        re.search(
            r"\b(vietnam|kenya|nigeria|ghana|bangladesh|ethiopia|rwanda|south africa|peru|morocco|turkey|egypt|indonesia|colombia|ukraine)\b",
            t,
        )
    )
    has_data_metric = bool(
        re.search(
            r"\b(gdp|growth|inflation|population|poverty|life expectancy|unemployment|co2|internet|electricity|maternal|exports|school|corruption|indicator|rate)\b",
            t,
        )
    )
    has_time_or_latest = bool(
        re.search(r"\b(latest|since|between|from|in\s+\d{4}|last\s+\d+)\b", t)
    )
    return has_data_metric and (has_country_like or has_time_or_latest)


def _is_context_dependent_query(text: str) -> bool:
    t = text.lower().strip()
    if not t:
        return False
    if len(t.split()) <= 4:
        return True
    return bool(
        re.search(
            r"\b(this|that|those|it|them|same|again|there|here|above|previous|last one)\b",
            t,
        )
    )


def _error_payload(exc: Exception) -> dict[str, Any]:
    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return {
        "error": f"{type(exc).__name__}: {exc}",
        "error_type": type(exc).__name__,
        "error_details": "".join(tb_lines[-8:]).strip(),
    }


def _extract_messages_from_chain_output(output: Any) -> list[Any] | None:
    if isinstance(output, dict):
        messages = output.get("messages")
        if isinstance(messages, list):
            return messages
    model_dump = getattr(output, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
            if isinstance(dumped, dict):
                messages = dumped.get("messages")
                if isinstance(messages, list):
                    return messages
        except Exception:
            return None
    return None


async def _emit_stage(
    stage_hook: Callable[[dict[str, Any]], Awaitable[None] | None] | None,
    stage: str,
    status: str,
    details: dict[str, Any] | None = None,
) -> None:
    if stage_hook is None:
        return
    payload: dict[str, Any] = {
        "stage": stage,
        "status": status,
    }
    if details:
        payload["details"] = details
    result = stage_hook(payload)
    if hasattr(result, "__await__"):
        await result


async def create_k360_graph(  # noqa: PLR0913
    *,
    llm: BaseChatModel | None = None,
    model_name: str | None = None,
    llm_streaming: bool | None = None,
    gate_llm: BaseChatModel | None = None,
    reform_llm: BaseChatModel | None = None,
    narrative_llm: BaseChatModel | None = None,
    use_mcp_prompts: bool = True,
    emit_tool_details: bool = False,
    narrative_streaming: bool = True,
    stage_hook: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
):
    """Create a compiled staged graph: gate -> rewrite -> compile -> narrative."""
    base_llm = _resolve_llm(model_name, llm, llm_streaming=llm_streaming)
    gate_model = gate_llm or base_llm
    reform_model = reform_llm or base_llm
    writer_model = narrative_llm or base_llm

    await prepare_cache_for_mcp_gate_prompts(use_mcp_prompts)
    try:
        compile_agent = await create_data360_mcp_agent(
            llm=base_llm,
            model_name=None,
            llm_streaming=llm_streaming,
        )
    finally:
        await release_mcp_gate_prompt_preparation()

    async def gate_node(state: K360State) -> K360State:
        try:
            await _emit_stage(stage_hook, "gate", "started")
            query = state.get("query", "").strip()
            if not query:
                return {
                    "gate": {
                        "relevant": False,
                        "reason": "Empty query",
                        "refusal_text": None,
                    },
                    "error": "Empty query",
                }
            gate_prompt = (
                get_cached_mcp_gate_system_prompt() if use_mcp_prompts else None
            )
            gate_result = await classify_data360_relevance(
                gate_model,
                query,
                gate_system_prompt=gate_prompt,
            )
            await _emit_stage(
                stage_hook,
                "gate",
                "completed",
                {"relevant": gate_result.relevant},
            )
            return {"gate": gate_result.model_dump()}
        except Exception as exc:
            raise RuntimeError(f"[gate] {type(exc).__name__}: {exc}") from exc

    async def rewrite_node(state: K360State) -> K360State:
        try:
            await _emit_stage(stage_hook, "rewrite", "started")
            query = state.get("query", "").strip()
            if not query:
                return {}
            if _is_explicit_data_question(query):
                await _emit_stage(
                    stage_hook,
                    "rewrite",
                    "completed",
                    {"rewritten": False, "reason": "explicit_data_question"},
                )
                return {
                    "rewrite": Data360ReformulationResult(
                        data_question=query,
                        search_hints=[],
                        rewritten=False,
                    ).model_dump()
                }

            context = state.get("context") or []
            user_message = query
            if context and _is_context_dependent_query(query):
                context_text = "\n".join(
                    f"- {item}" for item in context if item.strip()
                )
                if context_text:
                    user_message = (
                        "Conversation context:\n"
                        f"{context_text}\n\n"
                        "Current user message:\n"
                        f"{query}"
                    )

            if use_mcp_prompts:
                msgs = await fetch_mcp_prompt_messages(
                    "thematic_to_data",
                    {"user_message": user_message},
                )
                rewrite_result = await reformulate_for_data360(
                    reform_model,
                    user_message,
                    prompt_messages=msgs,
                )
            else:
                rewrite_result = await reformulate_for_data360(
                    reform_model,
                    user_message,
                )
            await _emit_stage(
                stage_hook,
                "rewrite",
                "completed",
                {"rewritten": rewrite_result.rewritten},
            )
            return {"rewrite": rewrite_result.model_dump()}
        except Exception as exc:
            raise RuntimeError(f"[rewrite] {type(exc).__name__}: {exc}") from exc

    async def compile_node(state: K360State) -> K360State:
        try:
            await _emit_stage(stage_hook, "compile", "started")
            query = state.get("query", "").strip()
            rewrite_raw = state.get("rewrite") or {}
            reform = (
                Data360ReformulationResult.model_validate(rewrite_raw)
                if rewrite_raw
                else None
            )
            messages = [HumanMessage(content=query)]
            if reform and reform.rewritten:
                messages = build_augmented_messages(messages, reform)

            final_messages: list[Any] | None = None
            async for event in compile_agent.astream_events(
                {"messages": messages},
                {"recursion_limit": get_agent_recursion_limit()},
                version="v2",
            ):
                event_type = str(event.get("event", ""))
                if event_type == "on_tool_start":
                    details: dict[str, Any] = {
                        "tool_name": event.get("name"),
                    }
                    if emit_tool_details:
                        details["tool_input"] = (event.get("data") or {}).get("input")
                    await _emit_stage(
                        stage_hook,
                        "tool_call",
                        "started",
                        details,
                    )
                elif event_type == "on_tool_end":
                    details = {
                        "tool_name": event.get("name"),
                    }
                    if emit_tool_details:
                        details["tool_output"] = (event.get("data") or {}).get("output")
                    await _emit_stage(
                        stage_hook,
                        "tool_call",
                        "completed",
                        details,
                    )
                elif event_type == "on_chain_end":
                    maybe = _extract_messages_from_chain_output(
                        (event.get("data") or {}).get("output")
                    )
                    if maybe is not None:
                        final_messages = maybe

            if final_messages is None:
                msg = "Compile stage ended without final messages."
                raise RuntimeError(msg)

            collected = _collect_agent_results(final_messages)
            tool_calls = list(collected.get("tool_calls") or [])
            packet = _content_packet_from_tool_calls(query, reform, tool_calls)
            await _emit_stage(
                stage_hook,
                "compile",
                "completed",
                {"tool_calls_count": len(tool_calls)},
            )
            return {
                "tool_calls": tool_calls,
                "compile_answer": collected.get("answer"),
                "content_packet": packet,
            }
        except Exception as exc:
            raise RuntimeError(f"[compile] {type(exc).__name__}: {exc}") from exc

    async def narrative_node(state: K360State) -> K360State:
        try:
            await _emit_stage(stage_hook, "narrative", "started")
            query = state.get("query", "").strip()
            packet = state.get("content_packet", {}) or {}
            tool_calls = state.get("tool_calls", []) or []
            if not packet and not tool_calls:
                return {"narrative": ""}
            prompt_msgs = await fetch_mcp_prompt_messages(
                "k360_narrative",
                {
                    "user_question": query,
                    "content_packet_json": _json_safe_text(packet),
                    "raw_tool_results_json": _json_safe_text(tool_calls),
                    "include_claim_tags": "true"
                    if _should_include_claim_tags()
                    else "false",
                },
            )
            narrative = ""
            if narrative_streaming:
                parts: list[str] = []
                async for chunk in writer_model.astream(prompt_msgs):
                    text = _message_content_to_text(getattr(chunk, "content", chunk))
                    if not text:
                        continue
                    parts.append(text)
                    await _emit_stage(
                        stage_hook,
                        "narrative_chunk",
                        "streaming",
                        {"chunk": text},
                    )
                narrative = "".join(parts).strip()
            else:
                writer_output = await writer_model.ainvoke(prompt_msgs)
                if isinstance(writer_output, AIMessage):
                    narrative = _message_content_to_text(writer_output.content).strip()
                else:
                    narrative = _message_content_to_text(writer_output).strip()
            await _emit_stage(
                stage_hook,
                "narrative",
                "completed",
                {"narrative_length": len(narrative)},
            )
            return {"narrative": _normalize_narrative_sections(narrative)}
        except Exception as exc:
            raise RuntimeError(f"[narrative] {type(exc).__name__}: {exc}") from exc

    graph = StateGraph(K360State)
    graph.add_node("gate", gate_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("compile", compile_node)
    graph.add_node("narrative", narrative_node)
    graph.add_edge(START, "gate")
    graph.add_conditional_edges(
        "gate",
        _is_relevant,
        {"relevant": "rewrite", "not_relevant": END},
    )
    graph.add_edge("rewrite", "compile")
    graph.add_edge("compile", "narrative")
    graph.add_edge("narrative", END)
    return graph.compile()


async def run_k360_query(
    query: str,
    model_name: str | None = None,
    *,
    context: list[str] | None = None,
    llm: BaseChatModel | None = None,
    llm_streaming: bool | None = None,
    use_mcp_prompts: bool = True,
    emit_tool_details: bool = False,
    narrative_streaming: bool = True,
    stage_hook: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
) -> dict[str, Any]:
    """Run the K360 staged flow and return a structured envelope."""
    try:
        graph = await create_k360_graph(
            llm=llm,
            model_name=model_name,
            llm_streaming=llm_streaming,
            use_mcp_prompts=use_mcp_prompts,
            emit_tool_details=emit_tool_details,
            narrative_streaming=narrative_streaming,
            stage_hook=stage_hook,
        )
        result = await graph.ainvoke(
            {
                "query": query.strip(),
                "context": context or [],
            }
        )
    except Exception as exc:
        logger.exception("K360 query failed")
        err = _error_payload(exc)
        return {
            "gate": {"relevant": False},
            "rewrite": {},
            "tool_calls": [],
            "content_packet": {},
            "narrative": "",
            "error": err["error"],
            "error_type": err["error_type"],
            "error_details": err["error_details"],
        }

    gate = result.get("gate", {}) or {}
    if gate.get("relevant") is not True:
        return {
            "gate": gate,
            "rewrite": {},
            "tool_calls": [],
            "content_packet": {},
            "narrative": "",
            "error": result.get("error"),
        }

    return {
        "gate": gate,
        "rewrite": result.get("rewrite", {}) or {},
        "tool_calls": result.get("tool_calls", []) or [],
        "content_packet": result.get("content_packet", {}) or {},
        "narrative": result.get("narrative", "") or "",
        "error": result.get("error"),
    }


__all__ = ["K360State", "create_k360_graph", "run_k360_query"]
