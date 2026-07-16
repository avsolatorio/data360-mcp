"""
Interactive Chart Explorer & "Surprise Me" Dashboard
===================================================

Runs a local FastAPI server that lets you dynamically generate random visual
queries using an LLM, resolve indicators, compile Vega-Lite specs, run
DeepEval G-Eval quality scoring, and render the resulting charts in real-time.
It now compares the Data360 engine against a direct LLM generation side-by-side,
supporting unique persistence, batch runs of 20 sets, and recommendations to improve.

Run:
    uv run python evals/interactive_explorer.py

Then open:  http://localhost:8090
"""

from __future__ import annotations

import os
import sys
import json
import hashlib
import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import uvicorn
import httpx
import pandas as pd
from pydantic import BaseModel
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

# Load env variables from .env
load_dotenv(Path(__file__).parent.parent / ".env")

async def call_mcp_tool_on_8021(name: str, arguments: dict) -> dict:
    """Call an MCP tool on the local running server (port 8021) and parse SSE response."""
    port = int(os.environ.get("MCP_PORT", 8021))
    url = f"http://localhost:{port}/mcp"
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": name,
            "arguments": arguments
        },
        "id": 1
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            if response.status_code != 200:
                raise RuntimeError(f"MCP server returned status code {response.status_code}")
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if not data_str:
                        continue
                    try:
                        res_json = json.loads(data_str)
                        if "result" in res_json:
                            result_data = res_json["result"]
                            if result_data.get("isError"):
                                error_msg = ""
                                if result_data.get("content"):
                                    error_msg = result_data["content"][0].get("text", "")
                                raise RuntimeError(error_msg or "Tool call failed")

                            if result_data.get("content"):
                                text_content = result_data["content"][0].get("text", "")
                                try:
                                    parsed_viz = json.loads(text_content)
                                    return parsed_viz
                                except json.JSONDecodeError:
                                    return {"url": None, "error": text_content}
                            return {"url": None, "error": "No content in result"}
                        elif "error" in res_json:
                            raise RuntimeError(res_json["error"].get("message", "Unknown JSON-RPC error"))
                    except Exception as e:
                        if isinstance(e, RuntimeError):
                            raise e
                        continue
    raise RuntimeError("No response data received from MCP server")

# Add project root to python path so data360 package is importable
_HERE = Path(__file__).parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from data360.visualization import get_viz_spec, get_multi_indicator_viz_spec
from data360.api import search as api_search, _resolve_country_code
from evals.test_chart_rules_deepeval import resolve_indicator, _zero_shot_grammar_of_graphics_metric
from evals.prompts.chartjs_prompt import get_chartjs_system_prompt, get_chartjs_user_prompt

# Setup directories
REPORTS_DIR = _HERE / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

HF_TOKEN = os.environ.get("HF_TOKEN")
HF_DATASET_ID = os.environ.get("HF_DATASET_ID", "rafmacalaba/data360-explorer-reports")

def sync_reports_from_hf():
    if not (HF_TOKEN and HF_DATASET_ID):
        print("[HF Dataset Sync] HF_TOKEN or HF_DATASET_ID not set. Running locally.")
        return
    print(f"[HF Dataset Sync] Pulling files from dataset: {HF_DATASET_ID}...")
    try:
        import urllib.request
        import json

        # 1. Fetch file list from Hugging Face REST API using urllib
        api_url = f"https://huggingface.co/api/datasets/{HF_DATASET_ID}/tree/main"
        req = urllib.request.Request(api_url)
        if HF_TOKEN:
            req.add_header("Authorization", f"Bearer {HF_TOKEN}")

        with urllib.request.urlopen(req) as response:
            tree_data = json.loads(response.read().decode())

        files = [item["path"] for item in tree_data if item.get("type") == "file"]

        # 2. Download each file individually using urllib
        for f in files:
            if f.startswith(".") or f == "README.md":
                continue

            raw_url = f"https://huggingface.co/datasets/{HF_DATASET_ID}/raw/main/{f}"
            file_req = urllib.request.Request(raw_url)
            if HF_TOKEN:
                file_req.add_header("Authorization", f"Bearer {HF_TOKEN}")

            local_path = REPORTS_DIR / f
            print(f"[HF Dataset Sync] Downloading {f}...")
            with urllib.request.urlopen(file_req) as file_resp:
                with open(local_path, "wb") as out_file:
                    out_file.write(file_resp.read())

        print("[HF Dataset Sync] Pull completed successfully.")
    except Exception as e:
        print(f"[HF Dataset Sync] Error pulling from Hugging Face: {e}")

def upload_file_to_hf(file_path: Path):
    if not (HF_TOKEN and HF_DATASET_ID):
        return
    try:
        from huggingface_hub import HfApi
        api = HfApi(token=HF_TOKEN)
        # Create private dataset if it doesn't exist yet
        api.create_repo(repo_id=HF_DATASET_ID, repo_type="dataset", private=True, exist_ok=True)

        # Upload the file
        relative_path = file_path.name
        api.upload_file(
            path_or_fileobj=str(file_path),
            path_in_repo=relative_path,
            repo_id=HF_DATASET_ID,
            repo_type="dataset"
        )
        print(f"[HF Dataset Sync] Uploaded {relative_path} to HF dataset successfully.")
    except Exception as e:
        print(f"[HF Dataset Sync] Failed to upload {file_path.name} to Hugging Face: {e}")

# FastAPI app
app = FastAPI(title="Data360 MCP - Interactive Chart Explorer")

@app.on_event("startup")
async def startup_event():
    sync_reports_from_hf()

# Global batch status
batch_status = {
    "running": False,
    "current": 0,
    "total": 50,
    "errors": []
}
batch_cancel_requested = False

# ---------------------------------------------------------------------------
# WB Theme + prepareSpec pipeline (ported from packages/mcp-viz-core/src/)
# ---------------------------------------------------------------------------

WB_THEME: dict[str, Any] = {
    "background": "#ffffff",
    "view": {"stroke": None},
    "arc": {"fill": "#34A7F2"},
    "area": {"fill": "#34A7F2"},
    "line": {"stroke": "#34A7F2", "strokeCap": "round", "strokeJoin": "round"},
    "rect": {"fill": "#34A7F2"},
    "point": {"filled": True, "stroke": "white", "strokeWidth": 1},
    "title": {
        "font": "Open Sans, Arial, sans-serif",
        "subtitleFont": "Open Sans, Arial, sans-serif",
        "anchor": "start",
        "fontSize": 18,
        "fontWeight": 600,
        "offset": 20,
        "subtitleFontSize": 15,
        "subtitleColor": "#666666",
        "subtitlePadding": 6,
    },
    "axis": {
        "titleFont": "Open Sans, Arial, sans-serif",
        "titleFontSize": 13,
        "titleFontWeight": 600,
        "labelFont": "Open Sans, Arial, sans-serif",
        "labelColor": "#666666",
        "labelFontSize": 13,
        "gridWidth": 1,
        "tickColor": "#CED4DE",
        "tickWidth": 0.2,
        "titleColor": "#111111",
        "gridDash": [4, 2],
        "gridColor": "#CED4DE",
        "labelPadding": 6,
        "labelOverlap": True,
        "labelFlush": False,
    },
    "axisBand": {"grid": False},
    "axisX": {"grid": True, "tickSize": 0, "domain": False},
    "axisY": {"domain": False, "grid": True, "tickSize": 0},
    "legend": {
        "labelFont": "Open Sans, Arial, sans-serif",
        "titleFont": "Open Sans, Arial, sans-serif",
        "titleFontSize": 15,
        "labelFontSize": 13,
        "labelColor": "#111111",
        "padding": 1,
        "symbolSize": 140,
        "orient": "bottom",
        "direction": "horizontal",
    },
    "range": {
        "category": ["#34A7F2", "#FF9800", "#664AB6", "#4EC2C0", "#F3578E", "#081079", "#0C7C68"],
    },
}

WB_PALETTE = WB_THEME["range"]["category"]


def _wb_get_mark(spec: dict) -> str:
    """Extract the mark type string from a flat or compound Vega-Lite spec."""
    mark = spec.get("mark")
    if not mark:
        return "line"
    if isinstance(mark, str):
        return mark
    return mark.get("type", "line")


def prepare_spec(spec: dict, chart_height: int = 340) -> dict:
    """
    Python port of prepareSpec from packages/mcp-viz-core/src/prepare-spec.ts.
    Applies the 8-guard pipeline to make any Data360 Vega-Lite spec compatible
    with the WB visual theme and the dashboard renderer.

    Guards:
      1. Inline named dataset -> data.values
      2. Responsive sizing (width: container, configurable height)
      3. Suppress built-in Vega legend (unless quantitative color)
      3b. Strip top-level title (shown in card header above the chart)
      4. Strip zoom/pan params (conflicts with card controls)
      5. Normalize $schema to vega-lite/v5
      6. Merge WB_THEME into spec.config (spec values win on conflict)
      7. scale.zero = False for line/area/point/tick; True for bar
      8. x-axis format: %Y for temporal; null title for nominal/ordinal
    """
    import copy
    out = copy.deepcopy(spec)
    mark_type = _wb_get_mark(out)

    # 1. Inline named dataset
    name = out.get("data", {}).get("name")
    if name and out.get("datasets", {}).get(name):
        out["data"] = {"values": out["datasets"][name]}
        out.pop("datasets", None)

    # 2. Responsive sizing
    out["width"] = "container"
    out["height"] = chart_height

    # 3. Suppress built-in legend unless quantitative
    encoding = out.get("encoding", {})
    color_enc = encoding.get("color", {})
    if color_enc and color_enc.get("type") != "quantitative":
        color_enc["legend"] = None

    # NOTE: guard 3b (strip title) is intentionally omitted here.
    # In the React app, VegaChartCard shows the title in the card header and strips it from the spec.
    # In this standalone dashboard there is no card header — the title must remain so vegaEmbed renders it.

    # 4. Strip zoom/pan params
    out.pop("params", None)

    # 5. Normalize schema to v5
    out["$schema"] = "https://vega.github.io/schema/vega-lite/v5.json"

    # 6. Merge WB theme: WB base, spec config wins on conflict
    import copy as _copy
    base_theme = _copy.deepcopy(WB_THEME)
    existing_config = out.get("config", {})
    out["config"] = {**base_theme, **existing_config}

    # 7. scale.zero
    y_enc = encoding.get("y", {})
    if y_enc:
        if "scale" not in y_enc:
            y_enc["scale"] = {}
        y_enc["scale"]["zero"] = (mark_type == "bar")

    # 8. x-axis format
    x_enc = encoding.get("x", {})
    if x_enc:
        if "axis" not in x_enc:
            x_enc["axis"] = {}
        x_type = x_enc.get("type", "")
        if x_type == "temporal":
            x_enc["axis"]["format"] = "%Y"
            x_enc["axis"]["title"] = None
        else:
            x_enc["axis"].pop("format", None)
            x_enc["axis"]["title"] = None

    return out


def _chartjs_quality_metric():
    """
    Dedicated G-Eval metric to evaluate Chart.js v4 configurations.
    Focuses on visualization layout, chart suitability, theme styling, and correctness.
    """
    from evals.test_chart_rules_deepeval import GEval, SingleTurnParams
    return GEval(
        name="Chart.js v4 Charting Suitability & Design Quality Metric",
        criteria="""
        Evaluate the visual charting quality and layout correctness of the generated Chart.js v4 JSON config. Focus entirely on the visualization's design, hierarchy, and representation suitability.

        Scoring Criteria:
        1. ENCODING & CHART TYPE SUITABILITY (0-4): Does the selected Chart.js type ('line', 'bar', 'scatter', etc.) represent the query intent effectively? (e.g. line charts for trends, bar charts for single-year comparisons, scatter plots for correlation).
        2. STYLING, THEMES & READABILITY (0-4): Does the chart follow professional design guidelines? (e.g. uses colors from the World Bank palette, displays clear scale titles for axes, legend placed at the bottom, and a descriptive title is defined in options).
        3. DESIGN ROBUSTNESS (0-2): Is the configuration format standard (type, data, options keys), responsive, and optimized for interactive rendering inside a canvas?

        Give a final score from 0.0 to 1.0 (where >= 0.75 passes).
        Provide:
        - A concise critique and rationale focusing on charting quality.
        - A dedicated section "RECOMMENDATIONS" listing concrete visual styling and charting suggestions.
        """,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        evaluation_steps=[
            "Inspect the INPUT (the requested query context and parameters).",
            "Inspect the ACTUAL_OUTPUT (the generated Chart.js JSON config).",
            "Verify the chart type fits the intent of the comparison (line vs bar vs scatter).",
            "Evaluate dataset structures (labels, datasets, data points) for clean charting representation.",
            "Assess thematic styling correctness (World Bank colors, axis titles, and options configuration).",
            "Check responsiveness and options settings.",
            "Generate the final score, written critique, and recommendations."
        ],
        threshold=0.75,
    )


def compile_deepeval_input(resolved_indicators: list, scenario: dict, rows: list) -> str:
    """Compile a clean summary of indicator min/max/count from actual values for the DeepEval judge."""
    data_summary = ""
    if rows:
        try:
            df_temp = pd.DataFrame(rows)
            # Find actual countries in the retrieved dataset
            actual_countries = sorted(list(set(df_temp["country"].dropna().tolist()))) if "country" in df_temp.columns else []
            actual_country_codes = sorted(list(set(df_temp["country_code"].dropna().tolist()))) if "country_code" in df_temp.columns else []
            if not actual_country_codes and "ref_area" in df_temp.columns:
                actual_country_codes = sorted(list(set(df_temp["ref_area"].dropna().tolist())))

            actual_years = sorted(list(set(df_temp["year"].dropna().tolist()))) if "year" in df_temp.columns else []
            if not actual_years and "time_period" in df_temp.columns:
                actual_years = sorted(list(set(df_temp["time_period"].dropna().tolist())))

            summary_parts = []
            if actual_countries:
                summary_parts.append(f"Actual Countries in Retrieved Data: {', '.join(actual_countries)} ({', '.join(actual_country_codes)})")
            if actual_years:
                summary_parts.append(f"Actual Years in Retrieved Data: {min(actual_years)} to {max(actual_years)}")

            for col in df_temp.columns:
                if col not in ("year", "time_period", "country", "country_code", "ref_area", "indicator_id", "indicator_name"):
                    try:
                        non_null = df_temp[col].dropna()
                        if not non_null.empty:
                            min_val = non_null.min()
                            max_val = non_null.max()
                            summary_parts.append(f"Indicator '{col}': min={min_val}, max={max_val}, count={len(non_null)}")
                    except Exception:
                        pass
            data_summary = "\n        ".join(summary_parts)
        except Exception:
            pass

    eval_input = f"""
    Requested Indicators:
    {json.dumps(resolved_indicators, indent=2)}

    Parameters:
    - Countries: {scenario.get('country_code')}
    - Start Year: {scenario.get('start_year')}
    - End Year: {scenario.get('end_year')}
    - Chart Type Hint: {scenario.get('chart_type')}
    - Disaggregation Filters: {scenario.get('disaggregation_filters')}

    User Context Question: {scenario.get('user_question', 'Plot custom indicators.')}

    Dataset Summary from Retrieved Data:
    {data_summary or "No data summary available."}

    CRITICAL EVALUATION RULE FOR MISSING DATA:
    If a country, year, or series requested by the user is completely missing from the 'Dataset Summary from Retrieved Data' (e.g. there are no rows/values retrieved for Argentina or a specific year), this means the data is NOT available in the database.
    Do NOT penalize the visualization engine or give a lower score for not plotting missing data. The engine can only visualize data that was actually retrieved from the database. Only evaluate the correctness of the layout, styling, and representation of the data that WAS actually retrieved.
    """
    return eval_input.strip()


# ---------------------------------------------------------------------------
# Core Generation Helper
# ---------------------------------------------------------------------------

async def run_surprise_generation(log_callback=None) -> dict:
    """
    Core surprise generation routine. Generates a visual query scenario,
    obtains data, runs Data360 viz compiler, calls direct LLM Vega-Lite generator,
    evaluates both via DeepEval G-Eval, and saves report with a unique scenario ID.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY not set in environment.", "status_code": 500}

    logs = []
    def log(msg: str):
        logs.append(msg)
        print(f"[Dashboard Log] {msg}")
        if log_callback:
            log_callback(msg)

    log("Initiating Surprise-Me request...")

    # Find recently generated questions to avoid repetition
    past_questions = []
    for p in REPORTS_DIR.glob("surprise_*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("question"):
                past_questions.append(data.get("question"))
        except Exception:
            pass
    # Keep them unique and cap at last 15
    past_questions = list(set(past_questions))[-15:]
    past_questions_str = "\n".join(f"- {q}" for q in past_questions)

    # 1. Select interesting database indicators first to inspect their breakdown
    CURATED_POOL = [
        # WDI (Simple indicators without breakdown dimensions in this DB)
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD", "name": "GDP per capita (constant 2015 USD)"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_ELC_ACCS_ZS", "name": "Access to electricity (% of population)"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_IT_NET_USER_ZS", "name": "Individuals using the Internet (% of population)"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SE_ADT_LITR_ZS", "name": "Literacy rate, adult total (% of people ages 15 and above)"},
        {"database_id": "WB_ESG", "indicator_id": "WB_ESG_EN_ATM_CO2E_PC", "name": "CO2 emissions (metric tons per capita)"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_POP_TOTL", "name": "Population, total"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_UEM_TOTL_ZS", "name": "Unemployment, total (% of total labor force)"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_DYN_LE00_IN", "name": "Life expectancy at birth, total (years)"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_FP_CPI_TOTL_ZG", "name": "Inflation, consumer prices (annual %)"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_AG_LND_FRST_ZS", "name": "Forest area (% of land area)"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_IT_CEL_SETS_P2", "name": "Mobile cellular subscriptions (per 100 people)"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NE_EXP_GNFS_ZS", "name": "Exports of goods and services (% of GDP)"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SI_POV_GINI", "name": "Gini index"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SH_TBS_INCD", "name": "Incidence of tuberculosis (per 100,000 people)"},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SE_PRM_CMPT_ZS", "name": "Primary completion rate, total (% of relevant age group)"},

        # ESG (Environmental, Social and Governance)
        {"database_id": "WB_ESG", "indicator_id": "WB_ESG_EG_FEC_RNEW_ZS", "name": "Renewable energy consumption (% of total final energy consumption)"},
        {"database_id": "WB_ESG", "indicator_id": "WB_ESG_SH_STA_BIRT", "name": "Births attended by skilled health staff (% of total)"},
        {"database_id": "WB_ESG", "indicator_id": "WB_ESG_GB_XPD_RSDV_GD_ZS", "name": "Research and development expenditure (% of GDP)"},

        # WGI (Worldwide Governance Indicators)
        {"database_id": "WB_WGI", "indicator_id": "GOV_WGI_VA", "name": "Voice and Accountability: Estimate"},
        {"database_id": "WB_WGI", "indicator_id": "GOV_WGI_GE", "name": "Government Effectiveness: Estimate"},
        {"database_id": "WB_WGI", "indicator_id": "GOV_WGI_CC", "name": "Control of Corruption: Estimate"},
        {"database_id": "WB_WGI", "indicator_id": "GOV_WGI_RL", "name": "Rule of Law: Estimate"},
        {"database_id": "WB_WGI", "indicator_id": "GOV_WGI_RQ", "name": "Regulatory Quality: Estimate"},
        {"database_id": "WB_WGI", "indicator_id": "GOV_WGI_PV", "name": "Political Stability and Absence of Violence/Terrorism: Estimate"},

        # Enterprise Surveys
        {"database_id": "WB_ES", "indicator_id": "WB_ES_T_JOBS1", "name": "Jobs share"},
        {"database_id": "WB_ES", "indicator_id": "WB_ES_T_PERF2", "name": "Annual employment growth (%)"},
        {"database_id": "WB_ES", "indicator_id": "WB_ES_T_EXPT1", "name": "Percent of firms that export"},
    ]

    import random
    from data360.api import get_disaggregation, get_metadata

    last_error_msg = "Unknown error"
    last_status_code = 500

    for attempt in range(4):
        log(f"Surprise-Me generation attempt {attempt + 1} of 4...")

        # 1. Decide number of indicators (single, 2, or 3)
        indicator_choice = random.random()
        if indicator_choice < 0.60:
            n_indicators = 1
        elif indicator_choice < 0.85:
            n_indicators = 2
        else:
            n_indicators = 3

        selected = []
        if n_indicators > 1:
            # Pick simple WDI indicators for multi-indicator comparison
            wdi_candidates = [ind for ind in CURATED_POOL if ind["database_id"] == "WB_WDI"]
            selected = random.sample(wdi_candidates, min(len(wdi_candidates), n_indicators))
        else:
            # Pick one from the whole pool
            selected = [random.choice(CURATED_POOL)]

        # Fetch metadata & disaggregation details for selected indicators
        indicators_info = []
        resolved_indicators = []

        for s in selected:
            db_id = s["database_id"]
            ind_id = s["indicator_id"]

            # Get disaggregation
            try:
                disagg = await get_disaggregation(db_id, ind_id)
                dims = disagg.get("dimensions", [])
            except Exception:
                dims = []

            # Clean dimensions to show only meaningful breakdown dimensions
            cleaned_dims = []
            for d in dims:
                f_name = d["field_name"]
                if f_name not in ["REF_AREA", "TIME_PERIOD", "REGION", "UNIT_MEASURE"]:
                    val_list = d.get("field_value") or d.get("sample") or []
                    clean_vals = [v for v in val_list if v not in ["_T", "_Z"]]
                    if clean_vals:
                        cleaned_dims.append({
                            "field_name": f_name,
                            "label_name": d.get("label_name", f_name),
                            "values": clean_vals
                        })

            # Fetch actual name from metadata if possible, fallback to default
            ind_name = s["name"]
            try:
                meta = await get_metadata(db_id, ind_id, select_fields=["name"])
                if meta and meta.get("name"):
                    ind_name = meta["name"]
            except Exception:
                pass

            indicators_info.append({
                "database_id": db_id,
                "indicator_id": ind_id,
                "name": ind_name,
                "breakdown_dimensions": cleaned_dims
            })

            resolved_indicators.append({
                "database_id": db_id,
                "indicator_id": ind_id,
                "name": ind_name
            })

        is_multi = len(resolved_indicators) >= 2

        # 2. Randomly select visual parameters on Python side to bypass LLM bias/hardcoding
        # A. Years: Single-year vs. Multi-year
        is_single_year = random.random() < 0.4  # 40% chance of single year
        if is_single_year:
            year = random.randint(2015, 2022)
            start_year = year
            end_year = year
        else:
            start_year = random.randint(2010, 2017)
            end_year = random.randint(2018, 2022)

        # B. Countries: Single vs. Multi-few (2-4) vs. Multi-many (8-15)
        country_pool = ["USA", "CHN", "JPN", "DEU", "FRA", "GBR", "IND", "BRA", "ITA", "CAN", "KEN", "UGA", "RWA", "ZAF", "ESP", "MEX", "COL", "BGD"]
        country_choice = random.random()
        if is_multi:
            # Multi-indicator is typically compared for a single country or a few countries
            if country_choice < 0.5:
                country_code = random.choice(country_pool)
            else:
                selected_countries = random.sample(country_pool, random.randint(2, 4))
                country_code = ";".join(selected_countries)
        else:
            # Single indicator
            if country_choice < 0.2:
                country_code = random.choice(country_pool)
            elif country_choice < 0.7:
                selected_countries = random.sample(country_pool, random.randint(2, 5))
                country_code = ";".join(selected_countries)
            else:
                # Many countries to trigger distribution / heatmaps
                selected_countries = random.sample(country_pool, random.randint(8, 15))
                country_code = ";".join(selected_countries)

        # C. Disaggregations / Breakdowns
        disaggregation_filters = {}
        available_dims = indicators_info[0]["breakdown_dimensions"]
        if available_dims:
            breakdown_choice = random.random()
            if breakdown_choice < 0.4:
                # Compare all values for a random dimension
                dim = random.choice(available_dims)
                disaggregation_filters[dim["field_name"]] = None
            elif breakdown_choice < 0.8:
                # Pin to one specific value
                dim = random.choice(available_dims)
                val = random.choice(dim["values"])
                disaggregation_filters[dim["field_name"]] = val
            else:
                pass

        # 3. Ask OpenAI to generate a realistic natural language question matching these exact parameters
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)

            prompt = f"""
            You are an expert World Bank Data360 query builder.
            Generate ONE realistic natural language question (user query) that matches the following pre-selected indicators and parameter configuration.

            Selected Indicator(s):
            {json.dumps(indicators_info, indent=2)}

            Configured Parameters:
            - Countries: {country_code}
            - Year Range: {start_year} to {end_year}
            - Disaggregation/Breakdown Filters: {json.dumps(disaggregation_filters, indent=2)}

            Instructions for framing the query:
            1. The query MUST exactly match the parameters. For example, if the country list is "KEN;UGA", make sure the query mentions Kenya and Uganda. If it is a single year, make sure it specifies that year (e.g. "in 2020").
            2. If a disaggregation filter maps to null (e.g., "COMP_BREAKDOWN_1": null), it means we want to compare all values of that dimension. Frame the question as a comparison of those values (e.g. "compare estimate and standard error of Control of Corruption...").
            3. If a disaggregation filter maps to a specific value (e.g. "COMP_BREAKDOWN_1": "WGI_EST"), make sure the question specifies that value (e.g. "Voice and Accountability estimate...").
            4. If no disaggregation filters are specified, do not ask for breakdowns.
            5. Ensure the final query is phrased naturally, like a human user would ask. Do NOT mention visual types (like line chart or bar chart) in the question.

            Avoid outputting the same queries repeatedly. Be creative and cover diverse global topics.
            Output ONLY a JSON object containing:
            "user_question": "Your framed question"
            No markdown wrapping.
            """

            # Add unique seed to force variety
            prompt += f"\n\nSeed: {time.time()}"
            if past_questions:
                prompt += f"\n\nYou MUST NOT generate questions that duplicate the semantic intent of any of these recent questions:\n{past_questions_str}"

            log("Contacting LLM to frame natural language query matching parameters...")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are a visual query scenario builder."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
            )
            llm_res = json.loads(response.choices[0].message.content)
            user_question = llm_res.get("user_question", "Visual query")

            # Construct scenario
            scenario = {
                "user_question": user_question,
                "country_code": country_code,
                "start_year": start_year,
                "end_year": end_year,
                "chart_type": None,
                "disaggregation_filters": disaggregation_filters
            }

            log(f"LLM framed query: '{user_question}'")
        except Exception as exc:
            last_error_msg = f"LLM generation failed: {exc}"
            last_status_code = 500
            log(f"[Attempt {attempt + 1} Error] {last_error_msg}. Retrying...")
            continue

        # 3. Call the visualization engine via local MCP server
        try:
            log("Executing Data360 visualization engine via MCP server on 8021...")
            if is_multi:
                viz_result = await call_mcp_tool_on_8021(
                    "data360_get_multi_indicator_viz_spec",
                    {
                        "indicator_ids": [
                            {"database_id": ri["database_id"], "indicator_id": ri["indicator_id"]}
                            for ri in resolved_indicators
                        ],
                        "country_code": scenario.get("country_code"),
                        "start_year": scenario.get("start_year"),
                        "end_year": scenario.get("end_year"),
                        "chart_type": scenario.get("chart_type"),
                        "disaggregation_filters": scenario.get("disaggregation_filters"),
                    }
                )
            else:
                ri = resolved_indicators[0]
                viz_result = await call_mcp_tool_on_8021(
                    "data360_get_viz_spec",
                    {
                        "database_id": ri["database_id"],
                        "indicator_id": ri["indicator_id"],
                        "country_code": scenario.get("country_code"),
                        "start_year": scenario.get("start_year"),
                        "end_year": scenario.get("end_year"),
                        "chart_type": scenario.get("chart_type"),
                        "disaggregation_filters": scenario.get("disaggregation_filters"),
                    }
                )

            if viz_result.get("error"):
                last_error_msg = viz_result["error"]
                last_status_code = 400
                log(f"[Attempt {attempt + 1} Error] Visual engine returned: {last_error_msg}. Retrying...")
                continue

            spec = viz_result.get("spec", {})
            log(f"Chart spec generated successfully via MCP (strategy: {viz_result.get('strategy')})")
            # Success! Break out of the retry loop
            break
        except Exception as exc:
            last_error_msg = f"Visualization spec building failed: {exc}"
            last_status_code = 500
            log(f"[Attempt {attempt + 1} Error] {last_error_msg}. Retrying...")
            continue
    else:
        # If we exhausted all attempts, return the final failure error
        log(f"All 4 generation attempts failed. Last error: {last_error_msg}")
        return {"error": last_error_msg, "status_code": last_status_code}

    # Extract raw data rows from the compiled spec
    name = spec.get("data", {}).get("name")
    if name and spec.get("datasets", {}).get(name):
        rows = spec["datasets"][name]
    else:
        rows = spec.get("data", {}).get("values", [])

    # 4a. Apply prepareSpec + WB Theme to the system spec
    system_spec = prepare_spec(spec)
    log("prepareSpec + WB Theme applied to system spec.")

    # 4b. Generate direct LLM Chart.js v4 config from raw data rows and user question
    llm_chartjs = {}
    llm_score_10 = 0.0
    llm_critique = "No direct LLM chart generated."

    if rows:
        try:
            log("Contacting LLM to generate Chart.js v4 config for comparison...")
            sample_data = rows
            column_names = list(sample_data[0].keys()) if sample_data else []

            llm_chartjs_prompt = get_chartjs_user_prompt(
                question=scenario['user_question'],
                column_names=column_names,
                sample_data=sample_data
            )

            llm_response = client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": get_chartjs_system_prompt()},
                    {"role": "user", "content": llm_chartjs_prompt}
                ],
                temperature=0.2,
            )
            llm_chartjs = json.loads(llm_response.choices[0].message.content)
            log("Direct LLM Chart.js config generated.")
        except Exception as exc:
            log(f"Direct LLM Chart.js generation failed: {exc}")

    # 5. Run DeepEval G-Eval quality scoring on BOTH
    try:
        from evals.test_chart_rules_deepeval import LLMTestCase
        log("Running DeepEval G-Eval visual quality score on System Spec...")
        metric = _zero_shot_grammar_of_graphics_metric()

        eval_input = compile_deepeval_input(resolved_indicators, scenario, rows)

        test_case = LLMTestCase(
            input=eval_input.strip(),
            actual_output=json.dumps(spec, indent=2)
        )
        metric.measure(test_case)
        score_10 = round((metric.score or 0.0) * 10, 1)
        critique = metric.reason or "No critique provided."
        log(f"DeepEval score: {score_10}/10")

        if llm_chartjs:
            log("Running DeepEval G-Eval visual quality score on LLM Chart.js config...")
            llm_metric = _chartjs_quality_metric()
            llm_test_case = LLMTestCase(
                input=eval_input.strip(),
                actual_output=json.dumps(llm_chartjs, indent=2)
            )
            llm_metric.measure(llm_test_case)
            llm_score_10 = round((llm_metric.score or 0.0) * 10, 1)
            llm_critique = llm_metric.reason or "No critique provided."
            log(f"Direct LLM Chart.js score: {llm_score_10}/10")

    except Exception as exc:
        log(f"DeepEval score failed: {exc}. Defaulting to score 0.0.")
        score_10 = 0.0
        critique = f"DeepEval scoring failed: {exc}"

    # 6. Save report to JSON file with unique scenario ID (timestamp)
    timestamp_sec = int(time.time())
    scenario_id = f"surprise_{hashlib.md5(scenario['user_question'].encode()).hexdigest()[:8]}_{timestamp_sec}"
    report_file = REPORTS_DIR / f"{scenario_id}.json"

    report_data = {
        "scenario_id": scenario_id,
        "question": scenario["user_question"],
        "scenario": scenario,
        "resolved_indicators": resolved_indicators,
        "viz_result": viz_result,
        "system_spec": system_spec,
        "system_score": score_10,
        "system_critique": critique,
        "llm_chartjs": llm_chartjs,
        "llm_score": llm_score_10,
        "llm_critique": llm_critique,
        # For backwards compatibility:
        "spec": system_spec,
        "score": score_10,
        "critique": critique,
        "timestamp": pd.Timestamp.now().isoformat(),
        "logs": logs
    }

    with open(report_file, "w") as f:
        json.dump(report_data, f, indent=2)
    upload_file_to_hf(report_file)

    log("Report saved successfully. Returning to client.")
    return report_data

# ---------------------------------------------------------------------------
# Background Batch Runner
# ---------------------------------------------------------------------------

async def run_batch_surprise():
    global batch_status, batch_cancel_requested
    batch_cancel_requested = False
    batch_status["running"] = True
    batch_status["current"] = 0
    batch_status["errors"] = []

    for i in range(50):
        if batch_cancel_requested:
            print("[Batch Run] Cancellation requested. Stopping batch loop.")
            batch_status["errors"].append("Cancelled by user request.")
            break
        try:
            print(f"[Batch Run] Starting set {i+1} of 50...")
            await run_surprise_generation()
            batch_status["current"] += 1
            # Add a small delay to avoid hitting rate limits
            await asyncio.sleep(1)
        except Exception as e:
            batch_status["errors"].append(str(e))
            print(f"[Batch Error] Set {i+1} failed: {e}")

    batch_status["running"] = False

# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/api/history")
def get_history():
    """List past generated surprise and custom charts."""
    reports = []
    for prefix in ("surprise_", "custom_"):
        for p in REPORTS_DIR.glob(f"{prefix}*.json"):
            try:
                data = json.loads(p.read_text())
                reports.append({
                    "filename": p.name,
                    "scenario_id": data.get("scenario_id"),
                    "question": data.get("question"),
                    "score": data.get("system_score", data.get("score", 0.0)),
                    "llm_score": data.get("llm_score", 0.0),
                    "timestamp": data.get("timestamp"),
                })
            except Exception:
                pass
    # Sort by timestamp descending
    reports.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return reports


@app.get("/api/reports/{filename}")
def get_report(filename: str):
    path = REPORTS_DIR / filename
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "Report not found"})
    return json.loads(path.read_text())


@app.post("/api/surprise-me")
async def surprise_me():
    """Trigger a single Surprise-Me run."""
    res = await run_surprise_generation()
    if "error" in res and res.get("status_code"):
        return JSONResponse(status_code=res["status_code"], content={"error": res["error"]})
    return res


async def parse_query_with_llm(question: str, indicators_info: list, api_key: str) -> dict:
    """Use GPT-4o-mini to parse a natural language question into scenario parameters."""
    if not api_key:
        return {}

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    prompt = f"""
    You are an expert World Bank Data360 query parser.
    Your task is to parse the natural language query: "{question}"
    into structured parameters matching the provided indicators:
    {json.dumps(indicators_info, indent=2)}

    You MUST output a JSON object with:
    1. `country_code`: A semi-colon separated string of ISO 3-letter codes for the countries mentioned in the query (e.g. "ARG;CHL" for Argentina and Chile).
    2. `start_year`: Start year (integer) mentioned in the query (e.g. 2015).
    3. `end_year`: End year (integer) mentioned in the query (e.g. 2021).
    4. `chart_type`: Visual hint. If the query explicitly asks for a "bar", "line", "map", etc., specify it. Otherwise, set to null.
    5. `disaggregation_filters`: A JSON object mapping breakdown dimension keys to null or specific values if requested in the query.

    Output ONLY the JSON object. No markdown wrapping.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a query parser."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"[Query Parser Error] {e}")
        return {}
@app.post("/api/reports/{scenario_id}/delete")
async def delete_report(scenario_id: str):
    """
    Delete a past report and all related artifacts (JSON, G-Eval critique, screenshots)
    both locally and from the Hugging Face dataset if configured.
    """
    # 1. Strip any directory traversal chars
    safe_id = "".join([c for c in scenario_id if c.isalnum() or c in ("-", "_")])
    if not safe_id:
        return JSONResponse(status_code=400, content={"error": "Invalid scenario ID"})

    # 2. Define filenames to delete
    artifacts = [
        f"{safe_id}.json",
        f"visual_critique_{safe_id}.json",
        f"render_{safe_id}_system.png",
        f"render_{safe_id}_llm.png",
    ]

    deleted_local = []
    errors = []

    # 3. Delete files locally
    for art in artifacts:
        local_path = REPORTS_DIR / art
        if local_path.exists():
            try:
                local_path.unlink()
                deleted_local.append(art)
                print(f"[Delete] Deleted local file: {local_path}")
            except Exception as e:
                errors.append(f"Failed to delete local file {art}: {e}")

    # 4. If HF dataset sync is enabled, delete from dataset repository
    if deleted_local and HF_TOKEN and HF_DATASET_ID:
        try:
            from huggingface_hub import HfApi
            api = HfApi(token=HF_TOKEN)
            for art in deleted_local:
                try:
                    # Hugging Face Hub delete_file operation
                    api.delete_file(
                        path_in_repo=art,
                        repo_id=HF_DATASET_ID,
                        repo_type="dataset"
                    )
                    print(f"[Delete] Deleted file from HF dataset: {art}")
                except Exception as hf_e:
                    # If file doesn't exist in HF yet (404), it is not a blocking error
                    print(f"[Delete] HF delete warning for {art}: {hf_e}")
        except Exception as api_e:
            errors.append(f"Hugging Face API deletion failed: {api_e}")

    if errors:
        return JSONResponse(
            status_code=207,
            content={
                "status": "partial",
                "deleted": deleted_local,
                "errors": errors,
            }
        )

    return {"status": "success", "deleted": deleted_local}


@app.post("/api/reports/{filename}/rerun")
async def rerun_report(filename: str):
    """
    Rerun a past report: compile with the latest Data360 visual routing
    rules and re-score both the engine and direct LLM outputs.
    """
    path = REPORTS_DIR / filename
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "Report not found"})

    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": f"Failed to parse report: {exc}"})

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return JSONResponse(status_code=500, content={"error": "OPENAI_API_KEY not set in environment."})

    logs = []
    def log(msg: str):
        logs.append(msg)
        print(f"[Rerun Log] {msg}")

    log(f"Rerunning past report scenario: '{data.get('question')}'...")

    question = data["question"]
    resolved_indicators = data["resolved_indicators"]
    scenario = data.get("scenario", {})

    # Extract params with fallbacks for older formats
    country_code = scenario.get("country_code")
    start_year = scenario.get("start_year")
    end_year = scenario.get("end_year")
    chart_type = scenario.get("chart_type")
    disaggregation_filters = scenario.get("disaggregation_filters")

    # If the loaded country_code is missing or has a suspicious list of all/many countries,
    # use the LLM to parse the question into correct parameters.
    num_countries = len(country_code.replace(",", ";").split(";")) if country_code else 0
    if not country_code or num_countries > 10:
        log(f"Detected missing or suspicious country count ({num_countries}). Attempting to parse query with LLM...")
        parsed_params = await parse_query_with_llm(question, resolved_indicators, api_key)
        if parsed_params:
            country_code = parsed_params.get("country_code")
            start_year = parsed_params.get("start_year") or start_year
            end_year = parsed_params.get("end_year") or end_year
            chart_type = parsed_params.get("chart_type") or chart_type
            disaggregation_filters = parsed_params.get("disaggregation_filters") or disaggregation_filters
            log(f"LLM parsed parameters: country_code={country_code}, start_year={start_year}, end_year={end_year}, chart_type={chart_type}")

    # Post-process chart_type to match user query keyword constraints:
    if chart_type:
        q = question.lower()
        hint_lower = chart_type.lower()
        has_keyword = False
        if "bar" in hint_lower or "column" in hint_lower:
            has_keyword = "bar" in q or "column" in q or "grouped" in q or "stacked" in q
        elif "line" in hint_lower or "trend" in hint_lower:
            has_keyword = "line" in q or "trend" in q or "over time" in q
        elif "map" in hint_lower or "choropleth" in hint_lower:
            has_keyword = "map" in q or "choropleth" in q
        elif "scatter" in hint_lower:
            has_keyword = "scatter" in q or "correlation" in q or "versus" in q or "vs" in q
        elif "heatmap" in hint_lower:
            has_keyword = "heatmap" in q or "grid" in q

        if not has_keyword:
            log(f"Stripping unrequested chart hint '{chart_type}' from rerun scenario")
            chart_type = None

    # Delete old screenshots and critique if they exist
    scenario_id = data.get("scenario_id")
    if scenario_id:
        sys_img_path = REPORTS_DIR / f"render_{scenario_id}_system.png"
        llm_img_path = REPORTS_DIR / f"render_{scenario_id}_llm.png"
        critique_file = REPORTS_DIR / f"visual_critique_{scenario_id}.json"
        for p in (sys_img_path, llm_img_path, critique_file):
            if p.exists():
                try:
                    p.unlink()
                    log(f"Cleaned up stale file: {p.name}")
                except Exception as e:
                    log(f"Failed to clean up stale file {p.name}: {e}")

    # Try parsing country codes and years from data as absolute fallback if scenario is missing
    if not country_code and "spec" in data and "data" in data["spec"]:
        rows = data["spec"]["data"].get("values", [])
        if rows:
            try:
                start_year = min(int(r["year"]) for r in rows if "year" in r)
                end_year = max(int(r["year"]) for r in rows if "year" in r)
                # Group by country name
                country_names = list(set(r["country"] for r in rows if "country" in r))
                log(f"Fallback extracted years: {start_year}-{end_year}, countries: {country_names}")

                # Resolve names to ISO country codes
                resolved_codes = []
                for name in country_names:
                    code = await _resolve_country_code(name)
                    if code:
                        resolved_codes.append(code)
                if resolved_codes:
                    country_code = ";".join(resolved_codes)
                    log(f"Resolved fallback country codes: {country_code}")
            except Exception as e:
                log(f"Failed to resolve fallback country codes: {e}")

    is_multi = len(resolved_indicators) >= 2

    # 1. Compile updated visualization engine spec via local MCP server
    try:
        log("Executing Data360 visualization engine via MCP server on 8021...")
        if is_multi:
            viz_result = await call_mcp_tool_on_8021(
                "data360_get_multi_indicator_viz_spec",
                {
                    "indicator_ids": [
                        {"database_id": ri["database_id"], "indicator_id": ri["indicator_id"]}
                        for ri in resolved_indicators
                    ],
                    "country_code": country_code,
                    "start_year": start_year,
                    "end_year": end_year,
                    "chart_type": chart_type,
                    "disaggregation_filters": disaggregation_filters,
                }
            )
        else:
            ri = resolved_indicators[0]
            viz_result = await call_mcp_tool_on_8021(
                "data360_get_viz_spec",
                {
                    "database_id": ri["database_id"],
                    "indicator_id": ri["indicator_id"],
                    "country_code": country_code,
                    "start_year": start_year,
                    "end_year": end_year,
                    "chart_type": chart_type,
                    "disaggregation_filters": disaggregation_filters,
                }
            )

        if viz_result.get("error"):
            log(f"Visualization engine returned error: {viz_result['error']}")
            return JSONResponse(status_code=400, content={"error": viz_result["error"]})

        spec = viz_result.get("spec", {})
        log(f"Chart spec generated successfully via MCP (strategy: {viz_result.get('strategy')})")
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": f"Visualization spec building failed: {exc}"})

    # Extract raw data rows
    name = spec.get("data", {}).get("name")
    if name and spec.get("datasets", {}).get(name):
        rows = spec["datasets"][name]
    else:
        rows = spec.get("data", {}).get("values", [])

    # 2a. Apply prepareSpec + WB Theme to the system spec
    system_spec = prepare_spec(spec)
    log("prepareSpec + WB Theme applied to system spec.")

    # 2b. Generate direct LLM Chart.js v4 config
    llm_chartjs = {}
    llm_score_10 = 0.0
    llm_critique = "No direct LLM chart generated."

    if rows:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            log("Contacting LLM to generate Chart.js v4 config for comparison...")
            sample_data = rows
            column_names = list(sample_data[0].keys()) if sample_data else []

            llm_chartjs_prompt = get_chartjs_user_prompt(
                question=question,
                column_names=column_names,
                sample_data=sample_data
            )

            llm_response = client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": get_chartjs_system_prompt()},
                    {"role": "user", "content": llm_chartjs_prompt}
                ],
                temperature=0.2,
            )
            llm_chartjs = json.loads(llm_response.choices[0].message.content)
            log("Direct LLM Chart.js config generated.")
        except Exception as exc:
            log(f"Direct LLM Chart.js generation failed: {exc}")

    # 3. Run DeepEval G-Eval quality scoring
    try:
        from evals.test_chart_rules_deepeval import LLMTestCase
        log("Running DeepEval G-Eval visual quality score on System Spec...")
        metric = _zero_shot_grammar_of_graphics_metric()

        scenario = {
            "country_code": country_code,
            "start_year": start_year,
            "end_year": end_year,
            "chart_type": chart_type,
            "disaggregation_filters": disaggregation_filters,
            "user_question": question
        }
        eval_input = compile_deepeval_input(resolved_indicators, scenario, rows)

        test_case = LLMTestCase(
            input=eval_input.strip(),
            actual_output=json.dumps(spec, indent=2)
        )
        metric.measure(test_case)
        score_10 = round((metric.score or 0.0) * 10, 1)
        critique = metric.reason or "No critique provided."
        log(f"DeepEval score: {score_10}/10")

        if llm_chartjs:
            log("Running DeepEval G-Eval visual quality score on LLM Chart.js config...")
            llm_metric = _chartjs_quality_metric()
            llm_test_case = LLMTestCase(
                input=eval_input.strip(),
                actual_output=json.dumps(llm_chartjs, indent=2)
            )
            llm_metric.measure(llm_test_case)
            llm_score_10 = round((llm_metric.score or 0.0) * 10, 1)
            llm_critique = llm_metric.reason or "No critique provided."
            log(f"Direct LLM Chart.js score: {llm_score_10}/10")

    except Exception as exc:
        log(f"DeepEval score failed: {exc}. Defaulting to score 0.0.")
        score_10 = 0.0
        critique = f"DeepEval scoring failed: {exc}"

    # Overwrite the existing report data
    report_data = {
        "scenario_id": data["scenario_id"],
        "question": question,
        "scenario": {
            "user_question": question,
            "country_code": country_code,
            "start_year": start_year,
            "end_year": end_year,
            "chart_type": chart_type,
            "disaggregation_filters": disaggregation_filters
        },
        "resolved_indicators": resolved_indicators,
        "viz_result": viz_result,
        "system_spec": system_spec,
        "system_score": score_10,
        "system_critique": critique,
        "llm_chartjs": llm_chartjs,
        "llm_score": llm_score_10,
        "llm_critique": llm_critique,
        "spec": system_spec,
        "score": score_10,
        "critique": critique,
        "timestamp": data["timestamp"],
        "logs": logs
    }

    with open(path, "w") as f:
        json.dump(report_data, f, indent=2)
    upload_file_to_hf(path)

    log("Report rerun completed and saved successfully.")
    return report_data


@app.post("/api/batch-surprise")
async def trigger_batch_surprise(background_tasks: BackgroundTasks):
    """Trigger background execution of 50 surprise sets."""
    if batch_status["running"]:
        return JSONResponse(status_code=400, content={"error": "A batch run is already in progress."})
    background_tasks.add_task(run_batch_surprise)
    return {"status": "Batch surprise-me run started in the background."}


class ImagePayload(BaseModel):
    scenario_id: str
    system_png_base64: str
    llm_png_base64: str


@app.post("/api/save-rendered-images")
async def save_rendered_images(payload: ImagePayload):
    """Decode and save client-side rendered system and LLM chart screenshots to disk."""
    try:
        import base64
        # Save System spec chart PNG
        if payload.system_png_base64.startswith("data:image/png;base64,"):
            sys_data = base64.b64decode(payload.system_png_base64.split(",")[1])
            sys_path = REPORTS_DIR / f"render_{payload.scenario_id}_system.png"
            sys_path.write_bytes(sys_data)
            print(f"[Dashboard Log] System chart screenshot saved: {sys_path.name}")
            upload_file_to_hf(sys_path)

        # Save LLM Chart.js chart PNG
        if payload.llm_png_base64.startswith("data:image/png;base64,"):
            llm_data = base64.b64decode(payload.llm_png_base64.split(",")[1])
            llm_path = REPORTS_DIR / f"render_{payload.scenario_id}_llm.png"
            llm_path.write_bytes(llm_data)
            print(f"[Dashboard Log] LLM chart screenshot saved: {llm_path.name}")
            upload_file_to_hf(llm_path)

        # Update report file with image path metadata
        report_files = list(REPORTS_DIR.glob(f"*{payload.scenario_id}*.json"))
        if report_files:
            report_file = report_files[0]
            try:
                data = json.loads(report_file.read_text())
                data["system_image_path"] = f"render_{payload.scenario_id}_system.png"
                data["llm_image_path"] = f"render_{payload.scenario_id}_llm.png"
                report_file.write_text(json.dumps(data, indent=2))
                upload_file_to_hf(report_file)
            except Exception as e:
                print(f"[Error] Failed to update report with image paths: {e}")

        return {"status": "success", "message": "Rendered charts stored successfully."}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": f"Failed to save screenshots: {exc}"})


@app.get("/api/reports/{scenario_id}/visual-critique")
def get_visual_critique(scenario_id: str):
    """Return the cached visual critique JSON for a scenario if it exists."""
    critique_file = REPORTS_DIR / f"visual_critique_{scenario_id}.json"
    if not critique_file.exists():
        return JSONResponse(status_code=404, content={"error": "No visual critique found for this scenario."})
    return json.loads(critique_file.read_text())


@app.post("/api/reports/{scenario_id}/visual-critique")
async def run_visual_critique(scenario_id: str):
    """Run GPT-4o Vision visual quality audit on the saved chart screenshots for a scenario."""
    # Check cache first
    critique_file = REPORTS_DIR / f"visual_critique_{scenario_id}.json"
    if critique_file.exists():
        try:
            return json.loads(critique_file.read_text())
        except Exception:
            pass

    import base64

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return JSONResponse(status_code=500, content={"error": "OPENAI_API_KEY not set in environment."})

    sys_img_path = REPORTS_DIR / f"render_{scenario_id}_system.png"
    llm_img_path = REPORTS_DIR / f"render_{scenario_id}_llm.png"

    if not sys_img_path.exists() and not llm_img_path.exists():
        return JSONResponse(
            status_code=404,
            content={"error": f"No rendered screenshots found for scenario '{scenario_id}'. Generate the chart first so screenshots are captured."}
        )

    # Read query and actual retrieved countries from the saved report JSON
    report_files = list(REPORTS_DIR.glob(f"*{scenario_id}*.json"))
    query = "Visualize data"
    actual_countries_msg = ""
    for rf in report_files:
        if "visual_critique" not in rf.name and "viz_score" not in rf.name:
            try:
                rd = json.loads(rf.read_text())
                query = rd.get("question", rd.get("query", "Visualize data"))

                # Extract actual countries from dataset
                spec = rd.get("spec", {})
                rows = []
                name = spec.get("data", {}).get("name")
                if name and spec.get("datasets", {}).get(name):
                    rows = spec["datasets"][name]
                else:
                    rows = spec.get("data", {}).get("values", [])

                if rows:
                    df_temp = pd.DataFrame(rows)
                    actual_countries = sorted(list(set(df_temp["country"].dropna().tolist()))) if "country" in df_temp.columns else []
                    actual_country_codes = sorted(list(set(df_temp["country_code"].dropna().tolist()))) if "country_code" in df_temp.columns else []
                    if not actual_country_codes and "ref_area" in df_temp.columns:
                        actual_country_codes = sorted(list(set(df_temp["ref_area"].dropna().tolist())))

                    if actual_countries:
                        actual_countries_msg = f"Actually retrieved countries in database: {', '.join(actual_countries)} ({', '.join(actual_country_codes)})"
                break
            except Exception:
                pass

    audit_prompt = f"""You are an expert data visualization design auditor. Evaluate the actual rendered chart screenshot based on the user query and data availability.

User Query Context: "{query}"
{actual_countries_msg}

Audit Guidelines:
1. VISUAL REPRESENTATION (0-4 points): Does the chart type fit the data layout? (e.g. line for trends, bar for comparison). Do the data lines/bars flatline at the zero axis or compress visual variation?
2. TYPOGRAPHY & DESIGN (0-4 points): Are titles, subtitles, axis labels, and legends readable? Are there any overlapping text labels or clipping issues?
3. THEME CONFORMANCE (0-2 points): Does it conform to clean, professional styling (approved color palette, subtle gridlines, clean layout bounds)?

CRITICAL EVALUATION RULE FOR MISSING DATA:
If some requested countries or series are missing from the chart because they are not listed in 'Actually retrieved countries in database', do NOT penalize the visualization engine or give a lower score for not plotting them. The engine can only plot the data that was actually retrieved from the database. Only evaluate the layout, design, and representation quality of the data that was actually retrieved.

Return a single JSON object containing:
- "score": A float from 0.0 to 10.0 (sum of the audit points).
- "critique": A detailed critique paragraph justifying the score based on visual evidence in the screenshot.
- "recommendations": A list of specific design improvements."""

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    def _judge(img_path: Path) -> dict:
        b64 = base64.b64encode(img_path.read_bytes()).decode("utf-8")
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional visual chart auditor. Return only a JSON object with keys: score, critique, recommendations. No markdown formatting."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": audit_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ]
                }
            ],
            temperature=0.2
        )
        return json.loads(response.choices[0].message.content)

    critique_results = {
        "scenario_id": scenario_id,
        "query": query,
        "system_visual_critique": None,
        "llm_visual_critique": None
    }

    try:
        if sys_img_path.exists():
            print(f"[Visual Critique] Auditing system render for {scenario_id}...")
            critique_results["system_visual_critique"] = _judge(sys_img_path)
            print(f"[Visual Critique] System score: {critique_results['system_visual_critique'].get('score')}/10")
    except Exception as exc:
        critique_results["system_visual_critique"] = {"score": 0.0, "critique": f"Audit failed: {exc}", "recommendations": []}

    try:
        if llm_img_path.exists():
            print(f"[Visual Critique] Auditing LLM render for {scenario_id}...")
            critique_results["llm_visual_critique"] = _judge(llm_img_path)
            print(f"[Visual Critique] LLM score: {critique_results['llm_visual_critique'].get('score')}/10")
    except Exception as exc:
        critique_results["llm_visual_critique"] = {"score": 0.0, "critique": f"Audit failed: {exc}", "recommendations": []}

    # Persist the critique
    critique_file = REPORTS_DIR / f"visual_critique_{scenario_id}.json"
    critique_file.write_text(json.dumps(critique_results, indent=2))
    print(f"[Visual Critique] Saved critique to {critique_file.name}")
    upload_file_to_hf(critique_file)

    return critique_results


@app.get("/api/batch-status")
def get_batch_status():
    """Get current progress of the background batch run."""
    return batch_status


@app.post("/api/batch-cancel")
def cancel_batch_surprise():
    """Cancel the active background batch run."""
    global batch_cancel_requested
    if not batch_status["running"]:
        return {"status": "No batch run is currently active."}
    batch_cancel_requested = True
    return {"status": "Batch surprise-me run cancellation requested."}


@app.get("/api/search-indicators")
async def search_indicators(query: str):
    """Search for database indicators matching the text query."""
    try:
        from data360 import api as data360_api
        res = await data360_api.search(query=query, limit=10)

        if hasattr(res, "error") and res.error:
            return {"error": res.error}
        if isinstance(res, dict) and res.get("error"):
            return {"error": res.get("error")}

        indicators = []
        if hasattr(res, "indicators") and res.indicators:
            for ind in res.indicators:
                indicators.append({
                    "database_id": ind.database_id,
                    "indicator_id": ind.idno,
                    "name": ind.name
                })
        elif isinstance(res, dict) and res.get("indicators"):
            for ind in res["indicators"]:
                indicators.append({
                    "database_id": ind.get("database_id"),
                    "indicator_id": ind.get("idno"),
                    "name": ind.get("name")
                })
        return indicators
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
@app.get("/api/search-countries")
async def search_countries(query: str):
    """Search for country/economy codes matching the query string."""
    try:
        from data360.providers import get_codelist_manager
        cm = get_codelist_manager()
        matches = await cm.find_value("REF_AREA", query, limit=10)
        return matches
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

@app.get("/api/groups")
async def get_all_groups():
    """Retrieve all FMR groups filtering to region, income, and lending types."""
    try:
        from data360.providers import get_group_hierarchy_manager
        ghm = get_group_hierarchy_manager()
        groups = []
        for code, info in ghm._groups.items():
            if info["type"] in {"REGION", "INCOME", "LENDING", "OTHER"}:
                groups.append({
                    "code": code,
                    "name": info["name"],
                    "type": info["type"],
                    "count": len(info["countries"])
                })
        groups.sort(key=lambda x: x["name"])
        return groups
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/api/groups/{group_code}/expand")
async def expand_group_endpoint(group_code: str):
    """Retrieve member country codes for a given FMR group."""
    try:
        from data360.providers import get_group_hierarchy_manager
        ghm = get_group_hierarchy_manager()
        return ghm.expand_group(group_code)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/api/indicator-disaggregation")
async def get_disaggregation_options(database_id: str, indicator_id: str):
    """Retrieve available timeframe, geography, and dimension breakdowns."""
    try:
        from data360 import api as data360_api
        res = await data360_api.get_disaggregation(
            database_id=database_id,
            indicator_id=indicator_id
        )
        return res
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


class CustomChartRequest(BaseModel):
    database_id: str
    indicator_id: str
    indicator_name: str
    country_code: str
    start_year: int
    end_year: int
    chart_type: str | None = None
    disaggregation_filters: dict[str, Any] = {}


@app.post("/api/custom-chart")
async def generate_custom_chart(req: CustomChartRequest):
    """Generate system Vega-Lite and direct LLM Chart.js specs for a custom user-defined query."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return JSONResponse(status_code=500, content={"error": "OPENAI_API_KEY not set in environment."})

    logs = []
    def log(msg: str):
        print(f"[Custom Chart] {msg}")
        logs.append(msg)

    database_id = req.database_id
    indicator_id = req.indicator_id
    indicator_name = req.indicator_name
    country_code = req.country_code.strip() if req.country_code else None
    if not country_code:
        country_code = None
    start_year = req.start_year
    end_year = req.end_year
    chart_type = req.chart_type if req.chart_type else None
    disaggregation_filters = req.disaggregation_filters

    resolved_indicators = [{
        "database_id": database_id,
        "indicator_id": indicator_id,
        "name": indicator_name
    }]

    log(f"Compiling spec for custom indicator request: {indicator_id} ({indicator_name})")

    try:
        log("Executing Data360 visualization engine via MCP server on 8021...")
        viz_result = await call_mcp_tool_on_8021(
            "data360_get_viz_spec",
            {
                "database_id": database_id,
                "indicator_id": indicator_id,
                "country_code": country_code,
                "start_year": start_year,
                "end_year": end_year,
                "chart_type": chart_type,
                "disaggregation_filters": disaggregation_filters,
            }
        )

        if viz_result.get("error"):
            log(f"Visualization engine returned error: {viz_result['error']}")
            return JSONResponse(status_code=400, content={"error": viz_result["error"]})

        spec = viz_result.get("spec", {})
        log(f"Chart spec generated successfully via MCP (strategy: {viz_result.get('strategy')})")
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": f"Visualization spec building failed: {exc}"})

    # Extract raw data rows
    name = spec.get("data", {}).get("name")
    if name and spec.get("datasets", {}).get(name):
        rows = spec["datasets"][name]
    else:
        rows = spec.get("data", {}).get("values", [])

    # Apply prepareSpec + WB Theme to the system spec
    system_spec = prepare_spec(spec)
    log("prepareSpec + WB Theme applied to system spec.")

    # Generate direct LLM Chart.js v4 config
    llm_chartjs = {}
    llm_score_10 = 0.0
    llm_critique = "No direct LLM chart generated."

    if rows:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            log("Contacting LLM to generate Chart.js v4 config for comparison...")
            sample_data = rows
            column_names = list(sample_data[0].keys()) if sample_data else []

            llm_chartjs_prompt = get_chartjs_user_prompt(
                question=f"Plot the indicator '{indicator_name}' for countries '{country_code}' from {start_year} to {end_year}.",
                column_names=column_names,
                sample_data=sample_data
            )

            llm_response = client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": get_chartjs_system_prompt()},
                    {"role": "user", "content": llm_chartjs_prompt}
                ],
                temperature=0.2,
            )
            llm_chartjs = json.loads(llm_response.choices[0].message.content)
            log("Direct LLM Chart.js config generated.")
        except Exception as exc:
            log(f"Direct LLM Chart.js generation failed: {exc}")

    # G-Eval quality scoring
    try:
        from evals.test_chart_rules_deepeval import LLMTestCase
        log("Running DeepEval G-Eval visual quality score on System Spec...")
        metric = _zero_shot_grammar_of_graphics_metric()

        scenario = {
            "country_code": country_code,
            "start_year": start_year,
            "end_year": end_year,
            "chart_type": chart_type,
            "disaggregation_filters": disaggregation_filters,
            "user_question": f"Plot custom indicator chart: {indicator_name}"
        }
        eval_input = compile_deepeval_input(resolved_indicators, scenario, rows)

        test_case = LLMTestCase(
            input=eval_input.strip(),
            actual_output=json.dumps(spec, indent=2)
        )
        metric.measure(test_case)
        score_10 = round((metric.score or 0.0) * 10, 1)
        critique = metric.reason or "No critique provided."
        log(f"DeepEval score: {score_10}/10")

        if llm_chartjs:
            log("Running DeepEval G-Eval visual quality score on LLM Chart.js config...")
            llm_metric = _chartjs_quality_metric()
            llm_test_case = LLMTestCase(
                input=eval_input.strip(),
                actual_output=json.dumps(llm_chartjs, indent=2)
            )
            llm_metric.measure(llm_test_case)
            llm_score_10 = round((llm_metric.score or 0.0) * 10, 1)
            llm_critique = llm_metric.reason or "No critique provided."
            log(f"Direct LLM Chart.js score: {llm_score_10}/10")

    except Exception as exc:
        log(f"DeepEval score failed: {exc}. Defaulting to score 0.0.")
        score_10 = 0.0
        critique = f"DeepEval scoring failed: {exc}"

    # Save report to JSON file
    timestamp_sec = int(time.time())
    scenario_id = f"custom_{hashlib.md5(indicator_id.encode()).hexdigest()[:8]}_{timestamp_sec}"
    report_file = REPORTS_DIR / f"{scenario_id}.json"

    report_data = {
        "scenario_id": scenario_id,
        "question": f"Custom Chart: {indicator_name} ({country_code}, {start_year}-{end_year})",
        "scenario": {
            "user_question": f"Custom Chart: {indicator_name} ({country_code}, {start_year}-{end_year})",
            "country_code": country_code,
            "start_year": start_year,
            "end_year": end_year,
            "chart_type": chart_type,
            "disaggregation_filters": disaggregation_filters
        },
        "resolved_indicators": resolved_indicators,
        "viz_result": viz_result,
        "system_spec": system_spec,
        "system_score": score_10,
        "system_critique": critique,
        "llm_chartjs": llm_chartjs,
        "llm_score": llm_score_10,
        "llm_critique": llm_critique,
        "spec": system_spec,
        "score": score_10,
        "critique": critique,
        "timestamp": pd.Timestamp.now().isoformat(),
        "logs": logs
    }

    with open(report_file, "w") as f:
        json.dump(report_data, f, indent=2)
    upload_file_to_hf(report_file)

    log("Custom chart generated and report saved successfully.")
    return report_data


# ---------------------------------------------------------------------------
# Dashboard Frontend (Single-Page App)
# ---------------------------------------------------------------------------

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Data360-MCP Visualization Engine Explorer</title>

  <!-- Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">

  <!-- Vega Embed (system panel) -->
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
  <!-- Chart.js v4 (LLM panel) -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>

  <style>
    @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Fira+Sans:wght@300;400;500;600;700&display=swap');

    :root {
      /* WBG Light Theme (Default) */
      --bg: #f8fafc;
      --surface1: #ffffff;
      --surface2: #f1f5f9;
      --border: #cbd5e1;
      --text: #0f172a;
      --text-muted: #475569;
      --accent: #0071BC;
      --accent-hover: #005a96;
      --accent-glow: rgba(0, 113, 188, 0.15);
      --wbg-gold: #CA8A04;
      --wbg-gold-hover: #a16207;
      --success: #059669;
      --warning: #d97706;
      --danger: #dc2626;
      --card-bg: rgba(255, 255, 255, 0.9);
      --sidebar-bg: #f1f5f9;
      --header-bg: rgba(255, 255, 255, 0.9);
      --header-border: #cbd5e1;
      --glass-glow: 0 8px 32px 0 rgba(0, 113, 188, 0.05);
      --transition-speed: 0.22s;
      --font-body: 'Fira Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: 'Fira Code', 'JetBrains Mono', monospace;
    }

    [data-theme="dark"] {
      /* WBG Dark Theme */
      --bg: #0b1329;
      --surface1: #111a36;
      --surface2: #1c274c;
      --border: #29386c;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #0071BC;
      --accent-hover: #008be5;
      --accent-glow: rgba(0, 113, 188, 0.25);
      --wbg-gold: #CA8A04;
      --wbg-gold-hover: #eab308;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --card-bg: rgba(17, 26, 54, 0.45);
      --sidebar-bg: #0a1024;
      --header-bg: rgba(10, 16, 36, 0.85);
      --header-border: #1c274c;
      --glass-glow: 0 8px 32px 0 rgba(0, 0, 0, 0.35);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: var(--font-body);
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transition: background-color var(--transition-speed) ease, color var(--transition-speed) ease;
    }

    header {
      background: var(--header-bg);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--header-border);
      padding: 14px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
      transition: background-color var(--transition-speed) ease, border-color var(--transition-speed) ease;
    }

    .header-logo {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .logo-badge {
      background: linear-gradient(135deg, var(--accent), var(--accent-hover));
      color: #fff;
      font-weight: 700;
      font-size: 14px;
      padding: 5px 12px;
      border-radius: 6px;
      box-shadow: 0 4px 12px var(--accent-glow);
    }

    .header-title {
      font-size: 18px;
      font-weight: 600;
      letter-spacing: -0.5px;
    }

    .header-controls {
      display: flex;
      align-items: center;
      gap: 16px;
    }

    /* Premium Theme Toggle Button */
    .theme-toggle-btn {
      background: var(--surface2);
      border: 1px solid var(--border);
      color: var(--text);
      cursor: pointer;
      width: 36px;
      height: 36px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all var(--transition-speed) cubic-bezier(0.4, 0, 0.2, 1);
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
    }

    .theme-toggle-btn:hover {
      background: var(--border);
      transform: scale(1.05);
    }

    .theme-toggle-btn svg {
      width: 18px;
      height: 18px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    [data-theme="light"] .theme-toggle-btn .moon-icon { display: none; }
    [data-theme="light"] .theme-toggle-btn .sun-icon { display: block; }
    [data-theme="dark"] .theme-toggle-btn .moon-icon { display: block; }
    [data-theme="dark"] .theme-toggle-btn .sun-icon { display: none; }

    .container {
      display: grid;
      grid-template-columns: 340px 1fr;
      flex: 1;
      height: 0;
      overflow: hidden;
    }

    /* Sidebar History */
    .sidebar {
      background: var(--sidebar-bg);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transition: background-color var(--transition-speed) ease, border-color var(--transition-speed) ease;
    }

    .sidebar-header {
      padding: 16px 20px;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      border-bottom: 1px solid var(--border);
    }

    .history-list {
      flex: 1;
      overflow-y: auto;
      padding: 12px;
    }

    /* Custom Scrollbar for visual continuity */
    ::-webkit-scrollbar {
      width: 6px;
      height: 6px;
    }
    ::-webkit-scrollbar-track {
      background: transparent;
    }
    ::-webkit-scrollbar-thumb {
      background: var(--border);
      border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
      background: var(--text-muted);
    }

    .history-card {
      background: var(--surface1);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 14px;
      margin-bottom: 8px;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .history-card:hover {
      background: var(--surface2);
      border-color: var(--text-muted);
      transform: translateY(-1px);
    }

    .history-card.active {
      background: var(--accent-glow);
      border-color: var(--accent);
      box-shadow: 0 4px 12px rgba(59, 130, 246, 0.08);
    }

    .history-card-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
      margin-bottom: 6px;
    }

    .history-question {
      font-size: 13px;
      font-weight: 600;
      line-height: 1.4;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .scores-badge {
      display: flex;
      gap: 4px;
    }

    .history-score {
      font-size: 10px;
      font-weight: 700;
      padding: 2px 5px;
      border-radius: 4px;
      white-space: nowrap;
    }

    .history-score.high { background: rgba(16, 185, 129, 0.12); color: var(--success); }
    .history-score.mid { background: rgba(245, 158, 11, 0.12); color: var(--warning); }
    .history-score.low { background: rgba(239, 68, 68, 0.12); color: var(--danger); }

    .history-time {
      font-size: 11px;
      color: var(--text-muted);
    }

    /* Main Content */
    .main-content {
      padding: 24px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 24px;
      transition: background-color var(--transition-speed) ease;
    }

    /* Batch progress banner */
    .batch-progress-bar {
      display: none;
      background: rgba(16, 185, 129, 0.08);
      border: 1px solid var(--success);
      color: var(--success);
      padding: 12px 20px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 500;
      align-items: center;
      justify-content: space-between;
      animation: pulse 2s infinite;
    }

    @keyframes pulse {
      0% { opacity: 0.9; }
      50% { opacity: 1; }
      100% { opacity: 0.9; }
    }

    /* Controls block */
    .controls-row {
      background: var(--surface1);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 20px;
      transition: background-color var(--transition-speed) ease, border-color var(--transition-speed) ease;
    }

    .query-display {
      flex: 1;
      min-width: 0;
    }

    .query-label {
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      color: var(--text-muted);
      margin-bottom: 4px;
      letter-spacing: 0.5px;
    }

    .query-text {
      font-size: 15px;
      font-weight: 500;
      line-height: 1.4;
      word-break: break-all;
      overflow-wrap: break-word;
    }

    .btn-surprise, .btn-batch {
      border: none;
      color: #fff;
      font-weight: 600;
      font-size: 13px;
      padding: 10px 20px;
      border-radius: 8px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      white-space: nowrap;
    }

    .btn-surprise {
      background: linear-gradient(135deg, var(--accent), #004d80);
      box-shadow: 0 4px 12px var(--accent-glow);
    }

    .btn-surprise:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 6px 16px rgba(0, 113, 188, 0.4);
    }

    .btn-batch {
      background: linear-gradient(135deg, #475569, #334155);
      box-shadow: 0 4px 12px rgba(71, 85, 105, 0.2);
    }

    .btn-batch:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 6px 16px rgba(71, 85, 105, 0.35);
    }

    .btn-surprise:disabled, .btn-batch:disabled {
      opacity: 0.6;
      cursor: not-allowed;
      transform: none !important;
      box-shadow: none !important;
    }

    /* Spinner */
    .spinner {
      width: 16px;
      height: 16px;
      border: 2px solid rgba(255, 255, 255, 0.3);
      border-top-color: #fff;
      border-radius: 50%;
      animation: spin 1s linear infinite;
      display: none;
    }

    .spinner-large {
      width: 40px;
      height: 40px;
      border: 3px solid rgba(255, 255, 255, 0.1);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    /* Side-by-side spec comparison layout */
    .viz-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
    }

    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      overflow: hidden;
      display: flex;
      flex-direction: column;
      box-shadow: var(--glass-glow);
      transition: background-color var(--transition-speed) ease, border-color var(--transition-speed) ease, box-shadow var(--transition-speed) ease;
    }

    .card-header {
      padding: 14px 20px;
      border-bottom: 1px solid var(--border);
      font-weight: 600;
      font-size: 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: rgba(255, 255, 255, 0.01);
      transition: border-color var(--transition-speed) ease;
    }

    .card-body {
      padding: 20px;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 250px;
      text-align: center;
      padding: 30px;
      border: 2px dashed var(--border);
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.01);
      transition: border-color var(--transition-speed) ease;
    }

    .empty-icon {
      font-size: 40px;
      margin-bottom: 12px;
      color: var(--border);
      transition: color var(--transition-speed) ease;
    }

    .empty-title {
      font-size: 15px;
      font-weight: 600;
      margin-bottom: 6px;
    }

    .empty-desc {
      font-size: 13px;
      color: var(--text-muted);
      line-height: 1.4;
      transition: color var(--transition-speed) ease;
    }

    .chart-container-div {
      width: 100%;
      min-height: 320px;
      display: none;
      overflow-x: auto;
    }

    .vega-embed canvas, .vega-embed svg {
      max-width: 100% !important;
      height: auto !important;
    }

    /* Score Header Section */
    .score-banner {
      display: flex;
      align-items: center;
      gap: 16px;
      background: rgba(255, 255, 255, 0.01);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      transition: border-color var(--transition-speed) ease;
    }

    .score-circle-wrapper {
      flex-shrink: 0;
    }

    .score-circle {
      position: relative;
      width: 64px;
      height: 64px;
    }

    .score-circle svg {
      width: 64px;
      height: 64px;
      transform: rotate(-90deg);
    }

    .score-circle circle {
      fill: none;
      stroke-width: 5;
    }

    .score-circle .circle-bg {
      stroke: var(--surface2);
      transition: stroke var(--transition-speed) ease;
    }

    .score-circle .circle-progress {
      stroke: var(--accent);
      stroke-linecap: round;
      transition: stroke-dashoffset 0.6s ease, stroke var(--transition-speed) ease;
    }

    .score-value {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }

    .score-num {
      font-size: 18px;
      font-weight: 700;
    }

    .score-max {
      font-size: 10px;
      color: var(--text-muted);
      transition: color var(--transition-speed) ease;
    }

    .score-critique-box {
      flex: 1;
    }

    .critique-title {
      font-size: 9px;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 4px;
      transition: color var(--transition-speed) ease;
    }

    .critique-text {
      font-size: 12px;
      line-height: 1.45;
      color: var(--text);
      max-height: 80px;
      overflow-y: auto;
      transition: color var(--transition-speed) ease;
    }

    /* Visual DeepEval Critique Button */
    .btn-visual-critique {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 6px 14px;
      font-size: 12px;
      font-weight: 600;
      font-family: var(--font-body);
      border-radius: 6px;
      border: 1px solid #7c3aed;
      background: rgba(124, 58, 237, 0.12);
      color: #a78bfa;
      cursor: pointer;
      transition: background 0.2s, color 0.2s, border-color 0.2s;
      white-space: nowrap;
    }
    .btn-visual-critique:hover:not(:disabled) {
      background: rgba(124, 58, 237, 0.25);
      color: #c4b5fd;
      border-color: #a78bfa;
    }
    .btn-visual-critique:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .btn-visual-critique .btn-spinner {
      width: 12px;
      height: 12px;
      border: 2px solid rgba(167,139,250,0.3);
      border-top-color: #a78bfa;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
      display: none;
    }
    /* Visual Critique Result Panel */
    .visual-critique-panel {
      display: none;
      flex-direction: column;
      gap: 8px;
      margin-top: 10px;
      padding: 12px 14px;
      border: 1px solid #7c3aed;
      border-radius: 8px;
      background: rgba(124, 58, 237, 0.06);
    }
    .visual-critique-panel .vc-score-row {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .visual-critique-panel .vc-score-badge {
      font-size: 22px;
      font-weight: 700;
      color: #a78bfa;
      line-height: 1;
    }
    .visual-critique-panel .vc-label {
      font-size: 9px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.6px;
      color: #7c3aed;
      margin-bottom: 2px;
    }
    .visual-critique-panel .vc-critique {
      font-size: 12px;
      line-height: 1.5;
      color: var(--text);
    }
    .visual-critique-panel .vc-recs {
      font-size: 11px;
      color: var(--text-muted);
      padding-left: 14px;
      margin: 0;
    }
    .visual-critique-panel .vc-recs li {
      margin-bottom: 2px;
    }

    /* Tooltip styling */
    .info-tooltip-wrapper {
      position: relative;
      display: inline-flex;
      align-items: center;
      margin-left: 6px;
      cursor: help;
      color: var(--text-muted);
      transition: color var(--transition-speed);
    }
    .info-tooltip-wrapper:hover {
      color: var(--accent);
    }
    .info-tooltip-text {
      visibility: hidden;
      width: 220px;
      background-color: var(--surface2);
      color: var(--text);
      text-align: left;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      position: absolute;
      z-index: 100;
      bottom: 125%; /* Position above the icon */
      left: 50%;
      transform: translateX(-50%);
      opacity: 0;
      transition: opacity 0.2s, visibility 0.2s;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
      font-size: 11px;
      line-height: 1.4;
      font-weight: normal;
      pointer-events: none;
      font-family: var(--font-body);
    }
    .info-tooltip-wrapper:hover .info-tooltip-text {
      visibility: visible;
      opacity: 1;
    }
    /* Scrollable card body */
    .card-body {
      overflow-y: auto;
    }

    /* Details tab bar */
    .details-card {
      display: none !important;
      background: var(--surface1);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: hidden;
      transition: background-color var(--transition-speed) ease, border-color var(--transition-speed) ease;
    }

    .tabs-header {
      background: var(--surface2);
      border-bottom: 1px solid var(--border);
      display: flex;
      transition: background-color var(--transition-speed) ease, border-color var(--transition-speed) ease;
    }

    .tab-btn {
      padding: 12px 18px;
      border: none;
      background: none;
      color: var(--text-muted);
      font-weight: 500;
      font-size: 13px;
      cursor: pointer;
      border-right: 1px solid var(--border);
      transition: all var(--transition-speed) ease;
      font-family: var(--font-body);
    }

    .tab-btn:hover {
      color: var(--text);
      background: rgba(255, 255, 255, 0.02);
    }

    .tab-btn.active {
      color: var(--text);
      background: var(--surface1);
      font-weight: 600;
    }

    .tab-body {
      padding: 20px;
      display: none;
    }

    .tab-body.active {
      display: block;
    }

    /* Pagination */
    .pagination-btn {
      padding: 6px 12px;
      background: var(--surface1);
      border: 1px solid var(--border);
      color: var(--text);
      font-size: 12px;
      font-weight: 500;
      border-radius: 6px;
      cursor: pointer;
      font-family: var(--font-body);
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .pagination-btn:hover:not(:disabled) {
      background: var(--surface2);
      border-color: var(--accent);
      color: var(--accent);
      box-shadow: 0 2px 8px var(--accent-glow);
    }
    .pagination-btn:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }

    /* Console lines */
    .log-container {
      background: #070b13;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 16px;
      font-family: var(--font-mono);
      font-size: 12px;
      line-height: 1.6;
      max-height: 250px;
      overflow-y: auto;
      transition: border-color var(--transition-speed) ease;
    }

    .terminal-line {
      margin-bottom: 4px;
      color: #94a3b8;
    }

    .terminal-line.info { color: #38bdf8; }
    .terminal-line.err { color: #f87171; }

    pre {
      background: #070b13;
      padding: 16px;
      border-radius: 6px;
      overflow: auto;
      max-height: 400px;
      border: 1px solid var(--border);
      transition: border-color var(--transition-speed) ease;
    }

    code {
      font-family: var(--font-mono);
      font-size: 12px;
      color: #38bdf8;
    }

    /* Responsive breakpoints for small monitors, laptops, and tablets */
    @media (max-width: 1550px) {
      .viz-grid {
        grid-template-columns: 1fr; /* Stack charts vertically on smaller monitors */
        gap: 16px;
      }
    }

    @media (max-width: 900px) {
      .container {
        grid-template-columns: 1fr; /* Stack sidebar and main content vertically */
        height: auto;
        overflow: auto;
      }
      body {
        height: auto;
        overflow: auto;
      }
      .sidebar {
        height: auto;
        border-right: none;
        border-bottom: 1px solid var(--border);
      }
      .controls-row {
        flex-direction: column;
        align-items: stretch;
      }
      .controls-row div[style*="display: flex"] {
        flex-direction: column;
        width: 100%;
      }
    }
  </style>
</head>
<body>

  <header>
    <div class="header-logo" onclick="showHomepage()" style="cursor: pointer;" title="Go to Homepage">
      <div class="logo-badge">Data360-MCP</div>
      <div class="header-title">Visualization Engine Explorer</div>
    </div>
    <div class="header-controls">
      <!-- Premium Switch Theme Button (No emoji, clean SVGs) -->
      <button class="theme-toggle-btn" onclick="toggleTheme()" title="Toggle Light/Dark Theme">
        <!-- Sun icon shown in Dark theme -->
        <svg class="sun-icon" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="4"></circle>
          <path d="M12 2v2"></path>
          <path d="M12 20v2"></path>
          <path d="M4.93 4.93l1.41 1.41"></path>
          <path d="M17.66 17.66l1.41 1.41"></path>
          <path d="M2 12h2"></path>
          <path d="M20 12h2"></path>
          <path d="M6.34 17.66l-1.41 1.41"></path>
          <path d="M19.07 4.93l-1.41 1.41"></path>
        </svg>
        <!-- Moon icon shown in Light theme -->
        <svg class="moon-icon" viewBox="0 0 24 24">
          <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path>
        </svg>
      </button>
      <div style="font-size: 13px; color: var(--text-muted);" id="connection-status">
        Connected
      </div>
    </div>
  </header>

  <div class="container">

    <!-- Sidebar History & Builder -->
    <div class="sidebar" id="sidebar" style="display: flex; flex-direction: column; transition: opacity var(--transition-speed) ease, filter var(--transition-speed) ease;">

      <!-- Sidebar Tabs -->
      <div style="display: flex; border-bottom: 1px solid var(--border); transition: border-color var(--transition-speed) ease;">
        <button id="sidebar-tab-history" onclick="switchSidebarTab('history')" style="flex: 1; padding: 12px; border: none; background: var(--surface2); color: var(--text); font-weight: 600; cursor: pointer; border-bottom: 2px solid var(--accent); transition: all 0.2s; font-family: var(--font-body); font-size: 13px;">Past Runs</button>
        <button id="sidebar-tab-builder" onclick="switchSidebarTab('builder')" style="flex: 1; padding: 12px; border: none; background: var(--surface1); color: var(--text-muted); font-weight: 500; cursor: pointer; border-bottom: 2px solid transparent; transition: all 0.2s; font-family: var(--font-body); font-size: 13px;">Chart Builder</button>
      </div>

      <!-- Tab Content: History List -->
      <div id="history-tab-content" style="display: flex; flex-direction: column; flex: 1; overflow: hidden;">
        <div class="sidebar-header" style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; transition: background-color var(--transition-speed) ease;">
          <span>Past Runs</span>
          <button onclick="triggerSurpriseMe()" style="background: rgba(37, 99, 235, 0.15); border: 1px solid var(--accent); color: var(--accent); font-size: 14px; font-weight: bold; cursor: pointer; padding: 2px 8px; border-radius: 4px; transition: all 0.2s ease;" title="New Surprise Run" id="btn-plus-new">+</button>
        </div>
        <div class="history-list" id="history-list" style="flex: 1; overflow-y: auto;">
          <!-- Dynamic history cards -->
        </div>
        <!-- Pagination controls -->
        <div class="pagination-controls" style="display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; border-top: 1px solid var(--border); background: var(--surface2); transition: border-color var(--transition-speed) ease, background-color var(--transition-speed) ease;">
          <button id="btn-page-prev" onclick="prevHistoryPage()" class="pagination-btn">Prev</button>
          <span id="page-indicator" style="font-size: 12px; color: var(--text-muted); font-family: var(--font-body);">Page 1 of 1</span>
          <button id="btn-page-next" onclick="nextHistoryPage()" class="pagination-btn">Next</button>
        </div>
      </div>

      <!-- Tab Content: Chart Builder Form -->
      <div id="builder-tab-content" style="display: none; padding: 16px; overflow-y: auto; flex: 1;">
        <div style="display: flex; flex-direction: column; gap: 14px;">

          <!-- Search indicators box -->
          <div style="display: flex; flex-direction: column; gap: 6px;">
            <label style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">1. Search Indicator</label>
            <div style="display: flex; gap: 8px;">
              <input type="text" id="builder-search-input" placeholder="e.g. government effectiveness" style="flex: 1; padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface2); color: var(--text); font-family: var(--font-body); font-size: 13px; outline: none; transition: border-color 0.2s;" onkeydown="if(event.key==='Enter') searchBuilderIndicators()">
              <button onclick="searchBuilderIndicators()" style="padding: 8px 12px; border: none; background: var(--accent); color: white; font-weight: 600; border-radius: 6px; cursor: pointer; font-size: 13px; transition: opacity 0.2s;">Search</button>
            </div>
            <div id="builder-search-results" style="max-height: 150px; overflow-y: auto; border: 1px solid var(--border); border-radius: 6px; background: var(--surface2); display: none; margin-top: 6px; transition: border-color var(--transition-speed) ease;">
              <!-- Dynamic search results list -->
            </div>
          </div>

          <!-- Configuration Fields (hidden until an indicator is selected) -->
          <div id="builder-configurator" style="display: none; flex-direction: column; gap: 14px; border-top: 1px dashed var(--border); padding-top: 14px;">

            <!-- Selected Indicator details -->
            <div style="background: rgba(37, 99, 235, 0.08); border: 1px solid rgba(37, 99, 235, 0.2); padding: 10px; border-radius: 6px;">
              <div style="font-size: 11px; font-weight: 700; color: var(--accent);" id="selected-indicator-db"></div>
              <div style="font-size: 13px; font-weight: 600; margin-top: 2px; color: var(--text);" id="selected-indicator-name"></div>
              <div style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); margin-top: 2px;" id="selected-indicator-id"></div>
            </div>            <!-- Countries selector -->
            <div style="display: flex; flex-direction: column; gap: 4px; position: relative;">
              <label style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">2. Selected Economies / Country Codes</label>
              <input type="text" id="builder-countries" value="USA;BRA;KEN;COL" style="padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface2); color: var(--text); font-family: var(--font-mono); font-size: 13px; outline: none;" placeholder="e.g. USA;BRA;KEN;COL" oninput="updateCountryBadges()">
              <div style="font-size: 11px; color: var(--text-muted); margin-top: 1px; margin-bottom: 2px;">Leave blank to query all economies.</div>

              <!-- Assisted Country Search -->
              <div style="display: flex; gap: 6px; margin-top: 4px;">
                <input type="text" id="builder-country-search" placeholder="Type country to add (e.g. India)..." style="flex: 1; padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface2); color: var(--text); font-family: var(--font-body); font-size: 12px; outline: none;" onkeydown="if(event.key==='Enter') { event.preventDefault(); searchBuilderCountries(); }">
                <button type="button" onclick="searchBuilderCountries()" style="padding: 6px 10px; border: none; background: var(--accent); color: white; font-weight: 600; border-radius: 6px; cursor: pointer; font-size: 12px;">Add</button>
              </div>
              <div id="builder-country-results" style="max-height: 120px; overflow-y: auto; border: 1px solid var(--border); border-radius: 6px; background: var(--surface2); display: none; margin-top: 4px; position: absolute; z-index: 10; width: 100%; top: 86px;">
                <!-- Country search results list -->
              </div>

              <!-- Economy Group (FMR) Selector -->
              <div style="display: flex; flex-direction: column; gap: 4px; margin-top: 8px;">
                <label style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">Add Economy Group (FMR)</label>
                <select id="builder-group-select" onchange="onGroupSelected()" style="padding: 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface2); color: var(--text); font-family: var(--font-body); font-size: 13px; outline: none; width: 100%;">
                  <option value="">Select a group...</option>
                  <optgroup label="Regions">
                    <option value="EAS">East Asia & Pacific</option>
                    <option value="ECS">Europe & Central Asia</option>
                    <option value="LCN">Latin America & Caribbean</option>
                    <option value="MEA">Middle East & North Africa</option>
                    <option value="NAC">North America</option>
                    <option value="SAS">South Asia</option>
                    <option value="SSF">Sub-Saharan Africa</option>
                  </optgroup>
                  <optgroup label="Income Groups">
                    <option value="LIC">Low income</option>
                    <option value="LMC">Lower middle income</option>
                    <option value="UMC">Upper middle income</option>
                    <option value="HIC">High income</option>
                  </optgroup>
                </select>
              </div>

              <!-- Economy Group Mode Configuration -->
              <div id="builder-group-config" style="display: none; flex-direction: column; gap: 6px; background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border); padding: 10px; border-radius: 6px; margin-top: 6px;">
                <div style="font-size: 12px; font-weight: 600; color: var(--text);" id="builder-selected-group-name"></div>
                <div style="display: flex; flex-direction: column; gap: 4px;">
                  <label style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text); cursor: pointer;">
                    <input type="radio" name="builder-group-mode" value="direct" checked style="cursor: pointer;">
                    <span>Use group code directly (e.g. <span id="builder-selected-group-code-direct" style="font-family: monospace; font-weight: 600;"></span>)</span>
                  </label>
                  <label style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text); cursor: pointer;">
                    <input type="radio" name="builder-group-mode" value="expand" style="cursor: pointer;">
                    <span>Expand to its member economies (<span id="builder-selected-group-count" style="font-weight: 600;"></span> countries)</span>
                  </label>
                </div>
                <button type="button" onclick="addGroupToBuilder()" style="margin-top: 4px; padding: 6px 12px; border: none; background: var(--accent); color: white; font-weight: 600; border-radius: 6px; cursor: pointer; font-size: 12px; align-self: flex-start;">Add Group</button>
              </div>

              <div id="builder-selected-countries-badges" style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;">
                <!-- Dynamically populated badges for active countries -->
              </div>
            </div>

            <!-- Year bounds -->
            <div style="display: flex; gap: 12px;">
              <div style="flex: 1; display: flex; flex-direction: column; gap: 4px;">
                <label style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">Start Year</label>
                <select id="builder-start-year" style="padding: 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface2); color: var(--text); font-family: var(--font-body); font-size: 13px; outline: none; width: 100%;">
                  <!-- Dynamic start years -->
                </select>
              </div>
              <div style="flex: 1; display: flex; flex-direction: column; gap: 4px;">
                <label style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">End Year</label>
                <select id="builder-end-year" style="padding: 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface2); color: var(--text); font-family: var(--font-body); font-size: 13px; outline: none; width: 100%;">
                  <!-- Dynamic end years -->
                </select>
              </div>
            </div>

            <!-- Dynamic Disaggregation filters -->
            <div id="builder-disaggregations-container" style="display: flex; flex-direction: column; gap: 6px;">
              <label style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">3. Disaggregation Options</label>
              <div id="builder-disaggregations-list" style="display: flex; flex-direction: column; gap: 8px; background: var(--surface2); padding: 10px; border-radius: 6px; border: 1px solid var(--border); max-height: 180px; overflow-y: auto;">
                <!-- Dynamic dimensions checkboxes/radios -->
              </div>
            </div>

            <!-- Chart Hint -->
            <div style="display: flex; flex-direction: column; gap: 4px;">
              <label style="font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">4. Chart Type Hint</label>
              <select id="builder-chart-type" style="padding: 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface2); color: var(--text); font-family: var(--font-body); font-size: 13px; outline: none; width: 100%;">
                <option value="">None (Auto-Route)</option>
                <option value="line">Line Chart</option>
                <option value="bar">Bar Chart</option>
                <option value="scatter">Scatter Plot</option>
                <option value="small_multiples">Small Multiples</option>
              </select>
            </div>

            <!-- Submit Button -->
            <button id="btn-builder-generate" onclick="generateCustomBuilderChart()" style="width: 100%; padding: 12px; border: none; background: linear-gradient(135deg, var(--accent), #1d4ed8); color: white; font-weight: bold; border-radius: 8px; cursor: pointer; font-size: 14px; margin-top: 8px; box-shadow: 0 4px 12px var(--accent-glow); transition: all 0.2s ease;">
              Generate Custom Visuals
            </button>
          </div>

        </div>
      </div>
    </div>

    <!-- Main Content -->
    <div class="main-content">

      <!-- Batch Progress Banner -->
      <div class="batch-progress-bar" id="batch-progress-bar" style="display: none; justify-content: space-between; align-items: center; width: 100%;">
        <span style="display: flex; align-items: center; gap: 6px;">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
          <strong>Batch Run in progress:</strong> <span id="batch-progress-text">0/50 sets completed</span>
        </span>
        <button onclick="cancelBatchSurprise()" style="background: #ef4444; border: 1px solid #dc2626; color: white; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 6px; cursor: pointer; transition: background 0.2s;" onmouseover="this.style.background='#dc2626'" onmouseout="this.style.background='#ef4444'">Cancel Run</button>
      </div>

      <!-- Controls Row -->
      <div class="controls-row">
        <div class="query-display" style="display: flex; flex-direction: column; width: 100%; flex: 1; min-width: 0;">
          <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
            <div class="query-label">Active Scenario Query</div>
            <button id="btn-clear-selection" onclick="showHomepage()" style="display: none; background: transparent; border: none; color: var(--text-muted); cursor: pointer; padding: 4px; border-radius: 4px; transition: color 0.2s;" onmouseover="this.style.color='var(--text)'" onmouseout="this.style.color='var(--text-muted)'" title="Return to Homepage">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
          <div class="query-text" id="query-text">No active query. Click "Surprise Me!" or trigger a past run.</div>
        </div>
        <div style="display: flex; gap: 12px; align-items: center;">
          <button class="btn-surprise" id="btn-visual-critique-global" onclick="triggerVisualCritiqueGlobal()" style="display: none; background: linear-gradient(135deg, var(--accent), var(--accent-hover)); box-shadow: 0 4px 15px var(--accent-glow);">
            <div class="spinner" id="vc-spinner-global"></div>
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
            <span id="btn-vc-label-global">Run Visual Critique</span>
          </button>
          <button class="btn-surprise" id="btn-rerun" onclick="triggerRerun()" style="display: none; background: linear-gradient(135deg, #4B5563, #374151); box-shadow: 0 4px 15px rgba(75, 85, 99, 0.4);">
            <div class="spinner" id="btn-rerun-spinner"></div>
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M3 21v-5h5"/></svg>
            <span id="btn-rerun-label">Rerun this run</span>
          </button>
          <button class="btn-surprise" id="btn-delete" onclick="triggerDelete()" style="display: none; background: linear-gradient(135deg, #EF4444, #DC2626); box-shadow: 0 4px 15px rgba(239, 68, 68, 0.4);">
            <div class="spinner" id="btn-delete-spinner"></div>
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
            <span id="btn-delete-label">Delete this run</span>
          </button>
          <button class="btn-batch" id="btn-batch" onclick="triggerBatchSurprise()" style="display: none !important;">
            <div class="spinner" id="btn-batch-spinner"></div>
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
            <span id="btn-batch-label">Batch Run (50 sets)</span>
          </button>
          <button class="btn-surprise" id="btn-surprise" onclick="triggerSurpriseMe()">
            <div class="spinner" id="btn-spinner"></div>
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 4px;"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275Z"/><path d="m5 3 1 2.5L8.5 6 6 7 5 9.5 4 7 1.5 6 4 5Z"/><path d="m19 17 1 2.5 2.5.5-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1Z"/></svg>
            <span id="btn-label">Surprise Me!</span>
          </button>
        </div>
      </div>

      <!-- Welcome / User Guide Homepage -->
      <div class="welcome-container" id="welcome-container" style="background: var(--card-bg); border: 1px solid var(--border); border-radius: 14px; padding: 32px; backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); box-shadow: var(--glass-glow); display: block; color: var(--text); margin-bottom: 24px;">
        <h1 style="font-size: 26px; font-weight: 700; margin-top: 0; margin-bottom: 8px; background: linear-gradient(135deg, var(--text), var(--text-muted)); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">Welcome to Data360-MCP Visualization Engine Explorer</h1>
        <p style="font-size: 14px; color: var(--text-muted); margin-bottom: 32px; line-height: 1.5;">An interactive interface for evaluating the Data360 MCP visualization engine vs. Direct LLM renders.</p>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 32px;">
          <div style="background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border); padding: 20px; border-radius: 10px;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275Z"/><path d="m5 3 1 2.5L8.5 6 6 7 5 9.5 4 7 1.5 6 4 5Z"/><path d="m19 17 1 2.5 2.5.5-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1Z"/></svg>
              <h3 style="font-size: 15px; font-weight: 600; margin: 0; color: var(--text);">Surprise Me! Action</h3>
            </div>
            <p style="font-size: 13px; color: var(--text-muted); margin: 0; line-height: 1.5;">
              Randomly generates a data profile (indicator counts, start/end years, country cardinalities, sex/age/urbanisation filters, and custom dimensions) directly from the Data360 MCP, then prompts GPT-4o-mini to frame a natural question matching those parameters. This ensures testing is free of prompt bias.
            </p>
          </div>

          <div style="background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border); padding: 20px; border-radius: 10px;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
              <h3 style="font-size: 15px; font-weight: 600; margin: 0; color: var(--text);">Run Visual Critique</h3>
            </div>
            <p style="font-size: 13px; color: var(--text-muted); margin: 0; line-height: 1.5;">
              Captures high-fidelity PNG screenshots of both chart renders and triggers a GPT-4o Vision audit to check for layout issues (axis overlapping, contrast, flatlining). Critique score and improvement lists are displayed under each chart and cached instantly.
            </p>
          </div>
        </div>

        <div style="background: rgba(0, 113, 188, 0.06); border: 1px solid var(--border); padding: 24px; border-radius: 10px;">
          <h3 style="font-size: 15px; font-weight: 600; margin-top: 0; margin-bottom: 8px; color: var(--text); display: flex; align-items: center; gap: 6px;">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            How it works
          </h3>
          <p style="font-size: 13px; color: var(--text-muted); margin: 0 0 16px 0; line-height: 1.5;">
            The central view allows side-by-side assessment. On the left is the <strong>Data360 Engine Spec</strong>, applying the repository's strict visualization routing and scaling rules. On the right is the <strong>Direct LLM Spec</strong> (GPT-4o), which generates free-form Chart.js graphs.
          </p>
          <div style="font-size: 12px; color: var(--text-muted); font-family: var(--font-mono); background: rgba(0,0,0,0.15); padding: 8px 12px; border-radius: 6px; display: inline-block;">
            No active query. Click "Surprise Me!" or trigger a past run from the sidebar.
          </div>
        </div>
      </div>

      <!-- Comparison Grid -->
      <div class="viz-grid" id="viz-grid" style="display: none;">

        <!-- Left: Data360 System Engine -->
        <div class="card">
          <div class="card-header">
            <span>Data360 Engine Spec</span>
            <span id="system-strategy-badge" style="font-size:11px; background:var(--surface2); padding:4px 8px; border-radius:4px; font-family:monospace; display:none;"></span>
          </div>
          <div class="card-body">

            <!-- Visualization rendering -->
            <div class="empty-state" id="system-chart-empty-state">
              <svg class="empty-icon-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="width: 48px; height: 48px; color: var(--text-muted); opacity: 0.6; margin-bottom: 12px;"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
              <div class="empty-title">Data360 Spec View</div>
              <div class="empty-desc">System engine visualization will render here.</div>
            </div>
            <div class="empty-state" id="system-chart-loading-state" style="display: none; flex-direction: column; justify-content: center; align-items: center; min-height: 250px;">
              <div class="spinner-large" style="margin-bottom: 16px;"></div>
              <div class="empty-title" style="font-size:14px; font-weight:600; color:var(--text);">Compiling Spec...</div>
              <div class="empty-desc" style="font-size:12px; color:var(--text-muted); margin-top:4px;">Retrieving MCP data and rendering charts</div>
            </div>
            <div class="chart-container-div" id="system-chart-container"></div>

            <!-- Score & Critique Banner -->
            <div class="score-banner" id="system-score-banner" style="display: none; margin-top: 20px;">
              <div class="score-circle-wrapper">
                <div class="score-circle">
                  <svg>
                    <circle class="circle-bg" cx="34" cy="34" r="30"></circle>
                    <circle class="circle-progress" id="system-circle-progress" cx="34" cy="34" r="30" stroke-dasharray="188.5" stroke-dashoffset="188.5"></circle>
                  </svg>
                  <div class="score-value">
                    <span class="score-num" id="system-score-num">0.0</span>
                    <span class="score-max">/ 10</span>
                  </div>
                </div>
              </div>
              <div class="score-critique-box">
                <div class="critique-title" style="display: flex; align-items: center;">
                  <span>G-Eval Scorer Critique & Rationale</span>
                  <span class="info-tooltip-wrapper">
                    <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                    <span class="info-tooltip-text">Assesses chart specification correctness, parameter alignment, and proper layout routing based on MCP metadata standards.</span>
                  </span>
                </div>
                <div class="critique-text" id="system-critique-text">No critique.</div>
              </div>
            </div>

            <!-- Visual Critique Result (System) -->
            <div class="visual-critique-panel" id="vc-panel-system" style="margin-top: 20px;">
              <div class="vc-label" style="display: flex; align-items: center;">
                <span>GPT-4o Vision Audit</span>
                <span class="info-tooltip-wrapper">
                  <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                  <span class="info-tooltip-text">Reviews the rendered chart image for visual bugs: overlapping text, clipped labels, color contrast, and empty flatlining.</span>
                </span>
              </div>
              <div class="vc-score-row">
                <div class="vc-score-badge" id="vc-score-system">–</div>
                <div style="font-size:11px; color:var(--text-muted);">/ 10</div>
              </div>
              <div class="vc-critique" id="vc-critique-system"></div>
              <ul class="vc-recs" id="vc-recs-system"></ul>
            </div>

          </div>
        </div>

        <!-- Right: Direct LLM Vega-Lite -->
        <div class="card">
          <div class="card-header">
            <span>Direct LLM Spec</span>
            <span style="font-size:11px; background:var(--surface2); padding:4px 8px; border-radius:4px; font-family:monospace;">Model: gpt-4o</span>
          </div>
          <div class="card-body">

            <!-- Visualization rendering -->
            <div class="empty-state" id="llm-chart-empty-state">
              <svg class="empty-icon-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="width: 48px; height: 48px; color: var(--text-muted); opacity: 0.6; margin-bottom: 12px;"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
              <div class="empty-title">Direct LLM Spec</div>
              <div class="empty-desc">Direct LLM generated visualization will render here.</div>
            </div>
            <div class="empty-state" id="llm-chart-loading-state" style="display: none; flex-direction: column; justify-content: center; align-items: center; min-height: 250px;">
              <div class="spinner-large" style="margin-bottom: 16px;"></div>
              <div class="empty-title" style="font-size:14px; font-weight:600; color:var(--text);">Compiling Spec...</div>
              <div class="empty-desc" style="font-size:12px; color:var(--text-muted); margin-top:4px;">Retrieving Direct LLM visualization output</div>
            </div>
            <div class="chart-container-div" id="llm-chart-container"></div>

            <!-- Score & Critique Banner -->
            <div class="score-banner" id="llm-score-banner" style="display: none; margin-top: 20px;">
              <div class="score-circle-wrapper">
                <div class="score-circle">
                  <svg>
                    <circle class="circle-bg" cx="34" cy="34" r="30"></circle>
                    <circle class="circle-progress" id="llm-circle-progress" cx="34" cy="34" r="30" stroke-dasharray="188.5" stroke-dashoffset="188.5"></circle>
                  </svg>
                  <div class="score-value">
                    <span class="score-num" id="llm-score-num">0.0</span>
                    <span class="score-max">/ 10</span>
                  </div>
                </div>
              </div>
              <div class="score-critique-box">
                <div class="critique-title" style="display: flex; align-items: center;">
                  <span>G-Eval Scorer Critique & Rationale</span>
                  <span class="info-tooltip-wrapper">
                    <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                    <span class="info-tooltip-text">Assesses chart specification correctness, parameter alignment, and proper layout routing based on MCP standards.</span>
                  </span>
                </div>
                <div class="critique-text" id="llm-critique-text">No critique.</div>
              </div>
            </div>

            <!-- Visual Critique Result (LLM) -->
            <div class="visual-critique-panel" id="vc-panel-llm" style="margin-top: 20px;">
              <div class="vc-label" style="display: flex; align-items: center;">
                <span>GPT-4o Vision Audit</span>
                <span class="info-tooltip-wrapper">
                  <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                  <span class="info-tooltip-text">Reviews the rendered chart image for visual bugs: overlapping text, clipped labels, color contrast, and empty flatlining.</span>
                </span>
              </div>
              <div class="vc-score-row">
                <div class="vc-score-badge" id="vc-score-llm">–</div>
                <div style="font-size:11px; color:var(--text-muted);">/ 10</div>
              </div>
              <div class="vc-critique" id="vc-critique-llm"></div>
              <ul class="vc-recs" id="vc-recs-llm"></ul>
            </div>

          </div>
        </div>

      </div>

      <!-- Bottom Details Tabs -->
      <div class="details-card" style="display: none;">
        <div class="tabs-header">
          <button class="tab-btn active" onclick="switchTab(event, 'tab-specs')">Vega-Lite Specs Comparison</button>
          <button class="tab-btn" onclick="switchTab(event, 'tab-resolved')">Resolved Parameters</button>
        </div>

        <div class="tab-body" id="tab-logs" style="display: none !important;">
          <div class="log-container" id="log-console">
            <div class="terminal-line">Console initialized. Ready to generate scenarios.</div>
          </div>
        </div>

        <div class="tab-body active" id="tab-specs">
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
            <div>
              <div style="font-size:12px; font-weight:600; color:var(--text-muted); margin-bottom:8px;">Data360 Engine Spec</div>
              <pre><code id="system-spec-code">No spec loaded</code></pre>
            </div>
            <div>
              <div style="font-size:12px; font-weight:600; color:var(--text-muted); margin-bottom:8px;">Direct LLM Spec</div>
              <pre><code id="llm-spec-code">No spec loaded</code></pre>
            </div>
          </div>
        </div>

        <div class="tab-body" id="tab-resolved">
          <pre><code id="resolved-code-block">{ "resolved": "No parameters resolved" }</code></pre>
        </div>
      </div>

    </div>
  </div>

  <script>
    let activeReport = null;
    let activeReportFilename = null;
    let batchCheckInterval = null;
    window.lastReportData = null;

    // Theme switching logic
    function initTheme() {
      const savedTheme = localStorage.getItem("theme") || "light";
      document.documentElement.setAttribute("data-theme", savedTheme);
    }

    function toggleTheme() {
      const currentTheme = document.documentElement.getAttribute("data-theme") || "light";
      const newTheme = currentTheme === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", newTheme);
      localStorage.setItem("theme", newTheme);
      if (window.lastReportData) {
        renderReport(window.lastReportData);
      }
    }

    initTheme();

    let historyItems = [];
    let currentHistoryPage = 1;
    const historyPageSize = 8;

    // Load History on startup
    async function loadHistory() {
      try {
        const res = await fetch("/api/history");
        historyItems = await res.json();

        // Clamp current page if items decreased
        const totalPages = Math.ceil(historyItems.length / historyPageSize) || 1;
        if (currentHistoryPage > totalPages) {
          currentHistoryPage = totalPages;
        }

        renderHistoryPage();
      } catch (err) {
        console.error("Failed to load history:", err);
      }
    }

    function renderHistoryPage() {
      const container = document.getElementById("history-list");
      container.innerHTML = "";

      if (historyItems.length === 0) {
        container.innerHTML = `<div style="text-align:center; padding:20px; font-size:12px; color:var(--text-muted);">No history found. Click "Surprise Me!"</div>`;
        document.getElementById("page-indicator").textContent = "Page 1 of 1";
        document.getElementById("btn-page-prev").disabled = true;
        document.getElementById("btn-page-next").disabled = true;
        return;
      }

      const totalPages = Math.ceil(historyItems.length / historyPageSize) || 1;
      document.getElementById("page-indicator").textContent = `Page ${currentHistoryPage} of ${totalPages}`;
      document.getElementById("btn-page-prev").disabled = (currentHistoryPage === 1);
      document.getElementById("btn-page-next").disabled = (currentHistoryPage === totalPages);

      const startIndex = (currentHistoryPage - 1) * historyPageSize;
      const endIndex = startIndex + historyPageSize;
      const pageItems = historyItems.slice(startIndex, endIndex);

      pageItems.forEach((item) => {
        const card = document.createElement("div");
        card.className = "history-card";
        if (activeReport && activeReport.scenario_id === item.scenario_id) {
          card.classList.add("active");
        }

        let scoreClass = "low";
        if (item.score >= 7.5) scoreClass = "high";
        else if (item.score >= 5.0) scoreClass = "mid";

        let llmScoreClass = "low";
        if (item.llm_score >= 7.5) llmScoreClass = "high";
        else if (item.llm_score >= 5.0) llmScoreClass = "mid";

        const formattedTime = new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        card.innerHTML = `
          <div class="history-card-header">
            <span class="history-question">${item.question}</span>
            <div class="scores-badge">
              <span class="history-score ${scoreClass}" title="Engine Score">E: ${item.score.toFixed(1)}</span>
              <span class="history-score ${llmScoreClass}" title="LLM Score">L: ${item.llm_score.toFixed(1)}</span>
            </div>
          </div>
          <div class="history-time">${formattedTime}</div>
        `;
        card.onclick = () => {
          activeReportFilename = item.filename;
          loadReport(item.filename);
        };
        container.appendChild(card);
      });
    }

    function prevHistoryPage() {
      if (currentHistoryPage > 1) {
        currentHistoryPage--;
        renderHistoryPage();
      }
    }

    function nextHistoryPage() {
      const totalPages = Math.ceil(historyItems.length / historyPageSize) || 1;
      if (currentHistoryPage < totalPages) {
        currentHistoryPage++;
        renderHistoryPage();
      }
    }

    function selectScenario(scenarioId, isNewRun = false) {
      const item = historyItems.find(x => x.scenario_id === scenarioId);
      if (item) {
        const index = historyItems.indexOf(item);
        currentHistoryPage = Math.floor(index / historyPageSize) + 1;
        activeReportFilename = item.filename;
        loadReport(item.filename, isNewRun);
      }
    }

    // Background task interface blocker
    function setSidebarDisabled(disabled) {
      const sidebar = document.getElementById('sidebar');
      if (!sidebar) return;
      if (disabled) {
        sidebar.style.pointerEvents = 'none';
        sidebar.style.opacity = '0.5';
        sidebar.style.filter = 'grayscale(35%)';
        sidebar.style.cursor = 'not-allowed';
      } else {
        sidebar.style.pointerEvents = 'auto';
        sidebar.style.opacity = '1';
        sidebar.style.filter = 'none';
        sidebar.style.cursor = 'default';
      }
    }

    // Chart loaders state toggler
    function setChartLoading(loading) {
      const sysEmpty = document.getElementById("system-chart-empty-state");
      const sysLoading = document.getElementById("system-chart-loading-state");
      const sysContainer = document.getElementById("system-chart-container");

      const llmEmpty = document.getElementById("llm-chart-empty-state");
      const llmLoading = document.getElementById("llm-chart-loading-state");
      const llmContainer = document.getElementById("llm-chart-container");

      if (loading) {
        if (sysEmpty) sysEmpty.style.display = "none";
        if (sysLoading) sysLoading.style.display = "flex";
        if (sysContainer) sysContainer.style.display = "none";

        if (llmEmpty) llmEmpty.style.display = "none";
        if (llmLoading) llmLoading.style.display = "flex";
        if (llmContainer) llmContainer.style.display = "none";
      } else {
        if (sysLoading) sysLoading.style.display = "none";
        if (llmLoading) llmLoading.style.display = "none";
      }
    }

    async function loadReport(filename, isNewRun = false) {
      try {
        activeReportFilename = filename;
        const res = await fetch(`/api/reports/${filename}`);
        const data = await res.json();
        if (activeReportFilename !== filename) return;
        data.filename = filename;
        renderReport(data, isNewRun);
      } catch (err) {
        console.error("Failed to load report:", err);
      }
    }

    function renderReport(data, isNewRun = false) {
      activeReport = data;
      window.lastReportData = data;
      setChartLoading(false);

      document.getElementById("welcome-container").style.display = "none";
      document.getElementById("viz-grid").style.display = "grid";
      document.querySelector(".details-card").style.display = "block";
      document.getElementById("btn-clear-selection").style.display = "block";

      const currentTheme = document.documentElement.getAttribute("data-theme") || "light";
      const isDark = currentTheme === "dark";

      document.getElementById("btn-rerun").style.display = "flex";
      document.getElementById("btn-delete").style.display = "flex";

      // Update UI active card states
      document.querySelectorAll(".history-card").forEach(card => {
        const question = card.querySelector(".history-question").textContent;
        if (question === data.question) {
          card.classList.add("active");
        } else {
          card.classList.remove("active");
        }
      });

      document.getElementById("query-text").textContent = data.question;

      // Render System Spec
      document.getElementById("system-chart-empty-state").style.display = "none";
      const systemContainer = document.getElementById("system-chart-container");
      systemContainer.style.display = "block";
      systemContainer.innerHTML = "";

      const strategyBadge = document.getElementById("system-strategy-badge");
      strategyBadge.style.display = "inline";
      strategyBadge.textContent = `Strategy: ${data.viz_result.strategy}`;

      // Clone system spec to dynamically customize colors based on active theme
      const spec = JSON.parse(JSON.stringify(data.system_spec || data.spec || {}));
      if (spec && Object.keys(spec).length > 0) {
        if (!spec.config) spec.config = {};
        spec.config.background = "transparent";

        const textColor = isDark ? "#f9fafb" : "#0f172a";
        const gridColor = isDark ? "#243146" : "#e2e8f0";
        const mutedColor = isDark ? "#9ca3af" : "#475569";

        if (!spec.config.axis) spec.config.axis = {};
        spec.config.axis.titleColor = textColor;
        spec.config.axis.labelColor = mutedColor;
        spec.config.axis.gridColor = gridColor;
        spec.config.axis.tickColor = gridColor;

        if (!spec.config.legend) spec.config.legend = {};
        spec.config.legend.labelColor = textColor;
        spec.config.legend.titleColor = textColor;

        if (!spec.config.title) spec.config.title = {};
        spec.config.title.color = textColor;
        spec.config.title.subtitleColor = mutedColor;

        // Apply dynamic subtitle and title limits to prevent layout squeezing
        const containerWidth = systemContainer.clientWidth || 500;
        const textLimit = Math.max(300, containerWidth - 40);
        spec.config.title.limit = textLimit;
        spec.config.title.subtitleLimit = textLimit;
        if (spec.title && typeof spec.title === "object") {
          if (spec.title.limit === undefined) spec.title.limit = textLimit;
          if (spec.title.subtitleLimit === undefined) spec.title.subtitleLimit = textLimit;
        }

        // Render at default specs, scaled proportionally in CSS to avoid squishing

        vegaEmbed("#system-chart-container", spec, {
          actions: { export: true, source: false, editor: false },
          renderer: "canvas",
        }).catch(err => {
          systemContainer.innerHTML = `<div style="color:var(--danger); padding:16px;">Compile error: ${err}</div>`;
        });
      }

      // Render LLM Chart.js panel
      const llmContainer = document.getElementById("llm-chart-container");
      if (data.llm_chartjs && data.llm_chartjs.type && data.llm_chartjs.data) {
        document.getElementById("llm-chart-empty-state").style.display = "none";
        llmContainer.style.display = "block";
        llmContainer.innerHTML = `<div style="position:relative;width:100%;height:340px;"><canvas id="llm-chartjs-canvas"></canvas></div>`;
        const canvas = document.getElementById("llm-chartjs-canvas");
        if (window._llmChart) {
          try { window._llmChart.destroy(); } catch(e) {}
        }
        try {
          const llmChartjs = JSON.parse(JSON.stringify(data.llm_chartjs));

          if (!llmChartjs.options) llmChartjs.options = {};
          llmChartjs.options.responsive = true;
          llmChartjs.options.maintainAspectRatio = false;

          // Theme options dynamically
          const textColor = isDark ? "#f9fafb" : "#0f172a";
          const gridColor = isDark ? "#243146" : "#e2e8f0";
          const mutedColor = isDark ? "#9ca3af" : "#475569";

          if (!llmChartjs.options.plugins) llmChartjs.options.plugins = {};

          // Style Title
          if (!llmChartjs.options.plugins.title) llmChartjs.options.plugins.title = {};
          llmChartjs.options.plugins.title.color = textColor;
          llmChartjs.options.plugins.title.font = {
            family: "var(--font-body)",
            size: 15,
            weight: '600'
          };

          // Style Legend
          if (!llmChartjs.options.plugins.legend) llmChartjs.options.plugins.legend = {};
          if (!llmChartjs.options.plugins.legend.labels) llmChartjs.options.plugins.legend.labels = {};
          llmChartjs.options.plugins.legend.labels.color = textColor;
          llmChartjs.options.plugins.legend.labels.font = { family: "var(--font-body)" };

          // Style Scales Grid & Ticks
          if (!llmChartjs.options.scales) llmChartjs.options.scales = {};
          for (let key in llmChartjs.options.scales) {
            const scale = llmChartjs.options.scales[key];
            if (!scale.grid) scale.grid = {};
            scale.grid.color = gridColor;

            if (!scale.ticks) scale.ticks = {};
            scale.ticks.color = mutedColor;
            scale.ticks.font = { family: "var(--font-body)" };

            if (scale.title) {
              scale.title.color = textColor;
              scale.title.font = { family: "var(--font-body)", weight: '600' };
            }
          }

          window._llmChart = new Chart(canvas, llmChartjs);
        } catch (err) {
          llmContainer.innerHTML = `<div style="color:var(--danger); padding:16px;">Chart.js render error: ${err}</div>`;
        }
      } else {
        const emptyState = document.getElementById("llm-chart-empty-state");
        emptyState.style.display = "flex";
        llmContainer.style.display = "none";

        const emptyDesc = emptyState.querySelector(".empty-desc");
        if (data.llm_chartjs && data.llm_chartjs.error) {
          emptyDesc.innerHTML = `<span style="color:var(--danger); font-weight:500;">Refusal: ${data.llm_chartjs.error}</span>`;
        } else {
          emptyDesc.textContent = "Direct LLM generated visualization will render here.";
        }
      }

      // Animate score circles
      renderScoreGauge("system", data.system_score || data.score || 0.0, data.system_critique || data.critique || "No critique");
      renderScoreGauge("llm", data.llm_score || 0.0, data.llm_critique || "No critique");

      // Always reset visual critique panels when loading a new report
      ["system", "llm"].forEach(panel => {
        document.getElementById(`vc-panel-${panel}`).style.display = "none";
        document.getElementById(`vc-score-${panel}`).textContent = "\u2013";
        document.getElementById(`vc-critique-${panel}`).textContent = "";
        document.getElementById(`vc-recs-${panel}`).innerHTML = "";
      });
      document.getElementById("btn-visual-critique-global").style.display = "flex";
      document.getElementById("btn-visual-critique-global").disabled = false;
      const globalLabel = document.getElementById("btn-vc-label-global");
      if (globalLabel) globalLabel.textContent = "Run Visual Critique";

      // Auto-capture rendered charts, then load cached critique
      if (data.scenario_id) {
        const scenarioId = data.scenario_id;

        // Load cached visual critique immediately (instant visual)
        fetch(`/api/reports/${scenarioId}/visual-critique`)
          .then(res => res.ok ? res.json() : null)
          .then(critique => {
            if (activeReport && activeReport.scenario_id !== scenarioId) return;
            if (!critique) {
              if (globalLabel) globalLabel.textContent = "Run Visual Critique";
              return;
            }
            if (globalLabel) globalLabel.textContent = "Visual Critique (Cached)";

            ["system", "llm"].forEach(panel => {
              const key = panel === "system" ? "system_visual_critique" : "llm_visual_critique";
              const result = critique[key];
              if (!result) return;
              applyVisualCritiqueResult(panel, result);
            });
          })
          .catch(() => {});

        // Delay DOM-to-PNG screen capture slightly to guarantee rendering has finished
        if (isNewRun) {
          setTimeout(() => {
            captureAndSaveRenderedCharts(scenarioId);
          }, 1500);
        }
      }

      // Update Specs Code Tab
      document.getElementById("system-spec-code").textContent = JSON.stringify(data.system_spec || data.spec, null, 2);
      document.getElementById("llm-spec-code").textContent = JSON.stringify(data.llm_chartjs || {}, null, 2);

      // Update Parameters Tab
      document.getElementById("resolved-code-block").textContent = JSON.stringify({
        resolved_indicators: data.resolved_indicators,
        viz_result: data.viz_result
      }, null, 2);

      // Log Console Rendering
      const logConsole = document.getElementById("log-console");
      logConsole.innerHTML = "";
      if (data.logs && data.logs.length > 0) {
        data.logs.forEach(l => {
          const line = document.createElement("div");
          line.className = "terminal-line";
          if (l.includes("score:") || l.includes("successfully") || l.includes("completed") || l.includes("generated")) {
            line.classList.add("info");
          } else if (l.includes("failed") || l.includes("error")) {
            line.classList.add("err");
          }
          line.textContent = l;
          logConsole.appendChild(line);
        });
      } else {
        logConsole.innerHTML = `<div class="terminal-line">No console log history available for this run.</div>`;
      }
    }

    function renderScoreGauge(prefix, score, critique) {
      document.getElementById(`${prefix}-score-banner`).style.display = "flex";
      document.getElementById(`${prefix}-score-num`).textContent = score.toFixed(1);

      const percent = score / 10;
      const circumference = 188.5; // 2 * pi * 30
      const offset = circumference - (percent * circumference);

      const circle = document.getElementById(`${prefix}-circle-progress`);
      circle.style.strokeDashoffset = offset;

      if (score >= 7.5) {
        circle.style.stroke = "var(--success)";
      } else if (score >= 5.0) {
        circle.style.stroke = "var(--warning)";
      } else {
        circle.style.stroke = "var(--danger)";
      }

      document.getElementById(`${prefix}-critique-text`).textContent = critique;
    }

    // Trigger Single Scenario
    function showHomepage() {
      activeReport = null;
      activeReportFilename = null;

      // Hide active scenario UI elements
      document.getElementById("btn-visual-critique-global").style.display = "none";
      document.getElementById("btn-rerun").style.display = "none";
      document.getElementById("btn-delete").style.display = "none";
      document.getElementById("btn-clear-selection").style.display = "none";

      // Reset query display text
      document.getElementById("query-text").textContent = 'No active query. Click "Surprise Me!" or trigger a past run.';

      // Hide charts and details, show welcome guide
      document.getElementById("viz-grid").style.display = "none";
      document.querySelector(".details-card").style.display = "none";
      document.getElementById("welcome-container").style.display = "block";

      // Deselect active cards in the sidebar
      document.querySelectorAll(".history-card").forEach(card => card.classList.remove("active"));
    }

    async function triggerSurpriseMe() {
      const btn = document.getElementById("btn-surprise");
      const spinner = document.getElementById("btn-spinner");
      const label = document.getElementById("btn-label");

      btn.disabled = true;
      spinner.style.display = "block";
      label.textContent = "Generating...";

      document.getElementById("welcome-container").style.display = "none";
      document.getElementById("viz-grid").style.display = "grid";
      document.querySelector(".details-card").style.display = "block";
      document.getElementById("btn-clear-selection").style.display = "block";

      // Empty states during generate
      document.getElementById("query-text").textContent = "Generating visual query scenario using LLM...";
      document.getElementById("system-chart-container").innerHTML = "";
      document.getElementById("system-chart-empty-state").style.display = "flex";
      document.getElementById("system-score-banner").style.display = "none";
      document.getElementById("system-strategy-badge").style.display = "none";
      document.getElementById("btn-rerun").style.display = "none";
      document.getElementById("btn-delete").style.display = "none";

      // Reset visual critique panels
      document.getElementById("vc-panel-system").style.display = "none";
      document.getElementById("vc-panel-llm").style.display = "none";
      document.getElementById("btn-visual-critique-global").disabled = true;
      document.getElementById("btn-visual-critique-global").style.display = "none";

      document.getElementById("llm-chart-container").innerHTML = "";
      document.getElementById("llm-chart-empty-state").style.display = "flex";
      document.getElementById("llm-score-banner").style.display = "none";

      const logConsole = document.getElementById("log-console");
      logConsole.innerHTML = `<div class="terminal-line info">Triggering Surprise-Me request...</div>`;

      try {
        const res = await fetch("/api/surprise-me", { method: "POST" });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.error || "Unknown server error");
        }
        const data = await res.json();

        // Inject filename for active tracking
        const filename = `${data.scenario_id}.json`;
        activeReportFilename = filename;
        data.filename = filename;

        renderReport(data, true);
        await loadHistory();
      } catch (err) {
        logConsole.innerHTML += `<div class="terminal-line err">Error during execution: ${err.message}</div>`;
        document.getElementById("query-text").textContent = "Generation failed. Review logs in terminal below.";
      } finally {
        btn.disabled = false;
        spinner.style.display = "none";
        label.textContent = "✨ Surprise Me!";
      }
    }

    // Shared helper: populate a visual critique panel with a result object
    function applyVisualCritiqueResult(panel, result) {
      if (!result) return;
      const score = result.score ?? 0;
      const critique = result.critique ?? "No critique available.";
      const recs = result.recommendations ?? [];

      const scoreEl = document.getElementById(`vc-score-${panel}`);
      const critiqueEl = document.getElementById(`vc-critique-${panel}`);
      const recsEl = document.getElementById(`vc-recs-${panel}`);
      const panelEl = document.getElementById(`vc-panel-${panel}`);

      scoreEl.textContent = score.toFixed(1);
      scoreEl.style.color = score >= 7.5 ? "var(--success)" : score >= 5 ? "var(--warning)" : "var(--danger)";
      critiqueEl.textContent = critique;
      recsEl.innerHTML = recs.map(r => `<li>${r}</li>`).join("");
      panelEl.style.display = "flex";
      panelEl.style.flexDirection = "column";

      const btn = document.getElementById(`btn-visual-critique-${panel}`);
      if (btn) {
        const textSpan = btn.querySelector("span:not(.btn-spinner)");
        if (textSpan) textSpan.textContent = "Visual Critique (Cached)";
      }
    }

    // Visual DeepEval critique for both rendered charts
    async function triggerVisualCritiqueGlobal() {
      if (!activeReportFilename) return;
      const scenarioId = activeReportFilename.replace(".json", "");

      const btn = document.getElementById("btn-visual-critique-global");
      const spinner = document.getElementById("vc-spinner-global");
      const label = document.getElementById("btn-vc-label-global");

      btn.disabled = true;
      spinner.style.display = "block";
      label.textContent = "Running Vision Audit...";
      setSidebarDisabled(true);

      const logConsole = document.getElementById("log-console");
      logConsole.innerHTML += `<div class="terminal-line info">Running Visual Critique on both spec renders (GPT-4o Vision)...</div>`;

      try {
        const res = await fetch(`/api/reports/${scenarioId}/visual-critique`, { method: "POST" });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.error || "Visual critique request failed.");
        }
        const data = await res.json();

        if (activeReport && activeReport.scenario_id !== scenarioId) return;

        ["system", "llm"].forEach(panel => {
          const key = panel === "system" ? "system_visual_critique" : "llm_visual_critique";
          const result = data[key];
          if (result) {
            applyVisualCritiqueResult(panel, result);
            const score = result.score ?? 0;
            logConsole.innerHTML += `<div class="terminal-line info">Visual Critique (${panel}): ${score.toFixed(1)}/10</div>`;
          }
        });

        label.textContent = "Visual Critique (Cached)";
      } catch (err) {
        logConsole.innerHTML += `<div class="terminal-line err">Visual Critique error: ${err.message}</div>`;
        label.textContent = "Run Visual Critique";
      } finally {
        btn.disabled = false;
        spinner.style.display = "none";
        setSidebarDisabled(false);
      }
    }

    // Rerun currently active report
    async function triggerRerun() {
      if (!activeReportFilename) return;

      const btn = document.getElementById("btn-rerun");
      const spinner = document.getElementById("btn-rerun-spinner");
      const label = document.getElementById("btn-rerun-label");

      btn.disabled = true;
      spinner.style.display = "block";
      label.textContent = "Rerunning...";
      setSidebarDisabled(true);
      setChartLoading(true);

      const logConsole = document.getElementById("log-console");
      logConsole.innerHTML = `<div class="terminal-line info">Triggering rerun for report: ${activeReportFilename}...</div>`;

      try {
        const res = await fetch(`/api/reports/${activeReportFilename}/rerun`, { method: "POST" });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.error || "Unknown server error");
        }
        const data = await res.json();

        // Reload history & render new report data
        await loadHistory();
        await loadReport(activeReportFilename);
      } catch (err) {
        logConsole.innerHTML += `<div class="terminal-line err">Error during rerun: ${err.message}</div>`;
        setChartLoading(false);
      } finally {
        btn.disabled = false;
        spinner.style.display = "none";
        label.textContent = "🔄 Rerun this run";
        setSidebarDisabled(false);
      }
    }

    // Delete currently active report and its artifacts
    async function triggerDelete() {
      if (!activeReportFilename) return;

      const scenarioId = activeReport ? activeReport.scenario_id : null;
      if (!scenarioId) return;

      if (!confirm("Are you sure you want to delete this run and all its related artifacts? This action cannot be undone.")) {
        return;
      }

      const btn = document.getElementById("btn-delete");
      const spinner = document.getElementById("btn-delete-spinner");
      const label = document.getElementById("btn-delete-label");

      btn.disabled = true;
      spinner.style.display = "block";
      label.textContent = "Deleting...";

      const logConsole = document.getElementById("log-console");
      logConsole.innerHTML = `<div class="terminal-line info">Deleting report: ${activeReportFilename}...</div>`;

      try {
        const res = await fetch(`/api/reports/${scenarioId}/delete`, { method: "POST" });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.error || "Unknown server error");
        }
        const data = await res.json();

        logConsole.innerHTML += `<div class="terminal-line success">Successfully deleted ${data.deleted.length} files.</div>`;

        // Return to homepage and reload history
        showHomepage();
        await loadHistory();
      } catch (err) {
        logConsole.innerHTML += `<div class="terminal-line err">Error during deletion: ${err.message}</div>`;
      } finally {
        btn.disabled = false;
        spinner.style.display = "none";
        label.textContent = "🗑️ Delete this run";
      }
    }

    // Trigger Batch Run (20 sets)
    async function triggerBatchSurprise() {
      const btn = document.getElementById("btn-batch");
      const spinner = document.getElementById("btn-batch-spinner");
      const label = document.getElementById("btn-batch-label");

      btn.disabled = true;
      spinner.style.display = "block";
      label.textContent = "Launching Batch...";

      try {
        const res = await fetch("/api/batch-surprise", { method: "POST" });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.error || "Unknown server error");
        }

        // Start polling for batch status
        document.getElementById("batch-progress-bar").style.display = "flex";
        pollBatchStatus();
        if (!batchCheckInterval) {
          batchCheckInterval = setInterval(pollBatchStatus, 3000);
        }
      } catch (err) {
        alert("Failed to start batch: " + err.message);
        btn.disabled = false;
        spinner.style.display = "none";
        label.textContent = "📦 Batch Run (50 sets)";
      }
    }

    async function pollBatchStatus() {
      try {
        const res = await fetch("/api/batch-status");
        const status = await res.json();

        if (status.running) {
          document.getElementById("batch-progress-bar").style.display = "flex";
          document.getElementById("batch-progress-text").textContent = `${status.current}/${status.total} sets completed`;

          document.getElementById("btn-batch").disabled = true;
          document.getElementById("btn-batch-spinner").style.display = "block";
          document.getElementById("btn-batch-label").textContent = "Batch Running...";
        } else {
          // Stopped running
          document.getElementById("batch-progress-bar").style.display = "none";
          document.getElementById("btn-batch").disabled = false;
          document.getElementById("btn-batch-spinner").style.display = "none";
          document.getElementById("btn-batch-label").textContent = "📦 Batch Run (50 sets)";

          if (batchCheckInterval) {
            clearInterval(batchCheckInterval);
            batchCheckInterval = null;
          }
          await loadHistory();
        }
      } catch (err) {
        console.error("Error polling batch status:", err);
      }
    }

    async function cancelBatchSurprise() {
      if (!confirm("Are you sure you want to cancel the active batch run?")) return;
      try {
        const res = await fetch("/api/batch-cancel", { method: "POST" });
        const data = await res.json();
        alert(data.status);
        await pollBatchStatus();
      } catch (err) {
        alert("Failed to cancel batch: " + err.message);
      }
    }

    // Switch Tabs helper
    function switchTab(evt, tabId) {
      document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
      document.querySelectorAll(".tab-body").forEach(body => body.classList.remove("active"));

      evt.currentTarget.classList.add("active");
      document.getElementById(tabId).classList.add("active");
    }

    // Sidebar Tabs switching helper
    function switchSidebarTab(tab) {
      const tabHistory = document.getElementById('sidebar-tab-history');
      const tabBuilder = document.getElementById('sidebar-tab-builder');
      const contentHistory = document.getElementById('history-tab-content');
      const contentBuilder = document.getElementById('builder-tab-content');

      if (tab === 'history') {
        tabHistory.style.background = 'var(--surface2)';
        tabHistory.style.borderBottomColor = 'var(--accent)';
        tabHistory.style.fontWeight = '600';
        tabHistory.style.color = 'var(--text)';

        tabBuilder.style.background = 'var(--surface1)';
        tabBuilder.style.borderBottomColor = 'transparent';
        tabBuilder.style.fontWeight = '500';
        tabBuilder.style.color = 'var(--text-muted)';

        contentHistory.style.display = 'block';
        contentBuilder.style.display = 'none';
      } else {
        tabBuilder.style.background = 'var(--surface2)';
        tabBuilder.style.borderBottomColor = 'var(--accent)';
        tabBuilder.style.fontWeight = '600';
        tabBuilder.style.color = 'var(--text)';

        tabHistory.style.background = 'var(--surface1)';
        tabHistory.style.borderBottomColor = 'transparent';
        tabHistory.style.fontWeight = '500';
        tabHistory.style.color = 'var(--text-muted)';

        contentHistory.style.display = 'none';
        contentBuilder.style.display = 'block';
        updateCountryBadges();
      }
    }

    let selectedIndicator = null;
    let currentDisaggregation = null;
    const allGroups = [
      { code: 'EAS', name: 'East Asia & Pacific' },
      { code: 'ECS', name: 'Europe & Central Asia' },
      { code: 'LCN', name: 'Latin America & Caribbean' },
      { code: 'MEA', name: 'Middle East & North Africa' },
      { code: 'NAC', name: 'North America' },
      { code: 'SAS', name: 'South Asia' },
      { code: 'SSF', name: 'Sub-Saharan Africa' },
      { code: 'LIC', name: 'Low income' },
      { code: 'LMC', name: 'Lower middle income' },
      { code: 'UMC', name: 'Upper middle income' },
      { code: 'HIC', name: 'High income' }
    ];
    let selectedGroupCountries = [];

    window.onGroupSelected = async function() {
      const select = document.getElementById('builder-group-select');
      const configDiv = document.getElementById('builder-group-config');
      if (!select || !configDiv) return;
      const code = select.value;
      if (!code) {
        configDiv.style.display = 'none';
        return;
      }

      const group = allGroups.find(g => g.code === code);
      if (!group) return;

      document.getElementById('builder-selected-group-name').innerText = `${group.name} (${group.code})`;
      document.getElementById('builder-selected-group-code-direct').innerText = group.code;
      document.getElementById('builder-selected-group-count').innerText = "...";
      configDiv.style.display = 'flex';

      try {
        const res = await fetch(`/api/groups/${code}/expand`);
        selectedGroupCountries = await res.json();
        document.getElementById('builder-selected-group-count').innerText = selectedGroupCountries.length;
      } catch (err) {
        console.error("Failed to load group details:", err);
        document.getElementById('builder-selected-group-count').innerText = "error";
      }
    };

    window.addGroupToBuilder = function() {
      const select = document.getElementById('builder-group-select');
      const configDiv = document.getElementById('builder-group-config');
      if (!select || !configDiv) return;
      const code = select.value;
      if (!code) return;

      const mode = document.querySelector('input[name="builder-group-mode"]:checked').value;
      if (mode === 'direct') {
        addCountryCode(code);
      } else {
        if (Array.isArray(selectedGroupCountries)) {
          selectedGroupCountries.forEach(c => addCountryCode(c));
        }
      }

      select.value = '';
      configDiv.style.display = 'none';
    };

    // Assisted country selection helpers
    function updateCountryBadges() {
      const input = document.getElementById('builder-countries');
      const container = document.getElementById('builder-selected-countries-badges');
      if (!input || !container) return;
      container.innerHTML = '';

      const codes = input.value.split(';').map(c => c.trim()).filter(Boolean);
      codes.forEach(code => {
        const badge = document.createElement('div');
        badge.style.display = 'inline-flex';
        badge.style.alignItems = 'center';
        badge.style.gap = '6px';
        badge.style.background = 'rgba(255, 255, 255, 0.05)';
        badge.style.border = '1px solid var(--border)';
        badge.style.padding = '4px 8px';
        badge.style.borderRadius = '4px';
        badge.style.fontSize = '11px';
        badge.style.color = 'var(--text)';
        badge.innerHTML = `
          <span style="font-weight:600; font-family:var(--font-mono);">${code}</span>
          <span onclick="removeCountryCode('${code}')" style="cursor:pointer; color:var(--text-muted); font-weight:700; transition:color 0.2s;" onmouseover="this.style.color='var(--danger)'" onmouseout="this.style.color='var(--text-muted)'">×</span>
        `;
        container.appendChild(badge);
      });
    }

    window.removeCountryCode = function(code) {
      const input = document.getElementById('builder-countries');
      if (!input) return;
      const codes = input.value.split(';').map(c => c.trim()).filter(Boolean);
      const index = codes.indexOf(code);
      if (index !== -1) {
        codes.splice(index, 1);
        input.value = codes.join(';');
        updateCountryBadges();
      }
    };

    function addCountryCode(code) {
      const input = document.getElementById('builder-countries');
      if (!input) return;
      const codes = input.value.split(';').map(c => c.trim()).filter(Boolean);
      if (!codes.includes(code)) {
        codes.push(code);
        input.value = codes.join(';');
        updateCountryBadges();
      }
      document.getElementById('builder-country-search').value = '';
      document.getElementById('builder-country-results').style.display = 'none';
    }

    async function searchBuilderCountries() {
      const query = document.getElementById('builder-country-search').value.trim();
      if (!query) return;

      const resultsDiv = document.getElementById('builder-country-results');
      resultsDiv.innerHTML = '<div style="padding: 8px; color: var(--text-muted); font-size:11px;">Searching countries...</div>';
      resultsDiv.style.display = 'block';

      try {
        const res = await fetch(`/api/search-countries?query=${encodeURIComponent(query)}`);
        const data = await res.json();
        if (!data.length) {
          resultsDiv.innerHTML = '<div style="padding: 8px; color: var(--text-muted); font-size:11px;">No countries found.</div>';
          return;
        }

        resultsDiv.innerHTML = '';
        data.forEach(item => {
          const card = document.createElement('div');
          card.style.padding = '6px 10px';
          card.style.borderBottom = '1px solid var(--border)';
          card.style.cursor = 'pointer';
          card.style.fontSize = '11px';
          card.style.color = 'var(--text)';
          card.innerHTML = `
            <span style="font-weight:600;">${item.name}</span>
            <span style="float:right; font-family:monospace; color:var(--accent); font-weight:600;">${item.id}</span>
          `;
          card.onmouseover = () => card.style.background = 'rgba(255,255,255,0.05)';
          card.onmouseout = () => card.style.background = 'transparent';
          card.onclick = () => addCountryCode(item.id);
          resultsDiv.appendChild(card);
        });
      } catch (err) {
        resultsDiv.innerHTML = `<div style="padding: 8px; color: var(--danger); font-size:11px;">Error: ${err.message}</div>`;
      }
    }

    // Call updateCountryBadges on load
    document.addEventListener("DOMContentLoaded", () => {
      setTimeout(updateCountryBadges, 100);
    });

    async function searchBuilderIndicators() {
      const query = document.getElementById('builder-search-input').value.trim();
      if (!query) return;

      const resultsDiv = document.getElementById('builder-search-results');
      resultsDiv.innerHTML = '<div style="padding: 10px; color: var(--text-muted); font-size:12px;">Searching...</div>';
      resultsDiv.style.display = 'block';

      try {
        const res = await fetch(`/api/search-indicators?query=${encodeURIComponent(query)}`);
        const data = await res.json();
        if (data.error) {
          resultsDiv.innerHTML = `<div style="padding: 10px; color: var(--danger); font-size:12px;">Error: ${data.error}</div>`;
          return;
        }
        if (!data.length) {
          resultsDiv.innerHTML = '<div style="padding: 10px; color: var(--text-muted); font-size:12px;">No indicators found.</div>';
          return;
        }

        resultsDiv.innerHTML = '';
        data.forEach(ind => {
          const card = document.createElement('div');
          card.style.padding = '8px 12px';
          card.style.borderBottom = '1px solid var(--border)';
          card.style.cursor = 'pointer';
          card.style.fontSize = '12px';
          card.style.transition = 'all 0.2s';
          card.innerHTML = `
            <div style="font-weight: 600; color: var(--text);">${ind.name}</div>
            <div style="font-size: 10px; color: var(--text-muted); font-family: monospace; margin-top:2px;">${ind.database_id} | ${ind.indicator_id}</div>
          `;
          card.onmouseover = () => card.style.background = 'rgba(255,255,255,0.05)';
          card.onmouseout = () => card.style.background = 'transparent';
          card.onclick = () => selectIndicatorForBuilder(ind);
          resultsDiv.appendChild(card);
        });
      } catch (err) {
        resultsDiv.innerHTML = `<div style="padding: 10px; color: var(--danger); font-size:12px;">Search failed: ${err}</div>`;
      }
    }

    async function selectIndicatorForBuilder(ind) {
      selectedIndicator = ind;
      document.getElementById('builder-search-results').style.display = 'none';
      document.getElementById('builder-search-input').value = ind.name;

      // Show selected indicator card details
      document.getElementById('selected-indicator-db').innerText = ind.database_id;
      document.getElementById('selected-indicator-name').innerText = ind.name;
      document.getElementById('selected-indicator-id').innerText = ind.indicator_id;
      document.getElementById('builder-configurator').style.display = 'flex';

      // Fetch disaggregation details
      const disaggList = document.getElementById('builder-disaggregations-list');
      disaggList.innerHTML = '<div style="color: var(--text-muted); font-size:12px;">Loading options...</div>';

      try {
        const res = await fetch(`/api/indicator-disaggregation?database_id=${ind.database_id}&indicator_id=${ind.indicator_id}`);
        const data = await res.json();
        currentDisaggregation = data;

        // 1. Populate Years
        const startSelect = document.getElementById('builder-start-year');
        const endSelect = document.getElementById('builder-end-year');
        startSelect.innerHTML = '';
        endSelect.innerHTML = '';

        const timeDim = data.dimensions ? data.dimensions.find(d => d.field_name === 'TIME_PERIOD') : null;
        let years = [];
        if (timeDim && Array.isArray(timeDim.field_value)) {
          years = timeDim.field_value.map(y => parseInt(y)).sort((a,b) => a - b);
        } else {
          // Fallback years
          const currentYear = new Date().getFullYear();
          for (let y = currentYear - 15; y <= currentYear; y++) {
            years.push(y);
          }
        }

        years.forEach(year => {
          const optStart = document.createElement('option');
          optStart.value = year;
          optStart.innerText = year;
          startSelect.appendChild(optStart);

          const optEnd = document.createElement('option');
          optEnd.value = year;
          optEnd.innerText = year;
          endSelect.appendChild(optEnd);
        });

        // Default to last 10 years or max range
        if (years.length > 0) {
          startSelect.value = years[0];
          endSelect.value = years[years.length - 1];
        }

        // 2. Populate Disaggregation Dimensions (excluding TIME_PERIOD and REF_AREA)
        disaggList.innerHTML = '';
        const otherDims = data.dimensions ? data.dimensions.filter(d => d.field_name !== 'TIME_PERIOD' && d.field_name !== 'REF_AREA' && d.field_name.toUpperCase() !== 'REGION') : [];

        if (!otherDims.length) {
          disaggList.innerHTML = '<div style="color: var(--text-muted); font-size:12px;">No breakdowns available (National values only).</div>';
        } else {
          otherDims.forEach(dim => {
            const dimGroup = document.createElement('div');
            dimGroup.style.display = 'flex';
            dimGroup.style.flexDirection = 'column';
            dimGroup.style.gap = '4px';
            dimGroup.style.borderBottom = '1px solid var(--border)';
            dimGroup.style.paddingBottom = '8px';
            dimGroup.style.marginBottom = '4px';

            dimGroup.innerHTML = `
              <div style="font-size:11px; font-weight:600; color:var(--text);">${dim.field_name}</div>
              <div style="display:flex; flex-wrap:wrap; gap:8px;" id="dim-values-${dim.field_name}"></div>
            `;
            disaggList.appendChild(dimGroup);

            const valuesContainer = document.getElementById(`dim-values-${dim.field_name}`);

            // Add "All / Compare" radio option first
            const allLabel = document.createElement('label');
            allLabel.style.display = 'flex';
            allLabel.style.alignItems = 'center';
            allLabel.style.gap = '4px';
            allLabel.style.fontSize = '12px';
            allLabel.style.cursor = 'pointer';
            allLabel.style.color = 'var(--text)';
            allLabel.innerHTML = `
              <input type="radio" name="dim-filter-${dim.field_name}" value="__ALL__" checked style="cursor:pointer;">
              <span style="font-weight: 500;">All / Compare</span>
            `;
            valuesContainer.appendChild(allLabel);

            dim.field_value.forEach(val => {
              const label = document.createElement('label');
              label.style.display = 'flex';
              label.style.alignItems = 'center';
              label.style.gap = '4px';
              label.style.fontSize = '12px';
              label.style.cursor = 'pointer';
              label.style.color = 'var(--text-muted)';

              label.innerHTML = `
                <input type="radio" name="dim-filter-${dim.field_name}" value="${val}" style="cursor:pointer;">
                <span>${val}</span>
              `;
              valuesContainer.appendChild(label);
            });
          });
        }

      } catch (err) {
        disaggList.innerHTML = `<div style="color: var(--danger); font-size:12px;">Failed to load dimensions: ${err}</div>`;
      }
    }

    async function generateCustomBuilderChart() {
      if (!selectedIndicator) return;

      const generateBtn = document.getElementById('btn-builder-generate');
      const oldText = generateBtn.innerText;
      generateBtn.disabled = true;
      generateBtn.innerText = 'Generating Visuals...';
      setSidebarDisabled(true);
      setChartLoading(true);

      // Build filters
      const disaggregation_filters = {};
      const otherDims = currentDisaggregation && currentDisaggregation.dimensions
        ? currentDisaggregation.dimensions.filter(d => d.field_name !== 'TIME_PERIOD' && d.field_name !== 'REF_AREA' && d.field_name.toUpperCase() !== 'REGION')
        : [];

      otherDims.forEach(dim => {
        const radioName = `dim-filter-${dim.field_name}`;
        const selectedRadio = document.querySelector(`input[name="${radioName}"]:checked`);
        if (selectedRadio && selectedRadio.value !== '__ALL__') {
          disaggregation_filters[dim.field_name] = selectedRadio.value;
        }
      });

      const body = {
        database_id: selectedIndicator.database_id,
        indicator_id: selectedIndicator.indicator_id,
        indicator_name: selectedIndicator.name,
        country_code: document.getElementById('builder-countries').value.trim(),
        start_year: parseInt(document.getElementById('builder-start-year').value),
        end_year: parseInt(document.getElementById('builder-end-year').value),
        chart_type: document.getElementById('builder-chart-type').value || null,
        disaggregation_filters: disaggregation_filters
      };

      try {
        const res = await fetch('/api/custom-chart', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });
        const data = await res.json();
        if (data.error) {
          alert(`Generation failed: ${data.error}`);
          setChartLoading(false);
          return;
        }

        // Refresh history list and switch back to history tab
        await loadHistory();
        switchSidebarTab('history');

        // Select the newly created custom run
        selectScenario(data.scenario_id, true);

      } catch (err) {
        alert(`Request failed: ${err}`);
        setChartLoading(false);
      } finally {
        generateBtn.disabled = false;
        generateBtn.innerText = oldText;
        setSidebarDisabled(false);
      }
    }

    async function captureAndSaveRenderedCharts(scenarioId) {
      const vegaCanvas = document.querySelector("#system-chart-container canvas");
      const chartjsCanvas = document.getElementById("llm-chartjs-canvas");

      const sysBase64 = vegaCanvas ? vegaCanvas.toDataURL("image/png") : "";
      const llmBase64 = chartjsCanvas ? chartjsCanvas.toDataURL("image/png") : "";

      if (!sysBase64 && !llmBase64) return;

      try {
        await fetch("/api/save-rendered-images", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            scenario_id: scenarioId,
            system_png_base64: sysBase64,
            llm_png_base64: llmBase64
          })
        });
        console.log("Rendered charts saved to backend successfully.");
      } catch (err) {
        console.error("Failed to save rendered charts:", err);
      }
    }

    // Init
    loadHistory();
    pollBatchStatus();
    setInterval(pollBatchStatus, 5000);
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(content=HTML_CONTENT)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run interactive chart explorer server.")
    parser.add_argument("--port", type=int, default=8090, help="Port to run the dashboard on.")
    args = parser.parse_args()

    print(f"Launching Data360-MCP Visualization Engine Explorer at: http://localhost:{args.port}")
    uvicorn.run("evals.interactive_explorer:app", host="0.0.0.0", port=args.port, reload=False, loop="asyncio")
