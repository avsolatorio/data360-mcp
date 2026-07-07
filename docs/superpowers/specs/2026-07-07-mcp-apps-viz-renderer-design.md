# Spec: MCP Apps Vega-Lite Rendering for Visualization Engine

Implement FastMCP version 3 Apps for the Data360 visualization engine to render interactive Vega-Lite v6 charts directly in app-supporting clients.

## Context & Background
Currently, the visualization tools (`data360_get_viz_spec` and `data360_get_multi_indicator_viz_spec`) return a dictionary containing the URL of the generated Vega-Lite spec JSON. Non-app clients display this dictionary or URL, and the user must open the URL in a browser to view the chart.

FastMCP v3 supports the Model Context Protocol (MCP) Apps extension. This allows tools to declare a UI HTML resource (`resource_uri`) that is loaded inside a sandboxed iframe to render structured data returned by the tool.

## Requirements
1. **FastMCP Version:** Pin `fastmcp==3.0.0` in `pyproject.toml` to avoid import errors present in the `3.4.x` oauth-proxy module.
2. **HTML Renderer:** Register a `ui://data360/vega-lite-renderer.html` resource.
   - Load Vega v5, Vega-Lite v6, and Vega-Embed v6 from jsDelivr.
   - Load the `@modelcontextprotocol/ext-apps` client from unpkg.
   - Allow these domains in the resource Content Security Policy (CSP).
   - Listen for `ontoolresult` and render `result.structuredContent.spec` using Vega-Embed.
3. **Visualization Tools integration:**
   - Decorate both visualization tools with `app=AppConfig(resource_uri="ui://data360/vega-lite-renderer.html")`.
   - Update the tools to return `ToolResult` from `fastmcp.tools` containing both `content` (text summary for standard client / LLM context) and `structured_content` (the Vega-Lite specification dictionary and metadata for the renderer).
4. **Backward Compatibility:**
   - Ensure clients that do not support Apps still receive a clean text description and URL.
   - Ensure all existing unit tests in `tests/` continue to pass.

## Proposed Changes

### Dependencies
- Modify `pyproject.toml` to change `"fastmcp>=2.12.4"` to `"fastmcp==3.0.0"`.

### Resources
- Register `ui://data360/vega-lite-renderer.html` in [resources.py](file:///Users/rafaelmacalaba/WBG/data360-mcp/src/data360/mcp_server/resources.py).
- Set `AppConfig(csp=ResourceCSP(resource_domains=["https://unpkg.com", "https://cdn.jsdelivr.net"]))`.

### Tools
- Import `AppConfig`, `ToolResult`, and `TextContent` in [tools.py](file:///Users/rafaelmacalaba/WBG/data360-mcp/src/data360/mcp_server/tools.py).
- Modify `get_viz_spec` and `get_multi_indicator_viz_spec` decorations and returns.

## Verification Plan
1. Run `uv run pytest` to ensure all existing unit tests pass.
2. Run the server locally and verify that the tools return a `ToolResult` structure.
