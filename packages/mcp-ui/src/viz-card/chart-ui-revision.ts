/**
 * Bump whenever choropleth / chart-card embed behavior changes.
 *
 * **Host contract:** After editing `@data360/mcp-ui` sources, run `pnpm run build` in
 * `packages/mcp-ui`, then reinstall/rebuild the consuming app (e.g. Next `pnpm install` +
 * `pnpm run build:local`) so `node_modules/@data360/mcp-ui` resolves to fresh `dist/`.
 *
 * Optional UI line (below Source on choropleth) reads `Data360 map UI · ${DATA360_CHART_UI_REVISION}`.
 */
export const DATA360_CHART_UI_REVISION = "2026.05.09.12-source-legend-gap";
