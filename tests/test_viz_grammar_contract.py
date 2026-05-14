"""Tests for the Grammar of Graphics contract in visualization tool docstrings
and the corresponding pipeline behavior for multi-breakdown indicators.

Concerns verified here:
  1. Contract presence — the docstring cannot be accidentally stripped without
     failing CI, preventing silent regression of the LLM guidance.
  2. Pipeline correctness — unfiltered WGI-style data (multi-country x
     multi-breakdown x multi-year) must produce SMALL_MULTIPLES with the
     correct Vega-Lite facet/color encoding, NOT a single collapsed series.
  3. Homogeneous breakdown detection — IPC phases must NOT trigger the
     mixed-unit warning; WGI breakdowns must.
  4. Facet cap — SMALL_MULTIPLES must not produce more than
     SMALL_MULTIPLES_MAX_FACETS panels.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data360.viz_config import (
    SMALL_MULTIPLES_MAX_FACETS,
    ChartStrategy,
    _format_breakdown_subtitle,
    _is_homogeneous_breakdown,
    dispatch_spec,
    select_strategy,
)
from data360.visualization import get_multi_indicator_viz_spec, get_viz_spec


# ============================================================================
# 1. Contract presence
# ============================================================================


class TestGrammarOfGraphicsContractPresence:
    """The grammar-of-graphics contract must be in both tool docstrings."""

    REQUIRED_PHRASES = [
        "Grammar of Graphics Contract",
        "disaggregation_filters decision rule",
        "OMIT it from disaggregation_filters",
        "Chart strategy",
        "Vega-Lite encoding",
        "_T",
        "_Z",
    ]

    def test_get_viz_spec_docstring_has_contract(self):
        doc = get_viz_spec.__doc__ or ""
        for phrase in self.REQUIRED_PHRASES:
            assert phrase in doc, (
                f"get_viz_spec docstring is missing required contract phrase: {phrase!r}\n"
                "The grammar-of-graphics contract must be present to guide the LLM."
            )

    def test_get_multi_indicator_viz_spec_docstring_has_contract(self):
        doc = get_multi_indicator_viz_spec.__doc__ or ""
        for phrase in self.REQUIRED_PHRASES:
            assert phrase in doc, (
                f"get_multi_indicator_viz_spec docstring is missing required contract "
                f"phrase: {phrase!r}\n"
                "The grammar-of-graphics contract must be present to guide the LLM."
            )

    def test_get_viz_spec_docstring_has_strategy_table(self):
        """The strategy-to-encoding table must enumerate all bypass strategies."""
        doc = get_viz_spec.__doc__ or ""
        required_strategies = [
            "TEMPORAL_SINGLE",
            "CROSS_SECTIONAL",
            "DISTRIBUTION",
            "BREAKDOWN_COMPARISON",
            "SMALL_MULTIPLES",
            "FALLBACK_LINE",
        ]
        for strategy in required_strategies:
            assert strategy in doc, (
                f"get_viz_spec strategy table is missing: {strategy!r}"
            )

    def test_get_viz_spec_docstring_has_encoding_type_rules(self):
        """Vega-Lite v5 encoding type rules must be documented."""
        doc = get_viz_spec.__doc__ or ""
        assert "ordinal" in doc, (
            "Docstring must warn against using 'ordinal' for year fields."
        )
        assert "temporal" in doc, (
            "Docstring must state year fields use type='temporal'."
        )

    def test_get_viz_spec_docstring_has_wrong_example(self):
        """A WRONG example for COMP_BREAKDOWN_1 must be present."""
        doc = get_viz_spec.__doc__ or ""
        assert "COMP_BREAKDOWN_1" in doc and "WRONG" in doc, (
            "Docstring must contain a WRONG example with COMP_BREAKDOWN_1 to "
            "explicitly show the LLM what not to do."
        )


# ============================================================================
# 2. Pipeline behavior: unfiltered multi-breakdown + multi-country
# ============================================================================


def _make_wgi_df(
    breakdowns: list[str],
    countries: list[str],
    years: list[int],
) -> pd.DataFrame:
    """Synthetic WGI-style DataFrame: multi-breakdown x multi-country x multi-year."""
    rows = []
    for country in countries:
        for bd in breakdowns:
            for yr in years:
                rows.append(
                    {
                        "year": pd.Timestamp(str(yr)),
                        "value": 0.5,
                        "country": country,
                        "comp_breakdown_1": bd,
                    }
                )
    return pd.DataFrame(rows)


WGI_BREAKDOWNS = ["WGI_EST", "WGI_SE", "WGI_SC", "WGI_SR", "WGI_SC_LB", "WGI_SC_UB"]
THREE_COUNTRIES = ["Ghana", "Kenya", "South Africa"]
YEARS_2010_2024 = list(range(2010, 2025))


class TestUnfilteredWGIPipelineBehavior:
    """Unfiltered WGI data (3 countries x 6 breakdowns x 15 years) must route
    to SMALL_MULTIPLES with facet=country and color=comp_breakdown_1.
    """

    def setup_method(self):
        self.df = _make_wgi_df(WGI_BREAKDOWNS, THREE_COUNTRIES, YEARS_2010_2024)

    def test_strategy_is_small_multiples(self):
        result = select_strategy(self.df, n_indicators=1)
        assert result.strategy == ChartStrategy.SMALL_MULTIPLES, (
            f"Expected SMALL_MULTIPLES for 3 countries x 6 breakdowns x 15 years, "
            f"got {result.strategy}."
        )

    def test_facet_dim_is_country(self):
        result = select_strategy(self.df, n_indicators=1)
        assert result.facet_dim == "country", (
            f"facet_dim should be 'country', got {result.facet_dim!r}."
        )

    def test_color_dim_is_comp_breakdown_1(self):
        result = select_strategy(self.df, n_indicators=1)
        assert result.color_dim == "comp_breakdown_1", (
            f"color_dim should be 'comp_breakdown_1', got {result.color_dim!r}."
        )

    def test_vega_lite_spec_has_facet_encoding(self):
        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)
        assert "facet" in spec, "SMALL_MULTIPLES spec must use top-level 'facet' key."

    def test_vega_lite_spec_facet_field_is_country(self):
        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)
        facet = spec.get("facet", {})
        assert facet.get("field") == "country"
        assert facet.get("type") == "nominal"

    def test_vega_lite_spec_inner_color_is_comp_breakdown_1(self):
        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)
        inner_enc = spec.get("spec", {}).get("encoding", {})
        color = inner_enc.get("color", {})
        assert color.get("field") == "comp_breakdown_1"
        assert color.get("type") == "nominal"

    def test_vega_lite_spec_x_axis_is_temporal(self):
        """Year axis must use type='temporal', not 'ordinal'."""
        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)
        inner_enc = spec.get("spec", {}).get("encoding", {})
        x = inner_enc.get("x", {})
        assert x.get("type") == "temporal", (
            f"x.type should be 'temporal', got {x.get('type')!r}."
        )


# ============================================================================
# 3. Pre-filter regression documentation
# ============================================================================


class TestPinningBreakdownCollapsesBehavior:
    """Documents what happens when the LLM incorrectly pins COMP_BREAKDOWN_1."""

    def test_filtered_to_single_breakdown_routes_to_temporal_single(self):
        df = _make_wgi_df(["WGI_EST"], THREE_COUNTRIES, YEARS_2010_2024)
        df_no_cb = df.drop(columns=["comp_breakdown_1"])
        result = select_strategy(df_no_cb, n_indicators=1)
        assert result.strategy == ChartStrategy.TEMPORAL_SINGLE
        assert result.color_dim == "country"

    def test_filtered_df_loses_breakdown_information(self):
        full_df = _make_wgi_df(WGI_BREAKDOWNS, THREE_COUNTRIES, YEARS_2010_2024)
        filtered_df = _make_wgi_df(["WGI_EST"], THREE_COUNTRIES, YEARS_2010_2024)
        full_series = len(WGI_BREAKDOWNS) * len(THREE_COUNTRIES)
        filtered_series = 1 * len(THREE_COUNTRIES)
        lost_pct = (1 - filtered_series / full_series) * 100
        assert lost_pct == pytest.approx(83.33, abs=0.01), (
            f"Expected ~83% series lost by pinning WGI_EST, got {lost_pct:.1f}%"
        )
        assert len(full_df) == full_series * len(YEARS_2010_2024)
        assert len(filtered_df) == filtered_series * len(YEARS_2010_2024)


# ============================================================================
# 4. Homogeneous breakdown detection
# ============================================================================


class TestHomogeneousBreakdownDetection:
    """IPC phases are ordinal categories of ONE metric.
    WGI breakdowns are structurally different metric types."""

    def test_ipc_phases_are_homogeneous(self):
        ipc = [
            "IPC_IPC_PHASE1", "IPC_IPC_PHASE2", "IPC_IPC_PHASE3",
            "IPC_IPC_PHASE4", "IPC_IPC_PHASE5",
        ]
        assert _is_homogeneous_breakdown(ipc) is True, (
            "IPC phases share base 'IPC_IPC_PHASE' — should be homogeneous."
        )

    def test_wgi_breakdowns_are_heterogeneous(self):
        wgi = ["WGI_EST", "WGI_SE", "WGI_SC", "WGI_SR", "WGI_SC_LB", "WGI_SC_UB"]
        assert _is_homogeneous_breakdown(wgi) is False, (
            "WGI breakdowns are structurally different metrics — heterogeneous."
        )

    def test_single_value_is_treated_as_homogeneous(self):
        assert _is_homogeneous_breakdown(["WGI_EST"]) is True

    def test_ipc_subtitle_has_no_mixed_unit_warning(self):
        """IPC phase subtitle: list series, no 'different units/scales' warning."""
        ipc_phases = ["IPC_IPC_PHASE1", "IPC_IPC_PHASE2", "IPC_IPC_PHASE3"]
        rows = [
            {"year": pd.Timestamp("2022"), "value": 10.0, "country": "Kenya",
             "comp_breakdown_2": p}
            for p in ipc_phases
        ]
        df = pd.DataFrame(rows)
        note = _format_breakdown_subtitle(df, "comp_breakdown_2")
        assert note is not None, "A note should still be returned for multi-value breakdowns."
        assert "different units" not in note, (
            "Homogeneous IPC phases must not show 'different units/scales' warning."
        )
        assert "Series:" in note, "Note must still list the series names."

    def test_wgi_subtitle_has_mixed_unit_warning(self):
        """WGI subtitle must include 'different units/scales' warning."""
        wgi_bds = ["WGI_EST", "WGI_SC", "WGI_SE", "WGI_SR"]
        rows = [
            {"year": pd.Timestamp("2022"), "value": 0.5, "country": "Kenya",
             "comp_breakdown_1": b}
            for b in wgi_bds
        ]
        df = pd.DataFrame(rows)
        note = _format_breakdown_subtitle(df, "comp_breakdown_1")
        assert note is not None
        assert "different units/scales" in note, (
            "WGI breakdowns must show the mixed-unit warning."
        )

    def test_standard_dim_returns_none(self):
        """Standard dims (country, sex) must never trigger a breakdown note."""
        rows = [{"year": pd.Timestamp("2022"), "value": 1.0, "country": c}
                for c in ["Kenya", "Ghana"]]
        df = pd.DataFrame(rows)
        assert _format_breakdown_subtitle(df, "country") is None
        assert _format_breakdown_subtitle(df, "sex") is None


# ============================================================================
# 5. SMALL_MULTIPLES facet cap
# ============================================================================


class TestSmallMultiplesFacetCap:
    """SMALL_MULTIPLES must cap at SMALL_MULTIPLES_MAX_FACETS panels.
    Chatbot UIs overflow vertically beyond this."""

    def _make_many_country_df(self, n_countries: int) -> pd.DataFrame:
        countries = [f"Country_{i:02d}" for i in range(n_countries)]
        # Two breakdown values ensures select_strategy routes to SMALL_MULTIPLES
        breakdowns = ["BD_A", "BD_B"]
        rows = []
        for c in countries:
            for bd in breakdowns:
                for yr in [2020, 2021, 2022]:
                    rows.append({
                        "year": pd.Timestamp(str(yr)),
                        "value": 1.0,
                        "country": c,
                        "comp_breakdown_1": bd,
                    })
        return pd.DataFrame(rows)

    def test_under_cap_produces_no_trim_note(self):
        """Fewer than MAX_FACETS countries: all panels, no trim note."""
        df = self._make_many_country_df(SMALL_MULTIPLES_MAX_FACETS)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, {"text": "T", "subtitle": "S"}, result)
        subtitle = spec.get("title", {}).get("subtitle", "")
        assert "Showing" not in subtitle, "No cap note should appear at or under MAX_FACETS."

    def test_over_cap_trims_to_max_facets(self):
        """More than MAX_FACETS countries: exactly MAX_FACETS shown."""
        n = SMALL_MULTIPLES_MAX_FACETS + 10
        df = self._make_many_country_df(n)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, {"text": "T", "subtitle": "S"}, result)
        shown = {r["country"] for r in spec["data"]["values"]}
        assert len(shown) == SMALL_MULTIPLES_MAX_FACETS, (
            f"Expected {SMALL_MULTIPLES_MAX_FACETS} panels, got {len(shown)}."
        )

    def test_over_cap_adds_showing_note_to_subtitle(self):
        """Subtitle must say 'Showing N of M' when panels are trimmed."""
        n = SMALL_MULTIPLES_MAX_FACETS + 10
        df = self._make_many_country_df(n)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, {"text": "T", "subtitle": "S"}, result)
        subtitle = spec.get("title", {}).get("subtitle", "")
        assert f"Showing {SMALL_MULTIPLES_MAX_FACETS} of {n}" in subtitle, (
            f"Expected 'Showing {SMALL_MULTIPLES_MAX_FACETS} of {n}' in subtitle, "
            f"got: {subtitle!r}"
        )

    def test_max_facets_constant_is_chatbot_safe(self):
        """SMALL_MULTIPLES_MAX_FACETS must be in the usable range [4, 12]."""
        assert 4 <= SMALL_MULTIPLES_MAX_FACETS <= 12, (
            f"SMALL_MULTIPLES_MAX_FACETS={SMALL_MULTIPLES_MAX_FACETS} is outside [4, 12]."
        )
