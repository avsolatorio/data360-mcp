from ._server_definition import mcp


@mcp.resource("users://{query}/profile")
async def data360_resource(query: str) -> str:
    """
    Get a resource from the Data360 MCP Server.
    """
    return f"Data360 MCP Server says hello to {query}! resource!"
