"""MCP Tools for the Data360 server.

Thin wrapper layer that registers API functions as MCP tools with optimized signatures,
concise docstrings to reduce token context bloat, and validation schemas.
"""

import json
from typing import Any

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
) -> Any:
    """Search for Data360 indicators with enriched metadata for selection.

    Use when the user asks for data on a development topic (e.g. GDP, poverty, education).
    Provide query, queries, or query_groups.

    Args:
        query: Single topic query (e.g. "unemployment").
        required_country: Semicolon-separated ISO country codes (e.g. "KEN;USA").
        limit: Max indicators per query (default 5).
        offset: Offset for pagination.
        queries: List of topics for multi-topic search.
        query_groups: Grouped queries with specific country scopes.
        result_layout: Mode to return results: "merged" or "by_query".
        dedupe: De-duplicate indicators across query results.
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
    For basic info like definitions or frequency, prefer fields returned by search.

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
    ref_area_filter: str = "member_economies_only",
) -> Any:
    """Retrieve indicator observations from the Data360 API.

    Use when you need actual numeric values (OBS_VALUE) for specific countries and years.
    Call get_disaggregation first to find available breakdowns and years.

    Args:
        database_id: Database identifier (e.g., "WB_WDI").
        indicator_id: Indicator ID (e.g., "WB_WDI_NY_GDP_PCAP_KD").
        country_code: Semicolon-separated ISO country codes (e.g. "KEN;USA").
        disaggregation_filters: Optional dimension filters. Values must be strings or null.
        start_year: Start year (inclusive). Defaults to last 20 years if omitted.
        end_year: End year (inclusive). Defaults to current year if omitted.
        limit: Max records per page (default 50, max 100).
        offset: Number of records to skip for pagination.
        ref_area_filter: Filter mode: "member_economies_only" (default) or "all".
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

    Args:
        database_id: Database identifier (e.g. "WB_WDI").
        indicator_id: Indicator ID (e.g. "WB_WDI_NY_GDP_PCAP_KD").
        country_code: Semicolon-separated ISO country codes.
        start_year: Start year (inclusive).
        end_year: End year (inclusive).
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

    Args:
        database_id: Database identifier (e.g. "WB_WDI").
        indicator_id: Indicator ID (e.g. "WB_WDI_NY_GDP_PCAP_KD").
        country_code: Semicolon-separated ISO country codes (e.g. "KEN;USA").
        start_year: Start year (inclusive).
        end_year: End year (inclusive).
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

    Args:
        indicator_ids: List of database/indicator dicts, e.g. [{"database_id": "WB_WDI", "indicator_id": "..."}].
        country_code: Semicolon-separated ISO country codes (e.g. "KEN;USA").
        start_year: Start year (inclusive).
        end_year: End year (inclusive).
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

    Args:
        database_id: Database identifier (e.g. "WB_WDI").
        indicator_id: Indicator ID (e.g. "WB_WDI_NY_GDP_PCAP_KD").
        country_code: Semicolon-separated ISO country codes (e.g. "KEN;USA").
        disaggregation_filters: Optional dimension filters.
        start_year: Start year (inclusive).
        end_year: End year (inclusive).
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
    order: str = "desc",
    top_n: int = 10,
    disaggregation_filters: dict[str, str | None] | None = None,
    rank_universe: str = "explicit",
) -> Any:
    """Rank countries by indicator value for a specific year.

    Use when asked to rank countries, find leaderboards, or query top/bottom performing economies.

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
        rank_universe=rank_universe,  # type: ignore
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

    Args:
        database_id: Database identifier (e.g. "WB_WDI").
        indicator_id: Indicator ID (e.g. "WB_WDI_NY_GDP_PCAP_KD").
        country_codes: Semicolon-separated ISO country codes (e.g. "KEN;NGA;ZAF").
        year: Snapshot comparison year. If omitted, selected automatically.
        include_time_series: Whether to return time-series data for trend comparison.
        start_year: Start year for time-series alignment.
        end_year: End year for time-series alignment.
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

get_metadata = mcp.tool(
    instrument_mcp_tool(_get_metadata, tool_name="data360_get_metadata"),
    name="data360_get_metadata",
)

get_data = mcp.tool(
    instrument_mcp_tool(_get_data, tool_name="data360_get_data"),
    name="data360_get_data",
)

get_disaggregation = mcp.tool(
    instrument_mcp_tool(
        _get_disaggregation, tool_name="data360_get_disaggregation"
    ),
    name="data360_get_disaggregation",
)

find_codelist_value = mcp.tool(
    instrument_mcp_tool(
        _find_codelist_value, tool_name="data360_find_codelist_value"
    ),
    name="data360_find_codelist_value",
)

list_indicators = mcp.tool(
    instrument_mcp_tool(
        _list_indicators, tool_name="data360_list_indicators"
    ),
    name="data360_list_indicators",
)

get_data_api_url = mcp.tool(
    instrument_mcp_tool(
        _get_data_api_url, tool_name="data360_get_data_api_url"
    ),
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
        instrument_mcp_tool(
            _summarize_data, tool_name="data360_summarize_data"
        ),
        name="data360_summarize_data",
        serializer=_compact_aggregation_serializer,
    )
)

rank_countries = mcp.add_tool(
    Tool.from_function(
        instrument_mcp_tool(
            _rank_countries, tool_name="data360_rank_countries"
        ),
        name="data360_rank_countries",
        serializer=_compact_aggregation_serializer,
    )
)

compare_countries = mcp.add_tool(
    Tool.from_function(
        instrument_mcp_tool(
            _compare_countries, tool_name="data360_compare_countries"
        ),
        name="data360_compare_countries",
        serializer=_compact_aggregation_serializer,
    )
)
