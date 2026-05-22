"""Tests for scale-incompatibility auto-detection in the visualization pipeline.

Covers:
  - _detect_scale_incompatibility() pure function
  - select_strategy() routing gate (WGI-style breakdowns → SMALL_MULTIPLES)
  - _build_scale_split_vconcat() spec output
  - build_small_multiples_spec() delegating when scale_incompatible=True
"""

import pandas as pd

from data360.viz_config import (
    HIGH_CARDINALITY_THRESHOLDS,
    ChartStrategy,
    StrategyResult,
    _build_scale_split_vconcat,
    _detect_scale_incompatibility,
    _group_breakdowns_by_scale,
    build_small_multiples_spec,
    dispatch_spec,
    select_strategy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

YEARS_MULTI = list(range(2010, 2025))


def _make_df(
    series: dict[str, float],
    years: list[int] = YEARS_MULTI,
    country: str = "Kenya",
    dim: str = "comp_breakdown_1",
) -> pd.DataFrame:
    """Build a synthetic DataFrame with one row per (dim_val, year)."""
    rows = []
    for dim_val, max_val in series.items():
        for yr in years:
            rows.append(
                {
                    "year": pd.Timestamp(str(yr)),
                    "value": max_val * (0.8 + 0.2 * (yr - years[0]) / max(len(years) - 1, 1)),
                    "country": country,
                    dim: dim_val,
                }
            )
    return pd.DataFrame(rows)


# WGI-style: estimate ~±0.6, score ~65, std_error ~0.2, rank ~60
WGI_SERIES = {
    "WGI_EST": 0.6,   # mag ≈ -0.22
    "WGI_SC":  65.0,  # mag ≈  1.81
    "WGI_SR":  9.0,   # mag ≈  0.95
    "WGI_SE":  0.2,   # mag ≈ -0.70
}

# IPC-style: all person counts in same order of magnitude (~thousands)
IPC_SERIES = {
    "IPC_IPC_PHASE1": 5000.0,  # mag ≈ 3.70
    "IPC_IPC_PHASE2": 3000.0,  # mag ≈ 3.48
    "IPC_IPC_PHASE3": 1000.0,  # mag ≈ 3.00
}

# Same-magnitude custom breakdown — should not fire
SAME_MAG_SERIES = {
    "BD_A": 50.0,   # mag ≈ 1.70
    "BD_B": 30.0,   # mag ≈ 1.48
    "BD_C": 80.0,   # mag ≈ 1.90
}


# ============================================================================
# 1. _detect_scale_incompatibility — pure function
# ============================================================================


class TestDetectScaleIncompatibility:
    """Unit tests for the log10-magnitude spread detector."""

    def test_wgi_style_is_incompatible(self):
        """WGI breakdowns span ~2.5 orders of magnitude → True."""
        df = _make_df(WGI_SERIES)
        assert _detect_scale_incompatibility(df, "comp_breakdown_1") is True, (
            "WGI EST (~0.6) vs SC (~65) should be detected as scale-incompatible."
        )

    def test_ipc_phases_are_compatible(self):
        """IPC phases are all person counts, similar magnitude → False."""
        df = _make_df(IPC_SERIES)
        assert _detect_scale_incompatibility(df, "comp_breakdown_1") is False, (
            "IPC phases share the same order of magnitude — compatible."
        )

    def test_same_magnitude_custom_breakdown_is_compatible(self):
        """Three series all in the 30–80 range → False."""
        df = _make_df(SAME_MAG_SERIES)
        assert _detect_scale_incompatibility(df, "comp_breakdown_1") is False

    def test_single_breakdown_value_is_false(self):
        """Fewer than 2 unique breakdown values — nothing to compare."""
        df = _make_df({"WGI_EST": 0.6})
        assert _detect_scale_incompatibility(df, "comp_breakdown_1") is False

    def test_missing_breakdown_col_is_false(self):
        df = _make_df(WGI_SERIES).drop(columns=["comp_breakdown_1"])
        assert _detect_scale_incompatibility(df, "comp_breakdown_1") is False

    def test_missing_value_col_is_false(self):
        df = _make_df(WGI_SERIES).drop(columns=["value"])
        assert _detect_scale_incompatibility(df, "comp_breakdown_1") is False

    def test_all_zero_values_returns_false(self):
        """Series where all values are zero → magnitudes are all 0 → spread = 0."""
        rows = [
            {"year": pd.Timestamp("2020"), "value": 0.0, "country": "Kenya", "comp_breakdown_1": v}
            for v in ["BD_A", "BD_B"]
        ]
        df = pd.DataFrame(rows)
        assert _detect_scale_incompatibility(df, "comp_breakdown_1") is False

    def test_exactly_at_threshold_is_incompatible(self):
        """A spread of exactly 1.5 should return True (>= threshold)."""
        # mag_A = log10(1) = 0.0, mag_B = log10(10^1.5) = 1.5 → spread = 1.5
        val_b = 10 ** 1.5
        rows = []
        for yr in [2020, 2021]:
            rows.append({"year": pd.Timestamp(str(yr)), "value": 1.0, "country": "K", "comp_breakdown_1": "A"})
            rows.append({"year": pd.Timestamp(str(yr)), "value": val_b, "country": "K", "comp_breakdown_1": "B"})
        df = pd.DataFrame(rows)
        assert _detect_scale_incompatibility(df, "comp_breakdown_1") is True

    def test_just_below_threshold_is_compatible(self):
        """A spread of 1.49 (just below 1.5) should return False."""
        val_b = 10 ** 1.49
        rows = []
        for yr in [2020, 2021]:
            rows.append({"year": pd.Timestamp(str(yr)), "value": 1.0, "country": "K", "comp_breakdown_1": "A"})
            rows.append({"year": pd.Timestamp(str(yr)), "value": val_b, "country": "K", "comp_breakdown_1": "B"})
        df = pd.DataFrame(rows)
        assert _detect_scale_incompatibility(df, "comp_breakdown_1") is False

    def test_custom_threshold_respected(self):
        """A tighter threshold (0.5) catches the IPC-style data."""
        df = _make_df(IPC_SERIES)
        # IPC spread ≈ 0.7 — below default 1.5 but above 0.5
        assert _detect_scale_incompatibility(df, "comp_breakdown_1", magnitude_threshold=0.5) is True

    def test_standard_dim_not_checked_by_caller(self):
        """Standard dims (sex) are guarded by the caller; the function itself
        doesn't refuse them, but the caller in select_strategy uses
        _CUSTOM_BREAKDOWN_DIMS to gate the call."""
        rows = [
            {"year": pd.Timestamp("2020"), "value": 50.0, "country": "K", "sex": "M"},
            {"year": pd.Timestamp("2020"), "value": 0.5, "country": "K", "sex": "F"},
        ]
        df = pd.DataFrame(rows)
        # sex has a large spread here, but select_strategy won't call _detect for sex
        result = select_strategy(df, n_indicators=1)
        # Should NOT route to scale-incompatible SMALL_MULTIPLES via standard dim
        assert result.scale_incompatible is False


# ============================================================================
# 2. select_strategy routing
# ============================================================================


class TestSelectStrategyScaleIncompatibleRouting:
    """Verify the routing gate in select_strategy."""

    def test_wgi_single_country_routes_to_small_multiples(self):
        """Single country × WGI breakdowns → SMALL_MULTIPLES, not TEMPORAL_SINGLE."""
        df = _make_df(WGI_SERIES)
        result = select_strategy(df, n_indicators=1)
        assert result.strategy == ChartStrategy.SMALL_MULTIPLES, (
            f"Expected SMALL_MULTIPLES for WGI scale-incompatible data, got {result.strategy}."
        )

    def test_wgi_single_country_sets_scale_incompatible_flag(self):
        df = _make_df(WGI_SERIES)
        result = select_strategy(df, n_indicators=1)
        assert result.scale_incompatible is True, (
            "scale_incompatible must be True so build_small_multiples_spec delegates to vconcat."
        )

    def test_wgi_single_country_facet_dim_is_breakdown(self):
        df = _make_df(WGI_SERIES)
        result = select_strategy(df, n_indicators=1)
        assert result.facet_dim == "comp_breakdown_1", (
            f"facet_dim should be 'comp_breakdown_1', got {result.facet_dim!r}."
        )

    def test_wgi_single_country_color_dim_is_none(self):
        """Each panel has a single series — no color legend needed."""
        df = _make_df(WGI_SERIES)
        result = select_strategy(df, n_indicators=1)
        assert result.color_dim is None, (
            f"color_dim should be None for scale-split panels, got {result.color_dim!r}."
        )

    def test_ipc_single_country_stays_temporal_single(self):
        """IPC phases are scale-compatible → stays TEMPORAL_SINGLE, no flag."""
        df = _make_df(IPC_SERIES)
        result = select_strategy(df, n_indicators=1)
        assert result.strategy == ChartStrategy.TEMPORAL_SINGLE, (
            f"IPC phases must NOT trigger scale-split, got {result.strategy}."
        )
        assert result.scale_incompatible is False

    def test_wgi_multi_country_routes_to_scale_split(self):
        """WGI + 2 countries + scale-incompatible breakdown → vconcat with facet=breakdown,
        color=country. Previously routed to SMALL_MULTIPLES facet=country (bug: incompatible
        series shared one Y-axis, governance estimate ±2.5 crushed against 0-100 scale)."""
        df_k = _make_df(WGI_SERIES, country="Kenya")
        df_g = _make_df(WGI_SERIES, country="Ghana")
        df = pd.concat([df_k, df_g], ignore_index=True)
        result = select_strategy(df, n_indicators=1)
        assert result.strategy == ChartStrategy.SMALL_MULTIPLES
        assert result.scale_incompatible is True, (
            "Multi-country WGI with scale-incompatible breakdown must set scale_incompatible."
        )
        assert result.facet_dim == "comp_breakdown_1", (
            "Facet must be the breakdown dim so each panel has a compatible Y-axis."
        )
        assert result.color_dim == "country", (
            "Color must be country so Georgia vs UK are distinguishable lines within each panel."
        )

    def test_same_magnitude_custom_breakdown_stays_temporal_single(self):
        df = _make_df(SAME_MAG_SERIES)
        result = select_strategy(df, n_indicators=1)
        assert result.strategy == ChartStrategy.TEMPORAL_SINGLE
        assert result.scale_incompatible is False

    def test_standard_breakdown_dim_never_triggers_scale_split(self):
        """Only _CUSTOM_BREAKDOWN_DIMS (comp_breakdown_1/2) should fire the gate.
        Standard dims like 'sex' must never trigger scale_incompatible routing,
        even if their values happen to have a large spread."""
        rows = []
        for yr in YEARS_MULTI:
            rows.append({"year": pd.Timestamp(str(yr)), "value": 80.0, "country": "Kenya", "sex": "M"})
            rows.append({"year": pd.Timestamp(str(yr)), "value": 0.1, "country": "Kenya", "sex": "F"})
        df = pd.DataFrame(rows)
        result = select_strategy(df, n_indicators=1)
        assert result.scale_incompatible is False
        assert result.strategy != ChartStrategy.SMALL_MULTIPLES or result.facet_dim != "sex"

    def test_comp_breakdown_2_also_triggers_gate(self):
        """comp_breakdown_2 is also in _CUSTOM_BREAKDOWN_DIMS and should fire."""
        df = _make_df(WGI_SERIES, dim="comp_breakdown_2")
        result = select_strategy(df, n_indicators=1)
        assert result.scale_incompatible is True
        assert result.facet_dim == "comp_breakdown_2"


# ============================================================================
# 3. _build_scale_split_vconcat spec output
# ============================================================================


class TestBuildScaleSplitVconcat:
    """Validate the vconcat spec structure produced by the helper."""

    def _make_result(self, facet_dim: str = "comp_breakdown_1") -> StrategyResult:
        return StrategyResult(
            ChartStrategy.SMALL_MULTIPLES,
            "scale-incompatible test",
            facet_dim=facet_dim,
            scale_incompatible=True,
        )

    def test_top_level_key_is_vconcat(self):
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        assert "vconcat" in spec, "Scale-split spec must use top-level 'vconcat' key."
        assert "facet" not in spec, "Scale-split spec must NOT use 'facet' key."

    def test_one_panel_per_group(self):
        """vconcat must have one panel per scale-compatible group, not per breakdown value.

        WGI_SERIES has 4 breakdown values but at threshold 0.75 the grouping
        algorithm should merge at least some of them — so the number of panels
        must be ≤ the number of breakdown values.
        """
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        n_groups = len(_group_breakdowns_by_scale(df, "comp_breakdown_1"))
        assert len(spec["vconcat"]) == n_groups, (
            f"Expected {n_groups} panels (one per group), got {len(spec['vconcat'])}."
        )
        assert len(spec["vconcat"]) <= len(WGI_SERIES), (
            "Panel count must not exceed the number of breakdown values."
        )

    def test_each_panel_width_is_680(self):
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        for panel in spec["vconcat"]:
            assert panel.get("width") == 680, f"Panel width should be 680, got {panel.get('width')}."

    def test_singleton_panel_height_is_140_multi_member_is_180(self):
        """Single-member group panels are 140px; multi-member panels are 180px."""
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        groups = _group_breakdowns_by_scale(df, "comp_breakdown_1")
        for panel, group in zip(spec["vconcat"], groups):
            expected_h = 140 if len(group) == 1 else 180
            assert panel.get("height") == expected_h, (
                f"Group {group!r} (size {len(group)}) → expected height {expected_h}, "
                f"got {panel.get('height')}."
            )

    def test_each_panel_mark_is_line(self):
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        for panel in spec["vconcat"]:
            mark = panel.get("mark", {})
            mark_type = mark.get("type") if isinstance(mark, dict) else mark
            assert mark_type == "line", f"Panel mark should be 'line', got {mark_type!r}."

    def test_each_panel_has_filter_transform(self):
        """Each panel must filter to its own breakdown value."""
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        for panel in spec["vconcat"]:
            transforms = panel.get("transform", [])
            assert len(transforms) >= 1, "Each panel must have a filter transform."
            assert "filter" in transforms[0], "First transform must be a 'filter'."

    def test_x_axis_shared_via_resolve(self):
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        resolve = spec.get("resolve", {})
        assert resolve.get("scale", {}).get("x") == "shared", (
            "vconcat must share the X (year) axis via resolve.scale.x='shared'."
        )

    def test_only_bottom_panel_has_x_labels(self):
        """All panels except the last should have x.axis.labels=False."""
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        panels = spec["vconcat"]
        for panel in panels[:-1]:
            x_axis = panel.get("encoding", {}).get("x", {}).get("axis", {})
            assert x_axis.get("labels") is False, (
                "Non-bottom panels should have x axis labels suppressed."
            )
        # Bottom panel should have labels (key absent or True)
        bottom_x_axis = panels[-1].get("encoding", {}).get("x", {}).get("axis", {})
        assert bottom_x_axis.get("labels") is not False, (
            "Bottom panel should display x-axis labels."
        )

    def test_singleton_panels_use_mark_color_multi_member_panels_use_color_encoding(self):
        """Single-member panels have mark.color; multi-member panels have encoding.color."""
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        groups = _group_breakdowns_by_scale(df, "comp_breakdown_1")
        for panel, group in zip(spec["vconcat"], groups):
            if len(group) == 1:
                # Singleton: fixed mark color, no encoding.color
                mark = panel.get("mark", {})
                assert mark.get("color"), (
                    f"Singleton panel for {group!r} must have mark.color set."
                )
                assert "color" not in panel.get("encoding", {}), (
                    f"Singleton panel for {group!r} must not have encoding.color."
                )
            else:
                # Multi-member: color encoding present, no fixed mark color
                enc_color = panel.get("encoding", {}).get("color")
                assert enc_color is not None, (
                    f"Multi-member panel for {group!r} must have encoding.color."
                )
                assert enc_color.get("field") == "comp_breakdown_1", (
                    f"encoding.color.field must be 'comp_breakdown_1', got {enc_color.get('field')!r}."
                )
                mark = panel.get("mark", {})
                assert "color" not in mark, (
                    f"Multi-member panel must not have a fixed mark.color."
                )

    def test_caps_panels_at_small_multiples_max_facets(self):
        """More than max_facets breakdown values → capped."""
        cap = HIGH_CARDINALITY_THRESHOLDS["small_multiples_max_facets"]
        big_series = {f"BD_{i:02d}": float(10 ** (i % 3)) for i in range(cap + 5)}
        df = _make_df(big_series)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        assert len(spec["vconcat"]) <= cap, (
            f"Scale-split must cap at {cap} panels, got {len(spec['vconcat'])}."
        )

    def test_panel_titles_use_series_labels_mapping(self):
        """When indicator_labels is provided, panel titles should use human labels.

        For singleton groups the title is the label directly.
        For multi-member groups the title is a joined string of member labels.
        All provided labels must appear somewhere in the rendered panel titles.
        """
        df = _make_df({"WGI_EST": 0.6, "WGI_SC": 65.0})
        result = self._make_result()
        labels = {"WGI_EST": "Estimate", "WGI_SC": "Score"}
        spec = _build_scale_split_vconcat(df, "Test", result, indicator_labels=labels)
        # Collect all text from panel titles (string or list)
        all_title_text = " | ".join(
            p.get("title", {}).get("text", "") or ""
            for p in spec["vconcat"]
        )
        assert "Estimate" in all_title_text, (
            "'Estimate' label must appear in panel title(s)."
        )
        assert "Score" in all_title_text, (
            "'Score' label must appear in panel title(s)."
        )

    def test_has_wb_config(self):
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        assert "config" in spec, "Scale-split spec must have WB config injected."

    def test_each_panel_x_is_temporal(self):
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        for panel in spec["vconcat"]:
            x = panel.get("encoding", {}).get("x", {})
            assert x.get("type") == "temporal", (
                f"Panel x-axis must be type='temporal', got {x.get('type')!r}."
            )

    def test_each_panel_y_is_quantitative(self):
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        for panel in spec["vconcat"]:
            y = panel.get("encoding", {}).get("y", {})
            assert y.get("type") == "quantitative", (
                f"Panel y-axis must be type='quantitative', got {y.get('type')!r}."
            )

    def test_each_panel_has_tooltip(self):
        df = _make_df(WGI_SERIES)
        result = self._make_result()
        spec = _build_scale_split_vconcat(df, "Test", result)
        for panel in spec["vconcat"]:
            tooltip = panel.get("encoding", {}).get("tooltip")
            assert tooltip, "Each panel must have tooltip encoding."


# ============================================================================
# 4. build_small_multiples_spec delegation
# ============================================================================


class TestBuildSmallMultiplesSpecDelegation:
    """build_small_multiples_spec must delegate to vconcat when scale_incompatible=True."""

    def _make_scale_incompatible_result(self) -> StrategyResult:
        return StrategyResult(
            ChartStrategy.SMALL_MULTIPLES,
            "test scale-incompatible",
            facet_dim="comp_breakdown_1",
            scale_incompatible=True,
        )

    def _make_normal_result(self) -> StrategyResult:
        return StrategyResult(
            ChartStrategy.SMALL_MULTIPLES,
            "test normal",
            facet_dim="country",
            color_dim="comp_breakdown_1",
            scale_incompatible=False,
        )

    def test_scale_incompatible_produces_vconcat(self):
        df = _make_df(WGI_SERIES)
        result = self._make_scale_incompatible_result()
        spec = build_small_multiples_spec(df, "Test", result)
        assert "vconcat" in spec, "scale_incompatible=True must produce a vconcat spec."
        assert "facet" not in spec

    def test_scale_compatible_produces_vconcat(self):
        """Normal (scale_incompatible=False) still produces the vconcat layout."""
        rows = []
        for country in ["Kenya", "Ghana", "Nigeria"]:
            for bd in ["BD_A", "BD_B"]:
                for yr in [2020, 2021, 2022]:
                    rows.append({
                        "year": pd.Timestamp(str(yr)), "value": 10.0,
                        "country": country, "comp_breakdown_1": bd,
                    })
        df = pd.DataFrame(rows)
        result = self._make_normal_result()
        spec = build_small_multiples_spec(df, "Test", result)
        assert "vconcat" in spec, "scale_incompatible=False must produce vconcat layout."


# ============================================================================
# 5. End-to-end: dispatch_spec routes correctly
# ============================================================================


class TestDispatchSpecScaleSplit:
    """dispatch_spec must forward scale_incompatible results to build_small_multiples_spec
    which then delegates to _build_scale_split_vconcat."""

    def test_dispatch_produces_vconcat_for_scale_incompatible_strategy(self):
        df = _make_df(WGI_SERIES)
        result = select_strategy(df, n_indicators=1)
        assert result.scale_incompatible, "Precondition: WGI data must be scale-incompatible."
        spec = dispatch_spec(result.strategy, df, "Test", result)
        assert "vconcat" in spec, (
            "dispatch_spec with scale_incompatible=True must produce a vconcat spec."
        )


# ============================================================================
# 6. _group_breakdowns_by_scale — generalized grouping algorithm
# ============================================================================


class TestGroupBreakdownsByScale:
    """Unit tests for the data-driven scale-grouping algorithm.

    All tests use synthetic data; no WGI-specific codes are assumed to
    exist in the implementation.
    """

    def test_single_series_returns_one_group(self):
        """One breakdown value → one group containing that value."""
        df = _make_df({"BD_A": 5.0})
        groups = _group_breakdowns_by_scale(df, "comp_breakdown_1")
        assert groups == [["BD_A"]]

    def test_all_compatible_returns_one_group(self):
        """Series within threshold → merged into one group."""
        # All within 0.75 log10 of each other
        df = _make_df({"BD_A": 10.0, "BD_B": 30.0, "BD_C": 50.0})
        # log10 mags: 1.0, 1.48, 1.70 → span 0.70 ≤ 0.75
        groups = _group_breakdowns_by_scale(df, "comp_breakdown_1")
        assert len(groups) == 1, (
            f"All-compatible series should form one group; got {groups}."
        )
        assert set(groups[0]) == {"BD_A", "BD_B", "BD_C"}

    def test_all_incompatible_returns_one_group_per_value(self):
        """Series all far apart → each gets its own group."""
        # log10 mags: 0, 1, 2, 3 → each consecutive pair differs by 1.0 > 0.75
        df = _make_df({"BD_A": 1.0, "BD_B": 10.0, "BD_C": 100.0, "BD_D": 1000.0})
        groups = _group_breakdowns_by_scale(df, "comp_breakdown_1")
        assert len(groups) == 4, (
            f"All-incompatible series should form 4 groups; got {len(groups)} — {groups}."
        )

    def test_wgi_produces_fewer_panels_than_values(self):
        """WGI-style data should be grouped into fewer panels than there are values."""
        df = _make_df(WGI_SERIES)  # 4 breakdown values
        groups = _group_breakdowns_by_scale(df, "comp_breakdown_1")
        assert len(groups) < len(WGI_SERIES), (
            f"WGI data should produce fewer groups than values; got {len(groups)} groups for "
            f"{len(WGI_SERIES)} values."
        )

    def test_wgi_high_magnitude_series_form_own_group(self):
        """The high-magnitude WGI series (WGI_SC ~65) must not be grouped with
        the low-magnitude ones (WGI_SE ~0.2, WGI_EST ~0.6)."""
        df = _make_df(WGI_SERIES)
        groups = _group_breakdowns_by_scale(df, "comp_breakdown_1")
        # Flatten to a lookup: value → group index
        val_to_group = {v: i for i, g in enumerate(groups) for v in g}
        assert val_to_group["WGI_SC"] != val_to_group["WGI_SE"], (
            "WGI_SC (mag ≈1.81) and WGI_SE (mag ≈−0.70) differ by 2.5 log10 units "
            "and must not be placed in the same group."
        )

    def test_custom_grouping_threshold_controls_merging(self):
        """A tighter threshold produces more (smaller) groups."""
        # log10(10)=1, log10(20)≈1.30, log10(100)=2, log10(200)≈2.30
        df = _make_df({"BD_A": 10.0, "BD_B": 20.0, "BD_C": 100.0, "BD_D": 200.0})
        loose = _group_breakdowns_by_scale(df, "comp_breakdown_1", grouping_threshold=1.5)
        tight = _group_breakdowns_by_scale(df, "comp_breakdown_1", grouping_threshold=0.25)
        assert len(tight) >= len(loose), (
            "Tighter threshold must produce at least as many groups as a looser threshold."
        )

    def test_missing_breakdown_column_falls_back_to_empty(self):
        """If the breakdown column is absent, return empty list gracefully."""
        df = _make_df(WGI_SERIES).drop(columns=["comp_breakdown_1"])
        groups = _group_breakdowns_by_scale(df, "comp_breakdown_1")
        assert groups == [], "Missing column must return empty list, not raise."

    def test_missing_value_column_returns_one_per_value(self):
        """If 'value' column is absent, fall back to one singleton per breakdown value."""
        df = _make_df(WGI_SERIES).drop(columns=["value"])
        groups = _group_breakdowns_by_scale(df, "comp_breakdown_1")
        all_vals = {v for g in groups for v in g}
        bd_vals = set(str(v) for v in _make_df(WGI_SERIES)["comp_breakdown_1"].unique())
        assert all_vals == bd_vals, (
            "All breakdown values must appear in the fallback singleton groups."
        )
        assert all(len(g) == 1 for g in groups), (
            "Without 'value' column all groups must be singletons."
        )

    def test_all_values_accounted_for(self):
        """Every unique breakdown value must appear in exactly one group."""
        df = _make_df(WGI_SERIES)
        groups = _group_breakdowns_by_scale(df, "comp_breakdown_1")
        all_in_groups = [v for g in groups for v in g]
        expected = sorted(str(v) for v in df["comp_breakdown_1"].unique())
        assert sorted(all_in_groups) == expected, (
            "All breakdown values must appear in exactly one group."
        )
