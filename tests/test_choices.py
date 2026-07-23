import json
import pytest


@pytest.mark.asyncio
async def test_data360_interactive_choices():
    from data360.mcp_server.tools import data360_interactive_choices

    res = await data360_interactive_choices(
        prompt="Which series would you like to view?",
        options=["Option A", "Option B", "Specify custom..."],
        title="Custom Title",
    )
    assert res is not None
    assert len(res.content) == 1
    assert res.content[0].type == "text"

    payload = json.loads(res.content[0].text)
    assert payload["prompt"] == "Which series would you like to view?"
    assert payload["options"] == ["Option A", "Option B", "Specify custom..."]
    assert payload["title"] == "Custom Title"


@pytest.mark.asyncio
async def test_data360_interactive_choices_default_title():
    from data360.mcp_server.tools import data360_interactive_choices

    res = await data360_interactive_choices(
        prompt="Select a country",
        options=["Kenya", "Nigeria", "Specify custom..."],
    )
    payload = json.loads(res.content[0].text)
    assert payload["title"] == "Choose an Option"
