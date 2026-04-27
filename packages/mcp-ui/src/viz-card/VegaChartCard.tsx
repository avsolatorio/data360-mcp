import {
  memo,
  useEffect,
  useRef,
  useState,
  useMemo,
  useCallback,
  type CSSProperties,
  type ReactNode,
} from "react";
import type { VegaChartCardProps } from "./types";
import { toPng } from "html-to-image";
import { WB_PALETTE } from "@data360/mcp-viz-core";
import { prepareSpec, parseSpec } from "@data360/mcp-viz-core";

// ─── Sub-components ───────────────────────────────────────────────────────────

function Divider() {
  return (
    <hr style={{
      border: "none",
      borderTop: "0.5px solid rgba(0,0,0,0.1)",
      margin: "12px 0",
    }} />
  );
}

function ToggleSwitch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      onClick={() => onChange(!checked)}
      style={{
        display: "flex", alignItems: "center", gap: 8,
        background: "none", border: "none", cursor: "pointer",
        padding: 0, fontFamily: "Open Sans, Arial, sans-serif",
        fontSize: 13, color: "#666666",
      }}
    >
      <div style={{
        width: 34, height: 19, borderRadius: 100,
        background: checked ? "#34A7F2" : "rgba(0,0,0,0.2)",
        position: "relative", transition: "background 0.15s", flexShrink: 0,
      }}>
        <div style={{
          position: "absolute", top: 2, left: 2,
          width: 15, height: 15, borderRadius: "50%",
          background: "white",
          transform: checked ? "translateX(15px)" : "translateX(0)",
          transition: "transform 0.15s",
        }} />
      </div>
      {label}
    </button>
  );
}

function LegendButton({
  label,
  color,
  active,
  onClick,
}: {
  label: string;
  color: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 13, fontWeight: 600, cursor: "pointer",
        background: "none", border: "none", padding: "4px 10px",
        borderRadius: 8, fontFamily: "Open Sans, Arial, sans-serif",
        color: active ? "#111111" : "#aaaaaa",
        opacity: active ? 1 : 0.4,
        transition: "opacity 0.15s",
      }}
    >
      <div style={{
        width: 22, height: 3, borderRadius: 2,
        background: active ? color : "#cccccc",
        flexShrink: 0,
      }} />
      {label}
    </button>
  );
}

/** World Bank rail accent (matches toggle / “Download data” reference). */
const RAIL_ACCENT = "#34A7F2";

/**
 * Collapsed: 28px circle, grey icon.
 * Hover: pill expands to the RIGHT (label after icon) — absolutely positioned with a fixed
 * 28px slot so the rail does not shrink the chart (avoids Vega resize / layout stutter).
 */
const HoverRailIcon = memo(function HoverRailIcon({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  const [hover, setHover] = useState(false);
  const expanded = Boolean(label) && hover;
  const accent = expanded && !disabled;

  return (
    <div
      style={{
        position: "relative",
        width: 28,
        height: 28,
        flexShrink: 0,
        overflow: "visible",
        zIndex: 2,
      }}
    >
      <button
        type="button"
        aria-label={label}
        disabled={disabled}
        onClick={disabled ? undefined : onClick}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: expanded ? "flex-start" : "center",
          boxSizing: "border-box",
          height: 28,
          minWidth: 28,
          width: expanded ? "max-content" : 28,
          maxWidth: expanded ? 280 : 28,
          padding: expanded ? "5px 14px 5px 8px" : "0",
          gap: expanded ? 8 : 0,
          borderRadius: expanded ? 999 : "50%",
          border: "0.5px solid rgba(0,0,0,0.12)",
          background: "#ffffff",
          color: accent ? RAIL_ACCENT : "#666666",
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.55 : 1,
          transition:
            "border-radius 0.18s ease, padding 0.18s ease, gap 0.18s ease, color 0.15s ease",
          fontFamily: "Open Sans, Arial, sans-serif",
          overflow: "visible",
          boxShadow: expanded ? "0 1px 4px rgba(0,0,0,0.06)" : "none",
        }}
      >
        <span
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            lineHeight: 0,
            width: expanded ? undefined : 28,
            height: 28,
            color: "inherit",
          }}
        >
          {children}
        </span>
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            whiteSpace: "nowrap",
            overflow: "hidden",
            maxWidth: expanded ? 240 : 0,
            opacity: expanded ? 1 : 0,
            transition: "max-width 0.18s ease, opacity 0.14s ease",
            color: "inherit",
          }}
        >
          {label}
        </span>
      </button>
    </div>
  );
});

// ─── Main component ───────────────────────────────────────────────────────────

export default function VegaChartCard({
  spec,
  title,
  subtitle,
  source,
  annotations = [],
  chartHeight = 260,
  onDownload,
  onExport,
  pngExportPixelRatio = 4,
  railTopSlot,
  className,
}: VegaChartCardProps) {
  const cardRef     = useRef<HTMLDivElement>(null);
  const chartRef    = useRef<HTMLDivElement>(null);
  const vegaViewRef = useRef<{ finalize(): void; toImageURL(fmt: string, scale: number): Promise<string> } | null>(null);

  const [activeGroups, setActiveGroups] = useState<Set<string>>(new Set());
  const [showAnnotations, setShowAnnotations] = useState(true);

  // Parse legend metadata from the original spec (not prepared)
  const parsed = useMemo(() => parseSpec(spec, WB_PALETTE), [spec]);

  // Initialise active groups when spec changes
  useEffect(() => {
    setActiveGroups(new Set(parsed.distinctGroups));
  }, [parsed.distinctGroups]);

  const toggleGroup = useCallback((group: string) => {
    setActiveGroups((prev) => {
      const next = new Set(prev);
      if (next.has(group) && next.size > 1) next.delete(group);
      else next.add(group);
      return next;
    });
  }, []);

  // Re-render chart when spec, active groups, or height changes
  useEffect(() => {
    if (!chartRef.current) return;
    // Single-series specs have no color legend → distinctGroups and activeGroups stay empty; still embed.
    if (parsed.distinctGroups.length > 0 && activeGroups.size === 0) return;

    // Dynamically import vega-embed (peer dep)
    import("vega-embed").then(({ default: embed }) => {
      let prepared = prepareSpec(spec, chartHeight);

      // Filter rows to active groups
      if (parsed.colorField && prepared.data?.values) {
        prepared = {
          ...prepared,
          data: {
            values: prepared.data.values.filter(
              (r) => activeGroups.has(String(r[parsed.colorField!]))
            ),
          },
        };
      }

      // Apply active color scale
      if (prepared.encoding?.color && parsed.colorField) {
        const activeDomain = parsed.distinctGroups.filter((g) => activeGroups.has(g));
        prepared.encoding.color.scale = {
          domain: activeDomain,
          range:  activeDomain.map((g) => parsed.colorMap[g]),
        };
      }

      // Finalize previous view
      try { vegaViewRef.current?.finalize(); } catch { /* ignore */ }

      embed(chartRef.current!, prepared as never, {
        actions: false,
        renderer: "svg",
      }).then((result) => {
        vegaViewRef.current = result.view as typeof vegaViewRef.current;
      }).catch(console.error);
    });

    return () => {
      try { vegaViewRef.current?.finalize(); } catch { /* ignore */ }
    };
  }, [spec, activeGroups, chartHeight, parsed]);

  // ── Handlers ────────────────────────────────────────────────────────────────

  const handleDownload = useCallback(() => {
    const rows = parsed.rows.filter(
      (r) => !parsed.colorField || activeGroups.has(String(r[parsed.colorField]))
    );
    if (onDownload) {
      onDownload(rows);
      return;
    }
    // Default: CSV download
    const keys = Object.keys(rows[0] ?? {});
    const csv  = [keys.join(","), ...rows.map((r) => keys.map((k) => r[k]).join(","))].join("\n");
    const a = document.createElement("a");
    a.href     = "data:text/csv;charset=utf-8," + encodeURIComponent(csv);
    a.download = "chart-data.csv";
    a.click();
  }, [parsed, activeGroups, onDownload]);

  const handleExport = useCallback(() => {
    const deliver = (url: string) => {
      if (onExport) {
        onExport(url);
        return;
      }
      const a = document.createElement("a");
      a.href = url;
      a.download = "chart.png";
      a.click();
    };

    const fromVegaOnly = () => {
      if (!vegaViewRef.current) return;
      void vegaViewRef.current.toImageURL("png", pngExportPixelRatio).then(deliver);
    };

    const node = cardRef.current;
    if (!node) {
      fromVegaOnly();
      return;
    }

    void toPng(node, {
      pixelRatio: pngExportPixelRatio,
      backgroundColor: "#ffffff",
      cacheBust: true,
      filter: (domNode) =>
        !(domNode instanceof HTMLElement && domNode.hasAttribute("data-chart-card-export-skip")),
    })
      .then(deliver)
      .catch(fromVegaOnly);
  }, [onExport, pngExportPixelRatio]);

  const handleCopySpec = useCallback(() => {
    try {
      void navigator.clipboard.writeText(JSON.stringify(spec, null, 2));
    } catch {
      /* ignore */
    }
  }, [spec]);

  // ── Derived values ───────────────────────────────────────────────────────────

  const cardTitle = title ?? parsed.specTitle ?? "";

  // ── Styles ───────────────────────────────────────────────────────────────────

  const card: CSSProperties = {
    flex: 1,
    minWidth: 0,
    background: "#ffffff",
    border: "0.5px solid rgba(0,0,0,0.12)",
    borderRadius: 12,
    padding: "20px 20px 14px",
    fontFamily: "Open Sans, Arial, sans-serif",
  };

  /** Fixed 28px column width so hover pills don’t reflow the chart. Overflow visible for pills. */
  const outerRailStyle: CSSProperties = {
    display: "flex",
    flexDirection: "column",
    justifyContent: railTopSlot ? "space-between" : "flex-end",
    alignItems: "flex-start",
    flexShrink: 0,
    width: 28,
    minWidth: 28,
    maxWidth: 28,
    overflow: "visible",
    paddingTop: railTopSlot ? 6 : 0,
    paddingBottom: 6,
  };

  const railActionStackStyle: CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    alignItems: "flex-start",
    width: 28,
    overflow: "visible",
  };

  const chartArea: CSSProperties = {
    background: "rgba(0,0,0,0.03)",
    borderRadius: 8,
    margin: "14px 0 0",
    minHeight: chartHeight,
    width: "100%",
    overflow: "hidden",
  };

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div
      className={className}
      style={{ display: "flex", gap: 10, alignItems: "stretch", width: "100%" }}
    >
      <div ref={cardRef} style={card}>

        {/* Title + subtitle */}
        <h2 style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.3, color: "#111111", margin: 0 }}>
          {cardTitle}
        </h2>
        {subtitle && (
          <p style={{ fontSize: 14, color: "#666666", marginTop: 4 }}>{subtitle}</p>
        )}

        {/* Chart (PNG export captures this whole card via html-to-image) */}
        <div ref={chartRef} style={chartArea} />

        {/* Interactive legend */}
        {parsed.distinctGroups.length > 0 && (
          <div style={{ display: "flex", gap: 4, justifyContent: "center", flexWrap: "wrap", margin: "10px 0 4px" }}>
            {parsed.distinctGroups.map((g) => (
              <LegendButton
                key={g}
                label={g}
                color={parsed.colorMap[g]}
                active={activeGroups.has(g)}
                onClick={() => toggleGroup(g)}
              />
            ))}
          </div>
        )}

        {/* Annotations */}
        {showAnnotations && annotations.length > 0 && (
          <>
            <Divider />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {annotations.map((ann) => (
                <div key={ann.id} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                  <div style={{
                    width: 20, height: 20, borderRadius: "50%", flexShrink: 0, marginTop: 1,
                    border: "0.5px solid rgba(0,0,0,0.2)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 11, fontWeight: 600, color: "#666666",
                  }}>
                    {ann.id}
                  </div>
                  <p style={{ fontSize: 13, color: "#666666", lineHeight: 1.6, fontStyle: "italic", margin: 0 }}>
                    {ann.text}
                  </p>
                </div>
              ))}
            </div>
          </>
        )}

        {/* Source */}
        {source && (
          <p style={{ fontSize: 12, color: "#999999", marginTop: 12 }}>
            <strong style={{ fontWeight: 600, color: "#666666" }}>Source:</strong> {source}
          </p>
        )}

        {/* Omitted from PNG export (toggle is UI chrome, not chart content) */}
        <div data-chart-card-export-skip="">
          <Divider />
          <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
            <ToggleSwitch
              checked={showAnnotations}
              onChange={setShowAnnotations}
              label="Show annotations"
            />
          </div>
        </div>
      </div>

      <div style={outerRailStyle}>
        {railTopSlot ? (
          <div
            style={{
              alignSelf: "flex-end",
              display: "flex",
              justifyContent: "flex-end",
              width: "100%",
              flexShrink: 0,
            }}
          >
            {railTopSlot}
          </div>
        ) : null}
        <div style={railActionStackStyle}>
          <HoverRailIcon label="Download data" onClick={handleDownload}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
              <rect
                x="1.25"
                y="1.25"
                width="11.5"
                height="11.5"
                rx="1.25"
                stroke="currentColor"
                strokeWidth="1.1"
              />
              <line
                x1="1.25"
                y1="4.75"
                x2="12.75"
                y2="4.75"
                stroke="currentColor"
                strokeWidth="1.1"
              />
              <line
                x1="7"
                y1="4.75"
                x2="7"
                y2="12.75"
                stroke="currentColor"
                strokeWidth="1.1"
              />
              <line
                x1="4"
                y1="8"
                x2="10"
                y2="8"
                stroke="currentColor"
                strokeWidth="0.9"
              />
              <line
                x1="4"
                y1="10.25"
                x2="10"
                y2="10.25"
                stroke="currentColor"
                strokeWidth="0.9"
              />
            </svg>
          </HoverRailIcon>
          <HoverRailIcon label="Save as PNG" onClick={handleExport}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
              <rect x="1" y="1" width="12" height="12" rx="2" />
              <polyline points="1,10 5,6 8,9 10,7 13,10" />
              <circle cx="4.5" cy="4.5" r="1" />
            </svg>
          </HoverRailIcon>
          <HoverRailIcon disabled label="Export as PDF (soon)">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
              <path
                d="M3 1.5h4.5L11 5v7.5H3z"
                stroke="currentColor"
                strokeWidth="1.1"
                strokeLinejoin="round"
              />
              <text
                fill="currentColor"
                fontSize="4.2"
                fontWeight="700"
                x="3.8"
                y="11.2"
                style={{ fontFamily: "Open Sans, Arial, sans-serif" }}
              >
                PDF
              </text>
            </svg>
          </HoverRailIcon>
          <HoverRailIcon label="Copy Vega-Lite spec" onClick={handleCopySpec}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
              <text
                fill="currentColor"
                fontSize="7.5"
                fontWeight="600"
                x="1.5"
                y="10.5"
                style={{ fontFamily: "ui-monospace, monospace" }}
              >
                {`${"<"}/${">"}`}
              </text>
            </svg>
          </HoverRailIcon>
        </div>
      </div>
    </div>
  );
}
