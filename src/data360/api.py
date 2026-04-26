import asyncio
import json
import logging
import re
import zlib
from typing import Any
from urllib.parse import urlencode

from fastmcp import Context
from pydantic import BaseModel

import dotenv
import httpx
from pydantic import ValidationError as PydanticValidationError

from .config import get_data360_settings
from .errors import (
    Data360MCPError,
    NotFoundError,
    ParseError,
    classify_error,
)
from .errors import ValidationError as Data360ValidationError
from .models import (
    DiscoveryResult,
    EnrichedIndicator,
    EnrichedSearchResponse,
    IndicatorDataRequest,
    IndicatorDataResponse,
    MetadataRequest,
    MetadataResponse,
    MultiQuerySearchResponse,
    QueryGroup,
    QueryGroupResult,
    SearchRequest,
    SearchResponse,
    SeriesDescription,
)
from .providers import get_database_mapping

dotenv.load_dotenv()
_logger = logging.getLogger(__name__)

data360_config = get_data360_settings()

# Constants for API logic
COUNTRY_CODE_LENGTH = 3
SCORE_THRESHOLD = 70
MAX_RETURN_STATEMENTS = 6
DEFAULT_SEARCH_LIMIT = 5

# Fields fetched by _search_raw for LLM-friendly enrichment.
# Shared between single-query and multi-query paths to ensure consistency.
_ENRICHMENT_SELECT_FIELDS = [
    "idno",
    "name",
    "database_id",
    "definition_long",
    "periodicity",
    "time_periods",
    "ref_country",
    "dimensions",
    "measurement_unit",
]

# Prefiltering constants for get_data output.
# Based on a 16-database survey (see payload_analysis.md for full documentation).
# Always-keep fields: the core data the LLM needs.
_CORE_FIELDS = frozenset(
    {"OBS_VALUE", "TIME_PERIOD", "REF_AREA", "UNIT_MEASURE", "claim_id"}
)
# Conditional fields: kept only when their value is non-trivial (not _T or _Z).
# SEX/AGE/URBANISATION carry real disaggregation in WB_HCP, WB_SSGD, OECD_IDD.
# COMP_BREAKDOWN_1/2 carry semantic data in IPC_IPC, OECD_BROADBAND, WB_SE4ALL, WEF_TTDI.
_CONDITIONAL_FIELDS = frozenset(
    {"SEX", "AGE", "URBANISATION", "COMP_BREAKDOWN_1", "COMP_BREAKDOWN_2"}
)
# SDMX standard codes meaning "total" and "not applicable".
_TRIVIAL_VALUES = frozenset({"_T", "_Z"})


def _short_hash(data: dict[str, Any]) -> str:
    """PCN claim_id 8-character hash for data verification."""
    return f"{zlib.crc32(json.dumps(data, sort_keys=True).encode()) & 0xFFFFFFFF:08x}"


def _get_valid_disaggregations(
    disagg_res: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Get valid disaggregation options from the raw response."""
    null_values = ["_Z"]
    valid = []
    for field in disagg_res:
        if field.get("field_value", ["_T"])[0] in null_values:
            continue
        else:
            valid.append(field)
    return valid


def _strip_data_row(row: dict[str, Any]) -> dict[str, Any]:
    """Strip boilerplate fields from a data row for LLM token savings.

    Keeps core fields (OBS_VALUE, TIME_PERIOD, REF_AREA, UNIT_MEASURE, claim_id)
    and conditionally includes disaggregation fields (SEX, AGE, URBANISATION,
    COMP_BREAKDOWN_1, COMP_BREAKDOWN_2) only when their value is non-trivial
    (i.e. not _T or _Z).

    Note: COMP_BREAKDOWN_3 is intentionally excluded -- it was observed as ``_Z``
    across all 16 surveyed databases and never carries data.

    Based on a 16-database survey documented in docs/payload_analysis.md.
    """
    filtered = {k: v for k, v in row.items() if k in _CORE_FIELDS}
    for field in _CONDITIONAL_FIELDS:
        val = row.get(field)
        if val and val not in _TRIVIAL_VALUES:
            filtered[field] = val
    return filtered


# Dimensions to always strip from disaggregation output.
_STRIP_DIMENSIONS = frozenset({"INDICATOR", "FREQ"})
# Dimensions where a single _T value means "no disaggregation available".
_TRIVIAL_SINGLE_DIMENSIONS = frozenset({"SEX", "AGE", "URBANISATION"})
# Maximum number of REF_AREA codes to include in the sample.
_REF_AREA_SAMPLE_SIZE = 5


def _strip_disaggregation(
    dimensions: list[dict[str, Any]],
    queried_countries: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Strip bloat from disaggregation dimensions for LLM token savings.

    Rules:
    1. Remove INDICATOR and FREQ (always single-value, already known).
    2. Remove SEX/AGE/URBANISATION if only value is _T (no disaggregation).
    3. Sort TIME_PERIOD chronologically.
    4. Summarize REF_AREA: total count + which queried countries have data.
    """
    result = []
    for dim in dimensions:
        name = dim.get("field_name", "")
        values = dim.get("field_value", [])

        # Rule 1: strip trivial dimensions
        if name in _STRIP_DIMENSIONS:
            continue

        # Rule 2: strip single-value _T dimensions
        if name in _TRIVIAL_SINGLE_DIMENSIONS and values == ["_T"]:
            continue

        entry: dict[str, Any] = {"field_name": name}

        # Preserve label_name if present
        if "label_name" in dim:
            entry["label_name"] = dim["label_name"]

        # Rule 3: sort TIME_PERIOD
        if name == "TIME_PERIOD":
            entry["field_value"] = sorted(values)
        # Rule 4: summarize REF_AREA with country lookup
        elif name == "REF_AREA":
            entry["count"] = len(values)
            if queried_countries:
                ref_set = set(values)
                entry["queried"] = {
                    code: code in ref_set for code in queried_countries
                }
            else:
                entry["sample"] = sorted(values)[:_REF_AREA_SAMPLE_SIZE]
        else:
            entry["field_value"] = values

        result.append(entry)
    return result


async def _resolve_queried_countries(
    required_country: str | None,
) -> list[str] | None:
    """Resolve a required_country string into a list of 3-letter codes.

    Returns None if required_country is falsy or resolution fails.
    """
    if not required_country:
        return None
    resolved = await _resolve_country_code(required_country)
    if not resolved:
        return None
    return [c.strip() for c in resolved.split(";") if c.strip()]


def _validate_user_filters(
    user_filters: dict[str, str | None] | None,
    available_disaggregations: dict[str, list[str]],
) -> tuple[dict[str, str | None], list[str]]:
    """Validate user filters against available options.

    Returns:
        Tuple of (valid_filters_dict, error_messages_list).
    """
    if not user_filters:
        return {}, []

    valid_filters = {}
    errors = []
    for dim, val in user_filters.items():
        # Skip special 'None' filters (meaning "all") or known non-dims like REF_AREA if we don't have metadata for them
        # Note: API metadata usually returns REF_AREA as a dimension too if valid.
        if val is None:
            valid_filters[dim] = None
            continue

        # If dimension exists in metadata, check value
        if dim in available_disaggregations:
            valid_values = available_disaggregations[dim]
            is_valid = True

            # Special handling for REF_AREA which supports comma-separated list
            if dim == "REF_AREA" and "," in val:
                parts = [p.strip() for p in val.split(",") if p.strip()]
                for part in parts:
                    if part not in valid_values:
                        errors.append(
                            f"Invalid value '{part}' in '{val}' for dimension '{dim}'. Available options: {valid_values}"
                        )
                        is_valid = False
            # Standard single value check
            elif val not in valid_values:
                errors.append(
                    f"Invalid value '{val}' for dimension '{dim}'. Available options: {valid_values}"
                )
                is_valid = False

            if is_valid:
                valid_filters[dim] = val
        else:
            # If dimension is unknown, we treat it as valid/passthrough for now
            # but we could also flag it. For consistency with previous behavior,
            # we'll keep it as valid.
            valid_filters[dim] = val

    return valid_filters, errors


def _build_disaggregation_params(
    disaggregation_filters: dict[str, str | None] | None,
    available_disaggregations: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    """Build effective disaggregation params with smart defaults.

    This is the single source of truth for disaggregation filtering logic.
    Used by both get_data() and get_data_api_url().

    Args:
        disaggregation_filters: User-provided filters.
            - None or {}: Use defaults (SEX=_T, AGE=_T, URBANISATION=_T)
            - {"SEX": "F"}: Use F for SEX, defaults for others
            - {"SEX": None}: Omit SEX filter (get all values), defaults for others
        available_disaggregations: Optional dict of {dimension: [values]}
            derived from indicator metadata. If provided, defaults (like _T)
            are only applied if they exist in the available values.

    Returns:
        Dict of dimension -> value to add to API params.
        Dimensions with None values are omitted (API returns all).
    """
    effective = {}

    # 1. Start with user-provided filters
    if disaggregation_filters:
        for dim, raw_val in disaggregation_filters.items():
            # Skip FREQ as it's not used for filtering in this API
            if dim == "FREQ":
                continue
            if raw_val is not None:
                # Clean value: remove spaces around commas for multi-value support
                val = raw_val
                if isinstance(val, str) and "," in val:
                    val = ",".join([p.strip() for p in val.split(",") if p.strip()])
                effective[dim] = val

    # 2. Apply smart defaults for unspecified dimensions
    if available_disaggregations:
        for dim, values in available_disaggregations.items():
            # Skip if user already specified/excluded this dimension
            if disaggregation_filters and dim in disaggregation_filters:
                continue

            # Check if this dimension has a "Total" option (_T)
            if "_T" in values:
                # Redundancy check: if _T is the ONLY option, don't force it
                if len(values) == 1:
                    continue

                # Otherwise, apply default
                effective[dim] = "_T"

    else:
        # Fallback for when metadata wasn't fetched or failed.
        # We CANNOT safely apply defaults like AGE=_T because we don't know if they exist.
        # It is better to return ALL data (no filter) than NONE (invalid filter).
        # So we leave 'effective' as-is (containing only user provided filters).
        pass

    return effective


def _get_items_from_response(response_data: dict[str, Any]) -> list[SeriesDescription]:
    """Extract and validate series descriptions from API response."""
    values = response_data.get("value", [])
    items = []
    for value in values:
        series_description = value.get("series_description", {})
        # Only include items that have required fields (idno, name, database_id)
        if (
            series_description
            and series_description.get("idno")
            and series_description.get("name")
            and series_description.get("database_id")
        ):
            try:
                items.append(SeriesDescription.model_validate(series_description))
            except Exception as e:
                _logger.warning(
                    f"Failed to validate series_description: [{series_description}], error: {e}, skipping item"
                )
    return items


def _build_search_payload(request: SearchRequest) -> dict[str, Any]:
    """Build the search API payload from SearchRequest."""
    payload = {
        "search": request.query,
        "top": request.limit,
        "skip": request.offset,
        "count": request.count,
        "filter": request.filter,
        "select": request.select,
    }
    if request.orderby is not None:
        payload["orderby"] = request.orderby
    return payload


def _process_search_response(
    response_data: dict[str, Any], request: SearchRequest
) -> SearchResponse:
    """Process API response and build SearchResponse."""
    search_response_data = {
        "items": _get_items_from_response(response_data),
        "total_count": response_data.get("@odata.count", None),
        "offset": request.offset,
    }
    search_response_data["count"] = len(search_response_data["items"])

    # Calculate has_more and next_offset
    if (
        search_response_data["total_count"] is not None
        and search_response_data["total_count"] > request.offset + request.limit
    ):
        search_response_data["has_more"] = True
        search_response_data["next_offset"] = request.offset + request.limit
    else:
        search_response_data["has_more"] = False
        search_response_data["next_offset"] = None

    return SearchResponse.model_validate(search_response_data)


async def _search_raw(
    query: str,
    limit: int = 5,
    offset: int = 0,
    count: bool = True,
    select_fields: list[str] | None = None,
    odata_options: dict[str, str] | None = None,
) -> SearchResponse:
    """Internal: Raw search for data360 indicators using the World Bank Data360 API.

    This is the low-level API. Use `search()` for the enriched LLM-friendly version.

    Args:
        query: Search query string to find relevant data series
        limit: Number of results to return (default is 5)
        offset: Offset of the current page
        count: Whether to include total count in response
        select_fields: List of fields to return (e.g., ["idno", "name", "periodicity"]).
            Available fields: idno, name, database_id, definition_long, periodicity,
            time_periods, dimensions, topics, ref_country
        odata_options: DEPRECATED - kept for backward compatibility, prefer select_fields

    Returns:
        SearchResponse with raw API results.
    """
    # Build select clause from select_fields if provided
    # Keep defaults minimal - tools layer handles enrichment
    if select_fields is None and not (odata_options and odata_options.get("select")):
        select_fields = ["idno", "name", "database_id", "definition_long"]

    if select_fields:
        select_val = ", ".join(f"series_description/{f}" for f in select_fields)
    elif odata_options and odata_options.get("select"):
        # Backward compatibility: use odata_options.select if provided
        select_val = odata_options.get("select")
    else:
        select_val = None

    # odata_options kept for backward compatibility but discouraged
    filter_val = odata_options.get("filter") if odata_options else None
    orderby_val = odata_options.get("orderby") if odata_options else None

    request = SearchRequest(
        query=query,
        limit=limit,
        filter=filter_val,
        orderby=orderby_val,
        select=select_val,
        offset=offset,
        count=count,
    )

    url = data360_config.search_url or f"{data360_config.api_url}/searchv2"
    payload = _build_search_payload(request)

    mcp_error: Data360MCPError | None = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

            try:
                response_data = response.json()
            except ValueError as e:
                mcp_error = ParseError(context="search", original_error=e)
            else:
                try:
                    return _process_search_response(response_data, request)
                except Exception as e:
                    mcp_error = ParseError(
                        context="search",
                        detail=f"Failed to parse API response: {str(e)}",
                        original_error=e,
                    )

    except Exception as e:
        mcp_error = classify_error(e, context="search")

    if mcp_error:
        return SearchResponse(items=None, error=mcp_error.detail)
    # This should never be reached, but pyright needs it for type checking
    return SearchResponse(
        items=None, error="Unexpected error: no response and no error message"
    )


async def _resolve_country_code(country_query: str) -> str | None:
    """Resolve country name to code using cached REF_AREA codelist."""
    from . import providers as data360_providers  # noqa: PLC0415

    if not country_query:
        return None

    # Handle multi-country: semicolons are the user-facing delimiter because
    # some country names contain commas (e.g. "Korea, Republic of").
    if ";" in country_query:
        parts = [p.strip() for p in country_query.split(";") if p.strip()]
        resolved_codes = []
        for part in parts:
            code = await _resolve_country_code(part)
            if code:
                resolved_codes.append(code)

        return ";".join(resolved_codes) if resolved_codes else None

    # Already a 3-letter code
    if len(country_query) == COUNTRY_CODE_LENGTH and country_query.isupper():
        return country_query
    # Look up in codelist
    matches = await data360_providers.find_codelist_value(
        "REF_AREA", country_query, limit=1
    )
    if matches and matches[0].get("score", 0) >= SCORE_THRESHOLD:
        return matches[0].get("id")
    return None


def _enrich_search_results(
    search_result: "SearchResponse",
    country_code: str | None,
    db_mapping: dict[str, str] | None = None,
) -> list[EnrichedIndicator]:
    """Convert raw SearchResponse items into a list of EnrichedIndicator objects.

    Extracted to avoid duplicating enrichment logic between the single-query
    and multi-query paths in search().

    Args:
        search_result: Raw response from _search_raw().
        country_code: Resolved country code (or None). Used to compute covers_country.
        db_mapping: Optional dict mapping database_id -> human-readable name.

    Returns:
        List of EnrichedIndicator objects. Empty if search_result.items is falsy.
    """
    if not search_result.items:
        return []

    _db = db_mapping or {}

    _label_to_code = {
        "sex": "SEX",
        "age": "AGE",
        "residential area": "URBANISATION",
        "urbanisation": "URBANISATION",
        "education": "EDUCATION",
    }

    indicators: list[EnrichedIndicator] = []
    for item in search_result.items:
        raw = item.model_dump()

        # Extract latest_data and time_period_range
        time_periods = raw.get("time_periods", [])
        latest_data = None
        time_period_range = None
        if time_periods and isinstance(time_periods, list):
            tp = time_periods[0] if isinstance(time_periods[0], dict) else {}
            latest_data = tp.get("LATEST_DATA_POINT") or tp.get("end")
            start = tp.get("start")
            end = tp.get("end")
            if start and end:
                time_period_range = f"{start}-{end}"

        # Check covers_country from ref_country — produce a per-country bool map
        covers_country: dict[str, bool] | None = None
        ref_country = raw.get("ref_country", [])
        if country_code and ref_country and isinstance(ref_country, list):
            country_codes = {
                c.get("code") if isinstance(c, dict) else c for c in ref_country
            }
            requested_codes = [c.strip() for c in country_code.split(";") if c.strip()]
            covers_country = {code: code in country_codes for code in requested_codes}
        elif country_code:
            requested_codes = [c.strip() for c in country_code.split(";") if c.strip()]
            covers_country = {code: False for code in requested_codes}

        # Extract dimension names
        dimensions = raw.get("dimensions", [])
        useful_dims: list[str] = []
        if dimensions and isinstance(dimensions, list):
            for dim in dimensions:
                if isinstance(dim, dict):
                    label = (dim.get("label") or "").lower()
                    if label in _label_to_code:
                        useful_dims.append(_label_to_code[label])

        db_id = raw.get("database_id", "")
        indicators.append(
            EnrichedIndicator(
                idno=raw.get("idno", ""),
                database_id=db_id,
                database_name=_db.get(db_id),
                name=raw.get("name", ""),
                truncated_definition=(raw.get("definition_long") or "")[:100],
                unit=raw.get("measurement_unit"),
                periodicity=raw.get("periodicity"),
                latest_data=latest_data,
                time_period_range=time_period_range,
                covers_country=covers_country,
                dimensions=useful_dims if useful_dims else None,
            )
        )

    # Set requested_country on all indicators
    for ind in indicators:
        ind.requested_country = country_code

    return indicators


async def search(  # noqa: PLR0911
    query: str | None = None,
    required_country: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
    # Multi-query parameters
    queries: list[str] | None = None,
    query_groups: list[QueryGroup] | None = None,
    result_layout: str = "merged",
    dedupe: bool = True,
    # The following parameters are accepted for robustness; LLM clients sometimes
    # hallucinate them from the internal SearchRequest model.
    # n_results/skip are treated as aliases for limit/offset when the primary
    # parameter is still at its default; the rest are silently ignored.
    count: bool = True,
    n_results: int | None = None,
    filter: str | None = None,  # noqa: A002 - name must match LLM-hallucinated param
    orderby: str | None = None,
    select: str | None = None,
    skip: int | None = None,
    odata_options: dict[str, str] | None = None,
) -> "EnrichedSearchResponse | MultiQuerySearchResponse":
    """Search for Data360 indicators with enriched metadata for selection.

    Use this first when the user asks for data on a topic (e.g. unemployment, poverty, GDP).
    No other tools are required before this one.

    ENRICHED DATA VS. FETCHING DATA:
    - For METADATA questions (e.g. "What is the definition of the unemployment rate indicator?", "How frequently is it updated?"): The enriched data returned by this search tool is often sufficient! You can directly use the `truncated_definition`, `name`, `periodicity`, `database_id`, and `latest_data` fields from the search results to answer the user WITHOUT needing to call `data360_get_metadata` or `data360_get_data`.
    - For DATA questions (e.g. "What was Kenya's GDP in 2020?", "Show me the trend of poverty"): The enriched data does NOT contain actual data values (OBS_VALUE). You MUST proceed to call `data360_get_disaggregation` and then `data360_get_data` (or `data360_get_viz_spec` for charts) to retrieve real numbers.

    Use when the user already names a specific indicator or metric — for example:
    "GDP per capita for Kenya", "unemployment rate in Morocco", "life expectancy in Sub-Saharan Africa".

    For multiple topics in one call (e.g. "GDP, inflation, employment for Kenya"), pass them as
    queries=["GDP growth", "inflation rate", "unemployment"] instead of making separate calls.

    Do NOT use this tool when the user asks a broad or vague question that does not name a
    specific indicator — for example: "What makes a country great?",
    "What are Ghana's economic challenges?", "How is education performing in Africa?"
    In those cases, use data360_analyze_development_topic instead, which decomposes
    the question into specific sub-queries and searches for each one.

    PARAMETER SELECTION — follow this decision tree strictly:
    1. ONE topic, any number of countries → use `query` + `required_country`.
    2. MULTIPLE topics, ALL in the SAME country → use `queries` + `required_country`.
    3. Topics targeting DIFFERENT countries → MUST use `query_groups`. Do NOT use `queries`.
       Example — "GDP for Japan and population for Philippines":
         query_groups=[
           {"queries": ["GDP per capita"], "country": "Japan"},
           {"queries": ["population"], "country": "Philippines"}
         ]
       Using `queries` for cross-country requests will lose per-country coverage data.

    Pass exactly ONE of query, queries, or query_groups. Omit the other two entirely.

    Args:
        query: Single search query (e.g., "unemployment rate", "poverty", "GDP per capita").
            Use this for ONE topic. If using this, do not pass queries or query_groups.
        queries: List of search terms for multi-topic search in one call (e.g.
            ["GDP growth", "inflation rate", "unemployment"]).
            Use ONLY when ALL topics target the SAME country (set via required_country).
            If topics span different countries, use query_groups instead.
            Requires at least 2 non-empty strings.
            If using this, do not pass query or query_groups.
        query_groups: List of QueryGroup objects, each binding one or more search terms to
            an optional country scope. Use when different queries target different countries.
            Use this instead of queries when each query targets a different country.
            JSON schema for each group: {"queries": ["<term1>", "<term2>"], "country": "<name or 3-letter code>"}
            Example: [
                {"queries": ["GDP per capita", "inflation"], "country": "Kenya"},
                {"queries": ["Gini coefficient"], "country": "Morocco"}
            ]
            Requires at least 2 non-empty queries total across all groups.
            If using this, do not pass query or queries. required_country is ignored.
        required_country: Optional country name or 3-letter code (e.g. "Kenya", "KEN").
            Use semicolon-separated names or codes to check multiple countries in one call
            (e.g. "China; USA"). Semicolons are used because some country names contain
            commas (e.g. "Korea, Republic of").
            Shared across all queries — only when all topics share the same geographic scope.
            Ignored when query_groups is used (each group has its own country).
        limit: Maximum number of indicators per query (default 5).
        offset: Number of results to skip per query for pagination (default 0).
        result_layout: Only used with queries/query_groups.
            Use "merged" (default) when you want a single flat list to pick from.
            Use "by_query" when you need to know which indicators came from which query —
            e.g. to attribute country coverage per query or display grouped results.
        dedupe: Only used with queries/query_groups. When True (default), deduplicates by
            (database_id, idno) across all query groups. First-seen order is preserved.

    Returns:
        With query: EnrichedSearchResponse with indicators, required_country, pagination fields.
            Each indicator has covers_country (dict[str, bool], e.g. {\"KEN\": True}) and
            requested_country (resolved semicolon-separated code string).
        With queries/query_groups: MultiQuerySearchResponse with indicators (merged) or
            results (by_query), total_candidates, deduplicated_count, and per-group errors.
            Each indicator has requested_country showing which group's country it was evaluated against.
        error: Error message string if the request failed; otherwise None.
    """

    # --- Validation ---
    # Normalise LLM-hallucinated empty defaults before mode detection.
    # When a client sends query="" or queries=[] alongside the real parameter
    # (e.g. query_groups), treat these as "not provided" — identical to None.
    if query is not None and not query.strip():
        _logger.debug("query='%s' normalised to None (empty/whitespace-only)", query)
        query = None
    if queries is not None and not any(q and q.strip() for q in queries):
        _logger.debug("queries=%r normalised to None (all entries empty)", queries)
        queries = None

    active_modes = sum((
        query is not None,
        queries is not None,
        query_groups is not None,
    ))
    if active_modes > 1:
        return EnrichedSearchResponse(
            error="Provide exactly one of 'query', 'queries', or 'query_groups', not multiple."
        )
    if active_modes == 0:
        return EnrichedSearchResponse(
            error="One of 'query', 'queries', or 'query_groups' must be provided."
        )


    # --- Multi-query path (queries= flat list) ---
    if queries is not None:
        clean_queries = [q.strip() for q in queries if q and q.strip()]
        if len(clean_queries) < len(queries):
            _logger.warning(
                "Stripped %d empty/whitespace-only entries from queries "
                "(original: %d, kept: %d)",
                len(queries) - len(clean_queries),
                len(queries),
                len(clean_queries),
            )
        if len(clean_queries) < 2:  # noqa: PLR2004
            return MultiQuerySearchResponse(
                error="'queries' must contain at least 2 non-empty search strings.",
                queries=queries or [],
            )
        if result_layout not in ("merged", "by_query"):
            return MultiQuerySearchResponse(
                error="result_layout must be 'merged' or 'by_query'.",
                queries=clean_queries,
            )

        # Handle limit/offset aliases (mirror single-query path warnings)
        if n_results is not None:
            if limit == DEFAULT_SEARCH_LIMIT:
                limit = n_results
            elif limit != n_results:
                _logger.warning(
                    "Both limit=%d and n_results=%d provided; using limit",
                    limit,
                    n_results,
                )
        if skip is not None:
            if offset == 0:
                offset = skip
            elif offset != skip:
                _logger.warning(
                    "Both offset=%d and skip=%d provided; using offset",
                    offset,
                    skip,
                )

        # Resolve shared country once for all sub-queries
        country_code: str | None = None
        if required_country:
            country_code = await _resolve_country_code(required_country)

        # Each query gets the same country code
        per_query_codes: list[str | None] = [country_code] * len(clean_queries)

        # Fan out concurrent _search_raw calls, one per query
        raw_tasks = [
            _search_raw(query=q, limit=limit, offset=offset, select_fields=_ENRICHMENT_SELECT_FIELDS)
            for q in clean_queries
        ]
        raw_results = await asyncio.gather(*raw_tasks, return_exceptions=True)

        db_mapping = await get_database_mapping()
        return await _build_multi_query_response(
            clean_queries=clean_queries,
            raw_results=raw_results,
            per_query_codes=per_query_codes,
            result_layout=result_layout,
            dedupe=dedupe,
            db_mapping=db_mapping,
        )

    # --- query_groups path ---
    if query_groups is not None:
        if required_country:
            _logger.warning(
                "required_country is ignored when query_groups is used; "
                "set country per QueryGroup instead."
            )

        # Flatten groups into (query, raw_country) pairs, stripping empty entries
        flat_pairs: list[tuple[str, str | None]] = []
        for group in query_groups:
            for q in group.queries:
                stripped = q.strip() if q else ""
                if stripped:
                    flat_pairs.append((stripped, group.country))
                else:
                    _logger.warning(
                        "Empty/whitespace-only query stripped from query_groups."
                    )

        if len(flat_pairs) < 2:  # noqa: PLR2004
            return MultiQuerySearchResponse(
                error="query_groups must produce at least 2 non-empty queries total.",
                queries=[fp[0] for fp in flat_pairs],
            )
        if result_layout not in ("merged", "by_query"):
            return MultiQuerySearchResponse(
                error="result_layout must be 'merged' or 'by_query'.",
                queries=[fp[0] for fp in flat_pairs],
            )

        # Handle limit/offset aliases
        if n_results is not None:
            if limit == DEFAULT_SEARCH_LIMIT:
                limit = n_results
            elif limit != n_results:
                _logger.warning(
                    "Both limit=%d and n_results=%d provided; using limit",
                    limit,
                    n_results,
                )
        if skip is not None:
            if offset == 0:
                offset = skip
            elif offset != skip:
                _logger.warning(
                    "Both offset=%d and skip=%d provided; using offset",
                    offset,
                    skip,
                )

        # Resolve unique country values concurrently to avoid redundant codelist lookups
        unique_countries = list({c for _, c in flat_pairs if c})
        resolved_map: dict[str, str | None] = {}
        if unique_countries:
            codes = await asyncio.gather(
                *[_resolve_country_code(c) for c in unique_countries]
            )
            resolved_map = dict(zip(unique_countries, codes))

        clean_queries = [q for q, _ in flat_pairs]
        per_query_codes = [
            resolved_map.get(c) if c else None
            for _, c in flat_pairs
        ]

        # Fan out concurrent _search_raw calls, one per flattened query
        raw_tasks = [
            _search_raw(query=q, limit=limit, offset=offset, select_fields=_ENRICHMENT_SELECT_FIELDS)
            for q in clean_queries
        ]
        raw_results = await asyncio.gather(*raw_tasks, return_exceptions=True)

        db_mapping = await get_database_mapping()
        return await _build_multi_query_response(
            clean_queries=clean_queries,
            raw_results=raw_results,
            per_query_codes=per_query_codes,
            result_layout=result_layout,
            dedupe=dedupe,
            db_mapping=db_mapping,
        )

    # --- Single-query path (original behavior, fully preserved) ---
    # Handle common parameter aliases sent by LLM clients.
    # Aliases only apply when the primary parameter is at its default value;
    # an explicit limit/offset always takes precedence over n_results/skip.
    if n_results is not None:
        if limit == DEFAULT_SEARCH_LIMIT:
            limit = n_results
        elif limit != n_results:
            _logger.warning(
                "Both limit=%d and n_results=%d provided; using limit",
                limit,
                n_results,
            )
    if skip is not None:
        if offset == 0:
            offset = skip
        elif offset != skip:
            _logger.warning(
                "Both offset=%d and skip=%d provided; using offset",
                offset,
                skip,
            )

    # NOTE: This function is for MVP only, we should be testing the relevance and performance
    # of the retrieval process in the future.
    # Resolve country code upfront using cached codelist
    country_code = None
    if required_country:
        country_code = await _resolve_country_code(required_country)

    # Fetch all needed metadata in ONE search call
    search_result = await _search_raw(
        query=query,  # type: ignore[arg-type]  # validated non-None above
        limit=limit,
        offset=offset,
        select_fields=_ENRICHMENT_SELECT_FIELDS,
    )

    if search_result.error:
        return EnrichedSearchResponse(error=search_result.error)

    if not search_result.items:
        return EnrichedSearchResponse(error=f"No indicators found for: '{query}'")

    db_mapping = await get_database_mapping()
    indicators = _enrich_search_results(search_result, country_code, db_mapping)

    # Sort: covers_country=True first, then by latest_data descending
    if country_code:
        indicators.sort(
            key=lambda x: (
                not any((x.covers_country or {}).values()),
                -(int(x.latest_data or 0) if str(x.latest_data or "").isdigit() else 0),
            )
        )

    return EnrichedSearchResponse(
        indicators=indicators,
        required_country=country_code,
        # Map pagination fields from underlying search result
        count=search_result.count,
        total_count=search_result.total_count,
        offset=search_result.offset,
        has_more=search_result.has_more,
        next_offset=search_result.next_offset,
    )


async def _build_multi_query_response(
    clean_queries: list[str],
    raw_results: list[Any],
    per_query_codes: list[str | None],
    result_layout: str,
    dedupe: bool,
    db_mapping: dict[str, str] | None = None,
) -> MultiQuerySearchResponse:
    """Shared response builder for queries= and query_groups= paths.

    Encapsulates enrichment, deduplication, and layout selection so both
    paths stay in sync without code duplication.
    """
    seen_dict: dict[tuple[str, str], EnrichedIndicator] = {}
    groups: list[QueryGroupResult] = []
    total_candidates = 0
    deduplicated_count = 0

    for i, (q, raw_result) in enumerate(zip(clean_queries, raw_results)):
        code_for_query = per_query_codes[i]
        if isinstance(raw_result, Exception):
            groups.append(QueryGroupResult(
                query=q,
                country_code=code_for_query,
                error=str(raw_result),
            ))
            continue
        if raw_result.error or not raw_result.items:
            groups.append(QueryGroupResult(
                query=q,
                country_code=code_for_query,
                error=raw_result.error or f"No indicators found for: '{q}'",
            ))
            continue

        enriched = _enrich_search_results(raw_result, code_for_query, db_mapping)
        total_candidates += len(enriched)

        group_indicators: list[EnrichedIndicator] = []
        group_seen: set[tuple[str, str]] = set()

        for ind in enriched:
            key = (ind.database_id, ind.idno)

            if key in seen_dict:
                existing_ind = seen_dict[key]

                # Merge covers_country data across queries/groups
                if existing_ind.covers_country is not None and ind.covers_country is not None:
                    existing_ind.covers_country.update(ind.covers_country)

                if dedupe and result_layout == "merged":
                    # Global deduplication: discard from subsequent groups in merged layout
                    deduplicated_count += 1
                else:
                    # In by_query layout, or if dedupe=False, we keep the indicator.
                    # But if dedupe=True, we still deduplicate WITHIN the same group.
                    if dedupe and key in group_seen:
                        deduplicated_count += 1
                    else:
                        group_seen.add(key)
                        group_indicators.append(existing_ind)
            else:
                seen_dict[key] = ind
                group_seen.add(key)
                group_indicators.append(ind)

        groups.append(QueryGroupResult(
            query=q,
            country_code=code_for_query,
            indicators=group_indicators,
            count=len(group_indicators),
        ))

    # Compute response-level required_country: join all unique resolved codes with ";"
    all_codes = sorted({c for c in per_query_codes if c})
    response_country = ";".join(all_codes) if all_codes else None

    if result_layout == "merged":
        merged_indicators: list[EnrichedIndicator] = [
            ind for g in groups for ind in g.indicators
        ]
        # Sort: covers_country=True first (per-indicator, already correct), then recency
        if response_country:
            merged_indicators.sort(
                key=lambda x: (
                    not any((x.covers_country or {}).values()),
                    -(int(x.latest_data or 0) if str(x.latest_data or "").isdigit() else 0),
                )
            )
        return MultiQuerySearchResponse(
            indicators=merged_indicators,
            result_layout="merged",
            queries=clean_queries,
            required_country=response_country,
            total_candidates=total_candidates,
            deduplicated_count=deduplicated_count if dedupe else None,
        )
    else:  # by_query
        return MultiQuerySearchResponse(
            results=groups,
            result_layout="by_query",
            queries=clean_queries,
            required_country=response_country,
            total_candidates=total_candidates,
            deduplicated_count=deduplicated_count if dedupe else None,
        )


# ruff: noqa: PLR0913, PLR0912, PLR0915
async def get_metadata(
    database_id: str,
    indicator_id: str,
    select_fields: list[str] | None = None,
    get_valid_disaggregations_func: Any | None = None,
    fetch_disaggregation: bool = True,
    required_country: str | None = None,
) -> MetadataResponse:
    """Get metadata and disaggregation options for a Data360 indicator.

    Call after data360_search_indicators only when you need deep metadata NOT included in the enriched search results (e.g. methodology, source notes). If the user asks a basic metadata question (like definition or periodicity), simply answer using the fields provided by data360_search_indicators.

    For valid filter values (years, country codes, SEX/AGE/URBANISATION), prefer data360_get_disaggregation. data360_get_data and data360_get_viz_spec call get_metadata internally.

    Args:
        database_id: Database identifier (e.g., IPC_IPC, WB_GS).
        indicator_id: Indicator ID (e.g., IPC_IPC_PHASE, WB_GS_NY_GDP_PCAP_KD).
        select_fields: Optional list of metadata fields to return. If None, returns all fields.
            Available fields: methodology, statistical_concept, definition_long, limitation,
            relevance, aggregation_method, periodicity, time_periods, ref_country, sources_note.
        get_valid_disaggregations_func: Internal parameter — do not pass this; leave it as None.
        fetch_disaggregation: If True (default), also fetch disaggregation dimensions (field_name, field_value).
        required_country: Optional country name or 3-letter code (e.g. "Kenya", "KEN").
            Use semicolon-separated for multiple (e.g. "China; USA"). When provided,
            REF_AREA in disaggregation shows which queried countries have data.

    Returns:
        MetadataResponse:
            indicator_metadata: Dict of requested metadata fields for the indicator, or None if not found.
            disaggregation_options: List of dicts with field_name and field_value (list of valid codes).
                Dimensions with no disaggregation (INDICATOR, FREQ, single-_T SEX/AGE/URBANISATION)
                are omitted. REF_AREA is summarized as {count, sample} or {count, queried}
                instead of the full field_value list.
            error: Error message string if any request failed; otherwise None.
    """
    # Use provided function or default
    if get_valid_disaggregations_func is None:
        get_valid_disaggregations_func = _get_valid_disaggregations

    # Resolve country codes if provided
    queried_countries = await _resolve_queried_countries(required_country)

    # Validate inputs
    try:
        MetadataRequest(database_id=database_id, indicator_id=indicator_id)
    except PydanticValidationError as e:
        mcp_err = Data360ValidationError(
            context="metadata",
            detail=f"Invalid arguments: {e}",
            original_error=e,
        )
        return MetadataResponse(error=mcp_err.detail)

    # Determine URLs
    metadata_url = data360_config.metadata_url or f"{data360_config.api_url}/metadata"
    disaggregation_url = (
        data360_config.disaggregation_url or f"{data360_config.api_url}/disaggregation"
    )

    indicator_metadata: dict[str, Any] | None = None
    disaggregations: list[dict[str, Any]] = []
    errors: list[str] = []
    headers = {"accept": "*/*", "Content-Type": "application/json"}

    # Build query with optional select clause
    query = f"series_description/idno eq '{indicator_id}'"
    if select_fields:
        select_clause = ", ".join(f"series_description/{f}" for f in select_fields)
        metadata_payload = {"query": query, "select": select_clause}
    else:
        metadata_payload = {"query": query}

    # 1. Fetch Metadata
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            metadata_res = await client.post(
                metadata_url, json=metadata_payload, headers=headers
            )
            metadata_res.raise_for_status()

            try:
                metadata_json = metadata_res.json()
                if metadata_json and metadata_json.get("value"):
                    indicator_metadata = metadata_json["value"][0].get(
                        "series_description", {}
                    )
                    # Inject database_name so clients always have the correct, grounded
                    # label for the database_id — prevents LLMs from guessing
                    # (e.g. WB_GS is "Gender Statistics", not "Global Statistics").
                    if indicator_metadata:
                        db_id = indicator_metadata.get("database_id", database_id)
                        db_mapping = await get_database_mapping()
                        indicator_metadata["database_name"] = db_mapping.get(db_id)
                    # Force filtering if select_fields provided (API might return more).
                    # Always retain database_name regardless of select_fields.
                    if select_fields and indicator_metadata:
                        indicator_metadata = {
                            k: v
                            for k, v in indicator_metadata.items()
                            if k in select_fields or k == "database_name"
                        }
                else:
                    mcp_err = NotFoundError(
                        context="metadata",
                        detail=f"No metadata found for indicator ID '{indicator_id}'",
                    )
                    errors.append(mcp_err.detail)
            except ValueError as e:
                mcp_err = ParseError(context="metadata", original_error=e)
                errors.append(mcp_err.detail)

    except Exception as e:
        mcp_err = classify_error(e, context="metadata")
        errors.append(mcp_err.detail)

    # 2. Fetch Disaggregation
    if fetch_disaggregation:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                disagg_res = await client.get(
                    disaggregation_url,
                    params={"datasetId": database_id, "indicatorId": indicator_id},
                    headers=headers,
                )
                disagg_res.raise_for_status()

                try:
                    raw_disaggregations = disagg_res.json()
                    disaggregations = _strip_disaggregation(
                        get_valid_disaggregations_func(raw_disaggregations),
                        queried_countries,
                    )
                except ValueError as e:
                    mcp_err = ParseError(context="disaggregation", original_error=e)
                    errors.append(mcp_err.detail)

        except Exception as e:
            mcp_err = classify_error(e, context="disaggregation")
            errors.append(mcp_err.detail)

    # 3. Combine and Return
    error_message = "; ".join(errors) if errors else None

    return MetadataResponse(
        indicator_metadata=indicator_metadata,
        disaggregation_options=disaggregations,
        error=error_message,
    )


async def get_disaggregation(
    database_id: str,
    indicator_id: str,
    required_country: str | None = None,
) -> dict[str, Any]:
    """Get disaggregation options for a Data360 indicator (valid filter values).

    Call before data360_get_data or data360_get_viz_spec to see which filter values are available.
    Typically call after data360_search_indicators when you need available years or breakdowns.
    Use the returned values in disaggregation_filters; do not use FREQ for filtering (it breaks queries).

    After calling this tool, use the returned field_value codes directly as disaggregation_filters
    in data360_get_data or data360_get_viz_spec. For example, if SEX returns ["M", "F", "_T"],
    pass {"SEX": "F"} to filter to female-only data.

    Args:
        database_id: Database identifier (e.g., WB_GS, WB_SSGD).
        indicator_id: Indicator ID (e.g., WB_GS_NY_GDP_PCAP_KD).
        required_country: Optional country name or 3-letter code (e.g. "Kenya", "KEN").
            Use semicolon-separated names or codes to check multiple countries in one call (e.g. "China; USA").
            When provided, REF_AREA shows which queried countries have data for this indicator.

    Returns:
        On success: dict with key "dimensions", a list of dicts. Trivial dimensions
            (INDICATOR, FREQ, single-_T SEX/AGE/URBANISATION) are omitted. Each dict has:
            field_name: Dimension name (e.g. TIME_PERIOD, REF_AREA, SEX).
            field_value: List of valid codes (for TIME_PERIOD sorted chronologically; for SEX/AGE etc.).
            REF_AREA is special: returns {count, sample} (5 sorted codes) or, when
            required_country is given, {count, queried: {code: bool}}.
        On failure: dict with key "error" and an error message string.
        TIME_PERIOD gives actual available years (may have gaps).
    """
    # Resolve country codes if provided
    queried_countries = await _resolve_queried_countries(required_country)

    disaggregation_url = (
        data360_config.disaggregation_url or f"{data360_config.api_url}/disaggregation"
    )
    headers = {"accept": "*/*", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                disaggregation_url,
                params={"datasetId": database_id, "indicatorId": indicator_id},
                headers=headers,
            )
            response.raise_for_status()

            raw_data = response.json()
            # Filter out _Z values and format response
            valid_dimensions = _get_valid_disaggregations(raw_data)
            return {"dimensions": _strip_disaggregation(valid_dimensions, queried_countries)}

    except Exception as e:
        mcp_err = classify_error(e, context="disaggregation")
        return {"error": mcp_err.detail}


async def get_data(
    database_id: str,
    indicator_id: str,
    country_code: str | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> IndicatorDataResponse:
    """Fetch indicator data from the Data360 API with pagination.

    Call after you have database_id and indicator_id (from data360_search_indicators). Use
    data360_get_disaggregation to get valid filter values; passing invalid values can yield empty results.
    For charts, prefer data360_get_viz_spec, which fetches data internally.

    Args:
        database_id: Database identifier (e.g., "IPC_IPC", "WB_GS").
        indicator_id: Indicator ID (e.g., "IPC_IPC_PHASE", "WB_GS_NY_GDP_PCAP_KD").
        country_code: Optional 3-letter code or semicolon-separated list (e.g. "KEN" or "KEN;MAR").
            Applied as REF_AREA filter. Takes precedence over REF_AREA in disaggregation_filters.
        disaggregation_filters: Optional dict of dimension filters. Keys: REF_AREA, SEX, AGE,
            URBANISATION, UNIT_MEASURE, etc. REF_AREA supports comma-separated codes (e.g. "KEN,TZA").
            Use value None to request all values for a dimension (e.g. {"SEX": None}).
        start_year: Optional start year (inclusive). Defaults to last 5 years if both start/end omitted.
        end_year: Optional end year (inclusive). Defaults to current year if both start/end omitted.
        limit: Maximum records per page (default 50, max 100).
        offset: Number of records to skip for pagination (default 0).

    Returns:
        IndicatorDataResponse:
            data: List of data point dicts (e.g. TIME_PERIOD, REF_AREA, OBS_VALUE, claim_id).
            metadata: Indicator metadata dict if available.
            count: Number of records in this response.
            total_count: Total records available, or None.
            offset, has_more, next_offset: Use next_offset for the next page when has_more is True.
            error: Error message if the request failed; otherwise None.
                If error contains "No metadata found", the indicator_id is invalid or stale.
                Do NOT retry with the same ID and do NOT call data360_search_indicators again.
                Instead, look back at the other indicators already returned by the previous
                data360_search_indicators call in this conversation and try the next best match.
                Only call data360_search_indicators again if no prior search results exist in context.
                If error is about a disaggregation or HTTP failure but data is still None,
                the upstream API may be temporarily unavailable — retry once or report the error.
            failed_validation: Optional list of filter validation messages. Non-empty means
                some filters were invalid; data may still be returned with valid filters applied.
    """
    data_url = data360_config.data_url or f"{data360_config.api_url}/data"

    # Cap limit to prevent token overflow
    limit = min(limit, 100)

    # Smart time defaults: if no time range specified, default to last 5 years
    if start_year is None and end_year is None:
        from datetime import datetime  # noqa: PLC0415

        current_year = datetime.now().year
        end_year = current_year
        start_year = current_year - 19  # Last 20 years
        _logger.info(f"Smart default: Applied time range {start_year}-{end_year}")

    # Validate arguments using Pydantic model
    try:
        IndicatorDataRequest(
            database_id=database_id,
            indicator_id=indicator_id,
            disaggregation_filters=disaggregation_filters,
        )
    except PydanticValidationError as e:
        mcp_err = Data360ValidationError(
            context="data",
            detail=f"Invalid arguments: {e}",
            original_error=e,
        )
        return IndicatorDataResponse(error=mcp_err.detail)

    # Prepare API parameters
    params: dict[str, Any] = {
        "DATABASE_ID": database_id,
        "INDICATOR": indicator_id,
        "timePeriodFrom": str(start_year),
        "timePeriodTo": str(end_year),
        "skip": offset,
        # Request one extra to detect if there are more results
        # Note: API uses "top" not "$top" (OData style would be URL-encoded to %24top which API ignores)
        "top": limit + 1,
    }

    # Convert semicolon-separated list into comma-separated list for Data API
    if country_code:
        # Takes precedence over REF_AREA in disaggregation_filters
        params["REF_AREA"] = country_code.replace(";", ",")

    # Fetch metadata and disaggregations FIRST to inform parameter building
    # This ensures we don't apply invalid defaults (like AGE=_T) which cause empty results
    metadata_res = await get_metadata(
        database_id,
        indicator_id,
        select_fields=[
            "idno",
            "name",
            "database_id",
            "periodicity",
            "measurement_unit",
            "definition_short",
        ],
        fetch_disaggregation=True,  # Crucial: fetch valid options
        required_country=country_code,  # Pass for REF_AREA validation
    )

    if metadata_res.error:
        if metadata_res.indicator_metadata is None:
            # Fatal: indicator not found or completely unavailable.
            _logger.warning(
                "Aborting get_data for %s: indicator metadata missing. Error: %s",
                indicator_id,
                metadata_res.error,
            )
            return IndicatorDataResponse(error=metadata_res.error)
        # Non-fatal: disaggregation lookup failed but indicator metadata is valid.
        # Proceed without validated disaggregation defaults.
        _logger.warning(
            "Non-fatal metadata error for %s (proceeding without disaggregation defaults): %s",
            indicator_id,
            metadata_res.error,
        )

    api_metadata = metadata_res.indicator_metadata or {}

    # Process valid disaggregations into {dim: [values]} format
    available_disaggregations = {}
    for d in metadata_res.disaggregation_options or []:
        if d.get("field_name") and d.get("field_value"):
            available_disaggregations[d["field_name"]] = d["field_value"]

    # Validate user filters BEFORE applying defaults
    # This gives hints for hallucinations like SEX=ALIEN
    valid_filters, validation_errors = _validate_user_filters(
        disaggregation_filters, available_disaggregations
    )
    if validation_errors:
        _logger.warning(f"Validation errors for {indicator_id}: {validation_errors}")

    # Use only valid filters for building params
    effective_disagg = _build_disaggregation_params(
        valid_filters, available_disaggregations=available_disaggregations
    )
    params.update(effective_disagg)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            _logger.debug("Fetching data from %s with params: %s", data_url, params)
            data_res = await client.get(data_url, params=params)
            data_res.raise_for_status()

            try:
                data_json = data_res.json()
            except ValueError as e:
                mcp_err = ParseError(context="data", original_error=e)
                return IndicatorDataResponse(data=None, error=mcp_err.detail)

            raw_data = data_json.get("value", [])
            total_count = data_json.get("@odata.count")  # May be None

            # Compute API-level pagination BEFORE any filtering
            # This ensures next_offset correctly tracks position in the API result set
            api_returned_count = len(raw_data)
            has_more = api_returned_count > limit

            # Trim the extra detection row (we requested limit+1 to detect has_more)
            if api_returned_count > limit:
                raw_data = raw_data[:limit]

            # Compute API-based next_offset - the true cursor position for next page
            api_next_offset = offset + len(raw_data) if has_more else None

            # Sort by TIME_PERIOD descending (most recent first)
            raw_data.sort(key=lambda x: str(x.get("TIME_PERIOD", "")), reverse=True)

            # Final limit enforcement (safety check)
            if len(raw_data) > limit:
                raw_data = raw_data[:limit]

            # Add claim_id for data verification (computed on raw row)
            for row in raw_data:
                row["claim_id"] = _short_hash(row)

            # Promote COMMENT_TS to metadata (repeats identically per row)
            if raw_data and api_metadata is not None:
                comment_ts = next(
                    (r.get("COMMENT_TS") for r in raw_data if r.get("COMMENT_TS")),
                    None,
                )
                if comment_ts:
                    api_metadata["indicator_description"] = comment_ts

            # Strip boilerplate fields for LLM token savings
            raw_data = [_strip_data_row(row) for row in raw_data]

            return IndicatorDataResponse(
                data=raw_data,
                metadata=api_metadata,
                count=len(raw_data),
                total_count=total_count,
                offset=offset,
                has_more=has_more,
                next_offset=api_next_offset,
                error=None,
                failed_validation=validation_errors if validation_errors else None,
            )

    except Exception as e:
        mcp_err = classify_error(e, context="data")
        return IndicatorDataResponse(data=None, error=mcp_err.detail)


async def get_indicators(database_id: str) -> list[str]:
    """Get all indicator IDs for a specific database.

    Use when you need the full list of indicator IDs for a dataset. For discovery by topic,
    use data360_search_indicators instead. You must know the database_id (e.g. from search or docs).

    Args:
        database_id: The database identifier (e.g., "WB_WDI", "WB_GS").

    Returns:
        List of indicator ID strings for that database. Empty list on error or if none exist.
    """
    url = f"{data360_config.api_url}/indicators"
    params = {"datasetId": database_id}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            if isinstance(data, list):
                # Data is a list of indicator ID strings
                return data
            return []

    except Exception as e:
        _logger.error(f"Failed to fetch indicators for {database_id}: {e}")
        raise


async def discover_indicators(
    query: str,
    required_country: str | None = None,
    required_dimensions: list[str] | None = None,
    limit: int = 5,
) -> DiscoveryResult:
    """Search for indicators and validate their capabilities.

    .. deprecated::
        This function is deprecated. Use the following workflow instead:
        1. search() with select_fields for candidates
        2. get_disaggregation() to validate availability
        3. get_metadata() with select_fields for specific info

    This is the primary tool that combines:
    1. Search for top K indicators matching the query
    2. Fetch metadata for all K indicators in parallel
    3. Cross-check capabilities (countries, dimensions available)
    4. Return condensed, validated results for LLM to select from

    Args:
        query: Search query string (e.g., "unemployment rate", "poverty")
        required_country: Country name or code to validate (e.g., "Kenya" or "KEN")
        required_dimensions: List of required disaggregations (e.g., ["SEX", "AGE"])
        limit: Maximum number of indicators to search and validate (default: 5)

    Returns:
        DiscoveryResult with list of validated indicator summaries and optional error

    Example:
        discover_indicators(
            query="unemployment rate",
            required_country="Kenya",
            required_dimensions=["SEX", "AGE"]
        )
    """
    import warnings  # noqa: PLC0415

    warnings.warn(
        "discover_indicators is deprecated. Use search() + get_disaggregation() + get_metadata() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # ... existing implementation ...


# --- Topic Analysis Helpers ---

# Conjunctions and stopwords used for rule-based query decomposition.
# Conjunctions and stopwords used for rule-based query decomposition.
_STOPWORDS = frozenset({
    "what", "are", "the", "main", "is", "a", "an", "of", "for", "in",
    "to", "how", "does", "do", "its", "their", "has", "been", "being",
    "with", "on", "at", "by", "from", "about", "between", "which",
    "facing", "challenges", "issues", "problems", "region", "country",
    "makes", "great", "key", "major", "most", "important",
})
_DEFAULT_SUMMARY_YEARS = 5

# System prompt for the sampling call. FastMCP automatically appends the
# JSON schema of _DecompositionResult when result_type is provided, so the
# prompt only needs to describe the intent and field semantics.
_SAMPLING_SYSTEM_PROMPT = (
    "You are a development economist. Given the user's question about "
    "development data or indicators, generate 3-5 specific, measurable "
    "topics that can be searched in a statistical database (e.g. World "
    "Bank indicators).\n\n"
    "Respond using the provided JSON schema:\n"
    "- If the question mentions MULTIPLE countries with DIFFERENT topics per country, "
    "populate 'query_groups' with per-country search terms and leave 'sub_queries' null.\n"
    "- Otherwise, populate 'sub_queries' with a flat list of short search strings "
    "and leave 'query_groups' null.\n"
    "Do not populate both fields simultaneously."
)


class _SampledQueryGroup(BaseModel):
    """A set of search queries scoped to a specific country (from structured sampling output)."""

    queries: list[str]
    country: str


class _DecompositionResult(BaseModel):
    """Structured sampling output for topic decomposition.

    FastMCP enforces this schema on the LLM response, eliminating the need
    for manual JSON parsing or regex extraction.

    Exactly one of sub_queries or query_groups should be populated.
    """

    sub_queries: list[str] | None = None
    query_groups: list[_SampledQueryGroup] | None = None


def _score_indicator(
    indicator: "EnrichedIndicator",
    query_tokens: set[str],
) -> float:
    """Score an indicator for relevance to the original query.

    Scoring factors:
    - Country coverage: +2 if covers_country has any True entry
    - Data recency: +1 if latest_data is within the last 3 years, +0.5 within 10 years
    - Token overlap: proportion of query tokens found in indicator name + definition
    """
    score = 0.0

    if indicator.covers_country and any(indicator.covers_country.values()):
        score += 2.0

    try:
        from datetime import datetime  # noqa: PLC0415
        latest = int(indicator.latest_data or "0")
        current_year = datetime.now().year
        if latest >= current_year - 3:
            score += 1.0
        elif latest >= current_year - 10:
            score += 0.5
    except (ValueError, TypeError):
        pass

    indicator_text = f"{indicator.name} {indicator.truncated_definition}".lower()
    indicator_tokens = set(indicator_text.split())
    if query_tokens:
        overlap = len(query_tokens & indicator_tokens)
        score += overlap / max(len(query_tokens), 1)

    return score


async def analyze_development_topic(
    query: str,
    country: str | None = None,
    max_indicators: int = 4,
    start_year: int | None = None,
    end_year: int | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Analyze a development topic by finding and fetching relevant indicators.

    Use this tool when the user asks a broad or vague question about development
    data that does not name a specific indicator — for example:
    "What makes a country great?", "What are Ghana's economic challenges?",
    "How is education performing in Sub-Saharan Africa?"

    The tool decomposes the question into specific searchable topics using the
    connected LLM (when sampling is available). If sampling fails, it proceeds
    with the raw query. It searches the Data360 catalog for each topic, scores and ranks
    the results, and prefetches recent data for the top indicators.

    Do NOT use this tool when the user already names a specific indicator or
    metric (e.g. "GDP per capita for Kenya") — use data360_search_indicators
    and data360_get_data directly instead.

    Args:
        query: The user's development-related question (can be vague/broad).
        country: Optional country name or 3-letter code (e.g. "Ghana", "GHA").
            Can also be comma-separated for multi-country comparisons (e.g. "Morocco, Ethiopia").
        max_indicators: Maximum number of indicators to return (default 4, max 6).
        start_year: Optional start year for data snapshots. Defaults to last 5 years.
        end_year: Optional end year for data snapshots. Defaults to current year.
        ctx: MCP Context object (injected by FastMCP). Used for sampling when available.

    Returns:
        Dict with:
            query: The original question.
            country / country_code: Resolved country info (if provided). May be comma-separated.
            sub_queries: The decomposed search terms (from LLM or rule-based).
            decomposition_method: "sampling_client", "sampling_server", or "none".
            selected_indicators: List of ranked indicator dicts, each with:
                rank, indicator_id, database_id, database_name, name, definition,
                matched_sub_queries (dict with original_query and decomposed_sub_query),
                score, data_snapshot (list of recent data points), data_error (if fetch failed).
            coverage_note: Summary of how many indicators were found.
            error: Top-level error message if the entire operation failed.
    """
    from datetime import datetime  # noqa: PLC0415

    max_indicators = min(max_indicators, 6)
    current_year = datetime.now().year
    if end_year is None:
        end_year = current_year
    if start_year is None:
        start_year = current_year - _DEFAULT_SUMMARY_YEARS + 1

    # --- Step 1: Resolve country code ---
    country_code = None
    if country:
        country_code = await _resolve_country_code(country)

    # --- Step 2: Decompose query into sub-queries ---
    # Attempt LLM-powered decomposition via MCP sampling (structured output).
    # On any failure — client does not support sampling, LiteLLM call fails,
    # or the response does not validate — log a warning and proceed with
    # the raw query. No partial JSON fallback is attempted.
    sub_queries: list[str] = []
    query_groups_from_sampling: list[QueryGroup] | None = None
    decomposition_method = "none"

    _logger.info(
        "analyze_development_topic: ctx=%s, type=%s",
        ctx is not None,
        type(ctx).__name__ if ctx is not None else "None",
    )

    if ctx is not None:
        try:
            # Determine tier before calling so we can surface it in the response.
            # Tier 1: client advertises native MCP sampling support.
            # Tier 2: server-side LiteLLM handler acts as fallback.
            from mcp.types import ClientCapabilities, SamplingCapability  # noqa: PLC0415
            _has_native_sampling = ctx.session.check_client_capability(
                ClientCapabilities(sampling=SamplingCapability())
            )
            _sampling_tier = "sampling_client" if _has_native_sampling else "sampling_server"

            sampling_result = await ctx.sample(
                f"User question: {query}",
                system_prompt=_SAMPLING_SYSTEM_PROMPT,
                result_type=_DecompositionResult,
                max_tokens=512,
            )
            decomposition: _DecompositionResult = sampling_result.result

            # Case A: grouped format — different topics per country
            if decomposition.query_groups:
                query_groups_from_sampling = [
                    QueryGroup(
                        queries=[q.strip() for q in g.queries if q and q.strip()][:5],
                        country=g.country,
                    )
                    for g in decomposition.query_groups
                    if g.queries
                ]
                if query_groups_from_sampling:
                    decomposition_method = _sampling_tier
                    sub_queries = [
                        q for g in query_groups_from_sampling for q in g.queries
                    ]
                    _logger.info(
                        "Sampling decomposition succeeded (grouped, tier=%s): %s",
                        decomposition_method,
                        query_groups_from_sampling,
                    )

            # Case B: flat format — same topics for all countries (or no country)
            elif decomposition.sub_queries:
                sub_queries = [
                    s.strip() for s in decomposition.sub_queries
                    if s and s.strip()
                ][:5]
                if sub_queries:
                    decomposition_method = _sampling_tier
                    _logger.info(
                        "Sampling decomposition succeeded (flat, tier=%s): %s",
                        decomposition_method,
                        sub_queries,
                    )

        except Exception:
            # Sampling unavailable (client does not support it) or the LiteLLM
            # call failed. Log and proceed with the raw query.
            _logger.warning(
                "Sampling unavailable or failed; proceeding with raw query.",
                exc_info=True,
            )

    # Proceed with the raw query when sampling produced nothing
    if not sub_queries:
        sub_queries = [query.strip()]
        decomposition_method = "none"

    _logger.info(
        "Decomposed into %d sub-queries (%s): %s",
        len(sub_queries),
        decomposition_method,
        sub_queries,
    )

    # --- Step 3: Search for indicators ---
    # Route to one of three paths based on the decomposition output:
    # Path A — sampling returned grouped structure: use query_groups directly
    # Path B — flat sub-queries + multiple countries detected: build cross-product query_groups
    # Path C — single country or no country: use queries= + required_country=
    all_indicators: list[tuple[EnrichedIndicator, str]] = []
    total_candidates = 0

    # Detect multi-country input for Path B
    multi_country_codes: list[str] = []
    if country_code and "," in country_code:
        multi_country_codes = [c.strip() for c in country_code.split(",") if c.strip()]

    if query_groups_from_sampling:
        # Path A
        search_res = await search(
            query_groups=query_groups_from_sampling,
            result_layout="by_query",
            dedupe=True,
        )
    elif multi_country_codes:
        # Path B: build cross-product — each sub-query × each country
        groups = [
            QueryGroup(queries=sub_queries, country=code)
            for code in multi_country_codes
        ]
        search_res = await search(
            query_groups=groups,
            result_layout="by_query",
            dedupe=True,
        )
    else:
        # Path C
        search_res = await search(
            queries=sub_queries,
            required_country=country_code,
            result_layout="by_query",
            dedupe=True,
        )

    if isinstance(search_res, MultiQuerySearchResponse) and search_res.results:
        for group in search_res.results:
            for ind in group.indicators:
                all_indicators.append((ind, group.query))
            total_candidates += group.count
    elif hasattr(search_res, "indicators") and search_res.indicators:
        for ind in search_res.indicators:
            all_indicators.append((ind, query))
        total_candidates = len(search_res.indicators)

    if not all_indicators:
        return {
            "query": query,
            "country": country,
            "country_code": country_code,
            "sub_queries": sub_queries,
            "decomposition_method": decomposition_method,
            "selected_indicators": [],
            "coverage_note": f"No indicators found across {len(sub_queries)} sub-queries.",
            "error": "No matching indicators found for this topic.",
        }

    # --- Step 4: Score and rank ---
    query_tokens = {
        w.lower() for w in query.split()
        if w.lower() not in _STOPWORDS and len(w) > 1
    }

    scored: list[tuple[float, EnrichedIndicator, str]] = []
    for ind, source_sq in all_indicators:
        score = _score_indicator(ind, query_tokens)
        scored.append((score, ind, source_sq))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max_indicators]

    # --- Step 5: Prefetch data for top indicators ---
    async def _fetch_data_for_indicator(
        ind: EnrichedIndicator,
    ) -> dict[str, Any] | None:
        """Fetch a small data snapshot for one indicator."""
        try:
            filters: dict[str, str | None] = {}
            # Prefer the per-indicator resolved scope (from query_groups);
            # fall back to the top-level country_code only when absent.
            requested_country = getattr(ind, "requested_country", None) or country_code
            if requested_country:
                filters["REF_AREA"] = requested_country

            data_result = await get_data(
                database_id=ind.database_id,
                indicator_id=ind.idno,
                disaggregation_filters=filters if filters else None,
                start_year=start_year,
                end_year=end_year,
                limit=20,
            )
            if data_result.error:
                return {"error": data_result.error}
            return {
                "data": data_result.data,
                "metadata": data_result.metadata,
                "count": data_result.count,
            }
        except Exception as e:
            return {"error": str(e)}

    data_tasks = [_fetch_data_for_indicator(ind) for _, ind, _ in top]
    data_results = await asyncio.gather(*data_tasks, return_exceptions=True)

    # --- Step 6: Build response ---
    selected_indicators = []
    for rank, ((score, ind, source_sq), data_res) in enumerate(
        zip(top, data_results), start=1
    ):
        data_snapshot = None
        data_error = None

        if isinstance(data_res, Exception):
            data_error = str(data_res)
        elif data_res is not None and "error" in data_res:
            data_error = data_res["error"]
        elif data_res is not None:
            data_snapshot = data_res

        selected_indicators.append({
            "rank": rank,
            "indicator_id": ind.idno,
            "database_id": ind.database_id,
            "database_name": ind.database_name,
            "name": ind.name,
            "definition": ind.truncated_definition,
            "matched_sub_queries": {
                "original_query": query,
                "decomposed_sub_query": source_sq,
            },
            "score": round(score, 2),
            "data_snapshot": data_snapshot,
            "data_error": data_error,
        })

    return {
        "query": query,
        "country": country,
        "country_code": country_code,
        "sub_queries": sub_queries,
        "decomposition_method": decomposition_method,
        "selected_indicators": selected_indicators,
        "coverage_note": (
            f"{len(selected_indicators)} indicators selected from "
            f"{len(sub_queries)} sub-queries ({total_candidates} candidates)"
        ),
    }


# --- Visualization Workflow Tools ---


async def get_data_api_url(
    database_id: str,
    indicator_id: str,
    country_code: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
) -> str:
    """Generate a Data360 API URL for a dataset without fetching data.

    Low-level tool: use only when you need the raw data API URL (e.g. custom clients or debugging).
    For charts, use data360_get_viz_spec instead; it builds the URL, fetches data, and generates the spec.
    Use data360_get_disaggregation to obtain valid filter values.

    Args:
        database_id: Database identifier (e.g., WB_HNP, WB_WDI).
        indicator_id: Indicator ID (e.g., WB_HNP_SP_POP_TOTL).
        country_code: Optional 3-letter code or semicolon-separated list (e.g. "KEN" or "CHN;USA").
        start_year: Optional start year (inclusive).
        end_year: Optional end year (inclusive).
        disaggregation_filters: Optional dict of dimension filters (e.g. {"SEX": "F"}).
            If omitted, defaults to totals (_T) for SEX, AGE, URBANISATION where applicable.

    Returns:
        Full Data360 data API URL string (query parameters included).
        Raises ValueError if the indicator is not found in the specified database.
            If this happens, the indicator_id is invalid or stale. Do NOT retry with the same ID.
            Look back at the other indicators already returned by the previous
            data360_search_indicators call in this conversation and try the next best match.
            Only call data360_search_indicators again if no prior search results exist in context.
    """
    settings = get_data360_settings()

    # Fix double-slash: ensure base URL doesn't end with slash before appending /data
    base_url = settings.api_url.rstrip("/")
    base = f"{base_url}/data"

    # Construct query params
    params = {"DATABASE_ID": database_id, "INDICATOR": indicator_id}

    if country_code:
        params["REF_AREA"] = country_code

    if start_year:
        params["timePeriodFrom"] = start_year

    if end_year:
        params["timePeriodTo"] = end_year
    # Fetch metadata and disaggregations FIRST to inform parameter building
    # This ensures we don't apply invalid defaults (like AGE=_T) which cause empty results
    metadata_res = await get_metadata(
        database_id,
        indicator_id,
        select_fields=[],  # We only need disaggregation options, metadata fields not needed
        fetch_disaggregation=True,
    )

    if metadata_res.error:
        if metadata_res.indicator_metadata is None:
            raise ValueError(
                f"Indicator '{indicator_id}' not found: {metadata_res.error}"
            )
        _logger.warning(
            "Non-fatal metadata error for %s in get_data_api_url (proceeding): %s",
            indicator_id,
            metadata_res.error,
        )

    # Process valid disaggregations into {dim: [values]} format
    available_disaggregations = {}
    for d in metadata_res.disaggregation_options or []:
        if d.get("field_name") and d.get("field_value"):
            available_disaggregations[d["field_name"]] = d["field_value"]

    # Validate user filters
    valid_filters, validation_errors = _validate_user_filters(
        disaggregation_filters, available_disaggregations
    )
    if validation_errors:
        # For URL generation, we might still want to raise if anything is invalid
        # or we could just skip invalid ones. Raising is safer for URL consistency.
        raise ValueError("\n\n".join(validation_errors))

    # See _build_disaggregation_params() docstring for behavior
    effective_filters = _build_disaggregation_params(
        valid_filters, available_disaggregations=available_disaggregations
    )

    # Add dimension filters to params
    params.update(effective_filters)

    # Default limit for viz
    limit = 1000
    if country_code:
        # Increase limit based on number of countries requested (max ~60 years per country)
        # Using 1000 as a safe multiplier to cover most time series data including higher frequency
        n_countries = len(country_code.split(","))
        limit = max(1000, n_countries * 1000)

    params["top"] = limit

    query_string = urlencode(params, safe=",")
    return f"{base}?{query_string}"
