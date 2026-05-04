# PR checklist: dual React + Angular MCP UI

Use for any change that adds or updates paired UI in `packages/mcp-ui` and `packages/mcp-ui-angular`.

## Contracts

- [ ] `packages/tool-types`: schemas / parsers updated for new or changed tool JSON
- [ ] Contract version or changelog note if consumers must coordinate releases

## Shared core

- [ ] No duplicated `prepareSpec`-style logic in React-only or Angular-only files
- [ ] New shared types or helpers live in `packages/mcp-viz-core` when both frameworks need them
- [ ] `packages/mcp-ui` lists `@data360/mcp-viz-core` in `dependencies`; Vite `external` includes it

## React (`@data360/mcp-ui`)

- [ ] Props extend shared base types from viz-core where applicable
- [ ] New library entry / exports in `package.json` + `vite.config.ts` if adding a subpath build

## Angular (`@data360/mcp-ui-angular`)

- [ ] Standalone component; inputs mirror React props (except slot type: `TemplateRef` vs `ReactNode`)
- [ ] `src/public-api.ts` exports new symbols
- [ ] `npm run build` produces `dist/`; `npm pack -w @data360/mcp-ui-angular --dry-run` lists `dist/fesm2022/*.mjs` before publishing

## Docs

- [ ] `packages/mcp-ui/README.md` and `packages/mcp-ui-angular/README.md` updated
- [ ] `components/README.md` lists new packages or surfaces if applicable

## Verification (optional)

- [ ] `packages/mcp-ui`: `npm run dev` demo still runs
- [ ] `packages/mcp-ui-angular-demo`: `npm run build:libs && npm start` shows the feature

## Release

- [ ] Version bumps: publish `mcp-viz-core` before dependent packages when core changed
- [ ] Peer / dependency ranges on `@data360/mcp-viz-core` match published versions
