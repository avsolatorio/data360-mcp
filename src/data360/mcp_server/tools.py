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

@mcp.tool()
async def data360_list_indicators(database_id: str) -> str:
    """List all indicator IDs available in a specific database.

    Use this tool to discover what indicators exist in a dataset before searching
    or to audit available data.

    Args:
        database_id: The database identifier (e.g. "WB_WDI", "WB_GS")
    
    Returns:
        A list of indicator ID strings.
    """
    try:
        from data360.api import get_indicators
        indicators = await get_indicators(database_id)
        return json.dumps(indicators, indent=2)
    except Exception as e:
        return f"Error listing indicators: {str(e)}"

# Primary search and validate tool
discover_indicators = mcp.tool(
    data360_api.discover_indicators,
    name="data360_discover_indicators",
    description=data360_api.discover_indicators.__doc__,
)
