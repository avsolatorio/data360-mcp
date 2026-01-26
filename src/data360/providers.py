"""Providers for Data360 codelist and reference area data."""

import asyncio
import logging
from typing import Any

import httpx

from data360.config import get_data360_settings

data360_config = get_data360_settings()

_logger = logging.getLogger(__name__)


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
                matches = await self.find_value(codelist_type, part, limit=1) # find top match for each
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
                results.append({
                    "id": item_id,
                    "name": item_name,
                    "score": score,
                })

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
                results.append({
                    "id": code,
                    "name": name.capitalize(),
                    "score": score,
                })

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
                if code not in mapping: # First win or preferred name logic could be added
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
    """Find values in a codelist matching the query.
    
    This is a convenience function that uses the global CodelistManager.
    
    Args:
        codelist_type: Type of codelist (REF_AREA, FREQ, SEX, AGE, URBANISATION, UNIT_MEASURE)
        query: Search query (e.g., "Kenya" or "Kenya, Uganda")
        limit: Maximum number of results to return
        
    Returns:
        List of matches with id, name, and score
        
    Examples:
        >>> await find_codelist_value("REF_AREA", "Kenya")
        [{"id": "KEN", "name": "Kenya", "score": 100}]
        
        >>> await find_codelist_value("REF_AREA", "Kenya, Tanzania")
        [{"id": "KEN", "name": "Kenya", ...}, {"id": "TZA", "name": "Tanzania", ...}]
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
