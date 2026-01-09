from data360.mcp_server import mcp

# NOTE: import to be able to run the server with all definitions loaded

# https://gofastmcp.com/deployment/http#asgi-application
app = mcp.http_app()  # pyright: ignore[reportUnusedExpression]
