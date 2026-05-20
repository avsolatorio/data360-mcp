"""Tests for GET /health and GET /ready."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_httpx
from fastapi.testclient import TestClient

from data360 import health as health_mod
from data360.config import get_mcp_server_settings

_test_api = os.environ["DATA360_API_BASE_URL"]
_search_url = os.environ["DATA360_SEARCH_URL"]
_codelist_url = f"{_test_api}/data360/codelist"
_codelist_probe_url = f"{_codelist_url}?type=REF_AREA"


def _mock_codelist(httpx_mock: pytest_httpx.HTTPXMock, json_body: dict | None = None) -> None:
    httpx_mock.add_response(
        url=_codelist_probe_url,
        method="GET",
        json=json_body or {"value": []},
    )


@pytest.fixture
def health_client() -> TestClient:
    from data360.server import app

    return TestClient(app)


def test_health_liveness(health_client: TestClient) -> None:
    response = health_client.get("/mcp/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "data360-mcp"
    assert "version" in body


def test_root_discoverability(health_client: TestClient) -> None:
    response = health_client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["health"] == "/mcp/health"
    assert body["ready"] == "/mcp/ready"
    assert body["mcp"] == "/mcp"


@pytest.mark.asyncio
async def test_ready_all_ok(
    httpx_mock: pytest_httpx.HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MCP_CHARTS_API_URL", raising=False)
    get_mcp_server_settings.cache_clear()

    httpx_mock.add_response(
        url=_search_url,
        method="POST",
        json={"value": [{"series_description": {"database_id": "WB_WDI"}}]},
    )
    _mock_codelist(
        httpx_mock, {"value": [{"id": "USA", "name": "United States"}]}
    )

    code, body = await health_mod.run_readiness()

    assert code == 200
    assert body["status"] == "ready"
    assert body["checks"]["data360_api"]["ok"] is True
    assert body["checks"]["database_mapping"]["ok"] is True
    assert body["checks"]["viz_storage"]["ok"] is True


@pytest.mark.asyncio
async def test_ready_data360_timeout(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    import httpx

    httpx_mock.add_exception(
        url=_search_url,
        method="POST",
        exception=httpx.ReadTimeout("timed out"),
    )
    _mock_codelist(httpx_mock)

    code, body = await health_mod.run_readiness()
    assert code == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["data360_api"]["ok"] is False


@pytest.mark.asyncio
async def test_ready_empty_database_mapping(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url=_search_url,
        method="POST",
        json={"value": []},
    )
    _mock_codelist(httpx_mock)

    with patch(
        "data360.health.get_database_mapping",
        new=AsyncMock(return_value={}),
    ):
        code, body = await health_mod.run_readiness()

    assert code == 503
    assert body["checks"]["database_mapping"]["ok"] is False
    assert body["checks"]["database_mapping"]["detail"] == "empty_cache"


@pytest.mark.asyncio
async def test_ready_readiness_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_READINESS_ENABLED", "false")
    get_mcp_server_settings.cache_clear()

    code, body = await health_mod.run_readiness()
    assert code == 200
    assert body.get("readiness_checks") == "disabled"

    monkeypatch.delenv("MCP_READINESS_ENABLED", raising=False)
    get_mcp_server_settings.cache_clear()


@pytest.mark.asyncio
async def test_ready_charts_down_static_ok(
    httpx_mock: pytest_httpx.HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import httpx

    charts_url = "https://charts.test.example/api/v1/charts"
    monkeypatch.setenv("MCP_CHARTS_API_URL", charts_url)
    get_mcp_server_settings.cache_clear()

    httpx_mock.add_response(
        url=_search_url,
        method="POST",
        json={"value": [{"series_description": {"database_id": "WB_WDI"}}]},
    )
    httpx_mock.add_exception(
        url=charts_url,
        method="HEAD",
        exception=httpx.ConnectError("connection refused"),
    )
    _mock_codelist(httpx_mock)

    specs_dir = tmp_path / "static" / "viz_specs"
    specs_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    code, body = await health_mod.run_readiness()
    assert code == 200
    assert body["checks"]["viz_storage"]["ok"] is True
    assert body["checks"]["viz_storage"]["backend"] == "static"

    monkeypatch.delenv("MCP_CHARTS_API_URL", raising=False)
    get_mcp_server_settings.cache_clear()


@pytest.mark.asyncio
async def test_ready_static_not_writable(
    httpx_mock: pytest_httpx.HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    httpx_mock.add_response(
        url=_search_url,
        method="POST",
        json={"value": []},
    )
    _mock_codelist(httpx_mock)

    static_dir = tmp_path / "static"
    static_dir.mkdir()
    viz_specs = static_dir / "viz_specs"
    viz_specs.mkdir()
    viz_specs.chmod(0o555)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MCP_CHARTS_API_URL", raising=False)
    get_mcp_server_settings.cache_clear()

    try:
        code, body = await health_mod.run_readiness()
    finally:
        viz_specs.chmod(0o755)

    assert code == 503
    assert body["checks"]["viz_storage"]["ok"] is False


def test_ready_endpoint_integration(
    health_client: TestClient,
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url=_search_url,
        method="POST",
        json={"value": [{"series_description": {"database_id": "WB_WDI"}}]},
    )
    _mock_codelist(httpx_mock)

    response = health_client.get("/mcp/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database_mapping"]["ok"] is True
