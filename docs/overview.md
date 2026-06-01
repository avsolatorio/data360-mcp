# Data360 MCP Server

> **Project site:** The full documentation for this repository is published at **[https://worldbank.github.io/data360-mcp](https://worldbank.github.io/data360-mcp)** (`docs/index.html`). This file is a markdown overview for readers browsing the repo on GitHub.

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that gives LLM agents direct access to the World Bank's [Data360 Platform](https://data360.worldbank.org/).

## Overview

The Data360 MCP Server bridges the gap between Large Language Models and the World Bank's development data infrastructure. It allows AI agents to search, validate, and retrieve precise development indicators — covering topics such as GDP, poverty, gender equality, health, and climate — without hallucinating data values.

**Who is this for?**
- Developers building AI agents that need reliable access to World Bank development data
- Researchers and analysts who want to integrate World Bank data into LLM workflows
- Teams building data-driven applications on top of the MCP ecosystem

For a complete guide — including example questions, charts, architecture, MCP Apps, and connection steps — see the [project site](https://worldbank.github.io/data360-mcp).

## Key Features

- **Indicator discovery** — search hundreds of indicators with metadata and country coverage checks
- **Rich metadata** — retrieve methodology, definitions, limitations, and statistical concepts
- **Time-series data** — query historical data with filters for country, time period, sex, age, and urbanization
- **LLM resources** — built-in system prompts, codelists, and chain-of-thought reasoning guidance
- **Agent-safe design** — composable tools with guardrails that prevent common LLM data errors

## Getting Started

See the [README](https://github.com/worldbank/data360-mcp#readme) for full installation and usage instructions.

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
| `data360_search_indicators` | Search indicators with country coverage check |
| `data360_get_data` | Fetch time-series data with filters |
| `data360_get_metadata` | Get indicator methodology and definitions |
| `data360_get_disaggregation` | Check available filter values |
| `data360_find_codelist_value` | Resolve names to standard codes |
| `data360_list_indicators` | List all indicators in a database |
| `data360_get_viz_spec` | Generate Vega-Lite chart specs |
| `data360_get_supported_chart_types` | List supported chart types |

## Available Databases

The server supports all databases on the Data360 Platform, including:

- **WB_WDI** — World Development Indicators
- **WB_SSGD** — Social Sustainability and Global Database
- **WB_POVERTY** — Poverty and inequality indicators
- **IPC_IPC** — International Poverty Comparison
- And many more accessible via `data360_list_indicators`

## Agent Integration

For agent integration, retrieve the `data360://system-prompt` resource and include it in your system prompt. It provides:
- Chain-of-thought reasoning templates for data queries
- Step-by-step workflow guidance
- Filter do's and don'ts

See the [Connect your agent](https://worldbank.github.io/data360-mcp#connect) section on the project site for Cursor, Claude Desktop, LangGraph, and custom client setup.

## Development

For local development setup, testing, and architecture details, see:
- [DEVELOPMENT.md](https://github.com/worldbank/data360-mcp/blob/main/DEVELOPMENT.md)
- [docs/architecture-data360-mcp.md](https://github.com/worldbank/data360-mcp/blob/main/docs/architecture-data360-mcp.md)
- [docs/mcp-apps-implementation-notes.md](https://github.com/worldbank/data360-mcp/blob/main/docs/mcp-apps-implementation-notes.md)

## Contact

**AI for Data - Data for AI Team** ([ai4data@worldbank.org](mailto:ai4data@worldbank.org))
Development Data Group / Office of the World Bank Group Chief Statistician
World Bank Group

## License

This project is licensed under the MIT License together with the World Bank IGO Rider.
The Rider is purely procedural: it reserves all privileges and immunities enjoyed by the
World Bank, without adding restrictions to the MIT permissions. Please review both files
before using, distributing or contributing.

See [LICENSE](https://github.com/worldbank/data360-mcp/blob/main/LICENSE) and [WB-IGO-RIDER.md](https://github.com/worldbank/data360-mcp/blob/main/WB-IGO-RIDER.md).
