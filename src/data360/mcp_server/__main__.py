import dotenv
import typer
from fastmcp.server.server import Transport

from data360.config import get_mcp_server_settings, setup_logging
from data360.mcp_server import mcp


def main(
    transport: Transport = typer.Option(
        "streamable-http", "-t", "--transport", help="Transport to use."
    ),
    port: int = typer.Option(8021, "-p", "--port", help="Port to bind the server to."),
):
    """Run the MCP server with configurable transport and port."""
    dotenv.load_dotenv()

    # Setup logging from configuration
    mcp_settings = get_mcp_server_settings()
    setup_logging(
        log_file=mcp_settings.log_file,
        log_level=mcp_settings.log_level,
        env=mcp_settings.env,
        azure_connection_string=mcp_settings.azure_connection_string,
    )

    mcp.run(transport=transport, port=port)


if __name__ == "__main__":
    typer.run(main)
