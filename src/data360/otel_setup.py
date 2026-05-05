"""OpenTelemetry setup: Azure Monitor (deployed), OTLP/console (local), httpx outbound spans."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

if TYPE_CHECKING:
    from data360.config import MCPServerSettings

_logger = logging.getLogger(__name__)

_HTTPX_INSTRUMENTED = False
_MIN_TRANSPORT_PARTS_FOR_URL = 2


def data360_operation_from_url(url: str | None) -> str:  # noqa: PLR0911
    """Derive a stable operation label for spans from the outbound request URL (no query logged)."""
    if not url:
        return "http"
    try:
        path = urlparse(url).path.lower()
    except Exception:
        return "http"
    if "searchv2" in path:
        return "search"
    if "metadata" in path:
        return "metadata"
    if "disaggregation" in path:
        return "disaggregation"
    # Avoid matching .../metadata/... "data" substring before generic data path
    if path.rstrip("/").endswith("/data") or "/data360/data" in path:
        return "data"
    if "codelist" in path:
        return "codelist"
    if path.rstrip("/").endswith("/indicators"):
        return "indicators"
    if "chart" in path or "vega" in path:
        return "charts"
    return "http"


def _httpx_request_hook(span, request: object) -> None:
    """Attach Data360-specific attributes; never log bodies or full URLs with secrets."""
    try:
        if span is None:
            return
        is_recording = getattr(span, "is_recording", None)
        if callable(is_recording) and not is_recording():
            return
        url_str: str | None = None
        if isinstance(request, tuple) and len(request) >= _MIN_TRANSPORT_PARTS_FOR_URL:
            url_str = str(request[1])
        else:
            req_any = cast("Any", request)
            url_attr = getattr(req_any, "url", None)
            if url_attr is not None:
                url_str = str(url_attr)
        op = data360_operation_from_url(url_str)
        span.set_attribute("data360.operation", op)
        if url_str:
            try:
                parsed = urlparse(url_str)
                netloc = parsed.netloc.split("@")[-1]
                span.set_attribute("server.address", netloc.split(":")[0])
            except Exception:
                pass
    except Exception:
        pass


def _httpx_response_hook(span, request: object, response: object) -> None:
    """Record outcome; avoid logging bodies."""
    try:
        if span is None:
            return
        is_recording = getattr(span, "is_recording", None)
        if callable(is_recording) and not is_recording():
            return
        status = getattr(response, "status_code", None)
        if status is not None:
            span.set_attribute("http.response.status_code", int(status))
    except Exception:
        pass


def configure_open_telemetry_for_server(settings: MCPServerSettings) -> None:
    """Configure trace export: Azure Monitor when deployed; OTLP or console when local."""
    connection_string = settings.azure_connection_string or os.environ.get(
        "APPLICATIONINSIGHTS_CONNECTION_STRING"
    )
    env = (settings.env or "").lower()

    if env != "local" and connection_string:
        try:
            from azure.monitor.opentelemetry import (  # type: ignore[import-untyped]  # noqa: PLC0415
                configure_azure_monitor,
            )

            configure_azure_monitor(connection_string=connection_string)
            _logger.info("Azure Monitor OpenTelemetry configured.")
        except ImportError:
            _logger.warning("azure-monitor-opentelemetry not available.")
        return

    # Local / no Azure: optional OTLP (Jaeger, collector) or console exporter
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
    )
    console = os.environ.get("MCP_OTEL_CONSOLE", "").lower() in ("1", "true", "yes")

    if not endpoint and not console:
        _logger.debug(
            "Local telemetry: no OTLP endpoint and MCP_OTEL_CONSOLE unset; "
            "traces use noop unless OTEL_* env configures a provider elsewhere."
        )
        return

    from opentelemetry import trace  # noqa: PLC0415
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # noqa: PLC0415
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415

    service_name = os.environ.get("OTEL_SERVICE_NAME", "data360-mcp")
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    if console:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter  # noqa: PLC0415

        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        _logger.info("OpenTelemetry console span export enabled (MCP_OTEL_CONSOLE).")

    if endpoint:
        try:
            use_http = endpoint.startswith(("http://", "https://"))
            proto = os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "").lower()
            if proto in ("http/protobuf", "http/json"):
                use_http = True
            if use_http:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
                    OTLPSpanExporter,
                )
            else:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415
                    OTLPSpanExporter,
                )

            exporter = OTLPSpanExporter()
            provider.add_span_processor(BatchSpanProcessor(exporter))
            _logger.info(
                "OpenTelemetry OTLP trace export enabled (endpoint from OTEL_EXPORTER_OTLP_*)."
            )
        except Exception:
            _logger.exception("Failed to configure OTLP trace exporter; traces may be incomplete.")

    trace.set_tracer_provider(provider)


def instrument_httpx_outbound() -> None:
    """Patch httpx so all AsyncClient/Client requests emit dependency spans."""
    global _HTTPX_INSTRUMENTED  # noqa: PLW0603
    if _HTTPX_INSTRUMENTED:
        return
    try:
        from opentelemetry.instrumentation.httpx import (  # noqa: PLC0415
            HTTPXClientInstrumentor,
        )

        HTTPXClientInstrumentor().instrument(
            request_hook=_httpx_request_hook,
            response_hook=_httpx_response_hook,
        )
        _HTTPX_INSTRUMENTED = True
        _logger.info("HTTPX OpenTelemetry instrumentation enabled.")
    except ImportError:
        _logger.warning("opentelemetry-instrumentation-httpx not installed.")
