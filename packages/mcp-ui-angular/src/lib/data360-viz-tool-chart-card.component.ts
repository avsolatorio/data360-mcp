import { NgTemplateOutlet } from "@angular/common";
import {
  ChangeDetectorRef,
  Component,
  Input,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  TemplateRef,
} from "@angular/core";
import { normalizeChartPayloadFromJson } from "@data360/chart-payload-normalize";
import {
  formatData360VizSourceLine,
  formatData360VizSubtitleLine,
  type Data360VizToolResult,
} from "@data360/tool-types";
import type { VLSpec } from "@data360/mcp-viz-core";
import { Data360VegaChartCardComponent } from "./data360-vega-chart-card.component";

/**
 * Argument to {@link Data360VizToolChartCardComponent.onChartReady} — aligned with React
 * `Data360ChartFromVizToolProps.onChartReady`.
 */
export interface Data360VizToolChartCardReadyInfo {
  spec: Record<string, unknown>;
  title: string;
  specJson: string;
  /** From Vega-Lite `title.subtitle` when present. */
  subtitleFromSpec?: string;
}

@Component({
  selector: "data360-viz-tool-chart-card",
  standalone: true,
  imports: [Data360VegaChartCardComponent, NgTemplateOutlet],
  template: `
    @if (loadError) {
      <div class="d360-viz-tool-err">{{ loadError }}</div>
    } @else if (hasChartUrl()) {
      @if (isLoading || spec === null) {
        @if (loadingFallback) {
          <ng-container [ngTemplateOutlet]="loadingFallback"></ng-container>
        } @else {
          <div class="d360-viz-tool-loading">Loading chart…</div>
        }
      } @else {
        <data360-vega-chart-card
          [spec]="spec"
          [title]="title"
          [subtitle]="subtitle"
          [source]="source"
          [chartHeight]="chartHeight"
          [railTopSlot]="railTopSlot"
          [className]="className"
        />
      }
    }
  `,
  styles: [
    `
      .d360-viz-tool-err {
        color: #b91c1c;
        padding: 16px;
        border: 1px solid rgba(239, 68, 68, 0.35);
        border-radius: 8px;
      }
      .d360-viz-tool-loading {
        min-height: 200px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 8px;
        border: 1px dashed rgba(0, 0, 0, 0.12);
        background: rgba(0, 0, 0, 0.03);
      }
    `,
  ],
})
export class Data360VizToolChartCardComponent
  implements OnChanges, OnDestroy
{
  /**
   * Parsed viz tool payload from {@link parseData360VizToolResult}
   * (must include `url` when successful).
   */
  @Input({ required: true }) toolResult!: Data360VizToolResult;

  /** Host-specific URL rewrite (proxy / base path). */
  @Input() mapUrlForFetch?: (url: string) => string;

  @Input() chartHeight = 280;
  @Input() className = "";
  @Input() railTopSlot: TemplateRef<unknown> | null = null;

  /**
   * Shown while the chart JSON is loading (same role as React `loadingFallback`).
   * Use an `ng-template` and bind `[loadingFallback]="tpl"`.
   */
  @Input() loadingFallback: TemplateRef<unknown> | null = null;

  /**
   * Called after JSON is fetched and normalized (same contract as React `onChartReady`).
   */
  @Input() onChartReady?: (info: Data360VizToolChartCardReadyInfo) => void;

  spec: VLSpec | null = null;
  title = "Chart";
  subtitle: string | undefined;
  source = "";
  loadError: string | null = null;
  isLoading = false;
  private loadRequestId = 0;
  private loadAbortController: AbortController | null = null;

  constructor(private readonly cdr: ChangeDetectorRef) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (
      changes["toolResult"] ||
      changes["mapUrlForFetch"] ||
      changes["onChartReady"]
    ) {
      void this.load();
    }
  }

  ngOnDestroy(): void {
    this.loadAbortController?.abort();
    this.loadAbortController = null;
  }

  /** Same semantics as {@link isData360VizToolSuccess} without a narrowing type that breaks ng-packagr. */
  hasChartUrl(): boolean {
    const tr = this.toolResult;
    return Boolean(tr.url) && (tr.error === null || tr.error === undefined);
  }

  private async load(): Promise<void> {
    const requestId = ++this.loadRequestId;
    this.loadAbortController?.abort();
    const abortController = new AbortController();
    this.loadAbortController = abortController;

    this.loadError = null;
    this.spec = null;
    this.isLoading = false;

    const tr = this.toolResult;
    if (!tr.url || !(tr.error === null || tr.error === undefined)) {
      this.cdr.markForCheck();
      return;
    }

    const fetchUrl = this.mapUrlForFetch
      ? this.mapUrlForFetch(tr.url)
      : tr.url;

    this.source = formatData360VizSourceLine(tr);
    this.subtitle = undefined;
    this.isLoading = true;
    this.cdr.markForCheck();

    try {
      const res = await fetch(fetchUrl, { signal: abortController.signal });
      if (!res.ok) {
        throw new Error(`Failed to load chart: ${res.status}`);
      }
      const data: unknown = await res.json();
      if (requestId !== this.loadRequestId) {
        return;
      }
      const normalized = normalizeChartPayloadFromJson(data);
      this.spec = normalized.spec as VLSpec;
      this.title = normalized.title;
      this.subtitle =
        normalized.subtitle ?? formatData360VizSubtitleLine(tr);
      this.loadError = null;
      this.onChartReady?.({
        spec: normalized.spec as Record<string, unknown>,
        title: normalized.title,
        specJson: JSON.stringify(normalized.spec),
        subtitleFromSpec: normalized.subtitle,
      });
    } catch (e: unknown) {
      if (requestId !== this.loadRequestId) {
        return;
      }
      if (e instanceof DOMException && e.name === "AbortError") {
        return;
      }
      this.spec = null;
      this.loadError =
        e instanceof Error ? e.message : "Failed to load chart";
    } finally {
      if (requestId !== this.loadRequestId) {
        return;
      }
      this.isLoading = false;
      if (this.loadAbortController === abortController) {
        this.loadAbortController = null;
      }
      this.cdr.markForCheck();
    }
  }
}
