"""Tests for data360.api module."""

import json
import re

import httpx
import pytest
import pytest_httpx
from data360.api import (
    _get_valid_disaggregations,
    _strip_data_row,
    get_data,
    get_metadata,
    search,
)
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


class TestSearch:
    """Tests for search() function."""

    @pytest.mark.asyncio
    async def test_search_success(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test successful search request."""
        NUM_ITEMS = 2
        mock_response = {
            "@odata.context": "https://api.test.example.com/$metadata",
            "@odata.count": NUM_ITEMS,
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_TOTL",
                        "name": "Population, total",
                        "database_id": "WB_WDI",
                        "definition_long": "Total population",
                        "dimensions": [],
                    }
                },
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_GROW",
                        "name": "Population growth",
                        "database_id": "WB_WDI",
                        "definition_long": "Population growth rate",
                        "dimensions": [],
                    }
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
    async def test_search_with_pagination(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test search with pagination."""
        NUM_ITEMS = 10
        TOTAL_COUNT = 25
        mock_response = {
            "@odata.context": "https://api.test.example.com/$metadata",
            "@odata.count": TOTAL_COUNT,
            "value": [
                {
                    "series_description": {
                        "idno": f"WB_WDI_SP_POP_{i}",
                        "name": f"Population {i}",
                        "database_id": "WB_WDI",
                        "definition_long": f"Population indicator {i}",
                        "dimensions": [],
                    }
                }
                for i in range(NUM_ITEMS)
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/searchv2",
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
            "@odata.context": "https://api.test.example.com/$metadata",
            "@odata.count": TOTAL_COUNT,
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_TOTL",
                        "name": "Population, total",
                        "database_id": "WB_WDI",
                        "definition_long": "Total population",
                        "dimensions": [],
                    }
                },
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_GROW",
                        # Missing name
                        "database_id": "WB_WDI",
                    }
                },
                {
                    "series_description": {
                        # Missing idno
                        "name": "Some indicator",
                        "database_id": "WB_WDI",
                    }
                },
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/searchv2",
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
            url="https://api.test.example.com/searchv2",
            status_code=500,
            text="Internal Server Error",
        )

        result = await search("population")

        assert not result.indicators
        assert result.error is not None
        assert "HTTP error 500" in result.error

    @pytest.mark.asyncio
    async def test_search_timeout(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test search handles timeout errors."""
        httpx_mock.add_exception(
            httpx.TimeoutException("Request timeout"),
            url="https://api.test.example.com/searchv2",
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
            url="https://api.test.example.com/searchv2",
            status_code=200,
            text="Invalid JSON response",
        )

        result = await search("population")

        assert not result.indicators
        assert result.error is not None
        assert "Failed to parse" in result.error

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
                    "@odata.context": "https://api.test.example.com/$metadata",
                    "@odata.count": 0,
                    "value": [],
                },
            )

        httpx_mock.add_callback(capture_callback, method="POST")

        await search("population", n_results=ALIAS_LIMIT)

        assert len(captured_payloads) == 1
        assert captured_payloads[0]["top"] == ALIAS_LIMIT

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
                    "@odata.context": "https://api.test.example.com/$metadata",
                    "@odata.count": 0,
                    "value": [],
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
                    "@odata.context": "https://api.test.example.com/$metadata",
                    "@odata.count": 0,
                    "value": [],
                },
            )

        httpx_mock.add_callback(capture_callback, method="POST")

        await search("population", limit=EXPLICIT_LIMIT, n_results=ALIAS_LIMIT)

        assert len(captured_payloads) == 1
        assert captured_payloads[0]["top"] == EXPLICIT_LIMIT

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
                    "@odata.context": "https://api.test.example.com/$metadata",
                    "@odata.count": 0,
                    "value": [],
                },
            )

        httpx_mock.add_callback(capture_callback, method="POST")

        await search("population", limit=AGREED_LIMIT, n_results=AGREED_LIMIT)

        assert len(captured_payloads) == 1
        assert captured_payloads[0]["top"] == AGREED_LIMIT


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

        disaggregation_response = [
            {"field_value": ["UGA"], "field_name": "REF_AREA"},
            {"field_value": ["KEN"], "field_name": "REF_AREA"},
            {"field_value": ["PT"], "field_name": "UNIT_MEASURE"},
        ]

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )

        # Match URL with query parameters using a callback
        def disaggregation_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/disaggregation"
                and "datasetId" in request.url.params
                and "indicatorId" in request.url.params
            ):
                return httpx.Response(200, json=disaggregation_response)
            return None

        httpx_mock.add_callback(disaggregation_callback)

        result = await get_metadata("WB_WDI_SP_POP_TOTL", "WB_WDI")

        EXPECTED_DISAGGREGATION_COUNT = 3
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

        # Even when metadata is not found, disaggregation is still fetched
        def empty_disaggregation_callback(
            request: httpx.Request,
        ) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/disaggregation"
            ):
                return httpx.Response(200, json=[])
            return None

        httpx_mock.add_callback(empty_disaggregation_callback)

        result = await get_metadata("INVALID_ID", "WB_WDI")

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

        disaggregation_response = [
            {"field_value": ["_Z"], "field_name": "REF_AREA"},  # Should be filtered
            {"field_value": ["UGA"], "field_name": "REF_AREA"},
            {
                "field_value": ["_T"],
                "field_name": "UNIT_MEASURE",
            },  # Should not be filtered
        ]

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json=metadata_response,
        )

        # Match URL with query parameters using a callback
        def disaggregation_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/disaggregation"
                and "datasetId" in request.url.params
                and "indicatorId" in request.url.params
            ):
                return httpx.Response(200, json=disaggregation_response)
            return None

        httpx_mock.add_callback(disaggregation_callback)

        result = await get_metadata("WB_WDI_SP_POP_TOTL", "WB_WDI")

        EXPECTED_FILTERED_COUNT = 2
        assert len(result.disaggregation_options) == EXPECTED_FILTERED_COUNT
        # Verify _Z was filtered out by _get_valid_disaggregations
        field_names = [opt["field_name"] for opt in result.disaggregation_options]
        # REF_AREA is summarized by _strip_disaggregation (count + sample)
        ref_area = next(opt for opt in result.disaggregation_options if opt["field_name"] == "REF_AREA")
        assert ref_area["count"] == 1
        assert "UGA" in ref_area["sample"]
        # UNIT_MEASURE is preserved as-is
        unit = next(opt for opt in result.disaggregation_options if opt["field_name"] == "UNIT_MEASURE")
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

        # Even when metadata fetch fails, disaggregation is still attempted
        def empty_disaggregation_callback(
            request: httpx.Request,
        ) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/disaggregation"
            ):
                return httpx.Response(200, json=[])
            return None

        httpx_mock.add_callback(empty_disaggregation_callback)

        result = await get_metadata("WB_WDI_SP_POP_TOTL", "WB_WDI")

        assert result.error is not None
        assert "HTTP error" in result.error

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

        def error_disaggregation_callback(
            request: httpx.Request,
        ) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/disaggregation"
                and "datasetId" in request.url.params
                and "indicatorId" in request.url.params
            ):
                return httpx.Response(500, text="Internal Server Error")
            return None

        httpx_mock.add_callback(error_disaggregation_callback)

        result = await get_metadata("WB_WDI_SP_POP_TOTL", "WB_WDI")

        assert result.indicator_metadata is not None
        assert result.error is not None
        assert "HTTP error" in result.error


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

        # Mock disaggregation response (called during metadata fetch)
        httpx_mock.add_response(
            method="GET",
            url=re.compile(r".*/disaggregation.*"),
            json=[{"field_name": "REF_AREA", "field_value": ["UGA"]}],
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

        # Mock disaggregation
        httpx_mock.add_response(
            method="GET",
            url=re.compile(r".*/disaggregation.*"),
            json=[
                {"field_name": "REF_AREA", "field_value": ["UGA"]},
                {"field_name": "UNIT_MEASURE", "field_value": ["PT"]},
            ],
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
    async def test_get_data_pagination(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test data retrieval with pagination."""

        # Mock metadata & disaggregation (needed for get_data to proceed)
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_WDI_SP_POP_TOTL"}}]},
        )
        httpx_mock.add_response(
            method="GET", url=re.compile(r".*/disaggregation.*"), json=[]
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
            method="GET", url=re.compile(r".*/disaggregation.*"), json=[]
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
            method="GET", url=re.compile(r".*/disaggregation.*"), json=[]
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

        result = await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL")

        assert result.data is None
        assert result.error is not None
        assert "HTTP error" in result.error

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
            method="GET", url=re.compile(r".*/disaggregation.*"), json=[]
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

        result = await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL")

        assert result.data is None
        assert result.error is not None
        assert "Failed to parse" in result.error


# NOTE: TestCodelistManager tests removed - CodelistManager was replaced with
# ReferenceAreaManager in providers.py with a different API.
# New tests for ReferenceAreaManager should be added in test_providers.py


class TestDatabaseNameInSearch:
    """Tests that search results carry the correct database_name for each indicator."""

    @pytest.mark.asyncio
    async def test_known_database_id_resolves_to_correct_name(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """WB_GS must resolve to 'Gender Statistics', not a guess."""
        mock_response = {
            "@odata.context": "https://api.test.example.com/$metadata",
            "@odata.count": 1,
            "value": [
                {
                    "series_description": {
                        "idno": "WB_GS_SP_POP_TOTL",
                        "name": "Population, total",
                        "database_id": "WB_GS",
                        "definition_long": "Total population",
                        "dimensions": [],
                    }
                }
            ],
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/searchv2",
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
            "@odata.context": "https://api.test.example.com/$metadata",
            "@odata.count": 1,
            "value": [
                {
                    "series_description": {
                        "idno": "UNKNOWN_DB_INDICATOR",
                        "name": "Some indicator",
                        "database_id": "UNKNOWN_DB",
                        "definition_long": "Definition",
                        "dimensions": [],
                    }
                }
            ],
        }
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/searchv2",
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

        value = [
            {
                "series_description": {
                    "idno": f"{db_id}_INDICATOR",
                    "name": f"Indicator for {db_id}",
                    "database_id": db_id,
                    "definition_long": "Definition",
                    "dimensions": [],
                }
            }
            for db_id in registered_ids
        ]
        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/searchv2",
            json={"@odata.count": len(value), "value": value},
        )

        result = await search("indicator", limit=len(registered_ids))

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
            method="GET",
            url=re.compile(r".*/disaggregation.*"),
            json=[],
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
            method="GET",
            url=re.compile(r".*/disaggregation.*"),
            json=[],
        )

        # Only request 'name' — database_name should still be included
        result = await get_metadata(
            "WB_GS", "WB_GS_INDICATOR", select_fields=["name"]
        )

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
            method="GET",
            url=re.compile(r".*/disaggregation.*"),
            json=[],
        )

        result = await get_metadata("UNKNOWN_DB", "UNKNOWN_DB_IND")

        assert result.indicator_metadata is not None
        assert result.indicator_metadata.get("database_name") is None
