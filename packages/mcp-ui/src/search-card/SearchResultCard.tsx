import { memo, useState, useCallback, useEffect, type CSSProperties } from "react";
import type { EnrichedIndicator, QueryGroupResult, SearchResultCardProps } from "./types";

// ─── Design tokens (WB palette, consistent with VegaChartCard) ───────────────

const FONT = "Open Sans, Arial, sans-serif";
const COLOR_TEXT_PRIMARY = "#111111";
const COLOR_TEXT_SECONDARY = "#666666";
const COLOR_TEXT_MUTED = "#999999";
const COLOR_BORDER = "rgba(0,0,0,0.12)";
const COLOR_SURFACE = "#ffffff";
const COLOR_HOVER = "rgba(0,0,0,0.03)";
const COLOR_SUCCESS = "#2E7D32";
const COLOR_MISSING = "#B71C1C";
const COLOR_ACCENT = "#34A7F2";
const COLOR_BADGE_BG = "rgba(52,167,242,0.08)";

// ─── Sub-components ────────────────────────────────────────────────────────────

function Divider() {
  return (
    <hr
      style={{
        border: "none",
        borderTop: `0.5px solid ${COLOR_BORDER}`,
        margin: "0",
      }}
    />
  );
}

/** Green check or red dash for country coverage. */
function CoverageBadge({ covers }: { covers: boolean | null | undefined }) {
  if (covers === null || covers === undefined) return null;
  return (
    <span
      aria-label={covers ? "Has data for requested country" : "No data for requested country"}
      title={covers ? "Has data for requested country" : "No data for requested country"}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 18,
        height: 18,
        borderRadius: "50%",
        background: covers ? "rgba(46,125,50,0.1)" : "rgba(183,28,28,0.1)",
        color: covers ? COLOR_SUCCESS : COLOR_MISSING,
        fontSize: 11,
        fontWeight: 700,
        flexShrink: 0,
      }}
    >
      {covers ? "✓" : "–"}
    </span>
  );
}

/** Small pill for periodicity, date range, etc. */
function MetaPill({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "1px 7px",
        borderRadius: 999,
        background: COLOR_BADGE_BG,
        color: COLOR_ACCENT,
        fontSize: 11,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

/** Small pill for each dimension (SEX, AGE, etc.). */
function DimPill({ label }: { label: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "1px 7px",
        borderRadius: 999,
        border: `0.5px solid ${COLOR_BORDER}`,
        color: COLOR_TEXT_SECONDARY,
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: "0.04em",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

// ─── Single indicator row ──────────────────────────────────────────────────────

const IndicatorRow = memo(function IndicatorRow({
  indicator,
  onSelect,
}: {
  indicator: EnrichedIndicator;
  onSelect?: (i: EnrichedIndicator) => void;
}) {
  const [hover, setHover] = useState(false);
  const clickable = Boolean(onSelect);

  const rowStyle: CSSProperties = {
    display: "flex",
    alignItems: "flex-start",
    gap: 12,
    padding: "12px 16px",
    cursor: clickable ? "pointer" : "default",
    background: hover && clickable ? COLOR_HOVER : COLOR_SURFACE,
    transition: "background 0.12s",
  };

  const handleClick = useCallback(() => {
    onSelect?.(indicator);
  }, [indicator, onSelect]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (clickable && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        onSelect?.(indicator);
      }
    },
    [indicator, clickable, onSelect]
  );

  return (
    <div
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      aria-label={clickable ? `Select indicator: ${indicator.name}` : undefined}
      style={rowStyle}
      onClick={clickable ? handleClick : undefined}
      onKeyDown={clickable ? handleKeyDown : undefined}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {/* Coverage badge */}
      <div style={{ paddingTop: 2, flexShrink: 0 }}>
        <CoverageBadge covers={indicator.covers_country} />
      </div>

      {/* Main content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Name row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: clickable && hover ? COLOR_ACCENT : COLOR_TEXT_PRIMARY,
              transition: "color 0.12s",
              lineHeight: 1.4,
            }}
          >
            {indicator.name}
          </span>
          {indicator.periodicity && <MetaPill>{indicator.periodicity}</MetaPill>}
          {indicator.time_period_range && (
            <MetaPill>{indicator.time_period_range}</MetaPill>
          )}
        </div>

        {/* Definition */}
        <p
          style={{
            fontSize: 13,
            color: COLOR_TEXT_SECONDARY,
            lineHeight: 1.6,
            margin: "3px 0 6px",
          }}
        >
          {indicator.truncated_definition}
        </p>

        {/* Bottom meta row: ID + dims */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span
            style={{
              fontSize: 11,
              color: COLOR_TEXT_MUTED,
              fontFamily: "ui-monospace, monospace",
            }}
          >
            {indicator.database_name
              ? `${indicator.database_name} (${indicator.database_id})`
              : indicator.database_id} · {indicator.idno}
          </span>
          {indicator.dimensions?.map((d: string) => (
            <DimPill key={d} label={d} />
          ))}
        </div>
      </div>

      {/* Chevron affordance when clickable */}
      {clickable && (
        <span
          aria-hidden
          style={{
            color: hover ? COLOR_ACCENT : COLOR_BORDER,
            fontSize: 16,
            flexShrink: 0,
            paddingTop: 1,
            transition: "color 0.12s",
          }}
        >
          ›
        </span>
      )}
    </div>
  );
});

// ─── Group accordion header ────────────────────────────────────────────────────

function GroupHeader({
  group,
  open,
  onToggle,
}: {
  group: QueryGroupResult;
  open: boolean;
  onToggle: () => void;
}) {
  const [hover, setHover] = useState(false);

  return (
    <button
      type="button"
      aria-expanded={open}
      onClick={onToggle}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: "10px 16px",
        background: hover ? COLOR_HOVER : "rgba(0,0,0,0.015)",
        border: "none",
        borderBottom: open ? `0.5px solid ${COLOR_BORDER}` : "none",
        cursor: "pointer",
        fontFamily: FONT,
        textAlign: "left",
        transition: "background 0.12s",
      }}
    >
      {/* Chevron */}
      <span
        aria-hidden
        style={{
          color: COLOR_TEXT_SECONDARY,
          fontSize: 13,
          transition: "transform 0.15s",
          transform: open ? "rotate(90deg)" : "rotate(0deg)",
          display: "inline-block",
          flexShrink: 0,
        }}
      >
        ›
      </span>

      {/* Query label */}
      <span
        style={{
          fontSize: 13,
          fontWeight: 600,
          color: COLOR_TEXT_PRIMARY,
          flex: 1,
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {group.query}
      </span>

      {/* Country badge */}
      {group.country_code && (
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: COLOR_ACCENT,
            background: COLOR_BADGE_BG,
            padding: "2px 8px",
            borderRadius: 999,
            flexShrink: 0,
          }}
        >
          {group.country_code}
        </span>
      )}

      {/* Count badge */}
      <span
        style={{
          fontSize: 11,
          color: COLOR_TEXT_MUTED,
          flexShrink: 0,
        }}
      >
        {group.count} result{group.count !== 1 ? "s" : ""}
      </span>
    </button>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────

export default function SearchResultCard({
  indicators = [],
  groups,
  title = "Search Results",
  subtitle,
  onSelect,
  className,
}: SearchResultCardProps) {
  // Track which groups are expanded (all open by default).
  // Reset when the group array changes identity (e.g. parent re-renders with new groups).
  const [openGroups, setOpenGroups] = useState<Set<number>>(
    () => new Set(groups?.map((_, i) => i) ?? [])
  );

  useEffect(() => {
    setOpenGroups(new Set(groups?.map((_, i) => i) ?? []));
    // Re-initialise only when the number of groups or their queries change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups?.length, groups?.map((g) => g.query).join(",")]);

  const toggleGroup = useCallback((index: number) => {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }, []);

  const card: CSSProperties = {
    background: COLOR_SURFACE,
    border: `0.5px solid ${COLOR_BORDER}`,
    borderRadius: 12,
    fontFamily: FONT,
    overflow: "hidden",
    width: "100%",
  };

  const isGrouped = groups && groups.length > 0;
  const totalCount = isGrouped
    ? groups.reduce((s, g) => s + g.count, 0)
    : indicators.length;

  return (
    <div className={className} style={card}>
      {/* Card header */}
      <div style={{ padding: "16px 16px 12px" }}>
        <h2
          style={{
            fontSize: 18,
            fontWeight: 600,
            color: COLOR_TEXT_PRIMARY,
            margin: 0,
            lineHeight: 1.3,
          }}
        >
          {title}
        </h2>
        {subtitle && (
          <p style={{ fontSize: 14, color: COLOR_TEXT_SECONDARY, marginTop: 4, marginBottom: 0 }}>
            {subtitle}
          </p>
        )}
        <p style={{ fontSize: 12, color: COLOR_TEXT_MUTED, marginTop: 6, marginBottom: 0 }}>
          {totalCount} indicator{totalCount !== 1 ? "s" : ""}
          {onSelect ? " — click a row to select" : ""}
        </p>
      </div>

      <Divider />

      {/* Body */}
      {isGrouped ? (
        // ── By-query grouped view ──
        <div role="list">
          {groups.map((group) => (
            <div key={group.query} role="listitem">
              <GroupHeader
                group={group}
                open={openGroups.has(groups.indexOf(group))}
                onToggle={() => toggleGroup(groups.indexOf(group))}
              />
              {openGroups.has(groups.indexOf(group)) && (
                <div role="list">
                  {group.error ? (
                    <p
                      style={{
                        padding: "10px 16px",
                        fontSize: 13,
                        color: COLOR_MISSING,
                        margin: 0,
                      }}
                    >
                      {group.error}
                    </p>
                  ) : group.indicators.length === 0 ? (
                    <p
                      style={{
                        padding: "10px 16px",
                        fontSize: 13,
                        color: COLOR_TEXT_MUTED,
                        margin: 0,
                      }}
                    >
                      No indicators found.
                    </p>
                  ) : (
                    group.indicators.map((ind: EnrichedIndicator, j: number) => (
                      <div key={ind.idno} role="listitem">
                        <IndicatorRow indicator={ind} onSelect={onSelect} />
                        {j < group.indicators.length - 1 && <Divider />}
                      </div>
                    ))
                  )}
                </div>
              )}
              <Divider />
            </div>
          ))}
        </div>
      ) : (
        // ── Merged flat view ──
        <div role="list">
          {indicators.length === 0 ? (
            <p
              style={{
                padding: "16px",
                fontSize: 13,
                color: COLOR_TEXT_MUTED,
                margin: 0,
              }}
            >
              No indicators found.
            </p>
          ) : (
            indicators.map((ind, i) => (
              <div key={ind.idno} role="listitem">
                <IndicatorRow indicator={ind} onSelect={onSelect} />
                {i < indicators.length - 1 && <Divider />}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
