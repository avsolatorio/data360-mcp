import logging
from typing import Any

import dotenv
import httpx

from .config import get_data360_settings
from .models import (
    IndicatorDataResponse,
    MetadataResponse,
    SearchRequest,
    SearchResponse,
    SeriesDescription,
)

dotenv.load_dotenv()
_logger = logging.getLogger(__name__)

data360_config = get_data360_settings()


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


async def search(
    query: str,
    limit: int = 10,
    offset: int = 0,
    count: bool = True,
    odata_options: dict[str, str] | None = None,
) -> SearchResponse:
    """Search for data360 indicators using the World Bank Data360 API.

    Args:
         query: Search query string to find relevant data series
         limit: Number of results to return (default is 10)
         offset: Offset of the current page
         count: Whether to include total count in response
         odata_options: Optional dict with OData parameters:
             - filter: OData filter expression (e.g., "type eq 'indicator'")
             - orderby: OData orderby expression (e.g., "series_description/name")
             - select: OData select expression (e.g., "series_description/idno, series_description/name")

    Returns:
        SearchResponse with search results

    Example API Request Payload:
        {
            "count": false,
            "filter": "series_description/topics/any(t: t/name eq 'Health' or t/name eq 'Jobs') and type eq 'indicator'",
            "orderby": "series_description/name",
            "select": "series_description/idno, series_description/name, series_description/database_id",
            "search": "nutrition",
            "top": 20,
            "skip": 0
        }
    """

    # Extract OData options from dict if provided
    filter_val = odata_options.get("filter") if odata_options else None
    orderby_val = odata_options.get("orderby") if odata_options else None
    select_val = odata_options.get("select") if odata_options else None

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
                    print(response_data)
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


# ruff: noqa: PLR0913, PLR0912, PLR0915
async def get_metadata(
    database_id: str,
    indicator_id: str,
    get_valid_disaggregations_func: Any | None = None,
) -> MetadataResponse:
    """Get metadata and disaggregation options for a Data360 indicator.

    Args:
        database_id: Database identifier (e.g., IPC_IPC, WB_WDI)
        indicator_id: Indicator ID (e.g., IPC_IPC_PHASE, WB_WDI_SP_POP_TOTL)
        get_valid_disaggregations_func: Function to get valid disaggregations (default is _get_valid_disaggregations)

    Returns:
        MetadataResponse with metadata and disaggregation options

    Example API Request Payload:
        {
            "query": "&$filter=series_description/idno eq 'WB_WDI_SP_POP_TOTL' and series_description/ref_country/any(t: t/code eq 'PHL')&$select=series_description/database_id,series_description/idno"
        }

        {
            "query": "&$filter=type eq 'indicator' and series_description/ref_country/all(t: t/code eq 'BRN' or t/code eq 'PHL') and series_description/ref_country/any()&$select=series_description/database_id,series_description/idno"
        }

    """
    # Use provided function or default
    if get_valid_disaggregations_func is None:
        get_valid_disaggregations_func = _get_valid_disaggregations

    # Determine URLs
    metadata_url = data360_config.metadata_url or f"{data360_config.api_url}/metadata"
    disaggregation_url = (
        data360_config.disaggregation_url or f"{data360_config.api_url}/disaggregation"
    )

    indicator_metadata: dict[str, Any] | None = None
    disaggregations: list[dict[str, Any]] = []
    errors: list[str] = []
    headers = {"accept": "*/*", "Content-Type": "application/json"}
    # 1. Fetch Metadata
    try:
        metadata_payload = {"query": f"series_description/idno eq '{indicator_id}'"}

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


async def get_data(
    database_id: str,
    indicator_id: str,
    disaggregation_filters: dict[str, str] | None = None,
) -> IndicatorDataResponse:
    """
    Fetch indicator data from Data360 API with pagination support.

    Args:
        database_id: Database identifier (e.g., "IPC_IPC", "WB_WDI")
        indicator_id: Indicator ID (e.g., "IPC_IPC_PHASE", "WB_WDI_SP_POP_TOTL")
        disaggregation_filters: Optional dictionary of disaggregation filters
            (e.g., {"REF_AREA": "UGA", "UNIT_MEASURE": "PT"})

    Returns:
        IndicatorDataResponse with data and count
    """
    data_url = data360_config.data_url or f"{data360_config.api_url}/data"
    all_data: list[dict[str, Any]] = []
    skip = 0

    # Prepare base parameters for the API call
    params: dict[str, Any] = {
        "DATABASE_ID": database_id,
        "INDICATOR": indicator_id,
    }

    # Add disaggregation filters to parameters if provided
    if disaggregation_filters:
        params.update(disaggregation_filters)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                current_params = params.copy()
                current_params["skip"] = skip

                try:
                    data_res = await client.get(data_url, params=current_params)
                    data_res.raise_for_status()

                    try:
                        data_json = data_res.json()
                    except ValueError as e:
                        error_msg = f"Failed to parse data JSON response: {str(e)}"
                        _logger.error(error_msg)
                        return IndicatorDataResponse(data=None, error=error_msg)

                    if not data_json.get("value"):
                        break  # No more data

                    all_data.extend(data_json["value"])

                    # Continue fetching if there's more data than currently retrieved
                    if data_json.get("count", 0) <= len(all_data):
                        break
                    skip = len(all_data)

                except Exception as e:
                    if isinstance(e, httpx.HTTPStatusError):
                        error_msg = f"HTTP error fetching data: {e.response.status_code} - {e.response.text}"
                    elif isinstance(e, httpx.TimeoutException):
                        error_msg = f"Timeout fetching data: {str(e)}"
                    elif isinstance(e, httpx.RequestError):
                        error_msg = f"Request error fetching data for {indicator_id!r}: {str(e)}"
                    else:
                        error_msg = f"Unexpected error fetching data: {str(e)}"
                    _logger.error(error_msg)
                    return IndicatorDataResponse(data=None, error=error_msg)

        return IndicatorDataResponse(data=all_data, count=len(all_data), error=None)

    except Exception as e:
        error_msg = f"Unexpected error fetching data: {str(e)}"
        _logger.exception("Unexpected error in data fetch")
        return IndicatorDataResponse(data=None, error=error_msg)
