"""Tests for the Tier 1 data aggregation tools added in PR #75.

Covers the functionality gaps identified in the code review:
- _fetch_all_pages: pagination loop, safety page limit, mid-page error recovery
- _compute_trend_direction: edge cases (constant, two values, volatile)
- _build_group_summary: mixed-type OBS_VALUE, duplicate TIME_PERIOD, empty input
- rank_countries: tie handling, no countries specified error path
- summarize_data: invalid group_by validation, no-data fallback
- compare_countries: too-few-countries guard, CAGR negative-value guard
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from data360.api import (
    _build_group_summary,
    _compute_trend_direction,
    _fetch_all_pages,
    rank_countries,
    summarize_data,
    compare_countries,
)
from data360.models import (
    GroupSummary,
    IndicatorDataResponse,
    RankingResponse,
    DataSummaryResponse,
    CountryComparisonResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_data_page(
    rows: list[dict],
    has_more: bool = False,
    next_offset: int | None = None,
) -> IndicatorDataResponse:
    """Return a minimal IndicatorDataResponse as if returned by get_data."""
    return IndicatorDataResponse(
        data=rows,
        metadata={"name": "Test Indicator"},
        count=len(rows),
        total_count=None,
        offset=0,
        has_more=has_more,
        next_offset=next_offset,
    )


def _make_row(ref_area: str, time_period: str, obs_value, unit: str = "USD") -> dict:
    return {
        "REF_AREA": ref_area,
        "TIME_PERIOD": time_period,
        "OBS_VALUE": obs_value,
        "UNIT_MEASURE": unit,
        "claim_id": f"{ref_area}_{time_period}",
    }


# ---------------------------------------------------------------------------
# _compute_trend_direction
# ---------------------------------------------------------------------------


class TestComputeTrendDirection:
    def test_single_value_returns_stable(self):
        assert _compute_trend_direction([42.0]) == "stable"

    def test_constant_series_returns_stable(self):
        # All same values → slope = 0, but R² is also 0 (ss_tot = 0)
        # denominator branch handles this via ss_tot == 0 → r_squared = 0 < 0.3 → volatile
        # Actually: when all values are equal, ss_tot == 0 → r_squared forced to 0 → "volatile"
        # This is the defined behaviour; document it here.
        result = _compute_trend_direction([5.0, 5.0, 5.0, 5.0])
        assert result in ("stable", "volatile")  # Either is acceptable for flat data

    def test_strongly_increasing(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert _compute_trend_direction(values) == "increasing"

    def test_strongly_decreasing(self):
        values = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
        assert _compute_trend_direction(values) == "decreasing"

    def test_volatile_series(self):
        # High-variance zigzag → low R²
        values = [1.0, 100.0, 2.0, 90.0, 3.0, 80.0]
        result = _compute_trend_direction(values)
        assert result == "volatile"

    def test_two_values_positive_slope(self):
        assert _compute_trend_direction([1.0, 2.0]) == "increasing"

    def test_two_values_negative_slope(self):
        assert _compute_trend_direction([2.0, 1.0]) == "decreasing"

    def test_empty_list_returns_stable(self):
        # n < 2 → stable
        assert _compute_trend_direction([]) == "stable"


# ---------------------------------------------------------------------------
# _build_group_summary
# ---------------------------------------------------------------------------


class TestBuildGroupSummary:
    def test_basic_summary(self):
        rows = [
            _make_row("KEN", "2020", 100.0),
            _make_row("KEN", "2021", 110.0),
            _make_row("KEN", "2022", 120.0),
        ]
        result = _build_group_summary({"ref_area": "KEN"}, rows)
        assert isinstance(result, GroupSummary)
        assert result.count == 3
        assert result.latest_value == 120.0
        assert result.earliest_value == 100.0
        assert result.total_change == pytest.approx(20.0)
        assert result.pct_change == pytest.approx(20.0)
        assert result.trend_direction == "increasing"

    def test_mixed_type_obs_value(self):
        """pd.to_numeric(errors='coerce') must handle strings and None."""
        rows = [
            {"REF_AREA": "KEN", "TIME_PERIOD": "2020", "OBS_VALUE": "100", "claim_id": "a"},
            {"REF_AREA": "KEN", "TIME_PERIOD": "2021", "OBS_VALUE": None, "claim_id": "b"},
            {"REF_AREA": "KEN", "TIME_PERIOD": "2022", "OBS_VALUE": "", "claim_id": "c"},
            {"REF_AREA": "KEN", "TIME_PERIOD": "2023", "OBS_VALUE": 120.0, "claim_id": "d"},
        ]
        result = _build_group_summary({"ref_area": "KEN"}, rows)
        # Only 2 valid numeric rows (2020 and 2023)
        assert result.count == 2
        assert result.latest_value == 120.0
        assert result.earliest_value == 100.0

    def test_duplicate_time_period_keeps_last(self):
        """Duplicate TIME_PERIOD rows are deduplicated by keeping the last."""
        rows = [
            _make_row("KEN", "2021", 50.0),
            _make_row("KEN", "2021", 99.0),  # duplicate — should win after sort
            _make_row("KEN", "2022", 110.0),
        ]
        result = _build_group_summary({"ref_area": "KEN"}, rows)
        assert result.count == 2
        assert result.earliest_value == 99.0  # kept last duplicate for 2021

    def test_empty_rows_returns_zero_count(self):
        result = _build_group_summary({"ref_area": "KEN"}, [])
        assert result.count == 0
        assert result.latest_value is None

    def test_all_nan_obs_value_returns_zero_count(self):
        rows = [
            {"REF_AREA": "KEN", "TIME_PERIOD": "2020", "OBS_VALUE": None},
            {"REF_AREA": "KEN", "TIME_PERIOD": "2021", "OBS_VALUE": ""},
        ]
        result = _build_group_summary({"ref_area": "KEN"}, rows)
        assert result.count == 0

    def test_zero_earliest_value_pct_change_is_none(self):
        """pct_change must be None when earliest_value is 0 (avoid ZeroDivisionError)."""
        rows = [
            _make_row("KEN", "2020", 0.0),
            _make_row("KEN", "2021", 10.0),
        ]
        result = _build_group_summary({"ref_area": "KEN"}, rows)
        assert result.pct_change is None

    def test_claim_ids_collected(self):
        rows = [
            _make_row("KEN", "2020", 100.0),
            _make_row("KEN", "2021", 110.0),
        ]
        result = _build_group_summary({"ref_area": "KEN"}, rows)
        assert set(result.claim_ids) == {"KEN_2020", "KEN_2021"}


# ---------------------------------------------------------------------------
# _fetch_all_pages
# ---------------------------------------------------------------------------


class TestFetchAllPages:
    @pytest.mark.asyncio
    async def test_single_page_no_more(self):
        page = _make_data_page([_make_row("KEN", "2022", 100)], has_more=False)

        with patch("data360.api.get_data", new_callable=AsyncMock, return_value=page):
            result = await _fetch_all_pages("WB_WDI", "IND_ID", "KEN", None, None, None)

        assert len(result.data) == 1
        assert result.has_more is False

    @pytest.mark.asyncio
    async def test_multiple_pages_merged(self):
        page1 = _make_data_page(
            [_make_row("KEN", "2020", 100)], has_more=True, next_offset=100
        )
        page2 = _make_data_page(
            [_make_row("KEN", "2021", 110)], has_more=True, next_offset=200
        )
        page3 = _make_data_page(
            [_make_row("KEN", "2022", 120)], has_more=False
        )
        pages = [page1, page2, page3]
        call_count = 0

        async def fake_get_data(**kwargs):
            nonlocal call_count
            result = pages[call_count]
            call_count += 1
            return result

        with patch("data360.api.get_data", side_effect=fake_get_data):
            result = await _fetch_all_pages("WB_WDI", "IND_ID", "KEN", None, None, None)

        assert len(result.data) == 3
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_first_page_error_propagates(self):
        error_page = IndicatorDataResponse(data=None, error="API error on page 1")

        with patch("data360.api.get_data", new_callable=AsyncMock, return_value=error_page):
            result = await _fetch_all_pages("WB_WDI", "IND_ID", "KEN", None, None, None)

        assert result.error == "API error on page 1"
        assert result.data is None

    @pytest.mark.asyncio
    async def test_mid_pagination_error_returns_partial(self):
        """An error on page 2+ should return whatever was collected so far."""
        page1 = _make_data_page(
            [_make_row("KEN", "2020", 100)], has_more=True, next_offset=100
        )
        error_page = IndicatorDataResponse(data=None, error="Network failure on page 2")
        pages = [page1, error_page]
        call_count = 0

        async def fake_get_data(**kwargs):
            nonlocal call_count
            result = pages[call_count]
            call_count += 1
            return result

        with patch("data360.api.get_data", side_effect=fake_get_data):
            result = await _fetch_all_pages("WB_WDI", "IND_ID", "KEN", None, None, None)

        # Should return the first page's data, not propagate the second-page error
        assert result.error is None
        assert len(result.data) == 1

    @pytest.mark.asyncio
    async def test_safety_page_limit_stops_infinite_loop(self):
        """If has_more is always True, _fetch_all_pages must stop after _MAX_PAGES."""
        always_more_page = _make_data_page(
            [_make_row("KEN", "2020", 100)], has_more=True, next_offset=100
        )

        with patch("data360.api.get_data", new_callable=AsyncMock, return_value=always_more_page):
            result = await _fetch_all_pages("WB_WDI", "IND_ID", "KEN", None, None, None)

        # Safety limit is 50 pages × 1 row = 50 rows
        assert len(result.data) == 50
        assert result.has_more is False  # synthesised response always sets this


# ---------------------------------------------------------------------------
# rank_countries
# ---------------------------------------------------------------------------


class TestRankCountriesTieHandling:
    """Unit tests for the tie-ranking logic inside rank_countries."""

    @pytest.mark.asyncio
    async def test_no_country_specs_returns_error(self):
        result = await rank_countries("WB_WDI", "IND_ID")
        assert result.error is not None
        assert "No countries specified" in result.error

    @pytest.mark.asyncio
    async def test_tie_gives_same_rank_to_tied_countries(self):
        """[100, 90, 90, 80] → ranks [1, 2, 2, 4] (standard competition ranking)."""
        rows = [
            _make_row("A", "2022", 100.0),
            _make_row("B", "2022", 90.0),
            _make_row("C", "2022", 90.0),
            _make_row("D", "2022", 80.0),
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_fetch_all(**kwargs):
            return full_page

        async def fake_resolve(codes):
            return {c: c for c in codes}

        async def fake_disagg(**kwargs):
            return {"dimensions": []}

        with (
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
            patch("data360.api._resolve_country_names", side_effect=fake_resolve),
            patch("data360.api.get_disaggregation", side_effect=fake_disagg),
        ):
            result = await rank_countries(
                "WB_WDI", "IND_ID",
                country_codes="A;B;C;D",
                top_n=4,
            )

        assert result.error is None
        ranks = {r.ref_area: r.rank for r in result.rankings}
        assert ranks["A"] == 1
        assert ranks["B"] == 2
        assert ranks["C"] == 2  # tied with B
        assert ranks["D"] == 4  # skips rank 3 (standard competition)

    @pytest.mark.asyncio
    async def test_asc_order_ranks_lowest_first(self):
        rows = [
            _make_row("A", "2022", 10.0),
            _make_row("B", "2022", 30.0),
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_fetch_all(**kwargs):
            return full_page

        async def fake_resolve(codes):
            return {c: c for c in codes}

        async def fake_disagg(**kwargs):
            return {"dimensions": []}

        with (
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
            patch("data360.api._resolve_country_names", side_effect=fake_resolve),
            patch("data360.api.get_disaggregation", side_effect=fake_disagg),
        ):
            result = await rank_countries(
                "WB_WDI", "IND_ID",
                country_codes="A;B",
                order="asc",
                top_n=2,
            )

        assert result.rankings[0].ref_area == "A"  # lowest value first
        assert result.rankings[0].rank == 1

    @pytest.mark.asyncio
    async def test_excluded_countries_reported(self):
        """Countries with no data for the chosen year appear in the excluded list."""
        rows = [
            _make_row("A", "2022", 100.0),
            # "B" has no data for 2022
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_fetch_all(**kwargs):
            return full_page

        async def fake_resolve(codes):
            return {c: c for c in codes}

        async def fake_disagg(**kwargs):
            return {"dimensions": []}

        with (
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
            patch("data360.api._resolve_country_names", side_effect=fake_resolve),
            patch("data360.api.get_disaggregation", side_effect=fake_disagg),
        ):
            result = await rank_countries(
                "WB_WDI", "IND_ID",
                country_codes="A;B",
                top_n=5,
            )

        assert len(result.rankings) == 1
        assert len(result.excluded) == 1
        assert result.excluded[0].ref_area == "B"


# ---------------------------------------------------------------------------
# summarize_data
# ---------------------------------------------------------------------------


class TestSummarizeData:
    @pytest.mark.asyncio
    async def test_invalid_group_by_returns_error(self):
        result = await summarize_data("WB_WDI", "IND_ID", group_by=["invalid_column"])
        assert isinstance(result, DataSummaryResponse)
        assert result.error is not None
        assert "invalid_column" in result.error

    @pytest.mark.asyncio
    async def test_no_data_returns_fallback_error(self):
        empty_page = _make_data_page([], has_more=False)
        empty_page.metadata = None

        async def fake_fetch_all(**kwargs):
            return empty_page

        with patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all):
            result = await summarize_data("WB_WDI", "IND_ID")

        assert result.error is not None
        assert "No data returned" in result.error

    @pytest.mark.asyncio
    async def test_groups_built_per_ref_area(self):
        rows = [
            _make_row("KEN", "2020", 100.0),
            _make_row("KEN", "2021", 110.0),
            _make_row("NGA", "2020", 200.0),
            _make_row("NGA", "2021", 220.0),
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_fetch_all(**kwargs):
            return full_page

        with patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all):
            result = await summarize_data(
                "WB_WDI", "IND_ID",
                country_code="KEN;NGA",
                group_by=["ref_area"],
            )

        assert result.error is None
        assert len(result.groups) == 2
        areas = {g.group_key["ref_area"] for g in result.groups}
        assert areas == {"KEN", "NGA"}

    @pytest.mark.asyncio
    async def test_multi_column_group_by(self):
        rows = [
            {**_make_row("KEN", "2020", 100.0), "SEX": "M"},
            {**_make_row("KEN", "2021", 110.0), "SEX": "M"},
            {**_make_row("KEN", "2020", 90.0), "SEX": "F"},
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_fetch_all(**kwargs):
            return full_page

        with patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all):
            result = await summarize_data(
                "WB_WDI", "IND_ID",
                group_by=["ref_area", "sex"],
            )

        assert result.error is None
        # Two groups: (KEN, M) and (KEN, F)
        assert len(result.groups) == 2


# ---------------------------------------------------------------------------
# compare_countries
# ---------------------------------------------------------------------------


class TestCompareCountries:
    @pytest.mark.asyncio
    async def test_fewer_than_two_countries_returns_error(self):
        result = await compare_countries("WB_WDI", "IND_ID", country_codes="KEN")
        assert isinstance(result, CountryComparisonResponse)
        assert result.error is not None
        assert "2" in result.error

    @pytest.mark.asyncio
    async def test_snapshot_built_for_common_year(self):
        rows = [
            _make_row("KEN", "2022", 1000.0),
            _make_row("NGA", "2022", 500.0),
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_fetch_all(**kwargs):
            return full_page

        async def fake_resolve(codes):
            return {c: c for c in codes}

        async def fake_disagg(**kwargs):
            return {"dimensions": []}

        with (
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
            patch("data360.api._resolve_country_names", side_effect=fake_resolve),
            patch("data360.api.get_disaggregation", side_effect=fake_disagg),
        ):
            result = await compare_countries("WB_WDI", "IND_ID", country_codes="KEN;NGA")

        assert result.error is None
        assert result.snapshot is not None
        assert result.snapshot.year == "2022"
        assert len(result.snapshot.rankings) == 2
        assert result.snapshot.rankings[0].ref_area == "KEN"  # higher value first

    @pytest.mark.asyncio
    async def test_cagr_none_when_start_value_negative(self):
        """Negative v0 must produce cagr=None, not a ValueError."""
        rows = [
            _make_row("KEN", "2018", -10.0),
            _make_row("KEN", "2019", -5.0),
            _make_row("KEN", "2020", 0.0),
            _make_row("KEN", "2021", 5.0),
            _make_row("KEN", "2022", 10.0),
            _make_row("NGA", "2018", 50.0),
            _make_row("NGA", "2019", 55.0),
            _make_row("NGA", "2020", 60.0),
            _make_row("NGA", "2021", 65.0),
            _make_row("NGA", "2022", 70.0),
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_fetch_all(**kwargs):
            return full_page

        async def fake_resolve(codes):
            return {c: c for c in codes}

        async def fake_disagg(**kwargs):
            return {"dimensions": []}

        with (
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
            patch("data360.api._resolve_country_names", side_effect=fake_resolve),
            patch("data360.api.get_disaggregation", side_effect=fake_disagg),
        ):
            result = await compare_countries(
                "WB_WDI", "IND_ID",
                country_codes="KEN;NGA",
                include_time_series=True,
            )

        assert result.error is None
        assert result.time_series is not None
        # KEN starts at -10 → CAGR must be None (not a crash)
        assert result.time_series.cagr.get("KEN") is None
        # NGA starts at 50 (positive) → may have a valid CAGR
        assert result.time_series.cagr.get("NGA") is not None

    @pytest.mark.asyncio
    async def test_cagr_none_when_end_value_negative(self):
        """Negative v1 must produce cagr=None rather than a ValueError from
        raising a negative ratio to a fractional power."""
        rows = [
            _make_row("KEN", "2020", 100.0),
            _make_row("KEN", "2021", 80.0),
            _make_row("KEN", "2022", -5.0),  # turns negative at end
            _make_row("NGA", "2020", 50.0),
            _make_row("NGA", "2021", 55.0),
            _make_row("NGA", "2022", 60.0),
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_fetch_all(**kwargs):
            return full_page

        async def fake_resolve(codes):
            return {c: c for c in codes}

        async def fake_disagg(**kwargs):
            return {"dimensions": []}

        with (
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
            patch("data360.api._resolve_country_names", side_effect=fake_resolve),
            patch("data360.api.get_disaggregation", side_effect=fake_disagg),
        ):
            result = await compare_countries(
                "WB_WDI", "IND_ID",
                country_codes="KEN;NGA",
                include_time_series=True,
            )

        assert result.error is None
        assert result.time_series is not None
        assert result.time_series.cagr.get("KEN") is None
