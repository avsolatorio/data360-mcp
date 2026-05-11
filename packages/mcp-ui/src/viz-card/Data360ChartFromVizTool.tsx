import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { normalizeChartPayloadFromJson } from "@data360/chart-payload-normalize";
import {
  formatData360VizSourceLine,
  formatData360VizSubtitleLine,
  isData360VizToolSuccess,
  type Data360VizToolResult,
} from "@data360/tool-types";
import VegaChartCard from "./VegaChartCard";
import type { VLSpec } from "./types";

export type Data360ChartFromVizToolProps = {
  /** Parsed viz tool payload (must include a chart `url` on success). */
  toolResult: Data360VizToolResult;
  /** Host-specific URL rewrite (e.g. Next.js basePath / same-origin proxy). */
  mapUrlForFetch?: (url: string) => string;
  /** Applied after fetch/normalize (e.g. point disputed layer at bundled TopoJSON). */
  prepareDisplaySpec?: (
    spec: Record<string, unknown>,
  ) => Record<string, unknown>;
  chartHeight?: number;
  railTopSlot?: ReactNode;
  className?: string;
  /** Shown while loading instead of default inline message. */
  loadingFallback?: ReactNode;
  /** Called after JSON is fetched and normalized (e.g. host artifact viewer). */
  onChartReady?: (info: {
    spec: Record<string, unknown>;
    title: string;
    specJson: string;
    /** From Vega-Lite `title.subtitle` when present. */
    subtitleFromSpec?: string;
  }) => void;
  /** Passed through to ``VegaChartCard`` (choropleth build stamp). */
  hideChartUiRevision?: boolean;
};

export function Data360ChartFromVizTool({
  toolResult,
  mapUrlForFetch,
  prepareDisplaySpec,
  chartHeight = 280,
  railTopSlot,
  className,
  loadingFallback,
  onChartReady,
  hideChartUiRevision,
}: Data360ChartFromVizToolProps) {
  const fetchUrl = useMemo(() => {
    if (!isData360VizToolSuccess(toolResult)) {
      return null;
    }
    const u = toolResult.url;
    return mapUrlForFetch ? mapUrlForFetch(u) : u;
  }, [toolResult, mapUrlForFetch]);

  const source = formatData360VizSourceLine(toolResult);
  const toolMetadataSubtitle = formatData360VizSubtitleLine(toolResult);

  const [chartData, setChartData] = useState<{
    spec: Record<string, unknown>;
    title: string;
    specSubtitle?: string;
  } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    setChartData(null);
    if (!fetchUrl) {
      return () => {
        cancelled = true;
      };
    }
    fetch(fetchUrl)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Failed to load chart: ${res.status}`);
        }
        return res.json() as Promise<unknown>;
      })
      .then((data) => {
        if (cancelled) {
          return;
        }
        const { spec, title, subtitle: specSubtitle } =
          normalizeChartPayloadFromJson(data);
        const displaySpec = prepareDisplaySpec
          ? prepareDisplaySpec(spec as Record<string, unknown>)
          : (spec as Record<string, unknown>);
        const specJson = JSON.stringify(displaySpec);
        setChartData({
          spec: displaySpec,
          title,
          specSubtitle,
        });
        onChartReady?.({
          spec: displaySpec,
          title,
          specJson,
          subtitleFromSpec: specSubtitle,
        });
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setChartData(null);
        setLoadError(
          err instanceof Error ? err.message : "Failed to load chart",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [fetchUrl, onChartReady, prepareDisplaySpec]);

  if (!isData360VizToolSuccess(toolResult)) {
    return null;
  }

  if (loadError) {
    return (
      <div className={className}>
        <div
          style={{
            borderRadius: 8,
            border: "1px solid rgba(239,68,68,0.35)",
            background: "rgba(239,68,68,0.08)",
            padding: 16,
            color: "#b91c1c",
          }}
        >
          {loadError}
        </div>
      </div>
    );
  }

  if (!chartData) {
    return (
      loadingFallback ?? (
        <div className={className}>
          <div
            style={{
              display: "flex",
              minHeight: 200,
              width: "100%",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: 8,
              border: "1px dashed rgba(0,0,0,0.12)",
              background: "rgba(0,0,0,0.03)",
            }}
          >
            <span style={{ opacity: 0.6 }}>Loading chart…</span>
          </div>
        </div>
      )
    );
  }

  const displaySubtitle =
    chartData.specSubtitle ?? toolMetadataSubtitle;

  return (
    <div className={className}>
      <VegaChartCard
        chartHeight={chartHeight}
        hideChartUiRevision={hideChartUiRevision}
        railTopSlot={railTopSlot}
        source={source}
        spec={chartData.spec as VLSpec}
        subtitle={displaySubtitle}
        title={chartData.title}
      />
    </div>
  );
}
