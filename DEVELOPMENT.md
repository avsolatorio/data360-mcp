# Development Guide

This guide is for developers contributing to the `data360-mcp` package or using it as a Python library directly.

## Setting Up Development Environment

We use `uv` for dependency management.

```bash
# Clone the repository
git clone <repository-url>
cd data360-mcp

# Install development dependencies
uv sync --dev

# Install pre-commit hooks
pre-commit install
```

## Project Structure

The package lives under `src/data360`:

```
src/data360/
├── api.py              # Async Data360 API client functions
├── config.py           # pydantic-settings configuration (MCP_CHARTS_API_URL for storing viz specs)
├── models.py           # Pydantic request/response models
├── providers.py        # Codelist management (REF_AREA, SEX, AGE, etc.)
└── mcp_server/
    ├── tools.py        # MCP tool registrations
    ├── resources.py    # MCP resources (system-prompt, codelists, etc.)
    └── prompts.py      # MCP workflow prompts
```

## Running Tests

```bash
# Run tests with pytest
uv run pytest

# Run tests with coverage
uv run pytest --cov=src/data360
```

## Code Quality

```bash
# Format
uv run ruff format .

# Lint
uv run ruff check .

# Type check
uv run pyright
```

## Third-Party Licenses

To regenerate `THIRD_PARTY_LICENSES.md`:

```bash
uv run poe licenses
```

## Using the Python Library Directly

```python
import asyncio
from data360 import api as data360_api

async def main():
    # Basic search
    result = await data360_api.search(query="unemployment", limit=5)

    # Enriched search with specific fields
    result = await data360_api.search(
        query="poverty",
        limit=5,
        select_fields=["idno", "name", "database_id", "periodicity"]
    )

    # Check available filters for an indicator
    disagg = await data360_api.get_disaggregation(
        database_id="WB_SSGD",
        indicator_id="WB_SSGD_UNEMPLOYMENT"
    )
    print(f"Available years: {disagg['dimensions']}")

    # Get specific metadata fields
    metadata = await data360_api.get_metadata(
        database_id="WB_WDI",
        indicator_id="WB_WDI_SP_POP_TOTL",
        select_fields=["methodology", "statistical_concept"]
    )

    # Fetch data with filters
    data = await data360_api.get_data(
        database_id="WB_WDI",
        indicator_id="WB_WDI_SP_POP_TOTL",
        disaggregation_filters={"REF_AREA": "KEN"},
        start_year=2018,
        end_year=2022
    )

asyncio.run(main())
```

## Library API Reference

| Function                                                             | Description                                                |
| -------------------------------------------------------------------- | ---------------------------------------------------------- |
| `search(query, limit, select_fields)`                                | Search for indicators with optional field selection        |
| `get_metadata(database_id, indicator_id, select_fields)`             | Get indicator metadata with optional field selection       |
| `get_disaggregation(database_id, indicator_id)`                      | Get available filter values (countries, years, dimensions) |
| `get_data(database_id, indicator_id, filters, start_year, end_year)` | Fetch indicator data                                       |
| `get_indicators(database_id)`                                        | List all indicators for a database                         |

### Key Parameters

#### `select_fields` for search
Available fields: `idno`, `name`, `database_id`, `definition_long`, `periodicity`, `time_periods`, `dimensions`, `topics`, `ref_country`

#### `select_fields` for get_metadata
Available fields: `methodology`, `statistical_concept`, `definition_long`, `limitation`, `relevance`, `aggregation_method`, `periodicity`, `time_periods`, `ref_country`, `sources_note`

#### Filter parameters for get_data
- `REF_AREA`: Country code (e.g., "KEN")
- `SEX`: "F", "M", "_T"
- `AGE`: "Y15T24", "Y_GE25", etc.
- `URBANISATION`: "URB", "RUR", "_T"

> **Warning**: Do NOT use `FREQ` as a filter - it breaks queries.

## MCP Resources

When developing chatbot integrations, use the `data360://system-prompt` resource content as your base system prompt. It includes:
- Chain-of-thought reasoning templates
- Step-by-step workflow guidance
- Best practices for tool usage

## Optional: Charts API

When generating visualizations (`data360_get_viz_spec`), the server can store Vega-Lite specs in an external charts API instead of saving to `static/viz_specs/`. Set:

- **`MCP_CHARTS_API_URL`**: Full URL of the charts API endpoint (e.g. `https://dataexppythonapidev.aseqa.worldbank.org/api/v1/charts`). The server will POST the Vega-Lite spec as JSON. If unset, specs are saved locally under `static/viz_specs/`.

## Technical Findings & Limitations

### 1. OData Filtering Reliability
Native OData filters (specifically `contains` on text fields) often return incomplete or irrelevant results for search queries involving definitions.
- **Impact**: We cannot rely on OData for high-quality search.
- **Solution**: The `search` tool implements server-side logic to fetch broader results and enrich/rank them in application code.

### 2. Metadata vs. Data availability
The `dimensions` field in search results/metadata indicates *potential* breakdowns (e.g., `SEX`), but does **not guarantee** data exists for all values.
- **Example**: An indicator might list `SEX` as a dimension but only contain data for `_T` (Total).
- **Verification**: Use `get_disaggregation` to check *actual* available values for a specific indicator. It scans the data and returns only values present (e.g. `['F', '_T']` only, missing 'M').
