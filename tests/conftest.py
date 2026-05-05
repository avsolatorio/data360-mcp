"""Pytest configuration — test API host and shared httpx client isolation."""

from __future__ import annotations

import os

# Must run before any import of data360.config (skip load_dotenv in config.py).
os.environ["PYTEST_RUNNING"] = "1"
_test_api = "https://api.test.example.com"
os.environ.setdefault("DATA360_API_BASE_URL", _test_api)
os.environ.setdefault(
    "DATA360_CODELIST_API_BASE_URL",
    f"{_test_api}/codelist",
)
# Match httpx_mock URLs in tests (short paths without /data360/).
os.environ.setdefault("DATA360_SEARCH_URL", f"{_test_api}/searchv2")
os.environ.setdefault("DATA360_METADATA_URL", f"{_test_api}/metadata")
os.environ.setdefault("DATA360_DISAGGREGATION_URL", f"{_test_api}/disaggregation")
os.environ.setdefault("DATA360_DATA_URL", f"{_test_api}/data")

import pytest

from data360.api import (
    _disaggregation_cache,
    _disaggregation_cache_lock,
    _metadata_cache,
    _metadata_cache_lock,
)
from data360.http_client import reset_shared_httpx_client_for_tests


@pytest.fixture(autouse=True)
def _isolate_data360_api_state():
    """Clear API TTL caches and shared httpx so tests do not share mocked responses."""
    if os.environ.get("PYTEST_RUNNING"):
        with _metadata_cache_lock:
            _metadata_cache.clear()
        with _disaggregation_cache_lock:
            _disaggregation_cache.clear()
    yield
    if os.environ.get("PYTEST_RUNNING"):
        with _metadata_cache_lock:
            _metadata_cache.clear()
        with _disaggregation_cache_lock:
            _disaggregation_cache.clear()
    reset_shared_httpx_client_for_tests()
