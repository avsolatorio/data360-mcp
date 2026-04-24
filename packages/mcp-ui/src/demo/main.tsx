import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import type { VLSpec } from "../viz-card/types";
import { VegaChartCard } from "../viz-card";
import { SearchResultCard } from "../search-card";
import type { EnrichedIndicator } from "../search-card";

// ─── Viz demo data ─────────────────────────────────────────────────────────────

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

// ─── Search demo data ──────────────────────────────────────────────────────────

const MERGED_INDICATORS: EnrichedIndicator[] = [
  {
    idno: "WB_WDI_NY_GDP_PCAP_KD",
    database_id: "WB_WDI",
    database_name: "World Development Indicators (WDI)",
    name: "GDP per capita (constant 2015 US$)",
    truncated_definition: "GDP per capita based on constant 2015 prices, in US dollars.",
    periodicity: "Annual",
    latest_data: "2023",
    time_period_range: "1960–2023",
    covers_country: { KEN: true },
    requested_country: "KEN",
    dimensions: ["AGE"],
  },
  {
    idno: "WB_WDI_FP_CPI_TOTL_ZG",
    database_id: "WB_WDI",
    database_name: "World Development Indicators (WDI)",
    name: "Inflation, consumer prices (annual %)",
    truncated_definition: "Annual growth rate of the CPI for the average consumer.",
    periodicity: "Annual",
    latest_data: "2023",
    time_period_range: "1960–2023",
    covers_country: { KEN: true },
    requested_country: "KEN",
  },
  {
    idno: "WB_WDI_SI_POV_GINI",
    database_id: "WB_WDI",
    database_name: "World Development Indicators (WDI)",
    name: "Gini index",
    truncated_definition: "Gini index measures the extent to which the distribution of income deviates from a perfectly equal distribution.",
    periodicity: "Annual",
    latest_data: "2021",
    time_period_range: "1967–2021",
    covers_country: { MAR: false },
    requested_country: "MAR",
  },
];

// Single-query results: no country context, so covers_country is absent (badge hidden).
const SINGLE_QUERY_INDICATORS: EnrichedIndicator[] = [
  {
    idno: "WB_WDI_NY_GDP_PCAP_KD",
    database_id: "WB_WDI",
    database_name: "World Development Indicators (WDI)",
    name: "GDP per capita (constant 2015 US$)",
    truncated_definition: "GDP per capita based on constant 2015 prices, in US dollars.",
    periodicity: "Annual",
    latest_data: "2023",
    time_period_range: "1960–2023",
    // covers_country intentionally absent — simulates no required_country in search
  },
  {
    idno: "WB_GS_NY_GDP_PCAP_KD",
    database_id: "WB_GS",
    database_name: "Gender Statistics",
    name: "GDP per capita (Gender Statistics)",
    truncated_definition: "Alternative GDP per capita series from the Gender Statistics database.",
    periodicity: "Annual",
    latest_data: "2022",
    time_period_range: "1980–2022",
  },
  {
    idno: "WB_WDI_NY_GNP_PCAP_KD",
    database_id: "WB_WDI",
    database_name: "World Development Indicators (WDI)",
    name: "GNI per capita (constant 2015 US$)",
    truncated_definition: "Gross national income per capita in constant 2015 US dollars.",
    periodicity: "Annual",
    latest_data: "2023",
    time_period_range: "1962–2023",
  },
];

const BY_QUERY_GROUPS = [
  {
    query: "GDP per capita",
    country_code: "KEN",
    count: 2,
    indicators: [
      MERGED_INDICATORS[0],
      {
        idno: "WB_GS_NY_GDP_PCAP_KD",
        database_id: "WB_GS",
        database_name: "Gender Statistics",
        name: "GDP per capita (Gender Statistics)",
        truncated_definition: "Alternative GDP per capita series from the Gender Statistics database.",
        periodicity: "Annual",
        latest_data: "2022",
        time_period_range: "1980–2022",
        covers_country: { KEN: true },
        requested_country: "KEN",
      },
    ],
  },
  {
    query: "Gini coefficient",
    country_code: "MAR",
    count: 1,
    indicators: [MERGED_INDICATORS[2]],
  },
];

// ─── Demo app ──────────────────────────────────────────────────────────────────

function App() {
  const [selected, setSelected] = useState<EnrichedIndicator | null>(null);

  return (
    <div style={{ padding: 32, maxWidth: 760, margin: "0 auto", display: "flex", flexDirection: "column", gap: 40 }}>

      {/* Section label */}
      <h1 style={{ fontFamily: "Open Sans, Arial, sans-serif", fontSize: 22, fontWeight: 700, margin: 0, color: "#111" }}>
        @data360/mcp-ui — Component demo
      </h1>

      {/* VegaChartCard */}
      <section>
        <h2 style={{ fontFamily: "Open Sans, Arial, sans-serif", fontSize: 15, fontWeight: 600, color: "#666", margin: "0 0 12px" }}>
          viz-card · VegaChartCard
        </h2>
        <VegaChartCard
          spec={DEMO_SPEC}
          subtitle="Brazil, Bangladesh, Germany, India, United States · 2018–2021"
          source="World Bank — World Development Indicators (WDI)"
          annotations={[
            { id: 1, text: "Brazil consistently leads with over 77% renewable electricity, driven primarily by large-scale hydropower." },
            { id: 2, text: "Germany grew from 35.6% in 2018 to 44.8% in 2020, reflecting accelerated wind and solar deployment." },
          ]}
        />
      </section>

      {/* SearchResultCard — single query (no country context, no badge) */}
      <section>
        <h2 style={{ fontFamily: "Open Sans, Arial, sans-serif", fontSize: 15, fontWeight: 600, color: "#666", margin: "0 0 12px" }}>
          search-card · SearchResultCard (single query, no country)
        </h2>
        <SearchResultCard
          indicators={SINGLE_QUERY_INDICATORS}
          title="Search Results"
          subtitle="query: GDP per capita"
          onSelect={(ind) => setSelected(ind)}
        />
        {selected && (
          <p style={{ fontFamily: "Open Sans, Arial, sans-serif", fontSize: 13, color: "#34A7F2", marginTop: 10 }}>
            Selected: <strong>{selected.name}</strong> ({selected.idno})
          </p>
        )}
      </section>

      {/* SearchResultCard — merged (multi-query, with country coverage badges) */}
      <section>
        <h2 style={{ fontFamily: "Open Sans, Arial, sans-serif", fontSize: 15, fontWeight: 600, color: "#666", margin: "0 0 12px" }}>
          search-card · SearchResultCard (merged layout, with country)
        </h2>
        <SearchResultCard
          indicators={MERGED_INDICATORS}
          title="Search Results"
          subtitle="GDP per capita · Kenya · Gini coefficient · Morocco"
          onSelect={(ind) => setSelected(ind)}
        />
      </section>

      {/* SearchResultCard — by_query grouped */}
      <section>
        <h2 style={{ fontFamily: "Open Sans, Arial, sans-serif", fontSize: 15, fontWeight: 600, color: "#666", margin: "0 0 12px" }}>
          search-card · SearchResultCard (by_query layout)
        </h2>
        <SearchResultCard
          groups={BY_QUERY_GROUPS}
          title="Search Results"
          subtitle="query_groups: GDP per capita (Kenya) · Gini (Morocco)"
          onSelect={(ind) => setSelected(ind)}
        />
      </section>

    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
