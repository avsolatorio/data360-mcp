"""Shared httpx.AsyncClient for connection reuse and consistent outbound behavior."""

from __future__ import annotations

import threading

import httpx

_DEFAULT_TIMEOUT = 30.0

_client: httpx.AsyncClient | None = None
_client_lock = threading.Lock()


def get_shared_httpx_client() -> httpx.AsyncClient:
    """Return a process-wide async HTTP client (lazy singleton)."""
    global _client  # noqa: PLW0603
    client = _client
    if client is not None and not client.is_closed:
        return client

    with _client_lock:
        client = _client
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
            _client = client
        return client


async def aclose_shared_httpx_client() -> None:
    """Close the shared client (call from ASGI shutdown)."""
    global _client  # noqa: PLW0603
    with _client_lock:
        client = _client
        _client = None

    if client is not None and not client.is_closed:
        await client.aclose()

