/**
 * DOM styling for Vega-Embed choropleths so the SVG scales with the container without intrinsic
 * ``width``/``height`` attrs fighting CSS in flex layouts.
 *
 * **Clipping:** Keep ``.vega-embed`` and root ``<svg>`` at ``overflow: visible`` — ``overflow:
 * hidden`` on ``<svg>`` hides the bottom gradient legend in browsers even when it sits inside the
 * viewBox. Map paths are clipped in **Vega** via ``patchVegaSpecChoroplethMapGroupClip``. The host
 * chart slot still uses ``overflow: hidden`` + ``border-radius`` for rounded containment.
 */

/** Vega-Embed puts ``vega-embed`` on the bind element when ``actions: false`` (no nested wrapper). */
export function resolveVegaEmbedRoot(host: HTMLElement): HTMLElement | null {
  if (host.classList.contains("vega-embed")) return host;
  const nested = host.querySelector(".vega-embed");
  return nested instanceof HTMLElement ? nested : null;
}

/**
 * After embed: responsive SVG. Legend and map stay inside the Vega viewBox; the host chart slot
 * clips anything that extends past the rounded panel.
 */
export function applyChoroplethEmbedDomStyles(host: HTMLElement): void {
  const wrap = resolveVegaEmbedRoot(host);
  if (!wrap) return;
  wrap.style.display = "block";
  wrap.style.width = "100%";
  wrap.style.maxWidth = "100%";
  wrap.style.minWidth = "0";
  wrap.style.height = "auto";
  wrap.style.boxSizing = "border-box";
  wrap.style.lineHeight = "1";
  wrap.style.overflow = "visible";

  const svg = wrap.querySelector("svg");
  if (!(svg instanceof SVGSVGElement)) return;

  const vb = svg.viewBox?.baseVal;
  if (vb && vb.width > 0 && vb.height > 0) {
    svg.style.aspectRatio = `${vb.width} / ${vb.height}`;
  }
  svg.style.width = "100%";
  svg.style.maxWidth = "100%";
  svg.style.height = "auto";
  svg.style.display = "block";
  svg.style.overflow = "visible";
  svg.removeAttribute("height");
  /** Vega sets numeric width (e.g. 600); intrinsic width breaks ``width: 100%`` in flex layouts. */
  svg.removeAttribute("width");
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
}
