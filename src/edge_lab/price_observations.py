"""Prospective later-price observations (ADR 0030): what a market's executable price did after
we decided on it. Read-only public GETs only; research evidence, never an order.

**Why.** A rejected opportunity is research evidence too (issue #50): "did our filters save
us money or filter out good trades?" needs the price path after the decision, up to the close.
That path exists only at the moment it is observed. This module plans the observations,
captures them in bounded manual runs, and keeps every miss visible.

**Phases** (`storage.PRICE_OBSERVATION_PHASES`):

| phase | intended time | source |
|---|---|---|
| decision | the decision time | backfilled from the decision capture (no request) |
| recheck | the re-check book (EXP-001: decision book + 10-15 min) | backfilled from the re-check capture |
| post_decision_1h / post_decision_6h | decision + 1 h / + 6 h | captured |
| pre_close | trading close - 15 min (or a documented reference time) | captured |
| close | trading close - 30 s, only where the venue defines a trading close | captured, labelled below |
| settlement_preceding | expected resolution - 30 min, when that is after the close | captured (lifecycle state) |
| custom | an operator-chosen time (`observe plan --custom`) | captured |

**Close semantics, per venue** (`CLOSE_SEMANTICS`). An observation of the close phase is
labelled `CLOSE` only when the source proves it is the last executable quote before the
defined trading close, up to `CLOSE_PROOF_TOLERANCE`; otherwise it is labelled
`LATEST_PRE_CLOSE` ("latest pre-close observation"), with the failed conditions stored.
- **Kalshi.** Trading close = the market's `close_time`. Markets may close early
  (`can_close_early`), so the time is re-read. `CLOSE` needs all of: the market was open in a
  read taken just before the book; the book was received within 60 s before `close_time` (the
  public book has no sequence number or update time, so "last" is proven only to within that
  tolerance); and a read taken after `close_time` shows the market no longer open with the same
  `close_time` (no extension, no earlier halt). Otherwise `LATEST_PRE_CLOSE`.
- **Polymarket US.** The documentation defines no trading close: `endDate` is only a "market
  end/expiration date", and `assetPriceTerms.windowEnd` is the end of a measurement window, not
  of trading. So no close target is ever planned and nothing is ever labelled `CLOSE`. A
  pre-close target may use `windowEnd` as its reference, and says so in its detail.

**Persistence** (schema v6, `storage`). One immutable target row per intended observation, with
its intended time and due window. One append-only observation row per attempt and side (or one
market-level row). The raw payload is kept by the existing immutable snapshot store (`snapshots`,
written through `forward._save`); each row names its snapshot and the payload's SHA-256. A
target not captured by its deadline becomes `MISSED` with its reason; nothing is overwritten.

**Capture** (`capture`). One bounded, locked, idempotent run. It refuses to start when it could
overlap a protected window (`PROTECTED_WINDOWS_ET`: the 17:40-18:35 ET EXP-001 capture window
through the 18:40 shadow run, and the 11:15/16:15 ET settlement runs), makes at most
`MAX_REQUESTS` GETs through the shared Kalshi pacer, and stops at `MAX_RUN`. A second run in the
same window finds its targets final and sends nothing. **No timer is installed or enabled**: the
schedule is an owner decision (ADR 0030).

CLV-style metrics come later; a price move after a decision is not proof of profit.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import forward, kalshi_quotes, polymarket_us
from .forward import DeadlineExceeded, LockBusy, exclusive_lock
from .freshness import Freshness, parse_utc
from .http import HttpFetchError, Pacer, fetch_json_result
from .kalshi import PACER as KALSHI_PACER, SOURCE as KALSHI_SOURCE, event_ticker_of
from .opportunity import DepthLadder, ExecutableQuote, PriceGrid
from .provenance import bytes_sha256
from .sources import get_source
from .storage import PRICE_OBSERVATION_PHASES, SnapshotStore

POLICY_VERSION = "price-observations-v1"
UTC = timezone.utc

POST_DECISION_OFFSETS = {"post_decision_1h": timedelta(hours=1), "post_decision_6h": timedelta(hours=6)}
PRE_CLOSE_LEAD = timedelta(minutes=15)
CLOSE_AIM = timedelta(seconds=30)  # the close book is fetched this long before close_time
CLOSE_EARLY = timedelta(minutes=2)  # a close target is due from this long before its aim
CLOSE_LAST_START = timedelta(seconds=10)  # never start the close book later than close - 10 s
CLOSE_PROOF_TOLERANCE = timedelta(seconds=60)
CLOSE_CONFIRM_DELAY = timedelta(seconds=5)  # the confirming read is sent this long after close_time
SETTLEMENT_PRECEDING_LEAD = timedelta(minutes=30)
EARLY = timedelta(minutes=5)  # other phases are due from 5 min before their time
LATE = timedelta(minutes=30)  # ... until 30 min after it
PRE_CLOSE_LAST = timedelta(minutes=2)  # a pre-close observation must be received by close - 2 min
DECISION_LOOKBACK = timedelta(days=7)
BACKFILL_PHASES = ("decision", "recheck")  # observed by the forward captures; never fetched here

MAX_TARGETS = 24  # markets per run
MAX_REQUESTS = 40  # GETs per run, all sources together
MAX_RUN = timedelta(minutes=4)  # hard run deadline, close waits included
LOCK_TIMEOUT_S = 5.0
# edgelab-observe.timer's interval (tests/test_deploy_units.py pins the two together). A FAILED target
# whose deadline is later than the next scheduled tick is retried there, so it does not fail the run.
SCHEDULED_TICK_INTERVAL = timedelta(minutes=15)
CLOSE_GUARD = timedelta(seconds=20)  # other groups stop this long before a pending close group's aim
BOOK_DEPTH = forward.BOOK_DEPTH
MAX_LISTING_PAGES = 2

POLYMARKET_SOURCE = get_source(polymarket_us.SOURCE_ID)
POLYMARKET_PACER = Pacer(polymarket_us.MIN_INTERVAL_S)

# Protected windows, America/New_York wall time: a capture never runs while they are open.
PROTECTED_WINDOWS_ET: tuple[tuple[str, dtime, dtime], ...] = (
    ("settlement_run_1115", dtime(11, 13), dtime(11, 30)),
    ("settlement_run_1615", dtime(16, 13), dtime(16, 30)),
    # The EXP-001 capture window (17:40-18:35 ET, ADR 0029) through the 18:40 shadow run.
    ("exp001_capture_window_and_shadow_run", dtime(17, 40), dtime(18, 50)),
)


@dataclass(frozen=True)
class CloseSemantics:
    venue: str
    basis: str  # stored as each target's close_basis
    close_definable: bool
    definition: str


CLOSE_SEMANTICS = {
    "kalshi": CloseSemantics(
        "kalshi", "kalshi_close_time_v1", True,
        "trading close = the market's close_time (may close early; re-read at capture). CLOSE only when the market "
        "was open just before the book, the book was received within 60 s before close_time, and a read after "
        "close_time shows the market no longer open with the same close_time"),
    "polymarket_us": CloseSemantics(
        "polymarket_us", "polymarket_us_no_documented_close_v1", False,
        "no documented trading close (endDate is a market end/expiration date; windowEnd ends a measurement "
        "window): no close target, never CLOSE; lifecycle state is read from the book"),
}

Clock = Callable[[], datetime]
Sleep = Callable[[float], None]


def _now() -> datetime:
    return datetime.now(UTC)


# The clock that stamps `recorded_at_utc`: the run's injected clock (plan's `now`, capture's clock).
_RECORD_CLOCK: ContextVar[Callable[[], datetime]] = ContextVar("price_observation_record_clock", default=_now)


def _attempt_id(run_id: str, target_id: str) -> str:
    """Unique per attempt: the rows of one attempt share it; no two attempts collide."""
    return f"{run_id}:{target_id}:{uuid.uuid4().hex[:12]}"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat()


def _iso_exact(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _t(value: Any) -> datetime | None:
    return parse_utc(value)


def _et(instant: datetime) -> datetime:
    return (instant + forward.eastern_offset(instant)).replace(tzinfo=None)


def _from_et(local: datetime) -> datetime:
    guess = local.replace(tzinfo=UTC) + timedelta(hours=5)
    return (local.replace(tzinfo=UTC) - forward.eastern_offset(guess)).astimezone(UTC)


def protected_window_at(start: datetime, end: datetime) -> tuple[str, datetime, datetime] | None:
    """The first protected window that [start, end] overlaps, or None."""
    day = _et(start).date()
    for offset in (-1, 0, 1):
        d = day + timedelta(days=offset)
        for name, a, b in PROTECTED_WINDOWS_ET:
            w0, w1 = _from_et(datetime.combine(d, a)), _from_et(datetime.combine(d, b))
            if start < w1 and end > w0:
                return name, w0, w1
    return None


# --------------------------------------------------------------------------- decisions


@dataclass(frozen=True)
class DecisionRecord:
    """One evaluated market (qualified or rejected) at its decision time: the planner's input.

    Venue-neutral. `close_time_utc` is set only where the venue defines a trading close;
    `pre_close_reference_utc` is what pre_close is measured from (the close, or a documented
    reference such as a measurement window's end), with `pre_close_reference_basis`."""

    venue: str
    market_id: str
    native_market_id: str
    event_id: str
    native_event_id: str | None
    decision_as_of_utc: datetime
    decision_ref: str
    qualifications: tuple[str, ...] = ()
    close_time_utc: datetime | None = None
    pre_close_reference_utc: datetime | None = None
    pre_close_reference_basis: str | None = None
    expected_resolution_utc: datetime | None = None
    rules_sha256: str | None = None
    price_grid: PriceGrid | None = None
    market_status: str | None = None
    close_time_at_decision_utc: datetime | None = None  # point in time: what the decision-time record said
    # EXP-001: the forward decision capture this decision was evaluated from (for backfill).
    target_date: date | None = None
    decision_capture_id: int | None = None
    origin: str = "ledger_decision"


def _decision_capture(store: SnapshotStore, target: date, evidence_ids: set[int], native: str):
    rows = store.forward_captures(target_date=target.isoformat(), phase="decision")
    usable = [r for r in rows if json.loads(r["links_json"]).get("market_snapshots")]
    for r in reversed(usable):
        book = (json.loads(r["links_json"]).get("books") or {}).get(native)
        if book and int(book["snapshot_id"]) in evidence_ids:
            return r
    complete = [r for r in usable if r["status"] == "complete"]
    return (complete or usable or [None])[-1]


def _kalshi_market_raw(store: SnapshotStore, capture_row, native: str) -> dict[str, Any] | None:
    ids = json.loads(capture_row["links_json"]).get("market_snapshots") or []
    for snap in store.snapshots_by_id(ids).values():
        for m in json.loads(snap["payload_json"]).get("markets") or []:
            if isinstance(m, dict) and m.get("ticker") == native:
                return m
    return None


def decisions_from_ledger(ledger, store: SnapshotStore, *, since: datetime | None = None) -> list[DecisionRecord]:
    """Every market the shadow ledger recorded a decision on (QUALIFY and REJECT alike, every
    account and side), one record per market and decision time, with the venue timing known
    at the decision.

    Read-only: the ledger's recorded decisions are the input; nothing is re-evaluated."""
    by_market: dict[tuple[str, datetime], dict[str, Any]] = {}
    for account in ledger.accounts():
        for row in ledger.entries(account):
            if row["kind"] != "decision":
                continue
            p = json.loads(row["payload_json"])
            as_of = _t(p.get("as_of_utc"))
            market_id = p.get("market_id")
            if as_of is None or not isinstance(market_id, str) or (since is not None and as_of < since):
                continue
            entry = by_market.setdefault((market_id, as_of), {"payload": p, "as_of": as_of, "ids": set(),
                                                              "quals": set(), "evidence": set()})
            entry["ids"].add(str(p.get("decision_id")))
            qual = p.get("qualification") or "UNKNOWN"
            entry["quals"].add(f"{p.get('side')}:{qual}" + (f":{p.get('reason')}" if qual != "QUALIFY" and p.get("reason") else ""))
            for ev in p.get("quote_evidence_ids") or []:
                if isinstance(ev, str) and ev.startswith("snapshot:") and ev[9:].isdigit():
                    entry["evidence"].add(int(ev[9:]))
    records = []
    for (market_id, _), e in sorted(by_market.items()):
        p = e["payload"]
        venue, _, native = market_id.partition(":")
        slot_day = str(p.get("slot") or "").split("|", 1)[0]
        target = date.fromisoformat(slot_day) if len(slot_day) == 10 else None
        common = dict(venue=venue, market_id=market_id, native_market_id=native, event_id=str(p.get("event_id")),
                      decision_as_of_utc=e["as_of"], decision_ref=",".join(sorted(e["ids"])),
                      qualifications=tuple(sorted(e["quals"])), target_date=target)
        if venue != "kalshi" or target is None:
            records.append(DecisionRecord(native_event_id=None, **common))
            continue
        capture = _decision_capture(store, target, e["evidence"], native)
        raw = _kalshi_market_raw(store, capture, native) if capture is not None else None
        timing = kalshi_quotes.timing_from_kalshi(raw) if raw else None
        close = _t(timing.close_time_utc) if timing else None
        at_decision = close
        basis = "kalshi close_time at the decision" if close else None
        # A close time the venue moved later (can_close_early) wins: the latest observed one.
        seen = [r for r in store.price_observations(market_id=market_id) if _t(r["close_time_utc"]) is not None]
        if seen and _t(seen[-1]["close_time_utc"]) != close:
            close = _t(seen[-1]["close_time_utc"])
            basis = f"kalshi close_time re-read at observation {seen[-1]['id']}"
        records.append(DecisionRecord(
            native_event_id=str((raw or {}).get("event_ticker") or event_ticker_of(native)),
            close_time_utc=close, pre_close_reference_utc=close, pre_close_reference_basis=basis,
            expected_resolution_utc=_t(timing.expected_resolution_utc) if timing else None,
            rules_sha256=kalshi_quotes.rules_sha256(raw) if raw else None,
            price_grid=kalshi_quotes.price_grid_from_kalshi(raw) if raw else None,
            market_status=(raw or {}).get("status"), close_time_at_decision_utc=at_decision,
            decision_capture_id=int(capture["id"]) if capture is not None else None, **common))
    return records


# --------------------------------------------------------------------------- planning


def target_id(market_id: str, phase: str, target_utc: datetime) -> str:
    return f"{market_id}|{phase}|{_iso(target_utc)}"


def _shift_out_of_protected(t: datetime, latest: datetime | None) -> tuple[datetime, str | None]:
    """Move a non-close target out of a protected window: to the window's end, or, if that is
    too late (after `latest`), to just before the window."""
    hit = protected_window_at(t, t + MAX_RUN)
    if hit is None:
        return t, None
    name, w0, w1 = hit
    if latest is None or w1 <= latest:
        return w1, name
    return w0 - MAX_RUN - timedelta(minutes=1), name


def _window(phase: str, t: datetime, close: datetime | None) -> tuple[datetime, datetime]:
    if phase == "close":
        assert close is not None
        return t - CLOSE_EARLY, close - CLOSE_LAST_START
    due, deadline = t - EARLY, t + LATE
    if phase == "pre_close" and close is not None:
        deadline = min(deadline, close - PRE_CLOSE_LAST)
    elif close is not None and phase in POST_DECISION_OFFSETS:
        deadline = min(deadline, close - PRE_CLOSE_LAST)
    return due, max(deadline, t)


def targets_for(record: DecisionRecord) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """The captured targets for one decision (decision/recheck are backfilled separately).
    Returns (targets, not_planned) — a phase that cannot be defined is listed with its reason."""
    semantics = CLOSE_SEMANTICS.get(record.venue)
    close = record.close_time_utc if semantics is not None and semantics.close_definable else None
    ref = record.pre_close_reference_utc
    out: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    def add(phase: str, t: datetime, detail: dict[str, Any]) -> None:
        t = t.astimezone(UTC).replace(microsecond=0)
        # Every pre-close phase must fall before the close's own window; the close and the
        # post-close lifecycle read are timed by the close itself.
        latest = (close - PRE_CLOSE_LAST) if close is not None and phase not in ("close", "settlement_preceding") \
            else None
        if phase != "close":
            t, shifted = _shift_out_of_protected(t, latest)
            if shifted:
                detail = {**detail, "shifted_out_of_protected_window": shifted}
                if t <= record.decision_as_of_utc:
                    skipped.append({"phase": phase, "reason": f"PROTECTED_WINDOW_UNAVOIDABLE: {shifted} leaves no "
                                                              "time after the decision and before the close"})
                    return
        if latest is not None and t > latest:
            skipped.append({"phase": phase, "reason": f"AFTER_TRADING_CLOSE: {_iso(t)} is not before close {_iso(close)}"})
            return
        due, deadline = _window(phase, t, close)
        out.append({"target_id": target_id(record.market_id, phase, t), "venue": record.venue,
                    "market_id": record.market_id, "native_market_id": record.native_market_id,
                    "event_id": record.event_id, "native_event_id": record.native_event_id, "phase": phase,
                    "target_utc": _iso(t), "due_from_utc": _iso(due), "deadline_utc": _iso(deadline),
                    "policy_version": POLICY_VERSION, "origin": record.origin, "decision_ref": record.decision_ref,
                    "decision_as_of_utc": _iso(record.decision_as_of_utc),
                    "close_time_utc": _iso(close) if close is not None else None,
                    "close_basis": semantics.basis if semantics else f"{record.venue}_close_undefined",
                    "planned_rules_sha256": record.rules_sha256,
                    "detail": {"qualifications": list(record.qualifications), **detail}})

    for phase, offset in POST_DECISION_OFFSETS.items():
        add(phase, record.decision_as_of_utc + offset, {})
    if ref is not None:
        add("pre_close", ref - PRE_CLOSE_LEAD, {"reference_utc": _iso(ref), "reference_basis": record.pre_close_reference_basis})
    else:
        skipped.append({"phase": "pre_close", "reason": "NO_CLOSE_OR_REFERENCE_TIME: the source states none"})
    if close is not None:
        add("close", close - CLOSE_AIM, {"close_semantics": semantics.definition})
    else:
        why = semantics.definition if semantics else "no close semantics for this venue"
        skipped.append({"phase": "close", "reason": f"CLOSE_NOT_DEFINABLE: {why}"
                        if semantics is None or not semantics.close_definable else "CLOSE_TIME_UNKNOWN"})
    resolution = record.expected_resolution_utc
    if resolution is not None and (close is None or resolution > close + SETTLEMENT_PRECEDING_LEAD):
        add("settlement_preceding", resolution - SETTLEMENT_PRECEDING_LEAD, {"expected_resolution_utc": _iso(resolution)})
    else:
        skipped.append({"phase": "settlement_preceding", "reason": "NO_EXPECTED_RESOLUTION_AFTER_CLOSE"})
    return out, skipped


def custom_target(*, venue: str, native_market_id: str, at: datetime, native_event_id: str | None = None,
                  event_id: str | None = None, note: str | None = None) -> dict[str, Any]:
    """An operator-chosen observation of any market (phase `custom`)."""
    if venue not in CLOSE_SEMANTICS:
        raise ValueError(f"unsupported venue {venue!r}; supported: {sorted(CLOSE_SEMANTICS)}")
    if venue == "kalshi" and native_event_id is None:
        native_event_id = event_ticker_of(native_market_id)
    market_id = f"{venue}:{native_market_id}"
    t = at.astimezone(UTC).replace(microsecond=0)
    return {"target_id": target_id(market_id, "custom", t), "venue": venue, "market_id": market_id,
            "native_market_id": native_market_id, "event_id": event_id or f"{venue}:{native_event_id or native_market_id}",
            "native_event_id": native_event_id, "phase": "custom", "target_utc": _iso(t),
            "due_from_utc": _iso(t - EARLY), "deadline_utc": _iso(t + LATE), "policy_version": POLICY_VERSION,
            "origin": "manual", "decision_ref": None, "decision_as_of_utc": None, "close_time_utc": None,
            "close_basis": CLOSE_SEMANTICS[venue].basis, "planned_rules_sha256": None,
            "detail": {"note": note} if note else {}}


# --------------------------------------------------------------------------- observation rows


def _grid_json(grid: PriceGrid | None) -> str | None:
    if grid is None:
        return None
    return json.dumps({"source": grid.source, "ranges": [[str(r.start), str(r.end), str(r.step)] for r in grid.ranges]},
                      sort_keys=True)


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _freshness(observed: datetime | None, target: Mapping[str, Any]) -> str:
    """Timeliness for the phase: FRESH inside the target's due window, STALE outside it,
    UNKNOWN without a receipt time."""
    if observed is None:
        return Freshness.UNKNOWN.value
    due, deadline = _t(target["due_from_utc"]), _t(target["deadline_utc"])
    if due is None or deadline is None:
        return Freshness.UNKNOWN.value
    return (Freshness.FRESH if due <= observed <= deadline else Freshness.STALE).value


def _base_row(run_id: str, attempt_id: str, target: Mapping[str, Any], *, status: str, reason: str | None = None,
              side: str | None = None, **extra: Any) -> dict[str, Any]:
    row = {"run_id": run_id, "attempt_id": attempt_id, "target_id": target["target_id"], "phase": target["phase"],
           "venue": target["venue"], "market_id": target["market_id"], "native_market_id": target["native_market_id"],
           "event_id": target["event_id"], "side": side, "target_utc": target["target_utc"],
           "collection_status": status, "miss_reason": reason, "recorded_at_utc": _iso_exact(_RECORD_CLOCK.get()()),
           "policy_version": POLICY_VERSION, "freshness": Freshness.UNKNOWN.value}
    row.update(extra)
    return row


def _not_executable(row: dict[str, Any], reason: str) -> dict[str, Any]:
    if row["collection_status"] != "CAPTURED":
        return row
    return {**row, "collection_status": "NOT_EXECUTABLE", "miss_reason": reason, "bid": None, "ask": None,
            "ask_size": None, "depth_json": None, "close_label": None, "close_proof_json": None}


def side_rows(run_id: str, attempt_id: str, target: Mapping[str, Any], *, quotes: Mapping[str, ExecutableQuote],
              ladders: Mapping[str, DepthLadder], received: datetime, snapshot_id: int, source_sha256: str | None,
              common: dict[str, Any], depth_limit: int | None) -> list[dict[str, Any]]:
    """YES and NO rows from one captured book; a missing or anomalous book is NOT_EXECUTABLE."""
    base = dict(observed_at_utc=_iso_exact(received), snapshot_id=snapshot_id, source_sha256=source_sha256,
                freshness=_freshness(received, target), **common)
    if not quotes:
        return [_base_row(run_id, attempt_id, target, status="NOT_EXECUTABLE", reason="BOOK_MISSING: no book in the payload",
                          **base)]
    rows = []
    for side in ("YES", "NO"):
        q, ladder = quotes[side], ladders.get(side)
        src_ts = q.source_timestamp_utc
        if q.anomaly:
            rows.append(_base_row(run_id, attempt_id, target, status="NOT_EXECUTABLE", reason=f"BOOK_ANOMALY: {q.anomaly}",
                                  side=side, source_timestamp_utc=src_ts, **base))
            continue
        depth = None if ladder is None else json.dumps(
            {"asks": [[str(lv.price), str(lv.size)] for lv in ladder.asks], "truncated": ladder.truncated,
             "depth_limit": depth_limit}, sort_keys=True)
        rows.append(_base_row(run_id, attempt_id, target, status="CAPTURED", side=side, source_timestamp_utc=src_ts,
                              bid=_dec(q.best_bid), ask=_dec(q.best_ask),
                              ask_size=_dec(q.displayed_size) if q.best_ask is not None else None,
                              depth_json=depth, **base))
    return rows


# --------------------------------------------------------------------------- backfill (EXP-001)


def _backfill_items(store: SnapshotStore, record: DecisionRecord, now: datetime
                    ) -> list[tuple[dict[str, Any], Callable[[str], list[dict[str, Any]]]]]:
    """decision and recheck targets with row builders from the forward captures' own snapshots.
    Reads only; nothing is requested or written here."""
    if record.venue != "kalshi" or record.target_date is None or record.decision_capture_id is None:
        return []
    target_day = record.target_date
    captures = {int(r["id"]): r for r in store.forward_captures(target_date=target_day.isoformat())}
    decision = captures.get(record.decision_capture_id)
    if decision is None:
        return []
    native = record.native_market_id
    books = json.loads(decision["links_json"]).get("books") or {}
    w = forward.windows(target_day)
    # Point in time: the decision-time market record, never a close time learned later. The
    # re-check capture reads books only, so its rows carry no market fields at all (missing
    # stays missing); its target detail says where the market record is.
    at_decision = _iso(record.close_time_at_decision_utc) if record.close_time_at_decision_utc else None
    decision_fields = dict(price_grid_json=_grid_json(record.price_grid), market_status=record.market_status,
                           close_time_utc=at_decision, rules_sha256=record.rules_sha256)

    def tgt(phase: str, t: datetime, due: datetime, deadline: datetime, detail: dict[str, Any]) -> dict[str, Any]:
        return {"target_id": target_id(record.market_id, phase, t), "venue": "kalshi", "market_id": record.market_id,
                "native_market_id": native, "event_id": record.event_id, "native_event_id": record.native_event_id,
                "phase": phase, "target_utc": _iso(t), "due_from_utc": _iso(due), "deadline_utc": _iso(deadline),
                "policy_version": POLICY_VERSION, "origin": "forward_capture_backfill",
                "decision_ref": record.decision_ref, "decision_as_of_utc": _iso(record.decision_as_of_utc),
                "close_time_utc": at_decision, "close_basis": CLOSE_SEMANTICS["kalshi"].basis,
                "planned_rules_sha256": record.rules_sha256, "detail": detail}

    def book_rows(run_id: str, target: dict[str, Any], info: Mapping[str, Any] | None, capture_row,
                  common: dict[str, Any]) -> list[dict[str, Any]]:
        attempt = _attempt_id(run_id, target["target_id"])
        snap = store.snapshots_by_id([int(info["snapshot_id"])]).get(int(info["snapshot_id"])) if info else None
        if snap is None or snap["entity_id"] != native or snap["kind"] != "orderbook" \
                or snap["run_id"] != capture_row["run_id"]:
            return [_base_row(run_id, attempt, target, status="MISSED",
                              reason=f"NO_BOOK_IN_{target['phase'].upper()}_CAPTURE: capture {capture_row['id']} "
                                     f"({capture_row['status']}) holds no book for {native}", **common)]
        payload = json.loads(snap["payload_json"])
        received = _t(snap["fetched_at_utc"])
        quotes = kalshi_quotes.quotes_from_orderbook(native, payload, received_at_utc=snap["fetched_at_utc"],
                                                     evidence_id=f"snapshot:{snap['id']}")
        ladders = kalshi_quotes.ladders_from_orderbook(native, payload, received_at_utc=snap["fetched_at_utc"],
                                                       evidence_id=f"snapshot:{snap['id']}", depth_limit=BOOK_DEPTH)
        return side_rows(run_id, attempt, target, quotes=quotes, ladders=ladders, received=received,
                         snapshot_id=int(snap["id"]), source_sha256=snap["raw_sha256"] or snap["payload_sha256"],
                         common=common, depth_limit=BOOK_DEPTH)

    items: list[tuple[dict[str, Any], Callable[[str], list[dict[str, Any]]]]] = []
    dec_target = tgt("decision", w["decision"], w["decision_window_start"], w["decision"],
                     {"forward_capture_id": int(decision["id"])})
    items.append((dec_target, lambda run_id: book_rows(run_id, dec_target, books.get(native), decision,
                                                       decision_fields)))
    info = books.get(native)
    book_at = _t(info["fetched_at_utc"]) if info else None
    if book_at is not None:
        rechecks = [r for r in captures.values() if r["phase"] == "recheck" and r["status"] == "complete"
                    and r["decision_capture_id"] == decision["id"]]
        low, high = book_at + forward.RECHECK_MIN, book_at + forward.RECHECK_MAX
        rc_target = tgt("recheck", low, low, high, {
            "decision_book_received_utc": _iso_exact(book_at),
            "market_fields": f"not re-read at the re-check; the market record is in decision capture {decision['id']}"})
        if rechecks:
            rc = rechecks[-1]
            rc_target["detail"]["forward_capture_id"] = int(rc["id"])
            items.append((rc_target, lambda run_id: book_rows(
                run_id, rc_target, (json.loads(rc["links_json"]).get("books") or {}).get(native), rc, {})))
        elif now > high + forward.DECISION_WINDOW:
            items.append((rc_target, lambda run_id: [_base_row(
                run_id, _attempt_id(run_id, rc_target["target_id"]), rc_target, status="MISSED",
                reason="NO_COMPLETE_RECHECK_CAPTURE for this decision capture")]))
    return items


def _backfill_exp001(store: SnapshotStore, run_id: str, record: DecisionRecord, now: datetime,
                     states: dict[str, str | None]) -> dict[str, int]:
    """Write the backfill: plan its targets and record rows for those not yet final. `states`
    is updated in place, so a target shared by two decisions is recorded once."""
    counts = {"planned": 0, "rows": 0}
    for target, rows_fn in _backfill_items(store, record, now):
        if target["target_id"] not in states and store.plan_price_target({**target, "planned_at_utc": _iso_exact(now)}):
            counts["planned"] += 1
            states[target["target_id"]] = None
        if states.get(target["target_id"]) in (None, "FAILED"):
            rows = rows_fn(run_id)
            store.record_price_observations(rows)
            counts["rows"] += len(rows)
            states[target["target_id"]] = rows[-1]["collection_status"]
    return counts


# --------------------------------------------------------------------------- expiry


def _target_states(store: SnapshotStore) -> dict[str, str | None]:
    return {r["target_id"]: r["state"] for r in store.price_targets()}


def capture_work(store: SnapshotStore, now: datetime) -> dict[str, int]:
    """Read only: how many open targets are overdue (to be marked MISSED) and how many are due now."""
    work = {"overdue": 0, "due": 0}
    for t in store.price_targets():
        if t["state"] not in (None, "FAILED") or t["phase"] in BACKFILL_PHASES:
            continue
        if now > _t(t["deadline_utc"]):
            work["overdue"] += 1
        elif _t(t["due_from_utc"]) <= now:
            work["due"] += 1
    return work


def plan_work(store: SnapshotStore, decisions: Sequence[DecisionRecord], now: datetime,
              custom: Sequence[dict[str, Any]] = ()) -> int:
    """Read only: how many writes a plan would make now (new targets, backfill rows, misses).
    Zero means an idle plan, which writes nothing, not even a collection run."""
    states = _target_states(store)
    n = sum(1 for c in custom if c["target_id"] not in states)
    for record in decisions:
        n += sum(1 for t in targets_for(record)[0] if t["target_id"] not in states)
        n += sum(1 for t, _ in _backfill_items(store, record, now) if states.get(t["target_id"]) in (None, "FAILED"))
    return n + capture_work(store, now)["overdue"]


def expire(store: SnapshotStore, run_id: str, now: datetime) -> list[dict[str, str]]:
    """Mark every open target whose deadline has passed MISSED, with its reason."""
    missed = []
    for t in store.price_targets():
        if t["state"] not in (None, "FAILED") or t["phase"] in BACKFILL_PHASES:
            continue  # decision/recheck are settled by the backfill from their own captures
        deadline = _t(t["deadline_utc"])
        if deadline is None or now <= deadline:
            continue
        if _t(t["planned_at_utc"]) and _t(t["planned_at_utc"]) > deadline:
            reason = f"PLANNED_AFTER_DEADLINE: planned {t['planned_at_utc']}, deadline {t['deadline_utc']}"
        elif t["state"] == "FAILED":
            reason = f"NOT_CAPTURED_BY_DEADLINE: last attempt failed ({t['state_reason']})"
        else:
            reason = (f"NOT_CAPTURED_BY_DEADLINE: no successful capture completed in "
                      f"[{t['due_from_utc']}, {t['deadline_utc']}] (policy ADR0030_OPTION_A)")
            hit = protected_window_at(_t(t["due_from_utc"]), deadline)
            if hit is not None:
                reason += f"; the due window overlaps protected window {hit[0]}"
        store.record_price_observations([_base_row(run_id, _attempt_id(run_id, t['target_id']), t, status="MISSED",
                                                    reason=reason)])
        missed.append({"target_id": t["target_id"], "reason": reason})
    return missed


# --------------------------------------------------------------------------- plan


def plan(store: SnapshotStore, *, decisions: Sequence[DecisionRecord], now: datetime,
         custom: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    """Persist targets for every decision (and custom request), backfill decision/recheck from
    stored captures, and mark overdue targets MISSED. No network. Idempotent: an idle plan
    (nothing new, nothing overdue) writes nothing, not even a collection run."""
    report: dict[str, Any] = {"command": "observe plan", "now_utc": _iso_exact(now), "policy_version": POLICY_VERSION,
                              "decisions": len(decisions), "targets_planned": 0, "targets_known": 0,
                              "backfill_rows": 0, "not_planned": [], "missed": []}
    if plan_work(store, decisions, now, custom) == 0:
        report["state"] = "NOTHING_TO_DO"
        return report
    run_id = f"observe-plan-{uuid.uuid4()}"
    report["run_id"] = run_id
    token = _RECORD_CLOCK.set(lambda: now)
    store.start_run(run_id)
    try:
        states = _target_states(store)
        for record in decisions:
            targets, skipped = targets_for(record)
            report["not_planned"] += [{"market_id": record.market_id, **s} for s in skipped]
            for target in targets:
                if target["target_id"] not in states and store.plan_price_target(
                        {**target, "planned_at_utc": _iso_exact(now)}):
                    report["targets_planned"] += 1
                    states[target["target_id"]] = None
                else:
                    report["targets_known"] += 1
            backfill = _backfill_exp001(store, run_id, record, now, states)
            report["targets_planned"] += backfill["planned"]
            report["backfill_rows"] += backfill["rows"]
        for target in custom:
            new = target["target_id"] not in states and store.plan_price_target(
                {**target, "planned_at_utc": _iso_exact(now)})
            report["targets_planned" if new else "targets_known"] += 1
            states.setdefault(target["target_id"], None)
        report["missed"] = expire(store, run_id, now)
    except BaseException:
        store.finish_run(run_id, status="failed", error="observe plan aborted")
        raise
    finally:
        _RECORD_CLOCK.reset(token)
    store.finish_run(run_id, status="succeeded")
    report["state"] = "OK"
    return report


# --------------------------------------------------------------------------- capture


class RequestBudgetExhausted(RuntimeError):
    """This run has used its request allowance."""


@dataclass
class _Requests:
    """At most `limit` GETs, none started too close to the run deadline."""

    limit: int
    deadline: datetime
    clock: Clock
    sleep: Sleep
    used: int = 0

    def get(self, url: str, *, pacer: Pacer, headers: dict[str, str] | None = None, retries: int = 2):
        if self.used >= self.limit:
            raise RequestBudgetExhausted(f"request budget of {self.limit} used")
        remaining = self.deadline - self.clock()
        if remaining < forward.MIN_REQUEST_BUDGET:
            raise DeadlineExceeded(f"{remaining.total_seconds():.1f}s left before {url}")

        def bounded_sleep(seconds: float) -> None:
            if self.deadline - self.clock() - timedelta(seconds=seconds) < forward.MIN_REQUEST_BUDGET:
                raise DeadlineExceeded(f"retry backoff of {seconds:.1f}s would pass the run deadline")
            self.sleep(seconds)

        self.used += 1
        timeout = min(forward.REQUEST_TIMEOUT_S, max(remaining.total_seconds() - 1.0, 1.0))
        return fetch_json_result(url, headers=headers, timeout=timeout, retries=retries, pacer=pacer,
                                 sleep=bounded_sleep)

    def wait_until(self, instant: datetime) -> bool:
        """Sleep until `instant` if the run deadline allows it."""
        delay = (instant - self.clock()).total_seconds()
        if delay <= 0:
            return True
        if instant + forward.MIN_REQUEST_BUDGET > self.deadline:
            return False
        self.sleep(delay)
        return True


_FETCH_ERRORS = (HttpFetchError, DeadlineExceeded, ValueError)


def _kalshi_listing(store: SnapshotStore, run_id: str, event: str, req: _Requests, *, retries: int = 2,
                    max_pages: int = MAX_LISTING_PAGES, require_exhausted: bool = True):
    """Every market of one Kalshi event (bounded pages), each page stored as a snapshot.
    Returns (last snapshot id, last receipt, {ticker: raw market}). With `require_exhausted` false,
    the markets of the pages read are returned even if a cursor remains (the NFL listing: 1 page)."""
    markets: dict[str, dict[str, Any]] = {}
    cursor, snapshot_id, received = None, None, None
    for page in range(1, max_pages + 1):
        url = forward._url("/markets", event_ticker=event, limit=1000, cursor=cursor)
        payload, result = req.get(url, pacer=KALSHI_PACER, retries=retries)
        snapshot_id = forward._save(store, run_id=run_id, spec=KALSHI_SOURCE, kind="markets", entity_id=event,
                                    url=url, payload=payload, fetch=result)
        received = _t(result.received_at_utc)
        rows = payload.get("markets")
        if not isinstance(rows, list):
            raise ValueError(f"markets page {page} for {event} has no markets list")
        markets.update({m["ticker"]: m for m in rows if isinstance(m, dict) and isinstance(m.get("ticker"), str)})
        cursor = payload.get("cursor") or None
        if cursor is None or (page == max_pages and not require_exhausted):
            return snapshot_id, received, markets
    raise ValueError(f"market listing for {event} still paginating after {max_pages} pages")


def _close_proof(target: Mapping[str, Any], pre: Mapping[str, Any], received: datetime,
                 confirm: Mapping[str, Any] | None, confirm_error: str | None,
                 confirm_meta: tuple[int | None, datetime | None]) -> tuple[str, dict[str, Any]]:
    """(label, proof) for a Kalshi close observation (see the module docstring)."""
    failures = []
    close = _t(pre.get("close_time"))
    planned = _t(target["close_time_utc"])
    if close is None:
        failures.append("close_time missing in the pre-book market read")
    elif planned is not None and close != planned:
        failures.append(f"close_time moved: planned {_iso(planned)}, source {_iso(close)}")
    if str(pre.get("status") or "").lower() not in kalshi_quotes.OPEN_STATUSES:
        failures.append(f"market status {pre.get('status')!r} before the book is not open")
    if close is not None and not (close - CLOSE_PROOF_TOLERANCE <= received < close):
        failures.append(f"book received {_iso_exact(received)} not within {int(CLOSE_PROOF_TOLERANCE.total_seconds())} s "
                        f"before close {_iso(close)}")
    confirm_id, confirm_at = confirm_meta
    if confirm_error:
        failures.append(f"post-close confirmation read failed: {confirm_error}")
    elif confirm is None:
        failures.append("market absent from the post-close confirmation read")
    else:
        if close is not None and (confirm_at is None or confirm_at < close):
            failures.append("confirmation read was not received after close_time")
        if str(confirm.get("status") or "").lower() in kalshi_quotes.OPEN_STATUSES:
            failures.append(f"market still {confirm.get('status')!r} after close_time (extended or delayed)")
        if close is not None and _t(confirm.get("close_time")) != close:
            failures.append(f"close_time changed to {confirm.get('close_time')!r} after the book")
    proof = {"close_time_utc": _iso(close) if close else None, "book_received_utc": _iso_exact(received),
             "tolerance_s": int(CLOSE_PROOF_TOLERANCE.total_seconds()), "confirm_snapshot_id": confirm_id,
             "confirm_received_utc": _iso_exact(confirm_at) if confirm_at else None,
             "confirm_status": (confirm or {}).get("status"), "semantics": CLOSE_SEMANTICS["kalshi"].basis}
    if failures:
        return "LATEST_PRE_CLOSE", {**proof, "not_close_because": failures}
    return "CLOSE", proof


def _capture_kalshi_group(store: SnapshotStore, run_id: str, targets: list[Mapping[str, Any]], req: _Requests,
                          clock: Clock) -> tuple[list[list[dict[str, Any]]], list[str]]:
    """One event's due targets of one phase. Returns (rows per attempted target, deferred ids)."""
    phase, event = targets[0]["phase"], targets[0]["native_event_id"]
    attempts: list[list[dict[str, Any]]] = []
    if phase == "close" and not req.wait_until(_t(targets[0]["target_utc"])):
        return [], [t["target_id"] for t in targets]
    nfl = all(is_nfl_target(t) for t in targets)
    if nfl and _nfl_role(targets[0]) == NFL_ROLE_SETTLEMENT:
        return _capture_nfl_settlement_read(store, run_id, targets, req)
    # NFL pairing (owner approval 2026-09-25): one listing page and no in-run retry per GET; the one
    # allowed retry is the next scheduled tick (NFL_MAX_ATTEMPTS), so a game-horizon costs at most 6 GETs.
    retries = 0 if nfl else 2

    def fail_all(reason: str, todo: Iterable[Mapping[str, Any]]) -> None:
        for t in todo:
            attempts.append([_base_row(run_id, _attempt_id(run_id, t['target_id']), t, status="FAILED", reason=reason)])

    try:
        listing_id, listing_at, markets = _kalshi_listing(
            store, run_id, event, req, retries=retries, max_pages=1 if nfl else MAX_LISTING_PAGES,
            require_exhausted=not nfl)
    except RequestBudgetExhausted:
        return [], [t["target_id"] for t in targets]
    except _FETCH_ERRORS as exc:
        fail_all(f"LISTING_FAILED: {type(exc).__name__}: {exc}", targets)
        return attempts, []
    pending: list[tuple[Mapping[str, Any], dict[str, Any], list[dict[str, Any]], datetime | None]] = []
    deferred: list[str] = []
    for t in targets:
        attempt, native = _attempt_id(run_id, t['target_id']), t["native_market_id"]
        raw = markets.get(native)
        if raw is None:
            attempts.append([_base_row(run_id, attempt, t, status="FAILED",
                                       reason=f"MARKET_NOT_IN_EVENT_LISTING: {native} not in {event}")])
            continue
        common = dict(market_status=raw.get("status"), close_time_utc=raw.get("close_time"),
                      rules_sha256=kalshi_quotes.rules_sha256(raw),
                      price_grid_json=_grid_json(kalshi_quotes.price_grid_from_kalshi(raw)))
        source_close, planned_close = _t(raw.get("close_time")), _t(t["close_time_utc"])
        if phase in ("pre_close", "close") and planned_close is not None and source_close != planned_close:
            attempts.append([_base_row(run_id, attempt, t, status="MISSED", snapshot_id=listing_id,
                                       observed_at_utc=_iso_exact(listing_at) if listing_at else None,
                                       reason=f"CLOSE_TIME_CHANGED: planned {t['close_time_utc']}, source now "
                                              f"{raw.get('close_time')!r}; the next plan re-targets it", **common)])
            continue
        status = str(raw.get("status") or "").lower()
        if status not in kalshi_quotes.OPEN_STATUSES:
            attempts.append([_base_row(run_id, attempt, t, status="NOT_EXECUTABLE", snapshot_id=listing_id,
                                       observed_at_utc=_iso_exact(listing_at) if listing_at else None,
                                       freshness=_freshness(listing_at, t),
                                       reason=f"MARKET_NOT_OPEN: status {raw.get('status')!r}", **common)])
            continue
        if phase == "close" and clock() > planned_close - CLOSE_LAST_START:
            attempts.append([_base_row(run_id, attempt, t, status="MISSED", snapshot_id=listing_id,
                                       reason=f"TOO_LATE_FOR_CLOSE: the book request would start after close - "
                                              f"{int(CLOSE_LAST_START.total_seconds())} s", **common)])
            continue
        url = forward._url(f"/markets/{native}/orderbook", depth=BOOK_DEPTH)
        try:
            payload, result = req.get(url, pacer=KALSHI_PACER, retries=retries)
        except RequestBudgetExhausted:
            if nfl:  # the listing was already sent in this run: it counts as this game-horizon's attempt
                attempts.append([_base_row(run_id, attempt, t, status="FAILED", **common,
                                           reason="BOOK_DEFERRED_AFTER_LISTING: the run's request budget was used")])
            else:
                deferred.append(t["target_id"])
            continue
        except _FETCH_ERRORS as exc:
            attempts.append([_base_row(run_id, attempt, t, status="FAILED",
                                       reason=f"BOOK_FAILED: {type(exc).__name__}: {exc}", **common)])
            continue
        snap = forward._save(store, run_id=run_id, spec=KALSHI_SOURCE, kind="orderbook", entity_id=native, url=url,
                             payload=payload, fetch=result)
        received = _t(result.received_at_utc)
        quotes = kalshi_quotes.quotes_from_orderbook(native, payload, received_at_utc=result.received_at_utc,
                                                     evidence_id=f"snapshot:{snap}")
        ladders = kalshi_quotes.ladders_from_orderbook(native, payload, received_at_utc=result.received_at_utc,
                                                       evidence_id=f"snapshot:{snap}", depth_limit=BOOK_DEPTH)
        rows = side_rows(run_id, attempt, t, quotes=quotes, ladders=ladders, received=received, snapshot_id=snap,
                         source_sha256=bytes_sha256(result.body), common=common, depth_limit=BOOK_DEPTH)
        pending.append((t, raw, rows, received))
    if phase == "close" and pending:
        close = _t(targets[0]["close_time_utc"])
        confirm_markets, confirm_error, meta = {}, None, (None, None)
        if not req.wait_until(close + CLOSE_CONFIRM_DELAY):
            confirm_error = "run deadline reached before close_time"
        else:
            try:
                cid, cat, confirm_markets = _kalshi_listing(store, run_id, event, req)
                meta = (cid, cat)
            except (RequestBudgetExhausted, *_FETCH_ERRORS) as exc:
                confirm_error = f"{type(exc).__name__}: {exc}"
        for t, raw, rows, received in pending:
            if received >= close:  # not a pre-close quote at all: keep the evidence, drop the prices
                rows[:] = [_not_executable(r, f"BOOK_RECEIVED_AT_OR_AFTER_CLOSE: {_iso_exact(received)} >= "
                                              f"{_iso(close)}") for r in rows]
                continue
            label, proof = _close_proof(t, raw, received, confirm_markets.get(t["native_market_id"]), confirm_error, meta)
            for r in rows:
                if r["collection_status"] == "CAPTURED":
                    r["close_label"], r["close_proof_json"] = label, json.dumps(proof, sort_keys=True)
    attempts += [rows for _, _, rows, _ in pending]
    return attempts, deferred


def _capture_polymarket(store: SnapshotStore, run_id: str, t: Mapping[str, Any], req: _Requests) -> list[dict[str, Any]]:
    slug, attempt = t["native_market_id"], _attempt_id(run_id, t['target_id'])
    url = polymarket_us.book_url(slug)
    try:
        payload, result = req.get(url, pacer=POLYMARKET_PACER, headers={"User-Agent": polymarket_us.USER_AGENT})
    except _FETCH_ERRORS as exc:
        return [_base_row(run_id, attempt, t, status="FAILED", reason=f"BOOK_FAILED: {type(exc).__name__}: {exc}")]
    snap = store.save_snapshot(run_id=run_id, source=POLYMARKET_SOURCE.legacy_name, kind="book", entity_id=slug,
                               url=url, payload=payload, fetch=result, source_id=POLYMARKET_SOURCE.source_id,
                               parser_version=polymarket_us.PARSER_VERSION, schema_version=POLYMARKET_SOURCE.schema_version)
    received = _t(result.received_at_utc)
    data = payload.get("marketData") if isinstance(payload.get("marketData"), dict) else {}
    state = data.get("state")
    common = dict(market_status=state, close_time_utc=None, rules_sha256=None, price_grid_json=None)
    if data and state != "MARKET_STATE_OPEN":
        return [_base_row(run_id, attempt, t, status="NOT_EXECUTABLE", snapshot_id=snap,
                          observed_at_utc=_iso_exact(received), source_sha256=bytes_sha256(result.body),
                          freshness=_freshness(received, t), reason=f"MARKET_NOT_OPEN: book state {state!r}", **common)]
    quotes = polymarket_us.quotes_from_book(slug, payload, received_at_utc=result.received_at_utc,
                                            evidence_id=f"snapshot:{snap}")
    ladders = polymarket_us.ladders_from_book(slug, payload, received_at_utc=result.received_at_utc,
                                              evidence_id=f"snapshot:{snap}")
    return side_rows(run_id, attempt, t, quotes=quotes, ladders=ladders, received=received, snapshot_id=snap,
                     source_sha256=bytes_sha256(result.body), common=common, depth_limit=None)


def protected_refusal(now: datetime) -> dict[str, Any] | None:
    """The report of a capture that must not start now (it could overlap a protected window), else None."""
    hit = protected_window_at(now, now + MAX_RUN)
    if hit is None:
        return None
    return {"command": "observe capture", "now_utc": _iso_exact(now), "policy_version": POLICY_VERSION,
            "state": "DEFERRED_PROTECTED_WINDOW", "requests": 0,
            "detail": f"[{_iso(now)}, +{int(MAX_RUN.total_seconds())} s] overlaps {hit[0]} "
                      f"({_iso(hit[1])} to {_iso(hit[2])}): no network, no writes"}


def _retry_tick_before(deadline: datetime, after: datetime) -> bool:
    """Whether a later scheduled tick (every SCHEDULED_TICK_INTERVAL after `after`) can still run before
    `deadline`, i.e. one that no protected window defers. Conservative: it assumes the next tick is a
    full interval away."""
    tick = after + SCHEDULED_TICK_INTERVAL
    while tick < deadline:
        if protected_refusal(tick) is None:
            return True
        tick += SCHEDULED_TICK_INTERVAL
    return False


def _check_bounds(max_targets: int, max_requests: int) -> None:
    if not 0 < max_targets <= MAX_TARGETS or not 0 < max_requests <= MAX_REQUESTS:
        raise ValueError(f"max_targets must be in 1..{MAX_TARGETS}, max_requests in 1..{MAX_REQUESTS}")


def capture(store: SnapshotStore, *, clock: Clock | None = None, sleep: Sleep = time.sleep,
            max_targets: int = MAX_TARGETS, max_requests: int = MAX_REQUESTS,
            nfl_enabled: bool | None = None) -> tuple[int, dict[str, Any]]:
    """One bounded capture run over the due targets. The caller holds the collector lock.
    Returns (exit code, report): 1 when a FAILED target cannot be retried by a later scheduled tick
    (`failed_final`), else 0. Retryable failures are recorded and listed in `failed_retrying`.

    NFL pairing targets (`NFL_ORIGIN`) never take priority over an ADR 0030 observation: they are ordered
    after every other target, and a run with a due close target attempts no NFL target at all. They are
    attempted only while the switch is on (`nfl_enabled`, default from the environment; off records them
    MISSED as NFL_CAPTURE_DISABLED), by at most `NFL_MAX_ATTEMPTS` runs per game-horizon (1 for a settled
    read), and their failures never fail the run: they are recorded FAILED and listed in `nfl_failed`."""
    clock = clock or _now
    nfl_on = nfl_capture_enabled() if nfl_enabled is None else nfl_enabled
    _check_bounds(max_targets, max_requests)
    now = clock()
    refusal = protected_refusal(now)
    if refusal is not None:
        return 0, refusal
    report: dict[str, Any] = {"command": "observe capture", "now_utc": _iso_exact(now), "policy_version": POLICY_VERSION,
                              "requests": 0, "attempted": 0, "by_status": {}, "deferred": [], "missed": []}
    if capture_work(store, now) == {"overdue": 0, "due": 0}:
        report["state"] = "NOTHING_DUE"  # an idle run writes nothing, not even a collection run
        return 0, report
    run_id = f"observe-capture-{uuid.uuid4()}"
    token = _RECORD_CLOCK.set(clock)
    store.start_run(run_id)
    report["run_id"] = run_id
    try:
        report["missed"] = expire(store, run_id, now)
        due = [t for t in store.price_targets() if t["state"] in (None, "FAILED")
               and _t(t["due_from_utc"]) <= now <= _t(t["deadline_utc"])
               and t["phase"] not in BACKFILL_PHASES]
        nfl_due = [t for t in due if is_nfl_target(t)]
        if nfl_due:
            held = _nfl_holds(store, nfl_due, nfl_on)
            for t in nfl_due:  # recorded now, with the actual cause; never attempted
                if t["target_id"] in held:
                    store.record_price_observations([_base_row(run_id, _attempt_id(run_id, t["target_id"]), t,
                                                               status="MISSED", reason=held[t["target_id"]])])
            if held:
                report["nfl_held"] = dict(sorted(held.items()))
            due = [t for t in due if t["target_id"] not in held]
            if any(t["phase"] == "close" and not is_nfl_target(t) for t in due):
                # EXP-001 close observations keep the whole run: NFL targets wait for the next tick.
                report["nfl_deferred_for_close"] = sorted(t["target_id"] for t in due if is_nfl_target(t))
                due = [t for t in due if not is_nfl_target(t)]
        due.sort(key=lambda t: (is_nfl_target(t), t["target_utc"], t["market_id"]))
        report["deferred"] = [t["target_id"] for t in due[max_targets:]]
        due = due[:max_targets]
        req = _Requests(max_requests, now + MAX_RUN, clock, sleep)
        by_id = {t["target_id"]: t for t in due}
        failed_targets: dict[str, Mapping[str, Any]] = {}
        groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
        for t in due:  # one listing read per event and phase; a close group shares one close time
            key = (t["venue"], t["native_event_id"] or t["native_market_id"], t["phase"],
                   t["target_utc"] if t["phase"] == "close" else "")
            groups.setdefault(key, []).append(t)
        # Other groups run first, in target order, but never into a pending close: their requests share a
        # deadline capped at the earliest close aim - CLOSE_GUARD, and a group without that budget left is
        # deferred, not started. Close groups then run last with the full run budget. A group whose own
        # deadline has passed is not fetched late: it is deferred, and the next run records it MISSED.
        close_aims = [_t(key[3]) for key in groups if key[2] == "close"]
        full_deadline = req.deadline
        guard = min(close_aims) - CLOSE_GUARD if close_aims else None
        for (venue, _, phase, _), targets in sorted(groups.items(),
                                                    key=lambda kv: (is_nfl_target(kv[1][0]), kv[0][2] == "close")):
            req.deadline = full_deadline if phase == "close" or guard is None else min(full_deadline, guard)
            if phase != "close" and clock() + forward.MIN_REQUEST_BUDGET >= req.deadline:
                report["deferred"] += [t["target_id"] for t in targets]
                continue
            if phase != "close":
                late = [t["target_id"] for t in targets if clock() > _t(t["deadline_utc"])]
                if late:
                    report["deferred"] += late
                    targets = [t for t in targets if t["target_id"] not in late]
                    if not targets:
                        continue
            if venue == "kalshi":
                attempts, deferred = _capture_kalshi_group(store, run_id, targets, req, clock)
            elif venue == "polymarket_us":
                attempts, deferred = [], []
                for t in targets:
                    if req.used >= req.limit:
                        deferred.append(t["target_id"])
                        continue
                    attempts.append(_capture_polymarket(store, run_id, t, req))
            else:
                attempts = [[_base_row(run_id, _attempt_id(run_id, t['target_id']), t, status="FAILED",
                                       reason=f"UNSUPPORTED_VENUE: {venue}")] for t in targets]
                deferred = []
            for rows in attempts:
                store.record_price_observations(rows)
                report["attempted"] += 1
                for r in rows:
                    report["by_status"][r["collection_status"]] = report["by_status"].get(r["collection_status"], 0) + 1
                    if r["collection_status"] == "FAILED":
                        failed_targets[r["target_id"]] = by_id[r["target_id"]]
            report["deferred"] += deferred
        report["requests"] = req.used
    except BaseException:
        store.finish_run(run_id, status="failed", error="observe capture aborted before completion")
        raise
    finally:
        _RECORD_CLOCK.reset(token)
    failed = report["by_status"].get("FAILED", 0)
    store.finish_run(run_id, status="partial" if failed else "succeeded",
                     error=f"{failed} FAILED observation row(s)" if failed else None)
    # A FAILED row stays evidence either way. The run fails (and alerts) only for a target that no later
    # scheduled tick can retry: a close target, or one with no unprotected tick left before its deadline.
    end = clock()
    # A failed NFL target never fails the run (no page: the owner has not agreed to NFL alerts). It is
    # recorded FAILED (the run is partial), listed in `nfl_failed`, retried once if allowed, then MISSED.
    quiet = sorted(i for i, t in failed_targets.items() if is_nfl_target(t))
    if quiet:
        report["nfl_failed"] = quiet
    final = sorted(i for i, t in failed_targets.items() if i not in quiet and (
                   t["phase"] == "close" or not _retry_tick_before(_t(t["deadline_utc"]), end)))
    report["failed_final"] = final
    report["failed_retrying"] = sorted(set(failed_targets) - set(final) - set(quiet))
    report["state"] = ("PARTIAL" if final else "PARTIAL_RETRYING") if failed else (
        "CAPTURED" if report["attempted"] else "NOTHING_DUE")
    return (1 if final else 0), report


# --------------------------------------------------------------------------- status and history


SCHEDULE_POLICY = ("ADR0030_OPTION_A (owner-approved 2026-09-24): edgelab-observe.timer at :05/:20/:35/:50 "
                   "America/New_York; edgelab-observe-close.timer at 04:57:45 UTC; both Persistent=false")
OBSERVE_TIMERS = ("edgelab-observe.timer", "edgelab-observe-close.timer")
CLOSE_TICK_UTC = dtime(4, 57, 45)  # edgelab-observe-close.timer; tests/test_deploy_units.py pins the two
CLOSE_TICK_START_SLACK = timedelta(seconds=5)  # interpreter start and lock before the first request


def timer_states(run: Callable[[Sequence[str]], str] | None = None) -> dict[str, str]:
    """`systemctl is-enabled` / `is-active` per observation timer, as reported; UNKNOWN when unavailable.

    The approved policy is not evidence that the timers run: this is what systemd says now."""
    def default(args: Sequence[str]) -> str:
        import subprocess
        out = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=5)
        return out.stdout.strip()

    run = run or default
    states: dict[str, str] = {}
    for timer in OBSERVE_TIMERS:
        try:
            states[timer] = f"{run(['is-enabled', timer]) or 'unknown'}/{run(['is-active', timer]) or 'unknown'}"
        except Exception as exc:  # no systemd here (tests, Windows, a sandbox): say so, never guess
            states[timer] = f"UNKNOWN ({type(exc).__name__})"
    return states


def close_tick_alignment(targets: Sequence[Mapping[str, Any]], now: datetime) -> dict[str, Any]:
    """Whether each open close target's due window contains the fixed close tick.

    The close timer is pinned to 04:57:45 UTC for the observed 05:00:00Z KXHIGHNY close; the window
    [close - 2 min 30 s, close - 10 s] fits the tick plus 5 s start-up for closes from 04:58:00Z to
    05:00:15Z. Before
    August 2026 close_time was 23:59 ET wall time (03:59Z in summer, 04:59Z in winter). If the venue moves
    it outside that range, every close target would silently become MISSED: this says so beforehand."""
    aligned, misaligned = 0, []
    for t in targets:
        if t["phase"] != "close" or (t["state"] or "PLANNED") not in ("PLANNED", "FAILED"):
            continue
        due, deadline = _t(t["due_from_utc"]), _t(t["deadline_utc"])
        if deadline is None or due is None or deadline < now:
            continue
        tick = datetime.combine(due.date(), CLOSE_TICK_UTC, tzinfo=timezone.utc)
        if tick < due:
            tick += timedelta(days=1)
        if tick + CLOSE_TICK_START_SLACK <= deadline:
            aligned += 1
        else:
            misaligned.append({"target_id": t["target_id"], "close_time_utc": t["close_time_utc"],
                               "due_from_utc": t["due_from_utc"], "deadline_utc": t["deadline_utc"]})
    return {"close_tick_utc": CLOSE_TICK_UTC.isoformat(), "aligned": aligned, "misaligned": misaligned[:10],
            "state": "MISALIGNED" if misaligned else ("ALIGNED" if aligned else "NO_OPEN_CLOSE_TARGET")}


def status(store: SnapshotStore, *, now: datetime,
           systemctl: Callable[[Sequence[str]], str] | None = None) -> dict[str, Any]:
    """Read-only summary: targets by phase and state, the next due, recent misses, schedule health."""
    targets = store.price_targets()
    by_phase: dict[str, dict[str, int]] = {}
    upcoming, misses = [], []
    for t in targets:
        state = t["state"] or "PLANNED"
        if state in ("PLANNED", "FAILED") and _t(t["deadline_utc"]) < now:
            state = "OVERDUE"  # shown as such; the next plan/capture run records it MISSED
        by_phase.setdefault(t["phase"], {})
        by_phase[t["phase"]][state] = by_phase[t["phase"]].get(state, 0) + 1
        if state in ("PLANNED", "FAILED") and _t(t["deadline_utc"]) >= now:
            upcoming.append({"target_id": t["target_id"], "due_from_utc": t["due_from_utc"],
                             "deadline_utc": t["deadline_utc"], "state": state})
        if state == "MISSED":
            reason = t["state_reason"]
            if nfl_label_withheld(t, venue=t["venue"], native_market_id=t["native_market_id"], at_utc=None):
                reason = _withheld_reason(reason)  # EXP-002 label: the code only, never the free text
            misses.append({"target_id": t["target_id"], "reason": reason, "at_utc": t["state_at_utc"]})
    labels: dict[str, int] = {}
    for r in store.price_observations():
        if r["close_label"]:
            labels[r["close_label"]] = labels.get(r["close_label"], 0) + 1
    return {"command": "observe status", "now_utc": _iso_exact(now), "policy_version": POLICY_VERSION,
            "schedule": SCHEDULE_POLICY, "timers": timer_states(systemctl),
            "close_tick_alignment": close_tick_alignment(targets, now),
            "targets": len(targets), "by_phase": dict(sorted(by_phase.items())), "close_labels": labels,
            "next_due": sorted(upcoming, key=lambda u: u["due_from_utc"])[:10],
            "recent_misses": sorted(misses, key=lambda m: m["at_utc"] or "")[-10:]}


# --------------------------------------------------------------------------- EXP-002 labels (display only)
#
# EXP-002's labels are the Kalshi KXNFLGAME books after the T-6h decision (the T-60m pairing books) and the
# settlements (docs/research/EXP002_FREEZE_PROPOSAL.md §4; `sports_evidence` withholds them unless a logged
# --with-results run shows them). `observe status` is not a logged consumer of labels, so for an NFL pairing
# observation at the T-60m horizon (or any horizon other than T-24h / T-6h, or an unknown one), for one received after
# that game's T-6h decision cutoff, and for a settlement read, `market_history` withholds the bid, ask, ask size,
# depth and price grid and reduces the reason to its code; `status` does the same to a missed target's reason.
# Status, timing, snapshot ids and counts stay: they say whether a book was read, never what it priced. The horizon
# and kickoff come from the planner's stored target detail (`plan_nfl_targets`: `nfl_role`, `odds_offset`,
# `commence_utc`); any other Kalshi NFL row (a `KXNFL` series without that detail, e.g. a manual custom target on
# KXNFLGAME or KXNFLSPREAD) has an unknown horizon and is withheld (fails closed). Every
# other row (EXP-001 / KXHIGHNY, ADR 0030 observations) is unchanged. There is no reveal path here; the stored rows
# are unchanged (raw evidence).
NFL_PRE_DECISION_OFFSETS = ("T-24h", "T-6h")
NFL_DECISION_OFFSET = "T-6h"
NFL_LABEL_FIELDS = ("bid", "ask", "ask_size", "depth", "price_grid")
NFL_LABEL_HIDDEN = ("HIDDEN (EXP-002 label: a Kalshi NFL book at T-60m, after the T-6h decision cutoff or at an "
                    "unknown horizon, or a settlement read; its prices, sizes, depth and result are not shown here)")
NFL_SERIES_PREFIX = "KXNFL"  # every Kalshi NFL series (KXNFLGAME, KXNFLSPREAD, ...): fail closed without detail
NFL_LABEL_REASON = "withheld (EXP-002 label)"
_REASON_CODE = re.compile(r"^([A-Z][A-Z0-9_]*):")


def nfl_decision_cutoff(commence_utc: Any) -> datetime | None:
    """EXP-002's T-6h decision cutoff of a game: `odds_schedule.deadline` of its T-6h Odds target under the Odds
    runner's default `PilotConfig` (the cutoff `sports_evidence` uses). None when the kickoff is unknown.

    The kickoff is the one stored in the book target's detail when it was planned. If a game were later moved much
    earlier, its real cutoff would move earlier too and a book between the two cutoffs would be shown. That matters
    only for a T-6h book near its cutoff; a T-24h book is received about 18 h before it, so a reschedule of that size
    is needed before it could matter. Documented rather than handled."""
    from .odds_schedule import DEFAULT_OFFSETS, CaptureTarget, PilotConfig, deadline

    start = _t(commence_utc)
    if start is None:
        return None
    off = next(o for o in DEFAULT_OFFSETS if o.label == NFL_DECISION_OFFSET)
    return deadline(CaptureTarget("", NFL_SPORT, "", off.label, off.priority, start, start - off.before),
                    PilotConfig())


def nfl_label_withheld(target: Any, *, venue: Any, native_market_id: Any, at_utc: Any) -> bool:
    """True when an observation's figures (received at `at_utc`) or a target's reason are EXP-002 labels for
    display: an NFL pairing target whose role is not a book (a settlement read), whose horizon is not T-24h / T-6h
    (T-60m or unknown), or whose receipt is after the game's T-6h decision cutoff (an unknown kickoff or receipt
    fails closed; the cutoff uses the kickoff stored at planning, see `nfl_decision_cutoff`); and any other Kalshi
    NFL row (`KXNFL` series, no stored horizon: fails closed). A row with no receipt holds no figure. False for every
    other market (EXP-001 / KXHIGHNY and ADR 0030 rows are never touched)."""
    nfl_origin = target is not None and is_nfl_target(target)
    if not nfl_origin:
        return str(venue or "") == "kalshi" and str(native_market_id or "").startswith(NFL_SERIES_PREFIX)
    d = _detail(target)
    if d.get("nfl_role") != NFL_ROLE_BOOK or d.get("odds_offset") not in NFL_PRE_DECISION_OFFSETS:
        return True
    if at_utc is None:
        return False
    cutoff, at = nfl_decision_cutoff(d.get("commence_utc")), _t(at_utc)
    return cutoff is None or at is None or at > cutoff


def _withheld_reason(reason: Any) -> Any:
    if not reason:
        return reason
    m = _REASON_CODE.match(str(reason))
    return f"{m.group(1)}: {NFL_LABEL_REASON}" if m else NFL_LABEL_REASON


def _withhold_nfl_label(row: dict[str, Any]) -> dict[str, Any]:
    for k in NFL_LABEL_FIELDS:
        row.pop(k, None)
    row["exp002_label"] = NFL_LABEL_HIDDEN
    row["miss_reason"] = _withheld_reason(row.get("miss_reason"))
    return row


_LABELS = {"CLOSE": f"close (within {int(CLOSE_PROOF_TOLERANCE.total_seconds())} s of trading close)",
           "LATEST_PRE_CLOSE": "latest pre-close observation"}


def market_history(store: SnapshotStore, market_id: str) -> list[dict[str, Any]]:
    """Read-only price path of one market (normalized id, e.g. "kalshi:KXHIGHNY-26SEP24-B67.5")
    for display. One dict per observation row, plus one per target not yet attempted, ordered by
    intended time. Prices are decimal strings as the venue stated them; missing stays None.

    Keys: observation_id, target_id, phase, label, side, venue, market_id, native_market_id,
    event_id, target_utc, observed_at_utc, deviation_s, source_timestamp_utc, bid, ask, ask_size,
    depth ({asks: [[price, size]], truncated, depth_limit} or None), price_grid, freshness,
    market_status, close_time_utc, close_label, close_proof, close_tolerance_s, rules_sha256, snapshot_id,
    source_sha256, collection_status (CAPTURED, NOT_EXECUTABLE, FAILED, MISSED, or PLANNED for a
    target not attempted yet), miss_reason, executable, is_latest_pre_close_observation.

    `label` is the phase, except for the close phase: "close (within 60 s of trading close)" for a
    proven CLOSE (never a bare "close": the public book has no sequence number, so the close is
    proven only to within `close_tolerance_s`), else "latest pre-close observation". `is_latest_pre_close_observation` marks, per side, the last
    CAPTURED quote received before the market's latest known close_time (None when no close
    time is known). Never a midpoint, a last price, or an order.

    EXP-002 labels are withheld (`nfl_label_withheld`): such a row has no bid, ask, ask_size, depth or price_grid
    key, carries `exp002_label`, and its miss_reason is reduced to its code."""
    out: list[dict[str, Any]] = []
    attempted = set()
    targets = {t["target_id"]: t for t in store.price_targets(market_id=market_id)}
    withheld: set[int] = set()
    for r in store.price_observations(market_id=market_id):
        if nfl_label_withheld(targets.get(r["target_id"]), venue=r["venue"], native_market_id=r["native_market_id"],
                              at_utc=r["observed_at_utc"]):
            withheld.add(int(r["id"]))
        attempted.add(r["target_id"])
        observed, target = _t(r["observed_at_utc"]), _t(r["target_utc"])
        out.append({
            "observation_id": int(r["id"]), "target_id": r["target_id"], "phase": r["phase"],
            "label": _LABELS.get(r["close_label"], r["phase"]) if r["phase"] == "close" else r["phase"],
            "side": r["side"], "venue": r["venue"], "market_id": r["market_id"],
            "native_market_id": r["native_market_id"], "event_id": r["event_id"], "target_utc": r["target_utc"],
            "observed_at_utc": r["observed_at_utc"],
            "deviation_s": (observed - target).total_seconds() if observed and target else None,
            "source_timestamp_utc": r["source_timestamp_utc"], "bid": r["bid"], "ask": r["ask"],
            "ask_size": r["ask_size"], "depth": json.loads(r["depth_json"]) if r["depth_json"] else None,
            "price_grid": json.loads(r["price_grid_json"]) if r["price_grid_json"] else None,
            "freshness": r["freshness"], "market_status": r["market_status"], "close_time_utc": r["close_time_utc"],
            "close_label": r["close_label"],
            "close_proof": json.loads(r["close_proof_json"]) if r["close_proof_json"] else None,
            "close_tolerance_s": (json.loads(r["close_proof_json"]).get("tolerance_s")
                                  if r["close_label"] == "CLOSE" else None),
            "rules_sha256": r["rules_sha256"], "snapshot_id": r["snapshot_id"], "source_sha256": r["source_sha256"],
            "collection_status": r["collection_status"], "miss_reason": r["miss_reason"],
            "executable": r["collection_status"] == "CAPTURED", "is_latest_pre_close_observation": None,
        })
    for t in targets.values():
        if t["target_id"] in attempted:
            continue
        out.append({"observation_id": None, "target_id": t["target_id"], "phase": t["phase"], "label": t["phase"],
                    "side": None, "venue": t["venue"], "market_id": t["market_id"],
                    "native_market_id": t["native_market_id"], "event_id": t["event_id"], "target_utc": t["target_utc"],
                    "observed_at_utc": None, "deviation_s": None, "source_timestamp_utc": None, "bid": None,
                    "ask": None, "ask_size": None, "depth": None, "price_grid": None, "freshness": "unknown",
                    "market_status": None, "close_time_utc": t["close_time_utc"], "close_label": None,
                    "close_proof": None, "close_tolerance_s": None, "rules_sha256": None, "snapshot_id": None, "source_sha256": None,
                    "collection_status": "PLANNED", "miss_reason": None, "executable": False,
                    "is_latest_pre_close_observation": None})
    closes = [(_t(h["observed_at_utc"]) or _t(h["target_utc"]), _t(h["close_time_utc"])) for h in out
              if _t(h["close_time_utc"]) is not None]
    close = max(closes, key=lambda c: c[0] or datetime.min.replace(tzinfo=UTC))[1] if closes else None
    if close is not None:
        for side in ("YES", "NO"):
            before = [h for h in out if h["side"] == side and h["executable"] and _t(h["observed_at_utc"]) < close]
            for h in out:
                if h["side"] == side and h["executable"]:
                    h["is_latest_pre_close_observation"] = False
            if before:
                max(before, key=lambda h: (h["observed_at_utc"], h["observation_id"]))["is_latest_pre_close_observation"] = True
    out.sort(key=lambda h: (h["target_utc"] or h["observed_at_utc"] or "", h["observation_id"] or 0))
    return [_withhold_nfl_label(h) if h["observation_id"] in withheld else h for h in out]


# --------------------------------------------------------------------------- Kalshi NFL pairing (EXP-002)
#
# Owner approval 2026-09-25 ("Approve Kalshi NFL capture"; docs/EXECUTION_PLAN.md, bounded by
# docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md section 6, review 2026-10-22). Scope and hard bounds:
# - KXNFLGAME only: both team markets of each game the Odds API pilot captured, at its T-24h / T-6h /
#   T-60m captures. The pairing is reactive: a Kalshi target is planned only after the Odds capture it
#   pairs with was CAPTURED, at that capture's receipt time, so the book always follows the odds it is
#   compared with (point in time) and no book is fetched for a horizon the Odds pilot skipped.
# - Per game-horizon: 1 listing + 2 book GETs, no in-run retry, at most one retry at the next tick
#   (NFL_MAX_ATTEMPTS): at most 6 GETs. Per ET game day: at most one settled-markets read, never retried.
# - Per NFL week (Tuesday-start, America/New_York, by capture time): at most 48 game-horizons and 7
#   settled-markets reads: at most 288 + 7 GETs. The existing per-run caps (24 markets, 40 GETs), the
#   protected windows, the shared Kalshi pacer and the collector lock apply unchanged.
# - Zero Odds API calls: the Odds targets are read from the evidence store only.
# - On by default: the owner approved the capture, so the reviewed, deployed code is the activation
#   record. `NFL_SWITCH=off` in /etc/market-edge-lab/env (install.sh keeps it across installs) is the
#   kill switch: nothing new is planned and pending NFL targets are not attempted (they expire MISSED).
#   Any value other than on/off fails closed (off). No new unit, timer or schema.
# Pair skew: the book is fetched at the first edgelab-observe tick (:05/:20/:35/:50) after the Odds
# capture (edgelab-odds ticks :00/:15/:30/:45), so it follows the odds by about 5 min, or about 20 min
# after a protected-window refusal, a busy lock or a retry. EXP-002 discloses the skew; pairs beyond its
# limit stay in the denominators (option (a)). Same-run capture (option (b)) is a separate follow-up.

NFL_PLAN_VERSION = "kalshi-nfl-pairing-v1"
NFL_ORIGIN = "kalshi_nfl_pairing_v1"
NFL_SWITCH = "EDGE_LAB_KALSHI_NFL_CAPTURE"
NFL_SERIES = "KXNFLGAME"
NFL_SPORT = "americanfootball_nfl"
NFL_ROLE_BOOK = "book"
NFL_ROLE_SETTLEMENT = "settlement_read"
NFL_PLAN_WINDOW = timedelta(minutes=25)  # an Odds capture older than this is never paired late
NFL_TARGET_WINDOW = timedelta(minutes=29)  # target..deadline: at most two 15-minute ticks fit
NFL_MIN_LEAD = timedelta(minutes=5)  # a pregame book is received at least this long before kickoff
NFL_MAX_ATTEMPTS = 2  # the first attempt plus one retry at the next tick
NFL_GETS_PER_ATTEMPT = 3  # 1 listing page + 2 books
NFL_WORST_GETS_PER_GAME_HORIZON = NFL_MAX_ATTEMPTS * NFL_GETS_PER_ATTEMPT  # 6
NFL_WEEKLY_GAME_HORIZONS = 48  # 16 games x 3 horizons: 288 GETs
NFL_WEEKLY_SETTLEMENT_READS = 7
NFL_WEEKLY_GET_CAP = NFL_WEEKLY_GAME_HORIZONS * NFL_WORST_GETS_PER_GAME_HORIZON + NFL_WEEKLY_SETTLEMENT_READS
# The settled-markets read: after the game day's last expected expiration (the recorded KXNFLGAME listing
# has expected_expiration_time = kickoff + 6 h), at an observe tick, in a window only that tick fits.
NFL_SETTLEMENT_AFTER_KICKOFF = timedelta(hours=6, minutes=30)
NFL_SETTLEMENT_WINDOW = timedelta(minutes=9)
NFL_SETTLEMENT_PLAN_LEAD = timedelta(minutes=30)
NFL_SETTLEMENT_PAGE_LIMIT = 100  # a game day has at most 13 games (26 markets); one page, never a second
NFL_MAX_REPORT_ITEMS = 50
NFL_HORIZONS = ("T-24h", "T-6h", "T-60m")  # the approved horizons, exactly; any other Odds offset is not paired
_OBSERVE_TICK_MINUTE = 5  # edgelab-observe.timer: *:05/15 America/New_York (whole-hour offset: same UTC minutes)

assert NFL_WEEKLY_GET_CAP == 288 + 7 and NFL_SWITCH == "EDGE_LAB_KALSHI_NFL_CAPTURE"


def nfl_switch_value(environ: Mapping[str, str] | None = None) -> str:
    """ON, OFF or INVALID. The owner approved the capture, so the reviewed, deployed code is the activation
    record: unset (or "on") means ON. "off" is the kill switch. Any other value fails closed (INVALID = off)."""
    import os

    # A literal name (tests/invariants/test_no_execution_paths.py scans every environment read).
    value = environ.get(NFL_SWITCH) if environ is not None else os.environ.get("EDGE_LAB_KALSHI_NFL_CAPTURE")
    # Exactly the values install.sh accepts and keeps: on or off, lowercase, nothing else.
    return "ON" if value in (None, "", "on") else "OFF" if value == "off" else "INVALID"


def nfl_capture_enabled(environ: Mapping[str, str] | None = None) -> bool:
    return nfl_switch_value(environ) == "ON"


def nfl_disabled_report(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    state = nfl_switch_value(environ)
    return {"state": state if state != "ON" else "OFF", "switch": NFL_SWITCH, "version": NFL_PLAN_VERSION,
            "detail": f"{NFL_SWITCH}={'off' if state == 'OFF' else 'an invalid value (only on or off)'}: no Kalshi "
                      "NFL target planned, pending ones are not attempted"}


def _keys(t: Any) -> set[str]:
    return set(t.keys())


def _detail(t: Any) -> dict[str, Any]:
    keys = _keys(t)
    if "detail" in keys and isinstance(t["detail"], dict):
        return t["detail"]
    raw = t["detail_json"] if "detail_json" in keys else None
    try:
        value = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def is_nfl_target(t: Any) -> bool:
    """A target planned by the NFL pairing planner (never a manual or ADR 0030 target)."""
    return "origin" in _keys(t) and t["origin"] == NFL_ORIGIN


def _nfl_role(t: Any) -> str | None:
    return _detail(t).get("nfl_role")


def _nfl_attempt_limit(t: Any) -> int:
    return 1 if _nfl_role(t) == NFL_ROLE_SETTLEMENT else NFL_MAX_ATTEMPTS


def _nfl_holds(store: SnapshotStore, nfl_due: Sequence[Any], nfl_on: bool) -> dict[str, str]:
    """{target id: reason} for the due NFL targets that must not be attempted in this run.

    The GET bound is enforced per game-horizon (both team markets at one Odds receipt, or one settled read),
    not per target: a run that sent any GET for the group left a non-MISSED row for every target it touched
    (a book deferred after its listing is recorded FAILED too). Each such run costs at most 3 GETs (1 for a
    settled read), so at most `_nfl_attempt_limit` runs keep a game-horizon within 6 (1), whichever run it
    was: a scheduled tick, the close tick or a manual capture."""
    if not nfl_on:
        return {t["target_id"]: f"NFL_CAPTURE_DISABLED: {NFL_SWITCH} is off (or invalid): not attempted" for t in nfl_due}
    group_of = lambda t: (t["native_event_id"], t["target_utc"])  # noqa: E731
    groups = {group_of(t) for t in nfl_due}
    ids: dict[tuple[str, str], set[str]] = {}
    markets: dict[tuple[str, str], set[str]] = {}
    for t in store.price_targets():
        if is_nfl_target(t) and group_of(t) in groups:
            ids.setdefault(group_of(t), set()).add(t["target_id"])
            markets.setdefault(group_of(t), set()).add(t["market_id"])
    runs: dict[tuple[str, str], set[str]] = {g: set() for g in groups}
    for g in groups:
        for market in sorted(markets.get(g, ())):
            for r in store.price_observations(market_id=market):
                if r["target_id"] in ids[g] and r["collection_status"] != "MISSED":
                    runs[g].add(r["run_id"])
    return {t["target_id"]: f"NFL_ATTEMPT_LIMIT: {len(runs[group_of(t)])} run(s) already sent GETs for this "
                            f"game-horizon (limit {_nfl_attempt_limit(t)})"
            for t in nfl_due if len(runs[group_of(t)]) >= _nfl_attempt_limit(t)}


_MONTH_CODES = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def nfl_event_ticker(away_abbr: str, home_abbr: str, day: date) -> str:
    """KXNFLGAME-<YY><MON><DD><AWAY><HOME>, the date being the game's originally scheduled New York date."""
    ticker = f"{NFL_SERIES}-{day:%y}{_MONTH_CODES[day.month - 1]}{day.day:02d}{away_abbr}{home_abbr}"
    if not ticker.startswith(f"{NFL_SERIES}-"):  # pragma: no cover - a hard scope guard
        raise ValueError(f"not a {NFL_SERIES} ticker: {ticker}")
    return ticker


def next_observe_tick(instant: datetime) -> datetime:
    """The first edgelab-observe tick at or after `instant` that no protected window refuses."""
    tick = instant.astimezone(UTC).replace(second=0, microsecond=0)
    if tick < instant:
        tick += timedelta(minutes=1)
    while tick.minute % 15 != _OBSERVE_TICK_MINUTE:
        tick += timedelta(minutes=1)
    while protected_refusal(tick) is not None:
        tick += SCHEDULED_TICK_INTERVAL
    return tick


def _nfl_mapping(store: SnapshotStore, event: str, expected: Mapping[str, str], now: datetime) -> tuple[str, str]:
    """(LISTED | DERIVED | NOT_LISTED | AMBIGUOUS, why) from the newest listing of `event` received at or
    before `now` (point in time: a later listing is never used, also in a dry run for a past `now`).
    With no listing received yet, the derived tickers are planned and the capture's own listing GET (inside
    the game-horizon's budget) verifies them; a received listing that lacks them stops further planning."""
    known = [m for m in store.snapshot_metadata(source=KALSHI_SOURCE.legacy_name, kinds=("markets",),
                                                entity_prefix=event, limit=1000)
             if m["entity_id"] == event and (_t(m["fetched_at_utc"]) or now + timedelta(seconds=1)) <= now]
    if not known:
        return "DERIVED", "no listing received yet: the capture's listing GET verifies the derived tickers"
    newest = int(known[-1]["id"])
    row = store.snapshots_by_id([newest])[newest]
    try:
        payload = json.loads(row["payload_json"])
    except ValueError:
        return "AMBIGUOUS", f"stored listing {row['id']} is not JSON"
    markets = {m["ticker"]: m for m in (payload.get("markets") or []) if isinstance(m, dict)
               and isinstance(m.get("ticker"), str)} if isinstance(payload, dict) else {}
    missing = sorted(set(expected) - set(markets))
    if missing:
        return "NOT_LISTED", f"stored listing {row['id']} ({row['fetched_at_utc']}) of {event} lacks {missing}"
    differ = sorted(tk for tk, label in expected.items() if markets[tk].get("yes_sub_title") not in (None, label))
    if differ:
        return "AMBIGUOUS", f"stored listing {row['id']}: yes_sub_title differs from the team table for {differ}"
    return "LISTED", f"stored listing {row['id']} ({row['fetched_at_utc']}) lists both team markets"


def plan_nfl_targets(store: SnapshotStore, now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The Kalshi NFL pairing targets to plan now, and a report. Read-only and network-free: it reads
    the Odds pilot's stored targets and stored Kalshi listings, writes nothing and makes no request.
    Idempotent: a target already planned is never returned again (its id is fixed by the Odds capture)."""
    from .sports_evidence import NFL_TEAMS, et_date, week_cluster

    report: dict[str, Any] = {"state": "ON", "switch": NFL_SWITCH, "version": NFL_PLAN_VERSION,
                              "series": NFL_SERIES, "odds_api_calls": 0, "planned": [], "not_planned": []}

    def skip(ref: str, reason: str) -> None:
        if len(report["not_planned"]) < NFL_MAX_REPORT_ITEMS:
            report["not_planned"].append({"ref": ref, "reason": reason})

    try:
        odds = store.odds_targets(sport=NFL_SPORT)
    except Exception as exc:  # an older store without the Odds tables: nothing to pair, say so
        report["state"] = "NO_ODDS_TARGETS"
        report["detail"] = f"{type(exc).__name__}: {exc}"
        return [], report
    existing = [t for t in store.price_targets() if is_nfl_target(t)]
    known = {t["target_id"] for t in existing}
    horizons: dict[str, set[tuple[str, str]]] = {}
    reads: dict[str, set[str]] = {}
    book_days: set[str] = set()
    for t in existing:
        d, week = _detail(t), week_cluster(_t(t["target_utc"]))
        if d.get("nfl_role") == NFL_ROLE_SETTLEMENT:
            reads.setdefault(week, set()).add(str(d.get("game_date")))
        else:
            horizons.setdefault(week, set()).add((str(t["native_event_id"]), str(t["target_utc"])))
            if d.get("game_date"):
                book_days.add(str(d["game_date"]))
    first_kickoff: dict[str, datetime] = {}
    kickoff: dict[str, datetime] = {}
    for r in odds:
        c = _t(r["commence_time_utc"])
        planned = _t(r["planned_at_utc"])
        if c is None or planned is None or planned > now:  # point in time: only targets known by now
            continue
        first_kickoff[r["event_id"]] = min(first_kickoff.get(r["event_id"], c), c)
        if r["state"] != "SUPERSEDED":
            kickoff[r["event_id"]] = c
    new: list[dict[str, Any]] = []
    captured = sorted((r for r in odds if r["state"] == "CAPTURED" and _t(r["captured_at_utc"]) is not None),
                      key=lambda r: (r["captured_at_utc"], r["target_id"]))
    for r in captured:
        at = _t(r["captured_at_utc"]).replace(microsecond=0)
        if not now - NFL_PLAN_WINDOW <= at <= now:
            continue  # older captures are never paired late; later ones do not exist yet
        if r["offset_label"] not in NFL_HORIZONS:
            skip(r["target_id"], f"HORIZON_NOT_APPROVED: {r['offset_label']!r} (approved: {', '.join(NFL_HORIZONS)})")
            continue
        commence = _t(r["commence_time_utc"])
        deadline = min(at + NFL_TARGET_WINDOW, commence - NFL_MIN_LEAD)
        if deadline <= now:
            skip(r["target_id"], f"TOO_LATE: the pregame book deadline {_iso(deadline)} has passed")
            continue
        home, away = r["home_team"], r["away_team"]
        if home not in NFL_TEAMS or away not in NFL_TEAMS:
            skip(r["target_id"], f"UNMAPPED_TEAM: {away!r} at {home!r} not in the NFL team table")
            continue
        original = first_kickoff.get(r["event_id"], commence)
        event = nfl_event_ticker(NFL_TEAMS[away][0], NFL_TEAMS[home][0], et_date(original))
        expected = {f"{event}-{NFL_TEAMS[team][0]}": NFL_TEAMS[team][1] for team in (away, home)}
        mapping, why = _nfl_mapping(store, event, expected, now)
        if mapping not in ("LISTED", "DERIVED"):
            skip(r["target_id"], f"{mapping}: {why}")
            continue
        week, key = week_cluster(at), (event, _iso(at))
        planned_week = horizons.setdefault(week, set())
        if key not in planned_week and len(planned_week) >= NFL_WEEKLY_GAME_HORIZONS:
            skip(r["target_id"], f"WEEKLY_BUDGET: {NFL_WEEKLY_GAME_HORIZONS} game-horizons already planned in {week}")
            continue
        game_date = et_date(commence).isoformat()
        for ticker in expected:
            target = custom_target(venue="kalshi", native_market_id=ticker, at=at, native_event_id=event)
            target.update(origin=NFL_ORIGIN, deadline_utc=_iso(deadline), detail={
                "nfl_role": NFL_ROLE_BOOK, "version": NFL_PLAN_VERSION, "odds_target_id": r["target_id"],
                "odds_offset": r["offset_label"], "odds_captured_at_utc": r["captured_at_utc"],
                "odds_event_id": r["event_id"], "commence_utc": _iso(commence), "game_date": game_date,
                "mapping": mapping, "mapping_detail": why,
                "pairing": "reactive: planned after the Odds capture, at its receipt time (option (a))"})
            if target["target_id"] in known:
                continue
            known.add(target["target_id"])
            new.append(target)
            report["planned"].append({"target_id": target["target_id"], "odds_target_id": r["target_id"],
                                      "mapping": mapping})
        planned_week.add(key)
        book_days.add(game_date)
    # One settled-markets read per ET game day with NFL books, after the day's last expected expiration.
    for game_date in sorted(book_days):
        day_kickoffs = [c for c in kickoff.values() if et_date(c).isoformat() == game_date]
        if not day_kickoffs or any(game_date in days for days in reads.values()):
            continue
        tick = next_observe_tick(max(day_kickoffs) + NFL_SETTLEMENT_AFTER_KICKOFF)
        if not tick - NFL_SETTLEMENT_PLAN_LEAD <= now <= tick:
            if now > tick:
                skip(f"settlement:{game_date}", f"SETTLEMENT_WINDOW_PASSED: its tick {_iso(tick)} is over")
            continue
        week = week_cluster(tick)
        if len(reads.setdefault(week, set())) >= NFL_WEEKLY_SETTLEMENT_READS:
            skip(f"settlement:{game_date}", f"WEEKLY_BUDGET: {NFL_WEEKLY_SETTLEMENT_READS} reads already in {week}")
            continue
        start = _from_et(datetime.combine(date.fromisoformat(game_date), dtime(0, 0)))
        market_id = f"kalshi:{NFL_SERIES}"
        target = {"target_id": target_id(market_id, "custom", tick), "venue": "kalshi", "market_id": market_id,
                  "native_market_id": NFL_SERIES, "event_id": f"kalshi:{NFL_SERIES}:settled:{game_date}",
                  "native_event_id": NFL_SERIES, "phase": "custom", "target_utc": _iso(tick),
                  "due_from_utc": _iso(tick - EARLY), "deadline_utc": _iso(tick + NFL_SETTLEMENT_WINDOW),
                  "policy_version": POLICY_VERSION, "origin": NFL_ORIGIN, "decision_ref": None,
                  "decision_as_of_utc": None, "close_time_utc": None, "close_basis": CLOSE_SEMANTICS["kalshi"].basis,
                  "planned_rules_sha256": None,
                  "detail": {"nfl_role": NFL_ROLE_SETTLEMENT, "version": NFL_PLAN_VERSION, "game_date": game_date,
                             "min_settled_utc": _iso(start), "max_settled_utc": _iso(tick),
                             "last_kickoff_utc": _iso(max(day_kickoffs))}}
        if target["target_id"] not in known:
            known.add(target["target_id"])
            new.append(target)
            reads[week].add(game_date)
            report["planned"].append({"target_id": target["target_id"], "game_date": game_date,
                                      "role": NFL_ROLE_SETTLEMENT})
    week = week_cluster(now)  # the current NFL week's budget, counting what this plan adds
    n_h, n_r = len(horizons.get(week, ())), len(reads.get(week, ()))
    report["budget"] = {
        "week": week, "game_horizons": n_h, "game_horizon_cap": NFL_WEEKLY_GAME_HORIZONS,
        "settlement_reads": n_r, "settlement_read_cap": NFL_WEEKLY_SETTLEMENT_READS,
        "worst_case_gets": n_h * NFL_WORST_GETS_PER_GAME_HORIZON + n_r, "weekly_get_cap": NFL_WEEKLY_GET_CAP,
        "worst_gets_per_game_horizon": NFL_WORST_GETS_PER_GAME_HORIZON,
        "expected_gets": n_h * NFL_GETS_PER_ATTEMPT + n_r}
    report["planned"] = report["planned"][:NFL_MAX_REPORT_ITEMS]
    return new, report


def _capture_nfl_settlement_read(store: SnapshotStore, run_id: str, targets: list[Mapping[str, Any]],
                                 req: _Requests) -> tuple[list[list[dict[str, Any]]], list[str]]:
    """One settled-markets page per game day: listing only, never a book, never a second page, no retry.
    The row is NOT_EXECUTABLE (it carries no quote) and names the stored snapshot."""
    attempts: list[list[dict[str, Any]]] = []
    deferred: list[str] = []
    for t in targets:
        d, attempt = _detail(t), _attempt_id(run_id, t["target_id"])
        lo, hi = _t(d.get("min_settled_utc")), _t(d.get("max_settled_utc"))
        if lo is None or hi is None:
            attempts.append([_base_row(run_id, attempt, t, status="FAILED",
                                       reason="SETTLEMENT_READ_FAILED: the target has no settled-time window")])
            continue
        # GET /markets filters, per https://docs.kalshi.com/api-reference/market/get-markets (read 2026-09-25):
        # min_settled_ts / max_settled_ts ("Filter items that settled after/before this Unix timestamp") are the
        # timestamp filters compatible with status=settled; min/max_close_ts are not (closed or empty status only).
        url = forward._url("/markets", series_ticker=NFL_SERIES, status="settled", min_settled_ts=int(lo.timestamp()),
                           max_settled_ts=int(hi.timestamp()), limit=NFL_SETTLEMENT_PAGE_LIMIT)
        try:
            payload, result = req.get(url, pacer=KALSHI_PACER, retries=0)
        except RequestBudgetExhausted:
            deferred.append(t["target_id"])
            continue
        except _FETCH_ERRORS as exc:
            attempts.append([_base_row(run_id, attempt, t, status="FAILED",
                                       reason=f"SETTLEMENT_READ_FAILED: {type(exc).__name__}: {exc}")])
            continue
        snap = forward._save(store, run_id=run_id, spec=KALSHI_SOURCE, kind="settled_markets", entity_id=NFL_SERIES,
                             url=url, payload=payload, fetch=result)
        received = _t(result.received_at_utc)
        rows = payload.get("markets")
        common = dict(snapshot_id=snap, observed_at_utc=_iso_exact(received) if received else None,
                      source_sha256=bytes_sha256(result.body), freshness=_freshness(received, t))
        if not isinstance(rows, list):
            attempts.append([_base_row(run_id, attempt, t, status="FAILED",
                                       reason="SETTLEMENT_READ_FAILED: the payload has no markets list", **common)])
            continue
        n = sum(1 for m in rows if isinstance(m, dict))
        more = "; a further page exists and was not fetched (one GET per game day)" if payload.get("cursor") else ""
        attempts.append([_base_row(run_id, attempt, t, status="NOT_EXECUTABLE", **common,
                                   reason=f"SETTLEMENT_METADATA_READ: {n} {NFL_SERIES} market(s) settled "
                                          f"{d.get('min_settled_utc')}..{d.get('max_settled_utc')}; listing only, no book{more}")])
    return attempts, deferred


def nfl_dry_run(db: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """What `observe plan` would plan for the NFL pairing now, from a read-only open of the store.
    Writes nothing and sends nothing, whatever the switch says (`switch_state` reports it)."""
    now = now or _now()
    store = SnapshotStore.open_readonly(db)
    targets, report = plan_nfl_targets(store, now)
    return {"command": "nfl dry-run", "now_utc": _iso_exact(now), "writes": 0, "requests": 0,
            "switch_state": nfl_switch_value(), "would_plan": targets, **report}


# --------------------------------------------------------------------------- CLI runners


def _lock_path(db: Path) -> Path:
    return db.with_name(db.name + ".forward.lock")  # shared with forward captures: one Kalshi pacer per host


def _readonly_or_none(db: Path) -> SnapshotStore | None:
    """A read-only view for the idle check; None when the store needs the write path (older schema)."""
    from .storage import ReadOnlyStoreError

    try:
        return SnapshotStore.open_readonly(db)
    except ReadOnlyStoreError:
        return None


def run_plan(db: Path, ledger_path: Path | None, *, now: datetime | None = None,
             lookback: timedelta = DECISION_LOOKBACK, custom: Sequence[dict[str, Any]] = (),
             environ: Mapping[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    """`observe plan`: refuses protected windows; requires an existing evidence store (it never
    creates one at an arbitrary path); an idle plan is the lock plus a read-only open only.

    With the NFL switch on (`NFL_SWITCH`), it also plans the Kalshi NFL pairing targets
    (`plan_nfl_targets`); with it off, it plans none and says so in `report["nfl"]`."""
    from .shadow_ledger import ShadowLedger

    now = now or _now()
    nfl_on = nfl_capture_enabled(environ)

    def nfl(store: SnapshotStore) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return plan_nfl_targets(store, now) if nfl_on else ([], nfl_disabled_report(environ))
    hit = protected_window_at(now, now + timedelta(minutes=1))
    if hit is not None:  # plan takes the same collector lock: never inside a protected window
        return 0, {"command": "observe plan", "now_utc": _iso_exact(now), "state": "DEFERRED_PROTECTED_WINDOW",
                   "detail": f"inside or next to {hit[0]}: nothing done"}
    if not db.is_file():
        return 0, {"command": "observe plan", "state": "NO_STORE", "detail": f"{db} does not exist; nothing created"}
    ledger = None
    ledger_state = "NOT_GIVEN"
    if ledger_path is not None:
        if ledger_path.is_file():
            ledger, ledger_state = ShadowLedger.open_readonly(ledger_path), "READ"
        else:
            ledger_state = "MISSING"
    try:
        with exclusive_lock(_lock_path(db), timeout_s=LOCK_TIMEOUT_S):
            ro = _readonly_or_none(db)
            if ro is not None:
                decisions = decisions_from_ledger(ledger, ro, since=now - lookback) if ledger else []
                nfl_custom, nfl_report = nfl(ro)
                if plan_work(ro, decisions, now, [*custom, *nfl_custom]) == 0:
                    return 0, {"command": "observe plan", "now_utc": _iso_exact(now), "state": "NOTHING_TO_DO",
                               "ledger": ledger_state, "decisions": len(decisions), "nfl": nfl_report}
            store = SnapshotStore(db)
            decisions = decisions_from_ledger(ledger, store, since=now - lookback) if ledger else []
            nfl_custom, nfl_report = nfl(store)
            report = plan(store, decisions=decisions, now=now, custom=[*custom, *nfl_custom])
    except LockBusy as exc:
        return 0, {"command": "observe plan", "state": "LOCK_BUSY", "detail": str(exc)}
    report["ledger"] = ledger_state
    report["nfl"] = nfl_report
    return 0, report


def run_capture(db: Path, *, clock: Clock | None = None, sleep: Sleep = time.sleep, max_targets: int = MAX_TARGETS,
                max_requests: int = MAX_REQUESTS, environ: Mapping[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    """`observe capture`: refuses protected windows before anything is opened; an idle run is the
    lock plus a read-only open only. NFL pairing targets are attempted only while `NFL_SWITCH` is on."""
    clock = clock or _now
    nfl_on = nfl_capture_enabled(environ)
    _check_bounds(max_targets, max_requests)
    refusal = protected_refusal(clock())
    if refusal is not None:  # before the lock: nothing is even opened inside a protected window
        return 0, refusal
    if not db.is_file():
        return 0, {"command": "observe capture", "state": "NO_STORE", "detail": f"{db} does not exist"}
    try:
        with exclusive_lock(_lock_path(db), timeout_s=LOCK_TIMEOUT_S):
            ro = _readonly_or_none(db)
            if ro is not None and capture_work(ro, clock()) == {"overdue": 0, "due": 0}:
                return 0, {"command": "observe capture", "now_utc": _iso_exact(clock()), "state": "NOTHING_DUE",
                           "requests": 0, "attempted": 0, "by_status": {}, "deferred": [], "missed": []}
            return capture(SnapshotStore(db), clock=clock, sleep=sleep, max_targets=max_targets,
                           max_requests=max_requests, nfl_enabled=nfl_on)
    except LockBusy as exc:
        return 0, {"command": "observe capture", "state": "LOCK_BUSY", "detail": str(exc)}


def run_status(db: Path, *, now: datetime | None = None, market_id: str | None = None,
               systemctl: Callable[[Sequence[str]], str] | None = None) -> tuple[int, dict[str, Any]]:
    store = SnapshotStore.open_readonly(db)
    report = status(store, now=now or _now(), systemctl=systemctl)
    if market_id:
        report["market_history"] = market_history(store, market_id)
    return 0, report


__all__ = [
    "CLOSE_SEMANTICS", "DecisionRecord", "PROTECTED_WINDOWS_ET", "capture", "custom_target", "decisions_from_ledger",
    "expire", "market_history", "plan", "protected_window_at", "run_capture", "run_plan", "run_status", "status",
    "targets_for", "NFL_SWITCH", "nfl_capture_enabled", "nfl_dry_run", "plan_nfl_targets",
]

assert set(POST_DECISION_OFFSETS) | {"decision", "recheck", "pre_close", "close", "settlement_preceding", "custom"} \
    == set(PRICE_OBSERVATION_PHASES)


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m edge_lab.price_observations nfl-dry-run --db PATH [--now ISO]`: read-only preview of the
    NFL pairing plan (no writes, no requests). The live path is `edge_lab.cli observe plan` with the switch on."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    dry = sub.add_parser("nfl-dry-run")
    dry.add_argument("--db", type=Path, required=True)
    dry.add_argument("--now", help="ISO-8601 time with zone (default: now)")
    args = parser.parse_args(argv)
    now = _t(args.now) if args.now else None
    if args.now and now is None:
        parser.error("--now needs a zone")
    print(json.dumps(nfl_dry_run(args.db, now=now), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
