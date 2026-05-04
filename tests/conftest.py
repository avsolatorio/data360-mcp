"""Pytest configuration and shared fixtures."""

from unittest.mock import patch

import pytest

from data360.config import Data360Settings


@pytest.fixture
def mock_data360_settings():
    """Mock Data360Settings for testing."""
    return Data360Settings(
        api_base_url="https://api.test.example.com",
        codelist_api_base_url="https://api.test.example.com/codelist",
        search_url="https://api.test.example.com/searchv2",
        metadata_url="https://api.test.example.com/metadata",
        disaggregation_url="https://api.test.example.com/disaggregation",
        data_url="https://api.test.example.com/data",
    )


@pytest.fixture(autouse=True)
def mock_database_mapping():
    """Mock the dynamic database mapping fetch from search API so we don't break existing tests that mock the search endpoint."""
    with patch(
        "data360.providers.DatabaseManager.get_mapping",
        return_value={"WB_WDI": "World Development Indicators", "WB_GS": "Gender Statistics"}
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
def patch_data360_config(mock_data360_settings):
    """Automatically patch the data360 config in all tests."""
    # Patch both the function and the module-level config variable
    with patch("data360.api.get_data360_settings", return_value=mock_data360_settings):
        with patch(
            "data360.config.get_data360_settings", return_value=mock_data360_settings
        ):
            with patch("data360.api.data360_config", mock_data360_settings):
                yield mock_data360_settings


@pytest.fixture(autouse=True)
def clear_api_caches():
    """Clear module-level TTL caches before each test.

    The metadata and disaggregation caches in data360.api persist across tests
    at module scope. Without this fixture, a test that mocks an HTTP response
    and populates the cache will cause the next test (with a different mock) to
    receive the cached value instead of hitting its own mock, producing false
    results.
    """
    import data360.api as api_module  # noqa: PLC0415
    api_module._metadata_cache.clear()
    api_module._disaggregation_cache.clear()
    yield
