import logging

import httpx

from .config import get_data360_settings
from .models import SearchResponse

_logger = logging.getLogger(__name__)

data360_config = get_data360_settings()


BASE_URL = data360_config.api_base_url
BASE_URL = f"{BASE_URL}/data360"


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
    url = f"{BASE_URL}/searchv2"

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
