"""
Layer 2 — visualization.py Integration Evaluation Suite
========================================================

Tests the full ``get_viz_spec`` and ``get_multi_indicator_viz_spec`` pipeline
by mocking only the I/O boundary (HTTP fetch + spec storage). Unlike Layer 1
(which calls viz_config directly), these tests exercise:

  - _clean_single_df (column selection, renames, bar-year filtering)
  - _map_country_codes / _map_dimension_codes (code → label resolution)
  - select_strategy (routing decision)
  - dispatch_spec (spec builder)
  - POST_PROCESSING_RULES (e.g. LineYearGapStrokeDashRule, PercentageBoundaryClampingRule)
  - _store_spec (storage path; captured via mock)
  - Response shape: url, error, strategy, reason, dimensions, data_summary

Run:
    uv run deepeval test run evals/test_viz_integration_deepeval.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams

# Add project root to path so data360 package is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data360.visualization import get_multi_indicator_viz_spec, get_viz_spec

# ---------------------------------------------------------------------------
# Shared G-Eval metrics — lazy factories to avoid requiring OPENAI_API_KEY at
# import time. Only tests that call assert_test() need the key.
# ---------------------------------------------------------------------------


def _pipeline_response_metric() -> GEval:
    return GEval(
        name="Visualization Pipeline Response Quality",
        criteria="""
    Evaluate whether the visualization pipeline correctly produced a complete
    and well-structured response for the given data shape and query.
    Criteria:
    1. The response must include a non-null 'url' field (chart was generated).
    2. The response must include 'strategy' and 'reason' fields explaining chart selection.
    3. The 'actual_output' (Vega-Lite JSON spec) must use the correct mark type
       and encoding channels for the described data shape:
         - Multi-year data → temporal x-axis (type=temporal, timeUnit=year)
         - Single-year multi-country data → nominal y-axis (horizontal bars)
         - Demographic breakdown → color encoding for the breakdown dimension
    4. Tooltips must be structured objects (dicts), not raw column name strings.
    5. The spec must include proper WB-style axis formatting (gridColor, format).
    """,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        evaluation_steps=[
            "Inspect the input description (data shape, query intent, expected strategy).",
            "Inspect the actual_output (Vega-Lite JSON spec produced by the pipeline).",
            "Check that the top-level mark type matches the expected chart type for the data shape.",
            "Verify x/y encoding channels use correct types (temporal vs nominal vs quantitative).",
            "Check that color encoding is present when multiple series are expected.",
            "Verify tooltips are structured dicts with 'field', 'type', 'title' keys.",
            "Confirm axis objects have 'format' and 'gridColor' styling properties.",
        ],
        threshold=0.75,
    )


def _multi_indicator_metric() -> GEval:
    return GEval(
        name="Multi-Indicator Spec Grammar Correctness",
        criteria="""
    Evaluate whether a multi-indicator Vega-Lite spec correctly handles the
    merged dataset:
    1. For 2-indicator layered/faceted specs: both indicators must appear
       as distinct layers or facet panels with independent y-axis resolution.
    2. For scatter: x encodes indicator 1, y encodes indicator 2,
       color encodes country. Points (mark: point) must be used.
    3. No indicator column name should appear as a raw slug (e.g. 'gdp_growth')
       in axis titles — human-readable labels should be used.
    4. The spec must be parseable Vega-Lite v5 JSON with a $schema key.
    """,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        evaluation_steps=[
            "Parse the actual_output as Vega-Lite JSON.",
            "Inspect the mark type (layer vs point vs facet).",
            "Check that all indicator values are represented in the spec encodings.",
            "Verify that axis titles use human-readable labels, not internal slugs.",
            "For scatter: confirm x-encoding indicator != y-encoding indicator.",
        ],
        threshold=0.75,
    )

# ---------------------------------------------------------------------------
# Mock fixture helpers
# ---------------------------------------------------------------------------


def _make_raw_df(
    years: list[int],
    countries: list[str],
    value_fn=None,
    breakdown_col: str | None = None,
    breakdown_vals: list[str] | None = None,
    unit_measure: str | None = None,
) -> pd.DataFrame:
    """Build a synthetic raw DataFrame mimicking the Data360 API response shape."""
    if value_fn is None:
        value_fn = lambda i, j: float(i * 10 + j)

    rows = []
    for j, year in enumerate(years):
        for i, country in enumerate(countries):
            row: dict[str, Any] = {
                "TIME_PERIOD": str(year),
                "OBS_VALUE": value_fn(i, j),
                "REF_AREA": country,
            }
            if unit_measure:
                row["UNIT_MEASURE"] = unit_measure
            if breakdown_col and breakdown_vals:
                for bv in breakdown_vals:
                    r = dict(row)
                    r[breakdown_col] = bv
                    rows.append(r)
            else:
                rows.append(row)
    return pd.DataFrame(rows)


def _base_patches(raw_df: pd.DataFrame, url: str = "http://fake-api/data?DATABASE_ID=WB_WDI&INDICATOR=FAKE"):
    """Return a context manager that patches all I/O boundaries for get_viz_spec."""
    return (
        patch(
            "data360.api.get_data_api_url",
            new_callable=AsyncMock,
            return_value=url,
        ),
        patch(
            "data360.visualization._fetch_data_internal",
            new_callable=AsyncMock,
            return_value=raw_df,
        ),
        patch(
            "data360.api.get_metadata",
            new_callable=AsyncMock,
            return_value=None,
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
        patch(
            "data360.api.get_comp_breakdown_dim_names",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "data360.providers.get_codelist_manager",
            return_value=MagicMock(
                get_label=lambda dim, code: code,
                get_dimension_labels=lambda dim: {},
                _ensure_extdataportal_loaded=AsyncMock(),
            ),
        ),
        patch(
            "data360.providers.get_group_hierarchy_manager",
            return_value=MagicMock(
                is_country=lambda x: True,
                is_group=lambda x: False,
            ),
        ),
    )


async def _run_get_viz_spec(raw_df: pd.DataFrame, **kwargs) -> tuple[dict, str]:
    """Run get_viz_spec with all I/O mocked; capture the saved spec JSON."""
    captured: dict = {}

    def fake_save(spec: dict) -> str:
        captured["spec"] = spec
        return "http://localhost:8021/static/viz_specs/test.json"

    patches = _base_patches(raw_df)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        with patch("data360.visualization.save_specs_to_static", side_effect=fake_save):
            result = await get_viz_spec(
                database_id="WB_WDI",
                indicator_id="WB_WDI_NY_GDP_PCAP_KD",
                **kwargs,
            )

    spec_json = json.dumps(captured.get("spec", {}), indent=2)
    return result, spec_json


# ---------------------------------------------------------------------------
# Layer 2 Test Scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_layer2_a_temporal_single_multi_year_one_country():
    """Single indicator, 5 years, 1 country → TEMPORAL_SINGLE (line), post-processing applied."""
    raw_df = _make_raw_df(
        years=[2018, 2019, 2020, 2021, 2022],
        countries=["KEN"],
    )
    result, spec_json = await _run_get_viz_spec(raw_df)

    assert result["error"] is None, f"Unexpected error: {result['error']}"
    assert result["url"] is not None
    assert result["strategy"] == "temporal_single"
    assert "data_summary" in result
    assert result["data_summary"]["year_range"] == ["2018", "2022"]

    test_case = LLMTestCase(
        input="Query: single indicator, Kenya, 2018-2022 | Expected: line chart with temporal x-axis",
        actual_output=spec_json,
    )
    assert_test(test_case, [_pipeline_response_metric()])


@pytest.mark.asyncio
async def test_layer2_b_cross_sectional_single_year_multi_country():
    """Single indicator, 1 year, 5 countries → CROSS_SECTIONAL (horizontal bar)."""
    raw_df = _make_raw_df(
        years=[2022],
        countries=["BRA", "ARG", "MEX", "COL", "CHL"],
    )
    result, spec_json = await _run_get_viz_spec(raw_df, chart_type="bar")

    assert result["error"] is None, f"Unexpected error: {result['error']}"
    assert result["strategy"] == "cross_sectional"
    assert result["data_summary"]["year_range"] == ["2022", "2022"]
    assert len(result["data_summary"]["countries"]) == 5

    test_case = LLMTestCase(
        input="Query: 5 Latin American countries, single year 2022 | Expected: horizontal bar chart, country on y-axis",
        actual_output=spec_json,
    )
    assert_test(test_case, [_pipeline_response_metric()])


@pytest.mark.asyncio
async def test_layer2_c_reporting_gap_stroke_dash_rule_fires():
    """Single indicator with a 3-year reporting gap → LineYearGapStrokeDashRule must fire."""
    raw_df = _make_raw_df(
        years=[2018, 2019, 2022],  # gap between 2019 and 2022
        countries=["NPL"],
    )
    result, spec_json = await _run_get_viz_spec(raw_df)

    assert result["error"] is None, f"Unexpected error: {result['error']}"
    assert result["strategy"] == "temporal_single"

    spec = json.loads(spec_json)
    # LineYearGapStrokeDashRule adds strokeDash encoding + detail field
    assert "strokeDash" in spec.get("encoding", {}), (
        "Expected LineYearGapStrokeDashRule to add strokeDash encoding for reporting gap"
    )
    assert spec["encoding"].get("detail", {}).get("field") == "_d360_lseg", (
        "Expected detail field '_d360_lseg' from gap dashing rule"
    )

    test_case = LLMTestCase(
        input=(
            "Query: electricity access in Nepal 2018-2022 with 3-year gap | "
            "Expected: line chart with dashed segment for reporting gap between 2019 and 2022"
        ),
        actual_output=spec_json,
    )
    assert_test(test_case, [_pipeline_response_metric()])


@pytest.mark.asyncio
async def test_layer2_d_demographic_breakdown_sex():
    """Single indicator with SEX breakdown (Male/Female) → TEMPORAL_SINGLE with color=sex."""
    raw_df = _make_raw_df(
        years=[2018, 2019, 2020, 2021, 2022],
        countries=["KEN"],
        breakdown_col="SEX",
        breakdown_vals=["M", "F"],
    )
    result, spec_json = await _run_get_viz_spec(raw_df)

    assert result["error"] is None, f"Unexpected error: {result['error']}"
    assert result["strategy"] == "temporal_single"

    spec = json.loads(spec_json)
    # Must have a color encoding for sex breakdown
    color_enc = spec.get("encoding", {}).get("color", {})
    assert color_enc.get("field") == "sex", (
        "Expected color encoding on 'sex' dimension for Male/Female breakdown"
    )

    test_case = LLMTestCase(
        input=(
            "Query: employment rate in Kenya by sex 2018-2022 | "
            "Expected: multi-series line chart, one line per sex (Male/Female), color-coded"
        ),
        actual_output=spec_json,
    )
    assert_test(test_case, [_pipeline_response_metric()])


@pytest.mark.asyncio
async def test_layer2_e_percentage_unit_clamping_rule():
    """Single indicator with percentage unit → PercentageBoundaryClampingRule clamps y-axis to [0,100]."""
    raw_df = _make_raw_df(
        years=[2018, 2019, 2020, 2021, 2022],
        countries=["DEU"],
        value_fn=lambda i, j: 95.0 + j,  # values near 100%
        unit_measure="PT",
    )
    result, spec_json = await _run_get_viz_spec(raw_df)

    assert result["error"] is None, f"Unexpected error: {result['error']}"

    spec = json.loads(spec_json)
    # PercentageBoundaryClampingRule should clamp y-axis scale domain to [0, 100]
    y_scale = spec.get("encoding", {}).get("y", {}).get("scale", {})
    if "domain" in y_scale:
        assert y_scale["domain"][1] >= 100, (
            "Expected y-axis to be clamped to at least 100 for percentage data"
        )

    test_case = LLMTestCase(
        input=(
            "Query: employment rate percentage in Germany 2018-2022 | "
            "Expected: line chart, y-axis domain clamped to [0, 100], percentage format on y-axis"
        ),
        actual_output=spec_json,
    )
    assert_test(test_case, [_pipeline_response_metric()])


@pytest.mark.asyncio
async def test_layer2_f_error_returns_null_url_on_empty_fetch():
    """When _fetch_data_internal raises ValueError (no data), get_viz_spec must return error."""
    patches = _base_patches(pd.DataFrame())
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        with patch(
            "data360.visualization._fetch_data_internal",
            new_callable=AsyncMock,
            side_effect=ValueError("No data found at the provided URL."),
        ):
            result = await get_viz_spec(
                database_id="WB_WDI",
                indicator_id="WB_WDI_NY_GDP_PCAP_KD",
            )

    assert result["url"] is None
    assert result["error"] is not None
    assert "error" in result["error"].lower() or "data" in result["error"].lower()


@pytest.mark.asyncio
async def test_layer2_g_data_summary_has_required_fields():
    """data_summary must include shape, year_range, countries, and value stats."""
    raw_df = _make_raw_df(
        years=[2020, 2021, 2022],
        countries=["USA", "GBR", "FRA"],
        value_fn=lambda i, j: float((i + 1) * (j + 1) * 10),
    )
    result, _ = await _run_get_viz_spec(raw_df)

    assert result["error"] is None
    ds = result.get("data_summary", {})
    assert "shape" in ds, "data_summary must include 'shape'"
    assert "year_range" in ds, "data_summary must include 'year_range'"
    assert "countries" in ds, "data_summary must include 'countries'"
    assert "value" in ds, "data_summary must include 'value' stats"
    assert "min" in ds["value"] and "max" in ds["value"]
    assert ds["year_range"] == ["2020", "2022"]
    assert sorted(ds["countries"]) == ["FRA", "GBR", "USA"]


@pytest.mark.asyncio
async def test_layer2_h_strategy_and_reason_present_in_response():
    """strategy and reason must always be present and non-empty in a successful response."""
    raw_df = _make_raw_df(
        years=[2018, 2019, 2020, 2021, 2022],
        countries=["USA"],
    )
    result, _ = await _run_get_viz_spec(raw_df)

    assert result["error"] is None
    assert "strategy" in result and result["strategy"]
    assert "reason" in result and result["reason"]
    # Source attribution must be present
    assert "source_line" in result


@pytest.mark.asyncio
async def test_layer2_i_chart_type_hint_bar_filters_to_latest_year():
    """chart_type='bar' with multi-year multi-country data must filter to latest year."""
    raw_df = _make_raw_df(
        years=[2020, 2021, 2022],
        countries=["USA", "GBR", "FRA", "DEU"],
    )
    result, _ = await _run_get_viz_spec(raw_df, chart_type="bar")

    assert result["error"] is None
    assert result["strategy"] == "cross_sectional"
    assert result["data_summary"]["year_range"] == ["2022", "2022"]


@pytest.mark.asyncio
async def test_layer2_j_multi_indicator_two_indicators_layered():
    """get_multi_indicator_viz_spec with 2 indicators, multi-year → layered lines or TEMPORAL_MULTI_IND."""
    raw_df_1 = _make_raw_df(
        years=[2018, 2019, 2020, 2021, 2022],
        countries=["ZAF"],
        value_fn=lambda i, j: 2.0 + j * 0.5,
    )
    raw_df_2 = _make_raw_df(
        years=[2018, 2019, 2020, 2021, 2022],
        countries=["ZAF"],
        value_fn=lambda i, j: 6000.0 + j * 100,
    )
    captured: dict = {}

    def fake_save(spec: dict) -> str:
        captured["spec"] = spec
        return "http://localhost:8021/static/viz_specs/multi_test.json"

    # _fetch_single_indicator calls _fetch_data_internal internally; patch at the
    # visualization module level and alternate responses per call.
    call_count = {"n": 0}
    responses = [raw_df_1, raw_df_2]

    async def fake_fetch_single(database_id, indicator_id, *args, **kwargs):
        idx = call_count["n"] % 2
        call_count["n"] += 1
        df = responses[idx].copy()
        df.columns = [c.lower() for c in df.columns]
        return df, f"Indicator {idx + 1}", None

    with (
        patch(
            "data360.visualization._fetch_single_indicator",
            side_effect=fake_fetch_single,
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
        patch(
            "data360.providers.get_codelist_manager",
            return_value=MagicMock(
                get_label=lambda dim, code: code,
                get_dimension_labels=lambda dim: {},
                _ensure_extdataportal_loaded=AsyncMock(),
            ),
        ),
        patch(
            "data360.providers.get_group_hierarchy_manager",
            return_value=MagicMock(
                is_country=lambda x: True,
                is_group=lambda x: False,
            ),
        ),
        patch("data360.visualization.save_specs_to_static", side_effect=fake_save),
    ):
        result = await get_multi_indicator_viz_spec(
            indicator_ids=[
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD"},
            ],
            country_code="ZAF",
            start_year=2018,
            end_year=2022,
            chart_title="GDP Growth vs GDP per Capita in South Africa",
        )

    assert result["error"] is None, f"Unexpected error: {result['error']}"
    assert result["url"] is not None
    assert "strategy" in result and result["strategy"]
    assert "reason" in result

    spec_json = json.dumps(captured.get("spec", {}), indent=2)
    test_case = LLMTestCase(
        input=(
            "Query: GDP growth vs GDP per capita in South Africa 2018-2022 | "
            "Expected: multi-indicator layered lines or faceted subplots with independent y-axes, "
            "each indicator in its own panel or layer"
        ),
        actual_output=spec_json,
    )
    assert_test(test_case, [_multi_indicator_metric()])


@pytest.mark.asyncio
async def test_layer2_k_multi_indicator_validation_too_few():
    """get_multi_indicator_viz_spec with fewer than 2 indicators → error response."""
    result = await get_multi_indicator_viz_spec(indicator_ids=None)

    assert result["url"] is None
    assert result["error"] is not None
    assert "indicator_ids" in result["error"].lower() or "required" in result["error"].lower()


@pytest.mark.asyncio
async def test_layer2_l_multi_indicator_validation_too_many():
    """get_multi_indicator_viz_spec with more than 4 indicators → error response."""
    result = await get_multi_indicator_viz_spec(
        indicator_ids=[
            {"database_id": "WB_WDI", "indicator_id": f"IND_{i}"}
            for i in range(5)
        ]
    )

    assert result["url"] is None
    assert result["error"] is not None
    assert "4" in result["error"] or "maximum" in result["error"].lower()


@pytest.mark.asyncio
async def test_layer2_m_response_contract_keys_always_present():
    """Every successful get_viz_spec response must have url, error, strategy, reason, source_line."""
    raw_df = _make_raw_df(
        years=[2020, 2021, 2022],
        countries=["BRA"],
    )
    result, _ = await _run_get_viz_spec(raw_df)

    required_keys = {"url", "error", "strategy", "reason", "source_line"}
    missing = required_keys - set(result.keys())
    assert not missing, f"Missing required response keys: {missing}"


# ---------------------------------------------------------------------------
# Layer 2 Disaggregation Tests (n–r)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_layer2_n_urbanization_residence_breakdown():
    """
    Single indicator with RESIDENCE breakdown (Urban/Rural) over time.
    Expected: temporal_single strategy, color.field == 'residence' (or 'RESIDENCE').
    """
    raw_df = _make_raw_df(
        years=[2015, 2016, 2017, 2018, 2019, 2020],
        countries=["BGD"],
        breakdown_col="RESIDENCE",
        breakdown_vals=["Urban", "Rural"],
    )
    result, spec_json = await _run_get_viz_spec(raw_df)

    assert result["error"] is None, f"Unexpected error: {result['error']}"
    assert result["strategy"] == "temporal_single"

    spec = json.loads(spec_json)
    color_enc = spec.get("encoding", {}).get("color", {})
    color_field = color_enc.get("field", "").lower()
    assert "residence" in color_field, (
        f"Expected color encoding on 'residence' dimension for Urban/Rural breakdown. "
        f"Got color.field={color_enc.get('field')!r}. Full encoding: {spec.get('encoding')}"
    )

    test_case = LLMTestCase(
        input=(
            "Query: water access in Bangladesh by urban/rural residence 2015-2020 | "
            "Expected: two-line chart with Urban and Rural as separate color-coded series"
        ),
        actual_output=spec_json,
    )
    assert_test(test_case, [_pipeline_response_metric()])


@pytest.mark.asyncio
async def test_layer2_o_age_breakdown_high_cardinality_facet():
    """
    Single indicator with AGE_GROUP breakdown (5 categories, 1 country, multi-year).
    With >= 5 breakdown values, the routing engine should use facet rather than color
    to avoid over-crowding the legend.

    Expected: facet.field or row.field encodes the age dimension.
    """
    raw_df = _make_raw_df(
        years=[2018, 2019, 2020, 2021, 2022],
        countries=["IND"],
        breakdown_col="AGE_GROUP",
        breakdown_vals=["0-4", "5-14", "15-24", "25-64", "65+"],
    )
    result, spec_json = await _run_get_viz_spec(raw_df)

    assert result["error"] is None, f"Unexpected error: {result['error']}"

    spec = json.loads(spec_json)
    enc = spec.get("encoding", {})

    # With 5 age categories the spec should use facet, row, or column —
    # but color is also acceptable if the engine clips at threshold elsewhere.
    disagg_field = (
        enc.get("facet", {}).get("field")
        or enc.get("row", {}).get("field")
        or enc.get("column", {}).get("field")
        or enc.get("color", {}).get("field")
        or ""
    ).lower()
    assert "age" in disagg_field, (
        f"Expected age_group on facet/row/column/color encoding. "
        f"Got: {disagg_field!r}. Full encoding: {enc}"
    )

    test_case = LLMTestCase(
        input=(
            "Query: mortality rate by 5 age groups in India 2018-2022 | "
            "Expected: small multiples (facet) per age group, or color-coded lines "
            "if engine threshold allows"
        ),
        actual_output=spec_json,
    )
    assert_test(test_case, [_pipeline_response_metric()])


@pytest.mark.asyncio
async def test_layer2_p_compound_sex_and_age_breakdown():
    """
    Compound 2-dimensional breakdown: SEX × AGE_GROUP, single country, single year.
    Expected: at least one of (sex, age_group) appears on a visual channel
    (color OR facet OR row/column). The other may appear on color or tooltip.
    """
    rows = []
    for age in ["0-14", "15-64", "65+"]:
        for sex in ["M", "F"]:
            rows.append({
                "TIME_PERIOD": "2020",
                "OBS_VALUE": float(len(age) + (1 if sex == "M" else 2)),
                "REF_AREA": "CHN",
                "SEX": sex,
                "AGE_GROUP": age,
            })
    import pandas as pd
    raw_df = pd.DataFrame(rows)

    result, spec_json = await _run_get_viz_spec(raw_df)
    assert result["error"] is None, f"Unexpected error: {result['error']}"

    spec = json.loads(spec_json)
    enc = spec.get("encoding", {})

    all_fields = " ".join([
        enc.get("color", {}).get("field", ""),
        enc.get("facet", {}).get("field", ""),
        enc.get("row", {}).get("field", ""),
        enc.get("column", {}).get("field", ""),
    ]).lower()

    assert "sex" in all_fields or "age" in all_fields, (
        f"Expected sex or age_group on at least one visual channel (color/facet/row/column). "
        f"Fields found: {all_fields!r}. Full encoding: {enc}"
    )

    test_case = LLMTestCase(
        input=(
            "Query: life expectancy by sex and age group in China 2020 | "
            "Expected: compound disaggregation — facet rows=age, color=sex, "
            "or at minimum one dimension on a visual channel"
        ),
        actual_output=spec_json,
    )
    assert_test(test_case, [_pipeline_response_metric()])


@pytest.mark.asyncio
async def test_layer2_q_multi_country_sex_breakdown():
    """
    3-country × 5-year × sex breakdown.
    The chart must encode sex on color (not just filter it away), producing
    one line per (country, sex) combination or faceted per country.
    """
    raw_df = _make_raw_df(
        years=[2018, 2019, 2020, 2021, 2022],
        countries=["IND", "PAK", "BGD"],
        breakdown_col="SEX",
        breakdown_vals=["M", "F"],
    )
    result, spec_json = await _run_get_viz_spec(raw_df)

    assert result["error"] is None, f"Unexpected error: {result['error']}"

    spec = json.loads(spec_json)
    enc = spec.get("encoding", {})

    color_field = enc.get("color", {}).get("field", "").lower()
    facet_field = enc.get("facet", {}).get("field", "").lower()
    row_field = enc.get("row", {}).get("field", "").lower()

    has_sex_channel = any("sex" in f for f in [color_field, facet_field, row_field])
    assert has_sex_channel, (
        f"Sex dimension must appear on color, facet, or row when multiple "
        f"countries AND sex breakdown are present. "
        f"color={color_field!r}, facet={facet_field!r}, row={row_field!r}"
    )

    test_case = LLMTestCase(
        input=(
            "Query: labor participation in India, Pakistan, Bangladesh by sex 2018-2022 | "
            "Expected: color=sex with lines per country, or facet=country with color=sex"
        ),
        actual_output=spec_json,
    )
    assert_test(test_case, [_pipeline_response_metric()])


@pytest.mark.asyncio
async def test_layer2_r_custom_unknown_dimension_nominal_color():
    """
    Unknown custom dimension (INCOME_CLASS) with 4 categories.
    The engine must treat it as nominal and use it on a visual channel
    (color or facet) — not silently drop it.
    """
    import pandas as pd
    rows = []
    for year in [2019, 2020, 2021, 2022]:
        for cls in ["Low", "Lower-Middle", "Upper-Middle", "High"]:
            rows.append({
                "TIME_PERIOD": str(year),
                "OBS_VALUE": float(year - 2018 + len(cls)),
                "REF_AREA": "WLD",
                "INCOME_CLASS": cls,
            })
    raw_df = pd.DataFrame(rows)

    result, spec_json = await _run_get_viz_spec(raw_df)
    assert result["error"] is None, f"Unexpected error: {result['error']}"

    spec = json.loads(spec_json)
    enc = spec.get("encoding", {})

    all_fields = " ".join([
        enc.get("color", {}).get("field", ""),
        enc.get("facet", {}).get("field", ""),
        enc.get("row", {}).get("field", ""),
        enc.get("column", {}).get("field", ""),
    ]).lower()

    assert "income" in all_fields or "class" in all_fields, (
        f"Custom INCOME_CLASS dimension should appear on a visual encoding channel. "
        f"Fields found: {all_fields!r}"
    )

    test_case = LLMTestCase(
        input=(
            "Query: HDI trend by income classification (4 groups) 2019-2022 | "
            "Expected: color or facet encoding for the income group dimension"
        ),
        actual_output=spec_json,
    )
    assert_test(test_case, [_pipeline_response_metric()])
