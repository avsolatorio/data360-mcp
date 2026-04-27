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

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

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
            "lineHeight": 1.2,
            "anchor": "start",
            "offset": 8,
            "subtitleFontSize": 12,
            "subtitleColor": WB_TEXT_SUBTLE,
            "subtitleFontWeight": "normal",
            "subtitlePadding": 4,
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

_TOOLTIP_SPECS: dict[str, dict] = {
    "year": {"title": "Year", "format": "%Y", "type": "temporal"},
    "value": {"title": "Value", "format": ",.2f", "type": "quantitative"},
    "country": {"title": "Country", "type": "nominal"},
    "sex": {"title": "Sex", "type": "nominal"},
    "age": {"title": "Age Group", "type": "nominal"},
    "urbanisation": {"title": "Urbanisation", "type": "nominal"},
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
]


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
    main_title: str,
    unit_subtitle: str | None,
    df: pd.DataFrame,
) -> str | dict:
    """Vega-Lite title: main text plus subtitle (geography + years · unit when present)."""
    ctx = format_chart_context_subtitle(df)
    subtitle_parts: list[str] = []
    if ctx:
        subtitle_parts.append(ctx)
    if unit_subtitle and str(unit_subtitle).strip():
        subtitle_parts.append(str(unit_subtitle).strip())
    if not subtitle_parts:
        return main_title
    return {"text": main_title, "subtitle": " · ".join(subtitle_parts)}


def build_structured_tooltips(
    columns: list[str],
    mark_type: str,
    indicator_labels: dict[str, str] | None = None,
    value_format: str = ",.2f",
) -> list[dict]:
    """Build typed, labelled tooltip list for a Vega-Lite encoding.

    indicator_labels: optional {col_name: human_label} for indicator value columns
    in multi-indicator charts (e.g. {"gdp_per_capita": "GDP per capita (USD)"}).
    value_format: D3 format string for quantitative value fields.
    """
    ordered = [c for c in _TOOLTIP_PRIORITY if c in columns]
    ordered += [c for c in columns if c not in _TOOLTIP_PRIORITY]

    tooltips = []
    for col in ordered:
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
) -> dict:
    tips = build_structured_tooltips(columns, mark_type, indicator_labels)
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

    breakdown_counts = {
        k: v
        for k, v in [
            ("sex", sex_count),
            ("age", age_count),
            ("urbanisation", urban_count),
        ]
        if v > 1
    }
    n_breakdowns = len(breakdown_counts)
    ind_cols = indicator_cols or []

    # ── Explicit scatter hint ──
    if hint == "point" and n_indicators == 2 and len(ind_cols) == 2:
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

    # ── Multi-indicator: 2-3 indicators ──
    if n_indicators == 2 and len(ind_cols) == 2:
        if year_count <= 1 and country_count > 1:
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
                ChartStrategy.CORRELATION_TEMPORAL,
                f"2 indicators, {country_count} countries, {year_count} years → connected scatter",
                indicator_cols=ind_cols,
                color_dim="country",
                x_dim=ind_cols[0],
                y_dim=ind_cols[1],
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

    # Small multiples: 2+ meaningful breakdowns, or breakdown + many countries
    if n_breakdowns >= 2 or (n_breakdowns >= 1 and country_count > 4):
        facet_dim = "country" if country_count > 1 else list(breakdown_counts.keys())[0]
        color_dim = list(breakdown_counts.keys())[0] if breakdown_counts else None
        return StrategyResult(
            ChartStrategy.SMALL_MULTIPLES,
            f"{n_breakdowns} breakdowns, {country_count} countries → small multiples",
            color_dim=color_dim,
            facet_dim=facet_dim,
        )

    # Breakdown comparison: 1 disaggregation, 2-4 values, ≤4 countries
    if n_breakdowns == 1 and country_count <= 4:
        color_dim = list(breakdown_counts.keys())[0]
        return StrategyResult(
            ChartStrategy.BREAKDOWN_COMPARISON,
            f"1 breakdown ({color_dim}), {breakdown_counts[color_dim]} values → grouped bar",
            color_dim=color_dim,
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
        return StrategyResult(
            ChartStrategy.TEMPORAL_SINGLE,
            f"Single indicator, {year_count} years, {country_count} countries → line chart",
            color_dim="country" if country_count > 0 else None,
        )

    return StrategyResult(
        ChartStrategy.FALLBACK_LINE,
        "Default fallback → line chart",
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
) -> dict:
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
            "labelLimit": 100,
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
            list(df.columns), "line", indicator_labels, value_format=tt_fmt
        ),
    }
    if result.color_dim:
        n_items = (
            df[result.color_dim].nunique() if result.color_dim in df.columns else 0
        )
        encoding["color"] = _color_encoding(
            result.color_dim, mark_type="line", n_items=n_items
        )

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": rows},
        "mark": {
            "type": "line",
            "strokeWidth": 3,
            "strokeCap": "round",
            "point": False,
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
    """Horizontal bar: 1 indicator, single year, ≤8 countries."""
    sorted_df = df.sort_values("value", ascending=False)
    rows = sorted_df.to_dict(orient="records")
    max_abs = float(df["value"].abs().max()) if "value" in df.columns else None
    tt_fmt = _compute_tooltip_format(max_abs, unit_measure)

    color_enc = (
        _color_encoding(result.color_dim)
        if result.color_dim
        else {"value": WB_CAT_COLORS[0]}
    )
    x_ax = {
        **_axis_style(),
        "title": None,
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
                list(df.columns), "bar", indicator_labels, value_format=tt_fmt
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
                list(sorted_df.columns), "tick", indicator_labels, value_format=tt_fmt
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
    x_type = "nominal" if x_field == "country" else "ordinal"
    y_ax = {
        **_axis_style(),
        "title": None,
        "labelExpr": _value_label_expr(unit_measure),
    }

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": rows},
        "mark": {"type": "bar"},
        "encoding": {
            "x": {
                "field": x_field,
                "type": x_type,
                "axis": {"title": None, "labelFontWeight": "bold"},
            },
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
                    "title": color_dim.title(),
                    "labelLimit": 100,
                    "columns": 3,
                },
            },
            "tooltip": build_structured_tooltips(
                list(df.columns), "bar", indicator_labels, value_format=tt_fmt
            ),
        },
        "width": max(300, df[x_field].nunique() * 80),
        "height": 320,
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
    """Faceted small multiples: 1 indicator, 2+ breakdowns or breakdown+many countries."""
    rows = df.to_dict(orient="records")
    facet_dim = result.facet_dim or "country"
    color_dim = result.color_dim
    max_abs = float(df["value"].abs().max()) if "value" in df.columns else None
    tt_fmt = _compute_tooltip_format(max_abs, unit_measure)

    n_facets = df[facet_dim].nunique() if facet_dim in df.columns else 1
    columns = min(3, n_facets)
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
                list(df.columns), "line", indicator_labels, value_format=tt_fmt
            ),
        },
    }
    if color_dim and color_dim != facet_dim:
        inner["encoding"]["color"] = _color_encoding(color_dim, mark_type="line")

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
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
        "spec": {**inner, "width": 220, "height": 160},
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

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": rows},
        "mark": {
            "type": "circle",
            "opacity": 0.85,
            "stroke": WB_WHITE,
            "strokeWidth": 1,
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
            "color": _color_encoding(result.color_dim or "country"),
            "tooltip": build_structured_tooltips(list(df.columns), "point", lab),
        },
        "width": 550,
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
        "tooltip": build_structured_tooltips(list(df.columns), "line", lab),
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
    """Layered multi-axis line chart: 2-4 indicators, multi-year when applicable.

    Uses Vega-Lite layer + independent y-scale resolution.
    Each indicator gets its own y-axis; left + right for the first two, staggered
    offsets on the right for additional series (Vega-Lite only lays out two
    independent Y-axes cleanly without offset).
    """
    ind_cols = result.indicator_cols
    if not ind_cols:
        raise ValueError("temporal_multi_indicator spec requires indicator_cols")

    lab = indicator_labels or {}
    rows = df.to_dict(orient="records")

    label_expr = _value_label_expr(unit_measure)
    layers = []
    for i, col in enumerate(ind_cols):
        color = WB_CAT_COLORS[i % len(WB_CAT_COLORS)]
        col_label = lab.get(col, col.replace("_", " ").title())
        max_abs = float(df[col].abs().max()) if col in df.columns else None
        tt_fmt = _compute_tooltip_format(max_abs, unit_measure)
        y_axis = {
            **_axis_style(col_label),
            "titleColor": color,
            "labelExpr": label_expr,
        }
        if i == 0:
            y_axis["orient"] = "left"
        elif i == 1:
            y_axis["orient"] = "right"
        else:
            y_axis["orient"] = "right"
            y_axis["offset"] = 50 * (i - 1)
        layer_enc: dict = {
            "x": {
                "field": "year",
                "type": "temporal",
                "axis": _axis_style(temporal=True),
            },
            "y": {
                "field": col,
                "type": "quantitative",
                "axis": y_axis,
                "scale": {"zero": False},
            },
            "color": {"value": color},
            "tooltip": build_structured_tooltips(
                list(df.columns), "line", lab, value_format=tt_fmt
            ),
        }
        layers.append(
            {
                "mark": {
                    "type": "line",
                    "strokeWidth": 3,
                    "strokeCap": "round",
                    "color": color,
                },
                "encoding": layer_enc,
            }
        )

    spec: dict = {
        "$schema": _vl_schema(),
        "title": title,
        "data": {"values": rows},
        "layer": layers,
        "resolve": {"scale": {"y": "independent"}},
        "width": 680 if len(ind_cols) > 2 else 620,
        "height": 380,
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
            list(df.columns), "line", indicator_labels, value_format=tt_fmt
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
        "mark": {"type": "line", "strokeWidth": 3, "strokeCap": "round"},
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
    "line_max_series": 8,
    "beeswarm_threshold": 8,
    "facet_threshold": 4,
    "top_n_series": 12,
}


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


class OrdinalToTemporalRule(PostProcessingRule):
    def __init__(self):
        super().__init__(
            "ordinal_to_temporal",
            ["line", "area", "point", "tick"],
            "Fix ordinal→temporal for time fields",
        )

    def should_apply(self, mark_type, x_enc, dataset):
        if mark_type not in self.applies_to_mark_types:
            return False
        if x_enc.get("type") != "ordinal":
            return False
        x_field = x_enc.get("field")
        if x_field not in ["year", "time_period"]:
            return False
        if dataset and x_field in dataset[0]:
            return isinstance(dataset[0][x_field], str) and "T" in dataset[0][x_field]
        return False

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
            ["line", "area", "point"],
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
    TemporalAxisCleanupRule(),
    ValueAxisLabelFormatRule(),
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
