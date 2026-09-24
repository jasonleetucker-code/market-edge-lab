"""The Odds API (v4, free tier) adapter foundation: quota, redaction, identity, research estimates.

Read-only sportsbook-consensus data (directive 2026-09-23 section 10, issue #29). What this
module does and does not do:

- **Offered odds are not executable prices.** A bookmaker's price is what a sportsbook
  advertises to its own customers. Nothing here builds an `ExecutableQuote`, and a de-vigged
  probability is labelled a research-only estimate. It is not a quote and not a model.
- **The key is a read-only data-feed credential** (`CredentialKind.READ_ONLY_DATA_FEED`).
  Only the owner installs it, in the environment variable the source registry names.
  `load_key` is the only reader. The key travels only as the documented `apiKey` query
  parameter, and every URL, error and provenance record that leaves this module is
  redacted. Errors are re-raised with redacted text and no exception chain.
- **Quota is protected locally** (`QuotaLedger`). A request is reserved before it is sent,
  against a ceiling below the provider's monthly allowance. The ledger fails closed. Before
  any reconciliation in the current UTC month it is QUOTA_UNKNOWN. A malformed header or an
  ambiguous failure keeps the reservation and makes it QUOTA_UNKNOWN. It never guesses when
  the provider's month resets: counters reset only when the provider's own `used` header
  goes down by more than the calls in flight could explain (a smaller drop is an out-of-order
  reading from concurrent calls and is ignored).
- **Scheduled pulls only through the pilot runner.** Nothing here runs by itself. The one
  authorized schedule is the game-relative NFL pilot (`edge_lab.odds_pilot`, ADR 0029): the
  quota-free events endpoint discovers the schedule (`fetch_events`), and paid odds calls are
  made only for planned capture slots that the monthly credit proof admits.

Cost rule, from the v4 guide (https://the-odds-api.com/liveapi/guides/v4/, read 2026-09-23):
`cost = markets x regions`; with `bookmakers`, every group of 10 bookmakers counts as one
region. The provider may charge less (it counts markets actually returned, and an empty
response is free), so the estimate is an upper bound and the response's `x-requests-last`
header is what gets booked.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import http
from .forward import LockBusy, exclusive_lock
from .freshness import Freshness, assess, parse_utc
from .odds_schedule import ScheduledEvent
from .opportunity import Event, Market, MarketStatus, Payoff
from .redaction import redact_text, redact_url
from .sources import CredentialKind, get_source

SOURCE_ID = "the_odds_api"
VENUE = "the_odds_api"
BASE_URL = "https://api.the-odds-api.com"
FREE_TIER_MONTHLY_CREDITS = 500
DEFAULT_CEILING = 450
PARSER_VERSION = "1"
KEY_PARAM = "apiKey"
USER_AGENT = "market-edge-lab/0.1 (read-only research; the_odds_api adapter)"

# Bookmakers that need a paid plan (issue #29, as given to this adapter). They are never
# requested on the free tier and are reported as PAID_ONLY_NOT_ENABLED, not as absent.
PAID_ONLY_BOOKMAKERS = frozenset({"williamhill_us", "fanatics"})
# Market keys whose outcome sets this adapter understands well enough to de-vig.
SUPPORTED_MARKETS = frozenset({"h2h", "spreads", "totals"})

_SLUG = re.compile(r"^[a-z0-9_]{1,64}$")
_COUNT = re.compile(r"^[0-9]+$")
# A RESERVED reservation older than this cannot still be in flight (one GET, 20 s timeout,
# no retries): the process that made it crashed. It is retired at the next header reading.
ORPHAN_AFTER = timedelta(minutes=10)


class QuotaState(str, Enum):
    READY = "READY"
    SETUP_NEEDED = "SETUP_NEEDED"  # no key installed: nothing is sent
    QUOTA_UNKNOWN = "QUOTA_UNKNOWN"  # no trustworthy provider reading this month
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"  # the protective ceiling or provider remaining would be exceeded


class CoverageStatus(str, Enum):
    RETURNED = "RETURNED"
    ABSENT = "ABSENT"  # requested and allowed, but not in this response (not "no market exists")
    PAID_ONLY_NOT_ENABLED = "PAID_ONLY_NOT_ENABLED"
    UNIMPLEMENTED = "UNIMPLEMENTED"  # returned, but this adapter does not interpret that market


class OddsApiError(RuntimeError):
    """A failed Odds API call. The message is always redacted."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.fetch: http.FetchResult | None = None  # set only when a charged response could not be decoded


class QuotaRefused(RuntimeError):
    def __init__(self, state: QuotaState, detail: str) -> None:
        super().__init__(f"{state.value}: {detail}")
        self.state = state
        self.detail = detail


# --------------------------------------------------------------------------- key and requests


def load_key(environ: Mapping[str, str] | None = None) -> str | None:
    """The owner-installed key from the registered environment variable, or None (SETUP_NEEDED).

    The value is never logged, stored or returned anywhere but to `build_request`."""
    spec = get_source(SOURCE_ID)
    if spec.credential_kind is not CredentialKind.READ_ONLY_DATA_FEED or not spec.credential_env_var:
        return None
    env = os.environ if environ is None else environ
    value = env.get(spec.credential_env_var)
    value = value.strip() if isinstance(value, str) else None
    return value or None


def _validate_list(name: str, values: Sequence[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} must be a list of keys")
    out = tuple(values)
    for value in out:
        if not isinstance(value, str) or not _SLUG.match(value):
            raise ValueError(f"invalid {name} entry {value!r}")
    if len(set(out)) != len(out):
        raise ValueError(f"duplicate {name} entries")
    return out


def estimate_cost(markets: Sequence[str], regions: Sequence[str] | None = None,
                  bookmakers: Sequence[str] | None = None) -> int:
    """Upper-bound credits for one odds call: markets x (regions, or bookmaker groups of 10)."""
    mk = _validate_list("markets", markets)
    rg = _validate_list("regions", regions)
    bk = _validate_list("bookmakers", bookmakers)
    if not mk:
        raise ValueError("at least one market is required")
    if bool(rg) == bool(bk):
        raise ValueError("give exactly one of regions or bookmakers")
    return len(mk) * (len(rg) if rg else math.ceil(len(bk) / 10))


def _iso_z(instant: datetime) -> str:
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise ValueError("commence bounds must be timezone-aware datetimes")
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scope_params(commence_from: datetime | None, commence_to: datetime | None,
                  event_ids: Sequence[str] | None) -> list[tuple[str, str]]:
    """Documented filters of the odds and events endpoints (v4 guide, re-read 2026-09-24):
    `commenceTimeFrom` / `commenceTimeTo` (ISO 8601, inclusive) and `eventIds`. They narrow the
    response; they do not change the odds endpoint's cost (markets x regions)."""
    params: list[tuple[str, str]] = []
    if commence_from is not None:
        params.append(("commenceTimeFrom", _iso_z(commence_from)))
    if commence_to is not None:
        params.append(("commenceTimeTo", _iso_z(commence_to)))
    if commence_from is not None and commence_to is not None and commence_to < commence_from:
        raise ValueError("commence_to is before commence_from")
    ids = _validate_list("event_ids", event_ids)
    if ids:
        params.append(("eventIds", ",".join(ids)))
    return params


def _validate_sport(sport: str) -> None:
    if not isinstance(sport, str) or not _SLUG.match(sport):
        raise ValueError(f"invalid sport key {sport!r}")


def build_request(sport: str, markets: Sequence[str], *, key: str, regions: Sequence[str] | None = None,
                  bookmakers: Sequence[str] | None = None, odds_format: str = "decimal",
                  commence_from: datetime | None = None, commence_to: datetime | None = None,
                  event_ids: Sequence[str] | None = None) -> tuple[str, str]:
    """(url with the key, redacted url) for GET /v4/sports/{sport}/odds.

    Paid-only bookmakers are refused rather than silently requested."""
    _validate_sport(sport)
    if odds_format not in ("decimal", "american"):
        raise ValueError("odds_format must be 'decimal' or 'american'")
    if not key:
        raise ValueError("no key: SETUP_NEEDED")
    estimate_cost(markets, regions, bookmakers)  # validates the combination
    bk = _validate_list("bookmakers", bookmakers)
    paid = sorted(set(bk) & PAID_ONLY_BOOKMAKERS)
    if paid:
        raise ValueError(f"paid-only bookmakers are not enabled on the free tier: {paid}")
    params: list[tuple[str, str]] = [(KEY_PARAM, key)]
    if bk:
        params.append(("bookmakers", ",".join(bk)))
    else:
        params.append(("regions", ",".join(_validate_list("regions", regions))))
    params += [("markets", ",".join(_validate_list("markets", markets))), ("oddsFormat", odds_format),
               ("dateFormat", "iso")]
    params += _scope_params(commence_from, commence_to, event_ids)
    url = f"{BASE_URL}/v4/sports/{quote(sport)}/odds/?{urlencode(params, safe=',:')}"
    return url, redact_url(url)


def build_events_request(sport: str, *, key: str, commence_from: datetime | None = None,
                         commence_to: datetime | None = None,
                         event_ids: Sequence[str] | None = None) -> tuple[str, str]:
    """GET /v4/sports/{sport}/events: documented as free of quota (no odds in the response)."""
    _validate_sport(sport)
    if not key:
        raise ValueError("no key: SETUP_NEEDED")
    params = [(KEY_PARAM, key), ("dateFormat", "iso")] + _scope_params(commence_from, commence_to, event_ids)
    url = f"{BASE_URL}/v4/sports/{quote(sport)}/events/?{urlencode(params, safe=',:')}"
    return url, redact_url(url)


def build_sports_request(*, key: str) -> tuple[str, str]:
    """GET /v4/sports: documented as free of quota; its headers reconcile the ledger."""
    if not key:
        raise ValueError("no key: SETUP_NEEDED")
    url = f"{BASE_URL}/v4/sports/?{urlencode([(KEY_PARAM, key)])}"
    return url, redact_url(url)


# --------------------------------------------------------------------------- quota headers


@dataclass(frozen=True)
class QuotaHeaders:
    remaining: int
    used: int
    last: int | None


def parse_quota_headers(headers: Iterable[tuple[str, str]] | Mapping[str, str] | None) -> QuotaHeaders | None:
    """Parsed x-requests-* headers, or None when missing or malformed (QUOTA_UNKNOWN)."""
    if headers is None:
        return None
    items = headers.items() if isinstance(headers, Mapping) else headers
    found = {str(k).lower(): str(v).strip() for k, v in items}

    def number(name: str) -> int | None:
        text = found.get(name)
        if text is None:
            return None
        if not _COUNT.match(text):  # plain non-negative integers only
            raise ValueError(name)
        return int(text)

    try:
        remaining, used, last = number("x-requests-remaining"), number("x-requests-used"), number("x-requests-last")
    except ValueError:
        return None
    if remaining is None or used is None:
        return None
    return QuotaHeaders(remaining=remaining, used=used, last=last)


# --------------------------------------------------------------------------- quota ledger


def _month(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m")


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    cost: int
    created_at_utc: str


class QuotaLedger:
    """Persisted, locked, fail-closed record of credits reserved and used.

    State on disk (JSON): the UTC month of the last provider reconciliation, credits booked
    locally (`used_local`), outstanding reservations, and the last provider header values.
    Every read-modify-write holds an exclusive file lock, so separate processes and threads
    cannot both spend the same headroom."""

    def __init__(self, path: str | Path, ceiling: int = DEFAULT_CEILING, *,
                 clock: Callable[[], datetime] | None = None, lock_timeout_s: float = 30.0) -> None:
        if not isinstance(ceiling, int) or isinstance(ceiling, bool) or not 0 < ceiling < FREE_TIER_MONTHLY_CREDITS:
            raise ValueError(f"ceiling must be an integer in (0, {FREE_TIER_MONTHLY_CREDITS})")
        self.path = Path(path)
        self.ceiling = ceiling
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock_path = self.path.with_name(self.path.name + ".lock")
        self._lock_timeout_s = lock_timeout_s
        self._thread_lock = threading.Lock()

    # -- persistence

    def _empty(self) -> dict[str, Any]:
        return {"schema": 1, "reconciled_month_utc": None, "quota_known": False, "used_local": 0,
                "reservations": {}, "last_headers": None, "events": []}

    def _load(self) -> dict[str, Any]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._empty()
        data = json.loads(text)  # a corrupt ledger raises: never silently start from zero
        if not isinstance(data, dict) or data.get("schema") != 1:
            raise ValueError(f"unrecognized quota ledger {self.path}")
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(data, sort_keys=True, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def _transaction(self, fn: Callable[[dict[str, Any], datetime], Any]) -> Any:
        with self._thread_lock:
            try:
                with exclusive_lock(self._lock_path, timeout_s=self._lock_timeout_s):
                    data = self._load()
                    result = fn(data, self._clock())
                    self._save(data)
                    return result
            except LockBusy:
                raise QuotaRefused(QuotaState.QUOTA_UNKNOWN, "quota ledger is locked by another process") from None

    @staticmethod
    def _event(data: dict[str, Any], now: datetime, kind: str, **values: Any) -> None:
        data["events"].append({"at_utc": now.isoformat(), "event": kind, **values})
        del data["events"][:-200]  # bounded history; totals live in the counters

    # -- views

    @staticmethod
    def _outstanding(data: dict[str, Any]) -> int:
        return sum(int(r["cost"]) for r in data["reservations"].values())

    def _state(self, data: dict[str, Any], now: datetime) -> tuple[QuotaState, str]:
        headers = data.get("last_headers")
        if not data.get("quota_known") or not headers:
            return QuotaState.QUOTA_UNKNOWN, "no trustworthy provider quota reading; reconcile first"
        if data.get("reconciled_month_utc") != _month(now):
            return QuotaState.QUOTA_UNKNOWN, "not reconciled in the current UTC month"
        spent = max(int(data["used_local"]), int(headers["used"])) + self._outstanding(data)
        if spent >= self.ceiling or int(headers["remaining"]) - self._outstanding(data) <= 0:
            return QuotaState.QUOTA_EXHAUSTED, f"{spent} credits spent or reserved; ceiling {self.ceiling}"
        return QuotaState.READY, f"{spent} of ceiling {self.ceiling} spent or reserved"

    def snapshot(self) -> dict[str, Any]:
        """The ledger's current contents plus its state (read under the lock)."""
        def view(data: dict[str, Any], now: datetime) -> dict[str, Any]:
            state, detail = self._state(data, now)
            return {**json.loads(json.dumps(data)), "state": state.value, "detail": detail,
                    "ceiling": self.ceiling, "outstanding": self._outstanding(data)}
        return self._transaction(view)

    def state(self) -> QuotaState:
        return QuotaState(self.snapshot()["state"])

    def read_only_view(self, now: datetime | None = None) -> dict[str, Any]:
        """The same view as `snapshot`, without taking the lock or writing anything (for the
        dashboard, which must never mutate the ledger). The file is replaced atomically, so a
        plain read sees one complete version. A missing file is an empty, QUOTA_UNKNOWN ledger;
        a corrupt one raises, as everywhere else."""
        data = self._load()
        at = now or self._clock()
        state, detail = self._state(data, at)
        return {**data, "state": state.value, "detail": detail, "ceiling": self.ceiling,
                "outstanding": self._outstanding(data), "exists": self.path.exists()}

    # -- mutations

    def reconcile(self, headers: Iterable[tuple[str, str]] | Mapping[str, str] | None) -> QuotaState:
        """Record provider headers from a quota-free call (GET /v4/sports)."""
        parsed = parse_quota_headers(headers)

        def apply(data: dict[str, Any], now: datetime) -> QuotaState:
            if parsed is None:
                data["quota_known"] = False
                self._event(data, now, "reconcile_failed", reason="missing or malformed quota headers")
                return QuotaState.QUOTA_UNKNOWN
            self._apply_headers(data, now, parsed, in_flight=self._outstanding(data))
            data["reconciled_month_utc"] = _month(now)
            self._event(data, now, "reconciled", remaining=parsed.remaining, used=parsed.used)
            return self._state(data, now)[0]
        return self._transaction(apply)

    def _apply_headers(self, data: dict[str, Any], now: datetime, parsed: QuotaHeaders, *, in_flight: int = 0) -> None:
        """Apply one provider reading. `in_flight` is the cost of calls that may have been
        counted by a later reading already (outstanding reservations, plus the call being
        settled). Concurrent calls can return their headers out of order, so a reading lower
        than the previous one by no more than `in_flight` is a stale reading: it is recorded
        and ignored, never taken as a reset (that would hand back credits already spent)."""
        previous = data.get("last_headers")
        if previous is not None and parsed.used < int(previous["used"]):
            drop = int(previous["used"]) - parsed.used
            if drop <= in_flight:
                self._event(data, now, "stale_reading_ignored", previous_used=int(previous["used"]),
                            used=parsed.used, in_flight=in_flight)
                data["quota_known"] = True
                self._retire_settled_by_provider(data, now)
                return
            # The provider's own counter went down by more than concurrency can explain: its
            # period reset. Only now are local counters reset, and only to what it reports.
            self._event(data, now, "provider_reset_observed", previous_used=int(previous["used"]),
                        used=parsed.used)
            data["used_local"] = parsed.used
        data["last_headers"] = {"remaining": parsed.remaining, "used": parsed.used, "last": parsed.last,
                                "observed_at_utc": now.isoformat()}
        data["quota_known"] = True
        self._retire_settled_by_provider(data, now)

    def _retire_settled_by_provider(self, data: dict[str, Any], now: datetime) -> None:
        """Retire reservations that the provider's own counter now accounts for.

        An AMBIGUOUS reservation's call finished (it failed) before this header reading, so
        whatever it cost is inside the provider's `used`, which the ceiling already counts.
        A RESERVED one older than ORPHAN_AFTER was orphaned by a crash. A recent RESERVED one
        may still be in flight and is kept."""
        for rid, entry in list(data["reservations"].items()):
            created = datetime.fromisoformat(entry["created_at_utc"])
            if created > now:
                continue
            orphaned = entry["state"] == "RESERVED" and now - created > ORPHAN_AFTER
            if entry["state"] == "AMBIGUOUS" or orphaned:
                del data["reservations"][rid]
                self._event(data, now, "reservation_retired", reservation_id=rid, cost=int(entry["cost"]),
                            previous_state=entry["state"], reason=("orphaned (no settle within "
                            f"{ORPHAN_AFTER})" if orphaned else "provider counter observed after the call"))

    def reserve(self, cost: int) -> Reservation:
        """Reserve `cost` credits or raise QuotaRefused. Nothing is sent without a reservation."""
        if not isinstance(cost, int) or isinstance(cost, bool) or cost <= 0:
            raise ValueError("cost must be a positive integer")

        def apply(data: dict[str, Any], now: datetime) -> Reservation:
            state, detail = self._state(data, now)
            if state is QuotaState.QUOTA_UNKNOWN:
                raise QuotaRefused(state, detail)
            headers = data["last_headers"]
            outstanding = self._outstanding(data)
            spent = max(int(data["used_local"]), int(headers["used"])) + outstanding
            if spent + cost > self.ceiling:
                raise QuotaRefused(QuotaState.QUOTA_EXHAUSTED,
                                   f"{spent} spent or reserved + {cost} > ceiling {self.ceiling}")
            if cost + outstanding > int(headers["remaining"]):
                raise QuotaRefused(QuotaState.QUOTA_EXHAUSTED,
                                   f"{cost} (+{outstanding} reserved) > provider remaining {headers['remaining']}")
            res = Reservation(uuid.uuid4().hex, cost, now.isoformat())
            data["reservations"][res.reservation_id] = {"cost": cost, "created_at_utc": res.created_at_utc,
                                                         "state": "RESERVED"}
            self._event(data, now, "reserved", reservation_id=res.reservation_id, cost=cost)
            return res
        return self._transaction(apply)

    def settle(self, reservation: Reservation,
               headers: Iterable[tuple[str, str]] | Mapping[str, str] | None) -> QuotaState:
        """Book a completed call. Malformed headers keep the reservation (QUOTA_UNKNOWN)."""
        parsed = parse_quota_headers(headers)

        def apply(data: dict[str, Any], now: datetime) -> QuotaState:
            entry = data["reservations"].get(reservation.reservation_id)
            if entry is None:
                raise ValueError(f"unknown or already settled reservation {reservation.reservation_id}")
            if parsed is None or parsed.last is None:
                entry["state"] = "AMBIGUOUS"
                data["quota_known"] = False
                self._event(data, now, "settle_ambiguous", reservation_id=reservation.reservation_id,
                            reason="missing or malformed quota headers; reservation kept")
                return QuotaState.QUOTA_UNKNOWN
            del data["reservations"][reservation.reservation_id]
            data["used_local"] = int(data["used_local"]) + parsed.last
            self._apply_headers(data, now, parsed, in_flight=self._outstanding(data) + reservation.cost)
            self._event(data, now, "settled", reservation_id=reservation.reservation_id,
                        reserved=reservation.cost, charged=parsed.last)
            return self._state(data, now)[0]
        return self._transaction(apply)

    def mark_ambiguous(self, reservation: Reservation, reason: str) -> None:
        """A call failed after it may have reached the provider: keep the reservation."""
        def apply(data: dict[str, Any], now: datetime) -> None:
            entry = data["reservations"].get(reservation.reservation_id)
            if entry is not None:
                entry["state"] = "AMBIGUOUS"
            data["quota_known"] = False
            self._event(data, now, "call_ambiguous", reservation_id=reservation.reservation_id,
                        reason=redact_text(reason))
        self._transaction(apply)

    def release_unsent(self, reservation: Reservation, reason: str) -> None:
        """Release a reservation whose request provably never left this process."""
        def apply(data: dict[str, Any], now: datetime) -> None:
            if data["reservations"].pop(reservation.reservation_id, None) is not None:
                self._event(data, now, "released_unsent", reservation_id=reservation.reservation_id,
                            reason=redact_text(reason))
        self._transaction(apply)


# --------------------------------------------------------------------------- fetching


@dataclass(frozen=True)
class OddsFetch:
    state: QuotaState
    detail: str
    redacted_url: str | None
    payload: Any | None = None
    fetch: http.FetchResult | None = None  # URLs redacted
    reservation: Reservation | None = None
    quota_after: QuotaState | None = None


def _redact(url: str, key: str) -> str:
    return redact_text(redact_url(url), (key,))


def _redacted_result(result: http.FetchResult, key: str) -> http.FetchResult:
    return replace(result, requested_url=_redact(result.requested_url, key),
                   final_url=_redact(result.final_url, key))


class _RefuseRedirects(HTTPRedirectHandler):
    """A redirect could carry the key to another URL: this source never follows one."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib hook
        return None  # urllib then raises HTTPError with the 3xx status


def _no_redirect_opener(request: Request, timeout: float) -> Any:
    return build_opener(_RefuseRedirects()).open(request, timeout=timeout)


def _get(url: str, key: str, *, opener: http.Opener | None, pacer: http.Pacer | None) -> http.FetchResult:
    """One GET, no retries (a retry could spend credits twice), no redirects. Errors are
    redacted and raised with no cause and no context."""
    failure: tuple[str, int | None] | None = None
    result = None
    try:
        result = http.fetch(url, headers={"User-Agent": USER_AGENT}, retries=0,
                            opener=opener or _no_redirect_opener, pacer=pacer, sleep=lambda s: None)
    except http.HttpFetchError as exc:
        failure = (redact_text(str(exc), (key,)), exc.status)
    except Exception as exc:  # anything else: still never leak the key or the chain
        failure = (redact_text(f"{type(exc).__name__}: {exc}", (key,)), None)
    if failure is not None:  # raised outside the except block: no __context__ either
        raise OddsApiError(failure[0], status=failure[1])
    if result.final_url != url:
        raise OddsApiError(f"redirect refused: {_redact(url, key)} answered from {_redact(result.final_url, key)}",
                           status=result.http_status)
    return _redacted_result(result, key)


def reconcile_quota(ledger: QuotaLedger, *, opener: http.Opener | None = None,
                    pacer: http.Pacer | None = None, environ: Mapping[str, str] | None = None) -> OddsFetch:
    """Read the quota-free sports list and reconcile the ledger from its headers."""
    key = load_key(environ)
    if key is None:
        return OddsFetch(QuotaState.SETUP_NEEDED, _setup_detail(), None)
    url, redacted = build_sports_request(key=key)
    try:
        result = _get(url, key, opener=opener, pacer=pacer)
    except OddsApiError as exc:
        return OddsFetch(QuotaState.QUOTA_UNKNOWN, str(exc), redacted)
    state = ledger.reconcile(result.response_headers)
    try:
        payload = _decode(result, key)
    except OddsApiError:
        payload = None  # the sports list is only a quota reading here; its body is not needed
    return OddsFetch(state, "reconciled" if state is not QuotaState.QUOTA_UNKNOWN else "headers unusable",
                     redacted, payload=payload, fetch=result, quota_after=state)


def fetch_events(sport: str, *, ledger: QuotaLedger | None = None, opener: http.Opener | None = None,
                 pacer: http.Pacer | None = None, commence_from: datetime | None = None,
                 commence_to: datetime | None = None, event_ids: Sequence[str] | None = None,
                 environ: Mapping[str, str] | None = None) -> OddsFetch:
    """Discover a sport's schedule through the quota-free events endpoint.

    No credits are reserved (the guide: the endpoint "does not count against the usage
    quota"). Quota headers, when present and well formed, reconcile the ledger. Missing or
    malformed headers leave the ledger untouched rather than marking it unknown: this call is
    not a quota reading by design. Same key handling as `fetch_odds`: one GET, no retries, no
    redirects, redacted URLs and errors. A failure raises OddsApiError."""
    key = load_key(environ)
    if key is None:
        return OddsFetch(QuotaState.SETUP_NEEDED, _setup_detail(), None)
    url, redacted = build_events_request(sport, key=key, commence_from=commence_from, commence_to=commence_to,
                                         event_ids=event_ids)
    result = _get(url, key, opener=opener, pacer=pacer)
    payload = _decode(result, key)
    after = None
    if ledger is not None and parse_quota_headers(result.response_headers) is not None:
        after = ledger.reconcile(result.response_headers)
    return OddsFetch(QuotaState.READY, "events (quota-free)", redacted, payload=payload, fetch=result,
                     quota_after=after)


def parse_events(payload: Any, *, sport: str) -> tuple[tuple[ScheduledEvent, ...], tuple[str, ...]]:
    """Scheduled events from an events payload. Malformed entries are skipped and reported,
    never guessed: an event without a valid id or a zoned commence time cannot be planned."""
    if not isinstance(payload, list):
        return (), ("events payload is not a list",)
    events: list[ScheduledEvent] = []
    problems: list[str] = []
    seen: set[str] = set()
    for raw in payload:
        if not isinstance(raw, Mapping):
            problems.append("event entry is not an object")
            continue
        native = raw.get("id")
        if not isinstance(native, str) or not _SLUG.match(native):
            problems.append(f"event with invalid id {native!r} skipped")
            continue
        if raw.get("sport_key") not in (None, sport):
            problems.append(f"{native}: sport_key {raw.get('sport_key')!r} is not {sport!r}; skipped")
            continue
        commence = parse_utc(raw.get("commence_time"))
        if commence is None:
            problems.append(f"{native}: commence_time {raw.get('commence_time')!r} is not a zoned timestamp")
            continue
        if native in seen:
            problems.append(f"{native}: duplicate event skipped")
            continue
        seen.add(native)
        home, away = raw.get("home_team"), raw.get("away_team")
        events.append(ScheduledEvent(native, sport, commence.astimezone(timezone.utc),
                                     home if isinstance(home, str) else None,
                                     away if isinstance(away, str) else None))
    return tuple(sorted(events, key=lambda e: (e.commence_utc, e.event_id))), tuple(problems)


def fetch_odds(sport: str, markets: Sequence[str], *, ledger: QuotaLedger, regions: Sequence[str] | None = None,
               bookmakers: Sequence[str] | None = None, odds_format: str = "decimal",
               opener: http.Opener | None = None, pacer: http.Pacer | None = None,
               environ: Mapping[str, str] | None = None, commence_from: datetime | None = None,
               commence_to: datetime | None = None, event_ids: Sequence[str] | None = None) -> OddsFetch:
    """Reserve, send one GET, book the provider's charge. SETUP_NEEDED and quota refusals send
    nothing. A failed call keeps its reservation and raises OddsApiError (redacted)."""
    key = load_key(environ)
    if key is None:
        return OddsFetch(QuotaState.SETUP_NEEDED, _setup_detail(), None)
    cost = estimate_cost(markets, regions, bookmakers)
    url, redacted = build_request(sport, markets, key=key, regions=regions, bookmakers=bookmakers,
                                  odds_format=odds_format, commence_from=commence_from, commence_to=commence_to,
                                  event_ids=event_ids)
    try:
        reservation = ledger.reserve(cost)
    except QuotaRefused as refusal:
        return OddsFetch(refusal.state, refusal.detail, redacted)
    try:
        result = _get(url, key, opener=opener, pacer=pacer)
    except OddsApiError as exc:
        ledger.mark_ambiguous(reservation, str(exc))
        raise
    after = ledger.settle(reservation, result.response_headers)
    try:
        payload = _decode(result, key)
        undecodable = None
    except OddsApiError as exc:
        undecodable = exc
    if undecodable is not None:
        # The call was charged: hand the (redacted) raw response to the caller as evidence.
        undecodable.fetch = result
        raise undecodable
    return OddsFetch(QuotaState.READY, f"reserved {cost}", redacted, payload=payload, fetch=result,
                     reservation=reservation, quota_after=after)


def _setup_detail() -> str:
    spec = get_source(SOURCE_ID)
    return (f"SETUP_NEEDED: the owner installs the free read-only key in the {spec.credential_env_var} "
            "environment variable on the host (never in git or chat); then reconcile the quota")


def _decode(result: http.FetchResult, key: str) -> Any:
    try:
        return json.loads(result.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    raise OddsApiError(redact_text(f"invalid JSON from {result.requested_url}", (key,)), status=result.http_status)


def save_snapshot(store: Any, *, run_id: str, sport: str, outcome: OddsFetch, kind: str = "odds",
                  context: Mapping[str, Any] | None = None) -> int:
    """Store one odds (or events) response as an immutable snapshot, with redacted provenance only.

    With `context` (the pilot runner's request identity: markets, regions, commence window,
    target ids), the payload also carries that context and the response's quota headers, so the
    stored row alone says what was asked, what came back and what it cost. The exact response
    bytes are hashed separately (`raw_sha256`) by the store."""
    if outcome.fetch is None or outcome.redacted_url is None:
        raise ValueError("nothing was fetched")
    if kind not in ("odds", "events"):
        raise ValueError("kind must be 'odds' or 'events'")
    spec = get_source(SOURCE_ID)
    payload: dict[str, Any] = {"sport": sport, "events": outcome.payload}
    if context is not None:
        payload["request"] = json.loads(redact_text(json.dumps(dict(context), sort_keys=True, default=str)))
        payload["quota_headers"] = dict(outcome.fetch.response_headers)
    return store.save_snapshot(run_id=run_id, source=spec.legacy_name, kind=kind, entity_id=sport,
                               url=outcome.redacted_url, payload=payload,
                               source_id=SOURCE_ID, fetch=outcome.fetch, parser_version=PARSER_VERSION,
                               schema_version=spec.schema_version)


# --------------------------------------------------------------------------- odds and identity


def american_to_decimal(price: Decimal) -> Decimal | None:
    if price >= 100:
        return Decimal(1) + price / Decimal(100)
    if price <= -100:
        return Decimal(1) + Decimal(100) / (-price)
    return None


def to_decimal_odds(raw: Any, odds_format: str) -> Decimal | None:
    """Decimal odds from a raw price, or None when the price is not a valid quote."""
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        price = Decimal(str(raw))
    except InvalidOperation:
        return None
    if not price.is_finite():
        return None
    if odds_format == "american":
        return american_to_decimal(price)
    if odds_format == "decimal":
        return price if price > 1 else None
    raise ValueError("odds_format must be 'decimal' or 'american'")


@dataclass(frozen=True)
class OddsOffer:
    """One bookmaker's offered price for one outcome. Research data, never executable."""

    event_id: str
    market_id: str
    bookmaker: str  # the route: each bookmaker is its own book
    market_key: str
    outcome_name: str
    point: str | None
    raw_price: str  # exactly as received
    odds_format: str
    decimal_odds: Decimal | None  # None when the raw price is not a valid quote
    market_last_update_utc: str | None
    executable: bool = False  # always False: offered odds are not fillable here
    # Event identity as the provider stated it in the same response (None when absent; never
    # filled in from another response). Used by `observation_identity` to link repeated
    # observations without collapsing distinct events.
    sport_key: str | None = None
    league: str | None = None  # the provider's `sport_title`, e.g. "NFL"
    home_team: str | None = None
    away_team: str | None = None
    commence_time_utc: str | None = None


@dataclass(frozen=True)
class DevigEstimate:
    """A research-only fair-probability estimate from one bookmaker's outcome set.

    It removes the bookmaker's margin by proportional normalization. It is not a quote, not
    a model estimate and not a price anyone can trade at."""

    label: str
    method: str
    probabilities: tuple[Decimal, ...]
    overround: Decimal
    executable: bool = False
    # (outcome name, normalized line) per probability, in the same order; () when unknown.
    outcomes: tuple[tuple[str, str | None], ...] = ()


RESEARCH_ONLY = "RESEARCH_ONLY_ESTIMATE"
IMPLIED_WITH_MARGIN = "IMPLIED_FROM_OFFERED_ODDS_INCLUDES_MARGIN"
RESEARCH_ONLY_CONSENSUS = "RESEARCH_ONLY_CONSENSUS"


@dataclass(frozen=True)
class ImpliedProbability:
    """1 / decimal odds of one offer. It still contains the bookmaker's margin, so a complete
    outcome set sums to more than 1. It is not a fair estimate and not a quote."""

    label: str
    offer_market_id: str
    bookmaker: str
    probability: Decimal
    executable: bool = False


@dataclass(frozen=True)
class ConsensusEstimate:
    """A research-only cross-book consensus: the per-outcome median of the books' de-vigged
    estimates for one exact proposition (same event, market, outcomes and lines), renormalized
    to sum to 1. It is not a quote, not a model and not executable anywhere."""

    label: str
    method: str
    event_id: str
    market_key: str
    outcomes: tuple[tuple[str, str | None], ...]
    probabilities: tuple[Decimal, ...]
    bookmakers: tuple[str, ...]
    executable: bool = False


def devig_probabilities(decimal_odds: Sequence[Decimal | None]) -> DevigEstimate | None:
    """Proportional de-vig of a complete outcome set; None if any price is missing or invalid."""
    if len(decimal_odds) < 2 or any(d is None or d <= 1 for d in decimal_odds):
        return None
    implied = [Decimal(1) / d for d in decimal_odds]  # type: ignore[operator]
    total = sum(implied, Decimal(0))
    return DevigEstimate(label=RESEARCH_ONLY, method="proportional_v1",
                         probabilities=tuple(p / total for p in implied), overround=total - 1)


@dataclass(frozen=True)
class CoverageRecord:
    scope: str  # "bookmaker" | "market"
    key: str
    status: CoverageStatus
    detail: str


@dataclass(frozen=True)
class OddsSnapshot:
    events: tuple[Event, ...]
    markets: tuple[Market, ...]
    offers: tuple[OddsOffer, ...]
    problems: tuple[str, ...]
    received_at_utc: str | None
    evidence_id: str | None

    def to_dict(self) -> dict[str, Any]:
        def plain(v: Any) -> Any:
            if isinstance(v, Decimal):
                return str(v)
            if isinstance(v, Enum):
                return v.value
            if isinstance(v, (list, tuple)):
                return [plain(x) for x in v]
            if isinstance(v, dict):
                return {k: plain(x) for k, x in v.items()}
            return v
        return plain(asdict(self))


def event_id(native_id: str) -> str:
    return f"{VENUE}:{native_id}"


def offer_market_id(native_event: str, bookmaker: str, market_key: str, outcome: str, point: str | None) -> str:
    tail = f":{point}" if point is not None else ""
    return f"{VENUE}:{bookmaker}:{native_event}:{market_key}:{outcome}{tail}"


def parse_odds(payload: Any, *, odds_format: str, received_at_utc: str | None = None,
               evidence_id: str | None = None) -> OddsSnapshot:
    """Events, one `Market` per (bookmaker, market, outcome) and the raw offers.

    Nothing here is an ExecutableQuote. Markets are `rules_resolved=False`: each sportsbook
    settles by its own house rules, which are not captured."""
    if odds_format not in ("decimal", "american"):
        raise ValueError("odds_format must be 'decimal' or 'american'")
    events: list[Event] = []
    markets: list[Market] = []
    offers: list[OddsOffer] = []
    problems: list[str] = []
    if not isinstance(payload, list):
        return OddsSnapshot((), (), (), ("odds payload is not a list of events",), received_at_utc, evidence_id)
    for raw_event in payload:
        if not isinstance(raw_event, Mapping) or not raw_event.get("id"):
            problems.append("event without an id skipped")
            continue
        native = str(raw_event["id"])
        commence = raw_event.get("commence_time")
        commence_dt = parse_utc(commence)
        eid = event_id(native)

        def _text(key: str) -> str | None:
            value = raw_event.get(key)
            return value if isinstance(value, str) and value else None
        ident = dict(sport_key=_text("sport_key"), league=_text("sport_title"), home_team=_text("home_team"),
                     away_team=_text("away_team"),
                     commence_time_utc=commence_dt.astimezone(timezone.utc).isoformat() if commence_dt else None)
        events.append(Event(
            domain="sports", event_id=eid,
            target_date=commence_dt.date().isoformat() if commence_dt else "UNKNOWN",  # UTC date
            target_time_utc=commence_dt.isoformat() if commence_dt else None,
            outcome_cluster=eid,
            # Venue-local and unverified: no two venues' identities are equal by construction.
            settlement_identity=f"{VENUE}:unverified:{raw_event.get('sport_key')}:{native}",
        ))
        for book in raw_event.get("bookmakers") or []:
            if not isinstance(book, Mapping) or not book.get("key"):
                problems.append(f"{native}: bookmaker without a key skipped")
                continue
            bkey = str(book["key"])
            for market in book.get("markets") or []:
                if not isinstance(market, Mapping) or not market.get("key"):
                    problems.append(f"{native}/{bkey}: market without a key skipped")
                    continue
                mkey = str(market["key"])
                updated = market.get("last_update") or book.get("last_update")
                for outcome in market.get("outcomes") or []:
                    if not isinstance(outcome, Mapping) or outcome.get("name") is None:
                        problems.append(f"{native}/{bkey}/{mkey}: outcome without a name skipped")
                        continue
                    name = str(outcome["name"])
                    point = None if outcome.get("point") is None else str(outcome["point"])
                    decimal_odds = to_decimal_odds(outcome.get("price"), odds_format)
                    if decimal_odds is None:
                        problems.append(f"{native}/{bkey}/{mkey}/{name}: invalid price {outcome.get('price')!r}")
                    mid = offer_market_id(native, bkey, mkey, name, point)
                    offers.append(OddsOffer(eid, mid, bkey, mkey, name, point, str(outcome.get("price")),
                                            odds_format, decimal_odds, None if updated is None else str(updated),
                                            **ident))
                    if decimal_odds is None:
                        continue  # the offer is kept as evidence; no Market with a made-up payoff
                    markets.append(Market(
                        venue=VENUE, market_id=mid, native_id=f"{native}:{mkey}:{name}" + (f":{point}" if point else ""),
                        event_id=eid, outcome=name if point is None else f"{name} {point}",
                        payoff=Payoff(kind="sportsbook_fixed_odds_per_unit_stake", amount=decimal_odds,
                                      yes_condition=f"{mkey}: {name}" + (f" {point}" if point else "")),
                        rules_sha256=None, status=MarketStatus.UNKNOWN, rules_resolved=False,
                        rules_detail=f"sportsbook house rules of {bkey} are not captured; offered odds only",
                    ))
    return OddsSnapshot(tuple(events), tuple(markets), tuple(offers), tuple(problems), received_at_utc, evidence_id)


def devig_by_market(snapshot: OddsSnapshot) -> dict[tuple[str, str, str], DevigEstimate | None]:
    """Research-only de-vig per (event, bookmaker, market) for the supported market keys.

    Spreads and totals are grouped by the normalized absolute line so both sides of one line
    pair up. This is a legacy per-book, whole-outcome-set view: it would de-vig a three-way set
    too, and it does not check that spread sides are exact opposites. Neither consensus uses it;
    both pool only exact two-sided complements from `pair_offers`."""
    groups: dict[tuple[str, str, str], list[OddsOffer]] = {}
    for offer in snapshot.offers:
        if offer.market_key not in SUPPORTED_MARKETS:
            continue
        line = "" if offer.point is None else _abs_line(offer.point)
        groups.setdefault((offer.event_id, offer.bookmaker, f"{offer.market_key}{':' + line if line else ''}"),
                          []).append(offer)
    out: dict[tuple[str, str, str], DevigEstimate | None] = {}
    for k, v in sorted(groups.items()):
        est = None if k[2].endswith(":invalid-line") else devig_probabilities([o.decimal_odds for o in v])
        out[k] = None if est is None else replace(est, outcomes=tuple((o.outcome_name, normalize_line(o.point))
                                                                      for o in v))
    return out


# --------------------------------------------------------------------------- observation identity


def normalize_line(point: str | None) -> str | None:
    """A spread/total line in one canonical text form ("44.50" and "44.5" are one line), or the
    raw text unchanged when it is not a finite number (never guessed)."""
    if point is None:
        return None
    try:
        value = Decimal(str(point))
    except InvalidOperation:
        return str(point)
    if not value.is_finite():
        return str(point)
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "0") else text


@dataclass(frozen=True)
class ObservationIdentity:
    """Everything that says which proposition an offered price was for.

    Two observations belong to one time series only when EVERY field is equal: provider event
    id, sport, league, home and away team, scheduled start, bookmaker, market, side and line.
    Similar or equal team names never link two events with different provider ids or starts
    (divisional rivals meet twice a season). A rescheduled game starts a new series; the
    provider event id still ties the two for audit."""

    provider: str
    provider_event_id: str
    sport_key: str | None
    league: str | None
    home_team: str | None
    away_team: str | None
    commence_time_utc: str | None
    bookmaker: str
    market_key: str
    side: str
    line: str | None

    @property
    def series_id(self) -> str:
        text = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return "oddsser:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]

    @property
    def complete(self) -> bool:
        """False when the response left any identity field out (sport, teams or start)."""
        return None not in (self.sport_key, self.home_team, self.away_team, self.commence_time_utc)


def observation_identity(offer: OddsOffer) -> ObservationIdentity:
    native = offer.event_id.split(":", 1)[1] if offer.event_id.startswith(f"{VENUE}:") else offer.event_id
    return ObservationIdentity(VENUE, native, offer.sport_key, offer.league, offer.home_team, offer.away_team,
                               offer.commence_time_utc, offer.bookmaker, offer.market_key, offer.outcome_name,
                               normalize_line(offer.point))


@dataclass(frozen=True)
class SeriesLinks:
    """Offers grouped into time series, plus what could not be linked safely."""

    series: dict[str, tuple[OddsOffer, ...]]
    identity_conflicts: tuple[str, ...]  # one provider event id reported with different sport/teams
    rescheduled: tuple[str, ...]  # one provider event id reported with different starts
    incomplete: tuple[str, ...]  # series whose identity lacks sport, teams or start


def link_series(offers: Iterable[OddsOffer]) -> SeriesLinks:
    """Group repeated observations (from any number of snapshots) into series by their full
    identity. An event id whose sport or teams disagree across observations is a conflict and
    is reported; its observations stay in separate series, never merged."""
    series: dict[str, list[OddsOffer]] = {}
    seen_event: dict[str, set[tuple]] = {}
    starts: dict[str, set[str | None]] = {}
    incomplete: set[str] = set()
    for offer in offers:
        ident = observation_identity(offer)
        series.setdefault(ident.series_id, []).append(offer)
        seen_event.setdefault(ident.provider_event_id, set()).add(
            (ident.sport_key, ident.league, ident.home_team, ident.away_team))
        starts.setdefault(ident.provider_event_id, set()).add(ident.commence_time_utc)
        if not ident.complete:
            incomplete.add(ident.series_id)
    conflicts = tuple(sorted(e for e, ids in seen_event.items() if len(ids) > 1))
    moved = tuple(sorted(e for e, s in starts.items() if len(s) > 1))
    return SeriesLinks({k: tuple(v) for k, v in sorted(series.items())}, conflicts, moved, tuple(sorted(incomplete)))


# --------------------------------------------------------------------------- research estimates


def implied_probability(offer: OddsOffer) -> ImpliedProbability | None:
    """1 / decimal odds, margin included; None for an invalid price."""
    if offer.decimal_odds is None or offer.decimal_odds <= 1:
        return None
    return ImpliedProbability(IMPLIED_WITH_MARGIN, offer.market_id, offer.bookmaker, Decimal(1) / offer.decimal_odds)


def _median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


# ---- consensus research benchmark (#9, ADR 0033). The canonical pairing and statistics live
# here; `edge_lab.odds_consensus` builds the versioned, point-in-time benchmark from stored
# snapshots on top of them. Nothing here is a price anyone can trade at.

CONSENSUS_VERSION = "odds-consensus-v1"
PAIRED_DEVIG_METHOD = "proportional_two_way_v1"
# Fixed arithmetic for every consensus figure, whatever the caller's decimal context is.
CONSENSUS_DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
_OVER_UNDER = ("Over", "Under")
_DRAW_NAMES = frozenset({"draw", "tie"})


class PairingStatus(str, Enum):
    """Why an offer did or did not enter a clean two-sided pair (one book, one exact line)."""

    PAIRED = "PAIRED"
    MARKET_NOT_SUPPORTED = "MARKET_NOT_SUPPORTED"  # market key outside h2h / spreads / totals
    NOT_TWO_WAY = "NOT_TWO_WAY"  # h2h with a draw or three or more outcomes (no 3-way math yet)
    MISSING_COMPLEMENT = "MISSING_COMPLEMENT"  # no exact opposite side at this line in this book
    AMBIGUOUS_COMPLEMENT = "AMBIGUOUS_COMPLEMENT"  # a side or line listed twice by one book
    INVALID_LINE = "INVALID_LINE"  # non-numeric line, a line on h2h, or no line on a spread/total
    INVALID_PRICE = "INVALID_PRICE"  # this side or its complement has no valid quote
    UNRECOGNIZED_OUTCOME = "UNRECOGNIZED_OUTCOME"  # not Over/Under, or not one of the event's two teams


@dataclass(frozen=True)
class PairedDevig:
    """One book's clean two-sided complement at one exact line, de-vigged proportionally.

    `offers` keep the offered prices exactly as received; `implied` is 1 / decimal odds (the
    margin included); `probabilities` are the de-vigged research estimates (they sum to 1).
    The three are different things and are never substituted for one another."""

    event_id: str
    bookmaker: str
    market_key: str
    proposition: tuple[tuple[str, str | None], tuple[str, str | None]]  # canonical order
    offers: tuple[OddsOffer, OddsOffer]  # same order as `proposition`
    implied: tuple[Decimal, Decimal]
    probabilities: tuple[Decimal, Decimal]
    overround: Decimal
    label: str = RESEARCH_ONLY
    method: str = PAIRED_DEVIG_METHOD
    executable: bool = False


@dataclass(frozen=True)
class UnpairedOffer:
    """An offer that is kept as evidence but enters no consensus, with the reason."""

    offer: OddsOffer
    status: PairingStatus
    reason: str


def _negated_line(line: str) -> str | None:
    try:
        value = Decimal(line)
    except InvalidOperation:
        return None
    return normalize_line(str(-value)) if value.is_finite() else None


def _numeric_line(point: str | None) -> str | None:
    """The normalized line when `point` is a finite number, else None."""
    if point is None:
        return None
    try:
        value = Decimal(str(point))
    except InvalidOperation:
        return None
    return normalize_line(str(point)) if value.is_finite() else None


def _pair_one_market(offers: list[OddsOffer]) -> tuple[list[PairedDevig], list[UnpairedOffer]]:
    """Pair the offers of one (event, bookmaker, market). Exact complements only:

    - h2h: exactly two outcomes, no draw, no line; when the response names the event's home and
      away teams, the two outcomes must be exactly those teams;
    - spreads: (team A, line L) with (team B, line -L), the two teams of the event;
    - totals: (Over, L) with (Under, L).
    Anything else is unpaired with a reason. Nothing is guessed."""
    first = offers[0]
    market = first.market_key
    paired: list[PairedDevig] = []
    unpaired: list[UnpairedOffer] = []

    def refuse(items: Iterable[OddsOffer], status: PairingStatus, reason: str) -> None:
        unpaired.extend(UnpairedOffer(o, status, reason) for o in items)

    if market not in SUPPORTED_MARKETS:
        refuse(offers, PairingStatus.MARKET_NOT_SUPPORTED, f"market {market!r} has no consensus math")
        return paired, unpaired
    teams = {first.home_team, first.away_team} if first.home_team and first.away_team else None
    known: set[str] | None = None  # the two team names a spread pairs between

    def make_pair(a: OddsOffer, b: OddsOffer, a_line: str | None, b_line: str | None) -> None:
        sides = sorted([(a, (a.outcome_name, a_line)), (b, (b.outcome_name, b_line))],
                       key=lambda s: (s[1][0], s[1][1] or ""))
        bad = [o for o, _ in sides if o.decimal_odds is None or o.decimal_odds <= 1]
        if bad:
            names = ", ".join(sorted(o.outcome_name for o in bad))
            refuse([a, b], PairingStatus.INVALID_PRICE, f"no valid price for {names}; the pair is not de-vigged")
            return
        implied = tuple(Decimal(1) / o.decimal_odds for o, _ in sides)  # type: ignore[operator]
        total = implied[0] + implied[1]
        paired.append(PairedDevig(first.event_id, first.bookmaker, market, (sides[0][1], sides[1][1]),
                                  (sides[0][0], sides[1][0]), (implied[0], implied[1]),
                                  (implied[0] / total, implied[1] / total), total - 1))

    if market == "h2h":
        lined = [o for o in offers if o.point is not None]
        if lined:
            refuse(offers, PairingStatus.INVALID_LINE, "an h2h outcome carries a line")
            return paired, unpaired
        names = [o.outcome_name for o in offers]
        if len(offers) != 2 or any(n.strip().lower() in _DRAW_NAMES for n in names):
            refuse(offers, PairingStatus.NOT_TWO_WAY,
                   f"h2h with {len(offers)} outcome(s) {sorted(names)}: not a clean two-way complement; "
                   "three-way / draw math is not implemented")
            return paired, unpaired
        if names[0] == names[1]:
            refuse(offers, PairingStatus.AMBIGUOUS_COMPLEMENT, f"h2h lists {names[0]!r} twice")
            return paired, unpaired
        if teams is not None and set(names) != teams:
            refuse(offers, PairingStatus.UNRECOGNIZED_OUTCOME,
                   f"h2h outcomes {sorted(names)} are not the event's teams {sorted(teams)}")
            return paired, unpaired
        make_pair(offers[0], offers[1], None, None)
        return paired, unpaired

    # spreads and totals: every offer needs a finite line, grouped by exact normalized line.
    by_side: dict[tuple[str, str], list[OddsOffer]] = {}
    for o in offers:
        line = _numeric_line(o.point)
        if line is None:
            refuse([o], PairingStatus.INVALID_LINE, f"line {o.point!r} is not a finite number")
            continue
        if market == "totals" and o.outcome_name not in _OVER_UNDER:
            refuse([o], PairingStatus.UNRECOGNIZED_OUTCOME, f"totals outcome {o.outcome_name!r} is not Over/Under")
            continue
        by_side.setdefault((o.outcome_name, line), []).append(o)
    if market == "spreads":
        names = {name for name, _ in by_side}
        known = teams if teams is not None else (names if len(names) == 2 else None)
        if known is None:
            for side in sorted(by_side):
                refuse(by_side[side], PairingStatus.UNRECOGNIZED_OUTCOME,
                       f"spread outcomes {sorted(names)} do not name exactly two teams")
            return paired, unpaired
        for side in sorted(k for k in by_side if k[0] not in known):
            refuse(by_side.pop(side), PairingStatus.UNRECOGNIZED_OUTCOME,
                   f"spread outcome {side[0]!r} is not one of the event's teams {sorted(known)}")

    def complement(side: tuple[str, str]) -> tuple[str, str] | None:
        name, line = side
        if market == "totals":
            return ("Under" if name == "Over" else "Over", line)
        other = sorted(known - {name})  # type: ignore[operator]
        negated = _negated_line(line)
        return (other[0], negated) if len(other) == 1 and negated is not None else None

    done: set[tuple[str, str]] = set()
    for side in sorted(by_side):
        if side in done:
            continue
        done.add(side)
        mate = complement(side)
        mine = by_side[side]
        theirs = by_side.get(mate, []) if mate is not None else []
        if mate is not None:
            done.add(mate)
        if not theirs:
            refuse(mine, PairingStatus.MISSING_COMPLEMENT,
                   f"no {mate[0]} {mate[1]} from this book: not an exact opposite line" if mate else
                   "no complement can be formed")
        elif len(mine) > 1 or len(theirs) > 1:
            refuse(mine + theirs, PairingStatus.AMBIGUOUS_COMPLEMENT,
                   f"{side[0]} {side[1]} / {mate[0]} {mate[1]} listed more than once by this book")  # type: ignore[index]
        else:
            make_pair(mine[0], theirs[0], side[1], mate[1])  # type: ignore[index]
    return paired, unpaired


def pair_offers(snapshot: OddsSnapshot) -> tuple[tuple[PairedDevig, ...], tuple[UnpairedOffer, ...]]:
    """Every clean two-sided complement per (event, bookmaker, market, exact line), and every
    other offer with the reason it was left out. Deterministic: sorted, never order-dependent,
    and computed in CONSENSUS_DECIMAL_CONTEXT whatever the caller's decimal context is."""
    with localcontext(CONSENSUS_DECIMAL_CONTEXT):
        return _pair_offers(snapshot)


def _pair_offers(snapshot: OddsSnapshot) -> tuple[tuple[PairedDevig, ...], tuple[UnpairedOffer, ...]]:
    groups: dict[tuple[str, str, str], list[OddsOffer]] = {}
    for offer in snapshot.offers:
        groups.setdefault((offer.event_id, offer.bookmaker, offer.market_key), []).append(offer)
    paired: list[PairedDevig] = []
    unpaired: list[UnpairedOffer] = []
    for key in sorted(groups):
        p, u = _pair_one_market(sorted(groups[key], key=lambda o: (o.outcome_name, o.point or "", o.raw_price)))
        paired += p
        unpaired += u
    paired.sort(key=lambda p: (p.event_id, p.market_key, p.proposition, p.bookmaker))
    unpaired.sort(key=lambda u: (u.offer.event_id, u.offer.market_key, u.offer.bookmaker, u.offer.outcome_name,
                                 u.offer.point or "", u.status.value))
    return tuple(paired), tuple(unpaired)


def group_propositions(paired: Iterable[PairedDevig]
                       ) -> dict[tuple[str, str, tuple[tuple[str, str | None], ...]], tuple[PairedDevig, ...]]:
    """Paired de-vigs pooled by exact proposition: same event, market, outcome names AND lines.
    A -3.5 spread is never pooled with -3, and "44.50" is the same line as "44.5"."""
    pooled: dict[tuple[str, str, tuple[tuple[str, str | None], ...]], list[PairedDevig]] = {}
    for p in paired:
        pooled.setdefault((p.event_id, p.market_key, p.proposition), []).append(p)
    return {k: tuple(sorted(v, key=lambda p: p.bookmaker)) for k, v in sorted(pooled.items())}


def median(values: Sequence[Decimal]) -> Decimal:
    """The median; the mean of the two middle values for an even count. Raises on no values."""
    if not values:
        raise ValueError("the median of no values is undefined")
    return _median(values)


def median_absolute_deviation(values: Sequence[Decimal]) -> Decimal:
    """MAD = median(|x - median(x)|), unscaled (no 1.4826 normal-consistency factor)."""
    centre = median(values)
    return median([abs(v - centre) for v in values])


def consensus_by_market(snapshot: OddsSnapshot, *, min_books: int = 2
                        ) -> dict[tuple[str, str, tuple[tuple[str, str | None], ...]], ConsensusEstimate]:
    """Research-only consensus per exact proposition across bookmakers: the per-outcome median
    of the books' paired de-vigged probabilities (`pair_offers`, `group_propositions`).

    Only clean two-sided complements at one exact line are pooled, so a -3.5 spread is never
    combined with a -3 one and a three-way h2h is never de-vigged. Fewer than `min_books` books
    is not a consensus and produces nothing. The full benchmark (dispersion, freshness, update
    bounds, versioned hashes, point-in-time reads) is `edge_lab.odds_consensus`."""
    if min_books < 2:
        raise ValueError("a consensus needs at least two books")
    with localcontext(CONSENSUS_DECIMAL_CONTEXT):
        return _consensus_by_market(snapshot, min_books)


def _consensus_by_market(snapshot: OddsSnapshot, min_books: int
                         ) -> dict[tuple[str, str, tuple[tuple[str, str | None], ...]], ConsensusEstimate]:
    out = {}
    for key, rows in group_propositions(pair_offers(snapshot)[0]).items():
        books = tuple(p.bookmaker for p in rows)
        if len(set(books)) < min_books or len(set(books)) != len(books):
            continue
        medians = [median([p.probabilities[i] for p in rows]) for i in range(2)]
        total = sum(medians, Decimal(0))
        out[key] = ConsensusEstimate(RESEARCH_ONLY_CONSENSUS, f"{CONSENSUS_VERSION}:median_of_paired_devig",
                                     key[0], key[1], key[2], tuple(m / total for m in medians), books)
    return out


def _abs_line(point: str) -> str:
    """The absolute line of a spread/total, or "invalid-line" (never de-vigged)."""
    try:
        value = Decimal(point)
    except InvalidOperation:
        return "invalid-line"
    if not value.is_finite():
        return "invalid-line"
    return normalize_line(str(abs(value))) or "invalid-line"  # "2.50" and "-2.5" are one line


def coverage(snapshot: OddsSnapshot, *, requested_bookmakers: Sequence[str] = (),
             requested_markets: Sequence[str] = ()) -> list[CoverageRecord]:
    """What the response covered. ABSENT means absent from this response only."""
    returned_books = {o.bookmaker for o in snapshot.offers}
    returned_markets = {o.market_key for o in snapshot.offers}
    out: list[CoverageRecord] = []
    for book in sorted(set(requested_bookmakers) | returned_books | PAID_ONLY_BOOKMAKERS):
        if book in PAID_ONLY_BOOKMAKERS:
            seen = " (present in this response, which is not a free-tier pull)" if book in returned_books else ""
            out.append(CoverageRecord("bookmaker", book, CoverageStatus.PAID_ONLY_NOT_ENABLED,
                                      f"needs a paid plan; never requested on the free tier{seen}"))
        elif book in returned_books:
            out.append(CoverageRecord("bookmaker", book, CoverageStatus.RETURNED, "offers present"))
        else:
            out.append(CoverageRecord("bookmaker", book, CoverageStatus.ABSENT,
                                      "requested but not in this response; not evidence it has no market"))
    for mkey in sorted(set(requested_markets) | returned_markets):
        if mkey in returned_markets and mkey not in SUPPORTED_MARKETS:
            out.append(CoverageRecord("market", mkey, CoverageStatus.UNIMPLEMENTED,
                                      "returned; raw prices kept, but this adapter does not interpret it"))
        elif mkey in returned_markets:
            out.append(CoverageRecord("market", mkey, CoverageStatus.RETURNED, "offers present"))
        else:
            out.append(CoverageRecord("market", mkey, CoverageStatus.ABSENT, "requested but not in this response"))
    return out


def offer_freshness(offer: OddsOffer, *, now: datetime) -> Freshness:
    """Freshness of an offer by its market-level last_update (source registry max age)."""
    return assess(offer.market_last_update_utc, max_age=get_source(SOURCE_ID).max_age["odds"], now=now)

