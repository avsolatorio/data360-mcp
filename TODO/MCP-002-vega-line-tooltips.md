---
id: MCP-002
repo: data360-mcp
title: Vega-Lite — default tooltips for line/area charts
status: pending
depends_on: []
blocks: []
---

# MCP-002 — Default chart tooltips

## Goal

Line (and similar) charts emitted by `get_viz_spec` show hover tooltips by default for readability in embedded previews (e.g. chat `ChartPreview`).

## Context

- Implementation likely in `src/data360/visualization.py` and/or `src/data360/viz_config.py` where Vega-Lite spec is built.
- Frontend: `vercel-ai-chatbot` renders spec via vega-embed in `frontend/components/data360/chart-preview.tsx` — no change required if spec includes tooltips.

## Acceptance criteria

- [ ] Line/area (and other relevant marks) include `tooltip` encoding or mark-level tooltip defaults.
- [ ] Tests in `tests/test_visualization.py` updated or added to assert tooltip presence in spec JSON.
- [ ] Performance/tooltip density acceptable for many points (coordinate with MCP-003).

## Dependencies

- None.

## Related

- **MCP-003** often touches the same spec-building code; coordinate or sequence to reduce merge conflicts (soft dependency only).
