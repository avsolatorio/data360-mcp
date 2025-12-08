from data360_mcp.data360 import api as data360_api
from fastmcp import FastMCP

mcp = FastMCP("Data360 MCP Server")


@mcp.tool
async def data360_search(
    query: str,
    n_results: int = 10,
    filter: str | None = None,
    orderby: str | None = None,
    select: str | None = None,
    skip: int = 0,
    count: bool = False,
) -> dict:
    """
    Search for data360 indicators using the World Bank Data360 API.

    Args:
        query: Search query string to find relevant data series
        n_results: Number of top results to return (default is 10)
        filter: OData filter expression (e.g., "type eq 'indicator'")
        orderby: OData orderby expression (e.g., "series_description/name")
        select: OData select expression (e.g., "series_description/idno, series_description/name")
        skip: Number of results to skip for pagination
        count: Whether to include total count in response
    """
    result = await data360_api.search(
        query=query,
        n_results=n_results,
        filter=filter,
        orderby=orderby,
        select=select,
        skip=skip,
        count=count,
    )
    return result.model_dump(by_alias=True)


@mcp.resource("users://{query}/profile")
async def data360_resource(query: str) -> str:
    """
    Get a resource from the Data360 MCP Server.
    """
    return f"Data360 MCP Server says hello to {query}! resource!"


@mcp.prompt
def data360_prompt(query: str) -> str:
    """
    Get a prompt from the Data360 MCP Server.
    """
    return f"Data360 MCP Server says hello to {query}! prompt!"


if __name__ == "__main__":
    mcp.run(transport="http", port=8000)
