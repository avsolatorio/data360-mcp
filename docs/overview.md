# Data360 MCP Server

> **Project site:** The full documentation for this repository is published at **[https://worldbank.github.io/data360-mcp](https://worldbank.github.io/data360-mcp)** (`docs/index.html`). This file is a markdown overview for readers browsing the repo on GitHub.

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that gives LLM agents direct access to the World Bank's [Data360 Platform](https://data360.worldbank.org/).

## Overview

The Data360 MCP Server bridges the gap between Large Language Models and the World Bank's development data infrastructure. It allows AI agents to search, validate, and retrieve precise development indicators — covering topics such as GDP, poverty, gender equality, health, and climate — without hallucinating data values.

**Who is this for?**
- Developers building AI agents that need reliable access to World Bank development data
- Researchers and analysts who want to integrate World Bank data into LLM workflows
- Teams building data-driven applications on top of the MCP ecosystem

For a complete guide — including example questions, charts, architecture, MCP Apps, prompts, and connection steps — see the [project site](https://worldbank.github.io/data360-mcp).

## Key Features

- **Indicator discovery** — search hundreds of indicators with metadata and country coverage checks
- **Dataset search** — find Data360 source databases by name
- **Rich metadata** — retrieve methodology, definitions, limitations, and statistical concepts
- **Time-series data** — query historical data with filters for country, time period, sex, age, and urbanization
- **Aggregation tools** — summarize, rank, and compare countries without raw series payloads
- **Charts** — Vega-Lite specs for single- and multi-indicator visualizations
- **LLM resources** — built-in system prompts, codelists, and chain-of-thought reasoning guidance
- **MCP prompts** — parameterized playbooks for search, country data, gating, and narrative flows
- **Agent-safe design** — composable tools with guardrails that prevent common LLM data errors

## Getting Started

See the [README](https://github.com/worldbank/data360-mcp/tree/dev#readme) for full installation and usage instructions.

**Quick start:**
```bash
git clone https://github.com/worldbank/data360-mcp.git
cd data360-mcp
uv sync
cp .env.example .env
uv run poe serve
```

The server starts at `http://localhost:8000/mcp`.

## Available Tools

| Tool | What it does |
|---|---|
| `data360_search_indicators` | Search indicators with coverage checks; supports multi-query |
| `data360_search_datasets` | Search dataset catalogs |
| `data360_get_data` | Fetch time-series observations |
| `data360_get_metadata` | Get indicator methodology and definitions |
| `data360_get_disaggregation` | Check available filter values |
| `data360_find_codelist_value` | Resolve names to standard codes |
| `data360_expand_country_group` | Expand region/income group codes to countries |
| `data360_list_indicators` | List all indicators in a database |
| `data360_summarize_data` | Summary statistics by dimension |
| `data360_rank_countries` | Rank countries for a year |
| `data360_compare_countries` | Compare 2–8 countries on one indicator |
| `data360_get_viz_spec` | Generate Vega-Lite chart for one indicator |
| `data360_get_multi_indicator_viz_spec` | Chart comparing 2–4 indicators |
| `data360_get_supported_chart_types` | List supported chart types |
| `data360_get_data_api_url` | Build a direct Data360 data API URL |

## Available Resources

| Resource | Role |
|---|---|
| `data360://system-prompt` | **Required** — tool workflow and reasoning guidance |
| `data360://context` | **Recommended** — current date/year |
| `data360://agent-recipe` | LangGraph / host integration recipe |
| `data360://k360-narrative-style` | Optional narrative formatting contract |
| `data360://databases` | Database list |
| `data360://codelists` | Code reference |
| `data360://metadata-fields` | Field routing map |
| `data360://data-filters` | Filter usage guidance |
| `data360://data-schema` | Column definitions |
| `data360://search-usage` | Search examples |

## Available Databases

The server supports all databases on the Data360 Platform, including:

- **WB_WDI** — World Development Indicators
- **WB_SSGD** — Social Sustainability and Global Database
- **WB_POVERTY** — Poverty and inequality indicators
- **IPC_IPC** — International Poverty Comparison
- And many more accessible via `data360_list_indicators` or `data360://databases`

## Agent Integration

Load `data360://system-prompt` and `data360://context` into your system message. Optionally fetch MCP prompts (`indicator_search`, `country_data`, `gate_classifier`, etc.) for specific user turns.

See the [Connect your agent](https://worldbank.github.io/data360-mcp#connect) section on the project site for Cursor, Claude Desktop, LangGraph, and custom client setup.

## Development

For local development setup, testing, and architecture details, see:
- [DEVELOPMENT.md](https://github.com/worldbank/data360-mcp/blob/dev/DEVELOPMENT.md)
- [docs/architecture-data360-mcp.md](https://github.com/worldbank/data360-mcp/blob/dev/docs/architecture-data360-mcp.md)
- [docs/mcp-apps-implementation-notes.md](https://github.com/worldbank/data360-mcp/blob/dev/docs/mcp-apps-implementation-notes.md)

## Contact

**AI for Data - Data for AI Team** ([ai4data@worldbank.org](mailto:ai4data@worldbank.org))
Development Data Group / Office of the World Bank Group Chief Statistician
World Bank Group

## License

This project is licensed under the MIT License together with the World Bank IGO Rider.
The Rider is purely procedural: it reserves all privileges and immunities enjoyed by the
World Bank, without adding restrictions to the MIT permissions. Please review both files
before using, distributing or contributing.

See [LICENSE](https://github.com/worldbank/data360-mcp/blob/dev/LICENSE) and [WB-IGO-RIDER.md](https://github.com/worldbank/data360-mcp/blob/dev/WB-IGO-RIDER.md).
