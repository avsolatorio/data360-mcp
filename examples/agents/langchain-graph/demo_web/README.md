# Browser demo (Data360 MCP agent)

Minimal **FastAPI** server + static page that streams **LangGraph v2** events (tokens + tools) via **Server-Sent Events**.

## Prerequisites

Same as other agent examples: running Data360 MCP server, `DATA360_MCP_URL`, `OPENAI_API_KEY`, and this repo synced with `uv sync` so `data360-mcp-agent` is available.

You can put those (and optional `DATA360_AGENT_MODEL`, etc.) in a **`.env`** file:

- **`data360-mcp/.env`** at the repository root — loaded automatically when you start uvicorn from anywhere under this repo.
- **`.env` in your current working directory** — loaded second; duplicate keys **override** the repo file (useful when you run the server from another folder).

Shell exports still win over `.env` unless you clear them.

## Run

From the **repository root** (`data360-mcp/`):

```bash
uv run uvicorn demo_web.server:app --app-dir examples/agents/langchain-graph --host 127.0.0.1 --port 8844
```

Or set variables explicitly instead of `.env`:

```bash
export DATA360_MCP_URL=http://127.0.0.1:8000/mcp
export OPENAI_API_KEY=...
uv run uvicorn demo_web.server:app --app-dir examples/agents/langchain-graph --host 127.0.0.1 --port 8844
```

Open **http://127.0.0.1:8844/** in a browser, enter a query, click **Stream**.

The **Answer** panel shows the assistant’s **final narrative**: the last `on_chat_model_end` event whose output has **no tool calls** (typical closing synthesis after tools). If the graph ends differently, the UI falls back to the last chat-model message text.

## Notes

- **Local dev only** — no authentication; bind to `127.0.0.1` as above.
- **Health:** `GET /api/health`
- **Stream:** `POST /api/stream` with JSON `{"query": "..."}` — response is `text/event-stream`.
- **K360 staged query:** `POST /api/k360-query` with JSON `{"query":"..."}` — returns
  `{gate, rewrite, tool_calls, content_packet, narrative, error}`.
- **Viz charts:** When the agent calls `data360_get_viz_spec` / `data360_get_multi_indicator_viz_spec`, the page listens for LangGraph **`on_tool_end`** events, reads the **`url`** in the tool result (static `…/static/viz_specs/*_vega.json`), and fetches the Vega-Lite JSON via **`GET /api/fetch-viz-spec?url=…`** (server-side proxy avoids browser CORS). The chart is rendered with **vega-embed** from a CDN — the same spec as **[`@data360/mcp-ui`](../../../packages/mcp-ui/)** `VegaChartCard`, without bundling React.
- **`WEBSITE_HOSTNAME`:** The MCP server builds chart URLs with `WEBSITE_HOSTNAME` or defaults to `http://localhost:{MCP_PORT}`. Set `WEBSITE_HOSTNAME` to the origin your browser can reach (e.g. `http://127.0.0.1:8000`) so it matches **`DATA360_MCP_URL`**’s host/port; otherwise the proxy may reject cross-host URLs (`localhost` vs `127.0.0.1` is allowed when ports match).
- The compiled agent is **cached** after the first successful request.
- `POST /api/k360-query` uses the staged K360 pipeline (`Gate -> Rewriter -> Compile -> Narrative`).

## Troubleshooting (chart not showing)

- **Tool output was not JSON in the stream:** LangGraph’s v2 events used to carry `ToolMessage` objects, which `json.dumps` turned into useless `repr` strings, so the page could not read `url`. The demo server now **normalizes** `on_tool_end` → `data.output` into plain dicts before SSE.
- **Query must actually call a viz tool** (e.g. ask for a chart, or a flow that runs `data360_get_viz_spec` after fetching data). A text-only answer will not produce a spec URL.
- **Proxy 400:** `GET /api/fetch-viz-spec` only allows the static `…/static/viz_specs/*_vega.json` path on the same **port** as `DATA360_MCP_URL` and a safe host. Set **`WEBSITE_HOSTNAME`** on the MCP process to match the host you use in the browser (see [`.env.example`](../../../.env.example)).
