/**
 * Choropleth Vega-Lite scene sizing for host embeds (chat cards).
 * Caps vertical map facet so wide containers do not reserve ``width/2`` pixels of height (tall SVG,
 * huge empty band inside the Vega scene).
 */

/**
 * Cap on the map facet height (before the legend strip). Too small vs Vega’s layout inflates the
 * scene or pushes the gradient outside the clipped viewport.
 */
export const CHOROPLETH_MAX_MAP_FACET_PX = 292;

/**
 * Vertical budget for the gradient legend strip (title + ramp + tick labels).
 * Keep aligned with ``legendStripPx`` in ``VegaChartCard`` / wheel-zoom patch — undershooting hides the legend.
 */
export function choroplethLegendVerticalReservePx(containerWidth: number): number {
  return Math.max(68, Math.min(118, Math.round(46 + containerWidth * 0.024)));
}

/**
 * Target height for the map projection band (before the legend). Uses ~0.44× width instead of 0.5×
 * so the overall VL scene (and host container) is shorter; projection scale still fills width.
 */
export function choroplethMapFacetHeightPx(containerWidth: number): number {
  if (containerWidth < 1) return 0;
  const ideal = Math.max(1, Math.round(containerWidth * 0.44));
  return Math.min(ideal, CHOROPLETH_MAX_MAP_FACET_PX);
}

/**
 * Total VL ``height`` for quantitative choropleth specs (``prepareSpec`` second argument).
 * Combines capped map facet + legend reserve, floored by ``chartHeight``.
 */
export function suggestChoroplethSceneHeight(containerWidth: number, chartHeight: number): number {
  if (containerWidth < 1) return chartHeight;
  const strip = choroplethLegendVerticalReservePx(containerWidth);
  const mapH = choroplethMapFacetHeightPx(containerWidth);
  return Math.max(chartHeight, mapH + strip);
}
