from ._server_definition import app


@app.prompt
def data360_prompt(query: str) -> str:
    """
    Get a prompt from the Data360 MCP Server.
    """
    return f"Data360 MCP Server says hello to {query}! prompt!"
