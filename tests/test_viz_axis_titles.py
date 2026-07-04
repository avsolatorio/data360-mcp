"""Phase 3 — Axis Title Completeness Tests.

The value axis (y on temporal/stacked-area/breakdown, x on cross-sectional,
color legend on heatmap/choropleth) must never show a blank title or the
generic placeholder "Value".

Contract:
  - When unit_label is meaningful (e.g. "Constant 2015 US$", "%"): title = unit_label
  - When unit_label is absent/generic and indicator_name is known: title = indicator_name
  - When both are absent: title = "Value"  (last resort, unchanged from current)
  - The generic string "Value" must NOT appear as an axis title when indicator_name is available.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data360.viz_config import (
    ChartStrategy,
    StrategyResult,
    _resolve_axis_title,
    build_choropleth_spec,
    build_cross_sectional_spec,
    build_distribution_spec,
    build_heatmap_spec,
    build_stacked_area_spec,
    build_temporal_single_spec,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _temporal_df(countries, years, value=50.0):
    return pd.DataFrame(
        [{"country": c, "year": str(y), "value": value} for c in countries for y in years]
    )


def _default_result(strategy=ChartStrategy.TEMPORAL_SINGLE, color_dim="country"):
    return StrategyResult(strategy=strategy, reason="test", color_dim=color_dim)


# ---------------------------------------------------------------------------
# Unit tests for _resolve_axis_title helper
# ---------------------------------------------------------------------------


class TestResolveAxisTitle:
    """Unit tests for the _resolve_axis_title() helper function."""

    def test_unit_label_takes_precedence(self):
        """When a real unit label is available it should always be used."""
        assert _resolve_axis_title("Constant 2015 US$", "GDP per Capita") == "Constant 2015 US$"

    def test_percent_unit_takes_precedence(self):
        assert _resolve_axis_title("%", "GDP Growth") == "%"

    def test_generic_value_falls_back_to_indicator_name(self):
        """'Value' is a placeholder — fall back to indicator_name."""
        assert _resolve_axis_title("Value", "Total Population") == "Total Population"

    def test_empty_unit_falls_back_to_indicator_name(self):
        assert _resolve_axis_title("", "Gini Index") == "Gini Index"

    def test_none_unit_falls_back_to_indicator_name(self):
        assert _resolve_axis_title(None, "CO2 Emissions") == "CO2 Emissions"

    def test_both_absent_returns_none(self):
        """Last resort: when nothing is known, return None (no axis title, not 'Value')."""
        assert _resolve_axis_title("Value", None) is None

    def test_empty_unit_and_no_name_returns_none(self):
        assert _resolve_axis_title("", None) is None

    def test_unit_label_none_and_no_name_returns_none(self):
        assert _resolve_axis_title(None, None) is None

    def test_indicator_name_trimmed(self):
        """Long indicator names should be used as-is (truncation is a UI concern)."""
        long_name = "GDP per Capita, PPP (constant 2017 international $)"
        assert _resolve_axis_title("", long_name) == long_name


# ---------------------------------------------------------------------------
# Integration: axis title never blank when indicator_name is known
# ---------------------------------------------------------------------------


class TestAxisTitleNeverBlankWithIndicatorName:
    """Axis titles must be a non-empty string whenever indicator_name is supplied."""

    def test_temporal_single_y_title_uses_indicator_name_when_no_unit(self):
        """When y_label='Value' (no unit mapping), y-axis title = indicator_name."""
        df = _temporal_df(["USA", "Germany"], [2018, 2019, 2020, 2021, 2022])
        result = _default_result(ChartStrategy.TEMPORAL_SINGLE)
        spec = build_temporal_single_spec(
            df, "Test", result,
            y_label="Value",           # ← no unit mapping
            indicator_name="Total Population",
        )

        y_title = spec.get("encoding", {}).get("y", {}).get("axis", {}).get("title")
        assert y_title is not None, (
            "temporal_single: y-axis title must not be None when indicator_name is known"
        )
        assert y_title != "Value", (
            "temporal_single: generic 'Value' must not be used as axis title"
        )
        assert y_title == "Total Population", (
            f"Expected 'Total Population', got {y_title!r}"
        )

    def test_temporal_single_y_title_uses_unit_when_present(self):
        """When a real unit is resolved, use it — don't override with indicator_name."""
        df = _temporal_df(["USA"], [2000, 2010, 2020])
        result = _default_result(ChartStrategy.TEMPORAL_SINGLE)
        spec = build_temporal_single_spec(
            df, "Test", result,
            y_label="Constant 2015 US$",  # ← real unit
            indicator_name="GDP per Capita",
        )
        y_title = spec.get("encoding", {}).get("y", {}).get("axis", {}).get("title")
        assert y_title == "Constant 2015 US$", (
            f"Expected unit label 'Constant 2015 US$' as y-axis title, got {y_title!r}"
        )

    def test_cross_sectional_x_title_uses_indicator_name_when_no_unit(self):
        """cross_sectional (horizontal bar): x-axis shows the value — must be labeled."""
        df = _temporal_df(["USA", "China", "Germany"], [2022])
        result = _default_result(ChartStrategy.CROSS_SECTIONAL, color_dim="country")
        spec = build_cross_sectional_spec(
            df, "Test", result,
            x_label="Value",             # ← no unit mapping
            indicator_name="Total Population",
        )

        x_title = spec.get("encoding", {}).get("x", {}).get("axis", {}).get("title")
        assert x_title is not None, (
            "cross_sectional: x-axis title must not be None when indicator_name is known"
        )
        assert x_title != "Value", (
            "cross_sectional: generic 'Value' must not appear as x-axis title"
        )

    def test_distribution_x_title_uses_indicator_name_when_no_unit(self):
        """Distribution/beeswarm: x-axis value must be labeled."""
        df = _temporal_df(
            ["USA", "UK", "FR", "DE", "JP", "CN", "IN", "BR", "CA", "AU",
             "MX", "ZA", "NG", "EG", "SA", "TR", "AR", "KR", "ID", "TH",
             "VN", "BD", "PK", "NG"],
            [2022], value=5.0,
        )
        result = _default_result(ChartStrategy.DISTRIBUTION, color_dim="country")
        spec = build_distribution_spec(
            df, "Test", result,
            x_label="Value",
            indicator_name="Gini Coefficient",
        )

        x_enc = spec.get("encoding", {}).get("x", {})
        x_title = x_enc.get("axis", {}).get("title") if x_enc.get("axis") else None
        # Distribution shows axis title through labelExpr; the axis title may be
        # None intentionally if the unit is shown via tick format. Accept either:
        # a meaningful title OR labelExpr format that encodes the unit.
        label_expr = x_enc.get("axis", {}).get("labelExpr", "")
        has_info = (x_title and x_title not in ("Value", "")) or bool(label_expr)
        assert has_info, (
            "distribution: x-axis must provide a meaningful title or labelExpr "
            f"when indicator_name is known. Got title={x_title!r}, labelExpr={label_expr!r}"
        )

    def test_heatmap_legend_title_not_generic_value(self):
        """Heatmap color-scale legend title must not be the bare string 'Value'."""
        df = _temporal_df(
            ["USA", "UK", "FR", "DE", "JP", "CN", "IN", "BR", "CA"],
            [2018, 2019, 2020, 2021, 2022],
        )
        result = _default_result(ChartStrategy.HEATMAP, color_dim=None)
        spec = build_heatmap_spec(
            df, "Test", result,
            y_label="Value",         # ← no unit mapping
            indicator_name="Inflation Rate",
        )

        legend = spec.get("encoding", {}).get("color", {}).get("legend", {})
        legend_title = legend.get("title") if isinstance(legend, dict) else None
        assert legend_title is not None and legend_title != "Value", (
            "heatmap: color-scale legend title must not be the generic 'Value' "
            f"when indicator_name='Inflation Rate' is available. Got {legend_title!r}"
        )

    def test_stacked_area_y_title_uses_indicator_name_when_no_unit(self):
        """Stacked area: y-axis shows cumulative value — must be labeled."""
        df = _temporal_df(["USA", "China", "India"], [2018, 2019, 2020, 2021])
        result = _default_result(ChartStrategy.STACKED_AREA, color_dim="country")
        spec = build_stacked_area_spec(
            df, "Test", result,
            y_label="Value",
            indicator_name="Population",
        )

        y_title = spec.get("encoding", {}).get("y", {}).get("axis", {}).get("title")
        assert y_title is not None, (
            "stacked_area: y-axis title must not be None when indicator_name is known"
        )
        assert y_title != "Value", (
            "stacked_area: generic 'Value' must not appear as y-axis title"
        )


# ---------------------------------------------------------------------------
# Regression: axis title must stay correct when unit IS available
# ---------------------------------------------------------------------------


class TestAxisTitleWithUnit:
    """Regression: real unit labels must not be overridden by indicator_name."""

    @pytest.mark.parametrize("unit_label,expected", [
        ("%", "%"),
        ("Constant 2015 US$", "Constant 2015 US$"),
        ("Persons (thousands)", "Persons (thousands)"),
    ])
    def test_temporal_unit_label_preserved(self, unit_label, expected):
        df = _temporal_df(["USA"], [2000, 2010, 2020])
        result = _default_result()
        spec = build_temporal_single_spec(
            df, "T", result,
            y_label=unit_label,
            indicator_name="Some Indicator",
        )
        y_title = spec["encoding"]["y"]["axis"]["title"]
        assert y_title == expected, (
            f"Expected axis title={expected!r}, got {y_title!r}"
        )
