"""Shared fixtures for DeepEval MCP evaluation suite.

Provides:
    - mcp_server: session-scoped MCPServer fixture
    - available_tools: session-scoped list of ToolCall for ToolCorrectnessMetric
    - result_logger: session-scoped JSONL logger for human review
    - Adds this directory to sys.path so harness/scenarios can be imported
"""

import asyncio
import os
import sys

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from deepeval.test_case import ToolCall
from deepeval.test_case.mcp import MCPServer

# Add this directory to sys.path so test files can import harness, scenarios, logger
sys.path.insert(0, os.path.dirname(__file__))

from logger import ResultLogger  # noqa: E402

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8021/mcp/")


async def _build_fixtures(url: str = MCP_SERVER_URL) -> tuple[MCPServer, list[ToolCall]]:
    """Connect to the MCP server and build both DeepEval fixtures."""
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            resources = await session.list_resources()
            prompts = await session.list_prompts()

    mcp_server = MCPServer(
        server_name="data360-mcp",
        transport="streamable-http",
        available_tools=tools.tools,
        available_resources=resources.resources,
        available_prompts=prompts.prompts,
    )

    # ToolCall list for ToolCorrectnessMetric's available_tools param
    tool_call_list = [
        ToolCall(name=t.name, description=t.description)
        for t in tools.tools
    ]

    return mcp_server, tool_call_list


# Cache the result so we only connect once
_cached_fixtures = None


def _get_fixtures():
    global _cached_fixtures
    if _cached_fixtures is None:
        _cached_fixtures = asyncio.run(_build_fixtures())
    return _cached_fixtures


@pytest.fixture(scope="session")
def mcp_server():
    """Session-scoped fixture providing the MCPServer object.

    Requires the MCP server to be running:
        bash scripts/start_server.sh
    """
    server, _ = _get_fixtures()
    return server


@pytest.fixture(scope="session")
def available_tools():
    """Session-scoped fixture providing available tools as ToolCall list.

    Used by ToolCorrectnessMetric to evaluate tool selection quality.
    """
    _, tools = _get_fixtures()
    return tools


@pytest.fixture(scope="session")
def result_logger():
    """Session-scoped JSONL logger for capturing all test run details.

    Results are written to evals/mcp_evals/results/run_<timestamp>.jsonl
    """
    logger = ResultLogger()
    print(f"\n📄 Logging results to {logger.path}")
    yield logger
    logger.close()
