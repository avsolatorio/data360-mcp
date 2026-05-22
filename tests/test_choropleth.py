import pandas as pd
from data360.viz_config import build_choropleth_spec, ChartStrategy, StrategyResult

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
