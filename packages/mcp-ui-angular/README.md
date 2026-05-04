# @data360/mcp-ui-angular

Angular **standalone** components for presenting Data360 MCP tool output, aligned with the React [`@data360/mcp-ui`](../mcp-ui) chart card and the shared [`@data360/mcp-viz-core`](../mcp-viz-core) pipeline.

## Install

```bash
npm install @data360/mcp-ui-angular @data360/mcp-viz-core @data360/tool-types vega vega-lite vega-embed
```

`@data360/tool-types` is optional but recommended for parsing MCP tool results before passing a `spec` into the component.

## Vega chart card

Import `Data360VegaChartCardComponent` and add it to your standalone component’s `imports` (or declare it in an `NgModule`).

```typescript
import { Component, OnInit } from "@angular/core";
import {
  parseData360VizToolResult,
  isData360VizToolSuccess,
} from "@data360/tool-types";
import type { VLSpec } from "@data360/mcp-viz-core";
import { Data360VegaChartCardComponent } from "@data360/mcp-ui-angular";

@Component({
  selector: "app-chart",
  standalone: true,
  imports: [Data360VegaChartCardComponent],
  template: `
    <data360-vega-chart-card
      [spec]="spec"
      [subtitle]="subtitle"
      [source]="source"
      [annotations]="annotations"
    />
  `,
})
export class ChartExampleComponent implements OnInit {
  spec!: VLSpec;
  subtitle = "Brazil, India · 2018–2022";
  source = "World Bank — WDI";
  annotations = [{ id: 1, text: "Example callout." }];

  // Replace with your MCP tool result payload.
  toolResult: unknown = {};

  async ngOnInit() {
    const parsed = parseData360VizToolResult(this.toolResult);
    if (!parsed.success || !isData360VizToolSuccess(parsed.data)) return;
    const specResponse = await fetch(parsed.data.url);
    this.spec = await specResponse.json();
  }
}
```

### Right-rail top slot (React `railTopSlot`)

Pass an `ng-template` to **`[railTopSlot]`** for optional content above the action icons (e.g. expand in chat):

```html
<ng-template #railTop>
  <button type="button">Expand</button>
</ng-template>

<data360-vega-chart-card [spec]="spec" [railTopSlot]="railTop" />
```

### Optional handlers

Same contract as React: **`[onDownload]`** and **`[onExport]`** accept callbacks; if omitted, the component triggers default CSV / PNG downloads in the browser.

### Peer dependencies

| Package | Notes |
|--------|--------|
| `@angular/core`, `@angular/common` | **17.0.0**–20.x (see `package.json` peer range `>=17.0.0 <21.0.0`) |
| `@data360/mcp-viz-core` | Same major/minor as this package |
| `rxjs` | ^7.5 |
| `vega`, `vega-lite`, `vega-embed` | Same as React viz card |

## Development

From `packages/mcp-ui-angular`:

```bash
npm install
npm run build
```

Output is written to `dist/` (FESM bundles and typings for publishing).

### Publishing to npm

The published tarball is the **package root** plus the **`dist/`** tree only (`files` in `package.json`). Entry points use **`./dist/...`** (`module`, `typings`, and `exports`).

From the monorepo root (after `npm login`):

```bash
npm pack -w @data360/mcp-ui-angular --dry-run   # optional: inspect tarball
npm publish -w @data360/mcp-ui-angular --access public
```

`prepublishOnly` runs **`npm run build`** so `dist/` is fresh before publish.

### Live demo app

A runnable sample app lives in **`packages/mcp-ui-angular-demo`** in this repo ([browse on GitHub](https://github.com/worldbank/data360-mcp/tree/main/packages/mcp-ui-angular-demo)). Clone the monorepo, then from `packages/mcp-ui-angular-demo`: `npm run build:libs`, then `npm install`, then `npm start` (see [that folder’s README](https://github.com/worldbank/data360-mcp/blob/main/packages/mcp-ui-angular-demo/README.md)).

## Version coupling

Keep versions aligned across **`@data360/tool-types`**, **`@data360/mcp-viz-core`**, **`@data360/mcp-ui`**, and **`@data360/mcp-ui-angular`** when viz contracts or `prepareSpec` behavior changes (see [`packages/mcp-ui` compatibility table](../mcp-ui/README.md)).
