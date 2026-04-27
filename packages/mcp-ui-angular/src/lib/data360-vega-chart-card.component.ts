import { NgTemplateOutlet } from "@angular/common";
import {
  AfterViewInit,
  ChangeDetectorRef,
  Component,
  ElementRef,
  Input,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  TemplateRef,
  ViewChild,
} from "@angular/core";
import {
  parseSpec,
  prepareSpec,
  WB_PALETTE,
  type Annotation,
  type ParsedSpec,
  type VLSpec,
} from "@data360/mcp-viz-core";

type VegaView = {
  finalize(): void;
  toImageURL(type: string, scale?: number): Promise<string>;
};

@Component({
  selector: "data360-vega-chart-card",
  standalone: true,
  imports: [NgTemplateOutlet],
  templateUrl: "./data360-vega-chart-card.component.html",
  styleUrl: "./data360-vega-chart-card.component.css",
})
export class Data360VegaChartCardComponent
  implements AfterViewInit, OnChanges, OnDestroy
{
  /** Shown in the Copy spec icon (avoid `"</>"` tokenization in TS source). */
  readonly copySpecIconText = "<" + "/" + ">";

  @Input({ required: true }) spec!: VLSpec;
  @Input() title?: string;
  @Input() subtitle?: string;
  @Input() source?: string;
  @Input() annotations: Annotation[] = [];
  @Input() chartHeight = 260;
  /**
   * Pixel ratio for Save as PNG (full-card raster via html-to-image and Vega chart-only fallback).
   * @default 4
   */
  @Input() pngExportPixelRatio = 4;
  @Input() className?: string;

  /** Optional CSV / custom download handler (same contract as React). */
  @Input() onDownload?: (rows: Record<string, unknown>[]) => void;
  /** Optional PNG handler (same contract as React). */
  @Input() onExport?: (dataUrl: string) => void;

  /** Optional template for the top of the right rail (replaces React `railTopSlot`). */
  @Input() railTopSlot?: TemplateRef<unknown> | null;

  @ViewChild("chartHost", { static: false })
  chartHost?: ElementRef<HTMLDivElement>;

  /** White card shell (title, chart, legend, annotations, source) — target for full-card PNG. */
  @ViewChild("cardRoot", { static: false })
  cardRoot?: ElementRef<HTMLDivElement>;

  parsed: ParsedSpec = {
    rows: [],
    colorField: null,
    specTitle: null,
    distinctGroups: [],
    colorMap: {},
  };

  activeGroups = new Set<string>();
  showAnnotations = true;
  railHover: "download" | "png" | "pdf" | "copy" | null = null;

  private vegaView: VegaView | null = null;
  private embedPending = false;

  constructor(private readonly cdr: ChangeDetectorRef) {}

  get cardTitle(): string {
    return this.title ?? this.parsed.specTitle ?? "";
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes["spec"] || changes["chartHeight"]) {
      this.refreshParsedFromSpec();
      this.scheduleEmbed();
    }
  }

  ngAfterViewInit(): void {
    this.refreshParsedFromSpec();
    this.scheduleEmbed();
  }

  ngOnDestroy(): void {
    this.finalizeView();
  }

  setRailHover(key: "download" | "png" | "pdf" | "copy" | null): void {
    this.railHover = key;
  }

  toggleGroup(group: string): void {
    const next = new Set(this.activeGroups);
    if (next.has(group) && next.size > 1) {
      next.delete(group);
    } else {
      next.add(group);
    }
    this.activeGroups = next;
    this.scheduleEmbed();
  }

  handleDownload(): void {
    const rows = this.parsed.rows.filter(
      (r) =>
        !this.parsed.colorField ||
        this.activeGroups.has(String(r[this.parsed.colorField]))
    );
    if (this.onDownload) {
      this.onDownload(rows);
      return;
    }
    const keys = Object.keys(rows[0] ?? {});
    const csv = [
      keys.join(","),
      ...rows.map((r) => keys.map((k) => r[k]).join(",")),
    ].join("\n");
    const a = document.createElement("a");
    a.href = "data:text/csv;charset=utf-8," + encodeURIComponent(csv);
    a.download = "chart-data.csv";
    a.click();
  }

  handleExport(): void {
    void this.runPngExport();
  }

  private async runPngExport(): Promise<void> {
    const deliver = (url: string) => {
      if (this.onExport) {
        this.onExport(url);
        return;
      }
      const a = document.createElement("a");
      a.href = url;
      a.download = "chart.png";
      a.click();
    };

    const fromVegaOnly = () => {
      if (!this.vegaView) return;
      void this.vegaView
        .toImageURL("png", this.pngExportPixelRatio)
        .then(deliver);
    };

    const cardEl = this.cardRoot?.nativeElement;
    if (!cardEl) {
      fromVegaOnly();
      return;
    }

    try {
      const { toPng } = await import("html-to-image");
      const url = await toPng(cardEl, {
        pixelRatio: this.pngExportPixelRatio,
        backgroundColor: "#ffffff",
        cacheBust: true,
        filter: (domNode) =>
          !(
            domNode instanceof HTMLElement &&
            domNode.hasAttribute("data-chart-card-export-skip")
          ),
      });
      deliver(url);
    } catch {
      fromVegaOnly();
    }
  }

  handleCopySpec(): void {
    try {
      void navigator.clipboard.writeText(JSON.stringify(this.spec, null, 2));
    } catch {
      /* ignore */
    }
  }

  private refreshParsedFromSpec(): void {
    this.parsed = parseSpec(this.spec, WB_PALETTE);
    this.activeGroups = new Set(this.parsed.distinctGroups);
  }

  private finalizeView(): void {
    try {
      this.vegaView?.finalize();
    } catch {
      /* ignore */
    }
    this.vegaView = null;
  }

  private scheduleEmbed(): void {
    if (this.embedPending) return;
    this.embedPending = true;
    queueMicrotask(() => {
      this.embedPending = false;
      void this.embedChart();
    });
  }

  private async embedChart(): Promise<void> {
    const el = this.chartHost?.nativeElement;
    if (!el) return;

    if (this.parsed.distinctGroups.length > 0 && this.activeGroups.size === 0) {
      return;
    }

    this.finalizeView();

    const { default: embed } = await import("vega-embed");

    let prepared = prepareSpec(this.spec, this.chartHeight);

    if (this.parsed.colorField && prepared.data?.values) {
      prepared = {
        ...prepared,
        data: {
          values: prepared.data.values.filter((r) =>
            this.activeGroups.has(String(r[this.parsed.colorField!]))
          ),
        },
      };
    }

    if (prepared.encoding?.color && this.parsed.colorField) {
      const activeDomain = this.parsed.distinctGroups.filter((g) =>
        this.activeGroups.has(g)
      );
      prepared.encoding.color.scale = {
        domain: activeDomain,
        range: activeDomain.map((g) => this.parsed.colorMap[g]),
      };
    }

    try {
      const result = await embed(el, prepared as never, {
        actions: false,
        renderer: "svg",
      });
      this.vegaView = result.view as VegaView;
      this.cdr.markForCheck();
    } catch {
      /* vega-embed errors are non-fatal for host app */
    }
  }
}
