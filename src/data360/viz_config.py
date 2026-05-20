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

from collections import defaultdict
import re
from dataclasses import dataclass, field
from enum import Enum
from numbers import Integral
from typing import Any, Literal

import pandas as pd

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
            "labelLimit": 200,
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
    "comp_breakdown_1": {"title": "Breakdown", "type": "nominal"},
    "comp_breakdown_2": {"title": "Sub-Breakdown", "type": "nominal"},
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
_CUSTOM_BREAKDOWN_DIMS = {"comp_breakdown_1", "comp_breakdown_2"}


def _is_homogeneous_breakdown(vals: list[str]) -> bool:
    """Return True when breakdown codes are ordinal categories of ONE metric.

    Strategy: strip trailing digits from each code. If all codes reduce to the
    same base string, they are categories of the same metric (e.g.
    IPC_IPC_PHASE1, IPC_IPC_PHASE2, IPC_IPC_PHASE3 → all become IPC_IPC_PHASE).
    Heterogeneous codes (WGI_EST, WGI_SC, WGI_SE, WGI_SR) reduce to distinct
    base strings and are correctly flagged as mixed-unit.
    """
    bases = {re.sub(r"\d+$", "", v) for v in vals}
    return len(bases) == 1 and next(iter(bases)) != ""  # non-empty shared prefix


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
    - the breakdowns are homogeneous (ordinal categories of the same metric,
      e.g. IPC Phase 1–5 are all person counts — no mixed-unit warning needed)
    """
    if color_dim not in _CUSTOM_BREAKDOWN_DIMS:
        return None
    if color_dim not in df.columns:
        return None
    vals = sorted(str(v) for v in df[color_dim].dropna().unique())
    if len(vals) <= 1:
        return None
    if _is_homogeneous_breakdown(vals):
        # Ordinal categories of one metric — list series but omit the mixed-unit warning.
        return f"Series: {', '.join(vals)}"
    series_list = ", ".join(vals)
    return f"Series: {series_list} — series may have different units/scales"


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


def _tooltip_spec_for_time_dim(col: str, viz_data: pd.DataFrame | None) -> dict:
    """Year/period tooltips: temporal only when the frame actually has datetime values."""
    title = "Year" if col == "year" else "Period"
    if viz_data is not None and col in viz_data.columns:
        s = viz_data[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            return {
                "field": col,
                "title": title,
                "type": "temporal",
                "format": "%Y",
            }
    return {"field": col, "title": title, "type": "nominal"}


def build_structured_tooltips(
    columns: list[str],
    mark_type: str,
    indicator_labels: dict[str, str] | None = None,
    value_format: str = ",.2f",
    viz_data: pd.DataFrame | None = None,
) -> list[dict]:
    """Build typed, labelled tooltip list for a Vega-Lite encoding.

    indicator_labels: optional {col_name: human_label} for indicator value columns
    in multi-indicator charts (e.g. {"gdp_per_capita": "GDP per capita (USD)"}).
    value_format: D3 format string for quantitative value fields.
    viz_data: when set, ``year`` / ``time_period`` tooltips use ``temporal`` only if
        that column is datetime64; otherwise ``nominal`` so VL does not parse string
        years as dates (which breaks ordinal x-axes).
    """
    ordered = [c for c in _TOOLTIP_PRIORITY if c in columns]
    ordered += [c for c in columns if c not in _TOOLTIP_PRIORITY]

    tooltips = []
    for col in ordered:
        if col in ("year", "time_period"):
            tooltips.append(_tooltip_spec_for_time_dim(col, viz_data))
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
            tip = {"field": col, "title": spec["title"], "type": spec["type"]}
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
    x_dim: str | None = None
    y_dim: str | None = None
    scale_incompatible: bool = False  # breakdown series need independent Y-axes


def select_strategy(
    df: pd.DataFrame,
    n_indicators: int = 1,
    chart_type_hint: str | None = None,
    indicator_cols: list[str] | None = None,
) -> StrategyResult:
    """
    Pure function: inspect DataFrame shape + intent → return ChartStrategy.

    Args:
        df: The merged/cleaned visualization DataFrame.
        n_indicators: Number of distinct indicators represented.
        chart_type_hint: Optional user hint (e.g. "scatter", "bar").
        indicator_cols: For multi-indicator DFs, the names of the value columns.
    """
    hint = parse_chart_type_hint(chart_type_hint)
    cols = set(df.columns)

    year_count = df["year"].nunique() if "year" in cols else 0
    country_count = df["country"].nunique() if "country" in cols else 0
    sex_count = df["sex"].nunique() if "sex" in cols else 0
    age_count = df["age"].nunique() if "age" in cols else 0
    urban_count = df["urbanisation"].nunique() if "urbanisation" in cols else 0
    cb1_count = df["comp_breakdown_1"].nunique() if "comp_breakdown_1" in cols else 0
    cb2_count = df["comp_breakdown_2"].nunique() if "comp_breakdown_2" in cols else 0

    breakdown_counts = {
        k: v
        for k, v in [
            ("sex", sex_count),
            ("age", age_count),
            ("urbanisation", urban_count),
            ("comp_breakdown_1", cb1_count),
            ("comp_breakdown_2", cb2_count),
        ]
        if v > 1
    }
    n_breakdowns = len(breakdown_counts)
    ind_cols = indicator_cols or []

    # ── Explicit scatter hint ──
    if hint in ("point", "scatter", "connected_scatter") and n_indicators == 2 and len(ind_cols) == 2:
        if year_count > 1:
            return StrategyResult(
                ChartStrategy.CORRELATION_TEMPORAL,
                "User requested scatter; 2 indicators, multi-year → connected scatter",
                indicator_cols=ind_cols,
                color_dim="country" if country_count > 0 else None,
            )
        return StrategyResult(
            ChartStrategy.CORRELATION,
            "User requested scatter; 2 indicators, single year → scatterplot",
            indicator_cols=ind_cols,
            color_dim="country" if country_count > 0 else None,
        )

    # ── Explicit stacked-area hint for multi-indicator ──
    # When the caller passes chart_type="stacked_area" (or "area") and supplies 2+
    # indicators, treat each indicator as a part-of-whole series rather than routing
    # to TEMPORAL_MULTI_IND (layered lines). The visualization.py pipeline will melt
    # the wide merged frame into long format before calling build_stacked_area_spec.
    if (hint in ("area", "stacked_area")) and n_indicators >= 2 and len(ind_cols) >= 2:
        if year_count > 1:
            return StrategyResult(
                ChartStrategy.STACKED_AREA,
                f"User requested stacked area; {n_indicators} indicators, {year_count} years → stacked area chart",
                indicator_cols=ind_cols,
                color_dim="indicator",
            )

    # ── Multi-indicator: 2-3 indicators ──
    if n_indicators == 2 and len(ind_cols) == 2:
        if year_count <= 1 and country_count > 1:
            # Explicit bar hint: 2 indicators × N countries, single year → grouped bar.
            # Each country gets a group of 2 side-by-side bars (one per indicator).
            # This is the canonical path for "male vs female unemployment for 3 countries".
            if hint == "bar":
                return StrategyResult(
                    ChartStrategy.BREAKDOWN_COMPARISON,
                    f"User requested bar; 2 indicators, {country_count} countries, single year → grouped bar",
                    indicator_cols=ind_cols,
                    color_dim="indicator",
                )
            return StrategyResult(
                ChartStrategy.CORRELATION,
                f"2 indicators, {country_count} countries, single year → scatterplot",
                indicator_cols=ind_cols,
                color_dim="country",
                x_dim=ind_cols[0],
                y_dim=ind_cols[1],
            )
        if year_count > 1 and country_count > 1:
            return StrategyResult(
                ChartStrategy.SMALL_MULTIPLES,
                f"2 indicators, {country_count} countries, {year_count} years → small multiples",
                indicator_cols=ind_cols,
                color_dim="indicator",
                facet_dim="country",
            )
        # 1 country, multi-year → layered lines
        return StrategyResult(
            ChartStrategy.TEMPORAL_MULTI_IND,
            f"2 indicators, 1 country, {year_count} years → layered lines",
            indicator_cols=ind_cols,
        )

    if n_indicators >= 2 and len(ind_cols) >= 2:
        # 3+ indicators, always layered lines (scatter matrix is too complex for now)
        return StrategyResult(
            ChartStrategy.TEMPORAL_MULTI_IND,
            f"{n_indicators} indicators → layered lines",
            indicator_cols=ind_cols,
        )

    # ── Single indicator from here ──

    # Stacked Area: Explicit hint or Homogeneous Breakdown + multi-year + single country
    if hint == "area" or hint == "stacked_area":
        if year_count > 1:
            color_dim = None
            if breakdown_counts:
                color_dim = list(breakdown_counts.keys())[0]
            elif country_count > 1:
                color_dim = "country"
            return StrategyResult(
                ChartStrategy.STACKED_AREA,
                f"User requested area; {year_count} years → stacked area chart",
                color_dim=color_dim,
            )

    # Heatmap: >8 countries, multi-year, no categorical breakdowns (dense matrix).
    # When a breakdown is present the data has a third categorical dimension that maps
    # better to SMALL_MULTIPLES faceting — each panel becomes one breakdown category.
    if country_count > HIGH_CARDINALITY_THRESHOLDS["beeswarm_threshold"] and year_count > 1:
        if n_breakdowns == 0:
            return StrategyResult(
                ChartStrategy.HEATMAP,
                f"{country_count} countries, {year_count} years → heatmap",
                color_dim="value",
            )

    # Explicit bar + 1 breakdown + few countries → grouped bar (xOffset) instead of small multiples.
    # GoG: if the user has explicitly requested a bar chart and there is exactly one breakdown
    # dimension with few countries (≤4), the correct mapping is BREAKDOWN_COMPARISON
    # (side-by-side bars within each country group) rather than SMALL_MULTIPLES (line facets).
    # This is the canonical fix for "unemployment by sex for 3 countries as a bar chart".
    if hint == "bar" and n_breakdowns == 1 and 0 < country_count <= 4:
        color_dim = list(breakdown_counts.keys())[0]
        return StrategyResult(
            ChartStrategy.BREAKDOWN_COMPARISON,
            f"User requested bar; 1 breakdown ({color_dim}), {country_count} countries → grouped bar",
            color_dim=color_dim,
        )

    # Small multiples: 2+ meaningful breakdowns, or breakdown + multiple countries.
    # With breakdown + 2+ countries, series count = country_count × breakdown_values.
    # Even 2 countries × 6 WGI metrics = 12 overlapping series on one chart — unreadable.
    # Facet by country so each panel shows one country's breakdown lines.
    if n_breakdowns >= 2 or (n_breakdowns >= 1 and country_count > 1):
        facet_dim = "country" if country_count > 1 else list(breakdown_counts.keys())[0]
        color_dim = list(breakdown_counts.keys())[0] if breakdown_counts else None
        return StrategyResult(
            ChartStrategy.SMALL_MULTIPLES,
            f"{n_breakdowns} breakdowns, {country_count} countries → small multiples (facet={facet_dim})",
            color_dim=color_dim,
            facet_dim=facet_dim,
        )

    # Breakdown + multi-year → line chart with breakdown as color dim.
    # Avoids a dense grouped bar chart (e.g. 6 breakdowns × 15 years = 90 bars).
    # Exception: custom breakdowns (comp_breakdown_1/2) with wildly different
    # value magnitudes (e.g. WGI estimate ~±2.5 vs percentile rank 0–100) cannot
    # share a Y-axis — the dominant series compresses the rest to flat lines.
    # Auto-route those to SMALL_MULTIPLES with facet=breakdown and independent Y-axes.
    if n_breakdowns == 1 and year_count > 1:
        color_dim = list(breakdown_counts.keys())[0]
        if (
            color_dim in _CUSTOM_BREAKDOWN_DIMS
            and _detect_scale_incompatibility(df, color_dim)
        ):
            return StrategyResult(
                ChartStrategy.SMALL_MULTIPLES,
                f"1 breakdown ({color_dim}), {year_count} years, scale-incompatible "
                f"→ faceted (independent Y-axes)",
                color_dim=None,
                facet_dim=color_dim,
                scale_incompatible=True,
            )
        return StrategyResult(
            ChartStrategy.TEMPORAL_SINGLE,
            f"1 breakdown ({color_dim}), {year_count} years → multi-series line chart",
            color_dim=color_dim,
        )

    # Breakdown comparison: 1 disaggregation, single year, ≤4 countries → grouped bar
    if n_breakdowns == 1 and country_count <= 4:
        color_dim = list(breakdown_counts.keys())[0]
        return StrategyResult(
            ChartStrategy.BREAKDOWN_COMPARISON,
            f"1 breakdown ({color_dim}), {breakdown_counts[color_dim]} values, single year → grouped bar",
            color_dim=color_dim,
        )

    # Explicit bar chart hint overrides high-cardinality distribution
    if hint == "bar" and year_count <= 1 and country_count > 0:
        return StrategyResult(
            ChartStrategy.CROSS_SECTIONAL,
            f"User requested bar; {country_count} countries, single year → horizontal bar",
            color_dim="country",
        )

    # Distribution: >8 countries, single year
    if (
        country_count > HIGH_CARDINALITY_THRESHOLDS["beeswarm_threshold"]
        and year_count <= 1
    ):
        return StrategyResult(
            ChartStrategy.DISTRIBUTION,
            f"{country_count} countries, single year → strip/beeswarm",
            color_dim="country",
        )

    # Cross-sectional: ≤8 countries, single year
    if year_count <= 1 and country_count > 0:
        return StrategyResult(
            ChartStrategy.CROSS_SECTIONAL,
            f"{country_count} countries, single year → horizontal bar",
            color_dim="country",
        )

    # Multi-year time series
    if year_count > 1:
        phrase = chart_type_phrase_for_reason(hint)
        return StrategyResult(
            ChartStrategy.TEMPORAL_SINGLE,
            f"Single indicator, {year_count} years, {country_count} countries → {phrase}",
            color_dim="country" if country_count > 0 else None,
        )

    return StrategyResult(
        ChartStrategy.FALLBACK_LINE,
        f"Default fallback → {chart_type_phrase_for_reason(hint)}",
        color_dim="country" if country_count > 0 else None,
    )


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
    """Returns D3 format string for tooltip quantitative fields."""
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
    return ",.3~s"


def _color_encoding(
    field: str,
    domain: list | None = None,
    mark_type: str = "point",
    n_items: int = 0,
    legend_title: str | None = None,
) -> dict:
    """Build a Vega-Lite color encoding channel.

    Legend title resolves in this priority order:
    1. Caller-supplied ``legend_title``
    2. Human-readable label from ``_TOOLTIP_SPECS`` (e.g. "Sub-Breakdown")
    3. Title-cased field name (e.g. "Comp Breakdown 2")
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
        legend: dict | None = {
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
    """Line chart: 1 indicator, multi-year, ≤8 countries."""
    rows = df.to_dict(orient="records")
    max_abs = float(df["value"].abs().max()) if "value" in df.columns else None
    tt_fmt = _compute_tooltip_format(max_abs, unit_measure)
    y_title = None if y_label == "Value" else y_label
    y_ax = {
        **_axis_style(),
        "title": y_title,
        "labelExpr": _value_label_expr(unit_measure),
    }
    encoding: dict = {
        "x": {"field": "year", "type": "temporal", "axis": _axis_style(temporal=True)},
        "y": {
            "field": "value",
            "type": "quantitative",
            "axis": y_ax,
            "scale": {"zero": False},
        },
        "tooltip": build_structured_tooltips(
            list(df.columns),
            "line",
            indicator_labels,
            value_format=tt_fmt,
            viz_data=df,
        ),
    }
    if result.color_dim:
        n_items = (
            df[result.color_dim].nunique() if result.color_dim in df.columns else 0
        )
        encoding["color"] = _color_encoding(
            result.color_dim, mark_type="line", n_items=n_items
        )

    # Option C: annotate chart subtitle with breakdown series names when color_dim is
    # a custom breakdown (comp_breakdown_1/2). Omits note for standard dims like country.
    annotated_title = _append_breakdown_note(title, df, result.color_dim)

    spec: dict = {
        "$schema": _vl_schema(),
        "title": annotated_title,
        "data": {"values": rows},
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

    sorted_df = df.sort_values("value", ascending=False)
    rows = sorted_df.to_dict(orient="records")
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
                viz_data=sorted_df,
            ),
        },
        "width": 500,
        "height": max(180, len(sorted_df) * 28),
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
    top_n = HIGH_CARDINALITY_THRESHOLDS["top_n_series"]
    sorted_df = df.sort_values("value", ascending=False).head(top_n)
    rows = sorted_df.to_dict(orient="records")
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
                list(sorted_df.columns),
                "tick",
                indicator_labels,
                value_format=tt_fmt,
                viz_data=sorted_df,
            ),
        },
        "width": 500,
        "height": max(250, len(sorted_df) * 22),
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
        x_enc = {
            "field": "year",
            "type": "temporal",
            "timeUnit": "year",
            "axis": {"title": None, "labelFontWeight": "bold", "format": "%Y", "labelAngle": -45},
        }
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
                viz_data=df,
            ),
        },
        "width": max(300, df[x_field].nunique() * 80),
        "height": 320,
    }
    return inject_wb_config(spec)


def _build_scale_split_vconcat(
    df: pd.DataFrame,
    title: str | dict,
    result: StrategyResult,
    indicator_labels: dict[str, str] | None = None,
    y_label: str = "Value",
    unit_measure: str | None = None,
) -> dict:
    """Vconcat layout for scale-incompatible custom breakdowns.

    Produces one full-width panel (680×140) per breakdown value, each with
    its own independent Y-axis and a WB categorical color. Panels share the
    X (year) axis via ``resolve.scale.x = 'shared'``.

    This replaces the default 180×120 facet layout when breakdown series
    differ by more than ~30× in magnitude (detected by
    :func:`_detect_scale_incompatibility`), preventing the visual
    compression of small-magnitude series on a shared axis.
    """
    facet_dim = result.facet_dim or "comp_breakdown_1"
    lab = indicator_labels or {}

    # Cap panels using the same threshold as regular small multiples.
    df, original_n = _cap_cardinality(
        df, facet_dim, HIGH_CARDINALITY_THRESHOLDS["small_multiples_max_facets"]
    )

    breakdown_vals = sorted(df[facet_dim].dropna().unique(), key=str)
    rows = df.to_dict(orient="records")
    label_expr = _value_label_expr(unit_measure)

    annotated_title = _append_trim_note(
        title, facet_dim,
        len(breakdown_vals),
        original_n,
    )

    charts: list[dict] = []
    for i, bd_val in enumerate(breakdown_vals):
        color = WB_CAT_COLORS[i % len(WB_CAT_COLORS)]
        bd_label = lab.get(str(bd_val), str(bd_val))

        bd_data = df[df[facet_dim] == bd_val]
        max_abs = (
            float(bd_data["value"].abs().max())
            if "value" in bd_data.columns and not bd_data.empty
            else None
        )
        tt_fmt = _compute_tooltip_format(max_abs, unit_measure)

        y_axis = {**_axis_style(), "title": None, "labelExpr": label_expr}
        x_axis = _axis_style(temporal=True)
        # Only show X-axis labels on the bottom-most panel.
        if i < len(breakdown_vals) - 1:
            x_axis["labels"] = False
            x_axis["title"] = None

        charts.append({
            "title": {
                "text": bd_label,
                "color": color,
                "fontSize": 12,
                "fontWeight": "bold",
                "anchor": "start",
                "offset": 4,
            },
            "width": 680,
            "height": 140,
            "transform": [{"filter": {"field": facet_dim, "equal": bd_val}}],
            "mark": {
                "type": "line",
                "strokeWidth": 3,
                "strokeCap": "round",
                "color": color,
                "point": _LINE_HOVER_POINT,
            },
            "encoding": {
                "x": {
                    "field": "year",
                    "type": "temporal",
                    "axis": x_axis,
                },
                "y": {
                    "field": "value",
                    "type": "quantitative",
                    "axis": y_axis,
                    "scale": {"zero": False},
                },
                "tooltip": [
                    {
                        "field": "year",
                        "type": "temporal",
                        "timeUnit": "year",
                        "title": "Year",
                        "format": "%Y",
                    },
                    {
                        "field": "value",
                        "type": "quantitative",
                        "title": bd_label,
                        "format": tt_fmt,
                    },
                ],
            },
        })

    spec: dict = {
        "$schema": _vl_schema(),
        "title": annotated_title,
        "data": {"values": rows},
        "vconcat": charts,
        "resolve": {"scale": {"x": "shared"}},
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
    # Scale-incompatible breakdowns: each series needs its own Y-axis to be readable.
    # Use a vconcat layout (680×140 per panel) instead of the shared-axis facet grid
    # (180×120 panels). See _build_scale_split_vconcat for details.
    if result.scale_incompatible:
        return _build_scale_split_vconcat(
            df, title, result, indicator_labels, y_label, unit_measure
        )

    facet_dim = result.facet_dim or "country"
    color_dim = result.color_dim

    # Shared cap utility — identical contract to cross_sectional bar rows.
    df, original_n = _cap_cardinality(
        df, facet_dim, HIGH_CARDINALITY_THRESHOLDS["small_multiples_max_facets"]
    )

    # Rebuild the context subtitle so it only names the countries actually shown,
    # not the full pre-cap list that build_chart_title_with_context built earlier.
    if original_n is not None and facet_dim == "country" and isinstance(title, dict):
        existing_sub = title.get("subtitle", "")
        # Normalise to list (handle legacy string subtitles from tests).
        if isinstance(existing_sub, str):
            existing_sub = [p.strip() for p in existing_sub.split(" · ") if p.strip()]
        # Rebuild element [0] (country + year range); keep [1:] (units, series notes).
        shown_countries = sorted(df["country"].unique().tolist(), key=str.casefold)
        year_lbl = _year_range_label(df["year"]) if "year" in df.columns else None
        new_geo = ", ".join(shown_countries)
        if year_lbl:
            new_geo = f"{new_geo}, {year_lbl}"
        title = {**title, "subtitle": [new_geo] + existing_sub[1:]}

    rows = df.to_dict(orient="records")
    max_abs = float(df["value"].abs().max()) if "value" in df.columns else None
    tt_fmt = _compute_tooltip_format(max_abs, unit_measure)

    n_facets = df[facet_dim].nunique() if facet_dim in df.columns else 1
    columns = min(2, n_facets)
    y_ax = {
        **_axis_style(),
        "title": None,
        "labelExpr": _value_label_expr(unit_measure),
    }

    inner: dict = {
        "mark": {"type": "line", "strokeWidth": 2},
        "encoding": {
            "x": {
                "field": "year",
                "type": "temporal",
                "axis": _axis_style(temporal=True),
            },
            "y": {
                "field": "value",
                "type": "quantitative",
                "axis": y_ax,
                "scale": {"zero": False},
            },
            "tooltip": build_structured_tooltips(
                list(df.columns),
                "line",
                indicator_labels,
                value_format=tt_fmt,
                viz_data=df,
            ),
        },
    }
    if color_dim and color_dim != facet_dim:
        inner["encoding"]["color"] = _color_encoding(color_dim, mark_type="line")

    # Option C: annotate with breakdown series names (heterogeneous → mixed-unit warning).
    annotated_title = _append_breakdown_note(title, df, color_dim)
    # Shared trim note — same utility as cross_sectional.
    annotated_title = _append_trim_note(annotated_title, facet_dim, n_facets, original_n)

    spec: dict = {
        "$schema": _vl_schema(),
        "title": annotated_title,
        "data": {"values": rows},
        "facet": {
            "field": facet_dim,
            "type": "nominal",
            "columns": columns,
            "header": {
                "labelFontWeight": "bold",
                "labelColor": WB_TEXT,
                "titleColor": WB_TEXT,
            },
        },
        "spec": {**inner, "width": 180, "height": 120},
    }
    return inject_wb_config(spec)


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

    y_enc = {
        "field": "country",
        "type": "nominal",
        "axis": {"title": None, "labelFontWeight": "bold"}
    }

    x_enc = {
        "field": "year",
        "type": "temporal",
        "timeUnit": "year",
        "axis": {"title": None, "format": "%Y"}
    }

    color_enc = {
        "field": "value",
        "type": "quantitative",
        "scale": {"scheme": scheme},
        "legend": {"title": y_label, "orient": "top", "direction": "horizontal", "gradientLength": 200}
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
            "tooltip": [
                {"field": "country", "type": "nominal", "title": "Country"},
                {"field": "year", "type": "temporal", "timeUnit": "year", "title": "Year", "format": "%Y"},
                {"field": "value", "type": "quantitative", "title": y_label, "format": tt_fmt},
            ]
        },
        "width": 600,
        "height": {"step": 15}
    }

    if result.facet_dim:
        spec["facet"] = {
            "field": result.facet_dim,
            "type": "nominal",
            "columns": 2,
            "header": {"labelFontWeight": "bold"}
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
            "x": {
                "field": "year",
                "type": "temporal",
                "timeUnit": "year",
                "axis": {"title": None, "format": "%Y"}
            },
            "y": {
                "field": "value",
                "type": "quantitative",
                "stack": "zero",
                "axis": {**_axis_style(), "title": None, "labelExpr": _value_label_expr(unit_measure)}
            },
            "color": _color_encoding(color_dim, domain=None, mark_type="area", legend_title=legend_title),
            "tooltip": [
                {"field": "year", "type": "temporal", "timeUnit": "year", "title": "Year", "format": "%Y"},
                {"field": color_dim, "type": "nominal", "title": legend_title},
                {"field": "value", "type": "quantitative", "title": y_label, "format": tt_fmt},
            ]
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
        x_axis = _axis_style(temporal=True)
        if i < len(ind_cols) - 1:
            x_axis["labels"] = False
            x_axis["title"] = None

        tooltip_cols = _multi_indicator_tooltip_columns(list(df.columns), col)
        layer_enc: dict = {
            "x": {
                "field": "year",
                "type": "temporal",
                "axis": x_axis,
            },
            "y": {
                "field": col,
                "type": "quantitative",
                "axis": y_axis,
                "scale": {"zero": False},
            },
            "color": {"value": color},
            "tooltip": build_structured_tooltips(
                tooltip_cols, "line", lab, value_format=tt_fmt, viz_data=df
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
        "x": {
            "field": x_col,
            "type": "temporal" if "year" in x_col else "ordinal",
            "axis": _axis_style(temporal=("year" in x_col)),
        },
        "y": {"field": y_col, "type": "quantitative", "axis": y_ax},
        "tooltip": build_structured_tooltips(
            list(df.columns),
            "line",
            indicator_labels,
            value_format=tt_fmt,
            viz_data=df,
        ),
    }
    if result.color_dim and result.color_dim in cols:
        n_items = df[result.color_dim].nunique()
        encoding["color"] = _color_encoding(
            result.color_dim, mark_type="line", n_items=n_items
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
        ChartStrategy.FALLBACK_LINE,
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
