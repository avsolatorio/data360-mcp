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
os.environ.setdefault("DATA360_SEARCH_URL", f"{_test_api}/portal/v1/public_data360_search")
os.environ.setdefault("DATA360_METADATA_URL", f"{_test_api}/metadata")
os.environ.setdefault("DATA360_DISAGGREGATION_URL", f"{_test_api}/disaggregation")
os.environ.setdefault("DATA360_DIMENSIONS_URL", f"{_test_api}/portal/v1/dimensions")
os.environ.setdefault("DATA360_DATA_URL", f"{_test_api}/data")

import pytest

from data360.api import (
    _disaggregation_cache,
    _disaggregation_cache_lock,
    _metadata_cache,
    _metadata_cache_lock,
    _dimensions_api_cache,
    _dimensions_api_cache_lock,
    _dimensions_api_inflight,
    _dimensions_api_inflight_lock,
)
from data360.http_client import aclose_shared_httpx_client


@pytest.fixture(autouse=True)
async def _isolate_data360_api_state():
    """Clear API TTL caches and shared httpx so tests do not share mocked responses."""
    if os.environ.get("PYTEST_RUNNING"):
        with _metadata_cache_lock:
            _metadata_cache.clear()
        with _disaggregation_cache_lock:
            _disaggregation_cache.clear()
        with _dimensions_api_cache_lock:
            _dimensions_api_cache.clear()
        with _dimensions_api_inflight_lock:
            _dimensions_api_inflight.clear()
    yield
    if os.environ.get("PYTEST_RUNNING"):
        with _metadata_cache_lock:
            _metadata_cache.clear()
        with _disaggregation_cache_lock:
            _disaggregation_cache.clear()
        with _dimensions_api_cache_lock:
            _dimensions_api_cache.clear()
        with _dimensions_api_inflight_lock:
            _dimensions_api_inflight.clear()
    await aclose_shared_httpx_client()


@pytest.fixture(autouse=True)
def _mock_extdataportal_global(monkeypatch):
    """Globally mock CodelistManager._fetch_extdataportal to prevent test failures from lazy loading."""
    from unittest.mock import AsyncMock
    from data360.providers import CodelistManager
    monkeypatch.setattr(
        CodelistManager,
        "_fetch_extdataportal",
        AsyncMock(return_value={})
    )
