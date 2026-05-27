import { z } from "zod";

// ─── Leaf models ──────────────────────────────────────────────────────────────

/**
 * A single enriched indicator returned by `data360_search_indicators`.
 * Mirrors the Python `EnrichedIndicator` Pydantic model.
 */
export const enrichedIndicatorSchema = z
  .object({
    /** Indicator ID (e.g. "WB_WDI_NY_GDP_PCAP_KD"). Use with database_id for data lookups. */
    idno: z.string(),
    /** Database ID (e.g. "WB_WDI"). Required by get_data and get_viz_spec. */
    database_id: z.string(),
    /**
     * Human-readable name for the database_id (e.g. "World Development Indicators" for WB_WDI).
     * Use this when presenting data to users — never expand database_id by guessing.
     */
    database_name: z.string().nullable().optional(),
    /** Human-readable indicator name. */
    name: z.string(),
    /** Truncated definition (max 100 chars). */
    truncated_definition: z.string(),
    /** Data periodicity ("Annual", "Monthly", etc.). */
    periodicity: z.string().nullable().optional(),
    /** Most recent year with data (e.g. "2023"). */
    latest_data: z.string().nullable().optional(),
    /** Data availability range (e.g. "1990–2024"). */
    time_period_range: z.string().nullable().optional(),
    /**
     * Per-country availability map, e.g. { KEN: true, GHA: false }.
     * Single-country requests produce a single-entry map, e.g. { KEN: true }.
     * null when no country was requested.
     */
    covers_country: z.record(z.string(), z.boolean()).nullable().optional(),
    /**
     * Resolved 3-letter country code this indicator was evaluated against.
     * Set when query_groups is used or required_country was provided.
     */
    requested_country: z.string().nullable().optional(),
    /** Available disaggregation dimensions (e.g. ["SEX", "AGE"]). */
    dimensions: z.array(z.string()).nullable().optional(),
  })
  .passthrough();

export type EnrichedIndicator = z.infer<typeof enrichedIndicatorSchema>;

// ─── Single-query response ────────────────────────────────────────────────────

/**
 * Result from `data360_search_indicators` when called with a single `query`.
 * Mirrors `EnrichedSearchResponse`.
 */
export const data360SearchToolResultSchema = z
  .object({
    /** Enriched indicators sorted by relevance / country coverage. */
    indicators: z.array(enrichedIndicatorSchema),
    /** Resolved 3-letter country code used for coverage checks (e.g. "KEN"). */
    required_country: z.string().nullable().optional(),
    /** Resolved country names mapping codes to display names. */
    country_names: z.record(z.string(), z.string()).nullable().optional(),
    /** Error message if the search failed; otherwise null/absent. */
    error: z.string().nullable().optional(),
    /** Total indicators available (before page limit). */
    total_count: z.number().nullable().optional(),
    /** Number of indicators in this page. */
    count: z.number().optional(),
  })
  .passthrough();

export type Data360SearchToolResult = z.infer<typeof data360SearchToolResultSchema>;

// ─── Multi-query (by_query) sub-group ─────────────────────────────────────────

/**
 * A single query's result group within a `by_query` multi-query response.
 * Mirrors `QueryGroupResult`.
 */
export const queryGroupResultSchema = z
  .object({
    /** The search query string that produced this group. */
    query: z.string(),
    /**
     * Resolved 3-letter country code for this group.
     * Set when query_groups is used and a country was specified.
     */
    country_code: z.string().nullable().optional(),
    /** Indicators found for this query. */
    indicators: z.array(enrichedIndicatorSchema),
    /** Number of indicators in this group. */
    count: z.number(),
    /** Error message if this sub-query failed; otherwise null/absent. */
    error: z.string().nullable().optional(),
  })
  .passthrough();

export type QueryGroupResult = z.infer<typeof queryGroupResultSchema>;

// ─── Multi-query response ─────────────────────────────────────────────────────

/**
 * Result from `data360_search_indicators` when called with `queries` or `query_groups`.
 * Mirrors `MultiQuerySearchResponse`.
 *
 * - `result_layout="merged"`: `indicators` is a flat deduped list; `results` is null.
 * - `result_layout="by_query"`: `results` holds one group per query; `indicators` is empty.
 */
export const data360MultiQuerySearchToolResultSchema = z
  .object({
    /**
     * Flat indicator list (result_layout="merged").
     * Empty when result_layout="by_query" — use `results` instead.
     */
    indicators: z.array(enrichedIndicatorSchema),
    /** Per-query groups (result_layout="by_query"). */
    results: z.array(queryGroupResultSchema).nullable().optional(),
    /** Layout mode used for this response. */
    result_layout: z.enum(["merged", "by_query"]),
    /** The input query strings. */
    queries: z.array(z.string()),
    /** Resolved country code(s) shared across all sub-queries. */
    required_country: z.string().nullable().optional(),
    /** Resolved country names mapping codes to display names. */
    country_names: z.record(z.string(), z.string()).nullable().optional(),
    /** Total indicators found before deduplication. */
    total_candidates: z.number(),
    /** Number of duplicates removed (merged layout only). */
    deduplicated_count: z.number().nullable().optional(),
    /** Top-level error if the entire operation failed; otherwise null/absent. */
    error: z.string().nullable().optional(),
  })
  .passthrough();

export type Data360MultiQuerySearchToolResult = z.infer<
  typeof data360MultiQuerySearchToolResultSchema
>;

// ─── Parsers and guards ───────────────────────────────────────────────────────

/** Safe-parse the JSON result of a single-query `data360_search_indicators` call. */
export function parseData360SearchToolResult(
  value: unknown
): z.SafeParseReturnType<unknown, Data360SearchToolResult> {
  return data360SearchToolResultSchema.safeParse(value);
}

/** Safe-parse the JSON result of a multi-query `data360_search_indicators` call. */
export function parseData360MultiQuerySearchToolResult(
  value: unknown
): z.SafeParseReturnType<unknown, Data360MultiQuerySearchToolResult> {
  return data360MultiQuerySearchToolResultSchema.safeParse(value);
}

/**
 * Type guard: returns true when a parsed single-query result is a success.
 * A success means no top-level error is present. An empty indicators list is
 * a valid success (the query returned no results) — callers should check
 * `r.indicators.length` separately to decide whether to show a "no results" state.
 */
export function isData360SearchToolSuccess(
  r: Data360SearchToolResult
): r is Data360SearchToolResult & { error: null | undefined } {
  return !r.error;
}

/**
 * Type guard: returns true when a parsed multi-query result is a success.
 * A success means no top-level error.
 */
export function isData360MultiQuerySearchToolSuccess(
  r: Data360MultiQuerySearchToolResult
): r is Data360MultiQuerySearchToolResult & { error: null | undefined } {
  return !r.error;
}
