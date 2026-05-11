#!/usr/bin/env python3
"""Build the same choropleth Vega-Lite spec as the MCP server, without calling the chat/API.

Reads a small JSON fixture (default: bundled poverty 2020 sample) and prints or writes
the spec produced by ``viz_config.build_choropleth_spec`` using ``MCPServerSettings``
(topojson URLs, country-names JSON URL, optional layers).

Examples::

    uv run python scripts/mock_choropleth_spec.py
    uv run python scripts/mock_choropleth_spec.py -o /tmp/choropleth.json
    uv run python scripts/mock_choropleth_spec.py --fixture path/to/data.json --no-disputed

Fixture shape::

    {
      "indicator_title": "…",
      "unit_measure": "%",
      "rows": [{ "wb_a3": "BRA", "country": "Brazil", "value": 42.5, "year": "2020" }]
    }

Environment: optional ``MCP_*`` overrides (see ``data360.config.MCPServerSettings``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _ensure_src_on_path() -> None:
    src = _ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def main() -> int:
    default_fixture = _ROOT / "scripts" / "fixtures" / "mock_choropleth_poverty_2020.json"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=default_fixture,
        help=f"JSON fixture path (default: {default_fixture})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write spec to this file instead of stdout",
    )
    parser.add_argument(
        "--no-small-countries",
        action="store_true",
        help="Omit small-country point layers",
    )
    parser.add_argument(
        "--no-disputed",
        action="store_true",
        help="Omit disputed-areas overlay",
    )
    parser.add_argument(
        "--plain-title",
        action="store_true",
        help="Use indicator_title only (no subtitle from geography/year/unit)",
    )
    args = parser.parse_args()

    _ensure_src_on_path()

    import pandas as pd

    from data360.config import get_mcp_server_settings
    from data360 import viz_config

    raw = json.loads(args.fixture.read_text(encoding="utf-8"))
    indicator_title = raw["indicator_title"]
    unit_measure = raw.get("unit_measure")
    rows = raw["rows"]
    df = pd.DataFrame(rows)

    err = viz_config.validate_choropleth_df(df)
    if err:
        print(f"Invalid choropleth data: {err}", file=sys.stderr)
        return 1

    if args.plain_title:
        title: str | dict = indicator_title
    else:
        title = viz_config.build_chart_title_with_context(
            indicator_title,
            unit_measure if unit_measure else None,
            df,
        )

    mcp = get_mcp_server_settings()
    spec = viz_config.build_choropleth_spec(
        df,
        title,
        geo_url=mcp.choropleth_geojson_url,
        geo_format=mcp.choropleth_geo_format,
        geo_feature=mcp.choropleth_geo_feature,
        geo_join_prop=mcp.choropleth_geo_join_key,
        small_countries_geo_url=(
            None if args.no_small_countries else mcp.choropleth_small_countries_geojson_url
        ),
        disputed_areas_geo_url=(
            None if args.no_disputed else mcp.choropleth_disputed_areas_geojson_url
        ),
        country_names_url=mcp.choropleth_country_names_json_url,
        unit_measure=unit_measure if unit_measure else None,
    )

    text = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
