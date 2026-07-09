import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { TOOL_CONTRACT_VERSION } from "./version";
import {
  isData360VizToolSuccess,
  parseData360VizToolResult,
} from "./viz-contract";

const __dirname = dirname(fileURLToPath(import.meta.url));

describe("Data360VizToolResult", () => {
  it("accepts success payloads from get_viz_spec / get_multi_indicator_viz_spec", () => {
    const ok = parseData360VizToolResult({
      url: "http://localhost:8021/static/viz_specs/abc_vega.json",
      error: null,
      warning: null,
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(isData360VizToolSuccess(ok.data)).toBe(true);
    }
  });

  it("accepts multi-indicator extras", () => {
    const ok = parseData360VizToolResult({
      url: "http://x/y.json",
      error: null,
      strategy: "layered_lines",
      reason: "merged time series",
    });
    expect(ok.success).toBe(true);
  });

  it("rejects non-objects", () => {
    const bad = parseData360VizToolResult(null);
    expect(bad.success).toBe(false);
  });
});

describe("tool contract version sync", () => {
  it("matches schemas/tool-contract-version.json", () => {
    const path = join(__dirname, "..", "schemas", "tool-contract-version.json");
    const raw = JSON.parse(readFileSync(path, "utf-8")) as { version: string };
    expect(raw.version).toBe(TOOL_CONTRACT_VERSION);
  });
});
