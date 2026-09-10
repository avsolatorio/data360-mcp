"""Degraded metadata serving: stale snapshots and the upstream failure cooldown."""

from __future__ import annotations

import asyncio
import re

import httpx
import pytest
import pytest_httpx

from data360 import api as data360_api
from data360.api import (
    _dimensions_api_cache,
    _dimensions_api_cache_lock,
    _ResilientTtlCache,
    get_data,
    get_metadata,
)

_METADATA_URL = "https://api.test.example.com/metadata"
_DIMENSIONS_URL = re.compile(r".*/portal/v1/dimensions.*")
_DATA_URL = re.compile(r".*/data\?.*")

_DATABASE = "WB_WDI"
_INDICATOR = "WB_WDI_SP_POP_TOTL"

# Short fresh TTL so the stale tier is reachable without waiting a day.
_FRESH_TTL_SECONDS = 0.01
_DEGRADED_TTL_SECONDS = 60.0
_CACHE_MAXSIZE = 8
_EXPIRY_SLEEP_SECONDS = 0.05

_EXPECTED_REQUESTS_AFTER_WARMUP_AND_FAILURE = 4

_METADATA_PAYLOAD = {
    "value": [
        {
            "series_description": {
                "idno": _INDICATOR,
                "name": "Population, total",
                "database_id": _DATABASE,
            }
        }
    ]
}
_DIMENSIONS_PAYLOAD = {
    "dimensions": [{"field_name": "SEX", "field_value": [{"code": "F"}, {"code": "M"}]}]
}


@pytest.fixture
def expiring_metadata_cache(monkeypatch):
    """Replace the module metadata cache with one whose fresh tier expires immediately."""
    cache = _ResilientTtlCache(
        ttl=_FRESH_TTL_SECONDS,
        degraded_ttl=_DEGRADED_TTL_SECONDS,
        maxsize=_CACHE_MAXSIZE,
    )
    monkeypatch.setattr(data360_api, "_metadata_cache", cache)
    return cache


async def _expire_fresh_tier() -> None:
    await asyncio.sleep(_EXPIRY_SLEEP_SECONDS)


def _clear_dimensions_cache() -> None:
    with _dimensions_api_cache_lock:
        _dimensions_api_cache.clear()


@pytest.mark.asyncio
async def test_transient_failure_serves_last_snapshot_and_stops_retrying(
    httpx_mock: pytest_httpx.HTTPXMock, expiring_metadata_cache
):
    """A timeout degrades to the last good snapshot, and the cooldown absorbs the burst."""
    httpx_mock.add_response(method="POST", url=_METADATA_URL, json=_METADATA_PAYLOAD)
    httpx_mock.add_response(
        method="POST", url=_DIMENSIONS_URL, json=_DIMENSIONS_PAYLOAD
    )

    warm = await get_metadata(_DATABASE, _INDICATOR)
    assert warm.error is None
    assert warm.stale is False
    assert warm.disaggregation_options

    await _expire_fresh_tier()
    # Both upstream calls fail: force the dimensions call past its own cache.
    _clear_dimensions_cache()
    httpx_mock.add_exception(
        httpx.ReadTimeout("read timed out"), method="POST", url=_METADATA_URL
    )
    httpx_mock.add_exception(
        httpx.ReadTimeout("read timed out"), method="POST", url=_DIMENSIONS_URL
    )

    degraded = await get_metadata(_DATABASE, _INDICATOR)

    assert degraded.stale is True
    assert degraded.error is not None
    assert (degraded.indicator_metadata or {}).get("name") == "Population, total"
    assert degraded.disaggregation_options == warm.disaggregation_options

    # Callers inside the cooldown are served the degraded outcome with no upstream calls.
    replay = await get_metadata(_DATABASE, _INDICATOR)

    assert replay.stale is True
    assert replay.error == degraded.error
    assert len(httpx_mock.get_requests()) == _EXPECTED_REQUESTS_AFTER_WARMUP_AND_FAILURE


@pytest.mark.asyncio
async def test_not_found_is_not_masked_by_stale(
    httpx_mock: pytest_httpx.HTTPXMock, expiring_metadata_cache
):
    """A withdrawn indicator must surface as not found, not as stale metadata."""
    httpx_mock.add_response(method="POST", url=_METADATA_URL, json=_METADATA_PAYLOAD)
    httpx_mock.add_response(
        method="POST", url=_DIMENSIONS_URL, json=_DIMENSIONS_PAYLOAD
    )
    await get_metadata(_DATABASE, _INDICATOR)

    await _expire_fresh_tier()
    httpx_mock.add_response(method="POST", url=_METADATA_URL, json={"value": []})

    result = await get_metadata(_DATABASE, _INDICATOR)

    assert result.stale is False
    assert result.indicator_metadata is None
    assert result.error is not None


@pytest.mark.asyncio
async def test_get_data_proceeds_with_stale_metadata(
    httpx_mock: pytest_httpx.HTTPXMock, expiring_metadata_cache
):
    """When metadata goes stale, data retrieval continues instead of aborting."""
    httpx_mock.add_response(method="POST", url=_METADATA_URL, json=_METADATA_PAYLOAD)
    httpx_mock.add_response(
        method="POST", url=_DIMENSIONS_URL, json=_DIMENSIONS_PAYLOAD
    )
    httpx_mock.add_response(
        method="GET",
        url=_DATA_URL,
        json={"value": [{"REF_AREA": "KEN", "TIME_PERIOD": "2020", "OBS_VALUE": 5000}]},
    )

    warm = await get_data(_DATABASE, _INDICATOR, country_code="KEN")
    assert warm.error is None
    assert warm.data

    await _expire_fresh_tier()
    # Metadata now times out; dimensions still answers from the 10-minute cache.
    httpx_mock.add_exception(
        httpx.ReadTimeout("read timed out"), method="POST", url=_METADATA_URL
    )
    httpx_mock.add_response(
        method="GET",
        url=_DATA_URL,
        json={"value": [{"REF_AREA": "KEN", "TIME_PERIOD": "2021", "OBS_VALUE": 5200}]},
    )

    result = await get_data(_DATABASE, _INDICATOR, country_code="KEN")

    assert result.error is None
    assert result.data is not None
    assert [row["OBS_VALUE"] for row in result.data] == [5200]
