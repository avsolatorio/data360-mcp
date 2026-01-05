import logging
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

        if self.codelist is None:
            _logger.warning("Codelist is None after set_codelist()")
            return None

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
    # ruff: noqa: PLW0603
    global _codelist_manager
    if _codelist_manager is None:
        _codelist_manager = CodelistManager()
    return await _codelist_manager.get_name(field_name, field_value_id)
