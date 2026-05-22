import pandas as pd
import pytest

from data360.viz_config import (
    ChartStrategy,
    StrategyResult,
    build_choropleth_spec,
    parse_chart_type_hint,
    select_strategy,
)


def test_build_choropleth_spec_multi_year_filters_latest():
    df = pd.DataFrame({
        "country": ["Italy", "Italy", "France", "France"],
        "year": ["2019", "2020", "2019", "2020"],
        "value": [1.0, 2.0, 3.0, 4.0]
    })
    result = StrategyResult(ChartStrategy.CHOROPLETH, "test")
    spec = build_choropleth_spec(df, "Test", result)

    # Should only contain 2020 data
    values = spec["transform"][0]["from"]["data"]["values"]
    assert len(values) == 2
    assert all(v["year"] == "2020" for v in values)

    # Subtitle should warn about the filter
    subtitle = "".join(spec["title"]["subtitle"])
    assert "most recent year (2020)" in subtitle

def test_build_choropleth_spec_has_geoshape():
    df = pd.DataFrame({
        "country": ["Italy"],
        "year": ["2020"],
        "value": [2.0]
    })
    result = StrategyResult(ChartStrategy.CHOROPLETH, "test")
    spec = build_choropleth_spec(df, "Test", result)

    assert spec["layer"][0]["mark"]["type"] == "geoshape"
    assert spec["layer"][1]["mark"]["type"] == "geoshape"
    assert "url" in spec["data"]


# ---------------------------------------------------------------------------
# parse_chart_type_hint — keyword normalisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("map", "map"),
    ("choropleth", "map"),
    ("choropleth map", "map"),
    ("geographic", "map"),
    ("geoshape", "map"),
    ("heatmap", "heatmap"),
    ("heat map", "heatmap"),
    ("heat", "heatmap"),
    # unrecognised falls back to default
    ("unknown_chart", "line"),
    (None, "line"),
])
def test_parse_chart_type_hint_normalises(raw, expected):
    assert parse_chart_type_hint(raw) == expected


# ---------------------------------------------------------------------------
# select_strategy — map/choropleth hint routing
# ---------------------------------------------------------------------------

def _make_df(countries: list[str], years: list[str]) -> pd.DataFrame:
    rows = [
        {"country": c, "year": y, "value": 1.0}
        for c in countries
        for y in years
    ]
    return pd.DataFrame(rows)


@pytest.mark.parametrize("hint", ["map", "choropleth", "geographic", "choropleth map"])
def test_map_hint_routes_to_choropleth(hint):
    """Any map-family hint must produce CHOROPLETH regardless of data shape."""
    df = _make_df(["Italy", "France", "Germany"], ["2020"])
    result = select_strategy(df, chart_type_hint=hint)
    assert result.strategy == ChartStrategy.CHOROPLETH, (
        f"hint={hint!r} → expected CHOROPLETH, got {result.strategy}"
    )


@pytest.mark.parametrize("hint", ["map", "choropleth"])
def test_map_hint_routes_to_choropleth_multi_year(hint):
    """Map hints with multi-year data should still produce CHOROPLETH (not HEATMAP)."""
    # 10 countries × 5 years — would normally auto-route to HEATMAP
    countries = [f"C{i}" for i in range(10)]
    df = _make_df(countries, ["2019", "2020", "2021", "2022", "2023"])
    result = select_strategy(df, chart_type_hint=hint)
    assert result.strategy == ChartStrategy.CHOROPLETH, (
        f"hint={hint!r} with multi-year data → expected CHOROPLETH, got {result.strategy}"
    )


# ---------------------------------------------------------------------------
# select_strategy — explicit heatmap hint routing
# ---------------------------------------------------------------------------

def test_explicit_heatmap_hint_routes_to_heatmap_below_auto_threshold():
    """Explicit 'heatmap' hint should produce HEATMAP even with fewer than 9 countries."""
    # 3 countries × 3 years — below the auto-routing beeswarm_threshold of 8
    df = _make_df(["Japan", "Indonesia", "Philippines"], ["2021", "2022", "2023"])
    result = select_strategy(df, chart_type_hint="heatmap")
    assert result.strategy == ChartStrategy.HEATMAP, (
        f"Explicit heatmap hint with 3 countries → expected HEATMAP, got {result.strategy}"
    )


def test_explicit_heatmap_hint_single_year_falls_through():
    """Explicit 'heatmap' hint with only one year should NOT produce HEATMAP
    (no meaningful country×year matrix); it falls through to a cross-sectional chart."""
    df = _make_df(["Japan", "Indonesia", "Philippines"], ["2022"])
    result = select_strategy(df, chart_type_hint="heatmap")
    assert result.strategy != ChartStrategy.HEATMAP, (
        f"Single-year data with heatmap hint should not route to HEATMAP, got {result.strategy}"
    )
