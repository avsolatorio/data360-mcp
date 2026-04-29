# @data360/mcp-ui

React components for presenting [Data360 MCP](https://github.com/worldbank/data360-mcp) tool output with World Bank styling.

Shared Vega-Lite logic (`prepareSpec`, `WB_THEME`, etc.) lives in **`@data360/mcp-viz-core`**, which this package depends on. For **Angular** apps, use [`@data360/mcp-ui-angular`](../mcp-ui-angular) instead.

## Install

```bash
npm install @data360/mcp-ui @data360/tool-types vega vega-lite vega-embed
```

`@data360/mcp-viz-core` is installed transitively with `@data360/mcp-ui`. `@data360/tool-types` is optional but recommended for parsing MCP JSON before rendering.

## Viz chart card

Import the Vega-Lite chart card (for `data360_get_viz_spec` and `data360_get_multi_indicator_viz_spec`):

```tsx
import { VegaChartCard } from "@data360/mcp-ui/viz-card";
import {
  parseData360VizToolResult,
  isData360VizToolSuccess,
} from "@data360/tool-types";

const parsed = parseData360VizToolResult(toolResult);
if (!parsed.success || !isData360VizToolSuccess(parsed.data)) {
  return <p>{parsed.success ? parsed.data.error : "Invalid payload"}</p>;
}

const specResponse = await fetch(parsed.data.url);
const spec = await specResponse.json();

<VegaChartCard
  spec={spec}
  subtitle="Brazil, India · 2018–2022"
  source="World Bank — WDI"
  annotations={[
    { id: 1, text: "Brazil leads with 83% renewable electricity in 2020." },
  ]}
/>;
```

### Compatibility

| `@data360/mcp-ui` | `@data360/mcp-viz-core` | Tool contract | Viz tools |
|-------------------|-------------------------|---------------|-----------|
| `0.0.1` | `0.0.1` | `1.0.0` | `data360_get_viz_spec`, `data360_get_multi_indicator_viz_spec` |

When the MCP server changes the JSON shape of viz tool results or the Vega-Lite conventions stored at `url`, bump the **tool contract** (see `@data360/tool-types` README) and release matching **`@data360/tool-types`**, **`@data360/mcp-viz-core`**, **`@data360/mcp-ui`**, and **`@data360/mcp-ui-angular`** versions together.

### Peer dependencies

| Package | Version |
|---------|---------|
| `react` | ≥ 18 |
| `react-dom` | ≥ 18 |
| `vega` | ≥ 5 |
| `vega-lite` | ≥ 5 |
| `vega-embed` | ≥ 6 |

## Development

From the `packages/mcp-ui` directory (or the repo root with npm workspaces):

```bash
npm install
npm run dev
npm run build
```

`npm run dev` serves the demo at `http://localhost:5173`.

### K360 interactive demo mode

The demo app can call the staged K360 backend endpoint from
`examples/agents/langchain-graph/demo_web/server.py` (`POST /api/k360-query`).

1. Start the backend demo API:

```bash
uv run uvicorn demo_web.server:app --app-dir examples/agents/langchain-graph --host 127.0.0.1 --port 8844
```

2. Start the React demo and point it to that API:

```bash
VITE_K360_API_BASE=http://127.0.0.1:8844 npm run dev
```

The UI renders:
- narrative markdown (sectioned style similar to the chatbot renderer),
- content packet inspector (`gate`, `rewrite`, packet fields),
- charts through `VegaChartCard` when viz tool output includes a spec URL.

## What the chart card does to your spec

The spec passes through an 8-guard pipeline (`prepareSpec`) before reaching vega-embed:

1. Inline dataset — resolves `spec.datasets[spec.data.name]` → `spec.data.values`
2. Responsive sizing — sets `width: "container"`, configurable height
3. Suppress legend — sets `encoding.color.legend = null` (card renders its own)
4. Strip params — removes zoom/pan `params` (conflicts with card controls)
5. Normalize schema — rewrites `$schema` v6 → v5 for vega-embed compatibility
6. WB theme — merges the World Bank Vega theme into `config`
7. `scale.zero` — `false` for line/area/point/tick; `true` for bar
8. x-axis format — applies `%Y` only when `encoding.x.type === "temporal"`

## Low-level exports

These are re-exported from `@data360/mcp-viz-core` for convenience:

```ts
import {
  prepareSpec,
  parseSpec,
  getMark,
  WB_THEME,
  WB_PALETTE,
} from "@data360/mcp-ui/viz-card";
```

You can also import them directly from `@data360/mcp-viz-core` in non-React code.
