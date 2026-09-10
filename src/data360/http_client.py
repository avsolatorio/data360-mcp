"""Shared httpx.AsyncClient: connection reuse, split timeouts, bounded retries.

One client per process (per gunicorn worker), reused by every Data360 API call.
The resilience policy for that dependency lives here:

* **Split timeouts.** Connect/read/write/pool are configured independently via
  ``Data360Settings``. A single flat 30 s timeout previously let one stalled
  downstream call hold an MCP tool request open for 30 s.
* **Bounded retries with exponential backoff and jitter** for transient failures
  (timeouts, connection errors, ``retry_status_codes``). ``retry_budget_seconds``
  caps the wall-clock time spent retrying a single request, so worst-case latency
  stays bounded instead of multiplying by ``retry_max_attempts``.
* **Retries are opt-in for non-idempotent methods.** GET/HEAD/OPTIONS/TRACE are
  always retried; POST (and other mutating methods) are retried only when the
  caller marks a read-only query with ``extensions={RETRY_SAFE_EXTENSION: True}``.
  The Data360 search/metadata/dimensions endpoints are read-only POSTs and set
  that marker; write endpoints such as the Charts API do not, so a timed-out
  write is never replayed.
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time

import httpx

from .config import get_data360_settings

_logger = logging.getLogger(__name__)

# Request extension marking a read-only request as safe to retry (see module docstring).
RETRY_SAFE_EXTENSION = "data360_retry_safe"

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Transport-level failures worth a second attempt. TimeoutException covers
# connect/read/write/pool timeouts; the rest cover refused/dropped connections.
_RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)

_client: httpx.AsyncClient | None = None
_client_lock = threading.Lock()


async def _sleep(delay: float) -> None:
    await asyncio.sleep(delay)


# Indirection so tests can assert retry timing without sleeping.
_RETRY_SLEEP = _sleep


class _RetryingTransport(httpx.AsyncHTTPTransport):
    """Retry transient failures for requests that are safe to replay."""

    def __init__(
        self,
        *,
        max_attempts: int,
        budget_seconds: float,
        backoff_base: float,
        backoff_max: float,
        retry_status_codes: frozenset[int],
    ) -> None:
        super().__init__()
        self._max_attempts = max(1, max_attempts)
        self._budget_seconds = budget_seconds
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._retry_status_codes = retry_status_codes

    @staticmethod
    def _retry_allowed(request: httpx.Request) -> bool:
        return (
            request.method in _IDEMPOTENT_METHODS
            or request.extensions.get(RETRY_SAFE_EXTENSION) is True
        )

    async def _backoff(
        self, request: httpx.Request, attempt: int, reason: BaseException | None
    ) -> None:
        delay = min(self._backoff_max, self._backoff_base * (2 ** (attempt - 1)))
        # Equal jitter keeps clients from retrying in lockstep without giving up
        # the exponential growth between consecutive delays.
        delay = random.uniform(delay / 2, delay)
        if reason is None:
            detail = "retryable status"
        else:
            message = str(reason).strip()
            detail = (
                f"{type(reason).__name__}: {message}"
                if message
                else type(reason).__name__
            )
        _logger.warning(
            "Retrying %s %s (attempt %d/%d) in %.2fs after %s",
            request.method,
            request.url.path,
            attempt + 1,
            self._max_attempts,
            delay,
            detail,
        )
        await _RETRY_SLEEP(delay)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        attempts = self._max_attempts if self._retry_allowed(request) else 1
        deadline = time.monotonic() + self._budget_seconds

        for attempt in range(1, attempts + 1):
            try:
                response = await super().handle_async_request(request)
            except _RETRYABLE_EXCEPTIONS as exc:
                if attempt >= attempts or time.monotonic() >= deadline:
                    raise
                await self._backoff(request, attempt, exc)
                continue

            if (
                response.status_code in self._retry_status_codes
                and attempt < attempts
                and time.monotonic() < deadline
            ):
                await response.aclose()
                await self._backoff(request, attempt, None)
                continue

            return response

        raise AssertionError("retry loop exited without a response")  # pragma: no cover


def _build_client() -> httpx.AsyncClient:
    settings = get_data360_settings()
    timeout = httpx.Timeout(
        connect=settings.connect_timeout,
        read=settings.read_timeout,
        write=settings.write_timeout,
        pool=settings.pool_timeout,
    )
    transport = _RetryingTransport(
        max_attempts=settings.retry_max_attempts,
        budget_seconds=settings.retry_budget_seconds,
        backoff_base=settings.retry_backoff_base,
        backoff_max=settings.retry_backoff_max,
        retry_status_codes=frozenset(settings.retry_status_codes),
    )
    return httpx.AsyncClient(timeout=timeout, transport=transport)


def get_shared_httpx_client() -> httpx.AsyncClient:
    """Return a process-wide async HTTP client (lazy singleton)."""
    global _client  # noqa: PLW0603
    client = _client
    if client is not None and not client.is_closed:
        return client

    with _client_lock:
        client = _client
        if client is None or client.is_closed:
            client = _build_client()
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
