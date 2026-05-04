# Angular demo — `@data360/mcp-ui-angular`

Small Angular app that embeds `Data360VegaChartCardComponent` with the same sample Vega-Lite spec as the React demo (`packages/mcp-ui`).

## One-time setup

From this directory (`packages/mcp-ui-angular-demo`):

```bash
npm run build:libs
npm install
```

`build:libs` compiles `@data360/mcp-viz-core` and `@data360/mcp-ui-angular` (the demo depends on `@data360/mcp-ui-angular` via the monorepo workspace so it shares the same `@angular/core` as the app; run **`build:libs` again** after you change the library source so `packages/mcp-ui-angular/dist` is up to date).

## Run the demo

```bash
npm start
```

Then open the URL shown in the terminal (usually `http://localhost:4200`).

## From the monorepo root

```bash
cd packages/mcp-ui-angular-demo
npm run build:libs && npm install && npm start
```
