import { memo, useState, useCallback, useEffect, type CSSProperties } from "react";
import type { EnrichedIndicator, QueryGroupResult, SearchResultCardProps } from "./types";

// ─── Design tokens (WB palette) ───────────────────────────────────────────────

const FONT = "Open Sans, Arial, sans-serif";
const COLOR_TEXT_PRIMARY = "#111111";
const COLOR_TEXT_SECONDARY = "#555555";
const COLOR_TEXT_MUTED = "#999999";
const COLOR_BORDER = "rgba(0,0,0,0.10)";
const COLOR_SURFACE = "transparent";
const COLOR_CARD_BG = "#ffffff";
const COLOR_CARD_HOVER_BORDER = "#4a90e2";
const COLOR_CARD_HOVER_SHADOW = "0 4px 16px rgba(74,144,226,0.18)";
const COLOR_SUCCESS = "#2E7D32";
const COLOR_MISSING = "#B71C1C";
const COLOR_MISSING_BG = "rgba(183, 28, 28, 0.08)";
const COLOR_ACCENT = "#4a90e2";
const COLOR_BADGE_BG = "rgba(74, 144, 226, 0.08)";
const COLOR_GROUP_HEADER_BG = "rgba(74, 144, 226, 0.04)";

// ─── Small pills ───────────────────────────────────────────────────────────────

function MetaPill({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "1px 7px",
        borderRadius: 999,
        background: COLOR_BADGE_BG,
        color: COLOR_ACCENT,
        fontSize: 10,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

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

// ─── Indicator card (horizontal rail item) ─────────────────────────────────────

const CARD_WIDTH = 240;
const CARD_MIN_HEIGHT = 170;

const IndicatorCard = memo(function IndicatorCard({
  indicator,
  onSelect,
}: {
  indicator: EnrichedIndicator;
  onSelect?: (i: EnrichedIndicator) => void;
}) {
  const [hover, setHover] = useState(false);
  const clickable = Boolean(onSelect);

  const handleClick = useCallback(() => onSelect?.(indicator), [indicator, onSelect]);
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (clickable && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        onSelect?.(indicator);
      }
    },
    [indicator, clickable, onSelect]
  );

  const cardStyle: CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: 6,
    width: CARD_WIDTH,
    minWidth: CARD_WIDTH,
    minHeight: CARD_MIN_HEIGHT,
    padding: "14px 14px 12px",
    borderRadius: 10,
    background: COLOR_CARD_BG,
    border: `1px solid ${hover && clickable ? COLOR_CARD_HOVER_BORDER : COLOR_BORDER}`,
    boxShadow: hover && clickable ? COLOR_CARD_HOVER_SHADOW : "0 1px 3px rgba(0,0,0,0.06)",
    cursor: clickable ? "pointer" : "default",
    transition: "border-color 0.14s, box-shadow 0.14s",
    boxSizing: "border-box",
    flexShrink: 0,
    fontFamily: "Open Sans, Arial, sans-serif",
  };

  let prefix = null;
  if (indicator.covers_country != null) {
    const entries = Object.entries(indicator.covers_country);
    if (entries.length > 0) {
      const allCovered = entries.every(([, ok]) => ok);
      if (allCovered) {
        prefix = <span style={{ color: COLOR_SUCCESS, marginRight: 4 }}>✓</span>;
      } else {
        prefix = <span style={{ color: COLOR_MISSING, marginRight: 4, fontWeight: 900 }}>−</span>;
      }
    }
  }

  return (
    <div
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      aria-label={clickable ? `Select: ${indicator.name}` : undefined}
      style={cardStyle}
      onClick={clickable ? handleClick : undefined}
      onKeyDown={clickable ? handleKeyDown : undefined}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {/* Indicator name */}
      <div
        style={{
          fontSize: 13,
          fontWeight: 700,
          color: hover && clickable ? COLOR_ACCENT : COLOR_TEXT_PRIMARY,
          lineHeight: 1.4,
          transition: "color 0.12s",
          // clamp to 3 lines
          display: "-webkit-box",
          WebkitLineClamp: 3,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
      >
        {prefix}
        {indicator.name}
      </div>

      {/* Indicator ID */}
      <div
        style={{
          fontSize: 10,
          color: COLOR_TEXT_MUTED,
          fontFamily: "ui-monospace, monospace",
          marginTop: -2,
        }}
      >
        {indicator.idno}
      </div>

      {/* Definition — clamped to 2 lines */}
      {indicator.truncated_definition && (
        <div
          style={{
            fontSize: 11,
            color: COLOR_TEXT_SECONDARY,
            lineHeight: 1.5,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
            flex: 1,
            marginTop: 2,
          }}
        >
          {indicator.truncated_definition}
        </div>
      )}

      {/* Meta pills row */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: "auto" }}>
        {indicator.periodicity && <MetaPill>{indicator.periodicity}</MetaPill>}
        {indicator.time_period_range && <MetaPill>{indicator.time_period_range}</MetaPill>}
      </div>

      {/* DB footer */}
      <div
        style={{
          fontSize: 9,
          color: COLOR_TEXT_MUTED,
          fontFamily: "ui-monospace, monospace",
          marginTop: 2,
          lineHeight: 1.3,
          wordBreak: "break-word",
        }}
      >
        {indicator.database_name
          ? `${indicator.database_name} · ${indicator.database_id}`
          : indicator.database_id}
      </div>
    </div>
  );
});

// ─── Horizontal rail ───────────────────────────────────────────────────────────

function IndicatorRail({
  indicators,
  onSelect,
  emptyMessage = "No indicators found.",
}: {
  indicators: EnrichedIndicator[];
  onSelect?: (i: EnrichedIndicator) => void;
  emptyMessage?: string;
}) {
  if (indicators.length === 0) {
    return (
      <p
        style={{
          padding: "14px 16px",
          fontSize: 13,
          color: COLOR_TEXT_MUTED,
          margin: 0,
        }}
      >
        {emptyMessage}
      </p>
    );
  }

  return (
    <div
      role="list"
      style={{
        display: "flex",
        flexDirection: "row",
        gap: 12,
        padding: "14px 16px",
        overflowX: "auto",
        // subtle scrollbar styling
        scrollbarWidth: "thin",
        scrollbarColor: `${COLOR_BORDER} transparent`,
      }}
    >
      {indicators.map((ind) => (
        <div key={ind.idno} role="listitem">
          <IndicatorCard indicator={ind} onSelect={onSelect} />
        </div>
      ))}
    </div>
  );
}

// ─── Group accordion header ────────────────────────────────────────────────────

function GroupHeader({
  group,
  open,
  onToggle,
  countryName,
}: {
  group: QueryGroupResult;
  open: boolean;
  onToggle: () => void;
  countryName?: string;
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
        background: hover ? "rgba(74,144,226,0.08)" : COLOR_GROUP_HEADER_BG,
        border: "none",
        borderBottom: open ? `0.5px solid ${COLOR_BORDER}` : "none",
        cursor: "pointer",
        fontFamily: FONT,
        textAlign: "left",
        transition: "background 0.12s",
      }}
    >
      {/* Animated chevron */}
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

      {/* Country pill */}
      {(countryName || group.country_code) && (
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            color: COLOR_ACCENT,
            background: COLOR_BADGE_BG,
            padding: "2px 8px",
            borderRadius: 999,
            flexShrink: 0,
            whiteSpace: "nowrap",
          }}
        >
          {countryName ?? group.country_code}
        </span>
      )}

      {/* Result count */}
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
  // All groups open by default; re-init when groups identity changes.
  const [openGroups, setOpenGroups] = useState<Set<number>>(
    () => new Set(groups?.map((_, i) => i) ?? [])
  );

  useEffect(() => {
    setOpenGroups(new Set(groups?.map((_, i) => i) ?? []));
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

  const isGrouped = Boolean(groups && groups.length > 0);
  const totalCount = isGrouped
    ? groups!.reduce((s, g) => s + g.count, 0)
    : indicators.length;

  const card: CSSProperties = {
    background: COLOR_SURFACE,
    border: `0.5px solid ${COLOR_BORDER}`,
    borderRadius: 12,
    fontFamily: FONT,
    overflow: "hidden",
    width: "100%",
  };

  return (
    <div className={className} style={card}>
      {/* ── Card header ─────────────────────────────────────────────── */}
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
        <p style={{ fontSize: 11, color: COLOR_TEXT_MUTED, marginTop: 5, marginBottom: 0 }}>
          {totalCount} indicator{totalCount !== 1 ? "s" : ""}
          {onSelect ? " · click a card to select" : ""}
        </p>
      </div>

      <Divider />

      {/* ── Body ────────────────────────────────────────────────────── */}
      {isGrouped ? (
        // by_query grouped view — accordion per query/country
        <div role="list">
          {groups!.map((group, idx) => (
            <div key={`${group.query}-${group.country_code ?? idx}`} role="listitem">
              <GroupHeader
                group={group}
                open={openGroups.has(idx)}
                onToggle={() => toggleGroup(idx)}
                countryName={(group as QueryGroupResult & { country_name?: string }).country_name}
              />
              {openGroups.has(idx) && (
                <>
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
                  ) : (
                    <IndicatorRail indicators={group.indicators} onSelect={onSelect} />
                  )}
                </>
              )}
              <Divider />
            </div>
          ))}
        </div>
      ) : (
        // merged / single-query view — flat horizontal rail
        <IndicatorRail indicators={indicators} onSelect={onSelect} />
      )}
    </div>
  );
}
