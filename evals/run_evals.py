"""
Data360 MCP — Visualization Engine CLI Runner
==============================================

Run evaluation scenarios from the terminal. Results are saved as JSON reports
to evals/reports/ and can be viewed in the dashboard at http://localhost:8099.

Usage
-----
    # Run all scenarios
    uv run python evals/run_evals.py

    # Run specific scenarios by prefix (matches the ID prefix)
    uv run python evals/run_evals.py 01 07 12

    # Run one scenario
    uv run python evals/run_evals.py 01

    # List available scenarios
    uv run python evals/run_evals.py --list

Prerequisites
-------------
    1. MCP server:   uv run poe serve
    2. Dashboard:    uv run python evals/dashboard.py   → http://localhost:8099
    3. OPENAI_API_KEY set in .env.evals
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env.evals", override=False)
    load_dotenv(_REPO / ".env", override=False)
except ImportError:
    pass

from evals.test_viz_scorer import SCENARIOS, run_scenario  # noqa: E402


# ── Pretty printer ────────────────────────────────────────────────────────────

def _header(text: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {text}")
    print(f"{'─' * 60}")


def _step(icon: str, text: str) -> None:
    print(f"  {icon}  {text}")


def _wrap(text: str, width: int = 72, indent: str = "       ") -> str:
    words = text.split()
    line, lines = [], []
    for w in words:
        if len(" ".join(line + [w])) > width:
            lines.append(indent + " ".join(line))
            line = [w]
        else:
            line.append(w)
    if line:
        lines.append(indent + " ".join(line))
    return "\n".join(lines)


# ── Run one scenario ──────────────────────────────────────────────────────────

async def _run_one(scenario: dict) -> dict:
    sid = scenario["id"]

    _header(f"[{sid}] {scenario['label']}")
    _step("📋", scenario.get("description", ""))

    # Show what we're resolving
    if scenario.get("indicator_id"):
        _step("🔧", f"Indicator: {scenario['indicator_id']} ({scenario.get('database_id', '')})")
    elif scenario.get("search_query"):
        _step("🔍", f"Resolving via search: {scenario['search_query']!r}")
    elif scenario.get("indicator_ids"):
        _step("🔧", f"Multi-indicator: {' | '.join(scenario['indicator_ids'])}")

    if scenario.get("country_code"):
        _step("🌍", f"Countries: {scenario['country_code']}")
    years = f"{scenario.get('start_year', 'default')} – {scenario.get('end_year', 'default')}"
    _step("📅", f"Years: {years}")
    print()

    # ── Run ──────────────────────────────────────────────────────────────────
    _step("⟳", "Calling viz engine against live MCP server...")
    t0 = time.monotonic()

    try:
        result = await run_scenario(scenario)
    except asyncio.TimeoutError:
        _step("✗", "Timed out after 90s")
        return {"scenario_id": sid, "score": 0, "error": "timeout"}
    except Exception as exc:
        _step("✗", f"Unexpected error: {exc}")
        return {"scenario_id": sid, "score": 0, "error": str(exc)}

    elapsed = time.monotonic() - t0

    if result.get("error") and not result.get("chart_url"):
        _step("✗", f"Viz failed ({elapsed:.1f}s): {result['error']}")
        return {"scenario_id": sid, "score": 0, "error": result["error"]}

    # ── Report results ────────────────────────────────────────────────────────
    _step("✓", f"Completed in {elapsed:.1f}s")

    if result.get("indicator_id"):
        _step("🔧", f"Resolved: {result['indicator_id']} — {result.get('indicator_name') or ''}")
    if result.get("chart_url"):
        _step("📊", f"Chart URL: {result['chart_url']}")
    if result.get("strategy"):
        _step("↳", f"Strategy: {result['strategy']} — {result.get('reason', '')}")

    score = result.get("score", 0.0)
    filled = int((score / 10) * 20)
    bar = "█" * filled + "░" * (20 - filled)
    icon = "✓" if score >= 7 else ("~" if score >= 4 else "✗")
    print()
    _step(icon, f"Score: {score}/10  [{bar}]")
    print()

    critique = result.get("critique", "")
    if critique:
        print("  💬  Critique:")
        print(_wrap(critique))

    report_name = result["report_path"].name if result.get("report_path") else "—"
    print()
    _step("📄", f"Report saved: {report_name}")

    return {"scenario_id": sid, "score": score, "error": result.get("error")}


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    args = sys.argv[1:]

    if "--list" in args:
        print("\n  Available scenarios:\n")
        for s in SCENARIOS:
            print(f"    {s['id'][:2]}  {s['id']:<45}  {s['label']}")
        print()
        return

    # Filter by prefix if IDs given
    if args:
        selected = [s for s in SCENARIOS if any(s["id"].startswith(a) for a in args)]
        if not selected:
            print(f"\n  No scenarios matched: {args}\n  Use --list to see available IDs.\n")
            sys.exit(1)
    else:
        selected = SCENARIOS

    n = len(selected)
    reports_dir = _REPO / "evals" / "reports"

    print(f"\n  📊  Data360 Visualization Engine Scorer")
    print(f"  Running {n} scenario(s). Reports → {reports_dir}")
    print(f"  Dashboard → http://localhost:8099  (uv run python evals/dashboard.py)")

    summaries: list[dict] = []
    for i, scenario in enumerate(selected, 1):
        print(f"\n\n  ({i}/{n})")
        summary = await _run_one(scenario)
        summaries.append(summary)

    # ── Summary table ─────────────────────────────────────────────────────────
    _header("Results Summary")
    print(f"  {'Scenario':<42} {'Score'}")
    print(f"  {'─' * 42} {'─' * 6}")
    for s in summaries:
        icon = "✓" if s["score"] >= 7 else ("~" if s["score"] >= 4 else "✗")
        err = f"  ERROR: {s['error']}" if s.get("error") else ""
        print(f"  {icon} {s['scenario_id']:<40} {s['score']}/10{err}")

    scores = [s["score"] for s in summaries if not s.get("error")]
    if scores:
        avg = round(sum(scores) / len(scores), 1)
        print(f"\n  Average: {avg}/10 across {len(scores)} scenario(s)")

    print(f"\n  Reports saved to: {reports_dir}")
    print(f"  Open the dashboard to view charts and critiques.\n")


if __name__ == "__main__":
    asyncio.run(main())
