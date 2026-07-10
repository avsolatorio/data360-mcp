import pytest
from unittest.mock import AsyncMock, patch, mock_open
from fastmcp.tools import ToolResult
from data360.mcp_server.tools import _get_viz_spec
from data360.mcp_server.resources import vega_lite_renderer

@pytest.mark.asyncio
async def test_viz_spec_returns_tool_result_with_app_metadata():
    import json
    mock_res = {
        "url": "http://localhost:8000/static/viz_specs/test_vega.json",
        "strategy": "temporal_single",
        "reason": "Single indicator time-series",
        "warning": None,
        "source_line": "Source: World Bank WDI",
        "subtitle_line": "Subtitle details",
        "dimensions": {"REF_AREA": ["KEN", "USA"]},
        "data_profile": {"indicators": {}},
    }

    mock_spec = {
        "title": {"text": "GDP per capita"},
        "data": {
            "values": [
                {"TIME_PERIOD": "2020", "OBS_VALUE": 1000},
                {"TIME_PERIOD": "2021", "OBS_VALUE": 1100},
            ]
        }
    }

    with (
        patch("data360.visualization.get_viz_spec", new_callable=AsyncMock, return_value=mock_res),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=json.dumps(mock_spec))),
    ):
        res = await _get_viz_spec(
            database_id="WB_WDI",
            indicator_id="WB_WDI_NY_GDP_PCAP_KD",
            country_code="KEN;USA",
            start_year=2020,
            end_year=2022,
        )

        assert isinstance(res, ToolResult)
        assert res.structured_content is not None
        assert "view" in res.structured_content
        assert len(res.content) == 2
        assert res.content[0].type == "text"
        assert res.content[1].type == "text"
        assert "Data Summary" in res.content[1].text


@pytest.mark.asyncio
async def test_get_viz_spec_list_title_validation():
    import json
    mock_res = {
        "url": "http://localhost:8000/static/viz_specs/test_list_title.json",
        "strategy": "small_multiples",
        "reason": "Pyramid strategy",
        "warning": None,
        "source_line": "Source: World Bank WDI",
        "subtitle_line": "Subtitle details",
        "dimensions": {"REF_AREA": ["ESP"]},
        "data_profile": {"indicators": {}},
    }

    mock_spec = {
        "title": {"text": ["Population, age group"], "subtitle": ["Spain, 2023", "Count"]},
        "data": {
            "values": [
                {"year": "2023", "value": 889871.0, "country": "Spain", "sex": "Female", "age": "under 5 years old"},
            ]
        }
    }

    with (
        patch("data360.visualization.get_viz_spec", new_callable=AsyncMock, return_value=mock_res),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=json.dumps(mock_spec))),
    ):
        res = await _get_viz_spec(
            database_id="WB_HNP",
            indicator_id="WB_HNP_SP_POP_5Y",
            country_code="ESP",
            start_year=2023,
            end_year=2023,
        )
        assert isinstance(res, ToolResult)
        assert res.structured_content is not None
        assert "view" in res.structured_content
        assert len(res.content) == 2

@pytest.mark.asyncio
async def test_ui_resource_contains_vega_lite_v6():
    html = await vega_lite_renderer()
    assert "vega-lite.js" in html
    assert "ext-apps.js" in html



def test_cors_static_files():
    from fastapi.testclient import TestClient
    from data360.server import app

    client = TestClient(app)
    
    # Test OPTIONS preflight on static file
    response = client.options("/static/nonexistent.json")
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"
    assert "GET" in response.headers.get("access-control-allow-methods", "")

    # Test GET on static file (CORS headers should be present even on 404)
    response = client.get("/static/nonexistent.json")
    assert response.headers.get("access-control-allow-origin") == "*"


def test_debug_log_endpoint():
    from fastapi.testclient import TestClient
    from data360.server import app

    client = TestClient(app)

    # Test OPTIONS preflight on debug-log
    response = client.options("/debug-log")
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"

    # Test POST on debug-log
    response = client.post("/debug-log", json={"message": "test", "detail": "info"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("access-control-allow-origin") == "*"


@pytest.mark.asyncio
async def test_viz_spec_error_raises_tool_error():
    from data360.mcp_server.tools import _get_viz_spec
    from fastmcp.exceptions import ToolError

    mock_res = {"error": "Indicator not found"}

    with patch("data360.visualization.get_viz_spec", new_callable=AsyncMock, return_value=mock_res):
        with pytest.raises(ToolError) as exc_info:
            await _get_viz_spec(
                database_id="WB_WDI",
                indicator_id="INVALID",
                country_code="KEN",
            )
        assert "Indicator not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_viz_spec_maps_year_parameter():
    from data360.mcp_server.tools import _get_viz_spec

    mock_res = {
        "url": "http://localhost:8021/static/viz_specs/test.json",
        "strategy": "cross_sectional",
        "reason": "OK",
        "warning": None,
        "spec": {"mark": "bar"},
    }

    with patch("data360.visualization.get_viz_spec", new_callable=AsyncMock, return_value=mock_res) as mock_get:
        await _get_viz_spec(
            database_id="WB_WDI",
            indicator_id="NY_GDP_PCAP_CD",
            country_code="KEN",
            year=2024,
        )
        mock_get.assert_called_once_with(
            database_id="WB_WDI",
            indicator_id="NY_GDP_PCAP_CD",
            country_code="KEN",
            start_year=2024,
            end_year=2024,
            disaggregation_filters=None,
            chart_type=None,
            relevant_fields=None,
            custom_constraints=None,
            use_default_constraints=True,
            chart_title=None,
            series_labels=None,
            strategy_override=None,
        )


def test_spec_to_prefab_renders_svg_when_enabled():
    from data360.mcp_server.tools import spec_to_prefab
    from data360.config import get_mcp_server_settings
    from prefab_ui.components import Svg
    
    settings = get_mcp_server_settings()
    settings.chart_render_mode = "svg"
    
    mock_spec = {
        "title": {"text": "GDP per capita"},
        "data": {
            "values": [
                {"TIME_PERIOD": "2020", "OBS_VALUE": 1000},
                {"TIME_PERIOD": "2021", "OBS_VALUE": 1100},
            ]
        },
        "mark": "line",
        "encoding": {
            "x": {"field": "TIME_PERIOD", "type": "temporal"},
            "y": {"field": "OBS_VALUE", "type": "quantitative"}
        }
    }
    
    try:
        res = spec_to_prefab(
            spec=mock_spec,
            strategy="temporal_single",
            reason="testing",
        )
        # Check that Container holds a Card containing a Svg element
        assert res.type == "Container"
        card = res.children[-1]
        assert card.type == "Card"
        card_content = card.children[1]
        assert card_content.type == "CardContent"
        svg_comp = card_content.children[0]
        assert isinstance(svg_comp, Svg)
        assert svg_comp.type == "Svg"
        assert "<svg" in svg_comp.content
    finally:
        settings.chart_render_mode = "embed"


def test_spec_to_prefab_renders_embed_when_enabled():
    from data360.mcp_server.tools import spec_to_prefab
    from data360.config import get_mcp_server_settings
    from prefab_ui.components import Embed
    
    settings = get_mcp_server_settings()
    settings.chart_render_mode = "embed"
    
    mock_spec = {
        "title": {"text": "GDP per capita"},
        "data": {
            "values": [
                {"TIME_PERIOD": "2020", "OBS_VALUE": 1000},
                {"TIME_PERIOD": "2021", "OBS_VALUE": 1100},
            ]
        },
        "mark": "line",
        "encoding": {
            "x": {"field": "TIME_PERIOD", "type": "temporal"},
            "y": {"field": "OBS_VALUE", "type": "quantitative"}
        }
    }
    
    res = spec_to_prefab(
        spec=mock_spec,
        strategy="temporal_single",
        reason="testing",
    )
    # Check that Container holds a Card containing a sandboxed Embed element
    assert res.type == "Container"
    card = res.children[-1]
    assert card.type == "Card"
    card_content = card.children[1]
    assert card_content.type == "CardContent"
    embed_comp = card_content.children[0]
    assert isinstance(embed_comp, Embed)
    assert embed_comp.type == "Embed"
    assert embed_comp.url is not None
    assert "static/embed.html" in embed_comp.url
    assert "spec=" in embed_comp.url
    assert embed_comp.sandbox == "allow-scripts allow-same-origin"





