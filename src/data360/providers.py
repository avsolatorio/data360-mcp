"""Providers for Data360 codelist and reference area data."""

import asyncio
import logging
from functools import lru_cache
from typing import Any

import httpx

from data360.config import get_data360_settings

data360_config = get_data360_settings()

_logger = logging.getLogger(__name__)


class ReferenceAreaManager:
    """Manager for fetching and querying Data360 reference area data.

    This manager fetches the REF_AREA codelist from the Data360 API and provides
    methods to search for reference areas by name or code.
    """

    def __init__(self):
        """Initialize the ReferenceAreaManager."""
        self._codelist: list[dict[str, Any]] | None = None
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        """Ensure the codelist is loaded."""
        if not self._loaded:
            await self._load()

    async def _load(self) -> None:
        """Fetch and cache the REF_AREA codelist from the API."""
        url = f"{data360_config.api_url}codelist"
        params = {"type": "REF_AREA"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                self._codelist = data.get("value", [])
                self._loaded = True
                _logger.info(
                    f"Loaded {len(self._codelist)} reference areas from codelist"
                )
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error fetching REF_AREA codelist: {e.response.status_code}"
            _logger.error(error_msg)
            raise
        except httpx.TimeoutException as e:
            error_msg = f"Timeout fetching REF_AREA codelist: {str(e)}"
            _logger.error(error_msg)
            raise
        except httpx.RequestError as e:
            error_msg = f"Request error fetching REF_AREA codelist: {str(e)}"
            _logger.error(error_msg)
            raise

    @property
    def codelist(self) -> list[dict[str, Any]]:
        """Get the codelist."""
        if self._codelist is None:
            raise RuntimeError(
                "REF_AREA codelist not loaded. Call ensure_loaded() first."
            )
        return self._codelist

    async def find_reference_areas(
        self, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Find reference areas matching the query.

        This tool validates that the geographic context (country, region) is valid
        based on the available reference areas from the Data360 codelist.

        Args:
            query: The geographic entity to search for (e.g., "Kenya", "East Africa")
            limit: Maximum number of matches to return

        Returns:
            A list of matching reference areas with id, name, and match score.

        Example:
            >>> await manager.find_reference_areas("Kenya")
            [{"id": "KEN", "name": "Kenya", "score": 100}]

            >>> await manager.find_reference_areas("Kanya")  # typo
            [{"id": "KEN", "name": "Kenya", "score": 91}]
        """
        await self._ensure_loaded()

        query_lower = query.lower().strip()
        results: list[dict[str, Any]] = []

        for item in self.codelist:
            item_id = item.get("Id", "")
            item_name = item.get("Name", "")
            name_lower = item_name.lower()

            # Calculate match score
            score = 0

            # Exact ID match (highest priority)
            if query_lower == item_id.lower():
                score = 100
            # Exact name match
            elif query_lower == name_lower:
                score = 100
            # ID starts with query or query starts with ID
            elif item_id.lower().startswith(query_lower) or query_lower.startswith(
                item_id.lower()
            ):
                score = 95
            # Name contains query exactly
            elif query_lower in name_lower:
                score = 90
            # Query contains name (partial match)
            elif name_lower in query_lower:
                score = 85
            else:
                # Fuzzy matching using simple similarity
                similarity = self._calculate_similarity(query_lower, name_lower)
                if similarity > 0.7:  # 70% similarity threshold
                    score = int(similarity * 100)

            if score > 0:
                results.append(
                    {
                        "id": item_id,
                        "name": item_name,
                        "score": score,
                    }
                )

        # Sort by score descending, then by name
        results.sort(key=lambda x: (-x["score"], x["name"]))

        return results[:limit]

    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity ratio between two strings.

        Uses a simple approach based on common characters and length difference.
        """
        if not s1 or not s2:
            return 0.0

        # For very short queries, use character-based matching
        if len(s1) <= 3:
            if s1 in s2 or s2.startswith(s1):
                return 0.8
            return 0.0

        # Calculate longest common subsequence ratio
        len1, len2 = len(s1), len(s2)

        # Quick length check - if lengths are very different, low similarity
        if abs(len1 - len2) > max(len1, len2) * 0.5:
            return 0.0

        # Count matching characters (simple approach)
        s1_chars = set(s1)
        s2_chars = set(s2)
        common = len(s1_chars & s2_chars)
        total = len(s1_chars | s2_chars)

        char_similarity = common / total if total > 0 else 0

        # Check prefix match
        prefix_len = 0
        for c1, c2 in zip(s1, s2):
            if c1 == c2:
                prefix_len += 1
            else:
                break

        prefix_ratio = prefix_len / min(len1, len2)

        # Combined score
        return (char_similarity * 0.4) + (prefix_ratio * 0.6)


# Global instance
_reference_area_manager: ReferenceAreaManager | None = None


def get_reference_area_manager() -> ReferenceAreaManager:
    """Get the global ReferenceAreaManager instance."""
    global _reference_area_manager
    if _reference_area_manager is None:
        _reference_area_manager = ReferenceAreaManager()
    return _reference_area_manager


async def find_reference_areas(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Find reference areas matching the query.

    This is a convenience function that uses the global ReferenceAreaManager.

    Args:
        query: The geographic entity to search for (e.g., "Kenya", "East Africa")
        limit: Maximum number of matches to return

    Returns:
        A list of matching reference areas with id, name, and match score.
    """
    manager = get_reference_area_manager()
    return await manager.find_reference_areas(query, limit)
