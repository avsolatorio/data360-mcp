"""Choropleth map spec helpers and validation."""

import pandas as pd

from data360 import viz_config


def test_normalize_year_column_for_display() -> None:
    s = pd.Series(
        pd.to_datetime(["2020-01-01", "2019-06-15", "2021-01-01"]),
    )
    out = viz_config.normalize_year_column_for_display(s)
    assert list(out) == ["2020", "2019-06-15", "2021"]
    s2 = pd.Series(["2020-01-01", "1999", ""])
    out2 = viz_config.normalize_year_column_for_display(s2)
    assert out2.tolist() == ["2020", "1999", ""]


def _choropleth_map_layer(spec: dict) -> dict:
    for lyr in spec["layer"]:
        for p in lyr.get("params") or []:
            if p.get("name") == "choropleth_hover":
                return lyr
    msg = "expected a geoshape layer with choropleth_hover"
    raise AssertionError(msg)


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


def _choropleth_base_layer(spec: dict) -> dict:
    """Grey landmass layer (no choropleth_hover params)."""
    for lyr in spec["layer"]:
        enc = lyr.get("encoding") or {}
        col = enc.get("color") or {}
        if col.get("value") == viz_config.WB_MAP_NO_DATA_FILL:
            return lyr
    raise AssertionError("expected base geoshape layer with no-data fill")


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
    assert spec["projection"]["type"] == "equirectangular"
    assert spec["projection"].get("clipAngle") is None
    assert spec["resolve"]["legend"]["merge"] is False
    assert spec["datasets"]["choropleth_stats"][0]["wb_a3"] == "BRA"
    base = _choropleth_base_layer(spec)
    assert base["encoding"]["color"]["legend"]["title"] == "No data"
    data_layer = _choropleth_map_layer(spec)
    assert data_layer["params"][0]["name"] == "choropleth_hover"
    assert data_layer["mark"]["type"] == "geoshape"
    assert data_layer["encoding"]["stroke"]["value"] == viz_config.WB_MAP_OUTLINE_GREY
    assert data_layer["encoding"]["strokeWidth"]["value"] == viz_config.WB_MAP_OUTLINE_WIDTH
    assert data_layer["encoding"]["detail"]["field"] == "wb_detail"
    color_enc = data_layer["encoding"]["color"]
    assert color_enc["field"] == "choropleth_value"
    assert color_enc["type"] == "quantitative"
    assert color_enc["scale"]["type"] == "linear"
    assert color_enc["scale"]["scheme"] == "blues"
    assert color_enc["scale"]["domainMin"] == 0
    assert color_enc["legend"]["values"] == [0.0, 21.25, 42.5]
    lookups = [t for t in data_layer["transform"] if "lookup" in t]
    stats_lookup = next(
        t for t in lookups if t["from"].get("data", {}).get("name") == "choropleth_stats"
    )
    assert stats_lookup["lookup"] == "properties.WB_A3"
    assert stats_lookup["from"]["key"] == "wb_a3"
    assert color_enc["legend"] is not None
    assert color_enc["legend"]["labelExpr"] == "format(datum.value, '.1f') + '%'"
    value_tip_tf = next(
        t for t in data_layer["transform"] if t.get("as") == "value_tip"
    )
    assert "format(datum.choropleth_value, '.1f') + '%'" in value_tip_tf["calculate"]
    filter_tf = next(t for t in data_layer["transform"] if "filter" in t)
    assert filter_tf["filter"] == "isValid(datum.choropleth_value)"


def test_build_choropleth_spec_legend_and_tooltip_use_compact_suffixes() -> None:
    df = pd.DataFrame(
        {
            "wb_a3": ["CHN"],
            "value": [1.5e9],
            "year": ["2020"],
            "country": ["China"],
        }
    )
    spec = viz_config.build_choropleth_spec(
        df,
        "GHG",
        geo_url="https://example.com/world.json",
        geo_join_prop="WB_A3",
        unit_measure="MtCO2eq/year",
    )
    data_layer = _choropleth_map_layer(spec)
    leg = data_layer["encoding"]["color"]["legend"]
    assert "labelExpr" in leg
    assert "1e9" in leg["labelExpr"] and "'b'" in leg["labelExpr"]
    value_tip_tf = next(
        t for t in data_layer["transform"] if t.get("as") == "value_tip"
    )
    assert "choropleth_value" in value_tip_tf["calculate"]
    assert "1e9" in value_tip_tf["calculate"] and "'b'" in value_tip_tf["calculate"]


def test_build_choropleth_spec_diverging_when_mixed_sign() -> None:
    df = pd.DataFrame(
        {
            "wb_a3": ["USA", "CHN"],
            "value": [-10.0, 5.0],
            "year": ["2019", "2019"],
            "country": ["United States", "China"],
        }
    )
    spec = viz_config.build_choropleth_spec(
        df,
        "Net flow",
        geo_url="https://example.com/world.json",
        geo_join_prop="WB_A3",
    )
    data_layer = _choropleth_map_layer(spec)
    scale = data_layer["encoding"]["color"]["scale"]
    assert scale["scheme"] == "redblue"
    assert scale["reverse"] is True
    assert scale["domain"] == [-10.0, 10.0]
    assert "domainMin" not in scale
    assert data_layer["encoding"]["color"]["legend"]["values"] == [-10.0, 0.0, 10.0]


def test_build_choropleth_spec_domain_excludes_aggregate_totals() -> None:
    """World/regional rows must not set the color domain or the legend washes out."""
    df = pd.DataFrame(
        {
            "wb_a3": ["CHN", "USA", "WLD"],
            "value": [13.15e9, -4.7e9, 48.87e9],
            "year": ["2020", "2020", "2020"],
            "country": ["China", "United States", "World"],
        }
    )
    spec = viz_config.build_choropleth_spec(
        df,
        "GHG",
        geo_url="https://example.com/world.json",
        geo_join_prop="WB_A3",
    )
    assert len(spec["datasets"]["choropleth_stats"]) == 3
    data_layer = _choropleth_map_layer(spec)
    dom = data_layer["encoding"]["color"]["scale"]["domain"]
    assert abs(dom[0] + 13.15e9) < 1e-3
    assert abs(dom[1] - 13.15e9) < 1e-3
    leg_vals = data_layer["encoding"]["color"]["legend"]["values"]
    assert len(leg_vals) == 3
    assert abs(leg_vals[0] + 13.15e9) < 1e-3
    assert leg_vals[1] == 0.0
    assert abs(leg_vals[2] - 13.15e9) < 1e-3


def test_build_choropleth_spec_sequential_all_negative() -> None:
    df = pd.DataFrame(
        {
            "wb_a3": ["USA", "CHN"],
            "value": [-100.0, -5.0],
            "year": ["2019", "2019"],
            "country": ["United States", "China"],
        }
    )
    spec = viz_config.build_choropleth_spec(
        df,
        "Shortfall",
        geo_url="https://example.com/world.json",
        geo_join_prop="WB_A3",
    )
    data_layer = _choropleth_map_layer(spec)
    scale = data_layer["encoding"]["color"]["scale"]
    assert scale["scheme"] == "blues"
    assert scale["reverse"] is True
    assert scale["domain"] == [-100.0, 0.0]
    assert data_layer["encoding"]["color"]["legend"]["values"] == [-100.0, -50.0, 0.0]


def test_build_choropleth_spec_country_names_lookup_precedence() -> None:
    df = pd.DataFrame(
        {
            "wb_a3": ["BRA"],
            "value": [1.0],
            "year": ["2019"],
            "country": ["Brazil"],
        }
    )
    url_spec = viz_config.build_choropleth_spec(
        df,
        "T",
        geo_url="https://example.com/w.json",
        geo_join_prop="WB_A3",
        country_names_url="https://example.com/names.json",
        country_name_rows=[{"wb_a3": "BRA", "country_name": "Inline"}],
    )
    url_layer = _choropleth_map_layer(url_spec)
    url_transform = url_layer["transform"]
    lookup_from = next(t for t in url_transform if "lookup" in t)["from"]
    assert lookup_from["data"]["url"] == "https://example.com/names.json"

    inline_spec = viz_config.build_choropleth_spec(
        df,
        "T",
        geo_url="https://example.com/w.json",
        geo_join_prop="WB_A3",
        country_names_url=None,
        country_name_rows=[{"wb_a3": "BRA", "country_name": "Inline"}],
    )
    inline_layer = _choropleth_map_layer(inline_spec)
    inline_lookup = next(t for t in inline_layer["transform"] if "lookup" in t)["from"]
    assert inline_lookup["data"]["values"][0]["country_name"] == "Inline"


def test_build_choropleth_spec_disputed_topojson_format() -> None:
    df = pd.DataFrame(
        {
            "wb_a3": ["USA"],
            "value": [1.0],
            "year": ["2020"],
            "country": ["United States"],
        }
    )
    spec = viz_config.build_choropleth_spec(
        df,
        "T",
        geo_url="https://example.com/world.json",
        geo_join_prop="WB_A3",
        disputed_areas_geo_url="https://example.com/wb_disputed_areas_topo.json",
    )
    disputed = spec["layer"][0]
    assert disputed["data"]["format"] == {
        "type": "topojson",
        "feature": viz_config.CHOROPLETH_DISPUTED_TOPOJSON_FEATURE,
    }


def test_build_choropleth_spec_disputed_geojson_format_when_not_topo_suffix() -> None:
    df = pd.DataFrame(
        {
            "wb_a3": ["USA"],
            "value": [1.0],
            "year": ["2020"],
            "country": ["United States"],
        }
    )
    spec = viz_config.build_choropleth_spec(
        df,
        "T",
        geo_url="https://example.com/world.json",
        geo_join_prop="WB_A3",
        disputed_areas_geo_url="https://example.com/wb_disputed_areas_geo.json",
    )
    disputed = spec["layer"][0]
    assert disputed["data"]["format"] == {"type": "json", "property": "features"}
