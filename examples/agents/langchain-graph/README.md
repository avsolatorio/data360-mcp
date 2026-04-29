# Pluggable Data360 agent (LangGraph node)

Use this when you want the Data360 MCP agent as **one specialist inside a larger multi-agent graph** (supervisor/router, parallel branches, human-in-the-loop, etc.).

## Install / imports

After `pip install -e .` or `uv sync` from this repo:

```python
from data360_mcp_agent.plugin import MessagesState, create_data360_langgraph_node
```

For a **gated** specialist that classifies in-scope (World Bank / Data360 / development-economics) questions, optionally reformulates them into data tasks, and **skips** or **refuses** irrelevant turns:

```python
from data360_mcp_agent.plugin import MessagesState, create_data360_gated_langgraph_node

node = await create_data360_gated_langgraph_node(llm=my_llm)
```

See `gated_parent_graph_demo.py` and [`packages/data360-mcp-agent/README.md`](../../packages/data360-mcp-agent/README.md) (`DATA360_GATE_SKIP_MODE`, `skip_mode`, `enable_reformulation`).

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

**Gated** parent graph (same env vars; optional `DATA360_GATE_SKIP_MODE`, `DATA360_DEMO_USE_GATED=0` to compare with the non-gated node):

```bash
uv run python examples/agents/langchain-graph/gated_parent_graph_demo.py
```

`parent_graph_demo.py` does **not** exercise streaming (it calls `ainvoke` on a helper node). To print live **`astream_events` v2** records (tokens + tools), run:

```bash
uv run python examples/agents/langchain-graph/stream_events_demo.py
```

### Browser UI (SSE)

A small **FastAPI** + static page streams the same v2 events into the browser. See [`demo_web/README.md`](demo_web/README.md); from the repo root:

```bash
export DATA360_MCP_URL=...
export OPENAI_API_KEY=...
uv run uvicorn demo_web.server:app --app-dir examples/agents/langchain-graph --host 127.0.0.1 --port 8844
# open http://127.0.0.1:8844/
```

### K360 interactive UI with `@data360/mcp-ui`

The FastAPI demo server now exposes `POST /api/k360-query` for the staged flow
(`Gate -> Rewriter -> Compile -> Narrative`). The React demo in
`packages/mcp-ui/src/demo/main.tsx` can call that endpoint and render:

- narrative markdown,
- content packet inspector (`gate`, `rewrite`, `content_packet`),
- chart cards via `VegaChartCard` when viz specs are available.

## Troubleshooting

- **`McpError: Session terminated` on connect:** With the MCP streamable-HTTP client this usually means the MCP URL returned **HTTP 404** (wrong path, server not mounted, proxy). Check `DATA360_MCP_URL` matches your server’s MCP route (e.g. `/mcp`). **Stateless** server mode is fine; see [`packages/data360-mcp-agent/README.md`](../../packages/data360-mcp-agent/README.md) troubleshooting.

## Streaming (LangGraph `astream_events`)

The demo node from `create_data360_langgraph_node` uses **`ainvoke`** only, so the parent graph does not see token or tool events **during** the Data360 step.

For **both** model token chunks and **tool** lifecycle events, use the compiled agent with streaming enabled and LangGraph v2 events (see runnable **`stream_events_demo.py`** above):

```python
from langchain_core.messages import HumanMessage
from data360_mcp_agent import aiter_data360_mcp_agent_events, create_data360_mcp_agent

agent = await create_data360_mcp_agent(llm_streaming=True)
async for ev in aiter_data360_mcp_agent_events(
    agent,
    {"messages": [HumanMessage(content="Population of Kenya (use tools).")]},
):
    # Inspect ev["event"], ev.get("metadata"), etc. (v2 schema)
    ...
```

To combine with a **supervisor** graph, `add_node("data360", agent)` with the same compiled `agent`, then run `parent.astream_events(..., version="v2")` on the parent.

## Design notes

- **Delta messages:** the node returns only **new** messages from the Data360 turn (tool + assistant), so the parent reducer appends without duplicating history.
- **Full context:** the node passes the **entire** `state["messages"]` into the agent so follow-up turns keep context; trim upstream if you need isolation.
- **Repo root shim:** `import data360_mcp_service` still works but delegates to `data360_mcp_agent`.

See also section **10. Resources and Prompts** in [`docs/architecture-data360-mcp.md`](../../docs/architecture-data360-mcp.md).
