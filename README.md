# 🌍 Data360 MCP Server

> **Unlock the World Bank's global development data directly within your LLM agents.**

This Model Context Protocol (MCP) server bridges the gap between Large Language Models and the World Bank's massive [Data360 Platform](https://tcdata360.worldbank.org/). It empowers agents to search, validate, and retrieve precise development indicators—from GDP to gender equality metrics—without hallucinating.

## ✨ Capabilities

This isn't just a wrapper; it's significant "glue" code that makes the Data360 API agent-friendly.

### 🔍 Smart Discovery
**Composable tools for precise searches.**
Use `data360_search_indicators` with `select_fields` to control what data is returned. Validate availability with `data360_get_disaggregation` to check which countries and years have data.

### 📊 Deep Metadata
**Context is king.**
Fetch rich metadata selectively using `data360_get_metadata` with `select_fields` to get only what you need—methodology, statistical concepts, or limitations.

### 📈 Reliable Data Retrieval
**Clean, time-series data.**
Fetch historical data points for any indicator with `data360_get_data`, supporting filters for country, time period, sex, age, and urbanization.

### 🤖 LLM-Optimized Resources
**Built-in guidance for chatbots.**
MCP resources provide system prompts with chain-of-thought reasoning, codelist references, and metadata field mappings.

---

## 🚀 Quick Start

### 1. Prerequisites
- **Python 3.10+** (or use Docker)
- [uv](https://github.com/astral-sh/uv) (recommended)

### 2. Run the Server
```bash
chmod +x scripts/start_server.sh
./scripts/start_server.sh
```

The server will start on port `8021` at `/sse`.

### 3. Connect your Agent
- **Transport**: SSE
- **URL**: `http://localhost:8021/sse`
- **Docker Users**: Use `http://host.docker.internal:8021/sse`

---

## 🛠️ Tools Available

| Tool | Description |
|------|-------------|
| **`data360_search_indicators`** | Search for indicators. Use `select_fields` for enriched results. |
| **`data360_get_disaggregation`** | Check available filter values (countries, years, dimensions). |
| **`data360_get_metadata`** | Get indicator metadata. Use `select_fields` for specific fields. |
| **`data360_get_data`** | Fetch data points with filters (REF_AREA, time period, etc.). |
| **`data360_find_codelist_value`** | Resolve country names to codes (e.g., "Kenya" → "KEN"). |
| **`data360_list_indicators`** | List all indicators for a database. |

---

## 📚 Resources Available

| Resource | Description |
|----------|-------------|
| `data360://system-prompt` | Chain-of-thought guidance for chatbot integration |
| `data360://databases` | Available databases (WB_WDI, WB_SSGD, etc.) |
| `data360://codelists` | Codelist reference (REF_AREA, SEX, AGE, etc.) |
| `data360://metadata-fields` | Field mapping for smart question routing |
| `data360://data-filters` | Available filters and usage guidance |
| `data360://search-usage` | Search examples and best practices |

---

## 💬 Chatbot Integration

For chatbot integration, copy the content of `data360://system-prompt` into your system prompt. It includes:
- Chain-of-thought reasoning templates
- Step-by-step workflow guidance
- Filter do's and don'ts (e.g., never use FREQ filter)

---

## ⚙️ Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DATA360_API_BASE_URL` | Base URL for the World Bank API | `https://data360api.worldbank.org` |
| `PORT` | Port for the MCP server | `8021` |

---

## 👨‍💻 Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed instructions on setting up the local dev environment.

---

<p align="center">
  <sub>Built with <a href="https://github.com/jlowin/fastmcp">FastMCP</a> and the <a href="https://modelcontextprotocol.io">Model Context Protocol</a>.</sub>
</p>
