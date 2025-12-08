from typing import Any

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Request model for data360 search queries."""

    query: str = Field(
        ..., description="Search query string to find relevant data series"
    )
    n_results: int = Field(
        10, description="Number of top results to return (default is 10)", ge=1, le=50
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
    skip: int = Field(default=0, description="Number of results to skip for pagination")
    count: bool = Field(
        default=False, description="Whether to include total count in response"
    )


class SeriesDescription(BaseModel):
    """Model for series description in search results."""

    idno: str = Field(..., description="Series identifier")
    name: str = Field(..., description="Series name")
    database_id: str = Field(..., description="Database identifier")


class SearchResponseItem(BaseModel):
    """Model for a single search result item from the value array."""

    search_score: float = Field(
        ..., alias="@search.score", description="Relevance score for the search result"
    )
    series_description: SeriesDescription = Field(
        ..., description="Series description information"
    )

    model_config = {"populate_by_name": True}


class SearchResponse(BaseModel):
    """Response model for data360 search results."""

    items: list[SearchResponseItem] | None = Field(
        default=None, description="List of search results containing series information"
    )
    count: int | None = Field(default=None, description="Number of results returned")
    total: int | None = Field(
        default=None, description="Total number of results available"
    )
    offset: int | None = Field(
        default=None, description="Offset of the current results set"
    )
    has_more: bool | None = Field(
        default=None, description="Whether there are more results"
    )
    next_offset: int | None = Field(
        default=None, description="Offset of the next results set"
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


class IndicatorDataResponse(BaseModel):
    """Response model for indicator data retrieval."""

    data: list[dict[str, Any]] | None = Field(
        default=None, description="List of indicator data points"
    )
    count: int | None = Field(
        default=None, description="Total number of data points returned"
    )
    error: str | None = Field(
        default=None, description="Error message if data retrieval failed"
    )
