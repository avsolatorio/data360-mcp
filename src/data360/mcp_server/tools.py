from data360 import api as data360_api
from data360 import providers as data360_providers

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

# Unified codelist lookup tool
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

# Primary search and validate tool
discover_indicators = mcp.tool(
    data360_api.discover_indicators,
    name="data360_discover_indicators",
    description=data360_api.discover_indicators.__doc__,
)
