import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { compile } from "vega-lite";

import {
  CHOROPLETH_MAX_MAP_FACET_PX,
  choroplethLegendVerticalReservePx,
  choroplethMapFacetHeightPx,
  suggestChoroplethSceneHeight,
} from "../src/choropleth-layout";
import { prepareSpec } from "../src/prepare-spec";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

test("choroplethMapFacetHeightPx caps wide containers", () => {
  assert.equal(choroplethMapFacetHeightPx(400), Math.round(400 * 0.44));
  assert.equal(choroplethMapFacetHeightPx(800), CHOROPLETH_MAX_MAP_FACET_PX);
});

test("suggestChoroplethSceneHeight is below loose half-width + strip ceiling", () => {
  const w = 800;
  const chartH = 280;
  const suggested = suggestChoroplethSceneHeight(w, chartH);
  const uncapped = Math.ceil(w / 2) + choroplethLegendVerticalReservePx(w);
  assert.ok(suggested < uncapped);
  assert.ok(
    suggested <= CHOROPLETH_MAX_MAP_FACET_PX + choroplethLegendVerticalReservePx(w),
  );
});

test("compiled choropleth fixture retains Vega legends after prepareSpec", () => {
  const fixturePath = path.join(
    __dirname,
    "../../../static/viz_specs/c80f0e59-8d0d-4c48-a780-5d5131814bf4_vega.json",
  );
  const raw = JSON.parse(fs.readFileSync(fixturePath, "utf8")) as Parameters<
    typeof prepareSpec
  >[0];
  const w = 720;
  const h = suggestChoroplethSceneHeight(w, 280);
  const prepared = prepareSpec(raw, h, w);
  const vega = compile(prepared).spec as { legends?: unknown[] };
  const legendCount = Array.isArray(vega.legends) ? vega.legends.length : 0;
  assert.ok(
    legendCount >= 1,
    `expected at least one Vega legend, got ${legendCount}`,
  );
});
