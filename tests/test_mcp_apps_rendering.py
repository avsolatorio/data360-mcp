import pytest
from unittest.mock import AsyncMock, patch, mock_open
from fastmcp.tools import ToolResult
from data360.mcp_server.tools import _get_viz_spec
from data360.mcp_server.resources import vega_lite_renderer

@pytest.mark.asyncio
async def test_viz_spec_returns_tool_result_with_app_metadata():
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

    with (
        patch("data360.visualization.get_viz_spec", new_callable=AsyncMock, return_value=mock_res),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data='{"mark": "line"}')),
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
        assert "spec" in res.structured_content
        assert res.structured_content["spec"] == {"mark": "line"}
        assert len(res.content) == 1
        assert res.content[0].type == "text"
        assert "Chart generated" in res.content[0].text
        assert "View spec: http://localhost:8000/static/viz_specs/test_vega.json" in res.content[0].text

@pytest.mark.asyncio
async def test_ui_resource_contains_vega_lite_v6():
    html = await vega_lite_renderer()
    assert "vega-lite@6" in html
    assert "io.modelcontextprotocol/ext-apps" in html or "ext-apps@0.4.0" in html
