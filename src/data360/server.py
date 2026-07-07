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
import sys
mcp_settings = get_mcp_server_settings()
if "--port" in sys.argv:
    try:
        _port_idx = sys.argv.index("--port")
        mcp_settings.port = int(sys.argv[_port_idx + 1])
    except (ValueError, IndexError):
        pass

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


from fastmcp import settings
settings.stateless_http = True

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


from pydantic import BaseModel
from typing import Any, Optional, Dict, List

class VizSpecRequest(BaseModel):
    database_id: str
    indicator_id: str
    country_code: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    disaggregation_filters: Optional[Dict[str, Optional[str]]] = None
    chart_type: Optional[str] = None
    relevant_fields: Optional[List[str]] = None
    chart_title: Optional[str] = None
    series_labels: Optional[Dict[str, str]] = None

class CritiqueRequest(BaseModel):
    spec: Dict[str, Any]
    query: str
    expected_description: str
    openai_api_key: Optional[str] = None


@app.post("/api/viz-spec")
async def get_viz_spec_endpoint(req: VizSpecRequest):
    from data360 import visualization as data360_viz
    from data360.config import get_mcp_server_settings

    # Temporarily disable Charts API URL to force local static file storage
    settings = get_mcp_server_settings()
    old_charts_url = settings.charts_api_url
    settings.charts_api_url = None

    try:
        res = await data360_viz.get_viz_spec(
            database_id=req.database_id,
            indicator_id=req.indicator_id,
            country_code=req.country_code,
            start_year=req.start_year,
            end_year=req.end_year,
            disaggregation_filters=req.disaggregation_filters,
            chart_type=req.chart_type,
            relevant_fields=req.relevant_fields,
            chart_title=req.chart_title,
            series_labels=req.series_labels,
        )
    finally:
        # Restore Charts API URL setting
        settings.charts_api_url = old_charts_url

    if res.get("error"):
        return JSONResponse(status_code=400, content={"error": res.get("error")})

    url_str = res.get("url")
    spec = None
    if url_str:
        try:
            spec_id = url_str.split("/")[-1].replace("_vega.json", "")
            specs_dir = os.path.join(os.getcwd(), "static", "viz_specs")
            vega_path = os.path.join(specs_dir, f"{spec_id}_vega.json")
            if os.path.exists(vega_path):
                with open(vega_path, "r") as f:
                    spec = json.load(f)
        except Exception as e:
            _audit_logger.exception("Failed to read generated spec")
            return JSONResponse(status_code=500, content={"error": "Failed to read generated spec"})

    if not spec:
        return JSONResponse(status_code=500, content={"error": "Spec was generated but could not be retrieved from disk."})

    return {
        "spec": spec,
        "reason": res.get("reason"),
        "strategy": res.get("strategy")
    }


@app.post("/api/critique")
async def critique_endpoint(req: CritiqueRequest):
    old_api_key = os.environ.get("OPENAI_API_KEY")
    if req.openai_api_key:
        os.environ["OPENAI_API_KEY"] = req.openai_api_key

    if not os.environ.get("OPENAI_API_KEY"):
        return JSONResponse(
            status_code=400,
            content={"error": "OpenAI API key not configured. Please supply an openai_api_key in the request."}
        )

    try:
        from deepeval.test_case import LLMTestCase, SingleTurnParams
        from deepeval.metrics import GEval

        grammar_of_graphics_metric = GEval(
            name="Grammar of Graphics & FT Visual Vocabulary Correctness",
            criteria="""
            Determine if the Vega-Lite JSON specification maps optimally to the retrieved data shape based on the Financial Times Visual Vocabulary:
            1. Single-indicator multi-year trends MUST map to a continuous line chart.
            2. Multi-indicator datasets with incompatible units MUST map to separate vertical subplot panels sharing a synchronized timeline.
            3. Single-year multi-country datasets MUST map to horizontal bars to allow label space, or route X-axis to country to avoid summing values.
            4. Gaps in reporting years MUST use dashed lines.
            5. Single-year nominal charts MUST have their 'year' field parsed as a string to prevent JS Date auto-parsing errors.
            """,
            evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.INPUT],
            evaluation_steps=[
                "Inspect the input query and simulated dataframe shape (number of indicators, countries, years, and breakdowns).",
                "Inspect the actual output Vega-Lite JSON specification.",
                "Check if the X/Y encoding channels, mark types, facets, and resolving settings are optimal.",
                "Deduct points if values are overlaid in a single bar on a nominal X-axis without proper country separation.",
                "Verify that scale formatting, title styling, and tooltips match standard specifications."
            ],
            threshold=0.8
        )

        test_case = LLMTestCase(
            input=f"Query: '{req.query}' | Expected layout: {req.expected_description}",
            actual_output=json.dumps(req.spec, indent=2)
        )

        grammar_of_graphics_metric.measure(test_case)

        return {
            "score": grammar_of_graphics_metric.score,
            "reason": grammar_of_graphics_metric.reason,
            "success": grammar_of_graphics_metric.is_successful()
        }
    except Exception as e:
        _audit_logger.exception("Evaluation failed")
        return JSONResponse(status_code=500, content={"error": "Evaluation failed"})
    finally:
        if req.openai_api_key:
            if old_api_key:
                os.environ["OPENAI_API_KEY"] = old_api_key
            else:
                os.environ.pop("OPENAI_API_KEY", None)


# Mount static files FIRST (more specific path must come before catch-all)
static_dir = os.path.join(os.getcwd(), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
# Mount MCP app at root — the path="/mcp" in http_app() handles the /mcp route
app.mount("/", mcp_app)


# Tools and other resources are automatically registered via imports in mcp_server/__init__.py
# See src/data360/mcp_server/tools.py for tool definitions
