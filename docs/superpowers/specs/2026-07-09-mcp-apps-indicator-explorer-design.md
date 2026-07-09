# Design Specification: Interactive Indicator Explorer via prefab_ui

## Goal
Build an interactive indicator discovery and explorer experience using native `prefab_ui` components, combined with a local HTTP search API endpoint, to help users find and select indicators for visualization.

## User Review Required
This replaces the static HTML-based explorer (`ui://data360-explorer/index.html`) with a native `prefab_ui` dashboard. The chart rendering remains on our custom visualization engine.

## Proposed Changes

### Backend API: `src/data360/server.py`
* Add `GET /api/indicators/search` endpoint.
* It accepts `query` and optional `database` parameters and returns matching indicator lists by reusing `_search_indicators`.

### MCP Tools: `src/data360/mcp_server/tools.py`
* Expose an internal tool `data360_search_indicators_internal` that returns raw dictionaries.
* Redefine `data360_indicator_explorer` to return a `PrefabApp` with:
  * A search `Form` component.
  * Inputs and dropdown select components.
  * A `ForEach` card grid of results.
  * A `Plot Chart` button that triggers a `SendMessage` action to post the selection command back to the chatbot.
* Remove the custom HTML resource `ui://data360-explorer/index.html` since it is replaced by the native app.

## Verification Plan

### Automated Tests
* Add `tests/test_indicator_explorer_app.py` to:
  * Verify the `/api/indicators/search` GET endpoint works.
  * Verify `data360_indicator_explorer` returns a valid `PrefabApp` structure.
