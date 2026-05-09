export type {
  Annotation,
  MarkType,
  VegaChartCardBaseProps,
  VLEncoding,
  VLSpec,
} from "./types";
export {
  WB_PALETTE,
  WB_THEME,
  WB_THEME_URL,
  type WBTheme,
} from "./wb-theme";
export {
  getEffectiveMarkType,
  getMark,
  hasChoroplethQuantitativeColor,
  parseSpec,
  prepareSpec,
  type ParsedSpec,
} from "./prepare-spec";
export {
  patchVegaSpecChoroplethWheelZoom,
  type ChoroplethWheelZoomPatchOpts,
} from "./choropleth-wheel-zoom";
