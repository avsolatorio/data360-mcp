import hashlib
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from data360.config import get_mcp_server_settings, setup_logging
from data360.health import get_liveness_body, run_readiness
from data360.http_client import aclose_shared_httpx_client
from data360.otel_setup import (
    configure_open_telemetry_for_server,
    instrument_httpx_outbound,
)

_audit_logger = logging.getLogger("audit")
_telemetry_client = None

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

# Initialize OpenCensus TelemetryClient for custom events (forwarded to Splunk)
if mcp_settings.env != "local" and _connection_string:
    try:
        from opencensus.ext.azure.log_exporter import (
            AzureEventHandler,  # type: ignore[import-untyped]
        )

        # Create a dedicated logger for custom events
        event_logger = logging.getLogger("customEvents")
        event_logger.setLevel(logging.INFO)

        # Add Azure handler that sends to customEvents table
        azure_handler = AzureEventHandler(connection_string=_connection_string)
        event_logger.addHandler(azure_handler)

        _telemetry_client = event_logger
    except ImportError:
        pass


class SecurityValidationMiddleware(BaseHTTPMiddleware):
    """Validate MCP tool calls to prevent prompt injection and unauthorized access."""

    async def dispatch(self, request: Request, call_next):
        # Only validate MCP JSON-RPC tool calls (not health probes under /mcp/*)
        if request.url.path in ("/mcp/health", "/mcp/ready"):
            return await call_next(request)
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)

        try:
            # Read and parse body
            body_bytes = await request.body()
            if not body_bytes:
                return await call_next(request)

            body = json.loads(body_bytes)
            method = body.get("method", "")

            # Log tools/list requests for monitoring (allowed but monitored)
            if method == "tools/list":
                client_ip = request.headers.get(
                    "X-Forwarded-For",
                    request.client.host if request.client else "unknown",
                )
                logging.info(f"tools/list called from IP: {client_ip}")

            # Validate tools/call requests
            if method == "tools/call":
                from data360.mcp_server.security_validator import (  # noqa: PLC0415
                    validate_search_arguments,
                    validate_tool_call,
                )

                params = body.get("params", {})
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})

                # Validate tool call
                is_valid, error_msg = validate_tool_call(tool_name, arguments)
                if not is_valid:
                    logging.warning(
                        f"Security violation: {error_msg} | Tool: {tool_name}"
                    )
                    return JSONResponse(
                        status_code=403,
                        content={
                            "jsonrpc": "2.0",
                            "id": body.get("id"),
                            "error": {"code": -32001, "message": error_msg},
                        },
                    )

                # Additional validation for all search term inputs
                if tool_name == "data360_search_indicators":
                    is_valid, error_msg = validate_search_arguments(arguments)
                    if not is_valid:
                        logging.warning(
                            "Search query blocked: %s",
                            str(arguments)[:200],
                        )
                        return JSONResponse(
                            status_code=403,
                            content={
                                "jsonrpc": "2.0",
                                "id": body.get("id"),
                                "error": {"code": -32001, "message": error_msg},
                            },
                        )

        except json.JSONDecodeError:
            pass  # Let MCP handle invalid JSON
        except Exception as e:
            logging.error(f"Security validation error: {e}")
            # Continue on validation errors to avoid blocking legitimate requests

        return await call_next(request)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Log structured audit entries for every MCP request."""

    async def dispatch(self, request: Request, call_next):
        # Only audit MCP JSON-RPC calls (not health probes)
        if request.url.path in ("/mcp/health", "/mcp/ready"):
            return await call_next(request)
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

        properties = {
            "session_id": session_id,
            "requestor_id": requestor_id,
            "timestamp": timestamp,
            "prompt": prompt,
            "prompt_hash": prompt_hash,
            "status_code": str(response.status_code),
            "path": request.url.path,
        }

        # Log to traces with custom dimensions
        _audit_logger.info("mcp_audit", extra={"custom_dimensions": properties})

        # Also log as custom event for Splunk forwarding
        if _telemetry_client:
            _telemetry_client.info(
                "MCP_Request",
                extra={
                    "custom_dimensions": properties,
                    "event_name": "MCP_Request",
                },
            )

        return response


mcp.settings.stateless_http = True

# NOTE: import to be able to run the server with all definitions loaded
# path="/mcp" means the MCP endpoint lives at /mcp (no trailing slash needed)
mcp_app = mcp.http_app(path="/mcp")


async def health_check(request: StarletteRequest) -> JSONResponse:
    """Liveness probe under the MCP URL prefix (GET /mcp/health)."""
    del request
    return JSONResponse(get_liveness_body())


async def ready_check(request: StarletteRequest) -> JSONResponse:
    """Readiness probe under the MCP URL prefix (GET /mcp/ready)."""
    del request
    status_code, body = await run_readiness()
    return JSONResponse(content=body, status_code=status_code)


# Starlette routes on mcp_app: paths are absolute from mount root (not nested under /mcp).
# Use /mcp/health so probes sit beside the streamable HTTP endpoint at /mcp.
mcp_app.add_route("/mcp/health", health_check, methods=["GET", "HEAD"])
mcp_app.add_route("/mcp/ready", ready_check, methods=["GET", "HEAD"])


@asynccontextmanager
async def _lifespan_with_http_cleanup(app: FastAPI):
    """Run MCP startup/shutdown, then close the shared httpx client."""
    async with mcp_app.router.lifespan_context(mcp_app):
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
# SecurityValidationMiddleware is enabled for incoming request validation.
app.add_middleware(SecurityValidationMiddleware)

# Instrument FastAPI for incoming request tracking
if mcp_settings.env != "local" and _connection_string:
    try:
        from opentelemetry.instrumentation.fastapi import (
            FastAPIInstrumentor,  # type: ignore[import-untyped]
        )

        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        pass


@app.get("/")
async def root():
    return {
        "service": "data360-mcp",
        "health": "/mcp/health",
        "ready": "/mcp/ready",
        "mcp": "/mcp",
    }


# Mount static files FIRST (more specific path must come before catch-all)
static_dir = os.path.join(os.getcwd(), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
# Mount MCP app at root — the path="/mcp" in http_app() handles the /mcp route
app.mount("/", mcp_app)


# Tools and other resources are automatically registered via imports in mcp_server/__init__.py
# See src/data360/mcp_server/tools.py for tool definitions
