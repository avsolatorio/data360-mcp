"""LangGraph helpers: plug the Data360 MCP agent in as a node in a larger graph.

Your parent graph should use a ``messages`` channel with the ``add_messages``
reducer (same pattern as LangGraph tutorials). The node returned by
:func:`create_data360_langgraph_node` forwards ``state["messages"]`` to the
Data360 agent and **appends only new** tool/assistant messages produced in that
step—so supervisors and sibling agents can share one transcript.

Example::

    from langgraph.graph import END, START, StateGraph

    from data360_mcp_agent.plugin import MessagesState, create_data360_langgraph_node

    async def build_graph():
        g = StateGraph(MessagesState)
        data360_node = await create_data360_langgraph_node(llm=my_shared_llm)
        g.add_node("data360", data360_node)
        g.add_edge(START, "data360")
        g.add_edge("data360", END)
        return g.compile()

"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph.message import add_messages

from data360_mcp_agent.gate import (
    DEFAULT_REFUSAL_TEXT,
    build_augmented_messages,
    classify_data360_relevance,
    last_user_text,
    reformulate_for_data360,
)
from data360_mcp_agent.integration import (
    create_data360_mcp_agent,
    fetch_mcp_prompt_messages,
    get_agent_recursion_limit,
    get_cached_mcp_gate_system_prompt,
    prepare_cache_for_mcp_gate_prompts,
    release_mcp_gate_prompt_preparation,
    use_mcp_prompts_from_env,
    _resolve_llm,
)

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel


class MessagesState(TypedDict, total=False):
    """Minimal shared state for multi-agent graphs using message reducers."""

    messages: Annotated[list[BaseMessage], add_messages]


async def create_data360_langgraph_node(
    *,
    llm: BaseChatModel | None = None,
    model_name: str | None = None,
    llm_streaming: bool | None = None,
):
    """Build an async node suitable for ``graph.add_node("data360", node)``.

    Parameters match :func:`data360_mcp_agent.integration.create_data360_mcp_agent`.

    This node uses ``ainvoke`` only — **no live token/tool stream** to the parent
    while the node runs. For ``astream_events`` (tokens + tools), add the compiled
    agent as a subgraph or use :func:`data360_mcp_agent.streaming.aiter_data360_mcp_agent_events`.

    Returns:
        An async callable ``async def node(state: MessagesState) -> dict`` that
        returns ``{"messages": [...]}`` with **delta** messages only.
    """
    agent = await create_data360_mcp_agent(
        llm=llm,
        model_name=model_name,
        llm_streaming=llm_streaming,
    )

    async def data360_node(state: MessagesState) -> dict[str, Any]:
        prior = state.get("messages") or []
        n_prior = len(prior)
        result = await agent.ainvoke(
            {"messages": prior},
            config={"recursion_limit": get_agent_recursion_limit()},
        )
        out = result.get("messages") or []
        delta = out[n_prior:] if len(out) >= n_prior else out
        return {"messages": delta}

    return data360_node


def _effective_skip_mode(
    skip_mode: Literal["silent", "refusal"],
    *,
    apply_skip_mode_from_env: bool,
) -> Literal["silent", "refusal"]:
    if apply_skip_mode_from_env:
        raw = os.getenv("DATA360_GATE_SKIP_MODE", "").strip().lower()
        if raw in ("silent", "refusal"):
            return raw  # type: ignore[return-value]
    return skip_mode


def _effective_use_mcp_prompts(
    explicit: bool | None,
    *,
    apply_from_env: bool,
) -> bool:
    """Use MCP ``gate_classifier`` / ``thematic_to_data`` when True."""
    if explicit is not None:
        return explicit
    if apply_from_env:
        return use_mcp_prompts_from_env()
    return False


async def create_data360_gated_langgraph_node(  # noqa: PLR0913
    *,
    llm: BaseChatModel | None = None,
    model_name: str | None = None,
    llm_streaming: bool | None = None,
    skip_mode: Literal["silent", "refusal"] = "silent",
    apply_skip_mode_from_env: bool = True,
    enable_reformulation: bool = True,
    gate_llm: BaseChatModel | None = None,
    reform_llm: BaseChatModel | None = None,
    use_mcp_prompts: bool | None = None,
    apply_mcp_prompts_from_env: bool = True,
):
    """Build a LangGraph node that **gates** Data360 before MCP tool orchestration.

    Runs a small structured LLM call to decide if the latest user turn is in scope
    for World Bank / Data360 data (including thematic development-economics questions).
    If not in scope, returns an empty message delta (``silent``) or a short
    ``AIMessage`` (``refusal``), depending on ``skip_mode`` and optional env
    ``DATA360_GATE_SKIP_MODE`` (``silent`` or ``refusal``).

    When in scope, optionally reformulates the user text into a concrete data task,
    then invokes the same MCP agent as :func:`create_data360_langgraph_node`.

    ``use_mcp_prompts`` / ``DATA360_AGENT_USE_MCP_PROMPTS`` — when enabled, the gate
    uses MCP ``prompts/get`` ``gate_classifier`` (cached with tools/resources) and
    reform uses ``thematic_to_data`` per turn so wording stays aligned with the server.

    Other parameters match :func:`create_data360_langgraph_node`.
    """
    base_llm = _resolve_llm(model_name, llm, llm_streaming=llm_streaming)
    gate_model = gate_llm or base_llm
    reform_model = reform_llm or base_llm
    effective_skip = _effective_skip_mode(
        skip_mode,
        apply_skip_mode_from_env=apply_skip_mode_from_env,
    )
    effective_mcp_prompts = _effective_use_mcp_prompts(
        use_mcp_prompts,
        apply_from_env=apply_mcp_prompts_from_env,
    )

    await prepare_cache_for_mcp_gate_prompts(effective_mcp_prompts)
    try:
        agent = await create_data360_mcp_agent(
            llm=base_llm,
            model_name=None,
            llm_streaming=llm_streaming,
        )
    finally:
        await release_mcp_gate_prompt_preparation()

    async def data360_gated_node(state: MessagesState) -> dict[str, Any]:
        prior = state.get("messages") or []
        user_text = last_user_text(prior)
        if not user_text:
            return {"messages": []}

        gate_extra = None
        if effective_mcp_prompts:
            gate_extra = get_cached_mcp_gate_system_prompt()
        gate_result = await classify_data360_relevance(
            gate_model,
            user_text,
            gate_system_prompt=gate_extra,
        )
        if not gate_result.relevant:
            if effective_skip == "silent":
                return {"messages": []}
            refusal = (gate_result.refusal_text or "").strip() or DEFAULT_REFUSAL_TEXT
            return {"messages": [AIMessage(content=refusal)]}

        to_invoke: list[BaseMessage] = list(prior)
        if enable_reformulation:
            if effective_mcp_prompts:
                mcp_reform_msgs = await fetch_mcp_prompt_messages(
                    "thematic_to_data",
                    {"user_message": user_text},
                )
                reform = await reformulate_for_data360(
                    reform_model,
                    user_text,
                    prompt_messages=mcp_reform_msgs,
                )
            else:
                reform = await reformulate_for_data360(reform_model, user_text)
            to_invoke = build_augmented_messages(prior, reform)

        n_prior = len(to_invoke)
        result = await agent.ainvoke(
            {"messages": to_invoke},
            config={"recursion_limit": get_agent_recursion_limit()},
        )
        out = result.get("messages") or []
        delta = out[n_prior:] if len(out) >= n_prior else out
        return {"messages": delta}

    return data360_gated_node
