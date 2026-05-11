import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { compile } from "vega-lite";

import {
  choroplethMapBandCenterY,
  patchVegaSpecChoroplethWheelZoom,
} from "../src/choropleth-wheel-zoom";
import { prepareSpec } from "../src/prepare-spec";
import { suggestChoroplethSceneHeight } from "../src/choropleth-layout";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

test("choropleth wheel-zoom patch keeps min base scale so gradient legend is not covered/clipped", () => {
  const fixturePath = path.join(
    __dirname,
    "../../../static/viz_specs/c80f0e59-8d0d-4c48-a780-5d5131814bf4_vega.json",
  );
  const raw = JSON.parse(fs.readFileSync(fixturePath, "utf8")) as Parameters<
    typeof prepareSpec
  >[0];
  const w = 640;
  const h = suggestChoroplethSceneHeight(w, 280);
  const prepared = prepareSpec(raw, h, w);
  const compiled = compile(prepared).spec as Record<string, unknown>;
  const patched = patchVegaSpecChoroplethWheelZoom(compiled, {
    plotWidth: prepared.width as number,
    plotHeight: prepared.height as number,
    legendStripPx: 96,
  });
  const signals = patched.signals as Array<{
    name?: string;
    update?: string;
    value?: number;
  }>;
  const base = signals.find((s) => s.name === "choropleth_base_scale");
  assert.ok(base?.update?.includes("min(width / (2 * PI)"));
  assert.equal(patched.padding, compiled.padding);
  const strip = 96;
  const plotH = prepared.height as number;
  const ty = signals.find((s) => s.name === "choropleth_ty");
  assert.equal(ty?.value, choroplethMapBandCenterY(plotH, strip));
});
