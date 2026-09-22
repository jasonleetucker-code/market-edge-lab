"""Forward Stage-B collection for EXP-001 (ADR 0012). Read-only public GETs only.

For target date D, the decision time is 18:00 America/New_York on D-1
(`dataset_exp001.decision_time`). Three capture phases write immutable evidence:

- pfm      PFMOKX products from api.weather.gov, so the forecast available at the cutoff
           (decision - 30 min) can be selected by the frozen availability rule.
- decision the KXHIGHNY event for D, its complete market list and one order book per open
           bracket, all received inside [decision - 5 min, decision].
- recheck  every bracket's book again, received 10-15 min after that bracket's decision
           book.

Every phase checks its own timing **before any network work**. An invocation outside its
window is recorded as `rejected_out_of_window` and does nothing else. The timer is never
trusted.

`day_status` re-derives a day's validity from the stored snapshots. A day is VALID only if
every requirement holds; otherwise it is INVALID with reasons. Never a partial day.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .dataset_exp001 import AVAILABILITY_BUFFER, Issuance, decision_time, select_forecast
from .http import HttpFetchError, fetch_json_result
from .kalshi import PACER as KALSHI_PACER, SOURCE as KALSHI_SOURCE
from .nws_cli import NWS_PACER
from .nws_pfm import extract, parse_pfm, sha256_text
from .sources import get_source
from .storage import SnapshotStore

EXPERIMENT = "EXP-001"
SERIES = "KXHIGHNY"
PFM_SOURCE = get_source("nws_pfm_okx")
PFM_LIST_URL = PFM_SOURCE.base_url
PFM_PRODUCT_URL = "https://api.weather.gov/products/{product_id}"
KALSHI_BASE = KALSHI_SOURCE.base_url

DECISION_WINDOW = timedelta(minutes=5)
RECHECK_MIN = timedelta(minutes=10)
RECHECK_MAX = timedelta(minutes=15)
# A decision capture must start at least this long before the decision, so it can finish
# inside the window.
DECISION_START_MARGIN = timedelta(seconds=30)
# A timer that fires slightly early waits for its window instead of being rejected.
EARLY_WAIT_MAX = timedelta(minutes=2)
# Each recheck fetch is aimed this far inside the bracket's [+10, +15] window.
RECHECK_AIM = timedelta(seconds=5)
# Never start a request with less time than this before its deadline.
MIN_REQUEST_BUDGET = timedelta(seconds=3)
REQUEST_TIMEOUT_S = 10.0
PFM_LOOKBACK = timedelta(hours=36)
BOOK_DEPTH = 100
MAX_MARKET_PAGES = 5
OPEN_STATUSES = ("active", "open")

_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December")

Clock = Callable[[], datetime]
Sleep = Callable[[float], None]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DeadlineExceeded(RuntimeError):
    """Not enough time is left inside the capture window for another request."""


class LockBusy(RuntimeError):
    """Another forward capture holds the lock."""


# --------------------------------------------------------------------------- time


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def eastern_offset(instant_utc: datetime) -> timedelta:
    """UTC offset of America/New_York at an instant (the US rule since 2007).
    DST starts on the second Sunday of March at 07:00 UTC and ends on the first Sunday
    of November at 06:00 UTC."""
    year = instant_utc.year
    start = datetime.combine(_nth_sunday(year, 3, 2), datetime.min.time(), timezone.utc) + timedelta(hours=7)
    end = datetime.combine(_nth_sunday(year, 11, 1), datetime.min.time(), timezone.utc) + timedelta(hours=6)
    return timedelta(hours=-4) if start <= instant_utc < end else timedelta(hours=-5)


def eastern_date(instant_utc: datetime) -> date:
    return (instant_utc + eastern_offset(instant_utc)).date()


def target_for(instant_utc: datetime) -> date:
    """The target date D whose decision falls on the Eastern calendar day of `instant_utc`."""
    return eastern_date(instant_utc) + timedelta(days=1)


def event_ticker_for(target: date) -> str:
    return f"{SERIES}-{target:%y}{_MONTHS[target.month - 1]}{target.day:02d}"


def date_labels(target: date) -> tuple[str, ...]:
    """The ways Kalshi has written D in titles and rules: "Sep 23, 2026" (2026-08 on) and
    "July 09, 2026" (earlier rules text). Abbreviated or full month, day with or without a
    leading zero."""
    months = {_MONTH_NAMES[target.month - 1], _MONTH_NAMES[target.month - 1][:3]}
    days = {str(target.day), f"{target.day:02d}"}
    return tuple(sorted(f"{m} {d}, {target.year}" for m in months for d in days))


def windows(target: date) -> dict[str, datetime]:
    _, decision = decision_time(target)
    return {
        "decision": decision,
        "decision_window_start": decision - DECISION_WINDOW,
        "cutoff": decision - AVAILABILITY_BUFFER,
    }


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"naive timestamp {value!r}")
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------- lock


@contextmanager
def exclusive_lock(path: Path, *, timeout_s: float = 60.0, sleep: Sleep = time.sleep) -> Iterator[None]:
    """Serialize forward captures across processes (one pacer budget per host)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    locked = False
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockBusy(f"another forward capture holds {path}") from None
                sleep(0.5)
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


# --------------------------------------------------------------------------- fetching


@dataclass
class _Budget:
    """Deadline-bounded GETs: a request never starts too close to the deadline, and a retry
    backoff that would sleep past it aborts instead."""

    deadline: datetime
    clock: Clock
    sleep: Sleep

    def remaining(self) -> timedelta:
        return self.deadline - self.clock()

    def get(self, url: str, *, pacer, headers: dict[str, str] | None = None):
        remaining = self.remaining()
        if remaining < MIN_REQUEST_BUDGET:
            raise DeadlineExceeded(f"{remaining.total_seconds():.1f}s left before {url}")

        def bounded_sleep(seconds: float) -> None:
            if self.remaining() - timedelta(seconds=seconds) < MIN_REQUEST_BUDGET:
                raise DeadlineExceeded(f"retry backoff of {seconds:.1f}s would pass the deadline")
            self.sleep(seconds)

        timeout = min(REQUEST_TIMEOUT_S, max(remaining.total_seconds() - 1.0, 1.0))
        return fetch_json_result(
            url, headers=headers, timeout=timeout, retries=2, pacer=pacer, sleep=bounded_sleep
        )


def _save(store: SnapshotStore, *, run_id: str, spec, kind: str, entity_id: str, url: str, payload, fetch) -> int:
    return store.save_snapshot(
        run_id=run_id,
        source=spec.legacy_name,
        kind=kind,
        entity_id=entity_id,
        url=url,
        payload=payload,
        fetch=fetch,
        source_id=spec.source_id,
        parser_version=spec.parser_version,
        schema_version=spec.schema_version,
    )


# --------------------------------------------------------------------------- outcomes


@dataclass
class CaptureOutcome:
    phase: str
    target_date: date
    status: str
    reasons: list[str] = field(default_factory=list)
    links: dict[str, Any] = field(default_factory=dict)
    capture_id: int | None = None
    records: int = 0

    @property
    def exit_code(self) -> int:
        return 0 if self.status in ("complete", "skipped_duplicate") else 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "target_date": self.target_date.isoformat(),
            "status": self.status,
            "reasons": self.reasons,
            "capture_id": self.capture_id,
            "records": self.records,
        }


def _record(
    store: SnapshotStore,
    outcome: CaptureOutcome,
    *,
    run_id: str,
    mode: str,
    started: datetime,
    clock: Clock,
    window: tuple[datetime, datetime],
    decision_capture_id: int | None = None,
) -> CaptureOutcome:
    outcome.capture_id = store.record_forward_capture(
        run_id=run_id,
        experiment=EXPERIMENT,
        phase=outcome.phase,
        mode=mode,
        target_date=outcome.target_date.isoformat(),
        event_ticker=event_ticker_for(outcome.target_date),
        started_at_utc=_iso(started),
        completed_at_utc=_iso(clock()),
        window_start_utc=_iso(window[0]),
        window_end_utc=_iso(window[1]),
        status=outcome.status,
        reasons=outcome.reasons,
        links=outcome.links,
        decision_capture_id=decision_capture_id,
        code_version=os.environ.get("EDGE_LAB_CODE_VERSION"),
    )
    return outcome


def _latest_complete(store: SnapshotStore, target: date, phase: str, mode: str):
    rows = [r for r in store.forward_captures(target_date=target.isoformat(), phase=phase, mode=mode)
            if r["status"] == "complete"]
    return rows[-1] if rows else None


@dataclass(frozen=True)
class Gate:
    """Whether a phase may do network work now. `status` is None to proceed, or the status to
    record without any network work (rejected_* / skipped_duplicate)."""

    phase: str
    target: date
    window: tuple[datetime, datetime]
    status: str | None = None
    reasons: tuple[str, ...] = ()
    decision: Any = None  # the decision capture row a recheck belongs to
    wait_s: float = 0.0  # decision: a timer that fired slightly early waits this long


def gate(phase: str, store: SnapshotStore, now: datetime, *, mode: str = "live") -> Gate:
    """The single timing and duplicate gate, evaluated before any network call."""
    target = target_for(now)
    w = windows(target)
    decision = None
    wait_s = 0.0
    if phase == "pfm":
        window = (w["cutoff"], w["decision"])
        if not (window[0] <= now < window[1]):
            return Gate(phase, target, window, "rejected_out_of_window",
                        (f"now {_iso(now)} outside [{_iso(window[0])}, {_iso(window[1])})",))
    elif phase == "decision":
        window = (w["decision_window_start"], w["decision"])
        early = window[0] - now
        if timedelta(0) < early <= EARLY_WAIT_MAX:
            wait_s = early.total_seconds()
        start_at = now + timedelta(seconds=wait_s)
        latest_start = window[1] - DECISION_START_MARGIN
        if not (window[0] <= start_at <= latest_start):
            return Gate(phase, target, window, "rejected_out_of_window",
                        (f"now {_iso(now)} outside [{_iso(window[0])}, {_iso(latest_start)}]",))
    elif phase == "recheck":
        decision = _latest_complete(store, target, "decision", mode)
        if decision is None:
            window = (w["decision"] - DECISION_WINDOW + RECHECK_MIN, w["decision"] + RECHECK_MAX)
            return Gate(phase, target, window, "rejected_no_decision_capture",
                        (f"no complete decision capture for {target.isoformat()}",))
        books = json.loads(decision["links_json"])["books"]
        times = sorted(_parse(b["fetched_at_utc"]) for b in books.values())
        window = (times[0] + RECHECK_MIN, times[-1] + RECHECK_MAX)
        # Too late for the last bracket's window means nothing can be captured. Starting
        # early is fine: each bracket waits for its own window.
        if not (times[0] <= now <= window[1] - MIN_REQUEST_BUDGET):
            return Gate(phase, target, window, "rejected_out_of_window",
                        (f"now {_iso(now)} outside the recheck windows [{_iso(window[0])}, {_iso(window[1])}]",),
                        decision=decision)
        prior = [r for r in store.forward_captures(target_date=target.isoformat(), phase="recheck", mode=mode)
                 if r["status"] == "complete" and r["decision_capture_id"] == decision["id"]]
        if prior:
            return Gate(phase, target, window, "skipped_duplicate", ("complete recheck already exists",),
                        decision=decision)
        return Gate(phase, target, window, decision=decision)
    else:
        raise ValueError(f"unknown phase {phase!r}")
    if _latest_complete(store, target, phase, mode) is not None:
        return Gate(phase, target, window, "skipped_duplicate", (f"complete {phase} capture already exists",))
    return Gate(phase, target, window, wait_s=wait_s)


def _gated(store: SnapshotStore, phase: str, *, run_id: str, mode: str, clock: Clock, sleep: Sleep):
    """(gate, started, outcome-if-stopped). Waits out an early timer, then re-checks."""
    started = clock()
    g = gate(phase, store, started, mode=mode)
    if g.status is None and g.wait_s > 0:
        sleep(g.wait_s)
        started = clock()
        g = gate(phase, store, started, mode=mode)
    if g.status is None:
        return g, started, None
    outcome = CaptureOutcome(phase, g.target, g.status, list(g.reasons))
    decision_id = int(g.decision["id"]) if g.decision is not None else None
    return g, started, _record(store, outcome, run_id=run_id, mode=mode, started=started, clock=clock,
                               window=g.window, decision_capture_id=decision_id)


def would_proceed(phase: str, store: SnapshotStore, now: datetime, *, mode: str = "live") -> bool:
    """True if `phase` would do network work at `now` (the CLI records source health only then)."""
    return gate(phase, store, now, mode=mode).status is None


# --------------------------------------------------------------------------- pfm


def _pfm_issuances(store: SnapshotStore, *, received_by: datetime) -> tuple[list[Issuance], dict[str, int]]:
    """Every stored PFMOKX product received by `received_by`, parsed, plus sha -> snapshot id."""
    issuances, ids = [], {}
    for row in store.snapshots_of_kind(source=PFM_SOURCE.legacy_name, kind="pfm_product"):
        if _parse(row["fetched_at_utc"]) > received_by:
            continue
        text = json.loads(row["payload_json"]).get("productText") or ""
        forecast = parse_pfm(text)
        if forecast is None:
            continue
        sha = sha256_text(text)
        ids.setdefault(sha, int(row["id"]))
        issuances.append(Issuance(forecast=forecast, product_sha256=sha, extract_sha256=sha256_text(extract(text) or "")))
    return issuances, ids


def select_pfm(store: SnapshotStore, target: date) -> tuple[dict[str, Any] | None, str | None]:
    """The frozen availability rule applied to the products we received before the decision."""
    w = windows(target)
    issuances, ids = _pfm_issuances(store, received_by=w["decision"])
    chosen, reason, after = select_forecast(issuances, target, w["cutoff"])
    if chosen is None:
        return None, reason
    f = chosen.forecast
    return {
        "wmo_header": f.wmo_header,
        "issued_utc": _iso(f.issued_utc),
        "forecast_max_f": f.max_by_date[target],
        "product_sha256": chosen.product_sha256,
        "extract_sha256": chosen.extract_sha256,
        "snapshot_id": ids[chosen.product_sha256],
        "issuances_after_cutoff_ignored": after,
    }, None


def capture_pfm(
    store: SnapshotStore,
    *,
    run_id: str,
    user_agent: str,
    mode: str = "live",
    clock: Clock = _utc_now,
    sleep: Sleep = time.sleep,
    anomalies: list[str] | None = None,
) -> CaptureOutcome:
    anomalies = anomalies if anomalies is not None else []
    g, started, stopped = _gated(store, "pfm", run_id=run_id, mode=mode, clock=clock, sleep=sleep)
    if stopped is not None:
        return stopped
    target, window = g.target, g.window
    outcome = CaptureOutcome("pfm", target, "failed")

    budget = _Budget(window[1], clock, sleep)
    headers = {"User-Agent": user_agent, "Accept": "application/ld+json"}
    try:
        payload, fetch = budget.get(PFM_LIST_URL, pacer=NWS_PACER, headers=headers)
        _save(store, run_id=run_id, spec=PFM_SOURCE, kind="pfm_list", entity_id="OKX",
              url=PFM_LIST_URL, payload=payload, fetch=fetch)
        outcome.records += 1
        graph = payload.get("@graph")
        if not isinstance(graph, list):
            raise ValueError("PFM product list has no @graph list")
        for item in graph:
            product_id = item.get("id") if isinstance(item, dict) else None
            issued = item.get("issuanceTime") if isinstance(item, dict) else None
            if not product_id or not issued:
                anomalies.append("PFM list entry without id/issuanceTime skipped")
                continue
            try:
                issued_at = _parse(issued)
            except ValueError:
                anomalies.append(f"PFM list entry {product_id} has unparseable issuanceTime")
                continue
            if issued_at < started - PFM_LOOKBACK or store.has_snapshot(
                source=PFM_SOURCE.legacy_name, kind="pfm_product", entity_id=product_id
            ):
                continue
            url = PFM_PRODUCT_URL.format(product_id=product_id)
            product, product_fetch = budget.get(url, pacer=NWS_PACER, headers=headers)
            _save(store, run_id=run_id, spec=PFM_SOURCE, kind="pfm_product", entity_id=product_id,
                  url=url, payload=product, fetch=product_fetch)
            outcome.records += 1
    except (HttpFetchError, DeadlineExceeded, ValueError) as exc:
        outcome.reasons.append(f"{type(exc).__name__}: {exc}")

    chosen, reason = select_pfm(store, target)
    if chosen is not None:
        outcome.links["selected"] = chosen
    else:
        outcome.reasons.append(f"no usable forecast: {reason}")
    outcome.status = "complete" if chosen is not None and not outcome.reasons else (
        "partial" if chosen is not None else "failed")
    anomalies.extend(outcome.reasons)
    return _record(store, outcome, run_id=run_id, mode=mode, started=started, clock=clock, window=window)


# --------------------------------------------------------------------------- decision


def _identity_problems(payload: dict[str, Any], target: date) -> list[str]:
    """Hard identity: the event we fetched is the target date's KXHIGHNY event."""
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    problems = []
    if event.get("event_ticker") != event_ticker_for(target):
        problems.append(f"event ticker {event.get('event_ticker')!r} != {event_ticker_for(target)!r}")
    if event.get("series_ticker") != SERIES:
        problems.append(f"series {event.get('series_ticker')!r} != {SERIES!r}")
    return problems


def _check_event(payload: dict[str, Any], target: date) -> list[str]:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    problems = _identity_problems(payload, target)
    text = f"{event.get('title') or ''} {event.get('sub_title') or ''}"
    if not any(label in text for label in date_labels(target)):
        problems.append(f"event title/sub_title do not name {target.isoformat()}")
    return problems


def _check_market(market: Any, target: date) -> list[str]:
    if not isinstance(market, dict) or not market.get("ticker"):
        return ["market entry without ticker"]
    problems = []
    if market.get("event_ticker") != event_ticker_for(target):
        problems.append(f"{market['ticker']}: event_ticker {market.get('event_ticker')!r}")
    rules = market.get("rules_primary") or ""
    if not any(f"for {label}" in rules for label in date_labels(target)):
        problems.append(f"{market['ticker']}: rules_primary does not name {target.isoformat()}")
    return problems


def open_brackets(markets: list[dict[str, Any]]) -> list[str]:
    return sorted(m["ticker"] for m in markets if isinstance(m, dict) and m.get("status") in OPEN_STATUSES)


def _url(path: str, **query: object) -> str:
    from urllib.parse import urlencode

    clean = {k: v for k, v in query.items() if v is not None}
    return f"{KALSHI_BASE}{path}?{urlencode(clean)}" if clean else f"{KALSHI_BASE}{path}"


def capture_decision(
    store: SnapshotStore,
    *,
    run_id: str,
    mode: str = "live",
    clock: Clock = _utc_now,
    sleep: Sleep = time.sleep,
    anomalies: list[str] | None = None,
) -> CaptureOutcome:
    anomalies = anomalies if anomalies is not None else []
    # Timing gate first: no network call happens outside the window.
    g, started, stopped = _gated(store, "decision", run_id=run_id, mode=mode, clock=clock, sleep=sleep)
    if stopped is not None:
        return stopped
    target, window = g.target, g.window
    outcome = CaptureOutcome("decision", target, "failed")

    budget = _Budget(window[1], clock, sleep)
    ticker = event_ticker_for(target)
    books: dict[str, dict[str, Any]] = {}
    brackets: list[str] = []
    try:
        url = _url(f"/events/{ticker}")
        payload, fetch = budget.get(url, pacer=KALSHI_PACER)
        outcome.links["event_snapshot"] = _save(store, run_id=run_id, spec=KALSHI_SOURCE, kind="event",
                                                entity_id=ticker, url=url, payload=payload, fetch=fetch)
        outcome.records += 1
        identity = _identity_problems(payload, target)
        outcome.reasons.extend(_check_event(payload, target))
        if identity:
            raise ValueError("wrong event: " + "; ".join(identity))

        markets: list[dict[str, Any]] = []
        market_snapshots: list[int] = []
        cursor: str | None = None
        for page in range(1, MAX_MARKET_PAGES + 1):
            url = _url("/markets", event_ticker=ticker, limit=1000, cursor=cursor)
            payload, fetch = budget.get(url, pacer=KALSHI_PACER)
            market_snapshots.append(_save(store, run_id=run_id, spec=KALSHI_SOURCE, kind="markets",
                                          entity_id=ticker, url=url, payload=payload, fetch=fetch))
            outcome.records += 1
            page_markets = payload.get("markets")
            if not isinstance(page_markets, list):
                raise ValueError(f"markets page {page} has no markets list")
            markets.extend(page_markets)
            cursor = payload.get("cursor") or None
            if cursor is None:
                break
        else:
            raise ValueError(f"market list still paginating after {MAX_MARKET_PAGES} pages")
        outcome.links["market_snapshots"] = market_snapshots
        for market in markets:
            outcome.reasons.extend(_check_market(market, target))
        brackets = open_brackets(markets)
        outcome.links["brackets"] = brackets
        if not brackets:
            outcome.reasons.append("no open brackets for the target event")
        if any(isinstance(m, dict) and m.get("event_ticker") != ticker for m in markets):
            raise ValueError("market list contains markets of another event")
        inventory_ok = True
    except (HttpFetchError, DeadlineExceeded, ValueError) as exc:
        outcome.reasons.append(f"{type(exc).__name__}: {exc}")
        inventory_ok = False

    # Books are captured whenever the event identity and inventory are sound, even if
    # a wording check failed: that makes the day INVALID, but the evidence is irreplaceable
    # and validity is always re-derived from it.
    if inventory_ok:
        for bracket in brackets:
            url = _url(f"/markets/{bracket}/orderbook", depth=BOOK_DEPTH)
            try:
                payload, fetch = budget.get(url, pacer=KALSHI_PACER)
            except (HttpFetchError, DeadlineExceeded) as exc:
                outcome.reasons.append(f"{bracket}: {type(exc).__name__}: {exc}")
                continue
            snapshot_id = _save(store, run_id=run_id, spec=KALSHI_SOURCE, kind="orderbook",
                                entity_id=bracket, url=url, payload=payload, fetch=fetch)
            outcome.records += 1
            received = _parse(fetch.received_at_utc)
            books[bracket] = {"snapshot_id": snapshot_id, "fetched_at_utc": _iso(received)}
            if not isinstance(payload.get("orderbook_fp"), dict):
                outcome.reasons.append(f"{bracket}: book payload has no orderbook_fp")
            if not (window[0] <= received <= window[1]):
                outcome.reasons.append(f"{bracket}: book received {_iso(received)} outside the decision window")
    outcome.links["books"] = books
    outcome.status = "complete" if not outcome.reasons else ("partial" if outcome.records else "failed")
    anomalies.extend(outcome.reasons)
    return _record(store, outcome, run_id=run_id, mode=mode, started=started, clock=clock, window=window)


# --------------------------------------------------------------------------- recheck


def capture_recheck(
    store: SnapshotStore,
    *,
    run_id: str,
    mode: str = "live",
    clock: Clock = _utc_now,
    sleep: Sleep = time.sleep,
    anomalies: list[str] | None = None,
) -> CaptureOutcome:
    anomalies = anomalies if anomalies is not None else []
    g, started, stopped = _gated(store, "recheck", run_id=run_id, mode=mode, clock=clock, sleep=sleep)
    if stopped is not None:
        return stopped
    target, window = g.target, g.window
    outcome = CaptureOutcome("recheck", target, "failed")
    books = json.loads(g.decision["links_json"])["books"]
    order = sorted(books, key=lambda t: (books[t]["fetched_at_utc"], t))
    decision_id = int(g.decision["id"])

    rechecks: dict[str, dict[str, Any]] = {}
    for bracket in order:
        book_at = _parse(books[bracket]["fetched_at_utc"])
        low, high = book_at + RECHECK_MIN, book_at + RECHECK_MAX
        wait = (low + RECHECK_AIM - clock()).total_seconds()
        if wait > 0:
            sleep(wait)
        url = _url(f"/markets/{bracket}/orderbook", depth=BOOK_DEPTH)
        try:
            payload, fetch = _Budget(high, clock, sleep).get(url, pacer=KALSHI_PACER)
        except (HttpFetchError, DeadlineExceeded) as exc:
            outcome.reasons.append(f"{bracket}: {type(exc).__name__}: {exc}")
            continue
        snapshot_id = _save(store, run_id=run_id, spec=KALSHI_SOURCE, kind="orderbook",
                            entity_id=bracket, url=url, payload=payload, fetch=fetch)
        outcome.records += 1
        received = _parse(fetch.received_at_utc)
        rechecks[bracket] = {"snapshot_id": snapshot_id, "fetched_at_utc": _iso(received)}
        if not isinstance(payload.get("orderbook_fp"), dict):
            outcome.reasons.append(f"{bracket}: book payload has no orderbook_fp")
        if not (low <= received <= high):
            outcome.reasons.append(f"{bracket}: recheck received {_iso(received)} outside [{_iso(low)}, {_iso(high)}]")
    outcome.links = {"books": rechecks}
    outcome.status = "complete" if not outcome.reasons else ("partial" if outcome.records else "failed")
    anomalies.extend(outcome.reasons)
    return _record(store, outcome, run_id=run_id, mode=mode, started=started, clock=clock,
                   window=window, decision_capture_id=decision_id)


# --------------------------------------------------------------------------- validity


def day_status(store: SnapshotStore, target: date, *, mode: str = "live") -> dict[str, Any]:
    """Re-derive one Stage B day from stored evidence: VALID only if every requirement holds."""
    w = windows(target)
    reasons: list[str] = []
    result: dict[str, Any] = {"target_date": target.isoformat(), "event_ticker": event_ticker_for(target),
                              "decision_utc": _iso(w["decision"])}

    chosen, why = select_pfm(store, target)
    if chosen is None:
        reasons.append(f"forecast: {why}")
    result["forecast"] = chosen

    decision = _latest_complete(store, target, "decision", mode)
    recheck = None
    if decision is None:
        reasons.append("no complete decision capture")
    else:
        links = json.loads(decision["links_json"])
        books = links.get("books") or {}
        ids = [links.get("event_snapshot"), *links.get("market_snapshots", []),
               *(b["snapshot_id"] for b in books.values())]
        snaps = store.snapshots_by_id(i for i in ids if i is not None)
        if len(snaps) != len([i for i in ids if i is not None]) or links.get("event_snapshot") is None:
            reasons.append("decision capture links to missing snapshots")
        if any(s["run_id"] != decision["run_id"] for s in snaps.values()):
            reasons.append("decision snapshots belong to a different run")
        event = snaps.get(links.get("event_snapshot"))
        if event is not None:
            reasons.extend(f"event: {p}" for p in _check_event(json.loads(event["payload_json"]), target))
        markets: list[dict[str, Any]] = []
        for sid in links.get("market_snapshots", []):
            snap = snaps.get(sid)
            if snap is None:
                continue
            received = _parse(snap["fetched_at_utc"])
            if not (w["decision_window_start"] <= received <= w["decision"]):
                reasons.append(f"market list received {_iso(received)} outside the decision window")
            markets.extend(json.loads(snap["payload_json"]).get("markets") or [])
        for market in markets:
            reasons.extend(_check_market(market, target))
        brackets = open_brackets(markets)
        if not brackets:
            reasons.append("no open brackets")
        if set(brackets) != set(books):
            reasons.append(f"decision books {sorted(books)} != open brackets {brackets}")
        for bracket, info in books.items():
            snap = snaps.get(info["snapshot_id"])
            if snap is None or snap["entity_id"] != bracket or snap["kind"] != "orderbook":
                reasons.append(f"{bracket}: decision book snapshot missing")
                continue
            received = _parse(snap["fetched_at_utc"])
            if not (w["decision_window_start"] <= received <= w["decision"]):
                reasons.append(f"{bracket}: decision book outside the decision window")
            if not isinstance(json.loads(snap["payload_json"]).get("orderbook_fp"), dict):
                reasons.append(f"{bracket}: decision book has no orderbook_fp")
        rechecks = [r for r in store.forward_captures(target_date=target.isoformat(), phase="recheck", mode=mode)
                    if r["status"] == "complete" and r["decision_capture_id"] == decision["id"]]
        recheck = rechecks[-1] if rechecks else None
        if recheck is None:
            reasons.append("no complete recheck capture")
        else:
            again = json.loads(recheck["links_json"]).get("books") or {}
            again_snaps = store.snapshots_by_id(b["snapshot_id"] for b in again.values())
            for bracket, info in books.items():
                snap = again_snaps.get(again[bracket]["snapshot_id"]) if bracket in again else None
                if snap is None or snap["entity_id"] != bracket or snap["run_id"] != recheck["run_id"]:
                    reasons.append(f"{bracket}: recheck book missing")
                    continue
                book_at, received = _parse(info["fetched_at_utc"]), _parse(snap["fetched_at_utc"])
                if not (book_at + RECHECK_MIN <= received <= book_at + RECHECK_MAX):
                    reasons.append(f"{bracket}: recheck {_iso(received)} not 10-15 min after its book")
                if not isinstance(json.loads(snap["payload_json"]).get("orderbook_fp"), dict):
                    reasons.append(f"{bracket}: recheck book has no orderbook_fp")
        result["brackets"] = brackets
    result["decision_capture_id"] = int(decision["id"]) if decision is not None else None
    result["recheck_capture_id"] = int(recheck["id"]) if recheck is not None else None
    result["status"] = "VALID" if not reasons else "INVALID"
    result["reasons"] = reasons
    return result


def last_closed_target(now_utc: datetime) -> date:
    """The most recent target date whose recheck windows have fully closed by `now_utc`."""
    target = target_for(now_utc)
    close = windows(target)["decision"] + RECHECK_MAX + DECISION_WINDOW
    return target if now_utc >= close else target - timedelta(days=1)


def summary(store: SnapshotStore, *, now_utc: datetime, mode: str = "live") -> dict[str, Any]:
    """Status of the last closed day plus the count of VALID days captured so far."""
    last = last_closed_target(now_utc)
    days = sorted({date.fromisoformat(r["target_date"]) for r in store.forward_captures(mode=mode)})
    statuses = {d.isoformat(): day_status(store, d, mode=mode) for d in days if d <= last}
    valid = [d for d, s in statuses.items() if s["status"] == "VALID"]
    latest = statuses.get(last.isoformat()) or day_status(store, last, mode=mode)
    return {
        "generated_at_utc": _iso(now_utc),
        "experiment": EXPERIMENT,
        "last_closed_target_date": last.isoformat(),
        "last_closed_status": latest["status"],
        "last_closed_reasons": latest["reasons"],
        "valid_days": len(valid),
        "first_valid_day": valid[0] if valid else None,
        "days_with_captures": len(statuses),
        "invalid_days": sorted(d for d, s in statuses.items() if s["status"] != "VALID"),
    }
