"""Tests for multi-query search (queries parameter) in data360_search_indicators."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data360.api import search
from data360.models import (
    EnrichedSearchResponse,
    MultiQuerySearchResponse,
    QueryGroupResult,
    SearchResponse,
    SeriesDescription,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_series(idno: str = "WB_WDI_GDP", name: str = "GDP") -> SeriesDescription:
    return SeriesDescription(
        idno=idno,
        name=name,
        database_id="WB_WDI",
        definition_long="A test indicator.",
        periodicity="Annual",
        time_periods=[{"start": "2000", "end": "2023", "LATEST_DATA_POINT": "2023"}],
        ref_country=[{"code": "KEN"}],
        dimensions=[],
    )


def _make_search_response(
    idno: str = "WB_WDI_GDP",
    name: str = "GDP",
    count: int = 1,
) -> SearchResponse:
    return SearchResponse(
        items=[_make_series(idno, name)],
        count=count,
        total_count=count,
        offset=0,
        has_more=False,
        next_offset=None,
    )


def _empty_search_response() -> SearchResponse:
    return SearchResponse(items=None, error="No indicators found for: 'xyz'")


# ---------------------------------------------------------------------------
# Backward-compatibility tests (single query path)
# ---------------------------------------------------------------------------


class TestSearchSingleQueryBackwardCompat:
    @pytest.mark.asyncio
    async def test_single_query_returns_enriched_response(self):
        with (
            patch(
                "data360.api._search_raw",
                new=AsyncMock(return_value=_make_search_response()),
            ),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(query="GDP per capita")

        assert isinstance(result, EnrichedSearchResponse)
        assert len(result.indicators) == 1
        assert result.error is None

    @pytest.mark.asyncio
    async def test_single_query_with_country(self):
        with (
            patch(
                "data360.api._search_raw",
                new=AsyncMock(return_value=_make_search_response()),
            ),
            patch(
                "data360.api._resolve_country_code",
                new=AsyncMock(return_value="KEN"),
            ),
        ):
            result = await search(query="GDP", required_country="Kenya")

        assert isinstance(result, EnrichedSearchResponse)
        assert result.required_country == "KEN"

    @pytest.mark.asyncio
    async def test_single_query_no_results_returns_error(self):
        with (
            patch(
                "data360.api._search_raw",
                new=AsyncMock(return_value=_empty_search_response()),
            ),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(query="xyz-does-not-exist")

        assert isinstance(result, EnrichedSearchResponse)
        assert result.error is not None


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestSearchValidation:
    @pytest.mark.asyncio
    async def test_both_query_and_queries_returns_error(self):
        result = await search(query="GDP", queries=["GDP", "inflation"])
        assert isinstance(result, EnrichedSearchResponse)
        assert result.error is not None
        assert "both" in result.error.lower()

    @pytest.mark.asyncio
    async def test_neither_query_nor_queries_returns_error(self):
        result = await search()
        assert isinstance(result, EnrichedSearchResponse)
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_queries_with_one_entry_returns_error(self):
        result = await search(queries=["GDP"])
        assert isinstance(result, MultiQuerySearchResponse)
        assert result.error is not None
        assert "at least 2" in result.error.lower()

    @pytest.mark.asyncio
    async def test_queries_with_empty_strings_filtered_to_under_two_errors(self):
        result = await search(queries=["GDP", "  ", ""])
        assert isinstance(result, MultiQuerySearchResponse)
        assert result.error is not None
        assert "at least 2" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invalid_result_layout_returns_error(self):
        result = await search(queries=["GDP", "inflation"], result_layout="invalid")
        assert isinstance(result, MultiQuerySearchResponse)
        assert result.error is not None
        assert "result_layout" in result.error.lower()


# ---------------------------------------------------------------------------
# Multi-query merged layout tests
# ---------------------------------------------------------------------------


class TestSearchMultiQueryMerged:
    @pytest.mark.asyncio
    async def test_two_queries_merged_returns_multi_response(self):
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")

        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(queries=["GDP", "inflation"])

        assert isinstance(result, MultiQuerySearchResponse)
        assert result.result_layout == "merged"
        assert len(result.indicators) == 2
        assert result.total_candidates == 2

    @pytest.mark.asyncio
    async def test_merged_deduplication_removes_duplicates(self):
        # Both queries return the same indicator
        same_resp_1 = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        same_resp_2 = _make_search_response(idno="WB_WDI_GDP", name="GDP")

        mock_raw = AsyncMock(side_effect=[same_resp_1, same_resp_2])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(queries=["GDP growth", "GDP"], dedupe=True)

        assert isinstance(result, MultiQuerySearchResponse)
        assert len(result.indicators) == 1
        assert result.deduplicated_count == 1

    @pytest.mark.asyncio
    async def test_merged_dedupe_false_preserves_duplicates(self):
        same_resp_1 = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        same_resp_2 = _make_search_response(idno="WB_WDI_GDP", name="GDP")

        mock_raw = AsyncMock(side_effect=[same_resp_1, same_resp_2])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(queries=["GDP growth", "GDP"], dedupe=False)

        assert isinstance(result, MultiQuerySearchResponse)
        assert len(result.indicators) == 2
        assert result.deduplicated_count is None

    @pytest.mark.asyncio
    async def test_country_resolved_once(self):
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")

        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp])
        mock_resolve = AsyncMock(return_value="KEN")

        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=mock_resolve),
        ):
            result = await search(
                queries=["GDP", "inflation"], required_country="Kenya"
            )

        # resolve called once regardless of query count
        mock_resolve.assert_awaited_once_with("Kenya")
        assert result.required_country == "KEN"

    @pytest.mark.asyncio
    async def test_one_failing_sub_query_does_not_crash(self):
        good_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        bad_resp = _empty_search_response()

        mock_raw = AsyncMock(side_effect=[good_resp, bad_resp])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(queries=["GDP", "xyz-missing"])

        assert isinstance(result, MultiQuerySearchResponse)
        # Good sub-query still returns its indicator
        assert len(result.indicators) == 1


# ---------------------------------------------------------------------------
# Multi-query by_query layout tests
# ---------------------------------------------------------------------------


class TestSearchMultiQueryByQuery:
    @pytest.mark.asyncio
    async def test_by_query_returns_groups(self):
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")

        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(
                queries=["GDP", "inflation"], result_layout="by_query"
            )

        assert isinstance(result, MultiQuerySearchResponse)
        assert result.result_layout == "by_query"
        assert result.results is not None
        assert len(result.results) == 2
        assert result.results[0].query == "GDP"
        assert result.results[1].query == "inflation"

    @pytest.mark.asyncio
    async def test_by_query_cross_group_dedup(self):
        """Same indicator in both groups: second group should not include it."""
        same_resp_1 = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        same_resp_2 = _make_search_response(idno="WB_WDI_GDP", name="GDP")

        mock_raw = AsyncMock(side_effect=[same_resp_1, same_resp_2])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(
                queries=["GDP growth", "GDP per capita"],
                result_layout="by_query",
                dedupe=True,
            )

        assert result.results is not None
        assert result.results[0].count == 1  # first group keeps it
        assert result.results[1].count == 0  # second group loses it to dedup
        assert result.deduplicated_count == 1

    @pytest.mark.asyncio
    async def test_by_query_failed_group_has_error_field(self):
        good_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        bad_resp = _empty_search_response()

        mock_raw = AsyncMock(side_effect=[good_resp, bad_resp])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(
                queries=["GDP", "xyz-missing"], result_layout="by_query"
            )

        assert result.results is not None
        assert result.results[0].error is None
        assert result.results[1].error is not None

    @pytest.mark.asyncio
    async def test_by_query_exception_in_sub_query(self):
        """_search_raw raises an exception for one sub-query."""

        async def _raise_on_second(*, query, **kwargs):
            if query == "crash":
                raise RuntimeError("Network timeout")
            return _make_search_response()

        with (
            patch("data360.api._search_raw", new=AsyncMock(side_effect=_raise_on_second)),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(queries=["GDP", "crash"], result_layout="by_query")

        assert result.results is not None
        crash_group = next(g for g in result.results if g.query == "crash")
        assert crash_group.error is not None
        assert "Network timeout" in crash_group.error
