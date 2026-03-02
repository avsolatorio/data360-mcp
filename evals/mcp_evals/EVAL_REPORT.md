# Evaluation Report - March 2, 2026

Current state of the data360 MCP server evaluation, including results, findings, and actionable recommendations.

## Results Summary

| Suite | Pass Rate | Tests | Cost | Time |
|---|---|---|---|---|
| DeepEval | 89.39% (59/66) | 3 metrics x 22 scenarios | $2.21 | 507s |
| QA-Pair | 100% (20/20) | 20 pairs | ~$0.40 | ~70s |

## DeepEval Breakdown

| Metric | Pass/Total | Notes |
|---|---|---|
| MCPUseMetric | 22/22 | Tool primitives are well designed |
| ToolCorrectnessMetric | 17/22 | 5 failures from extra or missing tools |
| ArgumentCorrectnessMetric | 20/22 | 2 failures from incomplete args |

### ToolCorrectness Failures (5)

| Scenario | Issue |
|---|---|
| Poverty by sex (Uganda) | LLM checked disaggregation but never called get_data |
| Visualization (population China) | Needed 2 attempts, first indicator search failed |
| Visualization (GDP Kenya and Tanzania) | Called find_codelist_value before search (extra tool) |
| Codelist (Kenya and Uganda) | Called find_codelist_value twice instead of comma-separated |
| HDI methodology | Called get_metadata directly without search_indicators |

### ArgumentCorrectness Failures (2)

| Scenario | Issue |
|---|---|
| Poverty by sex (Uganda) | Never used SEX disaggregation filter |
| Life expectancy (Japan) | Returned male-only data instead of total |

## Recommendations

### 1. Add "search first" note to 5 tool docstrings - HIGH IMPACT, LOW EFFORT

5 tools need database_id and indicator_id but do not say how to get them.

| Tool | Needs |
|---|---|
| get_metadata | database_id, indicator_id |
| get_data | database_id, indicator_id |
| get_disaggregation | database_id, indicator_id |
| get_data_api_url | database_id, indicator_id |
| get_viz_spec | database_id, indicator_id |

Fix: Add to each docstring in api.py:

```
NOTE: Use data360_search_indicators first to find valid database_id and indicator_id values.
```

### 2. LLM ignores comma-separated example in find_codelist_value - LOW IMPACT

The docstring already documents comma-separated queries (`query="Kenya, Uganda"`) with examples and a performance tip. Despite this, the LLM still calls the tool once per country.

Note: Not a docstring issue. The guidance already exists. This is an LLM compliance issue that may improve with better models or could be reinforced via system prompt in the chatbot layer.

### 3. Add fallback guidance for missing disaggregation - MEDIUM IMPACT

When asked "poverty by sex", the LLM checks disaggregation, finds no SEX option, and stops.

Fix: Note in get_disaggregation docstring: "If desired dimension is unavailable, try searching for alternative indicators."

### 4. Reduce visualization retry overhead - LOW IMPACT

Visualization scenarios sometimes need 2 get_viz_spec calls due to wrong indicator on first try.

Fix: Suggest in docstring to verify indicator availability before generating visualization.

## Run Logs

All raw results are stored in evals/mcp_evals/results/:

| File | Contents |
|---|---|
| run_20260302T101932Z.jsonl | DeepEval: 22 scenario logs |
| qa_run_20260302T122253Z.json | QA: 20 pair results |
| qa_report.md | QA: markdown report |
