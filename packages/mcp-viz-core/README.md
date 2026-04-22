# @data360/mcp-viz-core

Framework-agnostic TypeScript utilities for Data360 MCP **Vega-Lite** tool output: the same `prepareSpec` / `parseSpec` pipeline and World Bank theme used by [`@data360/mcp-ui`](../mcp-ui) (React) and [`@data360/mcp-ui-angular`](../mcp-ui-angular) (Angular).

## Install

```bash
npm install @data360/mcp-viz-core
```

## API

- **`prepareSpec(spec, chartHeight?)`** — eight-guard pipeline (inline datasets, responsive sizing, WB theme merge, axis rules, etc.). See [`packages/mcp-ui` README](../mcp-ui/README.md) for the full list.
- **`parseSpec(spec, palette)`** — legend metadata from the **raw** spec (before `prepareSpec`).
- **`getMark(spec)`**, **`WB_THEME`**, **`WB_PALETTE`**, **`WB_THEME_URL`**
- Types: **`VLSpec`**, **`Annotation`**, **`VegaChartCardBaseProps`**, etc.

## Version coupling

When the MCP server or [`@data360/tool-types`](../tool-types) changes viz JSON shape or Vega-Lite conventions, bump **`@data360/mcp-viz-core`** together with **`@data360/mcp-ui`** and **`@data360/mcp-ui-angular`** so all consumers stay aligned.
