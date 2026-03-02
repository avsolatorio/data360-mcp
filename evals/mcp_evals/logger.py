"""Response logger for MCP evaluation runs."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

RESULTS_DIR = Path(os.getenv(
    "EVAL_RESULTS_DIR",
    str(Path(__file__).parent / "results"),
))


class ResultLogger:
    """Logs each scenario run to a JSONL file for review."""

    def __init__(self, results_dir: Path = RESULTS_DIR):
        results_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path = results_dir / f"run_{ts}.jsonl"
        self._fh = open(self.path, "a", encoding="utf-8")

    def log(self, scenario: dict, result) -> None:
        """Log a single scenario execution result."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "input": scenario.get("input", ""),
            "tags": scenario.get("tags", []),
            "expected_tools": scenario.get("expected_tools", []),
            "actual_output": result.actual_output,
            "completion_time_s": round(result.completion_time, 2),
            "tools_called": [
                {
                    "name": tc.name,
                    "input_parameters": tc.input_parameters,
                    "output_preview": (
                        str(tc.output)[:500] if tc.output else None
                    ),
                }
                for tc in result.tools_called
            ],
            "mcp_tools_called": [
                {
                    "name": tc.name,
                    "args": tc.args,
                    "result_preview": (
                        str(tc.result)[:500] if tc.result else None
                    ),
                }
                for tc in result.mcp_tools_called
            ],
        }
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
