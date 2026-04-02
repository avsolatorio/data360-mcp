---
id: MCP-003
repo: data360-mcp
title: Many countries — beeswarm/strip or facet instead of clutter
status: pending
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

## Acceptance criteria

- [ ] Heuristic selects alternate mark/layout above a configurable threshold.
- [ ] Unit tests cover threshold boundary and spec shape.
- [ ] Planner/chatbot prompts (BE-001) mention behavior if user-facing copy needed — optional follow-up.

## Dependencies

- **MCP-002** (soft): tooltip behavior should remain sane on the chosen mark.
