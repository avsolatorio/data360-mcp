import { useState, useRef } from "react";
import type { ChoiceCardProps } from "./types";

export default function ChoiceCard({
  payload,
  onSelect,
  theme = "light",
  className = "",
}: ChoiceCardProps) {
  const { prompt, options } = payload;
  const [specifyIndex, setSpecifyIndex] = useState<number | null>(null);
  const [specifyValue, setSpecifyValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const isDark = theme === "dark";

  const wrapperStyle: React.CSSProperties = {
    padding: "8px 12px",
    fontFamily:
      '"Noto Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  };

  const promptStyle: React.CSSProperties = {
    fontSize: "1.05rem",
    fontWeight: 500,
    marginBottom: "16px",
    color: isDark ? "#cbd5e1" : "#0f172a",
    lineHeight: 1.4,
  };

  const containerStyle: React.CSSProperties = {
    display: "flex",
    gap: "12px",
    flexWrap: "wrap",
  };

  const btnStyle = (active: boolean): React.CSSProperties => ({
    flex: "1 1 calc(33.333% - 8px)",
    minWidth: "160px",
    padding: "14px 18px",
    background: isDark ? "#1e293b" : "#f1f5f9",
    border: "1px solid transparent",
    borderRadius: "1.25rem",
    color: isDark ? "#cbd5e1" : "#0f172a",
    fontSize: "0.95rem",
    fontWeight: 500,
    fontFamily: "inherit",
    cursor: active ? "default" : "pointer",
    textAlign: "left",
    display: "flex",
    flexDirection: "column",
    justifyContent: "space-between",
    transition: "background 0.15s",
    opacity: specifyIndex !== null && !active ? 0.35 : 1,
  });

  const arrowStyle: React.CSSProperties = {
    marginTop: "12px",
    fontSize: "1.1rem",
    color: isDark ? "#94a3b8" : "#64748b",
  };

  const isSpecifyOption = (opt: string) => {
    const l = opt.toLowerCase();
    return (
      l.includes("specify") ||
      l.includes("other") ||
      l.includes("custom") ||
      l.includes("enter") ||
      opt.endsWith("...")
    );
  };

  const handleClick = (opt: string, idx: number) => {
    if (specifyIndex !== null) return;
    if (isSpecifyOption(opt)) {
      setSpecifyIndex(idx);
      setSpecifyValue("");
      setTimeout(() => inputRef.current?.focus(), 10);
    } else {
      onSelect(opt);
    }
  };

  const handleSpecifySubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const val = specifyValue.trim();
    if (val) onSelect(val);
  };

  return (
    <div style={wrapperStyle} className={className}>
      {prompt && <p style={promptStyle}>{prompt}</p>}
      <div style={containerStyle}>
        {options.map((opt, idx) => {
          const isActive = specifyIndex === idx;
          return (
            <button
              key={idx}
              style={btnStyle(isActive)}
              disabled={specifyIndex !== null && !isActive}
              onClick={() => handleClick(opt, idx)}
              type="button"
            >
              {isActive ? (
                <form
                  onSubmit={handleSpecifySubmit}
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    display: "flex",
                    gap: "8px",
                    alignItems: "center",
                    width: "100%",
                  }}
                >
                  <input
                    ref={inputRef}
                    type="text"
                    value={specifyValue}
                    onChange={(e) => setSpecifyValue(e.target.value)}
                    placeholder="Type here..."
                    required
                    onKeyDown={(e) => {
                      if (e.key === "Escape") {
                        e.preventDefault();
                        setSpecifyIndex(null);
                      }
                    }}
                    style={{
                      flex: 1,
                      border: "none",
                      background: "transparent",
                      outline: "none",
                      fontSize: "0.9rem",
                      color: "inherit",
                      fontFamily: "inherit",
                    }}
                  />
                  <button
                    type="submit"
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      fontSize: "1.1rem",
                      color: "inherit",
                    }}
                  >
                    ↪
                  </button>
                </form>
              ) : (
                <>
                  <span>{opt}</span>
                  <span style={arrowStyle}>↪</span>
                </>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
