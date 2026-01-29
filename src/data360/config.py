import functools as ft
import logging
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPServerSettings(BaseSettings):
    """Configuration settings for MCP server."""

    port: int = Field(
        default=8000,
        description="Port for the MCP server",
    )
    transport: str = Field(
        default="http",
        description="Transport for the MCP server",
    )
    log_file: str | None = Field(
        default=None,
        description="Path to log file. If None, logs go to stderr/stdout.",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    model_config = SettingsConfigDict(env_prefix="MCP_")


class Data360Settings(BaseSettings):
    """Configuration settings for Data360 API integration."""

    api_base_url: str = Field(
        ...,
        description="Base URL for the Data360 API",
    )
    codelist_api_base_url: str | None = Field(
        default=None,
        description="Base URL for the Data360 codelist API",
    )
    search_url: str | None = Field(
        default=None,
        description="URL for search endpoint (defaults to {api_base_url}/data360/searchv2)",
    )
    metadata_url: str | None = Field(
        default=None,
        description="URL for metadata endpoint (defaults to {api_base_url}/data360/metadata)",
    )
    disaggregation_url: str | None = Field(
        default=None,
        description="URL for disaggregation endpoint (defaults to {api_base_url}/data360/disaggregation)",
    )
    data_url: str | None = Field(
        default=None,
        description="URL for data endpoint (defaults to {api_base_url}/data)",
    )
    metadata_search_fields: list[str] = Field(
        default=[
            "series_description/idno",
            "series_description/name",
            "series_description/database_id",
            "series_description/definition_long",
            "series_description/methodology",
            "series_description/limitation",
            "series_description/relevance",
            "series_description/aggregation_method",
        ]
    )

    # Limit the data observations to the following confidentiality levels
    data_obs_confidentiality_levels: list[str] = Field(
        default=[
            "PU",  # Public
            # "OU",  # Official Use
            # "CO",  # Confidential
            # "SC",  # Strictly Confidential
        ],
        description="Confidentiality levels to limit the data observations to",
    )

    model_config = SettingsConfigDict(env_prefix="DATA360_")

    @property
    def api_url(self) -> str:
        """Get the full search API URL."""
        return f"{self.api_base_url}/data360/"


@ft.cache
def get_data360_settings() -> Data360Settings:
    """Get cached Data360 settings instance."""
    return Data360Settings()  # pyright: ignore[reportCallIssue]


@ft.cache
def get_mcp_server_settings() -> MCPServerSettings:
    """Get cached MCP server settings instance."""
    return MCPServerSettings()  # pyright: ignore[reportCallIssue]


def setup_logging(log_file: str | None = None, log_level: str = "INFO") -> None:
    """Configure logging to write to a file and/or console.

    Args:
        log_file: Path to log file. If None, logs only go to stderr.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Convert string level to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Console handler (stderr)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (if log_file is specified)
    if log_file:
        log_path = Path(log_file)
        # Create parent directories if they don't exist
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
