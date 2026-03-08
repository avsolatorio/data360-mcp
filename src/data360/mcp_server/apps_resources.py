"""UI resources for Data360 MCP Apps.

- Chart viewer: when data360_get_viz_spec returns a chart URL, hosts render
  the chart in an iframe (Vega-Embed).
- Search results: when data360_search_indicators returns indicators, hosts
  render an interactive table/card list.
"""

from urllib.parse import urlparse

from fastmcp.server.apps import AppConfig, ResourceCSP

from ._server_definition import mcp

try:
    from data360.config import get_mcp_server_settings
except Exception:
    get_mcp_server_settings = None

CHART_VIEW_URI = "ui://data360/chart-view.html"
SEARCH_VIEW_URI = "ui://data360/search-results.html"
QR_VIEW_URI = "ui://data360/qr-view.html"


def _chart_view_html() -> str:
    """Return the chart viewer app HTML (inline Vega-Embed + MCP Apps SDK)."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light dark">
  <title>Data360 Chart</title>
  <style>
    html, body {
      margin: 0;
      padding: 0;
      height: 100%;
      font-family: var(--font-sans, system-ui, sans-serif);
      background: var(--color-background-secondary, #f5f5f5);
      color: var(--color-text-primary, #111);
    }
    body {
      padding: 12px;
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }
    #root {
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }
    #chart-container {
      flex: 1;
      width: 100%;
      min-height: 200px;
      min-width: 0;
    }
    #chart-container.vega-embed {
      margin: 0;
    }
    #chart-container.vega-embed,
    #chart-container.vega-embed > div {
      max-width: 100%;
      width: 100%;
      box-sizing: border-box;
    }
    .error {
      color: var(--color-text-error, #b91c1c);
      padding: 8px 0;
    }
    .loading {
      color: var(--color-text-secondary, #666);
      padding: 8px 0;
    }
    a {
      color: var(--color-text-link, #2563eb);
    }
    #app-error {
      display: none;
      margin-bottom: 12px;
      padding: 10px 12px;
      border-radius: 6px;
      background: var(--color-text-error, #b91c1c);
      color: #fff;
      font-size: 0.875rem;
      white-space: pre-wrap;
      word-break: break-word;
    }
    #app-error[aria-hidden="false"] { display: block; }
  </style>
</head>
<body>
  <div id="app-error" role="alert" aria-live="assertive" aria-hidden="true"></div>
  <div id="root">
    <div id="chart-container"></div>
    <div id="message" class="loading" aria-live="polite">Waiting for chart data…</div>
  </div>
  <script>
    (function () {
      var el = document.getElementById("app-error");
      window.__showAppError = function (msg) {
        if (el) { el.textContent = msg || "Unknown error"; el.setAttribute("aria-hidden", "false"); }
      };
      window.onerror = function (message, source, lineno, colno, err) {
        var text = (err && err.message) || message || "Script error";
        if (source) text += " (" + source + (lineno != null ? ":" + lineno : "") + ")";
        window.__showAppError(text);
        return false;
      };
      window.addEventListener("unhandledrejection", function (ev) {
        var r = ev.reason;
        window.__showAppError((r && (r.message || r.toString())) || "Promise rejected");
        ev.preventDefault();
      });
    })();
  </script>
  <script type="module">
    (async function () {
      try {
        const { App } = await import("https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps");
        // esm.sh provides proper ESM with default export; unpkg serves UMD (no default)
        const vegaEmbedModule = await import("https://esm.sh/vega-embed@7");
        const embed = typeof vegaEmbedModule.default === "function" ? vegaEmbedModule.default : vegaEmbedModule.embed;
        if (typeof embed !== "function") {
          throw new Error("vega-embed did not export an embed function");
        }

        const container = document.getElementById("chart-container");
        const messageEl = document.getElementById("message");

        function setMessage(text, isError = false) {
          messageEl.textContent = text;
          messageEl.className = isError ? "error" : "loading";
        }

        function clearChart() {
          container.innerHTML = "";
        }

        function resolveSpec(data) {
          if (!data || typeof data !== "object") return null;
          if (data.spec && typeof data.spec === "object") return data.spec;
          if (data.$schema && String(data.$schema).includes("vega")) return data;
          return null;
        }

        function applyThemeToSpec(spec, theme) {
          if (!spec || !theme || typeof theme !== "object") return spec;
          const mergedConfig = {
            ...(typeof spec.config === "object" && spec.config !== null ? spec.config : {}),
            ...theme,
          };
          return { ...spec, config: mergedConfig };
        }

        /** Apply autosize fit; width/height set from container in renderChart. */
        function applyResponsiveSpec(spec, width, height) {
          if (!spec || typeof spec !== "object") return spec;
          const autosize = {
            type: "fit",
            resize: true,
            ...(typeof spec.autosize === "object" && spec.autosize !== null ? spec.autosize : {}),
          };
          const out = { ...spec, autosize };
          if (typeof width === "number" && width > 0) out.width = width;
          if (typeof height === "number" && height > 0) out.height = height;
          return out;
        }

        function getContainerSize(el, useViewportFallback) {
          let w = 0, h = 0;
          if (el) {
            const rect = el.getBoundingClientRect();
            w = Math.round(rect.width) || el.clientWidth || 0;
            h = Math.round(rect.height) || el.clientHeight || 0;
          }
          if (useViewportFallback && (w <= 0 || h <= 0 || w < 200)) {
            const win = typeof window !== "undefined" ? window : null;
            w = w > 0 ? w : (win ? win.innerWidth : 800);
            h = h > 0 ? h : (win ? win.innerHeight : 450);
          }
          return { w: w || 0, h: h || 0 };
        }

        const DEFAULT_THEME_URL = "https://worldbank.github.io/data-visualization-style-guide/vega/wb-vega-theme.json";
        const DEFAULT_CHART_WIDTH = 800;
        const DEFAULT_CHART_HEIGHT = 450;
        let resizeObserver = null;
        let currentView = null;

        function scheduleResize() {
          if (!currentView || !container) return;
          const { w, h } = getContainerSize(container, true);
          const width = w > 0 ? w : DEFAULT_CHART_WIDTH;
          const height = h > 0 ? h : DEFAULT_CHART_HEIGHT;
          if (typeof currentView.width === "function" && typeof currentView.height === "function") {
            currentView.width(width).height(height);
            if (typeof currentView.runAsync === "function") {
              currentView.runAsync();
            }
          }
        }

        async function renderChart(url, themeUrl) {
          clearChart();
          currentView = null;
          if (resizeObserver && container) {
            try { resizeObserver.disconnect(); } catch (_e) {}
            resizeObserver = null;
          }
          setMessage("Loading chart…");
          try {
            const res = await fetch(url);
            if (!res.ok) throw new Error(res.statusText);
            const data = await res.json();
            let spec = resolveSpec(data);
            if (spec) {
              const themeSrc = themeUrl || DEFAULT_THEME_URL;
              if (themeSrc) {
                try {
                  const themeRes = await fetch(themeSrc);
                  if (themeRes.ok) {
                    const theme = await themeRes.json();
                    spec = applyThemeToSpec(spec, theme);
                  }
                } catch (_e) { /* use spec without theme */ }
              }
              const { w, h } = getContainerSize(container, true);
              const width = w > 0 ? w : DEFAULT_CHART_WIDTH;
              const height = h > 0 ? h : DEFAULT_CHART_HEIGHT;
              spec = applyResponsiveSpec(spec, width, height);
              const result = await embed(container, spec, { actions: false });
              currentView = result && result.view ? result.view : null;
              setMessage("");
              if (currentView && typeof ResizeObserver !== "undefined") {
                resizeObserver = new ResizeObserver(function () {
                  scheduleResize();
                });
                resizeObserver.observe(container);
              }
              [50, 150, 350, 600, 1000, 1500].forEach(function (delay) {
                setTimeout(scheduleResize, delay);
              });
            } else {
              const link = document.createElement("a");
              link.href = url;
              link.target = "_blank";
              link.rel = "noopener";
              link.textContent = "Open chart";
              container.appendChild(link);
              setMessage("");
            }
          } catch (e) {
            setMessage("Could not load chart: " + e.message, true);
          }
        }

        const app = new App({ name: "Data360 Chart View", version: "1.0.0" });

        function processToolResult(payload) {
          const content = payload && payload.content;
          const textPart = content && content.find(c => c.type === "text");
          if (!textPart || !textPart.text) return;
          try {
            const data = JSON.parse(textPart.text);
            if (data.error) {
              clearChart();
              setMessage(data.error, true);
              return;
            }
            if (data.url) {
              renderChart(data.url, data.themeUrl);
            } else {
              setMessage("No chart URL in result.", true);
            }
          } catch (_e) {
            setMessage("Invalid tool result.", true);
          }
        }

        try {
          app.ontoolresult = processToolResult;
        } catch (_e) {
          if (typeof window.__showAppError === "function") {
            window.__showAppError("Chart app could not register tool result handler.");
          }
        }

        app.onhostcontextchanged = (ctx) => {
          if (ctx.theme) document.documentElement.setAttribute("data-theme", ctx.theme);
          if (ctx.safeAreaInsets) {
            const { top, right, bottom, left } = ctx.safeAreaInsets;
            document.body.style.padding = `${top}px ${right}px ${bottom}px ${left}px`;
          }
        };

        await app.connect();
      } catch (e) {
        const msg = (e && e.message) || String(e);
        if (window.__showAppError) {
          window.__showAppError(
            msg.indexOf("Failed to fetch") !== -1 || msg.indexOf("import") !== -1 || msg.indexOf("Loading") !== -1
              ? "App script failed to load. When running locally, the chat host may need to allow https://unpkg.com in the app iframe CSP. Details: " + msg
              : msg
          );
        }
        throw e;
      }
    })();
  </script>
</body>
</html>"""


def _search_view_html() -> str:
    """Return the search results app HTML: card layout, horizontal scroll, and search input that calls MCP tool."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light dark">
  <title>Data360 Search Results</title>
  <style>
    body {
      margin: 0;
      padding: 12px;
      font-family: var(--font-sans, system-ui, sans-serif);
      background: var(--color-background-secondary, #f5f5f5);
      color: var(--color-text-primary, #111);
      min-height: 120px;
      max-width: 100%;
      min-width: 0;
      overflow-x: hidden;
    }
    #root {
      max-width: 100%;
      min-width: 0;
      overflow-x: hidden;
    }
    .search-header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
    }
    .search-header-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .search-results-title {
      font-size: 0.875rem;
      font-weight: 600;
    }
    .search-form {
      display: flex;
      gap: 8px;
      flex: 1;
      min-width: 200px;
      max-width: 400px;
    }
    #new-search-input {
      flex: 1;
      padding: 8px 12px;
      border: 1px solid var(--color-border-primary, #ddd);
      border-radius: 6px;
      font: inherit;
      background: var(--color-background-primary, #fff);
    }
    #new-search-btn {
      padding: 8px 16px;
      border: 1px solid var(--color-border-primary, #ddd);
      border-radius: 6px;
      background: var(--color-background-primary, #fff);
      font: inherit;
      cursor: pointer;
      white-space: nowrap;
    }
    #new-search-btn:hover { background: var(--color-background-secondary, #eee); }
    #new-search-btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .summary {
      font-size: 0.75rem;
      color: var(--color-text-secondary, #666);
      margin-left: auto;
    }
    .cards-scroll {
      width: 100%;
      min-width: 0;
      overflow-x: auto;
      overflow-y: hidden;
      padding-bottom: 12px;
      -webkit-overflow-scrolling: touch;
      scroll-behavior: smooth;
      scrollbar-gutter: stable;
    }
    .cards-scroll::-webkit-scrollbar { height: 8px; }
    .cards-scroll::-webkit-scrollbar-track { background: var(--color-border-secondary, #eee); border-radius: 4px; }
    .cards-scroll::-webkit-scrollbar-thumb { background: var(--color-text-secondary, #999); border-radius: 4px; }
    .cards-scroll::-webkit-scrollbar-thumb:hover { background: var(--color-text-primary, #333); }
    .cards-row {
      display: flex;
      flex-wrap: nowrap;
      gap: 12px;
      width: max-content;
      min-height: 1px;
    }
    .card {
      min-width: 320px;
      max-width: 400px;
      flex-shrink: 0;
      border: 1px solid var(--color-border-primary, #ddd);
      border-radius: 8px;
      background: var(--color-background-primary, #fff);
      padding: 12px;
      transition: border-color 0.15s;
    }
    .card:hover { border-color: var(--color-primary, #0066cc); }
    .card-title {
      font-weight: 500;
      font-size: 0.875rem;
      line-height: 1.3;
      margin-bottom: 8px;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .card-meta {
      font-size: 0.75rem;
      color: var(--color-text-secondary, #666);
      margin-bottom: 8px;
    }
    .card-definition {
      font-size: 0.75rem;
      color: var(--color-text-secondary, #666);
      line-height: 1.4;
      padding: 8px;
      border: 1px solid var(--color-border-secondary, #eee);
      border-radius: 4px;
      background: var(--color-background-secondary, #f9f9f9);
      margin-bottom: 8px;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .card-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      font-size: 0.7rem;
      color: var(--color-text-secondary, #666);
    }
    .card-grid span { font-weight: 500; }
    .error { color: var(--color-text-error, #b91c1c); padding: 8px 0; font-size: 0.875rem; }
    .loading { color: var(--color-text-secondary, #666); padding: 8px 0; font-size: 0.875rem; }
    .no-results { color: var(--color-text-secondary, #666); padding: 16px 0; font-size: 0.875rem; }
    #app-error {
      display: none;
      margin-bottom: 12px;
      padding: 10px 12px;
      border-radius: 6px;
      background: var(--color-text-error, #b91c1c);
      color: #fff;
      font-size: 0.875rem;
      white-space: pre-wrap;
      word-break: break-word;
    }
    #app-error[aria-hidden="false"] { display: block; }
  </style>
</head>
<body>
  <div id="app-error" role="alert" aria-live="assertive" aria-hidden="true"></div>
  <div id="root">
    <div class="search-header">
      <div class="search-header-left">
        <span class="search-results-title">Search Results</span>
        <form class="search-form" id="new-search-form" role="search">
          <input type="search" id="new-search-input" placeholder="Search indicators…" aria-label="Search indicators">
          <button type="submit" id="new-search-btn">Search</button>
        </form>
      </div>
      <div class="summary" id="summary" aria-live="polite"></div>
    </div>
    <div class="cards-scroll">
      <div class="cards-row" id="cards-row"></div>
    </div>
    <div id="message" class="loading" aria-live="polite">Waiting for search results…</div>
  </div>
  <script>
    (function () {
      var el = document.getElementById("app-error");
      window.__showAppError = function (msg) {
        if (el) { el.textContent = msg || "Unknown error"; el.setAttribute("aria-hidden", "false"); }
      };
      window.onerror = function (message, source, lineno, colno, err) {
        var text = (err && err.message) || message || "Script error";
        if (source) text += " (" + source + (lineno != null ? ":" + lineno : "") + ")";
        window.__showAppError(text);
        return false;
      };
      window.addEventListener("unhandledrejection", function (ev) {
        var r = ev.reason;
        window.__showAppError((r && (r.message || r.toString())) || "Promise rejected");
        ev.preventDefault();
      });
    })();
  </script>
  <script type="module">
    (async function () {
      try {
        const { App } = await import("https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps");

        const summaryEl = document.getElementById("summary");
        const cardsRow = document.getElementById("cards-row");
        const messageEl = document.getElementById("message");
        const newSearchForm = document.getElementById("new-search-form");
        const newSearchInput = document.getElementById("new-search-input");
        const newSearchBtn = document.getElementById("new-search-btn");

        function setMessage(text, className) {
          messageEl.textContent = text || "";
          messageEl.className = className || "loading";
        }

        function escapeHtml(s) {
          if (s == null) return "";
          var div = document.createElement("div");
          div.textContent = s;
          return div.innerHTML;
        }

        function buildCard(ind) {
          if (!ind || typeof ind !== "object") return null;
          var periodicity = ind.periodicity != null ? String(ind.periodicity) : "—";
          var latest = ind.latest_data != null ? String(ind.latest_data) : (ind.time_period_range != null ? String(ind.time_period_range) : "—");
          var range = ind.time_period_range != null ? String(ind.time_period_range) : latest;
          var dims = ind.dimensions && Array.isArray(ind.dimensions) ? ind.dimensions.join(", ") : "—";
          var card = document.createElement("div");
          card.className = "card";
          card.innerHTML =
            "<div class='card-title'>" + escapeHtml(ind.name) + "</div>" +
            "<div class='card-meta'><span>ID:</span> " + escapeHtml(ind.idno) + " · <span>DB:</span> " + escapeHtml(ind.database_id || "") + "</div>" +
            (ind.truncated_definition ? "<div class='card-definition'>" + escapeHtml(ind.truncated_definition) + "</div>" : "") +
            "<div class='card-grid'>" +
            "<div><span>Periodicity:</span> " + escapeHtml(periodicity) + "</div>" +
            "<div><span>Latest:</span> " + escapeHtml(latest) + "</div>" +
            "<div style='grid-column:1/-1'><span>Range:</span> " + escapeHtml(range) + "</div>" +
            (dims !== "—" ? "<div style='grid-column:1/-1'><span>Dimensions:</span> " + escapeHtml(dims) + "</div>" : "") +
            "</div>";
          return card;
        }

        function renderCards(indicators, totalCount) {
          cardsRow.innerHTML = "";
          if (!indicators || indicators.length === 0) {
            setMessage("No indicators found.", "no-results");
            return;
          }
          var total = totalCount != null && Number.isFinite(totalCount) ? totalCount : indicators.length;
          summaryEl.textContent = "Showing " + indicators.length + " of " + total.toLocaleString() + " indicator" + (total !== 1 ? "s" : "");
          setMessage("");
          for (var i = 0; i < indicators.length; i++) {
            var card = buildCard(indicators[i]);
            if (card) cardsRow.appendChild(card);
          }
        }

        var lastIndicators = [];
        var lastTotalCount = null;

        var app = new App({ name: "Data360 Search Results", version: "1.0.0" });

        function processToolResult(payload) {
          var content = payload && payload.content;
          var textPart = content && content.find(function (c) { return c.type === "text"; });
          if (!textPart || !textPart.text) return;
          try {
            var data = JSON.parse(textPart.text);
            if (data.error) {
              summaryEl.textContent = "";
              renderCards([]);
              setMessage(data.error, "error");
              return;
            }
            var raw = data.indicators;
            var indicators = Array.isArray(raw) ? raw : [];
            lastIndicators = indicators;
            lastTotalCount = data.total_count != null && Number.isFinite(data.total_count) ? data.total_count : null;
            renderCards(indicators, lastTotalCount);
          } catch (_e) {
            setMessage("Invalid tool result.", "error");
          }
        }

        try {
          app.ontoolresult = processToolResult;
        } catch (_e) {
          /* SDK may not expose ontoolresult in this version; new-search still works via processToolResult() */
        }

        newSearchForm.addEventListener("submit", async function (e) {
          e.preventDefault();
          var query = (newSearchInput.value || "").trim();
          if (!query) return;
          newSearchBtn.disabled = true;
          setMessage("Searching…", "loading");
          try {
            var result = await app.callServerTool({
              name: "data360_search_indicators",
              arguments: { query: query, limit: 20 }
            });
            if (result && result.content) {
              processToolResult({ content: result.content });
            } else {
              setMessage("No results returned.", "no-results");
            }
          } catch (err) {
            var msg = (err && err.message) || String(err);
            setMessage("Search failed: " + msg, "error");
            if (window.__showAppError) window.__showAppError(msg);
          } finally {
            newSearchBtn.disabled = false;
          }
        });

        app.onhostcontextchanged = function (ctx) {
          if (ctx && ctx.theme) document.documentElement.setAttribute("data-theme", ctx.theme);
          if (ctx && ctx.safeAreaInsets) {
            var insets = ctx.safeAreaInsets;
            document.body.style.padding = insets.top + "px " + insets.right + "px " + insets.bottom + "px " + insets.left + "px";
          }
        };

        await app.connect();
      } catch (e) {
        var msg = (e && e.message) || String(e);
        if (window.__showAppError) {
          window.__showAppError(
            msg.indexOf("Failed to fetch") !== -1 || msg.indexOf("import") !== -1 || msg.indexOf("Loading") !== -1
              ? "App script failed to load. Check if the host allows https://unpkg.com in the iframe CSP. Details: " + msg
              : msg
          );
        }
        throw e;
      }
    })();
  </script>
</body>
</html>"""


def _qr_view_html() -> str:
    """QR code viewer app HTML (from FastMCP low-level apps example)."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light dark">
  <title>QR Code Viewer</title>
  <style>
    body {
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 280px;
      margin: 0;
      padding: 12px;
      background: var(--color-background-secondary, transparent);
      font-family: var(--font-sans, system-ui, sans-serif);
    }
    #qr {
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 240px;
    }
    #qr img {
      width: 200px;
      height: 200px;
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    .placeholder {
      color: var(--color-text-secondary, #666);
      font-size: 14px;
    }
    #app-error {
      display: none;
      margin-bottom: 12px;
      padding: 10px 12px;
      border-radius: 6px;
      background: var(--color-text-error, #b91c1c);
      color: #fff;
      font-size: 0.875rem;
      white-space: pre-wrap;
      word-break: break-word;
    }
    #app-error[aria-hidden="false"] { display: block; }
  </style>
</head>
<body>
  <div id="app-error" role="alert" aria-live="assertive" aria-hidden="true"></div>
  <div id="qr"><span class="placeholder">Generate a QR code to see it here.</span></div>
  <script>
    (function () {
      var el = document.getElementById("app-error");
      window.__showAppError = function (msg) {
        if (el) { el.textContent = msg || "Unknown error"; el.setAttribute("aria-hidden", "false"); }
      };
      window.onerror = function (message, source, lineno, colno, err) {
        var text = (err && err.message) || message || "Script error";
        if (source) text += " (" + source + (lineno != null ? ":" + lineno : "") + ")";
        window.__showAppError(text);
        return false;
      };
      window.addEventListener("unhandledrejection", function (ev) {
        var r = ev.reason;
        window.__showAppError((r && (r.message || r.toString())) || "Promise rejected");
        ev.preventDefault();
      });
    })();
  </script>
  <script type="module">
    (async function () {
      try {
        const { App } = await import("https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps");

        const app = new App({ name: "QR View", version: "1.0.0" });

        app.ontoolresult = ({ content }) => {
          const img = content && content.find(function (c) { return c.type === "image"; });
          if (img && img.data) {
            const el = document.createElement("img");
            el.src = "data:" + (img.mimeType || "image/png") + ";base64," + img.data;
            el.alt = "QR Code";
            document.getElementById("qr").replaceChildren(el);
          }
        };

        await app.connect();
      } catch (e) {
        const msg = (e && e.message) || String(e);
        if (window.__showAppError) {
          window.__showAppError(
            msg.indexOf("Failed to fetch") !== -1 || msg.indexOf("import") !== -1 || msg.indexOf("Loading") !== -1
              ? "App script failed to load. When running locally, the chat host may need to allow https://unpkg.com in the app iframe CSP. Details: " + msg
              : msg
          );
        }
        throw e;
      }
    })();
  </script>
</body>
</html>"""


def qr_view_resource() -> None:
    """Register the QR viewer ui:// resource (CSP: unpkg for ext-apps SDK)."""
    csp = ResourceCSP(resource_domains=["https://unpkg.com"])

    @mcp.resource(
        QR_VIEW_URI,
        name=QR_VIEW_URI,
        description="QR code viewer (MCP Apps example).",
        app=AppConfig(csp=csp),
    )
    def _qr_view() -> str:
        return _qr_view_html()


def chart_view_resource() -> None:
    """Register the chart viewer ui:// resource with CSP for unpkg and chart fetches."""
    connect_domains = [
        "http://localhost:8022",
        "http://127.0.0.1:8022",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    try:
        if get_mcp_server_settings is not None:
            charts_url = get_mcp_server_settings().charts_api_url
        else:
            charts_url = None
        if charts_url:
            parsed = urlparse(charts_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin not in connect_domains:
                connect_domains.append(origin)
    except Exception:
        pass
    csp = ResourceCSP(
        resource_domains=["https://unpkg.com"],
        connect_domains=connect_domains,
    )

    @mcp.resource(
        CHART_VIEW_URI,
        name=CHART_VIEW_URI,
        description="Data360 chart viewer (Vega-Lite).",
        app=AppConfig(csp=csp),
    )
    def _chart_view() -> str:
        return _chart_view_html()


def search_view_resource() -> None:
    """Register the search results ui:// resource (CSP: unpkg only)."""
    csp = ResourceCSP(resource_domains=["https://unpkg.com"])

    @mcp.resource(
        SEARCH_VIEW_URI,
        name=SEARCH_VIEW_URI,
        description="Data360 search results table.",
        app=AppConfig(csp=csp),
    )
    def _search_view() -> str:
        return _search_view_html()
