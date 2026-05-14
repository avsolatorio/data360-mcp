"""Tests for COMP_BREAKDOWN_1/2 handling in the visualization pipeline.

Covers: _clean_single_df column discovery, color dim detection, strategy
selection breakdown counting, tooltip specs, and multi-indicator join keys.
Issue: https://github.com/worldbank/data360-mcp/issues/84
"""

from __future__ import annotations

import pandas as pd
import pytest

from data360.viz_config import (
    _TOOLTIP_PRIORITY,
    _TOOLTIP_SPECS,
    ChartStrategy,
    StrategyResult,
    select_strategy,
)
from data360.visualization import _VIZ_DISAGG_DIMS, _clean_single_df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wgi_df(breakdowns: list[str], years: list[int]) -> pd.DataFrame:
    """Build a synthetic WGI-style DataFrame with multiple COMP_BREAKDOWN_1 values."""
    rows = []
    for bd in breakdowns:
        for yr in years:
            rows.append(
                {
                    "time_period": str(yr),
                    "obs_value": 0.5,
                    "ref_area": "GEO",
                    "comp_breakdown_1": bd,
                    "sex": "_Z",
                    "age": "_Z",
                    "urbanisation": "_Z",
                }
            )
    return pd.DataFrame(rows)


def _make_viz_df(breakdowns: list[str], years: list[int]) -> pd.DataFrame:
    """Build a cleaned viz DataFrame (post-_clean_single_df rename) for strategy testing."""
    rows = []
    for bd in breakdowns:
        for yr in years:
            rows.append(
                {
                    "year": pd.Timestamp(f"{yr}-01-01"),
                    "value": 0.5,
                    "country": "Georgia",
                    "comp_breakdown_1": bd,
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Change 1: _clean_single_df column discovery
# ---------------------------------------------------------------------------


def test_clean_single_df_keeps_comp_breakdown_1_when_multi_value():
    """comp_breakdown_1 must be retained when it has multiple distinct non-trivial values."""
    WGI_BREAKDOWNS = ["WGI_EST", "WGI_SE", "WGI_SC", "WGI_SR", "WGI_SC_LB", "WGI_SC_UB"]
    raw = _make_wgi_df(WGI_BREAKDOWNS, [2022, 2023, 2024])

    viz_data, relevant_cols = _clean_single_df(raw, None, None, "A")

    assert "comp_breakdown_1" in viz_data.columns, (
        "comp_breakdown_1 should be retained when it has 6 distinct values"
    )
    assert "comp_breakdown_1" in relevant_cols


def test_clean_single_df_drops_comp_breakdown_1_when_trivial_z():
    """comp_breakdown_1 must be dropped when its only value is _Z (not applicable)."""
    raw = _make_wgi_df(["_Z"], [2022, 2023])  # single trivial value

    viz_data, relevant_cols = _clean_single_df(raw, None, None, "A")

    assert "comp_breakdown_1" not in viz_data.columns, (
        "comp_breakdown_1 should be dropped when value is only _Z"
    )


def test_clean_single_df_drops_comp_breakdown_1_when_trivial_t():
    """comp_breakdown_1 must be dropped when its only value is _T (aggregate total)."""
    df = pd.DataFrame(
        {
            "time_period": ["2023", "2024"],
            "obs_value": [1.0, 2.0],
            "ref_area": ["GEO", "GEO"],
            "comp_breakdown_1": ["_T", "_T"],
        }
    )
    viz_data, relevant_cols = _clean_single_df(df, None, None, "A")

    assert "comp_breakdown_1" not in viz_data.columns, (
        "comp_breakdown_1 should be dropped when value is only _T"
    )


def test_clean_single_df_keeps_comp_breakdown_2_when_multi_value():
    """comp_breakdown_2 follows the same inclusion logic as comp_breakdown_1."""
    df = pd.DataFrame(
        {
            "time_period": ["2023", "2023"],
            "obs_value": [1.0, 2.0],
            "ref_area": ["GEO", "GEO"],
            "comp_breakdown_2": ["PHASE1", "PHASE2"],
        }
    )
    viz_data, relevant_cols = _clean_single_df(df, None, None, "A")

    assert "comp_breakdown_2" in viz_data.columns
    assert "comp_breakdown_2" in relevant_cols


def test_clean_single_df_relevant_fields_branch_keeps_comp_breakdown():
    """The explicit relevant_fields branch should also auto-add comp_breakdown_1."""
    raw = _make_wgi_df(["WGI_EST", "WGI_SC"], [2022, 2023])

    # Pass only core fields; comp_breakdown_1 should be auto-added
    viz_data, relevant_cols = _clean_single_df(
        raw, ["time_period", "obs_value"], None, "A"
    )

    assert "comp_breakdown_1" in viz_data.columns, (
        "comp_breakdown_1 should be auto-added in relevant_fields branch"
    )


# ---------------------------------------------------------------------------
# Change 3: strategy selection counts comp_breakdown_1/2
# ---------------------------------------------------------------------------


def test_strategy_detects_comp_breakdown_1_as_breakdown():
    """select_strategy must count comp_breakdown_1 values in breakdown_counts."""
    WGI_BREAKDOWNS = ["WGI_EST", "WGI_SE", "WGI_SC", "WGI_SR", "WGI_SC_LB", "WGI_SC_UB"]
    df = _make_viz_df(WGI_BREAKDOWNS, list(range(2010, 2025)))

    result = select_strategy(df, n_indicators=1)

    # 6 breakdowns, 1 country, multi-year → must NOT fall through to TEMPORAL_SINGLE
    # (which would produce a tangled single-color line cloud)
    assert result.strategy != ChartStrategy.TEMPORAL_SINGLE, (
        "WGI-style indicators with 6 COMP_BREAKDOWN_1 values must not route to "
        "TEMPORAL_SINGLE — that produces an unreadable overlapping line cloud"
    )
    # Should route to BREAKDOWN_COMPARISON or SMALL_MULTIPLES
    assert result.strategy in (ChartStrategy.BREAKDOWN_COMPARISON, ChartStrategy.SMALL_MULTIPLES), (
        f"Expected BREAKDOWN_COMPARISON or SMALL_MULTIPLES, got {result.strategy}"
    )


def test_strategy_no_false_positive_for_trivial_comp_breakdown():
    """comp_breakdown_1 with a single trivial value must not inflate breakdown count."""
    df = pd.DataFrame(
        {
            "year": pd.to_datetime(["2022", "2023", "2024"]),
            "value": [1.0, 2.0, 3.0],
            "country": ["Kenya"] * 3,
            # Single trivial value — should NOT count as a breakdown
            "comp_breakdown_1": ["_Z"] * 3,
        }
    )

    result = select_strategy(df, n_indicators=1)

    # With no meaningful breakdown, multi-year single-country → TEMPORAL_SINGLE
    assert result.strategy == ChartStrategy.TEMPORAL_SINGLE


# ---------------------------------------------------------------------------
# Change 4: tooltip specs
# ---------------------------------------------------------------------------


def test_tooltip_specs_include_comp_breakdown_1():
    """_TOOLTIP_SPECS must have an entry for comp_breakdown_1."""
    assert "comp_breakdown_1" in _TOOLTIP_SPECS
    assert _TOOLTIP_SPECS["comp_breakdown_1"]["type"] == "nominal"
    assert _TOOLTIP_SPECS["comp_breakdown_1"]["title"] == "Breakdown"


def test_tooltip_specs_include_comp_breakdown_2():
    """_TOOLTIP_SPECS must have an entry for comp_breakdown_2."""
    assert "comp_breakdown_2" in _TOOLTIP_SPECS
    assert _TOOLTIP_SPECS["comp_breakdown_2"]["type"] == "nominal"
    assert _TOOLTIP_SPECS["comp_breakdown_2"]["title"] == "Sub-Breakdown"


def test_tooltip_priority_includes_comp_breakdown():
    """Both comp_breakdown_1 and comp_breakdown_2 must appear in _TOOLTIP_PRIORITY."""
    assert "comp_breakdown_1" in _TOOLTIP_PRIORITY
    assert "comp_breakdown_2" in _TOOLTIP_PRIORITY
    # They should appear after the standard dims, not before year/value
    cb1_idx = _TOOLTIP_PRIORITY.index("comp_breakdown_1")
    year_idx = _TOOLTIP_PRIORITY.index("year")
    assert cb1_idx > year_idx, "comp_breakdown_1 should appear after year in tooltip priority"


# ---------------------------------------------------------------------------
# Change 6: _VIZ_DISAGG_DIMS constant
# ---------------------------------------------------------------------------


def test_viz_disagg_dims_constant_is_complete():
    """_VIZ_DISAGG_DIMS must include both comp_breakdown dimensions."""
    assert "comp_breakdown_1" in _VIZ_DISAGG_DIMS
    assert "comp_breakdown_2" in _VIZ_DISAGG_DIMS
    # Must also preserve existing dims
    assert "sex" in _VIZ_DISAGG_DIMS
    assert "age" in _VIZ_DISAGG_DIMS
    assert "urbanisation" in _VIZ_DISAGG_DIMS


# ---------------------------------------------------------------------------
# Bugfix: build_breakdown_comparison_spec year axis and legend title
# ---------------------------------------------------------------------------


def test_breakdown_comparison_spec_uses_temporal_year_encoding():
    """Year X axis must use type=temporal so Vega-Lite renders years, not millisecond integers."""
    from data360.viz_config import ChartStrategy, StrategyResult, build_breakdown_comparison_spec

    WGI_BREAKDOWNS = ["WGI_EST", "WGI_SC", "WGI_SE"]
    df = _make_viz_df(WGI_BREAKDOWNS, [2020, 2021, 2022, 2023, 2024])
    result = StrategyResult(
        strategy=ChartStrategy.BREAKDOWN_COMPARISON,
        reason="test",
        color_dim="comp_breakdown_1",
    )

    spec = build_breakdown_comparison_spec(df, "Test Title", result)

    x_enc = spec["encoding"]["x"]
    assert x_enc["type"] == "temporal", (
        "X encoding must use type=temporal for year, not ordinal — "
        "ordinal causes Vega-Lite to render ISO timestamps as raw millisecond integers"
    )
    assert x_enc.get("timeUnit") == "year"
    assert x_enc.get("axis", {}).get("format") == "%Y"


def test_breakdown_comparison_spec_uses_friendly_legend_title():
    """Legend title must use the friendly label from _TOOLTIP_SPECS, not field.title()."""
    from data360.viz_config import ChartStrategy, StrategyResult, build_breakdown_comparison_spec

    WGI_BREAKDOWNS = ["WGI_EST", "WGI_SC"]
    df = _make_viz_df(WGI_BREAKDOWNS, [2022, 2023])
    result = StrategyResult(
        strategy=ChartStrategy.BREAKDOWN_COMPARISON,
        reason="test",
        color_dim="comp_breakdown_1",
    )

    spec = build_breakdown_comparison_spec(df, "Test Title", result)

    legend_title = spec["encoding"]["color"]["legend"]["title"]
    assert legend_title == "Breakdown", (
        f"Legend title should be 'Breakdown' from _TOOLTIP_SPECS, got '{legend_title}'. "
        "The old code used color_dim.title() which produced 'Comp_Breakdown_1'."
    )
