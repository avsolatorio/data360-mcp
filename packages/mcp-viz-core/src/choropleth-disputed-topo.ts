/**
 * TopoJSON object name in bundled `wb_disputed_areas_topo.json` (e.g. chatbot `public/json/`).
 */
export const CHOROPLETH_DISPUTED_TOPO_FEATURE = "wb_disputed_areas_geo";

function isDisputedAreasChoroplethLayerUrl(url: string): boolean {
  return url.trim().toLowerCase().includes("wb_disputed_areas");
}

/**
 * Point choropleth disputed-outline layers at a bundled TopoJSON URL and set ``data.format``.
 * Use for cached specs that still reference remote GeoJSON or legacy disputed URLs.
 */
export function rewriteChoroplethDisputedOverlayToBundledTopo(
  spec: Record<string, unknown>,
  bundledTopoUrl: string,
): Record<string, unknown> {
  const layers = spec.layer;
  if (!Array.isArray(layers)) {
    return spec;
  }
  let changed = false;
  const nextLayers = layers.map((ly) => {
    if (ly === null || typeof ly !== "object" || Array.isArray(ly)) {
      return ly;
    }
    const layer = ly as Record<string, unknown>;
    const data = layer.data;
    if (data === null || typeof data !== "object" || Array.isArray(data)) {
      return ly;
    }
    const d = data as Record<string, unknown>;
    const url = d.url;
    if (typeof url !== "string" || !isDisputedAreasChoroplethLayerUrl(url)) {
      return ly;
    }
    changed = true;
    return {
      ...layer,
      data: {
        url: bundledTopoUrl,
        format: {
          type: "topojson",
          feature: CHOROPLETH_DISPUTED_TOPO_FEATURE,
        },
      },
    };
  });
  if (!changed) {
    return spec;
  }
  return { ...spec, layer: nextLayers };
}

/**
 * Forces ``data.format`` to TopoJSON for any layer whose ``data.url`` references disputed areas.
 * Use for **legacy chart JSON** still served from the charts store (old server emitted
 * ``{ type: "json", property: "features" }`` for the same topo file). New MCP builds should set
 * format explicitly; this normalizes at read time so the UI validator passes.
 */
export function coerceChoroplethDisputedLayersToTopoJsonFormat(
  spec: Record<string, unknown>,
): Record<string, unknown> {
  const layers = spec.layer;
  if (!Array.isArray(layers)) {
    return spec;
  }
  let changed = false;
  const nextLayers = layers.map((ly) => {
    if (ly === null || typeof ly !== "object" || Array.isArray(ly)) {
      return ly;
    }
    const layer = ly as Record<string, unknown>;
    const data = layer.data;
    if (data === null || typeof data !== "object" || Array.isArray(data)) {
      return ly;
    }
    const d = data as Record<string, unknown>;
    const url = d.url;
    if (typeof url !== "string" || !isDisputedAreasChoroplethLayerUrl(url)) {
      return ly;
    }
    const want: Record<string, string> = {
      type: "topojson",
      feature: CHOROPLETH_DISPUTED_TOPO_FEATURE,
    };
    const fmt = d.format;
    if (
      fmt !== null &&
      typeof fmt === "object" &&
      !Array.isArray(fmt) &&
      (fmt as Record<string, unknown>).type === want.type &&
      (fmt as Record<string, unknown>).feature === want.feature
    ) {
      return ly;
    }
    changed = true;
    return {
      ...layer,
      data: {
        ...d,
        format: want,
      },
    };
  });
  if (!changed) {
    return spec;
  }
  return { ...spec, layer: nextLayers };
}

export type ChoroplethDisputedTopoJsonValidation =
  | { ok: true }
  | { ok: false; errors: string[] };

/**
 * Ensures every Vega-Lite layer whose `data.url` references disputed areas uses TopoJSON with the
 * expected feature name — not legacy GeoJSON or untyped URLs.
 */
export function validateChoroplethDisputedLayersUseTopoJson(
  spec: Record<string, unknown>,
): ChoroplethDisputedTopoJsonValidation {
  const layers = spec.layer;
  if (!Array.isArray(layers)) {
    return { ok: true };
  }
  const errors: string[] = [];
  for (let i = 0; i < layers.length; i++) {
    const ly = layers[i];
    if (ly === null || typeof ly !== "object" || Array.isArray(ly)) {
      continue;
    }
    const layer = ly as Record<string, unknown>;
    const data = layer.data;
    if (data === null || typeof data !== "object" || Array.isArray(data)) {
      continue;
    }
    const d = data as Record<string, unknown>;
    const url = d.url;
    if (typeof url !== "string" || !isDisputedAreasChoroplethLayerUrl(url)) {
      continue;
    }

    const fmt = d.format;
    if (fmt === null || typeof fmt !== "object" || Array.isArray(fmt)) {
      errors.push(
        `layer[${i}] disputed overlay must use TopoJSON (set data.format with type "topojson").`,
      );
      continue;
    }
    const f = fmt as Record<string, unknown>;
    const t = f.type;
    if (typeof t !== "string" || t.toLowerCase() !== "topojson") {
      errors.push(
        `layer[${i}] disputed overlay must use data.format.type "topojson" (got ${JSON.stringify(t)}).`,
      );
    }
    const feat = f.feature;
    if (feat !== CHOROPLETH_DISPUTED_TOPO_FEATURE) {
      errors.push(
        `layer[${i}] disputed TopoJSON must use feature "${CHOROPLETH_DISPUTED_TOPO_FEATURE}" (got ${JSON.stringify(feat)}).`,
      );
    }
  }
  if (errors.length > 0) {
    return { ok: false, errors };
  }
  return { ok: true };
}

/**
 * @throws Error when validation fails (see {@link validateChoroplethDisputedLayersUseTopoJson}).
 */
export function assertChoroplethDisputedLayersUseTopoJson(
  spec: Record<string, unknown>,
): void {
  const r = validateChoroplethDisputedLayersUseTopoJson(spec);
  if (!r.ok) {
    throw new Error(`Disputed areas must use TopoJSON: ${r.errors.join(" ")}`);
  }
}
