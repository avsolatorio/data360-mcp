#!/usr/bin/env bash
# uv run fastmcp run src/data360/server.py --transport streamable-http --port 8022 --host 0.0.0.0

# fastmcp run src/data360/server.py --transport streamable-http --port 8022 --host 0.0.0.0

# uv run gunicorn -w 4 -k uvicorn.workers.UvicornWorker data360.server:app --error-logfile '-'

gunicorn -w 4 -k uvicorn.workers.UvicornWorker data360.server:app --error-logfile '-'
