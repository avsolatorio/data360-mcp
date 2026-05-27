"""MCP Tools for the Data360 server.

Thin wrapper layer that registers API functions as MCP tools with optimized signatures,
concise docstrings to reduce token context bloat, and validation schemas.
"""

import json
from typing import Any, Literal

import pydantic_core
from fastmcp.tools.tool import Tool

from data360 import api as data360_api
from data360 import providers as data360_providers
from data360 import visualization as data360_viz

from ._server_definition import mcp
from .tool_spans import instrument_mcp_tool

# ---------------------------------------------------------------------------
# Serializer for aggregation tools
# ---------------------------------------------------------------------------


def _compact_aggregation_serializer(data: Any) -> str:
    """Compact serializer for aggregation tool responses.

    Calls ``to_compact()`` on the response model if available, producing a
    token-efficient JSON representation while preserving all PCN claim_ids
    for data provenance verification.
    """
    if hasattr(data, "to_compact"):
        return json.dumps(data.to_compact(), separators=(",", ":"))
    return pydantic_core.to_json(data, fallback=str).decode()


# ---------------------------------------------------------------------------
# Tool Wrapper Functions
# ---------------------------------------------------------------------------


async def _search_indicators(
    query: str | None = None,
    required_country: str | None = None,
    limit: int = 5,
    offset: int = 0,
    queries: list[str] | None = None,
    query_groups: list[dict[str, Any]] | None = None,
    result_layout: str = "merged",
    dedupe: bool = True,
    database: str | None = None,
) -> Any:
    """Search for Data360 indicators with enriched metadata for selection.

    Use when the user asks for data on a development topic (e.g. GDP, poverty, education).
    Default to using the single `query` parameter for any single topic/indicator search. Use the `queries` or `query_groups` parameters ONLY when the request involves multiple topics or scopes (2 or more).
    Provide exactly one of `query`, `queries`, or `query_groups`. One of these is strictly required.

    ### Parameter Selection Decision Tree (CRITICAL):
    1. **Exactly 1 Topic** (e.g., "life expectancy" or "mortality rate") for any number of countries → you MUST use the single `query` parameter + `required_country`. Do NOT use `queries` with only one element, as it will fail. Do NOT combine multiple topics with 'and' or 'or' in `query` (e.g. do NOT use query="GDP and inflation").
    2. **Multiple Topics, Same Country/Countries** (e.g., "life expectancy and GDP per capita" for Japan) → you MUST use the `queries` list parameter (e.g. `queries=["life expectancy", "GDP per capita"]`) + `required_country`. Do NOT make multiple tool calls. Do NOT pass multiple topics as a single query string (e.g., query="life expectancy and GDP per capita" is invalid).
    3. **Different Topics targeting Different Countries** (e.g., "life expectancy for Japan, but GDP and mortality rate for Korea") → you MUST use the `query_groups` parameter. Do NOT use `queries`.

    Args:
        query: Single topic query (e.g. "unemployment"). Use ONLY for a single topic. Do NOT combine multiple topics with 'and' or 'or' (e.g. do NOT use query="population and life expectancy"). Avoid special characters like parentheses () or dollar signs $. Example: 'GDP per capita'.
        required_country: Semicolon-separated ISO country codes (e.g. "KEN;USA"). Shared across all queries in 'query' or 'queries'. Consider calling `data360_expand_country_group` to find country codes in regional/income groups, or `data360_find_codelist_value` to resolve country names.
        limit: Max indicators per query (default 5).
        offset: Offset for pagination.
        queries: List of topics for multi-topic search (must contain at least 2 non-empty search strings). Use ONLY when 2 or more topics target the SAME countries/geographic scope (e.g. ['GDP per capita', 'inflation rate']).
        query_groups: Grouped queries with specific country scopes. Use ONLY when different topics/queries target different country scopes. Example: [{'queries': ['life expectancy'], 'country': 'JPN'}, {'queries': ['GDP per capita'], 'country': 'KOR'}].
        result_layout: Mode to return results: "merged" (flat, deduped list of indicators) or "by_query" (indicators grouped by search query).
        dedupe: De-duplicate indicators across query results.
        database: Optional database name or ID to filter search results (e.g. "wdi", "wgi", "World Development Indicators"). Multiple databases can be queried at once by separating them with a semicolon (e.g. "pip; lpgd; sgi").
    """
    return await data360_api.search(
        query=query,
        required_country=required_country,
        limit=limit,
        offset=offset,
        queries=queries,
        query_groups=query_groups,
        result_layout=result_layout,
        dedupe=dedupe,
        database=database,
    )


async def _search_datasets(
    query: str,
    limit: int = 10,
    offset: int = 0,
) -> Any:
    """Search for Data360 datasets matching a query.

    Use when the user asks for dataset details, catalogs, or source databases (e.g. "Findex", "WDI").

    Args:
        query: Topic or dataset search term (e.g. "findex"). Avoid special characters like parentheses () or dollar signs $ as they cause search failures.
        limit: Max datasets to return (default 10).
        offset: Offset for pagination.
    """
    return await data360_api.search_datasets(
        query=query,
        limit=limit,
        offset=offset,
    )


async def _get_metadata(
    database_id: str,
    indicator_id: str,
    select_fields: list[str] | None = None,
    fetch_disaggregation: bool = True,
    required_country: str | None = None,
) -> Any:
    """Get metadata and disaggregation options for a Data360 indicator.

    Use when you need detailed methodology, source notes, or limitations for an indicator.
    Ensure the database ID and the indicator ID are already in context (e.g., from `data360_search_indicators`) before using this tool. Do not guess or hallucinate these IDs.

    Args:
        database_id: Database identifier (e.g., "WB_WDI").
        indicator_id: Indicator ID (e.g., "WB_WDI_NY_GDP_PCAP_KD").
        select_fields: Optional metadata fields to return (e.g., ["methodology", "relevance"]).
        fetch_disaggregation: Whether to include disaggregation options.
        required_country: Semicolon-separated ISO country codes to check coverage.
    """
    return await data360_api.get_metadata(
        database_id=database_id,
        indicator_id=indicator_id,
        select_fields=select_fields,
        fetch_disaggregation=fetch_disaggregation,
        required_country=required_country,
    )


async def _get_data(
    database_id: str,
    indicator_id: str,
    country_code: str | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    limit: int = 50,
    offset: int = 0,
    ref_area_filter: Literal["none", "member_economies_only"] = "member_economies_only",
) -> Any:
    """Retrieve indicator observations from the Data360 API.

    Use when you need actual numeric values (OBS_VALUE) for specific countries and years.
    Ensure the database ID and the indicator ID are already in context before using this tool. Do not guess or hallucinate these IDs.
    Call `data360_get_disaggregation` first to find available years and breakdowns for the `disaggregation_filters`.

    Args:
        database_id: Database identifier (e.g., "WB_WDI").
        indicator_id: Indicator ID (e.g., "WB_WDI_NY_GDP_PCAP_KD").
        country_code: Semicolon-separated ISO country codes (e.g. "KEN;USA").
        disaggregation_filters: Optional dimension filters. Values must be strings or null. Call `data360_get_disaggregation` first to find valid options.
        start_year: Start year (inclusive). Defaults to last 5 years if both bounds omitted;
            if only end_year is set, defaults to a 5-year window ending at end_year.
        end_year: End year (inclusive). See start_year for partial-bound defaults.
        limit: Max records per page (default 50, max 100).
        offset: Number of records to skip for pagination.
        ref_area_filter: Filter mode: "member_economies_only" (default) or "none".
    """
    return await data360_api.get_data(
        database_id=database_id,
        indicator_id=indicator_id,
        country_code=country_code,
        disaggregation_filters=disaggregation_filters,
        start_year=start_year,
        end_year=end_year,
        limit=limit,
        offset=offset,
        ref_area_filter=ref_area_filter,
    )


async def _get_disaggregation(
    database_id: str,
    indicator_id: str,
    required_country: str | None = None,
) -> dict[str, Any]:
    """Get valid filter values and disaggregation options for an indicator.

    Use to find available dimensions (e.g., SEX, AGE) and years before querying data or charts.
    Ensure the database ID and the indicator ID are already in context before using this tool. Do not guess or hallucinate these IDs.

    Args:
        database_id: Database identifier (e.g., "WB_WDI").
        indicator_id: Indicator ID (e.g., "WB_WDI_NY_GDP_PCAP_KD").
        required_country: Semicolon-separated ISO country codes to check coverage.
    """
    return await data360_api.get_disaggregation(
        database_id=database_id,
        indicator_id=indicator_id,
        required_country=required_country,
    )


async def _find_codelist_value(
    codelist_type: str, query: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Resolve user-friendly names to API dimension codes.

    Use when you need to find codes for country names, sex, age, urbanisation, etc.

    Args:
        codelist_type: Dimension name (e.g. "REF_AREA", "SEX", "AGE", "URBANISATION").
        query: Search term (e.g. "Kenya", "female").
        limit: Max results to return (default 5).
    """
    return await data360_providers.find_codelist_value(
        codelist_type=codelist_type, query=query, limit=limit
    )


async def _list_indicators(database_id: str) -> list[str]:
    """Get all indicator IDs for a specific database.

    Use when you need the full list of indicator IDs for a dataset.

    Args:
        database_id: The database identifier (e.g., "WB_WDI").
    """
    return await data360_api.get_indicators(database_id=database_id)


async def _get_data_api_url(
    database_id: str,
    indicator_id: str,
    country_code: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
) -> str:
    """Generate the raw Data360 API URL for an indicator request.

    Low-level tool: use only when the caller specifically asks for the URL.
    Ensure the database ID and the indicator ID are already in context before using this tool. Do not guess or hallucinate these IDs.

    Args:
        database_id: Database identifier (e.g. "WB_WDI").
        indicator_id: Indicator ID (e.g. "WB_WDI_NY_GDP_PCAP_KD").
        country_code: Semicolon-separated ISO country codes.
        start_year: Start year (inclusive). Defaults to last 5 years if omitted.
        end_year: End year (inclusive). Defaults to current year if omitted.
        disaggregation_filters: Optional dimension filters.
    """
    return await data360_api.get_data_api_url(
        database_id=database_id,
        indicator_id=indicator_id,
        country_code=country_code,
        start_year=start_year,
        end_year=end_year,
        disaggregation_filters=disaggregation_filters,
    )


async def _get_viz_spec(
    database_id: str,
    indicator_id: str,
    country_code: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
    chart_type: str | None = None,
    relevant_fields: list[str] | None = None,
    custom_constraints: list[str] | None = None,
    use_default_constraints: bool = True,
    chart_title: str | None = None,
    series_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate a Vega-Lite chart from a single Data360 indicator.

    Use when the user requests a chart or plot for a single indicator.
    Ensure the database ID and the indicator ID are already in context before using this tool. Do not guess or hallucinate these IDs.
    Call `data360_get_disaggregation` first to find available years and breakdowns for the `disaggregation_filters`.

    Args:
        database_id: Database identifier (e.g. "WB_WDI").
        indicator_id: Indicator ID (e.g. "WB_WDI_NY_GDP_PCAP_KD").
        country_code: Semicolon-separated ISO country codes (e.g. "KEN;USA").
        start_year: Start year (inclusive). Defaults to last 5 years if omitted.
        end_year: End year (inclusive). Defaults to current year if omitted.
        disaggregation_filters: Optional dimension filters.
        chart_type: Optional chart type (e.g. "line", "bar", "strip", "heatmap").
        relevant_fields: Fields to include in visual encodings.
        custom_constraints: Custom Draco design rules.
        use_default_constraints: Whether to apply default Draco design constraints.
        chart_title: Title for the chart.
        series_labels: Rename dimension codes for legend (e.g. {"WGI_EST": "Estimate"}).
    """
    return await data360_viz.get_viz_spec(
        database_id=database_id,
        indicator_id=indicator_id,
        country_code=country_code,
        start_year=start_year,
        end_year=end_year,
        disaggregation_filters=disaggregation_filters,
        chart_type=chart_type,
        relevant_fields=relevant_fields,
        custom_constraints=custom_constraints,
        use_default_constraints=use_default_constraints,
        chart_title=chart_title,
        series_labels=series_labels,
    )


async def _get_multi_indicator_viz_spec(
    indicator_ids: list[dict[str, str]] | None = None,
    country_code: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
    chart_type: str | None = None,
    chart_title: str | None = None,
    series_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate a Vega-Lite chart comparing multiple Data360 indicators.

    Use when you need to compare 2–4 indicators (e.g. via scatterplot or dual-axis line chart).
    Ensure the database IDs and indicator IDs are already in context before using this tool. Do not guess or hallucinate these IDs.

    Args:
        indicator_ids: List of database/indicator dicts, e.g. [{"database_id": "WB_WDI", "indicator_id": "..."}].
        country_code: Semicolon-separated ISO country codes (e.g. "KEN;USA").
        start_year: Start year (inclusive). Defaults to last 5 years if omitted.
        end_year: End year (inclusive). Defaults to current year if omitted.
        disaggregation_filters: Optional dimension filters.
        chart_type: Optional chart type override (e.g. "scatter", "line").
        chart_title: Title for the chart.
        series_labels: Rename dimension codes for legend.
    """
    return await data360_viz.get_multi_indicator_viz_spec(
        indicator_ids=indicator_ids,
        country_code=country_code,
        start_year=start_year,
        end_year=end_year,
        disaggregation_filters=disaggregation_filters,
        chart_type=chart_type,
        chart_title=chart_title,
        series_labels=series_labels,
    )


def _get_supported_chart_types() -> str:
    """Return supported chart types and their data requirements as JSON.

    Use when deciding which chart_type value to pass to visualization tools.
    """
    return data360_viz.get_supported_chart_types()


async def _expand_country_group(
    group_code: str,
) -> dict[str, Any]:
    """Expand a REF_AREA group code into its constituent country codes.

    Use when you need individual country codes for a regional or income group code (e.g. "SAS").

    Args:
        group_code: The group code to expand (e.g. "SAS" for South Asia, "LIC" for Low Income).
    """
    return await data360_providers.expand_country_group(group_code=group_code)


async def _summarize_data(
    database_id: str,
    indicator_id: str,
    country_code: str | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    group_by: list[str] | None = None,
) -> Any:
    """Compute summary statistics for indicator data, grouped by dimensions.

    Use when the user asks about trends, changes over time, or general statistical summaries.
    Ensure the database ID and the indicator ID are already in context before using this tool. Do not guess or hallucinate these IDs.

    Args:
        database_id: Database identifier (e.g. "WB_WDI").
        indicator_id: Indicator ID (e.g. "WB_WDI_NY_GDP_PCAP_KD").
        country_code: Semicolon-separated ISO country codes (e.g. "KEN;USA").
        disaggregation_filters: Optional dimension filters.
        start_year: Start year (inclusive). Defaults to last 5 years if omitted.
        end_year: End year (inclusive). Defaults to current year if omitted.
        group_by: Dimensions to group by (default is ["ref_area"]).
    """
    return await data360_api.summarize_data(
        database_id=database_id,
        indicator_id=indicator_id,
        country_code=country_code,
        disaggregation_filters=disaggregation_filters,
        start_year=start_year,
        end_year=end_year,
        group_by=group_by,
    )


async def _rank_countries(
    database_id: str,
    indicator_id: str,
    country_group: str | None = None,
    country_codes: str | None = None,
    year: int | None = None,
    order: Literal["desc", "asc"] = "desc",
    top_n: int = 10,
    disaggregation_filters: dict[str, str | None] | None = None,
    rank_universe: Literal["explicit", "all_member_economies"] = "explicit",
) -> Any:
    """Rank countries by indicator value for a specific year.

    Use when asked to rank countries, find leaderboards, or query top/bottom performing economies.
    Ensure the database ID and the indicator ID are already in context before using this tool. Do not guess or hallucinate these IDs.

    Args:
        database_id: Database identifier (e.g. "WB_WDI").
        indicator_id: Indicator ID (e.g. "WB_WDI_NY_GDP_PCAP_KD").
        country_group: Code of region/income group (e.g. "SAS").
        country_codes: Semicolon-separated ISO country codes (e.g. "KEN;USA;NGA").
        year: Year for ranking. If omitted, selected automatically based on coverage.
        order: Sort order: "desc" (default, highest first) or "asc" (lowest first).
        top_n: Number of ranked entries to return.
        disaggregation_filters: Optional dimension filters.
        rank_universe: "explicit" (default, uses codes/group) or "all_member_economies" (world).
    """
    return await data360_api.rank_countries(
        database_id=database_id,
        indicator_id=indicator_id,
        country_group=country_group,
        country_codes=country_codes,
        year=year,
        order=order,
        top_n=top_n,
        disaggregation_filters=disaggregation_filters,
        rank_universe=rank_universe,
    )


async def _compare_countries(
    database_id: str,
    indicator_id: str,
    country_codes: str,
    year: int | None = None,
    include_time_series: bool = False,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
) -> Any:
    """Compare an indicator across multiple countries (2 to 8).

    Use when asked to compare specific countries or find gaps/convergence between them.
    Ensure the database ID and the indicator ID are already in context before using this tool. Do not guess or hallucinate these IDs.
    Call `data360_get_disaggregation` first to find available years and breakdowns for the `disaggregation_filters`.

    Args:
        database_id: Database identifier (e.g. "WB_WDI").
        indicator_id: Indicator ID (e.g. "WB_WDI_NY_GDP_PCAP_KD").
        country_codes: Semicolon-separated ISO country codes (e.g. "KEN;NGA;ZAF").
        year: Snapshot comparison year. If omitted, selected automatically.
        include_time_series: Whether to return time-series data for trend comparison.
        start_year: Start year for time-series alignment. Defaults to last 5 years if omitted.
        end_year: End year for time-series alignment. Defaults to current year if omitted.
        disaggregation_filters: Optional dimension filters.
    """
    return await data360_api.compare_countries(
        database_id=database_id,
        indicator_id=indicator_id,
        country_codes=country_codes,
        year=year,
        include_time_series=include_time_series,
        start_year=start_year,
        end_year=end_year,
        disaggregation_filters=disaggregation_filters,
    )


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------

search_indicators = mcp.tool(
    instrument_mcp_tool(_search_indicators, tool_name="data360_search_indicators"),
    name="data360_search_indicators",
)

search_datasets = mcp.tool(
    instrument_mcp_tool(_search_datasets, tool_name="data360_search_datasets"),
    name="data360_search_datasets",
)

get_metadata = mcp.tool(
    instrument_mcp_tool(_get_metadata, tool_name="data360_get_metadata"),
    name="data360_get_metadata",
)

get_data = mcp.tool(
    instrument_mcp_tool(_get_data, tool_name="data360_get_data"),
    name="data360_get_data",
)

get_disaggregation = mcp.tool(
    instrument_mcp_tool(_get_disaggregation, tool_name="data360_get_disaggregation"),
    name="data360_get_disaggregation",
)

find_codelist_value = mcp.tool(
    instrument_mcp_tool(_find_codelist_value, tool_name="data360_find_codelist_value"),
    name="data360_find_codelist_value",
)

list_indicators = mcp.tool(
    instrument_mcp_tool(_list_indicators, tool_name="data360_list_indicators"),
    name="data360_list_indicators",
)

get_data_api_url = mcp.tool(
    instrument_mcp_tool(_get_data_api_url, tool_name="data360_get_data_api_url"),
    name="data360_get_data_api_url",
)

get_viz_spec = mcp.tool(
    instrument_mcp_tool(_get_viz_spec, tool_name="data360_get_viz_spec"),
    name="data360_get_viz_spec",
)

get_multi_indicator_viz_spec = mcp.tool(
    instrument_mcp_tool(
        _get_multi_indicator_viz_spec,
        tool_name="data360_get_multi_indicator_viz_spec",
    ),
    name="data360_get_multi_indicator_viz_spec",
)

get_supported_chart_types = mcp.tool(
    instrument_mcp_tool(
        _get_supported_chart_types,
        tool_name="data360_get_supported_chart_types",
    ),
    name="data360_get_supported_chart_types",
)

expand_country_group = mcp.tool(
    instrument_mcp_tool(
        _expand_country_group, tool_name="data360_expand_country_group"
    ),
    name="data360_expand_country_group",
)

# ---------------------------------------------------------------------------
# Data Aggregation Tools (with custom serialization)
# ---------------------------------------------------------------------------

summarize_data = mcp.add_tool(
    Tool.from_function(
        instrument_mcp_tool(_summarize_data, tool_name="data360_summarize_data"),
        name="data360_summarize_data",
        serializer=_compact_aggregation_serializer,
    )
)

rank_countries = mcp.add_tool(
    Tool.from_function(
        instrument_mcp_tool(_rank_countries, tool_name="data360_rank_countries"),
        name="data360_rank_countries",
        serializer=_compact_aggregation_serializer,
    )
)

compare_countries = mcp.add_tool(
    Tool.from_function(
        instrument_mcp_tool(_compare_countries, tool_name="data360_compare_countries"),
        name="data360_compare_countries",
        serializer=_compact_aggregation_serializer,
    )
)
