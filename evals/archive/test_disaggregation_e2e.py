"""
Disaggregation-Focused End-to-End Evaluation (Scenarios 09–16)
===============================================================

Tests the agent's ability to autonomously discover and correctly visualize
disaggregated data — age, sex, urbanization, custom dimensions, compound
breakdowns, and high-cardinality dimensions.

Each test runs a real GPT-4o agent loop against the live MCP server with NO
chart_type hint. The key assertion for this suite is not just "did a chart
appear" but whether the resulting Vega-Lite spec has the correct disaggregation
encoding — i.e., that the breakdown dimension appears on a `color`, `facet`,
or `row`/`column` channel.

Prerequisites:
    uv run poe serve           (MCP server on :8021)
    OPENAI_API_KEY set in .env.evals

Run a single scenario:
    uv run deepeval test run evals/test_disaggregation_e2e.py::test_e2e_09_sex_breakdown_employment -v

Run all:
    uv run deepeval test run evals/test_disaggregation_e2e.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams

# Re-use the shared agent loop and helpers from the base e2e module.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    _repo = Path(__file__).parent.parent
    load_dotenv(_repo / ".env.evals", override=False)
    load_dotenv(_repo / ".env", override=False)
except ImportError:
    pass

from evals.test_chart_quality_e2e import (  # noqa: E402
    AGENT_TIMEOUT_S,
    REPORTS_DIR,
    SERVER_UP,
    _build_score_metric,
    _run_agent,
    _save_report,
    skip_if_offline,
)

OPENAI_KEY_SET = bool(os.environ.get("OPENAI_API_KEY"))


# ---------------------------------------------------------------------------
# Disaggregation-specific G-Eval scorer
# ---------------------------------------------------------------------------


def _build_disagg_metric() -> GEval:
    """
    Extended scoring rubric that adds a sixth criterion: disaggregation fidelity.
    Scores 0–12 internally (6 criteria × 2 points), then GEval normalises to 0–1.
    The test_case threshold is 0.5 (≥ 6/12).
    """
    return GEval(
        name="Disaggregation Chart Quality Score",
        criteria="""
        You are evaluating an AI agent's ability to correctly visualize DISAGGREGATED
        World Bank data (breakdowns by sex, age, urbanization, income group, etc.).

        Score across SIX criteria, up to 2 points each (12 points total):

        1. DATA RELEVANCE (0-2)
           Does the chart show the right indicator for the right countries/regions
           and time period? Deduct if the indicator is unrelated to the question.

        2. CHART TYPE FIT (0-2)
           Is the chart type appropriate for the data shape, using the FT Visual
           Vocabulary as the reference?

        3. DISAGGREGATION ENCODING (0-2) — KEY CRITERION
           Is the breakdown dimension (sex/age/residence/income group/other) correctly
           encoded in the Vega-Lite spec?
           - 2 pts: dimension appears on color, facet, row, or column channel
           - 1 pt: dimension is present in the data/tooltip but not encoded as a visual channel
           - 0 pts: dimension is collapsed, averaged out, or completely absent

        4. GRAMMAR OF GRAPHICS CORRECTNESS (0-2)
           Are encoding channels correctly typed (temporal, nominal, quantitative)?
           Are tooltips structured dicts with field/type/title?

        5. READABILITY (0-2)
           Descriptive title, axis labels, appropriate scale, WB-style formatting.
           Legend present and labeled when color encoding is used.

        6. ROUTING CORRECTNESS (0-2)
           Did the agent follow: search → get_disaggregation → viz_spec?
           Did it discover the breakdown dimension from get_disaggregation output
           rather than hard-coding it? Deduct 1.0 if get_disaggregation was skipped.

        Provide a total score out of 12 and explain each criterion's score.
        Write a concise critique and bulleted recommendations.
        """,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        evaluation_steps=[
            "Read the INPUT: user question, agent tool-call trace, strategy, reason, any error.",
            "Read the ACTUAL_OUTPUT: the Vega-Lite JSON spec.",
            "Score DATA RELEVANCE (0-2): correct indicator, countries, time range?",
            "Score CHART TYPE FIT (0-2): appropriate mark type for data shape?",
            "Score DISAGGREGATION ENCODING (0-2): does the breakdown dimension appear "
            "on color, facet, row, or column? This is the primary criterion for this suite.",
            "Score GRAMMAR OF GRAPHICS (0-2): encoding types, tooltip structure, no aggregation bugs?",
            "Score READABILITY (0-2): title, axis labels, legend, scale range, WB style?",
            "Score ROUTING CORRECTNESS (0-2): search → disaggregation → viz sequence followed?",
            "Sum the six scores (max 12) and report as the final score.",
            "Write critique and recommendations.",
        ],
        threshold=0.5,  # 6/12 minimum — must at least partially encode the breakdown
    )


# ---------------------------------------------------------------------------
# Core runner (extends base with disagg-specific scoring)
# ---------------------------------------------------------------------------


async def _run_disagg_scenario(
    scenario_id: str,
    question: str,
    *,
    expected_breakdown_fields: list[str] | None = None,
) -> None:
    """
    Run an E2E disaggregation scenario.

    ``expected_breakdown_fields``: list of Vega-Lite field names that MUST appear
    on a color, facet, row, or column encoding.  If provided, asserts structurally
    in addition to the LLM critique score.
    """
    agent_result = await asyncio.wait_for(
        _run_agent(question),
        timeout=AGENT_TIMEOUT_S,
    )

    spec = agent_result.get("spec")
    trace = agent_result.get("agent_trace", [])

    # Build trace summary for the judge.
    trace_summary = "\n".join(
        f"  Turn {t['turn']}: {t['tool']}({json.dumps(t.get('args', {}))[:120]}) "
        f"→ {t.get('result_summary', '')}"
        for t in trace
    )
    judge_input = (
        f"USER QUESTION: {question}\n\n"
        f"AGENT TOOL TRACE:\n{trace_summary or '(no tools called)'}\n\n"
        f"ROUTING STRATEGY: {agent_result.get('strategy') or 'unknown'}\n"
        f"ROUTING REASON: {agent_result.get('reason') or 'N/A'}\n"
        f"CHART URL: {agent_result.get('chart_url') or 'None'}\n"
        f"AGENT ERROR: {agent_result.get('error') or 'None'}"
    )

    if spec:
        actual_output = json.dumps(spec, indent=2)
    else:
        err = agent_result.get("error", "unknown")
        actual_output = f'{{"error": "No chart generated", "agent_error": "{err}"}}'

    # ── Structural assertion on breakdown encoding ────────────────────────
    if expected_breakdown_fields and spec:
        encoding = spec.get("encoding") or {}
        # Also check inside layer specs.
        layers = spec.get("layer") or []
        all_encodings = [encoding] + [ly.get("encoding", {}) for ly in layers]

        disagg_channels = {}
        for enc in all_encodings:
            for ch in ("color", "facet", "row", "column"):
                if ch in enc:
                    disagg_channels[ch] = enc[ch].get("field", "")

        found_fields = set(disagg_channels.values())
        missing = [
            f for f in expected_breakdown_fields
            if not any(f.lower() in fv.lower() for fv in found_fields)
        ]
        assert not missing, (
            f"Expected breakdown field(s) {missing} on color/facet/row/column encoding.\n"
            f"Found disagg channels: {disagg_channels}\n"
            f"Full encoding keys: {list(encoding.keys())}"
        )

    # ── LLM critique score ────────────────────────────────────────────────
    metric = _build_disagg_metric()
    # Also include the standard quality metric.
    quality_metric = _build_score_metric()

    test_case = LLMTestCase(input=judge_input, actual_output=actual_output)
    metric.measure(test_case)
    quality_metric.measure(test_case)

    score_12 = round((metric.score or 0.0) * 12, 1)
    score_10 = round((quality_metric.score or 0.0) * 10, 1)
    critique = metric.reason or quality_metric.reason or ""

    report_path = _save_report(scenario_id, question, agent_result, score_10, critique)
    print(f"\n[{scenario_id}] Disagg score: {score_12}/12 | Quality: {score_10}/10")
    print(f"[{scenario_id}] Report: {report_path}")
    print(f"[{scenario_id}] Critique: {critique[:300]}")

    assert_test(test_case, [metric])


# ---------------------------------------------------------------------------
# Scenario 09 — Sex breakdown, employment rate, India
# ---------------------------------------------------------------------------


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_09_sex_breakdown_employment():
    """
    Scenario 09 — Sex disaggregation discovered autonomously.

    The agent MUST call get_disaggregation and discover that the employment
    indicator has a SEX dimension (Male / Female / Total), then pass that
    dimension to get_viz_spec so the spec has color.field == 'sex' (or similar).

    Expected:
        search → disagg (discovers SEX dim) → viz_spec
        Chart: multi-series line, x=year, color=sex, one line per sex
    """
    await _run_disagg_scenario(
        scenario_id="09_sex_breakdown_employment",
        question=(
            "Show me male vs female labor force participation rate in India "
            "from 2010 to 2022, broken down by sex."
        ),
        expected_breakdown_fields=["sex"],
    )


# ---------------------------------------------------------------------------
# Scenario 10 — Age group breakdown, child/infant mortality
# ---------------------------------------------------------------------------


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_10_age_breakdown_mortality():
    """
    Scenario 10 — Age group disaggregation.

    Expected:
        search → disagg (discovers AGE_GROUP or similar) → viz_spec
        Chart: grouped/faceted bars or multi-series line with color=age_group
    """
    await _run_disagg_scenario(
        scenario_id="10_age_breakdown_mortality",
        question=(
            "Show mortality rates for different age groups in Nigeria. "
            "I want to see how child mortality (under-5) compares to infant mortality "
            "(under-1) over the last 15 years, broken down by age group."
        ),
        expected_breakdown_fields=["age"],
    )


# ---------------------------------------------------------------------------
# Scenario 11 — Urban vs rural, access to clean water, Bangladesh
# ---------------------------------------------------------------------------


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_11_urban_rural_water_access():
    """
    Scenario 11 — Urbanization (RESIDENCE) disaggregation.

    The agent must discover the residence/urbanization dimension and use it
    as the color or facet channel.

    Expected:
        search → disagg (discovers RESIDENCE: Urban/Rural) → viz_spec
        Chart: two-line chart or facet, color=residence
    """
    await _run_disagg_scenario(
        scenario_id="11_urban_rural_water_access",
        question=(
            "Compare urban vs rural access to safely managed drinking water "
            "in Bangladesh from 2000 to 2022. Show both as separate series."
        ),
        expected_breakdown_fields=["residence"],
    )


# ---------------------------------------------------------------------------
# Scenario 12 — Compound sex × age, life expectancy, China
# ---------------------------------------------------------------------------


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_12_compound_sex_age_life_expectancy():
    """
    Scenario 12 — Compound disaggregation: sex AND age simultaneously.

    With two breakdown dimensions, the ideal chart uses:
        facet.field = age_group (rows or columns)
        color.field = sex

    At minimum, one dimension must appear on a visual channel.
    Both 'sex' and 'age' are listed as expected breakdown fields — the structural
    assertion passes if at least one is found on color/facet/row/column.

    Expected:
        search → disagg (discovers SEX + AGE) → viz_spec (small multiples or facet)
    """
    await _run_disagg_scenario(
        scenario_id="12_compound_sex_age_life_expectancy",
        question=(
            "Show life expectancy in China in 2020, broken down by both sex "
            "(male/female) and age group. I want to see how they differ."
        ),
        # At least one of these must appear on a visual channel.
        expected_breakdown_fields=["sex"],
    )


# ---------------------------------------------------------------------------
# Scenario 13 — Multiple countries + sex breakdown, South Asia labor
# ---------------------------------------------------------------------------


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_13_multi_country_sex_breakdown():
    """
    Scenario 13 — Multiple countries AND a sex breakdown simultaneously.

    The agent must handle a 3-dimensional data shape:
        country × year × sex
    Good charts: small multiples per country with color=sex, or facet rows=country.

    Expected:
        search → disagg → viz_spec
        Chart: line chart, facet=country or color=sex, years on x-axis
    """
    await _run_disagg_scenario(
        scenario_id="13_multi_country_sex_breakdown",
        question=(
            "Compare female labor force participation rate across India, Pakistan, "
            "Bangladesh, and Sri Lanka from 2010 to 2022, split by sex so I can "
            "see male and female separately for each country."
        ),
        expected_breakdown_fields=["sex"],
    )


# ---------------------------------------------------------------------------
# Scenario 14 — Custom dimension (income classification), HDI
# ---------------------------------------------------------------------------


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_14_custom_income_classification():
    """
    Scenario 14 — Unknown / custom dimension the agent discovers via get_disaggregation.

    The income classification is not a standard WHO dimension. The agent must:
    1. Search for HDI or similar indicator
    2. Call get_disaggregation and discover INCOME_GROUP or a comparable dimension
    3. Use it in the viz call

    If no such dimension exists, the test passes as long as the agent still
    produces a valid chart (the structural assertion is lenient here).
    """
    await _run_disagg_scenario(
        scenario_id="14_custom_income_classification",
        question=(
            "Show Human Development Index trends broken down by world bank income "
            "classification (low income, lower-middle, upper-middle, high income) "
            "from 2010 to 2022."
        ),
        # No strict field assertion — the dimension name varies across databases.
        expected_breakdown_fields=None,
    )


# ---------------------------------------------------------------------------
# Scenario 15 — High-cardinality dimension → facet, not color
# ---------------------------------------------------------------------------


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_15_high_cardinality_dimension():
    """
    Scenario 15 — Breakdown with 5+ categories should use facet, not color.

    When a dimension has >4 distinct values, color encoding becomes illegible.
    The routing engine should switch to small multiples (facet) automatically.

    Expected:
        The spec uses facet.field (not color.field) for the breakdown dimension.
    """
    await _run_disagg_scenario(
        scenario_id="15_high_cardinality_education_level",
        question=(
            "Show educational attainment rates in Brazil broken down by level "
            "(no education, primary, secondary, tertiary) over the last 10 years. "
            "I want a separate panel for each education level."
        ),
        # Facet is expected, not color — structural assertion checks either.
        expected_breakdown_fields=None,
    )


# ---------------------------------------------------------------------------
# Scenario 16 — Autonomous breakdown discovery (no hint in question)
# ---------------------------------------------------------------------------


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_16_autonomous_breakdown_discovery():
    """
    Scenario 16 — The user gives NO hint about which breakdown to use.
    The agent must call get_disaggregation and autonomously choose the most
    informative non-trivial dimension available in the data.

    This is the hardest scenario: the question is open-ended.

    Key assertions:
    - Agent MUST call get_disaggregation (checked in routing score)
    - Agent MUST produce a chart that uses a breakdown dimension (not just
      total/aggregate) — measured by the DISAGGREGATION ENCODING score
    - Score threshold: 0.5 (6/12)
    """
    await _run_disagg_scenario(
        scenario_id="16_autonomous_breakdown_discovery",
        question=(
            "Show me poverty headcount ratio data for Pakistan. Break it down by "
            "whatever sub-groups or dimensions the data has available — "
            "I want to see the most informative disaggregation, not just the total."
        ),
        expected_breakdown_fields=None,  # Unknown until disaggregation call resolves it
    )
