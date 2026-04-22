import React from "react";
import ReactDOM from "react-dom/client";
import type { VLSpec } from "../viz-card/types";
import { VegaChartCard } from "../viz-card";

const DEMO_SPEC = {
  $schema: "https://vega.github.io/schema/vega-lite/v6.1.0.json",
  title: "Renewable electricity output (% of total electricity output)",
  data: { name: "data-demo" },
  datasets: {
    "data-demo": [
      { year: "2019-01-01T00:00:00", value: 81.43, country: "Brazil" },
      { year: "2019-01-01T00:00:00", value: 1.42,  country: "Bangladesh" },
      { year: "2018-01-01T00:00:00", value: 1.58,  country: "Bangladesh" },
      { year: "2020-01-01T00:00:00", value: 1.47,  country: "Bangladesh" },
      { year: "2021-01-01T00:00:00", value: 39.83, country: "Germany" },
      { year: "2020-01-01T00:00:00", value: 19.76, country: "India" },
      { year: "2018-01-01T00:00:00", value: 81.57, country: "Brazil" },
      { year: "2019-01-01T00:00:00", value: 40.58, country: "Germany" },
      { year: "2021-01-01T00:00:00", value: 19.13, country: "India" },
      { year: "2021-01-01T00:00:00", value: 1.50,  country: "Bangladesh" },
      { year: "2018-01-01T00:00:00", value: 15.01, country: "India" },
      { year: "2019-01-01T00:00:00", value: 17.94, country: "United States" },
      { year: "2021-01-01T00:00:00", value: 20.27, country: "United States" },
      { year: "2018-01-01T00:00:00", value: 17.16, country: "United States" },
      { year: "2020-01-01T00:00:00", value: 44.84, country: "Germany" },
      { year: "2020-01-01T00:00:00", value: 19.92, country: "United States" },
      { year: "2018-01-01T00:00:00", value: 35.64, country: "Germany" },
      { year: "2021-01-01T00:00:00", value: 77.38, country: "Brazil" },
      { year: "2020-01-01T00:00:00", value: 83.18, country: "Brazil" },
    ],
  },
  mark: { type: "line" as const },
  encoding: {
    x: { field: "year", type: "temporal", timeUnit: "year" },
    y: { field: "value", type: "quantitative", scale: { zero: true } },
    color: { field: "country", type: "nominal" },
    tooltip: [
      { field: "year",    type: "temporal" },
      { field: "value",   type: "quantitative" },
      { field: "country", type: "nominal" },
    ],
  },
  params: [{ name: "zoom", select: { type: "interval" }, bind: "scales" }],
} satisfies VLSpec;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <div style={{ padding: 32, maxWidth: 760, margin: "0 auto" }}>
      <VegaChartCard
        spec={DEMO_SPEC}
        subtitle="Brazil, Bangladesh, Germany, India, United States · 2018–2021"
        source="World Bank — World Development Indicators (WDI)"
        annotations={[
          { id: 1, text: "Brazil consistently leads with over 77% renewable electricity, driven primarily by large-scale hydropower." },
          { id: 2, text: "Germany grew from 35.6% in 2018 to 44.8% in 2020, reflecting accelerated wind and solar deployment." },
        ]}
      />
    </div>
  </React.StrictMode>
);
