"""Tests for COMP_BREAKDOWN_1/2 handling in the visualization pipeline.

Covers: _clean_single_df column discovery, color dim detection, strategy
selection breakdown counting, tooltip specs, and multi-indicator join keys.
Issue: https://github.com/worldbank/data360-mcp/issues/84
"""

from __future__ import annotations

import pandas as pd

from data360.visualization import _VIZ_DISAGG_DIMS, _clean_single_df
from data360.viz_config import (
    _TOOLTIP_PRIORITY,
    _TOOLTIP_SPECS,
    ChartStrategy,
    select_strategy,
)

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

    viz_data, relevant_cols, _ = _clean_single_df(raw, None, None, "A")

    assert "comp_breakdown_1" in viz_data.columns, (
        "comp_breakdown_1 should be retained when it has 6 distinct values"
    )
    assert "comp_breakdown_1" in relevant_cols


def test_clean_single_df_drops_comp_breakdown_1_when_trivial_z():
    """comp_breakdown_1 must be dropped when its only value is _Z (not applicable)."""
    raw = _make_wgi_df(["_Z"], [2022, 2023])  # single trivial value

    viz_data, relevant_cols, _ = _clean_single_df(raw, None, None, "A")

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
    viz_data, relevant_cols, _ = _clean_single_df(df, None, None, "A")

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
    viz_data, relevant_cols, _ = _clean_single_df(df, None, None, "A")

    assert "comp_breakdown_2" in viz_data.columns
    assert "comp_breakdown_2" in relevant_cols


def test_clean_single_df_relevant_fields_branch_keeps_comp_breakdown():
    """The explicit relevant_fields branch should also auto-add comp_breakdown_1."""
    raw = _make_wgi_df(["WGI_EST", "WGI_SC"], [2022, 2023])

    # Pass only core fields; comp_breakdown_1 should be auto-added
    viz_data, relevant_cols, _ = _clean_single_df(
        raw, ["time_period", "obs_value"], None, "A"
    )

    assert "comp_breakdown_1" in viz_data.columns, (
        "comp_breakdown_1 should be auto-added in relevant_fields branch"
    )


# ---------------------------------------------------------------------------
# Change 3: strategy selection counts comp_breakdown_1/2
# ---------------------------------------------------------------------------


def test_strategy_compatible_scales_multi_year_routes_to_temporal_single():
    """Verifies multi-year breakdown routing to TEMPORAL_SINGLE when scales are compatible."""
    WGI_BREAKDOWNS = ["WGI_EST", "WGI_SE", "WGI_SC", "WGI_SR", "WGI_SC_LB", "WGI_SC_UB"]
    df = _make_viz_df(WGI_BREAKDOWNS, list(range(2010, 2025)))

    result = select_strategy(df, n_indicators=1)

    # 6 breakdowns × 15 years → TEMPORAL_SINGLE with comp_breakdown_1 as color dim
    # (not BREAKDOWN_COMPARISON which produces 90 grouped bars — unreadable)
    assert result.strategy == ChartStrategy.TEMPORAL_SINGLE, (
        f"Expected TEMPORAL_SINGLE for multi-year breakdown data, got {result.strategy}. "
        "Multi-year breakdown should produce 6 colored lines, not 90 grouped bars."
    )
    assert result.color_dim == "comp_breakdown_1", (
        f"color_dim should be 'comp_breakdown_1', got '{result.color_dim}'"
    )


def test_strategy_single_year_breakdown_routes_to_breakdown_comparison():
    """Single-year breakdown still routes to BREAKDOWN_COMPARISON (grouped bar)."""
    WGI_BREAKDOWNS = ["WGI_EST", "WGI_SE", "WGI_SC"]
    # Only one year — grouped bar is correct here
    df = _make_viz_df(WGI_BREAKDOWNS, [2024])

    result = select_strategy(df, n_indicators=1)

    assert result.strategy == ChartStrategy.BREAKDOWN_COMPARISON, (
        f"Expected BREAKDOWN_COMPARISON for single-year breakdown, got {result.strategy}"
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
    """_TOOLTIP_SPECS must have an entry for comp_breakdown_1 with a neutral fallback label."""
    assert "comp_breakdown_1" in _TOOLTIP_SPECS
    assert _TOOLTIP_SPECS["comp_breakdown_1"]["type"] == "nominal"
    # Default is a generic fallback; the API-sourced label overrides this at render time.
    assert _TOOLTIP_SPECS["comp_breakdown_1"]["title"] == "Dimension 1"


def test_tooltip_specs_include_comp_breakdown_2():
    """_TOOLTIP_SPECS must have an entry for comp_breakdown_2 with a neutral fallback label."""
    assert "comp_breakdown_2" in _TOOLTIP_SPECS
    assert _TOOLTIP_SPECS["comp_breakdown_2"]["type"] == "nominal"
    # Default is a generic fallback; the API-sourced label overrides this at render time.
    assert _TOOLTIP_SPECS["comp_breakdown_2"]["title"] == "Dimension 2"


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
    from data360.viz_config import (
        ChartStrategy,
        StrategyResult,
        build_breakdown_comparison_spec,
    )

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
    """Legend title must use the label from _TOOLTIP_SPECS (or API override), not field.title()."""
    from data360.viz_config import (
        ChartStrategy,
        StrategyResult,
        build_breakdown_comparison_spec,
    )

    WGI_BREAKDOWNS = ["WGI_EST", "WGI_SC"]
    df = _make_viz_df(WGI_BREAKDOWNS, [2022, 2023])
    result = StrategyResult(
        strategy=ChartStrategy.BREAKDOWN_COMPARISON,
        reason="test",
        color_dim="comp_breakdown_1",
    )

    spec = build_breakdown_comparison_spec(df, "Test Title", result)

    legend_title = spec["encoding"]["color"]["legend"]["title"]
    # Without an API-sourced override, the default fallback from _TOOLTIP_SPECS is used.
    assert legend_title == "Dimension 1", (
        f"Legend title should be 'Dimension 1' from _TOOLTIP_SPECS fallback, got '{legend_title}'. "
        "The old code used color_dim.title() which produced 'Comp_Breakdown_1'."
    )
