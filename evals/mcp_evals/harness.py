"""Test harness for MCP server evaluation.

Connects an LLM agent to the MCP server via langchain-mcp-adapters,
runs queries, and captures all tool calls in DeepEval format.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from deepeval.test_case import ToolCall
from deepeval.test_case.mcp import MCPToolCall
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from mcp.types import CallToolResult, TextContent

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8021/mcp/")
EVAL_MODEL = os.getenv("EVAL_MODEL", "gpt-4o")


@dataclass
class HarnessResult:
    """Captured result from running a query through the LLM+MCP agent."""

    actual_output: str
    mcp_tools_called: list[MCPToolCall] = field(default_factory=list)
    tools_called: list[ToolCall] = field(default_factory=list)
    completion_time: float = 0.0


def _extract_tool_calls(messages: list) -> tuple[list[MCPToolCall], list[ToolCall]]:
    """Extract tool call info from LangGraph message history.

    Returns both MCPToolCall (for MCPUseMetric) and ToolCall (for ToolCorrectnessMetric).
    """
    mcp_tool_calls: list[MCPToolCall] = []
    tool_calls: list[ToolCall] = []

    for msg in messages:
        # AIMessage contains the tool_calls list
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})

                # Find the corresponding ToolMessage for this call
                tool_call_id = tc.get("id", "")
                tool_output = None
                for result_msg in messages:
                    if (
                        hasattr(result_msg, "tool_call_id")
                        and result_msg.tool_call_id == tool_call_id
                    ):
                        tool_output = result_msg.content
                        break

                # MCPToolCall for MCP-specific metrics
                # result must be mcp.types.CallToolResult
                call_result = None
                if tool_output:
                    call_result = CallToolResult(
                        content=[TextContent(type="text", text=str(tool_output))]
                    )
                mcp_tool_calls.append(
                    MCPToolCall(
                        name=tool_name,
                        args=tool_args,
                        result=call_result,
                    )
                )

                # ToolCall for ToolCorrectnessMetric / ArgumentCorrectnessMetric
                tool_calls.append(
                    ToolCall(
                        name=tool_name,
                        input_parameters=tool_args,
                        output=str(tool_output) if tool_output else None,
                    )
                )

    return mcp_tool_calls, tool_calls


async def run_single_turn(
    input_text: str,
    model: str = EVAL_MODEL,
    server_url: str = MCP_SERVER_URL,
) -> HarnessResult:
    """Run a single query through the LLM+MCP agent and capture results.

    Args:
        input_text: The user query to evaluate.
        model: LLM model name (default from EVAL_MODEL env var).
        server_url: MCP server URL (default from MCP_SERVER_URL env var).

    Returns:
        HarnessResult with actual_output, tool calls, and timing.
    """
    start = time.monotonic()

    # langchain-mcp-adapters >= 0.1.0: no context manager
    client = MultiServerMCPClient(
        {"data360": {"url": server_url, "transport": "streamable_http"}}
    )
    tools = await client.get_tools()
    llm = ChatOpenAI(model=model)
    agent = create_react_agent(llm, tools)

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": input_text}]}
    )

    elapsed = time.monotonic() - start
    messages = result["messages"]

    # Get final output (last AI message without tool_call_id)
    actual_output = ""
    for msg in reversed(messages):
        if hasattr(msg, "content") and not hasattr(msg, "tool_call_id"):
            actual_output = msg.content
            break

    mcp_tool_calls, tool_calls = _extract_tool_calls(messages)

    return HarnessResult(
        actual_output=actual_output,
        mcp_tools_called=mcp_tool_calls,
        tools_called=tool_calls,
        completion_time=elapsed,
    )
