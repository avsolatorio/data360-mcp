from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastmcp import FastMCP


@asynccontextmanager
async def _codelist_lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Fetch extdataportal codelists before the first request.

    Runs for every transport (streamable-http, stdio, SSE) because it is
    registered on the FastMCP object itself, not on the wrapping FastAPI app.
    """
    from data360.providers import get_codelist_manager

    await get_codelist_manager().initialize()
    yield


# NOTE: base definition to allow for mounting of resources, prompts, tools, independently
mcp = FastMCP("Data360 MCP Server", lifespan=_codelist_lifespan)
