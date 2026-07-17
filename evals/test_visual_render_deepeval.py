import os
import json
import base64
import pytest
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# Setup directories and load env files
_HERE = Path(__file__).parent
_REPO = _HERE.parent
REPORTS_DIR = _HERE / "reports"

# Load standard .env and .env.evals files
for env_name in (".env", ".env.evals"):
    env_path = _REPO / env_name
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)

def encode_image(image_path: Path) -> str:
    """Encode local image to base64 string."""
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")

def run_multimodal_judge(query: str, image_path: Path, api_key: str) -> dict:
    """Send image screenshot to GPT-4o Vision to evaluate visual rendering quality."""
    client = OpenAI(api_key=api_key)
    base64_image = encode_image(image_path)

    prompt = f"""
    You are an expert data visualization design auditor. Evaluate the actual rendered chart screenshot based on the user query.

    User Query Context: "{query}"

    Audit Guidelines:
    1. VISUAL REPRESENTATION (0-4 points): Does the chart type fit the data layout? (e.g. line for trends, bar for comparison). Do the data lines/bars flatline at the zero axis or compress visual variation?
    2. TYPOGRAPHY & DESIGN (0-4 points): Are titles, subtitles, axis labels, and legends readable? Are there any overlapping text labels or clipping issues?
    3. THEME CONFORMANCE (0-2 points): Does it conform to clean, professional styling (approved color palette, subtle gridlines, clean layout bounds)?

    Return a single JSON object containing:
    - "score": A float from 0.0 to 10.0 (sum of the audit points).
    - "critique": A detailed critique paragraph justifying the score based on visual evidence in the screenshot.
    - "recommendations": A list of specific design improvements.
    """

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
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        temperature=0.2
    )

    return json.loads(response.choices[0].message.content)

def get_reports_with_images() -> list[dict]:
    """Scan REPORTS_DIR for scenarios that have rendered screenshots."""
    scenarios = []
    if not REPORTS_DIR.exists():
        return []

    for p in REPORTS_DIR.glob("*.json"):
        # Ignore score logs and existing visual critiques
        if p.name.startswith("viz_score_") or p.name.startswith("visual_critique_"):
            continue
        try:
            data = json.loads(p.read_text())
            scenario_id = data.get("scenario_id")
            if not scenario_id:
                continue

            sys_img = REPORTS_DIR / f"render_{scenario_id}_system.png"
            llm_img = REPORTS_DIR / f"render_{scenario_id}_llm.png"

            # Add to list if at least one screenshot exists
            if sys_img.exists() or llm_img.exists():
                scenarios.append({
                    "filepath": p,
                    "scenario_id": scenario_id,
                    "question": data.get("question", "Plot custom chart"),
                    "system_image": sys_img if sys_img.exists() else None,
                    "llm_image": llm_img if llm_img.exists() else None
                })
        except Exception:
            pass
    return scenarios

# Load reports with screenshots to parameterize tests
REPORTS_TO_TEST = get_reports_with_images()

@pytest.mark.skipif(not REPORTS_TO_TEST, reason="No report screenshots found in evals/reports/ to audit.")
@pytest.mark.parametrize("report", REPORTS_TO_TEST, ids=lambda r: r["scenario_id"])
def test_rendered_chart_visuals(report):
    """Multimodal test suite to audit rendered chart screenshots using GPT-4o Vision."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.fail("OPENAI_API_KEY environment variable is not set.")

    scenario_id = report["scenario_id"]
    query = report["question"]

    critique_results = {
        "scenario_id": scenario_id,
        "query": query,
        "system_visual_critique": None,
        "llm_visual_critique": None
    }

    # 1. Audit System Spec Render
    if report["system_image"]:
        print(f"\n[Visual Audit] Auditing System spec render for: {scenario_id}")
        try:
            res = run_multimodal_judge(query, report["system_image"], api_key)
            critique_results["system_visual_critique"] = res
            print(f"System spec score: {res.get('score')}/10. Critique: {res.get('critique')}")
        except Exception as e:
            print(f"System visual audit failed: {e}")

    # 2. Audit LLM Spec Render
    if report["llm_image"]:
        print(f"\n[Visual Audit] Auditing LLM spec render for: {scenario_id}")
        try:
            res = run_multimodal_judge(query, report["llm_image"], api_key)
            critique_results["llm_visual_critique"] = res
            print(f"LLM spec score: {res.get('score')}/10. Critique: {res.get('critique')}")
        except Exception as e:
            print(f"LLM visual audit failed: {e}")

    # Save visual critique report
    critique_file = REPORTS_DIR / f"visual_critique_{scenario_id}.json"
    critique_file.write_text(json.dumps(critique_results, indent=2))

    # Assert quality threshold (at least 7.5/10)
    failed = False
    fail_reasons = []

    if critique_results["system_visual_critique"]:
        sys_score = critique_results["system_visual_critique"]["score"]
        if sys_score < 7.5:
            failed = True
            fail_reasons.append(f"System chart scored low ({sys_score}/10): {critique_results['system_visual_critique']['critique']}")

    if critique_results["llm_visual_critique"]:
        llm_score = critique_results["llm_visual_critique"]["score"]
        if llm_score < 7.5:
            failed = True
            fail_reasons.append(f"LLM chart scored low ({llm_score}/10): {critique_results['llm_visual_critique']['critique']}")

    if failed:
        pytest.fail("\n".join(fail_reasons))
