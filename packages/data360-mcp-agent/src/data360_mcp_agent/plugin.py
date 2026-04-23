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

from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from data360_mcp_agent.integration import (
    create_data360_mcp_agent,
    get_agent_recursion_limit,
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
):
    """Build an async node suitable for ``graph.add_node("data360", node)``.

    Parameters match :func:`data360_mcp_agent.integration.create_data360_mcp_agent`.

    Returns:
        An async callable ``async def node(state: MessagesState) -> dict`` that
        returns ``{"messages": [...]}`` with **delta** messages only.
    """
    agent = await create_data360_mcp_agent(llm=llm, model_name=model_name)

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
