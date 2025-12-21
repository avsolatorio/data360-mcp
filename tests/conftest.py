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
def patch_data360_config(mock_data360_settings):
    """Automatically patch the data360 config in all tests."""
    # Patch both the function and the module-level config variable
    with patch("data360.api.get_data360_settings", return_value=mock_data360_settings):
        with patch(
            "data360.config.get_data360_settings", return_value=mock_data360_settings
        ):
            with patch("data360.api.data360_config", mock_data360_settings):
                yield mock_data360_settings
