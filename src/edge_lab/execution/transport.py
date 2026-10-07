"""Environment-isolated Kalshi transport (#160 package F, ADR 0043). FIXTURE only.

`Transport(environment, signer, opener, clock)` sends one allowlisted `kalshi_wire.WireRequest`:

- **Environment.** Construction and every send refuse unless `model.environment_authorized(environment)`; today
  that is FIXTURE only, and DEMO and PRODUCTION raise `EnvironmentNotAuthorized`. There is no override or force
  flag, and a key being present changes nothing. FIXTURE's only host is `fixture.invalid`, which cannot resolve.
- **No default opener.** The caller injects `opener(request, timeout)`. There is no network default.
- **Allowlists.** The host must be one of the environment's hosts (conformance); the method and path must match
  an allowlisted endpoint template (kalshi_wire); the request must be for the signer's environment and account.
- **Redirects are refused**, never followed, so credentials are never forwarded to another URL. TLS verification
  is never disabled: this module creates no SSL context and passes none.
- **Retries.** Only idempotent GET reads are retried, a bounded number of times. A POST or DELETE is sent at most
  once per call. When its result is unknowable (timeout, connection error, 5xx, redirect, odd status) the outcome
  is AMBIGUOUS, which the journal records as OUTCOME_UNKNOWN and reconciles before anything is retried.
- **Rate budget.** Token buckets from the documented limits (RL-01 to RL-05), per shard for writes, with reserved
  headroom that only protective requests (cancels, decreases and reads) may use, so a throttled strategy can
  still cancel and reconcile. A request the local budget cannot cover is not sent.
- **Redaction.** Exceptions and `repr` never carry headers, the key id, signatures or bodies.

A 2xx write whose body then fails `kalshi_wire` parsing must also be treated as AMBIGUOUS by the caller.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request

from . import conformance as c
from . import kalshi_wire
from .conformance import Evidence, Fact
from .kalshi_wire import Bucket, HttpMethod, WireRequest
from .model import Environment, environment_authorized
from .signer import Signer

_KEYS = "https://docs.kalshi.com/getting_started/api_keys"

AUTH_HEADER_FACTS: tuple[Fact, ...] = (
    Fact("HDR-01", ("KALSHI-ACCESS-KEY", "KALSHI-ACCESS-TIMESTAMP", "KALSHI-ACCESS-SIGNATURE"), Evidence.DOCUMENTED,
         _KEYS),
    Fact("HDR-02", "KALSHI-ACCESS-TIMESTAMP is the request time in milliseconds", Evidence.DOCUMENTED, _KEYS),
)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MAX_TIMEOUT_S = 30.0
MAX_READ_ATTEMPTS = 5
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class TransportError(Exception):
    """Base class. Messages are fixed text plus an endpoint name: never headers, signatures or bodies."""


class EnvironmentNotAuthorized(TransportError):
    pass


class HostNotAllowed(TransportError):
    pass


class RequestNotAllowed(TransportError):
    pass


class Outcome(str, Enum):
    OK = "OK"  # 2xx
    REJECTED = "REJECTED"  # a definitive 4xx other than 429: the venue did not act
    THROTTLED = "THROTTLED"  # 429 from the venue (RL-06): not executed
    NOT_SENT = "NOT_SENT"  # the local rate budget could not cover it; nothing left this process
    AMBIGUOUS = "AMBIGUOUS"  # a write whose effect is unknown: journal OUTCOME_UNKNOWN, reconcile, never resend blindly
    UNAVAILABLE = "UNAVAILABLE"  # a read that failed after its bounded retries (or was redirected)


class Priority(str, Enum):
    ORDINARY = "ORDINARY"
    PROTECTIVE = "PROTECTIVE"  # cancels, decreases and reconciliation reads: may use the reserved headroom


@dataclass(frozen=True)
class TransportResult:
    outcome: Outcome
    endpoint: str
    status: int | None
    attempts: int
    reason: str
    body: bytes | None = field(default=None, repr=False)  # the caller parses it with kalshi_wire


# ---------------------------------------------------------------------------------------------- rate budget


class _Bucket:
    """Integer token bucket: milli-tokens and nanoseconds, so refill is exact."""

    def __init__(self, rate_per_s: int, capacity: int, now_ns: int):
        self.rate, self.capacity_milli = rate_per_s, capacity * 1000
        self.milli, self.at = self.capacity_milli, now_ns

    def _refill(self, now_ns: int) -> None:
        if now_ns > self.at:
            self.milli = min(self.capacity_milli, self.milli + self.rate * (now_ns - self.at) // 1_000_000)
            self.at = now_ns

    def take(self, cost: int, reserve_milli: int, now_ns: int) -> bool:
        self._refill(now_ns)
        if self.milli - cost * 1000 < reserve_milli:
            return False
        self.milli -= cost * 1000
        return True


class RateBudget:
    """Local token buckets from the documented tier (RL-03, RL-04). The account's tier and non-default endpoint
    costs are unknown (RL-07, RL-08), so the default is the smallest tier and the default cost for every request.

    Ordinary requests may not dip into the last `reserve_fraction` of a bucket; protective ones may. Writes are
    billed per shard (RL-05): shard 0 is the unscoped bucket and each other shard has its own full budget.

    The venue meters per account, so every transport for one account must share one `RateBudget`; two budgets
    for the same account would double the local allowance. Not thread-safe: one sender per budget."""

    def __init__(self, *, tier: str = c.DEFAULT_TIER, reserve_fraction: tuple[int, int] = (3, 10),
                 token_cost: int = c.DEFAULT_TOKEN_COST, monotonic_ns: Callable[[], int] = time.monotonic_ns):
        if tier not in c.RATE_TIERS:
            raise ValueError(f"unknown tier {tier!r}")
        num, den = reserve_fraction
        if not (isinstance(num, int) and isinstance(den, int) and 0 < num < den):
            raise ValueError("reserve_fraction must be a proper fraction (numerator, denominator)")
        if isinstance(token_cost, bool) or not isinstance(token_cost, int) or token_cost <= 0:
            raise ValueError("token_cost must be a positive int")
        read_rate, write_rate, read_s, write_s = c.RATE_TIERS[tier]
        self._clock = monotonic_ns
        self._cost = token_cost
        self._reserve = (num, den)
        self._read_spec = (read_rate, read_rate * read_s)
        self._write_spec = (write_rate, write_rate * write_s)
        self._read = _Bucket(*self._read_spec, monotonic_ns())
        self._writes: dict[int, _Bucket] = {}

    def _bucket(self, kind: Bucket, shard: int | None) -> _Bucket:
        if kind is Bucket.READ:
            return self._read
        if shard is None:
            raise RequestNotAllowed("a write must name its shard")
        if shard not in self._writes:
            self._writes[shard] = _Bucket(*self._write_spec, self._clock())
        return self._writes[shard]

    def try_acquire(self, kind: Bucket, shard: int | None, priority: Priority) -> bool:
        bucket = self._bucket(kind, shard)
        num, den = self._reserve
        reserve = 0 if priority is Priority.PROTECTIVE else bucket.capacity_milli * num // den
        return bucket.take(self._cost, reserve, self._clock())


# ---------------------------------------------------------------------------------------------- transport


Opener = Callable[[Request, float], Any]
Clock = Callable[[], datetime]


def _timestamp_ms(clock: Clock) -> int:
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise RequestNotAllowed("the clock must return a timezone-aware datetime")
    return (now.astimezone(timezone.utc) - _EPOCH) // timedelta(milliseconds=1)


class Transport:
    def __init__(self, environment: Environment, signer: Signer, opener: Opener | None, clock: Clock, *,
                 host: str | None = None, budget: RateBudget | None = None, timeout_s: float = 10.0,
                 read_attempts: int = 3, sleep: Callable[[float], None] = time.sleep):
        if not isinstance(environment, Environment) or not environment_authorized(environment):
            raise EnvironmentNotAuthorized("egress is not authorized in this environment")
        if not isinstance(signer, Signer):
            raise RequestNotAllowed("a signer.Signer is required")
        if signer.environment is not environment:
            raise EnvironmentNotAuthorized("the signer belongs to another environment")
        if opener is None or not callable(opener):
            raise RequestNotAllowed("an opener must be injected; there is no default network opener")
        if not callable(clock):
            raise RequestNotAllowed("a clock must be injected")
        allowed = c.hosts_for(environment)
        chosen = allowed[0] if host is None else host
        if chosen not in allowed:
            raise HostNotAllowed("host is not on this environment's allowlist")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not 0 < timeout_s <= MAX_TIMEOUT_S:
            raise ValueError(f"timeout_s must be in (0, {MAX_TIMEOUT_S}]")
        if isinstance(read_attempts, bool) or not isinstance(read_attempts, int) \
                or not 1 <= read_attempts <= MAX_READ_ATTEMPTS:
            raise ValueError(f"read_attempts must be in 1-{MAX_READ_ATTEMPTS}")
        self._environment, self._signer, self._opener, self._clock = environment, signer, opener, clock
        self._host, self._timeout, self._read_attempts, self._sleep = chosen, float(timeout_s), read_attempts, sleep
        self._budget = budget if budget is not None else RateBudget()

    def __repr__(self) -> str:
        return f"Transport(environment={self._environment.value}, host={self._host})"

    def __reduce_ex__(self, protocol: object) -> Any:
        raise TypeError("a Transport cannot be pickled")

    # -- checks

    def _check(self, request: WireRequest, priority: Priority) -> str:
        if not environment_authorized(self._environment):
            raise EnvironmentNotAuthorized("egress is not authorized in this environment")
        try:
            kalshi_wire.check_allowlisted(request)
        except ValueError:
            raise RequestNotAllowed("the request is not an allowlisted endpoint") from None
        name = request.endpoint.name
        if request.scope.environment is not self._environment:
            raise EnvironmentNotAuthorized(f"{name}: the request is for another environment")
        if request.scope.account_ref != self._signer.account_ref:
            raise RequestNotAllowed(f"{name}: the request is for another account")
        if not isinstance(priority, Priority):
            raise RequestNotAllowed(f"{name}: priority must be a Priority")
        if priority is Priority.PROTECTIVE and not request.endpoint.value.protective:
            raise RequestNotAllowed(f"{name}: only cancels, decreases and reads may use reserved capacity")
        url = f"https://{self._host}{request.full_path}"
        if request.query:
            url += "?" + request.query_string()
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != self._host or parts.port is not None or parts.username \
                or parts.password or parts.path != request.full_path:
            raise HostNotAllowed(f"{name}: the built URL left the allowlisted host")
        return url

    def _http_request(self, request: WireRequest, url: str) -> Request:
        auth = self._signer.sign(request, timestamp_ms=_timestamp_ms(self._clock))
        headers = {"Accept": "application/json"}
        headers["KALSHI-ACCESS-KEY"] = auth.key_id
        headers["KALSHI-ACCESS-SIGNATURE"] = auth.signature
        headers["KALSHI-ACCESS-TIMESTAMP"] = auth.timestamp_ms
        if request.method is HttpMethod.POST:
            headers["Content-Type"] = "application/json"
            return Request(url, data=request.body, headers=headers, method="POST")
        if request.method is HttpMethod.DELETE:
            return Request(url, headers=headers, method="DELETE")
        return Request(url, headers=headers, method="GET")

    # -- sending

    def send(self, request: WireRequest, *, priority: Priority = Priority.ORDINARY) -> TransportResult:
        url = self._check(request, priority)
        name = request.endpoint.name
        if request.is_write():
            return self._attempt(request, url, write=True, priority=priority, attempt=1)
        result = TransportResult(Outcome.UNAVAILABLE, name, None, 0, "no attempt made")
        for attempt in range(1, self._read_attempts + 1):
            result = self._attempt(request, url, write=False, priority=priority, attempt=attempt)
            if result.outcome is not Outcome.UNAVAILABLE or result.reason == "REDIRECT_REFUSED":
                return result
            if attempt < self._read_attempts:
                self._sleep(min(0.5 * 2 ** (attempt - 1), 4.0))
        return result

    def _attempt(self, request: WireRequest, url: str, *, write: bool, priority: Priority,
                 attempt: int) -> TransportResult:
        name = request.endpoint.name
        spec = request.endpoint.value
        if not self._budget.try_acquire(spec.bucket, request.exchange_index, priority):
            return TransportResult(Outcome.NOT_SENT, name, None, attempt, "LOCAL_RATE_BUDGET")
        http_request = self._http_request(request, url)
        unknown = Outcome.AMBIGUOUS if write else Outcome.UNAVAILABLE
        try:
            response = self._opener(http_request, self._timeout)
        except HTTPError as exc:
            status, final_url, body = exc.code, url, _read(exc)
        except (TimeoutError, URLError, OSError):
            return TransportResult(unknown, name, None, attempt, "NO_RESPONSE")
        except Exception:  # an opener bug is still an unknown outcome for a write
            return TransportResult(unknown, name, None, attempt, "OPENER_ERROR")
        else:
            status = _status(response)
            final_url = _final_url(response, url)
            body = _read(response)
        if final_url != url or (status is not None and 300 <= status < 400):
            return TransportResult(unknown, name, status, attempt, "REDIRECT_REFUSED")
        if body is None:
            return TransportResult(unknown, name, status, attempt, "BODY_UNREADABLE")
        if status is None:
            return TransportResult(unknown, name, None, attempt, "NO_STATUS")
        if 200 <= status < 300:
            return TransportResult(Outcome.OK, name, status, attempt, "OK", body)
        if status == 429:
            return TransportResult(Outcome.THROTTLED if write else Outcome.UNAVAILABLE, name, status, attempt,
                                   "VENUE_RATE_LIMIT", body)
        if 400 <= status < 500:
            return TransportResult(Outcome.REJECTED, name, status, attempt, "VENUE_REJECTED", body)
        return TransportResult(unknown, name, status, attempt, "VENUE_ERROR", body)


def _status(response: Any) -> int | None:
    status = getattr(response, "status", None)
    if status is None and callable(getattr(response, "getcode", None)):
        status = response.getcode()
    return status if isinstance(status, int) and not isinstance(status, bool) else None


def _final_url(response: Any, sent: str) -> str:
    geturl = getattr(response, "geturl", None)
    final = geturl() if callable(geturl) else sent
    return final if isinstance(final, str) else ""


def _read(response: Any) -> bytes | None:
    try:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    except Exception:
        return None
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_RESPONSE_BYTES:
        return None
    return bytes(data)


def header_names() -> Mapping[str, str]:
    """The auth header names this transport sends (HDR-01), for tests and documentation."""
    return {"key": "KALSHI-ACCESS-KEY", "signature": "KALSHI-ACCESS-SIGNATURE", "timestamp": "KALSHI-ACCESS-TIMESTAMP"}
