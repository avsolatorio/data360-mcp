"""MCP Tools for the Data360 server.

Thin wrapper layer that registers API functions as MCP tools.
All business logic is in api.py.
"""

from data360 import api as data360_api
from data360 import providers as data360_providers

from ._server_definition import mcp


# Register tools - just wrap the API functions
search_indicators = mcp.tool(
    data360_api.search_indicators_enriched,
    name="data360_search_indicators",
    description=data360_api.search_indicators_enriched.__doc__,
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
