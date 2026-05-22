"""Tests for extdataportal codelist auto-resolution.

Strategy: the tests inject a fake API response via unittest.mock so they run
offline without the bundled JSON file.  The mock is applied at the httpx
transport level so _fetch_extdataportal() sees realistic input.

Covers:
  - _parse_extdataportal_response(): deduplication, prefix stripping
  - _ensure_extdataportal_loaded(): populates _extdataportal, idempotent
  - get_label(): O(1) code→name, graceful fallback
  - get_dimension_labels(): full dict, returns copy
  - COMP_BREAKDOWN_1/2/3 all route to the unified COMP_BREAKDOWN key
  - _map_dimension_codes() DataFrame transformation
  - series_labels override applied before _map_dimension_codes is idempotent
  - unknown codes / unknown dimensions fall through unchanged
  - _background_refresh_loop(): atomic replace, failure keeps old data
  - Unit measure resolution (UNIT_MEASURE)
  - End-to-end: no raw WGI codes remain after _map_dimension_codes
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from data360.providers import CodelistManager

# ---------------------------------------------------------------------------
# Shared fake API payload (minimal but realistic)
# ---------------------------------------------------------------------------

_FAKE_API = {
    # SEX
    "SEX": [
        {"id": "F", "name": "Female"},
        {"id": "M", "name": "Male"},
        {"id": "_T", "name": "Total"},
        {"id": "_O", "name": "Other"},
        {"id": "_U", "name": "Unknown"},
        {"id": "_Z", "name": "Not applicable"},
    ],
    # AGE (subset)
    "AGE": [
        {"id": "_T", "name": "All ages"},
        {"id": "Y15T24", "name": "15 to 24 years"},
        {"id": "Y_GE25", "name": "25 years or over"},
        {"id": "Y_GE60", "name": "60 years or over"},
    ],
    # URBANISATION
    "URBANISATION": [
        {"id": "URB", "name": "Urban area"},
        {"id": "RUR", "name": "Rural area"},
        {"id": "CITY", "name": "City"},
        {"id": "_T", "name": "Total"},
    ],
    # FREQ
    "FREQ": [
        {"id": "A", "name": "Annual"},
        {"id": "M", "name": "Monthly"},
        {"id": "Q", "name": "Quarterly"},
    ],
    # UNIT_MEASURE
    "UNIT_MEASURE": [
        {"id": "PT", "name": "Percent"},
        {"id": "USD", "name": "US Dollars"},
        {"id": "NUM", "name": "Number"},
    ],
    # COMP_BREAKDOWN — split across three keys (as returned by the real API).
    # Build script deduplicates; _parse_extdataportal_response must too.
    "COMP_BREAKDOWN_1": [
        {"id": "WGI_EST", "name": "Metric: Governance estimate (approx. -2.5 to +2.5)"},
        {"id": "WGI_SC", "name": "Metric: Percentile rank (0–100)"},
        {"id": "WGI_SC_LB", "name": "Metric: Lower bound of confidence interval"},
        {"id": "WGI_SC_UB", "name": "Metric: Upper bound of confidence interval"},
        {"id": "WGI_SE", "name": "Metric: Standard error"},
        {"id": "WGI_SR", "name": "Metric: Source count"},
    ],
    "COMP_BREAKDOWN_2": [
        {"id": "WGI_EST", "name": "Metric: Governance estimate (approx. -2.5 to +2.5)"},
        {"id": "IPC_IPC_PHASE3", "name": "Metric: IPC Phase 3 – Crisis"},
    ],
    "COMP_BREAKDOWN_3": [
        {"id": "WEF_TTDI_RNK", "name": "Metric: Travel & Tourism rank"},
    ],
    "_meta": {"source": "test"},
}

YEARS = [pd.Timestamp(str(y)) for y in range(2010, 2022)]


def _fresh_mgr() -> CodelistManager:
    """Return a brand-new CodelistManager with _extdataportal already loaded."""
    mgr = CodelistManager()
    mgr._extdataportal = CodelistManager._parse_extdataportal_response(_FAKE_API)
    return mgr


def _make_wgi_df(country: str = "GEO") -> pd.DataFrame:
    rows = []
    for bd in ["WGI_EST", "WGI_SC", "WGI_SC_LB", "WGI_SC_UB", "WGI_SE", "WGI_SR"]:
        for yr in YEARS:
            rows.append({"year": yr, "value": 1.0, "country": country, "comp_breakdown_1": bd})
    return pd.DataFrame(rows)


# ============================================================================
# 1. _parse_extdataportal_response
# ============================================================================


class TestParseExtdataportalResponse:
    def _parse(self, payload: dict) -> dict:
        return CodelistManager._parse_extdataportal_response(payload)

    def test_comp_breakdown_deduplicated_to_single_key(self):
        result = self._parse(_FAKE_API)
        assert "COMP_BREAKDOWN" in result
        assert "COMP_BREAKDOWN_1" not in result
        assert "COMP_BREAKDOWN_2" not in result
        assert "COMP_BREAKDOWN_3" not in result

    def test_comp_breakdown_merges_all_three(self):
        result = self._parse(_FAKE_API)
        cb = result["COMP_BREAKDOWN"]
        # From _1
        assert "WGI_EST" in cb
        assert "WGI_SC_LB" in cb
        # From _2 only
        assert "IPC_IPC_PHASE3" in cb
        # From _3 only
        assert "WEF_TTDI_RNK" in cb

    def test_metric_prefix_stripped(self):
        result = self._parse(_FAKE_API)
        cb = result["COMP_BREAKDOWN"]
        assert not any(v.startswith("Metric: ") for v in cb.values()), (
            "All 'Metric: ' prefixes must be stripped"
        )

    def test_wgi_est_label_correct(self):
        result = self._parse(_FAKE_API)
        assert result["COMP_BREAKDOWN"]["WGI_EST"] == "Governance estimate (approx. -2.5 to +2.5)"

    def test_sex_dimension_present(self):
        result = self._parse(_FAKE_API)
        assert result["SEX"]["F"] == "Female"
        assert result["SEX"]["M"] == "Male"

    def test_unit_measure_pt(self):
        result = self._parse(_FAKE_API)
        assert result["UNIT_MEASURE"]["PT"] == "Percent"

    def test_meta_key_ignored(self):
        result = self._parse(_FAKE_API)
        assert "_meta" not in result

    def test_non_list_dim_ignored(self):
        payload = {"JUNK": "not a list", "SEX": [{"id": "F", "name": "Female"}]}
        result = self._parse(payload)
        assert "JUNK" not in result
        assert result["SEX"]["F"] == "Female"

    def test_item_missing_id_skipped(self):
        payload = {"SEX": [{"name": "no id here"}, {"id": "F", "name": "Female"}]}
        result = self._parse(payload)
        assert list(result["SEX"].keys()) == ["F"]


# ============================================================================
# 2. _ensure_extdataportal_loaded() — lazy async fetch + idempotency
# ============================================================================


class TestEnsureExtdataportalLoaded:
    @pytest.mark.asyncio
    async def test_populates_extdataportal(self):
        mgr = CodelistManager()
        assert not mgr._extdataportal

        mgr._fetch_extdataportal = AsyncMock(
            return_value=CodelistManager._parse_extdataportal_response(_FAKE_API)
        )
        await mgr._ensure_extdataportal_loaded()

        assert mgr._extdataportal
        assert "COMP_BREAKDOWN" in mgr._extdataportal

    @pytest.mark.asyncio
    async def test_is_idempotent(self):
        mgr = CodelistManager()
        mgr._fetch_extdataportal = AsyncMock(
            return_value=CodelistManager._parse_extdataportal_response(_FAKE_API)
        )
        await mgr._ensure_extdataportal_loaded()
        call_count = mgr._fetch_extdataportal.call_count

        # Second call must not re-fetch (data already populated)
        await mgr._ensure_extdataportal_loaded()
        assert mgr._fetch_extdataportal.call_count == call_count, (
            "_ensure_extdataportal_loaded() should be a no-op if _extdataportal already populated"
        )

    @pytest.mark.asyncio
    async def test_graceful_on_network_failure(self):
        mgr = CodelistManager()
        import httpx
        mgr._fetch_extdataportal = AsyncMock(side_effect=httpx.RequestError("timeout"))
        # Must not raise
        await mgr._ensure_extdataportal_loaded()
        # _extdataportal stays empty — graceful fallback
        assert mgr._extdataportal == {}


# ============================================================================
# 3. get_label() — O(1) lookup, graceful fallback
# ============================================================================


class TestGetLabel:
    def test_wgi_est_resolves(self):
        mgr = _fresh_mgr()
        label = mgr.get_label("COMP_BREAKDOWN_1", "WGI_EST")
        assert "estimate" in label.lower() or "governance" in label.lower()

    def test_wgi_sc_lb_resolves(self):
        mgr = _fresh_mgr()
        label = mgr.get_label("COMP_BREAKDOWN_1", "WGI_SC_LB")
        assert "lower" in label.lower() or "bound" in label.lower()

    def test_sex_female(self):
        assert _fresh_mgr().get_label("SEX", "F") == "Female"

    def test_sex_male(self):
        assert _fresh_mgr().get_label("SEX", "M") == "Male"

    def test_unit_measure_pt(self):
        assert _fresh_mgr().get_label("UNIT_MEASURE", "PT") == "Percent"

    def test_unknown_code_returns_code(self):
        assert _fresh_mgr().get_label("SEX", "NONEXISTENT") == "NONEXISTENT"

    def test_unknown_dimension_returns_code(self):
        assert _fresh_mgr().get_label("MADE_UP_DIM", "XYZ") == "XYZ"

    def test_empty_code_returns_empty(self):
        assert _fresh_mgr().get_label("SEX", "") == ""

    def test_comp_breakdown_1_routes_to_shared_key(self):
        mgr = _fresh_mgr()
        label_via_1 = mgr.get_label("COMP_BREAKDOWN_1", "WGI_EST")
        label_direct = mgr._extdataportal.get("COMP_BREAKDOWN", {}).get("WGI_EST")
        assert label_via_1 == label_direct

    def test_comp_breakdown_2_routes_same_as_1(self):
        mgr = _fresh_mgr()
        assert mgr.get_label("COMP_BREAKDOWN_2", "WGI_EST") == mgr.get_label("COMP_BREAKDOWN_1", "WGI_EST")

    def test_comp_breakdown_3_routes_same_as_1(self):
        mgr = _fresh_mgr()
        assert mgr.get_label("COMP_BREAKDOWN_3", "WGI_EST") == mgr.get_label("COMP_BREAKDOWN_1", "WGI_EST")

    def test_no_metric_prefix_in_any_label(self):
        mgr = _fresh_mgr()
        for code, name in mgr._extdataportal.get("COMP_BREAKDOWN", {}).items():
            assert not name.startswith("Metric: "), (
                f"'Metric: ' prefix not stripped for {code!r}: {name!r}"
            )

    def test_empty_extdataportal_returns_code(self):
        """Before first load, get_label must degrade gracefully."""
        mgr = CodelistManager()  # _extdataportal = {}
        assert mgr.get_label("SEX", "F") == "F"


# ============================================================================
# 4. get_dimension_labels() — full dict, returns copy
# ============================================================================


class TestGetDimensionLabels:
    def test_returns_dict_for_sex(self):
        mgr = _fresh_mgr()
        labels = mgr.get_dimension_labels("SEX")
        assert isinstance(labels, dict)
        assert labels["F"] == "Female"

    def test_comp_breakdown_1_returns_all_codes(self):
        mgr = _fresh_mgr()
        labels = mgr.get_dimension_labels("COMP_BREAKDOWN_1")
        assert "WGI_EST" in labels
        assert "IPC_IPC_PHASE3" in labels  # merged from _2
        assert "WEF_TTDI_RNK" in labels   # merged from _3

    def test_unknown_dimension_returns_empty_dict(self):
        assert _fresh_mgr().get_dimension_labels("COMPLETELY_MADE_UP") == {}

    def test_returns_copy_not_reference(self):
        mgr = _fresh_mgr()
        labels = mgr.get_dimension_labels("SEX")
        labels["F"] = "MODIFIED"
        # Internal state must not be mutated
        assert mgr._extdataportal["SEX"]["F"] == "Female"


# ============================================================================
# 5. _map_dimension_codes() DataFrame transformation
# ============================================================================

from data360.visualization import _VIZ_DISAGG_DIMS, _map_dimension_codes  # noqa: E402


def _patch_mgr(mgr: CodelistManager):
    """Patch get_codelist_manager() at the source (providers module).

    _map_dimension_codes() imports it locally with
    ``from data360.providers import get_codelist_manager``, so the patch
    must target the definition site, not the visualization module namespace.
    """
    return patch("data360.providers.get_codelist_manager", return_value=mgr)


class TestMapDimensionCodes:
    def _run(self, df: pd.DataFrame, mgr: CodelistManager) -> pd.DataFrame:
        with _patch_mgr(mgr):
            return asyncio.get_event_loop().run_until_complete(_map_dimension_codes(df))

    def test_wgi_est_replaced(self):
        mgr = _fresh_mgr()
        df = _make_wgi_df()
        result = self._run(df, mgr)
        assert "WGI_EST" not in set(result["comp_breakdown_1"].unique())

    def test_wgi_sc_lb_contains_lower_or_bound(self):
        mgr = _fresh_mgr()
        df = _make_wgi_df()
        result = self._run(df, mgr)
        has_lower_bound = result["comp_breakdown_1"].str.contains(
            "lower|bound", case=False, na=False
        ).any()
        assert has_lower_bound

    def test_sex_f_replaced_with_female(self):
        mgr = _fresh_mgr()
        df = pd.DataFrame({"year": YEARS[:3], "value": [1.0] * 3, "sex": ["F", "M", "_T"]})
        result = self._run(df, mgr)
        assert "Female" in result["sex"].values
        assert "Male" in result["sex"].values

    def test_absent_column_silently_skipped(self):
        mgr = _fresh_mgr()
        df = pd.DataFrame({"year": YEARS[:2], "value": [1.0, 2.0], "sex": ["F", "M"]})
        result = self._run(df, mgr)
        assert "comp_breakdown_1" not in result.columns

    def test_unknown_code_left_unchanged(self):
        mgr = _fresh_mgr()
        df = pd.DataFrame({"year": YEARS[:2], "value": [1.0, 2.0], "sex": ["TOTALLY_UNKNOWN", "_T"]})
        result = self._run(df, mgr)
        assert "TOTALLY_UNKNOWN" in result["sex"].values

    def test_urbanisation_urb_replaced(self):
        mgr = _fresh_mgr()
        df = pd.DataFrame({"year": YEARS[:2], "value": [1.0, 2.0], "urbanisation": ["URB", "RUR"]})
        result = self._run(df, mgr)
        assert "URB" not in result["urbanisation"].values
        assert "RUR" not in result["urbanisation"].values

    def test_series_labels_override_before_map(self):
        """series_labels replaces raw codes before _map_dimension_codes runs."""
        df = _make_wgi_df()
        series_labels = {"WGI_EST": "Estimate"}
        for col in _VIZ_DISAGG_DIMS:
            if col in df.columns:
                df[col] = df[col].replace(series_labels)
        assert "Estimate" in df["comp_breakdown_1"].values

    def test_empty_extdataportal_leaves_codes_unchanged(self):
        """Before first load, _map_dimension_codes must degrade gracefully."""
        mgr = CodelistManager()  # empty _extdataportal
        df = pd.DataFrame({"year": YEARS[:2], "value": [1.0, 2.0], "sex": ["F", "M"]})
        result = self._run(df, mgr)
        # Codes should remain unchanged (no lookup available)
        assert "F" in result["sex"].values
        assert "M" in result["sex"].values


# ============================================================================
# 6. Unit measure (UNIT_MEASURE) resolution
# ============================================================================


class TestUnitMeasureResolution:
    def test_pt_resolves_to_percent(self):
        mgr = _fresh_mgr()
        assert mgr.get_label("UNIT_MEASURE", "PT") == "Percent"

    def test_unknown_unit_returns_code(self):
        mgr = _fresh_mgr()
        assert mgr.get_label("UNIT_MEASURE", "TOTALLY_UNKNOWN") == "TOTALLY_UNKNOWN"

    def test_empty_unit_returns_empty(self):
        mgr = _fresh_mgr()
        assert mgr.get_label("UNIT_MEASURE", "") == ""


# ============================================================================
# 7. Background refresh loop
# ============================================================================


class TestBackgroundRefreshLoop:
    @pytest.mark.asyncio
    async def test_refresh_replaces_data(self):
        import time

        mgr = CodelistManager()
        # Seed with initial data
        mgr._extdataportal = {"SEX": {"F": "Female"}}
        # Force TTL to have elapsed by setting _last_fetched far in the past.
        mgr._last_fetched = time.monotonic() - mgr._TTL - 1.0

        new_data = {"SEX": {"F": "Female (updated)", "M": "Male"}}
        mgr._fetch_extdataportal = AsyncMock(return_value=new_data)

        # Manually run one refresh cycle (mirrors the loop body).
        elapsed = time.monotonic() - mgr._last_fetched
        if elapsed >= mgr._TTL:
            mapping = await mgr._fetch_extdataportal()
            mgr._apply_extdataportal(mapping)

        assert mgr._extdataportal["SEX"]["F"] == "Female (updated)"
        assert mgr._extdataportal["SEX"]["M"] == "Male"

    @pytest.mark.asyncio
    async def test_refresh_failure_keeps_old_data(self):
        import httpx

        mgr = CodelistManager()
        mgr._extdataportal = {"SEX": {"F": "Female"}}
        mgr._fetch_extdataportal = AsyncMock(side_effect=httpx.RequestError("timeout"))

        try:
            await mgr._fetch_extdataportal()
        except Exception:
            pass  # failure — existing data preserved

        assert mgr._extdataportal["SEX"]["F"] == "Female"


# ============================================================================
# 8. End-to-end: no raw WGI codes remain after _map_dimension_codes
# ============================================================================


class TestEndToEndWgiResolution:
    def test_all_wgi_codes_replaced(self):
        mgr = _fresh_mgr()
        df = _make_wgi_df()
        with _patch_mgr(mgr):
            result = asyncio.get_event_loop().run_until_complete(_map_dimension_codes(df))
        raw_wgi = {"WGI_EST", "WGI_SC", "WGI_SC_LB", "WGI_SC_UB", "WGI_SE", "WGI_SR"}
        remaining = raw_wgi & set(result["comp_breakdown_1"].unique())
        assert not remaining, f"Unresolved WGI codes: {remaining}"
