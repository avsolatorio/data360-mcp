"""MCP Tools for the Data360 server.

Thin wrapper layer that registers API functions as MCP tools.
All business logic and tool descriptions live in the docstrings of the
underlying functions in api.py, providers.py, and visualization.py.
"""

from fastmcp.server.apps import AppConfig

from data360 import api as data360_api
from data360 import providers as data360_providers
from data360 import visualization as data360_viz

from ._server_definition import mcp
from .apps_resources import CHART_VIEW_URI, SEARCH_VIEW_URI

# Wire format for MCP Apps: tool _meta must include ui.resourceUri so clients
# (e.g. Claude) show the app iframe. We pass both app= and meta= so the tool
# definition always includes this. Include legacy "ui/resourceUri" for older
# hosts (see ext-apps examples e.g. say-server).
_SEARCH_APP_META = {
    "ui": {"resourceUri": SEARCH_VIEW_URI},
    "ui/resourceUri": SEARCH_VIEW_URI,
}
_CHART_APP_META = {
    "ui": {"resourceUri": CHART_VIEW_URI},
    "ui/resourceUri": CHART_VIEW_URI,
}

search_indicators = mcp.tool(
    data360_api.search,
    name="data360_search_indicators",
    description=data360_api.search.__doc__,
    app=AppConfig(resource_uri=SEARCH_VIEW_URI, visibility=["app", "model"]),
    meta=_SEARCH_APP_META,
)

get_metadata = mcp.tool(
    data360_api.get_metadata,
    name="data360_get_metadata",
    description=data360_api.get_metadata.__doc__,
)

get_data = mcp.tool(
    data360_api.get_data,
    name="data360_get_data",
    description=data360_api.get_data.__doc__,
)

get_disaggregation = mcp.tool(
    data360_api.get_disaggregation,
    name="data360_get_disaggregation",
    description=data360_api.get_disaggregation.__doc__,
)

find_codelist_value = mcp.tool(
    data360_providers.find_codelist_value,
    name="data360_find_codelist_value",
    description=data360_providers.find_codelist_value.__doc__,
)

list_indicators = mcp.tool(
    data360_api.get_indicators,
    name="data360_list_indicators",
    description=data360_api.get_indicators.__doc__,
)

get_data_api_url = mcp.tool(
    data360_api.get_data_api_url,
    name="data360_get_data_api_url",
    description="[LOW-LEVEL] " + (data360_api.get_data_api_url.__doc__ or ""),
)

get_viz_spec = mcp.tool(
    data360_viz.get_viz_spec,
    name="data360_get_viz_spec",
    description=data360_viz.get_viz_spec.__doc__,
    app=AppConfig(resource_uri=CHART_VIEW_URI),
    meta=_CHART_APP_META,
)

get_supported_chart_types = mcp.tool(
    data360_viz.get_supported_chart_types,
    name="data360_get_supported_chart_types",
    description=data360_viz.get_supported_chart_types.__doc__,
)
