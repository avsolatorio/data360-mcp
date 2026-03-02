"""CLI entrypoint to run all MCP server evaluations.

Usage:
    uv run python evals/mcp_evals/run_evals.py [-v] [--deepeval] [--qa]
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Run MCP server evaluations (DeepEval + QA)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--deepeval",
        action="store_true",
        help="Run only DeepEval tests (tool quality)",
    )
    parser.add_argument(
        "--qa",
        action="store_true",
        help="Run only QA-pair evaluation (answer correctness)",
    )
    args = parser.parse_args()

    # If neither flag is set, run both
    run_deepeval = args.deepeval or (not args.deepeval and not args.qa)
    run_qa = args.qa or (not args.deepeval and not args.qa)

    base_dir = "evals/mcp_evals"
    failed = False

    if run_deepeval:
        cmd = ["deepeval", "test", "run", f"{base_dir}/test_single_turn.py"]
        if args.verbose:
            cmd.append("-v")

        print(f"\n{'='*60}")
        print("🔬 DeepEval: Tool Selection Quality")
        print(f"Running: {' '.join(cmd)}")
        print(f"{'='*60}\n")

        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"\n❌ DeepEval tests had failures")
            failed = True

    if run_qa:
        cmd = [
            sys.executable, f"{base_dir}/qa_eval.py",
            f"{base_dir}/evaluation.xml",
        ]
        if args.verbose:
            cmd.append("-v")

        print(f"\n{'='*60}")
        print("📋 QA-Pair: Answer Correctness")
        print(f"Running: {' '.join(cmd)}")
        print(f"{'='*60}\n")

        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"\n❌ QA evaluation had failures")
            failed = True

    print(f"\n{'='*60}")
    if failed:
        print("⚠️  Some evaluations had failures — see details above")
    else:
        print("✅ All evaluations complete!")
    print(f"{'='*60}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
