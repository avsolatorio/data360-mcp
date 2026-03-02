"""Single-turn evaluations for MCP server.

Tests TOOL SELECTION QUALITY (process):
    - MCPUseMetric: Primitive usage + argument correctness (MCP-native)
    - ToolCorrectnessMetric: Were expected tools called? (deterministic + LLM)
    - ArgumentCorrectnessMetric: Were arguments correct? (LLM judge)

All runs are automatically logged to evals/mcp_evals/results/ for review.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from deepeval import assert_test
from deepeval.metrics import (
    ArgumentCorrectnessMetric,
    MCPUseMetric,
    ToolCorrectnessMetric,
)
from deepeval.test_case import LLMTestCase, ToolCall

from harness import run_single_turn
from scenarios import SINGLE_TURN_SCENARIOS

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

JUDGE_MODEL = os.getenv("DEEPEVAL_JUDGE_MODEL", "gpt-4o")

mcp_use_metric = MCPUseMetric(
    threshold=0.5,
    model=JUDGE_MODEL,
    include_reason=True,
)

tool_correctness_metric = ToolCorrectnessMetric(
    threshold=0.7,
    model=JUDGE_MODEL,
    include_reason=True,
)

argument_correctness_metric = ArgumentCorrectnessMetric(
    threshold=0.5,
    model=JUDGE_MODEL,
    include_reason=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Cache harness results per scenario input to avoid re-running for each metric
_harness_cache: dict[str, object] = {}


def _run_scenario(scenario: dict):
    """Run a scenario through the harness (cached per input)."""
    key = scenario["input"]
    if key not in _harness_cache:
        import nest_asyncio
        nest_asyncio.apply()

        loop = asyncio.new_event_loop()
        try:
            _harness_cache[key] = loop.run_until_complete(
                run_single_turn(scenario["input"])
            )
        finally:
            loop.close()
    return _harness_cache[key]


def _build_test_case(scenario: dict, mcp_server, available_tools, result_logger=None) -> LLMTestCase:
    """Run a scenario through the harness and build an LLMTestCase."""
    result = _run_scenario(scenario)

    # Log result for human review (only once per scenario)
    if result_logger is not None:
        result_logger.log(scenario, result)

    return LLMTestCase(
        name=scenario["input"][:60],
        input=scenario["input"],
        actual_output=result.actual_output,
        tags=scenario["tags"],
        completion_time=result.completion_time,
        # MCP-native evaluation (MCPUseMetric)
        mcp_servers=[mcp_server],
        mcp_tools_called=result.mcp_tools_called,
        # Generic agent evaluation (ToolCorrectness + ArgumentCorrectness)
        tools_called=result.tools_called,
        expected_tools=[
            ToolCall(name=t) for t in scenario["expected_tools"]
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario",
    SINGLE_TURN_SCENARIOS,
    ids=[s["input"][:50] for s in SINGLE_TURN_SCENARIOS],
)
def test_mcp_use(scenario, mcp_server, available_tools, result_logger):
    """Evaluate whether the LLM selects the right MCP primitives."""
    test_case = _build_test_case(scenario, mcp_server, available_tools, result_logger)
    assert_test(test_case, [mcp_use_metric])


@pytest.mark.parametrize(
    "scenario",
    SINGLE_TURN_SCENARIOS,
    ids=[s["input"][:50] for s in SINGLE_TURN_SCENARIOS],
)
def test_tool_correctness(scenario, mcp_server, available_tools, result_logger):
    """Evaluate whether the expected tools were called."""
    tc_metric = ToolCorrectnessMetric(
        threshold=0.7,
        model=JUDGE_MODEL,
        include_reason=True,
        available_tools=available_tools,
    )
    test_case = _build_test_case(scenario, mcp_server, available_tools)
    assert_test(test_case, [tc_metric])


@pytest.mark.parametrize(
    "scenario",
    SINGLE_TURN_SCENARIOS,
    ids=[s["input"][:50] for s in SINGLE_TURN_SCENARIOS],
)
def test_argument_correctness(scenario, mcp_server, available_tools, result_logger):
    """Evaluate whether correct arguments were passed to tools."""
    test_case = _build_test_case(scenario, mcp_server, available_tools)
    assert_test(test_case, [argument_correctness_metric])
