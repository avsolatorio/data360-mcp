from data360_mcp.data360 import api as data360_api
from data360_mcp.data360.models import SearchRequest, SearchResponse
from data360_mcp.errors import Data360MCPLibraryError
from fastmcp import FastMCP

mcp = FastMCP("Data360 MCP Server")


@mcp.tool
async def data360_search(
    request: SearchRequest,
) -> SearchResponse:
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
    result: SearchResponse = await data360_api.search(**request.model_dump())
    if result.error:
        raise Data360MCPLibraryError(
            code="tool:data360_search_error", message=result.error
        )
    return result


if __name__ == "__main__":
    mcp.run(transport="http", port=8022)
