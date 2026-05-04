# Minimal LangChain agent (Data360 MCP)

This folder is a **copy-paste-friendly** example: one MCP connection load tools, read `data360://system-prompt` and `data360://context`, and run a single agent turn with [`create_agent`](https://docs.langchain.com/oss/python/langchain-agents).

For a longer **interactive REPL** with token tracking, use [`scripts/llm_mcp_demo.py`](../../scripts/llm_mcp_demo.py) instead.

## Prerequisites

- Python 3.11+ and `uv` (from the repo root: `uv sync`)
- A running Data360 MCP HTTP endpoint (e.g. `./run_server.sh` → default `http://127.0.0.1:8000/mcp`, or `uv run poe serve --port 8021` → `http://127.0.0.1:8021/mcp`)
- An OpenAI API key in the environment (same as other examples)

## Environment

| Variable | Required | Description |
|----------|------------|-------------|
| `DATA360_MCP_URL` | Yes | Full MCP URL, e.g. `http://127.0.0.1:8000/mcp` (must match the server port) |
| `DATA360_MCP_TRANSPORT` | No | Default `streamable_http` (matches `poe serve` default). Use the transport your server advertises. |
| `OPENAI_API_KEY` | Yes | For `ChatOpenAI` |
| `DATA360_AGENT_MODEL` | No | Default `gpt-4.1-mini` |

Set `DATA360_MCP_TRANSPORT` to match your server. The FastMCP app in this repo is mounted at `/mcp` (see `src/data360/server.py`). The interactive demo uses SSE in places; this minimal example uses **streamable HTTP** to match the default server.

## Run

From the **repository root**:

```bash
export DATA360_MCP_URL=http://127.0.0.1:8000/mcp
export OPENAI_API_KEY=...
uv run python examples/agents/langchain-minimal/run_once.py "GDP per capita for Kenya, last 10 years"
```

## Architecture note

Workflow instructions should come from MCP **resources** (`data360://system-prompt`, `data360://context`) so clients stay aligned with the server. See section **10. Resources and Prompts** in [`docs/architecture-data360-mcp.md`](../../docs/architecture-data360-mcp.md).

Parameterized workflows are also available as MCP **prompts** (`indicator_search`, `indicator_details`, `country_data`) — see [`src/data360/mcp_server/prompts.py`](../../src/data360/mcp_server/prompts.py). Production client wiring lives in the **`data360-mcp-agent`** package ([`packages/data360-mcp-agent/`](../../packages/data360-mcp-agent/)). To plug Data360 into a **broader LangGraph**, see [langchain-graph README](../langchain-graph/README.md).
