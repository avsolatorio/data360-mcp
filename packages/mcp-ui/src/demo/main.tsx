import React, { type CSSProperties, useMemo, useState } from "react";
import ReactDOM from "react-dom/client";
import type { Schema } from "hast-util-sanitize";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import type { PluggableList } from "unified";

import type { VLSpec } from "@data360/mcp-viz-core";
import { VegaChartCard } from "../viz-card";

type ToolCall = {
  tool_name: string;
  tool_args: Record<string, unknown>;
  tool_result: unknown;
};

type VizCardMeta = {
  subtitle?: string;
  source?: string;
  annotations?: Array<{ id: number; text: string }>;
};

const DATA360_CHART_SOURCE_FALLBACK = "World Bank Data360";

function firstNonEmptyString(values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (trimmed.length > 0) {
        return trimmed;
      }
    }
  }
  return undefined;
}

function formatData360VizSourceLine(raw: Record<string, unknown>): string {
  const serverLine = firstNonEmptyString([raw.source_line, raw.source]);
  if (serverLine) {
    return serverLine;
  }

  const database = firstNonEmptyString([raw.database_name, raw.database_id]);
  const indicator = firstNonEmptyString([raw.indicator_name, raw.indicator_id]);
  const parts = ["World Bank"];
  if (database) {
    parts.push(database);
  }
  if (indicator) {
    parts.push(indicator);
  }
  return parts.length > 1 ? parts.join(" — ") : DATA360_CHART_SOURCE_FALLBACK;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function flattenCandidateRecords(value: unknown): Record<string, unknown>[] {
  const direct = asRecord(value);
  if (direct) {
    const nested = [
      direct.data,
      direct.result,
      direct.output,
      direct.payload,
      direct.response,
    ];
    return [direct, ...nested.flatMap((item) => flattenCandidateRecords(item))];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => flattenCandidateRecords(item));
  }
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value) as unknown;
      return flattenCandidateRecords(parsed);
    } catch {
      return [];
    }
  }
  return [];
}

function findVizResultRecord(call: ToolCall): Record<string, unknown> | null {
  const candidates = flattenCandidateRecords(call.tool_result);
  const withUrl = candidates.find((rec) => {
    const maybeUrl = rec.url;
    return typeof maybeUrl === "string" && maybeUrl.includes("_vega.json");
  });
  if (withUrl) {
    return withUrl;
  }
  return candidates[0] ?? null;
}

function formatData360VizSubtitleLine(
  raw: Record<string, unknown>
): string | undefined {
  const serverLine = firstNonEmptyString([raw.subtitle_line, raw.subtitle]);
  if (serverLine) {
    return serverLine;
  }
  const warning = firstNonEmptyString([raw.warning]);
  const strategy = firstNonEmptyString([raw.strategy]);
  const reason = firstNonEmptyString([raw.reason]);
  if (!warning && !strategy && !reason) {
    return undefined;
  }
  const lead = [warning, strategy].filter(Boolean).join(" · ");
  return reason ? `${lead} — ${reason}` : lead;
}

type K360Envelope = {
  gate: Record<string, unknown>;
  rewrite: Record<string, unknown>;
  tool_calls: ToolCall[];
  content_packet: Record<string, unknown>;
  narrative: string;
  error?: string | null;
  error_type?: string | null;
  error_details?: string | null;
};

type StageEvent = {
  type: "stage";
  stage: string;
  status: string;
  details?: Record<string, unknown>;
};

type NarrativeChunkEvent = {
  type: "narrative_chunk";
  chunk: string;
};

function stageEventKey(evt: StageEvent): string {
  if (evt.stage === "tool_call") {
    const toolName = evt.details?.tool_name;
    if (typeof toolName === "string" && toolName.trim().length > 0) {
      return `tool_call:${toolName}`;
    }
  }
  return evt.stage;
}

function mergeStageEvent(prev: StageEvent, next: StageEvent): StageEvent {
  return {
    ...prev,
    ...next,
    details: {
      ...(prev.details ?? {}),
      ...(next.details ?? {}),
    },
  };
}

const STAGE_LABELS: Record<string, string> = {
  gate: "Gate",
  rewrite: "Rewrite",
  compile: "Compile",
  narrative: "Narrative",
  tool_call: "Tool Call",
};

const SAMPLE_PROMPTS = [
  "Latest GDP growth in Vietnam.",
  "Compare GDP per capita in Kenya, Tanzania, and Uganda.",
  "How has maternal mortality in Rwanda changed from 2000 to 2020?",
  "What are the main challenges facing Ghana's economic growth and public spending?",
];

const PANEL: CSSProperties = {
  background: "#fff",
  border: "1px solid #d9e0ea",
  borderRadius: 12,
  padding: 16,
  boxShadow: "0 4px 10px rgba(20, 32, 51, 0.04)",
};

function extractVizUrl(toolCalls: ToolCall[]): string | null {
  for (const call of toolCalls) {
    const raw = call.tool_result;
    if (raw && typeof raw === "object" && "url" in raw) {
      const maybe = (raw as { url?: unknown }).url;
      if (typeof maybe === "string" && maybe.includes("_vega.json")) {
        return maybe;
      }
    }
  }
  return null;
}

function extractVizMeta(toolCalls: ToolCall[]): VizCardMeta {
  for (const call of toolCalls) {
    const isVizTool =
      call.tool_name === "data360_get_viz_spec" ||
      call.tool_name === "data360_get_multi_indicator_viz_spec";
    const obj = findVizResultRecord(call);
    if (!obj) continue;
    const maybeUrl = obj.url;
    const hasVizUrl =
      typeof maybeUrl === "string" && maybeUrl.includes("_vega.json");
    if (!isVizTool && !hasVizUrl) {
      continue;
    }
    const mergedForAttribution: Record<string, unknown> = {
      ...call.tool_args,
      ...obj,
    };
    const subtitle = formatData360VizSubtitleLine(mergedForAttribution);
    const source = formatData360VizSourceLine(mergedForAttribution);
    const annotationsRaw = obj.annotations;
    const annotations = Array.isArray(annotationsRaw)
      ? annotationsRaw
          .map((item, idx) => {
            if (!item || typeof item !== "object") return null;
            const rec = item as Record<string, unknown>;
            const text = typeof rec.text === "string" ? rec.text : undefined;
            if (!text) return null;
            const idVal = rec.id;
            const id =
              typeof idVal === "number" && Number.isFinite(idVal)
                ? idVal
                : idx + 1;
            return { id, text };
          })
          .filter((v): v is { id: number; text: string } => v !== null)
      : undefined;
    if (subtitle || source || (annotations && annotations.length > 0)) {
      return { subtitle, source, annotations };
    }
  }
  return {};
}

/** Legacy demo: these list lines were rendered as subheadings. */
function preprocessK360NarrativeMarkdown(md: string): string {
  return md.replace(
    /^[ \t]*- (\*\*(?:Data|Analysis|Note|Sources):\*\*)(.*)$/gm,
    "### $1$2",
  );
}

const REHYPE_SANITIZE_SCHEMA: Schema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    a: [...(defaultSchema.attributes?.a ?? []), "target", "rel"],
  },
};

const REMARK_PLUGINS = [remarkGfm];
/** Tuple form so unified calls `use(rehypeSanitize, schema)` (not a bare transform). */
const REHYPE_PLUGINS: PluggableList = [[rehypeSanitize, REHYPE_SANITIZE_SCHEMA]];

const TABLE_BORDER = "1px solid #d9e0ea";

const RESPONSE_MARKDOWN_COMPONENTS: Components = {
  h1: ({ style, ...props }) => (
    <h1
      {...props}
      style={{ margin: "10px 0 6px", fontSize: 22, ...style }}
    />
  ),
  h2: ({ style, ...props }) => (
    <h2
      {...props}
      style={{ margin: "10px 0 6px", fontSize: 20, ...style }}
    />
  ),
  h3: ({ style, ...props }) => (
    <h3
      {...props}
      style={{ margin: "8px 0 4px", fontSize: 16, ...style }}
    />
  ),
  p: ({ style, ...props }) => (
    <p {...props} style={{ margin: "6px 0", ...style }} />
  ),
  ul: ({ style, ...props }) => (
    <ul {...props} style={{ margin: "6px 0", paddingLeft: 22, ...style }} />
  ),
  ol: ({ style, ...props }) => (
    <ol {...props} style={{ margin: "6px 0", paddingLeft: 22, ...style }} />
  ),
  li: ({ style, ...props }) => (
    <li {...props} style={{ margin: "2px 0", ...style }} />
  ),
  a: ({ style, ...props }) => (
    <a
      {...props}
      rel="noopener noreferrer"
      style={{ color: "#1d4ed8", ...style }}
      target="_blank"
    />
  ),
  table: ({ style, ...props }) => (
    <div style={{ overflowX: "auto", margin: "10px 0" }}>
      <table
        {...props}
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: 13,
          ...style,
        }}
      />
    </div>
  ),
  th: ({ style, ...props }) => (
    <th
      {...props}
      style={{
        border: TABLE_BORDER,
        background: "#f8fbff",
        textAlign: "left",
        padding: "6px 8px",
        fontWeight: 700,
        ...style,
      }}
    />
  ),
  td: ({ style, ...props }) => (
    <td
      {...props}
      style={{
        border: TABLE_BORDER,
        padding: "6px 8px",
        verticalAlign: "top",
        ...style,
      }}
    />
  ),
};

function extractSubtitleFromSpec(spec: VLSpec): string | undefined {
  const rawTitle = spec.title;
  if (!rawTitle || typeof rawTitle === "string") {
    return undefined;
  }
  const subtitle = (rawTitle as { subtitle?: unknown }).subtitle;
  if (typeof subtitle === "string") {
    const trimmed = subtitle.trim();
    return trimmed.length > 0 ? trimmed : undefined;
  }
  if (Array.isArray(subtitle)) {
    const parts = subtitle
      .map((item) => (typeof item === "string" ? item.trim() : ""))
      .filter((item) => item.length > 0);
    if (parts.length > 0) {
      return parts.join(" · ");
    }
  }
  return undefined;
}

function ResponseMarkdown({ content }: { content: string }) {
  const markdown = useMemo(
    () => preprocessK360NarrativeMarkdown(content),
    [content],
  );

  return (
    <div style={{ lineHeight: 1.6, color: "#183047" }}>
      <ReactMarkdown
        components={RESPONSE_MARKDOWN_COMPONENTS}
        rehypePlugins={REHYPE_PLUGINS}
        remarkPlugins={REMARK_PLUGINS}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

function App() {
  const [query, setQuery] = useState(SAMPLE_PROMPTS[0]);
  const [loading, setLoading] = useState(false);
  const [envelope, setEnvelope] = useState<K360Envelope | null>(null);
  const [vizSpec, setVizSpec] = useState<VLSpec | null>(null);
  const [vizMeta, setVizMeta] = useState<VizCardMeta>({});
  const [stageEvents, setStageEvents] = useState<StageEvent[]>([]);
  const [showToolDetails, setShowToolDetails] = useState(false);
  const [narrativeStreaming, setNarrativeStreaming] = useState(true);
  const [liveNarrative, setLiveNarrative] = useState("");
  const apiBase = useMemo(
    () =>
      (
        (globalThis as { __K360_API_BASE__?: string }).__K360_API_BASE__ ??
        "http://127.0.0.1:8844"
      ),
    []
  );

  const run = async () => {
    const text = query.trim();
    if (!text) return;
    setLoading(true);
    setEnvelope(null);
    setVizSpec(null);
    setVizMeta({});
    setStageEvents([]);
    setLiveNarrative("");
    try {
      const res = await fetch(`${apiBase}/api/k360-query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: text,
          show_tool_details: showToolDetails,
          narrative_streaming: narrativeStreaming,
        }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${await res.text()}`);
      }
      const reader = res.body?.getReader();
      if (!reader) {
        throw new Error("No stream body received");
      }
      const decoder = new TextDecoder();
      let buffer = "";
      let finalPayload: K360Envelope | null = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part
            .split("\n")
            .find((l) => l.startsWith("data: "));
          if (!line) continue;
          const raw = line.slice(6).trim();
          if (raw === "[DONE]") continue;
          const parsed = JSON.parse(raw) as
            | StageEvent
            | NarrativeChunkEvent
            | { type: "final"; payload: K360Envelope }
            | { type: "error"; message: string };
          if (parsed.type === "stage") {
            setStageEvents((prev) => {
              const nextKey = stageEventKey(parsed);
              const existingIndex = prev.findIndex(
                (evt) => stageEventKey(evt) === nextKey
              );
              if (existingIndex === -1) {
                return [...prev, parsed];
              }
              const updated = [...prev];
              updated[existingIndex] = mergeStageEvent(updated[existingIndex], parsed);
              return updated;
            });
          }
          if (parsed.type === "narrative_chunk") {
            setLiveNarrative((prev) => `${prev}${parsed.chunk}`);
          }
          if (parsed.type === "final") {
            finalPayload = parsed.payload;
          }
          if (parsed.type === "error") {
            throw new Error(parsed.message);
          }
        }
      }
      const out = finalPayload;
      if (!out) {
        throw new Error("Missing final payload from stream");
      }
      setEnvelope(out);
      const vizUrl = extractVizUrl(out.tool_calls ?? []);
      setVizMeta(extractVizMeta(out.tool_calls ?? []));
      if (vizUrl) {
        const specRes = await fetch(
          `${apiBase}/api/fetch-viz-spec?url=${encodeURIComponent(vizUrl)}`
        );
        if (specRes.ok) {
          const fetchedSpec = (await specRes.json()) as VLSpec;
          const specSubtitle = extractSubtitleFromSpec(fetchedSpec);
          if (specSubtitle) {
            setVizMeta((prev) => ({ ...prev, subtitle: prev.subtitle ?? specSubtitle }));
          }
          setVizSpec(fetchedSpec);
        }
      }
    } catch (err) {
      setEnvelope({
        gate: { relevant: false },
        rewrite: {},
        tool_calls: [],
        content_packet: {},
        narrative: "",
        error: String(err),
      });
      setVizMeta({});
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: 24, fontFamily: "Open Sans, Arial, sans-serif", color: "#142033" }}>
      <h1 style={{ margin: "0 0 8px" }}>K360 Data360 Interactive Demo</h1>
      <p style={{ marginTop: 0, color: "#4f647a" }}>
        Staged flow: Gate → Rewriter → Compile → Narrative
      </p>

      <div style={{ ...PANEL, marginBottom: 16 }}>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ width: "100%", minHeight: 88, borderRadius: 8, border: "1px solid #cad3df", padding: 10, fontSize: 14 }}
        />
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          <button type="button" onClick={run} disabled={loading} style={{ background: "#2f6feb", color: "#fff", border: "none", borderRadius: 8, padding: "8px 16px" }}>
            {loading ? "Running..." : "Run K360 Query"}
          </button>
          {SAMPLE_PROMPTS.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setQuery(item)}
              style={{ background: "#eef3ff", color: "#1d3a63", border: "1px solid #d3dffc", borderRadius: 8, padding: "6px 10px" }}
            >
              {item}
            </button>
          ))}
        </div>
        <label
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            marginTop: 10,
            fontSize: 13,
            color: "#274767",
          }}
        >
          <input
            type="checkbox"
            checked={showToolDetails}
            onChange={(e) => setShowToolDetails(e.target.checked)}
          />
          Show tool input/output details (default: off)
        </label>
        <label
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            marginTop: 8,
            fontSize: 13,
            color: "#274767",
          }}
        >
          <input
            type="checkbox"
            checked={narrativeStreaming}
            onChange={(e) => setNarrativeStreaming(e.target.checked)}
          />
          Stream narrative output (default: on)
        </label>
        {loading ? (
          <div
            style={{
              marginTop: 12,
              border: "1px solid #d9e0ea",
              borderRadius: 8,
              padding: 10,
              background: "#f8fbff",
            }}
          >
            <p style={{ margin: 0, fontWeight: 700, color: "#1d3a63" }}>
              Running agent stages...
            </p>
            <div style={{ marginTop: 8 }}>
              {stageEvents
                .filter((evt) => evt.stage !== "tool_call")
                .map((evt) => {
                const stageLabel = STAGE_LABELS[evt.stage] ?? evt.stage;
                const isComplete = evt.status === "completed";
                const badgeColor = isComplete ? "#166534" : "#92400e";
                const badgeBg = isComplete ? "#dcfce7" : "#fef3c7";
                return (
                  <div
                    key={stageEventKey(evt)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      border: "1px solid #d9e0ea",
                      borderRadius: 8,
                      padding: "8px 10px",
                      marginBottom: 6,
                      background: "#fff",
                    }}
                  >
                    <p style={{ margin: 0, fontSize: 13, color: "#1d3a63", fontWeight: 600 }}>
                      {stageLabel}
                      {evt.details?.tool_name ? ` · ${String(evt.details.tool_name)}` : ""}
                    </p>
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        color: badgeColor,
                        background: badgeBg,
                        borderRadius: 999,
                        padding: "2px 8px",
                      }}
                    >
                      {evt.status}
                    </span>
                  </div>
                );
              })}
            </div>
            {stageEvents.some((e) => e.stage === "tool_call") ? (
              <div style={{ marginTop: 10 }}>
                <p style={{ margin: "0 0 6px", fontWeight: 700, color: "#1d3a63" }}>
                  Tool Progress
                </p>
                {stageEvents
                  .filter((e) => e.stage === "tool_call")
                  .map((evt) => (
                    <div
                      key={stageEventKey(evt)}
                      style={{
                        border: "1px solid #d9e0ea",
                        borderRadius: 8,
                        padding: 8,
                        marginBottom: 6,
                        background: "#fff",
                      }}
                    >
                      <p style={{ margin: 0, fontSize: 12, fontWeight: 700 }}>
                        {String(evt.details?.tool_name ?? "tool")} — {evt.status}
                      </p>
                      {showToolDetails && evt.details?.tool_input ? (
                        <>
                          <p style={{ margin: "4px 0", fontSize: 11, color: "#3b556f" }}>
                            Input
                          </p>
                          <pre style={{ margin: 0, fontSize: 11, whiteSpace: "pre-wrap" }}>
                            {JSON.stringify(evt.details.tool_input, null, 2)}
                          </pre>
                        </>
                      ) : null}
                      {showToolDetails && evt.details?.tool_output ? (
                        <>
                          <p style={{ margin: "4px 0", fontSize: 11, color: "#3b556f" }}>
                            Output
                          </p>
                          <pre style={{ margin: 0, fontSize: 11, whiteSpace: "pre-wrap" }}>
                            {JSON.stringify(evt.details.tool_output, null, 2)}
                          </pre>
                        </>
                      ) : null}
                    </div>
                  ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {envelope && (
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16, alignItems: "start" }}>
          <div style={PANEL}>
            <h3 style={{ marginTop: 0 }}>Narrative</h3>
            {envelope.error ? (
              <div
                style={{
                  border: "1px solid #f5c2c7",
                  background: "#fff1f2",
                  borderRadius: 8,
                  padding: 12,
                }}
              >
                <p style={{ margin: 0, color: "#7a1021", fontWeight: 700 }}>
                  K360 Request Failed
                </p>
                <p style={{ margin: "6px 0 0", color: "#991b1b" }}>
                  {envelope.error_type ? `${envelope.error_type}: ` : ""}
                  {envelope.error}
                </p>
                {envelope.error_details ? (
                  <pre
                    style={{
                      marginTop: 10,
                      fontSize: 12,
                      whiteSpace: "pre-wrap",
                      color: "#7f1d1d",
                      background: "#fff",
                      border: "1px solid #fecdd3",
                      borderRadius: 6,
                      padding: 10,
                    }}
                  >
                    {envelope.error_details}
                  </pre>
                ) : null}
                <p style={{ margin: "8px 0 0", color: "#7f1d1d", fontSize: 12 }}>
                  Check backend logs on <code>/api/k360-query</code>. Common causes:
                  OpenAI proxy/network errors or missing API credentials.
                </p>
              </div>
            ) : (
              <ResponseMarkdown content={envelope.narrative || "_No narrative generated._"} />
            )}
          </div>
          <div style={{ ...PANEL, overflow: "auto", maxHeight: 680 }}>
            <h3 style={{ marginTop: 0 }}>Content Packet</h3>
            <pre style={{ fontSize: 12, whiteSpace: "pre-wrap", margin: 0 }}>
              {JSON.stringify(
                {
                  gate: envelope.gate,
                  rewrite: envelope.rewrite,
                  content_packet: envelope.content_packet,
                  tool_calls_count: envelope.tool_calls?.length ?? 0,
                },
                null,
                2
              )}
            </pre>
            {(envelope.tool_calls?.length ?? 0) > 0 ? (
              <div style={{ marginTop: 12 }}>
                <h4 style={{ margin: "0 0 8px" }}>Tool Input / Output</h4>
                {envelope.tool_calls.map((call, idx) => (
                  <div
                    key={`${call.tool_name}-${idx}`}
                    style={{
                      border: "1px solid #d9e0ea",
                      borderRadius: 8,
                      padding: 10,
                      marginBottom: 8,
                      background: "#fafcff",
                    }}
                  >
                    <p style={{ margin: 0, fontWeight: 700, color: "#0f2743" }}>
                      {idx + 1}. {call.tool_name}
                    </p>
                    <p style={{ margin: "8px 0 4px", fontSize: 12, color: "#3b556f" }}>
                      Input
                    </p>
                    <pre style={{ fontSize: 11, whiteSpace: "pre-wrap", margin: 0 }}>
                      {JSON.stringify(call.tool_args ?? {}, null, 2)}
                    </pre>
                    <p style={{ margin: "8px 0 4px", fontSize: 12, color: "#3b556f" }}>
                      Output
                    </p>
                    <pre style={{ fontSize: 11, whiteSpace: "pre-wrap", margin: 0 }}>
                      {JSON.stringify(call.tool_result ?? null, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      )}

      {loading && liveNarrative.trim().length > 0 ? (
        <div style={{ ...PANEL, marginTop: 16 }}>
          <h3 style={{ marginTop: 0 }}>Narrative (streaming)</h3>
          <ResponseMarkdown content={liveNarrative} />
        </div>
      ) : null}

      {vizSpec && (
        <div style={{ ...PANEL, marginTop: 16 }}>
          <h3 style={{ marginTop: 0 }}>Visualization</h3>
          <VegaChartCard
            spec={vizSpec}
            subtitle={vizMeta.subtitle}
            source={vizMeta.source ?? "Data360 MCP tool output"}
            annotations={vizMeta.annotations ?? []}
          />
        </div>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
