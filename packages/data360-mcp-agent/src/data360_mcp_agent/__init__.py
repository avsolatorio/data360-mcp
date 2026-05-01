"""``data360-mcp-agent``: LangChain / LangGraph client for a Data360 MCP server.

Install from PyPI (when published)::

    pip install data360-mcp-agent

Run a Data360 MCP server separately (e.g. from the ``data360-mcp`` repo or your
deployment), set ``DATA360_MCP_URL``, then import:

    from data360_mcp_agent import create_data360_mcp_agent, run_agent_query
    from data360_mcp_agent.plugin import (
        MessagesState,
        create_data360_gated_langgraph_node,
        create_data360_langgraph_node,
    )
"""

from __future__ import annotations

from data360_mcp_agent.integration import (
    AGENT_RECIPE_URI,
    CONTEXT_URI,
    SERVER_NAME,
    SYSTEM_PROMPT_URI,
    create_data360_mcp_agent,
    fetch_mcp_prompt_messages,
    get_agent_recursion_limit,
    get_cached_mcp_gate_system_prompt,
    list_mcp_tools,
    run_agent_query,
    use_mcp_prompts_from_env,
)
from data360_mcp_agent.k360_graph import create_k360_graph, run_k360_query
from data360_mcp_agent.plugin import (
    Data360AgentState,
    MessagesState,
    create_data360_agent_langgraph_node,
    create_data360_gated_langgraph_node,
    create_data360_langgraph_node,
)
from data360_mcp_agent.streaming import aiter_data360_mcp_agent_events

__all__ = [
    "AGENT_RECIPE_URI",
    "CONTEXT_URI",
    "Data360AgentState",
    "SERVER_NAME",
    "SYSTEM_PROMPT_URI",
    "MessagesState",
    "aiter_data360_mcp_agent_events",
    "create_data360_agent_langgraph_node",
    "create_data360_gated_langgraph_node",
    "create_data360_langgraph_node",
    "create_data360_mcp_agent",
    "create_k360_graph",
    "fetch_mcp_prompt_messages",
    "get_agent_recursion_limit",
    "get_cached_mcp_gate_system_prompt",
    "list_mcp_tools",
    "run_agent_query",
    "run_k360_query",
    "use_mcp_prompts_from_env",
]
