import { WB_THEME } from "./wb-theme";
import type { MarkType, VLSpec } from "./types";

// ─── Helpers ─────────────────────────────────────────────────────────────────

export function getMark(spec: VLSpec): MarkType {
  if (!spec.mark) return "line";
  return typeof spec.mark === "string" ? spec.mark : (spec.mark.type ?? "line");
}

/**
 * Layered maps use ``layer[]`` without top-level ``mark`` — detect geoshape inside layers.
 * Exported for hosts that still call ``getMark(spec)`` (which yields ``line`` when ``mark`` is absent).
 */
export function getEffectiveMarkType(spec: VLSpec): MarkType {
  const top = getMark(spec);
  if (top !== "line") return top;
  const layers = spec.layer as Array<{ mark?: string | { type?: string } }> | undefined;
  if (!Array.isArray(layers)) return top;
  for (const layer of layers) {
    const lm = layer?.mark;
    const t =
      typeof lm === "string"
        ? lm
        : lm && typeof lm === "object" && "type" in lm
          ? lm.type
          : undefined;
    if (t === "geoshape") return "geoshape";
  }
  return top;
}

/** True if encoding uses quantitative map fill (direct ``color`` or conditional branch). */
function colorEncodingIsQuantitative(color: Record<string, unknown> | undefined): boolean {
  if (!color || typeof color !== "object") return false;
  if (color.type === "quantitative") return true;
  const cond = color.condition;
  return Boolean(
    cond && typeof cond === "object" && (cond as { type?: string }).type === "quantitative",
  );
}

/**
 * Layered choropleths never set top-level ``encoding.color``; fill uses ``layer[]`` and often
 * ``color: { condition: { type: quantitative, ... }, value }``. ``getMark(spec) === "geoshape"``
 * is always false for those specs — this matches what ``prepareSpec`` already does via
 * ``getEffectiveMarkType``.
 */
export function hasChoroplethQuantitativeColor(spec: VLSpec): boolean {
  if (getEffectiveMarkType(spec) !== "geoshape") return false;
  if (colorEncodingIsQuantitative(spec.encoding?.color as Record<string, unknown> | undefined)) {
    return true;
  }
  const layers = spec.layer as
    | Array<{ encoding?: { color?: Record<string, unknown> } }>
    | undefined;
  if (!Array.isArray(layers)) return false;
  for (const layer of layers) {
    if (colorEncodingIsQuantitative(layer.encoding?.color)) return true;
  }
  return false;
}

/** Resolve spec.datasets[spec.data.name] → spec.data.values */
function inlineDataset(spec: VLSpec): VLSpec {
  const name = spec.data?.name;
  if (name && spec.datasets?.[name]) {
    return { ...spec, data: { values: spec.datasets[name] }, datasets: undefined };
  }
  return spec;
}

/** Drop zoom/pan selections that conflict with chart-card controls; keep point/hover params. */
function stripZoomPanParams(params: unknown): unknown[] | undefined {
  if (!Array.isArray(params)) return undefined;
  const filtered = params.filter((raw) => {
    const p = raw as Record<string, unknown>;
    const sel = p.select;
    if (sel == null) return true;
    const type =
      typeof sel === "object" && sel !== null && "type" in sel
        ? (sel as { type?: string }).type
        : typeof sel === "string"
          ? sel
          : undefined;
    if (type === "interval") return false;
    if (p.bind != null) return false;
    return true;
  });
  return filtered.length === 0 ? undefined : filtered;
}

/** Merge ``config.style`` so theme ``style.view`` / ``style.cell`` survive partial spec overrides. */
function mergeStyleConfig(
  baseStyle: Record<string, unknown> | undefined,
  specStyle: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  const b = typeof baseStyle === "object" && baseStyle ? baseStyle : {};
  const s = typeof specStyle === "object" && specStyle ? specStyle : {};
  const out = { ...b, ...s } as Record<string, unknown>;
  for (const key of ["view", "cell"] as const) {
    const bk = b[key] as Record<string, unknown> | undefined;
    const sk = s[key] as Record<string, unknown> | undefined;
    if (
      bk &&
      sk &&
      typeof bk === "object" &&
      typeof sk === "object" &&
      !Array.isArray(bk) &&
      !Array.isArray(sk)
    ) {
      out[key] = { ...bk, ...sk };
    }
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

/** Deep-merge WB theme into spec.config. Spec config values win on conflict. */
function mergeConfig(
  specConfig: Record<string, unknown> | undefined,
  theme: typeof WB_THEME
): Record<string, unknown> {
  const base = JSON.parse(JSON.stringify(theme)) as Record<string, unknown>;
  if (!specConfig) return base;
  // Shallow-merge top-level keys — spec overrides theme
  const merged = { ...base, ...specConfig } as Record<string, unknown>;
  // ``config.view`` must be merged deeply: a spec often sets only ``stroke``; shallow merge
  // then drops ``strokeWidth`` from the theme and Vega defaults draw a visible plot outline.
  const bv = base.view as Record<string, unknown> | undefined;
  const sv = specConfig.view as Record<string, unknown> | undefined;
  if (
    bv &&
    sv &&
    typeof bv === "object" &&
    typeof sv === "object" &&
    !Array.isArray(bv) &&
    !Array.isArray(sv)
  ) {
    merged.view = { ...bv, ...sv };
  }
  const mergedStyle = mergeStyleConfig(
    base.style as Record<string, unknown> | undefined,
    specConfig.style as Record<string, unknown> | undefined,
  );
  if (mergedStyle) {
    merged.style = mergedStyle;
  }
  // Deep-merge legend so a partial spec (e.g. only labelFont) does not drop theme orient.
  const baseLeg = base.legend as Record<string, unknown> | undefined;
  const specLeg = specConfig.legend as Record<string, unknown> | undefined;
  if (baseLeg && specLeg && typeof baseLeg === "object" && typeof specLeg === "object") {
    merged.legend = { ...baseLeg, ...specLeg };
  }
  return merged;
}

type ChoroplethLegendBottomOpts = {
  /** Horizontal gradient bar length when host measures slot width (reserves space for “No data” symbol). */
  gradientLength?: number;
};

/** Persisted MCP specs often pin legend to top; card layout expects gradient below the map. */
function forceChoroplethLegendBottom(
  spec: VLSpec,
  opts?: ChoroplethLegendBottomOpts,
): VLSpec {
  const gradientLength = opts?.gradientLength;
  const cfg = spec.config as Record<string, unknown> | undefined;
  const nextCfg = { ...(cfg ?? {}) };
  const leg =
    nextCfg.legend !== null &&
    typeof nextCfg.legend === "object" &&
    !Array.isArray(nextCfg.legend)
      ? { ...(nextCfg.legend as Record<string, unknown>) }
      : {};
  nextCfg.legend = { ...leg, orient: "bottom", direction: "horizontal" };

  const layers = spec.layer as
    | Array<{ encoding?: { color?: Record<string, unknown> } }>
    | undefined;
  if (Array.isArray(layers)) {
    const nextLayer = layers.map((layer) => {
      const col = layer.encoding?.color;
      if (col === undefined || typeof col !== "object") {
        return layer;
      }
      const lr = col.legend;
      if (lr === null || lr === false) {
        return layer;
      }
      const legendObj =
        lr !== null && typeof lr === "object" && !Array.isArray(lr)
          ? { ...(lr as Record<string, unknown>) }
          : {};
      const bottom = { ...legendObj, orient: "bottom", direction: "horizontal" };
      if (colorEncodingIsQuantitative(col) && gradientLength !== undefined) {
        return {
          ...layer,
          encoding: {
            ...layer.encoding,
            color: {
              ...col,
              legend: { ...bottom, gradientLength },
            },
          },
        };
      }
      return {
        ...layer,
        encoding: {
          ...layer.encoding,
          color: {
            ...col,
            legend: bottom,
          },
        },
      };
    }) as typeof spec.layer;
    return { ...spec, config: nextCfg as typeof spec.config, layer: nextLayer };
  }

  const col = spec.encoding?.color as Record<string, unknown> | undefined;
  if (col !== undefined && colorEncodingIsQuantitative(col)) {
    const lr = col.legend;
    if (lr !== null && lr !== false) {
      const legendObj =
        lr !== null && typeof lr === "object" && !Array.isArray(lr)
          ? { ...(lr as Record<string, unknown>) }
          : {};
      const bottom = { ...legendObj, orient: "bottom", direction: "horizontal" };
      return {
        ...spec,
        config: nextCfg as typeof spec.config,
        encoding: {
          ...spec.encoding,
          color: {
            ...col,
            legend:
              gradientLength !== undefined
                ? { ...bottom, gradientLength }
                : bottom,
          },
        },
      };
    }
  }

  return { ...spec, config: nextCfg as typeof spec.config };
}

// ─── prepareSpec ─────────────────────────────────────────────────────────────

/**
 * Applies the 8-guard pipeline to make any Data360 Vega-Lite spec compatible
 * with the VegaChartCard component and the WB visual theme.
 *
 * Guards:
 *  1. Inline named dataset → data.values
 *  2. Responsive sizing (width: "container" for most marks; geoshape uses numeric width from the
 *     spec, or ``containerWidth`` when the host measures the slot, or 600 fallback — avoids a
 *     fixed 600px map in a wide card)
 *  3. Suppress built-in legend (card renders its own)
 *  3b. Remove top-level title (card header shows it; avoids duplicating Vega’s title)
 *  4. Strip zoom/pan params (interval/bind); keep point hover selections for maps
 *  5. Normalize $schema v6 → v5 (vega-embed 6 compatibility)
 *  6. Merge WB theme into config
 *  7. scale.zero — false for line/area/point/tick, true for bar
 *  8. x-axis format — %Y only for temporal; dropped for ordinal/nominal
 */
export function prepareSpec(spec: VLSpec, chartHeight = 260, containerWidth?: number): VLSpec {
  let out: VLSpec = JSON.parse(JSON.stringify(spec));
  const markType = getEffectiveMarkType(out);

  // 1. Inline named dataset
  out = inlineDataset(out);

  // 2. Responsive sizing
  const origWidth = out.width;
  const origHeight = out.height;
  const measuredW =
    typeof containerWidth === "number" &&
    Number.isFinite(containerWidth) &&
    containerWidth >= 1
      ? Math.floor(containerWidth)
      : undefined;
  if (markType === "geoshape") {
    out.width =
      measuredW ??
      (typeof origWidth === "number" &&
      Number.isFinite(origWidth) &&
      origWidth > 0
        ? origWidth
        : 600);
    out.height =
      typeof origHeight === "number" &&
      Number.isFinite(origHeight) &&
      origHeight > 0
        ? origHeight
        : chartHeight;
  } else {
    out.width = "container";
    out.height = chartHeight;
  }

  // 3. Suppress built-in legend — card renders its own (except choropleth: quantitative
  // color needs Vega's gradient legend; stripping it removes the scale guide).
  if (out.encoding?.color) {
    const colorEnc = out.encoding.color as Record<string, unknown>;
    const keepLegendForChoropleth =
      markType === "geoshape" && colorEncodingIsQuantitative(colorEnc);
    if (!keepLegendForChoropleth) {
      out.encoding.color.legend = null;
    }
  }

  // 3b. Title is displayed by VegaChartCard (prop / parseSpec); strip from the embedded spec
  delete out.title;

  // 4. Strip zoom/pan params — conflicts with card controls
  const keptParams = stripZoomPanParams(out.params);
  if (keptParams !== undefined) {
    out.params = keptParams;
  } else {
    delete out.params;
  }

  // 5. Normalize $schema v6 → v5
  out.$schema = "https://vega.github.io/schema/vega-lite/v5.json";

  // 6. Merge WB theme
  out.config = mergeConfig(out.config as Record<string, unknown> | undefined, WB_THEME);

  // 6b. Choropleth gradient legend: baked specs override theme.legend entirely (shallow merge).
  // Force bottom legend so wide cards do not leave a top band + wasted width beside the map.
  if (hasChoroplethQuantitativeColor(out)) {
    const legendGradientLen =
      measuredW !== undefined ? Math.max(120, measuredW - 80) : undefined;
    out = forceChoroplethLegendBottom(out, { gradientLength: legendGradientLen });
  }

  // 7. scale.zero — bars must start at zero; everything else benefits from false
  if (out.encoding?.y) {
    if (!out.encoding.y.scale) out.encoding.y.scale = {};
    (out.encoding.y.scale as Record<string, unknown>).zero = markType === "bar";
  }

  // 8. x-axis format — only apply %Y for temporal x
  if (out.encoding?.x) {
    const xType = out.encoding.x.type;
    if (!out.encoding.x.axis) out.encoding.x.axis = {};
    const axis = out.encoding.x.axis as Record<string, unknown>;
    if (xType === "temporal") {
      axis.format = "%Y";
      axis.title = null;
    } else {
      // ordinal / nominal (bar with year strings, tick with country on x)
      delete axis.format;
      axis.title = null;
    }
  }

  return out;
}

// ─── parseSpec ───────────────────────────────────────────────────────────────

export interface ParsedSpec {
  rows: Record<string, unknown>[];
  colorField: string | null;
  specTitle: string | null;
  distinctGroups: string[];
  colorMap: Record<string, string>;
}

/**
 * Extract legend metadata from a raw (un-prepared) spec.
 * Call this once on the original spec, not the prepared one.
 */
export function parseSpec(spec: VLSpec, palette: string[]): ParsedSpec {
  const name = spec.data?.name;
  let rows: Record<string, unknown>[] =
    name && spec.datasets?.[name]
      ? spec.datasets[name]
      : (spec.data?.values ?? []);

  if (rows.length === 0 && spec.datasets?.choropleth_stats?.length) {
    rows = spec.datasets.choropleth_stats;
  }

  const colorField = spec.encoding?.color?.field ?? null;
  const specTitle =
    typeof spec.title === "string"
      ? spec.title
      : (spec.title as { text?: string } | undefined)?.text ?? null;

  const distinctGroups: string[] = colorField
    ? [...new Set(rows.map((r) => String(r[colorField])))]
    : [];

  const colorMap: Record<string, string> = {};
  distinctGroups.forEach((g, i) => {
    colorMap[g] = palette[i % palette.length];
  });

  return { rows, colorField, specTitle, distinctGroups, colorMap };
}
