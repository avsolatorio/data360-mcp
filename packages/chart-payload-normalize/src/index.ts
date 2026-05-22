/**
 * Chart URLs may return either a Charts API envelope `{ spec, title, ... }`
 * or a raw Vega-Lite spec object (e.g. Data360 MCP static JSON).
 */

export type NormalizedChartPayload = {
  spec: Record<string, unknown>;
  /** Main headline (matches Vega-Lite `title` string or `title.text`). */
  title: string;
  /**
   * Vega-Lite compound title subtitle (geography · years · unit), when present.
   * Prefer this for UI over tool `strategy`/`reason` metadata.
   */
  subtitle?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function looksLikeVegaLiteSpec(obj: Record<string, unknown>): boolean {
  if (typeof obj.$schema === "string" && /\bvega\b/i.test(obj.$schema)) {
    return true;
  }
  if ("mark" in obj) {
    return true;
  }
  if ("encoding" in obj && isRecord(obj.encoding as unknown)) {
    return true;
  }
  // Composite / faceted specs (no top-level mark)
  if ("layer" in obj) {
    return true;
  }
  if ("concat" in obj || "hconcat" in obj || "vconcat" in obj) {
    return true;
  }
  if ("facet" in obj || "repeat" in obj) {
    return true;
  }
  // Note: do not treat bare `{ spec: ... }` as VL — that pattern is also Charts API envelopes.
  return false;
}

function titleFromSpec(spec: Record<string, unknown>): string {
  const raw = spec.title;
  if (typeof raw === "string") {
    return raw;
  }
  if (Array.isArray(raw)) {
    const joined = raw.filter((s) => typeof s === "string").join("\n").trim();
    if (joined) return joined;
  }
  if (isRecord(raw)) {
    if (typeof raw.text === "string") {
      return raw.text;
    }
    if (Array.isArray(raw.text)) {
      const joined = raw.text
        .filter((s) => typeof s === "string")
        .join("\n")
        .trim();
      if (joined) return joined;
    }
  }
  return "Chart";
}

/** Vega-Lite `{ title: { text, subtitle } }` → second line for chart cards. */
export function subtitleFromSpec(spec: Record<string, unknown>): string | undefined {
  const raw = spec.title;
  if (!isRecord(raw)) {
    return undefined;
  }
  const sub = raw.subtitle;
  if (typeof sub === "string" && sub.trim()) {
    return sub.trim();
  }
  if (Array.isArray(sub)) {
    const lines = sub.filter(s => typeof s === "string" && s.trim()).map(s => s.trim());
    if (lines.length > 0) {
      return lines.join(" · ");
    }
  }
  return undefined;
}

function isLikelyChartsApiEnvelope(data: Record<string, unknown>): boolean {
  return typeof data.id === "string" || typeof data.createdAt === "string";
}

/**
 * @throws Error if the JSON is not a supported chart payload
 */
export function normalizeChartPayloadFromJson(
  data: unknown,
): NormalizedChartPayload {
  if (!isRecord(data)) {
    throw new Error("Chart JSON must be an object");
  }

  const nested = data.spec;

  // Charts API: explicit metadata — unwrap nested `spec` only.
  if (isRecord(nested) && isLikelyChartsApiEnvelope(data)) {
    const title =
      typeof data.title === "string" && data.title.trim()
        ? data.title
        : titleFromSpec(nested);
    return {
      spec: nested,
      title,
      subtitle: subtitleFromSpec(nested),
    };
  }

  // Raw Vega-Lite document at root (MCP static JSON, facet, layer, concat, …).
  if (looksLikeVegaLiteSpec(data)) {
    return {
      spec: data,
      title: titleFromSpec(data),
      subtitle: subtitleFromSpec(data),
    };
  }

  // Charts-style `{ title, spec }` without id/createdAt (unwrap nested VL only).
  if (
    isRecord(nested) &&
    typeof data.title === "string" &&
    data.title.trim() &&
    looksLikeVegaLiteSpec(nested)
  ) {
    return {
      spec: nested,
      title: data.title.trim(),
      subtitle: subtitleFromSpec(nested),
    };
  }

  // Nested `spec` that is clearly VL (legacy / loose envelopes).
  if (isRecord(nested) && looksLikeVegaLiteSpec(nested)) {
    const title =
      typeof data.title === "string" && data.title.trim()
        ? data.title.trim()
        : titleFromSpec(nested);
    return {
      spec: nested,
      title,
      subtitle: subtitleFromSpec(nested),
    };
  }

  throw new Error("Chart JSON did not contain a Vega-Lite spec");
}
