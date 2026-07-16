import os
import json
import pytest
import pandas as pd
from deepeval import assert_test
from deepeval.test_case import LLMTestCase, SingleTurnParams
from deepeval.metrics import GEval

# Add project root to path
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.data360.viz_config import select_strategy, dispatch_spec

# Define the G-Eval metric for visual grammar alignment
grammar_of_graphics_metric = GEval(
    name="Grammar of Graphics & FT Visual Vocabulary Correctness",
    criteria="""
    Determine if the Vega-Lite JSON specification maps optimally to the retrieved data shape based on the Financial Times Visual Vocabulary:
    1. Single-indicator multi-year trends MUST map to a continuous line chart.
    2. Multi-indicator datasets with incompatible units MUST map to separate vertical subplot panels sharing a synchronized timeline (no combined dual-Y layouts on a single grid).
    3. Single-year multi-country datasets MUST map to horizontal bars to allow label space, or route X-axis to country to avoid summing values.
    4. Gaps in reporting years MUST use dashed lines.
    5. Single-year nominal charts MUST have their 'year' field parsed as a string to prevent JS Date auto-parsing errors.
    """,
    evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.INPUT],
    evaluation_steps=[
        "Inspect the input query and simulated dataframe shape (number of indicators, countries, years, and breakdowns).",
        "Inspect the actual output Vega-Lite JSON specification.",
        "Check if the X/Y encoding channels, mark types, facets, and resolving settings are optimal.",
        "Deduct points if values are overlaid in a single bar on a nominal X-axis without proper country separation.",
        "Verify that scale formatting, title styling, and tooltips match standard specifications."
    ],
    threshold=0.8
)

def run_routing_test(
    df: pd.DataFrame,
    n_indicators: int,
    indicator_cols: list[str],
    query: str,
    expected_description: str,
    chart_type_hint: str | None = None,
    raw_unit: str | None = None,
    raw_unit_mult: int = 0,
):
    """Helper function to run viz routing and return the compiled spec string."""
    # 1. Execute routing engine
    res = select_strategy(
        df,
        n_indicators=n_indicators,
        indicator_cols=indicator_cols,
        chart_type_hint=chart_type_hint,
        raw_unit=raw_unit,
        raw_unit_mult=raw_unit_mult
    )

    # 2. Compile baseline spec
    spec = dispatch_spec(
        res.strategy,
        df,
        "Visual Evaluation Test Chart",
        res,
        indicator_labels={col: col for col in indicator_cols},
        unit_measure=raw_unit,
    )

    # 3. Apply post-processing rules
    import inspect
    from src.data360.viz_config import POST_PROCESSING_RULES

    for rule in POST_PROCESSING_RULES:
        sig = inspect.signature(rule.apply)
        kwargs = {}
        if "scale_type" in sig.parameters:
            kwargs["scale_type"] = res.scale_type
        if "unit_mult" in sig.parameters:
            kwargs["unit_mult"] = res.unit_mult
        if "df" in sig.parameters:
            kwargs["df"] = df
        if "raw_hint" in sig.parameters:
            kwargs["raw_hint"] = res.raw_hint

        spec = rule.apply(
            spec,
            data_frequency=None,
            unit_measure=raw_unit,
            **kwargs
        )

    # 4. Create test case for DeepEval
    test_case = LLMTestCase(
        input=f"Query: '{query}' | Expected layout: {expected_description}",
        actual_output=json.dumps(spec, indent=2)
    )

    # 5. Assert correctness using G-Eval
    assert_test(test_case, [grammar_of_graphics_metric])


def test_scenario_a_multi_indicator_single_year():
    # 3 indicators, 5 countries, 1 year
    df = pd.DataFrame({
        "year": [2022] * 15,
        "country": ["BRA", "ARG", "MEX", "COL", "CHL"] * 3,
        "indicator_id": ["GDP", "Population", "Inflation"] * 5,
        "value": [1.2, 50.0, 4.5] * 5
    })
    df_wide = df.pivot(index=["year", "country"], columns="indicator_id", values="value").reset_index()

    run_routing_test(
        df=df_wide,
        n_indicators=3,
        indicator_cols=["GDP", "Population", "Inflation"],
        query="Plot GDP, Population, and Inflation of Latin American countries in 2022",
        expected_description="Grouped or faceted bar charts displaying countries side-by-side on the X-axis."
    )


def test_scenario_b_demographic_breakdown():
    # 1 indicator, 1 country, 1 breakdown (sex), 1 year
    df = pd.DataFrame({
        "year": [2022, 2022],
        "country": ["KEN", "KEN"],
        "sex": ["Male", "Female"],
        "value": [45.0, 55.0]
    })

    run_routing_test(
        df=df,
        n_indicators=1,
        indicator_cols=["value"],
        query="Compare population of Kenya by sex in 2022",
        expected_description="Grouped bar chart comparing Male vs Female population sizes."
    )


def test_scenario_c_explicit_scatter_correlation():
    # 2 indicators, 5 countries, 1 year
    df = pd.DataFrame({
        "year": [2022] * 10,
        "country": ["BRA", "ARG", "MEX", "COL", "CHL"] * 2,
        "indicator_id": ["GDP_growth", "Inflation"] * 5,
        "value": [1.5, 4.2, 2.0, 3.8, -0.5, 6.0, 3.2, 5.1, 1.8, 3.9]
    })
    df_wide = df.pivot(index=["year", "country"], columns="indicator_id", values="value").reset_index()

    run_routing_test(
        df=df_wide,
        n_indicators=2,
        indicator_cols=["GDP_growth", "Inflation"],
        query="Plot scatter correlation between GDP growth and Inflation in Latin America for 2022",
        expected_description="Scatterplot with points representing countries, GDP growth on X-axis, and Inflation on Y-axis.",
        chart_type_hint="scatter"
    )


def test_scenario_d_dual_y_axis_mismatch():
    # 2 indicators with mixed units, 1 country, multi-year
    df = pd.DataFrame({
        "year": [2018, 2019, 2020, 2021, 2022],
        "country": ["ZAF"] * 5,
        "GDP_growth": [2.1, 1.5, -6.0, 4.9, 2.0],
        "GDP_per_capita": [6500, 6600, 5800, 6200, 6300]
    })

    run_routing_test(
        df=df,
        n_indicators=2,
        indicator_cols=["GDP_growth", "GDP_per_capita"],
        query="Plot GDP growth and GDP per capita of South Africa from 2018 to 2022",
        expected_description="Faceted line subplots with independent Y-axes sharing a synchronized timeline."
    )


def test_scenario_e_population_pyramid():
    # 1 indicator, 1 country, 1 year, sex & age breakdowns
    df = pd.DataFrame({
        "year": [2022] * 6,
        "country": ["IND"] * 6,
        "sex": ["Male", "Female", "Male", "Female", "Male", "Female"],
        "age": ["0-14", "0-14", "15-64", "15-64", "65+", "65+"],
        "value": [300, 280, 700, 680, 80, 90]
    })

    run_routing_test(
        df=df,
        n_indicators=1,
        indicator_cols=["value"],
        query="Plot a population pyramid for India in 2022",
        expected_description="Diverging horizontal bar chart (population pyramid) with Male values on one side (negative signed_value) and Female values on the other side.",
        chart_type_hint="population_pyramid"
    )


def test_scenario_f_general_error_band():
    # 1 indicator, 1 country, multi-year, with est, lower, upper confidence intervals
    df = pd.DataFrame({
        "year": [2020, 2020, 2020, 2021, 2021, 2021, 2022, 2022, 2022],
        "country": ["USA"] * 9,
        "comp_breakdown_1": ["est", "lower", "upper", "est", "lower", "upper", "est", "lower", "upper"],
        "value": [10.0, 9.2, 10.8, 11.2, 10.5, 11.9, 12.5, 11.8, 13.2]
    })

    run_routing_test(
        df=df,
        n_indicators=1,
        indicator_cols=["value"],
        query="Show USDA crop estimate trend with confidence intervals from 2020 to 2022",
        expected_description="A line chart representing the 'est' values layered on top of a shaded area (error band) representing the 'lower' and 'upper' bounds.",
    )


def test_scenario_g_skewness_log_scale():
    # 1 indicator, multi-country, 1 year, highly skewed values (e.g. GDP in billions)
    df = pd.DataFrame({
        "year": [2022] * 6,
        "country": ["USA", "CHN", "LUX", "ISL", "MLT", "TUV"],
        "value": [25000.0, 18000.0, 85.0, 28.0, 17.0, 0.06]
    })

    run_routing_test(
        df=df,
        n_indicators=1,
        indicator_cols=["value"],
        query="Plot GDP of select countries in 2022",
        expected_description="A bar chart with log-scaled axis to account for extremely skewed distribution.",
    )


def test_scenario_h_percentage_boundary_clamping():
    # 1 indicator, multi-year, percentage units
    df = pd.DataFrame({
        "year": [2018, 2019, 2020, 2021, 2022],
        "country": ["DEU"] * 5,
        "value": [98.5, 99.2, 100.0, 100.0, 100.0]
    })

    run_routing_test(
        df=df,
        n_indicators=1,
        indicator_cols=["value"],
        query="Plot employment rate percentage in Germany",
        expected_description="Line chart with percentage formatting and Y-axis scale domain clamped to percentage boundaries [0, 100].",
        raw_unit="%"
    )


def test_scenario_i_reporting_gap_dashing():
    # 1 indicator, 1 country, timeline with a gap (e.g. 2018, 2019, then 2022)
    df = pd.DataFrame({
        "year": [2018, 2019, 2022],
        "country": ["NPL"] * 3,
        "value": [45.0, 48.0, 52.0]
    })

    run_routing_test(
        df=df,
        n_indicators=1,
        indicator_cols=["value"],
        query="Plot population access to electricity in Nepal",
        expected_description="A line chart where segment connecting 2019 to 2022 is dashed to denote a reporting gap.",
    )


def test_scenario_j_choropleth_map():
    df = pd.DataFrame({
        "year": [2022] * 5,
        "country": ["USA", "CAN", "MEX", "GBR", "FRA"],
        "value": [12.0, 14.5, 8.2, 11.0, 13.1]
    })

    run_routing_test(
        df=df,
        n_indicators=1,
        indicator_cols=["value"],
        query="Show a world map of unemployment rate in 2022",
        expected_description="Choropleth map visualizing countries shaded by unemployment rate values.",
        chart_type_hint="map"
    )


def test_scenario_k_heatmap():
    # Multi-country, multi-year matrix
    df = pd.DataFrame({
        "year": [2020, 2021, 2022] * 4,
        "country": ["USA", "USA", "USA", "GBR", "GBR", "GBR", "FRA", "FRA", "FRA", "DEU", "DEU", "DEU"],
        "value": [3.1, 4.2, 5.0, 2.8, 3.9, 4.5, 4.0, 4.8, 5.2, 3.5, 4.0, 4.9]
    })

    run_routing_test(
        df=df,
        n_indicators=1,
        indicator_cols=["value"],
        query="Show a heatmap matrix of inflation rates across G4 countries",
        expected_description="A dense heatmap grid displaying country vs year.",
        chart_type_hint="heatmap"
    )


def test_scenario_l_small_multiples_2d_grid():
    # 1 indicator, multi-year, breakdown with 4 categories (high cardinality)
    df = pd.DataFrame({
        "year": [2020, 2021, 2022] * 4,
        "country": ["BRA"] * 12,
        "comp_breakdown_1": ["Low Income", "Low Income", "Low Income",
                             "Lower Middle", "Lower Middle", "Lower Middle",
                             "Upper Middle", "Upper Middle", "Upper Middle",
                             "High Income", "High Income", "High Income"],
        "value": [10, 12, 14, 25, 27, 30, 45, 48, 50, 75, 78, 82]
    })

    run_routing_test(
        df=df,
        n_indicators=1,
        indicator_cols=["value"],
        query="Show income group breakdown trends for Brazil",
        expected_description="Small multiples chart structured in a 2D facet grid (2 columns) showing each income group's trend over time.",
        chart_type_hint="facet"
    )
