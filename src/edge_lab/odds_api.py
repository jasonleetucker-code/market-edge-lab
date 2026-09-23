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
  goes down.
- **No scheduled pulls.** Nothing here runs by itself. A live pull needs the owner's key and
  an approved activation plan (docs/EXECUTION_PLAN.md).

Cost rule, from the v4 guide (https://the-odds-api.com/liveapi/guides/v4/, read 2026-09-23):
`cost = markets x regions`; with `bookmakers`, every group of 10 bookmakers counts as one
region. The provider may charge less (it counts markets actually returned, and an empty
response is free), so the estimate is an upper bound and the response's `x-requests-last`
header is what gets booked.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import quote, urlencode

from . import http
from .forward import LockBusy, exclusive_lock
from .freshness import Freshness, assess, parse_utc
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


def build_request(sport: str, markets: Sequence[str], *, key: str, regions: Sequence[str] | None = None,
                  bookmakers: Sequence[str] | None = None, odds_format: str = "decimal") -> tuple[str, str]:
    """(url with the key, redacted url) for GET /v4/sports/{sport}/odds.

    Paid-only bookmakers are refused rather than silently requested."""
    if not isinstance(sport, str) or not _SLUG.match(sport):
        raise ValueError(f"invalid sport key {sport!r}")
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
    url = f"{BASE_URL}/v4/sports/{quote(sport)}/odds/?{urlencode(params, safe=',')}"
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
        try:
            value = Decimal(text)
        except InvalidOperation:
            raise ValueError(name) from None
        if not value.is_finite() or value < 0 or value != value.to_integral_value():
            raise ValueError(name)
        return int(value)

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

    # -- mutations

    def reconcile(self, headers: Iterable[tuple[str, str]] | Mapping[str, str] | None) -> QuotaState:
        """Record provider headers from a quota-free call (GET /v4/sports)."""
        parsed = parse_quota_headers(headers)

        def apply(data: dict[str, Any], now: datetime) -> QuotaState:
            if parsed is None:
                data["quota_known"] = False
                self._event(data, now, "reconcile_failed", reason="missing or malformed quota headers")
                return QuotaState.QUOTA_UNKNOWN
            self._apply_headers(data, now, parsed)
            data["reconciled_month_utc"] = _month(now)
            self._event(data, now, "reconciled", remaining=parsed.remaining, used=parsed.used)
            return self._state(data, now)[0]
        return self._transaction(apply)

    def _apply_headers(self, data: dict[str, Any], now: datetime, parsed: QuotaHeaders) -> None:
        previous = data.get("last_headers")
        if previous is not None and parsed.used < int(previous["used"]):
            # The provider's own counter went down: its period reset. Only now are local
            # counters reset, and only to what the provider reports.
            self._event(data, now, "provider_reset_observed", previous_used=int(previous["used"]),
                        used=parsed.used)
            data["used_local"] = parsed.used
        data["last_headers"] = {"remaining": parsed.remaining, "used": parsed.used, "last": parsed.last,
                                "observed_at_utc": now.isoformat()}
        data["quota_known"] = True

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
            self._apply_headers(data, now, parsed)
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


def _redacted_result(result: http.FetchResult) -> http.FetchResult:
    return replace(result, requested_url=redact_url(result.requested_url), final_url=redact_url(result.final_url))


def _get(url: str, key: str, *, opener: http.Opener | None, pacer: http.Pacer | None) -> http.FetchResult:
    """One GET with no retries (a retry could spend credits twice). Errors are redacted."""
    try:
        result = http.fetch(url, headers={"User-Agent": USER_AGENT}, retries=0, opener=opener, pacer=pacer,
                            sleep=lambda s: None)
    except http.HttpFetchError as exc:
        raise OddsApiError(redact_text(str(exc), (key,)), status=exc.status) from None
    except Exception as exc:  # anything else: still never leak the key or the chain
        raise OddsApiError(redact_text(f"{type(exc).__name__}: {exc}", (key,))) from None
    return _redacted_result(result)


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
    return OddsFetch(state, "reconciled" if state is not QuotaState.QUOTA_UNKNOWN else "headers unusable",
                     redacted, payload=_decode(result, key), fetch=result, quota_after=state)


def fetch_odds(sport: str, markets: Sequence[str], *, ledger: QuotaLedger, regions: Sequence[str] | None = None,
               bookmakers: Sequence[str] | None = None, odds_format: str = "decimal",
               opener: http.Opener | None = None, pacer: http.Pacer | None = None,
               environ: Mapping[str, str] | None = None) -> OddsFetch:
    """Reserve, send one GET, book the provider's charge. SETUP_NEEDED and quota refusals send
    nothing. A failed call keeps its reservation and raises OddsApiError (redacted)."""
    key = load_key(environ)
    if key is None:
        return OddsFetch(QuotaState.SETUP_NEEDED, _setup_detail(), None)
    cost = estimate_cost(markets, regions, bookmakers)
    url, redacted = build_request(sport, markets, key=key, regions=regions, bookmakers=bookmakers,
                                  odds_format=odds_format)
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
    payload = _decode(result, key)
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
        raise OddsApiError(redact_text(f"invalid JSON from {result.requested_url}", (key,)),
                           status=result.http_status) from None


def save_snapshot(store: Any, *, run_id: str, sport: str, outcome: OddsFetch) -> int:
    """Store one odds response as an immutable snapshot, with redacted provenance only."""
    if outcome.fetch is None or outcome.redacted_url is None:
        raise ValueError("nothing was fetched")
    spec = get_source(SOURCE_ID)
    return store.save_snapshot(run_id=run_id, source=spec.legacy_name, kind="odds", entity_id=sport,
                               url=outcome.redacted_url, payload={"sport": sport, "events": outcome.payload},
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


RESEARCH_ONLY = "RESEARCH_ONLY_ESTIMATE"


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
                                            odds_format, decimal_odds, None if updated is None else str(updated)))
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

    Spreads and totals are grouped by the absolute line so both sides of one line pair up."""
    groups: dict[tuple[str, str, str], list[OddsOffer]] = {}
    for offer in snapshot.offers:
        if offer.market_key not in SUPPORTED_MARKETS:
            continue
        line = "" if offer.point is None else str(abs(Decimal(offer.point)))
        groups.setdefault((offer.event_id, offer.bookmaker, f"{offer.market_key}{':' + line if line else ''}"),
                          []).append(offer)
    return {k: devig_probabilities([o.decimal_odds for o in v]) for k, v in sorted(groups.items())}


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

