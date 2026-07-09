import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from data360.server import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_api_search_indicators_endpoint():
    mock_indicator = AsyncMock()
    mock_indicator.idno = "WB_WDI_NY_GDP_PCAP_CD"
    mock_indicator.database_id = "WB_WDI"
    mock_indicator.database_name = "World Development Indicators"
    mock_indicator.name = "GDP per capita (current US$)"
    mock_indicator.truncated_definition = "GDP per capita is..."
    mock_indicator.time_period_range = "1960-2022"

    mock_res = AsyncMock()
    mock_res.indicators = [mock_indicator]

    with patch("data360.mcp_server.tools._search_indicators", return_value=mock_res) as mock_search:
        response = client.get("/api/indicators/search?query=GDP&database=wdi")
        assert response.status_code == 200
        data = response.json()
        assert "indicators" in data
        assert len(data["indicators"]) == 1
        assert data["indicators"][0]["idno"] == "WB_WDI_NY_GDP_PCAP_CD"
        mock_search.assert_called_once_with(query="GDP", database="wdi", limit=20)


@pytest.mark.asyncio
async def test_search_indicators_internal():
    from data360.mcp_server.tools import data360_search_indicators_internal
    mock_indicator = AsyncMock()
    mock_indicator.idno = "WB_WDI_NY_GDP"
    mock_indicator.database_id = "WB_WDI"
    mock_indicator.database_name = "World Development Indicators"
    mock_indicator.name = "GDP"
    mock_indicator.truncated_definition = "GDP definition"
    mock_indicator.time_period_range = "2000-2022"

    mock_res = AsyncMock()
    mock_res.indicators = [mock_indicator]

    with patch("data360.mcp_server.tools._search_indicators", return_value=mock_res):
        res = await data360_search_indicators_internal(query="GDP", database="wdi")
        assert len(res) == 1
        assert res[0]["idno"] == "WB_WDI_NY_GDP"


@pytest.mark.asyncio
async def test_indicator_explorer_prefab_app():
    from data360.mcp_server.tools import data360_indicator_explorer
    from prefab_ui.app import PrefabApp
    
    mock_indicator = AsyncMock()
    mock_indicator.idno = "WB_WDI_NY_GDP"
    mock_indicator.database_id = "WB_WDI"
    mock_indicator.database_name = "World Development Indicators"
    mock_indicator.name = "GDP"
    mock_indicator.truncated_definition = "GDP definition"
    mock_indicator.time_period_range = "2000-2022"

    mock_res = AsyncMock()
    mock_res.indicators = [mock_indicator]

    with patch("data360.mcp_server.tools._search_indicators", return_value=mock_res):
        app_res = await data360_indicator_explorer(query="GDP", database="wdi")
        assert isinstance(app_res, PrefabApp)
        assert "indicators_list" in app_res.state
        assert len(app_res.state["indicators_list"]) == 1


