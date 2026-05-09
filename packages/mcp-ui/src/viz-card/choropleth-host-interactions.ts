import { choroplethMapBandCenterY } from "@data360/mcp-viz-core";

/** Wheel sensitivity — matched to choropleth projection zoom signals in Vega. */
export const CHOROPLETH_ZOOM_SENSITIVITY = 1.0018;

export function runChoroplethVegaView(view: {
  run?: () => void;
  runAsync(): Promise<unknown>;
}): void {
  if (typeof view.run === "function") {
    view.run();
    return;
  }
  void view.runAsync();
}

/** Double-click reset, drag to pan, wheel zoom (DOM coords → projection pivot). */
export function attachChoroplethMapInteractions(
  el: HTMLElement,
  view: {
    signal(name: string, value?: unknown): unknown;
    run?: () => void;
    runAsync(): Promise<unknown>;
    origin?: () => number[];
  },
): () => void {
  const reset = (e: MouseEvent) => {
    e.preventDefault();
    const w = view.signal("width") as number;
    const h = view.signal("height") as number;
    const strip = (view.signal("choropleth_legend_strip_px") as number) ?? 0;
    view.signal("choropleth_zoom", 1);
    view.signal("choropleth_tx", w / 2);
    /** Align with ``patchVegaSpecChoroplethWheelZoom`` initial ``choropleth_ty``. */
    view.signal("choropleth_ty", choroplethMapBandCenterY(h, strip));
    runChoroplethVegaView(view);
  };

  let pendingWheelDy = 0;
  let wheelClientX = 0;
  let wheelClientY = 0;
  let wheelRaf = 0;

  const flushWheel = () => {
    wheelRaf = 0;
    const dy = pendingWheelDy;
    pendingWheelDy = 0;
    if (dy === 0) return;
    const rect = el.getBoundingClientRect();
    const origin = view.origin?.() ?? [0, 0];
    const vw = view.signal("width") as number;
    const vh = view.signal("height") as number;
    const rw = rect.width > 0 ? rect.width : 1;
    const rh = rect.height > 0 ? rect.height : 1;
    const mx = ((wheelClientX - rect.left) / rw) * vw - origin[0];
    const my = ((wheelClientY - rect.top) / rh) * vh - origin[1];
    const rawF = CHOROPLETH_ZOOM_SENSITIVITY ** -dy;
    const zoom = view.signal("choropleth_zoom") as number;
    const tx = view.signal("choropleth_tx") as number;
    const ty = view.signal("choropleth_ty") as number;
    const nextZoom = Math.min(14, Math.max(0.35, zoom * rawF));
    const fApplied = nextZoom / zoom;
    view.signal("choropleth_zoom", nextZoom);
    view.signal("choropleth_tx", mx + (tx - mx) * fApplied);
    view.signal("choropleth_ty", my + (ty - my) * fApplied);
    runChoroplethVegaView(view);
  };

  const onWheel = (e: WheelEvent) => {
    e.preventDefault();
    pendingWheelDy += e.deltaY;
    wheelClientX = e.clientX;
    wheelClientY = e.clientY;
    if (wheelRaf) return;
    wheelRaf = requestAnimationFrame(flushWheel);
  };

  let dragging = false;
  let dragRaf = 0;

  const onDown = (e: PointerEvent) => {
    if (e.button !== 0) return;
    dragging = true;
    el.setPointerCapture(e.pointerId);
  };

  const onMove = (e: PointerEvent) => {
    if (!dragging) return;
    const tx = view.signal("choropleth_tx") as number;
    const ty = view.signal("choropleth_ty") as number;
    const vw = view.signal("width") as number;
    const vh = view.signal("height") as number;
    const rect = el.getBoundingClientRect();
    const rw = rect.width > 0 ? rect.width : 1;
    const rh = rect.height > 0 ? rect.height : 1;
    view.signal("choropleth_tx", tx + (e.movementX * vw) / rw);
    view.signal("choropleth_ty", ty + (e.movementY * vh) / rh);
    if (dragRaf) return;
    dragRaf = requestAnimationFrame(() => {
      dragRaf = 0;
      runChoroplethVegaView(view);
    });
  };

  const endDrag = (e: PointerEvent) => {
    if (!dragging) return;
    dragging = false;
    try {
      el.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  el.addEventListener("dblclick", reset);
  el.addEventListener("wheel", onWheel, { passive: false });
  el.addEventListener("pointerdown", onDown);
  el.addEventListener("pointermove", onMove);
  el.addEventListener("pointerup", endDrag);
  el.addEventListener("pointercancel", endDrag);

  return () => {
    if (wheelRaf) cancelAnimationFrame(wheelRaf);
    if (dragRaf) cancelAnimationFrame(dragRaf);
    el.removeEventListener("dblclick", reset);
    el.removeEventListener("wheel", onWheel);
    el.removeEventListener("pointerdown", onDown);
    el.removeEventListener("pointermove", onMove);
    el.removeEventListener("pointerup", endDrag);
    el.removeEventListener("pointercancel", endDrag);
  };
}
