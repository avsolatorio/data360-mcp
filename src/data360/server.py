import hashlib
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from data360.config import get_mcp_server_settings, setup_logging
from data360.http_client import aclose_shared_httpx_client
from data360.otel_setup import (
    configure_open_telemetry_for_server,
    instrument_httpx_outbound,
)

_audit_logger = logging.getLogger("audit")

# Setup logging from configuration
mcp_settings = get_mcp_server_settings()
setup_logging(
    log_file=mcp_settings.log_file,
    log_level=mcp_settings.log_level,
    env=mcp_settings.env,
    azure_connection_string=mcp_settings.azure_connection_string,
)

# Tracer export (Azure in deployed envs; optional OTLP/console when MCP_ENV=local) and httpx spans
configure_open_telemetry_for_server(mcp_settings)
instrument_httpx_outbound()

# Import MCP after telemetry so the process uses an instrumented httpx from the first request.
from data360.mcp_server import mcp  # noqa: E402

_connection_string = mcp_settings.azure_connection_string or os.environ.get(
    "APPLICATIONINSIGHTS_CONNECTION_STRING"
)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Log structured audit entries for every MCP request."""

    async def dispatch(self, request: Request, call_next):
        # Only audit MCP tool/resource/prompt calls
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)
        session_id = str(uuid.uuid4())
        requestor_id = request.headers.get(
            "X-Forwarded-For", request.client.host if request.client else "unknown"
        )
        timestamp = datetime.now(UTC).isoformat()
        # Read and restore body so downstream handlers still receive it
        body_bytes = await request.body()
        prompt = ""
        prompt_hash = ""
        try:
            body = json.loads(body_bytes)
            method = body.get("method", "")
            params = body.get("params", {})
            prompt = json.dumps(
                {"method": method, "params": params}, separators=(",", ":")
            )
            prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        except Exception:
            pass
        response = await call_next(request)
        _audit_logger.info(
            "mcp_audit",
            extra={
                "custom_dimensions": {
                    "session_id": session_id,
                    "requestor_id": requestor_id,
                    "timestamp": timestamp,
                    "prompt": prompt,
                    "prompt_hash": prompt_hash,
                    "status_code": response.status_code,
                    "path": request.url.path,
                }
            },
        )
        return response


mcp.settings.stateless_http = True

# NOTE: import to be able to run the server with all definitions loaded
# path="/mcp" means the MCP endpoint lives at /mcp (no trailing slash needed)
mcp_app = mcp.http_app(path="/mcp")


@asynccontextmanager
async def _lifespan_with_http_cleanup(app: FastAPI):
    """Run MCP startup/shutdown, then close the shared httpx client."""
    async with mcp_app.router.lifespan_context(mcp_app):
        # Pre-fetch extdataportal codelists so dimension codes (COMP_BREAKDOWN,
        # SEX, AGE, URBANISATION, UNIT_MEASURE) resolve to human labels before
        # the first chart request arrives.  Mirrors GroupHierarchyManager.
        from data360.providers import get_codelist_manager

        await get_codelist_manager().initialize()
        yield
    await aclose_shared_httpx_client()


# https://gofastmcp.com/deployment/http#asgi-application
# redirect_slashes=False prevents 308 redirects between /mcp and /mcp/
app = FastAPI(
    title="Data360 MCP Server",
    lifespan=_lifespan_with_http_cleanup,
    redirect_slashes=False,
)  # pyright: ignore[reportUnusedExpression]

app.add_middleware(AuditLogMiddleware)

# Instrument FastAPI for incoming request tracking
if mcp_settings.env != "local" and _connection_string:
    try:
        from opentelemetry.instrumentation.fastapi import (
            FastAPIInstrumentor,  # type: ignore[import-untyped]
        )

        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        pass

# Mount static files FIRST (more specific path must come before catch-all)
static_dir = os.path.join(os.getcwd(), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
# Mount MCP app at root — the path="/mcp" in http_app() handles the /mcp route
app.mount("/", mcp_app)


# Tools and other resources are automatically registered via imports in mcp_server/__init__.py
# See src/data360/mcp_server/tools.py for tool definitions
