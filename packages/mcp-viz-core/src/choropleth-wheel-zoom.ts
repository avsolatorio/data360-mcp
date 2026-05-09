/**
 * Replace Vega-Lite’s auto-``fit`` geographic projection with signal-driven scale/translate so
 * wheel events can zoom (and hosts can pan/reset via ``view.signal``).
 *
 * Only patches when a projection named ``projection`` uses both ``fit`` and ``size`` (VL
 * layered choropleth output). Idempotent if ``choropleth_zoom`` already exists.
 */

export type ChoroplethWheelZoomPatchOpts = {
  /** Initial view width (numeric VL ``width`` after prepareSpec). */
  plotWidth: number;
  /** Initial view height (numeric VL ``height``). */
  plotHeight: number;
  /** Pixels reserved for the gradient legend strip at the **bottom** (map band uses ``height - strip``). */
  legendStripPx?: number;
};

type UnknownRecord = Record<string, unknown>;

function isObject(x: unknown): x is UnknownRecord {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

/**
 * Vertical center of the projection in plot coordinates. Biased **down** in the map band so the
 * sphere sits closer to the legend strip (less empty gap between map silhouette and gradient).
 */
export function choroplethMapBandCenterY(plotHeight: number, legendStripPx: number): number {
  const strip = Math.max(0, Math.floor(legendStripPx ?? 0));
  const band = plotHeight - strip;
  if (band <= 0) {
    return plotHeight / 2;
  }
  /** Larger ty shifts the projection center **down** → globe sits closer to the legend strip (less dead air). */
  return band * 0.67;
}

export function patchVegaSpecChoroplethWheelZoom(
  vegaSpec: UnknownRecord,
  opts: ChoroplethWheelZoomPatchOpts,
): UnknownRecord {
  const signals = vegaSpec.signals;
  if (Array.isArray(signals) && signals.some((s) => isObject(s) && s.name === "choropleth_zoom")) {
    return vegaSpec;
  }

  const projections = vegaSpec.projections;
  if (!Array.isArray(projections)) return vegaSpec;

  const idx = projections.findIndex((p) => isObject(p) && p.name === "projection");
  if (idx < 0) return vegaSpec;

  const proj = projections[idx] as UnknownRecord;
  if (!("fit" in proj) || !("size" in proj)) return vegaSpec;

  const newProj: UnknownRecord = { ...proj };
  delete newProj.fit;
  delete newProj.size;
  newProj.scale = { signal: "choropleth_zoom * choropleth_base_scale" };
  newProj.translate = { signal: "[choropleth_tx, choropleth_ty]" };

  /**
   * Wheel zoom is handled in the host (``VegaChartCard``) with DOM coordinates so the pivot
   * matches the pointer. Vega ``event.x``/``event.y`` on ``scope:wheel`` are often not aligned
   * with the projection translate space for layered SVG maps.
   */
  const strip = Math.max(0, Math.floor(opts.legendStripPx ?? 0));
  const mapBandCenterY = choroplethMapBandCenterY(opts.plotHeight, strip);

  const zoomSignals: unknown[] = [
    {
      name: "choropleth_legend_strip_px",
      value: strip,
    },
    {
      name: "choropleth_base_scale",
      /**
       * ``min(...)`` fits the sphere in the map band above the bottom legend strip; letterboxing may
       * remain inside that band.
       */
      update:
        "min(width / (2 * PI), max(1, height - choropleth_legend_strip_px) / PI)",
    },
    {
      name: "choropleth_zoom",
      value: 1,
    },
    {
      name: "choropleth_tx",
      value: opts.plotWidth / 2,
    },
    {
      name: "choropleth_ty",
      value: mapBandCenterY,
    },
  ];

  const nextProjections = projections.map((p, i) => (i === idx ? newProj : p));

  // Keep Vega-Lite's scene ``padding`` (typically ~5px). Forcing ``padding: 0`` removed the
  // inset legends rely on with ``orient: "bottom"``, which made the gradient disappear in the embed.
  return {
    ...vegaSpec,
    projections: nextProjections,
    signals: [...zoomSignals, ...(Array.isArray(signals) ? signals : [])],
  };
}
