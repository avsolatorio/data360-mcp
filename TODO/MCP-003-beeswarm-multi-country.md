---
id: MCP-003
repo: data360-mcp
title: Many countries — beeswarm/strip or facet instead of clutter
status: pending
priority: medium
depends_on: []
blocks: []
soft_depends_on:
  - MCP-002
---

# MCP-003 — High cardinality series (multi-country) visualization

## Goal

When many countries/series make line charts unreadable or data is truncated, prefer a strip/beeswarm-style layout, faceting, or another documented strategy in the viz pipeline.

## Context

- `src/data360/viz_config.py`, `src/data360/visualization.py`.
- May require `data360_get_supported_chart_types` updates if new chart type names are exposed.
- Product threshold (country count) may come from design — document default in code comments.

## Implementation hints
- **Cardinality detection:** `src/data360/visualization.py` lines 490–515 — loops over breakdown dims (`country`, `sex`, `age`, `urbanisation`), picks first with `.nunique() > 1` as color dim. No upper-bound check for "too many series".
- **Chart type selection:** `src/data360/viz_config.py` → `should_use_temporal_x_axis()` lines 367–448. Returns `(True, None)` for time-series or `(False, categorical_field)` for categorical. Preference scores by chart type: tick=1.0, point=0.7, bar=0.5, line=0.2, area=0.1.
- **Current behavior:** With 20+ countries, Draco picks a line or bar chart with color encoding for each country. Above ~10 series, the chart becomes unreadable — overlapping lines, crowded legend.
- **Desired behavior:** When `country.nunique() > N` (suggested threshold: 10, make it configurable) AND single-year data (temporal cardinality = 1), switch to strip/beeswarm: `mark_point()` with jitter, value on y-axis, country as color limited to top-N or omitted.
- **Beeswarm in Vega-Lite:** No native beeswarm mark. Use `mark_point()` with `transform: [{"calculate": "random()", "as": "jitter"}]` and encode jitter on x-axis. Or use Altair's `mark_tick()` (already in the chart type list at line 173) as a simpler strip chart alternative.
- **Where to add:** Add `should_use_beeswarm(viz_data)` function in `viz_config.py` near `should_use_temporal_x_axis()`. Call it in `visualization.py` before Draco encoding (around line 490) when cardinality exceeds threshold.
- **Test file:** `tests/test_visualization.py`. Add `TestHighCardinalityChartSelection` — assert beeswarm/strip selected when country count > threshold, line chart when ≤ threshold.
- **Gotchas:** Vega-Lite jitter requires a `calculate` transform — adds complexity to the spec. `tick` mark already exists and may be sufficient as a simpler strip chart without jitter. Clarify with product whether jitter is required or if a tick/strip is acceptable. Cardinality thresholds should be centralised (add to `MCPServerSettings` in `config.py` alongside future `MCP_CACHE_TTL`).

## Acceptance criteria

- [ ] Heuristic selects alternate mark/layout above a configurable threshold.
- [ ] Unit tests cover threshold boundary and spec shape.
- [ ] Planner/chatbot prompts (BE-001) mention behavior if user-facing copy needed — optional follow-up.

## Dependencies

- **MCP-002** (soft): tooltip behavior should remain sane on the chosen mark.
