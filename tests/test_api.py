"""Tests for data360.api module."""

import json

import httpx
import pytest
import pytest_httpx

from data360.api import (
    CodelistManager,
    _get_valid_disaggregations,
    get_code_name,
    get_data,
    get_metadata,
    search,
)
from data360.models import IndicatorDataResponse, MetadataResponse, SearchResponse


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
                    }
                },
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_GROW",
                        "name": "Population growth",
                        "database_id": "WB_WDI",
                        "definition_long": "Population growth rate",
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

        assert isinstance(result, SearchResponse)
        assert result.items is not None
        assert len(result.items) == NUM_ITEMS
        assert result.items[0].idno == "WB_WDI_SP_POP_TOTL"
        assert result.items[0].name == "Population, total"
        assert result.items[1].idno == "WB_WDI_SP_POP_GROW"
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

        assert result.items is not None
        assert len(result.items) == NUM_VALID_ITEMS  # Only the valid item
        assert result.items[0].idno == "WB_WDI_SP_POP_TOTL"

    @pytest.mark.asyncio
    async def test_search_with_custom_parameters(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test search with filter, orderby, and select parameters."""
        TOTAL_COUNT = 1
        LIMIT = 5
        mock_response = {
            "@odata.context": "https://api.test.example.com/$metadata",
            "@odata.count": TOTAL_COUNT,
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_TOTL",
                        "name": "Population, total",
                        "database_id": "WB_WDI",
                    }
                }
            ],
        }

        httpx_mock.add_response(
            method="POST",
            url="https://api.test.example.com/searchv2",
            json=mock_response,
        )

        result = await search(
            "population",
            limit=LIMIT,
            offset=0,
            odata_options={
                "filter": "type eq 'indicator'",
                "orderby": "series_description/name",
                "select": "series_description/idno, series_description/name",
            },
        )

        # Verify the request was made with correct parameters
        request = httpx_mock.get_request()
        assert request is not None
        assert request.method == "POST"
        payload = json.loads(request.read())
        assert payload["search"] == "population"
        assert payload["top"] == LIMIT
        assert payload["skip"] == 0

        assert result.items is not None
        assert len(result.items) == TOTAL_COUNT

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

        assert result.items is None
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

        assert result.items is None
        assert result.error is not None
        assert "timeout" in result.error.lower()

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

        assert result.items is None
        assert result.error is not None
        assert "Failed to parse" in result.error


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
        # Verify _Z was filtered out
        field_values = [opt["field_value"][0] for opt in result.disaggregation_options]
        assert "_Z" not in field_values
        assert "UGA" in field_values
        assert "_T" in field_values

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
        assert "HTTP error fetching metadata" in result.error

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
        assert "HTTP error fetching disaggregations" in result.error


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

        # Match URL with query parameters
        def data_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/data"
            ):
                return httpx.Response(200, json=mock_response)
            return None

        httpx_mock.add_callback(data_callback)

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

        # Match URL with query parameters
        def data_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/data"
            ):
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

        # Verify the request included the filters
        request = httpx_mock.get_request()
        assert request is not None
        assert "REF_AREA=UGA" in str(request.url)
        assert "UNIT_MEASURE=PT" in str(request.url)

    @pytest.mark.asyncio
    async def test_get_data_pagination(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test data retrieval with pagination."""

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
                                "TIME_PERIOD": f"202{i}",
                                "OBS_VALUE": 1000 + i,
                            }
                            for i in range(5)
                        ],
                        "count": 10,  # Total count is 10, so there's more data
                    },
                )
            return None

        # Second page response
        def second_page_callback(request: httpx.Request) -> httpx.Response | None:
            if (
                request.method == "GET"
                and request.url.host == "api.test.example.com"
                and request.url.path == "/data"
                and request.url.params.get("skip") == "5"
            ):
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "REF_AREA": "UGA",
                                "TIME_PERIOD": f"202{i}",
                                "OBS_VALUE": 1000 + i,
                            }
                            for i in range(5, 10)
                        ],
                        "count": 10,
                    },
                )
            return None

        # Register both callbacks
        httpx_mock.add_callback(first_page_callback)
        httpx_mock.add_callback(second_page_callback)

        result = await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL")

        EXPECTED_TOTAL_COUNT = 10
        assert result.data is not None
        assert len(result.data) == EXPECTED_TOTAL_COUNT
        assert result.count == EXPECTED_TOTAL_COUNT

    @pytest.mark.asyncio
    async def test_get_data_empty_response(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test data retrieval with empty response."""

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
        assert "HTTP error fetching data" in result.error

    @pytest.mark.asyncio
    async def test_get_data_invalid_json(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test data retrieval handles invalid JSON."""

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


class TestCodelistManager:
    """Tests for CodelistManager class."""

    @pytest.mark.asyncio
    async def test_set_codelist_success(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test successful codelist fetch."""
        mock_codelist = {
            "UNIT_MEASURE": [
                {"id": "PT", "name": "Percentage"},
                {"id": "NR", "name": "Number"},
            ],
            "FREQ": [
                {"id": "M", "name": "Monthly"},
                {"id": "A", "name": "Annual"},
            ],
        }

        httpx_mock.add_response(
            method="GET",
            url="https://api.test.example.com/codelist",
            json=mock_codelist,
        )

        manager = CodelistManager()
        await manager.set_codelist()

        assert manager.codelist is not None
        assert manager.codelist == mock_codelist

    @pytest.mark.asyncio
    async def test_get_name_success(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test successful name retrieval."""
        mock_codelist = {
            "UNIT_MEASURE": [
                {"id": "PT", "name": "Percentage"},
                {"id": "NR", "name": "Number"},
            ],
        }

        httpx_mock.add_response(
            method="GET",
            url="https://api.test.example.com/codelist",
            json=mock_codelist,
        )

        manager = CodelistManager()
        name = await manager.get_name("UNIT_MEASURE", "PT")

        assert name == "Percentage"

    @pytest.mark.asyncio
    async def test_get_name_not_found(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test name retrieval when field or value not found."""
        mock_codelist = {
            "UNIT_MEASURE": [
                {"id": "PT", "name": "Percentage"},
            ],
        }

        httpx_mock.add_response(
            method="GET",
            url="https://api.test.example.com/codelist",
            json=mock_codelist,
        )

        manager = CodelistManager()

        # Test field not found
        name = await manager.get_name("INVALID_FIELD", "PT")
        assert name is None

        # Test value not found
        name = await manager.get_name("UNIT_MEASURE", "INVALID_ID")
        assert name is None

    @pytest.mark.asyncio
    async def test_get_code_success(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test successful code retrieval."""
        mock_codelist = {
            "UNIT_MEASURE": [
                {"id": "PT", "name": "Percentage", "description": "Percentage value"},
            ],
        }

        httpx_mock.add_response(
            method="GET",
            url="https://api.test.example.com/codelist",
            json=mock_codelist,
        )

        manager = CodelistManager()
        await manager.set_codelist()

        code = manager.get_code("UNIT_MEASURE", "PT")

        assert code is not None
        assert code["id"] == "PT"
        assert code["name"] == "Percentage"

    @pytest.mark.asyncio
    async def test_get_code_not_loaded(self):
        """Test get_code raises error when codelist not loaded."""
        manager = CodelistManager()

        with pytest.raises(ValueError, match="Codelist not loaded"):
            manager.get_code("UNIT_MEASURE", "PT")

    @pytest.mark.asyncio
    async def test_get_code_name_global_function(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test the global get_code_name convenience function."""
        mock_codelist = {
            "UNIT_MEASURE": [
                {"id": "PT", "name": "Percentage"},
            ],
        }

        httpx_mock.add_response(
            method="GET",
            url="https://api.test.example.com/codelist",
            json=mock_codelist,
        )

        name = await get_code_name("UNIT_MEASURE", "PT")

        assert name == "Percentage"
