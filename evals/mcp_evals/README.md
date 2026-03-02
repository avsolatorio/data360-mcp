# MCP Server Evaluation Suite

Evaluates the data360 MCP server's tool usability by LLMs, independent of any chatbot.

## What is DeepEval?

[DeepEval](https://deepeval.com) is an open-source evaluation framework for LLM applications. It provides metrics, some deterministic and some LLM-judged, to assess how well an LLM uses tools. We use three metrics from two categories.

### DeepEval Metrics We Use

**1. MCPUseMetric - MCP-native** ([docs](https://deepeval.com/docs/metrics-mcp-use))

The only metric designed specifically for MCP servers. It evaluates:

- **Primitive Usage** (0-1): Did the LLM use the right MCP primitives (tools, resources, prompts) from the server?
- **Argument Correctness** (0-1): Were the arguments passed to those primitives appropriate?

The final score is the **minimum** of both sub-scores. If the LLM picks the right tools but passes bad args, or vice versa, the score reflects the weakest link.

Requires `mcp_servers` (list of MCPServer objects with available_tools) and `mcp_tools_called` on the test case.

If it fails, tool descriptions are unclear, or the LLM cannot figure out the right tool from docstrings alone.

**2. ToolCorrectnessMetric - Generic agent metric** ([docs](https://deepeval.com/docs/metrics-tool-correctness))

Checks whether the LLM called the expected tools (defined in each scenario). Two-part evaluation:

- **Deterministic check**: Are the expected tools present in the actual tool calls?
- **LLM-scored selection quality** (when available_tools is provided): Given all available tools, was the LLM's selection optimal?

Requires `tools_called` and `expected_tools` on the test case. Optionally `available_tools` for the LLM selection score.

If it fails, the LLM called extra tools, missed expected tools, or made suboptimal choices (e.g., calling get_metadata directly instead of search_indicators first).

**3. ArgumentCorrectnessMetric - Generic agent metric** ([docs](https://deepeval.com/docs/metrics-argument-correctness))

LLM judge that evaluates whether the arguments passed to each tool were correct and aligned with the user's intent.

Requires `tools_called` on the test case.

If it fails, the LLM passed wrong parameters (e.g., wrong country code, missing year filter, incorrect indicator ID).

### Why Three Metrics?

MCPUseMetric gives a single merged score (min of primitive usage and arg correctness). The other two metrics give independent, granular signals:

| Question | Metric |
|---|---|
| Did the LLM use the right MCP primitives overall? | MCPUseMetric |
| Did the LLM call the specific tools we expected? | ToolCorrectnessMetric |
| Were the arguments to those tools correct? | ArgumentCorrectnessMetric |

This lets us distinguish between "wrong tool" and "right tool, wrong args" failures, which point to different fixes (tool descriptions vs argument examples).

## What We Test (and What We Do Not)

**In scope: MCP server tool usability**

- Can an LLM figure out which tools to call from docstrings alone?
- Are tool arguments correct for the user's intent?
- Do the tools return the right data (end-to-end)?

**Out of scope: Chatbot behavior**

- System prompts, conversation memory, multi-turn flows
- Custom orchestration, prompt engineering
- UI/UX, response formatting for end users

The eval uses a generic LLM agent with only MCP tools. There is no system prompt and no memory. If the eval fails, the problem is in our tool descriptions or return values, not in any chatbot prompt.

## Two Eval Approaches

### 1. DeepEval (tool quality, process)

Runs 22 scenarios through an LLM+MCP agent, then an LLM judge scores tool selection and argument quality.

```
uv run deepeval test run evals/mcp_evals/test_single_turn.py -v
```

- 66 tests (3 metrics x 22 scenarios)
- Cost: approximately $2 per run
- Signal: Rich, tells you why tool selection was good or bad

### 2. QA-Pair (answer correctness, outcome)

Runs 20 questions through the same agent, compares final answer by exact string match.

```
uv run python evals/mcp_evals/qa_eval.py evals/mcp_evals/evaluation.xml -v
```

- 20 tests
- Cost: approximately $0.40 per run
- Signal: Binary, right or wrong, deterministic

### How They Complement Each Other

DeepEval can pass when QA fails: the LLM picked the right tools with correct args, but the answer was wrong (e.g., tool returns a code instead of a label).

QA can pass when DeepEval fails: the LLM used unexpected tools but still got the right answer (e.g., skipped search but guessed the right indicator ID).

## Tool Coverage

| Tool | Scenarios | QA Pairs | Category |
|---|---|---|---|
| search_indicators | 17 | 3 | Core discovery |
| get_data | 7 | 5 | Data retrieval |
| find_codelist_value | 4 | 4 | Code lookups |
| get_metadata | 4 | 3 | Indicator info |
| get_viz_spec | 4 | - | Visualization |
| get_disaggregation | 2 | 3 | Dimension options |
| get_supported_chart_types | 1 | 1 | Structural |
| list_indicators | - | - | Not directly tested |
| get_data_api_url | - | - | Low-level, rarely used |

## How to Run

Prerequisites:

1. Start the MCP server: `bash scripts/start_server.sh`
2. Set the OPENAI_API_KEY environment variable

Run everything:

    uv run python evals/mcp_evals/run_evals.py -v

Run DeepEval only:

    uv run deepeval test run evals/mcp_evals/test_single_turn.py -v

Run QA only:

    uv run python evals/mcp_evals/qa_eval.py evals/mcp_evals/evaluation.xml -v

## How to Add Tests

### DeepEval scenario (scenarios.py)

Each scenario is a Python dictionary with three fields:

| Field | Description | Example |
|---|---|---|
| input | The user query to test | "What is the GDP per capita in Kenya?" |
| expected_tools | Minimum set of tools the LLM should call | ["data360_search_indicators", "data360_get_data"] |
| tags | Category labels for filtering results | ["data_retrieval"] |

### QA pair (evaluation.xml)

Each QA pair is an XML element with two children:

| Element | Description | Example |
|---|---|---|
| question | Clear question with exact format specified | "What is the 3-letter country code for Tanzania?" |
| answer | Single verifiable answer (exact string match) | "TZA" |

## File Structure

| File | Purpose |
|---|---|
| README.md | This file |
| EVAL_REPORT.md | Latest results and recommendations |
| conftest.py | Pytest fixtures |
| harness.py | LLM+MCP agent runner |
| logger.py | JSONL response logger |
| scenarios.py | 22 DeepEval scenarios |
| test_single_turn.py | DeepEval tests (66 total) |
| evaluation.xml | 20 QA pairs |
| qa_eval.py | QA runner |
| run_evals.py | CLI (--deepeval / --qa / both) |
| results/ | Auto-generated logs (gitignored) |

## DeepEval References

Resources used to build this evaluation suite:

| Resource | What we used it for |
|---|---|
| [Evaluating MCP Servers](https://deepeval.com/docs/evaluation-mcp) | Core guide: MCP evaluation concepts, MCPServer setup, MCPToolCall structure |
| [Getting Started with MCP Evals](https://deepeval.com/docs/getting-started-mcp) | Setup walkthrough: connecting to MCP server, running first tests |
| [MCPUseMetric](https://deepeval.com/docs/metrics-mcp-use) | MCP-native metric: primitive usage and argument correctness scoring |
| [ToolCorrectnessMetric](https://deepeval.com/docs/metrics-tool-correctness) | Deterministic and LLM-scored tool selection evaluation |
| [ArgumentCorrectnessMetric](https://deepeval.com/docs/metrics-argument-correctness) | LLM-judged argument quality assessment |
| [LLMTestCase](https://deepeval.com/docs/evaluation-test-cases) | Test case structure: input, actual_output, tools_called, mcp_tools_called |
| [MCPToolCall](https://deepeval.com/docs/evaluation-test-cases-mcp) | MCP-specific test case fields: mcp_servers, mcp_tools_called |
| [Running Tests](https://deepeval.com/docs/evaluation-introduction) | deepeval test run CLI and pytest integration |
