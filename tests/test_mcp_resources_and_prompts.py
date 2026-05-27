"""Tests to verify that Data360 MCP resources and prompts are correctly registered and serve the correct instructions."""

from __future__ import annotations

import json
import pytest
from data360.mcp_server import mcp


@pytest.mark.asyncio
async def test_mcp_resources_registered_and_valid() -> None:
    """Verify that all expected MCP resources are registered and contain correct content."""
    resources = await mcp.get_resources()

    expected_resources = {
        "data360://system-prompt",
        "data360://agent-recipe",
        "data360://context",
        "data360://databases",
        "data360://codelists",
        "data360://metadata-fields",
        "data360://data-filters",
        "data360://data-schema",
        "data360://search-usage",
        "data360://k360-narrative-style",
    }

    # Verify all expected keys are in the resources dict
    for uri in expected_resources:
        assert uri in resources, f"Resource URI '{uri}' is not registered on the MCP server"

    # 1. Assert content of data360://system-prompt
    sys_prompt_resource = resources["data360://system-prompt"]
    sys_prompt = await sys_prompt_resource.read()
    assert isinstance(sys_prompt, str)
    assert "data360_search_indicators" in sys_prompt
    assert "disaggregation_filters" in sys_prompt
    assert "Selected Indicator:" in sys_prompt
    assert "Grammar-of-graphics rule" in sys_prompt
    assert "OMIT the dimension entirely" in sys_prompt
    assert "data360_get_viz_spec" in sys_prompt
    assert "data360_get_multi_indicator_viz_spec" in sys_prompt
    assert "last 5 years" in sys_prompt
    assert "current_year - 4" in sys_prompt


    # 2. Assert content of data360://data-schema
    data_schema_resource = resources["data360://data-schema"]
    data_schema_json = await data_schema_resource.read()
    data_schema = json.loads(data_schema_json)

    assert "obs_value" in data_schema["core_fields"]
    assert "time_period" in data_schema["core_fields"]
    assert "ref_area" in data_schema["core_fields"]
    assert "unit_measure" in data_schema["core_fields"]
    assert "claim_id" in data_schema["core_fields"]

    assert "sex" in data_schema["conditional_fields"]
    assert "age" in data_schema["conditional_fields"]
    assert "urbanisation" in data_schema["conditional_fields"]
    assert "comp_breakdown_1" in data_schema["conditional_fields"]
    assert "comp_breakdown_2" in data_schema["conditional_fields"]

    # 3. Assert content of data360://data-filters
    data_filters_resource = resources["data360://data-filters"]
    data_filters_json = await data_filters_resource.read()
    data_filters = json.loads(data_filters_json)
    assert "timePeriodFrom" in data_filters["supported_filters"]
    assert "timePeriodTo" in data_filters["supported_filters"]
    assert "REF_AREA" in data_filters["supported_filters"]
    assert "FREQ" in data_filters["excluded_filters"]


@pytest.mark.asyncio
async def test_mcp_prompts_render_successfully() -> None:
    """Verify that all prompts are registered and render to strings without syntax/format errors."""
    prompts = await mcp.get_prompts()

    # 1. gate_classifier (no arguments)
    assert "gate_classifier" in prompts
    res_gate = await prompts["gate_classifier"].render()
    assert len(res_gate) > 0
    assert isinstance(res_gate[0].content.text, str)

    # 2. thematic_to_data
    assert "thematic_to_data" in prompts
    res_thematic = await prompts["thematic_to_data"].render(
        arguments={"user_message": "What is the unemployment rate in Kenya?"}
    )
    assert "unemployment rate in Kenya" in res_thematic[0].content.text

    # 3. indicator_search (the one that previously failed due to unescaped braces)
    assert "indicator_search" in prompts
    res_search = await prompts["indicator_search"].render(
        arguments={
            "query": "poverty rate",
            "country": "Kenya",
            "required_dimensions": "SEX,AGE",
        }
    )
    assert "poverty rate" in res_search[0].content.text
    assert "verify 'Kenya'" in res_search[0].content.text
    assert "['SEX', 'AGE']" in res_search[0].content.text
    assert 'disaggregation_filters={"REF_AREA": "KEN"}' in res_search[0].content.text

    # Test indicator_search with database parameter
    res_search_db = await prompts["indicator_search"].render(
        arguments={
            "query": "poverty rate",
            "country": "Kenya",
            "required_dimensions": "SEX,AGE",
            "database": "wdi",
        }
    )
    assert 'database="wdi"' in res_search_db[0].content.text

    # 4. indicator_details
    assert "indicator_details" in prompts
    res_details = await prompts["indicator_details"].render(
        arguments={
            "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
            "database_id": "WB_WDI",
            "question": "how is it calculated",
        }
    )
    assert "WB_WDI_NY_GDP_PCAP_KD" in res_details[0].content.text
    assert "how is it calculated" in res_details[0].content.text

    # 5. country_data
    assert "country_data" in prompts
    res_country = await prompts["country_data"].render(
        arguments={
            "query": "GDP growth",
            "country": "Kenya, Uganda",
            "start_year": "2018",
            "end_year": "2023",
        }
    )
    assert "GDP growth" in res_country[0].content.text
    assert "Kenya, Uganda" in res_country[0].content.text

    # Test country_data with database parameter
    res_country_db = await prompts["country_data"].render(
        arguments={
            "query": "GDP growth",
            "country": "Kenya, Uganda",
            "start_year": "2018",
            "end_year": "2023",
            "database": "wdi",
        }
    )
    assert 'database="wdi"' in res_country_db[0].content.text

    # 6. k360_research_compiler
    assert "k360_research_compiler" in prompts
    res_compiler = await prompts["k360_research_compiler"].render(
        arguments={
            "user_question": "Compare GDP in East Africa",
            "data_question": "GDP growth Kenya Uganda Tanzania",
            "tool_calls_json": "[]",
        }
    )
    assert "Compare GDP in East Africa" in res_compiler[0].content.text

    # 7. k360_narrative
    assert "k360_narrative" in prompts
    res_narrative = await prompts["k360_narrative"].render(
        arguments={
            "user_question": "Compare GDP in East Africa",
            "content_packet_json": "{}",
            "raw_tool_results_json": "[]",
            "include_claim_tags": "true",
        }
    )
    assert "Compare GDP in East Africa" in res_narrative[0].content.text
    assert "include_claim_tags=true" in res_narrative[0].content.text


@pytest.mark.asyncio
async def test_mcp_tools_registered() -> None:
    """Verify that the search_datasets tool is registered on the MCP server."""
    tools = await mcp.get_tools()
    assert "data360_search_datasets" in tools


@pytest.mark.asyncio
async def test_search_indicators_tool_schema() -> None:
    """Verify that the search_indicators tool has the database parameter in its schema."""
    tools = await mcp.get_tools()
    assert "data360_search_indicators" in tools
    tool = tools["data360_search_indicators"]
    properties = tool.parameters.get("properties", {})
    assert "database" in properties, "database parameter not found in tool schema"
    db_schema = properties["database"]
    assert "anyOf" in db_schema
    assert any(opt.get("type") == "string" for opt in db_schema["anyOf"])
