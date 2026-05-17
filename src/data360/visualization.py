"""
Visualization generation for Data360 data.

Fetches series via the Data360 API (``data360.api.get_data_api_url``), builds
Vega-Lite specifications, then persists them either through the optional Charts API
(``charts_api_url``) or as static JSON under ``static/viz_specs/``.

**Public tools**

- ``get_viz_spec`` — one indicator. Uses Draco where appropriate and
  ``data360.viz_config`` strategy dispatch for patterns Draco does not handle well.
- ``get_multi_indicator_viz_spec`` — two to four indicators; merges frames and
  dispatches multi-series strategies (scatter, layered lines, connected scatter, etc.).

Return shape for both: ``{"url": str|None, "error": str|None, ...}`` plus optional
``database_id``, ``database_name``, ``indicator_id``, ``indicator_name``, optional
``strategy`` / ``reason``, and optional preformatted ``source_line`` /
``subtitle_line`` for clients that only render strings. Before any HTTP
or ``json.dump``, specs are passed through ``_vega_spec_to_json_safe`` so
``data.values`` never contains raw ``pandas.Timestamp`` / numpy scalars that would
break JSON encoding.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import uuid
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

import altair as alt
import httpx
import numpy as np
import pandas as pd
from draco import Draco, answer_set_to_dict, dict_to_facts, schema_from_dataframe
from draco.renderer import AltairRenderer

from data360 import viz_config
from data360.config import get_mcp_server_settings
from data360.http_client import get_shared_httpx_client
from data360.providers import get_database_mapping

_logger = logging.getLogger(__name__)

_FALLBACK_WARNING = (
    "Draco could not determine an optimal encoding; "
    "a default chart was generated as fallback."
)

VizResult = dict[str, str | None]

# Disaggregation dimensions considered during viz data cleaning and encoding.
# Mirrors _DISAGG_DIMS_TO_DETECT from api.py but in lowercase (post-column-rename).
# Single source of truth for the viz pipeline: _clean_single_df, color dim
# detection, and multi-indicator join keys all reference this tuple.
_VIZ_DISAGG_DIMS: tuple[str, ...] = (
    "sex",
    "age",
    "urbanisation",
    "comp_breakdown_1",
    "comp_breakdown_2",
)


# ============================================================================
# STORAGE HELPERS
# ============================================================================


def save_specs_to_static(vl_spec: dict) -> str:
    """Persist ``vl_spec`` as JSON and return a URL the **browser** can fetch.

    The frontend (or another client) loads this file over HTTP; it is not read
    only inside Docker. ``WEBSITE_HOSTNAME`` should be a host:port the user's browser
    can resolve; when unset we default to ``localhost`` and the MCP server port from
    ``data360.config.get_mcp_server_settings()``.
    """
    spec_id = str(uuid.uuid4())
    specs_dir = os.path.join(os.getcwd(), "static", "viz_specs")
    os.makedirs(specs_dir, exist_ok=True)
    vega_path = os.path.join(specs_dir, f"{spec_id}_vega.json")
    with open(vega_path, "w") as f:
        json.dump(vl_spec, f, indent=2)
    base_url = os.environ.get(
        "WEBSITE_HOSTNAME", f"http://localhost:{get_mcp_server_settings().port}"
    )
    return f"{base_url}/static/viz_specs/{spec_id}_vega.json"


async def post_spec_to_charts_api(vl_spec: dict) -> str:
    """POST a Vega-Lite spec to the external Charts API (JSON body).

    The service expects standard Vega-Lite keys (``$schema``, ``data``, ``mark``,
    ``encoding``, …). Many deployments require a non-empty ``title``; we set a default
    if missing. On success, returns a chart URL from ``Location``, response JSON
    ``url`` / ``id``, or the configured API base as a last resort.
    """
    settings = get_mcp_server_settings()
    url = settings.charts_api_url
    if not url:
        raise ValueError("charts_api_url is not configured")
    payload = dict(vl_spec)
    # Charts API often rejects payloads without title
    payload.setdefault("title", vl_spec.get("title") or "Generated Visualization")
    headers = {"accept": "application/json", "Content-Type": "application/json"}
    if settings.charts_api_token:
        headers["Authorization"] = f"Bearer {settings.charts_api_token}"
    client = get_shared_httpx_client()
    response = await client.post(
        url,
        json=payload,
        headers=headers,
    )
    response.raise_for_status()
    location = response.headers.get("Location")
    if location:
        return (
            location
            if location.startswith("http")
            else f"{url.rsplit('/', 1)[0]}/{location.lstrip('/')}"
        )
    body = response.json() if response.content else {}
    if isinstance(body, dict):
        if body.get("url"):
            return body["url"]
        if body.get("id"):
            return f"{url.rstrip('/')}/{body['id']}"
    return url


def _vega_spec_to_json_safe(obj: object) -> object:
    """Recursively convert a Vega-Lite spec tree to JSON-serializable Python types.

    Covers pandas/numpy scalars and datetimes that can appear in ``data.values`` or
    elsewhere after ``DataFrame.to_dict`` (including merged dtypes and edge cases the
    DataFrame-only sanitizer misses).
    """
    if obj is None:
        return None
    if isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return obj
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat() if pd.notna(obj) else None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, np.datetime64):
        return str(pd.Timestamp(obj))
    if isinstance(obj, (np.integer, np.floating)):
        if pd.isna(obj):
            return None
        return obj.item()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, dict):
        return {k: _vega_spec_to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_vega_spec_to_json_safe(v) for v in obj]
    if hasattr(obj, "item"):
        try:
            return _vega_spec_to_json_safe(obj.item())
        except (ValueError, AttributeError, TypeError):
            pass
    raise TypeError(
        f"Vega-Lite spec contains unsupported type for JSON: {type(obj).__name__}"
    )


async def _store_spec(vl_spec: dict) -> str:
    """Persist a Vega-Lite dict: Charts API when configured, else static file.

    Always runs ``_vega_spec_to_json_safe`` first so httpx ``json=`` and
    ``json.dump`` cannot fail on non-JSON-native types in embedded data.
    """
    safe = _vega_spec_to_json_safe(vl_spec)
    if not isinstance(safe, dict):
        raise TypeError("Vega spec must serialize to a JSON object")
    charts_url = get_mcp_server_settings().charts_api_url
    if charts_url:
        try:
            return await post_spec_to_charts_api(safe)
        except Exception as e:
            _logger.warning(f"Charts API store failed, falling back to static: {e}")
    return save_specs_to_static(safe)


def _ok(
    url: str,
    warning: str | None = None,
    *,
    source_attribution: dict[str, str] | None = None,
    strategy: str | None = None,
    reason: str | None = None,
) -> VizResult:
    r: VizResult = {"url": url, "error": None}
    if warning:
        r["warning"] = warning
    if source_attribution:
        for key, val in source_attribution.items():
            if val:
                r[key] = val
    if strategy:
        r["strategy"] = strategy
    if reason:
        r["reason"] = reason
    attrib_for_line = {
        k: str(v)
        for k, v in r.items()
        if k
        in (
            "database_id",
            "database_name",
            "indicator_id",
            "indicator_name",
        )
        and v
    }
    r["source_line"] = _format_source_line_from_attribution(attrib_for_line)
    strat_v = r.get("strategy")
    reas_v = r.get("reason")
    sub = _format_subtitle_line(
        warning,
        strat_v if isinstance(strat_v, str) else None,
        reas_v if isinstance(reas_v, str) else None,
    )
    if sub:
        r["subtitle_line"] = sub
    return r


def _err(msg: str) -> VizResult:
    return {"url": None, "error": msg}


_SOURCE_FALLBACK = "World Bank — Data360"


def _format_source_line_from_attribution(attrib: dict[str, str]) -> str:
    """One-line \"Source\" string; matches client `formatData360VizSourceLine`."""
    db = (attrib.get("database_name") or attrib.get("database_id") or "").strip()
    ind = (attrib.get("indicator_name") or attrib.get("indicator_id") or "").strip()
    if db and ind:
        return f"World Bank — {db} — {ind}"
    if ind:
        return f"World Bank — {ind}"
    if db:
        return f"World Bank — {db}"
    return _SOURCE_FALLBACK


def _format_subtitle_line(
    warning: str | None,
    strategy: str | None,
    reason: str | None,
) -> str | None:
    """Optional subtitle under chart title; matches client `formatData360VizSubtitleLine`."""
    parts: list[str] = []
    if warning:
        parts.append(warning)
    if strategy or reason:
        parts.append(" — ".join(x for x in (strategy or "", reason or "") if x))
    if not parts:
        return None
    return " · ".join(parts)


def _scalar_for_json(value: object) -> object:
    """Coerce pandas/numpy scalars so stdlib json can encode them."""
    if isinstance(value, pd.Timestamp):
        return value.isoformat() if pd.notna(value) else None
    return value


def _sanitize_dataframe_for_json_records(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure ``DataFrame.to_dict(orient='records')`` is JSON-serializable (no Timestamp)."""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].map(lambda x: x.isoformat() if pd.notna(x) else None)
        elif out[col].dtype == object:
            out[col] = out[col].map(_scalar_for_json)
    return out


# ============================================================================
# DATA FETCHING
# ============================================================================


async def _fetch_data_internal(url: str) -> pd.DataFrame:
    client = get_shared_httpx_client()
    response = await client.get(url)
    response.raise_for_status()
    data = response.json()
    raw_data = data.get("value", [])
    if not raw_data:
        raise ValueError("No data found at the provided URL.")
    return pd.DataFrame(raw_data)


async def _fetch_single_indicator(
    database_id: str,
    indicator_id: str,
    country_code: str | None,
    start_year: int | None,
    end_year: int | None,
    disaggregation_filters: dict | None,
) -> tuple[pd.DataFrame, str | None, str | None]:
    """Fetch one indicator and return (DataFrame, title, unit_label).

    Returns (empty_df, None, None) on error — caller checks df.empty.
    """
    from data360.api import get_data_api_url, get_metadata

    try:
        data_url = await get_data_api_url(
            database_id=database_id,
            indicator_id=indicator_id,
            country_code=country_code,
            start_year=start_year,
            end_year=end_year,
            disaggregation_filters=disaggregation_filters,
        )
        df = await _fetch_data_internal(data_url)
        df.columns = [c.lower() for c in df.columns]
    except Exception as e:
        _logger.error(f"Failed to fetch {indicator_id}: {e}")
        return pd.DataFrame(), None, None

    # Fetch title + unit from metadata
    title, unit = None, None
    try:
        parsed = urlparse(data_url)
        params = parse_qs(parsed.query)
        db_id = params.get("DATABASE_ID", [database_id])[0]
        ind_id = (
            params.get("indicatorId", [None])[0]
            or params.get("INDICATOR", [None])[0]
            or indicator_id
        )
        meta = await get_metadata(db_id, ind_id)
        if meta and meta.indicator_metadata:
            title = meta.indicator_metadata.get("name")
            unit = meta.indicator_metadata.get(
                "measurement_unit"
            ) or meta.indicator_metadata.get("unit_measure")
    except Exception as e:
        _logger.warning(f"Could not fetch metadata for {indicator_id}: {e}")

    return df, title, unit


# ============================================================================
# DATA CLEANING HELPERS
# ============================================================================


def _clean_single_df(
    data: pd.DataFrame,
    relevant_fields: list[str] | None,
    chart_type: str | None,
    data_frequency: str | None,
) -> tuple[pd.DataFrame, list[str]]:
    """Clean + rename a single-indicator DataFrame for the Draco path."""
    # Trivial values for disaggregation dimensions: _T = aggregate total, _Z = not applicable.
    _TRIVIAL_DIM_VALUES = ("_T", "_Z")

    if relevant_fields:
        req = [f.lower() for f in relevant_fields]
        missing = [f for f in req if f not in data.columns]
        if missing:
            raise ValueError(
                f"Requested fields not found: {missing}. Available: {list(data.columns)}"
            )
        valid_cols = req
        for dim in ["ref_area", *_VIZ_DISAGG_DIMS]:
            if dim in data.columns and dim not in valid_cols:
                uv = data[dim].unique()
                if len(uv) > 1 or (len(uv) == 1 and uv[0] not in _TRIVIAL_DIM_VALUES):
                    valid_cols.append(dim)
        viz_data = data[valid_cols].copy()
        relevant_cols = valid_cols
    else:
        relevant_cols = []
        for col in ["time_period", "obs_value", "ref_area"]:
            if col in data.columns:
                relevant_cols.append(col)
        for dim in _VIZ_DISAGG_DIMS:
            if dim in data.columns:
                uv = data[dim].unique()
                if len(uv) > 1 or (len(uv) == 1 and uv[0] not in _TRIVIAL_DIM_VALUES):
                    relevant_cols.append(dim)
        viz_data = data[relevant_cols].copy() if relevant_cols else data.copy()

    # Temporal preparation
    if "time_period" in viz_data.columns:
        try:
            user_mark = viz_config.parse_chart_type_hint(chart_type)
            action = viz_config.get_data_preparation_action(user_mark, data_frequency)
            if action == "year_strings":
                viz_data["time_period"] = pd.to_datetime(
                    viz_data["time_period"]
                ).dt.year.astype(str)
            else:
                viz_data["time_period"] = pd.to_datetime(viz_data["time_period"])
        except Exception as e:
            _logger.warning(f"time_period conversion failed: {e}")

    if "obs_value" in viz_data.columns:
        viz_data["obs_value"] = pd.to_numeric(viz_data["obs_value"], errors="coerce")

    # Rename to friendly names
    viz_data = viz_data.rename(
        columns={"time_period": "year", "obs_value": "value", "ref_area": "country"}
    )
    relevant_cols = [
        {"time_period": "year", "obs_value": "value", "ref_area": "country"}.get(c, c)
        for c in relevant_cols
    ]
    if "value" in viz_data.columns:
        viz_data["value"] = pd.to_numeric(viz_data["value"], errors="coerce")
    return viz_data, relevant_cols


async def _map_country_codes(viz_data: pd.DataFrame) -> pd.DataFrame:
    """Map REF_AREA / country codes to human-readable names."""
    col = "country" if "country" in viz_data.columns else None
    if col is None:
        return viz_data
    try:
        from data360.providers import get_codelist_mapping

        country_map = await get_codelist_mapping("REF_AREA")
        viz_data[col] = viz_data[col].map(lambda x: country_map.get(x, x))
    except Exception as e:
        _logger.warning(f"Could not map country codes: {e}")
    return viz_data


def _slugify(name: str) -> str:
    """Convert indicator name to a safe column name."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s[:40].strip("_") or "indicator"


def _make_unique_col(base: str, existing: set[str]) -> str:
    col, n = base, 1
    while col in existing:
        col = f"{base}_{n}"
        n += 1
    return col


# ============================================================================
# TOOL: get_supported_chart_types
# ============================================================================


def get_supported_chart_types() -> str:
    """Return supported chart types and their data requirements as JSON.

    Call before data360_get_viz_spec or data360_get_multi_indicator_viz_spec
    to choose the right chart_type for the data and user intent.

    Returns:
        JSON string with chart_types list and strategy guidance.
    """
    chart_types = {
        "chart_types": [
            {
                "id": "line",
                "description": "Line chart for temporal trends.",
                "when_to_use": "Single indicator, 1+ countries, multiple years.",
                "data_requirements": "time_period + obs_value. Color-codes countries automatically.",
            },
            {
                "id": "bar",
                "description": "Horizontal bar chart for ranking/comparison.",
                "when_to_use": "Single indicator, multiple countries, typically one year.",
                "data_requirements": "obs_value + country dimension.",
            },
            {
                "id": "scatter",
                "description": "Scatterplot for correlation between two indicators.",
                "when_to_use": "Exactly 2 indicator_ids, multiple countries, single year.",
                "data_requirements": "Requires indicator_ids list with 2 entries in get_multi_indicator_viz_spec.",
            },
            {
                "id": "connected_scatter",
                "description": "Connected scatterplot: 2 indicators over time.",
                "when_to_use": "Exactly 2 indicator_ids, multiple countries, multiple years.",
                "data_requirements": "Same as scatter but multi-year.",
            },
            {
                "id": "layered_lines",
                "description": "Dual/multi-axis line chart for 2-3 indicators in one country.",
                "when_to_use": "2-3 indicator_ids, typically 1 country, multi-year.",
                "data_requirements": "Requires indicator_ids list in get_multi_indicator_viz_spec.",
            },
            {
                "id": "small_multiples",
                "description": "Faceted panel chart for breakdown × country comparisons.",
                "when_to_use": "1 indicator, multiple breakdowns (sex/age) or many countries.",
                "data_requirements": "Disaggregation dimensions with multiple values.",
            },
            {
                "id": "strip",
                "description": "Strip/beeswarm chart for cross-country distribution.",
                "when_to_use": ">8 countries, single year.",
                "data_requirements": "obs_value + many country values.",
            },
        ],
        "multi_indicator_note": (
            "For scatter, connected_scatter, and layered_lines, use "
            "data360_get_multi_indicator_viz_spec with an indicator_ids list."
        ),
    }
    return json.dumps(chart_types, indent=2)


# ============================================================================
# TOOL: get_viz_spec (single indicator — original interface preserved)
# ============================================================================


async def get_viz_spec(
    database_id: str,
    indicator_id: str,
    country_code: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
    chart_type: str | None = None,
    relevant_fields: list[str] | None = None,
    custom_constraints: list[str] | None = None,
    use_default_constraints: bool = True,
) -> VizResult:
    """Generate a Vega-Lite chart from a single Data360 indicator.

    Use when the user wants a visualization for ONE indicator. For comparing multiple
    indicators (scatter, dual-axis), use data360_get_multi_indicator_viz_spec instead.

    ## Grammar of Graphics Contract

    The pipeline maps data dimensions to Vega-Lite aesthetic channels automatically
    (color, facet). DO NOT pre-filter a dimension to simplify the chart — that collapses
    multi-series data into a single undifferentiated line and silently discards information.

    ### disaggregation_filters decision rule

    Only pin a dimension when the user has explicitly requested a specific value:

      CORRECT — user asked for females only:
        disaggregation_filters={"SEX": "F"}

      CORRECT — force aggregate totals (suppress breakdown display):
        disaggregation_filters={"SEX": "_T"}

      CORRECT — dimension is not applicable for this indicator:
        disaggregation_filters={"SEX": "_Z"}

      WRONG — do not pre-filter to reduce chart complexity:
        disaggregation_filters={"COMP_BREAKDOWN_1": "WGI_EST"}  # silently drops other series
        disaggregation_filters={"SEX": "_T"}                    # unless user said "totals only"

    When a dimension has multiple meaningful values and the user has not requested a
    specific one, OMIT it from disaggregation_filters entirely. The pipeline will:
      - detect non-trivial values (anything other than "_T" or "_Z")
      - choose the correct Vega-Lite channel based on data shape (see chart strategy table)

    ### Chart strategy → Vega-Lite encoding table

    The pipeline selects a strategy from the shape of the data after filtering. All
    strategies bypass Draco and produce validated Vega-Lite v5 specs directly.

    Strategy              | When selected                                       | Vega-Lite encoding
    ----------------------|-----------------------------------------------------|-------------------------------------------
    TEMPORAL_SINGLE       | multi-year, ≤8 countries, 0-1 breakdowns            | x=year(temporal), y=value(Q), color=country or breakdown(N)
    CROSS_SECTIONAL       | single year, ≤8 countries, no breakdown             | y=country(N) sorted, x=value(Q) (horizontal bar)
    DISTRIBUTION          | single year, >8 countries                           | x=value(Q), y=country(N) (tick/strip chart)
    BREAKDOWN_COMPARISON  | 1 breakdown, single year, ≤4 countries              | x=country(N), xOffset=breakdown(N), y=value(Q) (grouped bar)
    SMALL_MULTIPLES       | breakdown + >1 country, OR 2+ breakdowns            | facet=country(N), color=breakdown(N), x=year(temporal), y=value(Q)
    TEMPORAL_SINGLE*      | 1 breakdown (any dim), multi-year                   | x=year(temporal), y=value(Q), color=breakdown(N) (multi-series line)
    HEATMAP               | >8 countries, multi-year, 0 breakdowns              | x=year(temporal), y=country(N), color=value(Q) (rect grid)
    STACKED_AREA          | chart_type="area"/"stacked_area", composition Q     | x=year(temporal), y=value(Q) stacked, color=breakdown(N)
    FALLBACK_LINE         | unclassified shapes                                 | x=year(temporal), y=value(Q), color=country(N)

    *When comp_breakdown_1/2 has multiple values and year_count > 1, the pipeline routes
    to TEMPORAL_SINGLE with color=comp_breakdown_1 — producing one colored line per
    breakdown series. This is the correct encoding for WGI, sectoral breakdowns, etc.

    ### High-cardinality and high-dimensionality guidance

    DO NOT reduce country_code or disaggregation_filters to simplify the output.
    The pipeline handles high-cardinality data automatically:

    | Data shape                              | Pipeline action                              |
    |-----------------------------------------|----------------------------------------------|
    | >8 countries, multi-year, 0 breakdowns  | Auto-routes to HEATMAP (rect grid)           |
    | >8 countries + breakdown                | SMALL_MULTIPLES, caps at 6 facets            |
    | Single year, >8 countries               | DISTRIBUTION (strip chart), caps at 20 bars  |
    | ≤8 countries + breakdown, multi-year    | TEMPORAL_SINGLE with colored lines per series|

    If the LLM passes 3 countries when the user asked for all Sub-Saharan Africa,
    the pipeline cannot recover the missing data — it will produce a misleading chart.
    Always pass the full country list and let the pipeline decide the correct strategy.

    ### Visual channel hierarchy (perception accuracy)

    Channels are ranked by how accurately viewers read encoded values:

    Channel           | Type        | Used for
    ------------------|-------------|----------------------------------------
    Position (x/y)    | Highest     | Quantitative values, time axis
    Color (hue)       | Medium      | Nominal categories (country, breakdown)
    Color (lightness) | Medium      | Quantitative gradient (heatmap cells)
    Size              | Medium-low  | Not used in current strategies
    Shape             | Low         | Not used in current strategies

    The pipeline always maps `value` → position (y-axis) and `country`/`breakdown` → color
    (hue). Do not override this — a chart that encodes values as colors (instead of y) is
    strictly less readable, except in heatmaps where a 2D spatial grid makes position
    unavailable for both axes simultaneously.

    ### Encoding type rules (Vega-Lite v5)

    - Year fields: always type="temporal", format="%Y". Do not use "ordinal" for years
      — ordinal maps ISO timestamps to raw millisecond integers on the axis.
    - Country / breakdown fields: type="nominal"
    - Numeric values: type="quantitative"
    - Legend titles: derived from _TOOLTIP_SPECS labels (e.g. "Breakdown", not
      "Comp_Breakdown_1").
    - Color scale: WB categorical palette (9 colors). Gender data uses WB_GENDER_COLORS.
    - Heatmap color scale: sequential ("yellowgreenblue") for positive-only data;
      divergent ("redblue") when data contains negative values.

    Args:
        database_id: Database identifier (e.g., WB_HNP, WB_WDI).
        indicator_id: Indicator ID (e.g., WB_HNP_SP_POP_TOTL).
        country_code: Optional ISO code(s) for REF_AREA — one code, or several separated
            by semicolons (e.g. KEN or CHN;USA, matching required_country style) or commas
            (also accepted). Normalized to comma-separated for the Data API.
        start_year: Optional start year (inclusive).
        end_year: Optional end year (inclusive).
        disaggregation_filters: Optional dimension filters; each value is str or null, not a list.
            See grammar of graphics contract above — only pin a dimension when the user
            explicitly requested a specific value. Omitting a dimension fetches all values
            and lets the pipeline choose the correct Vega-Lite channel automatically.
            For REF_AREA use comma-separated ISO codes (e.g. 'KEN,TZA');
            semicolons in REF_AREA are normalized to commas.
        chart_type: Optional hint — "line", "bar", "scatter", "strip", "small_multiples",
            "area", "stacked_area".

            ## chart_type decision rule

            Only pass "area" or "stacked_area" when the user's question implies
            **composition or share over time** — i.e., the series together add up to a
            meaningful whole. Typical signal words: "breakdown of", "composition of",
            "share of", "proportion", "what portion", "structure of".

            CORRECT — user asked about composition:
              chart_type="stacked_area"   # "Show the age group breakdown in Japan"
              chart_type="area"           # "What is the composition of electricity by source?"

            WRONG — user asked about a trend:
              chart_type="area"           # "How has GDP changed in Africa?"   ← use default
              chart_type="stacked_area"   # "What is the trend of poverty?"    ← use default

            For trend questions ("how has X changed?", "show the evolution of Y"), omit
            chart_type entirely and let the pipeline choose the correct strategy
            (line chart, heatmap, etc.) based on data shape.
        relevant_fields: Optional list of column names to include in the chart.
        custom_constraints: Optional list of raw Draco ASP constraints.
        use_default_constraints: If True (default), apply standard encoding heuristics.

    Returns:
        Dict with "url" (chart URL on success), "error" (message on failure),
        and optionally "warning" (if fallback was used).
    """
    from data360.api import get_data_api_url, get_disaggregation, get_metadata

    # ── Detect "expand" dimensions ─────────────────────────────────────────────
    # If the caller passes disaggregation_filters={"SEX": None}, it means
    # "fetch all values for SEX". The Data360 API only accepts a single scalar
    # per dimension, so a None value is our internal sentinel for "expand me".
    # We resolve the valid non-trivial codes via get_disaggregation, then fire
    # one fetch per value concurrently and concat the results.
    _TRIVIAL_CODES = {"_T", "_Z"}
    expand_dims: dict[str, list[str]] = {}  # dim → [valid non-trivial codes]
    if disaggregation_filters:
        for dim, val in disaggregation_filters.items():
            if val is None:
                try:
                    disagg = await get_disaggregation(database_id, indicator_id)
                    for d in (disagg.get("dimensions") or []):
                        if d.get("field_name", "").upper() == dim.upper():
                            codes = [
                                c for c in (d.get("field_value") or [])
                                if c not in _TRIVIAL_CODES
                            ]
                            if codes:
                                expand_dims[dim] = codes
                            break
                except Exception as e:
                    _logger.warning(f"Could not resolve expand dim {dim}: {e}")

    # ── Fetch ──────────────────────────────────────────────────────────────────
    if expand_dims:
        # Build one filter dict per value combination (only handles single expand dim for now).
        # Multi-dim expansion (e.g. SEX × AGE) would be a combinatorial explosion — skip it.
        first_dim, codes = next(iter(expand_dims.items()))
        base_filters = {
            k: v for k, v in (disaggregation_filters or {}).items()
            if k != first_dim
        }

        async def _fetch_one(code: str) -> pd.DataFrame:
            filters = {**base_filters, first_dim: code}
            try:
                url = await get_data_api_url(
                    database_id=database_id,
                    indicator_id=indicator_id,
                    country_code=country_code,
                    start_year=start_year,
                    end_year=end_year,
                    disaggregation_filters=filters,
                )
                df = await _fetch_data_internal(url)
                df.columns = [c.lower() for c in df.columns]
                return df
            except Exception as e:
                _logger.warning(f"Expand fetch failed for {first_dim}={code}: {e}")
                return pd.DataFrame()

        frames = await asyncio.gather(*[_fetch_one(c) for c in codes])
        non_empty = [f for f in frames if not f.empty]
        if not non_empty:
            return _err("Error: No data returned for any disaggregation value.")
        data = pd.concat(non_empty, ignore_index=True)
        # data.columns already lowercased inside _fetch_one
    else:
        # 1. Build URL
        try:
            data_url = await get_data_api_url(
                database_id=database_id,
                indicator_id=indicator_id,
                country_code=country_code,
                start_year=start_year,
                end_year=end_year,
                disaggregation_filters=disaggregation_filters,
            )
        except ValueError as e:
            return _err(f"Error: {e}")

        # 2. Fetch data
        try:
            data = await _fetch_data_internal(data_url)
        except ValueError as e:
            return _err(f"Error: {e}")
        except httpx.HTTPStatusError as e:
            return _err(f"Error fetching data: {e.response.status_code}")
        except Exception as e:
            _logger.exception("Failed to fetch data")
            return _err(f"Error fetching data: {e}")

        data.columns = [c.lower() for c in data.columns]


    # 3. Detect frequency
    data_frequency = None
    try:
        parsed = urlparse(data_url)
        params = parse_qs(parsed.query)
        db_id = params.get("DATABASE_ID", [database_id])[0]
        ind_id_param = (
            params.get("indicatorId", [None])[0]
            or params.get("INDICATOR", [None])[0]
            or indicator_id
        )
        if db_id and ind_id_param:
            meta = await get_metadata(db_id, ind_id_param)
            if meta:
                if meta.disaggregation_options:
                    for d in meta.disaggregation_options:
                        if d.get("field_name") == "FREQ" and d.get("field_value"):
                            data_frequency = d["field_value"][0]
                            break
                if not data_frequency and meta.indicator_metadata:
                    data_frequency = viz_config.infer_frequency_from_periodicity(
                        meta.indicator_metadata.get("periodicity", "")
                    )
    except Exception as e:
        _logger.warning(f"Could not detect frequency: {e}")

    # 4. Fetch title and unit
    chart_title = "Generated Visualization"
    raw_unit = ""
    try:
        parsed = urlparse(data_url)
        params = parse_qs(parsed.query)
        db_id = params.get("DATABASE_ID", [database_id])[0]
        ind_id_param = (
            params.get("indicatorId", [None])[0]
            or params.get("INDICATOR", [None])[0]
            or indicator_id
        )
        if db_id and ind_id_param:
            meta = await get_metadata(db_id, ind_id_param)
            if meta and meta.indicator_metadata:
                chart_title = meta.indicator_metadata.get("name", chart_title)
                raw_unit = (
                    meta.indicator_metadata.get("measurement_unit")
                    or meta.indicator_metadata.get("unit_measure")
                    or ""
                )
    except Exception as e:
        _logger.warning(f"Could not fetch metadata for title: {e}")

    try:
        db_map = await get_database_mapping()
    except Exception as e:
        _logger.warning(f"Could not load database mapping for source attribution: {e}")
        db_map = {}
    database_display = db_map.get(database_id, database_id)
    indicator_display = (
        chart_title if chart_title != "Generated Visualization" else indicator_id
    )
    source_attribution: dict[str, str] = {
        "database_id": database_id,
        "database_name": database_display,
        "indicator_id": indicator_id,
        "indicator_name": indicator_display,
    }

    # 5. Clean data — column selection, bar-vs-temporal time handling, renames (→ year/value/country)
    if "obs_value" in data.columns:
        data["obs_value"] = pd.to_numeric(data["obs_value"], errors="coerce")

    try:
        viz_data, relevant_cols = _clean_single_df(
            data, relevant_fields, chart_type, data_frequency
        )
    except ValueError as e:
        return _err(str(e))

    if viz_data.empty:
        return _err("Error: No data available for visualization after cleaning.")

    # 6. Map country codes
    viz_data = await _map_country_codes(viz_data)

    import textwrap

    # Apply text wrapping (Typography T3 constraint) so long single-indicator titles don't overflow
    wrapped_title = textwrap.wrap(chart_title, width=80) if isinstance(chart_title, str) else chart_title

    # Vega-Lite title + subtitle (geography, year range, unit) after data is cleaned
    chart_title_vl: str | dict = viz_config.build_chart_title_with_context(
        wrapped_title, raw_unit or None, viz_data
    )

    # 7. Determine strategy — route around Draco for complex patterns
    n_indicators = 1
    strategy_result = viz_config.select_strategy(
        viz_data,
        n_indicators=n_indicators,
        chart_type_hint=chart_type,
    )

    _logger.info(
        f"Chart strategy: {strategy_result.strategy.value} — {strategy_result.reason}"
    )

    # Strategy-based direct spec (bypasses Draco for all known patterns).
    # TEMPORAL_SINGLE and FALLBACK_LINE are included unconditionally: Draco consistently
    # picks scatter/point for time-series data regardless of color_dim, ignoring the
    # strategy result. build_temporal_single_spec always produces the correct output.
    bypass_strategies = {
        viz_config.ChartStrategy.DISTRIBUTION,
        viz_config.ChartStrategy.CROSS_SECTIONAL,
        viz_config.ChartStrategy.BREAKDOWN_COMPARISON,
        viz_config.ChartStrategy.SMALL_MULTIPLES,
        viz_config.ChartStrategy.HEATMAP,
        viz_config.ChartStrategy.STACKED_AREA,
        viz_config.ChartStrategy.TEMPORAL_SINGLE,
        viz_config.ChartStrategy.FALLBACK_LINE,
    }

    if strategy_result.strategy in bypass_strategies:
        try:
            spec = viz_config.dispatch_spec(
                strategy_result.strategy,
                viz_data,
                chart_title_vl,
                strategy_result,
                unit_measure=raw_unit,
            )
            return _ok(
                await _store_spec(spec),
                source_attribution=source_attribution,
                strategy=strategy_result.strategy.value,
                reason=strategy_result.reason,
            )
        except Exception as e:
            _logger.exception("Strategy builder failed")
            return _err(f"Chart generation failed: {e}")

    # 8. Draco path (temporal_single, fallback)
    try:
        schema = schema_from_dataframe(viz_data)
        facts = dict_to_facts(schema)
    except Exception as e:
        _logger.exception("Error generating schema")
        return _err(f"Error generating data schema: {e}")

    d = Draco()
    program_constraints = ["entity(view,root,view).", "entity(mark,view,m)."]

    if use_default_constraints:
        user_mark_type = viz_config.parse_chart_type_hint(chart_type)
        use_temporal_x, categorical_x_field = viz_config.should_use_temporal_x_axis(
            viz_data, chart_type, viz_data.columns.tolist()
        )

        if use_temporal_x and "year" in viz_data.columns:
            program_constraints += [
                "entity(encoding,m,e1).",
                "attribute((encoding,channel),e1,x).",
                "attribute((encoding,field),e1,year).",
            ]
        elif not use_temporal_x and categorical_x_field:
            program_constraints += [
                "entity(encoding,m,e1).",
                "attribute((encoding,channel),e1,x).",
                f"attribute((encoding,field),e1,{categorical_x_field}).",
            ]
        elif "year" in viz_data.columns:
            program_constraints += [
                "entity(encoding,m,e1).",
                "attribute((encoding,channel),e1,x).",
                "attribute((encoding,field),e1,year).",
            ]

        if "value" in viz_data.columns:
            program_constraints += [
                "entity(encoding,m,e2).",
                "attribute((encoding,channel),e2,y).",
                "attribute((encoding,field),e2,value).",
            ]

        # Color dimension: prefer country, then standard disagg dims, then custom breakdowns.
        color_dim = strategy_result.color_dim
        if not color_dim:
            for dim in ["country", *_VIZ_DISAGG_DIMS]:
                if dim in viz_data.columns and viz_data[dim].nunique() > 1:
                    color_dim = dim
                    break

        if color_dim:
            program_constraints += [
                "entity(encoding,m,e3).",
                "attribute((encoding,channel),e3,color).",
                f"attribute((encoding,field),e3,{color_dim}).",
            ]

        if chart_type:
            program_constraints.append(f"attribute((mark,type),m,{user_mark_type}).")

    if custom_constraints:
        program_constraints.extend(custom_constraints)

    program = "\n".join(facts) + "\n" + "\n".join(program_constraints)

    try:
        model = next(d.complete_spec(program))
        draco_spec = answer_set_to_dict(model.answer_set)

        if "view" in draco_spec:
            for view in draco_spec["view"]:
                if "mark" in view:
                    for mark in view["mark"]:
                        if "encoding" in mark:
                            for enc in mark["encoding"]:
                                enc.pop("type", None)

        full_spec = {**schema, **draco_spec}
        renderer = AltairRenderer()
        chart = renderer.render(spec=full_spec, data=viz_data)
        chart = chart.properties(title=chart_title_vl).interactive()

        # Structured tooltips
        mark_type_for_tt = viz_config.parse_chart_type_hint(chart_type)
        structured_tooltips = viz_config.build_structured_tooltips(
            list(viz_data.columns), mark_type_for_tt, viz_data=viz_data
        )
        chart = chart.encode(tooltip=[alt.Tooltip(**t) for t in structured_tooltips])

        vl_spec = chart.to_dict()

        # Patch color type: nominal for all known categorical dims.
        # Without this, Draco sometimes assigns 'ordinal' to breakdown/sex dims.
        if "encoding" in vl_spec and "color" in vl_spec["encoding"]:
            _nominal_color_dims = {"country", "ref_area", *_VIZ_DISAGG_DIMS}
            if color_dim in _nominal_color_dims:
                vl_spec["encoding"]["color"]["type"] = "nominal"

        # Post-processing rules
        for rule in viz_config.POST_PROCESSING_RULES:
            vl_spec = rule.apply(vl_spec, data_frequency, raw_unit or None)

        out_reason = strategy_result.reason
        if strategy_result.strategy == viz_config.ChartStrategy.TEMPORAL_SINGLE:
            resolved_mark = viz_config.extract_top_level_mark_type(vl_spec)
            if resolved_mark:
                out_reason = viz_config.patch_strategy_reason_chart_phrase(
                    strategy_result.reason, resolved_mark
                )

        return _ok(
            await _store_spec(vl_spec),
            source_attribution=source_attribution,
            strategy=strategy_result.strategy.value,
            reason=out_reason,
        )

    except StopIteration:
        _logger.warning("Draco failed → fallback")
        # Strategy-aware fallback
        try:
            spec = viz_config.dispatch_spec(
                viz_config.ChartStrategy.FALLBACK_LINE,
                viz_data,
                chart_title_vl,
                strategy_result,
                unit_measure=raw_unit,
            )
            return _ok(
                await _store_spec(spec),
                warning=_FALLBACK_WARNING,
                source_attribution=source_attribution,
                strategy=strategy_result.strategy.value,
                reason=strategy_result.reason,
            )
        except Exception as fallback_err:
            _logger.exception(f"Fallback failed: {fallback_err}")
            return _err(
                "Error: Draco could not determine a suitable visualization, and fallback failed."
            )

    except Exception as e:
        _logger.exception(f"Draco error: {e}")
        return _err(f"Error generating visualization: {e}")


# ============================================================================
# TOOL: get_multi_indicator_viz_spec (NEW)
# ============================================================================


async def get_multi_indicator_viz_spec(
    indicator_ids: list[dict[str, str]] | None = None,
    country_code: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    disaggregation_filters: dict[str, str | None] | None = None,
    chart_type: str | None = None,
) -> VizResult:
    """Generate a Vega-Lite chart comparing multiple Data360 indicators.

    REQUIRED for success: indicator_ids (2–4 entries). Call data360_search_indicators first,
    then pass each series as {"database_id": "...", "indicator_id": "..."}. If you omit
    indicator_ids or pass fewer than 2 entries, this tool returns {"error": "..."} — fix
    the arguments and call again (do not rely on country_code alone).

    Use for: scatterplots (2 indicators vs each other), layered/dual-axis line charts
    (2-3 indicators over time in one country), connected scatter (trajectory charts).

    ## Grammar of Graphics Contract

    The pipeline maps data dimensions to Vega-Lite aesthetic channels automatically.
    DO NOT pre-filter a dimension to simplify the chart — that collapses multi-series
    data into a single undifferentiated line and silently discards information.

    ### disaggregation_filters decision rule

    disaggregation_filters applies to ALL indicators in this call. Only pin a dimension
    when the user has explicitly requested a specific value:

      CORRECT — user asked for females only:
        disaggregation_filters={"SEX": "F"}

      CORRECT — force aggregate totals (suppress breakdown display):
        disaggregation_filters={"SEX": "_T"}

      WRONG — do not pre-filter to reduce chart complexity:
        disaggregation_filters={"COMP_BREAKDOWN_1": "WGI_EST"}  # silently drops other series

    When a dimension has multiple meaningful values and the user has not requested a
    specific one, OMIT it from disaggregation_filters. The pipeline will detect
    non-trivial values (anything other than "_T" or "_Z") and choose the correct
    Vega-Lite channel for them.

    ### Chart strategy → Vega-Lite encoding table

    Strategy              | When selected                                       | Vega-Lite encoding
    ----------------------|-----------------------------------------------------|-------------------------------------------
    CORRELATION           | 2 indicators, >1 country, single year               | x=indicator1(Q), y=indicator2(Q), color=country(N) (scatter)
    CORRELATION_TEMPORAL  | 2 indicators, >1 country, multi-year                | x=indicator1(Q), y=indicator2(Q), color=country(N), order=year (connected scatter)
    TEMPORAL_MULTI_IND    | 2-4 indicators, 1 country or 3+ indicators          | layered lines, independent y-scales per indicator
    STACKED_AREA          | chart_type="area"/"stacked_area", composition Q     | x=year(temporal), y=value(Q) stacked, color=indicator(N)

    ### High-cardinality guidance

    DO NOT reduce indicator_ids or disaggregation_filters to simplify the output.
    Pass the full set of indicators the user asked about. The pipeline will:
    - Merge all indicator series into a single aligned DataFrame
    - Auto-select the correct strategy (scatter, layered lines, stacked area)
    - Cap series count if needed and annotate the subtitle with a trim note

    ### Visual channel hierarchy (perception accuracy)

    Channels are ranked by how accurately viewers read encoded values:

    Channel           | Type        | Used for
    ------------------|-------------|----------------------------------------
    Position (x/y)    | Highest     | Quantitative values, time axis
    Color (hue)       | Medium      | Nominal categories (country, indicator)
    Color (lightness) | Medium      | Not used for multi-indicator charts
    Size / Shape      | Low         | Not used in current strategies

    The pipeline always maps quantitative values → position (y-axis) and nominal
    categories → color (hue). Do not override this with custom disaggregation_filters.

    ### Encoding type rules (Vega-Lite v5)

    - Year fields: type="temporal", format="%Y". Never "ordinal" for years.
    - Country / breakdown fields: type="nominal"
    - Numeric values: type="quantitative", scale.zero=False for non-ratio data
    - Multi-indicator layers: each indicator gets its own y-axis (left/right), its own
      WB categorical color. Resolved with resolve.scale.y="independent".
    - Connected scatter uses order channel (order=year, type=temporal) to draw
      trajectory lines in chronological order.

    Args:
        indicator_ids: List of dicts, each with "database_id" and "indicator_id".
            Example: [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_DYN_LE00_IN"}
            ]
        country_code: Optional ISO code(s): one code or semicolon-separated (e.g. KEN;MAR)
            or comma-separated; normalized for the Data API like data360_get_data.
        start_year: Optional start year (inclusive).
        end_year: Optional end year (inclusive).
        disaggregation_filters: Optional filters applied to ALL indicators; values are str or null.
            See grammar of graphics contract above — only pin a dimension when the user
            explicitly requested a specific value. Omitting a dimension fetches all values
            and lets the pipeline choose the correct Vega-Lite channel automatically.
            REF_AREA uses comma-separated ISO codes (semicolons normalized to commas).
        chart_type: Optional hint — "scatter", "connected_scatter", "layered_lines",
            "line", "bar", "area", "stacked_area". If omitted, auto-selected by data shape.

            ## chart_type decision rule

            Only pass "area" or "stacked_area" when the user's question implies
            **composition or share over time** — i.e., the multiple indicators together
            add up to a meaningful whole (e.g., age groups summing to total population,
            electricity sources summing to total generation).
            Typical signal words: "breakdown of", "composition of", "share of",
            "proportion", "structure of".

            CORRECT — user asked about composition across multiple indicators:
              chart_type="stacked_area"   # "Show the age group breakdown in Japan"

            WRONG — user asked about a trend:
              chart_type="area"           # "How has GDP and poverty changed?" ← use default

            For trend or comparison questions, omit chart_type and let the pipeline
            select the correct strategy (layered lines, scatter, etc.).

    Returns:
        Dict with "url" (chart URL on success), "error" (on failure),
        "strategy" (which chart type was chosen), "warning" (if applicable).
    """
    if indicator_ids is None or len(indicator_ids) < 2:
        return _err(
            "indicator_ids is required: pass a JSON array of 2–4 objects, each "
            '{"database_id":"<db>","indicator_id":"<id>"} from data360_search_indicators '
            "(use idno + database_id). Example: "
            '[{"database_id":"WB_WDI","indicator_id":"WB_WDI_NY_GDP_PCAP_KD"},'
            '{"database_id":"WB_WDI","indicator_id":"WB_WDI_SP_DYN_LE00_IN"}]. '
            "Then add country_code, start_year, end_year as needed. "
            "Do not call this tool with only country_code or chart_type."
        )
    if len(indicator_ids) > 4:
        return _err("Maximum 4 indicators supported in one chart.")

    # 1. Fetch all indicators concurrently
    tasks = [
        _fetch_single_indicator(
            ind["database_id"],
            ind["indicator_id"],
            country_code,
            start_year,
            end_year,
            disaggregation_filters,
        )
        for ind in indicator_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    dfs: list[pd.DataFrame] = []
    titles: list[str] = []
    units: list[str] = []
    indicator_col_names: list[str] = []
    used_cols: set[str] = set()

    for i, (res, ind) in enumerate(zip(results, indicator_ids)):
        if isinstance(res, Exception):
            return _err(f"Failed to fetch indicator {ind['indicator_id']}: {res}")
        df, title, unit = res
        if df.empty:
            return _err(f"No data returned for indicator {ind['indicator_id']}.")

        ind_name = title or ind["indicator_id"]
        col_base = _slugify(ind_name)
        col = _make_unique_col(col_base, used_cols)
        used_cols.add(col)

        dfs.append(df)
        titles.append(ind_name)
        units.append(unit or "")
        indicator_col_names.append(col)

    # 2. Standardize each DataFrame
    std_dfs: list[pd.DataFrame] = []
    for df, col in zip(dfs, indicator_col_names):
        # Lowercase columns
        df.columns = [c.lower() for c in df.columns]

        # Parse time
        if "time_period" in df.columns:
            try:
                df["time_period"] = pd.to_datetime(df["time_period"])
            except Exception:
                pass

        # Coerce obs_value
        if "obs_value" in df.columns:
            df["obs_value"] = pd.to_numeric(df["obs_value"], errors="coerce")

        # Rename to standard
        df = df.rename(
            columns={"time_period": "year", "obs_value": col, "ref_area": "country"}
        )

        # Keep only join keys + value column
        keep = [
            c
            for c in ["year", "country", *_VIZ_DISAGG_DIMS]
            if c in df.columns
        ]
        keep.append(col)
        std_dfs.append(df[keep])

    # 3. Map country codes (use first df's country column as reference)
    try:
        from data360.providers import get_codelist_mapping

        country_map = await get_codelist_mapping("REF_AREA")
        for df in std_dfs:
            if "country" in df.columns:
                df["country"] = df["country"].map(lambda x: country_map.get(x, x))
    except Exception as e:
        _logger.warning(f"Country code mapping failed: {e}")

    # 4. Merge on common keys
    join_keys = [
        c
        for c in ["year", "country", *_VIZ_DISAGG_DIMS]
        if all(c in df.columns for df in std_dfs)
    ]

    if not join_keys:
        return _err(
            "Indicators could not be merged: no common dimensions (for example, one "
            "series is time-only and another is geography-only). Choose indicators "
            "that share at least one of: year, country, or the same disaggregation "
            "columns."
        )

    merged = std_dfs[0]
    for df in std_dfs[1:]:
        merged = pd.merge(merged, df, on=join_keys, how="outer")

    if merged.empty:
        return _err("No overlapping data found across indicators after merging.")

    merged = _sanitize_dataframe_for_json_records(merged)

    import textwrap

    # 5. Build chart title (with subtitle when all indicators share the same unit)
    # GoG / AntVis guideline: Do not arbitrarily truncate strings with ellipses.
    # Instead, preserve the full text but word-wrap it so it fits the chart width.
    if len(titles) == 2:
        full_title = f"{titles[0]} vs. {titles[1]}"
    else:
        full_title = " | ".join(titles)

    # Wrap at 80 characters to ensure it fits safely within standard chart widths
    chart_title = textwrap.wrap(full_title, width=80)

    unique_units = list(dict.fromkeys(u for u in units if u))
    shared_unit = unique_units[0] if len(unique_units) == 1 else ""
    chart_title_vl: str | dict = viz_config.build_chart_title_with_context(
        chart_title, shared_unit or None, merged
    )

    # 6. Build indicator_labels for axis/tooltip
    def _format_label(t: str, u: str | None) -> str:
        if not u:
            return t
        # Prevent redundant units like "GDP (annual % growth) (%)"
        if str(u).lower() in str(t).lower():
            return t
        return f"{t} ({u})"

    indicator_labels = {
        col: _format_label(title, unit)
        for col, title, unit in zip(indicator_col_names, titles, units)
    }

    # 7. Select strategy
    strategy_result = viz_config.select_strategy(
        merged,
        n_indicators=len(indicator_ids),
        chart_type_hint=chart_type,
        indicator_cols=indicator_col_names,
    )
    _logger.info(
        f"Multi-indicator strategy: {strategy_result.strategy.value} — {strategy_result.reason}"
    )

    # 7b. Reshape for stacked area: melt wide → long
    # build_stacked_area_spec expects a DataFrame with a single "value" column and a
    # "indicator" color column, not the wide merged layout produced by the join above.
    spec_df = merged
    if strategy_result.strategy == viz_config.ChartStrategy.STACKED_AREA:
        id_cols = [c for c in merged.columns if c not in indicator_col_names]
        spec_df = merged.melt(
            id_vars=id_cols,
            value_vars=indicator_col_names,
            var_name="indicator",
            value_name="value",
        )
        # Map internal slugified column names back to human-readable indicator titles
        slug_to_title = dict(zip(indicator_col_names, titles))
        spec_df["indicator"] = spec_df["indicator"].map(slug_to_title)
        spec_df = spec_df.dropna(subset=["value"])
        # Propagate the color_dim so the builder picks up the indicator column
        strategy_result = viz_config.StrategyResult(
            viz_config.ChartStrategy.STACKED_AREA,
            strategy_result.reason,
            indicator_cols=strategy_result.indicator_cols,
            color_dim="indicator",
        )

    # 7c. Reshape for grouped bar (multi-indicator path): melt wide → long.
    # build_breakdown_comparison_spec expects df["value"] + df[color_dim].
    # When color_dim="indicator" the wide merged frame must be melted so each
    # (country, indicator) pair becomes a row with a single "value" and an
    # "indicator" label column used as the xOffset grouping key.
    elif (
        strategy_result.strategy == viz_config.ChartStrategy.BREAKDOWN_COMPARISON
        and strategy_result.color_dim == "indicator"
    ):
        id_cols = [c for c in merged.columns if c not in indicator_col_names]
        spec_df = merged.melt(
            id_vars=id_cols,
            value_vars=indicator_col_names,
            var_name="indicator",
            value_name="value",
        )
        slug_to_title = dict(zip(indicator_col_names, titles))
        spec_df["indicator"] = spec_df["indicator"].map(slug_to_title)
        spec_df = spec_df.dropna(subset=["value"])

    # 8. Build spec
    try:
        spec = viz_config.dispatch_spec(
            strategy_result.strategy,
            spec_df,
            chart_title_vl,
            strategy_result,
            indicator_labels=indicator_labels,
            y_label=indicator_labels.get(indicator_col_names[1], "Value"),
            x_label=indicator_labels.get(indicator_col_names[0], "Value"),
            unit_measure=shared_unit or None,
        )
    except Exception as e:
        _logger.exception(f"Spec build failed: {e}")
        return _err(f"Error building chart spec: {e}")

    # 9. Store and return
    try:
        db_map_multi = await get_database_mapping()
    except Exception as e:
        _logger.warning(f"Could not load database mapping for source attribution: {e}")
        db_map_multi = {}
    db_displays = [
        db_map_multi.get(ind["database_id"], ind["database_id"])
        for ind in indicator_ids
    ]
    unique_db_displays = list(dict.fromkeys(db_displays))
    database_display_multi = (
        unique_db_displays[0]
        if len(unique_db_displays) == 1
        else " · ".join(unique_db_displays)
    )
    indicator_display_multi = " | ".join(titles)
    ids_joined = " · ".join(ind["indicator_id"] for ind in indicator_ids)
    dbs_ids_joined = " · ".join(
        dict.fromkeys(ind["database_id"] for ind in indicator_ids)
    )
    source_attribution_multi: dict[str, str] = {
        "database_id": dbs_ids_joined,
        "database_name": database_display_multi,
        "indicator_id": ids_joined,
        "indicator_name": indicator_display_multi,
    }

    url = await _store_spec(spec)
    return _ok(
        url,
        source_attribution=source_attribution_multi,
        strategy=strategy_result.strategy.value,
        reason=strategy_result.reason,
    )
