import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from data360.config import get_mcp_server_settings, setup_logging
from data360.mcp_server import mcp

# Setup logging from configuration
mcp_settings = get_mcp_server_settings()
setup_logging(log_file=mcp_settings.log_file, log_level=mcp_settings.log_level)

# NOTE: import to be able to run the server with all definitions loaded
# path="/mcp" means the MCP endpoint lives at /mcp (no trailing slash needed)
# stateless_http=True: new transport per request (horizontal scaling, e.g. Azure Web Apps)
mcp_app = mcp.http_app(path="/mcp", stateless_http=True)

# https://gofastmcp.com/deployment/http#asgi-application
# redirect_slashes=False prevents 308 redirects between /mcp and /mcp/
app = FastAPI(
    title="Data360 MCP Server",
    lifespan=mcp_app.lifespan,
    redirect_slashes=False,
)  # pyright: ignore[reportUnusedExpression]


# Mount MCP app at root — the path="/mcp" in http_app() handles the /mcp route
app.mount("/", mcp_app)
# Mount static files
static_dir = os.path.join(os.getcwd(), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Tools and other resources are automatically registered via imports in mcp_server/__init__.py
# See src/data360/mcp_server/tools.py for tool definitions
