import { z } from "zod";

/**
 * Normalized result from `data360_get_viz_spec` and `data360_get_multi_indicator_viz_spec`.
 * Matches `VizResult` in `data360.visualization` (plus optional multi-indicator fields).
 */
export const data360VizToolResultSchema = z
  .object({
    url: z.string().nullable(),
    error: z.string().nullable(),
    warning: z.string().nullable().optional(),
    strategy: z.string().optional(),
    reason: z.string().optional(),
    /** Human-readable database name(s) for chart source line */
    database_name: z.string().optional(),
    database_id: z.string().optional(),
    indicator_name: z.string().optional(),
    indicator_id: z.string().optional(),
    /** Preformatted one-line footer (preferred over computing from attribution fields). */
    source_line: z.string().optional(),
    /** Preformatted subtitle under the chart title (warning · strategy — reason). */
    subtitle_line: z.string().optional(),
  })
  .passthrough();

export type Data360VizToolResult = z.infer<typeof data360VizToolResultSchema>;

export function parseData360VizToolResult(
  value: unknown
): z.SafeParseReturnType<unknown, Data360VizToolResult> {
  return data360VizToolResultSchema.safeParse(value);
}

export function isData360VizToolSuccess(
  r: Data360VizToolResult
): r is Data360VizToolResult & { url: string; error: null } {
  return Boolean(r.url) && (r.error === null || r.error === undefined);
}
