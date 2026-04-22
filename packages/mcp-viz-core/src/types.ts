// ─── Vega-Lite spec (minimal typed surface) ───────────────────────────────────

export type MarkType = "line" | "bar" | "point" | "area" | "tick";

export interface VLEncoding {
  field?: string;
  type?: "temporal" | "quantitative" | "nominal" | "ordinal";
  axis?: Record<string, unknown>;
  scale?: Record<string, unknown>;
  legend?: Record<string, unknown> | null;
  timeUnit?: string;
  [key: string]: unknown;
}

export interface VLSpec {
  $schema?: string;
  title?: string | { text: string; [key: string]: unknown };
  data?: { name?: string; values?: Record<string, unknown>[] };
  datasets?: Record<string, Record<string, unknown>[]>;
  mark?: MarkType | { type: MarkType; [key: string]: unknown };
  encoding?: {
    x?: VLEncoding;
    y?: VLEncoding;
    color?: VLEncoding;
    tooltip?: VLEncoding[];
    [key: string]: unknown;
  };
  params?: unknown[];
  config?: Record<string, unknown>;
  width?: number | string;
  height?: number | string;
  [key: string]: unknown;
}

// ─── Chart card (framework-agnostic) ───────────────────────────────────────────

export interface Annotation {
  /** The circled number shown next to the callout. */
  id: number;
  /** The italic callout text. */
  text: string;
}

/**
 * Props shared by React and Angular chart card implementations.
 * React adds `railTopSlot`; Angular may use a projected content slot instead.
 */
export interface VegaChartCardBaseProps {
  /**
   * A valid Vega-Lite spec. Passed through the prepareSpec() pipeline before
   * rendering — named datasets are inlined, WB theme applied, and mark-aware
   * axis/scale guards run automatically.
   */
  spec: VLSpec;

  /**
   * Card title. If omitted, falls back to spec.title.
   */
  title?: string;

  /**
   * Secondary line shown below the title (e.g. "Brazil, India · 2018–2022").
   */
  subtitle?: string;

  /**
   * Attribution line shown below the chart area.
   */
  source?: string;

  /**
   * Numbered callout annotations shown below the chart.
   * Hidden when the user toggles "Show annotations" off.
   */
  annotations?: Annotation[];

  /**
   * Card height in pixels. Defaults to 260.
   */
  chartHeight?: number;

  /**
   * Called when "Download data" is clicked.
   * Receives the raw filtered rows currently visible in the chart.
   * Defaults to a CSV download if omitted.
   */
  onDownload?: (rows: Record<string, unknown>[]) => void;

  /**
   * Called when the PNG export button is clicked.
   * Receives the PNG data URL. Defaults to a file download if omitted.
   */
  onExport?: (dataUrl: string) => void;

  /** Extra class name applied to the outer card div. */
  className?: string;
}
