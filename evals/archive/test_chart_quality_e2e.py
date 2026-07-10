"""
Agentic End-to-End Chart Quality Evaluation
=============================================

Simulates an MCP-enabled LLM agent (GPT-4o with function calling) receiving a
natural language question about development data, autonomously deciding which
Data360 MCP tools to call, generating a Vega-Lite chart WITHOUT any chart_type
hint, and then scoring the result 0–10 across 5 charting criteria.

This is the closest approximation to what happens in VSCode (or any MCP-enabled
application) when a user asks a data question — the LLM is driving tool selection
and argument construction entirely on its own.

Prerequisites:
    1. MCP server running:
         uv run poe serve
       or:
         uv run fastmcp run src/data360/server.py \\
             --transport streamable-http --port 8021

    2. OPENAI_API_KEY set in environment.

Run:
    uv run deepeval test run evals/test_chart_quality_e2e.py -v

The ``chart_type`` parameter is STRIPPED from the tool schema before the agent
sees it. The routing engine selects the chart type purely based on data shape,
with no hint from the agent — exactly how an unprompted real user query works.

Each test produces a JSON report in evals/reports/ containing the agent trace,
chart URL, per-criterion scores, written critique, and recommendations.
"""

from __future__ import annotations

import asyncio
import copy
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

# Load environment variables from .env files (supports dotenv in uv subprocess).
# Priority: .env.evals (eval-specific overrides) > .env (shared project env)
try:
    from dotenv import load_dotenv
    _repo_root = Path(__file__).parent.parent
    load_dotenv(_repo_root / ".env.evals", override=False)  # eval-specific key file
    load_dotenv(_repo_root / ".env", override=False)        # project defaults
except ImportError:
    pass  # python-dotenv optional; key must be in os.environ directly

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCP_BASE_URL = os.environ.get("MCP_BASE_URL", "http://localhost:8021")
MCP_URL = f"{MCP_BASE_URL}/mcp"
STATIC_BASE = MCP_BASE_URL

REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

MAX_AGENT_TURNS = 8  # Max tool-call rounds before giving up
AGENT_TIMEOUT_S = 120  # Per-test timeout in seconds

# Tools that produce a chart spec — we watch for these in the agent loop.
VIZ_TOOL_NAMES = {"data360_get_viz_spec", "data360_get_multi_indicator_viz_spec"}

# Parameters stripped from viz tool schemas so the agent cannot pass a chart
# type hint — routing must happen purely from data shape.
_STRIP_PARAMS = {"chart_type", "custom_constraints", "use_default_constraints"}


# ---------------------------------------------------------------------------
# Preflight check — skip all tests if server is not reachable
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
    """Decorator: skip test when the MCP server is not running or OPENAI_API_KEY is missing."""
    return pytest.mark.skipif(
        not SERVER_UP or not OPENAI_KEY_SET,
        reason=(
            f"Skipped: "
            + (f"MCP server not reachable at {MCP_BASE_URL} (run: uv run poe serve). " if not SERVER_UP else "")
            + ("OPENAI_API_KEY not set in environment. " if not OPENAI_KEY_SET else "")
        ),
    )(fn)


# ---------------------------------------------------------------------------
# MCP client helpers
# ---------------------------------------------------------------------------


async def _list_tools() -> list[dict]:
    """List all tools from the live MCP server and return as dicts."""
    from fastmcp import Client

    async with Client(MCP_URL) as client:
        tools = await client.list_tools()
    return tools


async def _call_mcp_tool(tool_name: str, arguments: dict) -> Any:
    """Call a single MCP tool and return the parsed content."""
    from fastmcp import Client

    async with Client(MCP_URL) as client:
        result = await client.call_tool(tool_name, arguments)

    # fastmcp CallToolResult exposes .data as the parsed Python object when
    # the tool returns JSON, and .content as a list of raw content items.
    # Prefer .data (already parsed dict/list) over manual JSON decoding.
    if hasattr(result, "data") and result.data is not None:
        return result.data

    # Fallback: parse text from the first content item.
    content = getattr(result, "content", None) or []
    if content:
        item = content[0]
        text = getattr(item, "text", None)
        if text:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"raw": text}
    return {}


def _tools_to_openai_functions(mcp_tools: list) -> list[dict]:
    """
    Convert MCP tool objects to OpenAI function-calling format.
    Strips chart_type, custom_constraints, and use_default_constraints from
    viz spec tools so the agent cannot inject a chart type hint.
    """
    functions = []
    for tool in mcp_tools:
        schema = copy.deepcopy(tool.inputSchema or {"type": "object", "properties": {}})
        props = schema.get("properties", {})

        # Strip hint parameters from viz tools so routing is hint-free.
        if tool.name in VIZ_TOOL_NAMES:
            for param in _STRIP_PARAMS:
                props.pop(param, None)
            # Also remove from required list if present.
            req = schema.get("required", [])
            schema["required"] = [r for r in req if r not in _STRIP_PARAMS]

        functions.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": schema,
                },
            }
        )
    return functions


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


async def _run_agent(question: str) -> dict:
    """
    Run GPT-4o with MCP function tools against the live server.

    Returns a dict with:
        chart_url     : URL of the generated Vega-Lite spec (or None)
        spec          : parsed Vega-Lite JSON (or None)
        strategy      : routing strategy selected by the server
        reason        : routing reason string
        agent_trace   : list of {tool, args, result_summary} dicts
        error         : error string if agent failed
    """
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return {
            "chart_url": None,
            "spec": None,
            "strategy": None,
            "reason": None,
            "agent_trace": [],
            "error": "openai package not installed. Run: uv add openai --dev",
        }

    if not os.environ.get("OPENAI_API_KEY"):
        return {
            "chart_url": None,
            "spec": None,
            "strategy": None,
            "reason": None,
            "agent_trace": [],
            "error": "OPENAI_API_KEY not set",
        }

    openai_client = AsyncOpenAI()

    # Load tools from live server.
    mcp_tools = await _list_tools()
    openai_tools = _tools_to_openai_functions(mcp_tools)

    system_prompt = (
        "You are a World Bank data analyst assistant with access to Data360 MCP tools.\n\n"
        "STRICT WORKFLOW — follow this exact sequence, no deviations:\n\n"
        "STEP 1 — SEARCH (at most 2 times total):\n"
        "  Call data360_search_indicators once with the most relevant keyword.\n"
        "  Pick the FIRST indicator whose name and definition match the user's question.\n"
        "  If the first result is plausible, USE IT — do not search again.\n"
        "  Only search a second time if ZERO results were returned.\n"
        "  NEVER repeat the same query. NEVER search more than twice.\n\n"
        "STEP 2 — DISAGGREGATION (exactly once):\n"
        "  Call data360_get_disaggregation with the indicator_id and database_id you chose.\n"
        "  Use the returned available years and country list to determine the filter parameters.\n\n"
        "STEP 3 — VISUALIZATION (exactly once):\n"
        "  Call data360_get_viz_spec (single indicator) or data360_get_multi_indicator_viz_spec "
        "(multiple indicators).\n"
        "  Do NOT pass chart_type — let the system pick it.\n"
        "  Use the country codes and year range from Step 2.\n\n"
        "STEP 4 — REPORT:\n"
        "  Return the chart URL and a one-sentence description.\n\n"
        "RULES:\n"
        "- If data360_search_indicators returns results, ALWAYS proceed to Step 2 immediately.\n"
        "- Never call data360_search_indicators more than twice total.\n"
        "- Never skip Step 2 (disaggregation) before calling the viz tool.\n"
        "- If you have a chart URL from the viz tool, STOP — do not search further."
    )

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    agent_trace: list[dict] = []
    chart_url: str | None = None
    chart_strategy: str | None = None
    chart_reason: str | None = None
    spec_json: dict | None = None
    agent_error: str | None = None
    search_call_count: int = 0          # circuit breaker counter
    last_search_result: dict | None = None  # for injecting corrective message

    for turn in range(MAX_AGENT_TURNS):
        # ── Circuit breaker: inject corrective message after 2 consecutive searches ──
        if search_call_count >= 2:
            corrective = (
                "STOP SEARCHING. You have already called data360_search_indicators "
                f"{search_call_count} times. "
            )
            if last_search_result and isinstance(last_search_result, dict):
                indicators = last_search_result.get("indicators") or []
                if indicators:
                    top = indicators[0]
                    corrective += (
                        f"Use indicator_id='{top.get('idno')}' and "
                        f"database_id='{top.get('database_id')}' — the top result. "
                    )
            corrective += (
                "Proceed IMMEDIATELY to Step 2: call data360_get_disaggregation, "
                "then Step 3: call data360_get_viz_spec. Do not search again."
            )
            messages.append({"role": "user", "content": corrective})
            search_call_count = 0  # reset so the breaker doesn't fire again next turn

        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=openai_tools,
            tool_choice="auto",
            temperature=0,
        )

        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        # No more tool calls — agent is done.
        if not msg.tool_calls:
            break

        # Execute each tool call against the live MCP server.
        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            # Execute against live MCP server.
            try:
                result = await _call_mcp_tool(tool_name, args)
            except Exception as exc:
                result = {"error": str(exc)}

            # Track consecutive search calls for circuit breaker.
            if tool_name == "data360_search_indicators":
                search_call_count += 1
                last_search_result = result if isinstance(result, dict) else None
            else:
                search_call_count = 0  # reset on any non-search call

            # Capture trace entry.
            result_summary = _summarize_result(tool_name, result)
            agent_trace.append(
                {
                    "turn": turn + 1,
                    "tool": tool_name,
                    "args": args,
                    "result_summary": result_summary,
                }
            )

            # If this is a viz spec call, capture the chart URL + strategy.
            if tool_name in VIZ_TOOL_NAMES and isinstance(result, dict):
                url = result.get("url")
                if url and not result.get("error"):
                    chart_url = url
                    chart_strategy = result.get("strategy")
                    chart_reason = result.get("reason")
                    # Fetch the actual Vega-Lite JSON from the stored file.
                    spec_json = await _fetch_spec(url)

            # Feed tool result back into conversation.
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result) if isinstance(result, dict) else str(result),
                }
            )

        # Stop early once we have a chart.
        if chart_url:
            break


    if not chart_url:
        agent_error = (
            f"Agent did not produce a chart URL after {MAX_AGENT_TURNS} turns. "
            f"Trace: {json.dumps([t['tool'] for t in agent_trace])}"
        )

    return {
        "chart_url": chart_url,
        "spec": spec_json,
        "strategy": chart_strategy,
        "reason": chart_reason,
        "agent_trace": agent_trace,
        "error": agent_error,
    }


def _summarize_result(tool_name: str, result: Any) -> str:
    """Compact summary of a tool result for the trace log."""
    if not isinstance(result, dict):
        return str(result)[:200]
    if tool_name in VIZ_TOOL_NAMES:
        url = result.get("url")
        strategy = result.get("strategy")
        error = result.get("error")
        return f"url={url}, strategy={strategy}, error={error}"
    if "value" in result or "indicators" in result:
        n = len(result.get("value") or result.get("indicators") or [])
        return f"{n} results returned"
    if "error" in result:
        return f"error: {result['error']}"
    keys = list(result.keys())[:5]
    return f"keys: {keys}"


async def _fetch_spec(url: str) -> dict | None:
    """Fetch the Vega-Lite JSON from the static file URL."""
    # Convert to absolute URL if relative.
    if not url.startswith("http"):
        url = f"{STATIC_BASE}{url}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Scoring — 0-10 rubric via G-Eval (5 sub-criteria × 2 points each)
# ---------------------------------------------------------------------------


def _build_score_metric() -> GEval:
    return GEval(
        name="Agentic Chart Quality Score (0-10)",
        criteria="""
        You are a data visualization expert evaluating a Vega-Lite chart produced
        by an autonomous AI agent in response to a natural language question about
        development data. Score the chart out of 10 across the five criteria below,
        allocating up to 2 points each:

        1. DATA RELEVANCE (0-2)
           Does the chart show data that directly answers the question?
           Are the right countries, indicators, and time range represented?
           Deduct if the indicator appears mismatched to the user's intent,
           or if the data is suspiciously sparse (e.g., only 1 country when
           many were requested).

        2. CHART TYPE FIT (0-2)
           Is the auto-selected chart type appropriate for the data shape?
           Use the Financial Times Visual Vocabulary as the reference:
           - Multi-year single-indicator → line chart
           - Single-year multi-country → horizontal bar
           - Two indicators, single year, many countries → scatter
           - Two indicators, multi-year, one country → layered/faceted lines
           - High-cardinality country × year matrix → heatmap
           - User asked for map → choropleth
           Deduct if the chart type conflicts with the data shape.

        3. GRAMMAR OF GRAPHICS CORRECTNESS (0-2)
           Are the Vega-Lite encoding channels correctly typed?
           - Temporal data → type: temporal, timeUnit: year
           - Country names → type: nominal
           - Numeric values → type: quantitative
           Are tooltips structured dicts with field, type, title keys?
           Is color encoding used to distinguish series when appropriate?
           Is there no data aggregation artifact (e.g., values summed
           incorrectly across a country dimension)?

        4. READABILITY (0-2)
           Does the chart have a meaningful, descriptive title?
           Are axis labels present and readable?
           Is the data range appropriate (no extreme clipping or empty space)?
           Are WB-style axis properties present (gridColor, format)?
           For time-series: is the x-axis temporal scale correct?

        5. ROUTING CORRECTNESS (0-2)
           Did the agent call a sensible sequence of tools?
           The expected canonical path is:
             data360_search_indicators → data360_get_disaggregation → data360_get_viz_spec
           Deduct 0.5 if data360_get_disaggregation was skipped.
           Deduct 1.0 if indicator IDs were not validated through search before the viz call.
           Deduct 0.5 if more than 6 tool calls were needed for a simple question.

        Provide your final score as a number between 0 and 10.
        Also provide:
        - A concise critique paragraph explaining what worked and what did not.
        - A bulleted list of specific recommendations for improvement.
        """,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        evaluation_steps=[
            "Read the INPUT section which contains: the user question, the agent tool-call trace, "
            "the selected routing strategy, and the routing reason.",
            "Read the ACTUAL_OUTPUT section which contains the Vega-Lite JSON specification.",
            "Score DATA RELEVANCE (0-2): does the chart data match the question's intent?",
            "Score CHART TYPE FIT (0-2): is the auto-selected mark type correct for this data shape?",
            "Score GRAMMAR OF GRAPHICS (0-2): are encoding channels correctly typed, tooltips "
            "structured, and no aggregation artifacts?",
            "Score READABILITY (0-2): title, axis labels, scale range, WB style properties present?",
            "Score ROUTING CORRECTNESS (0-2): was the search → disaggregation → viz tool sequence "
            "followed, and did the agent use real indicator IDs from search results?",
            "Sum the five sub-scores to get the final score (0-10).",
            "Write a concise critique and bulleted recommendations.",
        ],
        threshold=5.0,  # Pass bar: 5/10 or above
    )


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def _save_report(scenario_id: str, question: str, agent_result: dict, score: float | None, critique: str | None) -> Path:
    """Write a JSON report to evals/reports/ and return its path."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"chart_quality_{scenario_id}_{ts}.json"

    report = {
        "scenario_id": scenario_id,
        "timestamp": ts,
        "question": question,
        "agent_trace": agent_result.get("agent_trace", []),
        "chart_url": agent_result.get("chart_url"),
        "strategy": agent_result.get("strategy"),
        "reason": agent_result.get("reason"),
        "agent_error": agent_result.get("error"),
        "score_out_of_10": score,
        "critique": critique,
    }

    report_path.write_text(json.dumps(report, indent=2, default=str))
    return report_path


# ---------------------------------------------------------------------------
# Core test runner
# ---------------------------------------------------------------------------


async def _run_e2e_scenario(scenario_id: str, question: str) -> None:
    """Execute a single E2E scenario end-to-end and assert on score."""
    # 1. Run the agent against the live MCP server.
    agent_result = await asyncio.wait_for(
        _run_agent(question),
        timeout=AGENT_TIMEOUT_S,
    )

    # 2. Build the input for the judge (question + agent trace + strategy).
    trace_summary = "\n".join(
        f"  Turn {t['turn']}: {t['tool']}({json.dumps(t['args'])[:120]}) "
        f"→ {t['result_summary']}"
        for t in agent_result.get("agent_trace", [])
    )
    judge_input = (
        f"USER QUESTION: {question}\n\n"
        f"AGENT TOOL TRACE:\n{trace_summary or '(no tools called)'}\n\n"
        f"ROUTING STRATEGY: {agent_result.get('strategy') or 'unknown'}\n"
        f"ROUTING REASON: {agent_result.get('reason') or 'N/A'}\n"
        f"CHART URL: {agent_result.get('chart_url') or 'None (chart not generated)'}\n"
        f"AGENT ERROR: {agent_result.get('error') or 'None'}"
    )

    # 3. Build actual_output: the Vega-Lite JSON spec (or a null sentinel).
    spec = agent_result.get("spec")
    if spec:
        actual_output = json.dumps(spec, indent=2)
    else:
        _err_msg = agent_result.get("error", "unknown")
        actual_output = (
            '{"error": "No chart was generated", '
            f'"agent_error": "{_err_msg}"'
            "}"
        )

    # 4. Score with G-Eval.
    metric = _build_score_metric()
    test_case = LLMTestCase(
        input=judge_input,
        actual_output=actual_output,
    )

    # Measure without asserting — we want the score and critique regardless.
    metric.measure(test_case)
    score = metric.score  # 0.0 – 1.0 (DeepEval normalises internally)
    critique = metric.reason

    # Convert to 0-10 for the report (DeepEval GEval scores are 0-1 internally
    # but the criteria text asks for 0-10; the judge writes scores summing to 10
    # and DeepEval normalises by dividing by 10).
    score_10 = round((score or 0.0) * 10, 1)

    # 5. Save the report.
    report_path = _save_report(scenario_id, question, agent_result, score_10, critique)
    print(f"\n[{scenario_id}] Score: {score_10}/10 | Report: {report_path}")
    print(f"[{scenario_id}] Critique: {(critique or '')[:300]}")

    # 6. Assert using DeepEval's standard mechanism.
    assert_test(test_case, [metric])


# ---------------------------------------------------------------------------
# Test scenarios
# ---------------------------------------------------------------------------


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_01_temporal_multi_country_gdp():
    """
    Scenario 1 — Multi-country temporal trend.
    Expected routing: search → disagg → get_viz_spec (no hint).
    Expected chart: multi-series line chart, x=year, color=country.
    """
    await _run_e2e_scenario(
        scenario_id="01_temporal_multi_country_gdp",
        question=(
            "Show me GDP growth trends for Brazil, Argentina, and Mexico "
            "from 2015 to 2023."
        ),
    )


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_02_cross_sectional_poverty():
    """
    Scenario 2 — Single-year cross-country ranking.
    Expected chart: horizontal bar chart, countries on y-axis.
    """
    await _run_e2e_scenario(
        scenario_id="02_cross_sectional_poverty",
        question=(
            "Which countries had the highest poverty headcount ratio "
            "in Sub-Saharan Africa in the most recent available year?"
        ),
    )


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_03_demographic_breakdown_labor():
    """
    Scenario 3 — Single indicator with demographic breakdown by sex.
    Expected routing: search → disagg (discovers SEX codes) → viz_spec.
    Expected chart: multi-series line, color=sex (Male/Female).
    """
    await _run_e2e_scenario(
        scenario_id="03_demographic_breakdown_labor",
        question=(
            "Compare female vs male labor force participation rate in Kenya "
            "over the last 10 years."
        ),
    )


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_04_dual_indicator_south_africa():
    """
    Scenario 4 — Two indicators, one country, multi-year.
    Expected routing: search ×2 → multi_indicator_viz_spec.
    Expected chart: faceted subplots or layered lines with independent y-axes.
    """
    await _run_e2e_scenario(
        scenario_id="04_dual_indicator_south_africa",
        question=(
            "Plot GDP growth alongside the inflation rate for South Africa "
            "from 2010 to 2023."
        ),
    )


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_05_life_expectancy_east_asia():
    """
    Scenario 5 — Regional group, temporal trend.
    Expected chart: multi-series line (countries in East Asia & Pacific region).
    """
    await _run_e2e_scenario(
        scenario_id="05_life_expectancy_east_asia",
        question=(
            "What is the life expectancy trend in East Asian countries "
            "over the past 20 years?"
        ),
    )


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_06_gini_world_map():
    """
    Scenario 6 — Global distribution, single year.
    Expected chart: choropleth map (agent requests a map-like view).
    No chart_type hint — routing must infer map from country cardinality + user intent.
    """
    await _run_e2e_scenario(
        scenario_id="06_gini_world_map",
        question=(
            "Show the Gini coefficient for as many countries as possible "
            "in the most recent available year. I want to see global inequality on a map."
        ),
    )


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_07_ambiguous_energy_germany():
    """
    Scenario 7 — Broad/ambiguous question. Agent must search and narrow down.
    Routing quality score is key: did the agent search before calling viz?
    """
    await _run_e2e_scenario(
        scenario_id="07_ambiguous_energy_germany",
        question=(
            "Show me energy-related data for Germany. "
            "Pick the most relevant indicator you can find."
        ),
    )


@skip_if_offline
@pytest.mark.asyncio
async def test_e2e_08_scatter_health_vs_income():
    """
    Scenario 8 — Correlation between two indicators across countries.
    Expected routing: search ×2 → multi_indicator_viz_spec.
    Expected chart: scatterplot (x=income, y=health metric, color=country/region).
    """
    await _run_e2e_scenario(
        scenario_id="08_scatter_health_vs_income",
        question=(
            "Is there a correlation between GDP per capita and life expectancy "
            "across countries in 2022? Show it visually."
        ),
    )
