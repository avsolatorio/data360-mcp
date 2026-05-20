#!/usr/bin/env python3
"""Build extdataportal_codelists.json from the extdataportal metadata API.

Fetches https://extdataportal.worldbank.org/api/data360/metadata/codelist — a single
public endpoint that returns all Data360 dimension codelists in one call.

Key facts about the source:
  - COMP_BREAKDOWN_1, _2, _3 are identical lists (5,192 items each) — deduplicated to
    a single COMP_BREAKDOWN key to avoid tripling the file size.
  - COMP_BREAKDOWN labels start with "Metric: " prefix — stripped for chart readability.
  - UNIT_MEASURE has 770 codes vs. 42 on the old /codelist API.
  - AGE has 174 codes, URBANISATION has 17, SEX has 8.

Run with:
    uv run python scripts/build_extdataportal_codelists.py

Output:
    src/data360/extdataportal_codelists.json
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ENDPOINT = "https://extdataportal.worldbank.org/api/data360/metadata/codelist"
OUTPUT_FILE = (
    Path(__file__).parent.parent / "src" / "data360" / "extdataportal_codelists.json"
)

# These three are always identical in the API — store once.
_COMP_BREAKDOWN_DIMS = {"COMP_BREAKDOWN_1", "COMP_BREAKDOWN_2", "COMP_BREAKDOWN_3"}
_COMP_BREAKDOWN_KEY = "COMP_BREAKDOWN"
_METRIC_PREFIX = "Metric: "

# Sentinel value produced by the API for sort-order metadata — not a real code.
_SENTINEL_SORT_NAME = "Y"


def _strip_metric_prefix(name: str) -> str:
    """Remove 'Metric: ' prefix from COMP_BREAKDOWN label text."""
    if name.startswith(_METRIC_PREFIX):
        return name[len(_METRIC_PREFIX):]
    return name


def _clean_items(
    items: list,
    strip_prefix: bool = False,
) -> list[dict[str, str]]:
    """Normalise a raw codelist item list to [{id, name}, ...]."""
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = item.get("id")
        name = item.get("name", "")
        if not code:
            continue
        # The API appends a phantom {"id": "order", "name": "Y"} entry — skip it.
        if code == "order" and name == _SENTINEL_SORT_NAME:
            continue
        if strip_prefix:
            name = _strip_metric_prefix(name)
        out.append({"id": code, "name": name or code})
    return out


def main() -> None:
    print(f"Fetching {ENDPOINT} ...")
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(ENDPOINT)
            response.raise_for_status()
            raw: dict = response.json()
    except httpx.HTTPError as exc:
        print(f"ERROR: HTTP request failed — {exc}", file=sys.stderr)
        sys.exit(1)

    result: dict = {}
    counts: dict[str, int] = {}
    comp_breakdown_written = False

    # Dimensions to include (in output order — skip operational/internal dims)
    _SKIP_DIMS = {"TIME_FORMAT", "DECIMALS", "UNIT_MULT", "AGG_METHOD", "WDI_REF_AREA"}

    for dim, items in raw.items():
        if not isinstance(items, list) or dim in _SKIP_DIMS:
            continue

        if dim in _COMP_BREAKDOWN_DIMS:
            if comp_breakdown_written:
                continue  # All three are identical — write only once.
            cleaned = _clean_items(items, strip_prefix=True)
            result[_COMP_BREAKDOWN_KEY] = cleaned
            counts[_COMP_BREAKDOWN_KEY] = len(cleaned)
            comp_breakdown_written = True
        else:
            cleaned = _clean_items(items)
            result[dim] = cleaned
            counts[dim] = len(cleaned)

    result["_meta"] = {
        "source": ENDPOINT,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "note": (
            "COMP_BREAKDOWN_1/2/3 are identical on the API — stored once as "
            "COMP_BREAKDOWN. 'Metric: ' prefix stripped from COMP_BREAKDOWN labels."
        ),
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nWritten to {OUTPUT_FILE}")
    for dim, count in sorted(counts.items()):
        print(f"  {dim}: {count} codes")
    print(f"\nTotal dimensions: {len(counts)}")


if __name__ == "__main__":
    main()
