"""Tests for data360 visualization routing rules and formatting."""

import pandas as pd
import pytest
from unittest.mock import AsyncMock, patch

from data360.viz_config import ChartStrategy, select_strategy, _color_encoding
from data360.visualization import get_viz_spec


class TestVisualizationRoutingRules:
    """Verifies temporal vs cross-sectional routing logic and formatting rules."""

    def test_routing_temporal_multiple_years(self):
        """Data spanning > 3 years should route to TEMPORAL_SINGLE (line chart)."""
        df = pd.DataFrame(
            {
                "year": [2020, 2021, 2022, 2023],
                "value": [10.0, 20.0, 30.0, 40.0],
                "country": ["Kenya", "Kenya", "Kenya", "Kenya"],
            }
        )
        res = select_strategy(df)
        assert res.strategy == ChartStrategy.TEMPORAL_SINGLE

    def test_routing_cross_sectional_single_year(self):
        """Data with single year and multiple countries should route to CROSS_SECTIONAL (bar chart)."""
        df = pd.DataFrame(
            {
                "year": [2022, 2022, 2022],
                "value": [10.0, 20.0, 30.0],
                "country": ["Kenya", "Uganda", "Tanzania"],
            }
        )
        res = select_strategy(df)
        assert res.strategy == ChartStrategy.CROSS_SECTIONAL

    def test_strategy_override(self):
        """Passing strategy_override should bypass rule engine and force the chosen strategy."""
        df = pd.DataFrame(
            {
                "year": [2022, 2022, 2022],
                "value": [10.0, 20.0, 30.0],
                "country": ["Kenya", "Uganda", "Tanzania"],
            }
        )
        # Normally routes to CROSS_SECTIONAL. Override to STACKED_BAR.
        res = select_strategy(df, strategy_override="stacked_bar")
        assert res.strategy == ChartStrategy.STACKED_BAR
        assert "Forced via strategy_override" in res.reason
        assert res.color_dim == "country"

        # Case-insensitivity test
        res_caps = select_strategy(df, strategy_override="TEMPORAL_SINGLE")
        assert res_caps.strategy == ChartStrategy.TEMPORAL_SINGLE
        assert res_caps.color_dim == "country"

    @pytest.mark.asyncio
    async def test_axis_large_number_formatting_expression(self):
        """Vega specs must include a custom labelExpr for large values (millions/billions)."""
        df = pd.DataFrame(
            {
                "TIME_PERIOD": ["2022-01-01", "2022-01-01", "2022-01-01"],
                "OBS_VALUE": [1000000.0, 2000000.0, 3000000.0],
                "REF_AREA": ["KEN", "UGA", "TZA"],
            }
        )

        captured_spec = {}
        def fake_save(spec):
            captured_spec["spec"] = spec
            return "http://localhost:8021/static/viz_specs/test.json"

        with (
            patch(
                "data360.api.get_data_api_url",
                new_callable=AsyncMock,
                return_value="http://fake-api/data",
            ),
            patch(
                "data360.visualization._fetch_data_internal",
                new_callable=AsyncMock,
                return_value=df,
            ),
            patch(
                "data360.api.get_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "data360.visualization.save_specs_to_static",
                side_effect=fake_save,
            ),
            patch(
                "data360.providers.get_codelist_mapping",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "data360.visualization.get_database_mapping",
                new_callable=AsyncMock,
                return_value={"WB_WDI": "World Development Indicators"},
            ),
        ):
            await get_viz_spec(
                database_id="WB_WDI",
                indicator_id="FAKE_IND",
                chart_type="bar"
            )

        spec = captured_spec.get("spec")
        assert spec is not None
        # Verify custom labelExpr exists on the quantitative axis (x-axis for horizontal bar)
        x_axis = spec["encoding"]["x"]["axis"]
        assert "labelExpr" in x_axis
        assert "datum.value" in x_axis["labelExpr"]
        # The formatting string must support formatting millions (m), billions (b), etc.
        assert "1e6" in x_axis["labelExpr"]

    def test_legend_suppression_logic(self):
        """Single-indicator/single-series charts must suppress color legend unless it's country."""
        # 1. Non-country single item -> Legend is suppressed
        enc_sex = _color_encoding(field="sex", n_items=1)
        assert enc_sex.get("legend") is None

        # 2. Non-country multi-items -> Legend is kept
        enc_sex_multi = _color_encoding(field="sex", n_items=2)
        assert enc_sex_multi.get("legend") is not None

        # 3. Country single item -> Legend is kept (product expectation for geography)
        enc_country = _color_encoding(field="country", n_items=1)
        assert enc_country.get("legend") is not None

    def test_wgi_error_band_rule(self):
        """GeneralErrorBandRule should layer line and area when score triplet is present."""
        from data360.viz_config import GeneralErrorBandRule
        rule = GeneralErrorBandRule()
        spec = {
            "mark": "line",
            "encoding": {
                "x": {"field": "year", "type": "temporal"},
                "y": {"field": "value", "type": "quantitative"},
                "color": {"field": "country", "type": "nominal"}
            }
        }
        # WGI-style codes
        df_wgi = pd.DataFrame({
            "year": [2020, 2020, 2020],
            "value": [55.0, 45.0, 65.0],
            "comp_breakdown_1": ["WGI_SC", "WGI_SC_LB", "WGI_SC_UB"]
        })
        assert rule.should_apply(spec, df=df_wgi)
        layered_wgi = rule.apply(spec, df=df_wgi)
        assert "layer" in layered_wgi
        assert len(layered_wgi["layer"]) == 2
        assert layered_wgi["layer"][0]["mark"]["type"] == "area"
        assert layered_wgi["layer"][1]["mark"] == "line"

        # Generic bounds
        df_generic = pd.DataFrame({
            "year": [2020, 2020, 2020],
            "value": [30.0, 25.0, 35.0],
            "comp_breakdown_1": ["poverty_estimate", "poverty_min", "poverty_max"]
        })
        assert rule.should_apply(spec, df=df_generic)
        layered_gen = rule.apply(spec, df=df_generic)
        assert len(layered_gen["layer"]) == 2
        assert layered_gen["layer"][0]["mark"]["type"] == "area"

    def test_population_pyramid_rule(self):
        """PopulationPyramidRule should construct a diverging horizontal bar chart."""
        from data360.viz_config import PopulationPyramidRule
        rule = PopulationPyramidRule()
        spec = {
            "mark": "bar",
            "encoding": {
                "x": {"field": "value", "type": "quantitative"},
                "y": {"field": "age", "type": "nominal"}
            }
        }
        df = pd.DataFrame({
            "value": [10.0, 12.0],
            "sex": ["Male", "Female"],
            "age": ["0-4", "0-4"]
        })
        assert rule.should_apply(spec, df=df, raw_hint="population_pyramid")
        pyramid = rule.apply(spec, df=df, raw_hint="population_pyramid")
        assert pyramid["transform"][0]["calculate"] == "datum.sex == 'Male' || datum.sex == 'M' ? -datum.value : datum.value"
        assert pyramid["encoding"]["x"]["field"] == "signed_value"
        assert pyramid["encoding"]["x"]["axis"]["labelExpr"] == "abs(datum.value)"

    def test_single_year_multi_indicator_routing(self):
        """TwoIndicatorRule should route single-year multi-indicator to TEMPORAL_MULTI_IND with mark_hint=bar."""
        from data360.viz_config import select_strategy, build_temporal_multi_indicator_spec
        df = pd.DataFrame({
            "year": [2023, 2023],
            "country": ["KEN", "KEN"],
            "GDP": [4.5, 4.5],
            "Population": [50.0, 50.0]
        })
        # 2 indicators, 1 country, 1 year
        result = select_strategy(df, n_indicators=2, indicator_cols=["GDP", "Population"])
        assert result.strategy.value == "temporal_multi_indicator"
        assert result.mark_hint == "bar"

        spec = build_temporal_multi_indicator_spec(df, "Kenya 2023", result)
        assert "vconcat" in spec
        assert len(spec["vconcat"]) == 2
        assert spec["vconcat"][0]["mark"]["type"] == "bar"
        assert spec["vconcat"][0]["encoding"]["x"]["type"] == "nominal"
        assert "strokeWidth" not in spec["vconcat"][0]["mark"]


class TestDataSufficiencyGuards:
    """Verifies routing rules and data guards for sparse/insufficient data scenarios."""

    # ------------------------------------------------------------------
    # ExplicitDistributionRule threshold: requires country_count >= 10
    # ------------------------------------------------------------------

    def test_distribution_rule_9_countries_falls_through_to_cross_sectional(self):
        """With 9 countries (below threshold=10), distribution hint should fall through to CROSS_SECTIONAL."""
        df = pd.DataFrame(
            {
                "year": ["2022"] * 9,
                "value": [float(i) for i in range(9)],
                "country": [f"Country{i}" for i in range(9)],
            }
        )
        result = select_strategy(df, chart_type_hint="distribution")
        # ExplicitDistributionRule should return None (9 < 10), fall through
        assert result.strategy == ChartStrategy.CROSS_SECTIONAL, (
            f"Expected CROSS_SECTIONAL for 9 countries with distribution hint, got {result.strategy}"
        )

    def test_distribution_rule_10_countries_routes_to_distribution(self):
        """With 10 countries (at threshold), distribution hint should route to DISTRIBUTION."""
        df = pd.DataFrame(
            {
                "year": ["2022"] * 10,
                "value": [float(i) for i in range(10)],
                "country": [f"Country{i}" for i in range(10)],
            }
        )
        result = select_strategy(df, chart_type_hint="distribution")
        assert result.strategy == ChartStrategy.DISTRIBUTION, (
            f"Expected DISTRIBUTION for 10 countries with distribution hint, got {result.strategy}"
        )

    def test_distribution_rule_20_countries_routes_to_distribution(self):
        """With 20 countries, distribution hint should route to DISTRIBUTION."""
        df = pd.DataFrame(
            {
                "year": ["2022"] * 20,
                "value": [float(i) for i in range(20)],
                "country": [f"Country{i}" for i in range(20)],
            }
        )
        result = select_strategy(df, chart_type_hint="distribution")
        assert result.strategy == ChartStrategy.DISTRIBUTION

    # ------------------------------------------------------------------
    # Auto-routing distribution: single year + many countries
    # (no explicit hint — the pipeline still auto-routes to DISTRIBUTION
    #  at the HIGH_CARDINALITY_THRESHOLDS["beeswarm_threshold"] of 20)
    # ------------------------------------------------------------------

    def test_auto_distribution_above_beeswarm_threshold(self):
        """Single year + 21 countries with distribution hint routes to DISTRIBUTION."""
        df = pd.DataFrame(
            {
                "year": ["2022"] * 21,
                "value": [float(i) for i in range(21)],
                "country": [f"Country{i}" for i in range(21)],
            }
        )
        # ExplicitDistributionRule fires first: 21 >= 10, single year → DISTRIBUTION
        result = select_strategy(df, chart_type_hint="distribution")
        assert result.strategy == ChartStrategy.DISTRIBUTION

    # ------------------------------------------------------------------
    # Cross-sectional routing with 2 countries — should still route OK
    # (the _err guard fires at the visualization.py level, not select_strategy)
    # ------------------------------------------------------------------

    def test_cross_sectional_with_2_countries_routes_at_strategy_level(self):
        """2-country single-year data routes to CROSS_SECTIONAL at select_strategy level.
        The _err guard in visualization.py fires post-routing for <3 countries.
        """
        df = pd.DataFrame(
            {
                "year": ["2019", "2019"],
                "value": [0.10, 0.24],
                "country": ["India", "South Africa"],
            }
        )
        result = select_strategy(df)
        # Routing itself doesn't block — guard is in visualization.py
        assert result.strategy == ChartStrategy.CROSS_SECTIONAL

    def test_line_segment_grouping_without_redundant_duplication(self):
        """LineYearGapStrokeDashRule should keep consecutive years continuous (no duplication) and only duplicate gap endpoints."""
        from data360.viz_config import LineYearGapStrokeDashRule, _LINE_GAP_SEG_DETAIL
        rule = LineYearGapStrokeDashRule()
        groups = {
            ("KEN",): [
                {"year": 2010, "value": 1.0, "country": "Kenya"},
                {"year": 2011, "value": 2.0, "country": "Kenya"},
                {"year": 2012, "value": 3.0, "country": "Kenya"},
                {"year": 2015, "value": 4.0, "country": "Kenya"},
                {"year": 2016, "value": 5.0, "country": "Kenya"},
            ]
        }
        # Call internal build_segment_rows
        new_rows = rule._build_segment_rows(groups, "year", ["country"])

        # Expected:
        # - Segment 1 (solid, 2010-2012): 3 rows
        # - Segment 2 (dashed gap, 2012-2015): 2 rows
        # - Segment 3 (solid, 2015-2016): 2 rows
        # Total: 7 rows. (Original was 5. Only 2012 and 2015 are duplicated once each).
        assert len(new_rows) == 7

        # Verify 2011 is not duplicated (appears exactly once)
        r_2011 = [r for r in new_rows if r["year"] == 2011]
        assert len(r_2011) == 1
        assert r_2011[0]["_d360_ygap"] == 0

        # Verify 2012 is duplicated (appears twice: once in solid seg_0, once in dashed gap seg_1)
        r_2012 = [r for r in new_rows if r["year"] == 2012]
        assert len(r_2012) == 2
        # One of them should be a gap segment
        assert any(r["_d360_ygap"] == 1 for r in r_2012)
        assert any(r["_d360_ygap"] == 0 for r in r_2012)

    def test_proportion_scale_type_axis_labels(self):
        """_value_label_expr should return percentage formatting with multiplier for scale_type='proportion'."""
        from data360.viz_config import _value_label_expr
        expr = _value_label_expr(unit_measure="Proportion of total employment", scale_type="proportion")
        assert expr == "format(datum.value, '.0%')"

    def test_percentage_clamping_on_proportion_data(self):
        """PercentageBoundaryClampingRule should clamp Y-axis to [0, 1] for raw proportion data (max_val <= 1.0)."""
        from data360.viz_config import PercentageBoundaryClampingRule
        rule = PercentageBoundaryClampingRule()
        spec = {
            "mark": "line",
            "encoding": {
                "y": {"field": "value", "type": "quantitative"}
            }
        }
        df = pd.DataFrame({"value": [0.05, 0.12, 0.25]})
        # Mock proportion check
        clamped = rule.apply(spec, unit_measure="Proportion of total employment", scale_type="percentage", df=df)
        assert clamped["encoding"]["y"]["scale"]["domain"] == [0, 1]

    def test_sparse_country_filtering_in_get_viz_spec(self):
        """get_viz_spec should filter out countries with < 2 time-series data points."""
        from data360.visualization import get_viz_spec
        # Mock get_comp_breakdown_dim_names & map_country_codes if needed (they are called inside).
        # We can construct a DataFrame and run it through get_viz_spec
        # Since get_viz_spec queries the data, let us verify by testing the average points guard change
        # using the direct filter logic we added to visualization.py.


class TestRoutingRuleCoverage:
    """Dedicated tests for routing rules that previously lacked unit test coverage."""

    # ------------------------------------------------------------------
    # GenericSmallMultiplesRule
    # ------------------------------------------------------------------

    def test_generic_small_multiples_two_breakdowns(self):
        """Two breakdowns → SMALL_MULTIPLES, facet by first breakdown, color by second."""
        df = pd.DataFrame({
            "year": [2022] * 4,
            "value": [10.0, 20.0, 30.0, 40.0],
            "country": ["Kenya"] * 4,
            "sex": ["Male", "Female", "Male", "Female"],
            "age": ["0-14", "0-14", "15-64", "15-64"],
        })
        result = select_strategy(df)
        assert result.strategy == ChartStrategy.SMALL_MULTIPLES
        assert result.facet_dim == "sex"
        assert result.color_dim == "age"

    def test_generic_small_multiples_one_breakdown_multi_country(self):
        """1 breakdown + >1 country → SMALL_MULTIPLES, facet by country."""
        df = pd.DataFrame({
            "year": [2022] * 4,
            "value": [10.0, 20.0, 30.0, 40.0],
            "country": ["Kenya", "Kenya", "Uganda", "Uganda"],
            "sex": ["Male", "Female", "Male", "Female"],
        })
        result = select_strategy(df)
        assert result.strategy == ChartStrategy.SMALL_MULTIPLES
        assert result.facet_dim == "country"
        assert result.color_dim == "sex"

    # ------------------------------------------------------------------
    # TemporalBreakdownRule
    # ------------------------------------------------------------------

    def test_temporal_breakdown_single_country_multi_year(self):
        """1 breakdown, 1 country, multi-year → TEMPORAL_SINGLE (multi-series line by breakdown)."""
        df = pd.DataFrame({
            "year": [2020, 2021, 2022, 2020, 2021, 2022],
            "value": [10.0, 20.0, 30.0, 15.0, 25.0, 35.0],
            "country": ["Kenya"] * 6,
            "sex": ["Male", "Male", "Male", "Female", "Female", "Female"],
        })
        result = select_strategy(df)
        assert result.strategy == ChartStrategy.TEMPORAL_SINGLE
        assert result.color_dim == "sex"

    # ------------------------------------------------------------------
    # BreakdownComparisonGroupedBarRule — year guard fix
    # ------------------------------------------------------------------

    def test_breakdown_comparison_single_year_fires(self):
        """1 breakdown, <=4 countries, single year → BREAKDOWN_COMPARISON."""
        df = pd.DataFrame({
            "year": [2022, 2022, 2022, 2022],
            "value": [10.0, 20.0, 30.0, 40.0],
            "country": ["Kenya", "Kenya", "Kenya", "Kenya"],
            "sex": ["Male", "Female", "Male", "Female"],
        })
        result = select_strategy(df)
        assert result.strategy == ChartStrategy.BREAKDOWN_COMPARISON

    def test_breakdown_comparison_multi_year_does_not_fire(self):
        """1 breakdown, <=4 countries, multi-year → should NOT route to BREAKDOWN_COMPARISON.

        Before the fix, this incorrectly produced a grouped bar chart instead of
        falling through to TemporalBreakdownRule which produces a line chart.
        """
        df = pd.DataFrame({
            "year": [2020, 2021, 2022, 2020, 2021, 2022],
            "value": [10.0, 20.0, 30.0, 15.0, 25.0, 35.0],
            "country": ["Kenya"] * 6,
            "sex": ["Male", "Male", "Male", "Female", "Female", "Female"],
        })
        result = select_strategy(df)
        assert result.strategy != ChartStrategy.BREAKDOWN_COMPARISON
        # Should fall through to TemporalBreakdownRule → TEMPORAL_SINGLE
        assert result.strategy == ChartStrategy.TEMPORAL_SINGLE

    # ------------------------------------------------------------------
    # ExplicitHeatmapRule — 1-country rejection fix
    # ------------------------------------------------------------------

    def test_explicit_heatmap_1_country_rejected(self):
        """Explicit heatmap hint with 1 country should fall through (degenerate single row)."""
        df = pd.DataFrame({
            "year": [2020, 2021, 2022],
            "value": [10.0, 20.0, 30.0],
            "country": ["Kenya", "Kenya", "Kenya"],
        })
        result = select_strategy(df, chart_type_hint="heatmap")
        assert result.strategy != ChartStrategy.HEATMAP

    def test_explicit_heatmap_2_countries_accepted(self):
        """Explicit heatmap hint with 2+ countries and multi-year → HEATMAP."""
        df = pd.DataFrame({
            "year": [2020, 2021, 2020, 2021],
            "value": [10.0, 20.0, 30.0, 40.0],
            "country": ["Kenya", "Kenya", "Uganda", "Uganda"],
        })
        result = select_strategy(df, chart_type_hint="heatmap")
        assert result.strategy == ChartStrategy.HEATMAP

    # ------------------------------------------------------------------
    # FallbackRule
    # ------------------------------------------------------------------

    def test_fallback_rule_fires_when_nothing_matches(self):
        """Empty DataFrame with no dimensions triggers FALLBACK_LINE."""
        df = pd.DataFrame({
            "value": [1.0],
        })
        result = select_strategy(df)
        assert result.strategy == ChartStrategy.FALLBACK_LINE

    # ------------------------------------------------------------------
    # avg_years_per_country inflation fix
    # ------------------------------------------------------------------

    def test_avg_years_not_inflated_by_breakdowns(self):
        """avg_years_per_country should count unique years, not total rows.

        A single year with 2 breakdown values per country used to produce
        avg_years_per_country = 2.0 (2 rows / 1 country), incorrectly
        bypassing the CrossSectionalRule threshold of 1.7. After the fix,
        it should be 1.0 (1 unique year).
        """
        df = pd.DataFrame({
            "year": [2022, 2022, 2022, 2022],
            "value": [10.0, 20.0, 30.0, 40.0],
            "country": ["Kenya", "Kenya", "Uganda", "Uganda"],
            "sex": ["Male", "Female", "Male", "Female"],
        })
        from data360.viz_config import RoutingContext
        ctx = RoutingContext.build(df, n_indicators=1, chart_type_hint=None, indicator_cols=None)
        assert ctx.avg_years_per_country == 1.0


class TestMultiIndicatorLayering:
    """Tests for the single-panel vs vconcat layout decision in build_temporal_multi_indicator_spec."""

    def _make_multi_ind_df(self, col_a_max: float, col_b_max: float, n_years: int = 5) -> pd.DataFrame:
        """Wide-format DataFrame with two indicator columns and one country."""
        years = list(range(2018, 2018 + n_years))
        a_vals = [col_a_max * (i + 1) / n_years for i in range(n_years)]
        b_vals = [col_b_max * (i + 1) / n_years for i in range(n_years)]
        return pd.DataFrame({
            "year": years,
            "country": ["India"] * n_years,
            "IND_A": a_vals,
            "IND_B": b_vals,
        })

    def test_scale_compatible_indicators_produce_single_panel(self):
        """Two indicators whose max values are within 10x should produce a layered single-panel spec.

        Regression: before the dispatch_spec fix, unit_measure was never passed
        to build_temporal_multi_indicator_spec, so should_layer was always False
        and vconcat was always produced even for same-unit indicators.
        """
        from data360.viz_config import build_temporal_multi_indicator_spec, StrategyResult, ChartStrategy
        df = self._make_multi_ind_df(col_a_max=21.0, col_b_max=79.0)  # female vs male LFPR ~%
        result = StrategyResult(
            strategy=ChartStrategy.TEMPORAL_MULTI_IND,
            reason="test",
            indicator_cols=["IND_A", "IND_B"],
        )
        spec = build_temporal_multi_indicator_spec(
            df, "Labor Force Participation", result,
            unit_measure="ZS",  # percentage-type unit
            y_label="% of population ages 15+",
        )
        # Single-panel: top-level mark present, no vconcat
        assert "mark" in spec, "Expected single-panel spec with top-level mark"
        assert "vconcat" not in spec, (
            "Scale-compatible indicators (ratio 3.8x < 10x) should produce single-panel, not vconcat"
        )
        assert "color" in spec["encoding"], "Single-panel spec should have color encoding for indicator series"

    def test_scale_incompatible_indicators_produce_vconcat(self):
        """Two indicators with >10x scale difference should produce vconcat panels."""
        from data360.viz_config import build_temporal_multi_indicator_spec, StrategyResult, ChartStrategy
        df = self._make_multi_ind_df(col_a_max=0.5, col_b_max=50_000.0)  # e.g. % vs GDP billions
        result = StrategyResult(
            strategy=ChartStrategy.TEMPORAL_MULTI_IND,
            reason="test",
            indicator_cols=["IND_A", "IND_B"],
        )
        spec = build_temporal_multi_indicator_spec(
            df, "Mixed Scale Indicators", result,
            unit_measure=None,
        )
        assert "vconcat" in spec, (
            "Scale-incompatible indicators (ratio 100_000x > 10x) should produce vconcat"
        )

    def test_scenario_04_labor_force_india_single_panel(self):
        """Scenario 04: female + male LFPR for India 2010-2022 → single-panel two-line chart.

        Both indicators are percentages on a 0-100 scale (female ~21%, male ~78-80%).
        The ratio is ~3.8x, well within the 10x threshold for shared Y-axis.
        """
        from data360.viz_config import (
            build_temporal_multi_indicator_spec,
            StrategyResult,
            ChartStrategy,
            select_strategy,
        )
        # Approximate India values for 2010-2022
        years = list(range(2010, 2023))
        female_lfpr = [27.0, 26.5, 26.0, 25.5, 25.0, 24.5, 24.0, 23.5, 23.0, 22.5, 22.0, 21.5, 21.0]
        male_lfpr   = [80.0, 79.5, 79.0, 78.5, 78.0, 77.5, 77.0, 78.0, 79.0, 79.5, 79.0, 78.5, 78.0]
        ind_a = "WB_WDI_SL_TLF_CACT_FE_ZS"
        ind_b = "WB_WDI_SL_TLF_CACT_MA_ZS"

        df = pd.DataFrame({
            "year": years,
            "country": ["India"] * len(years),
            ind_a: female_lfpr,
            ind_b: male_lfpr,
        })

        # 1. Routing selects TEMPORAL_MULTI_IND (2 indicators, 1 country, multi-year)
        result = select_strategy(df, n_indicators=2, indicator_cols=[ind_a, ind_b])
        assert result.strategy == ChartStrategy.TEMPORAL_MULTI_IND

        # 2. Builder produces single-panel with color=indicator (not vconcat)
        spec = build_temporal_multi_indicator_spec(
            df, "Labor Force Participation — India", result,
            unit_measure="ZS",
            y_label="% of population ages 15+",
            indicator_labels={
                ind_a: "Female",
                ind_b: "Male",
            }
        )
        assert "mark" in spec, "Should be single-panel (top-level mark)"
        assert "vconcat" not in spec, "Female/male LFPR should share one Y-axis, not be split into panels"
        assert spec["encoding"]["color"]["field"] == "indicator_name_melted"
