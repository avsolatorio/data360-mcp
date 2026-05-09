import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { compile } from "vega-lite";

import { patchVegaSpecChoroplethMapGroupClip } from "../src/choropleth-map-clip";
import { patchVegaSpecChoroplethWheelZoom } from "../src/choropleth-wheel-zoom";
import { prepareSpec } from "../src/prepare-spec";
import { suggestChoroplethSceneHeight } from "../src/choropleth-layout";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

test("choropleth map group clip wraps marks after wheel-zoom patch", () => {
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
  const zoomed = patchVegaSpecChoroplethWheelZoom(compiled, {
    plotWidth: prepared.width as number,
    plotHeight: prepared.height as number,
    legendStripPx: 96,
  });
  const clipped = patchVegaSpecChoroplethMapGroupClip(zoomed);
  const marks = clipped.marks as unknown[];
  assert.equal(marks.length, 1);
  const g = marks[0] as Record<string, unknown>;
  assert.equal(g.type, "group");
  assert.equal(g.name, "choropleth_map_clip_group");
  assert.equal(g.clip, true);
  const inner = g.marks as unknown[];
  assert.ok(Array.isArray(inner) && inner.length >= 1);
  const legends = clipped.legends as unknown[] | undefined;
  assert.ok(Array.isArray(legends) && legends.length >= 1);
});

test("choropleth map group clip is idempotent", () => {
  const fixturePath = path.join(
    __dirname,
    "../../../static/viz_specs/c80f0e59-8d0d-4c48-a780-5d5131814bf4_vega.json",
  );
  const raw = JSON.parse(fs.readFileSync(fixturePath, "utf8")) as Parameters<
    typeof prepareSpec
  >[0];
  const w = 400;
  const h = suggestChoroplethSceneHeight(w, 260);
  const prepared = prepareSpec(raw, h, w);
  const compiled = compile(prepared).spec as Record<string, unknown>;
  const once = patchVegaSpecChoroplethMapGroupClip(
    patchVegaSpecChoroplethWheelZoom(compiled, {
      plotWidth: prepared.width as number,
      plotHeight: prepared.height as number,
      legendStripPx: 88,
    }),
  );
  const twice = patchVegaSpecChoroplethMapGroupClip(once);
  assert.deepEqual(twice.marks, once.marks);
});
