"""Bar / ordinal year axis: confirm data-prep and post-processing avoid raw epoch ms labels."""

import pandas as pd

from data360.viz_config import (
    DiscreteYearBarXAxisRule,
    LineYearGapStrokeDashRule,
    OrdinalToTemporalRule,
    TemporalAxisCleanupRule,
    _first_non_null_dataset_value,
    _year_ordinal_value_needs_temporal_encoding,
    fill_missing_calendar_years_annual,
    frequency_allows_annual_year_gap_fill,
    get_data_preparation_action,
    wb_altair_config,
)

# 2014-01-01T00:00:00.000Z as milliseconds (example Altair dataset serialization)
YEAR_2014_JAN1_UTC_MS = 1_388_534_400_000


def test_get_data_preparation_action_bar_unknown_frequency_uses_year_strings() -> None:
    assert get_data_preparation_action("bar", None) == "year_strings"
    assert get_data_preparation_action("bar", "A") == "year_strings"


def test_get_data_preparation_action_line_unknown_frequency_stays_datetime() -> None:
    assert get_data_preparation_action("line", None) == "datetime"


def test_year_ordinal_value_needs_temporal_encoding() -> None:
    assert _year_ordinal_value_needs_temporal_encoding(YEAR_2014_JAN1_UTC_MS) is True
    assert _year_ordinal_value_needs_temporal_encoding("2014-01-01T00:00:00") is True
    assert _year_ordinal_value_needs_temporal_encoding("2014") is False
    assert _year_ordinal_value_needs_temporal_encoding(2014) is False


def test_first_non_null_dataset_value() -> None:
    rows = [{"year": None, "v": 1}, {"year": YEAR_2014_JAN1_UTC_MS, "v": 2}]
    assert _first_non_null_dataset_value(rows, "year") == YEAR_2014_JAN1_UTC_MS


def test_ordinal_to_temporal_rule_bar_ms_dataset_updates_encoding() -> None:
    rule = OrdinalToTemporalRule()
    spec = {
        "mark": {"type": "bar"},
        "data": {"name": "ds0"},
        "datasets": {
            "ds0": [
                {"year": YEAR_2014_JAN1_UTC_MS, "value": 41.7, "country": "Brazil"},
            ]
        },
        "encoding": {
            "x": {"field": "year", "type": "ordinal"},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    out = rule.apply(spec)
    assert out["encoding"]["x"]["type"] == "temporal"


def test_temporal_axis_cleanup_applies_to_bar_with_temporal_x() -> None:
    rule = TemporalAxisCleanupRule()
    spec = {
        "mark": {"type": "bar"},
        "encoding": {
            "x": {"field": "year", "type": "temporal", "axis": {}},
        },
    }
    assert rule.should_apply(spec) is True
    out = rule.apply(spec)
    assert out["encoding"]["x"]["axis"]["format"] == "%Y"


def test_discrete_year_bar_x_axis_sets_label_angle() -> None:
    rule = DiscreteYearBarXAxisRule()
    spec = {
        "mark": {"type": "bar"},
        "encoding": {
            "x": {"field": "year", "type": "ordinal"},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    assert rule.should_apply(spec) is True
    out = rule.apply(spec)
    assert out["encoding"]["x"]["axis"]["labelAngle"] == 0


def test_discrete_year_bar_x_axis_skips_temporal_x() -> None:
    rule = DiscreteYearBarXAxisRule()
    spec = {
        "mark": {"type": "bar"},
        "encoding": {"x": {"field": "year", "type": "temporal", "axis": {}}},
    }
    assert rule.should_apply(spec) is False


def test_wb_altair_config_has_no_mark_invalid_override() -> None:
    cfg = wb_altair_config()
    assert "invalid" not in cfg.get("mark", {})


def test_contiguous_year_domain_rule_sets_ordinal_domain() -> None:
    from data360.viz_config import ContiguousCalendarYearDomainRule

    rule = ContiguousCalendarYearDomainRule()
    spec = {
        "mark": {"type": "bar"},
        "data": {
            "values": [
                {"year": "2007", "value": 10.0, "country": "Brazil"},
                {"year": "2009", "value": 9.0, "country": "Brazil"},
            ]
        },
        "encoding": {
            "x": {"field": "year", "type": "ordinal"},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    out = rule.apply(spec, data_frequency="A")
    assert out["encoding"]["x"]["scale"]["domain"] == ["2007", "2008", "2009"]
    assert out["encoding"]["x"]["sort"] == ["2007", "2008", "2009"]


def test_frequency_allows_annual_year_gap_fill() -> None:
    assert frequency_allows_annual_year_gap_fill(None) is True
    assert frequency_allows_annual_year_gap_fill("A") is True
    assert frequency_allows_annual_year_gap_fill("M") is False
    assert frequency_allows_annual_year_gap_fill("Q") is False


def test_fill_missing_calendar_years_inserts_gap_year() -> None:
    df = pd.DataFrame(
        {
            "year": ["2007", "2008", "2009", "2011"],
            "value": [40.0, 39.0, 38.0, 36.0],
            "country": ["Brazil"] * 4,
        }
    )
    out = fill_missing_calendar_years_annual(df, "A")
    assert len(out) == 5
    years = sorted(int(str(y)[:4]) for y in out["year"])
    assert years == [2007, 2008, 2009, 2010, 2011]
    y2010 = out[out["year"].astype(str).str.startswith("2010")]
    assert len(y2010) == 1
    assert y2010["value"].isna().all()


def test_fill_missing_calendar_years_skips_duplicate_year_rows() -> None:
    df = pd.DataFrame(
        {"year": ["2007", "2007"], "value": [1.0, 2.0], "country": ["x", "x"]}
    )
    out = fill_missing_calendar_years_annual(df, "A")
    assert len(out) == len(df)


def test_line_year_gap_stroke_dash_splits_when_calendar_gap() -> None:
    rule = LineYearGapStrokeDashRule()
    spec = {
        "data": {
            "values": [
                {"year": "2020-01-01", "country": "A", "value": 1.0},
                {"year": "2021-01-01", "country": "A", "value": 2.0},
                {"year": "2024-01-01", "country": "A", "value": 3.0},
            ]
        },
        "mark": {"type": "line"},
        "encoding": {
            "x": {"field": "year", "type": "temporal"},
            "y": {"field": "value", "type": "quantitative"},
            "color": {"field": "country", "type": "nominal"},
        },
    }
    out = rule.apply(spec)
    assert len(out["data"]["values"]) == 4
    assert out["encoding"]["detail"]["field"] == "_d360_lseg"
    assert "strokeDash" in out["encoding"]
    cond = out["encoding"]["strokeDash"]["condition"]
    assert cond["value"] == [6, 4]


def test_line_year_gap_stroke_dash_applies_when_x_has_annual_timeunit() -> None:
    """WDI annual pipeline sets ``timeUnit: \"year\"`` on x before this rule — must still dash gaps."""
    rule = LineYearGapStrokeDashRule()
    spec = {
        "data": {
            "values": [
                {"year": "2009-01-01", "value": 8.4},
                {"year": "2011-01-01", "value": 7.1},
            ]
        },
        "mark": {"type": "line"},
        "encoding": {
            "x": {"field": "year", "type": "temporal", "timeUnit": "year"},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    out = rule.apply(spec)
    assert out["encoding"]["detail"]["field"] == "_d360_lseg"
    assert len(out["data"]["values"]) == 2


def test_line_year_gap_stroke_dash_skips_monthly_timeunit() -> None:
    rule = LineYearGapStrokeDashRule()
    spec = {
        "data": {
            "values": [
                {"year": "2009-01-01", "value": 8.4},
                {"year": "2011-01-01", "value": 7.1},
            ]
        },
        "mark": {"type": "line"},
        "encoding": {
            "x": {"field": "year", "type": "temporal", "timeUnit": "yearmonth"},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    out = rule.apply(spec)
    assert "detail" not in out["encoding"]
    assert len(out["data"]["values"]) == 2


def test_line_year_gap_stroke_dash_skips_monthly_timeunit() -> None:
    rule = LineYearGapStrokeDashRule()
    spec = {
        "data": {
            "values": [
                {"year": "2009-01-01", "value": 8.4},
                {"year": "2011-01-01", "value": 7.1},
            ]
        },
        "mark": {"type": "line"},
        "encoding": {
            "x": {"field": "year", "type": "temporal", "timeUnit": "yearmonth"},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    out = rule.apply(spec)
    assert "detail" not in out["encoding"]
    assert len(out["data"]["values"]) == 2


def test_line_year_gap_facet_with_inner_layer_reads_outer_data() -> None:
    rule = LineYearGapStrokeDashRule()
    spec = {
        "data": {
            "values": [
                {"country": "Brazil", "year": "2009-01-01", "value": 8.4},
                {"country": "Brazil", "year": "2011-01-01", "value": 7.1},
            ]
        },
        "facet": {"field": "country", "type": "nominal"},
        "spec": {
            "layer": [
                {
                    "mark": {"type": "line"},
                    "encoding": {
                        "x": {"field": "year", "type": "temporal"},
                        "y": {"field": "value", "type": "quantitative"},
                    },
                },
                {
                    "mark": {"type": "point"},
                    "encoding": {
                        "x": {"field": "year", "type": "temporal"},
                        "y": {"field": "value", "type": "quantitative"},
                    },
                },
            ]
        },
    }
    out = rule.apply(spec)
    line0 = out["spec"]["layer"][0]
    assert line0["encoding"]["detail"]["field"] == "_d360_lseg"
    assert len(out["data"]["values"]) == 2


def test_line_year_gap_stroke_dash_skips_consecutive_years() -> None:
    rule = LineYearGapStrokeDashRule()
    spec = {
        "data": {
            "values": [
                {"year": "2020-01-01", "value": 1.0},
                {"year": "2021-01-01", "value": 2.0},
            ]
        },
        "mark": {"type": "line"},
        "encoding": {
            "x": {"field": "year", "type": "temporal"},
            "y": {"field": "value", "type": "quantitative"},
        },
    }
    out = rule.apply(spec)
    assert len(out["data"]["values"]) == 2
    assert "detail" not in out["encoding"]


def test_line_year_gap_stroke_dash_respects_facet_field() -> None:
    """Each facet series is split separately (no merging countries into one line)."""
    rule = LineYearGapStrokeDashRule()
    spec = {
        "data": {
            "values": [
                {"country": "A", "year": "2020-01-01", "value": 1.0},
                {"country": "A", "year": "2024-01-01", "value": 2.0},
                {"country": "B", "year": "2020-01-01", "value": 3.0},
                {"country": "B", "year": "2021-01-01", "value": 4.0},
            ]
        },
        "facet": {"field": "country", "type": "nominal"},
        "spec": {
            "mark": {"type": "line"},
            "encoding": {
                "x": {"field": "year", "type": "temporal"},
                "y": {"field": "value", "type": "quantitative"},
            },
        },
    }
    out = rule.apply(spec)
    assert len(out["data"]["values"]) == 4
    assert out["spec"]["encoding"]["detail"]["field"] == "_d360_lseg"
