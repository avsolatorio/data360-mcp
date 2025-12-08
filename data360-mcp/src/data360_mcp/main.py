from fastmcp import FastMCP

mcp = FastMCP("My MCP Server")


@mcp.tool
def add(a: int, b: int) -> int:
    return a + b


@mcp.tool
def multiply(a: int, b: int) -> int:
    return a * b


@mcp.tool
def greet(name: str) -> str:
    return f"Hello, {name}! Welcome to Data360 MCP Server."


if __name__ == "__main__":
    mcp.run()
