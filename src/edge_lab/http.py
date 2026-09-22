"""Read-only HTTP retrieval with bounded retries and per-request provenance.

This module can only issue GET requests. There is deliberately no code path for
POST/PUT/DELETE, request signing, or credentials: order submission is out of
scope for this repository until an explicit owner decision changes that.
"""

from __future__ import annotations

import http.client
import json
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


class HttpFetchError(RuntimeError):
    """Raised when a public data endpoint cannot be fetched or decoded."""

    def __init__(self, message: str, *, status: int | None = None, attempts: int = 1) -> None:
        super().__init__(message)
        self.status = status
        self.attempts = attempts


class ResponseDecodeError(HttpFetchError):
    """The server answered, but the body was not the JSON object we expected."""


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
) -> FetchResult:
    """GET `url`, retrying only transient failures (network errors, 429, 5xx).

    Other 4xx responses fail immediately: retrying a bad request wastes the
    source's capacity and hides our bug.
    """
    request_headers = {"Accept": "application/json", "User-Agent": DEFAULT_USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers, method="GET")
    if request.get_method() != "GET":  # defensive: this module is read-only
        raise AssertionError("edge_lab.http only issues GET requests")

    open_fn = opener or _default_opener
    started = time.monotonic()
    attempt = 0

    while True:
        attempt += 1
        delay = backoff * (2 ** (attempt - 1))
        try:
            with open_fn(request, timeout) as response:
                body = response.read()
                status = int(getattr(response, "status", 200))
                final_url = response.geturl() if hasattr(response, "geturl") else url
                content_type = response.headers.get("Content-Type") if response.headers else None
            return FetchResult(
                requested_url=url,
                final_url=final_url,
                http_status=status,
                content_type=content_type,
                body=body,
                received_at_utc=datetime.now(timezone.utc).isoformat(),
                duration_ms=int((time.monotonic() - started) * 1000),
                attempts=attempt,
            )
        except HTTPError as exc:
            exc.close()
            if exc.code not in RETRYABLE_STATUS or attempt > retries:
                raise HttpFetchError(
                    f"HTTP {exc.code} fetching {url}", status=exc.code, attempts=attempt
                ) from exc
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
