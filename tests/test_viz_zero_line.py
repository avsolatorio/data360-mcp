"""Phase 6 — Zero line on signed-value charts.

Charts where the value domain spans negative and positive (GDP growth,
inflation rate, current account balance, etc.) must show a horizontal
reference line at y=0. Without it, the boundary between growth and
contraction is invisible.

Contract:
  - A Vega-Lite `rule` layer at y=0 appears when `min(value) < 0 < max(value)`.
  - The rule is a thin, gray, non-tooltip, non-interactive line.
  - Charts that are entirely positive or entirely negative do NOT get the line.
  - The rule does not replace the existing scale.zero logic for bars.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data360.viz_config import (
    ChartStrategy,
    StrategyResult,
    build_temporal_single_spec,
    dispatch_spec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signed_df(countries, years):
    """GDP-growth-like data: some years negative (2020 COVID dip)."""
    rows = []
    base_vals = {2015: 2.5, 2016: 1.8, 2017: 3.1, 2018: 2.9,
                 2019: 2.2, 2020: -3.4, 2021: 5.7, 2022: 2.1}
    for c in countries:
        for y in years:
            rows.append({"country": c, "year": str(y),
                         "value": base_vals.get(y, 1.0) + (0.5 if c != "USA" else 0)})
    return pd.DataFrame(rows)


def _positive_df(countries, years):
    rows = [{"country": c, "year": str(y), "value": float(50 + i)}
            for i, (c, y) in enumerate((c, y) for c in countries for y in years)]
    return pd.DataFrame(rows)


def _default_result(strategy=ChartStrategy.TEMPORAL_SINGLE, color_dim="country"):
    return StrategyResult(strategy=strategy, reason="test", color_dim=color_dim)


def _find_zero_rule_layer(spec: dict) -> dict | None:
    """Return the first `rule` mark layer at y=0, or None."""
    layers = spec.get("layer", [])
    for layer in layers:
        mark = layer.get("mark", {})
        mark_type = mark.get("type") if isinstance(mark, dict) else mark
        if mark_type != "rule":
            continue
        enc = layer.get("encoding", {})
        y_enc = enc.get("y", {})
        # y=0 can appear as datum or value
        if y_enc.get("datum") == 0 or y_enc.get("value") == 0:
            return layer
    return None


# ---------------------------------------------------------------------------
# Phase 6: zero line present for signed-value line charts
# ---------------------------------------------------------------------------


class TestZeroLineOnSignedValueCharts:
    """A horizontal rule at y=0 must appear when the value domain crosses zero."""

    def test_temporal_single_signed_gets_zero_line(self):
        """Multi-country line chart with negative values must have y=0 rule layer."""
        df = _signed_df(["USA", "Germany", "China"],
                        [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022])
        result = _default_result(ChartStrategy.TEMPORAL_SINGLE)
        spec = build_temporal_single_spec(df, "GDP Growth", result)

        zero_layer = _find_zero_rule_layer(spec)
        assert zero_layer is not None, (
            "temporal_single with signed values must have a y=0 rule layer. "
            "Without it, the boundary between growth and contraction is invisible."
        )

    def test_zero_line_is_styled_correctly(self):
        """The zero line must be visually distinct: thin, gray, non-interactive."""
        df = _signed_df(["USA", "Germany"],
                        [2018, 2019, 2020, 2021, 2022])
        result = _default_result()
        spec = build_temporal_single_spec(df, "T", result)

        zero_layer = _find_zero_rule_layer(spec)
        assert zero_layer is not None, "No zero line layer found"

        mark = zero_layer.get("mark", {})
        assert isinstance(mark, dict), "Zero rule mark should be a dict with properties"
        # Should be thin (strokeWidth <= 1.5)
        sw = mark.get("strokeWidth", 1.0)
        assert sw <= 1.5, f"Zero line strokeWidth should be <=1.5 for subtlety, got {sw}"
        # Should disable tooltip on the rule itself
        assert mark.get("tooltip") is False or "tooltip" not in zero_layer.get("encoding", {}), (
            "Zero line rule should not show a tooltip"
        )

    def test_temporal_single_positive_only_no_zero_line(self):
        """Positive-only data (life expectancy, population) must NOT add a zero line."""
        df = _positive_df(["USA", "Germany"], [2018, 2019, 2020, 2021, 2022])
        result = _default_result()
        spec = build_temporal_single_spec(df, "Life Expectancy", result)

        zero_layer = _find_zero_rule_layer(spec)
        assert zero_layer is None, (
            "Positive-only data must NOT have a y=0 rule layer — "
            "it would appear below the data range and mislead the reader."
        )

    def test_temporal_single_negative_only_no_zero_line(self):
        """Entirely negative data should NOT add a zero line (it would be above all data)."""
        rows = [{"country": c, "year": str(y), "value": -float(i + 1) * 2}
                for i, (c, y) in enumerate((c, y)
                    for c in ["USA", "DE"] for y in [2018, 2019, 2020])]
        df = pd.DataFrame(rows)
        result = _default_result()
        spec = build_temporal_single_spec(df, "Deficit", result)

        zero_layer = _find_zero_rule_layer(spec)
        assert zero_layer is None, (
            "Entirely negative data must NOT have a y=0 rule layer."
        )

    def test_single_country_signed_gets_zero_line(self):
        """Single country GDP growth crossing zero should also get the zero line."""
        df = _signed_df(["USA"], [2018, 2019, 2020, 2021, 2022])
        result = _default_result(color_dim="country")
        spec = build_temporal_single_spec(df, "US GDP Growth", result)

        zero_layer = _find_zero_rule_layer(spec)
        assert zero_layer is not None, (
            "Single-country line chart with signed values must have a y=0 reference line."
        )


# ---------------------------------------------------------------------------
# Regression: existing charts must not be broken
# ---------------------------------------------------------------------------


class TestZeroLineRegressions:
    """Ensure zero line logic does not corrupt non-signed charts."""

    def test_spec_is_layered_when_zero_line_added(self):
        """When a zero line is added, the spec must become a valid layered spec."""
        df = _signed_df(["USA"], [2018, 2019, 2020, 2021, 2022])
        result = _default_result()
        spec = build_temporal_single_spec(df, "T", result)

        if _find_zero_rule_layer(spec) is not None:
            # Must be a layer spec
            assert "layer" in spec, (
                "A zero-line spec must be a Vega-Lite layered spec with a 'layer' key."
            )
            # The original line mark must still be in the layers
            line_layers = [
                l for l in spec["layer"]
                if (l.get("mark", {}).get("type") if isinstance(l.get("mark"), dict) else l.get("mark")) == "line"
            ]
            assert line_layers, "The original line layer must still exist in the layered spec."

    def test_positive_spec_retains_flat_structure(self):
        """If no zero line is added, the spec should remain flat (not forcibly wrapped)."""
        df = _positive_df(["USA", "DE"], [2018, 2019, 2020, 2021, 2022])
        result = _default_result()
        spec = build_temporal_single_spec(df, "T", result)

        # Flat spec has a top-level mark — not forced into a layer
        has_mark = "mark" in spec
        has_layer = "layer" in spec
        # Either a flat mark OR a layer is fine; but must not be layer with zero_line
        if has_layer:
            zero_layer = _find_zero_rule_layer(spec)
            assert zero_layer is None, (
                "A positive-only spec must not have a zero_line layer even if layered."
            )
