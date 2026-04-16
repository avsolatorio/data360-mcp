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
    def validate_query(self) -> "SearchRequest":
        """Validate search query."""
        if not self.query or not self.query.strip():
            raise ValueError("Search query cannot be empty")
        return self

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
            # Default to indicator
            self.filter = "type eq 'indicator'"
        return self


class SeriesDescription(BaseModel):
    """Model for series description in search results.

    Fields available via select_fields in search:
    - idno, name, database_id, definition_long (core)
    - periodicity, time_periods, ref_country, dimensions (extended)
    """

    idno: str = Field(..., description="Series identifier")
    name: str = Field(..., description="Series name")
    database_id: str = Field(..., description="Database identifier")
    definition_long: str | None = Field(None, description="Series definition")
    periodicity: str | None = Field(
        None, description="Data periodicity (Annual, Monthly, etc)"
    )
    time_periods: list[dict[str, Any]] | None = Field(
        None, description="Time period coverage"
    )
    ref_country: list[dict[str, Any]] | None = Field(
        None, description="Countries with data"
    )
    dimensions: list[dict[str, Any]] | None = Field(
        None, description="Available disaggregations"
    )


class SearchResponse(MCPPagedResponse):
    """Response model for data360 search results (raw API response)."""

    items: list[SeriesDescription] | None = Field(
        default=None, description="List of search results containing series information"
    )
    error: str | None = Field(
        default=None, description="Error message if search failed"
    )


class EnrichedIndicator(BaseModel):
    """Model for an enriched indicator in search results.

    Optimized for LLM consumption with compact, relevant fields.
    """

    idno: str = Field(..., description="Indicator ID (e.g., WB_GS_NY_GDP_PCAP_KD)")
    database_id: str = Field(..., description="Database ID (e.g., WB_GS)")
    name: str = Field(..., description="Indicator name")
    truncated_definition: str = Field(
        ..., description="Truncated definition (max 100 chars)"
    )
    periodicity: str | None = Field(
        None, description="Data periodicity (Annual, Monthly)"
    )
    latest_data: str | None = Field(None, description="Most recent year with data")
    time_period_range: str | None = Field(
        None, description="Data availability range (e.g., '1990-2024')"
    )
    covers_country: bool | None = Field(
        None, description="True if indicator has data for the requested country"
    )
    dimensions: list[str] | None = Field(
        None, description="Available disaggregations (SEX, AGE, URBANISATION)"
    )


class EnrichedSearchResponse(MCPPagedResponse):
    """Response model for enriched search (LLM-optimized).

    Returns indicators sorted by country coverage and recency.
    """

    indicators: list[EnrichedIndicator] = Field(
        default_factory=list, description="Enriched indicators sorted by relevance"
    )
    required_country: str | None = Field(
        None, description="Resolved country code (e.g., KEN for Kenya)"
    )
    error: str | None = Field(None, description="Error message if search failed")


class QueryGroupResult(BaseModel):
    """Result group for a single query within a multi-query search.

    Only returned when result_layout='by_query'.
    """

    query: str = Field(..., description="The search query that produced these results")
    indicators: list[EnrichedIndicator] = Field(
        default_factory=list, description="Indicators found for this query"
    )
    count: int = Field(default=0, description="Number of indicators in this group")
    error: str | None = Field(
        None, description="Error message if this sub-query failed"
    )


class MultiQuerySearchResponse(BaseModel):
    """Response for multi-query search (when queries parameter is used).

    result_layout='merged': indicators contains a flat, deduped list.
    result_layout='by_query': results contains one group per input query.
    dedupe=True with by_query means cross-group dedup — first group to
    claim an indicator keeps it; later groups skip it.
    """

    indicators: list[EnrichedIndicator] = Field(
        default_factory=list,
        description="Merged, deduplicated indicators (result_layout='merged')",
    )
    results: list[QueryGroupResult] | None = Field(
        None,
        description="Per-query result groups (result_layout='by_query')",
    )
    result_layout: str = Field(
        "merged", description="Layout mode used: 'merged' or 'by_query'"
    )
    queries: list[str] = Field(
        default_factory=list, description="The input query strings"
    )
    required_country: str | None = Field(
        None, description="Resolved country code(s) used for all sub-queries"
    )
    total_candidates: int = Field(
        0,
        description="Total indicators found before dedup (merged) or across all groups (by_query)",
    )
    deduplicated_count: int | None = Field(
        None, description="Number of duplicates removed (merged layout only)"
    )
    error: str | None = Field(
        None, description="Top-level error if the entire multi-query operation failed"
    )


class MetadataRequest(BaseModel):
    """Request model for data 360 metadata retrieval."""

    indicator_id: str = Field(
        ..., description="Series ID (idno) to retrieve metadata for"
    )
    database_id: str = Field(
        ..., description="Database identifier (e.g., IPC_IPC, WB_GS)"
    )

    @model_validator(mode="after")
    def validate_ids(self) -> "MetadataRequest":
        """Validate database_id and indicator_id logic."""
        if self.database_id == self.indicator_id:
            raise ValueError(
                f"Invalid database_id: '{self.database_id}'. It matches indicator_id."
            )

        return self


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
        ..., description="Unique identifier for the database (e.g., WB_GS)"
    )
    indicator_id: str = Field(
        ..., description="Indicator ID (e.g., WB_GS_NY_GDP_PCAP_KD)"
    )
    disaggregation_filters: dict[str, str | None] | None = Field(
        default=None,
        description="Dictionary of disaggregation filters (e.g., {'REF_AREA': 'UGA', 'UNIT_MEASURE': 'PT'})",
    )

    @model_validator(mode="after")
    def validate_ids(self) -> "IndicatorDataRequest":
        """Validate database_id and indicator_id logic."""
        # 1. Check if database_id is suspicious (same as indicator_id)
        if self.database_id == self.indicator_id:
            raise ValueError(
                f"Invalid database_id: '{self.database_id}'. It matches indicator_id. "
                "Database ID should be the short dataset code (e.g., 'WB_GS', 'WB_HCP')."
            )

        return self


class IndicatorDataResponse(MCPPagedResponse):
    """Response model for indicator data retrieval."""

    data: list[dict[str, Any]] | None = Field(
        default=None, description="List of indicator data points"
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Basic metadata for the indicator (e.g., name, definition)",
    )
    error: str | None = Field(
        default=None, description="Error message if data retrieval failed"
    )
    failed_validation: list[str] | None = Field(
        default=None, description="List of filter validation errors"
    )


class DiscoveredIndicator(BaseModel):
    """Model for a discovered and validated indicator."""

    indicator_id: str = Field(..., description="Indicator ID")
    database_id: str = Field(..., description="Database identifier")
    name: str = Field(..., description="Indicator name")
    truncated_definition: str = Field(
        ..., description="Short definition (max 100 chars)"
    )
    has_country: bool = Field(
        ..., description="Whether data exists for the requested country"
    )
    country_code: str | None = Field(
        default=None, description="Country code used for validation"
    )
    available_dimensions: list[str] = Field(
        default_factory=list, description="List of available disaggregation dimensions"
    )
    available_frequencies: list[str] = Field(
        default_factory=list, description="List of available frequencies"
    )
    periodicity: str | None = Field(
        default=None, description="Periodicity of the indicator"
    )
    has_required_dimensions: bool = Field(
        default=True, description="Whether the indicator has all required dimensions"
    )
    time_range: dict[str, str | None] | None = Field(
        default=None, description="Start and end years of data availability"
    )
    error: str | None = Field(
        default=None, description="Error message if validation failed"
    )


class DiscoveryResult(BaseModel):
    """Result of indicator discovery process."""

    indicators: list[DiscoveredIndicator] = Field(
        default_factory=list, description="List of discovered and validated indicators"
    )
    error: str | None = Field(
        default=None, description="Error message if discovery failed entirely"
    )
