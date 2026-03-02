"""QA-Pair Evaluation for MCP Server — tests end-to-end answer correctness.

Reads evaluation.xml, runs each question through the LLM+MCP agent,
and compares the answer by exact string match.

Usage:
    uv run python evals/mcp_evals/qa_eval.py evals/mcp_evals/evaluation.xml -v
    uv run python evals/mcp_evals/qa_eval.py evals/mcp_evals/evaluation.xml -o report.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from harness import run_single_turn  # noqa: E402

EVAL_PROMPT_PREFIX = (
    "Answer the following question using the available tools. "
    "Provide ONLY the final answer - no explanation, no extra text. "
    "If you cannot find the answer, respond with NOT_FOUND.\n\n"
    "Question: "
)


def parse_evaluation_file(file_path: Path) -> list[dict]:
    """Parse XML evaluation file with qa_pair elements."""
    tree = ET.parse(file_path)
    root = tree.getroot()
    pairs = []
    for qa_pair in root.findall(".//qa_pair"):
        q = qa_pair.find("question")
        a = qa_pair.find("answer")
        if q is not None and a is not None:
            pairs.append({
                "question": (q.text or "").strip(),
                "answer": (a.text or "").strip(),
            })
    return pairs


def normalize(text: str) -> str:
    """Normalize answer for comparison."""
    return text.strip().rstrip(".").strip().lower()


async def evaluate_qa_pair(qa: dict, verbose: bool = False) -> dict:
    """Run one QA pair through the LLM+MCP agent and check the answer."""
    prompt = EVAL_PROMPT_PREFIX + qa["question"]
    start = time.monotonic()
    result = await run_single_turn(prompt)
    elapsed = time.monotonic() - start

    actual = result.actual_output.strip()
    expected = qa["answer"]

    exact_match = actual == expected
    normalized_match = normalize(actual) == normalize(expected)
    contains_match = normalize(expected) in normalize(actual)

    correct = exact_match or normalized_match or contains_match

    entry = {
        "question": qa["question"],
        "expected": expected,
        "actual": actual,
        "correct": correct,
        "match_type": (
            "exact" if exact_match
            else "normalized" if normalized_match
            else "contains" if contains_match
            else "none"
        ),
        "duration_s": round(elapsed, 2),
        "tools_called": [tc.name for tc in result.tools_called],
        "num_tool_calls": len(result.tools_called),
    }

    if verbose:
        icon = "pass" if correct else "FAIL"
        print(f"  [{icon}] Q: {qa['question'][:60]}...")
        print(f"     Expected: {expected}")
        print(f"     Actual:   {actual[:100]}")
        print(f"     Tools:    {entry['tools_called']}")
        print(f"     Time:     {elapsed:.1f}s")
        print()

    return entry


def generate_report(results: list[dict]) -> str:
    """Generate a markdown report from evaluation results."""
    correct = sum(1 for r in results if r["correct"])
    total = len(results)
    accuracy = (correct / total * 100) if total else 0
    avg_duration = sum(r["duration_s"] for r in results) / total if total else 0
    avg_tools = sum(r["num_tool_calls"] for r in results) / total if total else 0
    total_tools = sum(r["num_tool_calls"] for r in results)

    report = f"""# QA Evaluation Report

## Summary

- **Accuracy**: {correct}/{total} ({accuracy:.1f}%)
- **Average Duration**: {avg_duration:.1f}s
- **Average Tool Calls**: {avg_tools:.1f}
- **Total Tool Calls**: {total_tools}

---

## Results

"""
    for i, r in enumerate(results, 1):
        icon = "pass" if r["correct"] else "FAIL"
        report += f"""### Task {i} [{icon}]

**Question**: {r['question']}
**Expected**: `{r['expected']}`
**Actual**: `{r['actual'][:200]}`
**Match**: {r['match_type']}
**Duration**: {r['duration_s']}s
**Tools Called**: {', '.join(r['tools_called']) or 'none'}

---

"""
    return report


async def main():
    parser = argparse.ArgumentParser(
        description="Run QA-pair evaluation against MCP server"
    )
    parser.add_argument("eval_file", type=Path, help="Path to evaluation XML file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print per-question results")
    parser.add_argument("-o", "--output", type=Path, help="Save markdown report to file")
    args = parser.parse_args()

    if not args.eval_file.exists():
        print(f"Error: File not found: {args.eval_file}")
        sys.exit(1)

    qa_pairs = parse_evaluation_file(args.eval_file)
    print(f"Loaded {len(qa_pairs)} QA pairs from {args.eval_file}")
    print()

    results = []
    for i, qa in enumerate(qa_pairs, 1):
        print(f"[{i}/{len(qa_pairs)}] Running: {qa['question'][:60]}...")
        result = await evaluate_qa_pair(qa, verbose=args.verbose)
        results.append(result)

    correct = sum(1 for r in results if r["correct"])
    total = len(results)
    accuracy = (correct / total * 100) if total else 0

    print(f"\n{'='*60}")
    print(f"QA Evaluation: {correct}/{total} ({accuracy:.1f}%)")
    print(f"{'='*60}")

    if args.output:
        report = generate_report(results)
        args.output.write_text(report)
        print(f"\nReport saved to {args.output}")

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = results_dir / f"qa_run_{ts}.json"
    json_path.write_text(json.dumps(results, indent=2))
    print(f"Raw results saved to {json_path}")

    sys.exit(0 if accuracy == 100 else 1)


if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
