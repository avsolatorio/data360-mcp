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
import {
  WB_PALETTE,
  choroplethLegendVerticalReservePx,
  choroplethMapFacetHeightPx,
  hasChoroplethQuantitativeColor,
  patchVegaSpecChoroplethMapGroupClip,
  patchVegaSpecChoroplethWheelZoom,
  prepareSpec,
  parseSpec,
  suggestChoroplethSceneHeight,
} from "@data360/mcp-viz-core";
import { DATA360_CHART_UI_REVISION } from "./chart-ui-revision";
import { applyChoroplethEmbedDomStyles } from "./choropleth-embed-dom";
import { attachChoroplethMapInteractions } from "./choropleth-host-interactions";

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
  hideChartUiRevision = false,
}: VegaChartCardProps) {
  const cardRef     = useRef<HTMLDivElement>(null);
  const chartRef    = useRef<HTMLDivElement>(null);
  const vegaViewRef = useRef<{ finalize(): void; toImageURL(fmt: string, scale: number): Promise<string> } | null>(null);

  const [activeGroups, setActiveGroups] = useState<Set<string>>(new Set());
  const [showAnnotations, setShowAnnotations] = useState(true);
  /** Geoshape slot width so maps use full card width instead of a fixed 600px spec. */
  const [mapSlotWidth, setMapSlotWidth] = useState(0);

  // Parse legend metadata from the original spec (not prepared)
  const parsed = useMemo(() => parseSpec(spec, WB_PALETTE), [spec]);

  /** Choropleths use quantitative color + sequential scale; card legend toggles are categorical-only. */
  const isChoroplethQuantitative = useMemo(
    () => hasChoroplethQuantitativeColor(spec),
    [spec],
  );

  /** VL scene height (``prepareSpec``): capped map facet + legend strip — see ``suggestChoroplethSceneHeight``. */
  const choroplethSpecHeight = useMemo(() => {
    if (!isChoroplethQuantitative || mapSlotWidth < 1) {
      return chartHeight;
    }
    return suggestChoroplethSceneHeight(mapSlotWidth, chartHeight);
  }, [isChoroplethQuantitative, mapSlotWidth, chartHeight]);

  const choroplethVegaHeight = choroplethSpecHeight;

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

  useEffect(() => {
    const node = chartRef.current;
    if (!node || !isChoroplethQuantitative) {
      setMapSlotWidth(0);
      return;
    }
    const measure = () => {
      const w = node.clientWidth;
      if (w > 0) {
        setMapSlotWidth(Math.floor(w));
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(node);
    return () => {
      ro.disconnect();
    };
  }, [isChoroplethQuantitative]);

  // Re-render chart when spec, active groups, or height changes
  useEffect(() => {
    if (!chartRef.current) return;
    // Single-series specs have no color legend → distinctGroups and activeGroups stay empty; still embed.
    // Choropleth quantitative: skip this guard — distinct "groups" are numeric bins, not series toggles.
    if (
      !isChoroplethQuantitative &&
      parsed.distinctGroups.length > 0 &&
      activeGroups.size === 0
    ) {
      return;
    }

    if (isChoroplethQuantitative && mapSlotWidth < 1) {
      return;
    }

    let cancelled = false;
    let detachChoropleth: (() => void) | undefined;

    void Promise.all([import("vega-embed"), import("vega-lite")]).then(
      ([{ default: embed }, vl]) => {
        if (cancelled || !chartRef.current) return;

        let prepared = prepareSpec(
          spec,
          isChoroplethQuantitative ? choroplethVegaHeight : chartHeight,
          isChoroplethQuantitative ? mapSlotWidth : undefined,
        );

        // Filter rows to active groups (categorical series only; not choropleth sequential color)
        if (
          !isChoroplethQuantitative &&
          parsed.colorField &&
          prepared.data?.values
        ) {
          prepared = {
            ...prepared,
            data: {
              values: prepared.data.values.filter(
                (r) => activeGroups.has(String(r[parsed.colorField!]))
              ),
            },
          };
        }

        // Apply active color scale (categorical palette only; keep Vega sequential scale for choropleths)
        if (
          !isChoroplethQuantitative &&
          prepared.encoding?.color &&
          parsed.colorField
        ) {
          const activeDomain = parsed.distinctGroups.filter((g) => activeGroups.has(g));
          prepared.encoding.color.scale = {
            domain: activeDomain,
            range: activeDomain.map((g) => parsed.colorMap[g]),
          };
        }

        try {
          vegaViewRef.current?.finalize();
        } catch {
          /* ignore */
        }

        const embedCommon = { actions: false, renderer: "svg" as const };
        const host = chartRef.current;

        if (isChoroplethQuantitative) {
          const plotWidth =
            typeof prepared.width === "number" && Number.isFinite(prepared.width)
              ? prepared.width
              : 600;
          const plotHeight =
            typeof prepared.height === "number" && Number.isFinite(prepared.height)
              ? prepared.height
              : choroplethVegaHeight;
          const stripDesired = choroplethLegendVerticalReservePx(mapSlotWidth);
          /** Same cap as ``choroplethMapFacetHeightPx`` — must stay aligned with ``plotHeight`` / ``prepareSpec``. */
          const mapFacetMin = choroplethMapFacetHeightPx(mapSlotWidth);
          const legendStripPx = Math.min(
            stripDesired,
            Math.max(80, plotHeight - mapFacetMin - 8),
          );
          const compiled = vl.compile(prepared as Parameters<typeof vl.compile>[0])
            .spec as Record<string, unknown>;
          const vegaSpec = {
            ...patchVegaSpecChoroplethMapGroupClip(
              patchVegaSpecChoroplethWheelZoom(compiled, {
                plotWidth,
                plotHeight,
                legendStripPx,
              }),
            ),
            /**
             * ``fit`` + ``resize`` reflows layout when zoom/pan signals update → stutter and a
             * jumping legend. ``none`` keeps width/height fixed; the slot clips overflow.
             */
            autosize: "none" as const,
          };
          embed(host, vegaSpec as never, embedCommon)
            .then((result) => {
              if (cancelled) {
                result.finalize();
                return;
              }
              applyChoroplethEmbedDomStyles(host);
              vegaViewRef.current = result.view as typeof vegaViewRef.current;
              detachChoropleth?.();
              detachChoropleth = attachChoroplethMapInteractions(host, result.view);
            })
            .catch(console.error);
        } else {
          embed(host, prepared as never, embedCommon)
            .then((result) => {
              if (cancelled) {
                result.finalize();
                return;
              }
              vegaViewRef.current = result.view as typeof vegaViewRef.current;
            })
            .catch(console.error);
        }
      },
    );

    return () => {
      cancelled = true;
      detachChoropleth?.();
      detachChoropleth = undefined;
      try {
        vegaViewRef.current?.finalize();
      } catch {
        /* ignore */
      }
    };
  }, [
    spec,
    activeGroups,
    chartHeight,
    parsed,
    isChoroplethQuantitative,
    mapSlotWidth,
    choroplethVegaHeight,
  ]);

  // ── Handlers ────────────────────────────────────────────────────────────────

  const handleDownload = useCallback(() => {
    const rows = isChoroplethQuantitative
      ? parsed.rows
      : parsed.rows.filter(
          (r) =>
            !parsed.colorField ||
            activeGroups.has(String(r[parsed.colorField])),
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
  }, [parsed, activeGroups, onDownload, isChoroplethQuantitative]);

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
    /** Without this, ``alignItems: stretch`` on the row makes the card as tall as the rail → huge blank band. */
    alignSelf: "flex-start",
    minWidth: 0,
    width: "100%",
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

    /** Choropleth specs use a fixed pixel width (~600); the embed SVG stays centered with empty
   *  gutter unless the chart slot matches. A grey slot background reads as a rectangular “frame”
   *  around the white map — match the spec background instead. Other charts keep the subtle grey. */
  const chartArea: CSSProperties = {
    background: isChoroplethQuantitative ? "#ffffff" : "rgba(0,0,0,0.03)",
    borderRadius: 8,
    margin: "14px 0 0",
    width: "100%",
    minWidth: 0,
    /**
     * Choropleth: host clips the rounded slot; **map paths** clip inside Vega via
     * ``patchVegaSpecChoroplethMapGroupClip``. Do not use ``contain: paint`` / ``clip-path`` here
     * — they clip the legend.
     */
    overflow: "hidden",
    ...(isChoroplethQuantitative
      ? {
          position: "relative" as const,
          height: "auto",
          /** Slot hugs SVG height; small floor avoids layout flash before embed (not ``choroplethSpecHeight``). */
          minHeight: chartHeight,
          touchAction: "none" as const,
          /** Extra gap below SVG before Source (margins with Source collapse to the larger side). */
          marginBottom: source ? 36 : 14,
        }
      : { minHeight: chartHeight }),
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
        <div
          ref={chartRef}
          style={chartArea}
          title={
            isChoroplethQuantitative
              ? "Scroll to zoom. Drag to pan. Double-click to reset."
              : undefined
          }
        />

        {/* Interactive legend (categorical series only) */}
        {parsed.distinctGroups.length > 0 && !isChoroplethQuantitative && (
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

        {/* Source — choropleth: clear gap below Vega gradient/tick labels (avoids cramped legend ↔ Source). */}
        {source && (
          <p
            style={{
              fontSize: 12,
              color: "#999999",
              marginTop: isChoroplethQuantitative ? 58 : 12,
            }}
          >
            <strong style={{ fontWeight: 600, color: "#666666" }}>Source:</strong> {source}
          </p>
        )}

        {isChoroplethQuantitative && !hideChartUiRevision ? (
          <div
            data-chart-card-export-skip=""
            data-data360-chart-ui-revision={DATA360_CHART_UI_REVISION}
            style={{
              fontSize: 11,
              color: "#94a3b8",
              marginTop: 8,
              marginBottom: 0,
              letterSpacing: "0.02em",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
            }}
            title="Confirms this page loaded the Data360 chart-card bundle at this revision. Hidden from Save as PNG."
          >
            Data360 map UI · {DATA360_CHART_UI_REVISION}
          </div>
        ) : null}

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
