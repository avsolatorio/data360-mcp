"""Choropleth map spec helpers and validation."""

import pandas as pd

from data360 import viz_config


def test_build_choropleth_geo_join_alias_map_iso2_and_un_m49() -> None:
    features = [
        {
            "type": "Feature",
            "properties": {
                "WB_A3": "USA",
                "ISO_A3": "USA",
                "WB_A2": "US",
                "ISO_A2": "US",
                "UN_A3": "840",
            },
        },
        {
            "type": "Feature",
            "properties": {
                "WB_A3": "KEN",
                "ISO_A3": "KEN",
                "ISO_A2": "KE",
                "UN_A3": "404",
            },
        },
    ]
    m = viz_config.build_choropleth_geo_join_alias_map(features)
    assert m["USA"] == "USA"
    assert m["US"] == "USA"
    assert m["840"] == "USA"
    assert m["404"] == "KEN"
    assert m["KE"] == "KEN"


def test_normalize_choropleth_wb_a3_codes() -> None:
    alias = {"US": "USA", "840": "USA", "404": "KEN"}
    s = pd.Series(["us", "840", "404", "KEN"])
    out = viz_config.normalize_choropleth_wb_a3_codes(s, alias)
    assert list(out) == ["USA", "USA", "KEN", "KEN"]


def test_wants_choropleth_keywords() -> None:
    assert viz_config.wants_choropleth("choropleth")
    assert viz_config.wants_choropleth("World map of GDP")
    assert viz_config.wants_choropleth("geo map")
    assert not viz_config.wants_choropleth("map")
    assert not viz_config.wants_choropleth(None)
    assert not viz_config.wants_choropleth("line")


def test_validate_choropleth_df_multi_year_errors() -> None:
    df = pd.DataFrame(
        {
            "wb_a3": ["BRA", "ARG"],
            "value": [1.0, 2.0],
            "year": ["2019", "2020"],
            "country": ["Brazil", "Argentina"],
        }
    )
    err = viz_config.validate_choropleth_df(df)
    assert err is not None
    assert "single time period" in err.lower()


def test_validate_choropleth_df_ok() -> None:
    df = pd.DataFrame(
        {
            "wb_a3": ["BRA", "ARG"],
            "value": [1.0, 2.0],
            "year": ["2019", "2019"],
            "country": ["Brazil", "Argentina"],
        }
    )
    assert viz_config.validate_choropleth_df(df) is None


def test_build_choropleth_spec_structure() -> None:
    df = pd.DataFrame(
        {
            "wb_a3": ["BRA"],
            "value": [42.5],
            "year": ["2019"],
            "country": ["Brazil"],
        }
    )
    spec = viz_config.build_choropleth_spec(
        df,
        "Test indicator",
        geo_url="https://example.com/world.json",
        geo_join_prop="WB_A3",
        unit_measure="%",
    )
    assert spec["mark"]["type"] == "geoshape"
    assert spec["mark"]["stroke"] == viz_config.WB_GRID_COLOR
    assert spec["mark"]["strokeWidth"] == 0.55
    assert spec["encoding"]["color"]["scale"]["type"] == "linear"
    assert spec["projection"]["type"] == "equirectangular"
    assert spec["projection"].get("clipAngle") is None
    assert spec["encoding"]["shape"]["type"] == "geojson"
    assert spec["encoding"]["color"]["field"] == "value"
    transforms = spec["transform"]
    assert any("lookup" in t for t in transforms)
    lookup = next(t for t in transforms if "lookup" in t)
    assert lookup["lookup"] == "wb_a3"
    assert lookup["from"]["data"]["url"] == "https://example.com/world.json"
    assert lookup["from"]["key"] == "properties.WB_A3"
    assert "fields" not in lookup["from"]
    assert lookup["as"] == "geo"
    assert spec["encoding"]["color"]["legend"] is not None
