import asyncio
import logging
from functools import lru_cache
from typing import Any

import httpx

from data360.config import get_data360_settings

data360_config = get_data360_settings()

_logger = logging.getLogger(__name__)


class CodelistManager:
    """Manager for fetching and querying Data360 codelist data."""

    def __init__(self, codelist_url: str | None = None):
        """Initialize the CodelistManager."""
        self.codelist_url = (
            codelist_url
            or data360_config.codelist_api_base_url
            or f"{data360_config.api_url}/metadata/codelist"
        )
        self._codelist: dict[str, Any] | None = None

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._load())
        else:
            loop.create_task(self._load())

    @property
    def codelist(self) -> dict[str, Any]:
        """Get the codelist."""
        if self._codelist is None:
            raise RuntimeError("Codelist not loaded.")
        return self._codelist

    async def _load(self) -> None:
        """Fetch and cache the codelist from the API."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self.codelist_url)
                response.raise_for_status()
                self._codelist = response.json()
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

    def get_field_codelist(self, field_name: str) -> dict[str, Any] | None:
        """
        Get the codelist for a given field_name from the codelist.

        Args:
            field_name: The name of the field (e.g., "UNIT_MEASURE", "FREQ")

        Returns:
            The codelist for the given field_name, or None if not found
        """
        if self.codelist is None:
            raise ValueError("Codelist not loaded. Call set_codelist() first.")
        if field_name not in self.codelist:
            _logger.warning(f"field_name '{field_name}' not found in codelist.")
            return None
        return self.codelist[field_name]

    def get_name(self, field_name: str, field_value_id: str) -> str | None:
        """
        Get the name for a given field_name and field_value_id from the codelist.

        Args:
            field_name: The name of the field (e.g., "UNIT_MEASURE", "FREQ")
            field_value_id: The ID value to look up (e.g., "PS", "M")

        Returns:
            The name associated with the field_value_id, or None if not found
        """
        code = self.get_code(field_name, field_value_id)
        if code is None:
            return None
        return code["name"]

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


@lru_cache(maxsize=1)
def get_codelist_manager() -> CodelistManager:
    """Get the global codelist manager instance."""
    return CodelistManager()


# Implement reference area provider
class ReferenceAreaManager:
    """Manager for fetching and querying Data360 reference area data.

    We implement a search to get relevant reference areas.

    """

    def __init__(self, ref_area_field: str = "REF_AREA"):
        """Initialize the ReferenceAreaManager."""
        self.ref_area_field = ref_area_field
        self.ref_area_codelist: dict[str, Any] | None = (
            get_codelist_manager().get_field_codelist(ref_area_field)
        )

    def find_reference_areas(self, query: str) -> list[str]:
        """Find reference areas matching the query.

        Args:
            query: The query to search for

        Returns:
            A list of reference areas likely to match the query.
        """

        raise NotImplementedError("Not implemented yet.")


def build_disaggregation_filter(query: str) -> str:
    """Build a filter string for the disaggregation filters.

    Args:
        query: The query to search for

    Returns:
        A filter string for the disaggregation filters
    """
    filter_string = ""
    filter_string += f"series_description/ref_country/any(t: t/code eq '{query}')"
    return filter_string
