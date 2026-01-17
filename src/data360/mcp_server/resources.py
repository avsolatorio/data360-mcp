"""Resources for the Data360 MCP Server.

These resources provide static context to help LLMs understand the Data360 system.
"""

import json
from datetime import datetime

from ._server_definition import mcp


# System prompt with chain-of-thought guidance for chatbot integration
SYSTEM_PROMPT = """## Data360 Assistant Instructions

You help users find and analyze World Bank Data360 indicators.

### CRITICAL: CHAIN OF THOUGHT REASONING

For EVERY step, you must explicitly reason about what you are doing and why.
Format your thought process as:
"Thought: The user wants [goal]. To get there, I first need to [action] because [reason]."

**IMPORTANT**: 
1. If you are going to call a tool, you MUST provide a "Thought:" first explaining why.
2. If you are just thinking but not calling a tool yet, still use "Thought:".
3. When you have gathered all information and are providing the FINAL ANSWER to the user, specificy "Answer:" and do NOT use "Thought:".

### Workflow

**Step 1: Search for indicators**
- Thought: "User is asking for 'unemployment'. I need to find the correct indicator ID to query the database."
- Use data360_search_indicators(query="...", required_country="...")
- If user mentions a country, pass it as required_country
- Results are already sorted: covers_country=true first, then by latest_data
- Each indicator shows: name, definition_short, periodicity, latest_data, time_period_range, covers_country, dimensions
- Review `dimensions` to ensure the indicator supports requested breakdowns (e.g. SEX).
- Check `time_period_range` for data coverage (e.g. "1990-2024"). Prioritize indicators with longer history if needed.
- Select the most appropriate indicator based on name/definition. DO NOT blindly pick the first if another fits better.
- DO NOT call get_disaggregation - search already has the metadata

**Step 2: Get data**
- Thought: "I have the indicator ID 'SL.UEM.TOTL.ZS'. Now I need to fetch the actual data values for Kenya for the last 5 years."
- Use data360_get_data with:
  - database_id and indicator_id from search result
  - REF_AREA: use data360_find_codelist_value("REF_AREA", "country name") to get code
  - timePeriodFrom/timePeriodTo: year range (use current_date from context)
  - SEX, AGE, URBANISATION: 
    - Default: returns Total (_T) only to save tokens.
    - To get breakdowns: request specific values (e.g. SEX="F"). Do not omit filters if you need non-Total data.
- DO NOT use FREQ filter - it breaks queries

### When User Asks About Methodology/Definition

- Use data360_get_metadata with select_fields=["methodology"] for specific info
- Map: "how calculated" → methodology, "what does it measure" → statistical_concept

### Rules
- Select the best fitting indicator based on dimensions and definition.
- Use current_date from context for "last year", "last N years"
- Be explicit about data gaps: "You asked for [year], but latest available is [actual_year]"
"""


DATABASES = {
    "databases": [
        {"id": "WB_WDI", "name": "World Development Indicators"},
        {"id": "IPC_IPC", "name": "IPC Acute Food Insecurity"},
        {"id": "WB_SSGD", "name": "Social Sustainability Global Database"},
        {"id": "WB_POVERTY", "name": "Poverty and Inequality Platform"},
    ],
    "note": "Use search to find indicators within these databases",
}


CODELISTS = {
    "global_codelists": {
        "description": "Available via find_codelist_value tool",
        "REF_AREA": "Countries/regions (284 items) - use find_codelist_value('REF_AREA', 'Kenya')",
        "UNIT_MEASURE": "Measurement units (42 items)",
    },
    "indicator_level_codelists": {
        "description": "Available per indicator via get_disaggregation",
        "fields": ["FREQ", "SEX", "AGE", "URBANISATION", "TIME_PERIOD"],
        "example": "get_disaggregation('WB_WDI', 'WB_WDI_SP_POP_TOTL') returns valid values",
    },
    "static_mappings": {
        "SEX": {"F": "Female", "M": "Male", "_T": "Total"},
        "URBANISATION": {"URB": "Urban", "RUR": "Rural", "_T": "Total"},
        "FREQ": {"A": "Annual", "M": "Monthly", "Q": "Quarterly"},
    },
}


METADATA_FIELDS = {
    "fields": {
        "methodology": {
            "description": "How the indicator is calculated/measured",
            "use_when": ["how is it calculated", "calculation method", "methodology"],
        },
        "statistical_concept": {
            "description": "Statistical definition and conceptual framework",
            "use_when": ["statistical concept", "what does it measure", "definition"],
        },
        "definition_long": {
            "description": "Full description of the indicator",
            "use_when": ["what is", "describe", "explanation"],
        },
        "limitation": {
            "description": "Known data limitations and caveats",
            "use_when": ["limitations", "caveats", "data quality", "issues"],
        },
        "relevance": {
            "description": "Policy relevance and why this indicator matters",
            "use_when": ["why important", "relevance", "policy implications"],
        },
        "aggregation_method": {
            "description": "How values are aggregated (Sum, Average, etc.)",
            "use_when": ["aggregation", "how combined", "sum or average"],
        },
        "periodicity": {
            "description": "Data frequency (Annual, Monthly, etc.)",
            "use_when": ["frequency", "how often", "periodicity"],
        },
        "time_periods": {
            "description": "Nominal time range (may have gaps)",
            "use_when": ["time range", "years available", "coverage"],
            "note": "Call get_disaggregation for actual available years",
        },
        "ref_country": {
            "description": "List of countries with data",
            "use_when": ["countries", "coverage", "available for"],
        },
        "sources_note": {
            "description": "Information about data sources",
            "use_when": ["source", "where from", "data provider"],
        },
    }
}


DATA_FILTERS = {
    "workflow": "Call get_disaggregation first to see available values for each filter",
    "supported_filters": {
        "timePeriodFrom": {"description": "Start year", "example": "2020"},
        "timePeriodTo": {"description": "End year", "example": "2023"},
        "REF_AREA": {"description": "Country code from disaggregation", "example": "KEN"},
        "SEX": {"values": ["F", "M", "_T"]},
        "AGE": {"values": ["Y15T24", "Y15T29", "Y30T59", "Y_GE25", "Y_GE60", "_T"]},
        "URBANISATION": {"values": ["URB", "RUR", "_T"]},
    },
    "excluded_filters": {"FREQ": "DO NOT USE - breaks queries"},
    "important": "Check TIME_PERIOD in disaggregation for actual available years (may have gaps)",
}


SEARCH_USAGE = {
    "basic_search": {
        "example": "data360_search_indicators(query='poverty', limit=10)",
        "note": "Uses default select_fields",
    },
    "enriched_search": {
        "example": "data360_search_indicators(query='poverty', limit=5, select_fields=['idno', 'name', 'database_id', 'definition_long', 'periodicity', 'time_periods', 'dimensions'])",
        "note": "Use when LLM needs to pick best indicator",
    },
    "indicator_selection_workflow": [
        "1. Use enriched search with select_fields for extra coverage info",
        "2. Call get_disaggregation to check TIME_PERIOD and REF_AREA",
        "3. Pick indicator based on coverage, time range, and relevance",
    ],
    "warning": "DO NOT use odata_options - it is deprecated",
}


@mcp.resource("data360://system-prompt")
async def system_prompt_resource() -> str:
    """System prompt with chain-of-thought guidance for chatbot integration."""
    return SYSTEM_PROMPT


@mcp.resource("data360://context")
async def context_resource() -> str:
    """Runtime context including current date. Read this to know today's date."""
    return json.dumps({
        "current_date": datetime.now().strftime("%Y-%m-%d"),
        "current_year": datetime.now().year,
        "note": "Use current_year to calculate 'last N years' queries"
    }, indent=2)


@mcp.resource("data360://databases")
async def databases_resource() -> str:
    """List of available Data360 databases."""
    return json.dumps(DATABASES, indent=2)


@mcp.resource("data360://codelists")
async def codelists_resource() -> str:
    """Codelist reference information (global and indicator-level)."""
    return json.dumps(CODELISTS, indent=2)


@mcp.resource("data360://metadata-fields")
async def metadata_fields_resource() -> str:
    """Metadata field mapping for smart routing based on user questions."""
    return json.dumps(METADATA_FIELDS, indent=2)


@mcp.resource("data360://data-filters")
async def data_filters_resource() -> str:
    """Available data filters and usage guidance."""
    return json.dumps(DATA_FILTERS, indent=2)


@mcp.resource("data360://search-usage")
async def search_usage_resource() -> str:
    """Search tool usage guidance."""
    return json.dumps(SEARCH_USAGE, indent=2)
