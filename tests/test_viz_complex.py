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

    def test_cross_sectional_single_year_few_countries(self):
        df = _cs_df(n_countries=5)
        r = select_strategy(df)
        assert r.strategy == ChartStrategy.CROSS_SECTIONAL

    def test_distribution_single_year_many_countries(self):
        df = _cs_df(n_countries=12)
        r = select_strategy(df)
        assert r.strategy == ChartStrategy.DISTRIBUTION

    def test_breakdown_single_disagg(self):
        df = _sex_df(countries=2)
        r = select_strategy(df)
        assert r.strategy == ChartStrategy.BREAKDOWN_COMPARISON
        assert r.color_dim == "sex"

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

    def test_correlation_temporal_two_indicators_multi_year(self):
        df = _two_ind_ts_df()
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = select_strategy(df, n_indicators=2, indicator_cols=ind_cols)
        assert r.strategy == ChartStrategy.CORRELATION_TEMPORAL

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
        assert "Kenya" in t["subtitle"]
        assert "2020-2021" in t["subtitle"]
        assert "current US$" in t["subtitle"]


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
    def test_small_multiples_has_facet_key(self):
        df = _sex_df(countries=6)
        r = self._result(
            ChartStrategy.SMALL_MULTIPLES, color_dim="sex", facet_dim="country"
        )
        spec = build_small_multiples_spec(df, "Test", r)
        assert "facet" in spec

    def test_small_multiples_columns_capped_at_3(self):
        df = _sex_df(countries=6)
        r = self._result(
            ChartStrategy.SMALL_MULTIPLES, color_dim="sex", facet_dim="country"
        )
        spec = build_small_multiples_spec(df, "Test", r)
        assert spec["facet"]["columns"] <= 3

    # correlation
    def test_correlation_mark_is_circle(self):
        df = _two_ind_df()
        r = self._result(
            ChartStrategy.CORRELATION,
            color_dim="country",
            indicator_cols=["gdp_per_capita", "life_expectancy"],
        )
        spec = build_correlation_spec(df, "Test", r)
        assert spec["mark"]["type"] == "circle"

    def test_correlation_x_y_from_indicator_cols(self):
        df = _two_ind_df()
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = self._result(
            ChartStrategy.CORRELATION, color_dim="country", indicator_cols=ind_cols
        )
        spec = build_correlation_spec(df, "Test", r)
        assert spec["encoding"]["x"]["field"] == "gdp_per_capita"
        assert spec["encoding"]["y"]["field"] == "life_expectancy"

    def test_correlation_axis_labels_from_indicator_labels(self):
        df = _two_ind_df()
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = self._result(
            ChartStrategy.CORRELATION, color_dim="country", indicator_cols=ind_cols
        )
        labels = {"gdp_per_capita": "GDP (USD)", "life_expectancy": "Life Exp (years)"}
        spec = build_correlation_spec(df, "Test", r, indicator_labels=labels)
        assert spec["encoding"]["x"]["axis"]["title"] == "GDP (USD)"
        assert spec["encoding"]["y"]["axis"]["title"] == "Life Exp (years)"

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
        assert len(spec["layer"]) == 2

    def test_temporal_multi_indicator_independent_y_scale(self):
        df = _two_ind_ts_df()[lambda x: x["country"] == "CountryA"]
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = self._result(ChartStrategy.TEMPORAL_MULTI_IND, indicator_cols=ind_cols)
        spec = build_temporal_multi_indicator_spec(df, "Test", r)
        assert spec.get("resolve", {}).get("scale", {}).get("y") == "independent"

    def test_temporal_multi_indicator_each_layer_different_color(self):
        df = _two_ind_ts_df()[lambda x: x["country"] == "CountryA"]
        ind_cols = ["gdp_per_capita", "life_expectancy"]
        r = self._result(ChartStrategy.TEMPORAL_MULTI_IND, indicator_cols=ind_cols)
        spec = build_temporal_multi_indicator_spec(df, "Test", r)
        colors = [layer["mark"]["color"] for layer in spec["layer"]]
        assert len(set(colors)) == 2  # distinct colors

    def test_temporal_multi_indicator_staggered_y_axes_for_four_series(self):
        df = _four_ind_ts_df()
        ind_cols = ["ind_a", "ind_b", "ind_c", "ind_d"]
        r = self._result(ChartStrategy.TEMPORAL_MULTI_IND, indicator_cols=ind_cols)
        spec = build_temporal_multi_indicator_spec(df, "Test", r)
        assert len(spec["layer"]) == 4
        assert spec["width"] == 680
        axes = [layer["encoding"]["y"]["axis"] for layer in spec["layer"]]
        assert axes[0]["orient"] == "left"
        assert axes[1]["orient"] == "right"
        assert "offset" not in axes[1]
        assert axes[2]["orient"] == "right" and axes[2]["offset"] == 50
        assert axes[3]["orient"] == "right" and axes[3]["offset"] == 100

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
            layer_enc = None
            if "layer" in spec:
                # last layer has tooltips
                layer_enc = spec["layer"][-1].get("encoding", {})
            check_enc = layer_enc or enc
            assert "tooltip" in check_enc, (
                f"Missing tooltip in spec: {spec.get('title')}"
            )


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
        assert spec["encoding"]["x"]["axis"]["title"] == "GDP (USD)"
        assert spec["encoding"]["y"]["axis"]["title"] == "Life Exp"

    def test_multi_ind_layer_y_axis_per_indicator(self):
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
        y_titles = [layer["encoding"]["y"]["axis"]["title"] for layer in spec["layer"]]
        assert "GDP (USD)" in y_titles
        assert "Life Exp (yr)" in y_titles


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
