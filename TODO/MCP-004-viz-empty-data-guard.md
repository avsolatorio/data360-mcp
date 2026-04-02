---
id: MCP-004
repo: data360-mcp
title: viz — guard against empty data in generate_vega_spec()
status: pending
depends_on: []
blocks: []
source: pr-review
file_ref: src/data360/mcp_server/viz.py
line_ref: 142
---

# MCP-004 — Handle empty `data` list in `generate_vega_spec()`

## Goal

Prevent `generate_vega_spec()` from crashing with a `KeyError` when `data` is an empty list. Return a user-friendly error message or a graceful empty chart spec instead.

## Context

- PR review flagged that `data[0]['date']` raises `KeyError` when `data=[]`.
- The referenced file path in the review is `src/data360/mcp_server/viz.py` (line 142); the actual implementation lives in `src/data360/visualization.py` and/or `src/data360/viz_config.py` — confirm exact location before patching.
- Empty data can legitimately occur when an API query returns no results for a given filter combination; callers should receive a clear signal rather than an unhandled exception.

## Acceptance criteria

- [ ] `generate_vega_spec()` (or equivalent entry point) checks for an empty `data` list before accessing `data[0]`.
- [ ] Returns either a well-formed error dict/message or a minimal empty-chart Vega-Lite spec (document the chosen convention in a code comment).
- [ ] Unit test added: `test_generate_vega_spec_empty_data` asserts no exception is raised and the return value is well-formed.
- [ ] No regression on existing non-empty data tests.

## Implementation hints

- **Entry point:** `src/data360/visualization.py` → `get_viz_spec()` (function starting ~line 183). The `_fetch_data_internal()` helper at line ~109 already raises `ValueError("No data found...")` for empty API responses, and `get_viz_spec()` catches that at line ~243. However, if `data` reaches downstream spec-building steps (e.g. after filtering in the `relevant_fields` branch), an empty DataFrame/list can still cause `KeyError` or `IndexError` on first-row access.
- **Current behavior:** When `data` is empty after filtering, the code may attempt `data[0]['date']` (or an equivalent first-row access) and raise `KeyError` uncaught.
- **Desired behavior:** Add a guard immediately after any potential reduction to empty (e.g. after `viz_data = data[valid_cols].copy()`) that returns `err("Error: No data available after applying the requested filters.")`. The existing check at line ~439 (`if viz_data.empty: return err(...)`) provides the pattern to follow.
- **Test file:** `tests/test_visualization.py` — add a test case in the existing `TestGetVizSpecDracoFallbackWarning` class or a new class. Mock `_fetch_data_internal` to return a DataFrame that becomes empty after field filtering, and assert the returned dict has `url=None` and a non-None `error`.
- **Prior art:** `_fetch_data_internal()` at line ~109 already checks `if not raw_data: raise ValueError(...)` — follow the same early-exit pattern. The `if viz_data.empty: return err(...)` guard at line ~439 shows how to do it after cleaning.
- **Gotchas:** The file path in the original PR review (`src/data360/mcp_server/viz.py`) does not exist yet. If a separate `viz.py` module is created as part of a refactor, place the guard there; otherwise add it to `src/data360/visualization.py`.

## Dependencies

- None.

## Related

- **MCP-002** / **MCP-003** — touch the same spec-building pipeline; sequence or coordinate to avoid merge conflicts.
