"""Bar / ordinal year axis: confirm data-prep and post-processing avoid raw epoch ms labels."""

from data360.viz_config import (
    DiscreteYearBarXAxisRule,
    OrdinalToTemporalRule,
    TemporalAxisCleanupRule,
    _first_non_null_dataset_value,
    _year_ordinal_value_needs_temporal_encoding,
    get_data_preparation_action,
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
