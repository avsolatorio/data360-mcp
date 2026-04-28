# Data360 MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that gives LLM agents direct access to the World Bank's [Data360 Platform](https://data360.worldbank.org/). Agents can search, validate, and retrieve development indicators—covering topics from GDP and poverty to gender equality and climate—without hallucinating data values.

> **Audience**: Developers building AI agents and chatbots that need reliable, structured access to World Bank development data.

---

## Key Features

- **Smart indicator discovery** — search across hundreds of indicators with enriched metadata and country coverage checks
- **Rich metadata retrieval** — fetch methodology, definitions, limitations, and statistical concepts on demand
- **Reliable time-series data** — query historical data points with filters for country, time period, sex, age, and urbanization
- **LLM-optimized resources** — built-in system prompts, codelists, and chain-of-thought guidance for chatbot integration
- **Agent-friendly design** — significant "glue" logic makes the raw Data360 API composable and safe for LLM tool use

---

## Getting Started

### Prerequisites

- **Python 3.11+**
- [uv](https://github.com/astral-sh/uv) (recommended) — or `pip`

### Installation

**With uv (recommended):**
```bash
git clone https://github.com/worldbank/data360-mcp.git
cd data360-mcp
uv sync
# LangChain / LangGraph client + examples + repo-root shim (data360_mcp_service.py):
uv sync --extra agent --group dev
```

**With pip:**
```bash
git clone https://github.com/worldbank/data360-mcp.git
cd data360-mcp
pip install -e .
```

### Configuration

Copy the example environment file and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `DATA360_API_BASE_URL` | Base URL for the World Bank Data360 API | `https://data360api.worldbank.org` |
| `MCP_PORT` | Port for the MCP server | `8000` |
| `MCP_TRANSPORT` | Transport protocol (`http` or `sse`) | `http` |
| `MCP_CHARTS_API_URL` | Optional URL for an external chart rendering API | _(none)_ |

### Run the Server

```bash
uv run poe serve
# Server starts at http://localhost:8000/mcp
```

Or with custom port/transport:
```bash
uv run poe serve --port 8021 --transport sse
# SSE endpoint: http://localhost:8021/sse
```

### Connect Your Agent

| Setting | Value |
|---|---|
| Transport | `http` (default) or `sse` |
| URL (http) | `http://localhost:8000/mcp` |
| URL (sse) | `http://localhost:8021/sse` |
| Docker / external | Replace `localhost` with `host.docker.internal` |

### Try the Demo

```bash
uv run scripts/llm_mcp_demo.py
# DEBUG mode:
DEBUG=true uv run scripts/llm_mcp_demo.py
```

**Minimal external agent (one-shot):** [examples/agents/langchain-minimal/README.md](examples/agents/langchain-minimal/README.md) — copy-paste `run_once.py` that loads `data360://system-prompt` and tools, then calls the model.

**Multi-agent / LangGraph:** [examples/agents/langchain-graph/README.md](examples/agents/langchain-graph/README.md) — register Data360 as a node (`create_data360_langgraph_node` or gated `create_data360_gated_langgraph_node`) alongside supervisors and other specialists. Client library (publishable on PyPI): [`packages/data360-mcp-agent/`](packages/data360-mcp-agent/) (`pip install data360-mcp-agent`). The repo-root [`data360_mcp_service.py`](data360_mcp_service.py) shim re-exports `data360_mcp_agent` for older import paths.

---

## MCP Tools

| Tool | Description |
|---|---|
| `data360_search_indicators` | Search indicators with enriched metadata. Pass `required_country` for server-side coverage check. Returns `covers_country`, `latest_data`, `dimensions`. |
| `data360_get_data` | Fetch data points with filters (country, time period, SEX, AGE, etc.). |
| `data360_get_metadata` | Get indicator metadata. Use `select_fields` for specific fields. |
| `data360_get_disaggregation` | Check available filter values (countries, years, dimensions) for an indicator. |
| `data360_find_codelist_value` | Resolve human-readable names to codes (e.g., "Kenya" → `KEN`, "female" → `F`). |
| `data360_list_indicators` | List all indicators for a given database. |

### Recommended Agent Workflow

```
1. Search    → data360_search_indicators(query, required_country="Kenya")
               Returns: covers_country, latest_data, dimensions per indicator

2. Get Data  → data360_get_data(database_id, indicator_id, filters)
               Use REF_AREA code from search; add time period filters
```

---

## MCP Resources

| Resource | Description |
|---|---|
| `data360://system-prompt` | Chain-of-thought guidance for chatbot integration |
| `data360://databases` | Available databases (WB_WDI, WB_SSGD, etc.) |
| `data360://codelists` | Codelist reference (REF_AREA, SEX, AGE, etc.) |
| `data360://metadata-fields` | Field mapping for smart question routing |
| `data360://data-filters` | Available filters and usage guidance |
| `data360://search-usage` | Search examples and best practices |

For chatbot integration, copy `data360://system-prompt` into your system prompt. It includes chain-of-thought reasoning templates and filter guidance.

---

## Documentation

**Project site:** [worldbank.github.io/data360-mcp](https://worldbank.github.io/data360-mcp) — landing page with features, tools, and connection details.

A markdown overview lives in [docs/overview.md](docs/overview.md). The site is deployed with [GitHub Actions](.github/workflows/pages.yml) on pushes to `main` or `dev`. In the repository **Settings → Pages**, set **Build and deployment** source to **GitHub Actions** (first-time setup).

**Preview locally:** from the repository root, run `python -m http.server --directory docs` and open `http://127.0.0.1:8000/`.

For developer setup, testing, and contribution instructions, see [DEVELOPMENT.md](DEVELOPMENT.md).

---

## Contact

**AI for Data - Data for AI Team** ([ai4data@worldbank.org](mailto:ai4data@worldbank.org))
Development Data Group / Office of the World Bank Group Chief Statistician
World Bank Group

---

## License

This project is licensed under the MIT License together with the World Bank IGO Rider.
The Rider is purely procedural: it reserves all privileges and immunities enjoyed by the
World Bank, without adding restrictions to the MIT permissions. Please review both files
before using, distributing or contributing.

See [LICENSE](LICENSE) and [WB-IGO-RIDER.md](WB-IGO-RIDER.md) for the full license texts.

---

<p align="center">
  <sub>Built with <a href="https://github.com/jlowin/fastmcp">FastMCP</a> and the <a href="https://modelcontextprotocol.io">Model Context Protocol</a>.</sub>
</p>
