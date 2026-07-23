#!/usr/bin/env bash
# uv run fastmcp run src/data360/server.py --transport streamable-http --port 8022

# Load .env file if it exists
if [ -f .env ]; then
    set -a  # automatically export all variables
    source .env
    set +a  # stop automatically exporting
fi

# Read transport and port from environment variables, with defaults
TRANSPORT=${MCP_TRANSPORT:-http}
PORT=${MCP_PORT:-8000}
UVICORN_WORKERS=${UVICORN_WORKERS:-4}
LOG_LEVEL=${LOG_LEVEL:-info}

# Force unbuffered Python stdout/stderr so logs stream to terminal immediately
export PYTHONUNBUFFERED=1

echo "MCP_TRANSPORT=$TRANSPORT MCP_PORT=$PORT UVICORN_WORKERS=$UVICORN_WORKERS LOG_LEVEL=$LOG_LEVEL"

# Ensure static vendor libraries exist in static/libs/
if [ ! -f "static/libs/vega.js" ]; then
    echo "Static vendor libraries missing in static/libs/. Syncing now..."
    python3 scripts/sync_static_libs.py
fi

# uv run fastmcp run src/data360/server.py --transport "${TRANSPORT}" --port "${PORT}"

uv run uvicorn data360.server:app --host 0.0.0.0 --port "${PORT}" --workers "${UVICORN_WORKERS}" --log-level "${LOG_LEVEL}"
