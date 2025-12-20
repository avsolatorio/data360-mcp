from data360 import api as data360_api

from ._server_definition import app

# directly wrap function as tool
# can redefine with decorator if implementation override required
# can add more metadata like description, etc as parameters to tool decorator call
search_indicators = app.tool(
    data360_api.search,
    name="data360_search_indicators",
)
get_metadata = app.tool(
    data360_api.get_metadata,
    name="data360_get_metadata",
)

get_data = app.tool(
    data360_api.get_data,
    name="data360_get_data",
)
