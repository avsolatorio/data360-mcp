"""Tests for the Grammar of Graphics contract in visualization tool docstrings
and the corresponding pipeline behavior for multi-breakdown indicators.

Concerns verified here:
  1. Contract presence — the docstring cannot be accidentally stripped without
     failing CI, preventing silent regression of the LLM guidance.
  2. Pipeline correctness — unfiltered WGI-style data (multi-country x
     multi-breakdown x multi-year) must produce SMALL_MULTIPLES with the
     correct Vega-Lite facet/color encoding, NOT a single collapsed series.
  3. Scale-incompatibility detection — IPC phases (same magnitude) must NOT
     trigger the mixed-unit warning; WGI breakdowns (different magnitudes) must.
  4. Facet cap — SMALL_MULTIPLES must not produce more than
     SMALL_MULTIPLES_MAX_FACETS panels.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data360.visualization import get_multi_indicator_viz_spec, get_viz_spec
from data360.viz_config import (
    SMALL_MULTIPLES_MAX_FACETS,
    ChartStrategy,
    _append_trim_note,
    _format_breakdown_subtitle,
    dispatch_spec,
    select_strategy,
)

# ============================================================================
# 1. Contract presence
# ============================================================================


class TestGrammarOfGraphicsContractPresence:
    """The grammar-of-graphics contract must be in both tool docstrings."""

    REQUIRED_PHRASES = [
        "Grammar of Graphics Contract",
        "disaggregation_filters decision rule",
        "OMIT",
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
            "HEATMAP",
            "STACKED_AREA",
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

    def test_vega_lite_spec_has_vconcat_encoding(self):
        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)
        assert "vconcat" in spec, "SMALL_MULTIPLES spec must use top-level 'vconcat' key."

    def test_vega_lite_spec_vconcat_filters_by_country(self):
        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)
        vconcat = spec.get("vconcat", [])
        assert len(vconcat) > 0
        panel = vconcat[0]
        # vconcat panels use transform filters instead of facet
        transform = panel.get("transform", [])
        assert any("country" in str(t) for t in transform), "Panel must filter by country"

    def test_vega_lite_spec_inner_color_is_comp_breakdown_1(self):
        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)
        panel = spec.get("vconcat", [])[0]
        inner_enc = panel.get("encoding", {})
        color = inner_enc.get("color", {})
        assert color.get("field") == "comp_breakdown_1"
        assert color.get("type") == "nominal"

    def test_vega_lite_spec_x_axis_is_temporal(self):
        """Year axis must use type='temporal', not 'ordinal'."""
        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)
        panel = spec.get("vconcat", [])[0]
        inner_enc = panel.get("encoding", {})
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


class TestScaleIncompatibilityDetection:
    """IPC phases share the same magnitude and must NOT trigger the mixed-unit
    warning. WGI breakdowns span different magnitudes and must trigger it."""

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
        """WGI subtitle must include 'different units/scales' warning.

        Uses realistic values: governance estimates (WGI_EST/SE/SR ≈ ±0.6)
        vs percentile score (WGI_SC ≈ 65). The ~100× magnitude gap triggers
        _detect_scale_incompatibility (log10 spread ≈ 2.0 > threshold 1.5).
        """
        wgi_values = {
            "WGI_EST": 0.6,   # governance estimate ≈ ±2.5 range
            "WGI_SC": 65.0,   # percentile score ≈ 0–100 range
            "WGI_SE": 0.5,    # standard error
            "WGI_SR": 0.7,    # strength of rule of law
        }
        rows = [
            {"year": pd.Timestamp("2022"), "value": val, "country": "Kenya",
             "comp_breakdown_1": bd}
            for bd, val in wgi_values.items()
        ]
        df = pd.DataFrame(rows)
        note = _format_breakdown_subtitle(df, "comp_breakdown_1")
        assert note is not None
        assert "different units/scales" in note, (
            "WGI breakdowns must show the mixed-unit warning — "
            "governance estimate (≈0.6) and percentile score (≈65) differ by ~100×."
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
        """Subtitle must contain 'Showing N of M' when panels are trimmed."""
        n = SMALL_MULTIPLES_MAX_FACETS + 10
        df = self._make_many_country_df(n)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, {"text": "T", "subtitle": "S"}, result)
        raw_sub = spec.get("title", {}).get("subtitle", "")
        # subtitle may be a list (new multi-line form) or a plain string.
        subtitle = " ".join(raw_sub) if isinstance(raw_sub, list) else raw_sub
        assert f"Showing {SMALL_MULTIPLES_MAX_FACETS} of {n}" in subtitle, (
            f"Expected 'Showing {SMALL_MULTIPLES_MAX_FACETS} of {n}' in subtitle, "
            f"got: {subtitle!r}"
        )

    def test_max_facets_constant_is_chatbot_safe(self):
        """SMALL_MULTIPLES_MAX_FACETS must be in the usable range [4, 12]."""
        assert 4 <= SMALL_MULTIPLES_MAX_FACETS <= 12, (
            f"SMALL_MULTIPLES_MAX_FACETS={SMALL_MULTIPLES_MAX_FACETS} is outside [4, 12]."
        )

# ============================================================================
# 6. Legend title — _color_encoding resolves _TOOLTIP_SPECS labels
# ============================================================================


class TestColorEncodingLegendTitle:
    """_color_encoding must use human-readable labels from _TOOLTIP_SPECS.

    Previously the legend title was missing entirely, so Vega-Lite rendered the
    raw column name (e.g. 'comp_breakdown_2') as the legend header.
    """

    def test_comp_breakdown_2_legend_title_is_sub_breakdown(self):
        from data360.viz_config import _color_encoding
        enc = _color_encoding("comp_breakdown_2", mark_type="line", n_items=3)
        legend = enc.get("legend", {})
        assert legend is not None, "Legend should be present for n_items > 1."
        # Default is the neutral "Dimension 2" fallback (no API-sourced override).
        assert legend.get("title") == "Dimension 2", (
            f"Legend title for comp_breakdown_2 should be 'Dimension 2' (fallback), "
            f"got {legend.get('title')!r}."
        )

    def test_comp_breakdown_1_legend_title_is_breakdown(self):
        from data360.viz_config import _color_encoding
        enc = _color_encoding("comp_breakdown_1", mark_type="line", n_items=6)
        legend = enc.get("legend", {})
        # Default is the neutral "Dimension 1" fallback (no API-sourced override).
        assert legend.get("title") == "Dimension 1", (
            f"Legend title for comp_breakdown_1 should be 'Dimension 1' (fallback), "
            f"got {legend.get('title')!r}."
        )

    def test_country_legend_title_is_country(self):
        from data360.viz_config import _color_encoding
        enc = _color_encoding("country", mark_type="line", n_items=3)
        legend = enc.get("legend", {})
        assert legend.get("title") == "Country"

    def test_caller_supplied_title_takes_priority(self):
        from data360.viz_config import _color_encoding
        enc = _color_encoding("comp_breakdown_2", mark_type="line", n_items=3,
                               legend_title="Food Security Phase")
        assert enc["legend"]["title"] == "Food Security Phase"

    def test_unknown_field_falls_back_to_title_case(self):
        from data360.viz_config import _color_encoding
        enc = _color_encoding("some_custom_dim", mark_type="line", n_items=3)
        assert enc["legend"]["title"] == "Some Custom Dim"

    def test_small_multiples_spec_legend_not_raw_column_name(self):
        """End-to-end: SMALL_MULTIPLES spec must not expose raw column names in legend."""
        breakdowns = ["IPC_IPC_PHASE1", "IPC_IPC_PHASE2", "IPC_IPC_PHASE3"]
        countries = ["Kenya", "Ghana", "Nigeria"]
        rows = []
        for c in countries:
            for bd in breakdowns:
                for yr in [2021, 2022, 2023]:
                    rows.append({"year": pd.Timestamp(str(yr)), "value": 10.0,
                                 "country": c, "comp_breakdown_2": bd})
        df = pd.DataFrame(rows)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, "Test", result)

        # Legend is rendered in the first panel of the vconcat list
        panels = spec.get("vconcat", [])
        first_panel = panels[0] if panels else {}
        inner_color = first_panel.get("encoding", {}).get("color", {})
        legend = inner_color.get("legend", {})
        title = legend.get("title", "") if legend else ""
        assert title not in ("comp_breakdown_2", "comp_breakdown_1", ""), (
            f"Legend title must not be a raw column name. Got: {title!r}."
        )


# ============================================================================
# 7. Subtitle rebuild — shown countries only after SMALL_MULTIPLES cap
# ============================================================================


class TestSmallMultiplesSubtitleRebuild:
    """After capping, the subtitle country list must only name the shown countries."""

    def _make_many_country_df(self, n_countries: int) -> pd.DataFrame:
        countries = [f"Country_{i:02d}" for i in range(n_countries)]
        breakdowns = ["BD_A", "BD_B"]
        rows = []
        for c in countries:
            for bd in breakdowns:
                for yr in [2021, 2022, 2023]:
                    rows.append({"year": pd.Timestamp(str(yr)), "value": 1.0,
                                 "country": c, "comp_breakdown_1": bd})
        return pd.DataFrame(rows)

    def test_subtitle_only_lists_shown_countries(self):
        n = SMALL_MULTIPLES_MAX_FACETS + 10
        df = self._make_many_country_df(n)
        result = select_strategy(df, n_indicators=1)

        from data360.viz_config import build_chart_title_with_context
        pre_built = build_chart_title_with_context("Test", None, df)
        spec = dispatch_spec(result.strategy, df, pre_built, result)
        subtitle = spec.get("title", {}).get("subtitle", "")

        shown = {r["country"] for r in spec["data"]["values"]}
        assert len(shown) == SMALL_MULTIPLES_MAX_FACETS

        trimmed = {f"Country_{i:02d}" for i in range(n)} - shown
        for c in trimmed:
            assert c not in subtitle, (
                f"Trimmed country '{c}' must not appear in subtitle. Got: {subtitle!r}"
            )

    def test_subtitle_does_not_say_plus_more_after_cap(self):
        n = SMALL_MULTIPLES_MAX_FACETS + 10
        df = self._make_many_country_df(n)
        result = select_strategy(df, n_indicators=1)

        from data360.viz_config import build_chart_title_with_context
        pre_built = build_chart_title_with_context("Test", None, df)
        spec = dispatch_spec(result.strategy, df, pre_built, result)
        raw_sub = spec.get("title", {}).get("subtitle", "")
        subtitle = " ".join(raw_sub) if isinstance(raw_sub, list) else raw_sub
        assert "(+" not in subtitle, (
            f"After cap, '(+N more)' must not appear. Got: {subtitle!r}"
        )

    def test_no_subtitle_change_under_cap(self):
        n = SMALL_MULTIPLES_MAX_FACETS
        df = self._make_many_country_df(n)
        result = select_strategy(df, n_indicators=1)

        from data360.viz_config import build_chart_title_with_context
        pre_built = build_chart_title_with_context("Test", None, df)
        spec = dispatch_spec(result.strategy, df, pre_built, result)
        subtitle = spec.get("title", {}).get("subtitle", "")
        assert "Showing" not in subtitle, (
            f"No 'Showing N of M' note expected at or under cap. Got: {subtitle!r}"
        )

    def test_non_country_facet_keeps_geography_subtitle(self):
        rows = []
        for bd1 in [f"BD{i:02d}" for i in range(SMALL_MULTIPLES_MAX_FACETS + 5)]:
            for bd2 in ["A", "B"]:
                for yr in [2021, 2022, 2023]:
                    rows.append(
                        {
                            "year": pd.Timestamp(str(yr)),
                            "value": 1.0,
                            "country": "Kenya",
                            "comp_breakdown_1": bd1,
                            "comp_breakdown_2": bd2,
                        }
                    )
        df = pd.DataFrame(rows)
        result = select_strategy(df, n_indicators=1)
        assert result.facet_dim == "comp_breakdown_1"

        from data360.viz_config import build_chart_title_with_context

        pre_built = build_chart_title_with_context("Test", None, df)
        spec = dispatch_spec(result.strategy, df, pre_built, result)
        raw_sub = spec.get("title", {}).get("subtitle", "")
        subtitle = " ".join(raw_sub) if isinstance(raw_sub, list) else raw_sub
        assert "Kenya" in subtitle


# ============================================================================
# 7. New strategy docstring coverage: HEATMAP and STACKED_AREA
# ============================================================================


class TestNewStrategiesInDocstring:
    """HEATMAP and STACKED_AREA must be documented in both tool docstrings."""

    def test_get_viz_spec_strategy_table_has_heatmap(self):
        doc = get_viz_spec.__doc__ or ""
        assert "HEATMAP" in doc, (
            "get_viz_spec strategy table is missing HEATMAP. "
            "The LLM must know this strategy fires for >8 countries + multi-year + 0 breakdowns."
        )

    def test_get_viz_spec_strategy_table_has_stacked_area(self):
        doc = get_viz_spec.__doc__ or ""
        assert "STACKED_AREA" in doc, (
            "get_viz_spec strategy table is missing STACKED_AREA. "
            "The LLM must know this strategy is triggered by chart_type='area'/'stacked_area'."
        )

    def test_get_multi_indicator_strategy_table_has_stacked_area(self):
        doc = get_multi_indicator_viz_spec.__doc__ or ""
        assert "STACKED_AREA" in doc, (
            "get_multi_indicator_viz_spec strategy table is missing STACKED_AREA."
        )

    def test_get_viz_spec_has_high_cardinality_guidance(self):
        doc = get_viz_spec.__doc__ or ""
        assert "High-cardinality" in doc, (
            "get_viz_spec docstring is missing the high-cardinality guidance block."
        )
        assert "DO NOT reduce country_code" in doc, (
            "get_viz_spec docstring must explicitly forbid reducing country_code "
            "to simplify charts. The LLM must pass the full country list."
        )

    def test_get_multi_indicator_has_high_cardinality_guidance(self):
        doc = get_multi_indicator_viz_spec.__doc__ or ""
        assert "High-cardinality" in doc, (
            "get_multi_indicator_viz_spec docstring is missing the high-cardinality guidance block."
        )
        assert "DO NOT reduce indicator_ids" in doc, (
            "get_multi_indicator_viz_spec docstring must explicitly forbid reducing indicator_ids."
        )

    def test_get_viz_spec_has_visual_channel_hierarchy(self):
        doc = get_viz_spec.__doc__ or ""
        assert "Visual channel hierarchy" in doc, (
            "get_viz_spec docstring is missing the visual channel hierarchy section."
        )
        assert "Position" in doc and "Color (hue)" in doc, (
            "Visual channel hierarchy must list Position and Color (hue) as channels."
        )

    def test_get_multi_indicator_has_visual_channel_hierarchy(self):
        doc = get_multi_indicator_viz_spec.__doc__ or ""
        assert "Visual channel hierarchy" in doc, (
            "get_multi_indicator_viz_spec docstring is missing the visual channel hierarchy section."
        )

    def test_heatmap_color_palette_documented(self):
        """Sequential/divergent palette selection must be documented."""
        doc = get_viz_spec.__doc__ or ""
        assert "yellowgreenblue" in doc, (
            "Heatmap sequential palette (yellowgreenblue) must be documented."
        )
        assert "redblue" in doc, (
            "Heatmap divergent palette (redblue) must be documented for negative-value data."
        )


# ============================================================================
# 8. HEATMAP strategy routing and spec builder
# ============================================================================


def _make_many_country_multiyr_df(n_countries: int, n_years: int = 3) -> pd.DataFrame:
    """n_countries x n_years, no breakdown — triggers HEATMAP when n_countries > 8."""
    rows = []
    for i in range(n_countries):
        for yr in range(2020, 2020 + n_years):
            rows.append(
                {
                    "country": f"C{i:02d}",
                    "year": pd.Timestamp(str(yr)),
                    "value": float(i * 10 + yr - 2020),
                }
            )
    return pd.DataFrame(rows)


class TestHeatmapStrategyRouting:
    """HEATMAP is selected for >8 countries + multi-year + 0 breakdowns."""

    def test_routes_to_heatmap_above_threshold(self):
        df = _make_many_country_multiyr_df(n_countries=10)
        result = select_strategy(df, n_indicators=1)
        assert result.strategy == ChartStrategy.HEATMAP, (
            f"Expected HEATMAP for 10 countries x multi-year, got {result.strategy}."
        )

    def test_does_not_route_to_heatmap_below_threshold(self):
        df = _make_many_country_multiyr_df(n_countries=5)
        result = select_strategy(df, n_indicators=1)
        assert result.strategy != ChartStrategy.HEATMAP, (
            f"5 countries should NOT trigger HEATMAP, got {result.strategy}."
        )

    def test_does_not_route_to_heatmap_with_breakdown(self):
        """Presence of a meaningful breakdown (>1 unique value) must route to SMALL_MULTIPLES."""
        rows = []
        for i in range(10):
            for yr in [2020, 2021]:
                for bd in ["A", "B"]:  # 2 unique values → n_breakdowns = 1
                    rows.append(
                        {
                            "country": f"C{i:02d}",
                            "year": pd.Timestamp(str(yr)),
                            "comp_breakdown_1": bd,
                            "value": 1.0,
                        }
                    )
        df = pd.DataFrame(rows)
        result = select_strategy(df, n_indicators=1)
        assert result.strategy == ChartStrategy.SMALL_MULTIPLES, (
            f"With a breakdown (2+ unique values), 10-country multi-year data must route to "
            f"SMALL_MULTIPLES, got {result.strategy}."
        )

    def test_heatmap_color_dim_is_value(self):
        df = _make_many_country_multiyr_df(n_countries=10)
        result = select_strategy(df, n_indicators=1)
        assert result.color_dim == "value", (
            f"HEATMAP color_dim must be 'value' (the quantity to encode as cell color), "
            f"got {result.color_dim!r}."
        )

    def test_heatmap_spec_mark_is_rect(self):
        df = _make_many_country_multiyr_df(n_countries=10)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, "Test Heatmap", result)
        mark = spec.get("mark", {})
        mark_type = mark.get("type") if isinstance(mark, dict) else mark
        assert mark_type == "rect", (
            f"HEATMAP spec must use mark type 'rect', got {mark_type!r}."
        )

    def test_heatmap_spec_has_tooltip(self):
        df = _make_many_country_multiyr_df(n_countries=10)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, "Test Heatmap", result)
        enc = spec.get("encoding", {})
        assert "tooltip" in enc, "HEATMAP spec must have tooltip encoding."

    def test_heatmap_caps_at_50_countries(self):
        df = _make_many_country_multiyr_df(n_countries=60)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, "Test Heatmap", result)
        shown = {r["country"] for r in spec["data"]["values"]}
        assert len(shown) <= 50, (
            f"HEATMAP must cap at 50 countries, got {len(shown)}."
        )

    def test_heatmap_x_axis_is_temporal(self):
        df = _make_many_country_multiyr_df(n_countries=10)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, "Test Heatmap", result)
        x = spec.get("encoding", {}).get("x", {})
        assert x.get("type") == "temporal", (
            f"HEATMAP x-axis must be type='temporal', got {x.get('type')!r}."
        )

    def test_heatmap_y_axis_is_country_nominal(self):
        df = _make_many_country_multiyr_df(n_countries=10)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, "Test Heatmap", result)
        y = spec.get("encoding", {}).get("y", {})
        assert y.get("field") == "country", (
            f"HEATMAP y-axis must encode 'country', got {y.get('field')!r}."
        )
        assert y.get("type") == "nominal", (
            f"HEATMAP y-axis must be type='nominal', got {y.get('type')!r}."
        )

    def test_heatmap_color_encodes_value(self):
        df = _make_many_country_multiyr_df(n_countries=10)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, "Test Heatmap", result)
        color = spec.get("encoding", {}).get("color", {})
        assert color.get("field") == "value", (
            f"HEATMAP color must encode 'value', got {color.get('field')!r}."
        )
        assert color.get("type") == "quantitative", (
            f"HEATMAP color must be type='quantitative', got {color.get('type')!r}."
        )

    def test_heatmap_uses_sequential_palette_for_positive_data(self):
        df = _make_many_country_multiyr_df(n_countries=10)  # all values >= 0
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, "Test Heatmap", result)
        color = spec.get("encoding", {}).get("color", {})
        scheme = color.get("scale", {}).get("scheme")
        assert scheme == "yellowgreenblue", (
            f"Positive-only data must use sequential palette 'yellowgreenblue', got {scheme!r}."
        )

    def test_heatmap_uses_divergent_palette_for_negative_data(self):
        rows = []
        for i in range(10):
            for yr in [2020, 2021]:
                rows.append(
                    {
                        "country": f"C{i:02d}",
                        "year": pd.Timestamp(str(yr)),
                        "value": float(i - 5),  # includes negatives
                    }
                )
        df = pd.DataFrame(rows)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, "Test Heatmap", result)
        color = spec.get("encoding", {}).get("color", {})
        scheme = color.get("scale", {}).get("scheme")
        assert scheme == "redblue", (
            f"Mixed-sign data must use divergent palette 'redblue', got {scheme!r}."
        )

    def test_heatmap_has_wb_config(self):
        df = _make_many_country_multiyr_df(n_countries=10)
        result = select_strategy(df, n_indicators=1)
        spec = dispatch_spec(result.strategy, df, "Test Heatmap", result)
        assert "config" in spec, "HEATMAP spec must have WB config injected."


# ============================================================================
# 9. STACKED_AREA strategy routing and spec builder
# ============================================================================


def _make_stacked_area_df(
    n_series: int = 3, n_years: int = 5, country: str = "Kenya"
) -> pd.DataFrame:
    rows = []
    for s in range(n_series):
        for yr in range(2020, 2020 + n_years):
            rows.append(
                {
                    "country": country,
                    "year": pd.Timestamp(str(yr)),
                    "comp_breakdown_1": f"Series_{s}",
                    "value": float(10 + s * 5),
                }
            )
    return pd.DataFrame(rows)


class TestStackedAreaStrategyRouting:
    """STACKED_AREA is selected only when chart_type hint is 'area'/'stacked_area'."""

    def test_routes_to_stacked_area_with_area_hint(self):
        df = _make_stacked_area_df()
        result = select_strategy(df, n_indicators=1, chart_type_hint="area")
        assert result.strategy == ChartStrategy.STACKED_AREA, (
            f"chart_type='area' must route to STACKED_AREA, got {result.strategy}."
        )

    def test_routes_to_stacked_area_with_stacked_area_hint(self):
        df = _make_stacked_area_df()
        result = select_strategy(df, n_indicators=1, chart_type_hint="stacked_area")
        assert result.strategy == ChartStrategy.STACKED_AREA, (
            f"chart_type='stacked_area' must route to STACKED_AREA, got {result.strategy}."
        )

    def test_does_not_route_to_stacked_area_without_hint(self):
        """Without an explicit hint, a trend question must NOT produce a stacked area."""
        df = _make_stacked_area_df()
        result = select_strategy(df, n_indicators=1)
        assert result.strategy != ChartStrategy.STACKED_AREA, (
            "Without chart_type hint, data must NOT route to STACKED_AREA. "
            f"Got {result.strategy}. Trend questions must use line/small_multiples."
        )

    def test_stacked_area_color_dim_is_breakdown(self):
        df = _make_stacked_area_df()
        result = select_strategy(df, n_indicators=1, chart_type_hint="area")
        assert result.color_dim == "comp_breakdown_1", (
            f"STACKED_AREA color_dim must be 'comp_breakdown_1', got {result.color_dim!r}."
        )

    def test_stacked_area_color_dim_is_country_when_no_breakdown(self):
        rows = [
            {"country": c, "year": pd.Timestamp(str(yr)), "value": 10.0}
            for c in ["Kenya", "Ghana", "Nigeria"]
            for yr in [2020, 2021, 2022]
        ]
        df = pd.DataFrame(rows)
        result = select_strategy(df, n_indicators=1, chart_type_hint="area")
        assert result.color_dim == "country", (
            f"Without breakdown, STACKED_AREA color_dim must be 'country', got {result.color_dim!r}."
        )

    def test_stacked_area_spec_mark_is_area(self):
        df = _make_stacked_area_df()
        result = select_strategy(df, n_indicators=1, chart_type_hint="area")
        spec = dispatch_spec(result.strategy, df, "Stacked Area Test", result)
        mark = spec.get("mark", {})
        mark_type = mark.get("type") if isinstance(mark, dict) else mark
        assert mark_type == "area", (
            f"STACKED_AREA spec must use mark type 'area', got {mark_type!r}."
        )

    def test_stacked_area_y_has_stack_zero(self):
        df = _make_stacked_area_df()
        result = select_strategy(df, n_indicators=1, chart_type_hint="area")
        spec = dispatch_spec(result.strategy, df, "Stacked Area Test", result)
        y = spec.get("encoding", {}).get("y", {})
        assert y.get("stack") == "zero", (
            f"STACKED_AREA y-encoding must have stack='zero', got {y.get('stack')!r}."
        )

    def test_stacked_area_x_axis_is_temporal(self):
        df = _make_stacked_area_df()
        result = select_strategy(df, n_indicators=1, chart_type_hint="area")
        spec = dispatch_spec(result.strategy, df, "Stacked Area Test", result)
        x = spec.get("encoding", {}).get("x", {})
        assert x.get("type") == "temporal", (
            f"STACKED_AREA x-axis must be type='temporal', got {x.get('type')!r}."
        )

    def test_stacked_area_falls_back_to_line_for_negative_data(self):
        """Stacked area cannot represent negative values — must fall back to line."""
        rows = [
            {
                "country": "Kenya",
                "year": pd.Timestamp(str(yr)),
                "comp_breakdown_1": f"Series_{s}",
                "value": float(s - 2),  # Series_0 = -2 (negative)
            }
            for s in range(3)
            for yr in [2020, 2021, 2022]
        ]
        df = pd.DataFrame(rows)
        result = select_strategy(df, n_indicators=1, chart_type_hint="area")
        spec = dispatch_spec(result.strategy, df, "Negative Test", result)
        # The builder should fall back to temporal_single (line) mark
        mark = spec.get("mark", {})
        mark_type = mark.get("type") if isinstance(mark, dict) else mark
        assert mark_type == "line", (
            f"STACKED_AREA must fall back to 'line' mark for negative data, got {mark_type!r}."
        )

    def test_stacked_area_has_tooltip(self):
        df = _make_stacked_area_df()
        result = select_strategy(df, n_indicators=1, chart_type_hint="area")
        spec = dispatch_spec(result.strategy, df, "Stacked Area Test", result)
        enc = spec.get("encoding", {})
        assert "tooltip" in enc, "STACKED_AREA spec must have tooltip encoding."

    def test_stacked_area_has_wb_config(self):
        df = _make_stacked_area_df()
        result = select_strategy(df, n_indicators=1, chart_type_hint="area")
        spec = dispatch_spec(result.strategy, df, "Stacked Area Test", result)
        assert "config" in spec, "STACKED_AREA spec must have WB config injected."

    def test_stacked_area_caps_series_at_line_max(self):
        """More than line_max_series color series must be capped."""
        from data360.viz_config import HIGH_CARDINALITY_THRESHOLDS

        cap = HIGH_CARDINALITY_THRESHOLDS["line_max_series"]
        df = _make_stacked_area_df(n_series=cap + 5)
        result = select_strategy(df, n_indicators=1, chart_type_hint="area")
        spec = dispatch_spec(result.strategy, df, "Cap Test", result)
        color_dim = result.color_dim or "comp_breakdown_1"
        shown = {r[color_dim] for r in spec["data"]["values"]}
        assert len(shown) <= cap, (
            f"STACKED_AREA must cap at {cap} series, got {len(shown)}."
        )


class TestTrimNotePluralization:
    def test_append_trim_note_pluralizes_custom_dimensions(self):
        title = {"text": "Test", "subtitle": ["Kenya, 2021-2023"]}
        out = _append_trim_note(title, "comp_breakdown_1", shown=8, original=14)
        raw_sub = out.get("subtitle", "")
        subtitle = " ".join(raw_sub) if isinstance(raw_sub, list) else raw_sub
        assert "breakdowns" in subtitle
        assert "comp_breakdown_1s" not in subtitle
