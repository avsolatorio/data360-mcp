import functools as ft

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(env_prefix="DATA360_")

    @property
    def api_url(self) -> str:
        """Get the full search API URL."""
        return f"{self.api_base_url}/data360/"


@ft.cache
def get_data360_settings() -> Data360Settings:
    """Get cached Data360 settings instance."""
    return Data360Settings()  # pyright: ignore[reportCallIssue]
