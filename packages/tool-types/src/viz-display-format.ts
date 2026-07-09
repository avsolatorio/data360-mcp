/** Default chart footer when MCP does not return attribution fields. */
export const DATA360_CHART_SOURCE_FALLBACK = "World Bank — Data360";

function readOptionalString(obj: Record<string, unknown>, key: string): string {
  const v = obj[key];
  if (typeof v !== "string") {
    return "";
  }
  return v.trim();
}

/**
 * One-line attribution for Data360 viz tool results (Vega chart card "Source").
 * Uses `source_line` from the server when present; otherwise formats from
 * structured `database_*` / `indicator_*` fields (matches server and legacy client).
 */
export function formatData360VizSourceLine(result: unknown): string {
  if (!result || typeof result !== "object") {
    return DATA360_CHART_SOURCE_FALLBACK;
  }
  const r = result as Record<string, unknown>;
  const fromServer = readOptionalString(r, "source_line");
  if (fromServer) {
    return fromServer;
  }
  const db =
    readOptionalString(r, "database_name") ||
    readOptionalString(r, "database_id");
  const ind =
    readOptionalString(r, "indicator_name") ||
    readOptionalString(r, "indicator_id");
  if (db && ind) {
    return `World Bank — ${db} — ${ind}`;
  }
  if (ind) {
    return `World Bank — ${ind}`;
  }
  if (db) {
    return `World Bank — ${db}`;
  }
  return DATA360_CHART_SOURCE_FALLBACK;
}

/**
 * Subtitle under chart title when `subtitle_line` is absent (older MCP servers).
 */
export function formatData360VizSubtitleLine(result: unknown): string | undefined {
  if (!result || typeof result !== "object") {
    return undefined;
  }
  const r = result as Record<string, unknown>;
  const fromServer = readOptionalString(r, "subtitle_line");
  if (fromServer) {
    return fromServer;
  }
  const parts: string[] = [];
  const warning = readOptionalString(r, "warning");
  if (warning) {
    parts.push(warning);
  }
  const strategy = readOptionalString(r, "strategy");
  const reason = readOptionalString(r, "reason");
  if (strategy || reason) {
    parts.push([strategy, reason].filter(Boolean).join(" — "));
  }
  if (parts.length === 0) {
    return undefined;
  }
  return parts.join(" · ");
}
