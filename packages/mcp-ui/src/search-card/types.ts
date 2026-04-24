// Re-export types inline so mcp-ui does not need @data360/tool-types as a hard install-time dep.
// These must stay structurally identical to the Zod inferred types in search-contract.ts.

/** A single enriched indicator as returned by data360_search_indicators. */
export interface EnrichedIndicator {
  idno: string;
  database_id: string;
  /** Human-readable database name (e.g. "World Development Indicators"). Prefer over database_id for display. */
  database_name?: string | null;
  name: string;
  truncated_definition: string;
  periodicity?: string | null;
  latest_data?: string | null;
  time_period_range?: string | null;
  /**
   * Per-country availability map, e.g. { KEN: true, GHA: false }.
   * Single-country requests produce a single-entry map, e.g. { KEN: true }.
   * null when no country was requested.
   */
  covers_country?: Record<string, boolean> | null;
  requested_country?: string | null;
  dimensions?: string[] | null;
  [key: string]: unknown;
}

/** A per-query result group for by_query layout. */
export interface QueryGroupResult {
  query: string;
  country_code?: string | null;
  indicators: EnrichedIndicator[];
  count: number;
  error?: string | null;
  [key: string]: unknown;
}

// ─── Component props ──────────────────────────────────────────────────────────

export interface SearchResultCardProps {
  /**
   * Flat list of enriched indicators to display.
   * Used when result_layout="merged" or for a single-query response.
   * If `groups` is also provided, `indicators` is ignored in favour of the grouped view.
   */
  indicators?: EnrichedIndicator[];

  /**
   * Per-query result groups (result_layout="by_query").
   * When provided, renders an accordion grouped by query / country.
   * Each group's indicators are listed under a collapsible header.
   */
  groups?: QueryGroupResult[];

  /**
   * Card title shown at the top.
   * Defaults to "Search Results".
   */
  title?: string;

  /**
   * Secondary line shown below the title.
   * Typically the search topics or country context (e.g. "GDP · Kenya, Gini · Morocco").
   */
  subtitle?: string;

  /**
   * Called when the user clicks an indicator row.
   * The host app decides the follow-up action (e.g. call get_data, get_viz_spec).
   * When omitted, rows are rendered without a hover/click affordance.
   */
  onSelect?: (indicator: EnrichedIndicator) => void;

  /** Extra CSS class applied to the outer card div. */
  className?: string;
}
