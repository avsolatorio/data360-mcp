import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import type { VLSpec } from "@data360/mcp-viz-core";
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

// ── Demo 1: query — single topic, one country ──────────────────────────────────
// Simulates: data360_search_indicators(query="poverty headcount ratio", required_country="Philippines")
const DEMO_QUERY_SINGLE: EnrichedIndicator[] = [
  {
    idno: "WB_WDI_SI_POV_NAHC",
    database_id: "WB_WDI",
    database_name: "World Development Indicators (WDI)",
    name: "Poverty headcount ratio at national poverty lines (% of population)",
    truncated_definition: "National poverty headcount ratio is the percentage of the population living below the national poverty lines.",
    periodicity: "Annual",
    latest_data: "2021",
    time_period_range: "2000–2021",
    covers_country: { PHL: true },
    requested_country: "PHL",
  },
  {
    idno: "WB_WDI_SI_POV_DDAY",
    database_id: "WB_WDI",
    database_name: "World Development Indicators (WDI)",
    name: "Poverty headcount ratio at $2.15 a day (2017 PPP) (% of population)",
    truncated_definition: "Percentage of the population living on less than $2.15 a day at 2017 international prices.",
    periodicity: "Annual",
    latest_data: "2021",
    time_period_range: "2000–2021",
    covers_country: { PHL: true },
    requested_country: "PHL",
  },
  {
    idno: "WB_WDI_SI_POV_URHC",
    database_id: "WB_WDI",
    database_name: "World Development Indicators (WDI)",
    name: "Urban poverty headcount ratio at national poverty lines (% of urban population)",
    truncated_definition: "Urban poverty headcount ratio is the percentage of the urban population living below the national urban poverty line.",
    periodicity: "Annual",
    latest_data: "2021",
    time_period_range: "2000–2021",
    covers_country: { PHL: true },
    requested_country: "PHL",
    dimensions: ["URBANISATION"],
  },
];

// ── Demo 2: queries — multiple topics, shared country list ─────────────────────
// Simulates: data360_search_indicators(
//   queries=["GDP per capita","inflation","GNI per capita","Gini"],
//   required_country="Philippines;Japan"
// )
const DEMO_QUERIES_MULTI: EnrichedIndicator[] = [
  {
    idno: "WB_WDI_NY_GDP_PCAP_KD",
    database_id: "WB_WDI",
    database_name: "World Development Indicators (WDI)",
    name: "GDP per capita (constant 2015 US$)",
    truncated_definition: "GDP per capita based on constant 2015 prices, in US dollars.",
    periodicity: "Annual",
    latest_data: "2023",
    time_period_range: "1960–2023",
    covers_country: { PHL: true, JPN: true },
    requested_country: "PHL;JPN",
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
    covers_country: { PHL: true, JPN: true },
    requested_country: "PHL;JPN",
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
    covers_country: { PHL: true, JPN: true },
    requested_country: "PHL;JPN",
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
    // Japan has no Gini data — shows "− No data for JPN"
    covers_country: { PHL: true, JPN: false },
    requested_country: "PHL;JPN",
  },
];

// ── Demo 3: query_groups — different topics per country ────────────────────────
// Simulates: data360_search_indicators(query_groups=[
//   { queries: ["GDP per capita", "inflation"], country: "Japan" },
//   { queries: ["population"],                 country: "Philippines" }
// ])
const DEMO_QUERY_GROUPS = [
  {
    query: "GDP per capita, inflation",
    country_code: "JPN",
    country_name: "Japan",
    count: 2,
    indicators: [
      {
        idno: "WB_WDI_NY_GDP_PCAP_KD",
        database_id: "WB_WDI",
        database_name: "World Development Indicators (WDI)",
        name: "GDP per capita (constant 2015 US$)",
        truncated_definition: "GDP per capita based on constant 2015 prices, in US dollars.",
        periodicity: "Annual",
        latest_data: "2023",
        time_period_range: "1960–2023",
        covers_country: { JPN: true },
        requested_country: "JPN",
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
        covers_country: { JPN: true },
        requested_country: "JPN",
      },
    ],
  },
  {
    query: "population",
    country_code: "PHL",
    country_name: "Philippines",
    count: 2,
    indicators: [
      {
        idno: "WB_WDI_SP_POP_TOTL",
        database_id: "WB_WDI",
        database_name: "World Development Indicators (WDI)",
        name: "Population, total",
        truncated_definition: "Total population based on the de facto definition, counting all residents regardless of legal status or citizenship.",
        periodicity: "Annual",
        latest_data: "2023",
        time_period_range: "1960–2023",
        covers_country: { PHL: true },
        requested_country: "PHL",
      },
      {
        idno: "WB_WDI_SP_POP_GROW",
        database_id: "WB_WDI",
        database_name: "World Development Indicators (WDI)",
        name: "Population growth (annual %)",
        truncated_definition: "Annual population growth rate for year t is the exponential rate of growth of midyear population from year t-1 to t.",
        periodicity: "Annual",
        latest_data: "2023",
        time_period_range: "1961–2023",
        covers_country: { PHL: true },
        requested_country: "PHL",
      },
    ],
  },
];

// ─── Demo app ──────────────────────────────────────────────────────────────────

const SECTION_LABEL: React.CSSProperties = {
  fontFamily: "Open Sans, Arial, sans-serif",
  fontSize: 12,
  fontWeight: 700,
  color: "#888",
  margin: "0 0 3px",
  textTransform: "uppercase",
  letterSpacing: "0.07em",
};

const SECTION_DESC: React.CSSProperties = {
  fontFamily: "ui-monospace, monospace",
  fontSize: 11,
  color: "#aaa",
  margin: "0 0 10px",
};

function App() {
  const [selected, setSelected] = useState<EnrichedIndicator | null>(null);

  return (
    <div style={{ padding: 32, maxWidth: 920, margin: "0 auto", display: "flex", flexDirection: "column", gap: 40 }}>

      <h1 style={{ fontFamily: "Open Sans, Arial, sans-serif", fontSize: 22, fontWeight: 700, margin: 0, color: "#111" }}>
        @data360/mcp-ui — Component demo
      </h1>

      {/* VegaChartCard */}
      <section>
        <p style={SECTION_LABEL}>viz-card · VegaChartCard</p>
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

      {/* ── Demo 1: query ──────────────────────────────────────────────────── */}
      <section>
        <p style={SECTION_LABEL}>search-card · query — one topic, one country</p>
        <p style={SECTION_DESC}>
          data360_search_indicators(query="poverty headcount ratio", required_country="Philippines")
        </p>
        <SearchResultCard
          indicators={DEMO_QUERY_SINGLE}
          title="Indicator Search"
          subtitle="Poverty headcount ratio — Philippines"
          onSelect={(ind) => setSelected(ind)}
        />
        {selected && (
          <p style={{ fontFamily: "Open Sans, Arial, sans-serif", fontSize: 12, color: "#34A7F2", marginTop: 8 }}>
            Selected: <strong>{selected.name}</strong> ({selected.idno})
          </p>
        )}
      </section>

      {/* ── Demo 2: queries ─────────────────────────────────────────────────── */}
      <section>
        <p style={SECTION_LABEL}>search-card · queries — multiple topics, shared countries</p>
        <p style={SECTION_DESC}>
          data360_search_indicators(queries=["GDP per capita","inflation","GNI per capita","Gini"], required_country="Philippines;Japan")
        </p>
        <SearchResultCard
          indicators={DEMO_QUERIES_MULTI}
          title="Indicator Search"
          subtitle="GDP per capita · Inflation · GNI · Gini — Philippines, Japan"
          onSelect={(ind) => setSelected(ind)}
        />
      </section>

      {/* ── Demo 3: query_groups ────────────────────────────────────────────── */}
      <section>
        <p style={SECTION_LABEL}>search-card · query_groups — different topics per country</p>
        <p style={SECTION_DESC}>
          {'data360_search_indicators(query_groups=[{queries:["GDP per capita","inflation"], country:"Japan"}, {queries:["population"], country:"Philippines"}])'}
        </p>
        <SearchResultCard
          groups={DEMO_QUERY_GROUPS}
          title="Indicator Search"
          subtitle="Japan: GDP per capita, Inflation · Philippines: Population"
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
