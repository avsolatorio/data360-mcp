"""Tests for the background/bulk HTTP profile and the call sites that use it.

The interactive profile is covered in tests/test_http_client.py; the suite pins
``DATA360_RETRY_MAX_ATTEMPTS=1`` so unrelated tests stay single-attempt.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_httpx

from data360 import http_client, providers
from data360.config import get_data360_settings
from data360.http_client import (
    aclose_all_httpx_clients,
    aclose_background_httpx_client,
    aclose_shared_httpx_client,
    get_background_httpx_client,
    get_shared_httpx_client,
)
from data360.providers import CodelistManager, DatabaseManager

_API = "https://api.test.example.com"
_DATA_URL = f"{_API}/data"
_METADATA_URL = f"{_API}/metadata"
_CODELIST_URL = f"{_API}/codelist"
_SEARCH_URL = f"{_API}/portal/v1/public_data360_search"

_BULK_ATTEMPTS = 3
_PAGE_SIZE = 50
_INTERACTIVE_READ_SECONDS = 8.0
_EXPECTED_SYNC_PAGES = 2

# conftest's autouse stub replaces CodelistManager._fetch_extdataportal with an
# AsyncMock for every test; capture the real implementation at import time so the
# tests that must exercise the real HTTP path can restore it.
_REAL_FETCH_EXTDATAPORTAL = CodelistManager._fetch_extdataportal


@pytest.fixture
def real_catalog_http(monkeypatch):
    """Undo the suite-wide catalog stub for tests that assert on real HTTP."""
    monkeypatch.setattr(
        CodelistManager, "_fetch_extdataportal", _REAL_FETCH_EXTDATAPORTAL
    )


@pytest.fixture
async def bulk_retry_env(monkeypatch):
    """Rebuild clients with bulk retries enabled and no real backoff sleeping."""
    monkeypatch.setenv("DATA360_BACKGROUND_RETRY_MAX_ATTEMPTS", str(_BULK_ATTEMPTS))
    monkeypatch.setenv("DATA360_BACKGROUND_RETRY_BUDGET_SECONDS", "60")

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(http_client, "_RETRY_SLEEP", _no_sleep)
    get_data360_settings.cache_clear()
    await aclose_all_httpx_clients()
    yield
    get_data360_settings.cache_clear()
    await aclose_all_httpx_clients()


@pytest.fixture
def recorded_clients(monkeypatch):
    """Record which per-profile client the providers module asks for."""
    used: list[str] = []
    real_bulk = http_client.get_background_httpx_client
    real_interactive = http_client.get_shared_httpx_client

    def _bulk() -> httpx.AsyncClient:
        used.append("bulk")
        return real_bulk()

    def _interactive() -> httpx.AsyncClient:
        used.append("interactive")
        return real_interactive()

    monkeypatch.setattr(providers, "get_background_httpx_client", _bulk)
    monkeypatch.setattr(providers, "get_shared_httpx_client", _interactive)
    return used


@pytest.mark.asyncio
async def test_bulk_client_is_separate_from_interactive_with_its_own_lifecycle():
    """Bulk work gets its own client and pool, so closing one cannot break the other."""
    interactive = get_shared_httpx_client()
    bulk = get_background_httpx_client()

    assert bulk is not interactive
    assert bulk.timeout != interactive.timeout
    assert bulk.timeout.read > interactive.timeout.read

    await aclose_shared_httpx_client()
    assert bulk.is_closed is False
    assert get_shared_httpx_client() is not interactive

    await aclose_background_httpx_client()
    assert bulk.is_closed is True


@pytest.mark.asyncio
async def test_background_timeouts_come_from_settings(monkeypatch):
    """The bulk profile has its own tunables, independent of the interactive ones."""
    monkeypatch.setenv("DATA360_READ_TIMEOUT", "8")
    monkeypatch.setenv("DATA360_BACKGROUND_READ_TIMEOUT", "25")
    monkeypatch.setenv("DATA360_BACKGROUND_CONNECT_TIMEOUT", "7")
    get_data360_settings.cache_clear()
    await aclose_all_httpx_clients()

    try:
        bulk = get_background_httpx_client()
        assert (bulk.timeout.connect, bulk.timeout.read) == (7.0, 25.0)
        assert get_shared_httpx_client().timeout.read == _INTERACTIVE_READ_SECONDS
    finally:
        get_data360_settings.cache_clear()
        await aclose_all_httpx_clients()


@pytest.mark.asyncio
async def test_bulk_calls_retry_on_the_background_budget_only(
    httpx_mock: pytest_httpx.HTTPXMock, bulk_retry_env
):
    """Profiles carry independent retry policy: bulk retries, interactive does not."""
    for _ in range(_BULK_ATTEMPTS):
        httpx_mock.add_exception(httpx.ReadTimeout("read timed out"), url=_DATA_URL)
    httpx_mock.add_exception(httpx.ReadTimeout("read timed out"), url=_METADATA_URL)

    with pytest.raises(httpx.ReadTimeout):
        await get_background_httpx_client().get(_DATA_URL)
    with pytest.raises(httpx.ReadTimeout):
        await get_shared_httpx_client().get(_METADATA_URL)

    requests = httpx_mock.get_requests()
    bulk_calls = [r for r in requests if str(r.url) == _DATA_URL]
    interactive_calls = [r for r in requests if str(r.url) == _METADATA_URL]
    assert len(bulk_calls) == _BULK_ATTEMPTS
    assert len(interactive_calls) == 1


@pytest.mark.asyncio
async def test_catalog_fetch_uses_the_bulk_client(
    httpx_mock: pytest_httpx.HTTPXMock, recorded_clients, real_catalog_http
):
    """The 1.7 MB dimension catalog must not run on the interactive pool."""
    httpx_mock.add_response(
        method="GET",
        url=_CODELIST_URL,
        json={"SEX": [{"id": "F", "name": "Female"}]},
    )

    mapping = await CodelistManager()._fetch_extdataportal()

    assert mapping == {"SEX": {"F": "Female"}}
    assert recorded_clients == ["bulk"]


@pytest.mark.asyncio
async def test_dataset_sync_uses_the_bulk_client_and_paginates(
    httpx_mock: pytest_httpx.HTTPXMock, recorded_clients
):
    """The dataset catalogue sync pages on the bulk client and merges every page."""
    first_page = [
        {
            "series_description": {
                "database_id": f"DB_{i:03d}",
                "name": f"Dataset {i}",
            }
        }
        for i in range(_PAGE_SIZE)
    ]
    httpx_mock.add_response(method="POST", url=_SEARCH_URL, json={"value": first_page})
    httpx_mock.add_response(method="POST", url=_SEARCH_URL, json={"value": []})

    mapping = await DatabaseManager()._fetch_all()

    assert len(mapping) == _PAGE_SIZE
    assert mapping["DB_000"] == "Dataset 0"
    assert len(httpx_mock.get_requests()) == _EXPECTED_SYNC_PAGES
    assert recorded_clients == ["bulk"]
