import json
import logging
import zlib
from typing import Any
from urllib.parse import urlencode

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
    SearchRequest,
    SearchResponse,
    SeriesDescription,
)

dotenv.load_dotenv()
_logger = logging.getLogger(__name__)

data360_config = get_data360_settings()

# Constants for API logic
COUNTRY_CODE_LENGTH = 3
SCORE_THRESHOLD = 70
MAX_RETURN_STATEMENTS = 6
DEFAULT_SEARCH_LIMIT = 5

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

    Based on a 16-database survey documented in payload_analysis.md.
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
    from . import providers as data360_providers

    if not country_query:
        return None

    # Handle multi-country
    if "," in country_query:
        parts = [p.strip() for p in country_query.split(",") if p.strip()]
        resolved_codes = []
        for part in parts:
            code = await _resolve_country_code(part)
            if code:
                resolved_codes.append(code)

        return ",".join(resolved_codes) if resolved_codes else None

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


async def search(
    query: str,
    required_country: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
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
) -> "EnrichedSearchResponse":
    """Search for Data360 indicators with enriched metadata for selection.

    Use this first when the user asks for data on a topic (e.g. unemployment, poverty, GDP).
    No other tools are required before this one. After picking an indicator, call
    data360_get_metadata and/or data360_get_disaggregation before fetching data or generating a chart.

    Args:
        query: Search query (e.g., "unemployment rate", "poverty", "GDP per capita").
        required_country: Optional country name or 3-letter code (e.g. "Kenya", "KEN").
            Use comma-separated names or codes to check multiple countries in one call (e.g. "China, USA").
        limit: Maximum number of indicators to return (default 5).
        offset: Number of results to skip for pagination (default 0).

    Returns:
        EnrichedSearchResponse:
            indicators: List of EnrichedIndicator, each with idno, database_id, name,
                truncated_definition, unit, periodicity, latest_data, time_period_range,
                covers_country (True/False if required_country was given), and dimensions (e.g. SEX, AGE).
            required_country: Resolved country code(s) if required_country was provided.
            count, total_count, offset, has_more, next_offset: Pagination fields.
            error: Error message string if the request failed; otherwise None.
    """
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
        query=query,
        limit=limit,
        offset=offset,
        select_fields=[
            "idno",
            "name",
            "database_id",
            "definition_long",
            "periodicity",
            "time_periods",
            "ref_country",
            "dimensions",
            "measurement_unit",
        ],
    )

    if search_result.error:
        return EnrichedSearchResponse(error=search_result.error)

    if not search_result.items:
        return EnrichedSearchResponse(error=f"No indicators found for: '{query}'")

    # Process each indicator
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

        # Check covers_country from ref_country
        covers_country = None
        ref_country = raw.get("ref_country", [])
        if country_code and ref_country and isinstance(ref_country, list):
            country_codes = {
                c.get("code") if isinstance(c, dict) else c for c in ref_country
            }
            # Check overlap if multiple countries requested
            requested_codes = set([c.strip() for c in country_code.split(",")])
            covers_country = bool(country_codes & requested_codes)
        elif country_code:
            covers_country = False

        # Extract dimension names from series_description/dimensions
        dimensions = raw.get("dimensions", [])
        label_to_code = {
            "sex": "SEX",
            "age": "AGE",
            "residential area": "URBANISATION",
            "urbanisation": "URBANISATION",
            "education": "EDUCATION",
        }

        useful_dims: list[str] = []
        if dimensions and isinstance(dimensions, list):
            for dim in dimensions:
                if isinstance(dim, dict):
                    label = (dim.get("label") or "").lower()
                    if label in label_to_code:
                        useful_dims.append(label_to_code[label])

        # Build EnrichedIndicator
        indicators.append(
            EnrichedIndicator(
                idno=raw.get("idno", ""),
                database_id=raw.get("database_id", ""),
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

    # Sort: covers_country=True first, then by latest_data descending
    if country_code:
        indicators.sort(
            key=lambda x: (
                not (x.covers_country or False),
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

    Call after data360_search_indicators when you have chosen an indicator (you need its
    database_id and indicator_id). For valid filter values (years, country codes, SEX/AGE/URBANISATION),
    prefer data360_get_disaggregation. data360_get_data and data360_get_viz_spec call get_metadata internally.

    Args:
        database_id: Database identifier (e.g., IPC_IPC, WB_GS).
        indicator_id: Indicator ID (e.g., IPC_IPC_PHASE, WB_GS_NY_GDP_PCAP_KD).
        select_fields: Optional list of metadata fields to return. If None, returns all fields.
            Available fields: methodology, statistical_concept, definition_long, limitation,
            relevance, aggregation_method, periodicity, time_periods, ref_country, sources_note.
        get_valid_disaggregations_func: Internal use; function to filter raw disaggregation response.
        fetch_disaggregation: If True (default), also fetch disaggregation dimensions (field_name, field_value).
        required_country: Optional country name or 3-letter code (e.g. "Kenya", "KEN").
            Use comma-separated for multiple (e.g. "China, USA"). When provided,
            REF_AREA in disaggregation shows which queried countries have data.

    Returns:
        MetadataResponse:
            indicator_metadata: Dict of requested metadata fields for the indicator, or None if not found.
            disaggregation_options: List of dicts with field_name and field_value (list of valid codes).
            error: Error message string if any request failed; otherwise None.
    """
    # Use provided function or default
    if get_valid_disaggregations_func is None:
        get_valid_disaggregations_func = _get_valid_disaggregations

    # Resolve country codes if provided
    queried_countries: list[str] | None = None
    if required_country:
        resolved = await _resolve_country_code(required_country)
        if resolved:
            queried_countries = [c.strip() for c in resolved.split(",")]

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
                    # Force filtering if select_fields provided (API might return more)
                    if select_fields and indicator_metadata:
                        indicator_metadata = {
                            k: v
                            for k, v in indicator_metadata.items()
                            if k in select_fields
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

    Args:
        database_id: Database identifier (e.g., WB_GS, WB_SSGD).
        indicator_id: Indicator ID (e.g., WB_GS_NY_GDP_PCAP_KD).
        required_country: Optional country name or 3-letter code (e.g. "Kenya", "KEN").
            Use comma-separated names or codes to check multiple countries in one call (e.g. "China, USA").
            When provided, REF_AREA shows which queried countries have data for this indicator.

    Returns:
        On success: dict with key "dimensions", a list of dicts each with:
            field_name: Dimension name (e.g. TIME_PERIOD, REF_AREA, SEX, AGE, URBANISATION).
            field_value: List of valid codes (e.g. years, country codes, F/M/_T).
        On failure: dict with key "error" and an error message string.
        TIME_PERIOD gives actual available years (may have gaps). REF_AREA lists countries with data.
    """
    # Resolve country codes if provided
    queried_countries: list[str] | None = None
    if required_country:
        resolved = await _resolve_country_code(required_country)
        if resolved:
            queried_countries = [c.strip() for c in resolved.split(",")]

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
        disaggregation_filters: Optional dict of dimension filters. Keys: REF_AREA, SEX, AGE,
            URBANISATION, UNIT_MEASURE, etc. REF_AREA supports comma-separated codes (e.g. "KEN,TZA").
            Use value None to request all values for a dimension (e.g. {"SEX": None}).
        start_year: Optional start year (inclusive). Defaults to last 20 years if both start/end omitted.
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
            failed_validation: Optional list of filter validation messages.
    """
    data_url = data360_config.data_url or f"{data360_config.api_url}/data"

    # Cap limit to prevent token overflow
    limit = min(limit, 100)

    # Smart time defaults: if no time range specified, default to last 5 years
    if start_year is None and end_year is None:
        from datetime import datetime

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
    )

    if metadata_res.error:
        _logger.warning(
            f"Metadata fetch error for {indicator_id}: {metadata_res.error}"
        )
        return IndicatorDataResponse(error=metadata_res.error)

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
            print(f"Fetching data from {data_url} with params: {params}")
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
    import warnings

    warnings.warn(
        "discover_indicators is deprecated. Use search() + get_disaggregation() + get_metadata() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # ... existing implementation ...


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
        country_code: Optional 3-letter code or comma-separated list (e.g. "KEN" or "CHN,USA").
        start_year: Optional start year (inclusive).
        end_year: Optional end year (inclusive).
        disaggregation_filters: Optional dict of dimension filters (e.g. {"SEX": "F"}).
            If omitted, defaults to totals (_T) for SEX, AGE, URBANISATION where applicable.

    Returns:
        Full Data360 data API URL string (query parameters included).
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
        raise ValueError(
            f"Indicator '{indicator_id}' not found or error fetching metadata: {metadata_res.error}"
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
