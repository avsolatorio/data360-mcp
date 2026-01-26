import json
import logging
import zlib
import asyncio
from typing import Any

import dotenv
import httpx
from pydantic import ValidationError

from .config import get_data360_settings
from .models import (
    DiscoveryResult,
    DiscoveredIndicator,
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


def _build_disaggregation_params(
    disaggregation_filters: dict[str, str | None] | None
) -> dict[str, str]:
    """Build effective disaggregation params with smart defaults.
    
    This is the single source of truth for disaggregation filtering logic.
    Used by both get_data() and get_data_api_url().
    
    Args:
        disaggregation_filters: User-provided filters. 
            - None or {}: Use defaults (SEX=_T, AGE=_T, URBANISATION=_T)
            - {"SEX": "F"}: Use F for SEX, defaults for others
            - {"SEX": None}: Omit SEX filter (get all values), defaults for others
        
    Returns:
        Dict of dimension -> value to add to API params.
        Dimensions with None values are omitted (API returns all).
    """
    default_filters = {"SEX": "_T", "AGE": "_T", "URBANISATION": "_T"}
    
    if not disaggregation_filters:
        return default_filters
    
    effective = {}
    for dim, default_val in default_filters.items():
        if dim in disaggregation_filters:
            user_val = disaggregation_filters[dim]
            if user_val is not None:
                # User specified a value → use it
                effective[dim] = user_val
            # else: user passed None → omit dimension (get all values)
        else:
            # User didn't specify → use default
            effective[dim] = default_val
    
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

    error_msg: str | None = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

            try:
                response_data = response.json()
            except ValueError as e:
                _logger.error(f"Failed to parse JSON response: {e}")
                error_msg = f"Failed to parse API response: {str(e)}"
            else:
                try:
                    return _process_search_response(response_data, request)
                except Exception as e:
                    _logger.error(f"Failed to validate response data: {e}")
                    error_msg = f"Failed to validate API response: {str(e)}"

    except Exception as e:
        if isinstance(e, httpx.HTTPStatusError):
            error_msg = f"HTTP error {e.response.status_code}: {e.response.text}"
        elif isinstance(e, httpx.TimeoutException):
            error_msg = f"Request timeout: {str(e)}"
        elif isinstance(e, httpx.RequestError):
            error_msg = f"Request error: {str(e)}"
        else:
            error_msg = f"Unexpected error: {str(e)}"
        _logger.error(error_msg)

    if error_msg:
        return SearchResponse(items=None, error=error_msg)
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
    if len(country_query) == 3 and country_query.isupper():
        return country_query
    # Look up in codelist
    matches = await data360_providers.find_codelist_value("REF_AREA", country_query, limit=1)
    if matches and matches[0].get("score", 0) >= 70:
        return matches[0].get("id")
    return None


async def search(
    query: str,
    required_country: str | None = None,
    limit: int = 5,
    offset: int = 0,
) -> "EnrichedSearchResponse":
    """Search for Data360 indicators with enriched metadata for selection.
    
    Args:
        query: Search query (e.g., "unemployment rate", "poverty")
        required_country: Country name or code (e.g., "Kenya" or "KEN")
        limit: Max results (default 5)
        offset: Offset for pagination (default 0)
    
    Returns:
        EnrichedSearchResponse with:
            - indicators: List of EnrichedIndicator (idno, database_id, name, 
              truncated_definition, periodicity, latest_data, covers_country, dimensions)
            - count, total_count, offset, has_more, next_offset: Pagination fields
            - required_country: Resolved country code
            - error: Error message if failed
    """
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
            "idno", "name", "database_id", "definition_long",
            "periodicity", "time_periods", "ref_country", "dimensions"
        ]
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
            country_codes = [
                c.get("code") if isinstance(c, dict) else c 
                for c in ref_country
            ]
            covers_country = country_code in country_codes
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
        indicators.append(EnrichedIndicator(
            idno=raw.get("idno", ""),
            database_id=raw.get("database_id", ""),
            name=raw.get("name", ""),
            truncated_definition=(raw.get("definition_long") or "")[:100],
            periodicity=raw.get("periodicity"),
            latest_data=latest_data,
            time_period_range=time_period_range,
            covers_country=covers_country,
            dimensions=useful_dims if useful_dims else None,
        ))
    
    # Sort: covers_country=True first, then by latest_data descending
    if country_code:
        indicators.sort(key=lambda x: (
            not (x.covers_country or False),
            -(int(x.latest_data or 0) if str(x.latest_data or "").isdigit() else 0)
        ))
    
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
) -> MetadataResponse:
    """Get metadata and disaggregation options for a Data360 indicator.

    Args:
        database_id: Database identifier (e.g., IPC_IPC, WB_GS)
        indicator_id: Indicator ID (e.g., IPC_IPC_PHASE, WB_GS_NY_GDP_PCAP_KD)
        select_fields: Optional list of metadata fields to return (e.g., ["methodology", "statistical_concept"]).
            If None, returns all fields. Available fields include:
            methodology, statistical_concept, definition_long, limitation, relevance,
            aggregation_method, periodicity, time_periods, ref_country, sources_note
        get_valid_disaggregations_func: Function to get valid disaggregations (default is _get_valid_disaggregations)

    Returns:
        MetadataResponse with metadata and disaggregation options

    Example:
        # Get only methodology
        await get_metadata("WB_GS", "WB_GS_NY_GDP_PCAP_KD", select_fields=["methodology"])
        
        # Get full metadata
        await get_metadata("WB_GS", "WB_GS_NY_GDP_PCAP_KD")
    """
    # Use provided function or default
    if get_valid_disaggregations_func is None:
        get_valid_disaggregations_func = _get_valid_disaggregations

    # Validate inputs
    try:
        MetadataRequest(database_id=database_id, indicator_id=indicator_id)
    except ValidationError as e:
        return MetadataResponse(error=f"Invalid arguments: {e}")

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
                            k: v for k, v in indicator_metadata.items()
                            if k in select_fields
                        }
                else:
                    error_msg = f"No metadata found for indicator ID '{indicator_id}'"
                    _logger.warning(error_msg)
                    errors.append(error_msg)
            except ValueError as e:
                error_msg = f"Failed to parse metadata JSON response: {str(e)}"
                _logger.error(error_msg)
                errors.append(error_msg)

    except Exception as e:
        error_msg: str
        if isinstance(e, httpx.HTTPStatusError):
            error_msg = f"HTTP error fetching metadata: {e.response.status_code} - {e.response.text}"
        elif isinstance(e, httpx.TimeoutException):
            error_msg = f"Timeout fetching metadata: {str(e)}"
        elif isinstance(e, httpx.RequestError):
            error_msg = (
                f"Request error fetching metadata for {indicator_id!r}: {str(e)}"
            )
        else:
            error_msg = f"Unexpected error fetching metadata: {str(e)}"
        _logger.exception(error_msg)
        errors.append(error_msg)

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
                    disaggregations = get_valid_disaggregations_func(raw_disaggregations)
                except ValueError as e:
                    error_msg = f"Failed to parse disaggregation JSON response: {str(e)}"
                    _logger.error(error_msg)
                    errors.append(error_msg)

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error fetching disaggregations: {e.response.status_code} - {e.response.text}"
            _logger.error(error_msg)
            errors.append(error_msg)
        except httpx.TimeoutException as e:
            error_msg = f"Timeout fetching disaggregations: {str(e)}"
            _logger.error(error_msg)
            errors.append(error_msg)
        except httpx.RequestError as e:
            error_msg = (
                f"Request error fetching disaggregations for {indicator_id!r}: {str(e)}"
            )
            _logger.error(error_msg)
            errors.append(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error fetching disaggregations: {str(e)}"
            _logger.exception("Unexpected error in disaggregation fetch")
            errors.append(error_msg)

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
) -> dict[str, Any]:
    """Get disaggregation options for a Data360 indicator.
    
    This is the primary tool for checking what filter values are available
    for an indicator, including actual years (TIME_PERIOD), countries (REF_AREA),
    and dimensions (SEX, AGE, URBANISATION).

    Args:
        database_id: Database identifier (e.g., WB_GS, WB_SSGD)
        indicator_id: Indicator ID (e.g., WB_GS_NY_GDP_PCAP_KD)

    Returns:
        Dict with dimensions, each containing field_name, label_name, and field_value list.
        Returns {"error": "..."} on failure.

    Example:
        result = await get_disaggregation("WB_SSGD", "WB_SSGD_LF_PARTICIPATION_RATE")
        # Returns:
        # {
        #     "dimensions": [
        #         {"field_name": "TIME_PERIOD", "field_value": ["2015", "2018", "2020", "2022"]},
        #         {"field_name": "REF_AREA", "field_value": ["KEN", "UGA", "TZA", ...]},
        #         {"field_name": "SEX", "field_value": ["F", "M", "_T"]},
        #     ]
        # }
    
    Note:
        - TIME_PERIOD shows actual available years (may have gaps)
        - REF_AREA shows countries with data for this indicator
        - DO NOT use FREQ for filtering - it breaks queries
    """
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
            return {"dimensions": valid_dimensions}

    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP error: {e.response.status_code} - {e.response.text}"}
    except httpx.TimeoutException as e:
        return {"error": f"Timeout: {str(e)}"}
    except httpx.RequestError as e:
        return {"error": f"Request error: {str(e)}"}
    except Exception as e:
        _logger.exception("Unexpected error in get_disaggregation")
        return {"error": f"Unexpected error: {str(e)}"}


async def get_data(
    database_id: str,
    indicator_id: str,
    disaggregation_filters: dict[str, str | None] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> IndicatorDataResponse:
    """
    Fetch indicator data from Data360 API with LLM-friendly pagination.

    Args:
        database_id: Database identifier (e.g., "IPC_IPC", "WB_GS")
        indicator_id: Indicator ID (e.g., "IPC_IPC_PHASE", "WB_GS_NY_GDP_PCAP_KD")
        disaggregation_filters: Optional dictionary of disaggregation filters
            (e.g., {"REF_AREA": "UGA" or "KEN,TZA", "UNIT_MEASURE": "PT"})
        start_year: Optional start year to filter data (inclusive). Defaults to last 5 years.
        end_year: Optional end year to filter data (inclusive). Defaults to current year.
        limit: Maximum number of records to return (default 50, max 100)
        offset: Number of records to skip for pagination (default 0)

    Returns:
        IndicatorDataResponse with:
            - data: List of data points for this page
            - count: Number of records in this response
            - total_count: Total records available (if known)
            - has_more: True if more data is available
            - next_offset: Offset to use for next page (if has_more)
    
    Example:
        # First page
        result = get_data("WB_GS", "WB_GS_NY_GDP_PCAP_KD", 
                          disaggregation_filters={"REF_AREA": "KEN"})
        
        # If has_more=True, get next page:
        result2 = get_data("WB_GS", "WB_GS_NY_GDP_PCAP_KD",
                           disaggregation_filters={"REF_AREA": "KEN"}, 
                           offset=result.next_offset)
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
    except ValidationError as e:
        error_msg = f"Invalid arguments: {e}"
        _logger.error(error_msg)
        return IndicatorDataResponse(error=error_msg)

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

    # Apply smart disaggregation defaults using helper (single source of truth)
    # This adds filters to the URL, not post-fetch filtering
    effective_disagg = _build_disaggregation_params(disaggregation_filters)
    params.update(effective_disagg)
    
    # Also include any non-standard filters passed by user (e.g., REF_AREA)
    if disaggregation_filters:
        for k, v in disaggregation_filters.items():
            if k not in ["SEX", "AGE", "URBANISATION", "FREQ"] and v is not None:
                params[k] = v

    # Fetch basic metadata in parallel
    metadata_task = asyncio.create_task(
        get_metadata(
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
            fetch_disaggregation=False,
        )
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                data_res = await client.get(data_url, params=params)
                data_res.raise_for_status()

                try:
                    data_json = data_res.json()
                except ValueError as e:
                    error_msg = f"Failed to parse data JSON response: {str(e)}"
                    _logger.error(error_msg)
                    return IndicatorDataResponse(data=None, error=error_msg)

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

                # Note: Post-fetch filtering removed - filters now applied at URL level
                # via _build_disaggregation_params() for consistency with get_data_api_url()
                
                # Final limit enforcement (safety check)
                if len(raw_data) > limit:
                    raw_data = raw_data[:limit]

                # Add claim_id for data verification just before returning
                # We hash the FULL row to avoid collisions on dimensions not in the specific set
                for row in raw_data:
                    row["claim_id"] = _short_hash(row)

                # Await metadata
                metadata_res = await metadata_task
                api_metadata = metadata_res.indicator_metadata or {}

                return IndicatorDataResponse(
                    data=raw_data,
                    metadata=api_metadata,
                    count=len(raw_data),
                    total_count=total_count,
                    offset=offset,
                    has_more=has_more,
                    next_offset=api_next_offset,
                    error=None,
                )

            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP error fetching data: {e.response.status_code} - {e.response.text}"
                _logger.error(error_msg)
                return IndicatorDataResponse(data=None, error=error_msg)
            except httpx.TimeoutException as e:
                error_msg = f"Timeout fetching data: {str(e)}"
                _logger.error(error_msg)
                return IndicatorDataResponse(data=None, error=error_msg)
            except httpx.RequestError as e:
                error_msg = f"Request error fetching data for {indicator_id!r}: {str(e)}"
                _logger.error(error_msg)
                return IndicatorDataResponse(data=None, error=error_msg)
            except Exception as e:
                error_msg = f"Unexpected error fetching data: {str(e)}"
                _logger.error(error_msg)
                return IndicatorDataResponse(data=None, error=error_msg)

    except Exception as e:
        error_msg = f"Unexpected error fetching data: {str(e)}"
        _logger.exception("Unexpected error in data fetch")
        return IndicatorDataResponse(data=None, error=error_msg)


async def get_indicators(database_id: str) -> list[str]:
    """Get all indicator IDs for a specific database.
    
    Args:
        database_id: The database ID to fetch indicators for (e.g., "WB_WDI")
        
    Returns:
        List of indicator IDs
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
    
    from data360.providers import find_reference_area
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
    """Generate a Data360 API URL for a dataset (without fetching).
    
    Use this to get the `data_url` for visualization generation.
    
    Args:
        database_id: Database identifier (e.g., WB_HNP, WB_WDI)
        indicator_id: Indicator ID (e.g., WB_HNP_SP_POP_TOTL)
        country_code: Optional country code (e.g., "KEN" or "CHN,USA")
            Can be a single 3-letter code or comma-separated list.
        start_year: Optional start year
        end_year: Optional end year
        disaggregation_filters: Optional dict of dimension filters (e.g., {"SEX": "F"})
            If not provided, defaults to totals (_T) for SEX, AGE, URBANISATION
    
    Returns:
        Constructed API URL string
    """
    settings = get_data360_settings()
    
    # Fix double-slash: ensure base URL doesn't end with slash before appending /data
    base_url = settings.api_url.rstrip('/')
    base = f"{base_url}/data"
    
    # Construct query params
    params = [
        f"DATABASE_ID={database_id}",
        f"INDICATOR={indicator_id}"
    ]
    
    if country_code:
        params.append(f"REF_AREA={country_code}")
    
    if start_year:
        params.append(f"timePeriodFrom={start_year}")
    
    if end_year:
        params.append(f"timePeriodTo={end_year}")
    
    # Use shared helper for disaggregation defaults (single source of truth)
    # See _build_disaggregation_params() docstring for behavior
    effective_filters = _build_disaggregation_params(disaggregation_filters)
    
    # Add dimension filters to params
    for dim, val in effective_filters.items():
        params.append(f"{dim}={val}")

    # Also include any non-standard filters passed by user (e.g., UNIT_MEASURE)
    if disaggregation_filters:
        for k, v in disaggregation_filters.items():
            if k not in effective_filters and k != "FREQ" and v is not None:
                params.append(f"{k}={v}")
        
    # Default limit for viz
    limit = 1000
    if country_code:
        # Increase limit based on number of countries requested (max ~60 years per country)
        # Using 1000 as a safe multiplier to cover most time series data including higher frequency
        n_countries = len(country_code.split(','))
        limit = max(1000, n_countries * 1000)
    
    params.append(f"top={limit}")
        
    return f"{base}?{'&'.join(params)}"


    # Step 1: Resolve country code if provided as name
    country_code: str | None = None
    if required_country:
        # Check if it's already a code (3 letters uppercase)
        if len(required_country) == 3 and required_country.isupper():
            country_code = required_country
        else:
            # Try to resolve the country name
            matches = await find_reference_area(required_country, limit=1)
            if matches and matches[0]["score"] >= 80:
                country_code = matches[0]["id"]
            else:
                return DiscoveryResult(error=f"Could not resolve country: '{required_country}'")

    # Step 2: Search for indicators
    try:
        search_result = await search(query=query, limit=limit)
        if search_result.error:
            return DiscoveryResult(error=search_result.error)
        if not search_result.items:
            return DiscoveryResult(error=f"No indicators found for query: '{query}'")
    except Exception as e:
        return DiscoveryResult(error=f"Search failed: {str(e)}")

    # Step 3: Fetch metadata for all indicators in parallel
    async def fetch_indicator_metadata(item: SeriesDescription) -> DiscoveredIndicator:
        """Fetch and process metadata for a single indicator."""
        base_info = {
            "indicator_id": item.idno,
            "database_id": item.database_id,
            "name": item.name,
            "truncated_definition": item.definition_long[:100] if item.definition_long else item.name,
            "has_country": False,
            "country_code": country_code,
            "available_dimensions": [],
            "available_frequencies": [],
            "periodicity": None,
            "has_required_dimensions": True,
            "time_range": None,
            "error": None,
        }

        try:
            metadata_result = await get_metadata(
                database_id=item.database_id, indicator_id=item.idno
            )

            if metadata_result.error:
                base_info["error"] = metadata_result.error
                return DiscoveredIndicator(**base_info)

            # Extract time range and periodicity from metadata
            if metadata_result.indicator_metadata:
                time_periods = metadata_result.indicator_metadata.get("time_periods", [])
                if time_periods:
                    base_info["time_range"] = {
                        "start": time_periods[0].get("start"),
                        "end": time_periods[0].get("end"),
                    }
                
                # Get periodicity (more human-readable than FREQ codes)
                base_info["periodicity"] = metadata_result.indicator_metadata.get("periodicity")

                # Check if required country is in ref_country
                if country_code:
                    ref_countries = metadata_result.indicator_metadata.get(
                        "ref_country", []
                    )
                    country_codes = [c.get("code") for c in ref_countries]
                    base_info["has_country"] = country_code in country_codes

            # Extract available dimensions and frequencies from disaggregation options
            available_dims: list[str] = []
            available_freqs: list[str] = []
            #forces the LLM to only see dimensions that offer actual choices (like "Male/Female" or "Urban/Rural")
            for dim in metadata_result.disaggregation_options:
                field_name = dim.get("field_name", "")
                field_values = dim.get("field_value", [])
                
                # Extract FREQ values
                if field_name == "FREQ" and field_values:
                    available_freqs = field_values

                # Only include if not just "_T" or "_Z" and not FREQ
                if field_name != "FREQ" and field_values and not (
                    len(field_values) == 1 and field_values[0] in ["_T", "_Z"]
                ):
                    available_dims.append(field_name)
            
            base_info["available_frequencies"] = available_freqs
            base_info["available_dimensions"] = available_dims

            # Check if required dimensions are available
            if required_dimensions:
                missing_dims = set(required_dimensions) - set(available_dims)
                base_info["has_required_dimensions"] = len(missing_dims) == 0

        except Exception as e:
            base_info["error"] = str(e)

        return DiscoveredIndicator(**base_info)

    # Fetch all metadata in parallel
    import asyncio

    tasks = [fetch_indicator_metadata(item) for item in search_result.items]
    indicators = await asyncio.gather(*tasks)

    # Step 4: Sort by relevance
    # Priority: has_country + has_required_dimensions > has_country > everything else
    def sort_key(ind: DiscoveredIndicator) -> tuple[int, int, int]:
        score = 0
        if ind.has_country:
            score += 100
        if ind.has_required_dimensions:
            score += 50
        if ind.error is None:
            score += 10
        return (-score, 0, 0)

    indicators_sorted = sorted(indicators, key=sort_key)
    
    return DiscoveryResult(indicators=indicators_sorted)

