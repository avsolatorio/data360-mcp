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

echo "MCP_TRANSPORT=$TRANSPORT MCP_PORT=$PORT UVICORN_WORKERS=$UVICORN_WORKERS"

# uv run fastmcp run src/data360/server.py --transport "${TRANSPORT}" --port "${PORT}"

uv run uvicorn data360.server:app --host 0.0.0.0 --port "${PORT}" --workers "${UVICORN_WORKERS}"
