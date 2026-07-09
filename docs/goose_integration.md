# Goose MCP Client Visualization Integration Guide

This guide documents the technical architecture, challenges, and solutions implemented to enable rich, interactive, and theme-adaptive Vega-Lite visualizations within the Goose agentic desktop application using the `data360-mcp` server.

---

## Architecture Overview

Goose supports visual rendering of tool results by launching a sandboxed iframe. The communication between the Goose client and the iframe runs over JSON-RPC message passing via `window.parent.postMessage`.

To bypass strict network and security limitations, we serve a self-contained custom HTML application:
- **Resource URI:** `ui://data360-chart/index.html` (registered as a FastMCP custom resource).
- **Tool Configuration:** `data360_get_viz_spec` and `data360_get_multi_indicator_viz_spec` return the Vega-Lite specification payload while registering `app=AppConfig(resource_uri="ui://data360-chart/index.html")`.
- **Layout Strategy:** Uses standard Vega-Lite spec sizing combined with a dynamic size-reporting protocol to resize the iframe card.

---

## Technical Challenges & Solutions

### 1. Network Constraints (CDN Blocking)
*   **Challenge:** Standard FastMCP / Prefab UI components try to download React/Vue dependencies and CSS from external CDNs (like `cdn.jsdelivr.net` or `unpkg.com`). Because Goose runs iframes in a strict sandboxed environment without internet access, these requests fail, rendering a blank card stating *"Waiting for content..."*.
*   **Solution:** Enable local script bundling by setting `PREFAB_BUNDLED_RENDERER=1` in the environment before loading the MCP app. This forces the server to serve local cached JS assets.

### 2. Handshake Protocol (Zod Validation Errors)
*   **Challenge:** Custom HTML apps must negotiate a handshake with the host client using the Goose App Protocol. Initializing with empty parameters (e.g. `ui/initialize`) throws a Zod schema validation error in the Goose client:
    ```json
    "error": {"code": -32603, "message": "[{\"expected\": \"object\", \"code\": \"invalid_type\", \"path\": [\"params\", \"appInfo\"]}]"}
    ```
*   **Solution:** The custom Javascript RPC wrapper client must pass all required schema fields during initialization:
    ```javascript
    const result = await this.request('ui/initialize', {
      appInfo: { name: 'Data360 Chart', version: '1.0.0' },
      appCapabilities: {},
      protocolVersion: '2025-11-21'
    });
    ```

### 3. Content Security Policy (`unsafe-eval` restriction)
*   **Challenge:** Standard Vega-Lite embeds compile chart configurations dynamically using JavaScript's `new Function()`. Goose enforces a Content Security Policy (CSP) blocking `unsafe-eval`. When trying to compile, it throws a runtime crash:
    ```text
    Evaluating a string as JavaScript violates the following Content Security Policy directive...
    ```
*   **Solution:** Include `vega-interpreter.js` (an AST expression parser that evaluates Vega-Lite expressions without calling `eval` or `new Function`) in the resource static asset bundle. Configure the `vegaEmbed` call to run in interpreter mode:
    ```javascript
    vegaEmbed("#vis", spec, {
      actions: false,
      theme: mcpApp.hostContext?.theme === 'dark' ? 'dark' : 'default',
      ast: true,
      expr: vega.expressionInterpreter
    })
    ```

### 4. Dynamic Iframe Sizing (Vertical Clipping)
*   **Challenge:** Iframes default to a fixed CSS height. If a horizontal bar chart has many categories (e.g. 10 economies) or a line chart contains complex legends, it will overflow and be clipped by the iframe container.
*   **Solution:** After rendering completes, report the exact `scrollHeight` of the body to the host using a size-changed notification:
    ```javascript
    this.notify('ui/notifications/size-changed', {
      height: document.body.scrollHeight
    });
    ```
    This instructs Goose to automatically adjust the outer card frame to perfectly fit the chart.

### 5. Layout Sizing Recalculation Bugs
*   **Challenge:** Attempting to force both width and height constraints dynamically in JavaScript using `ResizeObserver` and `autosize: 'fit'` overrides the spec's calculated values. For charts with discrete steps (like 10 horizontal bars), forcing them into constrained heights reduces the plotting area too much, causing Vega-Lite's compiler to clip or drop the main titles entirely.
*   **Solution:** Keep rendering simple. Discard dynamic sizing observers in JavaScript. Let Vega-Lite use the spec's default sizes directly, allowing the height of the chart to grow naturally according to the category count calculated by Python, and let Goose resize the viewport container dynamically.

### 6. Title and Subtitle Array Formatting
*   **Challenge:** The CSP AST interpreter mode fails to calculate layout offsets correctly if `title.text` or `title.subtitle` are list-of-strings arrays (which occurs in Python when wrapping long titles with `textwrap.wrap`). This makes titles completely invisible.
*   **Solution:** Convert title and subtitle arrays into clean, single-line strings.
    - *Python layer (`spec_to_prefab`):* Join list titles with a space and subtitle elements with a dot (` · `).
    - *JavaScript client:* Convert list titles/subtitles to strings prior to rendering.

### 7. Adaptive Theme Synchronisation
*   **Challenge:** Visualizations must seamlessly adapt to Goose's Light/Dark mode changes to remain readable.
*   **Solution:** Resolve theme colors from the host environment:
    ```javascript
    theme: mcpApp.hostContext?.theme === 'dark' ? 'dark' : 'default'
    ```
