import logging
from typing import Any

import dotenv
import httpx

from .config import get_data360_settings
from .models import IndicatorDataResponse, MetadataResponse, SearchResponse

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


async def search(
    query: str,
    n_results: int = 10,
    filter: str | None = None,
    orderby: str | None = None,
    select: str | None = None,
    skip: int = 0,
    count: bool = False,
) -> SearchResponse:
    """Search for data360 indicators using the World Bank Data360 API.

    Args:
         query: Search query string to find relevant data series
         n_results: Number of top results to return (default is 10)
         filter: OData filter expression (e.g., "type eq 'indicator'")
         orderby: OData orderby expression (e.g., "series_description/name")
         select: OData select expression (e.g., "series_description/idno, series_description/name")
         skip: Number of results to skip for pagination
         count: Whether to include total count in response
    """
    url = data360_config.search_url or f"{data360_config.api_url}/searchv2"

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
    metadata_url = data360_config.metadata_url or f"{data360_config.api_url}/metadata"
    disaggregation_url = (
        data360_config.disaggregation_url or f"{data360_config.api_url}/disaggregation"
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


class CodelistManager:
    """Manager for fetching and querying Data360 codelist data."""

    def __init__(self, codelist_url: str | None = None):
        """Initialize the CodelistManager."""
        self.codelist_url = (
            codelist_url
            or data360_config.codelist_api_base_url
            or f"{data360_config.api_url}/metadata/codelist"
        )
        self.codelist: dict[str, Any] | None = None

    async def set_codelist(self) -> None:
        """Fetch and cache the codelist from the API."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.codelist_url)
                response.raise_for_status()
                self.codelist = response.json()
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error fetching codelist: {e.response.status_code} - {e.response.text}"
            _logger.error(error_msg)
            raise
        except httpx.TimeoutException as e:
            error_msg = f"Timeout fetching codelist: {str(e)}"
            _logger.error(error_msg)
            raise
        except httpx.RequestError as e:
            error_msg = f"Request error fetching codelist: {str(e)}"
            _logger.error(error_msg)
            raise
        except Exception as e:
            error_msg = f"Unexpected error fetching codelist: {str(e)}"
            _logger.exception("Unexpected error in codelist fetch")
            raise

    async def get_name(self, field_name: str, field_value_id: str) -> str | None:
        """
        Get the name for a given field_name and field_value_id from the codelist.

        Args:
            field_name: The name of the field (e.g., "UNIT_MEASURE", "FREQ")
            field_value_id: The ID value to look up (e.g., "PS", "M")

        Returns:
            The name associated with the field_value_id, or None if not found
        """
        if self.codelist is None:
            await self.set_codelist()

        if field_name not in self.codelist:
            _logger.warning(f"field_name '{field_name}' not found in codelist.")
            return None

        # Filter for the code with the matching ID
        found_codes = list(
            filter(lambda x: x["id"] == field_value_id, self.codelist[field_name])
        )

        if not found_codes:
            _logger.warning(
                f"field_value_id '{field_value_id}' not found for field_name '{field_name}'."
            )
            return None

        # Assuming unique IDs within each field_name, return the name of the first match
        return found_codes[0]["name"]

    def get_code(self, field_name: str, field_value_id: str) -> dict[str, Any] | None:
        """
        Get the full code object for a given field_name and field_value_id.

        Args:
            field_name: The name of the field (e.g., "UNIT_MEASURE", "FREQ")
            field_value_id: The ID value to look up (e.g., "PS", "M")

        Returns:
            The code dictionary, or None if not found
        """
        if self.codelist is None:
            raise ValueError("Codelist not loaded. Call set_codelist() first.")

        if field_name not in self.codelist:
            _logger.warning(f"field_name '{field_name}' not found in codelist.")
            return None

        found_codes = list(
            filter(lambda x: x["id"] == field_value_id, self.codelist[field_name])
        )

        if not found_codes:
            _logger.warning(
                f"field_value_id '{field_value_id}' not found for field_name '{field_name}'."
            )
            return None

        if len(found_codes) != 1:
            _logger.warning(
                f"Multiple codes found for field_name '{field_name}' and field_value_id '{field_value_id}'."
            )

        return found_codes[0]


# Global codelist manager instance
_codelist_manager: CodelistManager | None = None


async def get_code_name(field_name: str, field_value_id: str) -> str | None:
    """
    Convenience function to get code name from the global codelist manager.

    Args:
        field_name: The name of the field (e.g., "UNIT_MEASURE", "FREQ")
        field_value_id: The ID value to look up (e.g., "PS", "M")

    Returns:
        The name associated with the field_value_id, or None if not found
    """
    global _codelist_manager
    if _codelist_manager is None:
        _codelist_manager = CodelistManager()
    return await _codelist_manager.get_name(field_name, field_value_id)


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

                except httpx.HTTPStatusError as e:
                    error_msg = f"HTTP error fetching data: {e.response.status_code} - {e.response.text}"
                    _logger.error(error_msg)
                    return IndicatorDataResponse(data=None, error=error_msg)
                except httpx.TimeoutException as e:
                    error_msg = f"Timeout fetching data: {str(e)}"
                    _logger.error(error_msg)
                    return IndicatorDataResponse(data=None, error=error_msg)
                except httpx.RequestError as e:
                    error_msg = (
                        f"Request error fetching data for {indicator_id!r}: {str(e)}"
                    )
                    _logger.error(error_msg)
                    return IndicatorDataResponse(data=None, error=error_msg)

        return IndicatorDataResponse(data=all_data, count=len(all_data), error=None)

    except Exception as e:
        error_msg = f"Unexpected error fetching data: {str(e)}"
        _logger.exception("Unexpected error in data fetch")
        return IndicatorDataResponse(data=None, error=error_msg)
