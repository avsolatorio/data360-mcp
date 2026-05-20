"""Liveness and readiness checks for the Data360 MCP HTTP server."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import httpx

from data360.config import get_data360_settings, get_mcp_server_settings
from data360.http_client import get_shared_httpx_client
from data360.providers import get_database_mapping

_SERVICE_NAME = "data360-mcp"
_PROBE_FILENAME = ".health_probe"
_CHARTS_UP_STATUS_CODES = frozenset({401, 403, 405, 422})


def _package_version() -> str:
    try:
        return version("data360")
    except PackageNotFoundError:
        return "unknown"


def get_liveness_body() -> dict[str, Any]:
    """Return the JSON body for GET /health (no outbound I/O)."""
    settings = get_mcp_server_settings()
    return {
        "status": "ok",
        "service": _SERVICE_NAME,
        "version": _package_version(),
        "env": settings.env,
    }


def _static_viz_specs_dir() -> Path:
    return Path(os.getcwd()) / "static" / "viz_specs"


async def _check_data360_api(timeout: float) -> dict[str, Any]:
    """Probe Data360 search API with a minimal dataset query."""
    data360 = get_data360_settings()
    url = data360.search_url or f"{data360.api_url}/searchv2"
    started = time.perf_counter()

    async def _probe() -> dict[str, Any]:
        client = get_shared_httpx_client()
        response = await client.post(
            url,
            headers={"accept": "*/*", "Content-Type": "application/json"},
            json={
                "filter": "type eq 'dataset'",
                "select": "series_description/database_id",
                "top": 1,
                "skip": 0,
            },
        )
        response.raise_for_status()
        response.json()
        return {
            "ok": True,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }

    try:
        return await asyncio.wait_for(_probe(), timeout=timeout)
    except TimeoutError:
        return {"ok": False, "detail": "timeout"}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "detail": f"http_{e.response.status_code}"}
    except httpx.RequestError:
        return {"ok": False, "detail": "connection_error"}
    except Exception:
        return {"ok": False, "detail": "probe_failed"}


async def _check_database_mapping() -> dict[str, Any]:
    """Verify the in-memory database_id → name cache is usable."""
    try:
        mapping = await get_database_mapping()
    except Exception:
        return {"ok": False, "detail": "mapping_unavailable", "count": 0}

    valid = [
        (k, v)
        for k, v in mapping.items()
        if isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
    ]
    count = len(mapping)
    if count == 0:
        return {"ok": False, "detail": "empty_cache", "count": 0, "source": "cache"}
    if not valid:
        return {
            "ok": False,
            "detail": "invalid_entries",
            "count": count,
            "source": "cache",
        }
    return {"ok": True, "count": count, "source": "cache"}


async def _check_static_writable() -> dict[str, Any]:
    """Verify static/viz_specs exists and accepts writes."""
    specs_dir = _static_viz_specs_dir()
    try:
        specs_dir.mkdir(parents=True, exist_ok=True)
        probe_path = specs_dir / _PROBE_FILENAME
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
        return {"ok": True}
    except OSError:
        return {"ok": False, "detail": "not_writable"}


async def _check_charts_api_reachable(timeout: float) -> dict[str, Any]:
    """Probe Charts API reachability without creating a chart."""
    charts_url = get_mcp_server_settings().charts_api_url
    if not charts_url:
        return {"ok": False, "detail": "not_configured"}

    started = time.perf_counter()

    async def _probe() -> dict[str, Any]:
        client = get_shared_httpx_client()
        response = await client.head(charts_url)
        if response.status_code >= 500:
            response.raise_for_status()
        if (
            response.status_code < 400
            or response.status_code in _CHARTS_UP_STATUS_CODES
        ):
            return {
                "ok": True,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        response.raise_for_status()
        return {"ok": True}

    try:
        return await asyncio.wait_for(_probe(), timeout=timeout)
    except TimeoutError:
        return {"ok": False, "detail": "timeout"}
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status in _CHARTS_UP_STATUS_CODES:
            return {
                "ok": True,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        return {"ok": False, "detail": f"http_{status}"}
    except httpx.RequestError:
        return {"ok": False, "detail": "connection_error"}
    except Exception:
        return {"ok": False, "detail": "probe_failed"}


async def _check_viz_storage(timeout: float) -> dict[str, Any]:
    """Check viz spec persistence: Charts API and/or static fallback."""
    settings = get_mcp_server_settings()
    static_result = await _check_static_writable()
    static_ok = static_result.get("ok", False)

    if settings.charts_api_url:
        charts_result = await _check_charts_api_reachable(timeout)
        charts_ok = charts_result.get("ok", False)
        ok = charts_ok or static_ok
        entry: dict[str, Any] = {
            "ok": ok,
            "primary": "charts_api",
            "fallback": "static",
            "charts_api": charts_result,
            "static": static_result,
        }
        if charts_ok:
            entry["backend"] = "charts_api"
        elif static_ok:
            entry["backend"] = "static"
        else:
            entry["detail"] = "charts_and_static_unavailable"
        return entry

    entry = {
        "ok": static_ok,
        "backend": "static",
        "primary": "static",
        "static": static_result,
    }
    if not static_ok:
        entry["detail"] = static_result.get("detail", "not_writable")
    return entry


async def _check_codelist_api(timeout: float) -> dict[str, Any]:
    """Optional probe for REF_AREA codelist API (non-blocking for readiness)."""
    data360 = get_data360_settings()
    url = f"{data360.api_url}/codelist"
    started = time.perf_counter()

    async def _probe() -> dict[str, Any]:
        client = get_shared_httpx_client()
        response = await client.get(url, params={"type": "REF_AREA"})
        response.raise_for_status()
        response.json()
        return {
            "ok": True,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }

    try:
        result = await asyncio.wait_for(_probe(), timeout=timeout)
        return result
    except TimeoutError:
        return {"ok": False, "detail": "timeout", "degraded": True}
    except httpx.HTTPStatusError as e:
        return {
            "ok": False,
            "detail": f"http_{e.response.status_code}",
            "degraded": True,
        }
    except httpx.RequestError:
        return {"ok": False, "detail": "connection_error", "degraded": True}
    except Exception:
        return {"ok": False, "detail": "probe_failed", "degraded": True}


def _critical_checks_ok(checks: dict[str, Any]) -> bool:
    for name in ("data360_api", "database_mapping", "viz_storage"):
        entry = checks.get(name)
        if not entry or not entry.get("ok"):
            return False
    return True


async def run_readiness() -> tuple[int, dict[str, Any]]:
    """Run dependency probes; return (HTTP status code, JSON body)."""
    settings = get_mcp_server_settings()
    if not settings.readiness_enabled:
        return 200, {
            "status": "ready",
            "checks": {},
            "readiness_checks": "disabled",
        }

    timeout = settings.health_check_timeout
    timestamp = datetime.now(UTC).isoformat()

    (
        data360_result,
        mapping_result,
        viz_result,
        codelist_result,
    ) = await asyncio.gather(
        _check_data360_api(timeout),
        _check_database_mapping(),
        _check_viz_storage(timeout),
        _check_codelist_api(timeout),
    )

    checks: dict[str, Any] = {
        "data360_api": data360_result,
        "database_mapping": mapping_result,
        "viz_storage": viz_result,
        "codelist_api": codelist_result,
    }

    if _critical_checks_ok(checks):
        return 200, {"status": "ready", "timestamp": timestamp, "checks": checks}
    return 503, {"status": "not_ready", "timestamp": timestamp, "checks": checks}
