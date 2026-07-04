"""Tests for small multiples spec builder fixes."""

from __future__ import annotations

import pandas as pd
from data360.viz_config import (
    ChartStrategy,
    StrategyResult,
    build_small_multiples_spec,
    get_main_data_layer,
)

def test_small_multiples_colors_by_color_dim():
    """Verify that small multiples colors by result.color_dim when specified,
    instead of redundantly coloring by facet_dim and hiding the legend.
    """
    rows = []
    # 5 countries, 2 sexes, 5 years
    for c in ["USA", "CHN", "DEU", "FRA", "GBR"]:
        for sex in ["Male", "Female"]:
            for year in range(2015, 2020):
                rows.append({
                    "country": c,
                    "sex": sex,
                    "year": str(year),
                    "value": float(hash(c + sex + str(year)) % 100)
                })
    df = pd.DataFrame(rows)

    result = StrategyResult(
        strategy=ChartStrategy.SMALL_MULTIPLES,
        reason="test",
        color_dim="sex",
        facet_dim="country"
    )

    spec = build_small_multiples_spec(df, "Test", result)

    # Check that it uses native facet
    assert "facet" in spec
    assert "spec" in spec

    inner_spec = spec["spec"]
    color_encoding = inner_spec["encoding"]["color"]

    # Must color by "sex", not "country"
    assert color_encoding["field"] == "sex"
    assert color_encoding["type"] == "nominal"
    assert color_encoding.get("legend") is not None
    assert color_encoding["legend"] != None
