# Data360 MCP Server

A Model Context Protocol (MCP) library and server for accessing and searching the World Bank Data360 Platform. This project provides both a reusable library and a ready-to-use MCP server implementation for integrating Data360 data into AI applications.

## Overview

Data360 MCP Server enables AI assistants and applications to search, retrieve, and work with data from the World Bank's Data360 platform. It implements the MCP specification to provide a standardized interface for accessing Data360's extensive collection of development indicators.

### What is Data360?

The World Bank's Data360 Platform is a comprehensive data platform that provides access to thousands of development indicators from the World Bank. It is a platform for data discovery, exploration, and analysis.

## Features

- 🔍 **Powerful Search**: Semantic search across Data360 data with relevance scoring
- 📊 **Structured Responses**: Type-safe response models with Pydantic validation
- 🛡️ **Error Handling**: Comprehensive error handling with graceful degradation
- 🚀 **FastMCP Integration**: Built on FastMCP for high-performance MCP server implementation
- 🔧 **Configurable**: Environment-based configuration for API endpoints and settings
- 📦 **Modular Design**: Separate library and server packages for flexibility


## Project Structure

This repository contains two main packages:

- **`data360-mcp`**: Core library providing Data360 MCP functionality. This library implements the MCP specification for the Data360 Platform that can be used to build MCP servers. Tools, resources, and prompts are implemented in this library.
- **`data360-mcp-server`**: MCP server implementation that exposes the MCP tools, resources, and prompts defined in the `data360-mcp` library. This server is implemented using FastMCP.

## Installation

### Prerequisites

- Python 3.10 or higher
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Using uv (Recommended)

```bash
# Clone the repository
git clone <repository-url>
cd data360-mcp

# Install dependencies
uv sync

# Install the packages
uv pip install -e data360-mcp
uv pip install -e data360-mcp-server
```

### Using pip

```bash
# Install the library
pip install -e data360-mcp/

# Install the server
pip install -e data360-mcp-server/
```

## Configuration

The server requires configuration via environment variables. Create a `.env` file or set the following:

```bash
# Required: Base URL for the Data360 API
DATA360_API_BASE_URL=https://data360api.worldbank.org
```

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATA360_API_BASE_URL` | Base URL for the Data360 API | Yes | - |

## Usage

### Running the MCP Server

#### Using the provided script:

```bash
./run_server.sh
```

#### Using uv:

```bash
uv run fastmcp run data360-mcp-server/src/data360_mcp_server/main.py:mcp --transport http --port 8021
```

#### Using Python directly:

```bash
python -m data360_mcp_server.main
```

The server will start on `http://localhost:8021` by default.

### Using the Library Directly

```python
import asyncio
from data360_mcp.data360 import api as data360_api

async def main():
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

The server exposes the following MCP tools:

### `data360_search`

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
# Run tests (when available)
uv run pytest
```

### Code Quality

The project uses:
- **ruff**: For linting and code formatting
- **pre-commit**: For git hooks

```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check .
```

### Project Structure

```
data360-mcp/
├── data360-mcp/              # Core library package
│   ├── src/
│   │   └── data360_mcp/
│   │       ├── data360/      # Data360 API client
│   │       │   ├── api.py   # API functions
│   │       │   ├── config.py # Configuration
│   │       │   └── models.py # Pydantic models
│   │       └── ...
│   └── pyproject.toml
├── data360-mcp-server/       # MCP server package
│   ├── src/
│   │   └── data360_mcp_server/
│   │       └── main.py      # FastMCP server implementation
│   └── pyproject.toml
├── run_server.sh            # Server startup script
└── pyproject.toml           # Workspace configuration
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
            "data360_search",
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
