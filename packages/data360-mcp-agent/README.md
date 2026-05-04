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

### Integration recipe (resources + MCP prompts)

The MCP server publishes **`data360://agent-recipe`** — composition order, named prompts (`gate_classifier`, `thematic_to_data`, `country_data`, …), and how they relate to this package.

- To append that doc into the agent’s **system stack** (longer context):
  `DATA360_AGENT_EXTRA_RESOURCES=data360://agent-recipe`

- **`fetch_mcp_prompt_messages(name, …)`** — fetch `gate_classifier`, `thematic_to_data`, etc., as LangChain messages when you want the **same wording** as the MCP server instead of only the gated node’s embedded prompts.

Python constant: **`AGENT_RECIPE_URI`** (`data360://agent-recipe`).

Additional environment variables:

| Variable | Description |
|----------|-------------|
| `DATA360_MCP_TRANSPORT` | Default `streamable_http` |
| `DATA360_MCP_STREAMABLE_TERMINATE_ON_CLOSE` | Optional `false` to skip MCP session DELETE on disconnect (rare) |
| `OPENAI_API_KEY` | If using default `ChatOpenAI` (or inject your own `llm`) |
| `DATA360_AGENT_LLM_STREAMING` | Optional `true` — default `ChatOpenAI` uses `streaming=True` for `astream_events` token chunks |

## Multi-agent (LangGraph)

```python
from data360_mcp_agent.plugin import MessagesState, create_data360_langgraph_node
```

### Gated node (relevance + reformulation)

Use **`create_data360_gated_langgraph_node`** when the parent graph should **skip** Data360 for out-of-scope turns (chit-chat, non–development-data questions) and optionally **rewrite** thematic development-economics questions into concrete indicator/search tasks before tools run.

| Parameter | Description |
|-----------|-------------|
| `skip_mode` | `"silent"` (default): return no new messages when irrelevant. `"refusal"`: append a short `AIMessage`. |
| `apply_skip_mode_from_env` | If `True` (default), `DATA360_GATE_SKIP_MODE` (`silent` or `refusal`) overrides the constructor default when set. |
| `enable_reformulation` | If `True` (default), a second structured LLM call turns the user text into an orchestration prompt (economies, indicator themes, years, comparators). |
| `gate_llm` / `reform_llm` | Optional; default to the same resolved model as `llm`. |
| `use_mcp_prompts` | If `True`, gate/reform pull prompt text from the MCP server (`gate_classifier`, `thematic_to_data`) instead of embedded strings. If `None`, read env (see below). |
| `apply_mcp_prompts_from_env` | If `True` (default), `DATA360_AGENT_USE_MCP_PROMPTS` can turn MCP prompts on without code changes. |

**Streamlined MCP-aligned prompts:** set **`DATA360_AGENT_USE_MCP_PROMPTS=true`** (or pass **`use_mcp_prompts=True`**). The gated node then:

1. **Caches** the `gate_classifier` MCP prompt together with tools/resources (same TTL as `DATA360_MCP_CACHE_TTL`).
2. **Each in-scope turn** calls **`thematic_to_data`** via `fetch_mcp_prompt_messages` for reformulation, so wording stays in sync with the Data360 MCP server.

If the server is unreachable or prompts are missing, the gate falls back to the package’s embedded defaults.

Additional environment variables:

| Variable | Description |
|----------|-------------|
| `DATA360_GATE_SKIP_MODE` | `silent` or `refusal` — honored when `apply_skip_mode_from_env=True`. |
| `DATA360_AGENT_USE_MCP_PROMPTS` | `true` / `1` / `yes` — use MCP prompt names for gate + reform (when `use_mcp_prompts` is left default). |

Each gated turn performs **two small LLM calls** (classify + reformulate) before the MCP ReAct loop, plus **one MCP `prompts/get`** when MCP reform is enabled. Import from `data360_mcp_agent` or `data360_mcp_agent.plugin`.

See the **data360-mcp** repository under `examples/agents/langchain-graph/` for `gated_parent_graph_demo.py`.

### Streaming (tokens + tool events)

LangGraph exposes both through **`astream_events(version="v2")`** on the **compiled** agent graph.

1. **Build the agent with streaming LLM** (OpenAI default):
   `await create_data360_mcp_agent(..., llm_streaming=True)`
   or set `DATA360_AGENT_LLM_STREAMING=true`. For a custom `llm=`, enable streaming on that model yourself.

2. **Stream only Data360** (no parent graph):

   ```python
   from data360_mcp_agent import aiter_data360_mcp_agent_events, create_data360_mcp_agent

   agent = await create_data360_mcp_agent(llm_streaming=True)
   async for ev in aiter_data360_mcp_agent_events(agent, {"messages": [...]}):
       ...  # filter on ev["event"], metadata, etc.
   ```

3. **Supervisor + Data360 in one graph:** add the same `agent` as a **node** (subgraph), then call `parent.astream_events(..., version="v2")` on the parent. Tool and chat events from the Data360 subgraph appear in the combined stream; filter by node name / tags in `metadata` if needed.

The helper `create_data360_langgraph_node` still uses **`ainvoke`** — it updates `messages` only **after** the turn. Prefer (2) or (3) for live UX.

## API highlights

- `run_agent_query` — one-shot ReAct loop with MCP tools and server resources.
- `run_k360_query` — staged K360 envelope:
  `gate -> rewrite -> compile(tool loop) -> narrative`.
- `create_data360_mcp_agent` — compiled graph for custom orchestration.
- `create_k360_graph` — compiled LangGraph implementation of staged K360 flow.
- `aiter_data360_mcp_agent_events` — async iterator over `astream_events` for tokens + tools.
- `create_data360_langgraph_node` — async node factory for `StateGraph.add_node`.
- `create_data360_gated_langgraph_node` — same, with relevance gate + optional knowledge→data reformulation.
- `fetch_mcp_prompt_messages` — optional MCP prompt templates from the server.

### K360 stage mapping

| Stage | Component | Output |
|------|-----------|--------|
| Gate | `classify_data360_relevance` (optionally MCP `gate_classifier`) | `gate` |
| Rewriter | `reformulate_for_data360` (optionally MCP `thematic_to_data`) | `rewrite` |
| Compile content | Data360 ReAct agent (`create_data360_mcp_agent`) + tool trace extraction | `tool_calls`, `content_packet` |
| Narrative | MCP `k360_narrative` prompt rendered by LLM | `narrative` |

Out-of-scope queries return an empty payload envelope:
`tool_calls: []`, `content_packet: {}`, `narrative: ""`.

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
