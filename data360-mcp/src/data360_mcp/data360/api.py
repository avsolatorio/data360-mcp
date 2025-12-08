import logging
from typing import Any

import httpx

from .config import get_data360_settings
from .models import MetadataResponse, SearchResponse

_logger = logging.getLogger(__name__)

data360_config = get_data360_settings()


BASE_URL = data360_config.api_base_url
BASE_URL = f"{BASE_URL}/data360"


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


async def search(
    query: str,
    n_results: int = 10,
    filter: str | None = None,
    orderby: str | None = None,
    select: str | None = None,
    skip: int = 0,
    count: bool = False,
) -> SearchResponse:
    """Search for indicators in Data360."""
    url = data360_config.search_url or f"{BASE_URL}/searchv2"

    # Build the payload according to the API specification
    payload = {
        "search": query,
        "top": n_results,
        "skip": skip,
        "count": count,
    }

    # Add optional parameters if provided
    if filter is not None:
        payload["filter"] = filter
    if orderby is not None:
        payload["orderby"] = orderby
    if select is not None:
        payload["select"] = select

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

            try:
                response_data = response.json()
            except ValueError as e:
                _logger.error(f"Failed to parse JSON response: {e}")
                return SearchResponse(
                    items=None, error=f"Failed to parse API response: {str(e)}"
                )

            # Map the API response structure to SearchResponse
            # API returns {"@odata.context": "...", "value": [...]}
            # We map "value" to "items"
            try:
                search_response_data = {
                    "items": response_data.get("value", []),
                    "count": len(response_data.get("value", [])),
                }
                return SearchResponse.model_validate(search_response_data)
            except Exception as e:
                _logger.error(f"Failed to validate response data: {e}")
                return SearchResponse(
                    items=None, error=f"Failed to validate API response: {str(e)}"
                )

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error {e.response.status_code}: {e.response.text}"
        _logger.error(error_msg)
        return SearchResponse(items=None, error=error_msg)
    except httpx.TimeoutException as e:
        error_msg = f"Request timeout: {str(e)}"
        _logger.error(error_msg)
        return SearchResponse(items=None, error=error_msg)
    except httpx.RequestError as e:
        error_msg = f"Request error: {str(e)}"
        _logger.error(error_msg)
        return SearchResponse(items=None, error=error_msg)
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        _logger.exception("Unexpected error in search function")
        return SearchResponse(items=None, error=error_msg)


async def get_metadata(
    indicator_id: str,
    database_id: str,
    get_valid_disaggregations_func: Any | None = None,
) -> MetadataResponse:
    """Get metadata and disaggregation options for a Data360 indicator."""
    # Use provided function or default
    if get_valid_disaggregations_func is None:
        get_valid_disaggregations_func = _get_valid_disaggregations

    # Determine URLs
    metadata_url = data360_config.metadata_url or f"{BASE_URL}/metadata"
    disaggregation_url = (
        data360_config.disaggregation_url or f"{BASE_URL}/disaggregation"
    )

    indicator_metadata: dict[str, Any] | None = None
    disaggregations: list[dict[str, Any]] = []
    errors: list[str] = []

    # 1. Fetch Metadata
    try:
        metadata_payload = {"query": f"series_description/idno eq '{indicator_id}'"}
        headers = {"accept": "*/*", "Content-Type": "application/json"}

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

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error fetching metadata: {e.response.status_code} - {e.response.text}"
        _logger.error(error_msg)
        errors.append(error_msg)
    except httpx.TimeoutException as e:
        error_msg = f"Timeout fetching metadata: {str(e)}"
        _logger.error(error_msg)
        errors.append(error_msg)
    except httpx.RequestError as e:
        error_msg = f"Request error fetching metadata for {indicator_id!r}: {str(e)}"
        _logger.error(error_msg)
        errors.append(error_msg)
    except Exception as e:
        error_msg = f"Unexpected error fetching metadata: {str(e)}"
        _logger.exception("Unexpected error in metadata fetch")
        errors.append(error_msg)

    # 2. Fetch Disaggregation
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            disagg_res = await client.get(
                disaggregation_url,
                params={"datasetId": database_id, "indicatorId": indicator_id},
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
