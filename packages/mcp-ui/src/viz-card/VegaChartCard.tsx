import {
  useEffect,
  useRef,
  useState,
  useMemo,
  useCallback,
  type CSSProperties,
} from "react";
import type { VegaChartCardProps } from "./types";
import { WB_PALETTE } from "./wb-theme";
import { prepareSpec, parseSpec } from "./prepare-spec";

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

function IconButton({
  title,
  onClick,
  children,
}: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      style={{
        width: 28, height: 28, borderRadius: 8,
        border: "0.5px solid rgba(0,0,0,0.12)",
        background: "none", cursor: "pointer",
        display: "flex", alignItems: "center", justifyContent: "center",
        color: "#666666",
      }}
    >
      {children}
    </button>
  );
}

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
  className,
}: VegaChartCardProps) {
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
    if (!chartRef.current || activeGroups.size === 0) return;

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
    if (!vegaViewRef.current) return;
    vegaViewRef.current.toImageURL("png", 2).then((url) => {
      if (onExport) {
        onExport(url);
        return;
      }
      const a = document.createElement("a");
      a.href = url; a.download = "chart.png"; a.click();
    });
  }, [onExport]);

  // ── Derived values ───────────────────────────────────────────────────────────

  const cardTitle = title ?? parsed.specTitle ?? "";

  // ── Styles ───────────────────────────────────────────────────────────────────

  const card: CSSProperties = {
    flex: 1,
    background: "#ffffff",
    border: "0.5px solid rgba(0,0,0,0.12)",
    borderRadius: 12,
    padding: "20px 20px 14px",
    fontFamily: "Open Sans, Arial, sans-serif",
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
    <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }} className={className}>
      <div style={card}>

        {/* Title + subtitle */}
        <h2 style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.3, color: "#111111", margin: 0 }}>
          {cardTitle}
        </h2>
        {subtitle && (
          <p style={{ fontSize: 14, color: "#666666", marginTop: 4 }}>{subtitle}</p>
        )}

        {/* Chart */}
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

        <Divider />

        {/* Footer controls */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <ToggleSwitch
            checked={showAnnotations}
            onChange={setShowAnnotations}
            label="Show annotations"
          />
          <button
            onClick={handleDownload}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              fontSize: 13, fontWeight: 600, color: "#34A7F2",
              background: "none", border: "none", cursor: "pointer", padding: 0,
              fontFamily: "Open Sans, Arial, sans-serif",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <rect x="1" y="1" width="12" height="12" rx="2" />
              <line x1="7" y1="4" x2="7" y2="9" />
              <polyline points="4.5,7 7,9.5 9.5,7" />
            </svg>
            Download data
          </button>
        </div>
      </div>

      {/* Side icon buttons */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4, paddingTop: 8 }}>
        <IconButton title="Save as PNG" onClick={handleExport}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
            <rect x="1" y="1" width="12" height="12" rx="2" />
            <polyline points="1,10 5,6 8,9 10,7 13,10" />
            <circle cx="4.5" cy="4.5" r="1" />
          </svg>
        </IconButton>
      </div>
    </div>
  );
}
