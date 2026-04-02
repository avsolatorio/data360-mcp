---
id: MCP-002
repo: data360-mcp
title: Vega-Lite — default tooltips for line/area charts
status: pending
priority: medium
depends_on: []
blocks: []
---

# MCP-002 — Default chart tooltips

## Goal

Line (and similar) charts emitted by `get_viz_spec` show hover tooltips by default for readability in embedded previews (e.g. chat `ChartPreview`).

## Context

- Implementation likely in `src/data360/visualization.py` and/or `src/data360/viz_config.py` where Vega-Lite spec is built.
- Frontend: `vercel-ai-chatbot` renders spec via vega-embed in `frontend/components/data360/chart-preview.tsx` — no change required if spec includes tooltips.

## Implementation hints
- **Entry point (Draco path):** `src/data360/visualization.py` line 555–556 — `tooltip_cols = list(viz_data.columns); chart = chart.encode(tooltip=tooltip_cols)`. This runs after Draco rendering.
- **Entry point (fallback path):** `src/data360/visualization.py` line 603 — `base = alt.Chart(viz_data).mark_line().encode(tooltip=fc)`. Fallback uses `fc` (field config) for tooltip.
- **Current behavior:** Tooltip is a flat list of all columns. Column names at this point are already renamed: `time_period → year`, `obs_value → value`, `ref_area → country` (renaming happens at lines 414–434). Tooltip shows raw renamed columns with no formatting.
- **Desired behavior:** Structured tooltips per chart type — for line/area: show `year`, `value`, `country` with human-readable labels and number formatting. Use `alt.Tooltip(field, title, format)` objects instead of raw column names.
- **Chart types to cover:** line (line 149), area (line 167) as minimum. bar (line 155), point (line 161), tick (line 173) as stretch.
- **Test file:** `tests/test_visualization.py` — existing class `TestGetVizSpecDracoFallbackWarning` (lines 11–147). Add a new test class `TestTooltipEncoding` that asserts tooltip fields and titles on the returned spec dict.
- **Gotchas:** Tooltip encoding happens AFTER Draco (line 555) — this is intentional to allow override. Fallback path (line 603) hardcodes `mark_line()` regardless of chart type — tooltip fix should handle both paths. Codelist mapping runs before viz (lines 421–431) so `country` column contains names not codes at tooltip time.

## Acceptance criteria

- [ ] Line/area (and other relevant marks) include `tooltip` encoding or mark-level tooltip defaults.
- [ ] Tests in `tests/test_visualization.py` updated or added to assert tooltip presence in spec JSON.
- [ ] Performance/tooltip density acceptable for many points (coordinate with MCP-003).

## Dependencies

- None.

## Related

- **MCP-003** often touches the same spec-building code; coordinate or sequence to reduce merge conflicts (soft dependency only).
