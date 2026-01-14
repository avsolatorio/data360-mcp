from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastmcp.tools.tool import Tool

from data360.mcp_server import mcp


class DiscoveredTools:
    tools: dict[str, Tool] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    tools_dict = await mcp.get_tools()

    print(f"Discovered {len(tools_dict)} tools:")
    for tool_name, tool_info in tools_dict.items():
        DiscoveredTools.tools[tool_name] = tool_info
        print(f"  - {tool_name}")
        print(f"  - {tool_info}")
        create_tool_endpoint(tool_name, tool_info)

    yield


app = FastAPI(lifespan=lifespan)
app.mount("/mcp", mcp.http_app())


def create_tool_endpoint(tool_name: str, tool_info):
    """Create a FastAPI endpoint for a given tool"""

    async def endpoint(request_body: dict[str, Any] = Body(...)):
        try:
            # Get the actual function from tool_info
            if hasattr(tool_info, "fn"):
                tool_func = tool_info.fn
            elif hasattr(tool_info, "func"):
                tool_func = tool_info.func
            elif hasattr(tool_info, "_fn"):
                tool_func = tool_info._fn
            else:
                raise AttributeError(f"Cannot find callable in tool_info")

            # Call WITHOUT context - just pass the request body params
            result = await tool_func(**request_body)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    endpoint.__name__ = tool_name
    endpoint.__doc__ = tool_info.description

    app.add_api_route(
        f"/api/{tool_name}",
        endpoint,
        methods=["POST"],
        name=tool_name,
        tags=["Tools"],
        description=tool_info.description,
    )


@app.get("/api/tools")
async def list_tools():
    return {
        "tools": [
            {"name": name, "description": tool.description, "endpoint": f"/api/{name}"}
            for name, tool in DiscoveredTools.tools.items()
        ]
    }


@app.get("/")
async def root():
    return {"message": "Data360 MCP Server API", "docs": "/docs", "tools": "/api/tools"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
