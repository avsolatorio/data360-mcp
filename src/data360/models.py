import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# Prefix used by the search API's metadata_link entries.
# Strip this to derive the usable indicator_id.
_META_ID_PREFIX = "META_"


def sanitize_search_query(query: str) -> str:
    """Validate search query and sanitize unsafe characters for Search V3."""
    if not query or not query.strip():
        raise ValueError("Search query cannot be empty")
    # Strip parentheses, dollar signs, and other punctuation that causes Search V3 to return 0 results.
    # Preserve alphanumerics, underscores, hyphens, commas, and periods.
    cleaned = re.sub(r"[^\w\s\-\,\.]", " ", query)
    sanitized = " ".join(cleaned.split())
    if not sanitized or not sanitized.strip():
        raise ValueError("Search query cannot be empty after sanitization")
    return sanitized



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
        """Validate search query and sanitize unsafe characters."""
        self.query = sanitize_search_query(self.query)
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


class PrimarySourceInfo(BaseModel):
    """A single metadata_link entry identifying a primary source indicator.

    The search API returns this under ``additional.metadata_link`` when an
    indicator has been curated to point to its authoritative primary source
    (typically in WDI).
    """

    type: str = Field(..., description="Link type (e.g. 'primary')")
    metadata_id: str = Field(
        ...,
        description="Metadata ID with META_ prefix (e.g. META_WB_WDI_SP_POP_TOTL)",
    )
    database_id: str | None = Field(
        None, description="Primary source database (e.g. WB_WDI)"
    )
    database_name: str | None = Field(
        None, description="Human-readable database name"
    )

    @property
    def indicator_id(self) -> str:
        """Derive the usable indicator_id by stripping the META_ prefix."""
        if self.metadata_id.startswith(_META_ID_PREFIX):
            return self.metadata_id[len(_META_ID_PREFIX) :]
        return self.metadata_id


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
    ref_country: list[dict[str, Any] | str] | None = Field(
        None, description="Countries with data"
    )
    dimensions: list[dict[str, Any]] | None = Field(
        None, description="Available disaggregations"
    )
    metadata_link: list[PrimarySourceInfo] = Field(
        default_factory=list,
        description="Metadata links from the API's additional.metadata_link field.",
    )
    connected_entities: list[dict[str, Any]] | None = Field(
        default=None,
        description="Connected secondary entities for SearchV3 redirect mapping.",
    )

    @property
    def primary_source(self) -> PrimarySourceInfo | None:
        """Return the first primary-type metadata link, or None."""
        return next((link for link in self.metadata_link if link.type == "primary"), None)


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
    database_name: str | None = Field(
        None,
        description="Human-readable dataset name for the database_id "
        "(e.g., 'Gender Statistics' for WB_GS). "
        "Use this when presenting data to users — never expand database_id by guessing.",
    )
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
    covers_country: dict[str, bool] | None = Field(
        None,
        description="Per-country coverage map (e.g. {'KEN': True, 'GHA': False}). "
        "Populated when required_country is provided. None when no country was requested.",
    )
    requested_country: str | None = Field(
        None,
        description="Resolved country code this indicator was evaluated against "
        "(set when per-group countries are used via query_groups; also set for "
        "single-query path when required_country is provided).",
    )
    dimensions: list[str] | None = Field(
        None, description="Available disaggregations (SEX, AGE, URBANISATION)"
    )
    primary_source_of: str | None = Field(
        None,
        description="When this indicator was redirected from a secondary source, "
        "contains the original secondary idno (e.g. 'WB_HNP_SP_POP_TOTL'). "
        "None if the indicator was already the primary source.",
    )


class EnrichedSearchResponse(MCPPagedResponse):
    """Response model for enriched search (LLM-optimized).

    Returns indicators sorted by country coverage and recency.
    """

    indicators: list[EnrichedIndicator] = Field(
        default_factory=list, description="Enriched indicators sorted by relevance"
    )
    required_country: str | None = Field(
        None,
        description="Resolved country code(s). Semicolon-separated for multiple countries "
        "(e.g. 'KEN' or 'KEN;GHA').",
    )
    country_names: dict[str, str] | None = Field(
        None, description="Resolved names of requested countries"
    )
    error: str | None = Field(None, description="Error message if search failed")


class QueryGroup(BaseModel):
    """A group of search queries scoped to an optional country.

    Allows binding multiple search terms to a specific geographic scope
    in a single search() call. Used with the query_groups parameter.

    Example::

        QueryGroup(queries=["GDP per capita", "inflation rate"], country="Kenya")
    """

    queries: list[str] = Field(
        ...,
        description="Search terms for this group (e.g., ['GDP per capita', 'inflation rate']). "
        "At least one non-empty string required.",
        min_length=1,
    )
    country: str | None = Field(
        None,
        description="Country name or 3-letter code for this group (e.g., 'Kenya' or 'KEN'). "
        "If None, no country filtering is applied to indicators in this group.",
    )


class QueryGroupResult(BaseModel):
    """Result group for a single query within a multi-query search.

    Only returned when result_layout='by_query'.
    """

    query: str = Field(..., description="The search query that produced these results")
    country_code: str | None = Field(
        None,
        description="Resolved country code for this query group (e.g., 'KEN'). "
        "Set when query_groups is used and a country was specified for this group.",
    )
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
        description="Flat indicator list. Populated when result_layout='merged'; "
        "empty when 'by_query' (see results field instead).",
    )
    results: list[QueryGroupResult] | None = Field(
        None,
        description="Per-query result groups (result_layout='by_query')",
    )
    result_layout: Literal["merged", "by_query"] = Field(
        "merged", description="Layout mode used: 'merged' or 'by_query'"
    )
    queries: list[str] = Field(
        default_factory=list, description="The input query strings"
    )
    required_country: str | None = Field(
        None,
        description="Resolved country code(s) used for all sub-queries. "
        "Semicolon-separated for multiple countries (e.g. 'KEN;GHA').",
    )
    country_names: dict[str, str] | None = Field(
        None, description="Resolved names of requested countries"
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
        description=(
            "Per-dimension filters: each value is a string or null (never a JSON array). "
            "Example: {'REF_AREA': 'KEN', 'UNIT_MEASURE': 'KD'}. "
            "Multiple areas: comma-separated ISO codes in REF_AREA (e.g. 'KEN,TZA'); "
            "semicolons in REF_AREA are accepted and normalized to commas. "
            "Use null for a dimension to request all values of that dimension."
        ),
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


# ---------------------------------------------------------------------------
# Data Aggregation Tool Models (Tier 1 — full implementation)
# ---------------------------------------------------------------------------


class GroupSummary(BaseModel):
    """Summary statistics for a single group in a summarize_data response."""

    group_key: dict[str, str] = Field(
        ...,
        description="Dimension values defining this group "
        '(e.g. {"ref_area": "KEN"} or {"ref_area": "KEN", "sex": "F"})',
    )
    count: int = Field(..., description="Number of observations in this group")
    latest_value: float | None = Field(None, description="Most recent obs_value")
    latest_year: str | None = Field(None, description="Year of latest_value")
    earliest_value: float | None = Field(None, description="Oldest obs_value in range")
    earliest_year: str | None = Field(None, description="Year of earliest_value")
    min: float | None = Field(None, description="Minimum obs_value")
    max: float | None = Field(None, description="Maximum obs_value")
    mean: float | None = Field(None, description="Arithmetic mean of obs_values")
    median: float | None = Field(None, description="Median obs_value")
    total_change: float | None = Field(
        None, description="latest - earliest (absolute change)"
    )
    pct_change: float | None = Field(
        None,
        description="((latest - earliest) / |earliest|) * 100. "
        "None if earliest is zero or missing.",
    )
    trend_direction: str | None = Field(
        None,
        description="'increasing', 'decreasing', 'stable', or 'volatile'. "
        "Based on linear regression slope and R² over the series.",
    )
    time_range: str | None = Field(
        None, description="Actual data range (e.g. '2005-2023')"
    )
    claim_ids: list[str] = Field(
        default_factory=list,
        description="Source claim_ids from underlying raw observations",
    )

    def to_compact(self) -> dict[str, Any]:
        """Return a slimmed dict for LLM context.

        claim_ids are retained here — they are 8-character PCN hashes and the
        UI needs them to render provenance attribution per group. The token cost
        is bounded (one hash per observation per group) and preserves the
        group→claim_ids association that a flat top-level list would lose.
        """
        return {
            "group": self.group_key,
            "n": self.count,
            "latest": {"value": self.latest_value, "year": self.latest_year},
            "earliest": {"value": self.earliest_value, "year": self.earliest_year},
            "range": self.time_range,
            "stats": {
                "min": self.min,
                "max": self.max,
                "mean": self.mean,
                "median": self.median,
            },
            "change": {"abs": self.total_change, "pct": self.pct_change},
            "trend": self.trend_direction,
            "claim_ids": self.claim_ids,
        }


class DataSummaryResponse(BaseModel):
    """Response model for data360_summarize_data."""

    groups: list[GroupSummary] = Field(
        default_factory=list, description="Per-group summary statistics"
    )
    metadata: dict[str, Any] | None = Field(
        None, description="Indicator metadata (name, definition, database_name)"
    )
    unit_measure: str | None = Field(
        None, description="Unit of measurement for interpreting values"
    )
    error: str | None = Field(
        None, description="Error message if request failed; otherwise None"
    )
    ambiguous_dimensions: list[str] | None = Field(
        None,
        description=(
            "Disaggregation dimensions present in the data with more than one distinct "
            "value that are NOT included in group_by. When non-empty, the per-group "
            "time-series statistics may be computed over mixed disaggregation values "
            "(e.g. SEX=M, F, and _T all collapsed into one group), making trend and "
            "summary stats unreliable. To fix: either add these dimensions to group_by "
            "(e.g. group_by=['ref_area', 'sex']) or pass disaggregation_filters to pin "
            "each dimension to a single value (e.g. {'SEX': '_T'})."
        ),
    )

    def to_compact(self) -> dict[str, Any]:
        """Return a slimmed dict for LLM context.

        claim_ids are excluded from each GroupSummary entry — they are PCN
        hashes retained in the full model for provenance traceability.
        """
        return {
            "indicator": self.metadata.get("name") if self.metadata else None,
            "unit": self.unit_measure,
            "ambiguous_dimensions": self.ambiguous_dimensions,
            "groups": [g.to_compact() for g in self.groups],
            "error": self.error,
        }


class RankedCountry(BaseModel):
    """A single country entry in a ranking result."""

    rank: int = Field(..., description="Ordinal rank (ties share the same rank)")
    ref_area: str = Field(..., description="Country/region code (e.g. 'KEN')")
    country_name: str | None = Field(None, description="Human-readable country name")
    obs_value: float = Field(..., description="The indicator value for ranking year")
    percentile: float | None = Field(
        None,
        description="Percentile position (0-100) within the ranked set",
    )
    claim_id: str | None = Field(
        None, description="Claim ID from the source observation"
    )

    def to_compact(self) -> dict[str, Any]:
        """Return a slimmed dict for LLM context.

        claim_id is retained — it is the PCN hash for this observation and the
        UI needs it to render per-entry provenance attribution. Only percentile
        is dropped; it is derivable from rank order and adds no LLM value.
        """
        return {
            "rank": self.rank,
            "code": self.ref_area,
            "country": self.country_name or self.ref_area,
            "value": self.obs_value,
            "claim_id": self.claim_id,
        }


class ExcludedCountry(BaseModel):
    """A country excluded from ranking due to missing data."""

    ref_area: str = Field(..., description="Country/region code")
    country_name: str | None = Field(None, description="Human-readable country name")
    reason: str = Field(..., description="Why the country was excluded")


class RankingResponse(BaseModel):
    """Response model for data360_rank_countries."""

    year: str | None = Field(None, description="The year used for ranking")
    year_selection_note: str | None = Field(
        None,
        description="Explains how the ranking year was chosen. "
        "E.g. 'Latest year with broadest coverage (2022, 18/20 countries)' "
        "or 'Most recent year (2023, 12/20 countries)'.",
    )
    order: str = Field(
        "desc", description="'desc' (highest first) or 'asc' (lowest first)"
    )
    total_with_data: int = Field(0, description="Number of countries that had data")
    total_requested: int = Field(0, description="Number of countries attempted")
    universe: str | None = Field(
        None,
        description=(
            "'explicit' when country_group or country_codes was used; "
            "'all_member_economies' when ranking used full geographic fetch with "
            "member-economy row filtering."
        ),
    )
    universe_size: int | None = Field(
        None,
        description=(
            "For explicit scope: same as total_requested. For all_member_economies: "
            "count of known FMR leaf economies in the ranking universe."
        ),
    )
    rankings: list[RankedCountry] = Field(
        default_factory=list, description="Ranked list of countries"
    )
    excluded: list[ExcludedCountry] = Field(
        default_factory=list, description="Countries with no data for ranking year"
    )
    metadata: dict[str, Any] | None = Field(None, description="Indicator metadata")
    unit_measure: str | None = Field(None, description="Unit of measurement")
    error: str | None = Field(None, description="Error message if request failed")

    def to_compact(self) -> dict[str, Any]:
        """Return a slimmed dict for LLM context.

        Key reductions vs. the full model:
        - rankings: claim_id and percentile dropped from each entry (PCN hash
          retained in the full RankedCountry model).
        - excluded: capped at 5 sample entries; full count is in excluded_count.
          This prevents 30+ excluded entries from flooding the context when
          ranking a large group like SSF (48 countries).
        """
        return {
            "year": self.year,
            "year_selection_note": self.year_selection_note,
            "order": self.order,
            "counts": {
                "with_data": self.total_with_data,
                "requested": self.total_requested,
            },
            "unit": self.unit_measure,
            "indicator": self.metadata.get("name") if self.metadata else None,
            "rankings": [r.to_compact() for r in self.rankings],
            "excluded_count": len(self.excluded),
            "excluded_sample": [
                {"code": e.ref_area, "name": e.country_name}
                for e in self.excluded[:5]
            ],
            "error": self.error,
        }


class ComparisonSnapshot(BaseModel):
    """Single-year comparison snapshot across countries."""

    year: str = Field(..., description="The comparison year")
    year_selection_note: str | None = Field(
        None,
        description="Explains how the comparison year was chosen. "
        "E.g. 'User-specified year: 2022' or 'Latest year with data for all compared countries: 2023'.",
    )
    rankings: list[RankedCountry] = Field(
        default_factory=list,
        description="Countries sorted by obs_value with rank and gap_to_leader",
    )
    spread: dict[str, float | None] = Field(
        default_factory=dict,
        description="Spread statistics: min, max, range, coefficient_of_variation",
    )

    def to_compact(self) -> dict[str, Any]:
        """Return a slimmed dict for LLM context.

        Delegates to RankedCountry.to_compact() for each ranked entry, which
        retains claim_id (PCN hash) and drops percentile. claim_id is preserved
        here so the UI can render per-country provenance attribution in the
        snapshot table.
        """
        return {
            "year": self.year,
            "year_selection_note": self.year_selection_note,
            "rankings": [r.to_compact() for r in self.rankings],
            "spread": self.spread,
        }


class ComparisonTimeSeries(BaseModel):
    """Time-series comparison across countries."""

    aligned_years: list[str] = Field(
        default_factory=list,
        description="Years where ALL compared countries have data",
    )
    series: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict,
        description="Per-country time series: {ref_area: [{time_period, obs_value, claim_id}]}",
    )
    convergence: str | None = Field(
        None,
        description="'converging', 'diverging', or 'parallel'. "
        "Based on coefficient of variation trend across aligned years.",
    )
    cagr: dict[str, float | None] = Field(
        default_factory=dict,
        description="Compound annual growth rate per country over aligned period",
    )

    def to_compact(self) -> dict[str, Any]:
        """Return a slimmed dict for LLM context.

        The per-year ``series`` dict is retained but restructured: each data
        point is encoded as a positional array ``[time_period, obs_value, claim_id]``
        instead of a named dict. This reduces per-point overhead from ~55 chars
        to ~24 chars (~56% reduction) while preserving the year→value→PCN
        association the UI needs for provenance attribution.

        A ``series_schema`` field documents the array positions so the UI
        decoder does not need to hard-code positional assumptions.

        ``aligned_years`` list is replaced by ``year_range`` + ``n_aligned_years``
        since the LLM only needs to know the span, not the individual years.
        """
        year_range = (
            f"{self.aligned_years[0]}-{self.aligned_years[-1]}"
            if self.aligned_years
            else None
        )
        compact_series = {
            country: [
                [pt["time_period"], pt["obs_value"], pt.get("claim_id")]
                for pt in points
            ]
            for country, points in self.series.items()
        }
        return {
            "year_range": year_range,
            "n_aligned_years": len(self.aligned_years),
            "convergence": self.convergence,
            "cagr": self.cagr,
            "series_schema": ["time_period", "obs_value", "claim_id"],
            "series": compact_series,
        }


class CountryComparisonResponse(BaseModel):
    """Response model for data360_compare_countries."""

    snapshot: ComparisonSnapshot | None = Field(
        None, description="Single-year ranked comparison"
    )
    time_series: ComparisonTimeSeries | None = Field(
        None,
        description="Aligned time-series comparison (when include_time_series=True)",
    )
    metadata: dict[str, Any] | None = Field(None, description="Indicator metadata")
    unit_measure: str | None = Field(None, description="Unit of measurement")
    error: str | None = Field(None, description="Error message if request failed")
    country_names: dict[str, str] | None = Field(None, description="Resolved names of compared countries")

    def to_compact(self) -> dict[str, Any]:
        """Return a slimmed dict for LLM context.

        Delegates to ComparisonSnapshot.to_compact() and
        ComparisonTimeSeries.to_compact(), which strip claim_ids (PCN hashes)
        and per-year series data respectively.
        """
        return {
            "indicator": self.metadata.get("name") if self.metadata else None,
            "unit": self.unit_measure,
            "snapshot": self.snapshot.to_compact() if self.snapshot else None,
            "time_series": self.time_series.to_compact() if self.time_series else None,
            "country_names": self.country_names,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Data Aggregation Tool Models (Tier 2 — stubs for future implementation)
# ---------------------------------------------------------------------------


class DerivedDataResponse(BaseModel):
    """Response model for data360_compute_derived (stub — not yet implemented).

    Will contain derived/transformed values (growth rates, CAGR, moving averages,
    index rebasing) computed from raw indicator data.
    """

    computation: str | None = Field(None, description="Computation type applied")
    data: list[dict[str, Any]] = Field(
        default_factory=list, description="Computed values"
    )
    summary: str | None = Field(None, description="Human-readable one-line summary")
    metadata: dict[str, Any] | None = Field(None, description="Indicator metadata")
    unit_measure: str | None = Field(None, description="Original unit")
    derived_unit: str | None = Field(
        None, description="Unit for derived values (e.g. '%' for growth_rate)"
    )
    error: str | None = Field(None, description="Error message if request failed")


class PivotTableResponse(BaseModel):
    """Response model for data360_pivot_table (stub — not yet implemented).

    Will contain a cross-tabulation of multiple indicators and/or countries,
    organized as a structured table with row/column dimensions.
    """

    table: list[dict[str, Any]] = Field(default_factory=list, description="Table rows")
    column_metadata: list[dict[str, Any]] = Field(
        default_factory=list, description="Per-column metadata"
    )
    claim_map: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of cell keys to source claim_ids",
    )
    missing_cells: list[dict[str, str]] = Field(
        default_factory=list,
        description="Cells with no data: [{row, column, reason}]",
    )
    error: str | None = Field(None, description="Error message if request failed")


class DiagnosticIndicatorSummary(BaseModel):
    """Per-indicator summary within a diagnostic summary response (stub)."""

    indicator_id: str = Field(..., description="Indicator ID")
    database_id: str = Field(..., description="Database ID")
    name: str = Field(..., description="Indicator name")
    latest_value: float | None = Field(None, description="Most recent value")
    latest_year: str | None = Field(None, description="Year of latest value")
    trend_direction: str | None = Field(
        None, description="'increasing', 'decreasing', 'stable', 'volatile'"
    )
    pct_change: float | None = Field(None, description="Percent change over period")
    time_range: str | None = Field(None, description="Actual data range")
    claim_ids: list[str] = Field(default_factory=list, description="Source claim_ids")
    coverage_note: str | None = Field(None, description="Gaps or caveats")


class DiagnosticSummaryResponse(BaseModel):
    """Response model for data360_diagnostic_summary (stub — not yet implemented).

    Will contain a multi-indicator diagnostic summary for a topic and country,
    with per-indicator trend analysis and cross-indicator notes.
    """

    topic: str | None = Field(None, description="Diagnostic category used")
    country_code: str | None = Field(None, description="Resolved country code(s)")
    indicators: list[DiagnosticIndicatorSummary] = Field(
        default_factory=list, description="Per-indicator summaries"
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Topics searched but no indicator found",
    )
    metadata_sources: list[dict[str, str]] = Field(
        default_factory=list,
        description="List of {database_id, database_name} used",
    )
    error: str | None = Field(None, description="Error message if request failed")


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


class DatasetSearchRequest(BaseModel):
    """Request model for dataset search queries. Includes V3 special character sanitization."""

    query: str = Field(
        ..., description="Search query string to find relevant datasets"
    )
    limit: int = Field(
        default=10,
        description="Number of results to return (default is 10)",
        ge=1,
        le=50,
    )
    offset: int = Field(default=0, description="Offset of the current page")

    @model_validator(mode="after")
    def validate_query(self) -> "DatasetSearchRequest":
        """Validate search query and sanitize unsafe characters."""
        self.query = sanitize_search_query(self.query)
        return self


class DatasetDescription(BaseModel):
    """Model for dataset description in search results."""

    idno: str = Field(..., description="Dataset identifier")
    name: str = Field(..., description="Dataset name")
    description: str | None = Field(None, description="Dataset description")
    data_classification: str | None = Field(None, description="Data classification (e.g. public)")
    data_last_updated: str | None = Field(None, description="Last updated timestamp")
    economies_count: int | None = Field(None, description="Number of economies covered")
    time_period: dict[str, Any] | None = Field(None, description="Time period range covered")


class DatasetSearchResponse(MCPPagedResponse):
    """Response model for data360 dataset search results."""

    items: list[DatasetDescription] = Field(
        default_factory=list, description="List of search results containing dataset information"
    )
    error: str | None = Field(
        default=None, description="Error message if search failed"
    )
