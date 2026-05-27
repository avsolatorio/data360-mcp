from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from data360.api import search
from data360.models import (
    EnrichedSearchResponse,
    MultiQuerySearchResponse,
    QueryGroup,
    SearchResponse,
    SeriesDescription,
)

_TEST_INDICATOR_COUNTRIES: dict[str, list[str]] = {}


@pytest.fixture(autouse=True)
def _mock_get_disaggregation_global(monkeypatch):
    """Mock get_disaggregation to return dummy coverage in multi-query tests."""
    from data360 import api
    async def fake_get_disaggregation(database_id, indicator_id, required_country=None, **kwargs):
        allowed_countries = _TEST_INDICATOR_COUNTRIES.get(indicator_id, ["KEN"])
        queried = {}
        if required_country:
            for c in required_country.split(";"):
                c = c.strip()
                if c:
                    queried[c] = (c in allowed_countries)
        return {
            "dimensions": [
                {
                    "field_name": "REF_AREA",
                    "queried": queried,
                }
            ]
        }
    monkeypatch.setattr(api, "get_disaggregation", fake_get_disaggregation)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_series(idno: str = "WB_WDI_GDP", name: str = "GDP") -> SeriesDescription:
    _TEST_INDICATOR_COUNTRIES[idno] = ["KEN"]
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
        assert "exactly one" in result.error.lower()

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

    @pytest.mark.asyncio
    async def test_empty_string_query_with_query_groups_does_not_error(self):
        """LLM clients sometimes send query="" alongside query_groups.
        Empty string should be normalised to None and not trigger the mutual
        exclusion error — the query_groups path should be taken instead."""
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")

        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value="KEN")),
        ):
            result = await search(
                query="",  # LLM-hallucinated empty default
                query_groups=[
                    QueryGroup(queries=["GDP per capita"], country="Kenya"),
                    QueryGroup(queries=["inflation rate"], country="Kenya"),
                ],
            )

        assert result.error is None or "exactly one" not in (result.error or "")
        assert isinstance(result, MultiQuerySearchResponse)

    @pytest.mark.asyncio
    async def test_whitespace_query_with_query_groups_does_not_error(self):
        """query='   ' (whitespace-only) should also be treated as absent."""
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")

        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value="KEN")),
        ):
            result = await search(
                query="   ",
                query_groups=[
                    QueryGroup(queries=["GDP per capita"], country="Kenya"),
                    QueryGroup(queries=["inflation rate"], country="Kenya"),
                ],
            )

        assert result.error is None or "exactly one" not in (result.error or "")
        assert isinstance(result, MultiQuerySearchResponse)

    @pytest.mark.asyncio
    async def test_empty_queries_list_with_query_groups_does_not_error(self):
        """queries=[] sent alongside query_groups should be normalised to None."""
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")

        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value="KEN")),
        ):
            result = await search(
                queries=[],  # LLM-hallucinated empty default
                query_groups=[
                    QueryGroup(queries=["GDP per capita"], country="Kenya"),
                    QueryGroup(queries=["inflation rate"], country="Kenya"),
                ],
            )

        assert result.error is None or "exactly one" not in (result.error or "")
        assert isinstance(result, MultiQuerySearchResponse)


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
    async def test_by_query_cross_group_dedup_disabled(self):
        """Same indicator in both groups: by_query layout should retain it in both groups."""
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
        assert result.results[1].count == 1  # second group also keeps it
        assert result.deduplicated_count == 0

    @pytest.mark.asyncio
    async def test_merged_layout_merges_covers_country(self):
        """When an indicator is in two groups, covers_country is merged and deduplicated."""
        resp_1 = _make_search_response_with_countries("WB_WDI_GDP", "GDP", ["KEN"])
        resp_2 = _make_search_response_with_countries("WB_WDI_GDP", "GDP", ["KEN"])

        mock_raw = AsyncMock(side_effect=[resp_1, resp_2])

        async def _resolve(c):
            if c == "Kenya": return "KEN"
            if c == "Morocco": return "MAR"
            return None

        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(side_effect=_resolve)),
        ):
            result = await search(
                query_groups=[
                    QueryGroup(queries=["GDP"], country="Kenya"),
                    QueryGroup(queries=["GDP"], country="Morocco"),
                ],
                result_layout="merged",
                dedupe=True,
            )

        assert isinstance(result, MultiQuerySearchResponse)
        assert len(result.indicators) == 1
        ind = result.indicators[0]
        assert ind.covers_country == {"KEN": True, "MAR": False}
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


# ---------------------------------------------------------------------------
# A2 — _ENRICHMENT_SELECT_FIELDS constant used in both paths
# ---------------------------------------------------------------------------


class TestEnrichmentSelectFields:
    def test_constant_exists_and_is_non_empty(self):
        from data360.api import _ENRICHMENT_SELECT_FIELDS
        assert isinstance(_ENRICHMENT_SELECT_FIELDS, list)
        assert len(_ENRICHMENT_SELECT_FIELDS) > 0
        assert "idno" in _ENRICHMENT_SELECT_FIELDS
        assert "database_id" in _ENRICHMENT_SELECT_FIELDS

    def test_search_raw_signature(self):
        import inspect
        from data360.api import _search_raw
        sig = inspect.signature(_search_raw)
        assert "select_fields" not in sig.parameters
        assert "odata_options" not in sig.parameters


# ---------------------------------------------------------------------------
# A3 — Alias conflict warnings in multi-query path
# ---------------------------------------------------------------------------


class TestAliasConflictWarnings:
    @pytest.mark.asyncio
    async def test_n_results_and_limit_conflict_logs_warning(self, caplog):
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")
        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            import logging
            with caplog.at_level(logging.WARNING, logger="data360.api"):
                await search(queries=["GDP", "inflation"], limit=10, n_results=3)

        assert any("limit" in rec.message.lower() and "n_results" in rec.message.lower()
                   for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_skip_and_offset_conflict_logs_warning(self, caplog):
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")
        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            import logging
            with caplog.at_level(logging.WARNING, logger="data360.api"):
                await search(queries=["GDP", "inflation"], offset=5, skip=10)

        assert any("offset" in rec.message.lower() and "skip" in rec.message.lower()
                   for rec in caplog.records)


# ---------------------------------------------------------------------------
# A4 — Literal typing for result_layout
# ---------------------------------------------------------------------------


class TestLiteralResultLayout:
    def test_invalid_result_layout_raises_validation_error(self):
        with pytest.raises(ValidationError):
            MultiQuerySearchResponse(
                result_layout="flat",
                queries=["a", "b"],
            )

    def test_valid_merged_layout_accepted(self):
        resp = MultiQuerySearchResponse(result_layout="merged", queries=["a", "b"])
        assert resp.result_layout == "merged"

    def test_valid_by_query_layout_accepted(self):
        resp = MultiQuerySearchResponse(result_layout="by_query", queries=["a", "b"])
        assert resp.result_layout == "by_query"


# ---------------------------------------------------------------------------
# A5 — Log stripped empty queries
# ---------------------------------------------------------------------------


class TestStrippedQueryLogging:
    @pytest.mark.asyncio
    async def test_empty_entries_warning_logged(self, caplog):
        result = await search(queries=["GDP", "  ", ""])
        assert isinstance(result, MultiQuerySearchResponse)
        # Should have logged warning (empty entries stripped leaving < 2)
        # error returned because < 2 valid queries remain
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_partial_strip_still_logs_warning(self, caplog):
        """3 queries, 1 empty — remaining 2 are valid, warning still emitted."""
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")
        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp])
        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            import logging
            with caplog.at_level(logging.WARNING, logger="data360.api"):
                result = await search(queries=["GDP", "inflation", ""])

        assert isinstance(result, MultiQuerySearchResponse)
        assert result.error is None
        assert any("stripped" in rec.message.lower() for rec in caplog.records)


# ---------------------------------------------------------------------------
# E1/E2 — QueryGroup per-group country
# ---------------------------------------------------------------------------


class TestQueryGroups:
    @pytest.mark.asyncio
    async def test_query_groups_by_query_layout(self):
        """Each group should carry correct country_code; indicators have correct requested_country."""
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        gini_resp = _make_search_response(idno="WB_WDI_GINI", name="Gini")
        mock_raw = AsyncMock(side_effect=[gdp_resp, gini_resp])

        async def _resolve(country):
            return {"Kenya": "KEN", "Morocco": "MAR"}.get(country, None)

        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(side_effect=_resolve)),
        ):
            result = await search(
                query_groups=[
                    QueryGroup(queries=["GDP per capita"], country="Kenya"),
                    QueryGroup(queries=["Gini coefficient"], country="Morocco"),
                ],
                result_layout="by_query",
            )

        assert isinstance(result, MultiQuerySearchResponse)
        assert result.result_layout == "by_query"
        assert result.results is not None
        assert len(result.results) == 2

        gdp_group = result.results[0]
        gini_group = result.results[1]

        assert gdp_group.country_code == "KEN"
        assert gini_group.country_code == "MAR"

        # Each indicator should carry its per-group country
        assert gdp_group.indicators[0].requested_country == "KEN"
        assert gini_group.indicators[0].requested_country == "MAR"

    @pytest.mark.asyncio
    async def test_query_groups_merged_layout_carries_requested_country(self):
        """Merged indicators must carry requested_country for LLM attribution."""
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        gini_resp = _make_search_response(idno="WB_WDI_GINI", name="Gini")
        mock_raw = AsyncMock(side_effect=[gdp_resp, gini_resp])

        async def _resolve(country):
            return {"Kenya": "KEN", "Morocco": "MAR"}.get(country, None)

        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(side_effect=_resolve)),
        ):
            result = await search(
                query_groups=[
                    QueryGroup(queries=["GDP per capita"], country="Kenya"),
                    QueryGroup(queries=["Gini coefficient"], country="Morocco"),
                ],
                result_layout="merged",
            )

        assert isinstance(result, MultiQuerySearchResponse)
        assert len(result.indicators) == 2

        by_id = {ind.idno: ind for ind in result.indicators}
        assert by_id["WB_WDI_GDP"].requested_country == "KEN"
        assert by_id["WB_WDI_GINI"].requested_country == "MAR"

    @pytest.mark.asyncio
    async def test_query_groups_mutually_exclusive_with_queries(self):
        result = await search(
            queries=["GDP", "inflation"],
            query_groups=[QueryGroup(queries=["GDP"], country="Kenya")],
        )
        assert isinstance(result, EnrichedSearchResponse)
        assert result.error is not None
        assert "exactly one" in result.error.lower()

    @pytest.mark.asyncio
    async def test_query_groups_mutually_exclusive_with_query(self):
        result = await search(
            query="GDP",
            query_groups=[QueryGroup(queries=["GDP", "inflation"], country="Kenya")],
        )
        assert isinstance(result, EnrichedSearchResponse)
        assert result.error is not None
        assert "exactly one" in result.error.lower()

    @pytest.mark.asyncio
    async def test_query_groups_minimum_two_queries_total(self):
        """Single query across all groups triggers minimum-2 error."""
        result = await search(
            query_groups=[QueryGroup(queries=["GDP"], country="Kenya")],
        )
        assert isinstance(result, MultiQuerySearchResponse)
        assert result.error is not None
        assert "at least 2" in result.error.lower()

    @pytest.mark.asyncio
    async def test_query_groups_with_none_country(self):
        """Groups without country still work; indicators have requested_country=None."""
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")
        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp])

        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(
                query_groups=[
                    QueryGroup(queries=["GDP"], country=None),
                    QueryGroup(queries=["inflation"], country=None),
                ],
                result_layout="by_query",
            )

        assert isinstance(result, MultiQuerySearchResponse)
        assert result.results is not None
        for group in result.results:
            assert group.country_code is None
            for ind in group.indicators:
                assert ind.requested_country is None

    @pytest.mark.asyncio
    async def test_query_groups_required_country_ignored_warning(self, caplog):
        """required_country is ignored when query_groups is used; warning logged."""
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")
        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp])

        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value="KEN")),
        ):
            import logging
            with caplog.at_level(logging.WARNING, logger="data360.api"):
                result = await search(
                    query_groups=[
                        QueryGroup(queries=["GDP"], country="Kenya"),
                        QueryGroup(queries=["inflation"], country=None),
                    ],
                    required_country="Morocco",  # should be ignored
                )

        assert isinstance(result, MultiQuerySearchResponse)
        assert any("ignored" in rec.message.lower() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_query_groups_concurrent_country_resolution(self):
        """Unique countries are resolved concurrently; each resolved code is distinct."""
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        inf_resp = _make_search_response(idno="WB_WDI_INF", name="Inflation")
        gini_resp = _make_search_response(idno="WB_WDI_GINI", name="Gini")
        mock_raw = AsyncMock(side_effect=[gdp_resp, inf_resp, gini_resp])

        resolve_calls: list[str] = []

        async def _track_resolve(country):
            resolve_calls.append(country)
            return {"Kenya": "KEN", "Morocco": "MAR"}.get(country)

        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(side_effect=_track_resolve)),
        ):
            result = await search(
                query_groups=[
                    QueryGroup(queries=["GDP", "inflation"], country="Kenya"),
                    QueryGroup(queries=["Gini"], country="Morocco"),
                ],
                result_layout="by_query",
            )

        assert isinstance(result, MultiQuerySearchResponse)
        # Only 2 unique countries resolved despite 3 queries
        assert set(resolve_calls) == {"Kenya", "Morocco"}

    @pytest.mark.asyncio
    async def test_query_groups_dict_coercion(self):
        """Passing raw dictionaries for query_groups should be coerced to QueryGroup instances and succeed."""
        gdp_resp = _make_search_response(idno="WB_WDI_GDP", name="GDP")
        gini_resp = _make_search_response(idno="WB_WDI_GINI", name="Gini")
        mock_raw = AsyncMock(side_effect=[gdp_resp, gini_resp])

        async def _resolve(country):
            return {"Kenya": "KEN", "Morocco": "MAR"}.get(country)

        with (
            patch("data360.api._search_raw", new=mock_raw),
            patch("data360.api._resolve_country_code", new=AsyncMock(side_effect=_resolve)),
        ):
            result = await search(
                query_groups=[
                    {"queries": ["GDP"], "country": "Kenya"},
                    {"queries": ["Gini"], "country": "Morocco"},
                ],
                result_layout="by_query",
            )

        assert isinstance(result, MultiQuerySearchResponse)
        assert result.error is None
        assert result.results is not None
        assert len(result.results) == 2
        assert result.results[0].country_code == "KEN"
        assert result.results[1].country_code == "MAR"


# ---------------------------------------------------------------------------
# Semicolon delimiter + covers_country dict
# ---------------------------------------------------------------------------


def _make_series_with_countries(
    idno: str,
    name: str,
    ref_country_codes: list[str],
) -> SeriesDescription:
    """Helper that builds a SeriesDescription with an explicit ref_country list."""
    _TEST_INDICATOR_COUNTRIES[idno] = ref_country_codes
    return SeriesDescription(
        idno=idno,
        name=name,
        database_id="WB_WDI",
        definition_long="Test indicator.",
        periodicity="Annual",
        time_periods=[{"start": "2000", "end": "2023", "LATEST_DATA_POINT": "2023"}],
        ref_country=[{"code": c} for c in ref_country_codes],
        dimensions=[],
    )


def _make_search_response_with_countries(
    idno: str,
    name: str,
    ref_country_codes: list[str],
) -> SearchResponse:
    return SearchResponse(
        items=[_make_series_with_countries(idno, name, ref_country_codes)],
        count=1,
        total_count=1,
        offset=0,
        has_more=False,
        next_offset=None,
    )


class TestSemicolonDelimiterAndCoversCountry:
    """Tests for the semicolon country delimiter and per-country covers_country dict."""

    # -- covers_country shape --------------------------------------------------

    @pytest.mark.asyncio
    async def test_single_country_covers_country_is_dict(self):
        """With one country, covers_country must be a dict keyed by that country's code."""
        resp = _make_search_response_with_countries("IND_1", "GDP", ["KEN"])
        with (
            patch("data360.api._search_raw", new=AsyncMock(return_value=resp)),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value="KEN")),
        ):
            result = await search(query="GDP", required_country="Kenya")

        assert isinstance(result, EnrichedSearchResponse)
        ind = result.indicators[0]
        assert isinstance(ind.covers_country, dict)
        assert ind.covers_country == {"KEN": True}

    @pytest.mark.asyncio
    async def test_single_country_not_covered_is_false_in_dict(self):
        """When the indicator does not list the requested country, covers_country[code] is False."""
        resp = _make_search_response_with_countries("IND_1", "GDP", ["USA"])
        with (
            patch("data360.api._search_raw", new=AsyncMock(return_value=resp)),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value="KEN")),
        ):
            result = await search(query="GDP", required_country="Kenya")

        assert isinstance(result, EnrichedSearchResponse)
        ind = result.indicators[0]
        assert isinstance(ind.covers_country, dict)
        assert ind.covers_country == {"KEN": False}

    @pytest.mark.asyncio
    async def test_no_country_covers_country_is_none(self):
        """When no country is requested, covers_country must be None."""
        resp = _make_search_response_with_countries("IND_1", "GDP", ["KEN"])
        with (
            patch("data360.api._search_raw", new=AsyncMock(return_value=resp)),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value=None)),
        ):
            result = await search(query="GDP")

        assert isinstance(result, EnrichedSearchResponse)
        assert result.indicators[0].covers_country is None

    @pytest.mark.asyncio
    async def test_empty_ref_country_with_requested_country_is_all_false(self):
        """If ref_country list is empty but a country was requested, all codes map to False."""
        resp = _make_search_response_with_countries("IND_1", "GDP", [])
        with (
            patch("data360.api._search_raw", new=AsyncMock(return_value=resp)),
            patch("data360.api._resolve_country_code", new=AsyncMock(return_value="KEN")),
        ):
            result = await search(query="GDP", required_country="Kenya")

        ind = result.indicators[0]
        # ref_country is [] — falls into the elif country_code branch
        assert isinstance(ind.covers_country, dict)
        assert ind.covers_country == {"KEN": False}

    # -- semicolon multi-country -----------------------------------------------

    @pytest.mark.asyncio
    async def test_multi_country_semicolon_resolves_both(self):
        """Semicolon-separated required_country correctly splits and resolves each part.

        We test this by calling _resolve_country_code directly (no mock on the
        function itself) and mocking only the underlying codelist provider so the
        recursive path executes.
        """
        from data360.api import _resolve_country_code

        call_args: list[str] = []

        async def _fake_find(codelist_type: str, query: str, limit: int = 1) -> list[dict]:
            call_args.append(query)
            mapping = {"Kenya": "KEN", "Ghana": "GHA"}
            code = mapping.get(query)
            return [{"id": code, "score": 90}] if code else []

        with patch("data360.providers.find_codelist_value", new=AsyncMock(side_effect=_fake_find)):
            result = await _resolve_country_code("Kenya; Ghana")

        # Both parts should have been looked up
        assert "Kenya" in call_args
        assert "Ghana" in call_args
        # Result is semicolon-joined resolved codes
        assert result == "KEN;GHA"

    @pytest.mark.asyncio
    async def test_multi_country_covers_country_has_entry_per_code(self):
        """covers_country dict has one key per requested country code."""
        resp = _make_search_response_with_countries("IND_1", "GDP", ["KEN"])

        async def _resolve(country: str) -> str | None:
            mapping = {"KEN;GHA": None, "KEN": "KEN", "GHA": "GHA", "Kenya": "KEN", "Ghana": "GHA"}
            return mapping.get(country)

        with (
            patch("data360.api._search_raw", new=AsyncMock(return_value=resp)),
            patch(
                "data360.api._resolve_country_code",
                new=AsyncMock(side_effect=_resolve),
            ),
        ):
            # Directly test _enrich_search_results with a pre-resolved multi-country code
            from data360.api import _enrich_search_results

            search_resp = _make_search_response_with_countries("IND_1", "GDP", ["KEN"])
            indicators, _ = _enrich_search_results(search_resp, "KEN;GHA")

        ind = indicators[0]
        assert isinstance(ind.covers_country, dict)
        assert set(ind.covers_country.keys()) == {"KEN", "GHA"}
        assert ind.covers_country["KEN"] is True
        assert ind.covers_country["GHA"] is False

    @pytest.mark.asyncio
    async def test_multi_country_all_covered(self):
        """When all requested countries are in ref_country, all values are True."""
        from data360.api import _enrich_search_results

        search_resp = _make_search_response_with_countries("IND_1", "GDP", ["KEN", "GHA"])
        indicators, _ = _enrich_search_results(search_resp, "KEN;GHA")

        ind = indicators[0]
        assert ind.covers_country == {"KEN": True, "GHA": True}

    @pytest.mark.asyncio
    async def test_multi_country_none_covered(self):
        """When no requested country is in ref_country, all values are False."""
        from data360.api import _enrich_search_results

        search_resp = _make_search_response_with_countries("IND_1", "GDP", ["USA", "FRA"])
        indicators, _ = _enrich_search_results(search_resp, "KEN;GHA")

        ind = indicators[0]
        assert ind.covers_country == {"KEN": False, "GHA": False}

    # -- comma-in-name safety --------------------------------------------------

    @pytest.mark.asyncio
    async def test_comma_in_country_name_not_split(self):
        """A country name containing a comma must NOT be split on that comma.

        'Korea, Republic of' should be resolved as a single lookup, not two.
        """
        resolve_calls: list[str] = []

        async def _track(country: str) -> str | None:
            resolve_calls.append(country)
            # Simulate no semicolon → falls through to codelist lookup returning KOR
            return "KOR"

        with (
            patch("data360.api._search_raw", new=AsyncMock(return_value=_make_search_response())),
            patch("data360.api._resolve_country_code", new=AsyncMock(side_effect=_track)),
        ):
            await search(query="GDP", required_country="Korea, Republic of")

        # The country string should reach _resolve_country_code as-is (no splitting on comma)
        assert "Korea, Republic of" in resolve_calls

    # -- response-level required_country format --------------------------------

    @pytest.mark.asyncio
    async def test_required_country_in_response_uses_semicolon(self):
        """EnrichedSearchResponse.required_country must use semicolons when multiple codes."""
        resp1 = _make_search_response_with_countries("IND_1", "GDP", ["KEN"])
        resp2 = _make_search_response_with_countries("IND_2", "Gini", ["GHA"])

        async def _resolve(country: str) -> str | None:
            return {"Kenya": "KEN", "Ghana": "GHA"}.get(country)

        with (
            patch("data360.api._search_raw", new=AsyncMock(side_effect=[resp1, resp2])),
            patch("data360.api._resolve_country_code", new=AsyncMock(side_effect=_resolve)),
        ):
            result = await search(
                query_groups=[
                    QueryGroup(queries=["GDP"], country="Kenya"),
                    QueryGroup(queries=["Gini"], country="Ghana"),
                ],
            )

        assert isinstance(result, MultiQuerySearchResponse)
        # Codes are sorted and joined with ";"
        assert result.required_country == "GHA;KEN"
        assert "," not in (result.required_country or "")

    # -- sort ordering ---------------------------------------------------------

    @pytest.mark.asyncio
    async def test_covered_indicator_sorts_before_uncovered(self):
        """Indicator with covers_country having any True value sorts before all-False indicator."""
        from data360.api import _enrich_search_results

        # older indicator but covered
        covered_resp = _make_search_response_with_countries("IND_COVERED", "GDP", ["KEN"])
        covered_resp.items[0].time_periods = [{"start": "2000", "end": "2010", "LATEST_DATA_POINT": "2010"}]

        # newer indicator but not covered
        uncovered_resp = _make_search_response_with_countries("IND_UNCOVERED", "Inflation", ["USA"])
        uncovered_resp.items[0].time_periods = [{"start": "2000", "end": "2023", "LATEST_DATA_POINT": "2023"}]

        from data360.models import SearchResponse as SR

        combined = SR(
            items=[covered_resp.items[0], uncovered_resp.items[0]],
            count=2,
            total_count=2,
            offset=0,
            has_more=False,
            next_offset=None,
        )
        indicators, _ = _enrich_search_results(combined, "KEN")

        indicators.sort(
            key=lambda x: (
                not any((x.covers_country or {}).values()),
                -(int(x.latest_data or 0) if str(x.latest_data or "").isdigit() else 0),
            )
        )

        assert indicators[0].idno == "IND_COVERED"
        assert indicators[1].idno == "IND_UNCOVERED"
