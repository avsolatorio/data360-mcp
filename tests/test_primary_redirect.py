"""Tests for primary indicator redirect logic.

Covers:
- PrimarySourceInfo.indicator_id property
- SeriesDescription.primary_source property
- _get_items_from_response metadata_link hoisting
- _enrich_search_results redirect and deduplication
- End-to-end search() with mocked HTTP
"""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_httpx

from data360.api import (
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
        """Two secondary indicators pointing to the same primary should collapse."""
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
        assert len(indicators) == 1
        assert indicators[0].idno == "WB_WDI_SP_POP_TOTL"

    def test_mixed_redirected_and_native(self):
        """Native WDI indicator + secondary that redirects to same -> deduped to 1."""
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
        assert len(indicators) == 1
        assert indicators[0].idno == "WB_WDI_SP_POP_TOTL"
        # First occurrence was the native one (no redirect)
        assert indicators[0].primary_source_of is None

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
            "@odata.context": "...",
            "@odata.count": 2,
            "value": [
                {
                    "series_description": {
                        "idno": "WB_HNP_SP_POP_TOTL_ZS",
                        "name": "Population (% of total population)",
                        "database_id": "WB_HNP",
                        "definition_long": "Share of total population",
                        "dimensions": [],
                    },
                    "additional": {
                        "metadata_link": [
                            {
                                "type": "primary",
                                "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                                "database_id": "WB_WDI",
                                "database_name": "World Development Indicators (WDI)",
                            }
                        ]
                    },
                },
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_0014_MA_ZS",
                        "name": "Population ages 0-14, male",
                        "database_id": "WB_WDI",
                        "definition_long": "Male pop ages 0-14",
                        "dimensions": [],
                    },
                    "additional": {"metadata_link": []},
                },
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/searchv2",
            json=mock_response,
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
        """Verify the select clause includes additional/metadata_link."""
        captured_payloads: list[dict] = []

        def capture_callback(request: httpx.Request) -> httpx.Response:
            captured_payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "@odata.context": "...",
                    "@odata.count": 0,
                    "value": [],
                },
            )

        httpx_mock.add_callback(capture_callback, method="POST")

        await search("population", limit=5)

        assert len(captured_payloads) == 1
        assert "additional/metadata_link" in captured_payloads[0]["select"]

    @pytest.mark.asyncio
    async def test_search_deduplicates_after_redirect(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Two results redirecting to the same primary are collapsed."""
        mock_response = {
            "@odata.context": "...",
            "@odata.count": 2,
            "value": [
                {
                    "series_description": {
                        "idno": "WB_HNP_SP_POP_TOTL_ZS",
                        "name": "Pop HNP",
                        "database_id": "WB_HNP",
                        "definition_long": "d1",
                        "dimensions": [],
                    },
                    "additional": {
                        "metadata_link": [
                            {
                                "type": "primary",
                                "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                                "database_id": "WB_WDI",
                            }
                        ]
                    },
                },
                {
                    "series_description": {
                        "idno": "WB_GS_SP_POP_TOTL",
                        "name": "Pop GS",
                        "database_id": "WB_GS",
                        "definition_long": "d2",
                        "dimensions": [],
                    },
                    "additional": {
                        "metadata_link": [
                            {
                                "type": "primary",
                                "metadata_id": "META_WB_WDI_SP_POP_TOTL",
                                "database_id": "WB_WDI",
                            }
                        ]
                    },
                },
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/searchv2",
            json=mock_response,
        )

        result = await search("population", limit=10)

        assert len(result.indicators) == 1
        assert result.indicators[0].idno == "WB_WDI_SP_POP_TOTL"
