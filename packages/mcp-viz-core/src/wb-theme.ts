export const WB_THEME_URL =
  "https://worldbank.github.io/data-visualization-style-guide/vega/wb-vega-theme.json";

export const WB_THEME = {
  background: "#ffffff",
  view: { stroke: null },
  arc: { fill: "#34A7F2" },
  area: { fill: "#34A7F2" },
  line: { stroke: "#34A7F2", strokeCap: "round", strokeJoin: "round" },
  rect: { fill: "#34A7F2" },
  point: { filled: true, stroke: "white", strokeWidth: 1 },
  title: {
    font: "Open Sans, Arial, sans-serif",
    subtitleFont: "Open Sans, Arial, sans-serif",
    anchor: "start",
    fontSize: 18,
    fontWeight: 600,
    offset: 20,
    subtitleFontSize: 15,
    subtitleColor: "#666666",
    subtitlePadding: 6,
  },
  axis: {
    titleFont: "Open Sans, Arial, sans-serif",
    titleFontSize: 13,
    titleFontWeight: 600,
    labelFont: "Open Sans, Arial, sans-serif",
    labelColor: "#666666",
    labelFontSize: 13,
    gridWidth: 1,
    tickColor: "#CED4DE",
    tickWidth: 0.2,
    titleColor: "#111111",
    gridDash: [4, 2],
    gridColor: "#CED4DE",
    labelPadding: 6,
    labelOverlap: true,
    labelFlush: false,
  },
  axisBand: { grid: false },
  axisX: { grid: true, tickSize: 0, domain: false },
  axisY: { domain: false, grid: true, tickSize: 0 },
  legend: {
    labelFont: "Open Sans, Arial, sans-serif",
    titleFont: "Open Sans, Arial, sans-serif",
    titleFontSize: 15,
    labelFontSize: 13,
    labelColor: "#111111",
    padding: 1,
    symbolSize: 140,
    orient: "bottom",
    direction: "horizontal",
  },
  range: {
    category: [
      "#34A7F2",
      "#FF9800",
      "#664AB6",
      "#4EC2C0",
      "#F3578E",
      "#081079",
      "#0C7C68",
    ],
  },
} as const;

export type WBTheme = typeof WB_THEME;
export const WB_PALETTE = WB_THEME.range.category as unknown as string[];
