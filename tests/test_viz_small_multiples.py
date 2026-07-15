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
        color_dim="country",
        facet_dim="sex"
    )

    spec = build_small_multiples_spec(df, "Test", result)

    # Check that it uses flat single view spec (not concat)
    assert "concat" not in spec
    assert "vconcat" not in spec
    assert spec.get("width") == 600
    assert spec.get("height") == 350

    if "layer" in spec:
        color_encoding = spec["layer"][0]["encoding"]["color"]
    else:
        color_encoding = spec["encoding"]["color"]

    # Must color by combo field which includes "sex" and "country"
    assert color_encoding["field"] == "_combo_label"
    assert color_encoding["type"] == "nominal"


def test_small_multiples_single_panel_flat_spec():
    """Verify that small multiples with only 1 panel/group returns a flat single view spec (not concat)."""
    rows = []
    # 1 country, 1 sex, 5 years (results in 1 panel)
    for year in range(2015, 2020):
        rows.append({
            "country": "USA",
            "sex": "Male",
            "year": str(year),
            "value": float(year - 2017) # Spans negative & positive: -2, -1, 0, 1, 2
        })
    df = pd.DataFrame(rows)

    result = StrategyResult(
        strategy=ChartStrategy.SMALL_MULTIPLES,
        reason="test",
        color_dim="country",
        facet_dim="sex"
    )

    spec = build_small_multiples_spec(
        df, "Test Title", result,
        y_label="Percentage of population",
        indicator_name="Test Indicator"
    )

    # Must be a flat spec or flat layered spec, NOT concat/vconcat
    assert "concat" not in spec
    assert "vconcat" not in spec

    # Dimensions should match temporal_single
    assert spec.get("width") == 600
    assert spec.get("height") == 350

    # It has layers because value spans negative & positive (zero line)
    assert "layer" in spec
    main_layer = spec["layer"][0]

    # Y-axis title should be resolved
    y_axis = main_layer["encoding"]["y"]["axis"]
    assert y_axis["title"] == "Percentage of population"


def test_small_multiples_grouped_bar_with_xoffset():
    """Verify that single-panel bar charts with multiple color series add xOffset."""
    rows = [
        {"country": "USA", "indicator": "Total", "value": 0.12},
        {"country": "CHN", "indicator": "Total", "value": 0.15},
        {"country": "USA", "indicator": "Paid", "value": 0.18},
        {"country": "CHN", "indicator": "Paid", "value": 0.20},
    ]
    df = pd.DataFrame(rows)

    result = StrategyResult(
        strategy=ChartStrategy.SMALL_MULTIPLES,
        reason="test",
        color_dim="country",
        facet_dim="indicator"
    )

    spec = build_small_multiples_spec(
        df, "Test Title", result,
        y_label="Percentage"
    )

    assert "concat" not in spec
    assert "vconcat" not in spec

    # X-axis field should be the facet dimension ("indicator"), and color is "country"
    # To keep bars from stacking, xOffset should be present
    encoding = spec["encoding"] if "encoding" in spec else spec["layer"][0]["encoding"]
    assert encoding["x"]["field"] == "indicator"
    assert encoding["color"]["field"] == "country"
    assert encoding["xOffset"]["field"] == "country"


def test_percentage_boundary_clamping_proportion_label_scaling():
    """Verify that PercentageBoundaryClampingRule scales proportion labels correctly."""
    from data360.viz_config import PercentageBoundaryClampingRule

    # 1. Flat spec
    spec = {
        "mark": "bar",
        "encoding": {
            "y": {
                "type": "quantitative",
                "axis": {
                    "labelExpr": "format(datum.value, '.1~f') + '%'"
                }
            }
        }
    }

    df = pd.DataFrame([{"value": 0.25}, {"value": 0.58}])
    rule = PercentageBoundaryClampingRule()
    clamped_spec = rule.apply(spec, scale_type="percentage", df=df)

    # Label expression must evaluate datum.value * 100
    label_expr = clamped_spec["encoding"]["y"]["axis"]["labelExpr"]
    assert "datum.value * 100" in label_expr

    # 2. Layered spec
    layered_spec = {
        "layer": [
            {
                "mark": "line",
                "encoding": {
                    "y": {
                        "type": "quantitative",
                        "axis": {
                            "labelExpr": "format(datum.value, '.1~f') + '%'"
                        }
                    }
                }
            }
        ]
    }
    clamped_layered_spec = rule.apply(layered_spec, scale_type="percentage", df=df)
    label_expr_layered = clamped_layered_spec["layer"][0]["encoding"]["y"]["axis"]["labelExpr"]
    assert "datum.value * 100" in label_expr_layered


def test_generalized_proportion_indicator_detection():
    """Verify that indicators with percentage/rate/share names/units and values <= 1.0 are formatted as proportion."""
    from data360.viz_config import ValueAxisLabelFormatRule, PercentageBoundaryClampingRule

    spec = {
        "mark": "bar",
        "encoding": {
            "y": {
                "type": "quantitative",
                "axis": {},
                "field": "value"
            }
        }
    }

    # Dataframe with 'indicator' column having 'rate' in name
    df = pd.DataFrame([
        {"value": 0.05, "indicator": "Youth unemployment rate"},
        {"value": 0.45, "indicator": "Youth unemployment rate"},
    ])

    # Apply format rule (which uses _is_proportion_indicator helper)
    format_rule = ValueAxisLabelFormatRule()
    formatted = format_rule.apply(spec, df=df)

    # Should use '.0%' formatting for proportions
    assert formatted["encoding"]["y"]["axis"]["labelExpr"] == "format(datum.value, '.0%')"

    # Apply clamping rule
    clamp_rule = PercentageBoundaryClampingRule()
    clamped = clamp_rule.apply(spec, df=df)
    assert clamped["encoding"]["y"]["scale"]["domain"] == [0, 0.5]


def test_small_multiples_columns_layout():
    """Verify that _determine_small_multiples_columns caps at a maximum of 2 columns."""
    from data360.viz_config import _determine_small_multiples_columns

    # 1 panel -> None
    assert _determine_small_multiples_columns(1, 1) is None

    # 2 panels -> 2 columns
    assert _determine_small_multiples_columns(2, 1) == 2

    # 3 panels -> 2 columns
    assert _determine_small_multiples_columns(3, 1) == 2

    # 4 panels -> 2 columns
    assert _determine_small_multiples_columns(4, 1) == 2

    # 5 panels -> 2 columns
    assert _determine_small_multiples_columns(5, 1) == 2


def test_percentage_clamping_excludes_negatives_and_unbounded():
    """Verify that percentage clamping is bypassed for negative values or unbounded rates."""
    from data360.viz_config import PercentageBoundaryClampingRule

    spec = {
        "mark": "line",
        "encoding": {
            "y": {
                "type": "quantitative",
                "axis": {},
                "scale": {}
            }
        }
    }

    rule = PercentageBoundaryClampingRule()

    # 1. Negative values -> Bypass clamping
    df_neg = pd.DataFrame([{"value": -5.0}, {"value": 15.0}])
    res_neg = rule.apply(spec, scale_type="percentage", df=df_neg)
    assert "domain" not in res_neg["encoding"]["y"]["scale"]

    # 2. Unbounded growth rate -> Bypass clamping
    df_growth = pd.DataFrame([
        {"value": 1.5, "indicator": "Real GDP growth rate (annual %)"},
        {"value": 4.5, "indicator": "Real GDP growth rate (annual %)"},
    ])
    res_growth = rule.apply(spec, scale_type="percentage", df=df_growth)
    assert "domain" not in res_growth["encoding"]["y"]["scale"]

    # 3. Normal positive percentage indicator -> Apply clamping to [0, 100]
    df_normal = pd.DataFrame([
        {"value": 15.0, "indicator": "Participation rate (% of population)"},
        {"value": 65.0, "indicator": "Participation rate (% of population)"},
    ])
    res_normal = rule.apply(spec, scale_type="percentage", df=df_normal)
    assert res_normal["encoding"]["y"]["scale"]["domain"] == [0, 100]


def test_percentage_clamping_dynamic_bounds():
    """Verify that percentage clamping uses dynamic bounds or bypasses clamping when concentrated far from zero."""
    from data360.viz_config import PercentageBoundaryClampingRule

    spec = {
        "mark": "line",
        "encoding": {
            "y": {
                "type": "quantitative",
                "axis": {},
                "scale": {}
            }
        }
    }
    rule = PercentageBoundaryClampingRule()

    # 1. High-value concentration (min > 30%) -> Bypass clamping (allows full zoom-in)
    df_high = pd.DataFrame([
        {"value": 75.0, "indicator": "Labor force participation rate"},
        {"value": 78.0, "indicator": "Labor force participation rate"},
    ])
    res_high = rule.apply(spec, scale_type="percentage", df=df_high)
    assert "domain" not in res_high["encoding"]["y"]["scale"]

    # 2. Low-value concentration proportion (max <= 0.25) -> Clamp to [0, 0.25] (Q31 case)
    df_prop = pd.DataFrame([
        {"value": 0.08, "indicator": "Public employment share"},
        {"value": 0.20, "indicator": "Public employment share"},
    ])
    res_prop = rule.apply(spec, scale_type="percentage", df=df_prop)
    assert res_prop["encoding"]["y"]["scale"]["domain"] == [0, 0.25]


def test_small_multiples_broken_line_gap():
    """Verify that LineYearGapStrokeDashRule is applied correctly to concat/composite small multiples specs."""
    from data360.visualization import _apply_post_processing_rules
    import pandas as pd

    # Data for 2 countries (triggers small multiples with multi panels -> concat),
    # with a multi-year gap (2015 to 2018) to trigger the LineYearGapStrokeDashRule.
    rows = [
        {"country": "Argentina", "year": "2015", "value": 10.0, "indicator": "Ind"},
        {"country": "Argentina", "year": "2018", "value": 12.0, "indicator": "Ind"},
        {"country": "Chile", "year": "2015", "value": 20.0, "indicator": "Ind"},
        {"country": "Chile", "year": "2018", "value": 22.0, "indicator": "Ind"},
    ]
    df = pd.DataFrame(rows)

    # Let's mock a StrategyResult that routes to SMALL_MULTIPLES
    from data360.viz_config import StrategyResult, ChartStrategy
    result = StrategyResult(
        strategy=ChartStrategy.SMALL_MULTIPLES,
        reason="test",
        facet_dim="country"
    )

    # Call the visualization spec builder
    spec = build_small_multiples_spec(df, "Test Title", result)

    # Let's verify that the raw build_small_multiples_spec has concat and no local data/strokeDash yet
    assert "concat" in spec
    panel = spec["concat"][0]
    assert "data" not in panel or "values" not in panel["data"]

    # Now let's apply the post-processing rules (as visualization.py does)
    spec_processed = _apply_post_processing_rules(spec, "A", "Value", result, df)

    # Let's inspect the processed spec
    assert "concat" in spec_processed
    for panel in spec_processed["concat"]:
        # The panel could be layered or a direct leaf view depending on zero-line/end-labels requirements
        line_view = None
        if "layer" in panel:
            for layer in panel["layer"]:
                m = layer.get("mark")
                m_type = m.get("type") if isinstance(m, dict) else m
                if m_type == "line":
                    line_view = layer
                    break
        else:
            m = panel.get("mark")
            m_type = m.get("type") if isinstance(m, dict) else m
            if m_type == "line":
                line_view = panel

        assert line_view is not None
        assert "data" in line_view
        assert "values" in line_view["data"]
        assert len(line_view["data"]["values"]) == 2  # exactly 2 gap rows since entire series is a gap
        assert all(r["_d360_ygap"] == 1 for r in line_view["data"]["values"])
        assert "strokeDash" in line_view["encoding"]
        assert "detail" in line_view["encoding"]
        assert line_view["encoding"]["detail"]["field"] == "_d360_lseg"


def test_multi_indicator_broken_line_gap():
    """Verify that LineYearGapStrokeDashRule is applied correctly to vconcat multi-indicator line charts."""
    from data360.visualization import _apply_post_processing_rules
    from data360.viz_config import build_temporal_multi_indicator_spec, StrategyResult, ChartStrategy
    import pandas as pd

    # Data for 2 indicators with a multi-year gap (2015 to 2018)
    rows = [
        {"country": "Argentina", "year": "2015", "Ind1": 10.0, "Ind2": 1000.0},
        {"country": "Argentina", "year": "2018", "Ind1": 12.0, "Ind2": 1100.0},
    ]
    df = pd.DataFrame(rows)

    result = StrategyResult(
        strategy=ChartStrategy.TEMPORAL_MULTI_IND,
        reason="test",
        indicator_cols=["Ind1", "Ind2"]
    )

    # Call the multi-indicator spec builder (generates vconcat spec)
    spec = build_temporal_multi_indicator_spec(df, "Test Title", result)

    assert "vconcat" in spec

    # Apply the post-processing rules (as visualization.py does)
    spec_processed = _apply_post_processing_rules(spec, "A", "Value", result, df)

    assert "vconcat" in spec_processed
    for panel in spec_processed["vconcat"]:
        # Each panel should have layers (since it layered line + point)
        assert "layer" in panel
        line_layer = None
        for layer in panel["layer"]:
            m = layer.get("mark")
            m_type = m.get("type") if isinstance(m, dict) else m
            if m_type == "line":
                line_layer = layer
                break

        assert line_layer is not None
        assert "data" in line_layer
        assert "values" in line_layer["data"]
        assert len(line_layer["data"]["values"]) == 2
        assert all(r["_d360_ygap"] == 1 for r in line_layer["data"]["values"])
        assert "strokeDash" in line_layer["encoding"]
        assert "detail" in line_layer["encoding"]
        assert line_layer["encoding"]["detail"]["field"] == "_d360_lseg"
