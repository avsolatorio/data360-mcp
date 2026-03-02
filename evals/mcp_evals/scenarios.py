"""Hand-written test scenarios for MCP server evaluation.

Scenarios test whether an LLM selects the right MCP tools given a query.
They are derived from the canonical operating loop in the system prompt
(see src/data360/mcp_server/prompts.py).

## Tool Reference (9 tools)
    data360_search_indicators    – Find indicators by keyword + optional country
    data360_find_codelist_value  – Resolve names → codes (country, unit, sex, …)
    data360_get_disaggregation   – Check available years, countries, dimensions
    data360_get_data             – Fetch indicator values (requires REF_AREA filter)
    data360_get_metadata         – Fetch methodology, limitations, definition, …
    data360_get_viz_spec         – Generate chart (fetches data internally)
    data360_get_supported_chart_types – List available chart types
    data360_get_data_api_url     – [LOW-LEVEL] Build a data API URL
    data360_list_indicators      – List all indicator IDs for a database

## Canonical Sequences (from system prompt)
    Data retrieval : search → [find_codelist] → get_data(REF_AREA=…)
    Visualization  : search → get_viz_spec   (get_viz_spec fetches data internally)
    Metadata       : search → get_metadata(select_fields=[…])
    Codelist       : find_codelist_value
    Disaggregation : search → get_disaggregation
    Chart types    : get_supported_chart_types

## How to Add a Scenario
    1. Pick a category (or create a new one).
    2. Copy an existing dict and update `input`, `expected_tools`, and `tags`.
    3. `expected_tools` lists the *minimum required* tool names (order-independent).
    4. Run: `uv run deepeval test run evals/mcp_evals/test_single_turn.py -k "<substring>" -v`
"""

# ---------------------------------------------------------------------------
# Single-Turn Scenarios
# ---------------------------------------------------------------------------
# Each dict has:
#   input          – The user query (clear, unambiguous, specific)
#   expected_tools – Minimum set of tools the LLM should call (order-independent)
#   tags           – Category labels for filtering / grouping results

SINGLE_TURN_SCENARIOS: list[dict] = [
    # ── Data Retrieval ────────────────────────────────────────────────
    # Canonical: search_indicators(required_country=…) → get_data(REF_AREA=…)
    {
        "input": "What is the GDP per capita in Kenya?",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_data",
        ],
        "tags": ["data_retrieval"],
    },
    {
        "input": "Show me the unemployment rate in Nigeria from 2015 to 2023",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_data",
        ],
        "tags": ["data_retrieval"],
    },
    {
        "input": "What is the life expectancy at birth in Japan?",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_data",
        ],
        "tags": ["data_retrieval"],
    },
    {
        "input": "What is the poverty rate in Uganda broken down by sex?",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_data",
        ],
        "tags": ["data_retrieval"],
    },
    {
        "input": "What was the infant mortality rate in Brazil in 2020?",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_data",
        ],
        "tags": ["data_retrieval"],
    },
    {
        "input": "Get the access to electricity percentage for India in 2022",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_data",
        ],
        "tags": ["data_retrieval"],
    },
    {
        "input": "What is the life expectancy at birth in Brazil in 2020?",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_data",
        ],
        "tags": ["data_retrieval"],
    },

    # ── Visualization ─────────────────────────────────────────────────
    # Canonical: search_indicators → get_viz_spec
    # NOTE: get_viz_spec fetches data internally – do NOT expect get_data.
    {
        "input": "Create a line chart of population growth in China from 2000 to 2020",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_viz_spec",
        ],
        "tags": ["visualization"],
    },
    {
        "input": "Show me a bar chart of GDP for Kenya and Tanzania",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_viz_spec",
        ],
        "tags": ["visualization"],
    },
    {
        "input": "Generate an area chart of infant mortality in Brazil from 1990 to 2020",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_viz_spec",
        ],
        "tags": ["visualization"],
    },
    {
        "input": "Create a line chart comparing life expectancy in Japan and Germany from 2000 to 2020",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_viz_spec",
        ],
        "tags": ["visualization"],
    },

    # ── Codelist Lookup ───────────────────────────────────────────────
    # Canonical: find_codelist_value (standalone, no other tools needed)
    {
        "input": "What is the 3-letter country code for Tanzania?",
        "expected_tools": [
            "data360_find_codelist_value",
        ],
        "tags": ["codelist"],
    },
    {
        "input": "Find the country codes for Kenya, Uganda, and Nigeria",
        "expected_tools": [
            "data360_find_codelist_value",
        ],
        "tags": ["codelist"],
    },
    {
        "input": "What country does the code BRA represent?",
        "expected_tools": [
            "data360_find_codelist_value",
        ],
        "tags": ["codelist"],
    },
    {
        "input": "Look up the country codes for Mexico and South Africa",
        "expected_tools": [
            "data360_find_codelist_value",
        ],
        "tags": ["codelist"],
    },

    # ── Metadata ──────────────────────────────────────────────────────
    # Canonical: search → get_metadata(select_fields=[…])
    {
        "input": "What methodology is used for the Human Development Index?",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_metadata",
        ],
        "tags": ["metadata"],
    },
    {
        "input": "What are the limitations of the poverty headcount ratio indicator?",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_metadata",
        ],
        "tags": ["metadata"],
    },
    {
        "input": "What is the methodology for the infant mortality rate indicator?",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_metadata",
        ],
        "tags": ["metadata"],
    },
    {
        "input": "Explain the definition and data sources for the access to electricity indicator",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_metadata",
        ],
        "tags": ["metadata"],
    },

    # ── Disaggregation ────────────────────────────────────────────────
    # Canonical: search → get_disaggregation
    {
        "input": "What disaggregation options are available for the access to electricity indicator?",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_disaggregation",
        ],
        "tags": ["disaggregation"],
    },
    {
        "input": "Which years of data are available for life expectancy at birth in the WB_WDI database?",
        "expected_tools": [
            "data360_search_indicators",
            "data360_get_disaggregation",
        ],
        "tags": ["disaggregation"],
    },

    # ── Chart Types ───────────────────────────────────────────────────
    # Canonical: get_supported_chart_types (standalone)
    {
        "input": "What chart types can I create with the visualization system?",
        "expected_tools": [
            "data360_get_supported_chart_types",
        ],
        "tags": ["chart_types"],
    },
]
