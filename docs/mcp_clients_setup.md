# Data360 MCP Client Setup Guide

This guide describes how to configure the **Data360 MCP Server** for visual rendering and custom HTML apps on various clients, including **Claude Desktop**, **Goose**, and **VS Code**.

---

## 🚀 Port Configuration & Visual Rendering
The Data360 MCP server operates in two modes:
1. **Stdio Interface (MCP Protocol):** The client spawns the Python process and communicates with it via stdin/stdout.
2. **Static Web Server (Port 8021):** An auxiliary Uvicorn server runs in the background to host the custom HTML apps and generated Vega-Lite chart specifications.

Before running the server, make sure the static web server is running on port `8021`:
```bash
PREFAB_BUNDLED_RENDERER=1 uv run uvicorn data360.server:app --port 8021
```

---

## 1. Claude Desktop Setup
Claude Desktop spawns the server as a local stdio subprocess.

### Configuration Path
* **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

### Configuration Payload
Add the following entry under `"mcpServers"`:

```json
{
  "mcpServers": {
    "data360-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/Users/rafaelmacalaba/WBG/data360-mcp",
        "fastmcp",
        "run",
        "/Users/rafaelmacalaba/WBG/data360-mcp/src/data360/server.py"
      ],
      "env": {
        "PREFAB_BUNDLED_RENDERER": "1"
      }
    }
  }
}
```
*Replace `/Users/rafaelmacalaba/WBG/data360-mcp` with your actual local repository path.*

Restart **Claude Desktop** to apply the configuration. Charts will render directly inside the Claude chat window using local cached JavaScript libraries.

---

## 2. Goose Setup
Goose supports visual rendering using the `ui://` custom resource protocol.

### Configuration Path
* **Configuration File:** `~/.config/goose/config.yaml` or through the Goose UI settings.

### Configuration Payload
Under the `mcpServers` configuration, add:

```yaml
mcpServers:
  data360-mcp:
    command: "uv"
    args:
      - "run"
      - "--project"
      - "/Users/rafaelmacalaba/WBG/data360-mcp"
      - "fastmcp"
      - "run"
      - "/Users/rafaelmacalaba/WBG/data360-mcp/src/data360/server.py"
    env:
      PREFAB_BUNDLED_RENDERER: "1"
```

When you request charts (e.g. `data360_get_viz_spec`), the server returns the Vega-Lite spec and binds it to the custom app template URI `ui://data360-chart/index.html`. Goose renders the chart inside a secure sandboxed iframe card.

---

## 3. VS Code Setup
To use the MCP server inside VS Code (using extensions like **Cline**, **Roo Code**, or **Continue**):

### Configuration Payload (e.g., for Cline / Roo Code)
In your Cline or Roo Code extension settings (`cline_mcp_settings.json` located in `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`):

```json
{
  "mcpServers": {
    "data360-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/Users/rafaelmacalaba/WBG/data360-mcp",
        "fastmcp",
        "run",
        "/Users/rafaelmacalaba/WBG/data360-mcp/src/data360/server.py"
      ],
      "env": {
        "PREFAB_BUNDLED_RENDERER": "1"
      },
      "disabled": false
    }
  }
}
```

---

## 🛠 Troubleshooting CWD and Sandboxing Errors
If you see the error:
`OSError: [Errno 30] Read-only file system: '/static'`
or `No visualization spec available` in the iframe cards:
* **Cause:** The client spawned the server in a sandbox with the working directory set to `/`, causing it to try to write to `/static` or `/static/viz_specs`.
* **Solution:** Ensure you are using the latest version of the repository where path resolution has been updated to use script-relative resolution (`__file__`) instead of `os.getcwd()`.
