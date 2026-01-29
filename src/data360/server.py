import os

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from data360.config import get_mcp_server_settings, setup_logging
from data360.mcp_server import mcp

# Setup logging from configuration
mcp_settings = get_mcp_server_settings()
setup_logging(log_file=mcp_settings.log_file, log_level=mcp_settings.log_level)

mcp.settings.stateless_http = True

# NOTE: import to be able to run the server with all definitions loaded
mcp_app = mcp.http_app(path="/")

# https://gofastmcp.com/deployment/http#asgi-application
app = FastAPI(
    title="Data360 MCP Server",
    # routes=[
    #     *mcp_app.routes,
    # ],
    lifespan=mcp_app.lifespan,
)  # pyright: ignore[reportUnusedExpression]


@app.api_route(
    "/mcp",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
def mcp_redirect():
    # Make sure to add this before the mount of the mcp_app
    return RedirectResponse(url="/mcp/", status_code=308)


app.mount("/mcp", mcp_app)
# Mount static files
static_dir = os.path.join(os.getcwd(), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Tools and other resources are automatically registered via imports in mcp_server/__init__.py
# See src/data360/mcp_server/tools.py for tool definitions
