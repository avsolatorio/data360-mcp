"""
Tests for complex visualization features:
  - ChartStrategy router
  - All spec builders
  - Multi-indicator merge + dispatch
  - Fallback path awareness
  - Axis label threading
  - Edge cases
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from data360 import viz_config
from data360.visualization import get_multi_indicator_viz_spec
from data360.viz_config import (
    WB_CAT_COLORS,
    ChartStrategy,
    StrategyResult,
    build_breakdown_comparison_spec,
    build_chart_title_with_context,
    build_correlation_spec,
    build_correlation_temporal_spec,
    build_cross_sectional_spec,
    build_distribution_spec,
    build_fallback_line_spec,
    build_small_multiples_spec,
    build_structured_tooltips,
    build_temporal_multi_indicator_spec,
    build_temporal_single_spec,
    dispatch_spec,
    format_chart_context_subtitle,
    select_strategy,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _ts_df(n_countries=3, n_years=5, value_start=10.0):
    """Multi-year time-series DataFrame."""
    rows = []
    for i, c in enumerate([f"Country{j}" for j in range(n_countries)]):
        for y in range(2019, 2019 + n_years):
            rows.append(
                {
                    "country": c,
                    "year": pd.Timestamp(f"{y}-01-01"),
                    "value": float(value_start + i * n_years + (y - 2019)),
                }
            )
    return pd.DataFrame(rows)


def _cs_df(n_countries=5, single_year=True):
    """Cross-sectional DataFrame."""
    rows = [
        {
            "country": f"Country{i}",
            "value": float(i * 10 + 5),
            "year": pd.Timestamp("2022-01-01"),
        }
        for i in range(n_countries)
    ]
    return pd.DataFrame(rows)


def _sex_df(countries=2):
    """DataFrame with sex breakdown."""
    rows = []
    for c in [f"Country{i}" for i in range(countries)]:
        for s in ["M", "F"]:
            for y in range(2020, 2023):
                rows.append(
                    {
                        "country": c,
                        "sex": s,
                        "year": pd.Timestamp(f"{y}-01-01"),
                        "value": float(hash((c, s, y)) % 100),
                    }
                )
    return pd.DataFrame(rows)


def _two_ind_df():
    """DataFrame with two indicator columns (merged multi-indicator)."""
    rows = [
        {
            "country": f"Country{i}",
            "year": pd.Timestamp("2022-01-01"),
            "gdp_per_capita": float(i * 1000 + 500),
            "life_expectancy": float(60 + i * 2),
        }
        for i in range(8)
    ]
    return pd.DataFrame(rows)


def _two_ind_ts_df():
    """Multi-year two-indicator DataFrame."""
    rows = []
    for c in ["CountryA", "CountryB"]:
        for y in range(2018, 2024):
            rows.append(
                {
                    "country": c,
                    "year": pd.Timestamp(f"{y}-01-01"),
                    "gdp_per_capita": float(hash((c, y, "gdp")) % 10000),
                    "life_expectancy": float(60 + hash((c, y, "life")) % 20),
                }
            )
    return pd.DataFrame(rows)


def _four_ind_ts_df():
    """Single country, four indicator columns, multi-year (for layered multi-axis)."""
    rows = []
    for y in range(2018, 2024):
        rows.append(
            {
                "country": "CountryA",
                "year": pd.Timestamp(f"{y}-01-01"),
                "ind_a": float(hash((y, "a")) % 1000),
                "ind_b": float(hash((y, "b")) % 1000),
                "ind_c": float(hash((y, "c")) % 1000),
                "ind_d": float(hash((y, "d")) % 1000),
            }
        )
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy Router
# ─────────────────────────────────────────────────────────────────────────────


class TestStrategyRouter:
    def test_temporal_single_multi_year(self):
        df = _ts_df(n_countries=3, n_years=5)
        r = select_strategy(df)
        assert r.strategy == ChartStrategy.TEMPORAL_SINGLE

    def test_temporal_single_sets_color_dim_to_country(self):
        df = _ts_df(n_countries=3)
        r = select_strategy(df)
        assert r.color_dim == "country"

    def test_temporal_single_one_country_still_colors_by_country(self):
        df = _ts_df(n_countries=1, n_years=5)
        r = select_strategy(df)
        assert r.strategy == ChartStrategy.TEMPORAL_SINGLE
        assert r.color_dim == "country"

    def test_temporal_single_reason_reflects_chart_type_hint(self):
        df = _ts_df(n_countries=1, n_years=5)
        r_bar = select_strategy(df, chart_type_hint="bar chart")
        assert "→ bar chart" in r_bar.reason
        r_line = select_strategy(df, chart_type_hint="line")
        assert "→ line chart" in r_line.reason

    def test_cross_sectional_single_year_few_countries(self):
        df = _cs_df(n_countries=5)
        r = select_strategy(df)
        assert r.strategy == ChartStrategy.CROSS_SECTIONAL

    def test_choropleth_single_year_many_countries(self):
        df = pd.DataFrame(
            {"country": [f"C{i}" for i in range(10)], "year": [2020] * 10, "value": range(10)}
        )
        r = select_strategy(df)
        assert r.strategy == ChartStrategy.CHOROPLETH

    def test_breakdown_single_disagg(self):
        # 2 countries × 2 sex × 3 years → SMALL_MULTIPLES (facet by country, color by sex)
        # Overlaying 4 series on one chart loses per-country context.
        df = _sex_df(countries=2)
        r = select_strategy(df)
        assert r.strategy == ChartStrategy.SMALL_MULTIPLES
        assert r.color_dim == "sex"
        assert r.facet_dim == "country"

    def test_small_multiples_many_countries_with_breakdown(self):
        # 6 countries × 2 sexes → small multiples
        df = _sex_df(countries=6)
        r = select_strategy(df)
        assert r.strategy == ChartStrategy.SMALL_MULTIPLES

    def test_correlation_two_indicators_single_year(self):
        df = _two_ind_df()
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = select_strategy(df, n_indicators=2, indicator_cols=ind_cols)
        assert r.strategy == ChartStrategy.CORRELATION
        assert r.indicator_cols == ind_cols

    def test_small_multiples_two_indicators_multi_year(self):
        df = _two_ind_ts_df()
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = select_strategy(df, n_indicators=2, indicator_cols=ind_cols)
        assert r.strategy == ChartStrategy.SMALL_MULTIPLES

    def test_temporal_multi_indicator_single_country(self):
        df = _two_ind_ts_df()
        df = df[df["country"] == "CountryA"].copy()
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = select_strategy(df, n_indicators=2, indicator_cols=ind_cols)
        assert r.strategy == ChartStrategy.TEMPORAL_MULTI_IND

    def test_explicit_scatter_hint_overrides(self):
        df = _two_ind_ts_df()  # multi-year but user says scatter
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = select_strategy(
            df, n_indicators=2, chart_type_hint="scatter", indicator_cols=ind_cols
        )
        assert r.strategy in (
            ChartStrategy.CORRELATION,
            ChartStrategy.CORRELATION_TEMPORAL,
        )

    def test_fallback_for_empty_like_df(self):
        df = pd.DataFrame({"value": [1.0, 2.0]})
        r = select_strategy(df)
        assert r.strategy == ChartStrategy.FALLBACK_LINE


class TestChartTitleContext:
    def test_format_chart_context_subtitle_countries_and_year_range(self):
        df = pd.DataFrame(
            {
                "country": ["Philippines", "Belgium", "World"],
                "year": pd.to_datetime(["1990-01-01", "2000-01-01", "2024-01-01"]),
                "value": [1.0, 2.0, 3.0],
            }
        )
        s = format_chart_context_subtitle(df)
        assert "1990-2024" in s
        assert "Belgium" in s
        assert "Philippines" in s
        assert "World" in s

    def test_build_chart_title_with_context_merges_unit(self):
        df = pd.DataFrame(
            {
                "country": ["Kenya", "Kenya"],
                "year": [2020, 2021],
                "value": [1.0, 2.0],
            }
        )
        t = build_chart_title_with_context("My indicator", "current US$", df)
        assert isinstance(t, dict)
        assert t["text"] == "My indicator"
        # subtitle is now a list of lines; join for substring checks.
        full_text = " ".join(t["subtitle"]) if isinstance(t["subtitle"], list) else t["subtitle"]
        assert "Kenya" in full_text
        assert "2020-2021" in full_text
        assert "current US$" in full_text


# ─────────────────────────────────────────────────────────────────────────────
# Spec Builders — structure and WB style
# ─────────────────────────────────────────────────────────────────────────────


class TestSpecBuilders:
    def _result(
        self,
        strategy,
        color_dim=None,
        indicator_cols=None,
        facet_dim=None,
        x_dim=None,
        y_dim=None,
    ):
        return StrategyResult(
            strategy,
            "test",
            indicator_cols=indicator_cols or [],
            color_dim=color_dim,
            facet_dim=facet_dim,
            x_dim=x_dim,
            y_dim=y_dim,
        )

    # temporal_single
    def test_temporal_single_mark_is_line(self):
        df = _ts_df()
        r = self._result(ChartStrategy.TEMPORAL_SINGLE, color_dim="country")
        spec = build_temporal_single_spec(df, "Test", r)
        assert spec["mark"]["type"] == "line"

    def test_temporal_single_x_is_temporal(self):
        df = _ts_df()
        r = self._result(ChartStrategy.TEMPORAL_SINGLE, color_dim="country")
        spec = build_temporal_single_spec(df, "Test", r)
        assert spec["encoding"]["x"]["type"] == "temporal"

    def test_temporal_single_x_axis_title_is_none(self):
        df = _ts_df()
        r = self._result(ChartStrategy.TEMPORAL_SINGLE, color_dim="country")
        spec = build_temporal_single_spec(df, "Test", r)
        assert spec["encoding"]["x"]["axis"]["title"] is None

    def test_temporal_single_y_label_propagates(self):
        df = _ts_df()
        r = self._result(ChartStrategy.TEMPORAL_SINGLE)
        spec = build_temporal_single_spec(df, "Test", r, y_label="GDP (USD)")
        assert spec["encoding"]["y"]["axis"]["title"] == "GDP (USD)"

    def test_temporal_single_currency_axis_labels_have_dollar_prefix(self):
        df = _ts_df()
        r = self._result(ChartStrategy.TEMPORAL_SINGLE, color_dim="country")
        spec = build_temporal_single_spec(df, "Test", r, unit_measure="current US$")
        expr = spec["encoding"]["y"]["axis"]["labelExpr"]
        assert "'$'+format" in expr

    def test_temporal_single_currency_tooltip_accepts_current_usd_unit(self):
        df = _ts_df()
        r = self._result(ChartStrategy.TEMPORAL_SINGLE, color_dim="country")
        spec = build_temporal_single_spec(df, "Test", r, unit_measure="current US$")
        value_tip = next(
            tip for tip in spec["encoding"]["tooltip"] if tip.get("field") == "value"
        )
        assert value_tip["format"] == "$,.2f"

    def test_temporal_single_color_encoding_present(self):
        df = _ts_df(n_countries=3)
        r = self._result(ChartStrategy.TEMPORAL_SINGLE, color_dim="country")
        spec = build_temporal_single_spec(df, "Test", r)
        assert "color" in spec["encoding"]
        assert spec["encoding"]["color"]["field"] == "country"

    def test_temporal_single_one_country_keeps_legend(self):
        df = _ts_df(n_countries=1, n_years=4)
        r = self._result(ChartStrategy.TEMPORAL_SINGLE, color_dim="country")
        spec = build_temporal_single_spec(df, "Test", r)
        leg = spec["encoding"]["color"]["legend"]
        assert leg is not None

    def test_temporal_single_line_has_hover_points(self):
        df = _ts_df()
        r = self._result(ChartStrategy.TEMPORAL_SINGLE, color_dim="country")
        spec = build_temporal_single_spec(df, "Test", r)
        pt = spec["mark"]["point"]
        assert isinstance(pt, dict)
        assert pt.get("size", 0) >= 40

    # cross_sectional
    def test_cross_sectional_mark_is_bar(self):
        df = _cs_df()
        r = self._result(ChartStrategy.CROSS_SECTIONAL, color_dim="country")
        spec = build_cross_sectional_spec(df, "Test", r)
        assert spec["mark"]["type"] == "bar"

    def test_cross_sectional_y_is_country_nominal(self):
        df = _cs_df()
        r = self._result(ChartStrategy.CROSS_SECTIONAL, color_dim="country")
        spec = build_cross_sectional_spec(df, "Test", r)
        assert spec["encoding"]["y"]["field"] == "country"
        assert spec["encoding"]["y"]["type"] == "nominal"

    def test_cross_sectional_sorted_desc(self):
        df = _cs_df()
        r = self._result(ChartStrategy.CROSS_SECTIONAL)
        spec = build_cross_sectional_spec(df, "Test", r)
        assert spec["encoding"]["y"]["sort"] == "-x"

    def test_cross_sectional_x_label_sets_axis_title_when_not_default(self):
        df = _cs_df()
        r = self._result(ChartStrategy.CROSS_SECTIONAL, color_dim="country")
        spec = build_cross_sectional_spec(
            df, "Test", r, x_label="GDP (current US$)"
        )
        assert spec["encoding"]["x"]["axis"]["title"] == "GDP (current US$)"

    # distribution
    def test_distribution_mark_is_tick(self):
        df = _cs_df(n_countries=15)
        r = self._result(ChartStrategy.DISTRIBUTION, color_dim="country")
        spec = build_distribution_spec(df, "Test", r)
        assert spec["mark"]["type"] == "tick"

    def test_distribution_limits_rows(self):
        df = _cs_df(n_countries=20)
        r = self._result(ChartStrategy.DISTRIBUTION, color_dim="country")
        spec = build_distribution_spec(df, "Test", r)
        top_n = viz_config.HIGH_CARDINALITY_THRESHOLDS["top_n_series"]
        assert len(spec["data"]["values"]) <= top_n

    def test_distribution_uses_wb_colors(self):
        df = _cs_df(n_countries=15)
        r = self._result(ChartStrategy.DISTRIBUTION, color_dim="country")
        spec = build_distribution_spec(df, "Test", r)
        assert spec["encoding"]["color"]["scale"]["range"] == WB_CAT_COLORS

    # breakdown_comparison
    def test_breakdown_has_xoffset_for_grouped_bars(self):
        df = _sex_df(countries=2)
        r = self._result(ChartStrategy.BREAKDOWN_COMPARISON, color_dim="sex")
        spec = build_breakdown_comparison_spec(df, "Test", r)
        assert "xOffset" in spec["encoding"]

    def test_breakdown_gender_colors_for_sex(self):
        df = _sex_df(countries=2)
        r = self._result(ChartStrategy.BREAKDOWN_COMPARISON, color_dim="sex")
        spec = build_breakdown_comparison_spec(df, "Test", r)
        # Female color should be in the range
        color_range = spec["encoding"]["color"]["scale"]["range"]
        assert viz_config.WB_GENDER_COLORS["F"] in color_range

    # small_multiples
    def test_small_multiples_has_vconcat_key(self):
        df = _sex_df(countries=6)
        r = self._result(
            ChartStrategy.SMALL_MULTIPLES, color_dim="sex", facet_dim="country"
        )
        spec = build_small_multiples_spec(df, "Test", r)
        assert "vconcat" in spec

    def test_small_multiples_panels_capped(self):
        df = _sex_df(countries=6)
        r = self._result(
            ChartStrategy.SMALL_MULTIPLES, color_dim="sex", facet_dim="country"
        )
        spec = build_small_multiples_spec(df, "Test", r)
        # Verify it limits panels (12 is the cap)
        assert len(spec.get("vconcat", [])) <= 12

    # correlation
    def test_correlation_mark_is_circle(self):
        df = _two_ind_df()
        r = self._result(
            ChartStrategy.CORRELATION,
            color_dim="country",
            indicator_cols=["gdp_per_capita", "life_expectancy"],
        )
        spec = build_correlation_spec(df, "Test", r)
        assert spec["layer"][0]["mark"]["type"] == "circle"
        assert spec["layer"][1]["mark"]["type"] == "text"

    def test_correlation_x_y_from_indicator_cols(self):
        df = _two_ind_df()
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = self._result(
            ChartStrategy.CORRELATION, color_dim="country", indicator_cols=ind_cols
        )
        spec = build_correlation_spec(df, "Test", r)
        assert spec["layer"][0]["encoding"]["x"]["field"] == "gdp_per_capita"
        assert spec["layer"][0]["encoding"]["y"]["field"] == "life_expectancy"

    def test_correlation_axis_labels_from_indicator_labels(self):
        df = _two_ind_df()
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = self._result(
            ChartStrategy.CORRELATION, color_dim="country", indicator_cols=ind_cols
        )
        labels = {"gdp_per_capita": "GDP (USD)", "life_expectancy": "Life Exp (years)"}
        spec = build_correlation_spec(df, "Test", r, indicator_labels=labels)
        assert spec["layer"][0]["encoding"]["x"]["axis"]["title"] == "GDP (USD)"
        assert spec["layer"][0]["encoding"]["y"]["axis"]["title"] == "Life Exp (years)"

    def test_correlation_raises_without_indicator_cols(self):
        df = _two_ind_df()
        r = self._result(ChartStrategy.CORRELATION, color_dim="country")
        with pytest.raises(ValueError, match="2 indicator"):
            build_correlation_spec(df, "Test", r)

    def test_correlation_drops_rows_with_null_indicator_values(self):
        df = _two_ind_df().copy()
        df.loc[0, "gdp_per_capita"] = None
        r = self._result(
            ChartStrategy.CORRELATION,
            color_dim="country",
            indicator_cols=["gdp_per_capita", "life_expectancy"],
        )
        spec = build_correlation_spec(df, "Test", r)
        # Row with null should be dropped
        vals = [row["gdp_per_capita"] for row in spec["data"]["values"]]
        assert all(v is not None for v in vals)

    # correlation_temporal
    def test_correlation_temporal_has_two_layers(self):
        df = _two_ind_ts_df()
        r = self._result(
            ChartStrategy.CORRELATION_TEMPORAL,
            color_dim="country",
            indicator_cols=["gdp_per_capita", "life_expectancy"],
        )
        spec = build_correlation_temporal_spec(df, "Test", r)
        assert "layer" in spec
        assert len(spec["layer"]) == 2

    def test_correlation_temporal_has_order_encoding(self):
        df = _two_ind_ts_df()
        r = self._result(
            ChartStrategy.CORRELATION_TEMPORAL,
            color_dim="country",
            indicator_cols=["gdp_per_capita", "life_expectancy"],
        )
        spec = build_correlation_temporal_spec(df, "Test", r)
        # At least one layer should have order encoding
        has_order = any("order" in layer.get("encoding", {}) for layer in spec["layer"])
        assert has_order

    # temporal_multi_indicator
    def test_temporal_multi_indicator_layers_equal_n_indicators(self):
        df = _two_ind_ts_df()[lambda x: x["country"] == "CountryA"]
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = self._result(ChartStrategy.TEMPORAL_MULTI_IND, indicator_cols=ind_cols)
        spec = build_temporal_multi_indicator_spec(df, "Test", r)
        assert len(spec["vconcat"]) == 2

    def test_temporal_multi_indicator_shared_x_scale(self):
        df = _two_ind_ts_df()[lambda x: x["country"] == "CountryA"]
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = self._result(ChartStrategy.TEMPORAL_MULTI_IND, indicator_cols=ind_cols)
        spec = build_temporal_multi_indicator_spec(df, "Test", r)
        assert spec.get("resolve", {}).get("scale", {}).get("x") == "shared"

    def test_temporal_multi_indicator_each_layer_different_color(self):
        df = _two_ind_ts_df()[lambda x: x["country"] == "CountryA"]
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = self._result(ChartStrategy.TEMPORAL_MULTI_IND, indicator_cols=ind_cols)
        spec = build_temporal_multi_indicator_spec(df, "Test", r)
        colors = [chart["mark"]["color"] for chart in spec["vconcat"]]
        assert len(set(colors)) == 2  # distinct colors

    def test_temporal_multi_indicator_tooltip_one_value_field_per_layer(self):
        df = _two_ind_ts_df()[lambda x: x["country"] == "CountryA"]
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = self._result(ChartStrategy.TEMPORAL_MULTI_IND, indicator_cols=ind_cols)
        lab = {"gdp_per_capita": "GDP (USD)", "life_expectancy": "Life exp"}
        spec = build_temporal_multi_indicator_spec(df, "Test", r, indicator_labels=lab)
        tips0 = spec["vconcat"][0]["encoding"]["tooltip"]
        tips1 = spec["vconcat"][1]["encoding"]["tooltip"]
        fields0 = {t["field"] for t in tips0}
        fields1 = {t["field"] for t in tips1}
        assert "gdp_per_capita" in fields0
        assert "life_expectancy" not in fields0
        assert "life_expectancy" in fields1
        assert "gdp_per_capita" not in fields1

    def test_temporal_multi_indicator_four_series_stacked(self):
        df = _four_ind_ts_df()
        ind_cols = ["ind_a", "ind_b", "ind_c", "ind_d"]
        r = self._result(ChartStrategy.TEMPORAL_MULTI_IND, indicator_cols=ind_cols)
        spec = build_temporal_multi_indicator_spec(df, "Test", r)
        assert len(spec["vconcat"]) == 4
        axes_x_labels = [chart["encoding"]["x"]["axis"].get("labels") for chart in spec["vconcat"]]
        assert axes_x_labels[0] is False
        assert axes_x_labels[3] is None  # Not set, so defaults to true in VegaLite

    # fallback
    def test_fallback_produces_line(self):
        df = pd.DataFrame({"year": [pd.Timestamp("2020")], "value": [42.0]})
        r = StrategyResult(ChartStrategy.FALLBACK_LINE, "test")
        spec = build_fallback_line_spec(df, "Test", r)
        assert spec["mark"]["type"] == "line"


# ─────────────────────────────────────────────────────────────────────────────
# dispatch_spec
# ─────────────────────────────────────────────────────────────────────────────


class TestDispatch:
    def test_dispatch_calls_correct_builder_for_each_strategy(self):
        df_ts = _ts_df()
        df_cs = _cs_df()
        df_dist = _cs_df(15)
        df_sex = _sex_df(2)
        df_sm = _sex_df(6)
        df_2i = _two_ind_df()
        df_2its = _two_ind_ts_df()
        df_fb = pd.DataFrame({"year": [pd.Timestamp("2020")], "value": [1.0]})

        cases = [
            (
                ChartStrategy.TEMPORAL_SINGLE,
                df_ts,
                StrategyResult(ChartStrategy.TEMPORAL_SINGLE, "", color_dim="country"),
            ),
            (
                ChartStrategy.CROSS_SECTIONAL,
                df_cs,
                StrategyResult(ChartStrategy.CROSS_SECTIONAL, "", color_dim="country"),
            ),
            (
                ChartStrategy.DISTRIBUTION,
                df_dist,
                StrategyResult(ChartStrategy.DISTRIBUTION, "", color_dim="country"),
            ),
            (
                ChartStrategy.BREAKDOWN_COMPARISON,
                df_sex,
                StrategyResult(ChartStrategy.BREAKDOWN_COMPARISON, "", color_dim="sex"),
            ),
            (
                ChartStrategy.SMALL_MULTIPLES,
                df_sm,
                StrategyResult(
                    ChartStrategy.SMALL_MULTIPLES,
                    "",
                    color_dim="sex",
                    facet_dim="country",
                ),
            ),
            (
                ChartStrategy.CORRELATION,
                df_2i,
                StrategyResult(
                    ChartStrategy.CORRELATION,
                    "",
                    indicator_cols=["gdp_per_capita", "life_expectancy"],
                    color_dim="country",
                ),
            ),
            (
                ChartStrategy.CORRELATION_TEMPORAL,
                df_2its,
                StrategyResult(
                    ChartStrategy.CORRELATION_TEMPORAL,
                    "",
                    indicator_cols=["gdp_per_capita", "life_expectancy"],
                    color_dim="country",
                ),
            ),
            (
                ChartStrategy.TEMPORAL_MULTI_IND,
                df_2its[lambda x: x.country == "CountryA"],
                StrategyResult(
                    ChartStrategy.TEMPORAL_MULTI_IND,
                    "",
                    indicator_cols=["gdp_per_capita", "life_expectancy"],
                ),
            ),
            (
                ChartStrategy.FALLBACK_LINE,
                df_fb,
                StrategyResult(ChartStrategy.FALLBACK_LINE, ""),
            ),
        ]
        for strategy, df, result in cases:
            spec = dispatch_spec(strategy, df, "T", result, y_label="Y", x_label="X")
            assert "$schema" in spec, f"No $schema for {strategy}"
            assert "config" in spec, f"No WB config for {strategy}"


# ─────────────────────────────────────────────────────────────────────────────
# WB Style on every spec
# ─────────────────────────────────────────────────────────────────────────────


class TestWBStyleOnAllSpecs:
    def _all_specs(self):
        df_ts = _ts_df()
        df_cs = _cs_df()
        df_sex = _sex_df(2)
        df_2i = _two_ind_df()
        df_2ts = _two_ind_ts_df()
        return [
            build_temporal_single_spec(
                df_ts,
                "T",
                StrategyResult(ChartStrategy.TEMPORAL_SINGLE, "", color_dim="country"),
            ),
            build_cross_sectional_spec(
                df_cs,
                "T",
                StrategyResult(ChartStrategy.CROSS_SECTIONAL, "", color_dim="country"),
            ),
            build_distribution_spec(
                _cs_df(15),
                "T",
                StrategyResult(ChartStrategy.DISTRIBUTION, "", color_dim="country"),
            ),
            build_breakdown_comparison_spec(
                df_sex,
                "T",
                StrategyResult(ChartStrategy.BREAKDOWN_COMPARISON, "", color_dim="sex"),
            ),
            build_small_multiples_spec(
                _sex_df(6),
                "T",
                StrategyResult(
                    ChartStrategy.SMALL_MULTIPLES,
                    "",
                    color_dim="sex",
                    facet_dim="country",
                ),
            ),
            build_correlation_spec(
                df_2i,
                "T",
                StrategyResult(
                    ChartStrategy.CORRELATION,
                    "",
                    indicator_cols=["gdp_per_capita", "life_expectancy"],
                    color_dim="country",
                ),
            ),
            build_correlation_temporal_spec(
                df_2ts,
                "T",
                StrategyResult(
                    ChartStrategy.CORRELATION_TEMPORAL,
                    "",
                    indicator_cols=["gdp_per_capita", "life_expectancy"],
                    color_dim="country",
                ),
            ),
            build_temporal_multi_indicator_spec(
                df_2ts[lambda x: x.country == "CountryA"],
                "T",
                StrategyResult(
                    ChartStrategy.TEMPORAL_MULTI_IND,
                    "",
                    indicator_cols=["gdp_per_capita", "life_expectancy"],
                ),
            ),
        ]

    def test_all_specs_have_vl_schema(self):
        for spec in self._all_specs():
            assert "$schema" in spec, "Missing $schema"

    def test_all_specs_have_wb_config(self):
        for spec in self._all_specs():
            assert "config" in spec, "Missing WB config"

    def test_all_specs_have_wb_category_colors(self):
        for spec in self._all_specs():
            cat_colors = spec.get("config", {}).get("range", {}).get("category")
            assert cat_colors == WB_CAT_COLORS, "WB cat colors not injected"

    def test_all_specs_have_wb_font(self):
        for spec in self._all_specs():
            assert "Noto Sans" in spec.get("config", {}).get("font", ""), (
                "WB font not set"
            )

    def test_all_specs_have_tooltips(self):
        for spec in self._all_specs():
            enc = spec.get("encoding") or spec.get("spec", {}).get("encoding", {}) or {}
            has_tooltip = "tooltip" in enc
            if "layer" in spec:
                has_tooltip = any("tooltip" in layer.get("encoding", {}) for layer in spec["layer"])
            elif "vconcat" in spec:
                has_tooltip = "tooltip" in spec["vconcat"][0].get("encoding", {})

            assert has_tooltip, f"Missing tooltip in spec: {spec.get('title')}"


# ─────────────────────────────────────────────────────────────────────────────
# Structured Tooltips (multi-indicator variant)
# ─────────────────────────────────────────────────────────────────────────────


class TestMultiIndicatorTooltips:
    def test_indicator_label_replaces_col_name(self):
        labels = {"gdp_per_capita": "GDP per capita (USD)"}
        tips = build_structured_tooltips(["gdp_per_capita", "country"], "point", labels)
        gdp_tip = next(t for t in tips if t["field"] == "gdp_per_capita")
        assert gdp_tip["title"] == "GDP per capita (USD)"

    def test_indicator_label_tip_has_number_format(self):
        labels = {"life_exp": "Life Expectancy"}
        tips = build_structured_tooltips(["life_exp"], "point", labels)
        assert tips[0]["format"] == ",.2f"

    def test_indicator_label_tip_is_quantitative(self):
        labels = {"some_ind": "Some Indicator"}
        tips = build_structured_tooltips(["some_ind"], "point", labels)
        assert tips[0]["type"] == "quantitative"


# ─────────────────────────────────────────────────────────────────────────────
# Multi-indicator merge & dispatch integration (mocked fetches)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetMultiIndicatorVizSpec:
    """Integration tests for get_multi_indicator_viz_spec with mocked I/O."""

    def _make_df(self, col_name, countries, years):
        rows = [
            {
                "TIME_PERIOD": f"{y}-01-01",
                "REF_AREA": c,
                "OBS_VALUE": float(hash((c, y)) % 100),
            }
            for c in countries
            for y in years
        ]
        return pd.DataFrame(rows)

    @pytest.fixture
    def patches(self):
        with (
            patch(
                "data360.api.get_data_api_url",
                new_callable=AsyncMock,
                return_value="http://fake/data?DATABASE_ID=WB&INDICATOR=X",
            ) as mock_url,
            patch(
                "data360.visualization._fetch_data_internal", new_callable=AsyncMock
            ) as mock_fetch,
            patch(
                "data360.api.get_metadata", new_callable=AsyncMock, return_value=None
            ),
            patch(
                "data360.providers.get_codelist_mapping",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "data360.visualization.save_specs_to_static",
                return_value="http://localhost/spec.json",
            ),
        ):
            yield mock_url, mock_fetch

    @pytest.mark.asyncio
    async def test_returns_url_for_two_indicators(self, patches):
        _, mock_fetch = patches
        countries = ["KEN", "TZA", "UGA"]
        years = [2022]
        df1 = self._make_df("ind1", countries, years)
        df2 = self._make_df("ind2", countries, years)
        mock_fetch.side_effect = [df1, df2]

        result = await get_multi_indicator_viz_spec(
            indicator_ids=[
                {"database_id": "WB_WDI", "indicator_id": "IND_A"},
                {"database_id": "WB_WDI", "indicator_id": "IND_B"},
            ]
        )
        assert result["url"] is not None, (
            f"Expected URL, got error: {result.get('error')}"
        )
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_disjoint_dimensions_returns_merge_error(self, patches):
        """No shared merge keys (e.g. time-only vs geography-only) → clear error, no 500."""
        _, mock_fetch = patches
        df_time_only = pd.DataFrame(
            [{"TIME_PERIOD": "2020-01-01", "OBS_VALUE": 10.0}]
        )
        df_geo_only = pd.DataFrame([{"REF_AREA": "KEN", "OBS_VALUE": 20.0}])
        mock_fetch.side_effect = [df_time_only, df_geo_only]

        result = await get_multi_indicator_viz_spec(
            indicator_ids=[
                {"database_id": "WB_WDI", "indicator_id": "IND_A"},
                {"database_id": "WB_WDI", "indicator_id": "IND_B"},
            ],
        )
        assert result.get("url") is None
        assert result.get("error") is not None
        err = (result["error"] or "").lower()
        assert "no common dimensions" in err

    @pytest.mark.asyncio
    async def test_returns_strategy_in_result(self, patches):
        _, mock_fetch = patches
        countries = ["KEN", "TZA", "UGA"]
        years = [2022]
        df1 = self._make_df("ind1", countries, years)
        df2 = self._make_df("ind2", countries, years)
        mock_fetch.side_effect = [df1, df2]

        result = await get_multi_indicator_viz_spec(
            indicator_ids=[
                {"database_id": "WB", "indicator_id": "A"},
                {"database_id": "WB", "indicator_id": "B"},
            ]
        )
        assert "strategy" in result, "Result should include 'strategy' field"

    @pytest.mark.asyncio
    async def test_error_with_fewer_than_two_indicators(self):
        result = await get_multi_indicator_viz_spec(
            indicator_ids=[{"database_id": "WB", "indicator_id": "A"}]
        )
        assert result["url"] is None
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_error_when_indicator_ids_omitted(self):
        result = await get_multi_indicator_viz_spec(indicator_ids=None)
        assert result["url"] is None
        assert result["error"] is not None
        assert "indicator_ids is required" in (result["error"] or "")

    @pytest.mark.asyncio
    async def test_error_with_more_than_four_indicators(self):
        result = await get_multi_indicator_viz_spec(
            indicator_ids=[
                {"database_id": "WB", "indicator_id": f"IND{i}"} for i in range(5)
            ]
        )
        assert result["url"] is None
        assert "Maximum 4" in result["error"]

    @pytest.mark.asyncio
    async def test_uses_scatter_strategy_for_multi_country_single_year(self, patches):
        _, mock_fetch = patches
        countries = [f"C{i}" for i in range(10)]
        df1 = self._make_df("ind1", countries, [2022])
        df2 = self._make_df("ind2", countries, [2022])
        mock_fetch.side_effect = [df1, df2]

        result = await get_multi_indicator_viz_spec(
            indicator_ids=[
                {"database_id": "WB", "indicator_id": "A"},
                {"database_id": "WB", "indicator_id": "B"},
            ]
        )
        assert result.get("strategy") in (
            "correlation",
            "cross_sectional",
            "distribution",
            "temporal_single",
            "temporal_multi_indicator",
            "correlation_temporal",
        ), f"Unexpected strategy: {result.get('strategy')}"

    @pytest.mark.asyncio
    async def test_empty_data_returns_error(self, patches):
        _, mock_fetch = patches
        # First indicator has data, second returns empty
        df1 = self._make_df("ind1", ["KEN"], [2022])
        mock_fetch.side_effect = [df1, pd.DataFrame()]

        result = await get_multi_indicator_viz_spec(
            indicator_ids=[
                {"database_id": "WB", "indicator_id": "A"},
                {"database_id": "WB", "indicator_id": "B"},
            ]
        )
        assert result["url"] is None
        assert result["error"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# Axis label threading
# ─────────────────────────────────────────────────────────────────────────────


class TestAxisLabelThreading:
    """Y-axis must show indicator name + unit, not just 'Value'."""

    def test_temporal_single_y_axis_reflects_y_label(self):
        df = _ts_df()
        r = StrategyResult(ChartStrategy.TEMPORAL_SINGLE, "", color_dim="country")
        spec = build_temporal_single_spec(
            df, "T", r, y_label="GDP per capita (2017 USD)"
        )
        assert "GDP per capita" in spec["encoding"]["y"]["axis"]["title"]

    def test_correlation_x_label_from_indicator_labels(self):
        df = _two_ind_df()
        r = StrategyResult(
            ChartStrategy.CORRELATION,
            "",
            color_dim="country",
            indicator_cols=["gdp_per_capita", "life_expectancy"],
        )
        spec = build_correlation_spec(
            df,
            "T",
            r,
            indicator_labels={
                "gdp_per_capita": "GDP (USD)",
                "life_expectancy": "Life Exp",
            },
        )
        assert spec["layer"][0]["encoding"]["x"]["axis"]["title"] == "GDP (USD)"
        assert spec["layer"][0]["encoding"]["y"]["axis"]["title"] == "Life Exp"

    def test_multi_ind_vconcat_facet_title_per_indicator(self):
        df = _two_ind_ts_df()[lambda x: x.country == "CountryA"]
        r = StrategyResult(
            ChartStrategy.TEMPORAL_MULTI_IND,
            "",
            indicator_cols=["gdp_per_capita", "life_expectancy"],
        )
        spec = build_temporal_multi_indicator_spec(
            df,
            "T",
            r,
            indicator_labels={
                "gdp_per_capita": "GDP (USD)",
                "life_expectancy": "Life Exp (yr)",
            },
        )
        facet_titles = [chart.get("title", {}).get("text") for chart in spec["vconcat"]]
        assert "GDP (USD)" in facet_titles
        assert "Life Exp (yr)" in facet_titles


# ─────────────────────────────────────────────────────────────────────────────
# Null / NaN handling
# ─────────────────────────────────────────────────────────────────────────────


class TestNullHandling:
    def test_correlation_drops_nulls_before_plotting(self):
        df = _two_ind_df().copy()
        df.loc[2, "gdp_per_capita"] = None
        r = StrategyResult(
            ChartStrategy.CORRELATION,
            "",
            color_dim="country",
            indicator_cols=["gdp_per_capita", "life_expectancy"],
        )
        spec = build_correlation_spec(df, "T", r)
        assert all(r["gdp_per_capita"] is not None for r in spec["data"]["values"])

    def test_distribution_with_all_valid_values(self):
        df = _cs_df(15)
        assert not df["value"].isna().any()
        r = StrategyResult(ChartStrategy.DISTRIBUTION, "", color_dim="country")
        spec = build_distribution_spec(df, "T", r)
        assert len(spec["data"]["values"]) > 0

    def test_obs_value_not_fillna_zero_in_viz_module(self):
        """Regression guard: .fillna(0) must not exist on obs_value."""
        import inspect

        import data360.visualization as viz_mod

        src = inspect.getsource(viz_mod)
        assert "fillna(0)" not in src


# ─────────────────────────────────────────────────────────────────────────────
# get_supported_chart_types updated content
# ─────────────────────────────────────────────────────────────────────────────


class TestGetSupportedChartTypes:
    def test_returns_valid_json(self):
        import json

        from data360.visualization import get_supported_chart_types

        data = json.loads(get_supported_chart_types())
        assert "chart_types" in data

    def test_includes_scatter_type(self):
        import json

        from data360.visualization import get_supported_chart_types

        data = json.loads(get_supported_chart_types())
        ids = [ct["id"] for ct in data["chart_types"]]
        assert "scatter" in ids

    def test_includes_multi_indicator_note(self):
        import json

        from data360.visualization import get_supported_chart_types

        data = json.loads(get_supported_chart_types())
        assert "multi_indicator" in data.get("multi_indicator_note", "")


# ============================================================================
# Grammar of Graphics robustness: LINE (TEMPORAL_SINGLE)
# ============================================================================


def _make_line_result(**kwargs):
    return StrategyResult(
        strategy=ChartStrategy.TEMPORAL_SINGLE,
        reason="test",
        **kwargs,
    )


class TestLineChartGoGRobustness:
    """TEMPORAL_SINGLE must conform to Grammar of Graphics axioms for line charts."""

    # ── Scale ──────────────────────────────────────────────────────────────

    def test_y_scale_zero_is_false(self):
        """Y-axis must NOT force zero baseline — trend differences would be compressed."""
        df = _ts_df(n_countries=2)
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        assert spec["encoding"]["y"]["scale"]["zero"] is False, (
            "TEMPORAL_SINGLE Y scale must set zero=False. "
            "Forcing Y to start at 0 compresses small trend variations into noise."
        )

    # ── Axis types ─────────────────────────────────────────────────────────

    def test_x_axis_type_is_temporal_not_ordinal(self):
        """Year axis must be temporal, not ordinal."""
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        assert spec["encoding"]["x"]["type"] == "temporal", (
            "X axis must be type='temporal'. Ordinal encoding maps ISO timestamps "
            "to raw millisecond integers on the axis."
        )

    def test_y_axis_type_is_quantitative(self):
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        assert spec["encoding"]["y"]["type"] == "quantitative"

    def test_color_field_type_is_nominal(self):
        df = _ts_df(n_countries=3)
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        assert spec["encoding"]["color"]["type"] == "nominal", (
            "Color channel for country/breakdown must be nominal, not ordinal or quantitative."
        )

    # ── Axis format ────────────────────────────────────────────────────────

    def test_x_axis_has_no_title(self):
        """Year axis title must be suppressed — year is self-evident."""
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        x_axis = spec["encoding"]["x"]["axis"]
        assert x_axis.get("title") is None, (
            "X axis title must be None. 'Year' clutters the axis without adding information."
        )

    def test_y_axis_title_suppressed_when_label_is_value(self):
        """When y_label is the default 'Value', Y title must be None."""
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(), y_label="Value")
        assert spec["encoding"]["y"]["axis"]["title"] is None, (
            "Y axis must suppress title when y_label='Value' — generic labels add no information."
        )

    def test_y_axis_title_set_when_custom_label(self):
        """Custom y_label must propagate to axis title."""
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(), y_label="GDP (USD)")
        assert spec["encoding"]["y"]["axis"]["title"] == "GDP (USD)"

    def test_y_axis_has_label_expr_for_currency(self):
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"), unit_measure="current US$")
        expr = spec["encoding"]["y"]["axis"]["labelExpr"]
        assert "$" in expr, (
            "Currency units must produce a dollar-prefixed labelExpr for compact large number formatting."
        )

    # ── Mark visual integrity ───────────────────────────────────────────────

    def test_mark_type_is_line(self):
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        assert spec["mark"]["type"] == "line"

    def test_line_stroke_width_is_readable(self):
        """Thin lines are unreadable in small embeds — minimum 2px."""
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        assert spec["mark"].get("strokeWidth", 0) >= 2, (
            "Line strokeWidth must be >= 2. Lines thinner than 2px are unreadable in embeds."
        )

    def test_line_has_hover_points(self):
        """Hover points are required for interactive value lookup."""
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        pt = spec["mark"].get("point", {})
        assert isinstance(pt, dict) and pt.get("size", 0) >= 40, (
            "Line mark must include hover points (size >= 40) for interactive value lookup."
        )

    # ── Tooltip completeness ────────────────────────────────────────────────

    def test_tooltip_has_year_field(self):
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        fields = {t["field"] for t in spec["encoding"]["tooltip"]}
        assert "year" in fields, "Tooltip must include 'year' field."

    def test_tooltip_has_value_field(self):
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        fields = {t["field"] for t in spec["encoding"]["tooltip"]}
        assert "value" in fields, "Tooltip must include 'value' field."

    def test_tooltip_has_country_field(self):
        df = _ts_df(n_countries=3)
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        fields = {t["field"] for t in spec["encoding"]["tooltip"]}
        assert "country" in fields, "Tooltip must include 'country' field."

    def test_tooltip_year_type_is_temporal(self):
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        year_tip = next(t for t in spec["encoding"]["tooltip"] if t["field"] == "year")
        assert year_tip["type"] == "temporal", (
            "Tooltip year field must be type='temporal' to render as a human-readable date."
        )

    # ── WB config injection ─────────────────────────────────────────────────

    def test_wb_config_is_present(self):
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        assert "config" in spec, "TEMPORAL_SINGLE spec must have WB config injected."

    def test_wb_config_has_font(self):
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        assert "font" in spec["config"], "WB config must set a global font family."

    def test_wb_config_has_label_overlap_greedy(self):
        """labelOverlap='greedy' prevents axis label collision on dense charts."""
        df = _ts_df()
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        axis_cfg = spec["config"].get("axis", {})
        assert axis_cfg.get("labelOverlap") == "greedy", (
            "Global axis config must set labelOverlap='greedy' to prevent label collisions."
        )

    # ── Multi-country color handling ────────────────────────────────────────

    def test_color_uses_wb_categorical_palette(self):
        df = _ts_df(n_countries=3)
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        palette = spec["encoding"]["color"]["scale"]["range"]
        assert palette == WB_CAT_COLORS, (
            "Line chart must use the WB categorical color palette for country series."
        )

    def test_eight_countries_all_get_color(self):
        """Edge case: 8 countries is the max before HEATMAP — must still render cleanly."""
        df = _ts_df(n_countries=8)
        spec = build_temporal_single_spec(df, "Test", _make_line_result(color_dim="country"))
        assert "color" in spec["encoding"]
        palette = spec["encoding"]["color"]["scale"]["range"]
        assert len(palette) >= 8, (
            "WB categorical palette must support at least 8 colors for the max line-chart country count."
        )


# ============================================================================
# Grammar of Graphics robustness: BAR (CROSS_SECTIONAL)
# ============================================================================


def _make_bar_result(**kwargs):
    return StrategyResult(
        strategy=ChartStrategy.CROSS_SECTIONAL,
        reason="test",
        **kwargs,
    )


class TestBarChartGoGRobustness:
    """CROSS_SECTIONAL must conform to Grammar of Graphics axioms for bar charts."""

    # ── Scale ──────────────────────────────────────────────────────────────

    def test_x_scale_zero_is_true(self):
        """Bar chart X-axis MUST start at zero — non-zero baseline is deceptive."""
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result(color_dim="country"))
        assert spec["encoding"]["x"]["scale"]["zero"] is True, (
            "CROSS_SECTIONAL X scale must set zero=True. "
            "Bars that don't start at 0 make small differences look large — a classic deception."
        )

    # ── Axis types ─────────────────────────────────────────────────────────

    def test_y_axis_type_is_nominal(self):
        """Country axis must be nominal, not ordinal."""
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result(color_dim="country"))
        assert spec["encoding"]["y"]["type"] == "nominal", (
            "Country axis must be nominal. Ordinal implies a meaningful rank order in the data."
        )

    def test_x_axis_type_is_quantitative(self):
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result(color_dim="country"))
        assert spec["encoding"]["x"]["type"] == "quantitative"

    # ── Sort order ─────────────────────────────────────────────────────────

    def test_bars_sorted_descending_by_value(self):
        """Highest value must appear at the top for immediate visual ranking."""
        df = _cs_df(n_countries=5)
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result())
        assert spec["encoding"]["y"]["sort"] == "-x", (
            "Bars must be sorted descending (sort='-x') so the highest value appears at top."
        )

    def test_data_values_are_sorted_descending(self):
        """The inline data must also be sorted descending for consistent rendering."""
        df = _cs_df(n_countries=5)
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result())
        vals = [r["value"] for r in spec["data"]["values"]]
        assert vals == sorted(vals, reverse=True), (
            "Inline data values must be sorted descending to match the sort encoding."
        )

    # ── Axis format ────────────────────────────────────────────────────────

    def test_y_axis_has_no_title(self):
        """Country names are self-evident — no axis title needed."""
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result())
        assert spec["encoding"]["y"]["axis"]["title"] is None, (
            "Y axis (country names) must have title=None — the country names are self-labeling."
        )

    def test_x_axis_title_suppressed_when_default(self):
        """Default x_label='Value' must not appear as axis title."""
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result(), x_label="Value")
        assert spec["encoding"]["x"]["axis"]["title"] is None, (
            "Generic x_label='Value' must be suppressed from axis title."
        )

    def test_x_axis_title_set_when_custom(self):
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result(), x_label="GDP (USD)")
        assert spec["encoding"]["x"]["axis"]["title"] == "GDP (USD)"

    def test_x_axis_has_label_expr_for_currency(self):
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result(), unit_measure="current US$")
        expr = spec["encoding"]["x"]["axis"]["labelExpr"]
        assert "$" in expr, (
            "Currency units must produce a dollar-prefixed compact number format on the bar axis."
        )

    # ── Mark visual integrity ───────────────────────────────────────────────

    def test_mark_type_is_bar(self):
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result())
        assert spec["mark"]["type"] == "bar"

    def test_bar_has_corner_radius(self):
        """Rounded bar ends are a WB visual standard and improve readability."""
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result())
        mark = spec["mark"]
        has_radius = (
            mark.get("cornerRadiusTopRight", 0) > 0
            or mark.get("cornerRadiusBottomRight", 0) > 0
        )
        assert has_radius, (
            "Bar mark must have a non-zero corner radius on the bar-end side."
        )

    def test_bar_height_scales_with_row_count(self):
        """5-row chart must be taller than 3-row chart — bars must not be hair-thin."""
        df_small = _cs_df(n_countries=3)
        df_large = _cs_df(n_countries=7)
        r = _make_bar_result(color_dim="country")
        h_small = build_cross_sectional_spec(df_small, "Test", r)["height"]
        h_large = build_cross_sectional_spec(df_large, "Test", r)["height"]
        assert h_large > h_small, (
            "Chart height must scale with row count so bars don't become hair-thin."
        )

    def test_country_label_limit_is_sufficient(self):
        """Long country names must not be truncated to ellipsis."""
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result())
        label_limit = spec["encoding"]["y"]["axis"]["labelLimit"]
        assert label_limit >= 130, (
            f"Y axis labelLimit must be >= 130 to accommodate long country names, got {label_limit}."
        )

    # ── Tooltip completeness ────────────────────────────────────────────────

    def test_tooltip_has_country_field(self):
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result(color_dim="country"))
        fields = {t["field"] for t in spec["encoding"]["tooltip"]}
        assert "country" in fields, "Bar tooltip must include 'country' field."

    def test_tooltip_has_value_field(self):
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result(color_dim="country"))
        fields = {t["field"] for t in spec["encoding"]["tooltip"]}
        assert "value" in fields, "Bar tooltip must include 'value' field."

    def test_tooltip_value_type_is_quantitative(self):
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result(color_dim="country"))
        val_tip = next(t for t in spec["encoding"]["tooltip"] if t["field"] == "value")
        assert val_tip["type"] == "quantitative"

    # ── Cardinality cap ─────────────────────────────────────────────────────

    def test_bars_capped_at_cross_sectional_max(self):
        """Avoid overwhelming the reader with too many bars."""
        from data360 import viz_config as vc
        cap = vc.HIGH_CARDINALITY_THRESHOLDS["cross_sectional_max_items"]
        df = _cs_df(n_countries=cap + 10)
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result(color_dim="country"))
        assert len(spec["data"]["values"]) <= cap, (
            f"Bar chart must cap at {cap} items to prevent an unreadable wall of bars."
        )

    # ── WB config injection ─────────────────────────────────────────────────

    def test_wb_config_is_present(self):
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result())
        assert "config" in spec

    def test_wb_config_has_label_overlap_greedy(self):
        df = _cs_df()
        spec = build_cross_sectional_spec(df, "Test", _make_bar_result())
        assert spec["config"]["axis"].get("labelOverlap") == "greedy", (
            "Bar chart axis config must set labelOverlap='greedy'."
        )


# ============================================================================
# Gap L5/B12 — _value_label_expr compact number format (non-currency)
# ============================================================================


class TestValueLabelExpr:
    """_value_label_expr must emit compact K/M/B/T suffixes for non-currency units."""

    def test_non_currency_expr_contains_trillion_tier(self):
        """Default unit must produce a trillion ('t') tier for macro indicators."""
        from data360.viz_config import _value_label_expr

        expr = _value_label_expr(None)
        assert "1e12" in expr and "'t'" in expr, (
            "_value_label_expr must include a trillion tier (1e12 -> 't') "
            "for large-number macro indicators like population."
        )

    def test_non_currency_expr_contains_billion_tier(self):
        from data360.viz_config import _value_label_expr

        expr = _value_label_expr(None)
        assert "1e9" in expr and "'b'" in expr, (
            "_value_label_expr must include a billion tier (1e9 -> 'b')."
        )

    def test_non_currency_expr_contains_million_tier(self):
        from data360.viz_config import _value_label_expr

        expr = _value_label_expr(None)
        assert "1e6" in expr and "'m'" in expr, (
            "_value_label_expr must include a million tier (1e6 -> 'm')."
        )

    def test_non_currency_expr_contains_thousand_tier(self):
        from data360.viz_config import _value_label_expr

        expr = _value_label_expr(None)
        assert "1e3" in expr and "'k'" in expr, (
            "_value_label_expr must include a thousand tier (1e3 -> 'k')."
        )

    def test_percentage_unit_still_produces_expr(self):
        """Percentage units must still get a label expression (no empty string fallback)."""
        from data360.viz_config import _value_label_expr

        expr = _value_label_expr("%")
        assert isinstance(expr, str) and len(expr) > 0, (
            "_value_label_expr must return a non-empty string for percentage units."
        )

    def test_currency_expr_has_dollar_prefix(self):
        """Currency units must prepend a '$' prefix character in the expression."""
        from data360.viz_config import _value_label_expr

        expr = _value_label_expr("current US$")
        assert "'$'" in expr or "\"$\"" in expr, (
            "Currency labelExpr must include a '$' prefix. "
            "Got: " + repr(expr[:80])
        )

    def test_expr_handles_abs_for_negative_values(self):
        """Expression must use abs(datum.value) so negative axis labels are formatted correctly."""
        from data360.viz_config import _value_label_expr

        expr = _value_label_expr(None)
        assert "abs(datum.value)" in expr, (
            "labelExpr must use abs(datum.value) for tier comparison so that "
            "negative values like -2.5B are formatted as '-2.5b', not '0'."
        )


# ============================================================================
# Gap L6 — subtitle must be a list for long country lists (AntVis T3 wrap)
# ============================================================================


class TestSubtitleWrapping:
    """build_chart_title_with_context must produce a list subtitle for multi-line wrapping."""

    def _make_df(self, countries, years=(2000, 2023)):
        import pandas as pd

        rows = []
        for c in countries:
            for y in range(years[0], years[1] + 1):
                rows.append({"country": c, "year": y, "value": 1.0})
        return pd.DataFrame(rows)

    def test_subtitle_is_list_for_single_country(self):
        """Even single-country specs must return subtitle as a list for uniform rendering."""
        df = self._make_df(["Kenya"])
        t = build_chart_title_with_context("GDP per capita", "current US$", df)
        assert isinstance(t["subtitle"], list), (
            "subtitle must always be a list so the Vega-Lite renderer can wrap text. "
            f"Got type: {type(t['subtitle'])}"
        )

    def test_subtitle_is_list_for_many_countries(self):
        """8-country subtitle must be a list to allow wrapping at 80 chars."""
        countries = [
            "South Africa", "Spain", "Greece", "Brazil",
            "Germany", "France", "Japan", "Nigeria",
        ]
        df = self._make_df(countries)
        t = build_chart_title_with_context("Unemployment rate", "%", df)
        assert isinstance(t["subtitle"], list), (
            "8-country subtitle must be a list for multi-line wrapping in the chatbot UI."
        )

    def test_subtitle_list_contains_at_least_one_nonempty_line(self):
        df = self._make_df(["Kenya", "Tanzania", "Uganda"])
        t = build_chart_title_with_context("Life expectancy", "years", df)
        assert any(line.strip() for line in t["subtitle"]), (
            "subtitle list must contain at least one non-empty string."
        )

    def test_title_text_is_string_not_list(self):
        """title.text must be a string (or list with the indicator name in it)."""
        df = self._make_df(["Kenya"])
        t = build_chart_title_with_context("My indicator", None, df)
        text = t["text"]
        if isinstance(text, list):
            assert any("My indicator" in s for s in text), (
                "title.text list must contain the indicator name."
            )
        else:
            assert "My indicator" in text


# ============================================================================
# Gap L10/B11 — negative obs_values survive unchanged in line and bar specs
# ============================================================================


class TestNegativeValuePassthrough:
    """Negative data values must reach the Vega-Lite spec without clamping or dropping."""

    def test_line_spec_y_scale_zero_false_allows_negatives(self):
        """scale.zero=False is the GoG guarantee that negative Y-values are not clipped."""
        import pandas as pd

        df = pd.DataFrame({
            "year": pd.to_datetime(["2019-01-01", "2020-01-01", "2021-01-01"]),
            "value": [-3.5, -1.2, 2.0],  # Argentina-style GDP growth with negatives
            "country": ["ARG"] * 3,
        })
        result = _make_line_result(color_dim="country")
        spec = build_temporal_single_spec(df, "GDP Growth", result)
        assert spec["encoding"]["y"]["scale"]["zero"] is False, (
            "Y scale must not be forced to zero for line charts. "
            "Negative GDP growth (-3.5%) would be invisible if zero=True."
        )

    def test_line_spec_negative_values_present_in_data(self):
        """The negative values must actually appear in the spec's inline data."""
        import pandas as pd

        df = pd.DataFrame({
            "year": pd.to_datetime(["2019-01-01", "2020-01-01"]),
            "value": [-5.2, 3.1],
            "country": ["ARG"] * 2,
        })
        result = _make_line_result(color_dim="country")
        spec = build_temporal_single_spec(df, "GDP Growth", result)
        values = [row["value"] for row in spec["data"]["values"]]
        assert any(v < 0 for v in values), (
            "Negative obs_values must survive into spec data unchanged. "
            f"All values in spec: {values}"
        )

    def test_bar_spec_x_scale_zero_true_anchors_negative_bars(self):
        """scale.zero=True is the GoG guarantee that bars always originate at 0.
        For negative values this means the bar extends *left* of the zero line,
        which is the correct visual encoding — not clipping them away."""
        import pandas as pd

        df = pd.DataFrame({
            "year": [2020, 2020, 2020],
            "value": [-4.3, -1.1, 2.8],  # mix of negative and positive
            "country": ["ARG", "BRA", "USA"],
        })
        result = _make_bar_result(color_dim="country")
        spec = build_cross_sectional_spec(df, "GDP Growth", result)
        assert spec["encoding"]["x"]["scale"]["zero"] is True, (
            "Bar X scale must have zero=True so negative bars extend left of 0 "
            "rather than disappearing. Got zero=False."
        )

    def test_bar_spec_negative_values_present_in_data(self):
        """Negative obs_values must not be dropped or clamped before reaching the spec."""
        import pandas as pd

        df = pd.DataFrame({
            "year": [2020, 2020, 2020],
            "value": [-4.3, -1.1, 2.8],
            "country": ["ARG", "BRA", "USA"],
        })
        result = _make_bar_result(color_dim="country")
        spec = build_cross_sectional_spec(df, "GDP Growth", result)
        values = [row["value"] for row in spec["data"]["values"]]
        assert any(v < 0 for v in values), (
            "Negative obs_values must survive into bar spec data unchanged. "
            f"All values in spec: {values}"
        )
