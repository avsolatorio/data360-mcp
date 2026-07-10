# Data360 MCP — DeepEval Visualization Evaluation Suite

This directory contains the LLM-in-the-loop evaluation framework for the `data360-mcp`
server's visualization pipeline. Evaluations are organized in three layers, each
testing a different boundary of the charting system.

---

## Architectural Context: Three-Layer Evaluation Model

The visualization pipeline has three distinct testable boundaries. Each layer is
kept separate so failures can be precisely localized.

```
  LLM / chatbot
       │
       ▼
 mcp_server/tools.py        ← Layer 3: MCP Tool Contract
 (_get_viz_spec,
  _get_multi_indicator_viz_spec)
       │
       ▼
 visualization.py           ← Layer 2: Pipeline Integration
 (get_viz_spec,
  get_multi_indicator_viz_spec)
       │
       ▼
 viz_config.py              ← Layer 1: Spec Builder (original)
 (select_strategy,
  dispatch_spec,
  POST_PROCESSING_RULES)
```

### Layer 1 — Spec Builder (`test_mcp_routing_deepeval.py`)

**What it tests**: The routing rule engine and Vega-Lite spec builders in
isolation. Calls `select_strategy` and `dispatch_spec` directly with synthetic
DataFrames. No I/O, no HTTP, no async.

**What it covers**:
- Routing strategy correctness for 12 data shapes (temporal, cross-sectional,
  demographic breakdown, scatter, heatmap, choropleth, small multiples, etc.)
- Grammar of Graphics encoding (x/y channel types, facets, resolving settings)
- Post-processing rules: gap dashing, error bands, log scale, percentage clamping,
  population pyramid, WB style

**G-Eval metric**: `Grammar of Graphics & FT Visual Vocabulary Correctness`

---

### Layer 2 — Pipeline Integration (`test_viz_integration_deepeval.py`)

**What it tests**: The full `visualization.get_viz_spec` and
`visualization.get_multi_indicator_viz_spec` pipeline, with only the
HTTP/filesystem I/O boundary mocked:

| Mocked surface | Why |
|---|---|
| `_fetch_data_internal` | No real API calls |
| `save_specs_to_static` | No filesystem writes; spec captured for assertion |
| `api.get_data_api_url` | Returns a dummy URL |
| `api.get_metadata` | Returns `None` (no title/unit resolution) |
| `providers.get_codelist_mapping` | Returns `{}` (no country-name mapping) |
| `visualization.get_database_mapping` | Returns `{"WB_WDI": "World Development Indicators"}` |

**What it covers** (over Layer 1):
- `_clean_single_df`: column selection, time_period rename, obs_value cast
- `_map_country_codes` / `_map_dimension_codes`: code → label resolution
- `bar` chart type hint → latest-year filtering for cross-sectional requests
- `LineYearGapStrokeDashRule` firing correctly for reporting gaps
- `PercentageBoundaryClampingRule` clamping y-axis for `UNIT_MEASURE=PT`
- Response shape: `url`, `error`, `strategy`, `reason`, `data_summary`, `source_line`
- `get_multi_indicator_viz_spec`: multi-series merging, melting, and routing
- Error handling: empty fetch → `url=None`, `error` non-null
- Input validation: `indicator_ids=None` and `len>4` both return proper errors

**Scenarios**: 13 test cases (A through M)

**G-Eval metrics**:
- `Visualization Pipeline Response Quality` (structural + grammar, threshold 0.75)
- `Multi-Indicator Spec Grammar Correctness` (facet/layer/scatter, threshold 0.75)

---

### Layer 3 — MCP Tool Contract (`test_mcp_tool_contract_deepeval.py`)

**What it tests**: The thin MCP wrapper functions in `mcp_server/tools.py`.
Mocks `visualization.get_viz_spec` and `get_multi_indicator_viz_spec` at the
module boundary, so only the wrapper logic is under test.

**What it covers**:
- Arg forwarding: all parameters (`chart_type`, `series_labels`, `chart_title`,
  `disaggregation_filters`, `start_year`, `end_year`, etc.) reach the underlying
  visualization function unchanged
- Response contract: `url` and `error` keys always present on both success and error
- Optional keys on success: `strategy`, `reason`, `source_line` preserved
- No key injection: wrapper does not add extra keys to the response
- `_get_supported_chart_types`: returns valid JSON with all required chart type entries
- No spec corruption: the url returned by the wrapper matches what the pipeline produced

**Scenarios**: 12 test cases (1 through 12)

**G-Eval metric**: `MCP Wrapper Passthrough Integrity` (one happy-path test, threshold 0.8)

Most Layer 3 assertions are pure `assert` statements — they run without an
`OPENAI_API_KEY` and can be executed via standard pytest.

---

## Setup Instructions

### 1. Install Dependencies

```bash
uv add deepeval --dev
```

`deepeval` is already listed in `[dependency-groups.dev]` in `pyproject.toml`.

### 2. Configure OpenAI API Key

DeepEval G-Eval metrics use GPT-4o by default for LLM-as-judge evaluation.
Layer 2 and Layer 3 G-Eval tests require this key. Pure-assert tests in Layer 3
run without it.

```bash
export OPENAI_API_KEY="your-api-key-here"  # pragma: allowlist secret
```

---

## Running the Evaluations

### Run all three layers

```bash
# Layer 1 — spec builder
uv run deepeval test run evals/test_mcp_routing_deepeval.py

# Layer 2 — pipeline integration
uv run deepeval test run evals/test_viz_integration_deepeval.py

# Layer 3 — MCP tool contract (G-Eval + pure assertions)
uv run deepeval test run evals/test_mcp_tool_contract_deepeval.py
```

### Run Layer 3 contract tests without OpenAI key

```bash
uv run pytest evals/test_mcp_tool_contract_deepeval.py -v -k "not layer3_11"
```

> **Note**: `pyproject.toml` sets `testpaths = ["tests"]`, so running `pytest`
> from the repo root will NOT pick up the `evals/` directory. Use `deepeval test run`
> or point pytest directly at the file as shown above. This is intentional —
> evals are separate from the standard unit-test suite.

---

## What is NOT Evaluated Here (Client-Layer Concerns)

The following belong in `data-ai-chatbot`'s eval suite, not here:

- **Rendering performance**: DOM layout shifts, CSS theme rules, Canvas compiling via `vega-embed`
- **Conversational context**: Resolving implicit follow-up prompts or keyword disambiguation
- **E2E SSE streaming**: The full HTTP POST → SSE stream → LLM interpretation path
