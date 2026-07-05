"""
Data360 Visualization Engine Scorer
=====================================

Evaluates the Data360 MCP visualization engine directly.

Pipeline per scenario
---------------------
1. Resolve the indicator
   - Fixed: use the ``database_id`` + ``indicator_id`` already specified.
   - Search: call ``data360_search_indicators`` and pick the top result.

2. Fetch real data
   Call ``data360_get_viz_spec`` (or ``data360_get_multi_indicator_viz_spec``)
   against the live MCP server with the resolved indicator, countries, years,
   and any disaggregation filters.

3. Retrieve the Vega-Lite spec
   Download the JSON spec from the URL returned by the viz tool.

4. Score 0-10 with G-Eval (GPT-4o judge)
   Five criteria: data relevance, chart type fit, grammar of graphics,
   readability, disaggregation encoding (when applicable).

5. Save a JSON report to evals/reports/

No LLM agent loop — the routing path is deterministic.  The only LLM call
is the GPT-4o judge that scores the resulting chart.

Prerequisites
-------------
    MCP server running:
        uv run poe serve          (or: uv run fastmcp run src/data360/server.py \\
                                       --transport streamable-http --port 8021)

    OPENAI_API_KEY set in .env.evals

Run via CLI (recommended)
--------------------------
    uv run python evals/run_evals.py          # all scenarios
    uv run python evals/run_evals.py 01       # single scenario
    uv run python evals/run_evals.py --list   # list all scenario IDs
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    _repo = Path(__file__).parent.parent
    load_dotenv(_repo / ".env.evals", override=False)
    load_dotenv(_repo / ".env", override=False)
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MCP_BASE_URL = os.environ.get("MCP_BASE_URL", "http://localhost:8021")
MCP_URL = f"{MCP_BASE_URL}/mcp"
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def _server_reachable() -> bool:
    try:
        r = httpx.get(f"{MCP_BASE_URL}/mcp/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


SERVER_UP = _server_reachable()
OPENAI_KEY_SET = bool(os.environ.get("OPENAI_API_KEY"))


def skip_if_offline(fn):
    """Skip when MCP server is down or OPENAI_API_KEY is missing."""
    return pytest.mark.skipif(
        not SERVER_UP or not OPENAI_KEY_SET,
        reason=(
            "Skipped: "
            + (f"MCP server not reachable at {MCP_BASE_URL}. " if not SERVER_UP else "")
            + ("OPENAI_API_KEY not set. " if not OPENAI_KEY_SET else "")
        ),
    )(fn)


# ---------------------------------------------------------------------------
# MCP client helpers
# ---------------------------------------------------------------------------


async def _call_mcp(tool: str, args: dict) -> Any:
    """Call a single MCP tool and return parsed content."""
    from fastmcp import Client

    async with Client(MCP_URL, timeout=120.0) as client:
        result = await client.call_tool(tool, args)

    if hasattr(result, "data") and result.data is not None:
        return result.data

    content = getattr(result, "content", None) or []
    if content:
        text = getattr(content[0], "text", None)
        if text:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"raw": text}
    return {}


async def _search_top_indicator(query: str, country: str | None = None) -> dict | None:
    """
    Call data360_search_indicators and return the top result as a dict
    with keys: database_id, indicator_id, name.
    Returns None if no results found.
    """
    args: dict = {"query": query, "limit": 3}
    if country:
        # If multiple countries are passed (semicolon or comma separated), use the first one for filtering
        first_country = country.split(";")[0].split(",")[0].strip()
        if first_country:
            args["required_country"] = first_country
    results = await _call_mcp("data360_search_indicators", args)

    # The tool returns a list of indicator dicts or a dict with an 'indicators' key.
    if isinstance(results, list) and results:
        top = results[0]
    elif isinstance(results, dict):
        items = results.get("indicators") or results.get("results") or []
        top = items[0] if items else None
    else:
        return None

    if top is None:
        return None

    # Normalise key names across response formats.
    # The search API returns 'idno' as the primary indicator ID field.
    return {
        "database_id": top.get("database_id") or top.get("databaseId") or "",
        "indicator_id": (
            top.get("idno")
            or top.get("indicator_id")
            or top.get("indicatorId")
            or top.get("id")
            or ""
        ),
        "name": top.get("name") or top.get("label") or "",
    }


async def _fetch_spec(url: str) -> dict | None:
    """Download the Vega-Lite spec JSON from a chart URL."""
    if not url:
        return None
    if not url.startswith("http"):
        url = f"{MCP_BASE_URL}{url}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Viz engine call — deterministic, no agent loop
# ---------------------------------------------------------------------------


async def run_viz_pipeline(
    *,
    # Indicator resolution
    database_id: str | None = None,
    indicator_id: str | None = None,
    search_query: str | None = None,
    # Chart parameters
    country_code: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict | None = None,
    chart_title: str | None = None,
    chart_type: str | None = None,
    # Multi-indicator mode
    indicator_ids: list[str] | None = None,
    database_ids: list[str] | None = None,
) -> dict:
    """
    Resolve indicator (if needed), call the viz tool, fetch the spec.

    Returns:
        {
          database_id, indicator_id, indicator_name,
          chart_url, spec, strategy, reason,
          error, search_result
        }
    """
    result: dict = {
        "database_id": database_id,
        "indicator_id": indicator_id,
        "indicator_name": None,
        "chart_url": None,
        "spec": None,
        "strategy": None,
        "reason": None,
        "error": None,
        "search_result": None,
    }

    # ── Step 1: resolve indicator ────────────────────────────────────────────
    is_multi = indicator_ids and len(indicator_ids) >= 2
    if not is_multi and (not database_id or not indicator_id):
        if not search_query:
            result["error"] = "Must provide either (database_id + indicator_id) or search_query."
            return result

        found = await _search_top_indicator(search_query, country_code)
        if not found:
            result["error"] = f"No indicator found for query: {search_query!r}"
            return result

        database_id = found["database_id"]
        indicator_id = found["indicator_id"]
        result["database_id"] = database_id
        result["indicator_id"] = indicator_id
        result["indicator_name"] = found["name"]
        result["search_result"] = found

    # ── Step 2: call viz tool ────────────────────────────────────────────────
    try:
        if is_multi:
            # Multi-indicator path: indicator_ids must be [{database_id, indicator_id}, ...]
            db_list = database_ids or [database_id] * len(indicator_ids)
            indicator_dicts = [
                {"database_id": db, "indicator_id": iid}
                for db, iid in zip(db_list, indicator_ids)
            ]
            viz_args: dict = {"indicator_ids": indicator_dicts}
            if country_code:
                viz_args["country_code"] = country_code
            if start_year:
                viz_args["start_year"] = start_year
            if end_year:
                viz_args["end_year"] = end_year
            if chart_title:
                viz_args["chart_title"] = chart_title
            if chart_type:
                viz_args["chart_type"] = chart_type
            viz_result = await _call_mcp("data360_get_multi_indicator_viz_spec", viz_args)
        else:
            # Single-indicator path
            viz_args = {
                "database_id": database_id,
                "indicator_id": indicator_id,
            }
            if country_code:
                viz_args["country_code"] = country_code
            if start_year:
                viz_args["start_year"] = start_year
            if end_year:
                viz_args["end_year"] = end_year
            if disaggregation_filters:
                viz_args["disaggregation_filters"] = disaggregation_filters
            if chart_title:
                viz_args["chart_title"] = chart_title
            if chart_type:
                viz_args["chart_type"] = chart_type
            viz_result = await _call_mcp("data360_get_viz_spec", viz_args)

    except Exception as exc:
        result["error"] = f"viz tool call failed: {exc}"
        return result

    if isinstance(viz_result, dict):
        result["chart_url"] = viz_result.get("url")
        result["strategy"] = viz_result.get("strategy")
        result["reason"] = viz_result.get("reason")
        if viz_result.get("error"):
            result["error"] = viz_result["error"]
    else:
        result["error"] = f"Unexpected viz result type: {type(viz_result)}"
        return result

    # ── Step 3: fetch the Vega-Lite spec ────────────────────────────────────
    if result["chart_url"]:
        result["spec"] = await _fetch_spec(result["chart_url"])

    return result


# ---------------------------------------------------------------------------
# G-Eval scorer
# ---------------------------------------------------------------------------


def _build_score_metric() -> GEval:
    return GEval(
        name="Chart Quality Score (0-10)",
        criteria="""
        You are a data visualization expert scoring a Vega-Lite chart produced
        by the Data360 visualization engine. The chart was generated from real
        World Bank data for a specific indicator, countries, and time range.
        Score 0–10 across five criteria (2 points each):

        1. DATA RELEVANCE (0-2)
           Does the chart show the right data for the stated scenario?
           Are the correct countries, time range, and indicator represented?
           Deduct if the indicator or countries are clearly mismatched from the input request.
           Do NOT deduct points for sparse, missing, or incomplete years/countries if that data
           is simply not present in the upstream database (focus on how the retrieved data is charted).

        2. CHART TYPE FIT (0-2)
           Is the auto-selected chart type appropriate for the data shape?
           Reference: FT Visual Vocabulary.
           - Multi-year, multiple series → line chart
           - Single year, multiple countries → horizontal bar
           - Two indicators, many countries → scatter
           - Global cross-section → choropleth
           Deduct if the chart type conflicts with the data shape.

        3. DISAGGREGATION ENCODING (0-2)
           If the scenario involves a breakdown dimension (sex, age, urban/rural,
           income group etc.), is that dimension encoded on a visual channel?
           - 2 pts: dimension on color, facet, row, or column
           - 1 pt: dimension present in tooltip only
           - 0 pts: dimension absent or collapsed
           If no disaggregation is expected, award 2 pts automatically.

        4. GRAMMAR OF GRAPHICS CORRECTNESS (0-2)
           Are Vega-Lite encoding channels correctly typed?
           (temporal for years, nominal for country names, quantitative for values)
           Are tooltips structured dicts with field/type/title?
           Is there no aggregation artifact?

        5. READABILITY (0-2)
           Descriptive title present?
           Axis labels readable?
           WB-style formatting (gridColor, format, legend)?
           Scale appropriate — no extreme clipping or empty space?

        Sum the five sub-scores for the final score (0-10).
        Also write:
        - A concise critique paragraph.
        - A bulleted list of specific recommendations.
        """,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        evaluation_steps=[
            "Read the INPUT: scenario description, indicator used, countries, year range, strategy.",
            "Read the ACTUAL_OUTPUT: the Vega-Lite JSON specification.",
            "Score DATA RELEVANCE (0-2): correct indicator, countries, time range?",
            "Score CHART TYPE FIT (0-2): mark type appropriate for data shape?",
            "Score DISAGGREGATION ENCODING (0-2): breakdown dimension on a visual channel?",
            "Score GRAMMAR OF GRAPHICS (0-2): encoding types, tooltips, no aggregation bugs?",
            "Score READABILITY (0-2): title, axis labels, legend, scale, WB style?",
            "Sum to get final score (0-10), write critique and recommendations.",
        ],
        threshold=0.5,
    )


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def save_report(
    scenario_id: str,
    scenario: dict,
    viz_result: dict,
    score: float | None,
    critique: str | None,
    tool_data: Any = None,
) -> Path:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"viz_score_{scenario_id}_{ts}.json"
    report = {
        "scenario_id": scenario_id,
        "timestamp": ts,
        "label": scenario.get("label", ""),
        "description": scenario.get("description", ""),
        # Resolved indicator
        "database_id": viz_result.get("database_id"),
        "indicator_id": viz_result.get("indicator_id"),
        "indicator_name": viz_result.get("indicator_name"),
        "search_result": viz_result.get("search_result"),
        # Viz output
        "chart_url": viz_result.get("chart_url"),
        "strategy": viz_result.get("strategy"),
        "reason": viz_result.get("reason"),
        "viz_error": viz_result.get("error"),
        # Score
        "score_out_of_10": score,
        "critique": critique,
        # Raw tool output/data
        "tool_data": tool_data,
    }
    path.write_text(json.dumps(report, indent=2, default=str))
    return path


# ---------------------------------------------------------------------------
# Non-viz pipelines: rank / compare / summarize
# ---------------------------------------------------------------------------


async def rank_pipeline(scenario: dict) -> dict:
    """Call data360_rank_countries and return a standardised result dict."""
    args: dict = {
        "database_id": scenario["database_id"],
        "indicator_id": scenario["indicator_id"],
    }
    if scenario.get("country_group"):
        args["country_group"] = scenario["country_group"]
    if scenario.get("country_code"):
        args["country_codes"] = scenario["country_code"]
    if scenario.get("rank_year"):
        args["year"] = scenario["rank_year"]
    if scenario.get("order"):
        args["order"] = scenario["order"]
    if scenario.get("top_n"):
        args["top_n"] = scenario["top_n"]
    if scenario.get("rank_universe"):
        args["rank_universe"] = scenario["rank_universe"]

    try:
        data = await _call_mcp("data360_rank_countries", args)
        return {"tool": "rank_countries", "data": data, "error": None}
    except Exception as exc:
        return {"tool": "rank_countries", "data": None, "error": str(exc)}


async def compare_pipeline(scenario: dict) -> dict:
    """Call data360_compare_countries and return a standardised result dict."""
    args: dict = {
        "database_id": scenario["database_id"],
        "indicator_id": scenario["indicator_id"],
        "country_codes": scenario["country_code"],
    }
    if scenario.get("start_year"):
        args["start_year"] = scenario["start_year"]
    if scenario.get("end_year"):
        args["end_year"] = scenario["end_year"]
    if scenario.get("include_time_series"):
        args["include_time_series"] = scenario["include_time_series"]
    if scenario.get("snapshot_year"):
        args["year"] = scenario["snapshot_year"]

    try:
        data = await _call_mcp("data360_compare_countries", args)
        return {"tool": "compare_countries", "data": data, "error": None}
    except Exception as exc:
        return {"tool": "compare_countries", "data": None, "error": str(exc)}


async def summarize_pipeline(scenario: dict) -> dict:
    """Call data360_summarize_data and return a standardised result dict."""
    args: dict = {
        "database_id": scenario["database_id"],
        "indicator_id": scenario["indicator_id"],
    }
    if scenario.get("country_code"):
        args["country_code"] = scenario["country_code"]
    if scenario.get("start_year"):
        args["start_year"] = scenario["start_year"]
    if scenario.get("end_year"):
        args["end_year"] = scenario["end_year"]
    if scenario.get("group_by"):
        args["group_by"] = scenario["group_by"]
    if scenario.get("disaggregation_filters"):
        args["disaggregation_filters"] = scenario["disaggregation_filters"]

    try:
        data = await _call_mcp("data360_summarize_data", args)
        return {"tool": "summarize_data", "data": data, "error": None}
    except Exception as exc:
        return {"tool": "summarize_data", "data": None, "error": str(exc)}


def _build_data_quality_metric() -> GEval:
    """Judge for non-viz tools: rank, compare, summarize."""
    return GEval(
        name="Data Tool Quality Score (0-10)",
        criteria="""
        You are a data analyst scoring the output of a World Bank Data360 data tool.
        The tool was called with specific parameters and returned structured data.
        Score 0-10 across five criteria (2 points each):

        1. DATA PRESENCE (0-2)
           Did the tool return actual data (non-empty, non-error result)?
           2 pts: data present and non-trivial.
           0 pts: error, empty, or null response.

        2. CORRECTNESS (0-2)
           Does the data match the stated scenario parameters?
           - For rank: are the right countries present, in plausible order?
           - For compare: are the specified countries and indicator shown?
           - For summarize: does the summary cover the right time range and geography?

        3. COMPLETENESS (0-2)
           Is the data sufficiently complete for the use case?
           - For rank: are there enough entries (e.g., top 10)?
           - For compare: are all requested countries represented?
           - For summarize: are key statistics (mean, min, max, trend) present?

        4. STATISTICAL COHERENCE (0-2)
           Do the numbers make sense given the indicator and countries?
           - Values within plausible range for the indicator?
           - Rankings consistent with known economic facts?
           - Trends directionally correct?

        5. ACTIONABILITY (0-2)
           Could a researcher use this output directly?
           - Are country names/codes included?
           - Are years and units labeled?
           - Is the structure clear and interpretable?

        Sum the five sub-scores (0-10).
        Write a concise critique and specific recommendations.
        """,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        evaluation_steps=[
            "Read the INPUT: scenario description, tool used, parameters.",
            "Read the ACTUAL_OUTPUT: the tool's JSON response.",
            "Score DATA PRESENCE (0-2): is there non-empty data?",
            "Score CORRECTNESS (0-2): right countries, indicator, time range?",
            "Score COMPLETENESS (0-2): enough entries, all countries, key stats?",
            "Score STATISTICAL COHERENCE (0-2): plausible values and rankings?",
            "Score ACTIONABILITY (0-2): labeled, interpretable, usable?",
            "Sum to 0-10 and write critique + recommendations.",
        ],
        threshold=0.5,
    )


def _build_chained_score_metric() -> GEval:
    """Judge for chained visualization: Data Retrieval -> Charting."""
    return GEval(
        name="Chained Chart Quality Score (0-10)",
        criteria="""
        You are a data visualization expert scoring a Vega-Lite chart generated
        from data retrieved by a Data360 helper tool (rank, compare, or summarize).
        Score 0-10 across five criteria (2 points each):

        1. DATA ALIGNMENT (0-2)
           Did the chart plot the exact same set of countries and years returned
           by the data retrieval step?
           - 2 pts: perfect match of countries and temporal ranges returned by the data retrieval step.
           - 1 pt: minor deviations (e.g. one missing country or year compared to the retrieved set).
           - 0 pts: major mismatch or empty data.
           Do NOT penalize if the retrieved set is small/sparse compared to the original request
           due to upstream database limitations (score only the alignment between retrieval and chart).

        2. SORTING COHERENCE (0-2)
           Does the visual encoding preserve the sorting or comparisons calculated
           in the data retrieval step?
           - For rank: is the chart (e.g. horizontal bar) sorted by the ranked value?
           - For compare: does the visual ordering/highlighting match?
           - 2 pts: sorting/comparison perfectly preserved.
           - 0 pts: sorting is lost or random.

        3. CHART TYPE FIT FOR DATA SHAPE (0-2)
           Is the selected chart type optimal for presenting the retrieved results?
           - Rank output (snapshot year, multi-country) -> horizontal bar chart.
           - Compare output with timeseries -> multi-series line chart.
           - Summarize output -> heatmap or grouped bar.

        4. MUTATION & DATA LOSS (0-2)
           Are all quantitative values and dates from the data output correctly
           represented in the Vega-Lite spec without loss, clipping, or incorrect zeros?
           Check that encoding types are correct (temporal for years, quantitative for values).

        5. READABILITY & CONTEXTUAL ATTRIBUTION (0-2)
           Does the chart title or subtitle explicitly reference the relationship or rank
           context (e.g., "Top 10 Countries by Poverty Rate" or "BRICS GDP Comparison")?
           Are axes labeled with units and gridlines visible?

        Sum the five sub-scores (0-10).
        Write a concise critique and specific recommendations.
        """,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        evaluation_steps=[
            "Read the INPUT: description of the pipeline, data retrieved, target layout.",
            "Read the ACTUAL_OUTPUT: the generated Vega-Lite chart JSON.",
            "Score DATA ALIGNMENT (0-2): exact matching countries/years?",
            "Score SORTING COHERENCE (0-2): ranked order preserved?",
            "Score CHART TYPE FIT (0-2): correct chart family used?",
            "Score MUTATION & DATA LOSS (0-2): values mapped accurately?",
            "Score READABILITY & ATTRIBUTION (0-2): titles describe the rank/comparison context?",
            "Sum to 0-10 and write critique + recommendations.",
        ],
        threshold=0.5,
    )


# Core runner (used by both pytest and CLI)
# ---------------------------------------------------------------------------


async def run_scenario(scenario: dict) -> dict:
    """
    Full pipeline: call the appropriate tool → score the output.

    Dispatches by scenario['mode']:
      'viz' (default) — calls get_viz_spec / get_multi_indicator_viz_spec
      'rank'          — calls rank_countries
      'compare'       — calls compare_countries
      'summarize'     — calls summarize_data
    """
    sid = scenario["id"]
    mode = scenario.get("mode", "viz")

    # ── Dispatch ──────────────────────────────────────────────────────────────
    if mode == "rank":
        tool_result = await asyncio.wait_for(rank_pipeline(scenario), timeout=60)
        data = tool_result.get("data")
        err = tool_result.get("error")
        judge_input = (
            f"SCENARIO: {scenario.get('label', sid)}\n"
            f"DESCRIPTION: {scenario.get('description', '')}\n\n"
            f"TOOL: data360_rank_countries\n"
            f"INDICATOR: {scenario.get('indicator_id')} ({scenario.get('database_id')})\n"
            f"COUNTRY GROUP: {scenario.get('country_group', 'N/A')}\n"
            f"ORDER: {scenario.get('order', 'desc')} | TOP N: {scenario.get('top_n', 10)}\n"
            f"YEAR: {scenario.get('rank_year', 'auto')}\n"
            f"ERROR: {err or 'None'}"
        )
        actual_output = json.dumps(data, indent=2, default=str) if data else json.dumps({"error": err})
        metric = _build_data_quality_metric()
        viz_result = {"error": err, "chart_url": None, "strategy": None, "reason": None,
                      "indicator_id": scenario.get("indicator_id"), "database_id": scenario.get("database_id"),
                      "indicator_name": None, "search_result": None}

    elif mode == "compare":
        tool_result = await asyncio.wait_for(compare_pipeline(scenario), timeout=60)
        data = tool_result.get("data")
        err = tool_result.get("error")
        judge_input = (
            f"SCENARIO: {scenario.get('label', sid)}\n"
            f"DESCRIPTION: {scenario.get('description', '')}\n\n"
            f"TOOL: data360_compare_countries\n"
            f"INDICATOR: {scenario.get('indicator_id')} ({scenario.get('database_id')})\n"
            f"COUNTRIES: {scenario.get('country_code')}\n"
            f"YEARS: {scenario.get('start_year', 'default')} – {scenario.get('end_year', 'default')}\n"
            f"TIME SERIES: {scenario.get('include_time_series', False)}\n"
            f"ERROR: {err or 'None'}"
        )
        actual_output = json.dumps(data, indent=2, default=str) if data else json.dumps({"error": err})
        metric = _build_data_quality_metric()
        viz_result = {"error": err, "chart_url": None, "strategy": None, "reason": None,
                      "indicator_id": scenario.get("indicator_id"), "database_id": scenario.get("database_id"),
                      "indicator_name": None, "search_result": None}

    elif mode == "summarize":
        tool_result = await asyncio.wait_for(summarize_pipeline(scenario), timeout=60)
        data = tool_result.get("data")
        err = tool_result.get("error")
        group_by = scenario.get("group_by", ["ref_area"])
        judge_input = (
            f"SCENARIO: {scenario.get('label', sid)}\n"
            f"DESCRIPTION: {scenario.get('description', '')}\n\n"
            f"TOOL: data360_summarize_data\n"
            f"INDICATOR: {scenario.get('indicator_id')} ({scenario.get('database_id')})\n"
            f"COUNTRIES: {scenario.get('country_code', 'all')}\n"
            f"YEARS: {scenario.get('start_year', 'default')} – {scenario.get('end_year', 'default')}\n"
            f"GROUP BY: {group_by}\n"
            f"ERROR: {err or 'None'}"
        )
        actual_output = json.dumps(data, indent=2, default=str) if data else json.dumps({"error": err})
        metric = _build_data_quality_metric()
        viz_result = {"error": err, "chart_url": None, "strategy": None, "reason": None,
                      "indicator_id": scenario.get("indicator_id"), "database_id": scenario.get("database_id"),
                      "indicator_name": None, "search_result": None}

    elif mode == "chained_viz":
        # Stage 1: call data tool
        data_tool = scenario.get("data_tool", "rank")
        if data_tool == "rank":
            tool_result = await asyncio.wait_for(rank_pipeline(scenario), timeout=60)
            data = tool_result.get("data")
            err = tool_result.get("error")

            # Extract country codes and year
            country_codes = None
            start_year = None
            end_year = None
            if data and isinstance(data, dict):
                rankings = data.get("rankings") or []
                if rankings:
                    country_codes = ";".join(item["ref_area"] for item in rankings if "ref_area" in item)
                snapshot_year = data.get("snapshot", {}).get("year") or scenario.get("rank_year")
                if snapshot_year:
                    try:
                        start_year = int(snapshot_year)
                        end_year = int(snapshot_year)
                    except ValueError:
                        pass

        elif data_tool == "compare":
            tool_result = await asyncio.wait_for(compare_pipeline(scenario), timeout=60)
            data = tool_result.get("data")
            err = tool_result.get("error")
            country_codes = scenario.get("country_code")
            start_year = scenario.get("start_year")
            end_year = scenario.get("end_year")
            ts_dict = {}
            if isinstance(data, str):
                try:
                    data_parsed = json.loads(data)
                    if isinstance(data_parsed, dict):
                        ts_dict = data_parsed.get("time_series", {}).get("series") or {}
                except Exception:
                    pass
            elif isinstance(data, dict):
                ts_dict = data.get("time_series", {}).get("series") or {}
            elif data is not None:
                ts_ts = getattr(data, "time_series", None)
                if ts_ts:
                    ts_dict = getattr(ts_ts, "series", None) or {}

            if ts_dict:
                years = []
                for country_series in ts_dict.values():
                    # Handle if country_series is a list of dicts/objects
                    for entry in country_series:
                        y = None
                        if isinstance(entry, dict):
                            y = entry.get("time_period")
                        elif entry is not None:
                            y = getattr(entry, "time_period", None)
                        if y:
                            try:
                                years.append(int(y))
                            except ValueError:
                                pass
                if years:
                    start_year = min(years)
                    end_year = max(years)

        else: # summarize
            tool_result = await asyncio.wait_for(summarize_pipeline(scenario), timeout=60)
            data = tool_result.get("data")
            err = tool_result.get("error")
            country_codes = scenario.get("country_code")
            start_year = scenario.get("start_year")
            end_year = scenario.get("end_year")

        # Stage 2: Call viz tool using retrieved parameters
        if not err and (country_codes or not scenario.get("country_code")):
            viz_res = await asyncio.wait_for(
                run_viz_pipeline(
                    database_id=scenario.get("database_id"),
                    indicator_id=scenario.get("indicator_id"),
                    country_code=country_codes,
                    start_year=start_year,
                    end_year=end_year,
                    chart_title=scenario.get("chart_title"),
                ),
                timeout=60,
            )
            spec = viz_res.get("spec")
            viz_err = viz_res.get("error")
            viz_result = viz_res
        else:
            spec = None
            viz_err = f"Data retrieval failed: {err}"
            viz_result = {"error": viz_err, "chart_url": None, "strategy": None, "reason": None,
                          "indicator_id": scenario.get("indicator_id"), "database_id": scenario.get("database_id"),
                          "indicator_name": None, "search_result": None}

        # Build judge input with retrieval + charting details
        judge_input = (
            f"SCENARIO: {scenario.get('label', sid)} (Chained Data Retrieval -> Charting)\n"
            f"DESCRIPTION: {scenario.get('description', '')}\n\n"
            f"STAGE 1: RETRIEVED DATA\n"
            f"{json.dumps(data, indent=2, default=str) if data else 'No data (error: ' + str(err) + ')'}\n\n"
            f"STAGE 2: CHART GENERATION\n"
            f"Target Indicator: {scenario.get('indicator_id')}\n"
            f"Retrieved Countries: {country_codes or 'None'}\n"
            f"Retrieved Time: {start_year} - {end_year}\n"
            f"Chart Strategy: {viz_result.get('strategy') or 'None'}\n"
            f"Chart Reason: {viz_result.get('reason') or 'None'}\n"
            f"Chart URL: {viz_result.get('chart_url') or 'None'}\n"
            f"Viz Error: {viz_err or 'None'}"
        )
        actual_output = (
            json.dumps(spec, indent=2)
            if spec
            else json.dumps({"error": "No chart generated", "viz_error": viz_result.get("error", "unknown")})
        )
        metric = _build_chained_score_metric()

    else:
        # Default: viz mode
        viz_result = await asyncio.wait_for(
            run_viz_pipeline(
                database_id=scenario.get("database_id"),
                indicator_id=scenario.get("indicator_id"),
                search_query=scenario.get("search_query"),
                country_code=scenario.get("country_code"),
                start_year=scenario.get("start_year"),
                end_year=scenario.get("end_year"),
                disaggregation_filters=scenario.get("disaggregation_filters"),
                chart_title=scenario.get("chart_title"),
                chart_type=scenario.get("chart_type"),
                indicator_ids=scenario.get("indicator_ids"),
                database_ids=scenario.get("database_ids"),
            ),
            timeout=90,
        )
        spec = viz_result.get("spec")
        judge_input = (
            f"SCENARIO: {scenario.get('label', sid)}\n"
            f"DESCRIPTION: {scenario.get('description', 'No description provided.')}\n\n"
            f"INDICATOR: {viz_result.get('indicator_id')} "
            f"({viz_result.get('indicator_name') or 'name unknown'})\n"
            f"DATABASE: {viz_result.get('database_id')}\n"
            f"COUNTRIES: {scenario.get('country_code', 'all/default')}\n"
            f"YEARS: {scenario.get('start_year', 'default')} – {scenario.get('end_year', 'default')}\n"
            f"DISAGGREGATION FILTERS: {json.dumps(scenario.get('disaggregation_filters')) or 'none'}\n\n"
            f"ROUTING STRATEGY: {viz_result.get('strategy') or 'unknown'}\n"
            f"ROUTING REASON: {viz_result.get('reason') or 'N/A'}\n"
            f"CHART URL: {viz_result.get('chart_url') or 'None — chart not generated'}\n"
            f"VIZ ERROR: {viz_result.get('error') or 'None'}"
        )
        actual_output = (
            json.dumps(spec, indent=2)
            if spec
            else json.dumps({"error": "No chart generated", "viz_error": viz_result.get("error", "unknown")})
        )
        metric = _build_score_metric()

    # ── Score ─────────────────────────────────────────────────────────────────
    test_case = LLMTestCase(input=judge_input, actual_output=actual_output)
    metric.measure(test_case)

    score_10 = round((metric.score or 0.0) * 10, 1)
    critique = metric.reason or ""

    # Pass the raw tool output/data to save_report (for rank, compare, summarize, chained_viz modes)
    tool_data_to_save = data if mode in ("rank", "compare", "summarize", "chained_viz") else None
    report_path = save_report(sid, scenario, viz_result, score_10, critique, tool_data=tool_data_to_save)

    return {
        "scenario_id": sid,
        "score": score_10,
        "critique": critique,
        "chart_url": viz_result.get("chart_url"),
        "strategy": viz_result.get("strategy"),
        "reason": viz_result.get("reason"),
        "indicator_id": viz_result.get("indicator_id"),
        "error": viz_result.get("error"),
        "report_path": report_path,
        "test_case": test_case,
        "metric": metric,
    }


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

SCENARIOS: list[dict] = [
    # ── Temporal / multi-country ──────────────────────────────────────────────
    {
        "id": "01_gdp_growth_latam",
        "label": "GDP Growth — Brazil, Argentina, Mexico (2015–2023)",
        "description": (
            "Multi-country temporal trend. Expected: multi-series line chart "
            "with year on x-axis and color encoding per country."
        ),
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG",
        "country_code": "BRA;ARG;MEX",
        "start_year": 2015,
        "end_year": 2023,
    },
    {
        "id": "02_life_expectancy_east_asia",
        "label": "Life Expectancy — East Asia (2000–2022)",
        "description": (
            "Multi-country temporal trend. Expected: line chart, one line per country, "
            "x=year, y=life expectancy in years."
        ),
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_SP_DYN_LE00_IN",
        "country_code": "CHN;JPN;KOR;VNM;THA",
        "start_year": 2000,
        "end_year": 2022,
    },
    # ── Cross-sectional / ranking ─────────────────────────────────────────────
    {
        "id": "03_poverty_sub_saharan",
        "label": "Poverty Headcount — Sub-Saharan Africa (latest year)",
        "description": (
            "Cross-sectional ranking. Expected: horizontal bar chart sorted by value, "
            "countries on y-axis."
        ),
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_SI_POV_DDAY",
        "country_code": "NGA;ETH;COD;KEN;TZA;MOZ;UGA;GHA;ZMB;MDG",
        "start_year": 2020,
        "end_year": 2022,
    },
    # ── Sex disaggregation ────────────────────────────────────────────────────
    {
        "id": "04_labor_force_by_sex_india",
        "label": "Labor Force Participation by Sex — India (2010–2022)",
        "description": (
            "Two-indicator sex comparison: female vs male labor force participation. "
            "Expected: two-series line chart with one line per sex (Male/Female), "
            "distinct colors, x=year, y=participation rate (%)."
        ),
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": [
            "WB_WDI_SL_TLF_CACT_FE_ZS",   # female labour force participation
            "WB_WDI_SL_TLF_CACT_MA_ZS",   # male labour force participation
        ],
        "country_code": "IND",
        "start_year": 2010,
        "end_year": 2022,
    },
    {
        "id": "05_labor_force_sex_south_asia",
        "label": "Labor Force Participation by Sex — South Asia multi-country",
        "description": (
            "4 countries, female indicator. Expected: multi-series line, one per country. "
            "If sex dimension available, color=sex."
        ),
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_SL_TLF_CACT_FE_ZS",
        "country_code": "IND;PAK;BGD;LKA",
        "start_year": 2010,
        "end_year": 2022,
    },
    # ── Urban/rural disaggregation ────────────────────────────────────────────
    {
        "id": "06_water_access_urban_rural",
        "label": "Water Access Urban vs Rural — Bangladesh (2000–2022)",
        "description": (
            "Indicator with RESIDENCE disaggregation. Expected: two-line chart "
            "with color=residence (Urban/Rural), x=year."
        ),
        "database_id": "WB_CLEAR",
        "indicator_id": "WB_CLEAR_JMP_DW_SFMS",
        "country_code": "BGD",
        "start_year": 2000,
        "end_year": 2022,
        "disaggregation_filters": {"URBANISATION": None},
    },
    # ── Multi-indicator / dual ────────────────────────────────────────────────
    {
        "id": "07_gdp_inflation_south_africa",
        "label": "GDP Growth + Inflation — South Africa (2010–2023)",
        "description": (
            "Two indicators, one country, multi-year. Expected: faceted subplots "
            "or layered lines with independent y-axes."
        ),
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_NY_GDP_MKTP_KD_ZG", "WB_WDI_FP_CPI_TOTL_ZG"],
        "country_code": "ZAF",
        "start_year": 2010,
        "end_year": 2023,
    },
    {
        "id": "08_gdp_vs_life_expectancy_scatter",
        "label": "GDP per Capita vs Life Expectancy — Cross-country Scatter (2022)",
        "description": (
            "Two indicators, many countries, single year. Expected: scatter plot "
            "with x=GDP, y=life expectancy, color=country/region."
        ),
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_NY_GDP_PCAP_KD", "WB_WDI_SP_DYN_LE00_IN"],
        "country_code": "USA;CHN;IND;BRA;DEU;GBR;JPN;ZAF;NGN;IDN;MEX;ARG;COL;EGY;PAK",
        "start_year": 2022,
        "end_year": 2022,
    },
    # ── Search-resolved indicator ─────────────────────────────────────────────
    {
        "id": "09_gini_search_resolved",
        "label": "Gini Coefficient — Search-resolved, Global (latest)",
        "description": (
            "Indicator resolved via search. Expected: choropleth map or horizontal "
            "bar chart depending on country count returned."
        ),
        "search_query": "Gini coefficient",
        "start_year": 2018,
        "end_year": 2022,
    },
    {
        "id": "10_electricity_access_africa",
        "label": "Electricity Access — Sub-Saharan Africa (search-resolved)",
        "description": (
            "Indicator resolved via search with country filter. Expected: multi-series "
            "line or cross-sectional bar."
        ),
        "search_query": "access to electricity",
        "country_code": "NGA;ETH;KEN;GHA;SEN;ZMB;MOZ;TZA",
        "start_year": 2010,
        "end_year": 2022,
    },
    # ── Reporting gap ─────────────────────────────────────────────────────────
    {
        "id": "11_gdp_reporting_gap",
        "label": "GDP Growth — Nepal (sparse reporting, gap detection)",
        "description": (
            "Single country with sparse data years. Expected: line chart with dashed "
            "segment (LineYearGapStrokeDashRule) for reporting gaps."
        ),
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG",
        "country_code": "NPL",
        "start_year": 2010,
        "end_year": 2022,
    },
    # ── High-cardinality / facet ──────────────────────────────────────────────
    {
        "id": "12_inflation_g20_heatmap",
        "label": "Inflation Rate — G20 Countries Matrix (2015–2023)",
        "description": (
            "Many countries × many years matrix. Expected: heatmap grid "
            "(country vs year), or a small-multiples line chart."
        ),
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_FP_CPI_TOTL_ZG",
        "country_code": "USA;CHN;DEU;GBR;JPN;FRA;ITA;CAN;AUS;KOR;MEX;BRA;IND;IDN;ZAF;TUR;SAU;ARG;RUS",
        "start_year": 2015,
        "end_year": 2023,
    },
    {
        "id": "13_public_employment_wwbi",
        "label": "Public Employment relative to total (WB_WWBI)",
        "description": (
            "Explores labor market footprint of government employment. Expected: "
            "small multiples line chart by country with gender color encoding."
        ),
        "database_id": "WB_WWBI",
        "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": "MEX;COL;CHL",
        "start_year": 2010,
        "end_year": 2020,
        "chart_title": "Public Sector Employment as % of Total Employment",
    },
    # ── Chained Data Retrieval -> Charting ────────────────────────────────────
    {
        "id": "19_chained_rank_co2",
        "label": "Chained — Rank G20 CO2 Emitters & Chart",
        "description": (
            "Calls rank_countries for CO2 emissions per capita (descending, top 10), "
            "then extracts country codes to generate a sorted bar chart for that snapshot year."
        ),
        "mode": "chained_viz",
        "data_tool": "rank",
        "database_id": "WB_ESG",
        "indicator_id": "WB_ESG_EN_ATM_CO2E_PC",
        "country_code": "USA;CHN;DEU;GBR;JPN;FRA;ITA;CAN;AUS;KOR;MEX;BRA;IND;IDN;ZAF;TUR;SAU;ARG;RUS",
        "order": "desc",
        "top_n": 10,
        "rank_year": 2020,
        "chart_title": "Top 10 G20 CO2 Emitters Per Capita (2020)",
    },
    {
        "id": "20_chained_compare_gdp",
        "label": "Chained — Compare BRICS GDP & Chart",
        "description": (
            "Calls compare_countries for BRICS GDP per capita timeseries (2010–2022), "
            "then feeds retrieved parameters into viz spec to generate a multi-series line chart."
        ),
        "mode": "chained_viz",
        "data_tool": "compare",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
        "country_code": "BRA;RUS;IND;CHN;ZAF",
        "start_year": 2010,
        "end_year": 2022,
        "include_time_series": True,
        "chart_title": "BRICS GDP Per Capita (2010-2022)",
    },
    # ── Population Pyramid & Confidence Bands ─────────────────────────────────
    {
        "id": "21_pop_pyramid_kenya",
        "label": "Population Pyramid — Kenya (2020)",
        "description": (
            "Age and sex breakdown. Expected: diverging population pyramid bar chart "
            "with age on y-axis, male/female on opposite sides of x-axis."
        ),
        "database_id": "WB_HNP",
        "indicator_id": "WB_HNP_SP_POP_5Y",
        "country_code": "KEN",
        "start_year": 2020,
        "end_year": 2020,
        "chart_type": "pyramid",
        "disaggregation_filters": {"SEX": None, "AGE": None, "UNIT_MEASURE": "COUNT"},
        "chart_title": "Population Pyramid — Kenya (2020)",
    },
    {
        "id": "22_wgi_confidence_band",
        "label": "WGI Voice & Accountability — Confidence Intervals",
        "description": (
            "Governance score with confidence bounds over time. Expected: layered chart "
            "with estimate line and shaded upper/lower bound error band area."
        ),
        "database_id": "WB_WGI",
        "indicator_id": "GOV_WGI_VA",
        "country_code": "KEN",
        "start_year": 2010,
        "end_year": 2023,
        "disaggregation_filters": {"COMP_BREAKDOWN_1": None},
        "chart_title": "WGI Voice & Accountability — Kenya (2010–2023)",
    },
    # ── Non-World Bank Databases & Cross-Database ─────────────────────────────
    {
        "id": "23_democracy_index_brics",
        "label": "Democracy Index — BRICS Countries (2010–2023)",
        "description": (
            "Using EIU Democracy Index. Expected: multi-series line chart "
            "comparing BRICS democracy scores over time."
        ),
        "database_id": "EIU_DI",
        "indicator_id": "EIU_DI_INDEX",
        "country_code": "BRA;RUS;IND;CHN;ZAF",
        "start_year": 2010,
        "end_year": 2023,
        "chart_title": "EIU Democracy Index — BRICS (2010–2023)",
    },
    {
        "id": "24_liberal_democracy_timeseries",
        "label": "Liberal Democracy Index — G7 Countries (2015–2024)",
        "description": (
            "Using V-Dem Core Liberal Democracy Index. Expected: multi-series line chart "
            "comparing G7 democracy scores."
        ),
        "database_id": "VDEM_CORE",
        "indicator_id": "VDEM_CORE_V2X_LIBDEM",
        "country_code": "USA;GBR;FRA;DEU;ITA;JPN;CAN",
        "start_year": 2015,
        "end_year": 2024,
        "chart_title": "V-Dem Liberal Democracy Index — G7 (2015–2024)",
    },
    {
        "id": "25_co2_per_capita_owid",
        "label": "CO2 Emissions Per Capita — OWID (2000–2022)",
        "description": (
            "Using Our World in Data CO2 database. Expected: multi-series line chart "
            "comparing major emitters."
        ),
        "database_id": "OWID_CB",
        "indicator_id": "OWID_CB_CO2_PER_CAPITA",
        "country_code": "USA;CHN;IND;BRA;DEU;JPN",
        "start_year": 2000,
        "end_year": 2022,
        "chart_title": "CO2 Emissions Per Capita (Our World in Data)",
    },
    {
        "id": "27_gdp_vs_democracy_log_scatter",
        "label": "Democracy Index vs GDP per Capita — Log-Scaled Scatter (2022)",
        "description": (
            "Multi-indicator cross-sectional scatter plot using EIU Democracy Index "
            "and WDI GDP per capita. GDP per capita has extremely high positive skewness, "
            "and should trigger automatic log scaling on its axis for readability."
        ),
        "database_ids": ["WB_WDI", "EIU_DI"],
        "indicator_ids": ["WB_WDI_NY_GDP_PCAP_KD", "EIU_DI_INDEX"],
        "country_code": "USA;CHN;IND;BRA;DEU;GBR;JPN;ZAF;NGA;IDN;MEX;ARG;FRA;ITA;CAN;AUS;KOR;TUR;SAU;RUS;SWE;NOR;DNK;BDI;CAF;NER;MOZ;MDG;MWI;YEM",
        "start_year": 2022,
        "end_year": 2022,
        "chart_title": "Democracy Index vs GDP per Capita (Log-Scaled GDP, 2022)",
    },
    {
        "id": "28_population_skewness_log",
        "label": "Total Population — Log-Scaled Bar (2022)",
        "description": (
            "Cross-sectional population comparison of mixed sized economies in 2022. "
            "Expected: horizontal bar chart with log-scaled x-axis due to wide range of "
            "population sizes (from Seychelles to India/China)."
        ),
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_SP_POP_TOTL",
        "country_code": "ISL;SYC;MDV;LUX;SGP;BEL;SWE;CAN;GBR;DEU;USA;IND;CHN",
        "start_year": 2022,
        "end_year": 2022,
        "chart_title": "Total Population — Log-Scaled (2022)",
    },
    {
        "id": "29_gdp_pcap_us_long_trend",
        "label": "United States GDP per Capita — Long-Term Trend (1970–2022)",
        "description": (
            "Single country long-term temporal trend. Expected: simple line chart "
            "showing United States GDP per capita from 1970 to 2022."
        ),
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
        "country_code": "USA",
        "start_year": 1970,
        "end_year": 2022,
        "chart_title": "United States GDP per Capita Trend (1970–2022)",
    },
    {
        "id": "30_gdp_vs_inflation_brazil_temp",
        "label": "GDP Growth vs Inflation Rate — Brazil (2000–2022)",
        "description": (
            "Multi-indicator temporal trend for a single country. GDP growth rate vs "
            "Inflation rate in Brazil (2000–2022). Both share the unit 'annual %', so they "
            "should be plotted on the same Y-axis."
        ),
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_NY_GDP_MKTP_KD_ZG", "WB_WDI_FP_CPI_TOTL_ZG"],
        "country_code": "BRA",
        "start_year": 2000,
        "end_year": 2022,
        "chart_title": "GDP Growth vs Inflation Rate — Brazil (2000–2022)",
    },
    {
        "id": "31_gdp_growth_europe_east",
        "label": "GDP Growth — Eastern Europe (2014–2022)",
        "description": "Multi-country economic growth trend. Expected: line chart, one series per country, x=year, y=GDP growth (annual %).",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG",
        "country_code": "POL;UKR;ROU;HUN",
        "start_year": 2014,
        "end_year": 2022,
        "chart_title": "GDP Growth — Eastern Europe (2014–2022)",
    },
    {
        "id": "32_inflation_south_america",
        "label": "Inflation CPI — South America (2018–2023)",
        "description": "Multi-country consumer price inflation comparison. Expected: line chart comparing inflation rates over time.",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_FP_CPI_TOTL_ZG",
        "country_code": "BRA;ARG;COL;CHL;PER",
        "start_year": 2018,
        "end_year": 2023,
        "chart_title": "Consumer Price Inflation — South America (2018–2023)",
    },
    {
        "id": "33_co2_vs_forest_brazil",
        "label": "CO2 Emissions vs Forest Area — Brazil (2000–2020)",
        "description": "Two-indicator temporal correlation: CO2 emissions per capita vs Forest area (% of land area) over time in Brazil. Expected: path/connected scatterplot.",
        "database_ids": ["WB_ESG", "WB_ESG"],
        "indicator_ids": ["WB_ESG_EN_ATM_CO2E_PC", "WB_ESG_AG_LND_FRST_ZS"],
        "country_code": "BRA",
        "start_year": 2000,
        "end_year": 2020,
        "chart_title": "CO2 Emissions vs Forest Cover — Brazil (2000–2020)",
    },
    {
        "id": "34_safely_managed_water_africa",
        "label": "Safely Managed Water Access — East & West Africa (2015–2022)",
        "description": "Multi-country basic services trend. Expected: line chart comparing safely managed drinking water access.",
        "database_id": "WB_ESG",
        "indicator_id": "WB_ESG_SH_H2O_SMDW_ZS",
        "country_code": "NGA;KEN;UGA;RWA",
        "start_year": 2015,
        "end_year": 2022,
        "chart_title": "People Using Safely Managed Drinking Water (% of Population)",
    },
    {
        "id": "35_unemployment_imf_g7",
        "label": "Unemployment Rate — G7 Countries (2018–2023)",
        "description": "Multi-country unemployment rate comparison using IMF WEO. Expected: line chart, G7 countries, x=year, y=unemployment rate (%).",
        "database_id": "IMF_WEO",
        "indicator_id": "IMF_WEO_LUR",
        "country_code": "USA;GBR;FRA;DEU;ITA;JPN;CAN",
        "start_year": 2018,
        "end_year": 2023,
        "chart_title": "Unemployment Rate — G7 Countries (IMF WEO)",
    },
    {
        "id": "36_chained_rank_life_expectancy",
        "label": "Chained — Top 15 Life Expectancy (2022)",
        "description": "Calls rank_countries for life expectancy at birth (descending, top 15) in 2022, then extracts country codes to generate a sorted bar chart.",
        "mode": "chained_viz",
        "data_tool": "rank",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_SP_DYN_LE00_IN",
        "country_code": "USA;CHN;JPN;DEU;FRA;ITA;GBR;CAN;AUS;ESP;SWE;NOR;CHE;SGP;KOR;BRA;MEX;ZAF;IND;IDN",
        "order": "desc",
        "top_n": 15,
        "rank_year": 2022,
        "chart_title": "Top 15 Countries by Life Expectancy at Birth (2022)",
    },
    {
        "id": "37_chained_compare_inflation",
        "label": "Chained — High Inflation Comparison (2015–2023)",
        "description": "Calls compare_countries for high inflation countries (Turkey, Argentina), then generates a multi-series line chart.",
        "mode": "chained_viz",
        "data_tool": "compare",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_FP_CPI_TOTL_ZG",
        "country_code": "TUR;ARG",
        "start_year": 2015,
        "end_year": 2023,
        "include_time_series": True,
        "chart_title": "Consumer Price Inflation Trend (2015–2023)",
    },
    {
        "id": "38_secondary_school_enrollment",
        "label": "Secondary School Enrollment — South Asia (2010–2022)",
        "description": "Multi-country education trend. Expected: line chart of gross secondary enrollment rates.",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_SE_SEC_ENRR",
        "country_code": "IND;PAK;BGD",
        "start_year": 2010,
        "end_year": 2022,
        "chart_title": "Secondary Education Enrollment (Gross %)",
    },
    {
        "id": "39_urban_population_share",
        "label": "Urban Population Share — Asia (2000–2022)",
        "description": "Multi-country urbanization trend. Expected: line chart of urban population % of total.",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_SP_URB_TOTL_IN_ZS",
        "country_code": "CHN;IND;IDN;VNM",
        "start_year": 2000,
        "end_year": 2022,
        "chart_title": "Urban Population (% of Total Population)",
    },
    {
        "id": "40_tuberculosis_incidence_africa",
        "label": "Tuberculosis Incidence — East & South Africa (2015–2022)",
        "description": "Multi-country health trend. Expected: line chart of TB incidence rates per 100k.",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_SH_TBS_INCD",
        "country_code": "ZAF;NGA;ETH;KEN",
        "start_year": 2015,
        "end_year": 2022,
        "chart_title": "Tuberculosis Incidence (per 100,000 People)",
    },
    {
        "id": "41_energy_vs_co2_china",
        "label": "CO2 Emissions vs Forest Coverage — China (2010–2022)",
        "description": "Multi-indicator temporal trend for a single country. CO2 emissions and forest coverage indicators on different scales. Expected: dual Y-axis or faceted subplots.",
        "database_ids": ["WB_ESG", "WB_ESG"],
        "indicator_ids": ["WB_ESG_EN_ATM_CO2E_PC", "WB_ESG_AG_LND_FRST_ZS"],
        "country_code": "CHN",
        "start_year": 2010,
        "end_year": 2022,
        "chart_title": "CO2 Emissions vs Forest Coverage in China (2010-2022)",
    },
    {
        "id": "42_electricity_vs_poverty_india",
        "label": "Electricity Access vs Poverty Headcount — India (2000–2021)",
        "description": "Multi-indicator temporal correlation: electricity access % vs poverty headcount % over time in India. Expected: path/connected scatterplot.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_EG_ELC_ACCS_ZS", "WB_WDI_SI_POV_DDAY"],
        "country_code": "IND",
        "start_year": 2000,
        "end_year": 2021,
        "chart_title": "Electricity Access vs Poverty Rate — India (2000–2021)",
    },
    {
        "id": "43_chained_summarize_gdp_growth",
        "label": "Chained — Summarize G7 GDP Growth Trend (2018–2022)",
        "description": "Calls summarize_data for G7 GDP growth trend (2018–2022), then feeds outputs into viz engine for line chart.",
        "mode": "chained_viz",
        "data_tool": "summarize",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG",
        "country_code": "USA;GBR;FRA;DEU;ITA;JPN;CAN",
        "start_year": 2018,
        "end_year": 2022,
        "chart_title": "G7 GDP Growth Trend Summary (2018–2022)",
    },
    {
        "id": "44_imf_gdp_growth_east_asia",
        "label": "GDP Growth — East Asia (IMF WEO, 2010–2023)",
        "description": "Multi-country temporal comparison using IMF WEO. Expected: line chart, x=year, y=GDP constant prices % change.",
        "database_id": "IMF_WEO",
        "indicator_id": "IMF_WEO_NGDP_RPCH",
        "country_code": "CHN;JPN;KOR;VNM",
        "start_year": 2010,
        "end_year": 2023,
        "chart_title": "Gross Domestic Product Growth (IMF WEO, 2010–2023)",
    },
    {
        "id": "45_vdem_nordic_democracy",
        "label": "Liberal Democracy Index — Nordic Countries (2015–2024)",
        "description": "Nordic countries comparison of V-Dem liberal democracy. Expected: line chart comparing scores over time.",
        "database_id": "VDEM_CORE",
        "indicator_id": "VDEM_CORE_V2X_LIBDEM",
        "country_code": "SWE;NOR;DNK;FIN;ISL",
        "start_year": 2015,
        "end_year": 2024,
        "chart_title": "V-Dem Liberal Democracy Index — Nordic Countries (2015–2024)",
    },
    {
        "id": "46_chained_rank_poverty",
        "label": "Chained — Top 10 Poverty Headcount Africa (2020)",
        "description": "Rank countries by poverty rate ($2.15/day) in Africa (2020), then generate a sorted bar chart.",
        "mode": "chained_viz",
        "data_tool": "rank",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_SI_POV_DDAY",
        "country_code": "NGA;ETH;COD;KEN;TZA;MOZ;UGA;GHA;ZMB;MDG;RWA;MWI;ZWE;AGO;SEN",
        "order": "desc",
        "top_n": 10,
        "rank_year": 2020,
        "chart_title": "Top 10 Poverty Headcount Rates in Select African Countries (2020)",
    },
    {
        "id": "47_wgi_control_of_corruption",
        "label": "WGI Control of Corruption — Latin America (2015–2023)",
        "description": "Governance score comparison over time. Expected: multi-series line chart comparing estimate scores.",
        "database_id": "WB_WGI",
        "indicator_id": "GOV_WGI_CC",
        "country_code": "MEX;BRA;ARG;CHL;COL",
        "start_year": 2015,
        "end_year": 2023,
        "chart_title": "WGI Control of Corruption Estimate (2015–2023)",
    },
    {
        "id": "48_labor_force_participation_mideast",
        "label": "Labor Force Participation — Middle East & North Africa (2015–2023)",
        "description": "Multi-country labor comparison. Expected: line chart comparing total labor force participation rates.",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_SL_TLF_CACT_ZS",
        "country_code": "SAU;ARE;EGY;JOR",
        "start_year": 2015,
        "end_year": 2023,
        "chart_title": "Labor Force Participation Rate (% of Population 15+)",
    },
    {
        "id": "49_co2_per_capita_g20_heatmap",
        "label": "CO2 Emissions Per Capita Matrix — G20 Countries (2010–2020)",
        "description": "Heatmap matrix for carbon footprint in G20 economies over time. Expected: heatmap grid.",
        "database_id": "WB_ESG",
        "indicator_id": "WB_ESG_EN_ATM_CO2E_PC",
        "country_code": "USA;CHN;DEU;GBR;JPN;FRA;ITA;CAN;AUS;KOR;MEX;BRA;IND;IDN;ZAF;TUR;SAU;ARG;RUS",
        "start_year": 2010,
        "end_year": 2020,
        "chart_title": "CO2 Emissions Per Capita Matrix (2010–2020)",
    },
    {
        "id": "50_democracy_index_asean",
        "label": "Democracy Index — ASEAN Countries (2015–2023)",
        "description": "EIU Democracy Index score in select Southeast Asian nations. Expected: line chart comparing scores.",
        "database_id": "EIU_DI",
        "indicator_id": "EIU_DI_INDEX",
        "country_code": "IDN;MYS;PHL;THA;SGP;VNM",
        "start_year": 2015,
        "end_year": 2023,
        "chart_title": "EIU Democracy Index — Southeast Asia (2015–2023)",
    },
    {
        "id": "51_egypt_population_area",
        "label": "Total Population Trend — Egypt (2010–2020)",
        "description": "Single-indicator temporal trend for a single country. User requested area chart. Expected: area chart.",
        "database_id": "WB_WDI",
        "indicator_id": "WB_WDI_SP_POP_TOTL",
        "country_code": "EGY",
        "start_year": 2010,
        "end_year": 2020,
        "chart_type": "area",
        "chart_title": "Total Population Trend in Egypt (2010–2020)",
    },
    {
        "id": "52_india_urban_rural_stacked_area",
        "label": "Urban vs Rural Population Split — India (2000–2020)",
        "description": "Multi-indicator temporal trend representing mutually exclusive additive parts of a whole (urban headcount + rural headcount = total population). Expected: stacked area chart.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_SP_URB_TOTL", "WB_WDI_SP_RUR_TOTL"],
        "country_code": "IND",
        "start_year": 2000,
        "end_year": 2020,
        "chart_type": "stacked_area",
        "chart_title": "Urban vs Rural Population Headcount in India (2000–2020)",
    },
    {
        "id": "53_germany_gdp_sectors_stacked_bar",
        "label": "GDP Shares by Economic Sector — Germany (2022)",
        "description": "Multi-indicator cross-sectional snapshot of economic sectors (% of GDP). Expected: vertical stacked bar chart.",
        "database_ids": ["WB_WDI", "WB_WDI", "WB_WDI"],
        "indicator_ids": [
            "WB_WDI_NV_AGR_TOTL_ZS",
            "WB_WDI_NV_IND_TOTL_ZS",
            "WB_WDI_NV_SRV_TOTL_ZS",
        ],
        "country_code": "DEU",
        "start_year": 2022,
        "end_year": 2022,
        "chart_type": "stacked_bar",
        "chart_title": "GDP Shares by Economic Sector in Germany (2022)",
    },
]


# ---------------------------------------------------------------------------
# Pytest test functions (one per scenario)
# ---------------------------------------------------------------------------


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_01_gdp_growth_latam():
    """01 — GDP growth multi-country temporal line chart."""
    r = await run_scenario(SCENARIOS[0])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_02_life_expectancy_east_asia():
    """02 — Life expectancy, East Asia, multi-series line."""
    r = await run_scenario(SCENARIOS[1])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_03_poverty_sub_saharan():
    """03 — Poverty headcount, Sub-Saharan Africa, cross-sectional bar."""
    r = await run_scenario(SCENARIOS[2])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_04_labor_force_sex_india():
    """04 — Female labor force participation, India, sex breakdown."""
    r = await run_scenario(SCENARIOS[3])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_05_labor_force_sex_south_asia():
    """05 — Labor force, South Asia 4-country comparison."""
    r = await run_scenario(SCENARIOS[4])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_06_water_access_urban_rural():
    """06 — Water access, Bangladesh, urban vs rural (search-resolved)."""
    r = await run_scenario(SCENARIOS[5])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_07_gdp_inflation_south_africa():
    """07 — GDP + Inflation, South Africa, dual-indicator layered/facet."""
    r = await run_scenario(SCENARIOS[6])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_08_gdp_vs_life_expectancy_scatter():
    """08 — GDP per capita vs life expectancy, scatter correlation."""
    r = await run_scenario(SCENARIOS[7])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_09_gini_search_resolved():
    """09 — Gini coefficient, indicator resolved via search."""
    r = await run_scenario(SCENARIOS[8])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_10_electricity_access_africa():
    """10 — Electricity access, Sub-Saharan Africa, search-resolved."""
    r = await run_scenario(SCENARIOS[9])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_11_gdp_reporting_gap():
    """11 — GDP growth, Nepal, gap-detection dashed line rule."""
    r = await run_scenario(SCENARIOS[10])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_12_inflation_g20_heatmap():
    """12 — Inflation, G20 matrix, heatmap or small multiples."""
    r = await run_scenario(SCENARIOS[11])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_13_public_employment_wwbi():
    """13 — WWBI government public employment breakdown comparison."""
    r = await run_scenario(SCENARIOS[12])
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_19_chained_rank_co2():
    """19 — chained_viz: rank G20 CO2 emitters and generate bar chart."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "19_chained_rank_co2"))
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_20_chained_compare_gdp():
    """20 — chained_viz: compare BRICS GDP and generate line chart."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "20_chained_compare_gdp"))
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_21_pop_pyramid_kenya():
    """21 — viz: population pyramid for Kenya."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "21_pop_pyramid_kenya"))
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_22_wgi_confidence_band():
    """22 — viz: WGI governance score line chart with confidence error bands."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "22_wgi_confidence_band"))
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_23_democracy_index_brics():
    """23 — viz: EIU Democracy Index BRICS timeseries."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "23_democracy_index_brics"))
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_24_liberal_democracy_timeseries():
    """24 — viz: V-Dem Liberal Democracy G7 timeseries."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "24_liberal_democracy_timeseries"))
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_25_co2_per_capita_owid():
    """25 — viz: OWID CO2 per capita comparison."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "25_co2_per_capita_owid"))
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_26_democracy_vs_gdp_scatter():
    """26 — viz: V-Dem Democracy vs WDI GDP per capita scatter."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "26_democracy_vs_gdp_scatter"))
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_27_gdp_vs_democracy_log_scatter():
    """27 — viz: EIU Democracy Index vs WDI GDP per capita scatter with log-scale GDP."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "27_gdp_vs_democracy_log_scatter"))
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_28_population_skewness_log():
    """28 — viz: Total population log-scaled bar chart."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "28_population_skewness_log"))
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_29_gdp_pcap_us_long_trend():
    """29 — viz: United States GDP per capita long-term trend line chart."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "29_gdp_pcap_us_long_trend"))
    assert_test(r["test_case"], [r["metric"]])


@skip_if_offline
@pytest.mark.asyncio
async def test_viz_30_gdp_vs_inflation_brazil_temp():
    """30 — viz: GDP growth vs Inflation rate temporal line chart for Brazil."""
    r = await run_scenario(next(s for s in SCENARIOS if s["id"] == "30_gdp_vs_inflation_brazil_temp"))
    assert_test(r["test_case"], [r["metric"]])
