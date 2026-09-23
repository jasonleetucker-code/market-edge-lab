"""Read-only HTTP retrieval with bounded retries and per-request provenance.

This module can only issue GET requests. There is deliberately no code path for
POST/PUT/DELETE, request signing, or credentials: order submission is out of
scope for this repository until an explicit owner decision changes that.
"""

from __future__ import annotations

import http.client
import json
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DEFAULT_USER_AGENT = "market-edge-lab/0.1"
# Status codes worth retrying: throttling and transient server failures.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_SECONDS = 30.0
# Credential-bearing headers are refused outright: this client is unauthenticated.
_FORBIDDEN_HEADER_PARTS = ("authoriz", "cookie", "api-key", "apikey", "access-key", "signature", "token")
# Response headers kept on a FetchResult. Only this allowlist, lowercased: quota counters
# (The Odds API) carry no secret. Everything else, cookies included, is dropped.
RESPONSE_HEADER_ALLOWLIST = ("x-requests-remaining", "x-requests-used", "x-requests-last")


class HttpFetchError(RuntimeError):
    """Raised when a public data endpoint cannot be fetched or decoded."""

    def __init__(self, message: str, *, status: int | None = None, attempts: int = 1) -> None:
        super().__init__(message)
        self.status = status
        self.attempts = attempts


class ResponseDecodeError(HttpFetchError):
    """The server answered, but the body was not the JSON object we expected."""


class Pacer:
    """Minimum interval between requests to one source (polite, not maximal, throughput).

    Kalshi's public endpoints returned 429 at ~4 requests/s sustained (2026-09-22 probe) and
    send no Retry-After header, so pacing, not retrying, is the normal control flow.
    """

    def __init__(self, min_interval_s: float, *, clock=time.monotonic, sleep=time.sleep) -> None:
        self.min_interval_s = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last is not None:
                remaining = self.min_interval_s - (now - self._last)
                if remaining > 0:
                    self._sleep(remaining)
                    now = self._clock()
            self._last = now


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    http_status: int
    content_type: str | None
    body: bytes
    received_at_utc: str
    duration_ms: int
    attempts: int
    # One entry per failed attempt before success, e.g. "http_429", "URLError".
    retry_reasons: tuple[str, ...] = ()
    # Allowlisted response headers only (RESPONSE_HEADER_ALLOWLIST), as (lowercase name, value).
    response_headers: tuple[tuple[str, str], ...] = ()


def allowlisted_headers(headers: Any) -> tuple[tuple[str, str], ...]:
    """The allowlisted headers of a response, lowercased, in allowlist order; first value wins."""
    if not headers:
        return ()
    try:
        items = list(headers.items())
    except AttributeError:
        return ()
    found: dict[str, str] = {}
    for name, value in items:
        key = str(name).lower()
        if key in RESPONSE_HEADER_ALLOWLIST and key not in found:
            found[key] = str(value)
    return tuple((name, found[name]) for name in RESPONSE_HEADER_ALLOWLIST if name in found)


Opener = Callable[[Request, float], Any]


def _default_opener(request: Request, timeout: float) -> Any:
    return urlopen(request, timeout=timeout)


def _retry_after_seconds(exc: HTTPError) -> float | None:
    value = exc.headers.get("Retry-After") if exc.headers else None
    if value is None:
        return None
    try:
        return min(max(float(value), 0.0), MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        return None  # HTTP-date form; fall back to our own backoff


def fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    retries: int = 2,
    backoff: float = 1.0,
    opener: Opener | None = None,
    sleep: Callable[[float], None] = time.sleep,
    pacer: Pacer | None = None,
    jitter: Callable[[], float] = random.random,
) -> FetchResult:
    """GET `url`, retrying only transient failures (network errors, 429, 5xx).

    Other 4xx responses fail immediately: retrying a bad request wastes the
    source's capacity and hides our bug.
    """
    request_headers = {"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT}
    if headers:
        for name in headers:
            if any(part in name.lower() for part in _FORBIDDEN_HEADER_PARTS):
                raise ValueError(f"credential-bearing header {name!r} is not allowed")
        request_headers.update(headers)
    request = Request(url, headers=request_headers, method="GET")
    if request.get_method() != "GET":  # defensive: this module is read-only
        raise AssertionError("edge_lab.http only issues GET requests")

    open_fn = opener or _default_opener
    started = time.monotonic()
    attempt = 0
    reasons: list[str] = []

    while True:
        attempt += 1
        # Exponential backoff with up to 50% jitter (429s carry no Retry-After).
        delay = backoff * (2 ** (attempt - 1)) * (1 + 0.5 * jitter())
        if pacer is not None:
            pacer.wait()
        try:
            with open_fn(request, timeout) as response:
                body = response.read()
                status = int(getattr(response, "status", 200))
                final_url = response.geturl() if hasattr(response, "geturl") else url
                content_type = response.headers.get("Content-Type") if response.headers else None
                kept_headers = allowlisted_headers(response.headers)
            return FetchResult(
                requested_url=url,
                final_url=final_url,
                http_status=status,
                content_type=content_type,
                body=body,
                received_at_utc=datetime.now(timezone.utc).isoformat(),
                duration_ms=int((time.monotonic() - started) * 1000),
                attempts=attempt,
                retry_reasons=tuple(reasons),
                response_headers=kept_headers,
            )
        except HTTPError as exc:
            exc.close()
            if exc.code not in RETRYABLE_STATUS or attempt > retries:
                raise HttpFetchError(
                    f"HTTP {exc.code} fetching {url}", status=exc.code, attempts=attempt
                ) from exc
            reasons.append(f"http_{exc.code}")
            retry_after = _retry_after_seconds(exc)
            sleep(retry_after if retry_after is not None else delay)
        except (OSError, http.client.HTTPException) as exc:
            # URLError, timeouts, resets, RemoteDisconnected, IncompleteRead, SSL
            # errors: all transport failures, all transient.
            if attempt > retries:
                reason = getattr(exc, "reason", None) or f"{type(exc).__name__}: {exc}"
                raise HttpFetchError(
                    f"Network error fetching {url}: {reason}", attempts=attempt
                ) from exc
            reasons.append(type(exc).__name__)
            sleep(delay)


def decode_json_object(result: FetchResult) -> dict[str, Any]:
    url = result.requested_url
    try:
        payload = json.loads(result.body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ResponseDecodeError(
            f"Invalid JSON returned by {url}", status=result.http_status, attempts=result.attempts
        ) from exc
    if not isinstance(payload, dict):
        raise ResponseDecodeError(
            f"Expected a JSON object from {url}, got {type(payload).__name__}",
            status=result.http_status,
            attempts=result.attempts,
        )
    return payload


def fetch_json_result(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    **kwargs: Any,
) -> tuple[dict[str, Any], FetchResult]:
    result = fetch(url, headers=headers, timeout=timeout, **kwargs)
    return decode_json_object(result), result


def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    payload, _ = fetch_json_result(url, headers=headers, timeout=timeout)
    return payload
