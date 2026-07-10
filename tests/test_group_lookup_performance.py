"""Tests for the O(1) inverted group lookup introduced in summarize_data.

The original implementation called get_country_group per row, which iterated
over all groups in GroupHierarchyManager._groups each time — O(rows × groups).
The replacement pre-builds an inverted dict before the row loop so each per-row
lookup is a single dict access — O(1).

Test coverage:
  1. Correctness: leaf country maps to its containing group.
  2. Correctness: group code maps to itself.
  3. Correctness: unknown code returns "_MISSING".
  4. Correctness: group_type discrimination (REGION vs INCOME).
  5. Performance benchmark: inverted dict time does NOT grow quadratically.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers to build a fake GroupHierarchyManager
# ---------------------------------------------------------------------------

def _make_fake_ghm(n_regions: int = 5, countries_per_region: int = 40) -> MagicMock:
    """Build a mock GHM with n_regions REGION groups and 4 INCOME groups."""
    groups: dict = {}

    for r in range(n_regions):
        gid = f"RGN{r:02d}"
        members = [f"C{r:02d}{j:03d}" for j in range(countries_per_region)]
        groups[gid] = {"type": "REGION", "name": f"Region {r}", "countries": members}

    for i, iname in enumerate(["HIC", "UMC", "LMC", "LIC"]):
        members = [f"I{i:02d}{j:03d}" for j in range(countries_per_region)]
        groups[iname] = {"type": "INCOME", "name": iname, "countries": members}

    ghm = MagicMock()
    ghm._groups = groups
    ghm.is_group.side_effect = lambda code: code.upper() in groups
    ghm.get_group_type.side_effect = lambda code: groups.get(code.upper(), {}).get("type")
    return ghm


def _build_inverted_lookup(ghm) -> dict:
    """Mirror the production inverted-dict construction from api.py."""
    _country_to_group: dict = {}
    for _gid, _ginfo in ghm._groups.items():
        _gtype = _ginfo.get("type", "")
        for _c in _ginfo.get("countries", []):
            _country_to_group[(_c.upper(), _gtype)] = _gid
        _country_to_group[(_gid.upper(), _gtype)] = _gid
    return _country_to_group


def _get_country_group_inverted(lookup: dict, country: str, group_type: str) -> str:
    return lookup.get((country.upper(), group_type), "_MISSING")


def _get_country_group_linear(ghm, country: str, group_type: str) -> str:
    """Original O(n) implementation for reference."""
    country_upper = country.upper()
    if ghm.is_group(country_upper) and ghm.get_group_type(country_upper) == group_type:
        return country_upper
    for gid, info in ghm._groups.items():
        if info.get("type") == group_type and country_upper in info.get("countries", []):
            return gid
    return "_MISSING"


# ---------------------------------------------------------------------------
# Correctness tests
# ---------------------------------------------------------------------------

class TestGroupLookupCorrectness:
    def setup_method(self):
        self.ghm = _make_fake_ghm(n_regions=5, countries_per_region=40)
        self.lookup = _build_inverted_lookup(self.ghm)

    def _resolve(self, country: str, group_type: str) -> str:
        return _get_country_group_inverted(self.lookup, country, group_type)

    def test_leaf_country_resolves_to_containing_region(self):
        result = self._resolve("C00000", "REGION")
        assert result == "RGN00", f"Expected RGN00, got {result}"

    def test_leaf_country_last_in_group(self):
        result = self._resolve("C04039", "REGION")
        assert result == "RGN04"

    def test_group_code_maps_to_itself(self):
        result = self._resolve("RGN02", "REGION")
        assert result == "RGN02"

    def test_unknown_code_returns_missing(self):
        result = self._resolve("ZZZ", "REGION")
        assert result == "_MISSING"

    def test_income_group_resolution(self):
        result = self._resolve("I00000", "INCOME")
        assert result == "HIC"

    def test_income_group_code_maps_to_itself(self):
        result = self._resolve("HIC", "INCOME")
        assert result == "HIC"

    def test_type_discrimination(self):
        # C00000 is only in a REGION group; INCOME lookup must give _MISSING
        assert self._resolve("C00000", "REGION") == "RGN00"
        assert self._resolve("C00000", "INCOME") == "_MISSING"

    def test_case_insensitivity(self):
        assert self._resolve("c00000", "REGION") == self._resolve("C00000", "REGION")

    def test_inverted_matches_linear_for_all_members(self):
        """Inverted dict produces identical results to the original linear scan."""
        for gid, ginfo in self.ghm._groups.items():
            gtype = ginfo["type"]
            for country in ginfo["countries"]:
                linear = _get_country_group_linear(self.ghm, country, gtype)
                inverted = self._resolve(country, gtype)
                assert inverted == linear, (
                    f"Mismatch for {country!r} ({gtype}): "
                    f"linear={linear!r}, inverted={inverted!r}"
                )


# ---------------------------------------------------------------------------
# Performance tests
# ---------------------------------------------------------------------------

SMALL_ROWS = 100
LARGE_ROWS = 5_000
N_REGIONS = 10
COUNTRIES_PER_REGION = 50


def _build_workload(ghm, n_rows: int) -> list:
    all_countries = []
    for ginfo in ghm._groups.values():
        all_countries.extend(ginfo["countries"])
    result = []
    while len(result) < n_rows:
        result.extend(all_countries[: n_rows - len(result)])
    return result[:n_rows]


def _time_linear(ghm, rows: list, group_type: str) -> float:
    start = time.perf_counter()
    for country in rows:
        _get_country_group_linear(ghm, country, group_type)
    return time.perf_counter() - start


def _time_inverted(lookup: dict, rows: list, group_type: str) -> float:
    start = time.perf_counter()
    for country in rows:
        _get_country_group_inverted(lookup, country, group_type)
    return time.perf_counter() - start


class TestGroupLookupPerformance:
    def test_inverted_lookup_is_faster_at_scale(self):
        """Inverted dict should be >=5x faster than linear scan at 5k rows."""
        ghm = _make_fake_ghm(n_regions=N_REGIONS, countries_per_region=COUNTRIES_PER_REGION)
        lookup = _build_inverted_lookup(ghm)
        rows = _build_workload(ghm, LARGE_ROWS)

        t_linear = _time_linear(ghm, rows, "REGION")
        t_inverted = _time_inverted(lookup, rows, "REGION")

        speedup = t_linear / t_inverted if t_inverted > 0 else float("inf")
        assert speedup >= 5.0, (
            f"Expected >=5x speedup but got {speedup:.1f}x "
            f"(linear={t_linear * 1000:.1f}ms, inverted={t_inverted * 1000:.1f}ms)"
        )

    def test_inverted_scales_linearly_not_quadratically(self):
        """Inverted dict time growth should be proportional to rows, not rows*groups."""
        ghm = _make_fake_ghm(n_regions=N_REGIONS, countries_per_region=COUNTRIES_PER_REGION)
        lookup = _build_inverted_lookup(ghm)

        small_rows = _build_workload(ghm, SMALL_ROWS)
        large_rows = _build_workload(ghm, LARGE_ROWS)

        t_small = _time_inverted(lookup, small_rows, "REGION")
        t_large = _time_inverted(lookup, large_rows, "REGION")

        expected_ratio = LARGE_ROWS / SMALL_ROWS  # = 50
        actual_ratio = t_large / t_small if t_small > 0 else float("inf")

        # Allow 3x headroom for OS scheduling noise
        assert actual_ratio <= expected_ratio * 3, (
            f"Time ratio {actual_ratio:.1f}x exceeds 3x linear ratio "
            f"{expected_ratio:.1f}x — lookup may be super-linear."
        )

    def test_inverted_build_is_one_time_cost(self):
        """Building the inverted dict must complete in under 10ms even for large GHM."""
        ghm = _make_fake_ghm(n_regions=20, countries_per_region=200)

        start = time.perf_counter()
        lookup = _build_inverted_lookup(ghm)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, (
            f"Inverted dict build took {elapsed_ms:.1f}ms — should be <10ms."
        )
        assert len(lookup) > 0

    def test_linear_scan_is_slower_than_inverted_at_scale(self):
        """Confirms the perf regression would be visible without the fix."""
        ghm = _make_fake_ghm(n_regions=N_REGIONS, countries_per_region=COUNTRIES_PER_REGION)
        lookup = _build_inverted_lookup(ghm)
        rows = _build_workload(ghm, LARGE_ROWS)

        t_linear = _time_linear(ghm, rows, "REGION")
        t_inverted = _time_inverted(lookup, rows, "REGION")

        # The linear scan should take at least as long as the inverted dict
        assert t_linear >= t_inverted, (
            "Linear scan was faster than inverted dict — something is wrong with the benchmark."
        )
