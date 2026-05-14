"""Tests for the Grammar of Graphics contract in visualization tool docstrings
and the corresponding pipeline behavior for multi-breakdown indicators.

Two concerns verified here:
  1. Contract presence — the docstring cannot be accidentally stripped without
     failing CI, preventing silent regression of the LLM guidance.
  2. Pipeline correctness — unfiltered WGI-style data (multi-country ×
     multi-breakdown × multi-year) must produce SMALL_MULTIPLES with the
     correct Vega-Lite facet/color encoding, NOT a single collapsed series.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data360.viz_config import ChartStrategy, select_strategy
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
        # Year type rule — prevents ordinal-on-year bug
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
    """Synthetic WGI-style DataFrame: multi-breakdown × multi-country × multi-year."""
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
    """Unfiltered WGI data (3 countries × 6 breakdowns × 15 years) must route
    to SMALL_MULTIPLES with facet=country and color=comp_breakdown_1.

    This is the correct grammar-of-graphics encoding: each country gets its own
    panel (facet) and each breakdown series gets its own color line within that
    panel. Pre-filtering to COMP_BREAKDOWN_1=WGI_EST would collapse all 6 series
    into one line and produce TEMPORAL_SINGLE with color=country instead.
    """

    def setup_method(self):
        self.df = _make_wgi_df(WGI_BREAKDOWNS, THREE_COUNTRIES, YEARS_2010_2024)

    def test_strategy_is_small_multiples(self):
        result = select_strategy(self.df, n_indicators=1)
        assert result.strategy == ChartStrategy.SMALL_MULTIPLES, (
            f"Expected SMALL_MULTIPLES for 3 countries × 6 breakdowns × 15 years, "
            f"got {result.strategy}. "
            "Pre-filtering (COMP_BREAKDOWN_1=WGI_EST) would suppress this and "
            "produce TEMPORAL_SINGLE with color=country — wrong for multi-breakdown data."
        )

    def test_facet_dim_is_country(self):
        result = select_strategy(self.df, n_indicators=1)
        assert result.facet_dim == "country", (
            f"facet_dim should be 'country', got {result.facet_dim!r}. "
            "Each country must get its own panel so breakdown lines are readable."
        )

    def test_color_dim_is_comp_breakdown_1(self):
        result = select_strategy(self.df, n_indicators=1)
        assert result.color_dim == "comp_breakdown_1", (
            f"color_dim should be 'comp_breakdown_1', got {result.color_dim!r}. "
            "Each breakdown series must be a distinct colored line within each panel."
        )

    def test_vega_lite_spec_has_facet_encoding(self):
        """The Vega-Lite spec must use the facet operator, not a flat mark spec."""
        from data360.viz_config import dispatch_spec

        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)

        assert "facet" in spec, (
            "SMALL_MULTIPLES spec must use top-level 'facet' key. "
            "A flat mark spec would overlay all series on one chart."
        )

    def test_vega_lite_spec_facet_field_is_country(self):
        from data360.viz_config import dispatch_spec

        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)

        facet = spec.get("facet", {})
        assert facet.get("field") == "country", (
            f"facet.field should be 'country', got {facet.get('field')!r}"
        )
        assert facet.get("type") == "nominal", (
            f"facet.type should be 'nominal', got {facet.get('type')!r}"
        )

    def test_vega_lite_spec_inner_color_is_comp_breakdown_1(self):
        from data360.viz_config import dispatch_spec

        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)

        inner_enc = spec.get("spec", {}).get("encoding", {})
        color = inner_enc.get("color", {})
        assert color.get("field") == "comp_breakdown_1", (
            f"Inner color.field should be 'comp_breakdown_1', got {color.get('field')!r}. "
            "Each breakdown must map to a distinct color channel."
        )
        assert color.get("type") == "nominal", (
            f"color.type should be 'nominal', got {color.get('type')!r}"
        )

    def test_vega_lite_spec_x_axis_is_temporal(self):
        """Year axis must use type='temporal', not 'ordinal'.

        Using 'ordinal' causes Vega-Lite to render ISO timestamp strings as raw
        millisecond integers on the axis, which is unreadable.
        """
        from data360.viz_config import dispatch_spec

        result = select_strategy(self.df, n_indicators=1)
        spec = dispatch_spec(result.strategy, self.df, "Test Title", result)

        inner_enc = spec.get("spec", {}).get("encoding", {})
        x = inner_enc.get("x", {})
        assert x.get("type") == "temporal", (
            f"x.type should be 'temporal', got {x.get('type')!r}. "
            "Ordinal encoding converts ISO timestamps to raw millisecond integers."
        )


# ============================================================================
# 3. Pre-filter regression: confirm that filtering collapses to the wrong strategy
# ============================================================================


class TestPinningBreakdownCollapsesBehavior:
    """Verify that the bug scenario (pre-filtering to WGI_EST) does route to
    TEMPORAL_SINGLE with color=country — which is readable for 3 countries but
    discards the 5 other breakdown series without warning.

    These tests document the expected behavior of the WRONG pattern so it is
    clear in CI what information is being lost when a filter is pinned.
    """

    def test_filtered_to_single_breakdown_routes_to_temporal_single(self):
        """After pinning COMP_BREAKDOWN_1=WGI_EST, only 1 breakdown remains.
        The strategy degrades to TEMPORAL_SINGLE (no breakdown variation detected).
        """
        df = _make_wgi_df(["WGI_EST"], THREE_COUNTRIES, YEARS_2010_2024)
        # comp_breakdown_1 has only 1 unique value — treated as trivial, dropped
        # by _clean_single_df. Strategy sees: 3 countries × 15 years, no breakdown.
        # But in the strategy df the column would have been dropped already.
        # Simulate a df without comp_breakdown_1 (as _clean_single_df would produce):
        df_no_cb = df.drop(columns=["comp_breakdown_1"])

        result = select_strategy(df_no_cb, n_indicators=1)

        assert result.strategy == ChartStrategy.TEMPORAL_SINGLE, (
            f"After filtering to single breakdown, expected TEMPORAL_SINGLE, "
            f"got {result.strategy}"
        )
        assert result.color_dim == "country", (
            "With no breakdown dimension, color must fall back to country."
        )

    def test_filtered_df_loses_breakdown_information(self):
        """Quantify the information loss: 5 out of 6 breakdown series are invisible."""
        full_df = _make_wgi_df(WGI_BREAKDOWNS, THREE_COUNTRIES, YEARS_2010_2024)
        filtered_df = _make_wgi_df(["WGI_EST"], THREE_COUNTRIES, YEARS_2010_2024)

        full_series = len(WGI_BREAKDOWNS) * len(THREE_COUNTRIES)  # 18 series
        filtered_series = 1 * len(THREE_COUNTRIES)  # 3 series

        assert len(full_df) == full_series * len(YEARS_2010_2024)
        assert len(filtered_df) == filtered_series * len(YEARS_2010_2024)

        lost_pct = (1 - filtered_series / full_series) * 100
        assert lost_pct == pytest.approx(83.33, abs=0.01), (
            f"Expected ~83% of series to be lost by pinning WGI_EST, got {lost_pct:.1f}%"
        )
