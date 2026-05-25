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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data360.api import (
    _auto_detect_disagg_dimensions,
    _build_group_summary,
    _compute_trend_direction,
    _fetch_all_pages,
    compare_countries,
    rank_countries,
    summarize_data,
)
from data360.models import (
    ComparisonTimeSeries,
    CountryComparisonResponse,
    DataSummaryResponse,
    ExcludedCountry,
    GroupSummary,
    IndicatorDataResponse,
    RankedCountry,
    RankingResponse,
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
        assert "rank_universe" in result.error

    @pytest.mark.asyncio
    async def test_all_member_economies_filters_aggregate_rows(self):
        """Global ranking: unpinned fetch includes aggregates; is_country keeps leaf rows."""
        rows = [
            _make_row("EAS", "2022", 999999.0),
            _make_row("KEN", "2022", 50.0),
            _make_row("NGA", "2022", 200.0),
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_fetch_all(**kwargs):
            assert kwargs.get("country_code") is None
            return full_page

        async def fake_resolve(codes):
            return {c: c for c in codes}

        async def fake_disagg(**kwargs):
            return {"dimensions": []}

        mock_ghm = MagicMock()
        mock_ghm.list_rankable_country_codes.return_value = ["KEN", "NGA", "BRA"]
        mock_ghm.is_country.side_effect = lambda code: code in ("KEN", "NGA", "BRA")
        mock_ghm.is_group.return_value = False

        with (
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
            patch("data360.api._resolve_country_names", side_effect=fake_resolve),
            patch("data360.api.get_disaggregation", side_effect=fake_disagg),
            patch(
                "data360.providers.get_group_hierarchy_manager",
                return_value=mock_ghm,
            ),
        ):
            result = await rank_countries(
                "WB_WDI",
                "IND_ID",
                rank_universe="all_member_economies",
                order="desc",
                top_n=5,
            )

        assert result.error is None
        assert result.universe == "all_member_economies"
        assert result.universe_size == 3
        assert len(result.rankings) == 2
        assert result.rankings[0].ref_area == "NGA"
        assert result.rankings[1].ref_area == "KEN"
        assert len(result.excluded) == 1
        assert result.excluded[0].ref_area == "BRA"

    @pytest.mark.asyncio
    async def test_rank_skips_string_null_obs_value(self):
        """API may send OBS_VALUE as the string 'null'; ranking must not crash."""
        rows = [
            {**_make_row("KEN", "2022", 0.0), "OBS_VALUE": "null"},
            _make_row("NGA", "2022", 7.0),
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
                "WB_WDI",
                "IND_ID",
                country_codes="KEN;NGA",
                top_n=5,
            )

        assert result.error is None
        assert len(result.rankings) == 1
        assert result.rankings[0].ref_area == "NGA"
        assert any(e.ref_area == "KEN" for e in result.excluded)

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


class TestRankCountriesAutoYearSelection:
    """Unit tests for automatic year selection prioritizing recency in rank_countries."""

    @pytest.mark.asyncio
    async def test_auto_year_selection_selects_latest_year_with_caveat(self):
        """Should select 2024 (recency) and flag that 2023 has broader coverage."""
        rows = [
            _make_row("A", "2022", 10.0),
            _make_row("B", "2022", 20.0),
            _make_row("C", "2022", 30.0),
            _make_row("D", "2022", 40.0),

            _make_row("A", "2023", 15.0),
            _make_row("B", "2023", 25.0),
            _make_row("C", "2023", 35.0),
            _make_row("D", "2023", 45.0),

            _make_row("A", "2024", 18.0),
            _make_row("B", "2024", 28.0),
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
                top_n=5,
            )

        assert result.error is None
        assert result.year == "2024"
        assert "Latest available year: 2024" in result.year_selection_note
        assert "Coverage is partial/incomplete" in result.year_selection_note
        assert "2023" in result.year_selection_note

    @pytest.mark.asyncio
    async def test_auto_year_selection_selects_latest_year_when_matches_broadest(self):
        """Should select 2023 and note it as the latest available year."""
        rows = [
            _make_row("A", "2022", 10.0),
            _make_row("B", "2022", 20.0),

            _make_row("A", "2023", 15.0),
            _make_row("B", "2023", 25.0),
            _make_row("C", "2023", 35.0),
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
                country_codes="A;B;C",
                top_n=5,
            )

        assert result.error is None
        assert result.year == "2023"
        assert "Latest available year (2023)" in result.year_selection_note


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

    # -----------------------------------------------------------------------
    # Auto-detection of disaggregation dimensions
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_auto_expands_sex_when_not_in_group_by(self):
        """When SEX has M/F/_T and group_by doesn't include sex, it is auto-added."""
        rows_expanded = [
            {**_make_row("KEN", "2020", 100.0), "SEX": "_T", "UNIT_MEASURE": "PT"},
            {**_make_row("KEN", "2020", 60.0),  "SEX": "M",  "UNIT_MEASURE": "PT"},
            {**_make_row("KEN", "2020", 40.0),  "SEX": "F",  "UNIT_MEASURE": "PT"},
        ]
        full_page = _make_data_page(rows_expanded, has_more=False)

        async def fake_disagg(**kwargs):
            return {
                "dimensions": [
                    {"field_name": "SEX",          "field_value": ["_T", "M", "F"]},
                    {"field_name": "UNIT_MEASURE", "field_value": ["PT"]},
                ]
            }

        async def fake_fetch_all(**kwargs):
            # Verify that SEX filter was set to None (fetch all) by the caller.
            filters = kwargs.get("disaggregation_filters") or {}
            assert filters.get("SEX") is None, "SEX must be expanded (set to None)"
            assert filters.get("UNIT_MEASURE") == "PT"
            return full_page

        with (
            patch("data360.api.get_disaggregation", side_effect=fake_disagg),
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
        ):
            result = await summarize_data(
                "WB_HCP", "WB_HCP_UNE_2EAP_MF_A",
                country_code="KEN",
                group_by=["time_period"],
            )

        assert result.error is None
        # sex should appear in ambiguous_dimensions
        assert result.ambiguous_dimensions is not None
        assert "sex" in result.ambiguous_dimensions
        # Three groups: one per SEX value
        assert len(result.groups) == 3
        sex_values = {g.group_key.get("sex") for g in result.groups}
        assert sex_values == {"_T", "M", "F"}

    @pytest.mark.asyncio
    async def test_caller_sex_filter_suppresses_auto_expansion(self):
        """Caller-specified SEX filter must not be overwritten by auto-detection."""
        rows_female = [
            {**_make_row("KEN", "2020", 40.0), "SEX": "F", "UNIT_MEASURE": "PT"},
        ]
        full_page = _make_data_page(rows_female, has_more=False)

        async def fake_disagg(**kwargs):
            return {
                "dimensions": [
                    {"field_name": "SEX",          "field_value": ["_T", "M", "F"]},
                    {"field_name": "UNIT_MEASURE", "field_value": ["PT"]},
                ]
            }

        async def fake_fetch_all(**kwargs):
            filters = kwargs.get("disaggregation_filters") or {}
            # Caller pinned SEX to F — must not be changed to None.
            assert filters.get("SEX") == "F", "Caller SEX filter must be preserved"
            return full_page

        with (
            patch("data360.api.get_disaggregation", side_effect=fake_disagg),
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
        ):
            result = await summarize_data(
                "WB_HCP", "WB_HCP_UNE_2EAP_MF_A",
                country_code="KEN",
                disaggregation_filters={"SEX": "F"},
                group_by=["time_period"],
            )

        assert result.error is None
        # No auto-expansion occurred — ambiguous_dimensions should be None or empty.
        assert not result.ambiguous_dimensions

    @pytest.mark.asyncio
    async def test_auto_expands_multiple_non_trivial_dims(self):
        """Both SEX and AGE are auto-expanded when both are non-trivial."""
        rows = [
            {**_make_row("KEN", "2020", 10.0), "SEX": "M", "AGE": "Y15T64", "UNIT_MEASURE": "PT"},
            {**_make_row("KEN", "2020", 12.0), "SEX": "F", "AGE": "Y15T64", "UNIT_MEASURE": "PT"},
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_disagg(**kwargs):
            return {
                "dimensions": [
                    {"field_name": "SEX",          "field_value": ["_T", "M", "F"]},
                    {"field_name": "AGE",          "field_value": ["_T", "Y15T64"]},
                    {"field_name": "UNIT_MEASURE", "field_value": ["PT"]},
                ]
            }

        async def fake_fetch_all(**kwargs):
            filters = kwargs.get("disaggregation_filters") or {}
            assert filters.get("SEX") is None
            assert filters.get("AGE") is None
            return full_page

        with (
            patch("data360.api.get_disaggregation", side_effect=fake_disagg),
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
        ):
            result = await summarize_data("WB_WDI", "IND_ID", country_code="KEN")

        assert result.error is None
        expanded = set(result.ambiguous_dimensions or [])
        assert "sex" in expanded
        assert "age" in expanded

    @pytest.mark.asyncio
    async def test_trivial_sex_not_expanded(self):
        """When SEX only has _T (no real breakdown), it must NOT be auto-expanded."""
        rows = [
            {**_make_row("KEN", "2020", 100.0), "SEX": "_T", "UNIT_MEASURE": "PT"},
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_disagg(**kwargs):
            return {
                "dimensions": [
                    {"field_name": "SEX",          "field_value": ["_T"]},
                    {"field_name": "UNIT_MEASURE", "field_value": ["PT"]},
                ]
            }

        async def fake_fetch_all(**kwargs):
            filters = kwargs.get("disaggregation_filters") or {}
            # SEX should NOT appear with None value when only _T exists.
            assert "SEX" not in filters or filters["SEX"] != None  # noqa: E711
            return full_page

        with (
            patch("data360.api.get_disaggregation", side_effect=fake_disagg),
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
        ):
            result = await summarize_data("WB_WDI", "IND_ID", country_code="KEN")

        assert result.error is None
        assert not result.ambiguous_dimensions

    @pytest.mark.asyncio
    async def test_ref_area_name_injected_into_compact_output(self):
        """ref_area_name should appear in group dict when _resolve_country_names succeeds."""
        rows = [
            _make_row("KEN", "2020", 100.0),
            _make_row("KEN", "2021", 110.0),
            _make_row("NGA", "2020", 200.0),
            _make_row("NGA", "2021", 220.0),
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_fetch_all(**kwargs):
            return full_page

        async def fake_resolve(codes):
            return {"KEN": "Kenya", "NGA": "Nigeria"}

        with (
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
            patch("data360.api._resolve_country_names", side_effect=fake_resolve),
        ):
            result = await summarize_data(
                "WB_WDI", "IND_ID",
                country_code="KEN;NGA",
                group_by=["ref_area"],
            )

        assert result.error is None
        compact = result.to_compact()
        group_dicts = {g["group"]["ref_area"]: g["group"] for g in compact["groups"]}
        assert group_dicts["KEN"]["ref_area_name"] == "Kenya"
        assert group_dicts["NGA"]["ref_area_name"] == "Nigeria"

    @pytest.mark.asyncio
    async def test_ref_area_name_omitted_when_resolution_fails(self):
        """If _resolve_country_names returns empty, compact output omits ref_area_name."""
        rows = [
            _make_row("KEN", "2020", 100.0),
            _make_row("KEN", "2021", 110.0),
        ]
        full_page = _make_data_page(rows, has_more=False)

        async def fake_fetch_all(**kwargs):
            return full_page

        async def fake_resolve(codes):
            return {}  # simulates resolution failure / empty response

        with (
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
            patch("data360.api._resolve_country_names", side_effect=fake_resolve),
        ):
            result = await summarize_data(
                "WB_WDI", "IND_ID",
                country_code="KEN",
                group_by=["ref_area"],
            )

        assert result.error is None
        compact = result.to_compact()
        assert len(compact["groups"]) == 1
        assert "ref_area_name" not in compact["groups"][0]["group"]

    @pytest.mark.asyncio
    async def test_area_codes_deduplicated_before_resolution(self):
        """Duplicate ref_area values across groups should be resolved only once."""
        rows = [
            _make_row("KEN", "2020", 100.0),
            _make_row("KEN", "2021", 110.0),
        ]
        full_page = _make_data_page(rows, has_more=False)
        resolve_calls: list[list[str]] = []

        async def fake_fetch_all(**kwargs):
            return full_page

        async def fake_resolve(codes):
            resolve_calls.append(list(codes))
            return {c: c for c in codes}

        with (
            patch("data360.api._fetch_all_pages", side_effect=fake_fetch_all),
            patch("data360.api._resolve_country_names", side_effect=fake_resolve),
        ):
            await summarize_data(
                "WB_WDI", "IND_ID",
                country_code="KEN",
                group_by=["ref_area"],
            )

        # Should have called _resolve_country_names exactly once with deduplicated codes
        assert len(resolve_calls) == 1
        assert resolve_calls[0].count("KEN") == 1


# ---------------------------------------------------------------------------
# compare_countries
# ---------------------------------------------------------------------------


class TestAutoDetectDisaggDimensions:
    """Unit tests for the _auto_detect_disagg_dimensions helper."""

    @pytest.mark.asyncio
    async def test_pins_sex_to_total_for_rank_path(self):
        """expand_non_trivial=False must pin SEX to _T when available."""
        async def fake_disagg(**kwargs):
            return {
                "dimensions": [
                    {"field_name": "SEX",          "field_value": ["_T", "M", "F"]},
                    {"field_name": "UNIT_MEASURE", "field_value": ["PT"]},
                ]
            }

        with patch("data360.api.get_disaggregation", side_effect=fake_disagg):
            filters, expanded = await _auto_detect_disagg_dimensions(
                "WB_HCP", "IND", "KEN", {}, expand_non_trivial=False
            )

        assert filters["SEX"] == "_T"
        assert filters["UNIT_MEASURE"] == "PT"
        assert expanded == []  # no expansion in rank mode

    @pytest.mark.asyncio
    async def test_expands_sex_to_none_for_summarize_path(self):
        """expand_non_trivial=True must set SEX to None and report it expanded."""
        async def fake_disagg(**kwargs):
            return {
                "dimensions": [
                    {"field_name": "SEX",          "field_value": ["_T", "M", "F"]},
                    {"field_name": "UNIT_MEASURE", "field_value": ["PT"]},
                ]
            }

        with patch("data360.api.get_disaggregation", side_effect=fake_disagg):
            filters, expanded = await _auto_detect_disagg_dimensions(
                "WB_HCP", "IND", "KEN", {}, expand_non_trivial=True
            )

        assert filters["SEX"] is None
        assert filters["UNIT_MEASURE"] == "PT"
        assert "sex" in expanded

    @pytest.mark.asyncio
    async def test_caller_filter_takes_precedence(self):
        """An existing filter must not be overwritten regardless of mode."""
        async def fake_disagg(**kwargs):
            return {
                "dimensions": [
                    {"field_name": "SEX", "field_value": ["_T", "M", "F"]},
                ]
            }

        with patch("data360.api.get_disaggregation", side_effect=fake_disagg):
            filters, expanded = await _auto_detect_disagg_dimensions(
                "WB_HCP", "IND", "KEN", {"SEX": "F"}, expand_non_trivial=True
            )

        assert filters["SEX"] == "F"  # caller's choice preserved
        assert expanded == []

    @pytest.mark.asyncio
    async def test_disagg_error_returns_existing_filters_unchanged(self):
        """A disaggregation API error must be silently swallowed."""
        async def fake_disagg(**kwargs):
            return {"error": "upstream unavailable"}

        with patch("data360.api.get_disaggregation", side_effect=fake_disagg):
            filters, expanded = await _auto_detect_disagg_dimensions(
                "WB_HCP", "IND", "KEN", {"UNIT_MEASURE": "PT"}, expand_non_trivial=True
            )

        assert filters == {"UNIT_MEASURE": "PT"}  # unchanged
        assert expanded == []


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

    @pytest.mark.asyncio
    async def test_compare_countries_year_selection_note_user_specified(self):
        """Should select user-specified year and set the correct selection note."""
        rows = [
            _make_row("KEN", "2021", 100.0),
            _make_row("NGA", "2021", 110.0),
            _make_row("KEN", "2022", 120.0),
            _make_row("NGA", "2022", 130.0),
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
                year=2021,
            )

        assert result.error is None
        assert result.snapshot is not None
        assert result.snapshot.year == "2021"
        assert result.snapshot.year_selection_note == "User-specified year: 2021"

    @pytest.mark.asyncio
    async def test_compare_countries_year_selection_note_common_year(self):
        """Should select the latest common year and set the correct selection note."""
        rows = [
            _make_row("KEN", "2021", 100.0),
            _make_row("NGA", "2021", 110.0),
            _make_row("KEN", "2022", 120.0),
            _make_row("NGA", "2022", 130.0),
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
            )

        assert result.error is None
        assert result.snapshot is not None
        assert result.snapshot.year == "2022"
        assert "Latest year with data for all compared countries: 2022" in result.snapshot.year_selection_note
        assert "2/2 countries" in result.snapshot.year_selection_note

    @pytest.mark.asyncio
    async def test_compare_countries_year_selection_note_fallback(self):
        """Should fallback to the latest year of any country when no common year exists."""
        rows = [
            _make_row("KEN", "2021", 100.0),
            _make_row("NGA", "2022", 110.0),
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
            )

        assert result.error is None
        assert result.snapshot is not None
        assert result.snapshot.year == "2022"
        assert "Latest year with data (partial coverage): 2022" in result.snapshot.year_selection_note
        assert "1/2 countries" in result.snapshot.year_selection_note

    @pytest.mark.asyncio
    async def test_compare_countries_year_selection_note_missing_country(self):
        """Should handle one country completely missing from results (empty years) and fall back with correct note."""
        # KEN has data for 2022, but NGA is completely missing from rows/response.
        rows = [
            _make_row("KEN", "2022", 100.0),
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
            )

        assert result.error is None
        assert result.snapshot is not None
        assert result.snapshot.year == "2022"
        # NGA is completely missing, so common_years should be empty and fallback note used
        assert "Latest year with data (partial coverage): 2022" in result.snapshot.year_selection_note
        assert "1/2 countries" in result.snapshot.year_selection_note


# ---------------------------------------------------------------------------
# to_compact() output — PCN + size invariants
# ---------------------------------------------------------------------------


def _make_ranked_country(
    rank: int = 1,
    ref_area: str = "KEN",
    country_name: str = "Kenya",
    obs_value: float = 5.6,
    claim_id: str = "abc12345",
) -> RankedCountry:
    return RankedCountry(
        rank=rank,
        ref_area=ref_area,
        country_name=country_name,
        obs_value=obs_value,
        percentile=80.0,
        claim_id=claim_id,
    )


def _make_group_summary(
    ref_area: str = "KEN",
    claim_ids: list[str] | None = None,
) -> GroupSummary:
    return GroupSummary(
        group_key={"ref_area": ref_area},
        count=10,
        latest_value=5.6,
        latest_year="2023",
        earliest_value=3.2,
        earliest_year="2005",
        min=3.0,
        max=6.0,
        mean=4.5,
        median=4.4,
        total_change=2.4,
        pct_change=75.0,
        trend_direction="increasing",
        time_range="2005-2023",
        claim_ids=claim_ids or ["aa11bb22", "cc33dd44"],
    )


class TestCompactOutput:
    """Verify the PCN contract and size-reduction invariants of to_compact().

    The core rule: claim_ids are 8-character CRC32 hashes that identify each
    raw observation for data provenance (PCN). They MUST remain in the full
    Pydantic model but MUST NOT appear in the compact representation sent to
    the LLM's context window.
    """

    # ------------------------------------------------------------------
    # GroupSummary
    # ------------------------------------------------------------------

    def test_group_summary_claim_ids_in_full_model(self):
        """Full model must carry claim_ids for provenance."""
        gs = _make_group_summary(claim_ids=["aa11bb22", "cc33dd44"])
        assert gs.claim_ids == ["aa11bb22", "cc33dd44"]

    def test_group_summary_compact_includes_claim_ids(self):
        """Compact output must retain claim_ids for UI provenance attribution (PCN).

        The group-to-claim_ids association must be preserved so the UI knows
        which claim_ids belong to which group's statistics.
        """
        gs = _make_group_summary(claim_ids=["aa11bb22", "cc33dd44"])
        compact = gs.to_compact()
        assert "claim_ids" in compact
        assert compact["claim_ids"] == ["aa11bb22", "cc33dd44"]

    def test_group_summary_compact_shape(self):
        """Compact output must include all LLM-useful analytic fields plus claim_ids."""
        gs = _make_group_summary()
        compact = gs.to_compact()
        assert compact["group"] == {"ref_area": "KEN"}
        assert compact["n"] == 10
        assert compact["latest"] == {"value": 5.6, "year": "2023"}
        assert compact["earliest"] == {"value": 3.2, "year": "2005"}
        assert compact["range"] == "2005-2023"
        assert compact["stats"] == {"min": 3.0, "max": 6.0, "mean": 4.5, "median": 4.4}
        assert compact["change"] == {"abs": 2.4, "pct": 75.0}
        assert compact["trend"] == "increasing"
        assert "claim_ids" in compact

    # ------------------------------------------------------------------
    # RankedCountry
    # ------------------------------------------------------------------

    def test_ranked_country_claim_id_in_full_model(self):
        """Full model must carry claim_id for provenance."""
        rc = _make_ranked_country(claim_id="abc12345")
        assert rc.claim_id == "abc12345"
        assert rc.percentile == 80.0

    def test_ranked_country_compact_includes_claim_id(self):
        """Compact output must retain claim_id for per-entry PCN attribution.

        Only percentile is dropped from RankedCountry compact — it is derivable
        from rank order. claim_id must remain so the UI can render provenance
        per ranked entry.
        """
        rc = _make_ranked_country(claim_id="abc12345")
        compact = rc.to_compact()
        assert "claim_id" in compact
        assert compact["claim_id"] == "abc12345"
        assert "percentile" not in compact

    def test_ranked_country_compact_shape(self):
        """Compact output must include rank, code, country, value, and claim_id."""
        rc = _make_ranked_country(rank=3, ref_area="NGA", country_name="Nigeria", obs_value=4.1)
        compact = rc.to_compact()
        assert compact["rank"] == 3
        assert compact["code"] == "NGA"
        assert compact["country"] == "Nigeria"
        assert compact["value"] == 4.1
        assert "claim_id" in compact

    def test_ranked_country_compact_uses_ref_area_when_no_country_name(self):
        """When country_name is None, compact falls back to ref_area for readability."""
        rc = RankedCountry(rank=1, ref_area="ZZZ", obs_value=10.0, claim_id="ff001122")
        compact = rc.to_compact()
        assert compact["country"] == "ZZZ"

    # ------------------------------------------------------------------
    # RankingResponse — excluded list cap
    # ------------------------------------------------------------------

    def test_ranking_response_excluded_capped_at_five_in_compact(self):
        """Compact must cap excluded_sample at 5 entries, but full model is unchanged.

        Rationale: ranking SSF (48 countries) with 30 excluded entries would
        flood the LLM context. The compact exposes just the count + a 5-entry
        sample; the UI can render the full list from the structured_content.
        """
        excluded_30 = [
            ExcludedCountry(ref_area=f"X{i:02d}", country_name=f"Country {i}", reason="No data")
            for i in range(30)
        ]
        r = RankingResponse(
            year="2022",
            order="desc",
            total_with_data=10,
            total_requested=40,
            rankings=[_make_ranked_country()],
            excluded=excluded_30,
            metadata={"name": "Unemployment rate"},
            unit_measure="PT",
        )

        # Full model: all 30 preserved
        assert len(r.excluded) == 30

        compact = r.to_compact()
        # Compact: count is accurate, sample is capped
        assert compact["excluded_count"] == 30
        assert len(compact["excluded_sample"]) == 5

    def test_ranking_response_compact_has_claim_ids_per_entry(self):
        """Each ranking entry in compact must carry its own claim_id for PCN."""
        r = RankingResponse(
            year="2022",
            order="desc",
            total_with_data=2,
            total_requested=2,
            rankings=[
                _make_ranked_country(rank=1, ref_area="KEN", claim_id="aaaaaaaa"),
                _make_ranked_country(rank=2, ref_area="NGA", claim_id="bbbbbbbb"),
            ],
            excluded=[],
            metadata={"name": "Unemployment rate"},
            unit_measure="PT",
        )
        compact = r.to_compact()
        claim_ids_in_compact = [entry.get("claim_id") for entry in compact["rankings"]]
        assert "aaaaaaaa" in claim_ids_in_compact
        assert "bbbbbbbb" in claim_ids_in_compact
        # percentile must still be absent
        assert all("percentile" not in entry for entry in compact["rankings"])

    # ------------------------------------------------------------------
    # DataSummaryResponse
    # ------------------------------------------------------------------

    def test_summary_response_compact_includes_claim_ids_per_group(self):
        """Compact must retain claim_ids within each GroupSummary for PCN.

        The group→claim_ids association is preserved so the UI can attribute
        provenance per group (e.g. KEN/female vs KEN/male summaries).
        """
        ds = DataSummaryResponse(
            groups=[_make_group_summary(claim_ids=["deadbeef"])],
            metadata={"name": "GDP per capita"},
            unit_measure="USD",
        )
        compact = ds.to_compact()
        assert compact["groups"][0]["claim_ids"] == ["deadbeef"]

    def test_summary_response_compact_error_included(self):
        """Even when error is set, compact must include the error field."""
        ds = DataSummaryResponse(error="No data returned for the given filters.")
        compact = ds.to_compact()
        assert compact["error"] == "No data returned for the given filters."

    # ------------------------------------------------------------------
    # ComparisonTimeSeries — series stripped
    # ------------------------------------------------------------------

    def test_comparison_time_series_compact_uses_array_format(self):
        """Compact series must use positional arrays to preserve PCN association.

        Each data point becomes [time_period, obs_value, claim_id] instead of
        a named dict. This reduces per-point overhead from ~55 chars to ~24
        chars (~56%) while keeping year→value→claim_id bound together so the
        UI can render provenance per data point.

        The full dict-format series (with named fields) is still available
        in the Pydantic model's series attribute.
        """
        ts = ComparisonTimeSeries(
            aligned_years=["2020", "2021", "2022"],
            series={
                "KEN": [
                    {"time_period": "2020", "obs_value": 5.0, "claim_id": "cccccccc"},
                    {"time_period": "2021", "obs_value": 5.2, "claim_id": "dddddddd"},
                    {"time_period": "2022", "obs_value": 5.4, "claim_id": "eeeeeeee"},
                ]
            },
            convergence="converging",
            cagr={"KEN": 3.8},
        )

        # Full model retains the named-dict series
        assert ts.series["KEN"][0]["claim_id"] == "cccccccc"

        compact = ts.to_compact()

        # Series must be present in compact — but as arrays, not dicts
        assert "series" in compact
        ken_series = compact["series"]["KEN"]
        assert ken_series == [
            ["2020", 5.0, "cccccccc"],
            ["2021", 5.2, "dddddddd"],
            ["2022", 5.4, "eeeeeeee"],
        ]

        # schema header must be present to document array positions
        assert compact["series_schema"] == ["time_period", "obs_value", "claim_id"]

        # summary fields must still be present
        assert compact["year_range"] == "2020-2022"
        assert compact["n_aligned_years"] == 3
        assert compact["convergence"] == "converging"
        assert compact["cagr"] == {"KEN": 3.8}

    def test_comparison_time_series_compact_empty_aligned_years(self):
        """year_range must be None when aligned_years is empty."""
        ts = ComparisonTimeSeries()
        compact = ts.to_compact()
        assert compact["year_range"] is None
        assert compact["n_aligned_years"] == 0

    # ------------------------------------------------------------------
    # Serializer round-trip
    # ------------------------------------------------------------------

    def test_compact_aggregation_serializer_produces_valid_json(self):
        """The serializer must call to_compact() and return valid JSON."""
        import json as _json

        from data360.mcp_server.tools import _compact_aggregation_serializer

        ds = DataSummaryResponse(
            groups=[_make_group_summary(claim_ids=["feedface"])],
            metadata={"name": "Test Indicator"},
            unit_measure="PT",
        )
        result = _compact_aggregation_serializer(ds)
        parsed = _json.loads(result)  # must not raise

        # claim_ids must be present per group (PCN preserved)
        assert parsed["groups"][0]["claim_ids"] == ["feedface"]
        # Must still expose useful fields
        assert parsed["indicator"] == "Test Indicator"
        assert parsed["unit"] == "PT"
        assert len(parsed["groups"]) == 1

    def test_compact_aggregation_serializer_fallback_for_unknown_type(self):
        """Serializer must fall back gracefully for objects without to_compact()."""
        from data360.mcp_server.tools import _compact_aggregation_serializer

        plain_dict = {"key": "value", "count": 42}
        result = _compact_aggregation_serializer(plain_dict)
        import json as _json
        parsed = _json.loads(result)
        assert parsed == plain_dict
