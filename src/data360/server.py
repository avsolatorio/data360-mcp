from data360.mcp_server import mcp

# NOTE: import to be able to run the server with all definitions loaded

# https://gofastmcp.com/deployment/http#asgi-application
app = mcp.http_app()  # pyright: ignore[reportUnusedExpression]

# Mount static files
from fastapi.staticfiles import StaticFiles
import os

static_dir = os.path.join(os.getcwd(), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Tools and other resources are automatically registered via imports in mcp_server/__init__.py
# See src/data360/mcp_server/tools.py for tool definitions

