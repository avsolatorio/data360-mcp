"""
Layer 2 - Dynamic Chart Rules Evaluation Suite
==============================================

Tests the Data360 MCP visualization engine + routing rules comprehensively.
Does not reuse any existing scenarios.

Features:
- Dynamic scenario generation using OpenAI (with static defaults fallback).
- Transparent caching of all external HTTP API requests (metadata, data, search).
- Zero-shot G-Eval DeepEval metrics (judging the visual spec grammar from the query).
- Local run:
    uv run deepeval test run evals/test_chart_rules_deepeval.py
"""

from __future__ import annotations

import os
import sys
import json
import hashlib
import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

try:
    import pytest
except ImportError:
    class MockPytest:
        def fixture(self, *args, **kwargs):
            def decorator(fn):
                return fn
            return decorator

        class Mark:
            def asyncio(self, fn):
                return fn
            def parametrize(self, *args, **kwargs):
                def decorator(fn):
                    return fn
                return decorator

        mark = Mark()
    pytest = MockPytest()  # type: ignore

import pandas as pd
import httpx

try:
    from deepeval import assert_test
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, SingleTurnParams
except ImportError:
    assert_test = None  # type: ignore
    class GEval:
        def __init__(self, name: str, criteria: str, evaluation_params: list, evaluation_steps: list, threshold: float):
            self.name = name
            self.criteria = criteria
            self.evaluation_params = evaluation_params
            self.evaluation_steps = evaluation_steps
            self.threshold = threshold
            self.score = 0.0
            self.reason = ""

        def measure(self, test_case: Any):
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                self.score = 0.5
                self.reason = "OPENAI_API_KEY environment variable is missing. Cannot perform visual G-Eval critique."
                return

            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                system_prompt = (
                    "You are a visualization expert. Evaluate the provided Vega-Lite JSON specification "
                    "against the criteria and evaluation steps. Provide a score from 0.0 to 1.0 "
                    "and a detailed critique.\n\n"
                    f"Evaluation Criteria:\n{self.criteria}\n\n"
                    f"Steps:\n" + "\n".join(f"- {step}" for step in self.evaluation_steps)
                )
                user_prompt = (
                    f"Input Query / Context:\n{test_case.input}\n\n"
                    f"Generated Vega-Lite JSON Spec:\n{test_case.actual_output}\n\n"
                    "Output a JSON object with exactly two keys: \'score\' (float between 0.0 and 1.0) and "
                    "\'critique\' (string containing critique and engine recommendations). Do not wrap in markdown code blocks."
                )

                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )

                res_data = json.loads(response.choices[0].message.content)
                self.score = float(res_data.get("score", 0.0))
                self.reason = res_data.get("critique", "No critique provided.")
            except Exception as e:
                self.score = 0.0
                self.reason = f"Error during direct OpenAI visual G-Eval critique: {e}"

    class LLMTestCase:
        def __init__(self, input: str, actual_output: str):
            self.input = input
            self.actual_output = actual_output

    class SingleTurnParams:
        INPUT = "input"
        ACTUAL_OUTPUT = "actual_output"

from openai import OpenAI

# Add project root to python path so data360 package is importable
_HERE = Path(__file__).parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from data360.visualization import get_viz_spec, get_multi_indicator_viz_spec, save_specs_to_static
from data360.api import search as api_search
from data360.http_client import aclose_shared_httpx_client

@pytest.fixture(autouse=True)
async def reset_shared_client():
    await aclose_shared_httpx_client()
    yield
    await aclose_shared_httpx_client()


# Load env variables
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env.evals", override=False)
    load_dotenv(_REPO / ".env", override=False)
except ImportError:
    pass

# Setup directories
CACHE_DIR = _HERE / "cache"
CACHE_DIR.mkdir(exist_ok=True)
REPORTS_DIR = _HERE / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# HTTP Traffic Caching Layer (intercepts all external API requests)
# ---------------------------------------------------------------------------

original_async_send = httpx.AsyncClient.send
original_sync_send = httpx.Client.send

def get_cache_key(request: httpx.Request) -> str:
    content = request.read()
    key_src = f"{request.method}:{request.url}:{content.decode('utf-8', errors='ignore')}"
    return hashlib.md5(key_src.encode("utf-8")).hexdigest()

async def cached_async_send(self, request: httpx.Request, *args, **kwargs):
    # Only cache external APIs (do not cache localhost where local servers run)
    url_str = str(request.url)
    if "localhost" in url_str or "127.0.0.1" in url_str:
        return await original_async_send(self, request, *args, **kwargs)

    cache_key = get_cache_key(request)
    cache_file = CACHE_DIR / f"http_{cache_key}.json"

    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
            return httpx.Response(
                status_code=data["status_code"],
                headers=data["headers"],
                content=data["content"].encode("utf-8") if isinstance(data["content"], str) else bytes(data["content"]),
                request=request,
            )
        except Exception:
            pass

    response = await original_async_send(self, request, *args, **kwargs)

    if response.status_code < 400:
        try:
            content_str = response.content.decode("utf-8")
        except UnicodeDecodeError:
            content_str = response.content.hex()

        headers = dict(response.headers)
        for h in ["content-encoding", "transfer-encoding", "content-length"]:
            headers.pop(h, None)

        cache_data = {
            "status_code": response.status_code,
            "headers": headers,
            "content": content_str,
        }
        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=2)

    return response

def cached_sync_send(self, request: httpx.Request, *args, **kwargs):
    url_str = str(request.url)
    if "localhost" in url_str or "127.0.0.1" in url_str:
        return original_sync_send(self, request, *args, **kwargs)

    cache_key = get_cache_key(request)
    cache_file = CACHE_DIR / f"http_{cache_key}.json"

    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                data = json.load(f)
            return httpx.Response(
                status_code=data["status_code"],
                headers=data["headers"],
                content=data["content"].encode("utf-8") if isinstance(data["content"], str) else bytes(data["content"]),
                request=request,
            )
        except Exception:
            pass

    response = original_sync_send(self, request, *args, **kwargs)

    if response.status_code < 400:
        try:
            content_str = response.content.decode("utf-8")
        except UnicodeDecodeError:
            content_str = response.content.hex()

        headers = dict(response.headers)
        for h in ["content-encoding", "transfer-encoding", "content-length"]:
            headers.pop(h, None)

        cache_data = {
            "status_code": response.status_code,
            "headers": headers,
            "content": content_str,
        }
        with open(cache_file, "w") as f:
            json.dump(cache_data, f, indent=2)

    return response

# Apply monkey patches to httpx send methods
httpx.AsyncClient.send = cached_async_send
httpx.Client.send = cached_sync_send


# ---------------------------------------------------------------------------
# Dynamic Scenario Generation Logic
# ---------------------------------------------------------------------------

DEFAULT_SCENARIOS = [
    {
        "id": "dyn_001_gdp_trend",
        "user_question": "Show me a line chart of GDP growth for Brazil, Argentina, and Colombia from 2012 to 2022.",
        "search_queries": ["GDP growth (annual %)"],
        "country_code": "BRA;ARG;COL",
        "start_year": 2012,
        "end_year": 2022,
        "chart_type": "line"
    },
    {
        "id": "dyn_002_school_ranking",
        "user_question": "Compare primary school enrollment gross percentage in Southeast Asia countries in 2021.",
        "search_queries": ["Primary school enrollment, gross (%)"],
        "country_code": "IDN;MYS;THA;PHL;VNM;SGP",
        "start_year": 2021,
        "end_year": 2021,
        "chart_type": "bar"
    },
    {
        "id": "dyn_003_gdp_vs_life_expectancy",
        "user_question": "What is the relationship between GDP per capita and life expectancy across G7 countries in 2020?",
        "search_queries": ["GDP per capita (const 2015 USD)", "Life expectancy at birth (years)"],
        "country_code": "USA;GBR;DEU;FRA;JPN;CAN;ITA",
        "start_year": 2020,
        "end_year": 2020,
        "chart_type": "scatter"
    },
    {
        "id": "dyn_004_gdp_sectors_shares_compat",
        "user_question": "Compare the agriculture value added share of GDP and industry value added share of GDP in India from 2015 to 2020.",
        "search_queries": ["Agriculture, forestry, and fishing, value added (% of GDP)", "Industry (including construction), value added (% of GDP)"],
        "country_code": "IND",
        "start_year": 2015,
        "end_year": 2020,
        "chart_type": "line"
    },
    {
        "id": "dyn_005_public_sector_emp_disagg",
        "user_question": "Show the public sector employment share in Kenya by sex from 2015 to 2020.",
        "search_queries": ["Public employment (% of total employment)"],
        "country_code": "KEN",
        "start_year": 2015,
        "end_year": 2020,
        "chart_type": "line"
    }
]

SYSTEM_PROMPT = """
You are a test scenario generator for the World Bank Data360 MCP visualization engine.
Your task is to generate 5 diverse, realistic visual data queries that a user might ask a chatbot.
Each scenario must be represented as a JSON object with:
1. `id`: A short, unique slug starting with 'dyn_' (e.g. `dyn_gdp_growth`).
2. `user_question`: A natural language question (e.g. "Compare GDP growth in Germany and France from 2010 to 2022").
3. `search_queries`: A list of 1 or 2 search queries to locate the indicators (e.g. `["GDP growth (annual %)", "Inflation, consumer prices (annual %)"]`).
4. `country_code`: A semi-colon separated string of 3-letter country ISO codes (e.g. `DEU;FRA`).
5. `start_year`: The start year (integer).
6. `end_year`: The end year (integer).
7. `chart_type`: An optional visual hint (e.g. "line", "bar", "scatter").

Ensure the 5 scenarios cover these diverse profiles:
- Scenario 1: A single-indicator multi-country line chart over a multi-year range (temporal trend).
- Scenario 2: A single-indicator multi-country ranking/comparison for a single year (cross-sectional horizontal bar).
- Scenario 3: A multi-indicator scatter plot comparing two indicators for multiple countries in a single year (correlation).
- Scenario 4: A multi-indicator line chart/layered/faceted subplots for a single country over multiple years (multi-indicator comparison).
- Scenario 5: A single-indicator breakdown query (e.g., employment by sector/gender, or water access by urban/rural) for a country over time or a single year.

Output ONLY a JSON object containing the list under a top-level key "scenarios". No markdown wrapping.
"""

def generate_scenarios() -> list[dict]:
    cache_file = CACHE_DIR / "generated_scenarios.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                return json.load(f)
        except Exception:
            pass

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return DEFAULT_SCENARIOS

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "Generate 5 new, comprehensive visualization scenarios."}
            ],
            temperature=0.7,
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        scenarios = data.get("scenarios", [])
        if len(scenarios) == 5:
            # Cache it
            with open(cache_file, "w") as f:
                json.dump(scenarios, f, indent=2)
            return scenarios
    except Exception as e:
        print(f"Error generating dynamic scenarios: {e}. Falling back to default scenarios.")

    return DEFAULT_SCENARIOS


# ---------------------------------------------------------------------------
# DeepEval Metric & Resolver
# ---------------------------------------------------------------------------

def _zero_shot_grammar_of_graphics_metric() -> GEval:
    return GEval(
        name="Visual Charting Suitability & Graphics Grammar Metric",
        criteria="""
        Evaluate the visual charting quality and layout correctness of the Vega-Lite JSON specification. Focus entirely on the visualization's design, hierarchy, and representation suitability.

        Scoring Criteria:
        1. ENCODING & CHART TYPE SUITABILITY (0-4): Does the visual encoding (marks, axes mapping, facets) represent the query intent effectively? (e.g. line/area for multi-year trends, nominal/ordinal x-axis for categorical horizontal/vertical bar charts, scatter plots for correlation, small multiples/facets for breakdown subplots).
        2. STYLING, THEMES & READABILITY (0-4): Does the chart follow professional dashboard styling? (e.g. clean World Bank visual themes applied, gridlines visible but subtle, axis titles clear and formatted, legend placement, titles/subtitles descriptive).
        3. DESIGN ROBUSTNESS (0-2): Are there no duplicate legends/axes, no overlapping titles, and are tooltip configurations complete and functional for clean interaction?

        Give a final score from 0.0 to 1.0 (where >= 0.75 passes).
        Provide:
        - A concise critique and rationale focusing on charting quality.
        - A dedicated section "RECOMMENDATIONS TO IMPROVE THE ENGINE" listing concrete visual styling and charting suggestions.
        """,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        evaluation_steps=[
            "Inspect the INPUT (the requested query context and parameters).",
            "Inspect the ACTUAL_OUTPUT (the generated Vega-Lite JSON spec).",
            "Verify the mark type fits the cardinality and intent of the comparison (line vs bar vs scatter).",
            "Evaluate visual channels (x, y, color, facet) for encoding readability.",
            "Assess thematic styling correctness (World Bank themes, axis cleanups, and title preservation).",
            "Identify any visual overlaps, label truncation, or duplicate legends.",
            "Generate the final score, written critique, and recommendations."
        ],
        threshold=0.75,
    )

async def resolve_indicator(query: str, country: str | None = None) -> tuple[str, str, str]:
    """Resolve a search query to database_id, indicator_id, and name."""
    search_country = None
    if country:
        search_country = country.split(";")[0].split(",")[0].strip()

    # Sanitize query by removing punctuation like commas, parentheses, etc.
    clean_query = query
    for char in [",", "(", ")", "$", "%", "#", "@", "!"]:
        clean_query = clean_query.replace(char, " ")
    clean_query = " ".join(clean_query.split())

    res = await api_search(query=clean_query, required_country=search_country, limit=1)

    # Handle EnrichedSearchResponse
    if hasattr(res, "indicators") and res.indicators:
        ind = res.indicators[0]
        return ind.database_id, ind.idno, ind.name
    # Handle dict fallback
    elif isinstance(res, dict) and res.get("indicators"):
        ind = res["indicators"][0]
        return ind.get("database_id"), ind.get("idno"), ind.get("name")

    raise ValueError(f"Could not resolve indicator for query: {query} (sanitized: {clean_query})")


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------

SCENARIOS_LIST = generate_scenarios()

@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", SCENARIOS_LIST, ids=lambda s: s["id"])
async def test_dynamic_scenarios(scenario: dict):
    # 1. Resolve indicators
    search_queries = scenario["search_queries"]
    is_multi = len(search_queries) >= 2

    resolved_indicators = []
    for sq in search_queries:
        db_id, ind_id, ind_name = await resolve_indicator(sq, scenario.get("country_code"))
        resolved_indicators.append({
            "database_id": db_id,
            "indicator_id": ind_id,
            "name": ind_name
        })

    # 2. Run visualization spec pipeline
    captured_spec = {}
    def fake_save(spec: dict) -> str:
        captured_spec["spec"] = spec
        return "http://localhost:8021/static/viz_specs/dyn_test.json"

    # Call visualization engine directly
    with patch("data360.visualization.save_specs_to_static", side_effect=fake_save):
        if is_multi:
            # Multi-indicator path
            viz_result = await get_multi_indicator_viz_spec(
                indicator_ids=[
                    {"database_id": ri["database_id"], "indicator_id": ri["indicator_id"]}
                    for ri in resolved_indicators
                ],
                country_code=scenario.get("country_code"),
                start_year=scenario.get("start_year"),
                end_year=scenario.get("end_year"),
                chart_type=scenario.get("chart_type"),
            )
        else:
            # Single-indicator path
            ri = resolved_indicators[0]
            viz_result = await get_viz_spec(
                database_id=ri["database_id"],
                indicator_id=ri["indicator_id"],
                country_code=scenario.get("country_code"),
                start_year=scenario.get("start_year"),
                end_year=scenario.get("end_year"),
                chart_type=scenario.get("chart_type"),
            )

    assert viz_result["error"] is None, f"Visualization failed: {viz_result['error']}"
    assert "spec" in captured_spec, "No spec saved to static files."

    spec = captured_spec["spec"]
    spec_json = json.dumps(spec, indent=2)

    # 3. Save report JSON to file
    report_file = REPORTS_DIR / f"{scenario['id']}_report.json"
    report_data = {
        "scenario_id": scenario["id"],
        "question": scenario["user_question"],
        "resolved_indicators": resolved_indicators,
        "viz_result": viz_result,
        "spec": spec,
        "timestamp": pd.Timestamp.now().isoformat()
    }
    with open(report_file, "w") as f:
        json.dump(report_data, f, indent=2)

    # 4. DeepEval LLM evaluation (if key is present)
    if os.environ.get("OPENAI_API_KEY"):
        eval_input = f"""
        Requested Indicators:
        {json.dumps(resolved_indicators, indent=2)}

        Parameters:
        - Countries: {scenario.get('country_code')}
        - Start Year: {scenario.get('start_year')}
        - End Year: {scenario.get('end_year')}
        - Chart Type Hint: {scenario.get('chart_type')}
        - Disaggregation Filters: {scenario.get('disaggregation_filters')}

        User Context Question: {scenario['user_question']}
        """
        test_case = LLMTestCase(
            input=eval_input.strip(),
            actual_output=spec_json
        )
        assert_test(test_case, [_zero_shot_grammar_of_graphics_metric()])
    else:
        # Fallback offline assertions
        assert "$schema" in spec
        assert "data" in spec
        assert "encoding" in spec
