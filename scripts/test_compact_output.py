"""Smoke-test script: verify compact output from aggregation tools via live MCP server.

Run the MCP server first:
    uv run poe serve

Then run this script:
    uv run python scripts/test_compact_output.py

What it checks:
  rank_countries   — excluded_count instead of 30+ objects; claim_id per entry; no percentile
  summarize_data   — claim_ids per group present; compact field names
  compare_countries — series as arrays [year, value, claim_id]; series_schema present
"""

from __future__ import annotations

import json
import sys

import httpx

MCP_BASE = "http://localhost:8021/mcp/"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

# ---------------------------------------------------------------------------
# Minimal MCP JSON-RPC helpers
# ---------------------------------------------------------------------------

_id_counter = 0


def _next_id() -> int:
    global _id_counter
    _id_counter += 1
    return _id_counter


def _call_tool(client: httpx.Client, tool_name: str, arguments: dict) -> dict:
    """Send a tools/call request and return the parsed response dict."""
    payload = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = client.post("", json=payload, headers=HEADERS, timeout=60)
    resp.raise_for_status()

    # Streamable HTTP may return SSE lines — grab the first data: line
    body = resp.text
    if body.startswith("data:"):
        for line in body.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:"):].strip())
    return resp.json()


def _extract_text(result: dict) -> str:
    """Pull the TextContent string from a tools/call result."""
    content = result.get("result", result).get("content", [])
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block["text"]
    return json.dumps(result)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{status}] {label}{suffix}")
    return condition


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    failures = 0

    with httpx.Client(base_url=MCP_BASE) as client:

        # -- Initialize session (required by MCP protocol) ---------------
        init_resp = client.post(
            "",
            json={
                "jsonrpc": "2.0",
                "id": _next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke-test", "version": "0.1"},
                },
            },
            headers=HEADERS,
            timeout=15,
        )
        init_resp.raise_for_status()
        session_id = init_resp.headers.get("mcp-session-id", "")
        if session_id:
            HEADERS["mcp-session-id"] = session_id
        print(f"Session: {session_id or '(none — stateless)'}")

        # ----------------------------------------------------------------
        section("rank_countries — SSF top-5 by unemployment")
        # ----------------------------------------------------------------
        raw = _call_tool(client, "data360_rank_countries", {
            "database_id": "WB_WDI",
            "indicator_id": "WB_WDI_SL_UEM_TOTL_ZS",
            "country_group": "SSF",
            "top_n": 5,
        })
        text = _extract_text(raw)
        print(f"  Size: {len(text):,} chars (~{len(text)//4:,} tokens)")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"  [{FAIL}] Could not parse JSON: {e}")
            failures += 1
            data = {}

        if data:
            rankings = data.get("rankings", [])
            first = rankings[0] if rankings else {}

            failures += 0 if check("claim_id present per ranking entry",
                                   "claim_id" in first,
                                   f"keys: {list(first.keys())}") else 1
            failures += 0 if check("percentile absent from ranking entry",
                                   "percentile" not in first) else 1
            failures += 0 if check("excluded_count present (not full list)",
                                   "excluded_count" in data,
                                   str(data.get("excluded_count"))) else 1
            failures += 0 if check("excluded_sample <= 5 entries",
                                   len(data.get("excluded_sample", [])) <= 5) else 1
            failures += 0 if check("output < 2000 chars",
                                   len(text) < 2000,
                                   f"{len(text)} chars") else 1

        # ----------------------------------------------------------------
        section("summarize_data — Kenya unemployment by sex")
        # ----------------------------------------------------------------
        raw = _call_tool(client, "data360_summarize_data", {
            "database_id": "WB_WDI",
            "indicator_id": "WB_WDI_SL_UEM_TOTL_ZS",
            "country_code": "KEN",
            "group_by": ["ref_area"],
        })
        text = _extract_text(raw)
        print(f"  Size: {len(text):,} chars (~{len(text)//4:,} tokens)")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"  [{FAIL}] Could not parse JSON: {e}")
            failures += 1
            data = {}

        if data:
            groups = data.get("groups", [])
            first_group = groups[0] if groups else {}

            failures += 0 if check("claim_ids present per group",
                                   "claim_ids" in first_group,
                                   f"keys: {list(first_group.keys())}") else 1
            failures += 0 if check("compact field names (n, range, stats, change, trend)",
                                   all(k in first_group for k in ("n", "stats", "trend"))) else 1
            failures += 0 if check("output < 1500 chars",
                                   len(text) < 1500,
                                   f"{len(text)} chars") else 1

        # ----------------------------------------------------------------
        section("compare_countries — KEN vs NGA vs ZAF with time series")
        # ----------------------------------------------------------------
        raw = _call_tool(client, "data360_compare_countries", {
            "database_id": "WB_WDI",
            "indicator_id": "WB_WDI_SL_UEM_TOTL_ZS",
            "country_codes": "KEN;NGA;ZAF",
            "include_time_series": True,
        })
        text = _extract_text(raw)
        print(f"  Size: {len(text):,} chars (~{len(text)//4:,} tokens)")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"  [{FAIL}] Could not parse JSON: {e}")
            failures += 1
            data = {}

        if data:
            ts = data.get("time_series") or {}
            series = ts.get("series", {})
            first_country = next(iter(series.values()), [])
            first_point = first_country[0] if first_country else None

            failures += 0 if check("series_schema present",
                                   "series_schema" in ts,
                                   str(ts.get("series_schema"))) else 1
            failures += 0 if check("series data point is an array not a dict",
                                   isinstance(first_point, list),
                                   f"type: {type(first_point).__name__}") else 1
            if isinstance(first_point, list):
                failures += 0 if check("array has 3 elements [year, value, claim_id]",
                                       len(first_point) == 3,
                                       str(first_point)) else 1
                failures += 0 if check("third element is a string (claim_id)",
                                       isinstance(first_point[2], str) or first_point[2] is None,
                                       str(first_point[2])) else 1
            failures += 0 if check("year_range present instead of aligned_years list",
                                   "year_range" in ts and "aligned_years" not in ts) else 1
            failures += 0 if check("snapshot claim_ids present",
                                   all("claim_id" in r for r in
                                       (data.get("snapshot") or {}).get("rankings", []) if r)) else 1

    # ----------------------------------------------------------------
    print(f"\n{'─' * 60}")
    if failures == 0:
        print(f"  {PASS}  All checks passed.")
    else:
        print(f"  {FAIL}  {failures} check(s) failed.")
    print(f"{'─' * 60}\n")
    return failures


if __name__ == "__main__":
    sys.exit(main())
