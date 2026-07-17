"""LLM Chart Visualization Explorer.

Queries an LLM Chart Visualization Specialist to generate open-ended charting
recommendations and rationales based solely on computed dataset data_profile specifications.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from openai import OpenAI

from data360.visualization import get_viz_spec, get_multi_indicator_viz_spec
from evals.test_20_questions import QUESTIONS

# Load env variables
_repo = Path(__file__).parent.parent
load_dotenv(_repo / ".env.evals", override=False)
load_dotenv(_repo / ".env", override=False)

SYSTEM_PROMPT = (
    "You are an expert Data Visualization Specialist.\n"
    "Given a computed data profile (describing the structure, scale compatibility, breakdowns, and coverage of a dataset) and the user's original query, provide a detailed, professional recommendation on how to visualize this data.\n\n"
    "Your analysis should discuss:\n"
    "1. The recommended chart layout (e.g. single panel, layered, small multiples, grid).\n"
    "2. The suggested visual encodings (what variables map to X, Y, Color, Facet, etc.).\n"
    "3. The ideal mark type (lines, bars, areas, points, etc.) and visual treatments (e.g. baseline at zero, sorting, log scales).\n"
    "4. The reasoning behind these choices based on cardinality, scale differences, and temporal properties in the profile.\n\n"
    "Output your recommendation as a clean, structured Markdown response. Do not refer to any pre-defined strategy names or constraints of any specific system. Focus purely on general data visualization best practices."
)


async def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in .env.evals or environment.")
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    results = []

    print("=" * 80)
    print("Starting LLM Visualization Exploration Tool")
    print(f"Total scenarios to run: {len(QUESTIONS)}")
    print("=" * 80)

    for q in QUESTIONS:
        sid = q["id"]
        question = q["question"]
        viz_call = q["viz_call"]
        tool = viz_call["tool"]
        args = viz_call["args"]

        print(f"Profiling dataset and running LLM review for {sid}...")

        try:
            if tool == "data360_get_viz_spec":
                res = await get_viz_spec(**args)
            elif tool == "data360_get_multi_indicator_viz_spec":
                res = await get_multi_indicator_viz_spec(**args)
            else:
                continue

            if res.get("error"):
                print(f"  Error generating viz spec: {res['error']}")
                results.append({
                    "id": sid,
                    "question": question,
                    "engine_strategy": "ERROR",
                    "data_profile": {},
                    "llm_recommendation": f"Error: {res['error']}"
                })
                continue

            # Extract generated strategy & data profile
            engine_strategy = res.get("strategy")
            data_profile = res.get("data_profile") or {}

            # Invoke LLM specialist for open-ended discussion
            prompt = (
                f"Data Profile:\n{json.dumps(data_profile, indent=2)}\n\n"
                f"User Question: {question}"
            )
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ]
            )

            llm_recommendation = response.choices[0].message.content or ""

            results.append({
                "id": sid,
                "question": question,
                "engine_strategy": engine_strategy,
                "data_profile": data_profile,
                "llm_recommendation": llm_recommendation.strip()
            })

            print("  Completed successfully.")
            print("-" * 50)

        except Exception as e:
            print(f"  Execution failed: {e}")
            results.append({
                "id": sid,
                "question": question,
                "engine_strategy": "EXCEPTION",
                "data_profile": {},
                "llm_recommendation": f"Exception occurred during execution: {e}"
            })

    # Compile exploration dossier report
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_file = reports_dir / "llm_viz_exploration.md"

    md_lines = [
        "# Data360 Chart Visualization Exploration Dossier",
        "",
        "This dossier contains expert visualization recommendations from GPT-4o acting as a Chart Visualization Specialist. Each recommendation is based solely on the dataset's computed `data_profile` and user query, independent of any pre-defined platform rules.",
        "",
        "---",
        ""
    ]

    for r in results:
        md_lines.extend([
            f"## Scenario {r['id']}: {r['question']}",
            "",
            "### Dataset Metadata Summary",
            ""
        ])

        dp = r["data_profile"]
        if dp:
            dp_breakdowns = dp.get('breakdowns', {})
            bd_str = "None"
            if isinstance(dp_breakdowns, dict):
                bd_names = [b.get('meaning', k) for k, b in dp_breakdowns.items()]
                if bd_names:
                    bd_str = ", ".join(bd_names)
            md_lines.extend([
                f"- **Indicators**: {len(dp.get('indicators', []))}",
                f"- **Unique Economies**: {dp.get('structure', {}).get('country_count', 0)}",
                f"- **Time Span**: {dp.get('structure', {}).get('year_range', [])} ({dp.get('structure', {}).get('year_count', 0)} years)",
                f"- **Breakdowns**: {bd_str}",
                "",
                "### Full Computed Data Profile",
                "",
                "```json",
                f"{json.dumps(dp, indent=2)}",
                "```",
                ""
            ])
        else:
            md_lines.append("- *No metadata profile available due to error.*\n")

        # Reference what our rule-based engine did
        md_lines.extend([
            f"- **Implemented Engine Choice**: `{r['engine_strategy']}`",
            "",
            "### LLM Specialist Recommendation & Reasoning",
            "",
            r["llm_recommendation"],
            "",
            "---",
            ""
        ])

    with open(report_file, "w") as f:
        f.write("\n".join(md_lines))

    print(f"Exploration complete. Dossier saved to: {report_file}")


if __name__ == "__main__":
    asyncio.run(main())
