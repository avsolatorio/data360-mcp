"""Providers for Data360 codelist and reference area data."""

import logging
from typing import Any

import httpx

from data360.config import get_data360_settings

data360_config = get_data360_settings()

_logger = logging.getLogger(__name__)
import asyncio
import json
import time
from pathlib import Path

class DatabaseManager:
    """Manages the list of databases dynamically fetched from the Data360 API.

    On startup, loads a complete JSON fallback so the mapping is never empty.
    All subsequent live refreshes happen in a background asyncio task, ensuring
    that get_mapping() is always a sub-millisecond in-memory dict lookup with
    no I/O or network cost on the hot path.
    """

    def __init__(self, ttl_seconds: float = 86400.0):
        self._cache: dict[str, str] = {}
        self._last_fetched: float = 0.0
        self._ttl = ttl_seconds
        self._bg_task: asyncio.Task | None = None
        self._load_fallback()

    def _load_fallback(self):
        """Load the bundled databases.json at startup to guarantee a non-empty cache."""
        fallback_path = Path(__file__).parent / "databases.json"
        try:
            with open(fallback_path, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
            _logger.info(
                "Loaded %d databases from fallback JSON.", len(self._cache)
            )
        except Exception as e:
            _logger.error("Failed to load fallback database mapping: %s", e)
            self._cache = {}

    # ------------------------------------------------------------------
    # Public API — always a pure in-memory read, never blocks on network
    # ------------------------------------------------------------------

    async def get_mapping(self) -> dict[str, str]:
        """Return the cached database_id→name mapping.

        Always returns immediately from in-memory cache. A background task
        is responsible for keeping the cache fresh via periodic API fetches.
        """
        self._ensure_background_sync()
        return self._cache

    # ------------------------------------------------------------------
    # Background sync machinery
    # ------------------------------------------------------------------

    def _ensure_background_sync(self) -> None:
        """Spawn the background refresh loop if it is not already running."""
        if self._bg_task is None or self._bg_task.done():
            self._bg_task = asyncio.create_task(self._background_sync_loop())

    async def _background_sync_loop(self) -> None:
        """Run forever, refreshing the cache from the API when the TTL expires."""
        while True:
            elapsed = time.monotonic() - self._last_fetched
            if elapsed >= self._ttl:
                try:
                    mapping = await self._fetch_all()
                    if mapping:
                        self._cache = mapping
                        _logger.info(
                            "Background refresh: updated %d databases.", len(mapping)
                        )
                except Exception as e:
                    _logger.error("Background database fetch failed: %s", e)
                    # Keep existing cache; retry after the next full TTL cycle.
                finally:
                    self._last_fetched = time.monotonic()

            sleep_for = max(0.0, self._ttl - (time.monotonic() - self._last_fetched))
            await asyncio.sleep(sleep_for)

    async def _fetch_all(self) -> dict[str, str]:
        """Fetch all datasets from the search endpoint using pagination."""
        url = f"{data360_config.api_url}searchv2"
        mapping: dict[str, str] = {}
        skip = 0
        limit = 50

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                items = None
                last_error = None
                for attempt in range(3):
                    try:
                        response = await client.post(
                            url,
                            headers={"accept": "*/*", "Content-Type": "application/json"},
                            json={
                                "filter": "type eq 'dataset' and (is_active ne false or is_active eq null)",
                                "orderby": "series_description/name",
                                "select": "series_description/database_id, series_description/name",
                                "skip": skip,
                                "top": limit,
                            },
                        )
                        response.raise_for_status()
                        data = response.json()
                        items = data.get("value", [])
                        break  # Success
                    except Exception as e:
                        last_error = e
                        _logger.warning("Fetch attempt %d failed for skip=%d: %s", attempt + 1, skip, e)
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)  # Backoff: 1s, 2s

                if items is None:
                    # All attempts failed
                    raise last_error if last_error else Exception("Unknown error during fetch")

                if not items:
                    break

                for x in items:
                    sd = x.get("series_description", {})
                    db_id = sd.get("database_id")
                    db_name = sd.get("name")
                    if db_id and db_name and db_id not in mapping:
                        mapping[db_id] = db_name

                skip += limit

        return mapping


# Global instance
_database_manager: DatabaseManager | None = None


def get_database_manager() -> DatabaseManager:
    """Get the global DatabaseManager instance."""
    global _database_manager
    if _database_manager is None:
        _database_manager = DatabaseManager()
    return _database_manager


async def get_database_mapping() -> dict[str, str]:
    """Get mapping of database IDs to their actual names (e.g., {'WB_GS': 'Gender Statistics'})."""
    return await get_database_manager().get_mapping()


class CodelistManager:
    """Unified manager for all Data360 codelists.

    Handles both global codelists (fetched from API) and static codelists
    (hardcoded mappings for dimensions without global API endpoints).

    Global codelists available via API:
    - REF_AREA: 284 countries/regions
    - UNIT_MEASURE: 42 measurement units

    Static codelists (indicator-specific, using common patterns):
    - FREQ: Frequency codes (A=Annual, M=Monthly, Q=Quarterly)
    - SEX: Sex/gender codes (F=Female, M=Male, _T=Total)
    - AGE: Age group codes (Y15T24, Y_GE25, etc.)
    - URBANISATION: Urban/rural codes (URB, RUR, _T)
    """

    # Codelists available via /codelist?type=X API
    GLOBAL_CODELISTS = ["REF_AREA", "UNIT_MEASURE"]

    # Static mappings for codelists without global API endpoints
    # These are based on actual values from disaggregation responses
    # Reference: WB_SSGD_UNEMPLOYMENT_RATE_disaggregation.json
    STATIC_MAPPINGS: dict[str, dict[str, str]] = {
        "FREQ": {
            # Common frequency codes found in Data360
            "annual": "A",
            "yearly": "A",
            "year": "A",
            "monthly": "M",
            "month": "M",
            "quarterly": "Q",
            "quarter": "Q",
            "other": "_O",
            "irregular": "_O",
        },
        "SEX": {
            # Sex codes from actual disaggregation data
            "female": "F",
            "women": "F",
            "woman": "F",
            "girls": "F",
            "girl": "F",
            "male": "M",
            "men": "M",
            "man": "M",
            "boys": "M",
            "boy": "M",
            "total": "_T",
            "all": "_T",
            "both": "_T",
            "overall": "_T",
        },
        "AGE": {
            # Age group codes from actual disaggregation data
            "youth": "Y15T24",
            "young": "Y15T24",
            "15-24": "Y15T24",
            "15 to 24": "Y15T24",
            "young adults": "Y15T29",
            "15-29": "Y15T29",
            "adults": "Y30T59",
            "30-59": "Y30T59",
            "25+": "Y_GE25",
            "25 and over": "Y_GE25",
            "adult": "Y_GE25",
            "elderly": "Y_GE60",
            "60+": "Y_GE60",
            "60 and over": "Y_GE60",
            "seniors": "Y_GE60",
            "total": "_T",
            "all ages": "_T",
        },
        "URBANISATION": {
            # Urbanisation codes from actual disaggregation data
            "urban": "URB",
            "city": "URB",
            "cities": "URB",
            "rural": "RUR",
            "countryside": "RUR",
            "village": "RUR",
            "total": "_T",
            "all": "_T",
        },
    }

    def __init__(self):
        """Initialize the CodelistManager."""
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._loaded: set[str] = set()

    async def _ensure_loaded(self, codelist_type: str) -> None:
        """Ensure a global codelist is loaded."""
        if codelist_type in self._loaded:
            return
        if codelist_type in self.GLOBAL_CODELISTS:
            await self._load_from_api(codelist_type)

    async def _load_from_api(self, codelist_type: str) -> None:
        """Fetch a global codelist from the API."""
        url = f"{data360_config.api_url}codelist"
        params = {"type": codelist_type}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                self._cache[codelist_type] = data.get("value", [])
                self._loaded.add(codelist_type)
                _logger.info(
                    f"Loaded {len(self._cache[codelist_type])} items for {codelist_type}"
                )
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error fetching {codelist_type} codelist: {e.response.status_code}"
            _logger.error(error_msg)
            raise
        except httpx.RequestError as e:
            error_msg = f"Request error fetching {codelist_type} codelist: {str(e)}"
            _logger.error(error_msg)
            raise

    def _normalize_query(self, query: str) -> str:
        """Normalize query for case-insensitive and whitespace-invariant search."""
        return query.lower().strip()

    async def find_value(
        self, codelist_type: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Find values in a codelist matching the query.

        Args:
            codelist_type: Type of codelist (REF_AREA, FREQ, SEX, etc.)
            query: Search query (e.g., "Kenya", "monthly", "female")
            limit: Maximum number of results to return

        Returns:
            List of matches with id, name, and score
        """
        codelist_type = codelist_type.upper()

        # Check for multi-value query (comma-separated)
        if "," in query:
            parts = [p.strip() for p in query.split(",") if p.strip()]
            all_results = []
            seen_ids = set()

            for part in parts:
                part_lower = self._normalize_query(part)
                # Recurse for single value
                matches = await self.find_value(
                    codelist_type, part, limit=1
                )  # find top match for each
                for m in matches:
                    if m["id"] not in seen_ids:
                        all_results.append(m)
                        seen_ids.add(m["id"])
            return all_results

        # Explicitly normalize using helper
        query_lower = self._normalize_query(query)

        # Handle global codelists (API-based)
        if codelist_type in self.GLOBAL_CODELISTS:
            await self._ensure_loaded(codelist_type)
            return self._search_global(codelist_type, query_lower, limit)

        # Handle static codelists
        if codelist_type in self.STATIC_MAPPINGS:
            return self._search_static(codelist_type, query_lower, limit)

        # Unknown codelist
        _logger.warning(f"Unknown codelist type: {codelist_type}")
        return []

    def _search_global(
        self, codelist_type: str, query_lower: str, limit: int
    ) -> list[dict[str, Any]]:
        """Search in a global (API-fetched) codelist."""
        items = self._cache.get(codelist_type, [])
        results: list[dict[str, Any]] = []

        # Also search without spaces for cases like "Vietnam" vs "Viet Nam"
        query_no_spaces = query_lower.replace(" ", "")

        for item in items:
            item_id = item.get("Id", "")
            item_name = item.get("Name", "")
            name_lower = item_name.lower()
            name_no_spaces = name_lower.replace(" ", "")

            score = 0

            # Exact ID match
            if query_lower == item_id.lower():
                score = 100
            # Exact name match
            elif query_lower == name_lower:
                score = 100
            # Exact match ignoring spaces (Vietnam == Viet Nam)
            elif query_no_spaces == name_no_spaces:
                score = 100
            # ID starts with query
            elif item_id.lower().startswith(query_lower):
                score = 95
            # Name contains query exactly
            elif query_lower in name_lower:
                score = 90
            # No-space match (vietnam in vietnam)
            elif query_no_spaces in name_no_spaces:
                score = 90
            # Query contains name
            elif name_lower in query_lower:
                score = 85
            else:
                # Fuzzy: prefix matching
                similarity = self._calculate_similarity(query_lower, name_lower)
                if similarity > 0.7:
                    score = int(similarity * 100)

            if score > 0:
                results.append(
                    {
                        "id": item_id,
                        "name": item_name,
                        "score": score,
                    }
                )

        results.sort(key=lambda x: (-x["score"], x["name"]))
        return results[:limit]

    def _search_static(
        self, codelist_type: str, query_lower: str, limit: int
    ) -> list[dict[str, Any]]:
        """Search in a static (hardcoded) codelist."""
        mapping = self.STATIC_MAPPINGS.get(codelist_type, {})
        results: list[dict[str, Any]] = []

        for name, code in mapping.items():
            name_lower = name.lower()
            score = 0

            # Exact match
            if query_lower == name_lower:
                score = 100
            # Query is the code itself
            elif query_lower == code.lower():
                score = 100
            # Name contains query
            elif query_lower in name_lower:
                score = 90
            # Query contains name
            elif name_lower in query_lower:
                score = 80

            if score > 0:
                results.append(
                    {
                        "id": code,
                        "name": name.capitalize(),
                        "score": score,
                    }
                )

        # Deduplicate by id (keep highest score)
        seen: dict[str, dict[str, Any]] = {}
        for r in results:
            rid = r["id"]
            if rid not in seen or r["score"] > seen[rid]["score"]:
                seen[rid] = r

        deduped = list(seen.values())
        deduped.sort(key=lambda x: (-x["score"], x["name"]))
        return deduped[:limit]

    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity ratio between two strings."""
        if not s1 or not s2:
            return 0.0

        if len(s1) <= 3:
            if s1 in s2 or s2.startswith(s1):
                return 0.8
            return 0.0

        len1, len2 = len(s1), len(s2)
        if abs(len1 - len2) > max(len1, len2) * 0.5:
            return 0.0

        s1_chars = set(s1)
        s2_chars = set(s2)
        common = len(s1_chars & s2_chars)
        total = len(s1_chars | s2_chars)
        char_similarity = common / total if total > 0 else 0

        prefix_len = 0
        for c1, c2 in zip(s1, s2):
            if c1 == c2:
                prefix_len += 1
            else:
                break
        prefix_ratio = prefix_len / min(len1, len2)

        return (char_similarity * 0.4) + (prefix_ratio * 0.6)

    async def get_codelist_mapping(self, codelist_type: str) -> dict[str, str]:
        """Get a dictionary mapping codes to names (e.g., {'KEN': 'Kenya'})."""
        codelist_type = codelist_type.upper()

        # Ensure loaded if global
        if codelist_type in self.GLOBAL_CODELISTS:
            await self._ensure_loaded(codelist_type)
            items = self._cache.get(codelist_type, [])
            return {item.get("Id", ""): item.get("Name", "") for item in items}

        # Static mappings (reverse the value->code mapping to code->name)
        if codelist_type in self.STATIC_MAPPINGS:
            # STATIC_MAPPINGS is Name -> Code. We want Code -> Name.
            # Names in static mapping are lower case keys, we should capitalize for display.
            mapping = {}
            for name, code in self.STATIC_MAPPINGS[codelist_type].items():
                if (
                    code not in mapping
                ):  # First win or preferred name logic could be added
                    mapping[code] = name.capitalize()
            return mapping

        return {}


# Global instance
_codelist_manager: CodelistManager | None = None


def get_codelist_manager() -> CodelistManager:
    """Get the global CodelistManager instance."""
    global _codelist_manager
    if _codelist_manager is None:
        _codelist_manager = CodelistManager()
    return _codelist_manager


async def find_codelist_value(
    codelist_type: str, query: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Find values in a Data360 codelist by name (e.g. country or dimension labels).

    Use when you need to convert a user-friendly name to an API code. Helpful before
    data360_search_indicators (required_country) or when building disaggregation_filters
    for data360_get_data / data360_get_viz_spec. Not required if 3-letter codes are already known.

    Args:
        codelist_type: One of REF_AREA (countries/regions), FREQ, SEX, AGE, URBANISATION, UNIT_MEASURE.
        query: Search term (e.g. "Kenya", "female", "annual"). Comma-separated for multiple
            (e.g. "Kenya, Tanzania") returns one match per part.
        limit: Maximum number of matches to return (default 5).

    Returns:
        List of dicts, each with: id (code, e.g. "KEN"), name (e.g. "Kenya"), score (relevance 0–100).
        Sorted by score descending. Empty list if no matches or unknown codelist_type.
    """
    manager = get_codelist_manager()
    return await manager.find_value(codelist_type, query, limit)


async def get_codelist_mapping(codelist_type: str) -> dict[str, str]:
    """Get mapping of codes to names for a codelist."""
    manager = get_codelist_manager()
    return await manager.get_codelist_mapping(codelist_type)


# Convenience functions for common codelists
async def find_reference_area(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Find reference areas (countries/regions) matching the query."""
    return await find_codelist_value("REF_AREA", query, limit)


async def find_frequency(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Find frequency codes matching the query."""
    return await find_codelist_value("FREQ", query, limit)


async def find_sex(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Find sex/gender codes matching the query."""
    return await find_codelist_value("SEX", query, limit)


async def find_age_group(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Find age group codes matching the query."""
    return await find_codelist_value("AGE", query, limit)
