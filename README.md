# Data360 MCP

A small Python package + FastMCP server that exposes World Bank Data360 search/metadata/data endpoints via the Model Context Protocol (MCP).

## Overview

This repo provides:

- A Python client module (`data360.api`) for calling Data360 endpoints.
- An MCP server (`data360.mcp_server`) built on `fastmcp` that wraps those calls as MCP tools.

### What is Data360?

The World Bank's Data360 Platform is a comprehensive data platform that provides access to thousands of development indicators from the World Bank. It is a platform for data discovery, exploration, and analysis.

## Features

- **Search**: POST to Data360 `searchv2` and return typed results.
- **Metadata**: Fetch metadata and available disaggregation options.
- **Data**: Fetch indicator data (auto-paginates by `skip`).
- **MCP server**: Exposes the functions above as MCP tools over `streamable-http` (default).


## Project Structure

The package lives under `src/data360`:

- `src/data360/api.py`: async Data360 API client functions
- `src/data360/config.py`: `pydantic-settings` configuration (`DATA360_*` env vars)
- `src/data360/models.py`: Pydantic request/response models
- `src/data360/mcp_server/*`: FastMCP server definition + tool registration

## Library API

The library entrypoint is `data360.api`.

| Function | Description |
|---|---|
| `data360.api.search(...)` | Search for indicators/series via `searchv2`. |
| `data360.api.get_metadata(indicator_id, database_id, ...)` | Fetch series metadata and disaggregation options. |
| `data360.api.get_data(database_id, indicator_id, disaggregation_filters=None)` | Fetch indicator observations (auto-paginates). |


## Installation

### Prerequisites

- Python 3.10 or higher
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Using `uv` (recommended)

```bash
# Clone the repository
git clone <repository-url>
cd data360-mcp

# Install dependencies
uv sync

# Install editable
uv pip install -e .
```

### Using pip

```bash
pip install -e .
```

## Configuration

Configuration is read via `pydantic-settings` with the prefix `DATA360_`.
Create a `.env` file (see `.env.example`) or export env vars.

```bash
# Required
DATA360_API_BASE_URL=https://data360api.worldbank.org
```

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATA360_API_BASE_URL` | Base URL for the Data360 API | Yes | - |
| `DATA360_SEARCH_URL` | Override search endpoint URL | No | `${DATA360_API_BASE_URL}/data360/searchv2` |
| `DATA360_METADATA_URL` | Override metadata endpoint URL | No | `${DATA360_API_BASE_URL}/data360/metadata` |
| `DATA360_DISAGGREGATION_URL` | Override disaggregation endpoint URL | No | `${DATA360_API_BASE_URL}/data360/disaggregation` |
| `DATA360_DATA_URL` | Override data endpoint URL | No | `${DATA360_API_BASE_URL}/data360/data` |
| `DATA360_CODELIST_API_BASE_URL` | Override codelist base URL | No | `${DATA360_API_BASE_URL}/data360/metadata/codelist` |

## Usage

### Running the MCP Server

#### Using the provided script

```bash
./run_server.sh
```

#### Using `poe` (task runner)

The repo defines a Poetry-like task via `poethepoet`:

```bash
uv run poe serve
uv run poe serve --transport streamable-http --port 8021
```

#### Using `uv` directly

```bash
uv run fastmcp run src/data360/server.py --transport streamable-http --port 8021
```

#### Using Python directly

```bash
uv run python -m data360.mcp_server --transport streamable-http --port 8021
```

The server binds on port `8021` by default. With `streamable-http`, clients typically connect at `http://localhost:8021/mcp`.

### Using the Library Directly

```python
import asyncio
import os

from data360 import api as data360_api

async def main():
  # Required configuration
  # os.environ["DATA360_API_BASE_URL"] = "https://data360api.worldbank.org"

    # Simple search
    result = await data360_api.search(
        query="food security",
        n_results=10
    )

    if result.error:
        print(f"Error: {result.error}")
    else:
        print(f"Found {result.count} results")
        for item in result.items or []:
            print(f"- {item.series_description.name} ({item.series_description.idno})")

asyncio.run(main())
```

### Advanced Search with OData Filters

This will be abstracted away by the MCP tools and resources.

```python
result = await data360_api.search(
    query="food security",
    n_results=20,
    filter="type eq 'indicator'",
    orderby="series_description/name",
    select="series_description/idno, series_description/name, series_description/database_id",
    skip=0,
    count=True
)
```

## MCP Tools

The server exposes these tools (see `src/data360/mcp_server/tools.py`):

### `data360_search_indicators`

Search for Data360 indicators using the World Bank Data360 API.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search query string to find relevant data series |
| `n_results` | integer | No | 10 | Number of top results to return (1-50) |
| `filter` | string | No | None | OData filter expression (e.g., `"type eq 'indicator'"`) |
| `orderby` | string | No | None | OData orderby expression (e.g., `"series_description/name"`) |
| `select` | string | No | None | OData select expression (e.g., `"series_description/idno, series_description/name"`) |
| `skip` | integer | No | 0 | Number of results to skip for pagination |
| `count` | boolean | No | False | Whether to include total count in response |

**Example Request:**

```json
{
  "query": "food security",
  "n_results": 20,
  "filter": "type eq 'indicator'",
  "orderby": "series_description/name",
  "select": "series_description/idno, series_description/name, series_description/database_id"
}
```

**Example Response:**

```json
{
  "items": [
    {
      "@search.score": 14.934074,
      "series_description": {
        "idno": "UN_SDG_SN_ITK_DEFC",
        "name": "2.1.1 Prevalence of undernourishment",
        "database_id": "UN_SDG"
      }
    }
  ],
  "count": 1,
  "error": null
}
```

## OData Query Syntax

The search endpoint supports OData query syntax for advanced filtering and selection:

### Filter Examples

```python
# Filter by type
filter="type eq 'indicator'"

# Filter by topic
filter="series_description/topics/any(t: t/name eq 'Health') and type eq 'indicator'"

# Multiple conditions
filter="type eq 'indicator' and series_description/database_id eq 'WB_WDI'"
```

### Order By Examples

```python
# Sort by name
orderby="series_description/name"

# Sort by name descending
orderby="series_description/name desc"

# Multiple sort fields
orderby="series_description/database_id, series_description/name"
```

### Select Examples

```python
# Select specific fields
select="series_description/idno, series_description/name, series_description/database_id"

# Select all fields from series_description
select="series_description/*"
```

## Development

### Setting Up Development Environment

```bash
# Clone the repository
git clone <repository-url>
cd data360-mcp

# Install development dependencies
uv sync --dev

# Install pre-commit hooks
pre-commit install
```

### Running Tests

```bash
# There are currently no repo tests.
# If you add tests, run them like:
# uv run pytest
```

### Code Quality

The project uses:
- **ruff**: For linting and code formatting
- **pre-commit**: For git hooks

```bash
# Format
uv run ruff format .

# Lint
uv run ruff check .

# Type check
uv run pyright
```

### Repository Layout

```
.
├── src/
│   └── data360/
│       ├── api.py
│       ├── config.py
│       ├── models.py
│       ├── server.py
│       └── mcp_server/
│           ├── __main__.py
│           ├── _server_definition.py
│           ├── tools.py
│           ├── resources.py
│           └── prompts.py
├── run_server.sh
├── pyproject.toml
└── notebooks/example.ipynb
```

## Integration Examples

### With LangChain MCP Adapters

```python
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "data360": {
    "transport": "streamable_http",
        "url": "http://localhost:8021/mcp",
    }
})

async def search_indicators():
    async with client:
        tools = await client.get_tools()
        result = await client.call_tool(
          "data360_search_indicators",
            {
                "query": "poverty",
                "n_results": 10
            }
        )
        print(result)

asyncio.run(search_indicators())
```

<!-- ## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request -->

## License

See the [LICENSE](LICENSE) file for details.

## Support

For issues, questions, or contributions, please open an issue on the GitHub repository.

## Acknowledgments

- Built with [FastMCP](https://github.com/jlowin/fastmcp)
- Uses the [Model Context Protocol](https://modelcontextprotocol.io/) specification
- Integrates with the World Bank Data360 API
