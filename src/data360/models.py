from typing import Any

from pydantic import BaseModel, Field, model_validator


class MCPPagedResponse(BaseModel):
    """Response model for MCP paged results.
    For more information, see: https://github.com/anthropics/skills/blob/main/skills/mcp-builder/reference/mcp_best_practices.md#pagination

    Always respect limit parameter
    Return has_more, next_offset, total_count
    Default to 20-50 items
    """

    count: int = Field(default=0, description="Number of results in the current page")
    total_count: int | None = Field(default=None, description="Total number of results")
    offset: int | None = Field(default=None, description="Offset of the current page")
    has_more: bool | None = Field(
        default=None, description="Whether there are more results"
    )
    next_offset: int | None = Field(default=None, description="Offset of the next page")


class SearchRequest(BaseModel):
    """Request model for data360 search queries."""

    query: str = Field(
        ..., description="Search query string to find relevant data series"
    )
    limit: int = Field(
        default=10,
        description="Number of results to return (default is 10)",
        ge=1,
        le=50,
    )
    count: bool = Field(
        default=True, description="Whether to include total count in response"
    )
    filter: str | None = Field(
        default=None,
        description="OData filter expression (e.g., \"type eq 'indicator'\")",
    )
    orderby: str | None = Field(
        default=None,
        description='OData orderby expression (e.g., "series_description/name")',
    )
    select: str | None = Field(
        default=None,
        description='OData select expression (e.g., "series_description/idno, series_description/name")',
    )
    offset: int = Field(default=0, description="Offset of the current page")

    @model_validator(mode="after")
    def set_select_default(self) -> "SearchRequest":
        """Set default select value when None is provided."""
        if self.select is None:
            self.select = "series_description/idno, series_description/name, series_description/database_id, series_description/definition_long"
        return self

    @model_validator(mode="after")
    def set_filter_default(self) -> "SearchRequest":
        """Set default filter value when None is provided."""
        if self.filter is None:
            self.filter = "type eq 'indicator'"
        return self


class SeriesDescription(BaseModel):
    """Model for series description in search results."""

    idno: str = Field(..., description="Series identifier")
    name: str = Field(..., description="Series name")
    database_id: str = Field(..., description="Database identifier")
    definition_long: str | None = Field(None, description="Series definition")


class SearchResponse(MCPPagedResponse):
    """Response model for data360 search results."""

    items: list[SeriesDescription] | None = Field(
        default=None, description="List of search results containing series information"
    )
    error: str | None = Field(
        default=None, description="Error message if search failed"
    )


class MetadataRequest(BaseModel):
    """Request model for data 360 metadata retrieval."""

    idno: str = Field(..., description="Series ID (idno) to retrieve metadata for")
    database_id: str = Field(
        ..., description="Database identifier (e.g., IPC_IPC, WB_WDI)"
    )


class MetadataResponse(BaseModel):
    """Response model for metadata retrieval."""

    indicator_metadata: dict[str, Any] | None = Field(
        default=None, description="Metadata information for the requested series"
    )
    disaggregation_options: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Available disaggregation options for the indicator",
    )
    error: str | None = Field(
        default=None, description="Error message if metadata retrieval failed"
    )


class IndicatorDataRequest(BaseModel):
    """Request model for retrieving indicator data from Data360 API."""

    database_id: str = Field(
        ..., description="Unique identifier for the database (e.g., WB_WDI)"
    )
    indicator: str = Field(..., description="Indicator ID (e.g., WB_WDI_SP_POP_TOTL)")
    disaggregation_filters: dict[str, str] | None = Field(
        default=None,
        description="Dictionary of disaggregation filters (e.g., {'REF_AREA': 'UGA', 'UNIT_MEASURE': 'PT'})",
    )


class IndicatorDataResponse(MCPPagedResponse):
    """Response model for indicator data retrieval."""

    data: list[dict[str, Any]] | None = Field(
        default=None, description="List of indicator data points"
    )
    error: str | None = Field(
        default=None, description="Error message if data retrieval failed"
    )
