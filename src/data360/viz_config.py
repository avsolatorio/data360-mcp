"""
Visualization Configuration Module

Centralizes all rules, strategies, spec builders, and style tokens for the
Data360 visualization system.

Design principles:
  - World Bank Data Visualization Style Guide (colors, typography, grid)
  - FT Visual Vocabulary (chart-type selection by data relationship)
  - All functions here are pure (no async, no I/O) → fully unit-testable
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from numbers import Integral
from typing import Any, Literal

import pandas as pd

# Temporal frequency detected from TIME_PERIOD column values.
# Governs how the year column is formatted and how x-axis timeUnit/format
# is set in Vega-Lite.
TemporalFreq = Literal["annual", "quarterly", "monthly", "daily"]

# ============================================================================
# WORLD BANK COLOR PALETTE
# Source: https://worldbank.github.io/data-visualization-style-guide/colors
# ============================================================================

WB_CAT_COLORS: list[str] = [
    "#34A7F2",  # cat1 – blue
    "#FF9800",  # cat2 – orange
    "#664AB6",  # cat3 – purple
    "#4EC2C0",  # cat4 – teal
    "#F3578E",  # cat5 – pink
    "#081079",  # cat6 – navy
    "#0C7C68",  # cat7 – dark green
    "#AA0000",  # cat8 – red
    "#DDDA21",  # cat9 – yellow
]

WB_REGION_COLORS: dict[str, str] = {
    "NAC": "#34A7F2",
    "SSF": "#FF9800",
    "MEA": "#664AB6",
    "SAS": "#4EC2C0",
    "EAS": "#F3578E",
    "LCN": "#0C7C68",
    "ECS": "#AA0000",
    "AFW": "#DDDA21",
    "AFE": "#FF9800",
    "WLD": "#081079",
}

WB_GENDER_COLORS: dict[str, str] = {
    "F": "#FF9800",
    "M": "#664AB6",
    "_T": "#4EC2C0",
    "female": "#FF9800",
    "male": "#664AB6",
}

WB_INCOME_COLORS: dict[str, str] = {
    "HIC": "#016B6C",
    "UMC": "#73AF48",
    "LMC": "#DB95D7",
    "LIC": "#3B4DA6",
}

WB_SEQ_GOOD: list[str] = ["#FDF6DB", "#A1CBCF", "#5D99C2", "#2868A0", "#023B6F"]
WB_SEQ_BAD: list[str] = ["#E3F6FD", "#91C5F0", "#8B8AC0", "#88506E", "#691B15"]
WB_SEQ_BLUE: list[str] = ["#E3F6FD", "#75CCEC", "#089BD4", "#0169A1", "#023B6F"]
WB_DIV_DEFAULT: list[str] = [
    "#920000",
    "#BD6126",
    "#E3A763",
    "#EFEFEF",
    "#80BDE7",
    "#3587C3",
    "#025288",
]

WB_TEXT = "#111111"
WB_TEXT_SUBTLE = "#666666"
WB_GRID_COLOR = "#CED4DE"
WB_ZERO_COLOR = "#8A969F"
WB_REFERENCE = "#8A969F"
WB_NO_DATA = "#CED4DE"
WB_WHITE = "#FFFFFF"
WB_BACKGROUND = "#FFFFFF"
WB_FONT_FAMILY = "Noto Sans, Arial, sans-serif"


# ============================================================================
# WB ALTAIR THEME CONFIG
# ============================================================================


def wb_altair_config() -> dict:
    """Return World Bank style config dict for injection into Vega-Lite specs."""
    return {
        "background": WB_BACKGROUND,
        "font": WB_FONT_FAMILY,
        "title": {
            "fontSize": 16,
            "fontWeight": "bold",
            "color": WB_TEXT,
            # AntVis component guideline: use absolute px line-height for predictable wrapping.
            # ratio (1.2) causes tight stacking when title wraps to 2 lines.
            "lineHeight": 22,
            "anchor": "start",
            "offset": 8,
            "subtitleFontSize": 12,
            "subtitleColor": WB_TEXT_SUBTLE,
            "subtitleFontWeight": "normal",
            "subtitlePadding": 4,
            # Breathing room between each subtitle part (geography / unit / breakdown note).
            "subtitleLineHeight": 18,
        },
        "axis": {
            "labelColor": WB_TEXT_SUBTLE,
            "labelFontSize": 12,
            "labelFont": WB_FONT_FAMILY,
            "titleColor": WB_TEXT,
            "titleFontSize": 12,
            "titleFont": WB_FONT_FAMILY,
            "titleFontWeight": "bold",
            "gridColor": WB_GRID_COLOR,
            "gridDash": [4, 2],
            "gridWidth": 1,
            "domainColor": WB_GRID_COLOR,
            "tickColor": WB_GRID_COLOR,
            "tickCount": 5,
            "labelOverlap": "greedy",
        },
        "legend": {
            "labelColor": WB_TEXT,
            "labelFont": WB_FONT_FAMILY,
            "labelFontSize": 12,
            "labelFontWeight": "bold",
            "labelLimit": 300,
            "titleColor": WB_TEXT,
            "titleFont": WB_FONT_FAMILY,
            "titleFontSize": 12,
            "orient": "top",
            "direction": "horizontal",
        },
        "range": {"category": WB_CAT_COLORS},
        "view": {"stroke": "transparent"},
        "line": {"strokeWidth": 3, "strokeCap": "round"},
        "point": {"size": 60, "stroke": WB_WHITE, "strokeWidth": 1},
        "bar": {"cornerRadiusTopLeft": 2, "cornerRadiusTopRight": 2},
    }


def inject_wb_config(vl_spec: dict) -> dict:
    """Merge WB style config into a Vega-Lite spec without overwriting user settings."""
    wb_cfg = wb_altair_config()
    if "config" not in vl_spec:
        vl_spec["config"] = wb_cfg
    else:
        for section, props in wb_cfg.items():
            if section not in vl_spec["config"]:
                vl_spec["config"][section] = props
            elif isinstance(props, dict) and isinstance(
                vl_spec["config"].get(section), dict
            ):
                for k, v in props.items():
                    vl_spec["config"][section].setdefault(k, v)
    return vl_spec


# ============================================================================
# STRUCTURED TOOLTIPS
# ============================================================================

# ``year`` / ``time_period`` are built in ``build_structured_tooltips`` from ``viz_data``:
# marking them ``temporal`` when values are plain strings like "2018" makes Vega-Lite parse
# the field as dates for all encodings, so an ordinal x-axis shows epoch milliseconds.
_TOOLTIP_SPECS: dict[str, dict] = {
    "value": {"title": "Value", "format": ",.2f", "type": "quantitative"},
    "country": {"title": "Country", "type": "nominal"},
    "sex": {"title": "Sex", "type": "nominal"},
    "age": {"title": "Age Group", "type": "nominal"},
    "urbanisation": {"title": "Urbanisation", "type": "nominal"},
    "comp_breakdown_1": {"title": "Dimension 1", "type": "nominal"},
    "comp_breakdown_2": {"title": "Dimension 2", "type": "nominal"},
    "comp_breakdown_3": {"title": "Dimension 3", "type": "nominal"},
    "time_period": {"title": "Period", "type": "temporal"},
    "obs_value": {"title": "Value", "format": ",.2f", "type": "quantitative"},
    "ref_area": {"title": "Country", "type": "nominal"},
    "region": {"title": "Region", "type": "nominal"},
}

_TOOLTIP_PRIORITY = [
    "year",
    "time_period",
    "value",
    "obs_value",
    "country",
    "ref_area",
    "region",
    "sex",
    "age",
    "urbanisation",
    "comp_breakdown_1",
    "comp_breakdown_2",
]

_VOWELS = {"a", "e", "i", "o", "u"}


def _year_range_label(year_series: pd.Series) -> str | None:
    """Min–max year label, e.g. ``1990-2024`` or ``2020`` when only one year."""
    if year_series.empty:
        return None
    try:
        if pd.api.types.is_datetime64_any_dtype(year_series):
            ynum = year_series.dt.year
        else:
            ynum = pd.to_numeric(year_series, errors="coerce")
        yvalid = ynum.dropna()
        if yvalid.empty:
            return None
        y0, y1 = int(yvalid.min()), int(yvalid.max())
        return f"{y0}-{y1}" if y0 != y1 else str(y0)
    except (TypeError, ValueError):
        return None


def format_chart_context_subtitle(df: pd.DataFrame) -> str | None:
    """Build geography list + year range for chart subtitle (product-style).

    Example: ``\"Philippines, Belgium, 1990-2024\"``. Long geography lists are truncated.
    """
    parts: list[str] = []
    if "country" in df.columns:
        vals = sorted(
            {str(v).strip() for v in df["country"].dropna() if str(v).strip()},
            key=str.casefold,
        )
        if vals:
            cap = 12
            if len(vals) > cap:
                shown = ", ".join(vals[:10])
                parts.append(f"{shown}, … (+{len(vals) - 10} more)")
            else:
                parts.append(", ".join(vals))
    year_lbl = None
    if "year" in df.columns:
        year_lbl = _year_range_label(df["year"])
    if year_lbl:
        parts.append(year_lbl)
    if not parts:
        return None
    return ", ".join(parts)


def build_chart_title_with_context(
    main_title: str | list[str],
    unit_subtitle: str | None,
    df: pd.DataFrame,
) -> str | dict | list:
    """Vega-Lite title: main text plus subtitle lines (geography + years, unit).

    Subtitle is returned as a **list of strings** so Vega-Lite v5 renders each
    part on its own line. This prevents the single-line overflow that occurs
    when country names, year ranges, units, and trim notes are concatenated.
    """
    ctx = format_chart_context_subtitle(df)
    subtitle_parts: list[str] = []
    if ctx:
        subtitle_parts.append(ctx)
    if unit_subtitle and str(unit_subtitle).strip():
        subtitle_parts.append(str(unit_subtitle).strip())
    if not subtitle_parts:
        return main_title
    return {"text": main_title, "subtitle": subtitle_parts}


# Dimension codes that are custom breakdowns (not standard demographic dims).
_CUSTOM_BREAKDOWN_DIMS = {"comp_breakdown_1", "comp_breakdown_2", "comp_breakdown_3"}


def _generate_color_shades(hex_color: str, n: int) -> list[str]:
    """Return n shades of hex_color spread from dark to light (HSL lightness).

    n=1 → returns the base color unchanged.
    n=2 → [dark, base] (darker shade + original).
    n=3 → [dark, base, light].
    n>3 → evenly distributed from 0.28 L to 0.75 L.
    """
    import colorsys
    if n <= 0:
        return []
    if n == 1:
        return [hex_color]
    h_str = hex_color.lstrip("#")
    r, g, b = (int(h_str[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    shades: list[str] = []
    for i in range(n):
        factor = i / (n - 1)
        new_l = 0.28 + factor * 0.47  # 0.28 (dark) → 0.75 (light)
        nr, ng, nb = colorsys.hls_to_rgb(h, new_l, min(s, 0.90))
        shades.append(f"#{int(nr * 255):02x}{int(ng * 255):02x}{int(nb * 255):02x}")
    return shades


def _compute_legend_layout(labels: list[str], chart_width: int = 680) -> dict:
    """Compute Vega-Lite legend config (orient/direction/columns/labelLimit) from data.

    Uses the number of items, their rendered pixel width, and the chart width to
    determine whether the legend fits in one horizontal row, needs multiple rows
    (grid), or must fall back to a vertical list.

    Approximate rendered width per item at 11 px font:
      6.5 px/char × label_length  +  symbol (20 px)  +  padding (16 px)
    """
    import math
    n = len(labels)
    if n == 0:
        return {"orient": "bottom", "labelFontSize": 11, "symbolSize": 80}
    max_lbl = max(len(l) for l in labels)
    item_px = int(max_lbl * 6.5 + 36)  # estimated rendered width per item
    items_per_row = max(1, chart_width // item_px)

    base = {"labelFontSize": 11, "symbolSize": 80}

    if n <= items_per_row:
        # Everything fits in one row → horizontal, single row
        return {**base, "orient": "bottom", "direction": "horizontal",
                "labelLimit": max(150, item_px - 36)}

    if items_per_row >= 2:
        # Multi-row grid — aim for ≤3 rows to keep legend compact
        cols = min(items_per_row, max(2, math.ceil(n / 3)))
        return {**base, "orient": "bottom", "direction": "horizontal",
                "columns": cols, "labelLimit": max(150, item_px - 36)}

    # Labels too long for horizontal → vertical list
    return {**base, "orient": "bottom", "direction": "vertical", "labelLimit": 0}


def _estimate_legend_height(
    n_items: int,
    layout: dict,
    has_title: bool = True,
) -> int:
    """Estimate legend pixel height from the layout dict returned by _compute_legend_layout.

    Used to shrink panel heights so the total figure height stays within budget.
    """
    import math
    direction = layout.get("direction", "vertical")
    columns = layout.get("columns", 0)
    row_px = 22   # height per legend row (symbol + label + vertical gap)
    title_px = 20 if has_title else 0
    padding = 16  # top + bottom padding inside the legend box

    if direction == "horizontal" and columns:
        rows = math.ceil(n_items / columns)
    elif direction == "horizontal":
        rows = 1
    else:
        rows = n_items

    return title_px + rows * row_px + padding



def _detect_scale_incompatibility(
    df: pd.DataFrame,
    breakdown_dim: str,
    magnitude_threshold: float = 1.5,
) -> bool:
    """Return True when breakdown series have incompatible Y-axis scales.

    Computes the order of magnitude (log10 of max |value|) for each
    breakdown series. If the spread between the largest and smallest
    magnitudes exceeds *magnitude_threshold*, the series cannot share a
    Y-axis without visually compressing the small-magnitude series.

    A threshold of 1.5 corresponds to roughly a 30× difference between
    the dominant series and the smallest (e.g., a WGI percentile rank
    peaking at ~65 vs. a standard error peaking at ~0.2).

    Only meaningful for *_CUSTOM_BREAKDOWN_DIMS*; standard demographic
    dims (sex, age) almost always share a unit and should never fire.

    Returns False when:
    - breakdown_dim is not in df.columns or 'value' is missing
    - fewer than 2 unique breakdown values are present
    - all series are zero or NaN (no meaningful magnitudes to compare)

    Examples::

        WGI: EST max|val|≈0.6 (mag≈-0.22), SC max|val|≈65 (mag≈1.81)
        spread = 1.81 − (−0.22) = 2.03  → True  (exceeds 1.5)

        IPC phases: all person counts, max|val|∈[1000, 5000]
        mags ≈ [3.0, 3.5, 3.7], spread = 0.7  → False
    """
    import math

    if breakdown_dim not in df.columns or "value" not in df.columns:
        return False
    bd_vals = df[breakdown_dim].dropna().unique()
    if len(bd_vals) < 2:
        return False

    mags: list[float] = []
    for v in bd_vals:
        series_vals = df.loc[df[breakdown_dim] == v, "value"].dropna()
        if series_vals.empty:
            continue
        max_abs = float(series_vals.abs().max())
        if max_abs == 0:
            mags.append(0.0)
        else:
            mags.append(math.log10(max_abs))

    if len(mags) < 2:
        return False
    return (max(mags) - min(mags)) >= magnitude_threshold


def _format_breakdown_subtitle(df: pd.DataFrame, color_dim: str | None) -> str | None:
    """Return a compact subtitle note when color_dim is a heterogeneous custom breakdown.

    Appended to chart subtitles so end users can see which series are present
    and understand they may carry different units or scales.

    Returns None when:
    - color_dim is a standard dimension (country, sex, age, …)
    - there is only one unique breakdown value
    - series share a compatible scale (log10 magnitude spread ≤ 1.5) — the
      unit warning is suppressed because _detect_scale_incompatibility returns
      False.  This correctly handles summary-measure breakdowns such as
      "Arithmetic mean" vs "Median" which share the same currency unit.
    """
    if color_dim not in _CUSTOM_BREAKDOWN_DIMS:
        return None
    if color_dim not in df.columns:
        return None
    vals = sorted(str(v) for v in df[color_dim].dropna().unique())
    if len(vals) <= 1:
        return None
    series_list = ", ".join(vals)
    # Use the quantitative check (log10 magnitude spread) instead of the
    # trailing-digit string heuristic. This avoids false positives for
    # human-readable labels that happen not to end in a digit.
    if _detect_scale_incompatibility(df, color_dim):
        return f"Series: {series_list} — series may have different units/scales"
    return f"Series: {series_list}"


def _append_breakdown_note(
    title: str | dict,
    df: pd.DataFrame,
    color_dim: str | None,
) -> str | dict:
    """Inject breakdown note into a Vega-Lite title dict's subtitle.

    When subtitle is a list (Vega-Lite multi-line form), the note is appended
    as a new line. When subtitle is a string, it is appended with ' · '.
    """
    note = _format_breakdown_subtitle(df, color_dim)
    if not note:
        return title
    if isinstance(title, dict):
        existing = title.get("subtitle", "")
        if isinstance(existing, list):
            return {**title, "subtitle": existing + [note]}
        new_sub = f"{existing} · {note}" if existing else note
        return {**title, "subtitle": new_sub}
    # Plain string title — upgrade to single-line dict.
    return {"text": title, "subtitle": note}


def _cap_cardinality(
    df: pd.DataFrame,
    dim: str,
    max_n: int,
) -> tuple[pd.DataFrame, int | None]:
    """Cap the number of unique values for *dim* to *max_n*.

    Shared utility called by every spec builder that renders one visual element
    per dim value (facet panels, bar rows, color lines).  This is standard
    chart best practice: beyond ~8–12 elements embedded charts overflow the
    chatbot UI and individual items become unreadable.

    Selection strategy: top-N by most-recent data point, ties broken by row
    count (more data = more informative panel).  Rows outside the top-N are
    dropped from the returned DataFrame.

    Args:
        df:    Input DataFrame.  Must have a ``year`` column for recency sort.
        dim:   Dimension column whose cardinality to cap (e.g. ``country``).
        max_n: Maximum number of unique values to retain.

    Returns:
        (trimmed_df, original_n) where *original_n* is the pre-trim count, or
        *None* when no trimming was needed (df is returned unchanged).
    """
    if dim not in df.columns:
        return df, None
    n_total = df[dim].nunique()
    if n_total <= max_n:
        return df, None

    if "year" in df.columns:
        latest = df.groupby(dim)["year"].max()
    else:
        latest = pd.Series(dtype="object", index=df[dim].unique())
    count = df.groupby(dim).size()
    rank = pd.DataFrame(
        {"latest": latest.reindex(count.index).fillna(pd.Timestamp.min), "count": count}
    )
    top = (
        rank.sort_values(["latest", "count"], ascending=False)
        .head(max_n)
        .index.tolist()
    )
    return df[df[dim].isin(top)].copy(), n_total


def _append_trim_note(
    title: str | dict,
    dim_label: str,
    shown: int,
    original: int | None,
) -> str | dict:
    """Inject a 'Showing N of M' note into the chart subtitle when cardinality
    was capped by :func:`_cap_cardinality`.

    No-op when *original* is None (no trimming occurred).
    When subtitle is a list (Vega-Lite multi-line form), the note is appended
    as a new line. When subtitle is a string, it is appended with ' · '.
    """
    if original is None:
        return title
    dim_title = (
        _TOOLTIP_SPECS.get(dim_label, {}).get("title")
        or dim_label.replace("_", " ")
    ).strip().lower()
    # comp_breakdown_* fields use generic "Dimension N" labels in _TOOLTIP_SPECS;
    # for trim notes, the user-facing term should be "breakdown" instead.
    if dim_label.startswith("comp_breakdown_"):
        dim_title = "breakdown"
    # Simple English pluralization for subtitle notes.
    if dim_title.endswith("y") and len(dim_title) > 2 and dim_title[-2] not in _VOWELS:
        dim_plural = f"{dim_title[:-1]}ies"
    elif dim_title.endswith(("s", "x", "z", "ch", "sh")):
        dim_plural = f"{dim_title}es"
    else:
        dim_plural = f"{dim_title}s"
    note = (
        f"Showing {shown} of {original} {dim_plural} by most recent data — "
        "specify a subset for the full view"
    )
    if isinstance(title, dict):
        existing = title.get("subtitle", "")
        if isinstance(existing, list):
            return {**title, "subtitle": existing + [note]}
        return {**title, "subtitle": f"{existing} · {note}" if existing else note}
    return {"text": title, "subtitle": note}


# Shared dimensions for multi-indicator line layers: one value column per layer’s tooltip.
_MULTI_IND_TOOLTIP_DIMS: tuple[str, ...] = (
    "year",
    "time_period",
    "country",
    "ref_area",
    "region",
    "sex",
    "age",
    "urbanisation",
)

# Visible points widen the Vega hit target for line tooltips without a spec API change.
_LINE_HOVER_POINT: dict[str, object] = {"filled": True, "size": 56}


def _multi_indicator_tooltip_columns(
    df_columns: list[str], value_col: str
) -> list[str]:
    colset = set(df_columns)
    out: list[str] = []
    for c in _MULTI_IND_TOOLTIP_DIMS:
        if c in colset:
            out.append(c)
    if value_col in colset and value_col not in out:
        out.append(value_col)
    return out


def _tooltip_spec_for_time_dim(
    col: str,
    viz_data: pd.DataFrame | None,
    temporal_freq: TemporalFreq | None = None,
) -> dict:
    """Return a Vega-Lite tooltip spec for year/time_period columns.

    When a temporal frequency is known (or can be detected from the values),
    the spec uses ``type: temporal`` with the correct timeUnit + format so that
    Vega-Lite formats the internally-parsed epoch timestamp correctly.  Without
    this, charts with a temporal X-axis display the raw millisecond number
    (e.g. 1596240000000) instead of a human-readable date string.
    """
    title = "Year" if col == "year" else "Period"

    # Mapping that mirrors _TEMPORAL_X_ENCODING so tooltip labels match axis labels.
    _FREQ_TOOLTIP: dict[str, dict] = {
        "annual":    {"timeUnit": "year",          "format": "%Y"},
        "monthly":   {"timeUnit": "yearmonth",      "format": "%b %Y"},
        "quarterly": {"timeUnit": "yearquarter",    "format": "Q%q %Y"},
        "daily":     {"timeUnit": "yearmonthdate",  "format": "%Y-%m-%d"},
    }

    freq: TemporalFreq | None = temporal_freq
    if freq is None and viz_data is not None and col in viz_data.columns:
        # Infer from the formatted string values already in the frame.
        freq = _detect_temporal_frequency(viz_data[col])

    if freq is not None:
        cfg = _FREQ_TOOLTIP.get(freq, _FREQ_TOOLTIP["annual"])
        return {
            "field": col,
            "title": title,
            "type": "temporal",
            "timeUnit": cfg["timeUnit"],
            "format": cfg["format"],
        }

    return {"field": col, "title": title, "type": "nominal"}


def build_structured_tooltips(
    columns: list[str],
    mark_type: str,
    indicator_labels: dict[str, str] | None = None,
    value_format: str = ",.2f",
    viz_data: pd.DataFrame | None = None,
    temporal_freq: TemporalFreq | None = None,
    dim_name_labels: dict[str, str] | None = None,
) -> list[dict]:
    """Build typed, labelled tooltip list for a Vega-Lite encoding.

    indicator_labels: optional {col_name: human_label} for indicator value columns
    in multi-indicator charts (e.g. {"gdp_per_capita": "GDP per capita (USD)"}).
    value_format: D3 format string for quantitative value fields.
    viz_data: when set, ``year`` / ``time_period`` frequency is detected from the
        column values to produce correctly formatted temporal tooltip labels.
    temporal_freq: explicit temporal frequency; overrides auto-detection from
        viz_data. Pass ``result.temporal_frequency`` from temporal chart builders
        so the tooltip date format matches the X-axis format exactly.
    dim_name_labels: optional {col_name: human_label} for comp_breakdown_* columns
        sourced from the disaggregation API. Overrides the generic "Dimension N"
        fallback in ``_TOOLTIP_SPECS`` for those fields.
    """
    ordered = [c for c in _TOOLTIP_PRIORITY if c in columns]
    ordered += [c for c in columns if c not in _TOOLTIP_PRIORITY]

    tooltips = []
    for col in ordered:
        if col in ("year", "time_period"):
            tooltips.append(_tooltip_spec_for_time_dim(col, viz_data, temporal_freq))
            continue
        if indicator_labels and col in indicator_labels:
            tip = {
                "field": col,
                "title": indicator_labels[col],
                "format": value_format,
                "type": "quantitative",
            }
        elif col in _TOOLTIP_SPECS:
            spec = _TOOLTIP_SPECS[col]
            # Use the API-sourced dimension name when available, otherwise the
            # generic "Dimension N" fallback from _TOOLTIP_SPECS.
            title = (
                dim_name_labels.get(col)
                if (dim_name_labels and col in dim_name_labels)
                else spec["title"]
            )
            tip = {"field": col, "title": title, "type": spec["type"]}
            if "format" in spec:
                # Use value_format for quantitative value fields
                if col in ("value", "obs_value"):
                    tip["format"] = value_format
                else:
                    tip["format"] = spec["format"]
        else:
            tip = {"field": col, "title": col.replace("_", " ").title()}
        tooltips.append(tip)
    return tooltips


def apply_structured_tooltips(
    vl_spec: dict,
    columns: list[str],
    mark_type: str,
    indicator_labels: dict[str, str] | None = None,
    viz_data: pd.DataFrame | None = None,
) -> dict:
    tips = build_structured_tooltips(
        columns, mark_type, indicator_labels, viz_data=viz_data
    )
    vl_spec.setdefault("encoding", {})["tooltip"] = tips
    return vl_spec


# ============================================================================
# CHART STRATEGY ROUTER  (FT Visual Vocabulary aligned)
# ============================================================================


class ChartStrategy(str, Enum):
    """Named chart strategies mapped to FT Visual Vocabulary categories."""

    TEMPORAL_SINGLE = "temporal_single"  # 1 indicator, ≤8 countries, multi-year → lines
    TEMPORAL_MULTI_IND = (
        "temporal_multi_indicator"  # 2-4 indicators → layered lines (dual Y + offsets)
    )
    CORRELATION = "correlation"  # 2 indicators, multi-country, 1 year → scatter
    CORRELATION_TEMPORAL = "correlation_temporal"  # 2 indicators, multi-country, multi-year → connected scatter
    CROSS_SECTIONAL = (
        "cross_sectional"  # 1 indicator, ≤8 countries, 1 year → horizontal bar
    )
    DISTRIBUTION = "distribution"  # 1 indicator, >8 countries, 1 year → strip/beeswarm
    BREAKDOWN_COMPARISON = (
        "breakdown_comparison"  # 1 indicator, 1 disagg, 2-4 values → grouped bar
    )
    SMALL_MULTIPLES = (
        "small_multiples"  # 1 indicator, 2+ disagg or >4 cntry+breakdown → facet
    )
    HEATMAP = "heatmap"  # dense country x year matrix
    STACKED_AREA = "stacked_area"  # part-to-whole over time
    CHOROPLETH = "choropleth"  # geographic map
    FALLBACK_LINE = "fallback_line"  # anything else


@dataclass
class StrategyResult:
    strategy: ChartStrategy
    reason: str
    # Enriched context the spec builder needs
    indicator_cols: list[str] = field(
        default_factory=list
    )  # value columns for multi-indicator
    color_dim: str | None = None
    facet_dim: str | None = None
    # Secondary color dimension for 3-way combo encoding:
    # When both color_dim and secondary_color_dim are set, the spec builder
    # creates a combo color field = color_dim_value + ' / ' + secondary_color_dim_value
    # using shade families (e.g. IPC phases × countries: 5 shades per country).
    secondary_color_dim: str | None = None
    x_dim: str | None = None
    y_dim: str | None = None
    scale_incompatible: bool = False  # breakdown series need independent Y-axes
    temporal_frequency: TemporalFreq = "annual"  # detected from time_period values
    # Human-readable names for comp_breakdown_* columns sourced from the
    # disaggregation API label_name field; used for legend/tooltip titles.
    dim_name_labels: dict[str, str] = field(default_factory=dict)
    # Carries the user's mark preference ("bar", "line", etc.) from select_strategy
    # to the spec builder, so builders can switch mark type without re-routing.
    mark_hint: str | None = None


from typing import Protocol


@dataclass
class RoutingContext:
    df: pd.DataFrame
    n_indicators: int
    hint: str | None
    ind_cols: list[str]

    # Pre-computed metrics
    year_count: int
    country_count: int
    breakdown_counts: dict[str, int]
    n_breakdowns: int

    @classmethod
    def build(cls, df: pd.DataFrame, n_indicators: int, chart_type_hint: str | None, indicator_cols: list[str] | None) -> RoutingContext:
        hint = parse_chart_type_hint(chart_type_hint)
        cols = set(df.columns)

        year_count = df["year"].nunique() if "year" in cols else 0
        country_count = df["country"].nunique() if "country" in cols else 0

        sex_count = df["sex"].nunique() if "sex" in cols else 0
        age_count = df["age"].nunique() if "age" in cols else 0
        urban_count = df["urbanisation"].nunique() if "urbanisation" in cols else 0
        cb1_count = df["comp_breakdown_1"].nunique() if "comp_breakdown_1" in cols else 0
        cb2_count = df["comp_breakdown_2"].nunique() if "comp_breakdown_2" in cols else 0
        cb3_count = df["comp_breakdown_3"].nunique() if "comp_breakdown_3" in cols else 0
        unit_count = df["unit_measure"].nunique() if "unit_measure" in cols else 0

        breakdown_counts = {
            k: v
            for k, v in [
                ("sex", sex_count),
                ("age", age_count),
                ("urbanisation", urban_count),
                ("comp_breakdown_1", cb1_count),
                ("comp_breakdown_2", cb2_count),
                ("comp_breakdown_3", cb3_count),
                ("unit_measure", unit_count),
            ]
            if v > 1
        }

        return cls(
            df=df,
            n_indicators=n_indicators,
            hint=hint,
            ind_cols=indicator_cols or [],
            year_count=year_count,
            country_count=country_count,
            breakdown_counts=breakdown_counts,
            n_breakdowns=len(breakdown_counts)
        )

class RoutingRule(Protocol):
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None: ...

class ExplicitScatterRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.hint in ("point", "scatter", "connected_scatter") and ctx.n_indicators == 2 and len(ctx.ind_cols) == 2:
            if ctx.year_count > 1:
                return StrategyResult(
                    ChartStrategy.CORRELATION_TEMPORAL,
                    "User requested scatter; 2 indicators, multi-year → connected scatter",
                    indicator_cols=ctx.ind_cols,
                    color_dim="country" if ctx.country_count > 0 else None,
                )
            return StrategyResult(
                ChartStrategy.CORRELATION,
                "User requested scatter; 2 indicators, single year → scatterplot",
                indicator_cols=ctx.ind_cols,
                color_dim="country" if ctx.country_count > 0 else None,
            )
        return None

class ExplicitStackedAreaMultiIndicatorRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.hint in ("area", "stacked_area") and ctx.n_indicators >= 2 and len(ctx.ind_cols) >= 2:
            if ctx.year_count > 1:
                return StrategyResult(
                    ChartStrategy.STACKED_AREA,
                    f"User requested stacked area; {ctx.n_indicators} indicators, {ctx.year_count} years → stacked area chart",
                    indicator_cols=ctx.ind_cols,
                    color_dim="indicator",
                )
        return None

class ExplicitMapRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.hint in ("map", "choropleth", "geoshape"):
            if ctx.country_count > 0:
                return StrategyResult(
                    ChartStrategy.CHOROPLETH,
                    f"User requested map; {ctx.country_count} countries → choropleth map",
                    indicator_cols=ctx.ind_cols,
                )
        return None

class TwoIndicatorRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.n_indicators == 2 and len(ctx.ind_cols) == 2:
            if ctx.year_count <= 1 and ctx.country_count > 1:
                if ctx.hint == "bar":
                    return StrategyResult(
                        ChartStrategy.BREAKDOWN_COMPARISON,
                        f"User requested bar; 2 indicators, {ctx.country_count} countries, single year → grouped bar",
                        indicator_cols=ctx.ind_cols,
                        color_dim="indicator",
                    )
                return StrategyResult(
                    ChartStrategy.CORRELATION,
                    f"2 indicators, {ctx.country_count} countries, single year → scatterplot",
                    indicator_cols=ctx.ind_cols,
                    color_dim="country",
                    x_dim=ctx.ind_cols[0],
                    y_dim=ctx.ind_cols[1],
                )
            if ctx.year_count > 1 and ctx.country_count > 1:
                return StrategyResult(
                    ChartStrategy.SMALL_MULTIPLES,
                    f"2 indicators, {ctx.country_count} countries, {ctx.year_count} years → small multiples",
                    indicator_cols=ctx.ind_cols,
                    color_dim="indicator",
                    facet_dim="country",
                )
            return StrategyResult(
                ChartStrategy.TEMPORAL_MULTI_IND,
                f"2 indicators, 1 country, {ctx.year_count} years → layered lines",
                indicator_cols=ctx.ind_cols,
            )
        return None

class ThreePlusIndicatorRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.n_indicators >= 2 and len(ctx.ind_cols) >= 2:
            return StrategyResult(
                ChartStrategy.TEMPORAL_MULTI_IND,
                f"{ctx.n_indicators} indicators → layered lines",
                indicator_cols=ctx.ind_cols,
            )
        return None

class StackedAreaRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.hint in ("area", "stacked_area") and "unit_measure" not in ctx.breakdown_counts:
            if ctx.year_count > 1:
                color_dim = None
                if ctx.breakdown_counts:
                    color_dim = list(ctx.breakdown_counts.keys())[0]
                elif ctx.country_count > 1:
                    color_dim = "country"
                return StrategyResult(
                    ChartStrategy.STACKED_AREA,
                    f"User requested area; {ctx.year_count} years → stacked area chart",
                    color_dim=color_dim,
                )
        return None

class ExplicitHeatmapRule:
    """Honour an explicit ``heatmap`` hint from the caller.

    Requires multiple time periods so there is a meaningful country-x-year
    matrix.  Single-year requests fall through to the auto-routing rules
    (usually CrossSectional / BreakdownComparison).
    """

    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.hint == "heatmap" and ctx.year_count > 1 and ctx.country_count > 0:
            return StrategyResult(
                ChartStrategy.HEATMAP,
                f"User requested heatmap; {ctx.country_count} countries, {ctx.year_count} years → heatmap",
                color_dim="value",
            )
        return None


class HeatmapRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.country_count > HIGH_CARDINALITY_THRESHOLDS["beeswarm_threshold"] and ctx.year_count > 1:
            if ctx.n_breakdowns == 0:
                return StrategyResult(
                    ChartStrategy.HEATMAP,
                    f"{ctx.country_count} countries, {ctx.year_count} years → heatmap",
                    color_dim="value",
                )
        return None

class ExplicitBarBreakdownRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.hint == "bar" and ctx.n_breakdowns == 1 and 0 < ctx.country_count <= 4:
            color_dim = list(ctx.breakdown_counts.keys())[0]
            return StrategyResult(
                ChartStrategy.BREAKDOWN_COMPARISON,
                f"User requested bar; 1 breakdown ({color_dim}), {ctx.country_count} countries → grouped bar",
                color_dim=color_dim,
            )
        return None

class IncompatibleUnitsRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if "unit_measure" in ctx.breakdown_counts:
            facet_dim = "unit_measure"
            other_breakdowns = [k for k in ctx.breakdown_counts if k != "unit_measure"]
            color_dim = other_breakdowns[0] if other_breakdowns else None
            secondary_color_dim = "country" if ctx.country_count > 1 else None
            n_other = len(other_breakdowns)

            unit_count = ctx.breakdown_counts["unit_measure"]
            reason_detail = (
                f"unit_measure ({unit_count} units)"
                + (f" + {n_other} other breakdown(s)" if n_other else "")
                + f", {ctx.country_count} countr{'y' if ctx.country_count == 1 else 'ies'}"
                + (" + country combo" if secondary_color_dim else "")
                + " → faceted by unit (independent Y-axes)"
            )
            return StrategyResult(
                ChartStrategy.SMALL_MULTIPLES,
                reason_detail,
                color_dim=color_dim,
                facet_dim=facet_dim,
                secondary_color_dim=secondary_color_dim,
                scale_incompatible=True,
            )
        return None

class IncompatibleCustomBreakdownRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.n_breakdowns == 1 and ctx.country_count > 1:
            bd_dim = list(ctx.breakdown_counts.keys())[0]
            if bd_dim in _CUSTOM_BREAKDOWN_DIMS and _detect_scale_incompatibility(ctx.df, bd_dim):
                return StrategyResult(
                    ChartStrategy.SMALL_MULTIPLES,
                    f"1 breakdown ({bd_dim}), {ctx.country_count} countries, scale-incompatible "
                    f"→ scale-split panels (color=country)",
                    color_dim="country",
                    facet_dim=bd_dim,
                    scale_incompatible=True,
                )
        return None

class GenericSmallMultiplesRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.n_breakdowns >= 2 or (ctx.n_breakdowns >= 1 and ctx.country_count > 1):
            if ctx.country_count > 1:
                facet_dim = "country"
                color_dim = list(ctx.breakdown_counts.keys())[0] if ctx.breakdown_counts else None
            elif ctx.n_breakdowns >= 2:
                bd_keys = list(ctx.breakdown_counts.keys())
                facet_dim = bd_keys[0]
                color_dim = bd_keys[1] if len(bd_keys) >= 2 else None
            else:
                facet_dim = list(ctx.breakdown_counts.keys())[0]
                color_dim = None
            return StrategyResult(
                ChartStrategy.SMALL_MULTIPLES,
                f"{ctx.n_breakdowns} breakdowns, {ctx.country_count} countr{'y' if ctx.country_count == 1 else 'ies'} "
                f"→ small multiples (facet={facet_dim}, color={color_dim})",
                color_dim=color_dim,
                facet_dim=facet_dim,
            )
        return None

class TemporalBreakdownRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.n_breakdowns == 1 and ctx.year_count > 1:
            color_dim = list(ctx.breakdown_counts.keys())[0]
            if color_dim in _CUSTOM_BREAKDOWN_DIMS and _detect_scale_incompatibility(ctx.df, color_dim):
                return StrategyResult(
                    ChartStrategy.SMALL_MULTIPLES,
                    f"1 breakdown ({color_dim}), {ctx.year_count} years, scale-incompatible "
                    f"→ faceted (independent Y-axes)",
                    color_dim=None,
                    facet_dim=color_dim,
                    scale_incompatible=True,
                )
            return StrategyResult(
                ChartStrategy.TEMPORAL_SINGLE,
                f"1 breakdown ({color_dim}), {ctx.year_count} years → multi-series line chart",
                color_dim=color_dim,
            )
        return None

class BreakdownComparisonGroupedBarRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.n_breakdowns == 1 and ctx.country_count <= 4:
            color_dim = list(ctx.breakdown_counts.keys())[0]
            return StrategyResult(
                ChartStrategy.BREAKDOWN_COMPARISON,
                f"1 breakdown ({color_dim}), {ctx.breakdown_counts[color_dim]} values, single year → grouped bar",
                color_dim=color_dim,
            )
        return None

class ExplicitBarCrossSectionalRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.hint == "bar" and ctx.year_count <= 1 and ctx.country_count > 0:
            return StrategyResult(
                ChartStrategy.CROSS_SECTIONAL,
                f"User requested bar; {ctx.country_count} countries, single year → horizontal bar",
                color_dim="country",
            )
        return None

class HighCardinalityCrossSectionalRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.country_count > HIGH_CARDINALITY_THRESHOLDS["beeswarm_threshold"] and ctx.year_count <= 1:
            if ctx.hint in ("strip", "beeswarm", "tick", "distribution"):
                return StrategyResult(
                    ChartStrategy.DISTRIBUTION,
                    f"User requested strip/beeswarm; {ctx.country_count} countries, single year → strip/beeswarm",
                    color_dim="country",
                )
            return StrategyResult(
                ChartStrategy.CHOROPLETH,
                f"{ctx.country_count} countries, single year → default to choropleth map",
            )
        return None

class CrossSectionalRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.year_count <= 1 and ctx.country_count > 0:
            return StrategyResult(
                ChartStrategy.CROSS_SECTIONAL,
                f"{ctx.country_count} countries, single year → horizontal bar",
                color_dim="country",
            )
        return None

class TemporalSingleRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult | None:
        if ctx.year_count > 1:
            phrase = chart_type_phrase_for_reason(ctx.hint)
            return StrategyResult(
                ChartStrategy.TEMPORAL_SINGLE,
                f"Single indicator, {ctx.year_count} years, {ctx.country_count} countries → {phrase}",
                color_dim="country" if ctx.country_count > 0 else None,
                mark_hint=ctx.hint if ctx.hint in ("bar", "line") else None,
            )
        return None

class FallbackRule:
    def evaluate(self, ctx: RoutingContext) -> StrategyResult:
        return StrategyResult(
            ChartStrategy.FALLBACK_LINE,
            f"Default fallback → {chart_type_phrase_for_reason(ctx.hint)}",
            color_dim="country" if ctx.country_count > 0 else None,
        )

ROUTING_RULES: list[RoutingRule] = [
    ExplicitScatterRule(),
    ExplicitStackedAreaMultiIndicatorRule(),
    ExplicitMapRule(),
    ExplicitHeatmapRule(),
    TwoIndicatorRule(),
    ThreePlusIndicatorRule(),
    StackedAreaRule(),
    HeatmapRule(),
    ExplicitBarBreakdownRule(),
    IncompatibleUnitsRule(),
    IncompatibleCustomBreakdownRule(),
    GenericSmallMultiplesRule(),
    TemporalBreakdownRule(),
    BreakdownComparisonGroupedBarRule(),
    ExplicitBarCrossSectionalRule(),
    HighCardinalityCrossSectionalRule(),
    CrossSectionalRule(),
    TemporalSingleRule(),
]

def select_strategy(
    df: pd.DataFrame,
    n_indicators: int = 1,
    chart_type_hint: str | None = None,
    indicator_cols: list[str] | None = None,
) -> StrategyResult:
    """
    Applies the Rule Engine to select the correct ChartStrategy.
    """
    ctx = RoutingContext.build(df, n_indicators, chart_type_hint, indicator_cols)
    for rule in ROUTING_RULES:
        res = rule.evaluate(ctx)
        if res is not None:
            return res
    return FallbackRule().evaluate(ctx)

# ============================================================================
# SPEC BUILDERS — one per strategy, pure functions returning raw VL dicts
# ============================================================================


def _vl_schema() -> str:
    return "https://vega.github.io/schema/vega-lite/v5.json"


def _axis_style(title: str | None = None, temporal: bool = False) -> dict:
    ax: dict = {
        "gridColor": WB_GRID_COLOR,
        "gridDash": [4, 2],
        "labelColor": WB_TEXT_SUBTLE,
        "titleColor": WB_TEXT,
        "titleFontWeight": "bold",
        "tickCount": 5,
    }
    if temporal:
        ax["title"] = None
        ax["format"] = "%Y"
        ax["tickCount"] = 5
        ax["labelAngle"] = 0
    elif title is not None:
        ax["title"] = title
    return ax


def _detect_temporal_frequency(series: pd.Series) -> TemporalFreq:
    """Infer temporal frequency from raw TIME_PERIOD values.

    Handles all formats the Data360 API produces:
      - Annual:    "2019", "2020"
      - Monthly:   "2019-09", "2019-09-01", "2019M09"
      - Quarterly: "2019-Q1", "2019Q1", "2019-q1"
      - Daily:     "2019-09-15"

    Logic:
      - Parse unique values as datetime. If all land on Jan-1 (or are bare
        4-digit integers), treat as annual.
      - If distinct parsed periods show > 1 period per year → sub-annual.
        Distinguish quarterly (avg ~4/year) vs monthly (avg ~12/year).
      - Fall back to annual on any parse error or empty series.
    """
    values = series.dropna().astype(str).unique()
    if len(values) == 0:
        return "annual"

    # Fast path: all values are bare 4-digit years (most common case)
    if all(v.strip().isdigit() and len(v.strip()) == 4 for v in values):
        return "annual"

    # Check for explicit quarter markers before parsing as datetime
    q_pattern = re.compile(r"\d{4}[-\s]?[Qq]\d", re.IGNORECASE)
    if any(q_pattern.search(v) for v in values):
        return "quarterly"

    # Parse as datetime
    try:
        parsed = pd.to_datetime(pd.Series(values), errors="coerce").dropna()
    except Exception:
        return "annual"

    if parsed.empty:
        return "annual"

    # If every date is Jan-1 → effectively annual
    if (parsed.dt.month == 1).all() and (parsed.dt.day == 1).all():
        return "annual"

    n_years = max(parsed.dt.year.nunique(), 1)
    # Count distinct year-month combos to correctly classify monthly data
    # where dates span calendar-year boundaries (e.g. Sep 2019 – Aug 2020).
    n_year_months = parsed.dt.to_period("M").nunique()
    avg_months_per_year = n_year_months / n_years

    # Quarterly data has at most 4 year-months per year.
    # Monthly data has >= 5 (even sparse datasets).
    if avg_months_per_year >= 5:
        return "monthly"
    if avg_months_per_year >= 3:
        return "quarterly"
    # Fewer than 3 distinct months per year on average → annual (e.g. IPC biannual)
    return "annual"


def _format_time_period_series(
    series: pd.Series, freq: TemporalFreq
) -> pd.Series:
    """Convert raw TIME_PERIOD strings to the correct format for a given frequency.

    Annual   → "2019"         (4-digit year string; Vega-Lite ordinal)
    Monthly  → "2019-09"      (ISO yearmonth; Vega-Lite temporal + timeUnit yearmonth)
    Quarterly→ "2019-Q1"      (ISO yearquarter; Vega-Lite temporal + timeUnit yearquarter)
    Daily    → "2019-09-15"   (ISO date; Vega-Lite temporal)

    Values that fail parsing are left as-is (graceful fallback).
    """
    try:
        parsed = pd.to_datetime(series, errors="coerce")
    except Exception:
        return series

    if freq == "annual":
        return parsed.dt.year.astype("Int64").astype(str).where(parsed.notna(), series)
    elif freq == "monthly":
        return parsed.dt.to_period("M").astype(str).where(parsed.notna(), series)
    elif freq == "quarterly":
        return parsed.dt.to_period("Q").astype(str).where(parsed.notna(), series)
    else:  # daily
        return parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), series)


# Vega-Lite x-axis configuration per temporal frequency.
# Using a separate dict per frequency so builder functions have a single
# call site (_x_temporal_encoding) rather than hardcoded copies.
_TEMPORAL_X_ENCODING: dict[TemporalFreq, dict] = {
    "annual": {
        "field": "year",
        "type": "temporal",
        "timeUnit": "year",
        "axis": {
            "title": None,
            "format": "%Y",
            "tickCount": 5,
            "labelAngle": 0,
            "gridColor": WB_GRID_COLOR,
            "gridDash": [4, 2],
            "labelColor": WB_TEXT_SUBTLE,
            "titleColor": WB_TEXT,
            "titleFontWeight": "bold",
        },
    },
    "monthly": {
        "field": "year",
        "type": "temporal",
        "timeUnit": "yearmonth",
        "axis": {
            "title": None,
            "format": "%b %Y",
            "tickCount": 8,
            "labelAngle": -45,
            "gridColor": WB_GRID_COLOR,
            "gridDash": [4, 2],
            "labelColor": WB_TEXT_SUBTLE,
            "titleColor": WB_TEXT,
            "titleFontWeight": "bold",
        },
    },
    "quarterly": {
        "field": "year",
        "type": "temporal",
        "timeUnit": "yearquarter",
        "axis": {
            "title": None,
            "format": "Q%q %Y",
            "tickCount": 6,
            "labelAngle": -45,
            "gridColor": WB_GRID_COLOR,
            "gridDash": [4, 2],
            "labelColor": WB_TEXT_SUBTLE,
            "titleColor": WB_TEXT,
            "titleFontWeight": "bold",
        },
    },
    "daily": {
        "field": "year",
        "type": "temporal",
        "axis": {
            "title": None,
            "format": "%d %b %Y",
            "tickCount": 6,
            "labelAngle": -45,
            "gridColor": WB_GRID_COLOR,
            "gridDash": [4, 2],
            "labelColor": WB_TEXT_SUBTLE,
            "titleColor": WB_TEXT,
            "titleFontWeight": "bold",
        },
    },
}


def _x_temporal_encoding(freq: TemporalFreq = "annual") -> dict:
    """Return the correct Vega-Lite x encoding for the given temporal frequency.

    Returns a deep copy so callers can mutate axis overrides (e.g. labels=False
    for non-bottom panels) without affecting subsequent calls.
    """
    import copy
    return copy.deepcopy(_TEMPORAL_X_ENCODING.get(freq, _TEMPORAL_X_ENCODING["annual"]))


def _value_label_expr(unit_measure: str | None = None) -> str:
    """Vega expression for custom k/m/b/t axis label formatting."""
    normalized = (unit_measure or "").upper().strip()
    is_currency = "$" in normalized or "USD" in normalized
    prefix = "$" if is_currency else ""
    if unit_measure == "T":
        tiers = [("1e12", "Gt"), ("1e9", "Mt"), ("1e6", "Kt")]
    elif unit_measure == "W_POP":
        tiers = [("1e12", "Gw"), ("1e9", "Mw"), ("1e6", "Kw")]
    elif unit_measure in ("BITS", "BIT_S_IU"):
        tiers = [("1e12", "Gb"), ("1e9", "Mb"), ("1e6", "Kb")]
    else:
        tiers = [("1e12", "t"), ("1e9", "b"), ("1e6", "m"), ("1e3", "k")]
    parts = [
        f"abs(datum.value)>={t} ? '{prefix}'+format(datum.value/{t},'.1f')+'{s}'"
        for t, s in tiers
    ]
    tail = (
        f" : abs(datum.value)>=10 ? '{prefix}'+format(datum.value,',.1f')"
        f" : abs(datum.value)>=1 ? '{prefix}'+format(datum.value,'.1f')"
        f" : '{prefix}'+format(datum.value,'.2f')"
    )
    return " : ".join(parts) + tail


def _compute_tooltip_format(
    max_abs: float | None = None, unit_measure: str | None = None
) -> str:
    """Returns D3 format string for tooltip quantitative fields.

    Avoids D3's SI-prefix format (~s) which uses G/M/k (giga/mega/kilo) —
    these conflict with our axis labelExpr which uses b/m/k (billion/million/thousand).
    Large values are formatted as plain integers with comma separators instead.
    """
    normalized = (unit_measure or "").upper().strip()
    if unit_measure == "%":
        return ".1f"
    if "$" in normalized or "USD" in normalized:
        return "$,.2f"
    if max_abs is None or max_abs < 1:
        return ".2f"
    if max_abs < 10:
        return ".1f"
    if max_abs < 1000:
        return ",.1f"
    # Use comma-separated integers for large numbers (population, GDP, etc.)
    # ",.0f" → "1,400,000,000"  — unambiguous, no SI prefix conflict.
    return ",.0f"


def _color_encoding(
    field: str,
    domain: list | None = None,
    mark_type: str = "point",
    n_items: int = 0,
    legend_title: str | None = None,
    domain_labels: list[str] | None = None,
) -> dict:
    """Build a Vega-Lite color encoding channel.

    Legend title resolves in this priority order:
    1. Caller-supplied ``legend_title``
    2. Human-readable label from ``_TOOLTIP_SPECS`` (e.g. "Dimension 1")
    3. Title-cased field name (e.g. "Comp Breakdown 2")

    Legend orientation is chosen dynamically:
    - When the longest label in ``domain_labels`` exceeds 40 chars the legend
      switches to ``orient: bottom`` / ``direction: vertical`` so labels are not
      truncated and are not clipped in narrow containers (e.g. chatbot panels).
    - Otherwise ``orient: top`` / ``direction: horizontal`` is used.
    """
    resolved_title = (
        legend_title
        or _TOOLTIP_SPECS.get(field, {}).get("title")
        or field.replace("_", " ").title()
    )
    scale = {"range": WB_CAT_COLORS}
    if domain:
        scale["domain"] = domain
    # Keep a legend for geography even with one series (product expectation).
    if n_items == 1 and field != "country":
        legend = None
    else:
        _LONG_LABEL_THRESHOLD = 40
        max_label_len = (
            max((len(lbl) for lbl in domain_labels), default=0)
            if domain_labels
            else 0
        )
        if max_label_len > _LONG_LABEL_THRESHOLD:
            legend: dict | None = {
                "orient": "bottom",
                "direction": "vertical",
                "title": resolved_title,
                "labelLimit": 0,
            }
        else:
            legend = {
                "orient": "top",
                "direction": "horizontal",
                "title": resolved_title,
                "labelLimit": 250,
                "columns": 3,
            }
        if mark_type == "line":
            legend["symbolType"] = "stroke"
    return {
        "field": field,
        "type": "nominal",
        "scale": scale,
        "legend": legend,
    }


def build_temporal_single_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    y_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Line or grouped-bar chart: 1 indicator, multi-year, ≤8 countries.

    When result.mark_hint == "bar", renders a grouped bar chart with:
    - x = year as temporal (same encoding as line chart, timeUnit+format ensures correct display)
    - xOffset = country (side-by-side bars within each year band)
    - mark = bar with rounded top corners
    """
    rows = df.to_dict(orient="records")
    max_abs = float(df["value"].abs().max()) if "value" in df.columns else None
    tt_fmt = _compute_tooltip_format(max_abs, unit_measure)
    is_bar = result.mark_hint == "bar"
    y_title = None if y_label == "Value" else y_label
    y_ax = {
        **_axis_style(),
        "title": y_title,
        "labelExpr": _value_label_expr(unit_measure),
    }

    # Both bar and line use the same temporal encoding — timeUnit+format handles
    # date parsing and display (e.g. "%Y" for annual). Ordinal type was wrong
    # because it doesn't parse dates, causing epoch-ms to render as raw numbers.
    x_enc = _x_temporal_encoding(result.temporal_frequency)

    encoding: dict = {
        "x": x_enc,
        "y": {
            "field": "value",
            "type": "quantitative",
            "axis": y_ax,
            "scale": {"zero": is_bar},
        },
        "tooltip": build_structured_tooltips(
            list(df.columns),
            "bar" if is_bar else "line",
            indicator_labels,
            value_format=tt_fmt,
            viz_data=df,
            temporal_freq=result.temporal_frequency,
            dim_name_labels=result.dim_name_labels,
        ),
    }
    if result.color_dim:
        n_items = (
            df[result.color_dim].nunique() if result.color_dim in df.columns else 0
        )
        domain_labels = (
            list(df[result.color_dim].unique()) if result.color_dim in df.columns else None
        )
        legend_title = result.dim_name_labels.get(result.color_dim)
        encoding["color"] = _color_encoding(
            result.color_dim,
            mark_type="bar" if is_bar else "line",
            n_items=n_items,
            legend_title=legend_title,
            domain_labels=domain_labels,
        )
        if is_bar and result.color_dim in df.columns:
            encoding["xOffset"] = {"field": result.color_dim, "type": "nominal"}

    # Annotate subtitle with breakdown series names when color_dim is a custom breakdown.
    annotated_title = _append_breakdown_note(title, df, result.color_dim)

    if is_bar:
        mark_spec: dict = {
            "type": "bar",
            "opacity": 0.85,
            "cornerRadiusTopLeft": 2,
            "cornerRadiusTopRight": 2,
        }
    else:
        mark_spec = {
            "type": "line",
            "strokeWidth": 3,
            "strokeCap": "round",
            "point": _LINE_HOVER_POINT,
        }

    spec: dict = {
        "$schema": _vl_schema(),
        "title": annotated_title,
        "data": {"values": rows},
        "mark": mark_spec,
        "encoding": encoding,
        "width": 600,
        "height": 350,
    }
    return inject_wb_config(spec)


def build_cross_sectional_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    x_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Horizontal bar: 1 indicator, single year.

    Rows are capped at HIGH_CARDINALITY_THRESHOLDS["cross_sectional_max_items"]
    and sorted descending by value (highest performing country at top).
    """
    bar_dim = result.color_dim or "country"
    df, original_n = _cap_cardinality(
        df.sort_values("value", ascending=False),
        bar_dim,
        HIGH_CARDINALITY_THRESHOLDS["cross_sectional_max_items"],
    )
    title = _append_trim_note(title, bar_dim, df[bar_dim].nunique() if bar_dim in df.columns else 0, original_n)

    rows = df.to_dict(orient="records")
    max_abs = float(df["value"].abs().max()) if "value" in df.columns else None
    tt_fmt = _compute_tooltip_format(max_abs, unit_measure)

    color_enc = (
        _color_encoding(result.color_dim)
        if result.color_dim
        else {"value": WB_CAT_COLORS[0]}
    )
    # The Y-axis already labels the rows; the legend is purely redundant.
    if isinstance(color_enc, dict) and "field" in color_enc:
        color_enc["legend"] = None
    x_title = None if x_label == "Value" else x_label
    x_ax = {
        **_axis_style(),
        "title": x_title,
        "labelExpr": _value_label_expr(unit_measure),
    }

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": rows},
        "mark": {
            "type": "bar",
            "cornerRadiusTopRight": 3,
            "cornerRadiusBottomRight": 3,
        },
        "encoding": {
            "y": {
                "field": "country",
                "type": "nominal",
                "sort": "-x",
                "axis": {
                    "title": None,
                    "labelColor": WB_TEXT,
                    "labelFontWeight": "bold",
                    "labelLimit": 150,
                },
            },
            "x": {
                "field": "value",
                "type": "quantitative",
                "axis": x_ax,
                "scale": {"zero": True},
            },
            "color": color_enc,
            "tooltip": build_structured_tooltips(
                list(df.columns),
                "bar",
                indicator_labels,
                value_format=tt_fmt,
            ),
        },
        "width": 500,
        "height": max(180, len(df) * 28),
    }
    return inject_wb_config(spec)


def build_distribution_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    x_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Strip/beeswarm: 1 indicator, >8 countries, single year."""
    df, original_n = _cap_cardinality(
        df.sort_values("value", ascending=False),
        "country",
        HIGH_CARDINALITY_THRESHOLDS["top_n_series"],
    )
    title = _append_trim_note(title, "country", df["country"].nunique() if "country" in df.columns else 0, original_n)

    rows = df.to_dict(orient="records")
    max_abs = float(df["value"].abs().max()) if "value" in df.columns else None
    tt_fmt = _compute_tooltip_format(max_abs, unit_measure)
    x_ax = {
        **_axis_style(),
        "title": None,
        "labelExpr": _value_label_expr(unit_measure),
    }

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": rows},
        "mark": {"type": "tick", "thickness": 3, "bandSize": 18},
        "encoding": {
            "x": {
                "field": "value",
                "type": "quantitative",
                "axis": x_ax,
            },
            "y": {
                "field": "country",
                "type": "nominal",
                "sort": "-x",
                "axis": {
                    "title": None,
                    "labelColor": WB_TEXT,
                    "labelFontWeight": "bold",
                    "labelLimit": 160,
                },
            },
            "color": _color_encoding("country"),
            "tooltip": build_structured_tooltips(
                list(df.columns),
                "tick",
                indicator_labels,
                value_format=tt_fmt,
            ),
        },
        "width": 500,
        "height": max(250, len(df) * 22),
    }
    return inject_wb_config(spec)


def build_breakdown_comparison_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    y_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Grouped bar: 1 indicator, 1 breakdown (sex/age/urban), 2-4 values, ≤4 countries."""
    rows = df.to_dict(orient="records")
    color_dim = result.color_dim or "sex"
    max_abs = float(df["value"].abs().max()) if "value" in df.columns else None
    tt_fmt = _compute_tooltip_format(max_abs, unit_measure)

    if color_dim == "sex":
        domain = [k for k in WB_GENDER_COLORS if k in df[color_dim].unique()]
        color_range = [WB_GENDER_COLORS[k] for k in domain]
        color_scale = {"domain": domain, "range": color_range}
    else:
        color_scale = {"range": WB_CAT_COLORS}

    x_field = "country" if df.get("country", pd.Series()).nunique() > 1 else "year"
    # Use temporal type for year so Vega-Lite formats ISO strings as years, not raw ms integers.
    x_enc: dict
    if x_field == "year":
        x_enc = _x_temporal_encoding(result.temporal_frequency)
    else:
        x_enc = {
            "field": x_field,
            "type": "nominal",
            "axis": {"title": None, "labelFontWeight": "bold"},
        }
    y_ax = {
        **_axis_style(),
        "title": None,
        "labelExpr": _value_label_expr(unit_measure),
    }

    # Resolve a friendly legend title: prefer _TOOLTIP_SPECS label, fall back to title-cased field.
    legend_title = _TOOLTIP_SPECS.get(color_dim, {}).get("title") or color_dim.replace("_", " ").title()

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": rows},
        "mark": {"type": "bar"},
        "encoding": {
            "x": x_enc,
            "xOffset": {"field": color_dim, "type": "nominal"},
            "y": {
                "field": "value",
                "type": "quantitative",
                "axis": y_ax,
                "scale": {"zero": True},
            },
            "color": {
                "field": color_dim,
                "type": "nominal",
                "scale": color_scale,
                "legend": {
                    "orient": "top",
                    "title": legend_title,
                    "labelLimit": 100,
                    "columns": 3,
                },
            },
            "tooltip": build_structured_tooltips(
                list(df.columns),
                "bar",
                indicator_labels,
                value_format=tt_fmt,
            ),
        },
        "width": max(300, df[x_field].nunique() * 80),
        "height": 320,
    }
    return inject_wb_config(spec)


def _group_breakdowns_by_scale(
    df: pd.DataFrame,
    breakdown_dim: str,
    grouping_threshold: float = 0.75,
) -> list[list[str]]:
    """Cluster breakdown values into scale-compatible groups.

    Groups breakdown series so that all members within a group can share a
    Y-axis without any one series visually dominating the others.  Series in
    different groups will be rendered as separate panels.

    Algorithm
    ---------
    1. Compute ``log10(max |value|)`` for each breakdown value.
    2. Sort breakdown values by this magnitude.
    3. Greedily build groups: add the next value to the current group if the
       group's magnitude span (max_mag − min_mag) stays within
       *grouping_threshold*.  Otherwise start a new group.

    The default *grouping_threshold* of **0.75** (≈5.6× difference max within
    a group) is intentionally tighter than the detection threshold of 1.5
    (≈30×) used by :func:`_detect_scale_incompatibility`.  This ensures that
    within-group series are visually comparable on a shared Y-axis.

    This function is **purely data-driven**: it does not use any hardcoded
    dimension names, indicator codes, or external metadata.  It works for any
    indicator and any number of breakdown values.

    Args:
        df: DataFrame containing *breakdown_dim* and ``value`` columns.
        breakdown_dim: Column containing breakdown series identifiers.
        grouping_threshold: Maximum log10 span within a group.  Default
            ``0.75`` ≈ 5.6× — half the detection threshold.

    Returns:
        Ordered list of groups; each group is an ordered list of breakdown
        value strings.  Every unique non-null breakdown value appears in
        exactly one group.  Falls back to one singleton group per value if
        computation fails.
    """
    import math

    bd_vals = sorted(
        str(v) for v in df[breakdown_dim].dropna().unique()
    ) if breakdown_dim in df.columns else []

    if len(bd_vals) <= 1:
        return [bd_vals] if bd_vals else []

    if "value" not in df.columns:
        return [[v] for v in bd_vals]

    # Compute log10(max|value|) for each breakdown value.
    mags: dict[str, float] = {}
    for v in bd_vals:
        series = df.loc[df[breakdown_dim] == v, "value"].dropna()
        if series.empty:
            mags[v] = 0.0
            continue
        max_abs = float(series.abs().max())
        mags[v] = math.log10(max_abs) if max_abs > 0 else 0.0

    # Sort by magnitude then build groups greedily.
    sorted_vals = sorted(bd_vals, key=lambda v: mags[v])

    groups: list[list[str]] = []
    current_group: list[str] = []
    group_min_mag: float = 0.0
    group_max_mag: float = 0.0

    for v in sorted_vals:
        mag = mags[v]
        if not current_group:
            current_group = [v]
            group_min_mag = group_max_mag = mag
        else:
            new_min = min(group_min_mag, mag)
            new_max = max(group_max_mag, mag)
            if new_max - new_min <= grouping_threshold:
                current_group.append(v)
                group_min_mag = new_min
                group_max_mag = new_max
            else:
                groups.append(current_group)
                current_group = [v]
                group_min_mag = group_max_mag = mag

    if current_group:
        groups.append(current_group)

    return groups


def _build_scale_split_vconcat(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    y_label: str = "Value",
    unit_measure: str | None = None,
    grouping_threshold: float = 0.75,
    force_separate_panels: bool = False,
) -> dict:
    """Vconcat layout for scale-incompatible custom breakdowns.

    Produces one full-width panel per **scale-compatible group** of breakdown
    values.  Groups are discovered automatically by
    :func:`_group_breakdowns_by_scale` (data-driven, no hard-coded metadata).

    Panel layout
    ------------
    - **Single-member group** (680×140): one fixed-color line, panel title =
      series label.  Identical to the pre-grouping behaviour.
    - **Multi-member group** (680×180): layered multi-series lines with Vega-Lite
      ``color`` encoding, a right-side legend, and a panel title listing the
      member labels (truncated at 80 characters).

    All panels share the X (year) axis via ``resolve.scale.x = 'shared'``.
    X-axis labels are suppressed on all but the bottom panel.

    The default *grouping_threshold* of 0.75 (≈5.6×) is tighter than the
    detection threshold of 1.5 (≈30×), so within-group series are always
    visually comparable on a shared Y-axis.
    """
    facet_dim = result.facet_dim or "comp_breakdown_1"
    lab = indicator_labels or {}

    # Cap using the same threshold as regular small multiples.
    df, original_n = _cap_cardinality(
        df, facet_dim, HIGH_CARDINALITY_THRESHOLDS["small_multiples_max_facets"]
    )

    breakdown_vals = sorted(df[facet_dim].dropna().unique(), key=str)
    rows = df.to_dict(orient="records")
    label_expr = _value_label_expr(unit_measure)

    # Rebuild the context subtitle so it only names the countries actually shown,
    # not the full pre-cap list that build_chart_title_with_context built earlier.
    if original_n is not None and facet_dim == "country" and isinstance(title, dict):
        existing_sub = title.get("subtitle", "")
        if isinstance(existing_sub, str):
            existing_sub = [p.strip() for p in existing_sub.split(" · ") if p.strip()]

        shown_countries = sorted(df["country"].unique().tolist(), key=str.casefold)
        # _year_range_label expects a Series. It's imported in viz_config.
        from data360.viz_config import _year_range_label
        year_lbl = _year_range_label(df["year"]) if "year" in df.columns else None

        new_geo = ", ".join(shown_countries)
        if year_lbl:
            new_geo = f"{new_geo}, {year_lbl}"
        title = {**title, "subtitle": [new_geo] + existing_sub[1:]}

    annotated_title = _append_trim_note(
        title, facet_dim,
        len(breakdown_vals),
        original_n,
    )

    # Discover scale-compatible groups from the data — no hard-coded logic.
    if force_separate_panels:
        # One panel per facet value, sorted alphabetically (standard facet behavior)
        groups = [[v] for v in breakdown_vals]
    else:
        groups = _group_breakdowns_by_scale(df, facet_dim, grouping_threshold)

    # GoG: when the color channel encodes a variable DIFFERENT from the facet variable
    # (e.g. IPC phases within unit panels, or countries within WGI breakdown panels),
    # the color mapping is identical in every panel — share the scale so Vega-Lite
    # renders exactly one legend. When color and facet are the same variable (original
    # single-country WGI) each panel has its own color domain — keep independent.
    #
    # For the cross-dim multi-member case (multi-country + multi-breakdown per panel),
    # each panel gets its own combo-color domain (country shades × breakdowns in that
    # group), so resolve must be "independent" there. We track this and override below.
    color_resolve = (
        "shared"
        if result.color_dim and result.color_dim != facet_dim
        else "independent"
    )

    # Pre-compute a globally sorted domain for the color dimension so that
    # color assignments are deterministic and consistent across all panels.
    # Without a pinned domain, Vega-Lite assigns colors by first-encounter order
    # in the data, which depends on fetch ordering and can vary between runs.
    _color_dim_domain: list[str] | None = (
        sorted(df[result.color_dim].dropna().unique().tolist())
        if result.color_dim and result.color_dim in df.columns
        else None
    )

    # ── Pre-compute legend layout and dynamic panel height ────────────────────
    # Build the worst-case combo label list (most items any panel will show) so
    # the layout helper can pick orient/direction/columns once for the whole spec.
    _n_panels = len(groups)
    _legend_target_total_px = 700  # desired total figure height in pixels
    _base_single_px = 140          # default single-member panel height
    _base_multi_px  = 180          # default multi-member panel height

    if result.color_dim and (result.color_dim != facet_dim or result.secondary_color_dim):
        # Combo path (Case B / secondary_color_dim): compute worst-case labels.
        _sec_dim  = result.secondary_color_dim  # e.g. "country" or None
        _pri_dim  = result.color_dim             # e.g. "comp_breakdown_2" or country
        if _sec_dim:
            # secondary_color_dim path: country | breakdown
            _sorted_sec = sorted(df[_sec_dim].dropna().unique().tolist())
            _sorted_pri = sorted(df[_pri_dim].dropna().unique().tolist())
            _all_combo_labels = [
                f"{s} | {lab.get(p, p)}"
                for s in _sorted_sec
                for p in _sorted_pri
            ]
        else:
            # Case B multi-member: country | breakdown per panel — largest group
            _sorted_countries = sorted(df[_pri_dim].dropna().unique().tolist())
            _max_group = max(groups, key=len) if groups else []
            _all_combo_labels = [
                f"{c} | {lab.get(bd, bd)}"
                for c in _sorted_countries
                for bd in _max_group
            ]
        _legend_layout = _compute_legend_layout(_all_combo_labels)
        _legend_h      = _estimate_legend_height(len(_all_combo_labels), _legend_layout, has_title=True)
        _panel_h_single = max(80, (_legend_target_total_px - _legend_h) // _n_panels)
        _panel_h_multi  = max(100, (_legend_target_total_px - _legend_h) // _n_panels)
    else:
        # No combo: use a small legend and default panel heights.
        _legend_layout  = _compute_legend_layout([])
        _legend_h       = 0
        _panel_h_single = _base_single_px
        _panel_h_multi  = _base_multi_px

    charts: list[dict] = []
    color_offset = 0  # global color index so adjacent panels never share a colour

    for g_idx, group in enumerate(groups):
        is_last_panel = g_idx == len(groups) - 1

        x_enc = _x_temporal_encoding(result.temporal_frequency)
        if not is_last_panel:
            x_enc = {**x_enc, "axis": {**x_enc.get("axis", {}), "labels": False, "title": None}}

        y_axis = {**_axis_style(), "title": None, "labelExpr": label_expr}

        if len(group) == 1:
            # ----------------------------------------------------------------
            # Single-member group — identical to pre-grouping behaviour.
            # ----------------------------------------------------------------
            bd_val = group[0]
            color = WB_CAT_COLORS[color_offset % len(WB_CAT_COLORS)]
            color_offset += 1
            bd_label = lab.get(bd_val, bd_val)

            bd_data = df[df[facet_dim] == bd_val]
            max_abs = (
                float(bd_data["value"].abs().max())
                if "value" in bd_data.columns and not bd_data.empty
                else None
            )
            tt_fmt = _compute_tooltip_format(max_abs, unit_measure)

            mark_spec = {
                "type": "line",
                "strokeWidth": 3,
                "strokeCap": "round",
                "point": _LINE_HOVER_POINT,
            }

            chart_enc = {
                "x": x_enc,
                "y": {
                    "field": "value",
                    "type": "quantitative",
                    "axis": y_axis,
                    "scale": {"zero": False},
                },
                "tooltip": build_structured_tooltips(
                    list(bd_data.columns),
                    "line",
                    indicator_labels={**lab, "value": bd_label},
                    value_format=tt_fmt,
                    viz_data=bd_data,
                    temporal_freq=result.temporal_frequency,
                    dim_name_labels=result.dim_name_labels,
                ),
            }

            if result.color_dim and result.secondary_color_dim:
                # 3-way encoding: facet_dim=unit_measure, color_dim=breakdown,
                # secondary_color_dim=country → combo shade families per panel.
                # Format: "{country} | {breakdown}" — country is primary (base color),
                # breakdown is secondary (shade within country family).
                _sec = result.secondary_color_dim  # country
                _pri = result.color_dim            # comp_breakdown_2
                sorted_secondary = sorted(
                    df[_sec].dropna().unique().tolist()
                ) if _sec in df.columns else []
                sorted_primary = sorted(
                    bd_data[_pri].dropna().unique().tolist()
                ) if _pri in bd_data.columns else []
                # Domain: grouped by country first, then breakdown within each country.
                _s_combo_domain: list[str] = [
                    f"{s} | {lab.get(p, p)}"
                    for s in sorted_secondary    # country = outer loop
                    for p in sorted_primary      # breakdown = inner loop
                ]
                # Color: each country gets a base color, breakdowns get shades.
                _s_combo_range: list[str] = []
                for si, _country in enumerate(sorted_secondary):
                    base_color = WB_CAT_COLORS[si % len(WB_CAT_COLORS)]
                    _s_combo_range.extend(_generate_color_shades(base_color, len(sorted_primary)))
                _s_combo_field = "_s_combo_label"
                _s_combo_calc = {
                    "calculate": f"datum['{_sec}'] + ' | ' + datum['{_pri}']",
                    "as": _s_combo_field,
                }
                _pri_title = result.dim_name_labels.get(_pri) or _pri.replace("_", " ").title()
                _sec_title = result.dim_name_labels.get(_sec) or _sec.replace("_", " ").title()
                # Show legend only on the last panel so it appears once at the bottom.
                _s_legend: dict | None = (
                    {**_legend_layout, "title": f"{_sec_title} | {_pri_title}"}
                    if is_last_panel
                    else None
                )
                chart_enc["color"] = {
                    "field": _s_combo_field,
                    "type": "nominal",
                    "scale": {"domain": _s_combo_domain, "range": _s_combo_range},
                    "legend": _s_legend,
                }
                charts.append({
                    "title": {
                        "text": bd_label,
                        "fontSize": 12,
                        "fontWeight": "bold",
                        "anchor": "start",
                        "offset": 4,
                    },
                    "width": 680,
                    "height": _panel_h_single,
                    "transform": [
                        _s_combo_calc,
                        {"filter": {"field": facet_dim, "equal": bd_val}},
                    ],
                    "mark": mark_spec,
                    "encoding": chart_enc,
                })
                continue  # skip the generic charts.append below

            elif result.color_dim:
                n_items = (
                    bd_data[result.color_dim].nunique()
                    if result.color_dim in bd_data.columns
                    else 0
                )
                domain_labels_for_group = (
                    list(bd_data[result.color_dim].unique())
                    if result.color_dim and result.color_dim in bd_data.columns
                    else None
                )
                legend_title_for_group = result.dim_name_labels.get(result.color_dim) if result.color_dim else None
                chart_enc["color"] = _color_encoding(
                    result.color_dim,
                    mark_type="line",
                    n_items=n_items,
                    legend_title=legend_title_for_group,
                    domain_labels=domain_labels_for_group,
                    domain=_color_dim_domain,
                )
                # Suppress legend on non-first panels when color is shared across units.
                if color_resolve == "shared" and g_idx > 0:
                    chart_enc["color"] = {**chart_enc["color"], "legend": None}
            else:
                mark_spec["color"] = color

            charts.append({
                "title": {
                    "text": bd_label,
                    "color": color if not result.color_dim else None,
                    "fontSize": 12,
                    "fontWeight": "bold",
                    "anchor": "start",
                    "offset": 4,
                },
                "width": 680,
                "height": _panel_h_single,
                "transform": [{"filter": {"field": facet_dim, "equal": bd_val}}],
                "mark": mark_spec,
                "encoding": chart_enc,
            })

        else:
            # ----------------------------------------------------------------
            # Multi-member group — layered lines, shared Y-axis, color legend.
            # ----------------------------------------------------------------
            group_labels = [lab.get(v, v) for v in group]
            import textwrap as _textwrap
            joined = ", ".join(group_labels)
            wrapped = _textwrap.wrap(joined, width=100)
            if len(wrapped) > 2:
                wrapped = wrapped[:2]
                wrapped[-1] = wrapped[-1].rstrip(",") + "\u2026"
            panel_title: str | list[str] = wrapped if len(wrapped) > 1 else (wrapped[0] if wrapped else joined)

            group_data = df[df[facet_dim].isin(group)]
            max_abs = (
                float(group_data["value"].abs().max())
                if "value" in group_data.columns and not group_data.empty
                else None
            )
            tt_fmt = _compute_tooltip_format(max_abs, unit_measure)

            # Two rendering modes for multi-member groups:
            # A. color_dim IS the facet_dim (or color_dim is None):
            #    Original WGI single-country case — color by breakdown value within panel.
            # B. color_dim != facet_dim (e.g. multi-country WGI, color=country):
            #    Cross-dimension case — shade families per country.
            #    Georgia gets N shades of blue (dark→light per breakdown),
            #    UK gets N shades of orange. A single color channel encodes
            #    both dimensions; strokeDash is dropped entirely.
            _panel_extra_transforms: list[dict] = []  # e.g. calculate for combo field
            if result.color_dim and result.color_dim != facet_dim:
                # Case B: combo color families — format "{country} | {breakdown}".
                # Country (color_dim) is the primary grouping (base color family).
                # Breakdown values (facet_dim items in this group) are shades.
                sorted_countries = sorted(
                    df[result.color_dim].dropna().unique().tolist()
                )
                # Domain: all country×breakdown combos, grouped by country first.
                combo_domain: list[str] = [
                    f"{c} | {lab.get(bd, bd)}"
                    for c in sorted_countries
                    for bd in group
                ]
                # Range: each country gets N shades (dark→light per breakdown).
                combo_range: list[str] = []
                for ci, country in enumerate(sorted_countries):
                    base_color = WB_CAT_COLORS[ci % len(WB_CAT_COLORS)]
                    combo_range.extend(_generate_color_shades(base_color, len(group)))

                # Vega-Lite calculate: "{country} | {breakdown_value}".
                _combo_field = "_combo_label"
                _combo_calc = {
                    "calculate": (
                        f"datum['{result.color_dim}'] + ' | ' + datum['{facet_dim}']"
                    ),
                    "as": _combo_field,
                }

                _country_title = (
                    result.dim_name_labels.get(result.color_dim, result.color_dim.title())
                )
                _bd_title = (
                    result.dim_name_labels.get(facet_dim, facet_dim.title())
                )
                # Show legend only on the last panel.
                combo_legend: dict | None = (
                    {**_legend_layout, "title": f"{_country_title} | {_bd_title}"}
                    if is_last_panel
                    else None
                )

                panel_encoding: dict = {
                    "x": x_enc,
                    "y": {
                        "field": "value",
                        "type": "quantitative",
                        "axis": y_axis,
                        "scale": {"zero": False},
                    },
                    "color": {
                        "field": _combo_field,
                        "type": "nominal",
                        "scale": {"domain": combo_domain, "range": combo_range},
                        "legend": combo_legend,
                    },
                    "tooltip": build_structured_tooltips(
                        list(group_data.columns),
                        "line",
                        indicator_labels=lab,
                        value_format=tt_fmt,
                        viz_data=group_data,
                        temporal_freq=result.temporal_frequency,
                        dim_name_labels=result.dim_name_labels,
                    ),
                }
                # Add the combo calculate to this panel's transforms.
                _panel_extra_transforms = [_combo_calc]
            else:
                # Case A: original — color by the breakdown value within the panel.
                group_colors = [
                    WB_CAT_COLORS[(color_offset + j) % len(WB_CAT_COLORS)]
                    for j in range(len(group))
                ]
                color_offset += len(group)
                panel_encoding = {
                    "x": x_enc,
                    "y": {
                        "field": "value",
                        "type": "quantitative",
                        "axis": y_axis,
                        "scale": {"zero": False},
                    },
                    "color": {
                        "field": facet_dim,
                        "type": "nominal",
                        "scale": {
                            "domain": group,
                            "range": group_colors,
                        },
                        "legend": {
                            "orient": "bottom" if max((len(lbl) for lbl in group_labels), default=0) > 40 else "right",
                            "labelFontSize": 11,
                            "symbolSize": 80,
                            **(
                                {"labelLimit": 0, "direction": "vertical"}
                                if max((len(lbl) for lbl in group_labels), default=0) > 40
                                else {"labelLimit": 200}
                            ),
                        },
                    },
                    "tooltip": build_structured_tooltips(
                        list(group_data.columns),
                        "line",
                        indicator_labels=lab,
                        value_format=tt_fmt,
                        viz_data=group_data,
                        temporal_freq=result.temporal_frequency,
                        dim_name_labels=result.dim_name_labels,
                    ),
                }

            charts.append({
                "title": {
                    "text": panel_title,
                    "fontSize": 12,
                    "fontWeight": "bold",
                    "anchor": "start",
                    "offset": 4,
                },
                "width": 680,
                "height": _panel_h_multi,
                # Extra transforms (e.g. calculate for combo field) must come
                # BEFORE the filter so the calculated field is available.
                "transform": _panel_extra_transforms + [{"filter": {"field": facet_dim, "oneOf": group}}],
                "mark": {
                    "type": "line",
                    "strokeWidth": 3,
                    "strokeCap": "round",
                    "point": _LINE_HOVER_POINT,
                },
                "encoding": panel_encoding,
            })

    spec: dict = {
        "$schema": _vl_schema(),
        "title": annotated_title,
        "data": {"values": rows},
        "vconcat": charts,
        "resolve": {"scale": {"x": "shared", "color": "independent"}},
    }
    return inject_wb_config(spec)


def build_small_multiples_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    y_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Faceted small multiples: 1 indicator, 2+ breakdowns or breakdown+many countries.

    Facet panels are capped at HIGH_CARDINALITY_THRESHOLDS["small_multiples_max_facets"]
    via the shared :func:`_cap_cardinality` utility. When trimmed, the top-N facet
    values by most-recent data point are retained and a subtitle note is injected via
    :func:`_append_trim_note` — the same logic used by build_cross_sectional_spec.

    When ``result.scale_incompatible`` is True, delegates to
    :func:`_build_scale_split_vconcat` which produces one full-width vertically
    stacked panel per breakdown value, each with an independent Y-axis. This
    prevents scale-dominant series from compressing smaller ones on a shared axis.
    """
    # We now unconditionally use the vconcat layout (680×140 per panel) instead
    # of the shared-axis facet grid (180×120 panels) to improve visual spacing,
    # as the facet grid produces tiny charts that resemble seaborn grids.
    # When not scale-incompatible, we force each facet value into its own panel.
    return _build_scale_split_vconcat(
        df, title, result, indicator_labels, y_label, unit_measure,
        force_separate_panels=not result.scale_incompatible
    )



def build_heatmap_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    y_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Heatmap chart: >8 countries, multi-year matrix."""
    df, original_n = _cap_cardinality(df, "country", 50)
    title = _append_trim_note(title, "country", df["country"].nunique() if "country" in df.columns else 0, original_n)

    rows = df.to_dict(orient="records")
    tt_fmt = _compute_tooltip_format(float(df["value"].abs().max()) if "value" in df.columns else None, unit_measure)

    # Determine scheme based on values: divergent for mixed signs, sequential otherwise
    has_negative = df["value"].min() < 0 if "value" in df.columns else False
    scheme = "redblue" if has_negative else "yellowgreenblue"

    # Compute explicit domain so Vega-Lite cannot infer a discrete/ordinal scale
    # from the data shape.  Without this, symbol legend entries are rendered for
    # each unique float value instead of a continuous gradient.
    val_series = pd.to_numeric(df["value"], errors="coerce").dropna() if "value" in df.columns else pd.Series(dtype=float)
    if not val_series.empty:
        val_min = float(val_series.min())
        val_max = float(val_series.max())
        if has_negative:
            # Symmetric domain for diverging schemes so the midpoint is always 0.
            abs_max = max(abs(val_min), abs(val_max))
            color_domain = [-abs_max, abs_max]
        else:
            color_domain = [val_min, val_max]
    else:
        color_domain = [0, 1]

    y_enc = {
        "field": "country",
        "type": "nominal",
        "axis": {"title": None, "labelFontWeight": "bold"}
    }

    x_enc = _x_temporal_encoding(result.temporal_frequency)

    color_enc = {
        "field": "value",
        "type": "quantitative",
        # Explicit domain forces a continuous quantitative scale; without it
        # Vega-Lite may fall back to an ordinal scale and render symbol swatches.
        "scale": {"scheme": scheme, "domain": color_domain},
        "legend": {
            "type": "gradient",
            "title": y_label,
            "orient": "top",
            "direction": "horizontal",
            "gradientLength": 200,
            # Explicit gradient stops mirror the domain so the legend
            # colour bar matches the cell colours exactly.
            "gradientThickness": 12,
            "labelFontSize": 10,
        },
    }

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": rows},
        "mark": {"type": "rect", "tooltip": True},
        "encoding": {
            "x": x_enc,
            "y": y_enc,
            "color": color_enc,
            "tooltip": build_structured_tooltips(
                list(df.columns),
                "rect",
                indicator_labels,
                value_format=tt_fmt,
                viz_data=df,
                temporal_freq=result.temporal_frequency,
                dim_name_labels=result.dim_name_labels,
            )
        },
        "width": 600,
        "height": {"step": 15},
        # Override the global config.legend for heatmaps: the WB theme default
        # does not include symbolType/gradientLength, causing Vega-Lite to
        # render a symbol swatch legend when the global config is merged in.
        "config": {
            "legend": {
                "symbolType": "square",
            }
        },
    }

    if result.facet_dim:
        spec["facet"] = {
            "field": result.facet_dim,
            "type": "nominal",
            "columns": 2,
            "header": {"title": None, "labelFontWeight": "bold"}
        }
        spec["spec"] = {
            "mark": {"type": "rect", "tooltip": True},
            "encoding": spec.pop("encoding"),
            "width": 250,
            "height": {"step": 15}
        }
        del spec["mark"]
        del spec["width"]
        del spec["height"]

    return inject_wb_config(spec)


def build_choropleth_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    y_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Choropleth map chart: single indicator, geographic display."""
    # Maps display a single point in time. If data is multi-year, filter to the latest year.
    year_count = df["year"].nunique() if "year" in df.columns else 0
    if year_count > 1:
        latest_year = df["year"].max()
        df = df[df["year"] == latest_year].copy()
        # Ensure title dict structure
        if isinstance(title, str):
            title = {"text": title}
        subs = title.get("subtitle", [])
        if isinstance(subs, str):
            subs = [subs]
        subs.append(f"Note: Map displays data for the most recent year ({latest_year})")
        title["subtitle"] = subs

    rows = df.to_dict(orient="records")
    max_abs = float(df["value"].abs().max()) if "value" in df.columns else None
    tt_fmt = _compute_tooltip_format(max_abs, unit_measure)

    has_negative = df["value"].min() < 0 if "value" in df.columns else False
    scheme = "redblue" if has_negative else "blues"

    # Use TopoJSON as the main data so countries without data are still drawn (in gray)
    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "width": 800,
        "height": 450,
        "data": {
            "url": "https://unpkg.com/world-atlas@2.0.2/countries-110m.json",
            "format": {"type": "topojson", "feature": "countries"}
        },
        "transform": [
            {
                "lookup": "properties.name",
                "from": {
                    "data": {"values": rows},
                    "key": "country",
                    "fields": list(df.columns)
                }
            }
        ],
        "projection": {"type": "equalEarth"},
        "layer": [
            {
                # Base layer: draw all countries in light gray
                "mark": {"type": "geoshape", "fill": "#eee", "stroke": "white", "strokeWidth": 0.5}
            },
            {
                # Data layer: color countries that have values
                "mark": {"type": "geoshape", "stroke": "white", "strokeWidth": 0.5},
                "transform": [{"filter": "isValid(datum.value)"}],
                "encoding": {
                    "color": {
                        "field": "value",
                        "type": "quantitative",
                        "scale": {"scheme": scheme},
                        "legend": {
                            "title": y_label,
                            "orient": "bottom",
                            "direction": "horizontal",
                            "gradientLength": 300
                        }
                    },
                    "tooltip": build_structured_tooltips(
                        list(df.columns),
                        "geoshape",
                        indicator_labels,
                        value_format=tt_fmt,
                        dim_name_labels=result.dim_name_labels,
                    )
                }
            }
        ]
    }

    return inject_wb_config(spec)


def build_stacked_area_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    y_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Stacked Area chart: multi-year, multiple series (part-to-whole)."""
    color_dim = result.color_dim or "country"

    # Fallback if mixed signs, as stacked area expects same-sign data
    has_negative = df["value"].min() < 0 if "value" in df.columns else False
    if has_negative:
        return build_temporal_single_spec(df, title, result, indicator_labels, y_label, unit_measure)

    df, original_n = _cap_cardinality(df, color_dim, HIGH_CARDINALITY_THRESHOLDS["line_max_series"])

    annotated_title = _append_breakdown_note(title, df, color_dim)
    annotated_title = _append_trim_note(annotated_title, color_dim, df[color_dim].nunique() if color_dim in df.columns else 0, original_n)

    rows = df.to_dict(orient="records")
    tt_fmt = _compute_tooltip_format(float(df["value"].abs().max()) if "value" in df.columns else None, unit_measure)

    legend_title = _TOOLTIP_SPECS.get(color_dim, {}).get("title") or color_dim.replace("_", " ").title()

    spec: dict = {
        "$schema": _vl_schema(),
        "title": annotated_title,
        "data": {"values": rows},
        "mark": {"type": "area", "tooltip": True, "line": True, "opacity": 0.8},
        "encoding": {
            "x": _x_temporal_encoding(result.temporal_frequency),
            "y": {
                "field": "value",
                "type": "quantitative",
                "stack": "zero",
                "axis": {**_axis_style(), "title": None, "labelExpr": _value_label_expr(unit_measure)}
            },
            "color": _color_encoding(color_dim, domain=None, mark_type="area", legend_title=legend_title),
            "tooltip": build_structured_tooltips(
                list(df.columns),
                "area",
                indicator_labels,
                value_format=tt_fmt,
                viz_data=df,
                temporal_freq=result.temporal_frequency,
                dim_name_labels=result.dim_name_labels,
            )
        },
        "width": 600,
        "height": 350
    }

    return inject_wb_config(spec)



def build_correlation_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
) -> dict:
    """Scatterplot: 2 indicators, single year, multi-country."""
    ind_cols = result.indicator_cols
    if len(ind_cols) < 2:
        raise ValueError("correlation spec requires exactly 2 indicator columns")

    x_col, y_col = ind_cols[0], ind_cols[1]
    lab = indicator_labels or {}
    x_label = lab.get(x_col, x_col.replace("_", " ").title())
    y_label = lab.get(y_col, y_col.replace("_", " ").title())

    rows = df.dropna(subset=[x_col, y_col]).to_dict(orient="records")

    color_dim = result.color_dim or "country"
    color_enc = _color_encoding(color_dim)

    # The legend is 100% redundant now because every dot has a direct text label.
    # Direct labeling is superior in GoG as it prevents saccadic eye movement.
    if isinstance(color_enc, dict) and "legend" in color_enc:
        color_enc["legend"] = None

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": rows},
        "layer": [
            {
                "mark": {
                    "type": "circle",
                    "opacity": 0.85,
                    "stroke": WB_WHITE,
                    "strokeWidth": 1,
                    "size": 70
                },
                "encoding": {
                    "x": {
                        "field": x_col,
                        "type": "quantitative",
                        "axis": _axis_style(x_label),
                        "scale": {"zero": False},
                    },
                    "y": {
                        "field": y_col,
                        "type": "quantitative",
                        "axis": _axis_style(y_label),
                        "scale": {"zero": False},
                    },
                    "color": color_enc,
                    "tooltip": build_structured_tooltips(
                        list(df.columns), "point", lab, viz_data=df
                    ),
                }
            },
            {
                "mark": {
                    "type": "text",
                    "dy": -10,
                    "fontSize": 10,
                    "fontWeight": "bold"
                },
                "encoding": {
                    "x": {
                        "field": x_col,
                        "type": "quantitative"
                    },
                    "y": {
                        "field": y_col,
                        "type": "quantitative"
                    },
                    "text": {
                        "field": color_dim,
                        "type": "nominal"
                    },
                    "color": color_enc
                }
            }
        ],
        "width": 600,
        "height": 450,
    }

    return inject_wb_config(spec)


def build_correlation_temporal_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
) -> dict:
    """Connected scatterplot: 2 indicators, multi-country, multi-year."""
    ind_cols = result.indicator_cols
    if len(ind_cols) < 2:
        raise ValueError("correlation_temporal spec requires 2 indicator columns")

    x_col, y_col = ind_cols[0], ind_cols[1]
    lab = indicator_labels or {}
    x_label = lab.get(x_col, x_col.replace("_", " ").title())
    y_label = lab.get(y_col, y_col.replace("_", " ").title())

    rows = df.dropna(subset=[x_col, y_col]).to_dict(orient="records")
    color_dim = result.color_dim or "country"

    # Layer: lines + points
    base_enc: dict = {
        "x": {
            "field": x_col,
            "type": "quantitative",
            "axis": _axis_style(x_label),
            "scale": {"zero": False},
        },
        "y": {
            "field": y_col,
            "type": "quantitative",
            "axis": _axis_style(y_label),
            "scale": {"zero": False},
        },
        "color": _color_encoding(color_dim),
        "order": {"field": "year", "type": "temporal"},
        "tooltip": build_structured_tooltips(
            list(df.columns), "line", lab, viz_data=df
        ),
    }

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": rows},
        "layer": [
            {
                "mark": {"type": "line", "strokeWidth": 2, "opacity": 0.6},
                "encoding": {k: v for k, v in base_enc.items() if k != "tooltip"},
            },
            {
                "mark": {"type": "circle", "size": 40, "opacity": 0.9},
                "encoding": base_enc,
            },
        ],
        "width": 550,
        "height": 450,
    }
    return inject_wb_config(spec)


def build_temporal_multi_indicator_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    y_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Faceted (Small Multiples) multi-axis line chart: 2-4 indicators, multi-year.

    Complies with Grammar of Graphics by strictly avoiding dual-axis overlapping.
    Uses Vega-Lite `vconcat` to create vertically stacked charts that share a
    common X-axis (time), giving each indicator its own isolated Y-axis plane.
    """
    ind_cols = result.indicator_cols
    if not ind_cols:
        raise ValueError("temporal_multi_indicator spec requires indicator_cols")

    lab = indicator_labels or {}
    rows = df.to_dict(orient="records")

    label_expr = _value_label_expr(unit_measure)
    charts = []
    for i, col in enumerate(ind_cols):
        color = WB_CAT_COLORS[i % len(WB_CAT_COLORS)]
        col_label = lab.get(col, col.replace("_", " ").title())
        max_abs = float(df[col].abs().max()) if col in df.columns else None
        tt_fmt = _compute_tooltip_format(max_abs, unit_measure)
        y_axis = {
            **_axis_style(),
            "title": None,  # Remove vertical Y-axis title
            "labelExpr": label_expr,
        }

        # Only show X-axis labels on the bottom-most chart to reduce clutter
        x_enc = _x_temporal_encoding(result.temporal_frequency)
        if i < len(ind_cols) - 1:
            x_enc = {**x_enc, "axis": {**x_enc.get("axis", {}), "labels": False, "title": None}}

        tooltip_cols = _multi_indicator_tooltip_columns(list(df.columns), col)
        layer_enc: dict = {
            "x": x_enc,
            "y": {
                "field": col,
                "type": "quantitative",
                "axis": y_axis,
                "scale": {"zero": False},
            },
            "color": {"value": color},
            "tooltip": build_structured_tooltips(
                tooltip_cols, "line", lab, value_format=tt_fmt, viz_data=df,
                temporal_freq=result.temporal_frequency,
                dim_name_labels=result.dim_name_labels,
            ),
        }
        charts.append(
            {
                "title": {
                    "text": col_label,
                    "color": color,
                    "fontSize": 12,
                    "fontWeight": "bold",
                    "anchor": "start",
                    "offset": 4
                },
                "width": 680,
                "height": 140,  # Fixed height per small multiple
                "mark": {
                    "type": "line",
                    "strokeWidth": 3,
                    "strokeCap": "round",
                    "color": color,
                    "point": _LINE_HOVER_POINT,
                },
                "encoding": layer_enc,
            }
        )

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": rows},
        "vconcat": charts,
        "resolve": {"scale": {"x": "shared"}},
    }
    return inject_wb_config(spec)


def build_fallback_line_spec(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    y_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Fallback: best-effort line chart for unclassified data shapes."""
    cols = set(df.columns)
    x_col = (
        "year"
        if "year" in cols
        else ("time_period" if "time_period" in cols else df.columns[0])
    )
    y_col = (
        "value"
        if "value" in cols
        else ("obs_value" if "obs_value" in cols else df.columns[-1])
    )
    max_abs = float(df[y_col].abs().max()) if y_col in df.columns else None
    tt_fmt = _compute_tooltip_format(max_abs, unit_measure)
    y_ax = {
        **_axis_style(),
        "title": None,
        "labelExpr": _value_label_expr(unit_measure),
    }

    encoding: dict = {
        "x": _x_temporal_encoding(result.temporal_frequency) if "year" in x_col else {
            "field": x_col,
            "type": "ordinal",
            "axis": _axis_style(),
        },
        "y": {"field": y_col, "type": "quantitative", "axis": y_ax},
        "tooltip": build_structured_tooltips(
            list(df.columns),
            "line",
            indicator_labels,
            value_format=tt_fmt,
            viz_data=df,
            temporal_freq=result.temporal_frequency,
            dim_name_labels=result.dim_name_labels,
        ),
    }
    if result.color_dim and result.color_dim in cols:
        n_items = df[result.color_dim].nunique()
        _domain_labels = list(df[result.color_dim].unique())
        encoding["color"] = _color_encoding(
            result.color_dim,
            mark_type="line",
            n_items=n_items,
            legend_title=result.dim_name_labels.get(result.color_dim),
            domain_labels=_domain_labels,
        )

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": df.to_dict(orient="records")},
        "mark": {
            "type": "line",
            "strokeWidth": 3,
            "strokeCap": "round",
            "point": _LINE_HOVER_POINT,
        },
        "encoding": encoding,
        "width": 600,
        "height": 350,
    }
    return inject_wb_config(spec)


# Dispatch table: strategy → builder function
STRATEGY_BUILDERS: dict[ChartStrategy, callable] = {
    ChartStrategy.TEMPORAL_SINGLE: build_temporal_single_spec,
    ChartStrategy.CROSS_SECTIONAL: build_cross_sectional_spec,
    ChartStrategy.DISTRIBUTION: build_distribution_spec,
    ChartStrategy.BREAKDOWN_COMPARISON: build_breakdown_comparison_spec,
    ChartStrategy.SMALL_MULTIPLES: build_small_multiples_spec,
    ChartStrategy.HEATMAP: build_heatmap_spec,
    ChartStrategy.STACKED_AREA: build_stacked_area_spec,
    ChartStrategy.CHOROPLETH: build_choropleth_spec,
    ChartStrategy.CORRELATION: build_correlation_spec,
    ChartStrategy.CORRELATION_TEMPORAL: build_correlation_temporal_spec,
    ChartStrategy.TEMPORAL_MULTI_IND: build_temporal_multi_indicator_spec,
    ChartStrategy.FALLBACK_LINE: build_fallback_line_spec,
}


def dispatch_spec(
    strategy: ChartStrategy,
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    y_label: str = "Value",
    x_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Call the right spec builder for the given strategy."""
    builder = STRATEGY_BUILDERS[strategy]
    if strategy in (
        ChartStrategy.TEMPORAL_SINGLE,
        ChartStrategy.TEMPORAL_MULTI_IND,
        ChartStrategy.BREAKDOWN_COMPARISON,
        ChartStrategy.SMALL_MULTIPLES,
        ChartStrategy.STACKED_AREA,
        ChartStrategy.CHOROPLETH,
        ChartStrategy.FALLBACK_LINE,
        ChartStrategy.HEATMAP,
    ):
        return builder(df, title, result, indicator_labels, y_label, unit_measure)
    elif strategy in (ChartStrategy.CROSS_SECTIONAL, ChartStrategy.DISTRIBUTION):
        return builder(df, title, result, indicator_labels, x_label, unit_measure)
    else:
        return builder(df, title, result, indicator_labels)


# ============================================================================
# HIGH-CARDINALITY THRESHOLDS
# ============================================================================

HIGH_CARDINALITY_THRESHOLDS: dict[str, int] = {
    # Maximum color series in a TEMPORAL_SINGLE line chart.
    # Strategy routing enforces this before the builder is called.
    "line_max_series": 8,
    # Minimum country count to switch from line to strip (beeswarm) in single-year views.
    "beeswarm_threshold": 8,
    # Minimum breakdown count to prefer SMALL_MULTIPLES over BREAKDOWN_COMPARISON.
    "facet_threshold": 4,
    # Maximum color series in any context where the strategy router can’t pre-filter.
    "top_n_series": 12,
    # Maximum facet panels in SMALL_MULTIPLES.
    # Chatbot UIs embed charts at fixed widths; beyond this panels become unreadably
    # small and the page overflows vertically.
    "small_multiples_max_facets": 6,
    # Maximum bar rows in CROSS_SECTIONAL horizontal bar charts.
    # Beyond this, bars become hair-thin and labels collide.
    "cross_sectional_max_items": 20,
}

# Keep the standalone constant as a typed alias for backward compat with existing tests.
SMALL_MULTIPLES_MAX_FACETS: int = HIGH_CARDINALITY_THRESHOLDS["small_multiples_max_facets"]


# Keep legacy aliases for backward compat with existing tests
def should_use_beeswarm(
    viz_data: pd.DataFrame,
    chart_type: str | None = None,
    color_dim: str | None = None,
) -> bool:
    if color_dim is None or color_dim not in viz_data.columns:
        return False
    if chart_type and chart_type not in (None, "line", "area"):
        return False
    series_count = viz_data[color_dim].nunique()
    year_count = viz_data["year"].nunique() if "year" in viz_data.columns else 0
    return (
        series_count > HIGH_CARDINALITY_THRESHOLDS["beeswarm_threshold"]
        and year_count <= 1
    )


def build_beeswarm_spec(
    viz_data: pd.DataFrame,
    title: str,
    value_col: str = "value",
    color_col: str = "country",
) -> dict:
    """Legacy alias → delegates to build_distribution_spec."""
    r = StrategyResult(ChartStrategy.DISTRIBUTION, "beeswarm", color_dim=color_col)
    # rename value_col if needed
    df = viz_data.copy()
    if value_col != "value" and value_col in df.columns:
        df = df.rename(columns={value_col: "value"})
    return build_distribution_spec(df, title, r)


# ============================================================================
# FREQUENCY / CHART TYPE MAPPINGS (unchanged from original)
# ============================================================================

FREQUENCY_TO_TIMEUNIT: dict[str, str] = {
    "A": "year",
    "M": "yearmonth",
    "Q": "yearquarter",
}

PERIODICITY_KEYWORDS: dict[str, list[str]] = {
    "A": ["annual", "yearly"],
    "M": ["month", "monthly"],
    "Q": ["quarter", "quarterly"],
}

CHART_TYPE_KEYWORDS: dict[str, list[str]] = {
    "line": ["line", "trend", "time series", "over time"],
    "bar": ["bar", "column", "ranking", "compare", "histogram"],
    "point": ["scatter", "point", "dot", "correlation", "bubble"],
    "area": ["area", "filled", "cumulative", "stacked"],
    "tick": ["tick", "strip", "beeswarm", "distribution"],
    # NOTE: "heatmap" must be evaluated before "map" because the substring "map"
    # appears inside "heatmap" and "heat map".  Insertion order is significant.
    "heatmap": ["heatmap", "heat map", "heat"],
    "map": ["map", "choropleth", "geoshape", "geographic"],
}
DEFAULT_CHART_TYPE: str = "line"


def parse_chart_type_hint(chart_type: str | None) -> str:
    if not chart_type:
        return DEFAULT_CHART_TYPE
    hint = chart_type.lower().strip()
    for mark_type, keywords in CHART_TYPE_KEYWORDS.items():
        if any(keyword in hint for keyword in keywords):
            return mark_type
    return DEFAULT_CHART_TYPE


_REASON_CHART_PHRASES: dict[str, str] = {
    "line": "line chart",
    "bar": "bar chart",
    "area": "area chart",
    "point": "point chart",
    "tick": "strip chart",
}


def chart_type_phrase_for_reason(mark_type: str | None) -> str:
    """Human phrase for strategy / tool ``reason`` (aligned with mark type hint or render)."""
    if not mark_type:
        return _REASON_CHART_PHRASES["line"]
    normalized = mark_type.lower().strip()
    return _REASON_CHART_PHRASES.get(normalized, f"{normalized} chart")


def patch_strategy_reason_chart_phrase(reason: str, mark_type: str) -> str:
    """Replace the trailing ``→ …`` segment so it reflects the given mark type."""
    sep = " → "
    if sep not in reason:
        return reason
    prefix, _old = reason.rsplit(sep, 1)
    return f"{prefix}{sep}{chart_type_phrase_for_reason(mark_type)}"


def extract_top_level_mark_type(vl_spec: dict) -> str | None:
    """Best-effort mark ``type`` from a single-view Vega-Lite spec."""
    mark = vl_spec.get("mark")
    if isinstance(mark, str):
        return mark
    if isinstance(mark, dict):
        t = mark.get("type")
        return t if isinstance(t, str) else None
    return None


def infer_frequency_from_periodicity(periodicity: str) -> str | None:
    pl = periodicity.lower()
    for code, kws in PERIODICITY_KEYWORDS.items():
        if any(kw in pl for kw in kws):
            return code
    return None


def should_use_temporal_x_axis(
    viz_data: pd.DataFrame, chart_type: str | None, available_dimensions: list[str]
) -> tuple[bool, str | None]:
    if "year" not in available_dimensions:
        return False, _select_categorical_dimension(available_dimensions)
    year_count = viz_data["year"].nunique() if "year" in viz_data.columns else 0
    if year_count > 1:
        return True, None
    mark_type = parse_chart_type_hint(chart_type) if chart_type else "line"
    pref = {"tick": 1.0, "point": 0.7, "bar": 0.5, "line": 0.2, "area": 0.1}
    cat_field = _select_categorical_dimension(available_dimensions)
    if cat_field is None:
        return True, None
    if pref.get(mark_type, 0.5) >= 0.5:
        return False, cat_field
    return True, None


def _select_categorical_dimension(available_dimensions: list[str]) -> str | None:
    for dim in ["country", "sex", "age", "urbanisation", "education", "income_group"]:
        if dim in available_dimensions:
            return dim
    for dim in available_dimensions:
        if dim not in ["year", "value", "time_period", "obs_value"]:
            return dim
    return None


# ============================================================================
# DATA PREPARATION RULES (unchanged)
# ============================================================================


@dataclass
class DataPreparationRule:
    chart_type: str
    frequency: str | None
    action: Literal["year_strings", "datetime"]
    description: str


DATA_PREPARATION_RULES: list[DataPreparationRule] = [
    DataPreparationRule(
        "bar", "A", "year_strings", "Bar charts with annual data use year strings"
    ),
    DataPreparationRule(
        "bar",
        None,
        "year_strings",
        "Bar charts when API frequency is unknown — assume annual WDI-style years",
    ),
    DataPreparationRule("*", "*", "datetime", "Default: datetime"),
]


def get_data_preparation_action(
    chart_type: str, frequency: str | None
) -> Literal["year_strings", "datetime"]:
    for rule in DATA_PREPARATION_RULES:
        if (rule.chart_type == "*" or rule.chart_type == chart_type) and (
            rule.frequency == "*" or rule.frequency == frequency
        ):
            return rule.action
    return "datetime"


_YEAR_GAP_FILL_MAX_SPAN = 400


def frequency_allows_annual_year_gap_fill(data_frequency: str | None) -> bool:
    """True when data are treated as annual so missing calendar years can be inserted."""
    if data_frequency is None or not str(data_frequency).strip():
        return True
    code = str(data_frequency).strip().upper()
    if code in FREQUENCY_TO_TIMEUNIT and code != "A":
        return False
    return code in ("A", "ANNUAL", "Y", "YEAR", "YA")


def _clone_year_field(y_int: int, sample: Any) -> Any:
    """Match ``year`` dtype/shape used in the source group (string, datetime, int)."""
    if isinstance(sample, str):
        stripped = sample.strip()
        if len(stripped) == 4 and stripped.isdigit():
            return str(y_int)
        return pd.Timestamp(year=y_int, month=1, day=1)
    if isinstance(sample, pd.Timestamp):
        return pd.Timestamp(year=y_int, month=1, day=1)
    if isinstance(sample, Integral) and not isinstance(sample, bool):
        return int(y_int)
    if isinstance(sample, float) and not pd.isna(sample) and sample == int(sample):
        return int(y_int)
    return pd.Timestamp(year=y_int, month=1, day=1)


def _coerce_year_column_to_int(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.dt.year.astype("Int64")
    parsed = pd.to_datetime(series, errors="coerce")
    if parsed.notna().mean() >= 0.99 and parsed.notna().any():
        return parsed.dt.year.astype("Int64")
    num = pd.to_numeric(series, errors="coerce")
    return num.round().astype("Int64")


def fill_missing_calendar_years_annual(
    df: pd.DataFrame,
    data_frequency: str | None,
) -> pd.DataFrame:
    """Insert NaN rows for missing integer calendar years within each series' span.

    Each *series* is defined by every column except ``year`` and ``value`` (e.g. one
    country). For that series, all calendar years from min(year) to max(year) appear
    exactly once; gaps in the source (e.g. no 2010) become explicit rows with null
    ``value``. Skipped when frequency is not annual, years cannot be coerced, any
    (series, year) duplicates exist, or the span exceeds ``_YEAR_GAP_FILL_MAX_SPAN``.
    """
    if df.empty or "year" not in df.columns or "value" not in df.columns:
        return df
    if not frequency_allows_annual_year_gap_fill(data_frequency):
        return df

    y_int = _coerce_year_column_to_int(df["year"])
    if y_int.isna().all():
        return df

    work = df.copy()
    work["_yi"] = y_int
    work = work.loc[~work["_yi"].isna()].copy()
    work["_yi"] = work["_yi"].astype(int)

    gcols = [c for c in work.columns if c not in ("year", "value", "_yi")]
    dup_check = work.groupby(gcols + ["_yi"], dropna=False).size()
    if (dup_check > 1).any():
        return df

    out_rows: list[pd.Series] = []
    grouped = (
        work.groupby(gcols, dropna=False)
        if gcols
        else [(tuple(), work)]
    )
    for _gkey, g in grouped:
        lo = int(g["_yi"].min())
        hi = int(g["_yi"].max())
        if hi - lo > _YEAR_GAP_FILL_MAX_SPAN:
            return df
        sample_year = g["year"].iloc[0]
        existing = set(int(x) for x in g["_yi"].tolist())
        for yi in range(lo, hi + 1):
            match = g[g["_yi"] == yi]
            if len(match) > 0:
                out_rows.append(match.iloc[0].drop(labels=["_yi"]))
            else:
                proto = g.iloc[0].drop(labels=["_yi"]).to_dict()
                proto["year"] = _clone_year_field(yi, sample_year)
                proto["value"] = float("nan")
                out_rows.append(pd.Series(proto))

    out = pd.DataFrame(out_rows)
    out = out.reindex(columns=df.columns)
    meta_cols = [c for c in df.columns if c not in ("year", "value")]
    out["_sy"] = _coerce_year_column_to_int(out["year"])
    sort_keys = [k for k in (*meta_cols, "_sy") if k in out.columns]
    out = out.sort_values(by=sort_keys, na_position="last").drop(columns=["_sy"])
    return out


def should_prepare_as_datetime(
    viz_data: pd.DataFrame, chart_type: str, frequency: str | None
) -> bool:
    return get_data_preparation_action(chart_type, frequency) == "datetime"


# ============================================================================
# POST-PROCESSING RULES (kept for backward compat with existing Draco path)
# ============================================================================


@dataclass
class PostProcessingRule:
    name: str
    applies_to_mark_types: list[str]
    description: str

    def should_apply(self, mark_type: str, encoding: dict, data: dict) -> bool:
        raise NotImplementedError

    def apply(
        self,
        spec: dict,
        data_frequency: str | None = None,
        unit_measure: str | None = None,
    ) -> dict:
        raise NotImplementedError


def _first_non_null_dataset_value(dataset: list, field: str) -> object:
    for row in dataset:
        if field in row:
            v = row[field]
            if v is not None:
                return v
    return None


# Ordinal ``year`` values at or above this magnitude are treated as epoch milliseconds
# (typical Altair / Vega-Lite JSON for datetimes), not calendar years.
_YEAR_ORDINAL_EPOCH_MS_THRESHOLD = 1e12


def _year_ordinal_value_needs_temporal_encoding(value: object) -> bool:
    """True when x is ordinal but values are ISO datetimes or epoch ms (Vega-Lite)."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        return "T" in value
    if isinstance(value, (int, float)):
        fv = float(value)
        # Altair often serializes datetimes as milliseconds in embedded datasets
        return abs(fv) >= _YEAR_ORDINAL_EPOCH_MS_THRESHOLD
    return False


def _extract_spec_dataset_rows(spec: dict) -> list[dict] | None:
    """Return embedded chart rows from ``data.values`` or ``datasets[name]``."""
    data = spec.get("data")
    if isinstance(data, dict) and "values" in data:
        v = data.get("values")
        return v if isinstance(v, list) else None
    ds_name = data.get("name") if isinstance(data, dict) else None
    if ds_name and isinstance(spec.get("datasets"), dict):
        rows = spec["datasets"].get(ds_name)
        return rows if isinstance(rows, list) else None
    return None


def _single_obs_year_to_int(value: object) -> int | None:
    """Parse one observation's year field to a calendar year, or None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if len(s) >= 4 and s[:4].isdigit():
            return int(s[:4])
        ts = pd.to_datetime(s, errors="coerce")
        if pd.notna(ts):
            return int(ts.year)
        return None
    if isinstance(value, pd.Timestamp):
        return int(value.year)
    return None


class ContiguousCalendarYearDomainRule(PostProcessingRule):
    """Ordinal/nominal ``year`` / ``time_period`` on x: full calendar year range on the scale.

    Applies to marks that commonly use a discrete year axis (bar, line, area, point, tick).
    Does **not** apply when ``x`` is ``temporal`` (handled separately; continuous time ≠ discrete domain).
    """

    def __init__(self):
        super().__init__(
            "contiguous_calendar_year_domain",
            ["bar", "line", "area", "point", "tick"],
            "Ordinal/nominal year x: explicit scale.domain for every calendar year in min–max span",
        )

    def apply(self, spec, data_frequency=None, unit_measure=None):
        if not frequency_allows_annual_year_gap_fill(data_frequency):
            return spec
        if "encoding" not in spec or "x" not in spec["encoding"]:
            return spec
        mark_type = (
            spec.get("mark", {}).get("type")
            if isinstance(spec.get("mark"), dict)
            else spec.get("mark")
        )
        if mark_type not in self.applies_to_mark_types:
            return spec
        x = spec["encoding"]["x"]
        xf = x.get("field")
        if xf not in ("year", "time_period"):
            return spec
        if x.get("type") not in ("ordinal", "nominal"):
            return spec
        if x.get("scale", {}).get("domain") is not None:
            return spec
        rows = _extract_spec_dataset_rows(spec)
        if not rows or len(rows) < 2:
            return spec
        years: list[int] = []
        template: object | None = None
        for row in rows:
            if not isinstance(row, dict) or xf not in row:
                continue
            raw = row.get(xf)
            if raw is None:
                continue
            if template is None:
                template = raw
            yi = _single_obs_year_to_int(raw)
            if yi is not None:
                years.append(yi)
        if len(years) < 2:
            return spec
        lo, hi = min(years), max(years)
        if hi - lo > _YEAR_GAP_FILL_MAX_SPAN:
            return spec
        if template is None:
            return spec
        domain = [_clone_year_field(y, template) for y in range(lo, hi + 1)]
        x.setdefault("scale", {})["domain"] = domain
        # Explicit sort matches domain order (helps Vega-Lite / Vega compile stability).
        x["sort"] = domain
        return spec


class OrdinalToTemporalRule(PostProcessingRule):
    def __init__(self):
        super().__init__(
            "ordinal_to_temporal",
            ["line", "area", "point", "tick", "bar"],
            "Fix ordinal→temporal for time fields (ISO or epoch ms), including bars",
        )

    def should_apply(self, mark_type, x_enc, dataset):
        if mark_type not in self.applies_to_mark_types:
            return False
        if x_enc.get("type") != "ordinal":
            return False
        x_field = x_enc.get("field")
        if x_field not in ["year", "time_period"]:
            return False
        if not dataset:
            return False
        sample = _first_non_null_dataset_value(dataset, x_field)
        return _year_ordinal_value_needs_temporal_encoding(sample)

    def apply(self, spec, data_frequency=None, unit_measure=None):
        mark_type = (
            spec.get("mark", {}).get("type")
            if isinstance(spec.get("mark"), dict)
            else spec.get("mark")
        )
        if "encoding" not in spec or "x" not in spec["encoding"]:
            return spec
        x_enc = spec["encoding"]["x"]
        ds_name = spec.get("data", {}).get("name")
        if not ds_name or "datasets" not in spec:
            return spec
        dataset = spec["datasets"].get(ds_name, [])
        if self.should_apply(mark_type, x_enc, dataset):
            x_enc["type"] = "temporal"
        return spec


class ApplyTimeUnitRule(PostProcessingRule):
    def __init__(self):
        super().__init__(
            "apply_timeunit",
            ["line", "area", "point", "tick"],
            "Add timeUnit from frequency",
        )

    def should_apply(self, x_enc, freq):
        return freq in FREQUENCY_TO_TIMEUNIT and x_enc.get("type") == "temporal"

    def apply(self, spec, data_frequency=None, unit_measure=None):
        if "encoding" not in spec or "x" not in spec["encoding"]:
            return spec
        x_enc = spec["encoding"]["x"]
        if self.should_apply(x_enc, data_frequency):
            x_enc["timeUnit"] = FREQUENCY_TO_TIMEUNIT[data_frequency]
        return spec


class FixValueAxisEncodingRule(PostProcessingRule):
    """Altair can infer ordinal for `value` after Draco strips types; fix for line/area/point."""

    def __init__(self):
        super().__init__(
            "fix_value_axis_encodings",
            ["point", "line", "area"],
            "Fix ordinal y on value for line/area/point; point-only size cleanup",
        )

    def should_apply(self, spec, data_frequency=None):
        mark_type = (
            spec.get("mark", {}).get("type")
            if isinstance(spec.get("mark"), dict)
            else spec.get("mark")
        )
        return mark_type in self.applies_to_mark_types

    def apply(self, spec, data_frequency=None, unit_measure=None):
        if not self.should_apply(spec, data_frequency):
            return spec
        if "encoding" not in spec:
            return spec
        mark_type = (
            spec.get("mark", {}).get("type")
            if isinstance(spec.get("mark"), dict)
            else spec.get("mark")
        )
        y = spec["encoding"].get("y", {})
        if y.get("type") == "ordinal" and y.get("field") == "value":
            y["type"] = "quantitative"
            y.setdefault("scale", {})["type"] = "linear"
        if mark_type == "point":
            sz = spec["encoding"].get("size", {})
            if sz.get("aggregate") == "count" and "field" not in sz:
                del spec["encoding"]["size"]
        return spec


class TemporalAxisCleanupRule(PostProcessingRule):
    def __init__(self):
        super().__init__(
            "temporal_axis_cleanup",
            ["line", "area", "point", "bar"],
            "Remove title from temporal x-axis",
        )

    def should_apply(self, spec, data_frequency=None):
        mark_type = (
            spec.get("mark", {}).get("type")
            if isinstance(spec.get("mark"), dict)
            else spec.get("mark")
        )
        if mark_type not in self.applies_to_mark_types:
            return False
        return spec.get("encoding", {}).get("x", {}).get("type") == "temporal"

    def apply(self, spec, data_frequency=None, unit_measure=None):
        if not self.should_apply(spec):
            return spec
        x = spec["encoding"]["x"]
        x.setdefault("axis", {})
        x["axis"]["title"] = None
        x["axis"]["labelAngle"] = 0
        x["axis"].setdefault("format", "%Y")
        x["axis"].setdefault("tickCount", 5)
        return spec


class DiscreteYearBarXAxisRule(PostProcessingRule):
    """Vega-Lite defaults often rotate discrete x labels on bars; force horizontal years."""

    def __init__(self):
        super().__init__(
            "discrete_year_bar_x_axis",
            ["bar"],
            "Horizontal labels for ordinal/nominal year on column/bar x-axis",
        )

    def should_apply(self, spec, data_frequency=None):
        mark_type = (
            spec.get("mark", {}).get("type")
            if isinstance(spec.get("mark"), dict)
            else spec.get("mark")
        )
        if mark_type not in self.applies_to_mark_types:
            return False
        x = spec.get("encoding", {}).get("x", {})
        if x.get("field") not in ("year", "time_period"):
            return False
        return x.get("type") in ("ordinal", "nominal")

    def apply(self, spec, data_frequency=None, unit_measure=None):
        if not self.should_apply(spec):
            return spec
        x = spec["encoding"]["x"]
        x.setdefault("axis", {})
        x["axis"]["labelAngle"] = 0
        return spec


class ValueAxisLabelFormatRule(PostProcessingRule):
    def __init__(self):
        super().__init__(
            "value_axis_label_format",
            ["bar", "line", "area", "point", "tick"],
            "Apply compact/value-aware y-axis label formatting",
        )

    def should_apply(self, spec, data_frequency=None):
        mark_type = (
            spec.get("mark", {}).get("type")
            if isinstance(spec.get("mark"), dict)
            else spec.get("mark")
        )
        if mark_type not in self.applies_to_mark_types:
            return False
        y = spec.get("encoding", {}).get("y", {})
        return y.get("type") == "quantitative" and y.get("field") in {
            "value",
            "obs_value",
        }

    def apply(self, spec, data_frequency=None, unit_measure=None):
        if not self.should_apply(spec, data_frequency):
            return spec
        y = spec["encoding"]["y"]
        y.setdefault("axis", {})
        y["axis"]["labelExpr"] = _value_label_expr(unit_measure)
        return spec


# Internal columns for year-gap dashed line segments (unlikely to collide with WDI columns).
_LINE_GAP_SEG_DETAIL = "_d360_lseg"
_LINE_GAP_STROKE_FLAG = "_d360_ygap"


class LineYearGapStrokeDashRule(PostProcessingRule):
    """Temporal / discrete-year line charts: dashed stroke across multi-year gaps.

    Vega-Lite draws one continuous polyline per color series. We split each
    consecutive observation pair into its own ``detail`` group and use
    ``strokeDash`` so segments that skip one or more calendar years render dashed.
    """

    def __init__(self):
        super().__init__(
            "line_year_gap_stroke_dash",
            ["line"],
            "Dashed line segments where consecutive points differ by >1 calendar year",
        )

    def apply(self, spec, data_frequency=None, unit_measure=None):
        if not isinstance(spec, dict):
            return spec
        if "layer" in spec and isinstance(spec["layer"], list):
            self._apply_to_layer_root(spec)
            return spec
        if "spec" in spec and isinstance(spec.get("spec"), dict):
            inner = spec["spec"]
            # Facet + inner layer (e.g. line + point from interactive) — data often on facet root
            if "layer" in inner and isinstance(inner["layer"], list):
                self._apply_to_layer_root(inner, data_root=spec)
                return spec
            if self._is_candidate_line_spec(inner):
                self._maybe_transform_line_spec(inner, spec)
            return spec
        if self._is_candidate_line_spec(spec):
            self._maybe_transform_line_spec(spec, spec)
        return spec

    def _apply_to_layer_root(
        self, layer_parent: dict, data_root: dict | None = None
    ) -> None:
        root = data_root if data_root is not None else layer_parent
        line_layers = [
            layer
            for layer in layer_parent["layer"]
            if isinstance(layer, dict) and self._is_candidate_line_spec(layer)
        ]
        if len(line_layers) != 1:
            return
        self._maybe_transform_line_spec(line_layers[0], root)

    def _mark_type(self, enc_spec: dict) -> str | None:
        m = enc_spec.get("mark")
        if isinstance(m, str):
            return m
        if isinstance(m, dict):
            return m.get("type")
        return None

    def _is_candidate_line_spec(self, enc_spec: dict) -> bool:
        if self._mark_type(enc_spec) != "line":
            return False
        enc = enc_spec.get("encoding")
        if not isinstance(enc, dict):
            return False
        x = enc.get("x", {})
        if not isinstance(x, dict):
            return False
        xf = x.get("field")
        if xf not in ("year", "time_period"):
            return False
        # ApplyTimeUnitRule sets ``timeUnit: "year"`` for annual (A) data; still one value
        # per calendar year — allow dashed segments across missing years. Reject finer
        # units (month, quarter) where calendar-year gap logic does not apply.
        if not self._x_timeunit_allows_year_gap_segments(x):
            return False
        if x.get("type") not in ("temporal", "ordinal", "nominal"):
            return False
        y = enc.get("y", {})
        if not isinstance(y, dict) or y.get("type") != "quantitative":
            return False
        if not y.get("field"):
            return False
        if enc.get("detail") is not None:
            return False
        if enc.get("strokeDash") is not None:
            return False
        return True

    @staticmethod
    def _x_timeunit_allows_year_gap_segments(x: dict) -> bool:
        tu = x.get("timeUnit")
        if tu is None:
            return True
        if isinstance(tu, str):
            return tu == "year"
        if isinstance(tu, dict):
            return tu.get("unit") == "year"
        return False

    def _find_inline_values_holder(self, line_spec: dict, data_root: dict) -> dict | None:
        for candidate in (line_spec, data_root):
            data = candidate.get("data")
            if isinstance(data, dict) and isinstance(data.get("values"), list):
                return candidate
        return None

    def _write_inline_values(self, holder: dict, rows: list[dict]) -> None:
        data = holder.get("data")
        if isinstance(data, dict) and "values" in data:
            data["values"] = rows

    def _named_dataset_rows(
        self, line_spec: dict, data_root: dict
    ) -> tuple[str, list] | None:
        for candidate in (line_spec, data_root):
            data = candidate.get("data")
            if not isinstance(data, dict):
                continue
            name = data.get("name")
            if (
                isinstance(name, str)
                and isinstance(data_root.get("datasets"), dict)
                and isinstance(data_root["datasets"].get(name), list)
            ):
                return name, data_root["datasets"][name]
        return None

    def _set_named_dataset_rows(self, data_root: dict, name: str, rows: list[dict]) -> None:
        data_root.setdefault("datasets", {})[name] = rows

    def _series_keys(self, encoding: dict) -> list[str]:
        c = encoding.get("color")
        if isinstance(c, dict) and isinstance(c.get("field"), str):
            return [c["field"]]
        return []

    def _facet_field_keys(self, data_root: dict) -> list[str]:
        """Facet / row / column fields so multi-panel specs split series per panel."""
        keys: list[str] = []
        for name in ("facet", "row", "column"):
            node = data_root.get(name)
            if not isinstance(node, dict):
                continue
            f = node.get("field")
            if isinstance(f, str):
                keys.append(f)
        return keys

    def _dedupe_sort_group(
        self, rows: list[dict], x_field: str
    ) -> list[tuple[int, dict]]:
        by_year: dict[int, dict] = {}
        order: list[int] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            yi = _single_obs_year_to_int(row.get(x_field))
            if yi is None:
                continue
            if yi not in by_year:
                order.append(yi)
            by_year[yi] = dict(row)
        order.sort()
        return [(y, by_year[y]) for y in order]

    def _group_rows_by_series(
        self, rows: list[dict], series_keys: list[str]
    ) -> dict[tuple, list[dict]]:
        groups: defaultdict[tuple, list[dict]] = defaultdict(list)
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = tuple(row.get(k) for k in series_keys) if series_keys else (None,)
            groups[key].append(dict(row))
        return dict(groups)

    def _any_calendar_year_gap(
        self, groups: dict[tuple, list[dict]], x_field: str
    ) -> bool:
        for grp_rows in groups.values():
            chain = self._dedupe_sort_group(grp_rows, x_field)
            if len(chain) < 2:
                continue
            for i in range(len(chain) - 1):
                y0 = chain[i][0]
                y1 = chain[i + 1][0]
                if y1 - y0 > 1:
                    return True
        return False

    def _build_segment_rows(
        self, groups: dict[tuple, list[dict]], x_field: str, series_keys: list[str]
    ) -> list[dict]:
        out: list[dict] = []
        seg_i = 0
        for key, grp_rows in groups.items():
            chain = self._dedupe_sort_group(grp_rows, x_field)
            if len(chain) < 2:
                continue
            prefix = "_".join("" if v is None else str(v) for v in key)
            for i in range(len(chain) - 1):
                y0, r0 = chain[i]
                y1, r1 = chain[i + 1]
                gap = 1 if (y1 - y0) > 1 else 0
                sid = f"{prefix}_{seg_i}" if prefix else str(seg_i)
                seg_i += 1
                a = {**r0, _LINE_GAP_SEG_DETAIL: sid, _LINE_GAP_STROKE_FLAG: gap}
                b = {**r1, _LINE_GAP_SEG_DETAIL: sid, _LINE_GAP_STROKE_FLAG: gap}
                out.append(a)
                out.append(b)
        return out

    def _strip_internal_tooltip_channels(self, encoding: dict) -> None:
        tips = encoding.get("tooltip")
        if not isinstance(tips, list):
            return
        internal = {_LINE_GAP_SEG_DETAIL, _LINE_GAP_STROKE_FLAG}
        encoding["tooltip"] = [
            t
            for t in tips
            if not (isinstance(t, dict) and t.get("field") in internal)
        ]

    def _maybe_transform_line_spec(self, line_spec: dict, data_root: dict) -> None:
        enc = line_spec.get("encoding")
        if not isinstance(enc, dict):
            return
        x = enc.get("x", {})
        x_field = x.get("field") if isinstance(x, dict) else None
        if x_field not in ("year", "time_period"):
            return

        holder = self._find_inline_values_holder(line_spec, data_root)
        rows: list[dict] | None = None
        if holder is not None:
            v = holder["data"]["values"]
            rows = v if isinstance(v, list) else None
        else:
            named = self._named_dataset_rows(line_spec, data_root)
            if named is not None:
                _, rows_list = named
                rows = rows_list if isinstance(rows_list, list) else None
        if not rows or len(rows) < 2:
            return

        facet_keys = self._facet_field_keys(data_root)
        series_keys = list(
            dict.fromkeys([*self._series_keys(enc), *facet_keys]),
        )
        groups = self._group_rows_by_series(rows, series_keys)
        if not self._any_calendar_year_gap(groups, x_field):
            return

        new_rows = self._build_segment_rows(groups, x_field, series_keys)
        if len(new_rows) < 2:
            return

        if holder is not None:
            self._write_inline_values(holder, new_rows)
        else:
            named = self._named_dataset_rows(line_spec, data_root)
            if named is None:
                return
            name, _ = named
            self._set_named_dataset_rows(data_root, name, new_rows)

        enc["detail"] = {"field": _LINE_GAP_SEG_DETAIL, "type": "nominal"}
        enc["strokeDash"] = {
            "condition": {
                "test": f"datum.{_LINE_GAP_STROKE_FLAG} == 1",
                "value": [6, 4],
            },
            "value": [],
        }
        self._strip_internal_tooltip_channels(enc)


class LineChartPointHoverRule(PostProcessingRule):
    """Add / enlarge line points so tooltips are easier to trigger (thin line geometry)."""

    def __init__(self):
        super().__init__(
            "line_chart_point_hover",
            ["line"],
            "Widen line tooltip hit target with point marks",
        )

    def should_apply(self, spec, data_frequency=None, unit_measure=None):
        m = spec.get("mark")
        if isinstance(m, str):
            return m == "line"
        if isinstance(m, dict):
            return m.get("type") == "line"
        return False

    def apply(self, spec, data_frequency=None, unit_measure=None):
        if not self.should_apply(spec):
            return spec
        m = spec["mark"]
        if isinstance(m, str):
            spec["mark"] = {
                "type": "line",
                "point": _LINE_HOVER_POINT,
            }
            return spec
        pt = m.get("point")
        if pt is False or pt is None or pt is True:
            m["point"] = dict(_LINE_HOVER_POINT)
        elif isinstance(pt, dict):
            sz = pt.get("size", 0)
            if not isinstance(sz, (int, float)) or sz < 40:
                m["point"] = {**pt, **_LINE_HOVER_POINT}
        return spec


class ZeroLineRule(PostProcessingRule):
    def __init__(self):
        super().__init__(
            "zero_line", ["bar", "line", "area"], "Bar charts start at zero"
        )

    def should_apply(self, spec, data_frequency=None):
        mark_type = (
            spec.get("mark", {}).get("type")
            if isinstance(spec.get("mark"), dict)
            else spec.get("mark")
        )
        return mark_type in self.applies_to_mark_types

    def apply(self, spec, data_frequency=None, unit_measure=None):
        if not self.should_apply(spec):
            return spec
        y = spec.get("encoding", {}).get("y", {})
        if y.get("type") == "quantitative":
            y.setdefault("scale", {})
            mark_type = (
                spec.get("mark", {}).get("type")
                if isinstance(spec.get("mark"), dict)
                else spec.get("mark")
            )
            if mark_type == "bar":
                y["scale"]["zero"] = True
        return spec


class ApplyWBStyleRule(PostProcessingRule):
    def __init__(self):
        super().__init__("apply_wb_style", ["*"], "Inject WB style config")

    def should_apply(self, spec, data_frequency=None):
        return True

    def apply(self, spec, data_frequency=None, unit_measure=None):
        return inject_wb_config(spec)


POST_PROCESSING_RULES: list[PostProcessingRule] = [
    OrdinalToTemporalRule(),
    ApplyTimeUnitRule(),
    FixValueAxisEncodingRule(),
    ContiguousCalendarYearDomainRule(),
    TemporalAxisCleanupRule(),
    DiscreteYearBarXAxisRule(),
    ValueAxisLabelFormatRule(),
    LineYearGapStrokeDashRule(),
    LineChartPointHoverRule(),
    ZeroLineRule(),
    ApplyWBStyleRule(),
]


# ============================================================================
# DRACO CONSTRAINT CONFIG (unchanged)
# ============================================================================


@dataclass
class DracoConstraintConfig:
    base_constraints: list[str]
    nominal_color_fields: list[str]
    color_dimension_priority: list[str]

    def __init__(self):
        self.base_constraints = ["entity(view,root,view).", "entity(mark,view,m)."]
        self.nominal_color_fields = ["country", "sex", "urbanisation", "ref_area"]
        self.color_dimension_priority = ["country", "sex", "age", "urbanisation"]


DEFAULT_DRACO_CONFIG = DracoConstraintConfig()
