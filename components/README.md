# Companion UI components

Published npm packages live under [`packages/`](../packages/) as a workspace:

- **`@data360/tool-types`** — MCP tool JSON contracts and parsers (`packages/tool-types`).
  - `viz-contract`: Zod schemas for `data360_get_viz_spec` / `data360_get_multi_indicator_viz_spec` output.
  - `search-contract`: Zod schemas for `data360_search_indicators` output (single and multi-query).
- **`@data360/mcp-viz-core`** — Framework-agnostic Vega-Lite prep and WB theme (`packages/mcp-viz-core`).
- **`@data360/mcp-ui`** — React UI components for MCP tool output (`packages/mcp-ui`).
  - `@data360/mcp-ui/viz-card`: `VegaChartCard` — renders Vega-Lite chart specs with WB styling.
  - `@data360/mcp-ui/search-card`: `SearchResultCard` — renders enriched indicator search results in flat (merged) or grouped (by_query) layout with country coverage badges.
- **`@data360/mcp-ui-angular`** — Angular standalone chart card (`packages/mcp-ui-angular`).

Install and usage examples are in each package README.
