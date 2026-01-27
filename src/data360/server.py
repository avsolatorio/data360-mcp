import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from data360.mcp_server import mcp

# NOTE: import to be able to run the server with all definitions loaded
mcp_app = mcp.http_app(path="/mcp")

# https://gofastmcp.com/deployment/http#asgi-application
app = FastAPI(
    title="Data360 MCP Server",
    routes=[
        *mcp_app.routes,
    ],
    lifespan=mcp_app.lifespan,
)  # pyright: ignore[reportUnusedExpression]

# Mount static files
static_dir = os.path.join(os.getcwd(), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Tools and other resources are automatically registered via imports in mcp_server/__init__.py
# See src/data360/mcp_server/tools.py for tool definitions
