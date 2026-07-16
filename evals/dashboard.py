"""
Data360 MCP — Chart Quality Evaluation Dashboard
=================================================

A local web dashboard to run E2E chart quality scenarios, watch the agent
tool-call trace in real time, render the resulting Vega-Lite chart, and
view the DeepEval 0-10 score breakdown with written critique.

Run:
    uv run python evals/dashboard.py

Then open:  http://localhost:8099
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import json
import os
import sys
from pathlib import Path

import uvicorn
import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

# ── path setup ──────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

# Load env vars (.env.evals takes priority over .env)
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env.evals", override=False)
    load_dotenv(_REPO / ".env", override=False)
except ImportError:
    pass

# ── import shared eval helpers ───────────────────────────────────────────────
from evals.test_viz_scorer import SCENARIOS as _VIZ_SCENARIOS  # noqa: E402
from evals.test_viz_scorer import MCP_BASE_URL, REPORTS_DIR   # noqa: E402
STATIC_BASE = MCP_BASE_URL

# ── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(title="Chart Quality Eval Dashboard")

# Adapt the viz scorer scenario dicts to the dashboard format
SCENARIOS: list[dict] = [
    {
        "id": s["id"],
        "label": s["label"],
        "question": s.get("description", ""),
        "expected": (
            f"Indicator: {s.get('indicator_id') or s.get('search_query', 'search-resolved')} | "
            f"Countries: {s.get('country_code', 'default')} | "
            f"Years: {s.get('start_year', 'default')}–{s.get('end_year', 'default')}"
        ),
    }
    for s in _VIZ_SCENARIOS
]


# ── API routes ───────────────────────────────────────────────────────────────


@app.get("/api/scenarios")
def get_scenarios():
    return SCENARIOS


@app.get("/api/reports")
def list_reports():
    reports = []
    # Sort files by modification time descending (newest first)
    sorted_paths = sorted(
        REPORTS_DIR.glob("*.json"),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    for p in sorted_paths:
        try:
            data = json.loads(p.read_text())
            reports.append(
                {
                    "filename": p.name,
                    "scenario_id": data.get("scenario_id"),
                    "question": data.get("question", "")[:80],
                    "score": data.get("score_out_of_10"),
                    "timestamp": data.get("timestamp"),
                    "chart_url": data.get("chart_url"),
                }
            )
        except Exception:
            pass
    return reports


@app.get("/api/reports/{filename}")
def get_report(filename: str):
    path = REPORTS_DIR / filename
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "report not found"})
    return json.loads(path.read_text())


@app.get("/api/proxy-spec")
async def proxy_spec(url: str):
    """
    Server-side proxy: fetch a Vega-Lite spec JSON from any URL and return it.
    Required because chart specs may be stored on localhost:8001 (chatbot backend)
    which would be blocked by CORS if fetched directly from the browser.
    """
    from urllib.parse import urlparse
    urls_to_try = [url]
    try:
        parsed_base = urlparse(MCP_BASE_URL)
        active_port = parsed_base.port or 8021
        if "localhost:8000" in url:
            urls_to_try.append(url.replace("localhost:8000", f"localhost:{active_port}"))
        if "127.0.0.1:8000" in url:
            urls_to_try.append(url.replace("127.0.0.1:8000", f"localhost:{active_port}"))
    except Exception:
        pass

    last_exc = None
    for target_url in urls_to_try:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(target_url)
                r.raise_for_status()
                data = r.json()
                # The chatbot backend wraps the spec: {"id":..., "spec": {...}}
                # The MCP static files are bare Vega-Lite JSON.
                if "spec" in data and isinstance(data["spec"], dict):
                    return data["spec"]
                return data
        except Exception as exc:
            last_exc = exc
            continue

    return JSONResponse(status_code=502, content={"error": str(last_exc)})

@app.get("/api/mcp-health")
async def mcp_health():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{MCP_BASE_URL}/mcp/health")
            if r.status_code == 200:
                return {"status": "ok"}
    except Exception:
        pass
    return JSONResponse(status_code=503, content={"status": "offline"})

@app.post("/api/run/{scenario_id}")
async def run_scenario_stub(scenario_id: str):
    """Dashboard is read-only. Run evaluations via: uv run python evals/run_evals.py"""
    return JSONResponse(
        status_code=410,
        content={"error": "Run evaluations via CLI: uv run python evals/run_evals.py"},
    )


def _evt(event_type: str, data: dict) -> str:
    return json.dumps({"type": event_type, **data}) + "\n"


# ── HTML dashboard ───────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Data360 Chart Quality Evaluator</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/vega@5.30.0/build/vega.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-lite@5.21.0/build/vega-lite.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@6.26.0/build/vega-embed.min.js"></script>
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --surface2: #21262d;
    --surface3: #30363d;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #7d8590;
    --accent: #2f81f7;
    --accent-glow: rgba(47, 129, 247, 0.15);
    --green: #3fb950;
    --yellow: #d29922;
    --red: #f85149;
    --purple: #bc8cff;
    --orange: #ffa657;
    --teal: #39d353;
    --radius: 8px;
    --radius-lg: 12px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Inter', sans-serif;
    background: var(--bg);
    color: var(--text);
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ── Header ── */
  header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 0 24px;
    height: 56px;
    display: flex;
    align-items: center;
    gap: 16px;
    flex-shrink: 0;
  }
  .logo {
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 600;
    font-size: 15px;
  }
  .logo-icon {
    width: 28px; height: 28px;
    background: linear-gradient(135deg, var(--accent), var(--purple));
    border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    font-size: 14px;
  }
  .header-badge {
    background: var(--surface3);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 11px;
    color: var(--text-muted);
    margin-left: auto;
  }
  #server-status {
    display: flex; align-items: center; gap: 6px;
    font-size: 12px; color: var(--text-muted);
  }
  .status-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--surface3);
    transition: background 0.3s;
  }
  .status-dot.online { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .status-dot.offline { background: var(--red); }

  /* ── Layout ── */
  .layout {
    display: grid;
    grid-template-columns: 280px 1fr;
    flex: 1;
    overflow: hidden;
  }

  /* ── Sidebar ── */
  .sidebar {
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex; flex-direction: column;
    overflow: hidden;
  }
  .sidebar-section {
    padding: 12px 16px 8px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border);
  }
  .scenario-list {
    flex: 1; overflow-y: auto;
    padding: 8px 0;
  }
  .scenario-item {
    padding: 10px 16px;
    cursor: pointer;
    border-left: 3px solid transparent;
    transition: all 0.15s;
    display: flex; flex-direction: column; gap: 2px;
  }
  .scenario-item:hover { background: var(--surface2); }
  .scenario-item.active {
    border-left-color: var(--accent);
    background: var(--accent-glow);
  }
  .scenario-label {
    font-size: 13px; font-weight: 500; line-height: 1.3;
  }
  .scenario-meta {
    font-size: 11px; color: var(--text-muted); line-height: 1.3;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }

  /* Reports section */
  .reports-section { border-top: 1px solid var(--border); }
  .report-list { max-height: 200px; overflow-y: auto; padding: 4px 0; }
  .report-item {
    padding: 8px 16px;
    cursor: pointer;
    transition: background 0.15s;
    display: flex; align-items: center; gap: 8px;
  }
  .report-item:hover { background: var(--surface2); }
  .report-score {
    font-size: 11px; font-weight: 700;
    min-width: 30px;
    color: var(--green);
  }
  .report-score.mid { color: var(--yellow); }
  .report-score.low { color: var(--red); }
  .report-label { font-size: 11px; color: var(--text-muted); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .report-time { font-size: 10px; color: var(--surface3); }

  /* Summary Dashboard button & views */
  .summary-btn {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    margin: 12px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }
  .summary-btn:hover {
    background: var(--surface3);
    border-color: var(--accent);
  }
  .summary-btn.active {
    background: var(--accent-glow);
    border-color: var(--accent);
    color: var(--accent);
  }

  .summary-dashboard {
    padding: 32px;
    display: flex;
    flex-direction: column;
    gap: 24px;
    overflow-y: auto;
    height: 100%;
  }
  .summary-header {
    border-bottom: 1px solid var(--border);
    padding-bottom: 16px;
  }
  .metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
  }
  .metric-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    position: relative;
    overflow: hidden;
  }
  .metric-card::before {
    content: '';
    position: absolute;
    inset: 0;
    background: radial-gradient(ellipse at 50% 0%, var(--accent-glow), transparent 70%);
    pointer-events: none;
  }
  .metric-label {
    font-size: 10px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .metric-value {
    font-size: 28px;
    font-weight: 700;
    color: var(--text);
  }
  .charts-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
    gap: 20px;
  }
  .summary-chart-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .summary-chart-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text);
  }

  /* ── Main panel ── */
  .main { display: flex; flex-direction: column; overflow: hidden; }

  /* Question bar */
  .question-bar {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex; gap: 12px; align-items: flex-start;
    flex-shrink: 0;
  }
  .question-text {
    flex: 1;
    font-size: 14px; line-height: 1.5;
    color: var(--text);
  }
  .scenario-id-badge {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: var(--text-muted);
    background: var(--surface2);
    padding: 2px 6px;
    border-radius: 4px;
    margin-bottom: 4px;
  }
  .run-btn {
    background: linear-gradient(135deg, var(--accent), #1a6fd4);
    color: white;
    border: none; border-radius: var(--radius);
    padding: 10px 20px;
    font-size: 13px; font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    white-space: nowrap;
    display: flex; align-items: center; gap: 8px;
    flex-shrink: 0;
  }
  .run-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 16px rgba(47,129,247,0.3); }
  .run-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; box-shadow: none; }
  .run-btn .spinner {
    width: 14px; height: 14px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    display: none;
  }
  .run-btn.running .spinner { display: block; }

  /* Content area */
  .content-area {
    flex: 1; overflow-y: auto;
    display: grid;
    grid-template-columns: 1fr 380px;
    gap: 0;
  }

  /* Chart panel */
  .chart-panel {
    padding: 24px;
    border-right: 1px solid var(--border);
    display: flex; flex-direction: column; gap: 16px;
    overflow-y: auto;
  }
  .panel-title {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--text-muted);
    display: flex; align-items: center; gap: 8px;
  }
  #chart-container {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: visible;
    position: relative;
    width: 100%;
  }
  .chart-placeholder {
    text-align: center; color: var(--text-muted);
    display: flex; flex-direction: column; align-items: center; gap: 12px;
  }
  .chart-placeholder .icon { font-size: 40px; opacity: 0.3; }
  .chart-placeholder p { font-size: 13px; }
  .chart-meta {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 16px;
    display: none;
    gap: 16px;
    flex-wrap: wrap;
  }
  .chart-meta.visible { display: flex; }
  .meta-item { display: flex; flex-direction: column; gap: 2px; }
  .meta-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; }
  .meta-value { font-size: 13px; font-weight: 500; color: var(--text); }
  .strategy-badge {
    background: var(--accent-glow);
    color: var(--accent);
    border: 1px solid var(--accent);
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 11px; font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
  }

  /* Agent trace */
  .trace-container { display: flex; flex-direction: column; gap: 6px; }
  .trace-step {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 14px;
    animation: slideIn 0.2s ease;
  }
  @keyframes slideIn { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:translateY(0); } }
  .trace-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .trace-turn {
    background: var(--surface3);
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 10px; font-weight: 600; font-family: 'JetBrains Mono', monospace;
    color: var(--text-muted);
  }
  .trace-tool {
    font-size: 12px; font-weight: 600; font-family: 'JetBrains Mono', monospace;
    color: var(--accent);
  }
  .trace-tool.viz { color: var(--green); }
  .trace-args {
    font-size: 11px; font-family: 'JetBrains Mono', monospace;
    color: var(--text-muted);
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 80px; overflow: hidden;
  }
  .trace-result {
    font-size: 11px; color: var(--teal);
    margin-top: 4px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .status-msg {
    font-size: 12px; color: var(--text-muted);
    display: flex; align-items: center; gap: 8px;
    padding: 8px 0;
  }

  /* Score & critique panel */
  .score-panel { padding: 24px; overflow-y: auto; }
  .score-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 20px;
    text-align: center;
    margin-bottom: 16px;
    position: relative;
    overflow: hidden;
  }
  .score-card::before {
    content: '';
    position: absolute;
    inset: 0;
    background: radial-gradient(ellipse at 50% 0%, var(--accent-glow), transparent 70%);
    pointer-events: none;
  }
  .score-number {
    font-size: 56px; font-weight: 700;
    line-height: 1;
    color: var(--green);
    transition: color 0.3s;
  }
  .score-number.mid { color: var(--yellow); }
  .score-number.low { color: var(--red); }
  .score-denom { font-size: 20px; color: var(--text-muted); font-weight: 400; }
  .score-label { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

  .criteria-list { display: flex; flex-direction: column; gap: 10px; margin-bottom: 16px; }
  .criterion {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 14px;
  }
  .criterion-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
  .criterion-name { font-size: 12px; font-weight: 500; }
  .criterion-score { font-size: 12px; font-weight: 700; color: var(--text-muted); }
  .criterion-bar-bg {
    height: 4px; background: var(--surface3); border-radius: 2px; overflow: hidden;
  }
  .criterion-bar {
    height: 100%; border-radius: 2px;
    background: linear-gradient(90deg, var(--accent), var(--purple));
    transition: width 0.6s ease;
    width: 0;
  }

  .critique-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px;
    font-size: 12px; line-height: 1.6;
    color: var(--text);
    margin-bottom: 12px;
  }
  .critique-card p { color: var(--text-muted); }
  .critique-card ul { padding-left: 16px; margin-top: 8px; }
  .critique-card li { margin-bottom: 4px; color: var(--text-muted); }

  /* Empty state */
  .empty-main {
    flex: 1; display: flex; align-items: center; justify-content: center;
    flex-direction: column; gap: 12px; color: var(--text-muted);
    text-align: center; padding: 48px;
  }
  .empty-icon { font-size: 48px; opacity: 0.2; }
  .empty-title { font-size: 16px; font-weight: 500; color: var(--text); }
  .empty-sub { font-size: 13px; }

  @keyframes spin { to { transform: rotate(360deg); } }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--surface3); border-radius: 3px; }
</style>
</head>
<body>

<header>
  <div class="logo" onclick="showSummaryDashboard()" style="cursor:pointer">
    <div class="logo-icon">📊</div>
    Data360 Chart Quality Evaluator
  </div>
  <div id="server-status">
    <div class="status-dot" id="server-dot"></div>
    <span id="server-label">Checking server...</span>
  </div>
  <div class="header-badge">DeepEval · GPT-4o Judge · 0–10 Score</div>
</header>

<div class="layout">
  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="summary-btn" onclick="showSummaryDashboard()" id="summary-btn">
      <span style="font-size:14px">📈</span> Summary Dashboard
    </div>
    <div class="sidebar-section">Scenarios</div>
    <div class="scenario-list" id="scenario-list"></div>
    <div class="reports-section">
      <div class="sidebar-section" style="display:flex;justify-content:space-between;align-items:center">
        <span>Explorations</span>
        <button onclick="loadExplorations()" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:11px">↻ refresh</button>
      </div>
      <div class="report-list" id="exploration-list"></div>
    </div>
    <div class="reports-section">
      <div class="sidebar-section" style="display:flex;justify-content:space-between;align-items:center">
        <span>Past Reports</span>
        <button onclick="loadReports()" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:11px">↻ refresh</button>
      </div>
      <div class="report-list" id="report-list"></div>
    </div>
  </aside>

  <!-- Main panel -->
  <main class="main" id="main-panel">
    <div class="empty-main">
      <div class="empty-icon">🎯</div>
      <div class="empty-title">Select a scenario to begin</div>
      <div class="empty-sub">Choose a scenario from the sidebar, then click Run Evaluation<br>to watch the agent call MCP tools and generate a chart.</div>
    </div>
  </main>
</div>

<script>
const MCP_BASE = '__MCP_BASE__';
let activeScenario = null;
let runController = null;

// ── Server health check ──────────────────────────────────────────────────────
async function checkServer() {
  try {
    const r = await fetch('/api/mcp-health');
    const data = await r.json();
    const ok = r.ok && data.status === 'ok';
    document.getElementById('server-dot').className = 'status-dot ' + (ok ? 'online' : 'offline');
    document.getElementById('server-label').textContent = ok ? 'MCP server online' : 'MCP server offline';
  } catch {
    document.getElementById('server-dot').className = 'status-dot offline';
    document.getElementById('server-label').textContent = 'MCP server unreachable';
  }
}
checkServer();
setInterval(checkServer, 10000);

// ── Load scenarios ───────────────────────────────────────────────────────────
// ── Load scenarios ───────────────────────────────────────────────────────────
let allScenarios = [];
async function loadScenarios() {
  const r = await fetch('/api/scenarios');
  allScenarios = await r.json();
  const list = document.getElementById('scenario-list');
  list.innerHTML = '';
  allScenarios.forEach(s => {
    const el = document.createElement('div');
    el.className = 'scenario-item';
    el.dataset.id = s.id;
    el.innerHTML = `
      <div class="scenario-label">${s.label}</div>
      <div class="scenario-meta">${s.question}</div>`;
    el.onclick = () => selectScenario(s);
    list.appendChild(el);
  });
}

// ── Load exploration reports ─────────────────────────────────────────────────
// Groups rnd_* reports by scenario ID, shows each with its latest score.
async function loadExplorations() {
  const r = await fetch('/api/reports');
  const reports = await r.json();
  const list = document.getElementById('exploration-list');
  list.innerHTML = '';

  // Collect rnd_* scenario IDs not in the fixed scenario list
  const fixedIds = new Set(allScenarios.map(s => s.id));
  const explorationMap = new Map(); // scenario_id -> most recent report
  reports.forEach(rep => {
    const sid = rep.scenario_id || '';
    if ((sid.startsWith('rnd_') || sid.startsWith('target_') || sid.startsWith('exp_')) && !fixedIds.has(sid)) {
      if (!explorationMap.has(sid)) {
        explorationMap.set(sid, rep); // reports are already sorted newest-first
      }
    }
  });

  if (!explorationMap.size) {
    list.innerHTML = '<div style="padding:12px 16px;font-size:11px;color:var(--text-muted)">No explorations yet. Run explore_chart_types.py</div>';
    return;
  }

  // Sort by scenario ID alphabetically
  const sorted = [...explorationMap.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  sorted.forEach(([sid, rep]) => {
    const score = rep.score;
    const cls = score == null ? '' : score >= 7 ? '' : score >= 4 ? 'mid' : 'low';
    const el = document.createElement('div');
    el.className = 'report-item';
    const label = sid.replace(/^(rnd_\d+|exp_\d+|target)_/, '').replace(/_/g, ' ');
    const index = sid.match(/^(rnd|exp)_(\d+)/)?.[2] || '';
    el.innerHTML = `
      <span class="report-score ${cls}">${score != null ? score : '?'}</span>
      <span class="report-label" title="${sid}">${index ? index + ' ' : ''}${label}</span>`;
    el.onclick = () => loadReport(rep.filename);
    list.appendChild(el);
  });
}

// ── Load past reports ────────────────────────────────────────────────────────
async function loadReports() {
  const r = await fetch('/api/reports');
  const reports = await r.json();
  const list = document.getElementById('report-list');
  list.innerHTML = '';
  if (!reports.length) {
    list.innerHTML = '<div style="padding:12px 16px;font-size:11px;color:var(--text-muted)">No reports yet</div>';
    return;
  }
  reports.slice(0, 20).forEach(rep => {
    const score = rep.score;
    const cls = score == null ? '' : score >= 7 ? '' : score >= 4 ? 'mid' : 'low';
    const el = document.createElement('div');
    el.className = 'report-item';
    el.innerHTML = `
      <span class="report-score ${cls}">${score != null ? score : '?'}</span>
      <span class="report-label">${rep.scenario_id || rep.question}</span>`;
    el.onclick = () => loadReport(rep.filename);
    list.appendChild(el);
  });
}

// ── Select scenario ──────────────────────────────────────────────────────────
async function selectScenario(s) {
  activeScenario = s;
  document.querySelectorAll('.scenario-item').forEach(el => el.classList.remove('active'));
  document.querySelector(`[data-id="${s.id}"]`)?.classList.add('active');
  document.getElementById('summary-btn')?.classList.remove('active');
  renderMainPanel(s);

  // Auto-load the most recent report for this scenario.
  try {
    const r = await fetch('/api/reports');
    const reports = await r.json();
    const match = reports.find(rep => rep.scenario_id === s.id);
    if (match) {
      loadReport(match.filename);
    } else {
      const container = document.getElementById('version-select-container');
      if (container) container.innerHTML = '';
    }
  } catch {}
}

function showSummaryDashboard() {
  activeScenario = null;
  document.querySelectorAll('.scenario-item').forEach(el => el.classList.remove('active'));
  document.getElementById('summary-btn')?.classList.add('active');

  const main = document.getElementById('main-panel');
  main.innerHTML = `
    <div class="summary-dashboard">
      <div class="summary-header">
        <div style="font-size:20px;font-weight:600;color:var(--text);margin-bottom:4px">📊 DeepEval Quality Overview</div>
        <div style="font-size:12px;color:var(--text-muted)">Aggregated metrics across the latest evaluation reports</div>
      </div>
      <div class="metrics-grid">
        <div class="metric-card">
          <div class="metric-label">Overall Average Score</div>
          <div class="metric-value" id="agg-avg-score">—</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Pass Rate (≥ 7.0)</div>
          <div class="metric-value" id="agg-pass-rate">—</div>
        </div>
        <div class="metric-card">
          <div class="metric-label">Scenarios Evaluated</div>
          <div class="metric-value" id="agg-total-count">—</div>
        </div>
      </div>
      <div class="charts-grid">
        <div class="summary-chart-card">
          <div class="summary-chart-title">DeepEval Score Distribution</div>
          <div id="chart-score-dist" style="width:100%;height:220px"></div>
        </div>
        <div class="summary-chart-card">
          <div class="summary-chart-title">Average Score by Strategy Category</div>
          <div id="chart-score-category" style="width:100%;height:220px"></div>
        </div>
      </div>
    </div>
  `;

  // Fetch reports and build charts
  fetch('/api/reports')
    .then(r => r.json())
    .then(reports => refreshSummaryDashboard(reports))
    .catch(err => console.error('Failed to load summary metrics:', err));
}

function refreshSummaryDashboard(reports) {
  // Find the latest report for each scenario_id
  const latestMap = new Map();
  // reports is already sorted newest-first
  reports.forEach(rep => {
    const sid = rep.scenario_id;
    if (sid && !latestMap.has(sid)) {
      latestMap.set(sid, rep);
    }
  });

  const latestReports = Array.from(latestMap.values());
  const scores = latestReports.map(r => r.score).filter(s => s != null);

  if (scores.length === 0) {
    const scoreVal = document.getElementById('agg-avg-score');
    if (scoreVal) scoreVal.textContent = '—';
    const passVal = document.getElementById('agg-pass-rate');
    if (passVal) passVal.textContent = '—';
    const countVal = document.getElementById('agg-total-count');
    if (countVal) countVal.textContent = '0';
    return;
  }

  const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
  const passes = scores.filter(s => s >= 7.0).length;
  const passRate = (passes / scores.length) * 100;

  const scoreVal = document.getElementById('agg-avg-score');
  if (scoreVal) scoreVal.textContent = `${avg.toFixed(1)}/10`;
  const passVal = document.getElementById('agg-pass-rate');
  if (passVal) passVal.textContent = `${passRate.toFixed(0)}%`;
  const countVal = document.getElementById('agg-total-count');
  if (countVal) countVal.textContent = latestReports.length;

  // 1. Build score distribution data
  const ranges = [
    { range: "0.0 - 3.9", count: 0 },
    { range: "4.0 - 6.9", count: 0 },
    { range: "7.0 - 8.9", count: 0 },
    { range: "9.0 - 10.0", count: 0 }
  ];
  scores.forEach(s => {
    if (s < 4.0) ranges[0].count++;
    else if (s < 7.0) ranges[1].count++;
    else if (s < 9.0) ranges[2].count++;
    else ranges[3].count++;
  });

  // 2. Build category average data
  const catScores = {};
  latestReports.forEach(r => {
    let cat = r.strategy || 'unknown';
    // Clean up category labels for display
    if (cat === 'temporal_single') cat = 'Line';
    else if (cat === 'temporal_multi_indicator') cat = 'Multi-Indicator';
    else if (cat === 'cross_sectional') cat = 'Bar';
    else if (cat === 'stacked_bar') cat = 'Stacked Bar';
    else if (cat === 'stacked_area') cat = 'Stacked Area';
    else if (cat === 'correlation') cat = 'Scatter';
    else if (cat === 'correlation_temporal') cat = 'Connected Scatter';
    else if (cat === 'distribution') cat = 'Strip Plot';
    else if (cat === 'heatmap') cat = 'Heatmap';
    else if (cat === 'choropleth') cat = 'Choropleth Map';
    else if (cat === 'small_multiples') cat = 'Small Multiples';
    else if (cat === 'chained') cat = 'Chained';
    else if (cat === 'pop_pyramid') cat = 'Pop Pyramid';
    else if (cat === 'wgi_confidence') cat = 'Confidence Band';

    // Capitalize first letter if not mapped
    if (cat === 'unknown' || !['Line','Multi-Indicator','Bar','Stacked Bar','Stacked Area','Scatter','Connected Scatter','Strip Plot','Heatmap','Choropleth Map','Small Multiples','Chained','Pop Pyramid','Confidence Band'].includes(cat)) {
      cat = cat.charAt(0).toUpperCase() + cat.slice(1).replace(/_/g, ' ');
    }

    if (r.score != null) {
      if (!catScores[cat]) catScores[cat] = [];
      catScores[cat].push(r.score);
    }
  });

  const categoryData = Object.entries(catScores).map(([cat, valList]) => {
    const catAvg = valList.reduce((a, b) => a + b, 0) / valList.length;
    return { category: cat, avgScore: parseFloat(catAvg.toFixed(1)) };
  });

  // Embed Vega-lite specs
  if (typeof vegaEmbed !== 'undefined') {
    const distSpec = {
      "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
      "description": "DeepEval Score Distribution",
      "width": "container",
      "height": 180,
      "data": { "values": ranges },
      "mark": "bar",
      "encoding": {
        "x": {
          "field": "range",
          "type": "nominal",
          "axis": { "title": "Score Range", "labelAngle": 0 },
          "sort": ["0.0 - 3.9", "4.0 - 6.9", "7.0 - 8.9", "9.0 - 10.0"]
        },
        "y": {
          "field": "count",
          "type": "quantitative",
          "axis": { "title": "Number of Scenarios", "tickMinStep": 1 }
        },
        "color": {
          "field": "range",
          "type": "nominal",
          "scale": {
            "domain": ["0.0 - 3.9", "4.0 - 6.9", "7.0 - 8.9", "9.0 - 10.0"],
            "range": ["#f87171", "#fbbf24", "#60a5fa", "#34d399"]
          },
          "legend": null
        }
      },
      "config": {
        "background": "transparent",
        "view": { "stroke": null },
        "font": "Inter, system-ui, sans-serif",
        "axis": { "gridColor": "#30363d", "tickColor": "#30363d", "labelColor": "#8b949e", "titleColor": "#c9d1d9" }
      }
    };

    const catSpec = {
      "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
      "description": "Average Score by Chart Category",
      "width": "container",
      "height": 180,
      "data": { "values": categoryData },
      "mark": { "type": "bar", "color": "#58a6ff" },
      "encoding": {
        "x": {
          "field": "avgScore",
          "type": "quantitative",
          "scale": { "domain": [0, 10] },
          "axis": { "title": "Average Score" }
        },
        "y": {
          "field": "category",
          "type": "nominal",
          "axis": { "title": null },
          "sort": { "field": "avgScore", "order": "descending" }
        }
      },
      "config": {
        "background": "transparent",
        "view": { "stroke": null },
        "font": "Inter, system-ui, sans-serif",
        "axis": { "gridColor": "#30363d", "tickColor": "#30363d", "labelColor": "#8b949e", "titleColor": "#c9d1d9" }
      }
    };

    const el1 = document.getElementById('chart-score-dist');
    if (el1) vegaEmbed('#chart-score-dist', distSpec, { actions: false });
    const el2 = document.getElementById('chart-score-category');
    if (el2) vegaEmbed('#chart-score-category', catSpec, { actions: false });
  }
}

async function populateVersionSelector(scenarioId, activeFilename) {
  function parseTimestamp(ts) {
    if (!ts) return new Date(0);
    const match = String(ts).match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/);
    if (match) {
      return new Date(
        parseInt(match[1]),
        parseInt(match[2]) - 1,
        parseInt(match[3]),
        parseInt(match[4]),
        parseInt(match[5]),
        parseInt(match[6])
      );
    }
    const d = new Date(ts);
    return isNaN(d.getTime()) ? new Date(0) : d;
  }

  try {
    const r = await fetch('/api/reports');
    const reports = await r.json();
    const matches = reports.filter(rep => rep.scenario_id === scenarioId);

    // Sort matches chronologically (oldest first)
    matches.sort((a, b) => parseTimestamp(a.timestamp) - parseTimestamp(b.timestamp));

    const container = document.getElementById('version-select-container');
    if (!container) return;

    if (matches.length <= 1) {
      container.innerHTML = '';
      return;
    }

    let html = `<select class="version-select" onchange="loadReport(this.value)" style="background:var(--surface2);border:1px solid var(--border);color:var(--text);border-radius:4px;padding:2px 8px;font-size:11px;outline:none;cursor:pointer">`;
    matches.forEach((rep, idx) => {
      const isSelected = rep.filename === activeFilename ? 'selected' : '';
      const scoreStr = rep.score != null ? `${rep.score}/10` : '?/10';
      const parsedDate = parseTimestamp(rep.timestamp);
      const timeStr = parsedDate.getTime() > 0 ? parsedDate.toLocaleString() : 'unknown';
      html += `<option value="${rep.filename}" ${isSelected}>Version ${idx + 1} (${scoreStr}) — ${timeStr}</option>`;
    });
    html += `</select>`;
    container.innerHTML = html;
  } catch (err) {
    console.error('Failed to populate version selector:', err);
  }
}

function renderMainPanel(s) {
  const mode = s.id.includes('chained') ? 'chained_viz' : ((s.id.includes('rank') || s.id.includes('compare') || s.id.includes('summarize')) ? 'data' : 'viz');
  const main = document.getElementById('main-panel');
  main.innerHTML = `
    <div class="question-bar">
      <div style="flex:1">
        <div style="display:flex;align-items:center;margin-bottom:6px">
          <div class="scenario-id-badge">${s.id}</div>
          <div id="version-select-container" style="margin-left:12px"></div>
        </div>
        <div class="question-text">${s.question}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:4px">Expected: ${s.expected || '—'}</div>
      </div>
      <div style="flex-shrink:0;text-align:right">
        <div style="font-size:10px;color:var(--text-muted);margin-bottom:4px">Run via terminal:</div>
        <code style="font-family:'JetBrains Mono',monospace;font-size:11px;background:var(--surface2);border:1px solid var(--border);border-radius:4px;padding:4px 10px;color:var(--accent);white-space:nowrap">uv run python evals/run_evals.py ${s.id.slice(0,2)}</code>
      </div>
    </div>
    <div class="content-area">
      <div class="chart-panel">
        <div class="panel-title">📈 Generated Chart / Data</div>
        <div id="chart-container">
          <div class="chart-placeholder">
            <div class="icon">📊</div>
            <p>No report yet for this scenario.</p>
            <p style="font-size:11px;margin-top:4px">Run: <code style="font-family:monospace;color:var(--accent)">uv run python evals/run_evals.py ${s.id.slice(0,2)}</code></p>
          </div>
        </div>
        <div class="chart-meta" id="chart-meta">
          <div class="meta-item">
            <div class="meta-label">Strategy</div>
            <div class="meta-value" id="meta-strategy">—</div>
          </div>
          <div class="meta-item">
            <div class="meta-label">Reason</div>
            <div class="meta-value" id="meta-reason" style="max-width:300px;font-size:12px">—</div>
          </div>
        </div>
        <div class="panel-title">🔍 Agent Tool Trace</div>
        <div class="trace-container" id="trace-container">
          <div style="font-size:12px;color:var(--text-muted)">Tool calls will stream here as the agent runs...</div>
        </div>
      </div>
      <div class="score-panel">
        <div class="panel-title" style="margin-bottom:12px">🏆 Evaluation Score</div>
        <div class="score-card">
          <div class="score-number" id="score-number">—</div>
          <div class="score-label">out of 10 · DeepEval G-Eval</div>
        </div>
        <div class="criteria-list" id="criteria-list">
          ${renderCriteria(null, mode)}
        </div>
        <div class="panel-title" style="margin-bottom:10px">💬 Critique</div>
        <div class="critique-card" id="critique-text">
          <p style="color:var(--text-muted)">Critique will appear after scoring completes...</p>
        </div>
      </div>
    </div>`;
}

function renderCriteria(scoreTotal, mode = 'viz') {
  const isChained = mode === 'chained_viz';
  const isData = mode === 'data';
  const criteria = isChained ? [
    { name: 'Data Alignment', max: 2 },
    { name: 'Sorting Coherence', max: 2 },
    { name: 'Chart Type Fit', max: 2 },
    { name: 'Mutation & Data Loss', max: 2 },
    { name: 'Readability & Attribution', max: 2 },
  ] : (isData ? [
    { name: 'Data Presence', max: 2 },
    { name: 'Correctness', max: 2 },
    { name: 'Completeness', max: 2 },
    { name: 'Statistical Coherence', max: 2 },
    { name: 'Actionability', max: 2 },
  ] : [
    { name: 'Data Relevance', max: 2 },
    { name: 'Chart Type Fit', max: 2 },
    { name: 'Grammar of Graphics', max: 2 },
    { name: 'Readability', max: 2 },
    { name: 'Routing Correctness', max: 2 },
  ]);
  return criteria.map(c => `
    <div class="criterion">
      <div class="criterion-header">
        <span class="criterion-name">${c.name}</span>
        <span class="criterion-score" id="crit-${c.name.replace(/ /g,'-')}">${scoreTotal != null ? '?' : '—'}/2</span>
      </div>
      <div class="criterion-bar-bg">
        <div class="criterion-bar" id="bar-${c.name.replace(/ /g,'-')}" style="width:0"></div>
      </div>
    </div>`).join('');
}

// ── Run scenario ─────────────────────────────────────────────────────────────
async function runScenario() {
  if (!activeScenario) return;
  const btn = document.getElementById('run-btn');
  btn.disabled = true;
  btn.classList.add('running');
  document.getElementById('run-label').textContent = 'Running...';

  const traceEl = document.getElementById('trace-container');
  traceEl.innerHTML = '';

  const addStatus = (msg) => {
    const el = document.createElement('div');
    el.className = 'status-msg';
    el.innerHTML = `<span style="color:var(--accent)">⟳</span> ${msg}`;
    traceEl.appendChild(el);
    traceEl.scrollTop = traceEl.scrollHeight;
  };

  try {
    const resp = await fetch('/api/run/' + activeScenario.id, { method: 'POST' });
    if (!resp.ok) {
      const err = await resp.json();
      addStatus('Error: ' + (err.error || 'Unknown error'));
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try { handleEvent(JSON.parse(line), addStatus); } catch {}
      }
    }
  } finally {
    btn.disabled = false;
    btn.classList.remove('running');
    document.getElementById('run-label').textContent = '▶ Run Evaluation';
    loadReports();
  }
}

function handleEvent(evt, addStatus) {
  const traceEl = document.getElementById('trace-container');

  if (evt.type === 'status') {
    addStatus(evt.message);

  } else if (evt.type === 'heartbeat') {
    // keep-alive, no UI update needed

  } else if (evt.type === 'trace') {
    const isViz = ['data360_get_viz_spec','data360_get_multi_indicator_viz_spec'].includes(evt.tool);
    const el = document.createElement('div');
    el.className = 'trace-step';
    const args = JSON.stringify(evt.args || {}, null, 2);
    el.innerHTML = `
      <div class="trace-header">
        <span class="trace-turn">Turn ${evt.turn}</span>
        <span class="trace-tool ${isViz ? 'viz' : ''}">${evt.tool}</span>
      </div>
      <div class="trace-args">${escHtml(args.length > 300 ? args.slice(0, 300) + '…' : args)}</div>
      <div class="trace-result">→ ${escHtml(evt.result_summary || '')}</div>`;
    traceEl.appendChild(el);
    traceEl.scrollTop = traceEl.scrollHeight;

  } else if (evt.type === 'agent_error') {
    addStatus('⚠ Agent error: ' + evt.message);

  } else if (evt.type === 'error') {
    addStatus('✗ ' + evt.message);

  } else if (evt.type === 'done') {
    const mode = (activeScenario && activeScenario.id.includes('chained')) ? 'chained_viz' : ((activeScenario && (activeScenario.id.includes('rank') || activeScenario.id.includes('compare') || activeScenario.id.includes('summarize'))) ? 'data' : 'viz');
    renderDone(evt, mode);
  }
}

function renderDone(evt, mode = 'viz') {
  // Chart or Data view
  const chartUrl = evt.chart_url;
  const container = document.getElementById('chart-container');
  const meta = document.getElementById('chart-meta');

  if (chartUrl) {
    const absUrl = chartUrl.startsWith('http') ? chartUrl : MCP_BASE + chartUrl;
    const proxyUrl = '/api/proxy-spec?url=' + encodeURIComponent(absUrl);

    let dataSection = '';
    if (evt.tool_data) {
      dataSection = `
        <div style="border-top: 1px solid var(--border); margin-top: 16px; padding: 16px 16px 16px;">
          <details>
            <summary style="font-size: 12px; color: var(--green); font-weight: 600; cursor: pointer; user-select: none;">
              ✓ Stage 1 Data Retrieval Output (Click to expand)
            </summary>
            <pre style="margin-top: 8px; max-height: 200px; background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px; font-family:'JetBrains Mono',monospace; font-size: 11px; color: var(--text); overflow: auto; white-space: pre-wrap; text-align: left">${escHtml(JSON.stringify(evt.tool_data, null, 2))}</pre>
          </details>
        </div>`;
    }

    container.innerHTML = `<div id="vega-embed-target" style="width:100%;padding:16px 16px 0"></div>${dataSection}`;

    if (typeof vegaEmbed === 'undefined') {
      container.innerHTML = `<div class="chart-placeholder"><div class="icon">⚠</div><p>Chart library (vega-embed) failed to load from CDN. Check your network connection and reload the page.</p><p style="font-size:11px;margin-top:4px"><a href="${absUrl}" target="_blank" style="color:var(--accent)">Open raw JSON</a></p></div>`;
      return;
    }

    fetch(proxyUrl)
      .then(r => {
        if (!r.ok) {
          return r.json().then(err => { throw new Error(err.error || `HTTP status ${r.status}`); }, () => { throw new Error(`HTTP status ${r.status}`); });
        }
        return r.json();
      })
      .then(spec => {
        if (spec && spec.error) {
          throw new Error(spec.error);
        }
        const panelW = container.offsetWidth - 32; // minus padding
        const fitted = {
          ...spec,
          width: panelW > 0 ? panelW : 'container',
          autosize: { type: 'fit', contains: 'padding' },
        };
        return vegaEmbed('#vega-embed-target', fitted, {
          actions: { export: true, source: false, compiled: false, editor: false },
          renderer: 'svg',
        });
      })
      .catch(err => {
        container.innerHTML = `<div class="chart-placeholder"><div class="icon">⚠</div><p>Could not render chart: ${err.message}</p><p style="font-size:11px;margin-top:4px"><a href="${absUrl}" target="_blank" style="color:var(--accent)">Open raw JSON</a></p></div>`;
      });


    meta.classList.add('visible');
    document.getElementById('meta-strategy').innerHTML =
      `<span class="strategy-badge">${evt.strategy || 'unknown'}</span>`;
    document.getElementById('meta-reason').textContent = evt.reason || '—';
  } else {
    // If we have tool_data, render it as a beautifully scrollable JSON block
    if (evt.tool_data) {
      container.innerHTML = `
        <div style="padding:16px;height:100%;display:flex;flex-direction:column;gap:8px;overflow:hidden">
          <div style="font-size:12px;color:var(--green);font-weight:600;display:flex;align-items:center;gap:6px">
            <span>✓ Data Tool Output</span>
          </div>
          <pre style="flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:12px;font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text);overflow:auto;white-space:pre-wrap;text-align:left">${escHtml(JSON.stringify(evt.tool_data, null, 2))}</pre>
        </div>`;
    } else {
      const errMsg = evt.viz_error ? `<p style="font-size:12px;color:var(--red);margin-top:8px">${escHtml(evt.viz_error)}</p>` : '';
      container.innerHTML = `
        <div class="chart-placeholder">
          <div class="icon">❌</div>
          <p>No chart was generated</p>
          ${errMsg}
        </div>`;
    }
    meta.classList.remove('visible');
  }

  // Score
  const score = evt.score;
  const scoreEl = document.getElementById('score-number');
  if (score != null) {
    scoreEl.textContent = score;
    scoreEl.className = 'score-number' + (score >= 7 ? '' : score >= 4 ? ' mid' : ' low');

    // Distribute score across 5 criteria (proportional, since we only have total)
    const perCrit = (score / 10);
    const names = mode === 'viz'
      ? ['Data-Relevance','Chart-Type-Fit','Grammar-of-Graphics','Readability','Routing-Correctness']
      : (mode === 'chained_viz'
         ? ['Data-Alignment','Sorting-Coherence','Chart-Type-Fit','Mutation-&-Data-Loss','Readability-&-Attribution']
         : ['Data-Presence','Correctness','Completeness','Statistical-Coherence','Actionability']);
    names.forEach(n => {
      const bar = document.getElementById('bar-' + n);
      if (bar) bar.style.width = (perCrit * 100) + '%';
      const lbl = document.getElementById('crit-' + n);
      if (lbl) lbl.textContent = '~/2';
    });
  } else {
    scoreEl.textContent = '—';
  }

  // Critique
  const critiqueEl = document.getElementById('critique-text');
  if (evt.critique) {
    critiqueEl.innerHTML = `<p>${escHtml(evt.critique)}</p>`;
  }
}

// ── Load a past report ───────────────────────────────────────────────────────
let _activeReportFilename = '';
async function loadReport(filename) {
  _activeReportFilename = filename;
  const r = await fetch('/api/reports/' + filename);
  const data = await r.json();

  // Find scenario details from allScenarios using data.scenario_id
  const matched = allScenarios.find(s => s.id === data.scenario_id);
  const s = {
    id: data.scenario_id,
    question: matched ? matched.question : (data.question || data.description || 'Scenario details unknown'),
    expected: matched ? matched.expected : '—'
  };
  activeScenario = s;
  document.querySelectorAll('.scenario-item').forEach(el => el.classList.remove('active'));
  document.querySelector(`[data-id="${s.id}"]`)?.classList.add('active');
  renderMainPanel(s);

  // Populate trace
  const traceEl = document.getElementById('trace-container');
  traceEl.innerHTML = '';
  const traceSteps = data.agent_trace || [];
  if (traceSteps.length === 0) {
    traceEl.innerHTML = '<div style="font-size:12px;color:var(--text-muted);font-style:italic">No tool calls recorded (direct viz/data pipeline execution).</div>';
  } else {
    traceSteps.forEach(step => {
      const isViz = ['data360_get_viz_spec','data360_get_multi_indicator_viz_spec'].includes(step.tool);
      const el = document.createElement('div');
      el.className = 'trace-step';
      const args = JSON.stringify(step.args || {}, null, 2);
      el.innerHTML = `
        <div class="trace-header">
          <span class="trace-turn">Turn ${step.turn}</span>
          <span class="trace-tool ${isViz ? 'viz' : ''}">${step.tool}</span>
        </div>
        <div class="trace-args">${escHtml(args.length > 300 ? args.slice(0, 300) + '…' : args)}</div>
        <div class="trace-result">→ ${escHtml(step.result_summary || '')}</div>`;
      traceEl.appendChild(el);
    });
  }

  // Populate score + chart
  const mode = s.id.includes('chained') ? 'chained_viz' : ((s.id.includes('rank') || s.id.includes('compare') || s.id.includes('summarize')) ? 'data' : 'viz');
  renderDone({
    score: data.score_out_of_10,
    critique: data.critique,
    chart_url: data.chart_url,
    strategy: data.strategy,
    reason: data.reason,
    viz_error: data.viz_error,
    tool_data: data.tool_data,
  }, mode);

  // Populate the version select container
  await populateVersionSelector(s.id, filename);
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}


// ── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  await loadScenarios();
  loadReports();
  loadExplorations();
  showSummaryDashboard();
}
init();

// ── Auto-refresh: poll for new reports every 5 s ─────────────────────────────
let _lastReportCount = 0;
let _lastReportTopFilename = '';
setInterval(async () => {
  try {
    const r = await fetch('/api/reports');
    const reports = await r.json();
    const topFilename = reports[0]?.filename || '';
    // Refresh list if a new report appeared
    if (reports.length !== _lastReportCount || topFilename !== _lastReportTopFilename) {
      _lastReportCount = reports.length;
      _lastReportTopFilename = topFilename;
      loadReports();
      loadExplorations();
      // If there is an active scenario, auto-load its newest report
      if (activeScenario) {
        const match = reports.find(rep => rep.scenario_id === activeScenario.id);
        if (match && match.filename !== _activeReportFilename) {
          loadReport(match.filename);
        }
      } else {
        refreshSummaryDashboard(reports);
      }
    }
  } catch { /* server may be restarting */ }
}, 5000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    html = _HTML.replace("__MCP_BASE__", MCP_BASE_URL)
    return HTMLResponse(html)


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 8099))
    print(f"\n  📊  Chart Quality Eval Dashboard")
    print(f"  Open: http://localhost:{port}\n")
    uvicorn.run("evals.dashboard:app", host="0.0.0.0", port=port, reload=False)
