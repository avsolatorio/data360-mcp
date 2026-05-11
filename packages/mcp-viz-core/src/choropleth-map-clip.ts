/**
 * Wrap root ``marks`` in a clipped ``group`` so geoshape paths cannot paint past the map band
 * (wheel-zoom bleed) while Vega renders **legends** outside this group (top-level ``legends[]``).
 *
 * Must run **after** ``patchVegaSpecChoroplethWheelZoom`` so ``choropleth_legend_strip_px`` exists.
 */

type UnknownRecord = Record<string, unknown>;

function isObject(x: unknown): x is UnknownRecord {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

export function patchVegaSpecChoroplethMapGroupClip(vegaSpec: UnknownRecord): UnknownRecord {
  const marks = vegaSpec.marks;
  if (!Array.isArray(marks) || marks.length === 0) return vegaSpec;

  const first = marks[0] as UnknownRecord | undefined;
  if (first?.type === "group" && first?.name === "choropleth_map_clip_group") {
    return vegaSpec;
  }

  const signals = vegaSpec.signals;
  const hasStrip =
    Array.isArray(signals) &&
    signals.some((s) => isObject(s) && s.name === "choropleth_legend_strip_px");
  if (!hasStrip) return vegaSpec;

  return {
    ...vegaSpec,
    marks: [
      {
        type: "group",
        name: "choropleth_map_clip_group",
        clip: true,
        encode: {
          update: {
            x: { value: 0 },
            y: { value: 0 },
            width: { signal: "width" },
            height: { signal: "max(1, height - choropleth_legend_strip_px)" },
          },
        },
        marks,
      },
    ],
  };
}
