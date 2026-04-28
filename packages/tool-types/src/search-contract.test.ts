import { describe, expect, it } from "vitest";
import {
  parseData360SearchToolResult,
  parseData360MultiQuerySearchToolResult,
  isData360SearchToolSuccess,
  isData360MultiQuerySearchToolSuccess,
} from "./search-contract";

// ─── Single-query ─────────────────────────────────────────────────────────────

describe("Data360SearchToolResult", () => {
  it("accepts a minimal success payload (single query)", () => {
    const ok = parseData360SearchToolResult({
      indicators: [
        {
          idno: "WB_WDI_NY_GDP_PCAP_KD",
          database_id: "WB_WDI",
          name: "GDP per capita (constant 2015 US$)",
          truncated_definition: "GDP per capita based on constant 2015 US dollars.",
        },
      ],
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(isData360SearchToolSuccess(ok.data)).toBe(true);
    }
  });

  it("accepts full shape with country coverage fields", () => {
    const ok = parseData360SearchToolResult({
      indicators: [
        {
          idno: "WB_WDI_NY_GDP_PCAP_KD",
          database_id: "WB_WDI",
          name: "GDP per capita",
          truncated_definition: "GDP per capita.",
          periodicity: "Annual",
          latest_data: "2023",
          time_period_range: "1990–2023",
          covers_country: { KEN: true },
          requested_country: "KEN",
          dimensions: ["SEX", "AGE"],
        },
      ],
      required_country: "KEN",
      error: null,
      total_count: 1,
      count: 1,
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(ok.data.indicators[0].covers_country).toEqual({ KEN: true });
      expect(ok.data.indicators[0].requested_country).toBe("KEN");
    }
  });

  it("success guard returns false when error is set", () => {
    const ok = parseData360SearchToolResult({
      indicators: [],
      error: "Search failed",
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(isData360SearchToolSuccess(ok.data)).toBe(false);
    }
  });

  it("success guard returns true when indicators is empty and no error (valid \"no results\" state)", () => {
    const ok = parseData360SearchToolResult({ indicators: [] });
    expect(ok.success).toBe(true);
    if (ok.success) {
      // An empty result set without an error is a valid success — not a failure.
      // Callers should check indicators.length to decide on the "no results" UI state.
      expect(isData360SearchToolSuccess(ok.data)).toBe(true);
    }
  });

  it("rejects non-objects", () => {
    expect(parseData360SearchToolResult(null).success).toBe(false);
    expect(parseData360SearchToolResult("string").success).toBe(false);
    expect(parseData360SearchToolResult(42).success).toBe(false);
  });

  it("rejects payloads missing required indicator fields", () => {
    const bad = parseData360SearchToolResult({
      indicators: [{ idno: "X" }], // missing name, database_id, truncated_definition
    });
    expect(bad.success).toBe(false);
  });
});

// ─── database_name field ──────────────────────────────────────────────────────

describe("EnrichedIndicator database_name field", () => {
  const base = {
    idno: "WB_WDI_NY_GDP_PCAP_KD",
    database_id: "WB_WDI",
    name: "GDP per capita",
    truncated_definition: "GDP per capita based on constant 2015 US dollars.",
  };

  it("accepts a string database_name", () => {
    const ok = parseData360SearchToolResult({
      indicators: [{ ...base, database_name: "World Development Indicators" }],
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(ok.data.indicators[0].database_name).toBe("World Development Indicators");
    }
  });

  it("accepts null database_name (unknown database id)", () => {
    const ok = parseData360SearchToolResult({
      indicators: [{ ...base, database_id: "WB_UNKNOWN", database_name: null }],
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(ok.data.indicators[0].database_name).toBeNull();
    }
  });

  it("accepts absent database_name (optional field)", () => {
    // Omitting the field entirely should still parse — backward compatible with
    // responses from older server versions that do not include database_name.
    const ok = parseData360SearchToolResult({ indicators: [base] });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(ok.data.indicators[0].database_name).toBeUndefined();
    }
  });
});

// ─── Multi-query ──────────────────────────────────────────────────────────────

describe("Data360MultiQuerySearchToolResult", () => {
  it("accepts a merged layout payload", () => {
    const ok = parseData360MultiQuerySearchToolResult({
      indicators: [
        {
          idno: "WB_WDI_NY_GDP_PCAP_KD",
          database_id: "WB_WDI",
          name: "GDP per capita",
          truncated_definition: "GDP per capita.",
          requested_country: "KEN",
        },
      ],
      result_layout: "merged",
      queries: ["GDP per capita", "inflation"],
      total_candidates: 1,
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(isData360MultiQuerySearchToolSuccess(ok.data)).toBe(true);
      expect(ok.data.result_layout).toBe("merged");
    }
  });

  it("accepts a by_query layout payload with per-group results", () => {
    const ok = parseData360MultiQuerySearchToolResult({
      indicators: [],
      results: [
        {
          query: "GDP per capita",
          country_code: "KEN",
          indicators: [
            {
              idno: "WB_WDI_NY_GDP_PCAP_KD",
              database_id: "WB_WDI",
              name: "GDP per capita",
              truncated_definition: "GDP per capita.",
            },
          ],
          count: 1,
        },
        {
          query: "Gini coefficient",
          country_code: "MAR",
          indicators: [],
          count: 0,
          error: "No results found",
        },
      ],
      result_layout: "by_query",
      queries: ["GDP per capita", "Gini coefficient"],
      total_candidates: 1,
      deduplicated_count: null,
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(ok.data.results?.length).toBe(2);
      expect(ok.data.results?.[0].country_code).toBe("KEN");
    }
  });

  it("success guard returns false when top-level error is set", () => {
    const ok = parseData360MultiQuerySearchToolResult({
      indicators: [],
      result_layout: "merged",
      queries: [],
      total_candidates: 0,
      error: "Internal error",
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(isData360MultiQuerySearchToolSuccess(ok.data)).toBe(false);
    }
  });

  it("rejects non-objects", () => {
    expect(parseData360MultiQuerySearchToolResult(null).success).toBe(false);
  });

  it("rejects invalid result_layout values", () => {
    const bad = parseData360MultiQuerySearchToolResult({
      indicators: [],
      result_layout: "unknown_layout",
      queries: [],
      total_candidates: 0,
    });
    expect(bad.success).toBe(false);
  });

  it("success guard returns true when merged result has zero indicators and no error", () => {
    // A valid query that found nothing — should be treated as success, not failure.
    const ok = parseData360MultiQuerySearchToolResult({
      indicators: [],
      result_layout: "merged",
      queries: ["obscure topic no one has data for"],
      total_candidates: 0,
    });
    expect(ok.success).toBe(true);
    if (ok.success) {
      expect(isData360MultiQuerySearchToolSuccess(ok.data)).toBe(true);
    }
  });
});
