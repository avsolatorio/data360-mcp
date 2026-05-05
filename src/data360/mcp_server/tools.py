"""MCP Tools for the Data360 server.

Thin wrapper layer that registers API functions as MCP tools.
All business logic and tool descriptions live in the docstrings of the
underlying functions in api.py, providers.py, and visualization.py.
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

    Calls ``to_compact()`` on the response model if available. This strips
    PCN claim_ids from the LLM-facing TextContent output — they are retained
    in the full Pydantic model (and in the MCP structured_content block)
    for data provenance verification, but they consume tokens without aiding
    the LLM's reasoning.

    For RankingResponse the excluded list is also capped at 5 sample entries
    (see RankingResponse.to_compact for details).

    For ComparisonTimeSeries the per-year series dict is dropped; the LLM
    receives only the year_range, n_aligned_years, convergence, and CAGR.

    Falls back to FastMCP's default pydantic_core serializer when the model
    has no to_compact() method (should not happen for these three tools but
    guards against future subclasses or unexpected return types).
    """
    if hasattr(data, "to_compact"):
        return json.dumps(data.to_compact(), separators=(",", ":"))
    return pydantic_core.to_json(data, fallback=str).decode()

search_indicators = mcp.tool(
    instrument_mcp_tool(data360_api.search, tool_name="data360_search_indicators"),
    name="data360_search_indicators",
    description=data360_api.search.__doc__,
)

get_metadata = mcp.tool(
    instrument_mcp_tool(data360_api.get_metadata, tool_name="data360_get_metadata"),
    name="data360_get_metadata",
    description=data360_api.get_metadata.__doc__,
)

get_data = mcp.tool(
    instrument_mcp_tool(data360_api.get_data, tool_name="data360_get_data"),
    name="data360_get_data",
    description=data360_api.get_data.__doc__,
)

get_disaggregation = mcp.tool(
    instrument_mcp_tool(
        data360_api.get_disaggregation, tool_name="data360_get_disaggregation"
    ),
    name="data360_get_disaggregation",
    description=data360_api.get_disaggregation.__doc__,
)

find_codelist_value = mcp.tool(
    instrument_mcp_tool(
        data360_providers.find_codelist_value, tool_name="data360_find_codelist_value"
    ),
    name="data360_find_codelist_value",
    description=data360_providers.find_codelist_value.__doc__,
)

list_indicators = mcp.tool(
    instrument_mcp_tool(data360_api.get_indicators, tool_name="data360_list_indicators"),
    name="data360_list_indicators",
    description=data360_api.get_indicators.__doc__,
)

get_data_api_url = mcp.tool(
    instrument_mcp_tool(
        data360_api.get_data_api_url, tool_name="data360_get_data_api_url"
    ),
    name="data360_get_data_api_url",
    description="[LOW-LEVEL] " + (data360_api.get_data_api_url.__doc__ or ""),
)

get_viz_spec = mcp.tool(
    instrument_mcp_tool(data360_viz.get_viz_spec, tool_name="data360_get_viz_spec"),
    name="data360_get_viz_spec",
    description=data360_viz.get_viz_spec.__doc__,
)

get_multi_indicator_viz_spec = mcp.tool(
    instrument_mcp_tool(
        data360_viz.get_multi_indicator_viz_spec,
        tool_name="data360_get_multi_indicator_viz_spec",
    ),
    name="data360_get_multi_indicator_viz_spec",
    description=data360_viz.get_multi_indicator_viz_spec.__doc__,
)

get_supported_chart_types = mcp.tool(
    instrument_mcp_tool(
        data360_viz.get_supported_chart_types,
        tool_name="data360_get_supported_chart_types",
    ),
    name="data360_get_supported_chart_types",
    description=data360_viz.get_supported_chart_types.__doc__,
)

expand_country_group = mcp.tool(
    instrument_mcp_tool(
        data360_providers.expand_country_group, tool_name="data360_expand_country_group"
    ),
    name="data360_expand_country_group",
    description=data360_providers.expand_country_group.__doc__,
)

# ---------------------------------------------------------------------------
# Data Aggregation Tools
# ---------------------------------------------------------------------------

summarize_data = mcp.add_tool(
    Tool.from_function(
        instrument_mcp_tool(data360_api.summarize_data, tool_name="data360_summarize_data"),
        name="data360_summarize_data",
        description=data360_api.summarize_data.__doc__,
        serializer=_compact_aggregation_serializer,
    )
)

rank_countries = mcp.add_tool(
    Tool.from_function(
        instrument_mcp_tool(data360_api.rank_countries, tool_name="data360_rank_countries"),
        name="data360_rank_countries",
        description=data360_api.rank_countries.__doc__,
        serializer=_compact_aggregation_serializer,
    )
)

compare_countries = mcp.add_tool(
    Tool.from_function(
        instrument_mcp_tool(
            data360_api.compare_countries, tool_name="data360_compare_countries"
        ),
        name="data360_compare_countries",
        description=data360_api.compare_countries.__doc__,
        serializer=_compact_aggregation_serializer,
    )
)


compute_derived = mcp.tool(
    instrument_mcp_tool(data360_api.compute_derived, tool_name="data360_compute_derived"),
    name="data360_compute_derived",
    description=data360_api.compute_derived.__doc__,
)

pivot_table = mcp.tool(
    instrument_mcp_tool(data360_api.pivot_table, tool_name="data360_pivot_table"),
    name="data360_pivot_table",
    description=data360_api.pivot_table.__doc__,
)

diagnostic_summary = mcp.tool(
    instrument_mcp_tool(
        data360_api.diagnostic_summary, tool_name="data360_diagnostic_summary"
    ),
    name="data360_diagnostic_summary",
    description=data360_api.diagnostic_summary.__doc__,
)
