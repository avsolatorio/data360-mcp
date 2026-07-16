"""Comparison script for Scenario Q01.

Generates the Vega-Lite specs for both our Implemented Engine and the LLM recommendation,
and compiles them into a single comparison HTML page.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data360.visualization import get_multi_indicator_viz_spec


async def main():
    args = {
        "indicator_ids": [
            {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_TLF_CACT_FE_ZS"},
            {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_TLF_CACT_MA_ZS"}
        ],
        "country_code": "IND", "start_year": 2010, "end_year": 2022
    }

    print("Fetching visualization engine spec for Scenario Q01...")
    res = await get_multi_indicator_viz_spec(**args)
    url = res.get("url")
    if not url:
        print("Error: No spec URL returned.")
        sys.exit(1)

    filename = url.split("/")[-1]
    filepath = Path(__file__).parent.parent / "static" / "viz_specs" / filename

    with open(filepath) as f:
        engine_spec = json.load(f)

    # Clone and modify the spec to reflect the LLM's recommendation
    llm_spec = json.loads(json.dumps(engine_spec))

    # LLM recommendation: zero-baseline on Y-axis (and ideally domain [0, 100])
    # LLM recommendation: custom colors (e.g. pink for female, blue for male)
    if "layer" in llm_spec:
        llm_spec["layer"][0]["encoding"]["y"]["scale"] = {"zero": True, "domain": [0, 100]}
        llm_spec["layer"][0]["encoding"]["color"]["scale"] = {
            "domain": ["Female", "Male"],
            "range": ["#E91E63", "#2196F3"] # Pink and Blue
        }
    else:
        llm_spec["encoding"]["y"]["scale"] = {"zero": True, "domain": [0, 100]}
        llm_spec["encoding"]["color"]["scale"] = {
            "domain": ["Female", "Male"],
            "range": ["#E91E63", "#2196F3"] # Pink and Blue
        }

    # Generate the comparison HTML
    out_dir = Path(__file__).parent / "reports"
    out_dir.mkdir(exist_ok=True)
    html_file = out_dir / "q01_comparison.html"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Scenario Q01: Visual Engine vs. LLM Specialist Recommendation</title>
    <!-- Vega & Vega-Lite Libraries -->
    <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
    <style>
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #0F172A;
            color: #E2E8F0;
            margin: 0;
            padding: 40px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        h1 {{
            color: #FFFFFF;
            font-size: 2.2rem;
            margin-bottom: 8px;
            text-align: center;
        }}
        .question {{
            color: #94A3B8;
            font-size: 1.2rem;
            margin-bottom: 40px;
            text-align: center;
            max-width: 800px;
        }}
        .comparison-container {{
            display: flex;
            flex-wrap: wrap;
            gap: 40px;
            justify-content: center;
            width: 100%;
            max-width: 1500px;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            padding: 24px;
            width: 700px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
            display: flex;
            flex-direction: column;
        }}
        .card h2 {{
            margin-top: 0;
            font-size: 1.5rem;
            color: #38BDF8;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding-bottom: 12px;
            margin-bottom: 20px;
        }}
        .chart {{
            background: #FFFFFF;
            border-radius: 8px;
            padding: 16px;
            display: flex;
            justify-content: center;
            align-items: center;
        }}
        .rationale {{
            margin-top: 20px;
            font-size: 0.95rem;
            line-height: 1.6;
            color: #CBD5E1;
        }}
    </style>
</head>
<body>
    <h1>Visual Comparison: Scenario Q01</h1>
    <div class="question">"Show me female versus male labor force participation rates (% of population ages 15+) in India from 2010 to 2022."</div>

    <div class="comparison-container">
        <!-- Engine Implementation -->
        <div class="card">
            <h2>1. Implemented Rule-Based Engine</h2>
            <div id="vis-engine" class="chart"></div>
            <div class="rationale">
                <strong>Strategy:</strong> <code>temporal_multi_indicator</code> (Layered Lines)<br>
                <strong>Y-Axis Scale:</strong> Zoomed-in (<code>zero: false</code>)<br>
                <strong>Design Choice:</strong> Zooming in highlights the year-over-year fluctuations and volatility within each gender group (e.g. the recovery post-2020), but hides the absolute gap context relative to 0%-100%.
            </div>
        </div>

        <!-- LLM Specialist Recommendation -->
        <div class="card">
            <h2>2. LLM Specialist Recommendation</h2>
            <div id="vis-llm" class="chart"></div>
            <div class="rationale">
                <strong>Strategy:</strong> Zero-Baseline and Absolute Scale<br>
                <strong>Y-Axis Scale:</strong> Explicitly 0% to 100% (<code>zero: true</code>)<br>
                <strong>Design Choice:</strong> Setting the baseline to 0% and domain to 100% preserves the proportional context, showing the massive absolute gap between male and female participation rates, although year-over-year changes appear flatter.
            </div>
        </div>
    </div>

    <script>
        const engineSpec = {json.dumps(engine_spec)};
        const llmSpec = {json.dumps(llm_spec)};

        // Render charts
        vegaEmbed('#vis-engine', engineSpec, {{actions: false}});
        vegaEmbed('#vis-vis-engine', engineSpec, {{actions: false}}); // Fallback if name mismatches
        vegaEmbed('#vis-llm', llmSpec, {{actions: false}});
    </script>
</body>
</html>
"""

    with open(html_file, "w") as f:
        f.write(html_content)

    print(f"Comparison HTML generated at: {html_file}")


if __name__ == "__main__":
    asyncio.run(main())
