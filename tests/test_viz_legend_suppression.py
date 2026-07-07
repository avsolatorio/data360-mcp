"""Phase 2 — Legend Suppression Audit Tests.

Documents and enforces the correct legend visibility contract across all
chart strategies:

  INTENTIONALLY SUPPRESSED (y-axis/facet label makes legend redundant):
    - cross_sectional: y-axis labels each country row
    - small_multiples (Vega facet, color == facet_dim): panel header = legend
    - correlation scatter: direct country text labels replace legend

  MUST BE VISIBLE:
    - temporal_single with multiple series: color legend needed for each country
    - breakdown_comparison multi-panel vconcat: ALL panels must show a legend
      (not just panel 0) because chat embeds scroll and users cannot scroll
      back to the first panel's legend
"""

from __future__ import annotations

import pandas as pd
import pytest

from data360.viz_config import (
    ChartStrategy,
    StrategyResult,
    build_breakdown_comparison_spec,
    build_choropleth_spec,
    build_correlation_spec,
    build_cross_sectional_spec,
    build_heatmap_spec,
    build_small_multiples_spec,
    build_stacked_area_spec,
    build_temporal_single_spec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _temporal_df(
    countries: list[str],
    years: list[int],
    value: float = 50.0,
) -> pd.DataFrame:
    rows = [
        {"country": c, "year": str(y), "value": value}
        for c in countries
        for y in years
    ]
    return pd.DataFrame(rows)


def _breakdown_df(
    breakdowns: list[str],
    years: list[int],
    value: float = 50.0,
) -> pd.DataFrame:
    rows = [
        {"country": "USA", "year": str(y), "comp_breakdown_1": bd, "value": value}
        for bd in breakdowns
        for y in years
    ]
    return pd.DataFrame(rows)


def _multi_country_breakdown_df(
    countries: list[str],
    breakdowns: list[str],
    years: list[int],
) -> pd.DataFrame:
    rows = []
    idx = 0
    for c in countries:
        for y in years:
            for bd in breakdowns:
                rows.append(
                    {
                        "country": c,
                        "year": str(y),
                        "comp_breakdown_1": bd,
                        "value": float(idx * 10 + 1),
                    }
                )
                idx += 1
    return pd.DataFrame(rows)


def _default_result(
    strategy: ChartStrategy = ChartStrategy.TEMPORAL_SINGLE,
    color_dim: str | None = "country",
    facet_dim: str | None = None,
) -> StrategyResult:
    return StrategyResult(
        strategy=strategy,
        reason="test",
        color_dim=color_dim,
        facet_dim=facet_dim,
    )


def _all_color_legends(spec: dict) -> list:
    """Recursively collect all color.legend values from a Vega-Lite spec."""
    results: list = []

    def _walk(node: dict) -> None:
        if not isinstance(node, dict):
            return
        enc = node.get("encoding", {})
        if isinstance(enc, dict) and "color" in enc:
            color_enc = enc["color"]
            if isinstance(color_enc, dict):
                results.append(color_enc.get("legend", "PRESENT"))
        for key in ("layer", "vconcat", "hconcat", "concat"):
            for child in node.get(key, []):
                _walk(child)
        for key in ("spec",):
            child = node.get(key)
            if isinstance(child, dict):
                _walk(child)

    _walk(spec)
    return results


# ---------------------------------------------------------------------------
# INTENTIONALLY SUPPRESSED
# ---------------------------------------------------------------------------


class TestLegendSuppressedIntentionally:
    """These legends must remain suppressed — visual context makes them redundant."""

    def test_cross_sectional_legend_suppressed(self):
        """Horizontal bar: y-axis labels each country row — legend is redundant."""
        df = _temporal_df(["USA", "China", "Germany"], [2022])
        result = _default_result(ChartStrategy.CROSS_SECTIONAL, color_dim="country")
        spec = build_cross_sectional_spec(df, "Test", result)

        enc = spec.get("encoding", {})
        color = enc.get("color", {})
        assert color.get("legend") is None, (
            "cross_sectional should suppress the legend because the y-axis "
            "already labels each country row."
        )

    def test_small_multiples_facet_legend_suppressed_when_color_equals_facet(self):
        """Vega facet small multiples where color == facet_dim: panel header = legend."""
        df = _breakdown_df(["BD1", "BD2", "BD3", "BD4", "BD5"], [2019, 2020, 2021, 2022])
        result = _default_result(
            ChartStrategy.SMALL_MULTIPLES,
            color_dim="comp_breakdown_1",
            facet_dim="comp_breakdown_1",
        )
        spec = build_small_multiples_spec(df, "Test", result)

        inner = spec.get("spec", {})
        color = inner.get("encoding", {}).get("color", {})
        assert color.get("legend") is None, (
            "small_multiples with color==facet_dim should suppress the legend "
            "because each facet panel header already labels the series."
        )

    def test_correlation_scatter_legend_suppressed_with_direct_labels(self):
        """Scatterplot: every dot has a country text label — legend is redundant."""
        df = pd.DataFrame(
            [
                {"country": "USA", "year": "2022", "ind_a": 10.0, "ind_b": 20.0},
                {"country": "UK", "year": "2022", "ind_a": 15.0, "ind_b": 25.0},
                {"country": "France", "year": "2022", "ind_a": 12.0, "ind_b": 22.0},
            ]
        )
        result = StrategyResult(
            strategy=ChartStrategy.CORRELATION,
            reason="test",
            color_dim="country",
            indicator_cols=["ind_a", "ind_b"],
        )
        spec = build_correlation_spec(df, "Test", result)

        legends = _all_color_legends(spec)
        for leg in legends:
            assert leg is None, (
                "correlation scatter should suppress color legend because direct "
                "country text labels are applied to each dot."
            )


# ---------------------------------------------------------------------------
# MUST BE VISIBLE
# ---------------------------------------------------------------------------


class TestLegendMustBeVisible:
    """These legends must NOT be suppressed."""

    def test_temporal_single_multi_country_has_legend(self):
        """Line chart with 3 countries needs a color legend."""
        df = _temporal_df(["USA", "China", "Germany"], [2018, 2019, 2020, 2021, 2022])
        result = _default_result(ChartStrategy.TEMPORAL_SINGLE, color_dim="country")
        spec = build_temporal_single_spec(df, "GDP", result)

        enc = spec.get("encoding", {})
        color = enc.get("color", {})
        assert color.get("legend") is not None or "legend" not in color, (
            "temporal_single with multiple countries must show a color legend."
        )

    def test_stacked_area_has_legend(self):
        """Stacked area: color encodes the series category — legend required."""
        df = _temporal_df(["USA", "China", "Germany"], [2018, 2019, 2020, 2021], value=10.0)
        result = _default_result(ChartStrategy.STACKED_AREA, color_dim="country")
        spec = build_stacked_area_spec(df, "Test", result)

        enc = spec.get("encoding", {})
        color = enc.get("color", {})
        assert color.get("legend") is not None or "legend" not in color, (
            "stacked_area must show a color legend."
        )

    def test_small_multiples_all_panels_have_legend_when_color_differs_from_facet(self):
        """Multi-panel vconcat (small_multiples with color!=facet): ALL panels must show legend.

        The bug: _build_scale_split_vconcat suppressed legend on panels index > 0
        when color_resolve == 'shared'. In a chat embed the panels scroll; users
        cannot reference the first panel's legend when reading panel 2 or 3.
        """
        # color_dim='country', facet_dim='comp_breakdown_1' — triggers _build_scale_split_vconcat
        # which has the shared-color legend suppression on non-first panels.
        df = _multi_country_breakdown_df(
            countries=["USA", "Germany"],
            breakdowns=["BD1", "BD2", "BD3"],
            years=[2018, 2019, 2020, 2021, 2022],
        )
        result = StrategyResult(
            strategy=ChartStrategy.SMALL_MULTIPLES,
            reason="test",
            color_dim="country",
            facet_dim="comp_breakdown_1",
            scale_incompatible=True,
        )
        spec = build_small_multiples_spec(df, "Test", result)

        panels = spec.get("concat") or spec.get("vconcat", [])
        assert len(panels) >= 2, (
            f"Expected at least 2 panels, got {len(panels)}. "
            "Check that the fixture has enough breakdowns to trigger multiple panels."
        )

        suppressed = []
        for i, panel in enumerate(panels):
            enc = panel.get("encoding", {})
            color_enc = enc.get("color", {})
            if isinstance(color_enc, dict) and color_enc.get("legend") is None:
                suppressed.append(i)

        assert not suppressed, (
            f"Panels {suppressed} have legend=None. All panels in a multi-panel "
            f"vconcat must show a legend."
        )

    def test_heatmap_has_gradient_legend(self):
        """Heatmap: gradient legend is the only way to read color=value."""
        df = _temporal_df(
            ["USA", "UK", "France", "Germany", "Japan", "China", "India", "Brazil", "Canada"],
            [2018, 2019, 2020, 2021, 2022],
        )
        result = _default_result(ChartStrategy.HEATMAP, color_dim=None)
        spec = build_heatmap_spec(df, "Test", result)

        enc = spec.get("encoding", {})
        color = enc.get("color", {})
        leg = color.get("legend")
        assert isinstance(leg, dict), (
            "heatmap must have an explicit gradient legend dict."
        )
        assert leg.get("type") == "gradient" or "gradientLength" in leg, (
            "heatmap legend should be a gradient type."
        )

    def test_choropleth_has_gradient_legend(self):
        """Choropleth: color scale legend is the only way to read the map."""
        df = _temporal_df(
            ["United States", "United Kingdom", "Germany", "France"],
            [2022],
            value=75.0,
        )
        result = _default_result(ChartStrategy.CHOROPLETH, color_dim=None)
        spec = build_choropleth_spec(df, "Test", result)

        data_layer = next(
            (layer for layer in spec.get("layer", []) if "encoding" in layer),
            None,
        )
        assert data_layer is not None, "Choropleth should have a data layer with encoding"
        color = data_layer["encoding"].get("color", {})
        leg = color.get("legend")
        assert isinstance(leg, dict), (
            "choropleth must have an explicit legend dict."
        )


# ---------------------------------------------------------------------------
# Phase 2 Regression: shared-color suppression was the bug
# ---------------------------------------------------------------------------


class TestLegendSharedColorSuppression:
    """Regression tests for the 'shared color / non-first panel' suppression bug
    that appeared in 31% of eval reports (n=111, avg score 7.5).

    The bug lives in _build_scale_split_vconcat (called from build_small_multiples_spec
    when color_dim != facet_dim). The first panel gets a legend; subsequent panels
    get legend=None to 'avoid repetition'. This is wrong for chat embed contexts.
    """

    @pytest.mark.parametrize("n_breakdowns", [2, 3, 4])
    def test_all_panels_show_legend_for_various_breakdown_counts(self, n_breakdowns: int):
        """All panels in a vconcat small_multiples chart must have a visible legend."""
        breakdowns = [f"BD{i}" for i in range(1, n_breakdowns + 1)]
        df = _multi_country_breakdown_df(
            countries=["USA", "Germany"],  # multi-country triggers color!=facet path
            breakdowns=breakdowns,
            years=[2018, 2019, 2020, 2021, 2022],
        )
        result = StrategyResult(
            strategy=ChartStrategy.SMALL_MULTIPLES,
            reason="test",
            color_dim="country",
            facet_dim="comp_breakdown_1",
        )
        spec = build_small_multiples_spec(df, "Test", result)

        panels = spec.get("concat") or spec.get("vconcat", [])
        if not panels:
            pytest.skip("Spec uses Vega-Lite native facet — concat/vconcat panel check not applicable")

        suppressed = []
        for i, panel in enumerate(panels):
            enc = panel.get("encoding", {})
            color_enc = enc.get("color", {})
            if isinstance(color_enc, dict) and color_enc.get("legend") is None:
                suppressed.append(i)

        assert not suppressed, (
            f"With {n_breakdowns} breakdowns, panels {suppressed} have legend=None. "
            f"All panels must show a legend."
        )
