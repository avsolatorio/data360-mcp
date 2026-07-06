import { WB_THEME } from "./wb-theme";
import type { MarkType, VLSpec } from "./types";

// ─── Helpers ─────────────────────────────────────────────────────────────────

export function getMark(spec: VLSpec): MarkType {
  if (!spec.mark) return "line";
  return typeof spec.mark === "string" ? spec.mark : (spec.mark.type ?? "line");
}

/** Resolve spec.datasets[spec.data.name] → spec.data.values */
function inlineDataset(spec: VLSpec): VLSpec {
  const name = spec.data?.name;
  if (name && spec.datasets?.[name]) {
    return { ...spec, data: { values: spec.datasets[name] }, datasets: undefined };
  }
  return spec;
}

/** Deep-merge WB theme into spec.config. Spec config values win on conflict. */
function mergeConfig(
  specConfig: Record<string, unknown> | undefined,
  theme: typeof WB_THEME
): Record<string, unknown> {
  const base = JSON.parse(JSON.stringify(theme)) as Record<string, unknown>;
  if (!specConfig) return base;
  // Shallow-merge top-level keys — spec overrides theme
  return { ...base, ...specConfig };
}

function checkAndApplyLogScale(encodingChannel: any, valField: string, rows: Record<string, unknown>[]): void {
  if (!encodingChannel || encodingChannel.type !== "quantitative" || !valField || !Array.isArray(rows)) return;
  const values = rows
    .map((r: any) => parseFloat(r[valField]))
    .filter((v: number) => !isNaN(v));
  if (values.length > 0 && values.every((v: number) => v > 0)) {
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    // Auto-apply log scale if values span more than 2 orders of magnitude (max/min > 100)
    if (minVal > 0 && maxVal / minVal > 100) {
      if (!encodingChannel.scale) encodingChannel.scale = {};
      encodingChannel.scale.type = "log";
    }
  }
}

// ─── prepareSpec ─────────────────────────────────────────────────────────────

/**
 * Applies the 8-guard pipeline to make any Data360 Vega-Lite spec compatible
 * with the VegaChartCard component and the WB visual theme.
 *
 * Guards:
 *  1. Inline named dataset → data.values
 *  2. Responsive sizing (width: "container", configurable height)
 *  3. Suppress built-in legend (card renders its own)
 *  3b. Remove top-level title (card header shows it; avoids duplicating Vega’s title)
 *  4. Strip zoom/pan params (conflicts with card controls)
 *  5. Normalize $schema v6 → v5 (vega-embed 6 compatibility)
 *  6. Merge WB theme into config
 *  7. scale.zero — false for line/area/point/tick, true for bar
 *  8. x-axis format — %Y only for temporal; dropped for ordinal/nominal
 *  9. Dynamic outlier log-scale (auto-detect wide positive ranges)
 *  10. Chronological timeline check (enforce chronological sort for timeline dimensions)
 */
export function prepareSpec(spec: VLSpec, chartHeight = 260): VLSpec {
  let out: VLSpec = JSON.parse(JSON.stringify(spec));
  const markType = getMark(out);

  // 1. Inline named dataset
  out = inlineDataset(out);

  const rows: Record<string, unknown>[] = out.data?.values ?? [];

  // 2. Responsive sizing
  out.width = "container";
  out.height = chartHeight;

  // 3. Suppress built-in legend — card renders its own (unless quantitative)
  if (out.encoding?.color && out.encoding.color.type !== "quantitative") {
    out.encoding.color.legend = null;
  }

  // 3b. Title is displayed by VegaChartCard (prop / parseSpec); strip from the embedded spec
  delete out.title;

  // 4. Strip zoom/pan params — conflicts with card controls
  delete out.params;

  // 5. Normalize $schema v6 → v5
  out.$schema = "https://vega.github.io/schema/vega-lite/v5.json";

  // 6. Merge WB theme
  out.config = mergeConfig(out.config as Record<string, unknown> | undefined, WB_THEME);

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

  // 9. Dynamic outlier log-scale (X and Y quantitative axes)
  if (out.encoding?.y?.field) {
    checkAndApplyLogScale(out.encoding.y, out.encoding.y.field, rows);
  }
  if (out.encoding?.x?.field) {
    checkAndApplyLogScale(out.encoding.x, out.encoding.x.field, rows);
  }

  // 10. Chronological timeline check (ensure time period fields are sorted chronologically if nominal/ordinal)
  if (out.encoding?.x) {
    const xField = out.encoding.x.field;
    if (xField === "year" || xField === "time_period") {
      if (out.encoding.x.type === "ordinal" || out.encoding.x.type === "nominal") {
        out.encoding.x.sort = "ascending";
      }
    }
  }
  if (out.encoding?.y) {
    const yField = out.encoding.y.field;
    if (yField === "year" || yField === "time_period") {
      if (out.encoding.y.type === "ordinal" || out.encoding.y.type === "nominal") {
        out.encoding.y.sort = "ascending";
      }
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
  const rows: Record<string, unknown>[] =
    name && spec.datasets?.[name]
      ? spec.datasets[name]
      : (spec.data?.values ?? []);

  const isQuantitative = spec.encoding?.color?.type === "quantitative";
  const legendVal = spec.encoding?.color?.legend as any;
  const xField = spec.encoding?.x?.field ?? null;
  const yField = spec.encoding?.y?.field ?? null;
  const colorFieldVal = spec.encoding?.color?.field ?? null;
  const isRepresentedOnAxis = colorFieldVal !== null && (colorFieldVal === xField || colorFieldVal === yField);
  const hasNoLegend = legendVal === null || legendVal === false || isRepresentedOnAxis;

  const rawGroups: string[] = colorFieldVal
    ? [...new Set(rows.map((r) => String(r[colorFieldVal])))]
    : [];

  // Legend-Linter Rule: Suppress card legends if categories exceed 8 to avoid legend-overload clutter.
  // Hover tooltips remain active for identifying individual series.
  const tooManyGroups = rawGroups.length > 8;
  const colorField = (isQuantitative || hasNoLegend || tooManyGroups) ? null : colorFieldVal;

  const specTitle =
    typeof spec.title === "string"
      ? spec.title
      : (spec.title as { text?: string } | undefined)?.text ?? null;

  const distinctGroups: string[] = colorField ? rawGroups : [];

  const colorMap: Record<string, string> = {};
  distinctGroups.forEach((g, i) => {
    colorMap[g] = palette[i % palette.length];
  });

  return { rows, colorField, specTitle, distinctGroups, colorMap };
}
