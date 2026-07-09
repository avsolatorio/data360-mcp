"""MCP Tools for the Data360 server.

Thin wrapper layer that registers API functions as MCP tools with optimized signatures,
concise docstrings to reduce token context bloat, and validation schemas.
"""

import os
import json
from typing import Any, Literal, Optional

import pydantic_core
from fastmcp.apps import AppConfig, PrefabAppConfig
from prefab_ui.app import PrefabApp
from prefab_ui.components import Column, Row, Heading, Input, Select, SelectOption, Button, ForEach, Card, CardHeader, CardTitle, CardContent, CardFooter, Text, Form, Rx, RESULT
from prefab_ui.actions import CallTool, SetState, SendMessage
from fastmcp.tools import ToolResult
from fastmcp.tools.tool import Tool
from mcp.types import TextContent
from fastmcp.exceptions import ToolError

from data360 import api as data360_api
from data360 import providers as data360_providers
from data360 import visualization as data360_viz
from data360 import viz_config as data360_viz_config

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


def _normalize_disaggregation_filters(filters: dict[str, Any] | None) -> dict[str, str | None] | None:
    """Normalize user-provided disaggregation filters.
    Converts list values (e.g., ["F", "M"]) to comma-separated strings (e.g., "F,M")
    to conform to the underlying API support while remaining type-flexible for LLM callers.
    """
    if filters is None:
        return None
    normalized = {}
    for k, v in filters.items():
        if v is None:
            normalized[k] = None
        elif isinstance(v, list):
            normalized[k] = ",".join(str(item).strip() for item in v if item is not None)
        else:
            normalized[k] = str(v)
    return normalized


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
    disaggregation_filters: dict[str, Any] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    limit: int = 50,
    offset: int = 0,
    ref_area_filter: Literal["none", "member_economies_only"] = "member_economies_only",
    year: int | None = None,
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
        year: Specific single year to retrieve data for. Maps internally to start_year and end_year.
    """
    if year is not None:
        if start_year is None:
            start_year = year
        if end_year is None:
            end_year = year


    norm_filters = _normalize_disaggregation_filters(disaggregation_filters)

    return await data360_api.get_data(
        database_id=database_id,
        indicator_id=indicator_id,
        country_code=country_code,
        disaggregation_filters=norm_filters,
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
    disaggregation_filters: dict[str, Any] | None = None,
    year: int | None = None,
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
        year: Specific single year to generate the URL for. Maps internally to start_year and end_year.
    """
    if year is not None:
        if start_year is None:
            start_year = year
        if end_year is None:
            end_year = year


    norm_filters = _normalize_disaggregation_filters(disaggregation_filters)

    return await data360_api.get_data_api_url(
        database_id=database_id,
        indicator_id=indicator_id,
        country_code=country_code,
        start_year=start_year,
        end_year=end_year,
        disaggregation_filters=norm_filters,
    )



# Cache for local Vega library contents to prevent disk read overhead on every tool call
_vega_js_cache = None
_vega_lite_js_cache = None
_vega_embed_js_cache = None
_vega_interpreter_js_cache = None

def get_cached_vega_libs() -> tuple[str, str, str, str]:
    """Load and cache local Vega library scripts from static/libs."""
    global _vega_js_cache, _vega_lite_js_cache, _vega_embed_js_cache, _vega_interpreter_js_cache
    if _vega_js_cache is None:
        from pathlib import Path
        libs_dir = Path(__file__).resolve().parent.parent.parent.parent / "static" / "libs"
        try:
            _vega_js_cache = (libs_dir / "vega.js").read_text(encoding="utf-8")
            _vega_lite_js_cache = (libs_dir / "vega-lite.js").read_text(encoding="utf-8")
            _vega_embed_js_cache = (libs_dir / "vega-embed.js").read_text(encoding="utf-8")
            _vega_interpreter_js_cache = (libs_dir / "vega-interpreter.js").read_text(encoding="utf-8")
        except Exception as e:
            import logging
            logger = logging.getLogger("data360")
            logger.warning(f"Failed to load local Vega library scripts: {e}")
            _vega_js_cache = ""
            _vega_lite_js_cache = ""
            _vega_embed_js_cache = ""
            _vega_interpreter_js_cache = ""
    return _vega_js_cache, _vega_lite_js_cache, _vega_embed_js_cache, _vega_interpreter_js_cache


def spec_to_prefab(
    spec: dict[str, Any] | None,
    strategy: str,
    reason: str,
    warning: str | None = None,
    source_line: str | None = None,
    subtitle_line: str | None = None,
) -> Any:
    """Map a Vega-Lite spec to prefab_ui components."""
    from prefab_ui.components import (
        Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter, Alert, AlertTitle, AlertDescription, Markdown, Container, DataTable, DataTableColumn, Grid
    )
    from prefab_ui.components.charts import LineChart, BarChart, ScatterChart, ChartSeries, AreaChart
    import pandas as pd

    children = []

    # 1. Add warning Alert if present
    if warning:
        children.append(
            Alert(
                variant="warning",
                children=[
                    AlertTitle(content="Warning"),
                    AlertDescription(content=warning),
                ]
            )
        )

    # 2. Extract embedded data
    data_rows = []
    if isinstance(spec, dict) and "data" in spec and "values" in spec["data"]:
        data_rows = spec["data"]["values"]

    chart_component = None

    if data_rows:
        from data360.config import get_mcp_server_settings
        import logging
        
        logger = logging.getLogger("data360")
        mcp_settings = get_mcp_server_settings()
        
        chart_render_mode = mcp_settings.chart_render_mode
        
        # 1. If in 'embed' mode, render Vega-Lite directly inside an iframe using Embed
        if chart_render_mode == "embed" and spec:
            try:
                from prefab_ui.components import Embed
                import copy
                # Copy the spec and strip title from the embedded canvas (Card renders the title cleanly)
                spec_for_embed = copy.deepcopy(spec)
                if "title" in spec_for_embed:
                    del spec_for_embed["title"]
                import urllib.parse
                
                port = mcp_settings.port or 8021
                server_base = f"http://localhost:{port}"
                spec_json = json.dumps(spec_for_embed)
                quoted_spec = urllib.parse.quote(spec_json)
                url = f"{server_base}/static/embed.html?spec={quoted_spec}"
                
                chart_component = Embed(
                    url=url,
                    sandbox="allow-scripts allow-same-origin",
                    width="100%",
                    height="480px"
                )
            except Exception as e:
                logger.warning(f"Embed rendering failed: {e}; falling back to interactive charts.")

        # 2. If in 'svg' mode (or if embed failed), render static SVG using vl_convert
        elif chart_render_mode == "svg" and spec:
            try:
                import vl_convert as vlc
                from prefab_ui.components import Svg
                import copy
                
                spec_for_svg = copy.deepcopy(spec)
                if "title" in spec_for_svg:
                    del spec_for_svg["title"]
                
                svg_str = vlc.vegalite_to_svg(json.dumps(spec_for_svg))
                chart_component = Svg(content=svg_str, width="100%", height="auto")
            except Exception as e:
                logger.warning(f"SVG rendering failed: {e}; falling back to interactive charts.")

        # If we successfully generated the SVG or Embed component, wrap in Card and return immediately
        if chart_component is not None:
            title = "Data360 Visualization"
            real_subtitle = ""
            if isinstance(spec, dict) and isinstance(spec.get("title"), dict):
                title_val = spec["title"].get("text", "Data360 Visualization")
                if isinstance(title_val, list):
                    title = " ".join(str(t) for t in title_val if t)
                else:
                    title = str(title_val)
                sub_val = spec["title"].get("subtitle")
                if isinstance(sub_val, list):
                    real_subtitle = " · ".join(str(s) for s in sub_val if s)
                elif sub_val:
                    real_subtitle = str(sub_val)
            elif isinstance(spec, dict) and isinstance(spec.get("title"), str):
                title = spec["title"]
            
            card_header_children = [CardTitle(content=title)]
            if real_subtitle:
                card_header_children.append(CardDescription(content=real_subtitle))
            elif subtitle_line:
                card_header_children.append(CardDescription(content=subtitle_line))
                
            card_children = [
                CardHeader(children=card_header_children)
            ]
            card_children.append(CardContent(children=[chart_component]))
                
            footer_text = []
            if source_line:
                footer_text.append(source_line)
                
            if footer_text:
                card_children.append(CardFooter(children=[Markdown(content="\n\n".join(footer_text))]))
        
            children.append(Card(children=card_children))
            return Container(children=children)

        try:
            df = pd.DataFrame(data_rows)
            # Normalize columns to lowercase to prevent casing mismatches in Recharts
            df.columns = [col.lower() for col in df.columns]

            # 1. Determine value column (quantitative axis)
            val_col = ""
            for possible_val in ["obs_value", "value", "val", "obs"]:
                if possible_val in df.columns:
                    val_col = possible_val
                    break
            if not val_col:
                # Fallback to the first numeric or non-time/non-country column
                for col in df.columns:
                    if col not in ["time_period", "year", "date", "ref_area", "country", "country_code", "indicator", "indicator_id"]:
                        val_col = col
                        break

            # 2. Determine x/categorical column
            x_col = ""
            strategy_lower = strategy.lower() if strategy else ""
            if "temporal" in strategy_lower or "small_multiples" in strategy_lower:
                for possible_time in ["time_period", "year", "date", "time"]:
                    if possible_time in df.columns:
                        x_col = possible_time
                        break
                if not x_col and len(df.columns) > 0:
                    x_col = df.columns[0]
            else:
                for possible_cat in ["ref_area", "country", "country_code", "economy"]:
                    if possible_cat in df.columns:
                        x_col = possible_cat
                        break
                if not x_col:
                    for col in df.columns:
                        if col != val_col:
                            x_col = col
                            break
            
            # 1. Determine if the Vega-Lite spec uses a concatenated layout (vconcat/hconcat)
            is_concatenated = isinstance(spec, dict) and ("vconcat" in spec or "hconcat" in spec or "concat" in spec)
            
            # Determine chart type based on structure and strategy
            if is_concatenated:
                import re
                concat_key = "vconcat" if "vconcat" in spec else ("hconcat" in spec and "hconcat" or "concat")
                children_specs = spec[concat_key]
                facet_cards = []
                
                # The data values are shared at the top level or child level
                top_data = spec.get("data", {}).get("values", [])
                if not top_data:
                    top_data = data_rows
                
                for i, child_spec in enumerate(children_specs):
                    if not isinstance(child_spec, dict):
                        continue
                    child_title_val = child_spec.get("title", {}).get("text", f"Panel {i+1}") if isinstance(child_spec.get("title"), dict) else f"Panel {i+1}"
                    if isinstance(child_title_val, list):
                        child_title = " ".join(str(t) for t in child_title_val if t)
                    else:
                        child_title = str(child_title_val)
                    
                    # Handle transform filtering (e.g. filter by country or indicator)
                    child_data = top_data
                    transforms = child_spec.get("transform", [])
                    for transform in transforms:
                        if isinstance(transform, dict) and "filter" in transform and isinstance(transform["filter"], str):
                            filter_expr = transform["filter"]
                            match = re.search(r"datum\.(\w+)\s*==\s*['\"]([^'\"]+)['\"]", filter_expr)
                            if match:
                                col, val = match.groups()
                                child_data = [row for row in child_data if str(row.get(col, row.get(col.lower(), row.get(col.upper(), "")))) == val]
                    
                    # Detect encoding fields for this child spec
                    y_encoding = child_spec.get("encoding", {}).get("y", {})
                    child_val_col = y_encoding.get("field", "").lower() if isinstance(y_encoding, dict) else ""
                    
                    x_encoding = child_spec.get("encoding", {}).get("x", {})
                    child_x_col = x_encoding.get("field", "").lower() if isinstance(x_encoding, dict) else ""
                    
                    if not child_val_col:
                        child_val_col = val_col
                    if not child_x_col:
                        child_x_col = x_col
                        
                    if child_data and child_x_col and child_val_col:
                        child_df = pd.DataFrame(child_data)
                        child_df.columns = [c.lower() for c in child_df.columns]
                        
                        if child_x_col in child_df.columns:
                            child_df = child_df.sort_values(by=child_x_col)
                            
                        child_df_clean = child_df.where(pd.notnull(child_df), None)
                        sub_chart_data = child_df_clean.to_dict(orient="records")
                        
                        # Detect mark type
                        mark_spec = child_spec.get("mark", "line")
                        mark_type = mark_spec.get("type", "line") if isinstance(mark_spec, dict) else str(mark_spec)
                        is_bar = mark_type == "bar" or "bar" in strategy_lower
                        
                        color_encoding = child_spec.get("encoding", {}).get("color", {})
                        if isinstance(color_encoding, dict) and "field" in color_encoding:
                            # If we color by another column (e.g. country inside this panel), it's a multi-series line chart
                            group_field = color_encoding.get("field", "").lower()
                            if group_field in child_df.columns and child_df[group_field].nunique() > 1:
                                pivot_df = child_df.pivot(index=child_x_col, columns=group_field, values=child_val_col)
                                pivot_df = pivot_df.reset_index()
                                pivot_df = pivot_df.where(pd.notnull(pivot_df), None)
                                sub_chart_data = pivot_df.to_dict(orient="records")
                                
                                series_list = [ChartSeries(data_key=col, label=col) for col in pivot_df.columns if col != child_x_col]
                                sub_chart = LineChart(
                                    data=sub_chart_data,
                                    series=series_list,
                                    x_axis=child_x_col,
                                    height=200,
                                )
                            else:
                                sub_chart = LineChart(
                                    data=sub_chart_data,
                                    series=[ChartSeries(data_key=child_val_col, label=child_title)],
                                    x_axis=child_x_col,
                                    height=200,
                                )
                        else:
                            if is_bar:
                                sub_chart = BarChart(
                                    data=sub_chart_data,
                                    series=[ChartSeries(data_key=child_val_col, label=child_title)],
                                    x_axis=child_x_col,
                                    horizontal=True,
                                    height=200,
                                )
                            else:
                                sub_chart = LineChart(
                                    data=sub_chart_data,
                                    series=[ChartSeries(data_key=child_val_col, label=child_title)],
                                    x_axis=child_x_col,
                                    height=200,
                                )
                                
                        facet_cards.append(
                            Card(
                                children=[
                                    CardHeader(children=[CardTitle(content=child_title)]),
                                    CardContent(children=[sub_chart])
                                ]
                            )
                        )
                
                if facet_cards:
                    chart_component = Grid(
                        columns={"default": 1, "md": 2},
                        gap=4,
                        children=facet_cards
                    )
            elif "small_multiples" in strategy_lower or "concat" in strategy_lower:
                # Group data by the grouping column (country or indicator)
                group_col = ""
                for possible_group in ["ref_area", "country", "country_code"]:
                    if possible_group in df.columns:
                        group_col = possible_group
                        break
                
                if group_col and x_col and val_col:
                    # Get unique values of the group column
                    groups = df[group_col].unique()
                    facet_cards = []
                    
                    for group_val in groups:
                        group_df = df[df[group_col] == group_val]
                        group_df_sorted = group_df.sort_values(by=x_col)
                        group_df_clean = group_df_sorted.where(pd.notnull(group_df_sorted), None)
                        group_chart_data = group_df_clean.to_dict(orient="records")
                        
                        # Determine sub-chart type (LineChart if temporal, else BarChart)
                        is_temporal = "year" in x_col or "time_period" in x_col
                        if is_temporal:
                            sub_chart = LineChart(
                                data=group_chart_data,
                                series=[ChartSeries(data_key=val_col, label=str(group_val))],
                                x_axis=x_col,
                                height=200,
                            )
                        else:
                            sub_chart = BarChart(
                                data=group_chart_data,
                                series=[ChartSeries(data_key=val_col, label=str(group_val))],
                                x_axis=x_col,
                                horizontal=True,
                                height=200,
                            )
                            
                        # Wrap each facet in its own Card
                        facet_cards.append(
                            Card(
                                children=[
                                    CardHeader(children=[CardTitle(content=str(group_val))]),
                                    CardContent(children=[sub_chart])
                                ]
                            )
                        )
                    
                    if facet_cards:
                        chart_component = Grid(
                            columns={"default": 1, "md": 2},
                            gap=4,
                            children=facet_cards
                        )
            elif "correlation" in strategy_lower:
                # Scatterplot of two indicators
                # Usually the dataset contains x and y columns mapped in the encoding
                encoding = spec.get("encoding", {})
                if not encoding and "layer" in spec:
                    for layer in spec["layer"]:
                        if isinstance(layer, dict) and "encoding" in layer:
                            encoding = layer["encoding"]
                            break
                            
                x_col_corr = encoding.get("x", {}).get("field", "").lower() if isinstance(encoding.get("x"), dict) else ""
                y_col_corr = encoding.get("y", {}).get("field", "").lower() if isinstance(encoding.get("y"), dict) else ""
                
                if x_col_corr and y_col_corr:
                    # Determine data key for grouping points
                    pt_key = "point"
                    for possible_pt in ["ref_area", "country", "country_code"]:
                        if possible_pt in df.columns:
                            pt_key = possible_pt
                            break
                            
                    # Generate a unique series for each country so the tooltip name mapping works correctly in Prefab
                    unique_pts = sorted([pt for pt in df[pt_key].dropna().unique() if str(pt).strip() != ""])
                    series_list = []
                    for pt in unique_pts:
                        pt_str = str(pt)
                        series_key = pt_str.replace(" ", "_").replace("'", "").replace("&", "")
                        
                        # Find matching metadata for this point to build a rich label
                        pt_df = df[df[pt_key] == pt]
                        
                        # Resolve year
                        yr_val = ""
                        if "year" in pt_df.columns and not pt_df["year"].dropna().empty:
                            yr_val = str(int(pt_df["year"].dropna().iloc[0]))
                        elif "time_period" in pt_df.columns and not pt_df["time_period"].dropna().empty:
                            yr_val = str(pt_df["time_period"].dropna().iloc[0])
                            
                        # Resolve country code / ref_area
                        code_val = ""
                        for possible_code in ["ref_area", "country_code"]:
                            if possible_code in pt_df.columns and possible_code != pt_key and not pt_df[possible_code].dropna().empty:
                                code_val = str(pt_df[possible_code].dropna().iloc[0])
                                break
                                
                        # Build rich label containing all available metadata
                        label_parts = [pt_str]
                        if code_val:
                            label_parts.append(f"({code_val})")
                        if yr_val:
                            label_parts.append(f"- {yr_val}")
                        pt_label = " ".join(label_parts)
                        
                        series_list.append(ChartSeries(data_key=series_key, label=pt_label))
                        
                    # Map the rows to have the corresponding _series property
                    df_clean = df.where(pd.notnull(df), None)
                    chart_data = []
                    for _, row in df_clean.iterrows():
                        row_dict = row.to_dict()
                        pt_val = row_dict.get(pt_key)
                        if pt_val is not None:
                            row_dict["_series"] = str(pt_val).replace(" ", "_").replace("'", "").replace("&", "")
                        else:
                            row_dict["_series"] = "unknown"
                        chart_data.append(row_dict)

                    chart_component = ScatterChart(
                        data=chart_data,
                        series=series_list,
                        x_axis=x_col_corr,
                        y_axis=y_col_corr,
                        z_axis=pt_key,
                        show_legend=True,
                    )
            elif "stacked_area" in strategy_lower or "stacked" in strategy_lower:
                # Multi-series stacked area chart
                group_col = ""
                for possible_group in ["ref_area", "country", "country_code"]:
                    if possible_group in df.columns:
                        group_col = possible_group
                        break
                        
                if group_col and df[group_col].nunique() > 1 and x_col and val_col:
                    # Pivot index=x_col, columns=group_col, values=val_col
                    pivot_df = df.pivot(index=x_col, columns=group_col, values=val_col)
                    pivot_df = pivot_df.reset_index()
                    pivot_df = pivot_df.where(pd.notnull(pivot_df), None)
                    chart_data = pivot_df.to_dict(orient="records")
                    
                    series_list = []
                    for col in pivot_df.columns:
                        if col != x_col:
                            series_list.append(ChartSeries(data_key=col, label=col))
                            
                    chart_component = AreaChart(
                        data=chart_data,
                        series=series_list,
                        x_axis=x_col,
                        stacked=True,
                    )
            elif isinstance(spec, dict) and "layer" in spec:
                # Layered specs: plot multiple indicators on the same cartesian axes
                layers = spec["layer"]
                series_list = []
                for i, layer in enumerate(layers):
                    if not isinstance(layer, dict):
                        continue
                    layer_y = layer.get("encoding", {}).get("y", {})
                    layer_val_col = layer_y.get("field", "").lower() if isinstance(layer_y, dict) else ""
                    if layer_val_col and layer_val_col in df.columns:
                        title_text = layer_y.get("axis", {}).get("title") if isinstance(layer_y.get("axis"), dict) else ""
                        if not title_text:
                            title_text = layer_val_col.replace("_", " ").title()
                        series_list.append(ChartSeries(data_key=layer_val_col, label=title_text))
                        
                if series_list and x_col:
                    df_clean = df.where(pd.notnull(df), None)
                    chart_data = df_clean.to_dict(orient="records")
                    
                    # Check if it uses bar marks
                    is_bar = any("bar" in str(l.get("mark", "")) for l in layers) or "bar" in strategy_lower
                    if is_bar:
                        chart_component = BarChart(
                            data=chart_data,
                            series=series_list,
                            x_axis=x_col,
                        )
                    else:
                        chart_component = LineChart(
                            data=chart_data,
                            series=series_list,
                            x_axis=x_col,
                        )
            elif "temporal" in strategy_lower:
                # Time-series data
                # Determine group column (e.g., country/region) for pivoting
                group_col = ""
                for possible_group in ["ref_area", "country", "country_code"]:
                    if possible_group in df.columns:
                        group_col = possible_group
                        break

                # If there are multiple series
                if group_col and df[group_col].nunique() > 1 and x_col and val_col:
                    # Pivot: index=x_col, columns=group_col, values=val_col
                    pivot_df = df.pivot(index=x_col, columns=group_col, values=val_col)
                    pivot_df = pivot_df.reset_index()
                    pivot_df = pivot_df.where(pd.notnull(pivot_df), None)
                    chart_data = pivot_df.to_dict(orient="records")
                    
                    # Each column other than x_col is a series line
                    series_list = []
                    for col in pivot_df.columns:
                        if col != x_col:
                            series_list.append(ChartSeries(data_key=col, label=col))
                    
                    chart_component = LineChart(
                        data=chart_data,
                        series=series_list,
                        x_axis=x_col,
                    )
                else:
                    # Single series time-series
                    df_clean = df.where(pd.notnull(df), None)
                    chart_data = df_clean.to_dict(orient="records")
                    
                    label = spec.get("title", {}).get("text", "Value") if isinstance(spec.get("title"), dict) else "Value"
                    chart_component = LineChart(
                        data=chart_data,
                        series=[ChartSeries(data_key=val_col, label=label)],
                        x_axis=x_col,
                    )
            elif "cross_sectional" in strategy_lower:
                # Country comparison for a single year
                if x_col and val_col:
                    df_sorted = df.sort_values(by=val_col, ascending=False)
                    df_clean = df_sorted.where(pd.notnull(df_sorted), None)
                    chart_data = df_clean.to_dict(orient="records")
                    
                    label = spec.get("title", {}).get("text", "Value") if isinstance(spec.get("title"), dict) else "Value"
                    chart_component = BarChart(
                        data=chart_data,
                        series=[ChartSeries(data_key=val_col, label=label)],
                        x_axis=x_col,
                        horizontal=True,
                    )
        except Exception:
            pass

    # 3. Fallback: If no chart component generated (or for choropleth maps/unsupported strategies), show a clean DataTable
    if chart_component is None:
        if data_rows:
            df = pd.DataFrame(data_rows)
            df_clean = df.where(pd.notnull(df), None)
            table_data = df_clean.to_dict(orient="records")
            
            # Generate DataTableColumn for each column
            columns = []
            for col in df.columns:
                columns.append(DataTableColumn(key=col, header=col.replace("_", " ").title()))
                
            chart_component = DataTable(
                rows=table_data,
                columns=columns,
                search=True,
            )
        else:
            chart_component = Markdown(content="No data or visualization available.")

    # 4. Build Card Structure
    title = "Data360 Visualization"
    real_subtitle = ""
    if isinstance(spec, dict) and isinstance(spec.get("title"), dict):
        title_val = spec["title"].get("text", "Data360 Visualization")
        if isinstance(title_val, list):
            title = " ".join(str(t) for t in title_val if t)
        else:
            title = str(title_val)
        sub_val = spec["title"].get("subtitle")
        if isinstance(sub_val, list):
            real_subtitle = " · ".join(str(s) for s in sub_val if s)
        elif sub_val:
            real_subtitle = str(sub_val)
    elif isinstance(spec, dict) and isinstance(spec.get("title"), str):
        title = spec["title"]
    
    card_header_children = [CardTitle(content=title)]
    if real_subtitle:
        card_header_children.append(CardDescription(content=real_subtitle))
    elif subtitle_line:
        card_header_children.append(CardDescription(content=subtitle_line))
        
    card_children = [
        CardHeader(children=card_header_children)
    ]
    
    card_children.append(CardContent(children=[chart_component]))
        
    footer_text = []
    if source_line:
        footer_text.append(source_line)
        
    if footer_text:
        card_children.append(CardFooter(children=[Markdown(content="\n\n".join(footer_text))]))

    children.append(Card(children=card_children))
    return Container(children=children)


def spec_to_prefab_and_summary(
    spec: dict[str, Any] | None,
    strategy: str,
    reason: str,
    warning: str | None = None,
    source_line: str | None = None,
    subtitle_line: str | None = None,
    url: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Map a Vega-Lite spec to prefab_ui app json and a text summary/table."""
    from prefab_ui.app import PrefabApp
    
    prefab_comp = spec_to_prefab(
        spec=spec,
        strategy=strategy,
        reason=reason,
        warning=warning,
        source_line=source_line,
        subtitle_line=subtitle_line,
    )
    app_json = PrefabApp(view=prefab_comp).to_json()

    # Generate Markdown summary table
    data_rows = []
    if isinstance(spec, dict) and "data" in spec and "values" in spec["data"]:
        data_rows = spec["data"]["values"]

    lines = []
    if warning:
        lines.append(f"### ⚠️ Warning\n{warning}\n")

    lines.append(f"### 📊 Data Summary ({strategy})")
    lines.append(reason)
    if subtitle_line:
        lines.append(f"*{subtitle_line}*")
    lines.append("")

    if data_rows:
        try:
            import pandas as pd
            df = pd.DataFrame(data_rows)
            # Reorder columns to place time_period and ref_area first if present
            cols = list(df.columns)
            preferred = ["TIME_PERIOD", "time_period", "REF_AREA", "ref_area"]
            for p in reversed(preferred):
                if p in cols:
                    cols.remove(p)
                    cols.insert(0, p)
            df = df[cols]
            
            headers = [col.replace("_", " ").title() for col in df.columns]
            header_line = "| " + " | ".join(headers) + " |"
            separator_line = "| " + " | ".join(["---"] * len(df.columns)) + " |"
            row_lines = []
            for _, row in df.iterrows():
                vals = []
                for col in df.columns:
                    val = row[col]
                    if val is None:
                        vals.append("")
                    elif isinstance(val, float):
                        vals.append(f"{val:,.2f}")
                    else:
                        vals.append(str(val))
                row_lines.append("| " + " | ".join(vals) + " |")
            lines.append("\n".join([header_line, separator_line] + row_lines))
        except Exception:
            lines.append("No tabular data available.")
    else:
        lines.append("No data available.")

    if source_line:
        lines.append(f"\n*{source_line}*")
    if url:
        lines.append(f"\n*Vega-Lite Spec URL:* {url}")

    return app_json, "\n".join(lines)


async def _get_viz_spec(
    database_id: str,
    indicator_id: str,
    country_code: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict[str, Any] | None = None,
    chart_type: str | None = None,
    relevant_fields: list[str] | None = None,
    custom_constraints: list[str] | None = None,
    use_default_constraints: bool = True,
    chart_title: str | dict | None = None,
    series_labels: dict[str, str] | None = None,
    strategy_override: str | None = None,
    year: int | None = None,
) -> ToolResult:
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
        chart_type: Optional chart type suggestion. If omitted (recommended), the routing engine automatically determines the optimal chart type and strategy based on the data profile. Do not specify this argument unless the user explicitly requested a specific chart type.
        relevant_fields: Fields to include in visual encodings.
        custom_constraints: Custom Draco design rules.
        use_default_constraints: Whether to apply default Draco design constraints.
        chart_title: A concise, human-synthesized title summarizing the data insight (e.g. 'Renewable Energy Share in South Asia (2020)'). Prefer clean, natural phrasing instead of raw long indicator names.
        series_labels: Rename dimension codes for legend (e.g. {"WGI_EST": "Estimate"}).
        strategy_override: Explicitly force a chart strategy (e.g. "stacked_bar", "temporal_single").
        year: Specific single year to generate the chart for. Maps internally to start_year and end_year.
    """
    if year is not None:
        if start_year is None:
            start_year = year
        if end_year is None:
            end_year = year

    norm_filters = _normalize_disaggregation_filters(disaggregation_filters)

    res = await data360_viz.get_viz_spec(
        database_id=database_id,
        indicator_id=indicator_id,
        country_code=country_code,
        start_year=start_year,
        end_year=end_year,
        disaggregation_filters=norm_filters,
        chart_type=chart_type,
        relevant_fields=relevant_fields,
        custom_constraints=custom_constraints,
        use_default_constraints=use_default_constraints,
        chart_title=chart_title,
        series_labels=series_labels,
        strategy_override=strategy_override,
    )

    if res.get("error"):
        raise ToolError(res["error"])

    url = res.get("url")
    strategy = res.get("strategy") or "unknown"
    reason = res.get("reason") or ""
    warning = res.get("warning")
    source_line = res.get("source_line")
    subtitle_line = res.get("subtitle_line")

    spec = None
    if url:
        try:
            spec_id = url.split("/")[-1].replace("_vega.json", "")
            if os.environ.get("PYTEST_CURRENT_TEST"):
                specs_dir = os.path.join(os.getcwd(), "static", "viz_specs")
            else:
                server_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.abspath(os.path.join(server_dir, "..", "..", ".."))
                specs_dir = os.path.join(project_root, "static", "viz_specs")
            vega_path = os.path.join(specs_dir, f"{spec_id}_vega.json")
            if os.path.exists(vega_path):
                with open(vega_path, "r") as f:
                    spec = json.load(f)
        except Exception:
            pass

    app_json, text_summary = spec_to_prefab_and_summary(
        spec=spec,
        strategy=strategy,
        reason=reason,
        warning=warning,
        source_line=source_line,
        subtitle_line=subtitle_line,
        url=url,
    )

    payload = {
        "spec": spec,
        "strategy": strategy,
    }
    return ToolResult(
        content=[
            TextContent(type="text", text=json.dumps(payload)),
            TextContent(type="text", text=text_summary),
        ],
        structured_content=app_json,
    )


async def _get_multi_indicator_viz_spec(
    indicator_ids: list[dict[str, str]] | None = None,
    country_code: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict[str, Any] | None = None,
    chart_type: str | None = None,
    chart_title: str | dict | None = None,
    series_labels: dict[str, str] | None = None,
    strategy_override: str | None = None,
    year: int | None = None,
) -> ToolResult:
    """Generate a Vega-Lite chart comparing multiple Data360 indicators.

    Use when you need to compare 2–4 indicators (e.g. via scatterplot or dual-axis line chart).
    Ensure the database IDs and indicator IDs are already in context before using this tool. Do not guess or hallucinate these IDs.

    Args:
        indicator_ids: List of database/indicator dicts, e.g. [{"database_id": "WB_WDI", "indicator_id": "..."}].
        country_code: Semicolon-separated ISO country codes (e.g. "KEN;USA").
        start_year: Start year (inclusive). Defaults to last 5 years if omitted.
        end_year: End year (inclusive). Defaults to current year if omitted.
        disaggregation_filters: Optional dimension filters.
        chart_type: Optional chart type suggestion. If omitted (recommended), the routing engine automatically determines the optimal chart type and strategy based on the data profile. Do not specify this argument unless the user explicitly requested a specific chart type.
        chart_title: A concise, human-synthesized title summarizing the data insight (e.g. 'Renewable Energy Share in South Asia (2020)'). Prefer clean, natural phrasing instead of raw long indicator names.
        series_labels: Rename dimension codes for legend.
        strategy_override: Explicitly force a chart strategy (e.g. "stacked_bar", "vconcat_panels").
        year: Specific single year to compare indicators for. Maps internally to start_year and end_year.
    """
    if year is not None:
        if start_year is None:
            start_year = year
        if end_year is None:
            end_year = year

    norm_filters = _normalize_disaggregation_filters(disaggregation_filters)

    res = await data360_viz.get_multi_indicator_viz_spec(
        indicator_ids=indicator_ids,
        country_code=country_code,
        start_year=start_year,
        end_year=end_year,
        disaggregation_filters=norm_filters,
        chart_type=chart_type,
        chart_title=chart_title,
        series_labels=series_labels,
        strategy_override=strategy_override,
    )

    if res.get("error"):
        raise ToolError(res["error"])

    url = res.get("url")
    strategy = res.get("strategy") or "unknown"
    reason = res.get("reason") or ""
    warning = res.get("warning")
    source_line = res.get("source_line")
    subtitle_line = res.get("subtitle_line")

    spec = None
    if url:
        try:
            spec_id = url.split("/")[-1].replace("_vega.json", "")
            if os.environ.get("PYTEST_CURRENT_TEST"):
                specs_dir = os.path.join(os.getcwd(), "static", "viz_specs")
            else:
                server_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.abspath(os.path.join(server_dir, "..", "..", ".."))
                specs_dir = os.path.join(project_root, "static", "viz_specs")
            vega_path = os.path.join(specs_dir, f"{spec_id}_vega.json")
            if os.path.exists(vega_path):
                with open(vega_path, "r") as f:
                    spec = json.load(f)
        except Exception:
            pass

    app_json, text_summary = spec_to_prefab_and_summary(
        spec=spec,
        strategy=strategy,
        reason=reason,
        warning=warning,
        source_line=source_line,
        subtitle_line=subtitle_line,
        url=url,
    )

    payload = {
        "spec": spec,
        "strategy": strategy,
    }
    return ToolResult(
        content=[
            TextContent(type="text", text=json.dumps(payload)),
            TextContent(type="text", text=text_summary),
        ],
        structured_content=app_json,
    )


def _get_supported_chart_types() -> str:
    """Return supported chart types and their data requirements as JSON.

    **DEPRECATED**: Read the ``data360://viz/chart-grammar`` resource instead.
    This tool is preserved for backward compatibility.
    """
    import json

    result = data360_viz.get_supported_chart_types()
    parsed = json.loads(result)
    parsed["_deprecation_notice"] = (
        "This tool is deprecated. Read the data360://viz/chart-grammar resource "
        "for comprehensive chart strategy rules. The data_profile in every viz "
        "response now includes per-indicator ranges and scale compatibility."
    )
    return json.dumps(parsed, indent=2)


async def _explain_chart_routing(
    n_indicators: int,
    country_count: int,
    year_count: int,
    avg_years_per_country: float,
    breakdown_dims: list[str] | None = None,
    chart_type_hint: str | None = None,
    scale_type: str | None = None,
    indicator_scales: list[dict] | None = None,
) -> Any:
    """Explain which chart strategy the routing engine would select for the given data shape."""
    return data360_viz_config.explain_chart_routing(
        n_indicators=n_indicators,
        country_count=country_count,
        year_count=year_count,
        avg_years_per_country=avg_years_per_country,
        breakdown_dims=breakdown_dims,
        chart_type_hint=chart_type_hint,
        scale_type=scale_type,
        indicator_scales=indicator_scales,
    )


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
    disaggregation_filters: dict[str, Any] | None = None,
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
    norm_filters = _normalize_disaggregation_filters(disaggregation_filters)

    return await data360_api.summarize_data(
        database_id=database_id,
        indicator_id=indicator_id,
        country_code=country_code,
        disaggregation_filters=norm_filters,
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
    disaggregation_filters: dict[str, Any] | None = None,
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
    norm_filters = _normalize_disaggregation_filters(disaggregation_filters)

    return await data360_api.rank_countries(
        database_id=database_id,
        indicator_id=indicator_id,
        country_group=country_group,
        country_codes=country_codes,
        year=year,
        order=order,
        top_n=top_n,
        disaggregation_filters=norm_filters,
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
    disaggregation_filters: dict[str, Any] | None = None,
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
    norm_filters = _normalize_disaggregation_filters(disaggregation_filters)

    return await data360_api.compare_countries(
        database_id=database_id,
        indicator_id=indicator_id,
        country_codes=country_codes,
        year=year,
        include_time_series=include_time_series,
        start_year=start_year,
        end_year=end_year,
        disaggregation_filters=norm_filters,
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
    app=AppConfig(resource_uri="ui://data360-chart/index.html"),
)

get_multi_indicator_viz_spec = mcp.tool(
    instrument_mcp_tool(
        _get_multi_indicator_viz_spec,
        tool_name="data360_get_multi_indicator_viz_spec",
    ),
    name="data360_get_multi_indicator_viz_spec",
    app=AppConfig(resource_uri="ui://data360-chart/index.html"),
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

explain_chart_routing = mcp.tool(
    instrument_mcp_tool(
        _explain_chart_routing, tool_name="data360_explain_chart_routing"
    ),
    name="data360_explain_chart_routing",
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


# ---------------------------------------------------------------------------
# Custom HTML Explorer App
# ---------------------------------------------------------------------------


@mcp.resource("ui://data360-explorer/index.html")
def data360_explorer_html() -> str:
    """HTML resource for the Data360 indicator explorer Custom HTML app."""
    return """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Data360 Indicator Explorer</title>
  <style>
    body {
      margin: 0;
      padding: 12px;
      background: transparent;
      color: #cbd5e1;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    .search-bar {
      display: flex;
      gap: 8px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }
    input, select, button {
      padding: 8px 12px;
      border-radius: 6px;
      border: 1px solid #475569;
      background: #1e293b;
      color: #f8fafc;
      font-size: 14px;
      box-sizing: border-box;
    }
    input {
      flex: 1;
      min-width: 200px;
    }
    select {
      min-width: 150px;
    }
    button {
      background: #3b82f6;
      color: white;
      border: none;
      cursor: pointer;
      font-weight: 600;
      transition: background 0.2s;
    }
    button:hover {
      background: #2563eb;
    }
    .subtitle {
      font-size: 12px;
      color: #94a3b8;
      margin-bottom: 12px;
    }
    .indicator-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .indicator-card {
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 12px;
      cursor: pointer;
      transition: background-color 0.2s, border-color 0.2s;
    }
    .indicator-card:hover {
      background: #334155;
      border-color: #3b82f6;
    }
    .indicator-name {
      font-weight: 600;
      font-size: 14px;
      color: #f8fafc;
      margin-bottom: 4px;
    }
    .indicator-meta {
      font-size: 11px;
      color: #94a3b8;
      display: flex;
      justify-content: space-between;
      margin-bottom: 6px;
    }
    .indicator-desc {
      font-size: 12px;
      color: #94a3b8;
      line-height: 1.4;
    }
  </style>
</head>
<body>
  <div class="search-bar">
    <input type="text" id="search-input" placeholder="Search indicators...">
    <select id="db-select">
      <option value="">All Databases</option>
      <option value="wdi">World Development Indicators (WDI)</option>
      <option value="hnp">Health Nutrition & Population (HNP)</option>
      <option value="pip">Poverty & Inequality (PIP)</option>
    </select>
    <button id="search-btn">Search</button>
  </div>
  <div id="subtitle" class="subtitle">Enter keywords to search.</div>
  <div class="indicator-list" id="list"></div>

  <script type="module">
    class McpAppClient {
      constructor() {
        this.pendingRequests = new Map();
        this.requestId = 0;
        this.initialized = false;
        this.hostContext = null;
        window.addEventListener('message', (e) => this.handleMessage(e));
        this.initialize();
      }

      async initialize() {
        try {
          const result = await this.request('ui/initialize', {
            appInfo: { name: 'Data360 Explorer', version: '1.0.0' },
            appCapabilities: {},
            protocolVersion: '2025-11-21'
          });
          this.hostContext = result.hostContext;
          this.initialized = true;
          this.notify('ui/notifications/initialized', {});
          this.reportSize();
        } catch (error) {
          console.error('Failed to initialize MCP App:', error);
        }
      }

      handleMessage(event) {
        const data = event.data;
        if (!data || typeof data !== 'object') return;
        if ('id' in data && this.pendingRequests.has(data.id)) {
          const { resolve, reject } = this.pendingRequests.get(data.id);
          this.pendingRequests.delete(data.id);
          if (data.error) {
            reject(new Error(data.error.message));
          } else {
            resolve(data.result);
          }
          return;
        }
        if (data.method === 'ui/notifications/tool-result') {
          try {
            const result = data.params;
            const content = result.content;
            const textBlock = content.find(c => c.type === 'text');
            if (textBlock) {
              const payload = JSON.parse(textBlock.text);
              if (payload.query && !document.getElementById('search-input').value) {
                document.getElementById('search-input').value = payload.query;
              }
              renderIndicators(payload);
            }
          } catch (e) {
            console.error('Error parsing tool result:', e);
          }
        }
      }

      request(method, params) {
        return new Promise((resolve, reject) => {
          const id = ++this.requestId;
          this.pendingRequests.set(id, { resolve, reject });
          window.parent.postMessage({ jsonrpc: '2.0', id, method, params }, '*');
          setTimeout(() => {
            if (this.pendingRequests.has(id)) {
              this.pendingRequests.delete(id);
              reject(new Error('Request timed out'));
            }
          }, 30000);
        });
      }

      notify(method, params) {
        window.parent.postMessage({ jsonrpc: '2.0', method, params }, '*');
      }

      reportSize() {
        this.notify('ui/notifications/size-changed', {
          height: document.body.scrollHeight
        });
      }

      async sendMessageToChat(text) {
        return this.request('ui/message', {
          role: 'user',
          content: [{ type: 'text', text }]
        });
      }
    }

    const mcpApp = new McpAppClient();
    const listDiv = document.getElementById('list');
    const subtitleDiv = document.getElementById('subtitle');
    const searchInput = document.getElementById('search-input');
    const dbSelect = document.getElementById('db-select');
    const searchBtn = document.getElementById('search-btn');

    function renderIndicators(payload) {
      const indicators = payload.indicators || [];
      const query = payload.query || "";
      subtitleDiv.textContent = `Found ${indicators.length} indicators for query: "${query}"`;
      listDiv.innerHTML = "";
      
      if (indicators.length === 0) {
        listDiv.innerHTML = '<div style="text-align:center; padding:20px; color:#94a3b8;">No indicators found.</div>';
        mcpApp.reportSize();
        return;
      }

      indicators.forEach(ind => {
        const card = document.createElement('div');
        card.className = 'indicator-card';
        
        const nameDiv = document.createElement('div');
        nameDiv.className = 'indicator-name';
        nameDiv.textContent = ind.name;
        
        const metaDiv = document.createElement('div');
        metaDiv.className = 'indicator-meta';
        metaDiv.innerHTML = `<span>Source: ${ind.database_name}</span><span>Years: ${ind.time_period_range || "N/A"}</span>`;
        
        card.appendChild(nameDiv);
        card.appendChild(metaDiv);
        
        if (ind.truncated_definition) {
          const descDiv = document.createElement('div');
          descDiv.className = 'indicator-desc';
          descDiv.textContent = ind.truncated_definition;
          card.appendChild(descDiv);
        }
        
        card.addEventListener('click', async () => {
          try {
            await mcpApp.sendMessageToChat(`Let's plot the indicator: "${ind.name}" (ID: ${ind.idno}, Database: ${ind.database_id})`);
          } catch (err) {
            console.error(err);
          }
        });
        
        listDiv.appendChild(card);
      });
      
      setTimeout(() => {
        mcpApp.reportSize();
      }, 50);
    }

    let debounceTimeout;
    async function triggerSearch() {
      clearTimeout(debounceTimeout);
      const query = searchInput.value.trim();
      const db = dbSelect.value;
      if (!query) return;

      subtitleDiv.textContent = "Searching indicators...";
      try {
        const res = await fetch(`/api/indicators/search?query=${encodeURIComponent(query)}&database=${encodeURIComponent(db)}`);
        const payload = await res.json();
        renderIndicators({ query, indicators: payload.indicators });
      } catch (err) {
        subtitleDiv.textContent = "Search failed: " + err.message;
      }
    }

    searchInput.addEventListener('input', () => {
      clearTimeout(debounceTimeout);
      debounceTimeout = setTimeout(triggerSearch, 300);
    });
    dbSelect.addEventListener('change', triggerSearch);
    searchBtn.addEventListener('click', triggerSearch);

    window.addEventListener('load', () => {
      mcpApp.reportSize();
    });
  </script>
</body>
</html>
"""


@mcp.tool(
    name="data360_indicator_explorer",
    app=AppConfig(resource_uri="ui://data360-explorer/index.html"),
)
async def data360_indicator_explorer(
    query: str,
    database: Optional[str] = None,
) -> ToolResult:
    """Interactively explore and search World Bank Data360 development indicators.

    Use when the user wants to browse, search, and select specific development indicators or variables.

    Args:
        query: Search term (e.g. 'GDP', 'poverty', 'education').
        database: Optional database ID filter (e.g. 'wdi', 'pip').
    """
    res = await data360_search_indicators_internal(query=query, database=database)
    
    payload = {
        "query": query,
        "indicators": res
    }
    
    return ToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))]
    )
@mcp.resource("ui://data360-chart/index.html")
def data360_chart_html() -> str:
    """HTML resource for the Data360 self-contained Vega-Lite chart viewer Custom HTML app."""
    vega_js, vega_lite_js, vega_embed_js, vega_interpreter_js = get_cached_vega_libs()
    html_template = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Data360 Vega-Lite Renderer</title>
  <style>
    body {
      margin: 0;
      padding: 8px;
      background: transparent;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    #vis {
      width: 100%;
      height: 100%;
      min-height: 400px;
    }
  </style>
  <script>{vega_js}</script>
  <script>{vega_interpreter_js}</script>
  <script>{vega_lite_js}</script>
  <script>{vega_embed_js}</script>
</head>
<body>
  <div id="vis"></div>

  <script type="module">
    class McpAppClient {
      constructor() {
        this.pendingRequests = new Map();
        this.requestId = 0;
        this.initialized = false;
        this.hostContext = null;
        window.addEventListener('message', (e) => this.handleMessage(e));
        this.initialize();
      }

      async initialize() {
        try {
          const result = await this.request('ui/initialize', {
            appInfo: { name: 'Data360 Chart', version: '1.0.0' },
            appCapabilities: {},
            protocolVersion: '2025-11-21'
          });
          this.hostContext = result.hostContext;
          this.initialized = true;
          this.notify('ui/notifications/initialized', {});
          this.reportSize();
        } catch (error) {
          console.error('Failed to initialize MCP App:', error);
        }
      }

      handleMessage(event) {
        const data = event.data;
        if (!data || typeof data !== 'object') return;
        if ('id' in data && this.pendingRequests.has(data.id)) {
          const { resolve, reject } = this.pendingRequests.get(data.id);
          this.pendingRequests.delete(data.id);
          if (data.error) {
            reject(new Error(data.error.message));
          } else {
            resolve(data.result);
          }
          return;
        }
        if (data.method === 'ui/notifications/tool-result') {
          try {
            const result = data.params;
            let spec = null;
            let strategy = null;
            if (result.structuredContent) {
              spec = result.structuredContent.spec;
              strategy = result.structuredContent.strategy;
            }
            if (!spec && result.content) {
              const textBlock = result.content.find(c => c.type === 'text');
              if (textBlock) {
                try {
                  const payload = JSON.parse(textBlock.text);
                  spec = payload.spec;
                  strategy = payload.strategy;
                } catch (e) {
                  // Ignore JSON parse error for plain text
                }
              }
            }
            renderChart(spec, strategy);
          } catch (e) {
            console.error('Error parsing tool result:', e);
          }
        }
      }

      request(method, params) {
        return new Promise((resolve, reject) => {
          const id = ++this.requestId;
          this.pendingRequests.set(id, { resolve, reject });
          window.parent.postMessage({ jsonrpc: '2.0', id, method, params }, '*');
          setTimeout(() => {
            if (this.pendingRequests.has(id)) {
              this.pendingRequests.delete(id);
              reject(new Error('Request timed out'));
            }
          }, 30000);
        });
      }

      notify(method, params) {
        window.parent.postMessage({ jsonrpc: '2.0', method, params }, '*');
      }

      reportSize() {
        this.notify('ui/notifications/size-changed', {
          height: document.body.scrollHeight
        });
      }
    }

    const mcpApp = new McpAppClient();
    const visDiv = document.getElementById('vis');

    function renderChart(spec, strategy) {
      if (!spec) {
        visDiv.innerHTML = '<p>No visualization spec available</p>';
        mcpApp.reportSize();
        return;
      }
      
      try {
        vegaEmbed("#vis", spec, {
          actions: false,
          theme: mcpApp.hostContext?.theme === 'dark' ? 'dark' : 'default',
          ast: true,
          expr: vega.expressionInterpreter
        }).then(() => {
          mcpApp.reportSize();
        }).catch(err => {
          console.error(err);
          visDiv.innerHTML = `<p style="color:red;">Failed to render chart spec: ${err.message}</p>`;
          mcpApp.reportSize();
        });
      } catch (e) {
        visDiv.innerHTML = `<p style="color:red;">Error preparing spec: ${e.message}</p>`;
        mcpApp.reportSize();
      }
    }

    window.addEventListener('load', () => {
      mcpApp.reportSize();
    });
  </script>
</body>
</html>
"""
    return html_template.replace("{vega_js}", vega_js).replace("{vega_lite_js}", vega_lite_js).replace("{vega_embed_js}", vega_embed_js).replace("{vega_interpreter_js}", vega_interpreter_js)


@mcp.tool(name="data360_search_indicators_internal")
async def data360_search_indicators_internal(
    query: str,
    database: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Helper internal tool to return a clean list of indicators for the UI app."""
    if not query.strip():
        return []
    res = await _search_indicators(query=query, database=database, limit=limit)
    indicators_data = []
    if hasattr(res, "indicators") and res.indicators:
        for ind in res.indicators:
            indicators_data.append({
                "idno": ind.idno,
                "database_id": ind.database_id,
                "database_name": ind.database_name,
                "name": ind.name,
                "truncated_definition": ind.truncated_definition,
                "time_period_range": ind.time_period_range,
            })
    return indicators_data

