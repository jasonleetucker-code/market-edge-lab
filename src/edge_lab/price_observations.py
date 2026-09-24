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

    def get(self, url: str, *, pacer: Pacer, headers: dict[str, str] | None = None):
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
        return fetch_json_result(url, headers=headers, timeout=timeout, retries=2, pacer=pacer, sleep=bounded_sleep)

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


def _kalshi_listing(store: SnapshotStore, run_id: str, event: str, req: _Requests):
    """Every market of one Kalshi event (bounded pages), each page stored as a snapshot.
    Returns (last snapshot id, last receipt, {ticker: raw market})."""
    markets: dict[str, dict[str, Any]] = {}
    cursor, snapshot_id, received = None, None, None
    for page in range(1, MAX_LISTING_PAGES + 1):
        url = forward._url("/markets", event_ticker=event, limit=1000, cursor=cursor)
        payload, result = req.get(url, pacer=KALSHI_PACER)
        snapshot_id = forward._save(store, run_id=run_id, spec=KALSHI_SOURCE, kind="markets", entity_id=event,
                                    url=url, payload=payload, fetch=result)
        received = _t(result.received_at_utc)
        rows = payload.get("markets")
        if not isinstance(rows, list):
            raise ValueError(f"markets page {page} for {event} has no markets list")
        markets.update({m["ticker"]: m for m in rows if isinstance(m, dict) and isinstance(m.get("ticker"), str)})
        cursor = payload.get("cursor") or None
        if cursor is None:
            return snapshot_id, received, markets
    raise ValueError(f"market listing for {event} still paginating after {MAX_LISTING_PAGES} pages")


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

    def fail_all(reason: str, todo: Iterable[Mapping[str, Any]]) -> None:
        for t in todo:
            attempts.append([_base_row(run_id, _attempt_id(run_id, t['target_id']), t, status="FAILED", reason=reason)])

    try:
        listing_id, listing_at, markets = _kalshi_listing(store, run_id, event, req)
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
            payload, result = req.get(url, pacer=KALSHI_PACER)
        except RequestBudgetExhausted:
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
            max_targets: int = MAX_TARGETS, max_requests: int = MAX_REQUESTS) -> tuple[int, dict[str, Any]]:
    """One bounded capture run over the due targets. The caller holds the collector lock.
    Returns (exit code, report): 1 when a FAILED target cannot be retried by a later scheduled tick
    (`failed_final`), else 0. Retryable failures are recorded and listed in `failed_retrying`."""
    clock = clock or _now
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
        due.sort(key=lambda t: (t["target_utc"], t["market_id"]))
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
        for (venue, _, phase, _), targets in sorted(groups.items(), key=lambda kv: kv[0][2] == "close"):
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
    final = sorted(i for i, t in failed_targets.items()
                   if t["phase"] == "close" or not _retry_tick_before(_t(t["deadline_utc"]), end))
    report["failed_final"] = final
    report["failed_retrying"] = sorted(set(failed_targets) - set(final))
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
            misses.append({"target_id": t["target_id"], "reason": t["state_reason"], "at_utc": t["state_at_utc"]})
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
    time is known). Never a midpoint, a last price, or an order."""
    out: list[dict[str, Any]] = []
    attempted = set()
    for r in store.price_observations(market_id=market_id):
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
    for t in store.price_targets(market_id=market_id):
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
    return out


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
             lookback: timedelta = DECISION_LOOKBACK, custom: Sequence[dict[str, Any]] = ()) -> tuple[int, dict[str, Any]]:
    """`observe plan`: refuses protected windows; requires an existing evidence store (it never
    creates one at an arbitrary path); an idle plan is the lock plus a read-only open only."""
    from .shadow_ledger import ShadowLedger

    now = now or _now()
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
                if plan_work(ro, decisions, now, custom) == 0:
                    return 0, {"command": "observe plan", "now_utc": _iso_exact(now), "state": "NOTHING_TO_DO",
                               "ledger": ledger_state, "decisions": len(decisions)}
            store = SnapshotStore(db)
            decisions = decisions_from_ledger(ledger, store, since=now - lookback) if ledger else []
            report = plan(store, decisions=decisions, now=now, custom=custom)
    except LockBusy as exc:
        return 0, {"command": "observe plan", "state": "LOCK_BUSY", "detail": str(exc)}
    report["ledger"] = ledger_state
    return 0, report


def run_capture(db: Path, *, clock: Clock | None = None, sleep: Sleep = time.sleep, max_targets: int = MAX_TARGETS,
                max_requests: int = MAX_REQUESTS) -> tuple[int, dict[str, Any]]:
    """`observe capture`: refuses protected windows before anything is opened; an idle run is the
    lock plus a read-only open only."""
    clock = clock or _now
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
                           max_requests=max_requests)
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
    "targets_for",
]

assert set(POST_DECISION_OFFSETS) | {"decision", "recheck", "pre_close", "close", "settlement_preceding", "custom"} \
    == set(PRICE_OBSERVATION_PHASES)
