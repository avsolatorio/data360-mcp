from fastmcp import FastMCP

# NOTE: base definition to allow for mounting of resources, prompts, tools, independently
mcp = FastMCP(
    "Data360 MCP Server",
    version="0.1.0",
    include_fastmcp_meta=False,
)
