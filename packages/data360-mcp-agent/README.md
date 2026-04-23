# data360-mcp-agent

**PyPI-oriented client library** for building LLM agents and LangGraph workflows against a **running** [Data360 MCP](https://github.com/worldbank/data360-mcp) server. This package does **not** embed the MCP server; you deploy or run the server separately and point this client at `DATA360_MCP_URL`.

## Install

```bash
pip install data360-mcp-agent
```

From a checkout of the `data360-mcp` monorepo (workspace):

```bash
uv sync --package data360-mcp-agent
# or
pip install -e packages/data360-mcp-agent
```

## Quick start

```python
import asyncio
from data360_mcp_agent import run_agent_query

async def main():
    out = await run_agent_query("GDP per capita for Kenya, last 10 years")
    print(out["answer"])

asyncio.run(main())
```

Environment (minimum):

| Variable | Description |
|----------|-------------|
| `DATA360_MCP_URL` | MCP HTTP URL, e.g. `http://127.0.0.1:8000/mcp` (match `MCP_PORT` / how you start the server) |
| `DATA360_MCP_TRANSPORT` | Default `streamable_http` |
| `DATA360_MCP_STREAMABLE_TERMINATE_ON_CLOSE` | Optional `false` to skip MCP session DELETE on disconnect (rare) |
| `OPENAI_API_KEY` | If using default `ChatOpenAI` (or inject your own `llm`) |

## Multi-agent (LangGraph)

```python
from data360_mcp_agent.plugin import MessagesState, create_data360_langgraph_node
```

See the **data360-mcp** repository under `examples/agents/langchain-graph/` for a runnable parent graph.

## API highlights

- `run_agent_query` — one-shot ReAct loop with MCP tools and server resources.
- `create_data360_mcp_agent` — compiled graph for custom orchestration.
- `create_data360_langgraph_node` — async node factory for `StateGraph.add_node`.
- `fetch_mcp_prompt_messages` — optional MCP prompt templates from the server.

## Troubleshooting

- **`McpError: Session terminated` during `initialize`:** The MCP Python streamable-HTTP client maps **HTTP 404** on the POST to this error (see `mcp/client/streamable_http.py`). The MCP **server** can also return 404 for an invalid/expired `mcp-session-id` (see `mcp/server/streamable_http.py`). **Fix:** ensure `DATA360_MCP_URL` ends with **`/mcp`**, the host/port matches the running server (`./run_server.sh` → default **8000**; `poe serve` may differ), and no proxy drops the path. **Stateless** (`stateless_http=True`) is fine. If the traceback shows `ExceptionGroup`, the underlying cause is still this MCP error — `data360-mcp-agent` unwraps it and raises a clearer `RuntimeError` with the URL in the message.
- **Stateful streamable HTTP + multiple workers:** If you later run **without** true stateless mode and the server tracks sessions in memory, use **one Uvicorn worker** or sticky routing so follow-up POSTs hit the same process.

## Relationship to `data360-mcp`

| Package | Role |
|---------|------|
| **`data360-mcp`** (this repo’s server) | FastMCP server, tools, resources — often **not** published to PyPI. |
| **`data360-mcp-agent`** (this package) | Client-only; **suitable for PyPI** — depends only on LangChain/LangGraph and talks to MCP over HTTP. |

### Publishing notes

- **PyPI `data360-mcp-agent`:** publish from `packages/data360-mcp-agent/` (`hatchling`/`setuptools` sdist/wheel). No dependency on the server wheel.
- **Monorepo → PyPI `data360-mcp` (server):** replace the workspace `data360-mcp-agent` optional extra with a **version range** on PyPI (e.g. `data360-mcp-agent>=0.1.0`) and drop `[tool.uv.sources]` / workspace `members` entry for that release line, or keep the server package free of any agent dependency (recommended).
