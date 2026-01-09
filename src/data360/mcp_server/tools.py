from data360 import api as data360_api

from ._server_definition import mcp

# directly wrap function as tool
# can redefine with decorator if implementation override required
# can add more metadata like description, etc as parameters to tool decorator call
search_indicators = mcp.tool(
    data360_api.search,
    name="data360_search_indicators",
    description=data360_api.search.__doc__,
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
