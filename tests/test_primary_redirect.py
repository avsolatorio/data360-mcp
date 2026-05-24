"""Tests for primary indicator redirect logic.

Covers:
- PrimarySourceInfo.indicator_id property
- SeriesDescription.primary_source property
- _get_items_from_response metadata_link hoisting
- _enrich_search_results redirect and deduplication
- _backfill_primary_metadata: patches latest_data/time_period_range from primary
- End-to-end search() with mocked HTTP
"""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_httpx

from data360.api import (
    _backfill_primary_metadata,
    _enrich_search_results,
    _get_items_from_response,
    search,
)
from data360.models import (
    EnrichedSearchResponse,
    PrimarySourceInfo,
    SearchResponse,
    SeriesDescription,
)

# ---------------------------------------------------------------------------
# PrimarySourceInfo.indicator_id
# ---------------------------------------------------------------------------


class TestPrimarySourceInfoIndicatorId:
    def test_strips_meta_prefix(self):
        info = PrimarySourceInfo(
            type="primary",
            metadata_id="META_WB_WDI_SP_POP_TOTL",
            database_id="WB_WDI",
        )
        assert info.indicator_id == "WB_WDI_SP_POP_TOTL"

    def test_no_prefix_passthrough(self):
        info = PrimarySourceInfo(
            type="primary",
            metadata_id="WB_WDI_SP_POP_TOTL",
            database_id="WB_WDI",
        )
        assert info.indicator_id == "WB_WDI_SP_POP_TOTL"

    def test_empty_string(self):
        info = PrimarySourceInfo(
            type="primary",
            metadata_id="",
            database_id="WB_WDI",
        )
        assert info.indicator_id == ""


# ---------------------------------------------------------------------------
# SeriesDescription.primary_source
# ---------------------------------------------------------------------------


class TestSeriesDescriptionPrimarySource:
    def _make_sd(self, metadata_link=None) -> SeriesDescription:
        return SeriesDescription(
            idno="WB_HNP_SP_POP_TOTL_ZS",
            name="Population",
            database_id="WB_HNP",
            metadata_link=metadata_link or [],
        )

    def test_returns_primary_link(self):
        sd = self._make_sd(
            metadata_link=[
                PrimarySourceInfo(
                    type="primary",
                    metadata_id="META_WB_WDI_SP_POP_TOTL",
                    database_id="WB_WDI",
                )
            ]
        )
        assert sd.primary_source is not None
        assert sd.primary_source.indicator_id == "WB_WDI_SP_POP_TOTL"

    def test_returns_none_when_empty(self):
        sd = self._make_sd(metadata_link=[])
        assert sd.primary_source is None

    def test_returns_none_when_no_primary_type(self):
        sd = self._make_sd(
            metadata_link=[
                PrimarySourceInfo(
                    type="secondary",
                    metadata_id="META_WB_GS_SP_POP_TOTL",
                    database_id="WB_GS",
                )
            ]
        )
        assert sd.primary_source is None

    def test_returns_first_primary_when_multiple(self):
        sd = self._make_sd(
            metadata_link=[
                PrimarySourceInfo(
                    type="primary",
                    metadata_id="META_WB_WDI_FIRST",
                    database_id="WB_WDI",
                ),
                PrimarySourceInfo(
                    type="primary",
                    metadata_id="META_WB_WDI_SECOND",
                    database_id="WB_WDI",
                ),
            ]
        )
        assert sd.primary_source is not None
        assert sd.primary_source.indicator_id == "WB_WDI_FIRST"


# ---------------------------------------------------------------------------
# _get_items_from_response — metadata_link hoisting
# ---------------------------------------------------------------------------


class TestGetItemsFromResponseMetadataLink:
    def test_hoists_metadata_link_from_additional(self):
        response_data = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_HNP_X",
                        "name": "Test",
                        "database_id": "WB_HNP",
                    },
                    "additional": {
                        "metadata_link": [
                            {
                                "type": "primary",
                                "metadata_id": "META_WB_WDI_X",
                                "database_id": "WB_WDI",
                            }
                        ]
                    },
                }
            ]
        }
        items = _get_items_from_response(response_data)
        assert len(items) == 1
        assert len(items[0].metadata_link) == 1
        assert items[0].metadata_link[0].type == "primary"
        assert items[0].primary_source is not None
        assert items[0].primary_source.indicator_id == "WB_WDI_X"

    def test_no_additional_key(self):
        response_data = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_Y",
                        "name": "Test",
                        "database_id": "WB_WDI",
                    }
                }
            ]
        }
        items = _get_items_from_response(response_data)
        assert len(items) == 1
        assert items[0].metadata_link == []

    def test_empty_additional(self):
        response_data = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_Y",
                        "name": "Test",
                        "database_id": "WB_WDI",
                    },
                    "additional": {},
                }
            ]
        }
        items = _get_items_from_response(response_data)
        assert items[0].metadata_link == []

    def test_empty_metadata_link_array(self):
        response_data = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_Y",
                        "name": "Test",
                        "database_id": "WB_WDI",
                    },
                    "additional": {"metadata_link": []},
                }
            ]
        }
        items = _get_items_from_response(response_data)
        assert items[0].metadata_link == []


# ---------------------------------------------------------------------------
# _enrich_search_results — redirect and dedup
# ---------------------------------------------------------------------------


def _make_search_response(items_data: list[dict]) -> SearchResponse:
    """Build a SearchResponse from simple item dicts."""
    items = []
    for d in items_data:
        ml = d.get("metadata_link", [])
        items.append(
            SeriesDescription(
                idno=d["idno"],
                name=d.get("name", "Test"),
                database_id=d["database_id"],
                definition_long=d.get("definition_long"),
                metadata_link=[PrimarySourceInfo(**link) for link in ml],
            )
        )
    return SearchResponse(items=items, count=len(items))


class TestEnrichSearchResultsRedirect:
    def test_redirects_to_primary(self):
        response = _make_search_response(
            [
                {
                    "idno": "WB_HNP_SP_POP_TOTL_ZS",
                    "database_id": "WB_HNP",
                    "metadata_link": [
                        {
                            "type": "primary",
                            "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                            "database_id": "WB_WDI",
                        }
                    ],
                }
            ]
        )
        indicators, _ = _enrich_search_results(response, country_code=None)
        assert len(indicators) == 1
        assert indicators[0].idno == "WB_WDI_SP_POP_TOTL"
        assert indicators[0].database_id == "WB_WDI"
        assert indicators[0].primary_source_of == "WB_HNP_SP_POP_TOTL_ZS"

    def test_no_redirect_when_no_metadata_link(self):
        response = _make_search_response(
            [
                {
                    "idno": "WB_WDI_SP_POP_TOTL",
                    "database_id": "WB_WDI",
                    "metadata_link": [],
                }
            ]
        )
        indicators, _ = _enrich_search_results(response, country_code=None)
        assert indicators[0].idno == "WB_WDI_SP_POP_TOTL"
        assert indicators[0].primary_source_of is None

    def test_no_redirect_when_non_primary_type(self):
        response = _make_search_response(
            [
                {
                    "idno": "FAO_AS_1234",
                    "database_id": "FAO_AS",
                    "metadata_link": [
                        {
                            "type": "related",
                            "metadata_id": "META_WB_WDI_X",
                            "database_id": "WB_WDI",
                        }
                    ],
                }
            ]
        )
        indicators, _ = _enrich_search_results(response, country_code=None)
        assert indicators[0].idno == "FAO_AS_1234"
        assert indicators[0].primary_source_of is None

    def test_deduplicates_after_redirect(self):
        """Two secondary indicators pointing to the same primary both appear in the
        full list returned by _enrich_search_results — dedup is the caller's job."""
        response = _make_search_response(
            [
                {
                    "idno": "WB_HNP_SP_POP_TOTL_ZS",
                    "database_id": "WB_HNP",
                    "metadata_link": [
                        {
                            "type": "primary",
                            "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                            "database_id": "WB_WDI",
                        }
                    ],
                },
                {
                    "idno": "WB_GS_SP_POP_TOTL",
                    "database_id": "WB_GS",
                    "metadata_link": [
                        {
                            "type": "primary",
                            "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                            "database_id": "WB_WDI",
                        }
                    ],
                },
            ]
        )
        indicators, _ = _enrich_search_results(response, country_code=None)
        # Both are redirected to the same primary; the full (undeduped) list is returned.
        assert len(indicators) == 2
        assert all(ind.idno == "WB_WDI_SP_POP_TOTL" for ind in indicators)
        assert all(ind.primary_source_of is not None for ind in indicators)

    def test_mixed_redirected_and_native(self):
        """Native WDI + secondary that redirects to same primary both appear.
        Dedup (collapsing to 1) is the caller's responsibility."""
        response = _make_search_response(
            [
                {
                    "idno": "WB_WDI_SP_POP_TOTL",
                    "database_id": "WB_WDI",
                    "metadata_link": [],
                },
                {
                    "idno": "WB_HNP_SP_POP_TOTL_ZS",
                    "database_id": "WB_HNP",
                    "metadata_link": [
                        {
                            "type": "primary",
                            "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                            "database_id": "WB_WDI",
                        }
                    ],
                },
            ]
        )
        indicators, _ = _enrich_search_results(response, country_code=None)
        # _enrich_search_results no longer deduplicates; both items are returned.
        assert len(indicators) == 2
        # First occurrence was the native one (no redirect)
        assert indicators[0].idno == "WB_WDI_SP_POP_TOTL"
        assert indicators[0].primary_source_of is None
        # Second was redirected
        assert indicators[1].idno == "WB_WDI_SP_POP_TOTL"
        assert indicators[1].primary_source_of == "WB_HNP_SP_POP_TOTL_ZS"

    def test_preserves_original_name(self):
        """Redirect changes idno/database_id but preserves the original name."""
        response = _make_search_response(
            [
                {
                    "idno": "WB_HNP_SP_POP_TOTL_ZS",
                    "name": "Population (% of total population)",
                    "database_id": "WB_HNP",
                    "metadata_link": [
                        {
                            "type": "primary",
                            "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                            "database_id": "WB_WDI",
                        }
                    ],
                }
            ]
        )
        indicators, _ = _enrich_search_results(response, country_code=None)
        assert indicators[0].name == "Population (% of total population)"

    def test_empty_items_returns_empty(self):
        response = SearchResponse(items=[], count=0)
        indicators, _ = _enrich_search_results(response, country_code=None)
        assert indicators == []

    def test_none_items_returns_empty(self):
        response = SearchResponse(items=None, count=0)
        indicators, _ = _enrich_search_results(response, country_code=None)
        assert indicators == []

    def test_no_redirect_when_database_id_is_none(self):
        """metadata_link with database_id=None (real case: META_SI.POV.MPWB) should not redirect."""
        response = _make_search_response(
            [
                {
                    "idno": "WB_SSGD_MULTIDIM_POVERTY_RATIO",
                    "database_id": "WB_SSGD",
                    "metadata_link": [
                        {
                            "type": "primary",
                            "metadata_id": "META_SI.POV.MPWB",
                            "database_id": None,
                        }
                    ],
                }
            ]
        )
        indicators, _ = _enrich_search_results(response, country_code=None)
        assert len(indicators) == 1
        # Should NOT redirect since database_id is None
        assert indicators[0].idno == "WB_SSGD_MULTIDIM_POVERTY_RATIO"
        assert indicators[0].database_id == "WB_SSGD"
        assert indicators[0].primary_source_of is None


    def test_no_redirect_when_database_id_is_none_logs_warning(self, caplog):
        """A primary link with database_id=None must emit a warning and not redirect."""
        import logging

        response = _make_search_response(
            [
                {
                    "idno": "WB_SSGD_MULTIDIM_POVERTY_RATIO",
                    "database_id": "WB_SSGD",
                    "metadata_link": [
                        {
                            "type": "primary",
                            "metadata_id": "META_SI.POV.MPWB",
                            "database_id": None,
                        }
                    ],
                }
            ]
        )
        with caplog.at_level(logging.WARNING, logger="data360.api"):
            indicators, _ = _enrich_search_results(response, country_code=None)

        assert indicators[0].idno == "WB_SSGD_MULTIDIM_POVERTY_RATIO"
        assert indicators[0].primary_source_of is None
        assert any("database_id is None" in r.message for r in caplog.records)


class TestGetItemsNullDatabaseIdInMetadataLink:
    """Ensure items with null database_id in metadata_link are still parsed."""

    def test_item_with_null_database_id_in_metadata_link_is_not_dropped(self):
        """Previously this caused a Pydantic ValidationError and dropped the item."""
        response_data = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_SSGD_MULTIDIM_POVERTY_RATIO",
                        "name": "Multidimensional poverty headcount ratio",
                        "database_id": "WB_SSGD",
                    },
                    "additional": {
                        "metadata_link": [
                            {
                                "type": "primary",
                                "metadata_id": "META_SI.POV.MPWB",
                                "database_id": None,
                                "database_name": None,
                            }
                        ]
                    },
                }
            ]
        }
        items = _get_items_from_response(response_data)
        assert len(items) == 1
        assert items[0].idno == "WB_SSGD_MULTIDIM_POVERTY_RATIO"
        assert len(items[0].metadata_link) == 1
        assert items[0].metadata_link[0].database_id is None


# ---------------------------------------------------------------------------
# Integration: search() with mocked HTTP
# ---------------------------------------------------------------------------


class TestSearchPrimaryRedirectIntegration:
    """Test search() end-to-end with metadata_link in API response."""

    @pytest.mark.asyncio
    async def test_search_applies_redirect(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        mock_response = {
            "count": 2,
            "results": [
                {
                    "idno": "WB_HNP_SP_POP_TOTL_ZS",
                    "name": "Population (% of total population)",
                    "databases": [{"idno": "WB_HNP"}],
                    "description": "Share of total population",
                    "dimensions": [],
                    "metadata_link": [
                        {
                            "type": "primary",
                            "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                            "database_id": "WB_WDI",
                            "database_name": "World Development Indicators (WDI)",
                        }
                    ],
                },
                {
                    "idno": "WB_WDI_SP_POP_0014_MA_ZS",
                    "name": "Population ages 0-14, male",
                    "databases": [{"idno": "WB_WDI"}],
                    "description": "Male pop ages 0-14",
                    "dimensions": [],
                },
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=mock_response,
        )
        # The redirected indicator triggers a backfill metadata fetch.
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={"value": []},  # empty — backfill gracefully skips
            is_optional=True,
        )

        result = await search("population", limit=10)

        assert isinstance(result, EnrichedSearchResponse)
        assert result.error is None
        assert len(result.indicators) == 2

        # First item should be redirected to WDI
        assert result.indicators[0].idno == "WB_WDI_SP_POP_TOTL"
        assert result.indicators[0].database_id == "WB_WDI"
        assert result.indicators[0].primary_source_of == "WB_HNP_SP_POP_TOTL_ZS"
        # Name preserved from search result
        assert (
            result.indicators[0].name == "Population (% of total population)"
        )

        # Second item unchanged
        assert result.indicators[1].idno == "WB_WDI_SP_POP_0014_MA_ZS"
        assert result.indicators[1].primary_source_of is None

    @pytest.mark.asyncio
    async def test_search_includes_metadata_link_in_select(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Verify the SearchV3 query payload contains site and types keys."""
        captured_payloads: list[dict] = []

        def capture_callback(request: httpx.Request) -> httpx.Response:
            captured_payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "count": 0,
                    "results": [],
                },
            )

        httpx_mock.add_callback(capture_callback, method="POST")

        await search("population", limit=5)

        assert len(captured_payloads) == 1
        assert captured_payloads[0].get("site") == "data360"
        assert captured_payloads[0].get("types") == ["indicator"]

    @pytest.mark.asyncio
    async def test_search_deduplicates_after_redirect(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Two results redirecting to the same primary — single-query search() does not
        deduplicate; both are returned (dedup is the multi-query caller's responsibility)."""
        mock_response = {
            "count": 2,
            "results": [
                {
                    "idno": "WB_HNP_SP_POP_TOTL_ZS",
                    "name": "Pop HNP",
                    "databases": [{"idno": "WB_HNP"}],
                    "description": "d1",
                    "dimensions": [],
                    "metadata_link": [
                        {
                            "type": "primary",
                            "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                            "database_id": "WB_WDI",
                        }
                    ],
                },
                {
                    "idno": "WB_GS_SP_POP_TOTL",
                    "name": "Pop GS",
                    "databases": [{"idno": "WB_GS"}],
                    "description": "d2",
                    "dimensions": [],
                    "metadata_link": [
                        {
                            "type": "primary",
                            "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                            "database_id": "WB_WDI",
                        }
                    ],
                },
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=mock_response,
        )
        # One (or both) redirected indicators trigger backfill metadata fetches.
        # We use is_optional because the dedup-from-caller may vary in multi-mock order.
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={"value": []},  # empty — backfill gracefully skips
            is_optional=True,
        )

        result = await search("population", limit=10)

        # Single-query search() does not deduplicate: both items are returned.
        assert len(result.indicators) == 2
        assert all(ind.idno == "WB_WDI_SP_POP_TOTL" for ind in result.indicators)
        assert all(ind.primary_source_of is not None for ind in result.indicators)



# ---------------------------------------------------------------------------
# _backfill_primary_metadata
# ---------------------------------------------------------------------------


_METADATA_URL = "https://api.test.example.com/metadata"
_SEARCH_URL = "https://api.test.example.com/portal/v1/public_data360_search"


def _make_metadata_response(start: str, end: str, latest: str) -> dict:
    """Build a minimal metadata API response payload."""
    return {
        "value": [
            {
                "series_description": {
                    "idno": "IGNORED",
                    "database_id": "IGNORED",
                    "time_periods": [
                        {
                            "start": start,
                            "end": end,
                            "LATEST_DATA_POINT": latest,
                        }
                    ],
                }
            }
        ]
    }


class TestBackfillPrimaryMetadata:
    """Unit tests for _backfill_primary_metadata using mocked HTTP."""

    @pytest.mark.asyncio
    async def test_backfill_patches_latest_data_and_range(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Redirected indicator gets latest_data and time_period_range from the primary."""
        httpx_mock.add_response(
            method="POST",
            url=_METADATA_URL,
            json=_make_metadata_response("1960", "2025", "2025"),
        )

        from data360.models import EnrichedIndicator

        ind = EnrichedIndicator(
            idno="WB_WDI_SP_POP_TOTL",
            database_id="WB_WDI",
            name="Population",
            truncated_definition="Total population.",
            latest_data="2023",           # stale secondary value
            time_period_range="1960-2023",  # stale secondary value
        )

        await _backfill_primary_metadata([ind])

        assert ind.latest_data == "2025"
        assert ind.time_period_range == "1960-2025"

    @pytest.mark.asyncio
    async def test_backfill_noop_on_empty_list(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Empty redirected list must not trigger any HTTP request."""
        await _backfill_primary_metadata([])
        # httpx_mock would raise AssertionError if any unexpected requests were fired.

    @pytest.mark.asyncio
    async def test_backfill_graceful_on_metadata_failure(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """HTTP failure during backfill must not raise; original values are kept."""
        httpx_mock.add_response(
            method="POST",
            url=_METADATA_URL,
            status_code=500,
        )

        from data360.models import EnrichedIndicator

        ind = EnrichedIndicator(
            idno="WB_WDI_SP_POP_TOTL",
            database_id="WB_WDI",
            name="Population",
            truncated_definition="Total population.",
            latest_data="2023",
            time_period_range="1960-2023",
        )

        # Should not raise — failure is swallowed with a warning.
        await _backfill_primary_metadata([ind])

        # Original (secondary) values are preserved on failure.
        assert ind.latest_data == "2023"
        assert ind.time_period_range == "1960-2023"

    @pytest.mark.asyncio
    async def test_backfill_deduplicates_same_primary(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Two indicators pointing to the same primary should issue only one fetch."""
        httpx_mock.add_response(
            method="POST",
            url=_METADATA_URL,
            json=_make_metadata_response("1960", "2025", "2025"),
        )

        from data360.models import EnrichedIndicator

        # Two separate EnrichedIndicator instances that both resolved to the same primary.
        ind1 = EnrichedIndicator(
            idno="WB_WDI_SP_POP_TOTL",
            database_id="WB_WDI",
            name="Population (HNP)",
            truncated_definition="HNP source.",
            latest_data="2020",
            time_period_range="1960-2020",
        )
        ind2 = EnrichedIndicator(
            idno="WB_WDI_SP_POP_TOTL",
            database_id="WB_WDI",
            name="Population (GS)",
            truncated_definition="GS source.",
            latest_data="2021",
            time_period_range="1960-2021",
        )

        # Only one metadata mock registered — if both fetch, the second will fail.
        await _backfill_primary_metadata([ind1, ind2])

        # ind1 was the unique representative; its values should be updated.
        assert ind1.latest_data == "2025"
        assert ind1.time_period_range == "1960-2025"
        # ind2 was skipped (deduped); original values preserved.
        assert ind2.latest_data == "2021"

    @pytest.mark.asyncio
    async def test_search_backfills_primary_time_period(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """End-to-end: search() redirects and then backfills time period from primary."""
        search_response = {
            "count": 1,
            "results": [
                {
                    "idno": "WB_HNP_SP_POP_TOTL_ZS",
                    "name": "Population (secondary)",
                    "databases": [{"idno": "WB_HNP"}],
                    "description": "Secondary source",
                    "dimensions": [],
                    "time_period": [
                        {"start": "1960", "end": "2023", "LATEST_DATA_POINT": "2023"}
                    ],
                    "metadata_link": [
                        {
                            "type": "primary",
                            "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                            "database_id": "WB_WDI",
                        }
                    ],
                }
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url=_SEARCH_URL,
            json=search_response,
        )
        httpx_mock.add_response(
            method="POST",
            url=_METADATA_URL,
            json=_make_metadata_response("1960", "2025", "2025"),
        )

        result = await search("population", limit=5)

        assert isinstance(result, EnrichedSearchResponse)
        ind = result.indicators[0]
        assert ind.idno == "WB_WDI_SP_POP_TOTL"
        # Backfill should have replaced the secondary's 2023 with the primary's 2025.
        assert ind.latest_data == "2025"
        assert ind.time_period_range == "1960-2025"

    @pytest.mark.asyncio
    async def test_search_applies_redirect_v3_connected_entities(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Verify that SearchV3 responses map primary_source_of correctly using
        connected_entities when a secondary indicator ID is searched.
        """
        search_response = {
            "count": 1,
            "results": [
                {
                    "idno": "WB_WDI_SP_POP_TOTL",
                    "name": "Population, total",
                    "databases": [{"idno": "WB_WDI"}],
                    "description": "Total population",
                    "dimensions": [],
                    "time_period": [
                        {"start": "1960", "end": "2024", "LATEST_DATA_POINT": "2024"}
                    ],
                    "connected_entities": [
                        {
                            "type": "indicator",
                            "idno": "WB_HNP_SP_POP_TOTL_ZS",
                            "parent_idno": "WB_HNP",
                            "parent_name": "Health Nutrition and Population Statistics",
                        }
                    ],
                }
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url=_SEARCH_URL,
            json=search_response,
        )
        httpx_mock.add_response(
            method="POST",
            url=_METADATA_URL,
            json=_make_metadata_response("1960", "2024", "2024"),
        )

        result = await search("WB_HNP_SP_POP_TOTL_ZS", limit=5)

        assert isinstance(result, EnrichedSearchResponse)
        assert result.error is None
        assert len(result.indicators) == 1
        ind = result.indicators[0]
        assert ind.idno == "WB_WDI_SP_POP_TOTL"
        assert ind.database_id == "WB_WDI"
        assert ind.primary_source_of == "WB_HNP_SP_POP_TOTL_ZS"

    @pytest.mark.asyncio
    async def test_search_single_country_optimization(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Verify that single-country searches bypass disaggregation/dimensions checks."""
        search_response = {
            "count": 1,
            "results": [
                {
                    "idno": "WB_WDI_SP_POP_TOTL",
                    "name": "Population, total",
                    "databases": [{"idno": "WB_WDI"}],
                    "description": "Total population",
                    "dimensions": [],
                    "time_period": [
                        {"start": "1960", "end": "2024", "LATEST_DATA_POINT": "2024"}
                    ],
                }
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url=_SEARCH_URL,
            json=search_response,
        )

        result = await search("population", required_country="JPN", limit=5)

        assert isinstance(result, EnrichedSearchResponse)
        assert result.error is None
        assert len(result.indicators) == 1
        ind = result.indicators[0]
        assert ind.covers_country == {"JPN": True}

        # Verify that dimensions/disaggregation endpoint was NOT called
        for req in httpx_mock.get_requests():
            assert "dimensions" not in str(req.url)
            assert "disaggregation" not in str(req.url)

    @pytest.mark.asyncio
    async def test_search_handles_invalid_connected_entities_gracefully(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Verify that search handles an indicator with connected_entities being non-list
        (e.g., None, string, dict) gracefully without raising a TypeError.
        """
        search_response = {
            "count": 1,
            "results": [
                {
                    "idno": "WB_WDI_SP_POP_TOTL",
                    "name": "Population, total",
                    "databases": [{"idno": "WB_WDI"}],
                    "description": "Total population",
                    "dimensions": [],
                    "time_period": [
                        {"start": "1960", "end": "2024", "LATEST_DATA_POINT": "2024"}
                    ],
                    "connected_entities": "not-a-list-but-a-string",  # Invalid type
                }
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url=_SEARCH_URL,
            json=search_response,
        )

        result = await search("WB_WDI_SP_POP_TOTL", limit=5)

        assert isinstance(result, EnrichedSearchResponse)
        assert result.error is None
        assert len(result.indicators) == 1
        assert result.indicators[0].idno == "WB_WDI_SP_POP_TOTL"
