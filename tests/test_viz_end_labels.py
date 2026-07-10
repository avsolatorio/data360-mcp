"""Phase 7 — Country end labels on multi-series line charts.

When a temporal_single chart shows 2–8 countries, the legend forces the user
to look away from the data to identify each line. Direct end labels (country
name anchored to the line's last data point) eliminate this cognitive load.

Contract:
  - A `text` layer anchored to the last year of each series appears when
    country_count is in [2, MAX_END_LABEL_SERIES].
  - The text encodes `country` (or whichever color_dim is used).
  - Single-country charts do NOT get end labels (no ambiguity exists).
  - Charts with >MAX_END_LABEL_SERIES countries do NOT get end labels
    (too crowded; the legend is cleaner).
  - The text layer does NOT show a tooltip (it is decoration, not data).
"""

from __future__ import annotations

import pandas as pd
import pytest

from data360.viz_config import (
    ChartStrategy,
    MAX_END_LABEL_SERIES,
    StrategyResult,
    build_temporal_single_spec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _multi_df(country_count: int, years: list[int]) -> pd.DataFrame:
    countries = [f"C{i:02d}" for i in range(country_count)]
    return pd.DataFrame(
        [{"country": c, "year": str(y), "value": float(i * 10 + j)}
         for i, c in enumerate(countries)
         for j, y in enumerate(years)]
    )


def _default_result():
    return StrategyResult(
        strategy=ChartStrategy.TEMPORAL_SINGLE,
        reason="test",
        color_dim="country",
    )


def _find_end_label_layer(spec: dict) -> dict | None:
    """Return the text layer used for end labels, or None."""
    for layer in spec.get("layer", []):
        mark = layer.get("mark", {})
        mark_type = mark.get("type") if isinstance(mark, dict) else mark
        if mark_type != "text":
            continue
        enc = layer.get("encoding", {})
        # Must encode the country/color_dim as text
        text_enc = enc.get("text", {})
        if text_enc.get("field") in ("country", "ref_area"):
            return layer
    return None


# ---------------------------------------------------------------------------
# Phase 7: end labels
# ---------------------------------------------------------------------------


class TestEndLabelsOnMultiSeriesLines:
    """Direct end labels must appear for 2 to MAX_END_LABEL_SERIES countries."""

    @pytest.mark.parametrize("n_countries", [2, 3, 4, 5])
    def test_end_labels_appear_for_small_multiseries(self, n_countries: int):
        """Charts with 2–5 countries must show a text end-label layer."""
        df = _multi_df(n_countries, [2018, 2019, 2020, 2021, 2022])
        result = _default_result()
        spec = build_temporal_single_spec(df, f"{n_countries}-country chart", result)

        text_layer = _find_end_label_layer(spec)
        assert text_layer is not None, (
            f"temporal_single with {n_countries} countries must have a text "
            f"end-label layer so users can identify each line without consulting the legend."
        )

    def test_end_labels_absent_for_single_country(self):
        """Single-country line chart has no ambiguity — no end label needed."""
        df = _multi_df(1, [2018, 2019, 2020, 2021, 2022])
        result = _default_result()
        spec = build_temporal_single_spec(df, "Single country", result)

        text_layer = _find_end_label_layer(spec)
        assert text_layer is None, (
            "Single-country line chart must NOT have an end-label layer."
        )

    def test_end_labels_absent_for_too_many_countries(self):
        """With >MAX_END_LABEL_SERIES countries the legend is cleaner than cramped labels."""
        n = MAX_END_LABEL_SERIES + 1
        df = _multi_df(n, [2018, 2019, 2020, 2021, 2022])
        result = _default_result()
        spec = build_temporal_single_spec(df, "Many countries", result)

        text_layer = _find_end_label_layer(spec)
        assert text_layer is None, (
            f"Charts with >{MAX_END_LABEL_SERIES} countries must NOT have end labels "
            f"(too cramped); the color legend should be used instead."
        )

    def test_end_label_anchored_to_last_year(self):
        """The text mark must use a transform or filter to show only the last data point."""
        df = _multi_df(3, [2018, 2019, 2020, 2021, 2022])
        result = _default_result()
        spec = build_temporal_single_spec(df, "T", result)

        text_layer = _find_end_label_layer(spec)
        if text_layer is None:
            pytest.skip("End labels not yet implemented")

        transforms = text_layer.get("transform", [])
        # Must have a filter or aggregate that selects the last year
        has_last_year_filter = any(
            "max" in str(t).lower() or "last" in str(t).lower()
            or "argmax" in str(t).lower() or "filter" in str(t).lower()
            for t in transforms
        )
        assert has_last_year_filter, (
            "End label text layer must filter to last data point "
            f"(via argmax, filter, or similar). Transforms found: {transforms}"
        )

    def test_end_label_positioned_right_of_line(self):
        """The text mark must be right-aligned and offset slightly right of the line end."""
        df = _multi_df(3, [2018, 2019, 2020, 2021, 2022])
        result = _default_result()
        spec = build_temporal_single_spec(df, "T", result)

        text_layer = _find_end_label_layer(spec)
        if text_layer is None:
            pytest.skip("End labels not yet implemented")

        mark = text_layer.get("mark", {})
        align = mark.get("align", "") if isinstance(mark, dict) else ""
        dx = mark.get("dx", 0) if isinstance(mark, dict) else 0

        assert align == "left", (
            f"End labels should be left-aligned (placed to the right of the line end). Got: {align!r}"
        )
        assert dx >= 3, (
            f"End labels should have a positive dx offset to sit right of the line. Got: {dx}"
        )

    def test_end_label_no_tooltip(self):
        """The text decoration layer must not show a tooltip (it is visual, not interactive)."""
        df = _multi_df(3, [2018, 2019, 2020, 2021, 2022])
        result = _default_result()
        spec = build_temporal_single_spec(df, "T", result)

        text_layer = _find_end_label_layer(spec)
        if text_layer is None:
            pytest.skip("End labels not yet implemented")

        mark = text_layer.get("mark", {})
        assert mark.get("tooltip") is False or mark.get("tooltip") is None, (
            "End label text layer must not show a tooltip."
        )

    def test_original_line_layer_still_present(self):
        """Adding a text layer must not remove the original line mark."""
        df = _multi_df(3, [2018, 2019, 2020, 2021, 2022])
        result = _default_result()
        spec = build_temporal_single_spec(df, "T", result)

        layers = spec.get("layer", [])
        line_layers = [
            l for l in layers
            if (l.get("mark", {}).get("type") if isinstance(l.get("mark"), dict) else l.get("mark")) == "line"
        ]
        # Either still a flat spec (no layers) or must have a line layer
        has_top_mark = spec.get("mark", {}).get("type") == "line" if isinstance(spec.get("mark"), dict) else spec.get("mark") == "line"
        assert has_top_mark or line_layers, (
            "The original line layer must still exist after end labels are added."
        )
