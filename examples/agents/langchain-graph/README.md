# Pluggable Data360 agent (LangGraph node)

Use this when you want the Data360 MCP agent as **one specialist inside a larger multi-agent graph** (supervisor/router, parallel branches, human-in-the-loop, etc.).

## Install / imports

After `pip install -e .` or `uv sync` from this repo:

```python
from data360_mcp_agent.plugin import MessagesState, create_data360_langgraph_node
```

The factory returns an **async node** compatible with `StateGraph.add_node("data360", node)`. It shares the usual LangGraph **`messages` + `add_messages`** pattern so your supervisor can append user turns and route to Data360 or other specialists on the same transcript.

The compiled agent graph is also available directly:

```python
from data360_mcp_agent import create_data360_mcp_agent

agent = await create_data360_mcp_agent(llm=my_llm)
await agent.ainvoke({"messages": [...]})
```

Use that if you embed the graph yourself (e.g. custom orchestration, non-LangGraph framework).

## Environment

Same as other agent examples: `DATA360_MCP_URL`, `DATA360_MCP_TRANSPORT`, `OPENAI_API_KEY`, etc. See [langchain-minimal README](../langchain-minimal/README.md). Install the client with `pip install data360-mcp-agent` or, from this monorepo, `uv sync --group dev` (workspace member).

## Demo

```bash
# Port must match the server: ./run_server.sh defaults MCP_PORT to 8000;
# `poe serve` / `python -m data360.mcp_server` often use 8021.
export DATA360_MCP_URL=http://127.0.0.1:8000/mcp
export OPENAI_API_KEY=...
uv run python examples/agents/langchain-graph/parent_graph_demo.py
```

## Troubleshooting

- **`McpError: Session terminated` on connect:** With the MCP streamable-HTTP client this usually means the MCP URL returned **HTTP 404** (wrong path, server not mounted, proxy). Check `DATA360_MCP_URL` matches your server’s MCP route (e.g. `/mcp`). **Stateless** server mode is fine; see [`packages/data360-mcp-agent/README.md`](../../packages/data360-mcp-agent/README.md) troubleshooting.

## Design notes

- **Delta messages:** the node returns only **new** messages from the Data360 turn (tool + assistant), so the parent reducer appends without duplicating history.
- **Full context:** the node passes the **entire** `state["messages"]` into the agent so follow-up turns keep context; trim upstream if you need isolation.
- **Repo root shim:** `import data360_mcp_service` still works but delegates to `data360_mcp_agent`.

See also section **10. Resources and Prompts** in [`docs/architecture-data360-mcp.md`](../../docs/architecture-data360-mcp.md).
