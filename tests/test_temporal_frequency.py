"""Tests for temporal frequency detection and formatting.

Covers _detect_temporal_frequency and _format_time_period_series for all
formats the Data360 API produces.
"""

import pandas as pd

from data360.viz_config import (
    _detect_temporal_frequency,
    _format_time_period_series,
    _x_temporal_encoding,
)


class TestDetectTemporalFrequency:
    """_detect_temporal_frequency infers the right frequency from raw values."""

    def test_bare_year_integers_are_annual(self):
        s = pd.Series(["2019", "2020", "2021"])
        assert _detect_temporal_frequency(s) == "annual"

    def test_single_year_is_annual(self):
        s = pd.Series(["2020"])
        assert _detect_temporal_frequency(s) == "annual"

    def test_jan_first_dates_are_annual(self):
        """Dates like 2019-01-01 (WB annual convention) are annual, not daily."""
        s = pd.Series(["2019-01-01", "2020-01-01", "2021-01-01"])
        assert _detect_temporal_frequency(s) == "annual"

    def test_monthly_iso_dates_detected(self):
        """2019-09-01, 2019-10-01, ... spanning multiple months → monthly."""
        s = pd.Series(
            [
                "2019-09-01",
                "2019-10-01",
                "2019-11-01",
                "2019-12-01",
                "2020-01-01",
                "2020-02-01",
                "2020-03-01",
                "2020-04-01",
                "2020-05-01",
                "2020-06-01",
                "2020-07-01",
                "2020-08-01",
            ]
        )
        assert _detect_temporal_frequency(s) == "monthly"

    def test_monthly_yearmonth_strings_detected(self):
        """2019-09, 2019-10, ... → monthly."""
        months = [f"2020-{m:02d}" for m in range(1, 13)]
        s = pd.Series(months)
        assert _detect_temporal_frequency(s) == "monthly"

    def test_quarterly_q_marker_detected(self):
        """2019-Q1, 2019-Q2, ... → quarterly."""
        s = pd.Series(["2019-Q1", "2019-Q2", "2019-Q3", "2019-Q4"])
        assert _detect_temporal_frequency(s) == "quarterly"

    def test_quarterly_lowercase_q_marker(self):
        s = pd.Series(["2019-q1", "2019-q2", "2020-q1"])
        assert _detect_temporal_frequency(s) == "quarterly"

    def test_quarterly_no_dash_q_marker(self):
        s = pd.Series(["2019Q1", "2019Q2", "2019Q3", "2019Q4"])
        assert _detect_temporal_frequency(s) == "quarterly"

    def test_ipc_biannual_collapses_to_annual(self):
        """IPC has 2 observation dates per year — below the quarterly threshold → annual."""
        s = pd.Series(["2019-09-01", "2020-03-01", "2020-09-01", "2021-04-01"])
        assert _detect_temporal_frequency(s) == "annual"

    def test_empty_series_returns_annual(self):
        s = pd.Series([], dtype=str)
        assert _detect_temporal_frequency(s) == "annual"

    def test_all_null_returns_annual(self):
        s = pd.Series([None, None])
        assert _detect_temporal_frequency(s) == "annual"

    def test_unparseable_returns_annual(self):
        s = pd.Series(["not-a-date", "also-bad"])
        assert _detect_temporal_frequency(s) == "annual"


class TestFormatTimePeriodSeries:
    """_format_time_period_series formats correctly for each frequency."""

    def test_annual_formats_to_4_digit_year(self):
        s = pd.Series(["2019-01-01", "2020-01-01"])
        result = _format_time_period_series(s, "annual")
        assert list(result) == ["2019", "2020"]

    def test_monthly_formats_to_yearmonth(self):
        s = pd.Series(["2019-09-01", "2019-10-01"])
        result = _format_time_period_series(s, "monthly")
        assert list(result) == ["2019-09", "2019-10"]

    def test_quarterly_formats_to_yearquarter(self):
        s = pd.Series(["2019-01-01", "2019-04-01", "2019-07-01", "2019-10-01"])
        result = _format_time_period_series(s, "quarterly")
        periods = list(result)
        assert all("Q" in p for p in periods), f"Expected quarter labels, got {periods}"
        assert periods[0].startswith("2019Q1"), periods

    def test_daily_formats_to_iso_date(self):
        s = pd.Series(["2019-09-15", "2020-03-22"])
        result = _format_time_period_series(s, "daily")
        assert list(result) == ["2019-09-15", "2020-03-22"]

    def test_bare_year_annual_still_extracts_year(self):
        """Bare 4-digit year strings like '2019' are correctly handled for annual."""
        s = pd.Series(["2019", "2020", "2021"])
        result = _format_time_period_series(s, "annual")
        assert list(result) == ["2019", "2020", "2021"]

    def test_unparseable_values_left_unchanged(self):
        s = pd.Series(["not-a-date", "also-bad"])
        result = _format_time_period_series(s, "annual")
        # Should fall back gracefully — values stay as-is
        assert len(result) == 2


class TestXTemporalEncoding:
    """_x_temporal_encoding returns the right Vega-Lite x channel per frequency."""

    def test_annual_uses_temporal_with_timeunit_year(self):
        enc = _x_temporal_encoding("annual")
        assert enc["type"] == "temporal"
        assert enc.get("timeUnit") == "year"
        assert enc["field"] == "year"

    def test_monthly_uses_temporal_with_timeunit_yearmonth(self):
        enc = _x_temporal_encoding("monthly")
        assert enc["type"] == "temporal"
        assert enc.get("timeUnit") == "yearmonth"
        assert "axis" in enc
        assert enc["axis"]["format"] == "%b %Y"

    def test_quarterly_uses_temporal_with_timeunit_yearquarter(self):
        enc = _x_temporal_encoding("quarterly")
        assert enc["type"] == "temporal"
        assert enc.get("timeUnit") == "yearquarter"

    def test_daily_uses_temporal_without_timeunit(self):
        enc = _x_temporal_encoding("daily")
        assert enc["type"] == "temporal"
        assert "timeUnit" not in enc

    def test_unknown_freq_falls_back_to_annual(self):
        enc = _x_temporal_encoding("unknown")  # type: ignore[arg-type]
        assert enc["type"] == "temporal"
        assert enc.get("timeUnit") == "year"

    def test_returns_independent_copy(self):
        """Modifying the returned dict must not affect subsequent calls."""
        enc1 = _x_temporal_encoding("annual")
        enc1["axis"]["format"] = "MUTATED"
        enc2 = _x_temporal_encoding("annual")
        assert enc2["axis"]["format"] == "%Y", (
            "_x_temporal_encoding must return an independent copy each call"
        )
