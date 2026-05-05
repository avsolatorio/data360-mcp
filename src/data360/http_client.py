"""Shared httpx.AsyncClient for connection reuse and consistent outbound behavior."""

from __future__ import annotations

import httpx

_DEFAULT_TIMEOUT = 30.0

_client: httpx.AsyncClient | None = None


def get_shared_httpx_client() -> httpx.AsyncClient:
    """Return a process-wide async HTTP client (lazy singleton)."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
    return _client


async def aclose_shared_httpx_client() -> None:
    """Close the shared client (call from ASGI shutdown)."""
    global _client  # noqa: PLW0603
    if _client is not None:
        await _client.aclose()
        _client = None


def reset_shared_httpx_client_for_tests() -> None:
    """Sync reset for pytest (clears singleton without async close when unused)."""
    global _client  # noqa: PLW0603
    _client = None
