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
    body {
      margin: 0;
      padding: 12px;
      font-family: var(--font-sans, system-ui, sans-serif);
      background: var(--color-background-secondary, #f5f5f5);
      color: var(--color-text-primary, #111);
      min-height: 120px;
    }
    #chart-container {
      width: 100%;
      min-height: 280px;
    }
    #chart-container.vega-embed {
      margin: 0;
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
        const { embed } = await import("https://unpkg.com/vega-embed@7");

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

        async function renderChart(url) {
          clearChart();
          setMessage("Loading chart…");
          try {
            const res = await fetch(url);
            if (!res.ok) throw new Error(res.statusText);
            const data = await res.json();
            const spec = resolveSpec(data);
            if (spec) {
              await embed(container, spec, { actions: false });
              setMessage("");
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

        app.ontoolresult = ({ content }) => {
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
              renderChart(data.url);
            } else {
              setMessage("No chart URL in result.", true);
            }
          } catch (_e) {
            setMessage("Invalid tool result.", true);
          }
        };

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
    """Return the search results app HTML (interactive table of indicators)."""
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
    }
    .search-header {
      margin-bottom: 12px;
      font-size: var(--font-text-sm-size, 0.875rem);
      color: var(--color-text-secondary, #666);
    }
    .search-summary {
      font-weight: 600;
      color: var(--color-text-primary, #111);
    }
    .request-summary {
      font-size: 0.8125rem;
      color: var(--color-text-secondary, #666);
      margin-bottom: 4px;
    }
    .search-results-title {
      font-size: 0.875rem;
      font-weight: 600;
      margin-bottom: 8px;
    }
    #search-input {
      width: 100%;
      max-width: 320px;
      padding: 8px 12px;
      margin-bottom: 12px;
      border: 1px solid var(--color-border-primary, #ddd);
      border-radius: var(--border-radius-md, 6px);
      font: inherit;
      background: var(--color-background-primary, #fff);
    }
    .table-wrap {
      overflow-x: auto;
      border-radius: var(--border-radius-md, 6px);
      border: 1px solid var(--color-border-primary, #ddd);
      background: var(--color-background-primary, #fff);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: var(--font-text-sm-size, 0.875rem);
    }
    th, td {
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid var(--color-border-secondary, #eee);
    }
    th {
      font-weight: 600;
      background: var(--color-background-secondary, #f5f5f5);
      position: sticky;
      top: 0;
    }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: var(--color-background-secondary, #f9f9f9); }
    .name { font-weight: 500; }
    .idno { font-family: var(--font-mono, monospace); font-size: 0.85em; color: var(--color-text-secondary, #666); }
    .definition { max-width: 320px; white-space: normal; }
    .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; background: var(--color-background-secondary, #eee); }
    .error { color: var(--color-text-error, #b91c1c); padding: 8px 0; }
    .loading { color: var(--color-text-secondary, #666); padding: 8px 0; }
    .no-results { color: var(--color-text-secondary, #666); padding: 16px 0; }
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
      <div id="request-summary" class="request-summary" aria-live="polite"></div>
      <div class="search-results-title" id="results-title">Search Results</div>
      <div id="summary" class="search-summary" aria-live="polite"></div>
      <input type="search" id="search-input" placeholder="Filter results…" aria-label="Filter results">
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">ID</th>
            <th scope="col">Definition</th>
            <th scope="col">Periodicity</th>
            <th scope="col">Coverage</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
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

        const requestSummaryEl = document.getElementById("request-summary");
    const summaryEl = document.getElementById("summary");
    const filterInput = document.getElementById("search-input");
    const tbody = document.getElementById("tbody");
    const messageEl = document.getElementById("message");

    function setMessage(text, className = "loading") {
      messageEl.textContent = text;
      messageEl.className = className;
    }

    function escapeHtml(s) {
      if (s == null) return "";
      const div = document.createElement("div");
      div.textContent = s;
      return div.innerHTML;
    }

    function renderRow(ind) {
      if (!ind || typeof ind !== "object") return null;
      const tr = document.createElement("tr");
      const periodicity = ind.periodicity != null ? String(ind.periodicity) : "—";
      const range = ind.time_period_range != null ? String(ind.time_period_range) : (ind.latest_data != null ? String(ind.latest_data) : "—");
      const coverage = range !== "—" ? range + (ind.covers_country === true ? " (country ✓)" : ind.covers_country === false ? " (country ✗)" : "") : "—";
      tr.innerHTML =
        "<td class='name'>" + escapeHtml(ind.name) + "</td>" +
        "<td class='idno'>" + escapeHtml(ind.database_id) + " / " + escapeHtml(ind.idno) + "</td>" +
        "<td class='definition'>" + escapeHtml(ind.truncated_definition || "") + "</td>" +
        "<td>" + escapeHtml(periodicity) + "</td>" +
        "<td>" + escapeHtml(coverage) + "</td>";
      return tr;
    }

    function render(indicators, filterText, totalCount) {
      const q = (filterText || "").toLowerCase().trim();
      const filtered = q ? indicators.filter(function (i) {
        return (i.name && i.name.toLowerCase().includes(q)) ||
          (i.idno && i.idno.toLowerCase().includes(q)) ||
          (i.database_id && i.database_id.toLowerCase().includes(q)) ||
          (i.truncated_definition && i.truncated_definition.toLowerCase().includes(q));
      }) : indicators;
      const total = totalCount != null && Number.isFinite(totalCount) ? totalCount : indicators.length;
      summaryEl.textContent = "Showing " + filtered.length + " of " + total.toLocaleString() + " indicator" + (total !== 1 ? "s" : "");
      tbody.innerHTML = "";
      for (let i = 0; i < filtered.length; i++) {
        const row = renderRow(filtered[i]);
        if (row) tbody.appendChild(row);
      }
      if (filtered.length === 0) setMessage("No indicators match the filter.", "no-results");
      else setMessage("");
    }

    let lastIndicators = [];
    let lastTotalCount = null;

    const app = new App({ name: "Data360 Search Results", version: "1.0.0" });

    app.ontoolinput = function (params) {
      const args = params.arguments || {};
      const parts = [];
      if (args.query) parts.push('Query: "' + String(args.query) + '"');
      if (args.required_country) parts.push("Country: " + String(args.required_country));
      if (args.limit != null) parts.push("Limit: " + args.limit);
      if (args.offset != null) parts.push("Offset: " + args.offset);
      requestSummaryEl.textContent = parts.length ? parts.join(" · ") : "";
    };

    app.ontoolresult = ({ content }) => {
      const textPart = content && content.find(function (c) { return c.type === "text"; });
      if (!textPart || !textPart.text) return;
      try {
        const data = JSON.parse(textPart.text);
        if (data.error) {
          requestSummaryEl.textContent = "";
          summaryEl.textContent = "";
          tbody.innerHTML = "";
          setMessage(data.error, "error");
          return;
        }
        const raw = data.indicators;
        const indicators = Array.isArray(raw) ? raw : [];
        lastIndicators = indicators;
        lastTotalCount = data.total_count != null && Number.isFinite(data.total_count) ? data.total_count : null;
        if (indicators.length === 0) {
          requestSummaryEl.textContent = "";
          summaryEl.textContent = "0 indicators";
          tbody.innerHTML = "";
          setMessage("No indicators found.", "no-results");
          return;
        }
        render(indicators, filterInput.value, lastTotalCount);
      } catch (_e) {
        setMessage("Invalid tool result.", "error");
      }
    };

    filterInput.addEventListener("input", function () {
      render(lastIndicators, filterInput.value, lastTotalCount);
    });

    app.onhostcontextchanged = function (ctx) {
      if (ctx.theme) document.documentElement.setAttribute("data-theme", ctx.theme);
      if (ctx.safeAreaInsets) {
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
