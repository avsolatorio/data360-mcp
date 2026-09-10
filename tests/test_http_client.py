"""Tests for the shared httpx client: split timeouts, bounded retries, replay safety.

The suite pins ``DATA360_RETRY_MAX_ATTEMPTS=1`` (see conftest) so unrelated tests
keep asserting single-attempt behaviour; these tests opt back into retries.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import pytest_httpx

from data360 import http_client
from data360.api import get_metadata
from data360.config import get_data360_settings
from data360.http_client import (
    RETRY_SAFE_EXTENSION,
    aclose_shared_httpx_client,
    get_shared_httpx_client,
)

_API = "https://api.test.example.com"
_DATA_URL = f"{_API}/data"
_METADATA_URL = f"{_API}/metadata"
_DIMENSIONS_URL = f"{_API}/portal/v1/dimensions"
_CHARTS_URL = "https://charts.test.example.com/api/v1/charts"

_HTTP_OK = 200
_HTTP_NOT_FOUND = 404
_HTTP_SERVICE_UNAVAILABLE = 503

_CONFIGURED_ATTEMPTS = 3
_BUDGET_SECONDS = 20.0

_SINGLE_ATTEMPT = 1
_AFTER_ONE_RETRY = 2
_AFTER_RETRY_AND_FOLLOW_UP = 3


@pytest.fixture
async def retry_env(monkeypatch):
    """Rebuild the shared client with retries on, recording backoff instead of sleeping."""
    monkeypatch.setenv("DATA360_RETRY_MAX_ATTEMPTS", str(_CONFIGURED_ATTEMPTS))
    monkeypatch.setenv("DATA360_RETRY_BUDGET_SECONDS", str(_BUDGET_SECONDS))
    monkeypatch.setenv("DATA360_RETRY_BACKOFF_BASE", "0.3")
    monkeypatch.setenv("DATA360_RETRY_BACKOFF_MAX", "2.0")
    delays: list[float] = []

    async def _record(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(http_client, "_RETRY_SLEEP", _record)
    get_data360_settings.cache_clear()
    await aclose_shared_httpx_client()
    yield delays
    get_data360_settings.cache_clear()
    await aclose_shared_httpx_client()


@pytest.mark.asyncio
async def test_split_timeouts_come_from_settings(monkeypatch):
    """Each timeout phase is configured independently instead of a flat 30 s wall."""
    monkeypatch.setenv("DATA360_CONNECT_TIMEOUT", "2")
    monkeypatch.setenv("DATA360_READ_TIMEOUT", "7")
    monkeypatch.setenv("DATA360_WRITE_TIMEOUT", "3")
    monkeypatch.setenv("DATA360_POOL_TIMEOUT", "1")
    get_data360_settings.cache_clear()
    await aclose_shared_httpx_client()

    try:
        timeout = get_shared_httpx_client().timeout
        assert (timeout.connect, timeout.read) == (2.0, 7.0)
        assert (timeout.write, timeout.pool) == (3.0, 1.0)
    finally:
        get_data360_settings.cache_clear()
        await aclose_shared_httpx_client()


@pytest.mark.asyncio
async def test_read_timeout_is_retried_then_succeeds(
    httpx_mock: pytest_httpx.HTTPXMock, retry_env
):
    """A transient read timeout is retried and the request still succeeds."""
    httpx_mock.add_exception(httpx.ReadTimeout("read timed out"), url=_DATA_URL)
    httpx_mock.add_response(url=_DATA_URL, json={"value": []})

    response = await get_shared_httpx_client().get(_DATA_URL)

    assert response.status_code == _HTTP_OK
    assert len(httpx_mock.get_requests()) == _AFTER_ONE_RETRY


@pytest.mark.asyncio
async def test_retries_are_bounded_and_backoff_grows(
    httpx_mock: pytest_httpx.HTTPXMock, retry_env
):
    """A permanently failing call stops after the configured attempts, backing off each time."""
    for _ in range(_CONFIGURED_ATTEMPTS):
        httpx_mock.add_exception(httpx.ReadTimeout("read timed out"), url=_DATA_URL)

    with pytest.raises(httpx.ReadTimeout):
        await get_shared_httpx_client().get(_DATA_URL)

    assert len(httpx_mock.get_requests()) == _CONFIGURED_ATTEMPTS
    # One sleep between attempts, each no shorter than the previous one.
    assert len(retry_env) == _CONFIGURED_ATTEMPTS - 1
    assert retry_env == sorted(retry_env)


@pytest.mark.asyncio
async def test_retry_budget_stops_attempts_before_max(
    httpx_mock: pytest_httpx.HTTPXMock, retry_env, monkeypatch
):
    """Retrying is capped by wall-clock budget, not only by attempt count."""
    now = {"t": 0.0}
    monkeypatch.setattr(
        http_client, "time", SimpleNamespace(monotonic=lambda: now["t"])
    )

    async def _burn_budget(delay: float) -> None:
        now["t"] += _BUDGET_SECONDS

    monkeypatch.setattr(http_client, "_RETRY_SLEEP", _burn_budget)
    for _ in range(_AFTER_ONE_RETRY):
        httpx_mock.add_exception(httpx.ReadTimeout("read timed out"), url=_DATA_URL)

    with pytest.raises(httpx.ReadTimeout):
        await get_shared_httpx_client().get(_DATA_URL)

    # Two attempts fit in the budget; the third is refused.
    assert len(httpx_mock.get_requests()) == _AFTER_ONE_RETRY


@pytest.mark.asyncio
async def test_unmarked_post_is_not_replayed(
    httpx_mock: pytest_httpx.HTTPXMock, retry_env
):
    """A write (unmarked POST) must never be replayed after a timeout."""
    httpx_mock.add_exception(httpx.ReadTimeout("read timed out"), url=_CHARTS_URL)

    with pytest.raises(httpx.ReadTimeout):
        await get_shared_httpx_client().post(_CHARTS_URL, json={"title": "t"})

    assert len(httpx_mock.get_requests()) == _SINGLE_ATTEMPT


@pytest.mark.asyncio
async def test_retry_safe_post_is_retried(
    httpx_mock: pytest_httpx.HTTPXMock, retry_env
):
    """A read-only POST marked retry-safe is retried like an idempotent request."""
    httpx_mock.add_exception(httpx.ReadTimeout("read timed out"), url=_METADATA_URL)
    httpx_mock.add_response(url=_METADATA_URL, json={"value": []})

    response = await get_shared_httpx_client().post(
        _METADATA_URL, json={}, extensions={RETRY_SAFE_EXTENSION: True}
    )

    assert response.status_code == _HTTP_OK
    assert len(httpx_mock.get_requests()) == _AFTER_ONE_RETRY


@pytest.mark.asyncio
async def test_retryable_status_is_retried_but_client_error_is_not(
    httpx_mock: pytest_httpx.HTTPXMock, retry_env
):
    """5xx/429 are transient; 4xx responses are returned as-is after one attempt."""
    httpx_mock.add_response(url=_DATA_URL, status_code=_HTTP_SERVICE_UNAVAILABLE)
    httpx_mock.add_response(url=_DATA_URL, json={"value": []})
    client = get_shared_httpx_client()

    recovered = await client.get(_DATA_URL)
    assert recovered.status_code == _HTTP_OK
    assert len(httpx_mock.get_requests()) == _AFTER_ONE_RETRY

    httpx_mock.add_response(url=_DIMENSIONS_URL, status_code=_HTTP_NOT_FOUND)
    rejected = await client.get(_DIMENSIONS_URL)
    assert rejected.status_code == _HTTP_NOT_FOUND
    assert len(httpx_mock.get_requests()) == _AFTER_RETRY_AND_FOLLOW_UP


@pytest.mark.asyncio
async def test_metadata_query_is_retry_safe(
    httpx_mock: pytest_httpx.HTTPXMock, retry_env
):
    """The real metadata call site opts into retries, so a blip does not surface to callers."""
    httpx_mock.add_exception(httpx.ReadTimeout("read timed out"), url=_METADATA_URL)
    httpx_mock.add_response(
        url=_METADATA_URL,
        json={
            "value": [
                {
                    "series_description": {
                        "idno": "WB_WDI_SP_POP_TOTL",
                        "name": "Population, total",
                        "database_id": "WB_WDI",
                    }
                }
            ]
        },
    )
    httpx_mock.add_response(url=_DIMENSIONS_URL, json={"dimensions": []})

    result = await get_metadata("WB_WDI", "WB_WDI_SP_POP_TOTL")

    assert result.error is None
    assert result.stale is False
    assert (result.indicator_metadata or {}).get("name") == "Population, total"
    assert len(httpx_mock.get_requests()) == _AFTER_RETRY_AND_FOLLOW_UP
