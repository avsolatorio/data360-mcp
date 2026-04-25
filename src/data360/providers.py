"""Providers for Data360 codelist and reference area data."""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from data360.config import get_data360_settings

data360_config = get_data360_settings()

_logger = logging.getLogger(__name__)

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
            with open(fallback_path, encoding="utf-8") as f:
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


# ---------------------------------------------------------------------------
# Natural-language aliases for group codes.
# Keys are lower-cased phrases a user might type; values are FMR group codes.
# ---------------------------------------------------------------------------
_GROUP_ALIASES: dict[str, str] = {
    # South Asia
    "south asian countries": "SAS",
    "south asian": "SAS",
    "south asia": "SAS",
    # Sub-Saharan Africa
    "sub-saharan african countries": "SSF",
    "sub-saharan africa": "SSF",
    "sub-saharan": "SSF",
    # East Asia & Pacific
    "east asia and pacific": "EAS",
    "east asia & pacific": "EAS",
    "east asia pacific": "EAS",
    # Europe & Central Asia
    "europe and central asia": "ECS",
    "europe & central asia": "ECS",
    # Latin America & Caribbean
    "latin america and the caribbean": "LCN",
    "latin america & caribbean": "LCN",
    "latin america": "LCN",
    # Middle East & North Africa
    "middle east and north africa": "MEA",
    "middle east & north africa": "MEA",
    "mena": "MEA",
    # North America
    "north america": "NAC",
    # Income groups
    "low income": "LIC",
    "low income countries": "LIC",
    "lower income": "LIC",
    "high income": "HIC",
    "high income countries": "HIC",
    "upper middle income": "UMC",
    "upper middle income countries": "UMC",
    "lower middle income": "LMC",
    "lower middle income countries": "LMC",
    "low and middle income": "LMY",
    "middle income": "MIC",
    "middle income countries": "MIC",
    # Special groupings
    "fragile states": "FCS",
    "fragile and conflict": "FCS",
    "fragile and conflict affected": "FCS",
    "least developed countries": "LDC",
    "least developed": "LDC",
    "small island states": "SST",
    "small states": "SST",
    "oecd members": "OED",
    "oecd": "OED",
    "european union": "EUU",
    "eu": "EUU",
    # Africa sub-regions
    "eastern africa": "AFE",
    "western africa": "AFW",
    "arab world": "ARB",
    # IDA/IBRD
    "ida": "IDA",
    "ibrd": "IBD",
}


class GroupHierarchyManager:
    """Manages REF_AREA group-to-country mappings from bundled FMR hierarchy data.

    Loaded once from src/data360/data/ref_area_groups.json at first access.
    That file is generated by scripts/build_ref_area_groups.py from the FMR
    SDMX hierarchy (H_REF_AREA_GROUPS) and codelist (CL_REF_GROUPINGS).

    Covers all 147 group codes across 6 group types:
      REGION, INCOME, LENDING, OTHER, REGION_UN, CONTINENT.
    """

    _DATA_FILE = Path(__file__).parent / "data" / "ref_area_groups.json"

    def __init__(self, include_types: set[str] | None = None) -> None:
        """Initialize with optional group type filter.

        Args:
            include_types: If provided, only load groups of these types.
                Defaults to all types. Common subset:
                {"REGION", "INCOME", "LENDING", "OTHER"}
        """
        self._groups: dict[str, dict[str, Any]] = {}
        self._all_countries: set[str] = set()
        self._meta: dict[str, Any] = {}
        self._include_types = include_types
        self._loaded = False

    def _load(self) -> None:
        """Load bundled ref_area_groups.json. Called lazily on first access."""
        if self._loaded:
            return
        try:
            with open(self._DATA_FILE, encoding="utf-8") as f:
                data = json.load(f)
            raw_groups: dict[str, dict] = data.get("groups", {})
            if self._include_types:
                raw_groups = {
                    k: v
                    for k, v in raw_groups.items()
                    if v.get("type") in self._include_types
                }
            self._groups = raw_groups
            self._all_countries = set(data.get("all_countries", []))
            self._meta = data.get("_meta", {})
            self._loaded = True
            _logger.info(
                "GroupHierarchyManager: loaded %d groups (%d countries). Source: %s",
                len(self._groups),
                len(self._all_countries),
                self._meta.get("source", "unknown"),
            )
        except FileNotFoundError:
            _logger.error(
                "GroupHierarchyManager: bundled data file not found at %s. "
                "Run scripts/build_ref_area_groups.py to generate it.",
                self._DATA_FILE,
            )
            self._loaded = True  # Prevent repeated failure attempts.
        except Exception as e:
            _logger.error("GroupHierarchyManager: failed to load data: %s", e)
            self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_group(self, code: str) -> bool:
        """Return True if the code is a known country group (not a leaf country)."""
        self._ensure_loaded()
        return code.upper() in self._groups

    def is_country(self, code: str) -> bool:
        """Return True if the code is an individual country in the hierarchy."""
        self._ensure_loaded()
        return code.upper() in self._all_countries and not self.is_group(code.upper())

    def get_group_info(self, code: str) -> dict[str, Any] | None:
        """Return {name, type, countries} for a group code, or None if unknown."""
        self._ensure_loaded()
        return self._groups.get(code.upper())

    def get_group_type(self, code: str) -> str | None:
        """Return the group type string (REGION, INCOME, ...) or None."""
        info = self.get_group_info(code)
        return info["type"] if info else None

    def expand_group(self, code: str) -> list[str]:
        """Return sorted list of country codes in a group, or [] if unknown."""
        info = self.get_group_info(code)
        return list(info["countries"]) if info else []

    def get_meta(self) -> dict[str, Any]:
        """Return metadata about the loaded hierarchy (version, built_at, etc.)."""
        self._ensure_loaded()
        return self._meta

    def search_groups(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search group names by substring. Returns [{id, name, type, count}]."""
        self._ensure_loaded()
        q = query.lower().strip()
        results = []
        for gid, info in self._groups.items():
            if q in info["name"].lower() or q == gid.lower():
                results.append(
                    {
                        "id": gid,
                        "name": info["name"],
                        "type": info["type"],
                        "count": len(info["countries"]),
                    }
                )
        results.sort(key=lambda x: x["name"])
        return results[:limit]


# Global instance
_group_hierarchy_manager: GroupHierarchyManager | None = None


def get_group_hierarchy_manager() -> GroupHierarchyManager:
    """Get the global GroupHierarchyManager instance."""
    global _group_hierarchy_manager
    if _group_hierarchy_manager is None:
        _group_hierarchy_manager = GroupHierarchyManager()
    return _group_hierarchy_manager


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
        """Search in a global (API-fetched) codelist.

        For REF_AREA, results are enriched with group metadata (is_group,
        group_type, member_count) sourced from the GroupHierarchyManager.
        """
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
        matches = results[:limit]

        # Enrich REF_AREA results with group metadata.
        if codelist_type == "REF_AREA":
            ghm = get_group_hierarchy_manager()
            for match in matches:
                info = ghm.get_group_info(match["id"])
                if info:
                    match["is_group"] = True
                    match["group_type"] = info["type"]
                    match["member_count"] = len(info["countries"])
                    match["note"] = (
                        f"This is a {info['type'].lower()} group with "
                        f"{len(info['countries'])} member countries. "
                        f"Use data360_expand_country_group('{match['id']}') "
                        "to get individual country codes."
                    )
                else:
                    match["is_group"] = False

        return matches

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

    For REF_AREA queries, results include group metadata:
      - is_group (bool): whether the code is a country group or an individual country
      - group_type (str): REGION, INCOME, LENDING, OTHER, REGION_UN, or CONTINENT
      - member_count (int): number of countries in the group
      - note (str): guidance on using data360_expand_country_group

    Workflow for country groups (e.g. "South Asian countries", "low income countries"):
      1. Call this function with codelist_type="REF_AREA" and the group name as query.
      2. If the result has is_group=True, you have the group code (e.g. "SAS", "LIC").
      3. To get individual country-level codes, call data360_expand_country_group with
         that code. Use the returned country_codes string directly in data360_get_data
         or data360_search_indicators disaggregation_filters.
      4. To use the group as a regional aggregate instead, pass the group code directly
         (e.g. REF_AREA="SAS") without expanding.

    Args:
        codelist_type: One of REF_AREA (countries/regions), FREQ, SEX, AGE, URBANISATION, UNIT_MEASURE.
        query: Search term (e.g. "Kenya", "female", "annual"). Comma-separated for multiple
            (e.g. "Kenya, Tanzania") returns one match per part. For REF_AREA, natural-language
            group phrases are also recognized (e.g. "South Asian countries", "low income countries").
        limit: Maximum number of matches to return (default 5).

    Returns:
        List of dicts, each with: id (code, e.g. "KEN"), name (e.g. "Kenya"), score (relevance 0–100).
        For REF_AREA, also includes is_group, group_type, member_count, note when applicable.
        Sorted by score descending. Empty list if no matches or unknown codelist_type.
    """
    # Check alias map for REF_AREA before fuzzy search.
    if codelist_type.upper() == "REF_AREA":
        alias_key = query.lower().strip()
        if alias_key in _GROUP_ALIASES:
            group_code = _GROUP_ALIASES[alias_key]
            ghm = get_group_hierarchy_manager()
            info = ghm.get_group_info(group_code)
            if info:
                result = {
                    "id": group_code,
                    "name": info["name"],
                    "score": 100,
                    "is_group": True,
                    "group_type": info["type"],
                    "member_count": len(info["countries"]),
                    "note": (
                        f"This is a {info['type'].lower()} group with "
                        f"{len(info['countries'])} member countries. "
                        f"Use data360_expand_country_group('{group_code}') "
                        "to get individual country codes."
                    ),
                }
                return [result]

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


async def expand_country_group(
    group_code: str,
) -> dict[str, Any]:
    """Expand a REF_AREA group code into its constituent country codes.

    Use this when a user asks about a region, income group, or lending category
    and you need individual country-level data rather than the aggregate.

    Workflow for group discovery and expansion:
      1. If you only have a natural-language name (e.g. "South Asian countries"),
         call data360_find_codelist_value(codelist_type="REF_AREA", query="<name>")
         first to resolve it to a group code (e.g. "SAS").
      2. Pass that code to this function to get the full country list.
      3. Use the returned country_codes string directly in data360_get_data or
         data360_search_indicators disaggregation_filters for country-level queries.

    Decision guidance:
    - "Compare X across South Asian countries" -> expand SAS, query each country
    - "What is South Asia's GDP?" -> use SAS directly with get_data (aggregate)
    - If the group has >20 countries, consider using the aggregate code instead.

    Covers groups sourced from FMR H_REF_AREA_GROUPS v38.0:
      REGION    - WB regional classifications (SAS, SSF, EAS, ECS, LCN, ...)
      INCOME    - LIC, LMC, UMC, HIC, MIC, LMY, MIX
      LENDING   - IDA, IBRD, blend classifications
      OTHER     - FCS, LDC, SST, OED, EUU, ...
      REGION_UN - UN M49 statistical divisions
      CONTINENT - Continental groupings

    Args:
        group_code: REF_AREA group code (e.g. "SAS", "LIC", "EAS", "FCS").
            Case-insensitive. Natural-language names (e.g. "south asian countries")
            are also accepted as a convenience; they are resolved via the alias map.
            For reliable discovery, use data360_find_codelist_value first.

    Returns:
        Dict with:
          - group_code (str): uppercased code
          - group_name (str): human-readable name
          - group_type (str): REGION | INCOME | LENDING | OTHER | REGION_UN | CONTINENT
          - countries (list[dict]): [{code, name}] for each member country
          - country_codes (str): comma-separated codes for direct use in API calls
          - count (int): number of member countries
          - hierarchy_version (str): FMR hierarchy version used
        On failure:
          - error (str): description of what went wrong
    """
    ghm = get_group_hierarchy_manager()
    code_upper = group_code.strip().upper()
    info = ghm.get_group_info(code_upper)

    if not info:
        # Try alias resolution as a fallback
        alias_key = group_code.lower().strip()
        if alias_key in _GROUP_ALIASES:
            code_upper = _GROUP_ALIASES[alias_key]
            info = ghm.get_group_info(code_upper)

    if not info:
        return {
            "error": (
                f"Unknown group code: '{group_code}'. "
                "Use data360_find_codelist_value('REF_AREA', '<name>') to find "
                "the correct code, or check that the group exists in the FMR hierarchy."
            )
        }

    # Build country list with names from the Data360 codelist (best-effort).
    # Codes are always available; names may be missing for some entries.
    cl_manager = get_codelist_manager()
    country_name_map: dict[str, str] = {}
    try:
        country_name_map = await cl_manager.get_codelist_mapping("REF_AREA")
    except Exception as e:
        # Names are a convenience; codes are always returned even without them.
        _logger.warning(
            "expand_country_group: failed to fetch REF_AREA name mapping for '%s': %s. "
            "Country names will fall back to code strings.",
            code_upper,
            e,
        )

    countries = [
        {"code": c, "name": country_name_map.get(c, c)}
        for c in info["countries"]
    ]

    meta = ghm.get_meta()

    return {
        "group_code": code_upper,
        "group_name": info["name"],
        "group_type": info["type"],
        "countries": countries,
        "country_codes": ",".join(c["code"] for c in countries),
        "count": len(countries),
        "hierarchy_version": meta.get("hierarchy_version", "unknown"),
    }
