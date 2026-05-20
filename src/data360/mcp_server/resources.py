"""Resources for the Data360 MCP Server.

These resources provide static context to help LLMs understand the Data360 system.
Includes ``data360://agent-recipe`` for host integrators (LangGraph / data360-mcp-agent).
"""

import json
from datetime import datetime

from data360.providers import get_database_mapping

from ._server_definition import mcp
from .agent_recipe import AGENT_RECIPE_MARKDOWN

# System prompt with chain-of-thought guidance for chatbot integration
from .prompts import SYSTEM_PROMPT

CODELISTS = {
    "auto_resolved": {
        "description": (
            "The pipeline auto-resolves these dimensions from the extdataportal codelist. "
            "series_labels is NOT required for these dimensions."
        ),
        "source": "https://extdataportal.worldbank.org/api/data360/metadata/codelist",
        "dimensions": {
            "COMP_BREAKDOWN_1": "5 191 indicator-subtype codes (e.g. WGI_EST, IPC_IPC_PHASE3, WEF_TTDI_RNK)",
            "COMP_BREAKDOWN_2": "Same pool as COMP_BREAKDOWN_1",
            "UNIT_MEASURE": "769 unit codes auto-resolved in Y-axis labels and subtitles",
            "SEX": "7 codes: F=Female, M=Male, _T=Total, _O=Other, _U=Unknown, _Z=Not applicable",
            "AGE": "173 codes: _T=All ages, Y15T24=15-24 years, Y_GE25=25+ years, etc.",
            "URBANISATION": "16 codes: URB=Urban area, RUR=Rural area, CITY=City, VILL=Village, etc.",
            "FREQ": "34 codes: A=Annual, M=Monthly, Q=Quarterly, etc.",
        },
    },
    "manual_override": {
        "description": (
            "Provide series_labels only to shorten or rename auto-resolved labels, "
            "e.g. to show 'Estimate' instead of 'Governance estimate (approx. -2.5 to +2.5)'."
        ),
        "example": {"WGI_EST": "Estimate", "WGI_SC": "Score", "WGI_SE": "Std. Error"},
    },
    "geographic": {
        "description": "REF_AREA groups resolved via GroupHierarchyManager (FMR H_REF_AREA_GROUPS)",
        "individual_countries": "532 codes — resolved automatically to country names",
        "groups": "147 group codes (REGION, INCOME, LENDING, CONTINENT) — use expand_country_group",
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
        "REF_AREA": {
            "description": "Country code(s). Use comma-separated for multiple.",
            "example": "KEN,TZA",
        },
        "SEX": {"values": ["F", "M", "_T", "_O", "_U", "_Z"]},
        "AGE": {
            "description": "173 age codes — common ones below; use get_disaggregation for indicator-specific values",
            "common_values": ["_T", "Y15T24", "Y15T29", "Y30T59", "Y_GE25", "Y_GE60", "Y18T65"],
        },
        "URBANISATION": {
            "values": ["_T", "URB", "RUR", "CITY", "VILL", "DTOW", "TSUB", "STOW", "SUBU", "SURB", "LURB", "_O", "_Z"],
        },
    },
    "excluded_filters": {"FREQ": "DO NOT USE - breaks queries"},
    "important": "Check TIME_PERIOD in disaggregation for actual available years (may have gaps)",
}


DATA_SCHEMA = {
    "description": "Data rows are prefiltered to only include relevant fields. Always present: 5 core fields. Conditionally present: disaggregation fields when their values are non-trivial.",
    "core_fields": {
        "obs_value": "The numeric data value.",
        "time_period": "Date or year of the observation (e.g., '2023', '2024-07-01').",
        "ref_area": "Country or region code (e.g., 'KEN').",
        "unit_measure": "Unit of measurement (e.g., 'PT', 'USD_K_2015', 'PS').",
        "claim_id": "Verification hash for data provenance.",
    },
    "conditional_fields": {
        "description": "Included only when values carry real disaggregation (not _T total or _Z not-applicable).",
        "sex": "Gender breakdown ('F', 'M'). Present in WB_HCP, WB_SSGD, WB_GS.",
        "age": "Age group ('Y15T24', 'Y18T65', etc.). Present in WB_SSGD, OECD_IDD.",
        "urbanisation": "Urban/Rural ('URB', 'RUR'). Present in WB_SSGD.",
        "comp_breakdown_1": "Indicator subtype (e.g., IPC phase period, OECD indicator type, WEF rank/value/score).",
        "comp_breakdown_2": "Secondary breakdown (e.g., IPC phase level, OECD income definition).",
    },
    "visualization_guidance": "When calling get_viz_spec(relevant_fields=...), prioritize 'time_period' and 'obs_value'. Include 'ref_area' or dimensions like 'sex' only for comparison/grouping.",
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

K360_NARRATIVE_STYLE = {
    "sections": ["Data", "Analysis", "Note", "Sources"],
    "required_behavior": [
        "Ground every statement in tool evidence or content packet fields.",
        "Use concise markdown suitable for analyst and policy audiences.",
        "When chart outputs exist, describe what each chart conveys in 1-2 sentences.",
        "If no data is available, clearly state the gap and suggest a narrower follow-up query.",
    ],
    "optional_claim_tags": {
        "enabled_by": "include_claim_tags=true",
        "format": "<claim id=\"short-id\">numeric statement</claim>",
    },
}


@mcp.resource("data360://system-prompt")
async def system_prompt_resource() -> str:
    """System prompt with chain-of-thought guidance for chatbot integration."""
    return SYSTEM_PROMPT


@mcp.resource("data360://agent-recipe")
async def agent_recipe_resource() -> str:
    """How to compose MCP resources + named prompts for LangGraph / ``data360-mcp-agent``."""
    return AGENT_RECIPE_MARKDOWN


@mcp.resource("data360://context")
async def context_resource() -> str:
    """Runtime context including current date. Read this to know today's date."""
    return json.dumps(
        {
            "current_date": datetime.now().strftime("%Y-%m-%d"),
            "current_year": datetime.now().year,
            "note": "Use current_year to calculate 'last N years' queries",
        },
        indent=2,
    )


@mcp.resource("data360://databases")
async def databases_resource() -> str:
    """List of available Data360 databases."""
    db_mapping = await get_database_mapping()
    formatted = {"databases": [{"id": k, "name": v} for k, v in db_mapping.items()]}
    return json.dumps(formatted, indent=2)


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


@mcp.resource("data360://data-schema")
async def data_schema_resource() -> str:
    """Standard data schema and column definitions for visualization."""
    return json.dumps(DATA_SCHEMA, indent=2)


@mcp.resource("data360://search-usage")
async def search_usage_resource() -> str:
    """Search tool usage guidance."""
    return json.dumps(SEARCH_USAGE, indent=2)


@mcp.resource("data360://k360-narrative-style")
async def k360_narrative_style_resource() -> str:
    """Narrative formatting contract for K360 staged agent hosts."""
    return json.dumps(K360_NARRATIVE_STYLE, indent=2)
