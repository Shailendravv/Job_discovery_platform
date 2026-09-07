"""Shared async HTTP utilities for ATS providers.

Provides fetch_json, fetch_text with configurable timeout, retry + backoff,
and SSRF-safe redirect control.
"""

import asyncio
import contextvars
import logging
import random
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

# Defaults
DEFAULT_TIMEOUT_MS = 10_000
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; job-app-ats/1.0)"


class HostThrottle:
    """Per-hostname min-interval throttle (max ~1 request/sec/host).

    Used only by the ingest CLI's batch runs across many companies on the
    same ATS host (e.g. many orgs under ``boards-api.greenhouse.io``). The
    live dashboard search path never sets this — it fetches one org at a
    time and does not need it — so it stays opt-in via a contextvar rather
    than a module-level global that would also throttle that path.
    """

    def __init__(self, min_interval_seconds: float = 1.0) -> None:
        self._min_interval = min_interval_seconds
        self._last_request: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, host: str) -> asyncio.Lock:
        lock = self._locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[host] = lock
        return lock

    async def wait(self, url: str) -> None:
        host = urlparse(url).hostname or ""
        if not host:
            return
        async with self._lock_for(host):
            last = self._last_request.get(host)
            now = time.monotonic()
            if last is not None:
                elapsed = now - last
                remaining = self._min_interval - elapsed
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_request[host] = time.monotonic()


_current_throttle: contextvars.ContextVar[Optional[HostThrottle]] = contextvars.ContextVar(
    "ats_host_throttle", default=None
)


def set_host_throttle(throttle: Optional[HostThrottle]) -> contextvars.Token:
    """Install a ``HostThrottle`` for the current context. Returns a reset token."""
    return _current_throttle.set(throttle)


def reset_host_throttle(token: contextvars.Token) -> None:
    _current_throttle.reset(token)


async def fetch_json(
    url: str,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    method: str = "GET",
    body: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    redirect: str = "follow",
) -> Any:
    """Fetch a URL and return parsed JSON.

    Parameters
    ----------
    url : str
        Target URL.
    timeout_ms : int
        Request timeout in milliseconds.
    method : str
        HTTP method (GET, POST, etc.).
    body : str or None
        Request body for POST requests.
    headers : dict or None
        Additional HTTP headers.
    redirect : str
        Redirect policy — "follow" or "error". Use "error" for SSRF protection.

    Returns
    -------
    Parsed JSON response.

    Raises
    ------
    httpx.HTTPStatusError
        On non-2xx status.
    httpx.RequestError
        On network errors or timeout.
    """
    res = await _fetch(url, timeout_ms=timeout_ms, method=method, body=body, headers=headers, redirect=redirect)
    return res.json()


async def fetch_text(
    url: str,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    method: str = "GET",
    body: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    redirect: str = "follow",
) -> str:
    """Fetch a URL and return the response body as text."""
    res = await _fetch(url, timeout_ms=timeout_ms, method=method, body=body, headers=headers, redirect=redirect)
    return res.text


async def _fetch(
    url: str,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    method: str = "GET",
    body: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    redirect: str = "follow",
) -> httpx.Response:
    """Low-level async HTTP request."""
    throttle = _current_throttle.get()
    if throttle is not None:
        await throttle.wait(url)

    request_headers = {
        "User-Agent": DEFAULT_USER_AGENT,
    }
    if headers:
        request_headers.update(headers)

    redirect_map = {"follow": True, "error": False}

    async with httpx.AsyncClient(timeout=timeout_ms / 1000.0, follow_redirects=redirect_map.get(redirect, True)) as client:
        if method.upper() == "GET":
            response = await client.get(url, headers=request_headers)
        elif method.upper() == "POST":
            content_type = "application/json" if body else None
            if content_type and "content-type" not in {k.lower() for k in request_headers}:
                request_headers["content-type"] = content_type
            response = await client.post(url, content=body, headers=request_headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if redirect == "error" and response.history:
            raise httpx.RequestError(f"Redirect blocked (SSRF protection) for {url}")

        response.raise_for_status()
        return response


async def fetch_with_retry(
    url: str,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    retries: int = 2,
    method: str = "GET",
    body: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    redirect: str = "follow",
) -> Any:
    """Fetch JSON with exponential backoff + jitter retry logic.

    Useful for providers like Ashby that have ~10s+ latency floors
    and rate-limit unauthenticated requests.

    Retries are skipped on 4xx client errors (except 429 rate-limit)
    since those are permanent and won't resolve with retries.
    """
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        if attempt > 0:
            backoff = 1000 * 2 ** (attempt - 1) + random.randint(0, 500)
            log.info("[http] retry %d/%d for %s — backing off %d ms", attempt, retries, url, backoff)
            await asyncio.sleep(backoff / 1000.0)

        try:
            return await fetch_json(url, timeout_ms=timeout_ms, method=method, body=body, headers=headers, redirect=redirect)
        except httpx.HTTPStatusError as e:
            # 4xx client errors (except 429 rate-limit) are permanent, skip retries
            if e.response is not None and 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                log.warning("[http] permanent client error %d for %s — not retrying", e.response.status_code, url)
                raise
            last_err = e
            log.warning("[http] attempt %d/%d failed for %s: %s", attempt + 1, retries + 1, url, e)
        except (httpx.RequestError, httpx.TimeoutException) as e:
            last_err = e
            log.warning("[http] attempt %d/%d failed for %s: %s", attempt + 1, retries + 1, url, e)

    raise last_err  # type: ignore[misc]
