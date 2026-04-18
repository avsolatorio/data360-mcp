# @data360/tool-types

TypeScript types and runtime guards for JSON payloads returned by [data360-mcp](https://github.com/worldbank/data360-mcp) tools.

## Install

```bash
npm install @data360/tool-types
```

## Usage

```ts
import {
  TOOL_CONTRACT_VERSION,
  parseData360VizToolResult,
  isData360VizToolSuccess,
} from "@data360/tool-types";

const parsed = parseData360VizToolResult(mcpToolContent);
if (parsed.success && isData360VizToolSuccess(parsed.data)) {
  await fetch(parsed.data.url);
}
```

## Compatibility

| `@data360/tool-types` | Tool contract | Typical `data360-mcp` |
|----------------------|---------------|------------------------|
| `1.0.0` | `1.0.0` | `>= 0.1.2` (see repo release notes) |

The **tool contract version** is the semver in `schemas/tool-contract-version.json` (mirrored under `contracts/` and `src/data360/tool_contract_version.json` in the server repo). Bump it when MCP tool JSON shapes change in a **breaking** way for consumers; release `@data360/tool-types` and UI packages together.

Use `TOOL_CONTRACT_VERSION` and `data360.get_tool_contract_version()` (Python) to assert alignment in your app if needed.

## Exports

- **`TOOL_CONTRACT_VERSION`** — string semver for the shared contract.
- **`parseData360VizToolResult(unknown)`** — Zod `safeParse` for `data360_get_viz_spec` / `data360_get_multi_indicator_viz_spec` results (`url`, `error`, optional `warning`, `strategy`, `reason`).
- **`isData360VizToolSuccess`** — type guard for successful viz payloads.

## Development

```bash
npm install
npm run build
npm test
```
