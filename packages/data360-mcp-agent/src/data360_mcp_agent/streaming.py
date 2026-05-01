"""Stream LangGraph v2 events from the compiled Data360 MCP agent.

Use this when you need **live** model tokens and **tool** lifecycle events. The
opaque :func:`data360_mcp_agent.plugin.create_data360_langgraph_node` helper
uses ``ainvoke`` only; for streaming, either iterate here or add the compiled
agent as a **subgraph node** on the parent and call ``parent.astream_events``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from data360_mcp_agent.integration import get_agent_recursion_limit


async def aiter_data360_mcp_agent_events(  # noqa: PLR0913
    agent: CompiledStateGraph,
    input_state: dict[str, Any],
    *,
    config: RunnableConfig | None = None,
    recursion_limit: int | None = None,
    version: Literal["v1", "v2"] = "v2",
    include_types: Sequence[str] | None = None,
    include_names: Sequence[str] | None = None,
    exclude_types: Sequence[str] | None = None,
    exclude_names: Sequence[str] | None = None,
) -> AsyncIterator[Any]:
    """Yield raw ``astream_events`` records from the Data360 agent graph.

    **Token chunks:** pass ``llm_streaming=True`` (or set ``DATA360_AGENT_LLM_STREAMING``)
    when building the agent with :func:`data360_mcp_agent.integration.create_data360_mcp_agent`
    so the default ``ChatOpenAI`` uses ``streaming=True``. Custom LLMs should
    already be configured for streaming.

    **Tool calls:** v2 events include tool starts/ends from LangGraph’s ReAct-style
    agent without extra wiring.

    **Parent graph:** compile the same ``agent`` as a node on a larger graph, then
    call ``parent.astream_events(...)`` on the parent — inner tool and chat events
    are included in the combined stream (filter on ``metadata`` / ``name`` as needed).

    Args:
        agent: Graph from :func:`data360_mcp_agent.integration.create_data360_mcp_agent`.
        input_state: e.g. ``{"messages": [HumanMessage(...)]}``.
        config: Optional LangGraph runnable config (merged with ``recursion_limit``).
        recursion_limit: Overrides default from :func:`get_agent_recursion_limit`.
        version: LangGraph stream protocol (default ``v2``).
        include_types / include_names / exclude_*: Forwarded to ``astream_events``
            for cheaper clients (optional filtering).

    Yields:
        LangGraph stream event dicts (shape depends on ``version``).
    """
    cfg = cast(RunnableConfig, {**(config or {})})
    if recursion_limit is not None:
        cfg["recursion_limit"] = recursion_limit
    else:
        cfg.setdefault("recursion_limit", get_agent_recursion_limit())

    stream_kw: dict[str, Any] = {"version": version}
    if include_types is not None:
        stream_kw["include_types"] = include_types
    if include_names is not None:
        stream_kw["include_names"] = include_names
    if exclude_types is not None:
        stream_kw["exclude_types"] = exclude_types
    if exclude_names is not None:
        stream_kw["exclude_names"] = exclude_names

    async for event in agent.astream_events(input_state, cfg, **stream_kw):
        yield event


__all__ = ["aiter_data360_mcp_agent_events"]
