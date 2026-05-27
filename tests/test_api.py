"""Tests for data360.api module."""

import json
import re

import httpx
import pytest
import pytest_httpx

from data360.api import (
    _get_valid_disaggregations,
    _obs_value_to_float,
    get_data,
    get_metadata,
    search,
    search_datasets,
)
from data360.errors import Data360MCPError
from data360.models import (
    EnrichedSearchResponse,
    IndicatorDataResponse,
    MetadataResponse,
)


class TestGetValidDisaggregations:
    """Tests for _get_valid_disaggregations helper function."""

    def test_filters_out_null_values(self):
        """Test that _Z values are filtered out."""
        EXPECTED_VALID_COUNT = 2
        disagg_res = [
            {"field_value": ["_Z"], "field_name": "REF_AREA"},  # Should be filtered
            {"field_value": ["UGA"], "field_name": "REF_AREA"},  # Should be included
            {"field_value": ["_T"], "field_name": "UNIT_MEASURE"},  # Should be included
        ]
        result = _get_valid_disaggregations(disagg_res)
        assert len(result) == EXPECTED_VALID_COUNT
        # Verify _Z was filtered out
        field_values = [item["field_value"][0] for item in result]
        assert "_Z" not in field_values
        assert "UGA" in field_values
        assert "_T" in field_values

    def test_handles_empty_list(self):
        """Test that empty list returns empty list."""
        result = _get_valid_disaggregations([])
        assert result == []

    def test_handles_missing_field_value(self):
        """Test that missing field_value uses default."""
        disagg_res = [{"field_name": "REF_AREA"}]
        result = _get_valid_disaggregations(disagg_res)
        # Default is ["_T"], which is not in null_values, so it should be included
        assert len(result) == 1


@pytest.mark.parametrize(
    ("val", "expected"),
    [
        (None, None),
        ("", None),
        ("  ", None),
        ("null", None),
        ("NaN", None),
        ("none", None),
        (float("nan"), None),
        ("abc", None),
        (42, 42.0),
        ("42.5", 42.5),
        (0, 0.0),
        ("0", 0.0),
        (" 3.14 ", 3.14),
    ],
)
def test_obs_value_to_float(val, expected):
    """_obs_value_to_float normalizes API edge-case values for ranking/comparison."""
    assert _obs_value_to_float(val) == expected


class TestSearch:
    """Tests for search() function."""

    @pytest.mark.asyncio
    async def test_search_success(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test successful search request."""
        NUM_ITEMS = 2
        mock_response = {
            "count": NUM_ITEMS,
            "results": [
                {
                    "idno": "WB_WDI_SP_POP_TOTL",
                    "name": "Population, total",
                    "databases": [{"idno": "WB_WDI"}],
                    "description": "Total population",
                    "dimensions": [],
                },
                {
                    "idno": "WB_WDI_SP_POP_GROW",
                    "name": "Population growth",
                    "databases": [{"idno": "WB_WDI"}],
                    "description": "Population growth rate",
                    "dimensions": [],
                },
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=mock_response,
        )

        result = await search("population", limit=10)

        assert isinstance(result, EnrichedSearchResponse)
        assert result.indicators is not None
        assert len(result.indicators) == NUM_ITEMS
        assert result.indicators[0].idno == "WB_WDI_SP_POP_TOTL"
        assert result.indicators[0].name == "Population, total"
        assert result.indicators[1].idno == "WB_WDI_SP_POP_GROW"
        assert result.total_count == NUM_ITEMS
        assert result.count == NUM_ITEMS
        assert result.has_more is False
        assert result.error is None

    @pytest.mark.asyncio
    async def test_search_empty_result_preserves_count_zero(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that search with empty results preserves count=0 and does not resolve to None."""
        mock_response = {
            "count": 0,
            "results": [],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=mock_response,
        )

        result = await search("nonexistent_indicator", limit=10)

        assert isinstance(result, EnrichedSearchResponse)
        assert result.total_count == 0
        assert result.count == 0
        assert result.has_more is False
        assert result.error == "No indicators found for: 'nonexistent_indicator'"

    @pytest.mark.asyncio
    async def test_search_with_pagination(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test search with pagination."""
        NUM_ITEMS = 10
        TOTAL_COUNT = 25
        mock_response = {
            "count": TOTAL_COUNT,
            "results": [
                {
                    "idno": f"WB_WDI_SP_POP_{i}",
                    "name": f"Population {i}",
                    "databases": [{"idno": "WB_WDI"}],
                    "description": f"Population indicator {i}",
                    "dimensions": [],
                }
                for i in range(NUM_ITEMS)
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=mock_response,
        )

        result = await search("population", limit=10, offset=0)

        assert result.total_count == TOTAL_COUNT
        assert result.count == NUM_ITEMS
        assert result.has_more is True
        assert result.next_offset == NUM_ITEMS

    @pytest.mark.asyncio
    async def test_search_filters_invalid_items(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that items missing required fields are filtered out."""
        NUM_VALID_ITEMS = 1
        TOTAL_COUNT = 3
        mock_response = {
            "count": TOTAL_COUNT,
            "results": [
                {
                    "idno": "WB_WDI_SP_POP_TOTL",
                    "name": "Population, total",
                    "databases": [{"idno": "WB_WDI"}],
                    "description": "Total population",
                    "dimensions": [],
                },
                {
                    "idno": "WB_WDI_SP_POP_GROW",
                    # Missing name
                    "databases": [{"idno": "WB_WDI"}],
                },
                {
                    # Missing idno
                    "name": "Some indicator",
                    "databases": [{"idno": "WB_WDI"}],
                },
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=mock_response,
        )

        result = await search("population", limit=10)

        assert result.indicators is not None
        assert len(result.indicators) == NUM_VALID_ITEMS  # Only the valid item
        assert result.indicators[0].idno == "WB_WDI_SP_POP_TOTL"

    @pytest.mark.asyncio
    async def test_search_http_error(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test search handles HTTP errors."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            status_code=500,
            text="Internal Server Error",
        )

        result = await search("population")

        assert not result.indicators
        assert result.error is not None
        assert "HTTP 500" in result.error

    @pytest.mark.asyncio
    async def test_search_timeout(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test search handles timeout errors."""
        httpx_mock.add_exception(
            httpx.TimeoutException("Request timeout"),
            url="https://api.test.example.com/portal/v1/public_data360_search",
        )

        result = await search("population")

        assert not result.indicators
        assert result.error is not None
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_search_invalid_json(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test search handles invalid JSON responses."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            status_code=200,
            text="Invalid JSON response",
        )

        result = await search("population")

        assert not result.indicators
        assert result.error is not None
        assert "Failed to parse" in result.error

    @pytest.mark.asyncio
    async def test_search_query_sanitization(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test that query string is sanitized of unsafe special characters."""
        captured_payloads = []

        def capture_callback(request: httpx.Request) -> httpx.Response:
            captured_payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "count": 0,
                    "results": [],
                },
            )

        httpx_mock.add_callback(
            capture_callback,
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
        )

        # Test query with parentheses and currency symbols (unsafe) alongside safe characters (_, -, ,, .)
        await search(
            "GDP per capita (current US$) WB_WDI_NY_GDP_PCAP_CD-2022, test.", limit=5
        )

        assert len(captured_payloads) == 1
        # The parentheses and currency symbols should be replaced by spaces and collapsed,
        # while the underscores, hyphens, commas, and periods are kept.
        assert (
            captured_payloads[0].get("query_string")
            == "GDP per capita current US WB_WDI_NY_GDP_PCAP_CD-2022, test."
        )

    @pytest.mark.asyncio
    async def test_search_empty_query_after_sanitization(self):
        """Test search with query that becomes empty after sanitization returns clean error."""
        response = await search("   $$$   ")
        assert response.error is not None
        assert "Search query cannot be empty" in response.error

    @pytest.mark.asyncio
    async def test_search_n_results_alias_at_default_limit(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that n_results overrides the default limit."""
        ALIAS_LIMIT = 3
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

        await search("population", n_results=ALIAS_LIMIT)

        assert len(captured_payloads) == 1
        assert captured_payloads[0]["items_per_page"] == ALIAS_LIMIT

    @pytest.mark.asyncio
    async def test_search_skip_alias_at_default_offset(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that skip overrides the default offset."""
        ALIAS_OFFSET = 2
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

        await search("population", skip=ALIAS_OFFSET)

        assert len(captured_payloads) == 1
        assert captured_payloads[0]["skip"] == ALIAS_OFFSET

    @pytest.mark.asyncio
    async def test_search_explicit_limit_takes_precedence_over_alias(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that an explicit limit takes precedence when n_results also provided."""
        EXPLICIT_LIMIT = 10
        ALIAS_LIMIT = 3
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

        await search("population", limit=EXPLICIT_LIMIT, n_results=ALIAS_LIMIT)

        assert len(captured_payloads) == 1
        assert captured_payloads[0]["items_per_page"] == EXPLICIT_LIMIT

    @pytest.mark.asyncio
    async def test_search_alias_agrees_with_primary(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that no issue arises when limit and n_results agree."""
        AGREED_LIMIT = 3
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

        await search("population", limit=AGREED_LIMIT, n_results=AGREED_LIMIT)

        assert len(captured_payloads) == 1
        assert captured_payloads[0]["items_per_page"] == AGREED_LIMIT

    @pytest.mark.asyncio
    async def test_search_with_database_filter_success(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test search with a valid database filter that gets resolved."""
        captured_payloads = []

        def capture_callback(request: httpx.Request) -> httpx.Response:
            captured_payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "count": 1,
                    "results": [
                        {
                            "idno": "WB_WDI_SP_POP_TOTL",
                            "name": "Population, total",
                            "databases": [{"idno": "WB_WDI"}],
                            "description": "Total population",
                            "dimensions": [],
                        }
                    ],
                },
            )

        httpx_mock.add_callback(
            capture_callback,
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
        )

        from unittest.mock import patch, AsyncMock
        with patch("data360.providers.get_database_manager") as mock_mgr_getter:
            from unittest.mock import MagicMock
            mock_mgr = MagicMock()
            mock_mgr.resolve_database_ids.return_value = ["WB_WDI"]
            mock_mgr.get_mapping = AsyncMock(return_value={"WB_WDI": "World Development Indicators"})
            mock_mgr_getter.return_value = mock_mgr

            result = await search("population", database="wdi")

        assert isinstance(result, EnrichedSearchResponse)
        assert len(result.indicators) == 1
        assert len(captured_payloads) == 1
        assert captured_payloads[0].get("database_names") == ["World Development Indicators"]
        assert result.error is None

    @pytest.mark.asyncio
    async def test_search_with_multiple_database_filters(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test search with multiple database filters that get resolved."""
        captured_payloads = []

        def capture_callback(request: httpx.Request) -> httpx.Response:
            captured_payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "count": 1,
                    "results": [
                        {
                            "idno": "WB_WDI_SP_POP_TOTL",
                            "name": "Population, total",
                            "databases": [{"idno": "WB_WDI"}],
                            "description": "Total population",
                            "dimensions": [],
                        }
                    ],
                },
            )

        httpx_mock.add_callback(
            capture_callback,
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
        )

        from unittest.mock import patch, AsyncMock
        with patch("data360.providers.get_database_manager") as mock_mgr_getter:
            from unittest.mock import MagicMock
            mock_mgr = MagicMock()
            mock_mgr.resolve_database_ids.return_value = ["WB_WDI", "WB_WGI"]
            mock_mgr.get_mapping = AsyncMock(return_value={
                "WB_WDI": "World Development Indicators",
                "WB_WGI": "Worldwide Governance Indicators"
            })
            mock_mgr_getter.return_value = mock_mgr

            result = await search("population", database="wdi; wgi")

        assert isinstance(result, EnrichedSearchResponse)
        assert len(result.indicators) == 1
        assert len(captured_payloads) == 1
        assert captured_payloads[0].get("database_names") == [
            "World Development Indicators",
            "Worldwide Governance Indicators"
        ]
        assert result.error is None

    @pytest.mark.asyncio
    async def test_search_with_unresolved_database_filter(self):
        """Test search with a database filter that cannot be resolved returns an error."""
        from unittest.mock import patch
        with patch("data360.providers.get_database_manager") as mock_mgr_getter:
            from unittest.mock import MagicMock, AsyncMock
            mock_mgr = MagicMock()
            mock_mgr.resolve_database_ids.side_effect = ValueError("Database 'InvalidDB' could not be resolved.")
            mock_mgr.get_mapping = AsyncMock(return_value={})
            mock_mgr_getter.return_value = mock_mgr

            result = await search("population", database="InvalidDB")

        assert isinstance(result, EnrichedSearchResponse)
        assert result.error is not None
        assert "could not be resolved" in result.error
        assert not result.indicators


class TestSearchDatasets:
    """Tests for search_datasets() function."""

    @pytest.mark.asyncio
    async def test_search_datasets_success(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test successful dataset search request."""
        mock_response = {
            "count": 1,
            "results": [
                {
                    "idno": "WB_FINDEX",
                    "name": "Global Financial Inclusion Database",
                    "description": "Findex data",
                    "data_classification": "public",
                    "data_last_updated": "2024-01-01",
                    "economies_count": 150,
                    "time_period": {"start": 2011, "end": 2021},
                }
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=mock_response,
        )

        response = await search_datasets("findex")

        assert response.error is None
        assert response.count == 1
        assert len(response.items) == 1
        assert response.items[0].idno == "WB_FINDEX"
        assert response.items[0].name == "Global Financial Inclusion Database"

    @pytest.mark.asyncio
    async def test_search_datasets_query_sanitization(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that special characters are sanitized in dataset search queries."""
        captured_payloads = []

        def capture_callback(request: httpx.Request) -> httpx.Response:
            captured_payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "count": 0,
                    "results": [],
                },
            )

        httpx_mock.add_callback(
            capture_callback,
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
        )

        await search_datasets("Findex (database) $2022")

        assert len(captured_payloads) == 1
        assert captured_payloads[0].get("query_string") == "Findex database 2022"

    @pytest.mark.asyncio
    async def test_search_datasets_empty_query(self):
        """Test search_datasets with empty query after sanitization raises validation error."""
        response = await search_datasets("   $$$   ")
        assert response.error is not None
        assert "Search query cannot be empty" in response.error

    @pytest.mark.asyncio
    async def test_search_datasets_http_error(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test HTTP error handling in dataset search."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            status_code=500,
        )

        response = await search_datasets("findex")
        assert response.error is not None
        assert (
            "Server Error" in response.error
            or "500" in response.error
            or "Internal Server Error" in response.error
        )

    @pytest.mark.asyncio
    async def test_search_datasets_exception_classification(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that other exceptions during dataset search are classified robustly."""
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://api.test.example.com/portal/v1/public_data360_search",
        )

        response = await search_datasets("findex")
        assert response.error is not None
        assert "connectivity" in response.error.lower()


class TestGetMetadata:
    """Tests for get_metadata() function."""

    @pytest.mark.asyncio
    async def test_get_metadata_success(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test successful metadata retrieval."""
        metadata_response = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_TOTL",
                        "name": "Population, total",
                        "database_id": "WB_WDI",
                        "definition_long": "Total population",
                    }
                }
            ]
        }

        dimensions_response = {
            "dimensions": [
                {
                    "field_name": "REF_AREA",
                    "field_value": [{"code": "UGA"}, {"code": "KEN"}],
                },
                {
                    "field_name": "UNIT_MEASURE",
                    "field_value": [{"code": "PT"}],
                },
            ]
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )

        # Match URL with query parameters using a callback
        def dimensions_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "POST"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/portal/v1/dimensions"
            ):
                return httpx.Response(200, json=dimensions_response)
            return None

        httpx_mock.add_callback(dimensions_callback)

        result = await get_metadata("WB_WDI", "WB_WDI_SP_POP_TOTL")

        EXPECTED_DISAGGREGATION_COUNT = 2
        assert isinstance(result, MetadataResponse)
        assert result.indicator_metadata is not None
        assert result.indicator_metadata["idno"] == "WB_WDI_SP_POP_TOTL"
        assert len(result.disaggregation_options) == EXPECTED_DISAGGREGATION_COUNT
        assert result.error is None

    @pytest.mark.asyncio
    async def test_get_metadata_no_metadata_found(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test metadata retrieval when no metadata is found."""
        metadata_response = {"value": []}

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )

        # Even when metadata is not found, dimensions is still fetched
        def empty_dimensions_callback(
            request: httpx.Request,
        ) -> httpx.Response | None:
            if (
                request.method == "POST"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/portal/v1/dimensions"
            ):
                return httpx.Response(200, json={"dimensions": []})
            return None

        httpx_mock.add_callback(empty_dimensions_callback)

        result = await get_metadata("WB_WDI", "INVALID_ID")

        assert result.indicator_metadata is None
        assert result.error is not None
        assert "No metadata found" in result.error

    @pytest.mark.asyncio
    async def test_get_metadata_filters_disaggregations(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that _Z values are filtered from disaggregations."""
        metadata_response = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_TOTL",
                        "name": "Population, total",
                        "database_id": "WB_WDI",
                    }
                }
            ]
        }

        dimensions_response = {
            "dimensions": [
                {
                    "field_name": "REF_AREA",
                    "field_value": [{"code": "_Z"}, {"code": "UGA"}],
                },
                {
                    "field_name": "UNIT_MEASURE",
                    "field_value": [{"code": "_T"}],
                },
            ]
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )

        # Match URL with query parameters using a callback
        def dimensions_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "POST"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/portal/v1/dimensions"
            ):
                return httpx.Response(200, json=dimensions_response)
            return None

        httpx_mock.add_callback(dimensions_callback)

        result = await get_metadata("WB_WDI", "WB_WDI_SP_POP_TOTL")

        EXPECTED_FILTERED_COUNT = 2
        assert len(result.disaggregation_options) == EXPECTED_FILTERED_COUNT
        # Verify _Z was filtered out by _get_valid_disaggregations
        field_names = [opt["field_name"] for opt in result.disaggregation_options]
        # REF_AREA is summarized by _strip_disaggregation (count + sample)
        ref_area = next(
            opt
            for opt in result.disaggregation_options
            if opt["field_name"] == "REF_AREA"
        )
        assert ref_area["count"] == 1
        assert "UGA" in ref_area["sample"]
        # UNIT_MEASURE is preserved as-is
        unit = next(
            opt
            for opt in result.disaggregation_options
            if opt["field_name"] == "UNIT_MEASURE"
        )
        assert unit["field_value"] == ["_T"]

    @pytest.mark.asyncio
    async def test_get_metadata_http_error_metadata(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test metadata retrieval handles HTTP errors for metadata endpoint."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            status_code=500,
            text="Internal Server Error",
        )

        # Even when metadata fetch fails, dimensions is still attempted
        def empty_dimensions_callback(
            request: httpx.Request,
        ) -> httpx.Response | None:
            if (
                request.method == "POST"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/portal/v1/dimensions"
            ):
                return httpx.Response(200, json={"dimensions": []})
            return None

        httpx_mock.add_callback(empty_dimensions_callback)

        result = await get_metadata("WB_WDI", "WB_WDI_SP_POP_TOTL")

        assert result.error is not None
        assert "HTTP" in result.error

    @pytest.mark.asyncio
    async def test_get_metadata_http_error_disaggregation(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test metadata retrieval handles HTTP errors for disaggregation endpoint."""
        metadata_response = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_TOTL",
                        "name": "Population, total",
                        "database_id": "WB_WDI",
                    }
                }
            ]
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )

        def error_dimensions_callback(
            request: httpx.Request,
        ) -> httpx.Response | None:
            if (
                request.method == "POST"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/portal/v1/dimensions"
            ):
                return httpx.Response(500, text="Internal Server Error")
            return None

        httpx_mock.add_callback(error_dimensions_callback)

        result = await get_metadata("WB_WDI", "WB_WDI_SP_POP_TOTL")

        assert result.indicator_metadata is not None
        assert result.error is not None
        assert "HTTP" in result.error


class TestGetData:
    """Tests for get_data() function."""

    @pytest.mark.asyncio
    async def test_get_data_success(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test successful data retrieval."""
        mock_response = {
            "value": [
                {"REF_AREA": "UGA", "TIME_PERIOD": "2020", "OBS_VALUE": 1000},
                {"REF_AREA": "UGA", "TIME_PERIOD": "2021", "OBS_VALUE": 1100},
            ],
            "count": 2,
        }

        # Mock metadata response (called first)
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={
                "value": [
                    {
                        "series_description": {
                            "idno": "WB_WDI_SP_POP_TOTL",
                            "name": "Pop",
                        }
                    }
                ]
            },
        )

        # Mock dimensions response (called during metadata fetch)
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={
                "dimensions": [
                    {"field_name": "REF_AREA", "field_value": [{"code": "UGA"}]}
                ]
            },
        )

        # Mock data response
        httpx_mock.add_response(
            method="GET", url=re.compile(r".*/data\?.*"), json=mock_response
        )

        result = await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL")

        EXPECTED_DATA_COUNT = 2
        assert isinstance(result, IndicatorDataResponse)
        assert result.data is not None
        assert len(result.data) == EXPECTED_DATA_COUNT
        assert result.count == EXPECTED_DATA_COUNT
        assert result.error is None

    @pytest.mark.asyncio
    async def test_get_data_with_disaggregation_filters(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test data retrieval with disaggregation filters."""
        mock_response = {
            "value": [
                {"REF_AREA": "UGA", "TIME_PERIOD": "2020", "OBS_VALUE": 1000},
            ],
            "count": 1,
        }

        # Mock metadata
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_WDI_SP_POP_TOTL"}}]},
        )

        # Mock dimensions
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={
                "dimensions": [
                    {"field_name": "REF_AREA", "field_value": [{"code": "UGA"}]},
                    {"field_name": "UNIT_MEASURE", "field_value": [{"code": "PT"}]},
                ]
            },
        )

        # Mock data response
        def data_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/data"
            ):
                # Verify params in URL
                assert "REF_AREA=UGA" in str(request.url)
                assert "UNIT_MEASURE=PT" in str(request.url)
                return httpx.Response(200, json=mock_response)
            return None

        httpx_mock.add_callback(data_callback)

        result = await get_data(
            "WB_WDI",
            "WB_WDI_SP_POP_TOTL",
            disaggregation_filters={"REF_AREA": "UGA", "UNIT_MEASURE": "PT"},
        )

        assert result.data is not None
        assert len(result.data) == 1

    @pytest.mark.asyncio
    async def test_get_data_with_empty_string_filter_uses_default(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that empty string filters are treated as unspecified and get smart defaults."""
        mock_response = {
            "value": [
                {"REF_AREA": "UGA", "TIME_PERIOD": "2020", "OBS_VALUE": 1000},
            ],
            "count": 1,
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_WDI_SP_POP_TOTL"}}]},
        )

        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={
                "dimensions": [
                    {
                        "field_name": "URBANISATION",
                        "field_value": [{"code": "_T"}, {"code": "URB"}],
                    },
                ]
            },
        )

        def data_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/data"
            ):
                assert "URBANISATION=_T" in str(request.url)
                return httpx.Response(200, json=mock_response)
            return None

        httpx_mock.add_callback(data_callback)

        result = await get_data(
            "WB_WDI",
            "WB_WDI_SP_POP_TOTL",
            disaggregation_filters={"URBANISATION": ""},
        )

        assert result.data is not None
        assert result.failed_validation is None

    @pytest.mark.asyncio
    async def test_get_data_pagination(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test data retrieval with pagination."""

        # Mock metadata & disaggregation (needed for get_data to proceed)
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_WDI_SP_POP_TOTL"}}]},
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        # First page response
        def first_page_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/data"
                and request.url.params.get("skip", "0") == "0"
            ):
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "REF_AREA": "UGA",
                                "TIME_PERIOD": f"201{i}",
                                "OBS_VALUE": 1000 + i,
                            }
                            for i in range(5)
                        ],
                        "count": 10,  # Total count is 10, so there's more data
                    },
                )
            return None

        # Register callback
        httpx_mock.add_callback(first_page_callback)

        # Pass explicit time range to avoid smart defaults filtering
        result = await get_data(
            "WB_WDI", "WB_WDI_SP_POP_TOTL", start_year=2010, end_year=2019
        )

        EXPECTED_TOTAL_COUNT = 5  # First page only
        assert result.data is not None
        assert len(result.data) == EXPECTED_TOTAL_COUNT

    @pytest.mark.asyncio
    async def test_get_data_empty_response(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test data retrieval with empty response."""

        # Mocks
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_WDI_SP_POP_TOTL"}}]},
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        def empty_data_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/data"
            ):
                return httpx.Response(200, json={"value": [], "count": 0})
            return None

        httpx_mock.add_callback(empty_data_callback)

        result = await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL")

        assert result.data is not None
        assert len(result.data) == 0
        assert result.count == 0

    @pytest.mark.asyncio
    async def test_get_data_http_error(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test data retrieval handles HTTP errors."""

        # Mocks for metadata (successful, so we proceed to data)
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_WDI_SP_POP_TOTL"}}]},
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        # Data error
        def error_data_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/data"
            ):
                return httpx.Response(500, text="Internal Server Error")
            return None

        httpx_mock.add_callback(error_data_callback)

        with pytest.raises(Data360MCPError) as exc_info:
            await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL")
        assert "HTTP 500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_data_invalid_json(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test data retrieval handles invalid JSON."""

        # Mocks
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_WDI_SP_POP_TOTL"}}]},
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        def invalid_json_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/data"
            ):
                return httpx.Response(200, text="Invalid JSON")
            return None

        httpx_mock.add_callback(invalid_json_callback)

        with pytest.raises(Data360MCPError) as exc_info:
            await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL")
        assert "parse" in str(exc_info.value).lower()


# NOTE: TestCodelistManager tests removed - CodelistManager was replaced with
# ReferenceAreaManager in providers.py with a different API.
# New tests for ReferenceAreaManager should be added in test_providers.py


# ---------------------------------------------------------------------------
# B1 — get_data() graceful degradation on disaggregation-only errors (Issue #59)
# ---------------------------------------------------------------------------


class TestGetDataResilience:
    """Tests for Issue #59: get_data should not abort when only disaggregation fails."""

    @pytest.mark.asyncio
    async def test_get_data_proceeds_when_disaggregation_fails_but_metadata_valid(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """When indicator metadata is found but disaggregation errors, data fetch still proceeds."""
        # Metadata succeeds
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={
                "value": [
                    {
                        "series_description": {
                            "idno": "WB_WDI_SP_POP_TOTL",
                            "name": "Pop",
                        }
                    }
                ]
            },
        )
        # Disaggregation fails with 500
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            status_code=500,
            text="Internal Server Error",
        )
        # Data fetch succeeds
        httpx_mock.add_response(
            method="GET",
            url=re.compile(r".*/data\?.*"),
            json={
                "value": [{"REF_AREA": "KEN", "TIME_PERIOD": "2020", "OBS_VALUE": 5000}]
            },
        )

        result = await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL")

        # Should have data despite disaggregation error
        assert result.data is not None
        assert len(result.data) >= 1
        assert result.error is None

    @pytest.mark.asyncio
    async def test_get_data_aborts_when_indicator_metadata_missing(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """When indicator metadata is missing (indicator not found), abort with error."""
        # Metadata returns empty (indicator not found)
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={"value": []},
        )
        # Disaggregation returns 200 empty (doesn't matter)
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        result = await get_data("WB_WDI", "NONEXISTENT_INDICATOR")

        # Should abort — indicator not found
        assert result.data is None or result.data == []
        assert result.error is not None

    # ---------------------------------------------------------------------------
    # C1 — country_code parameter on get_data()
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_data_end_year_only_resolves_five_year_window(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Only end_year should not send timePeriodFrom=None; use 5-year window ending at end_year."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={
                "value": [
                    {
                        "series_description": {
                            "idno": "WB_WDI_SP_POP_TOTL",
                            "name": "Pop",
                        }
                    }
                ]
            },
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        captured_urls: list[str] = []

        def data_callback(request: httpx.Request) -> httpx.Response | None:
            if request.method == "GET" and request.url.path == "/data":
                captured_urls.append(str(request.url))
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "REF_AREA": "PHL",
                                "TIME_PERIOD": "2018",
                                "OBS_VALUE": 16.7,
                            }
                        ]
                    },
                )
            return None

        httpx_mock.add_callback(data_callback)

        result = await get_data(
            "WB_WDI",
            "WB_WDI_SP_POP_TOTL",
            country_code="PHL",
            end_year=2019,
        )

        assert len(captured_urls) == 1
        assert "timePeriodFrom=2015" in captured_urls[0]
        assert "timePeriodTo=2019" in captured_urls[0]
        assert result.error is None
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_get_data_country_code_param_sets_ref_area(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """country_code parameter should be passed as REF_AREA in the data request URL."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={
                "value": [
                    {
                        "series_description": {
                            "idno": "WB_WDI_SP_POP_TOTL",
                            "name": "Pop",
                        }
                    }
                ]
            },
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        captured_urls: list[str] = []

        def data_callback(request: httpx.Request) -> httpx.Response | None:
            if request.method == "GET" and request.url.path == "/data":
                captured_urls.append(str(request.url))
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "REF_AREA": "KEN",
                                "TIME_PERIOD": "2020",
                                "OBS_VALUE": 100,
                            },
                            {
                                "REF_AREA": "MAR",
                                "TIME_PERIOD": "2020",
                                "OBS_VALUE": 200,
                            },
                        ]
                    },
                )
            return None

        httpx_mock.add_callback(data_callback)

        result = await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL", country_code="KEN;MAR")

        assert len(captured_urls) == 1
        assert (
            "REF_AREA=KEN%2CMAR" in captured_urls[0]
            or "REF_AREA=KEN,MAR" in captured_urls[0]
        )
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_get_data_ref_area_filter_drops_aggregates_when_unpinned(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """member_economies_only removes regional aggregate rows from an unpinned REF_AREA page."""
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={
                "value": [
                    {
                        "series_description": {
                            "idno": "WB_WDI_SP_POP_TOTL",
                            "name": "Pop",
                        }
                    }
                ]
            },
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )
        httpx_mock.add_response(
            method="GET",
            url=re.compile(r".*/data\?.*"),
            json={
                "value": [
                    {"REF_AREA": "EAS", "TIME_PERIOD": "2020", "OBS_VALUE": 1e9},
                    {"REF_AREA": "KEN", "TIME_PERIOD": "2020", "OBS_VALUE": 5000},
                ]
            },
        )

        result = await get_data(
            "WB_WDI",
            "WB_WDI_SP_POP_TOTL",
            ref_area_filter="member_economies_only",
        )

        assert result.error is None
        assert result.data is not None
        areas = {r["REF_AREA"] for r in result.data}
        assert "EAS" not in areas
        assert "KEN" in areas


class TestCountryNamesInSearch:
    """Tests that search results carry resolved country_names mapping."""

    @pytest.mark.asyncio
    async def test_search_resolves_country_names(
        self, httpx_mock: pytest_httpx.HTTPXMock, monkeypatch
    ):
        mock_response = {
            "count": 1,
            "results": [
                {
                    "idno": "WB_GS_SP_POP_TOTL",
                    "name": "Population, total",
                    "databases": [{"idno": "WB_GS"}],
                    "description": "Total population",
                    "dimensions": [],
                }
            ],
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=mock_response,
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/dimensions",
            json={"dimensions": []},
        )

        # Mock CodelistManager.get_label to return custom names
        from data360.providers import CodelistManager
        monkeypatch.setattr(
            CodelistManager,
            "get_label",
            lambda self, dim, code: "Japan" if code == "JPN" else "Philippines" if code == "PHL" else code
        )

        result = await search("population", required_country="JPN;PHL")

        assert isinstance(result, EnrichedSearchResponse)
        assert result.country_names == {"JPN": "Japan", "PHL": "Philippines"}


class TestDatabaseNameInSearch:
    """Tests that search results carry the correct database_name for each indicator."""

    @pytest.mark.asyncio
    async def test_known_database_id_resolves_to_correct_name(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """WB_GS must resolve to 'Gender Statistics', not a guess."""
        mock_response = {
            "count": 1,
            "results": [
                {
                    "idno": "WB_GS_SP_POP_TOTL",
                    "name": "Population, total",
                    "databases": [{"idno": "WB_GS"}],
                    "description": "Total population",
                    "dimensions": [],
                }
            ],
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=mock_response,
        )

        result = await search("population")

        assert isinstance(result, EnrichedSearchResponse)
        assert len(result.indicators) == 1
        indicator = result.indicators[0]
        assert indicator.database_id == "WB_GS"
        assert indicator.database_name == "Gender Statistics"

    @pytest.mark.asyncio
    async def test_unknown_database_id_returns_none_not_hallucination(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """An unregistered database_id must yield database_name=None, not a guessed string."""
        mock_response = {
            "count": 1,
            "results": [
                {
                    "idno": "UNKNOWN_DB_INDICATOR",
                    "name": "Some indicator",
                    "databases": [{"idno": "UNKNOWN_DB"}],
                    "description": "Definition",
                    "dimensions": [],
                }
            ],
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=mock_response,
        )

        result = await search("some indicator")

        assert isinstance(result, EnrichedSearchResponse)
        assert len(result.indicators) == 1
        # Must be None — not an invented string
        assert result.indicators[0].database_name is None

    @pytest.mark.asyncio
    async def test_all_known_databases_resolve_to_non_empty_name(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Every database_id dynamically fetched must resolve to a non-empty name."""
        from data360.providers import get_database_mapping

        mapping = await get_database_mapping()
        registered_ids = list(mapping.keys())
        # SearchRequest enforces limit <= 50; fallback databases.json can exceed that.
        limit = min(len(registered_ids), 50)
        slice_ids = registered_ids[:limit]

        results = [
            {
                "idno": f"{db_id}_INDICATOR",
                "name": f"Indicator for {db_id}",
                "databases": [{"idno": db_id}],
                "description": "Definition",
                "dimensions": [],
            }
            for db_id in slice_ids
        ]
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json={"count": len(results), "results": results},
        )

        result = await search("indicator", limit=limit)

        assert isinstance(result, EnrichedSearchResponse)
        for ind in result.indicators:
            assert ind.database_name is not None, (
                f"Expected database_name for id '{ind.database_id}', got None"
            )
            assert ind.database_name == mapping[ind.database_id]


class TestDatabaseNameInMetadata:
    """Tests that get_metadata injects database_name into indicator_metadata."""

    @pytest.mark.asyncio
    async def test_get_metadata_injects_database_name(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """indicator_metadata must contain database_name resolved from database_id."""
        metadata_response = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_GS_INDICATOR",
                        "name": "Some indicator",
                        "database_id": "WB_GS",
                        "definition_long": "Full definition",
                    }
                }
            ]
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        captured_urls: list[str] = []

        def data_callback(request: httpx.Request) -> httpx.Response | None:
            if request.method == "GET" and request.url.path == "/data":
                captured_urls.append(str(request.url))
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "REF_AREA": "KEN",
                                "TIME_PERIOD": "2020",
                                "OBS_VALUE": 100,
                            },
                            {
                                "REF_AREA": "MAR",
                                "TIME_PERIOD": "2020",
                                "OBS_VALUE": 200,
                            },
                        ]
                    },
                )
            return None

        httpx_mock.add_callback(data_callback)

        result = await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL", country_code="KEN,MAR")

        assert len(captured_urls) == 1
        assert (
            "REF_AREA=KEN%2CMAR" in captured_urls[0]
            or "REF_AREA=KEN,MAR" in captured_urls[0]
        )
        assert result.data is not None


# ---------------------------------------------------------------------------
# D1 — get_data_api_url() parity fix (same Issue #59 resilience)
# ---------------------------------------------------------------------------


class TestGetDataApiUrlResilience:
    @pytest.mark.asyncio
    async def test_get_data_api_url_proceeds_on_nonfatal_metadata_error(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """get_data_api_url should not raise when indicator metadata exists but disaggregation fails."""
        from data360.api import get_data_api_url

        # Metadata succeeds
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={
                "value": [
                    {
                        "series_description": {
                            "idno": "WB_WDI_SP_POP_TOTL",
                            "name": "Pop",
                        }
                    }
                ]
            },
        )
        # Disaggregation fails
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            status_code=500,
            text="Internal Server Error",
        )

        # Should not raise — returns a URL string
        url = await get_data_api_url("WB_WDI", "WB_WDI_SP_POP_TOTL")
        assert isinstance(url, str)
        assert "WB_WDI" in url
        assert "WB_WDI_SP_POP_TOTL" in url

    @pytest.mark.asyncio
    async def test_get_data_api_url_raises_when_indicator_not_found(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """get_data_api_url should raise ValueError when indicator metadata is missing."""
        from data360.api import get_data_api_url

        # Metadata returns empty
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={"value": []},
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        with pytest.raises(ValueError, match="not found"):
            await get_data_api_url("WB_WDI", "NONEXISTENT_INDICATOR")


class TestDatabaseNameInMetadata:
    """Tests that get_metadata injects database_name into indicator_metadata."""

    @pytest.mark.asyncio
    async def test_get_metadata_injects_database_name(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """indicator_metadata must contain database_name resolved from database_id."""
        metadata_response = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_GS_INDICATOR",
                        "name": "Some indicator",
                        "database_id": "WB_GS",
                        "definition_long": "Full definition",
                    }
                }
            ]
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        result = await get_metadata("WB_GS", "WB_GS_INDICATOR")

        assert result.indicator_metadata is not None
        assert result.indicator_metadata.get("database_name") == "Gender Statistics"

    @pytest.mark.asyncio
    async def test_get_metadata_database_name_survives_select_fields_filter(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """database_name must be retained even when select_fields restricts other keys."""
        metadata_response = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_GS_INDICATOR",
                        "name": "Some indicator",
                        "database_id": "WB_GS",
                        "definition_long": "Full definition",
                        "periodicity": "Annual",
                    }
                }
            ]
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        # Only request 'name' — database_name should still be included
        result = await get_metadata("WB_GS", "WB_GS_INDICATOR", select_fields=["name"])

        assert result.indicator_metadata is not None
        assert "name" in result.indicator_metadata
        assert "periodicity" not in result.indicator_metadata
        assert result.indicator_metadata.get("database_name") == "Gender Statistics"

    @pytest.mark.asyncio
    async def test_get_metadata_unknown_database_id_gives_none(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """An unregistered database_id must yield database_name=None in metadata."""
        metadata_response = {
            "value": [
                {
                    "series_description": {
                        "idno": "UNKNOWN_DB_IND",
                        "name": "Indicator",
                        "database_id": "UNKNOWN_DB",
                    }
                }
            ]
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )
        httpx_mock.add_response(
            method="POST",
            url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": []},
        )

        result = await get_metadata("UNKNOWN_DB", "UNKNOWN_DB_IND")

        assert result.indicator_metadata is not None
        assert result.indicator_metadata.get("database_name") is None


class TestDimensionsResilienceAndParsing:
    """Reproduction tests for covers_country validation bug and empty dimensions resilience."""

    @pytest.mark.asyncio
    async def test_covers_country_verification_succeeds_for_group(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that covers_country resolves to True when the country is present in dimensions."""
        from data360.api import search

        # 1. Mock search results (SearchV3 structure, no ref_country)
        search_response = {
            "count": 1,
            "results": [
                {
                    "idno": "WB_WDI_SP_POP_TOTL",
                    "name": "Population, total",
                    "databases": [{"idno": "WB_WDI"}],
                    "description": "Total population",
                    "dimensions": [],
                }
            ],
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=search_response,
        )

        # 2. Mock dimensions endpoint returning a list of country codes under REF_AREA
        # We put JPN at the end to ensure grouping/early-termination bugs are caught.
        dimensions_response = {
            "dimensions": [
                {
                    "field_name": "REF_AREA",
                    "label_name": "REF_AREA",
                    "field_value": [
                        {"code": "ABW"},
                        {"code": "AFE"},
                        {"code": "JPN"},
                    ],
                }
            ]
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/dimensions",
            json=dimensions_response,
        )

        # 3. Perform search with required_country="JPN;USA"
        result = await search(query="population", required_country="JPN;USA")

        assert isinstance(result, EnrichedSearchResponse)
        assert result.indicators is not None
        assert len(result.indicators) == 1
        ind = result.indicators[0]
        # covers_country should be a dictionary resolving JPN to True and USA to False
        assert ind.covers_country == {"JPN": True, "USA": False}

    @pytest.mark.asyncio
    async def test_covers_country_handles_raw_string_ref_country(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that covers_country correctly parses raw strings in ref_country list."""
        from data360.api import search

        search_response = {
            "count": 1,
            "results": [
                {
                    "idno": "WB_WDI_SP_POP_TOTL",
                    "name": "Population, total",
                    "databases": [{"idno": "WB_WDI"}],
                    "description": "Total population",
                    "dimensions": [],
                    "ref_country": ["JPN", "USA"],
                }
            ],
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
            json=search_response,
        )

        # Mock dimensions endpoint for verification
        dimensions_response = {
            "dimensions": [
                {
                    "field_name": "REF_AREA",
                    "label_name": "REF_AREA",
                    "field_value": [
                        {"code": "JPN"},
                        {"code": "USA"},
                    ],
                }
            ]
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/dimensions",
            json=dimensions_response,
        )

        result = await search(query="population", required_country="JPN;CAN")

        assert isinstance(result, EnrichedSearchResponse)
        assert result.indicators is not None
        assert len(result.indicators) == 1
        ind = result.indicators[0]
        assert ind.covers_country == {"JPN": True, "CAN": False}

    @pytest.mark.asyncio
    async def test_get_disaggregation_handles_400_gracefully(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that get_disaggregation returns empty dimensions on 400 from dimensions API."""
        from data360.api import get_disaggregation

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/dimensions",
            status_code=400,
            text='{"code":"400","message":"Error Dimensions data is empty for dataset"}',
        )

        res = await get_disaggregation("WB_WDI", "WB_WDI_SP_POP_TOTL")
        assert res == {"dimensions": []}

    @pytest.mark.asyncio
    async def test_get_disaggregation_handles_404_gracefully(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that get_disaggregation returns empty dimensions on 404 from dimensions API."""
        from data360.api import get_disaggregation

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/dimensions",
            status_code=404,
            text="Not Found",
        )

        res = await get_disaggregation("WB_WDI", "WB_WDI_SP_POP_TOTL")
        assert res == {"dimensions": []}

    @pytest.mark.asyncio
    async def test_get_metadata_handles_dimensions_400_gracefully(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test that get_metadata succeeds even if dimensions API returns 400 Bad Request."""
        from data360.api import get_metadata

        metadata_response = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_TOTL",
                        "name": "Population, total",
                        "database_id": "WB_WDI",
                    }
                }
            ]
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/dimensions",
            status_code=400,
            text='{"code":"400","message":"Error Dimensions data is empty for dataset"}',
        )

        result = await get_metadata("WB_WDI", "WB_WDI_SP_POP_TOTL")
        assert result.indicator_metadata is not None
        assert result.disaggregation_options == []
        assert result.error is None

    @pytest.mark.asyncio
    async def test_dimensions_api_cache_ttl(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Verify that dimensions API requests are cached and use cachetools.TTLCache."""
        from data360.api import get_metadata

        metadata_response = {
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_TOTL",
                        "name": "Population, total",
                        "database_id": "WB_WDI",
                    }
                }
            ]
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/dimensions",
            json={
                "dimensions": [{"field_name": "SEX", "field_value": [{"code": "_T"}]}]
            },
        )
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )

        # Clear the metadata cache so get_metadata does not hit the metadata cache itself,
        # forcing it to run the dimensions fetch logic.
        from data360.api import _metadata_cache, _metadata_cache_lock

        with _metadata_cache_lock:
            _metadata_cache.clear()

        # Call get_metadata once: will fetch metadata and fetch dimensions (uncached)
        await get_metadata("WB_WDI", "WB_WDI_SP_POP_TOTL")

        # Clear the metadata cache again, but NOT the dimensions cache
        with _metadata_cache_lock:
            _metadata_cache.clear()

        # Call get_metadata again: will fetch metadata but reuse cached dimensions
        await get_metadata("WB_WDI", "WB_WDI_SP_POP_TOTL")

        # Verify only 1 request was sent to the dimensions API endpoint
        requests = httpx_mock.get_requests()
        dim_reqs = [r for r in requests if "portal/v1/dimensions" in str(r.url)]
        assert len(dim_reqs) == 1

    @pytest.mark.asyncio
    async def test_dimensions_api_cache_edge_cases(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Verify:
        1. HTTP 500 status code propagation, and that it's NOT cached.
        2. Blank/empty response body is handled and returns empty dimensions.
        3. Concurrent calls to the same endpoint are deduplicated.
        """
        import asyncio
        import json

        import httpx

        from data360.api import (
            _dimensions_api_cache,
            _dimensions_api_cache_lock,
            _fetch_dimensions_with_cache,
        )

        # --- 1. HTTP 500 Propagation and No Caching ---
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/dimensions",
            status_code=500,
        )

        with pytest.raises(httpx.HTTPStatusError):
            await _fetch_dimensions_with_cache("DB_FAIL", "IND_FAIL")

        with _dimensions_api_cache_lock:
            assert ("DB_FAIL", "IND_FAIL") not in _dimensions_api_cache

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/dimensions",
            status_code=200,
            json={"dimensions": []},
        )
        res = await _fetch_dimensions_with_cache("DB_FAIL", "IND_FAIL")
        assert res == {"dimensions": []}

        # --- 2. Blank / Empty Response Body ---
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/dimensions",
            status_code=200,
            content=b"",
        )
        res_empty = await _fetch_dimensions_with_cache("DB_EMPTY", "IND_EMPTY")
        assert res_empty == {"dimensions": []}

        # --- 3. Concurrent Requests Deduplication ---
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/portal/v1/dimensions",
            status_code=200,
            json={"dimensions": [{"field_name": "CONCURRENT", "field_value": ["1"]}]},
        )

        res1, res2 = await asyncio.gather(
            _fetch_dimensions_with_cache("DB_CONC", "IND_CONC"),
            _fetch_dimensions_with_cache("DB_CONC", "IND_CONC"),
        )

        assert res1 == res2
        assert res1["dimensions"][0]["field_name"] == "CONCURRENT"

        requests = httpx_mock.get_requests()
        dim_reqs = [r for r in requests if "portal/v1/dimensions" in str(r.url)]

        conc_reqs = []
        for req in dim_reqs:
            try:
                body = json.loads(req.content.decode("utf-8"))
                if body.get("database_id") == "DB_CONC":
                    conc_reqs.append(req)
            except Exception:
                pass

        assert len(conc_reqs) == 1
