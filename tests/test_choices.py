import pytest
import json
from fastmcp.tools import ToolResult

@pytest.mark.asyncio
async def test_data360_interactive_choices():
    from data360.mcp_server.tools import data360_interactive_choices

    # Call the custom choice tool
    res = await data360_interactive_choices(
        prompt="Is it real or nominal GDP per capita?",
        options=["Real GDP per capita", "Nominal GDP per capita"],
        title="Clarify Query"
    )

    # Verify the custom tool returns a ToolResult
    assert isinstance(res, ToolResult)

    # Parse the content to make sure the JSON matches the schema
    text_block = res.content[0]
    payload = json.loads(text_block.text)
    assert payload["prompt"] == "Is it real or nominal GDP per capita?"
    assert payload["options"] == ["Real GDP per capita", "Nominal GDP per capita"]
    assert payload["title"] == "Clarify Query"


@pytest.mark.asyncio
async def test_data360_interactive_choices_default_title():
    from data360.mcp_server.tools import data360_interactive_choices

    # Call the custom choice tool without title
    res = await data360_interactive_choices(
        prompt="Is it real or nominal GDP per capita?",
        options=["Real GDP per capita", "Nominal GDP per capita"]
    )

    # Verify the custom tool returns a ToolResult
    assert isinstance(res, ToolResult)

    text_block = res.content[0]
    payload = json.loads(text_block.text)
    assert payload["title"] == "Choose an Option"
