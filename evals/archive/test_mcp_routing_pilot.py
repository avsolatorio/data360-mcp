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
    2. Multi-indicator datasets with incompatible units MUST map to separate vertical subplot panels sharing a synchronized timeline.
    3. Single-year multi-country datasets MUST map to horizontal bars to allow label space, or route X-axis to country to avoid summing values.
    """,
    evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.INPUT],
    evaluation_steps=[
        "Inspect the input query and simulated dataframe shape.",
        "Inspect the actual output Vega-Lite JSON specification.",
        "Check if the X/Y encoding channels, mark types, facets, and resolving settings are optimal."
    ],
    threshold=0.8
)

def run_pilot_test(
    df: pd.DataFrame,
    n_indicators: int,
    indicator_cols: list[str],
    query: str,
    expected_description: str,
    chart_type_hint: str | None = None,
    raw_unit: str | None = None,
):
    # 1. Execute routing engine
    res = select_strategy(
        df,
        n_indicators=n_indicators,
        indicator_cols=indicator_cols,
        chart_type_hint=chart_type_hint,
        raw_unit=raw_unit
    )

    # 2. Compile baseline spec
    spec = dispatch_spec(
        res.strategy,
        df,
        "Pilot Evaluation Test Chart",
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

    # Print the generated specification for manual critique
    print(f"\n========================================================")
    print(f"PILOT TEST: {query}")
    print(f"Routed Strategy: {res.strategy} ({res.reason})")
    print(f"========================================================")
    print(json.dumps(spec, indent=2))
    print(f"========================================================\n")

    # 4. Create test case for DeepEval
    test_case = LLMTestCase(
        input=f"Query: '{query}' | Expected layout: {expected_description}",
        actual_output=json.dumps(spec, indent=2)
    )

    # 5. Assert correctness using G-Eval
    assert_test(test_case, [grammar_of_graphics_metric])


def test_pilot_example_1_line_hint_single_year():
    # 1 indicator, 5 countries, 1 year, user explicitly requests a line chart
    df = pd.DataFrame({
        "year": [2022] * 5,
        "country": ["BRA", "ARG", "MEX", "COL", "CHL"],
        "value": [1.5, 2.0, -0.5, 3.2, 1.8]
    })

    run_pilot_test(
        df=df,
        n_indicators=1,
        indicator_cols=["value"],
        query="Plot line chart of Latin American GDP growth in 2022",
        expected_description="Horizontal bar chart (due to single year of data, overriding the line hint).",
        chart_type_hint="line"
    )


def test_pilot_example_2_bar_hint_multi_year():
    # 1 indicator, 1 country, 5 years, user explicitly requests a bar chart
    df = pd.DataFrame({
        "year": [2018, 2019, 2020, 2021, 2022],
        "country": ["USA"] * 5,
        "value": [2.5, 2.8, -3.4, 5.7, 2.1]
    })

    run_pilot_test(
        df=df,
        n_indicators=1,
        indicator_cols=["value"],
        query="Plot bar chart of US GDP growth from 2018 to 2022",
        expected_description="Grouped/vertical bar chart over time (respecting the bar hint on a timeline).",
        chart_type_hint="bar"
    )
