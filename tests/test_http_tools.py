"""Tests for Streamable HTTP JSON responses and standard HTTP tool routes."""

# ruff: noqa: PLR2004

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

_MCP_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


@pytest.fixture
def client():
    """TestClient as a context manager so FastMCP Streamable HTTP lifespan starts."""
    from data360.server import app  # noqa: PLC0415

    with TestClient(app) as test_client:
        yield test_client


def test_mcp_initialize_returns_json(client: TestClient) -> None:
    """Streamable HTTP /mcp initialize is application/json, not text/event-stream."""
    response = client.post(
        "/mcp",
        json=_MCP_INITIALIZE,
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "application/json" in content_type
    assert "text/event-stream" not in content_type
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert "result" in body


def test_root_includes_tools_http(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["tools_http"] == "/api/v1/tools"


def test_list_tools_http(client: TestClient) -> None:
    response = client.get("/api/v1/tools")
    assert response.status_code == 200
    tools = response.json()["tools"]
    assert "data360_search_indicators" in tools
    assert "data360_interactive_choices" in tools


def test_call_tool_http_interactive_choices(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tools/data360_interactive_choices",
        json={
            "prompt": "Which series?",
            "options": ["Real GDP", "Nominal GDP", "Specify custom..."],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["prompt"] == "Which series?"
    assert "Real GDP" in body["options"]


def test_call_tool_http_unknown_tool_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tools/data360_not_a_real_tool",
        json={},
    )
    assert response.status_code == 404
    assert "error" in response.json()


def test_call_tool_http_blocked_search_returns_403(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tools/data360_search_indicators",
        json={"query": "*"},
    )
    assert response.status_code == 403
    assert "error" in response.json()


def test_call_tool_http_unauthorized_tool_returns_403(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tools/system_admin_tool",
        json={},
    )
    assert response.status_code == 403
    assert "error" in response.json()


def test_call_tool_http_unauthorized_tool_empty_body_returns_403(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/tools/system_admin_tool")
    assert response.status_code == 403
    assert "error" in response.json()


def test_call_tool_http_search_empty_body_returns_403(client: TestClient) -> None:
    response = client.post("/api/v1/tools/data360_search_indicators")
    assert response.status_code == 403
    assert "error" in response.json()


def test_call_tool_http_unauthorized_tool_invalid_json_returns_403(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/tools/system_admin_tool",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 403
    assert "error" in response.json()


def test_call_tool_http_search_invalid_json_returns_400(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tools/data360_search_indicators",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert "JSON" in response.json()["error"]
