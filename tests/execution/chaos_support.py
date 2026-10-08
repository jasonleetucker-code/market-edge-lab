"""Shared support for the #160 package P chaos, performance and regression suite. It holds no tests.

FIXTURE only. Nothing leaves the process except the kill-test child, which is another local Python process on the
same disposable store. It reuses the orchestrator harness (`test_orchestrator_harness`) by import: the real merged
components run (orchestrator, journal, reservations, lifecycle, control, risk gate, account reads and, where a test
asks for it, the real `transport.Transport` with a fixture signer); only the venue is the in-memory `FakeVenue`.

What lives here:
- `ChaosAdapter`: the harness `VenueAdapter` plus probes and faults. Every ORDER_CREATE that reaches the venue is
  checked against the journal FILE (a separate connection) for an attempt prepared and committed before the send,
  and its client order id is logged. Optional listing faults: duplicated fills, reversed pages, stale order rows and
  crossed (out-of-order) create replies. Optional kill points for the process-death child.
- `HttpVenue`: the real `Transport` (fixture signer, injected opener, real `RateBudget`) in front of the adapter, with a
  seeded HTTP fault mix (429, 5xx, timeouts, malformed bodies, 409). It is the caller's `send` glue and picks the
  documented PROTECTIVE priority for reads and cancels (`EndpointSpec.protective`).
- `Workload`: the declared synthetic workload (seeded).
- `Rig`: one orchestrator on one journal file, with restart, an operator who arms only after a COMPLETE cycle, and the
  global invariant check after every step.
- `check_invariants`: the global invariants of package P, read from the durable store and the venue.
- `Timings`: latency samples and nearest-rank percentiles.
- `kill_child_main`: the out-of-process worker that dies (`os._exit`) at a chosen journal commit or send.

Scale: the defaults are small so that default CI stays fast. Set `EDGE_LAB_CHAOS_SCALE=full` to scale every knob up,
or set one knob (`EDGE_LAB_CHAOS_SEEDS`, `EDGE_LAB_LOAD_CYCLES`, ...) to an integer. See docs/execution/PERFORMANCE.md.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError

import test_orchestrator_harness as h
from edge_lab.execution import control as ctl
from edge_lab.execution import model as m
from edge_lab.execution import orchestrator as o
from edge_lab.execution.journal import CONTROL_EVENT_KIND, ExecutionJournal

SCALE_ENV = "EDGE_LAB_CHAOS_SCALE"
SENDING = frozenset({ctl.Mode.HUMAN_CONFIRMATION, ctl.Mode.BOUNDED_AUTO, ctl.Mode.DEMO})


def full_scale() -> bool:
    return os.environ.get(SCALE_ENV, "").strip().lower() == "full"


def knob(name: str, small: int, full: int) -> int:
    """`EDGE_LAB_<name>` if set (an int), else `full` under EDGE_LAB_CHAOS_SCALE=full, else `small`."""
    raw = os.environ.get(f"EDGE_LAB_{name}")
    if raw is not None and raw.strip():
        return int(raw)
    return full if full_scale() else small


def ticker(i: int) -> str:
    return f"KXHIGHNY-26OCT08-B{i:03d}"


def seed_books(adapter: h.VenueAdapter, markets: tuple[str, ...]) -> None:
    """The harness's two-sided books on every market: YES bids 0.40-0.42, NO bids 0.54-0.56 (YES asks 0.44-0.46)."""
    for t in markets:
        for p, q in (("0.40", "5"), ("0.41", "5"), ("0.42", "4")):
            adapter.venue.add_liquidity(t, m.Side.YES, p, q)
        for p, q in (("0.54", "6"), ("0.55", "5"), ("0.56", "4")):
            adapter.venue.add_liquidity(t, m.Side.NO, p, q)
    adapter.sync()


def best_yes_ask(adapter: h.VenueAdapter, t: str) -> Decimal | None:
    no_bids = adapter.venue.book(t)["no"]
    return None if not no_bids else 1 - no_bids[0][0]


def best_yes_bid(adapter: h.VenueAdapter, t: str) -> Decimal | None:
    yes_bids = adapter.venue.book(t)["yes"]
    return None if not yes_bids else yes_bids[0][0]


# ---------------------------------------------------------------------------------------------- the venue adapter


@dataclass
class ChaosAdapter(h.VenueAdapter):
    """The harness adapter plus probes and faults (module docstring). Picklable for the kill child."""

    journal_path: str | None = None
    creates: list = field(default_factory=list)  # client order id of every ORDER_CREATE the venue received
    unprepared: list = field(default_factory=list)  # creates with no committed attempt at send time (must stay empty)
    manual: set = field(default_factory=set)  # client ids of orders placed directly at the venue (someone else's)
    duplicate_fills: bool = False  # every fill appears twice in each listing page (identical duplicates)
    reverse_listings: bool = False  # orders and fills pages are served newest first
    stale_orders: bool = False  # while set, GET_ORDERS serves each row as last seen before it was set (older stamps)
    crossed_reply: str | None = None  # "with_id" / "without_id": the next create gets the previous create's ack
    kill_point: Any = None  # child only: called with a label at each kill point; never pickled
    # Clocks. The harness ties the venue to our clock; these separate them. `skew`: the venue's true time minus our
    # clock (a wrong clock on our side). `venue_lag`: how far the venue's stamps trail the true time (the harness's
    # VENUE_LAG). `as_of_lag`: how far the venue's user-data timestamp trails the true time (ACC-16: approximate).
    skew: float = 0.0
    venue_lag: float = h.VENUE_LAG.total_seconds()
    as_of_lag: float = 1.0
    _last_ack: bytes | None = None
    _last_orders: dict = field(default_factory=dict)
    _cache: dict = field(default_factory=dict)

    # -- clocks

    def true_now(self) -> datetime:
        return self.clock() + timedelta(seconds=self.skew)

    def sync(self) -> None:
        """The harness's `sync`, against the venue's true time (`skew`) and `venue_lag`."""
        target = self.true_now() - timedelta(seconds=self.venue_lag)
        gap = int((target - self.venue_now()).total_seconds())
        if gap > 0:
            self.venue.advance(gap)
        for order_id, expires in sorted(self.expiries.items()):
            if expires <= self.true_now() and self.venue.expire(order_id):
                self.touched[self.venue.get_order(order_id)["ticker"]] = self.venue.now_text()
        fills = self.venue.list_fills()
        for f in fills[self.fills_seen:]:
            self._book_fill(f)
        self.fills_seen = len(fills)

    # -- probes

    def _prepared(self, client_order_id: str) -> str | None:
        if self.journal_path is None:
            return "NO_JOURNAL_PATH"
        conn = sqlite3.connect(self.journal_path, timeout=5)
        try:
            row = conn.execute("SELECT state FROM attempts WHERE client_order_id = ?", (client_order_id,)).fetchone()
        finally:
            conn.close()
        return None if row is None else row[0]

    def _create(self, body: dict) -> h.Reply:
        coid = body["client_order_id"]
        state = self._prepared(coid)  # PENDING_EGRESS, or OUTCOME_UNKNOWN when a takeover superseded its fence
        self.creates.append(coid)
        if state is None:
            self.unprepared.append((coid, state))
        reply = super()._create(body)
        if self.crossed_reply and reply.outcome == "OK" and self._last_ack is not None:
            ack = json.loads(self._last_ack)
            if self.crossed_reply == "without_id":
                ack.pop("client_order_id", None)
            self.crossed_reply = None
            self._last_ack = reply.body
            return h.Reply("OK", 201, json.dumps(ack, sort_keys=True).encode())
        if reply.outcome == "OK":
            self._last_ack = reply.body
        return reply

    def _write(self, request):
        if self.kill_point is not None:
            self.kill_point("before_send")
        reply = super()._write(request)
        if self.kill_point is not None:
            self.kill_point("after_send")
        return reply

    # -- listings

    def _listing(self, name: str) -> list:
        """The full orders or fills listing in venue shape, cached while the venue is unchanged. The harness rebuilds
        every record for every page and filters every fill per order (quadratic in history); this keeps the
        harness's own cost from dominating long runs. The records are the harness's, unchanged."""
        orders, fills = self.venue.list_orders(), self.venue.list_fills()
        key = (name, len(fills), tuple((x["order_id"], x["status"], x["fill_count"]) for x in orders),
               frozenset(self.hidden_orders))
        cache = self._cache.get(name, (None, []))
        if cache[0] != key:
            if name == "GET_FILLS":
                items = [self._fill_json(f) for f in fills]
            else:
                by_order: dict = {}
                for f in fills:
                    by_order.setdefault(f["order_id"], []).append(f)
                real = self.venue.list_fills
                self.venue.list_fills = lambda order_id=None: real() if order_id is None else by_order.get(order_id, [])
                try:
                    items = [self._order_json(x) for x in orders if x["order_id"] not in self.hidden_orders]
                finally:
                    del self.venue.list_fills
            self._cache[name] = cache = (key, items)
        return cache[1]

    def __call__(self, request):
        name = request.endpoint.name
        if name == "GET_USER_DATA_TIMESTAMP" and not self.reads_fail:
            assert request.scope == h.SCOPE
            self.sync()
            self.requests.append(name)
            return h.ok({"as_of_time": m.utc_text(self.true_now() - timedelta(seconds=self.as_of_lag))})
        if name in ("GET_FILLS", "GET_ORDERS") and not self.reads_fail:
            assert request.scope == h.SCOPE
            self.sync()
            self.requests.append(name)
            key = "fills" if name == "GET_FILLS" else "orders"
            reply = h.ok(self._page(key, self._listing(name), dict(request.query)))
        else:
            reply = super().__call__(request)
        if reply.outcome != "OK" or name not in ("GET_FILLS", "GET_ORDERS"):
            return reply
        body = json.loads(reply.body)
        key = "fills" if name == "GET_FILLS" else "orders"
        items = body[key]
        if name == "GET_ORDERS":
            if self.stale_orders:  # an older version of every row seen before (served consistently while set)
                items = [self._last_orders.get(x["order_id"], x) for x in items]
            else:
                self._last_orders.update({x["order_id"]: x for x in items})
        if self.duplicate_fills and name == "GET_FILLS":
            items = [x for x in items for _ in (0, 1)]
        if self.reverse_listings:
            items = list(reversed(items))
        body[key] = items
        return h.Reply("OK", reply.status, json.dumps(body, sort_keys=True).encode())

    def save(self, path: str | None = None) -> None:
        self.kill_point = None
        super().save(path)

    def place_manual(self, t: str, side: m.Side, price: str, qty: str, *, n: int) -> None:
        """An order placed in the venue's own interface (not through our send): it has no attempt, by design."""
        coid = f"manual-{n:06d}"
        self.manual.add(coid)
        reply = self.venue.new_order(ticker=t, side=side, action=m.Action.BUY, count=Decimal(qty),
                                     price=Decimal(price), time_in_force=m.TimeInForce.IMMEDIATE_OR_CANCEL,
                                     client_order_id=coid, post_only=False, reduce_only=False)
        assert reply.outcome == "ok", reply
        self.touched[t] = self.venue.now_text()


# ---------------------------------------------------------------------------------------------- the HTTP glue


class _Response:
    def __init__(self, status: int, body: bytes, url: str):
        self.status, self._body, self._url = status, body, url

    def read(self, n: int = -1) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


WRITE_FAULTS = ("ok", "429", "503_before", "503_after", "timeout_before", "timeout_after", "malformed_after",
                "409_after")
READ_FAULTS = ("ok", "429", "503", "timeout", "malformed")


class HttpVenue:
    """The orchestrator's `send`: the real `transport.Transport` (fixture signer, real `RateBudget`, this object as its
    injected opener) in front of a `ChaosAdapter`. `write_mix`/`read_mix` are (fault, weight) pairs drawn by a seeded
    RNG; `script` forces the next write faults in order. Reads and cancels use PROTECTIVE priority."""

    def __init__(self, adapter: ChaosAdapter, clock: h.Clock, *, seed: int = 0, write_mix=(("ok", 1),),
                 read_mix=(("ok", 1),), budget=None):
        from cryptography.hazmat.primitives.asymmetric import ed25519

        from edge_lab.execution import transport as t
        from edge_lab.execution.signer import Signer

        self.t = t
        signer = Signer(key_id="fixture-key-id", private_key=ed25519.Ed25519PrivateKey.generate(),
                        environment=m.Environment.FIXTURE, account_ref=h.SCOPE.account_ref)
        self.adapter, self.clock, self.rng = adapter, clock, random.Random(seed)
        self.write_mix, self.read_mix = write_mix, read_mix
        self.script: list[str] = []
        self.log: list[tuple[str, str]] = []  # (endpoint, fault drawn) per opener call
        self.budget = budget if budget is not None else t.RateBudget(
            monotonic_ns=lambda: int(clock().timestamp() * 1_000_000_000))
        self.transport = t.Transport(m.Environment.FIXTURE, signer, self._open, clock, budget=self.budget,
                                     sleep=lambda s: None)
        self._pending = None

    def _pick(self, mix) -> str:
        names, weights = zip(*mix)
        return self.rng.choices(names, weights)[0]

    def __call__(self, request):
        self._pending = request
        prio = self.t.Priority.PROTECTIVE if request.endpoint.value.protective else self.t.Priority.ORDINARY
        try:
            result = self.transport.send(request, priority=prio)
        finally:
            self._pending = None
        return result

    def _open(self, http_request, timeout):
        request, url = self._pending, http_request.full_url
        write = request.is_write()
        fault = (self.script.pop(0) if write and self.script else
                 self._pick(self.write_mix if write else self.read_mix))
        self.log.append((request.endpoint.name, fault))
        if fault in ("429", "503_before", "timeout_before", "503", "timeout") or (not write and fault == "malformed"):
            if fault == "429":
                return _Response(429, b'{"error":"rate limited"}', url)
            if fault in ("503", "503_before"):
                return _Response(503, b'{"error":"unavailable"}', url)
            if fault in ("timeout", "timeout_before"):
                raise TimeoutError("fixture timeout")
            self.adapter(request)  # a read that reached the venue but whose body was mangled on the way back
            return _Response(200, b'{"orders": [ {"order_id": ', url)
        reply = self.adapter(request)  # the venue acts
        if fault == "503_after":
            return _Response(503, b'{"error":"upstream"}', url)
        if fault == "timeout_after":
            raise TimeoutError("fixture timeout after the venue acted")
        if fault == "malformed_after":
            return _Response(201, b'{"order_id": "', url)
        if fault == "409_after":
            return _Response(409, b'{"error":"conflict"}', url)
        if reply.outcome == "OK":
            return _Response(reply.status, reply.body, url)
        if reply.outcome == "REJECTED":
            return _Response(reply.status or 400, reply.body or b"{}", url)
        if reply.outcome == "UNAVAILABLE":
            raise URLError("fixture source loss")
        raise TimeoutError("fixture venue fault")  # AMBIGUOUS from a FakeVenue fault


# ---------------------------------------------------------------------------------------------- the workload


class Workload:
    """The declared synthetic workload (seeded; no edge, no strategy): per cycle, fresh liquidity on each live market
    with probability 0.6 (NO side) and 0.5 (YES side); `per_cycle` draws the number of ENTRY signals (default 0, 1, 1
    or 2); 35% of entries are GTC one tick inside the ask, the rest IOC at the ask, 25% of IOCs race a competitor
    lifting one contract first; an EXIT of up to 3 held YES contracts with probability 0.35."""

    def __init__(self, seed: int, markets: tuple[str, ...] = h.MARKETS, *, per_cycle=(0, 1, 1, 2),
                 exit_share: float = 0.35, prefix: str = "w"):
        self.rng, self.markets, self.per_cycle, self.exit_share = random.Random(seed), markets, per_cycle, exit_share
        self.n, self.prefix = 0, prefix

    def signal_id(self, cycle: int) -> str:
        self.n += 1
        return f"{self.prefix}{cycle:05d}-{self.n:06d}"

    def liquidity(self, adapter: h.VenueAdapter) -> None:
        rng = self.rng
        for t in self.markets:
            if t in adapter.settled:
                continue
            if rng.random() < 0.6:
                adapter.venue.add_liquidity(t, m.Side.NO, f"0.{rng.randint(53, 57)}", rng.randint(1, 5))
            if rng.random() < 0.5:
                adapter.venue.add_liquidity(t, m.Side.YES, f"0.{rng.randint(38, 43)}", rng.randint(1, 5))

    def signals(self, cycle: int, adapter: h.VenueAdapter, clock: h.Clock, n: int | None = None) -> list[o.Signal]:
        rng, out = self.rng, []
        live = [t for t in self.markets if t not in adapter.settled]
        for _ in range(rng.choice(self.per_cycle) if n is None else n):
            t = rng.choice(live)
            ask = best_yes_ask(adapter, t)
            if ask is None:
                continue
            gtc = rng.random() < 0.35
            limit = ask - Decimal("0.01") * rng.randint(0, 1) if gtc else ask
            qty = rng.randint(1, 4) + (rng.randint(2, 4) if gtc else 0)
            if not gtc and rng.random() < 0.25:
                adapter.competitor.append((t, m.Side.YES, f"{ask:.2f}", 1))
            out.append(h.signal(self.signal_id(cycle), t, at=clock(), limit=f"{limit:.2f}", qty=str(qty),
                                tif="good_till_canceled" if gtc else "immediate_or_cancel"))
        held = sorted((t, q) for (t, s), q in adapter.venue.positions.items()
                      if s is m.Side.YES and q > 0 and t not in adapter.settled and t in self.markets)
        if held and rng.random() < self.exit_share:
            t, q = rng.choice(held)
            bid = best_yes_bid(adapter, t)
            if bid is not None:
                out.append(h.signal(self.signal_id(cycle), t, at=clock(), kind="EXIT", limit=f"{bid:.2f}",
                                    qty=str(min(int(q), rng.randint(1, 3)))))
        return out

    def stimulate(self, cycle: int, orch: o.Orchestrator, adapter: h.VenueAdapter, clock: h.Clock,
                  n: int | None = None) -> list[o.SignalAdmission]:
        self.liquidity(adapter)
        return [orch.submit_signal(s) for s in self.signals(cycle, adapter, clock, n)]


# ---------------------------------------------------------------------------------------------- invariants


class InvariantViolation(AssertionError):
    pass


def _rows(journal: ExecutionJournal, sql: str, args: tuple = ()) -> list[tuple]:
    return journal._conn.execute(sql, args).fetchall()  # test-only read of the store's own tables


def check_invariants(journal: ExecutionJournal, adapter: ChaosAdapter, *, live: o.Orchestrator | None = None,
                     report: o.CycleReport | None = None, chain: bool = True) -> dict:
    """The global invariants of package P, from the durable store and the venue. Raises InvariantViolation.

    1. No venue order without a prepared attempt: every create reached the venue only after its PENDING_EGRESS
       attempt was committed (probe at send time), and every venue order's client id has an attempt.
    2. At most one attempt per intent key, and no client order id reached the venue twice.
    3. The journal never shows more fills than the venue (every reservation, released ones included).
    4. Positions reconcile: venue positions equal the fills' net (zero once settled), never negative; after a COMPLETE
       cycle the latest snapshot's positions equal what the venue served.
    5. No reservation released without confirmation: a REJECTED/ABSENT release follows an attempt outcome backed by a
       recorded receipt; any other release follows BOUND (with a receipt) and names a later snapshot; and no released
       reservation's order is still resting at the venue.
    6. `verify_chain` is OK.
    7. Control: replaying the persisted control events, every incident leaves the controller DISARMED, only an
       accepted arm leaves DISARMED, and every attempt was prepared while the replayed mode was a sending mode. The
       live, unfenced orchestrator's state equals the replay.
    """
    problems: list[str] = []
    venue = adapter.venue
    attempts = _rows(journal, "SELECT attempt_id, intent_key, client_order_id, state FROM attempts")
    by_key: dict[str, int] = defaultdict(int)
    for _, key, _, _ in attempts:
        by_key[key] += 1
    problems += [f"INV2 intent {k} has {n} attempts" for k, n in by_key.items() if n > 1]
    prepared = {coid for _, _, coid, _ in attempts}
    orders = venue.list_orders()
    venue_coids = [x["client_order_id"] for x in orders]
    problems += [f"INV2 client id {c} at the venue twice" for c in set(venue_coids) if venue_coids.count(c) > 1]
    problems += [f"INV2 client id {c} created {adapter.creates.count(c)} times" for c in set(adapter.creates)
                 if adapter.creates.count(c) > 1]
    problems += [f"INV1 venue order {c} has no prepared attempt" for c in venue_coids
                 if c not in prepared and c not in adapter.manual]
    problems += [f"INV1 create {c} reached the venue with attempt state {s}" for c, s in adapter.unprepared]

    by_coid = {x["client_order_id"]: x for x in orders}
    reservations = _rows(journal, "SELECT reservation_id, client_order_id, filled_quantity, state, release_reason"
                                  " FROM reservations")
    for rid, coid, filled, state, _ in reservations:
        venue_filled = by_coid[coid]["fill_count"] if coid in by_coid else Decimal(0)
        if Decimal(filled) > venue_filled:
            problems.append(f"INV3 {rid} records {filled} filled, the venue {venue_filled}")
        if state == "RELEASED" and coid in by_coid and by_coid[coid]["status"] == "resting":
            problems.append(f"INV5 {rid} released while its order rests at the venue")

    fills = venue.list_fills()
    net: dict = defaultdict(Decimal)
    for f in fills:
        net[(f["ticker"], m.Side(f["side"]))] += f["count"] if f["action"] == "buy" else -f["count"]
    for key, qty in venue.positions.items():
        expected = Decimal(0) if key[0] in adapter.settled else net.get(key, Decimal(0))
        if qty != expected or qty < 0:
            problems.append(f"INV4 venue position {key} is {qty}, the fills' net {expected}")
    if report is not None and report.reconciliation == "COMPLETE" and not report.fenced_out:
        snap = journal.reservations.latest_snapshot(h.SCOPE)
        if snap is None or not snap.consistent or dict(snap.positions) != adapter.positions_served:
            problems.append(f"INV4 the COMPLETE snapshot's positions differ from the venue's: "
                            f"{None if snap is None else dict(snap.positions or {})} vs {adapter.positions_served}")

    events = _rows(journal, "SELECT seq, kind, subject, body_json FROM events ORDER BY seq")
    attempt_state = {a: s for a, _, _, s in attempts}
    receipts = {r[0]: r[1] for r in _rows(journal, "SELECT receipt_id, kind FROM receipts WHERE status = 'ORIGINAL'")}
    outcome_receipt: dict[str, str | None] = {}
    bound: dict[str, str | None] = {}
    for _, kind, subject, body_json in events:
        if kind != "ATTEMPT_STATE" and not kind.startswith("RESERVATION_"):
            continue
        body = json.loads(body_json)
        if kind == "ATTEMPT_STATE" and body.get("to") in ("REJECTED", "ABSENT"):
            outcome_receipt[subject] = body.get("receipt_id")
        if kind.startswith("RESERVATION_") and body.get("to") == "BOUND" and body.get("from") != "BOUND":
            bound[subject] = body.get("receipt_id")  # ended at the venue (a cancel, an expiry or the last fill)
        if kind == "RESERVATION_STATE" and body.get("to") == "RELEASED":
            reason = body.get("release_reason")
            if reason in ("REJECTED", "ABSENT_AT_VENUE"):
                rec = outcome_receipt.get(subject)
                if attempt_state.get(subject) not in ("REJECTED", "ABSENT") or rec not in receipts \
                        or receipts[rec] not in ("ORDER_REJECT", "ORDER_LOOKUP"):
                    problems.append(f"INV5 {subject} released {reason} without a recorded venue outcome")
            elif reason in ("CANCEL_CONFIRMED", "EXPIRED", "CONVERTED_TO_POSITION"):
                if subject not in bound or bound[subject] not in receipts or "snapshot_revision" not in body:
                    problems.append(f"INV5 {subject} released {reason} without BOUND evidence and a later snapshot")
            else:
                problems.append(f"INV5 {subject} released with reason {reason!r}")

    if chain:
        verification = journal.verify_chain()
        if not verification.ok:
            problems.append(f"INV6 verify_chain: {list(verification.problems)[:5]}")

    seqs = [s for s, kind, subject, _ in events if kind == CONTROL_EVENT_KIND and subject == h.SCOPE.key()]
    control_events = journal.control_events(h.SCOPE)
    prepared_at = {s for s, kind, _, _ in events if kind == "ATTEMPT_PREPARED"}
    state = ctl.initial_state(h.SCOPE)
    timeline = sorted([(s, "control", e) for s, e in zip(seqs, control_events)] +
                      [(s, "prepare", None) for s in prepared_at], key=lambda x: x[0])
    for seq, what, event in timeline:
        if what == "prepare":
            if state.mode not in SENDING:
                problems.append(f"INV7 an attempt was prepared at seq {seq} while the replayed mode is "
                                f"{state.mode.value}")
            continue
        before = state.mode
        state = ctl.reduce(state, event)
        incident = isinstance(event, ctl.IncidentRaised) or (
            isinstance(event, ctl.ReconciliationObserved) and event.status is not ctl.Reconciliation.COMPLETE
            and before in ctl.RECONCILED_MODES)
        if incident and state.mode is not ctl.Mode.DISARMED:
            problems.append(f"INV7 incident at seq {seq} left the mode {state.mode.value}")
        left = before is ctl.Mode.DISARMED and state.mode is not ctl.Mode.DISARMED
        if left and not isinstance(event, ctl.ArmAccepted):
            problems.append(f"INV7 {type(event).__name__} at seq {seq} left DISARMED")
    if live is not None and not live.fenced_out and live.state != state:
        problems.append(f"INV7 the live state ({live.state.mode.value}, {len(live.state.log)} lines) is not the "
                        f"replay of the store ({state.mode.value}, {len(state.log)} lines)")
    if problems:
        raise InvariantViolation("; ".join(problems[:12]))
    return {"attempts": len(attempts), "orders": len(orders), "fills": len(fills), "events": len(events),
            "mode": state.mode.value}


def unresolved(journal: ExecutionJournal) -> list[tuple[str, str]]:
    """Attempts not yet in a terminal state (PENDING_EGRESS, SENT, OUTCOME_UNKNOWN)."""
    return [(a.attempt_id, a.state.value) for a in journal.non_terminal_attempts()]


# ---------------------------------------------------------------------------------------------- the rig


class Rig:
    """One orchestrator on one journal file, a ChaosAdapter venue and an operator. `send` defaults to the adapter;
    pass `http=dict(...)` to put the real transport in between (`HttpVenue`)."""

    def __init__(self, tmp_path: Path, *, name: str = "p", markets: tuple[str, ...] = h.MARKETS, seed: int = 0,
                 http: dict | None = None, adapter: ChaosAdapter | None = None, clock: h.Clock | None = None,
                 **config_kw):
        self.tmp_path, self.markets, self.config_kw = tmp_path, markets, config_kw
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.jpath = tmp_path / f"{name}.execution.sqlite3"
        self.clock = clock or h.Clock()
        if adapter is None:
            adapter = ChaosAdapter(self.clock, journal_path=str(self.jpath))
            seed_books(adapter, markets)
        self.adapter = adapter
        self.http = None if http is None else HttpVenue(adapter, self.clock, seed=seed, **http)
        self.send: Callable = self.adapter if self.http is None else self.http
        self.journal = ExecutionJournal.open(self.jpath)
        self.reports: list[o.CycleReport] = []
        self.operator: list[tuple[int, str]] = []
        grants = config_kw.get("grants")
        self.grant_digest = None if not grants else grants[0].digest()  # None: the harness's default grant
        self.orch = self.boot()

    def boot(self, **kw) -> o.Orchestrator:
        cfg = {**self.config_kw, **kw}
        self.feed = h.Feed(self.adapter)
        return o.Orchestrator(self.journal, h.config(**cfg), send=lambda r: self.send(r), feed=self.feed,
                              strategies=(h.DemoStrategy(),), clock=self.clock, sleep=self.clock.sleep)

    def restart(self, **kw) -> o.Orchestrator:
        """A process restart on the same store: a new journal connection and a new orchestrator (boot, lease)."""
        try:
            self.journal.close()
        except Exception:
            pass
        self.journal = ExecutionJournal.open(self.jpath)
        self.orch = self.boot(**kw)
        assert self.orch.state.mode is ctl.Mode.DISARMED, "a restart never re-arms itself"
        return self.orch

    def operate(self, report: o.CycleReport, mode: ctl.Mode = ctl.Mode.BOUNDED_AUTO) -> bool:
        """The operator: after a COMPLETE cycle in DISARMED, arm naming the open incidents (one action per episode)."""
        if report.reconciliation == "COMPLETE" and not report.fenced_out and self.orch.state.mode is ctl.Mode.DISARMED:
            outcome = h.arm(self.orch, mode, self.clock, grant_digest=self.grant_digest)
            self.operator.append((report.cycle, type(outcome).__name__))
            return isinstance(outcome, ctl.ArmAccepted)
        return False

    def cycle(self, *, check: bool = True, chain: bool = True) -> o.CycleReport:
        report = self.orch.run_cycle()
        self.reports.append(report)
        if check:
            check_invariants(self.journal, self.adapter, live=self.orch, report=report, chain=chain)
        return report

    def step(self, workload: Workload | None = None, *, n: int | None = None, advance: float = 60,
             arm: bool = True, check: bool = True, chain: bool = True) -> o.CycleReport:
        if workload is not None:
            workload.stimulate(len(self.reports) + 1, self.orch, self.adapter, self.clock, n)
        report = self.cycle(check=check, chain=chain)
        if arm:
            self.operate(report)
        self.clock.advance(advance)
        return report

    def jump(self, seconds: float) -> None:
        """Our clock jumps; the venue's true time does not."""
        self.clock.advance(seconds)
        self.adapter.skew -= seconds

    def warm(self) -> None:
        """Boot cycle plus arm: BOUNDED_AUTO with a COMPLETE reconciliation."""
        report = self.cycle()
        assert report.reconciliation == "COMPLETE", report
        assert self.operate(report), self.orch.state.log[-1]
        self.clock.advance(60)

    def settle(self, cycles: int = 6, *, arm: bool = True) -> None:
        """Quiet cycles (no new signals) until every attempt is terminal; fails if some stays unresolved."""
        for _ in range(cycles):
            self.step(arm=arm)
            if not unresolved(self.journal):
                return
        assert not unresolved(self.journal), unresolved(self.journal)

    def close(self) -> None:
        try:
            self.journal.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------------------------- measurement


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile (no interpolation); NaN for no samples."""
    if not values:
        return float("nan")
    xs = sorted(values)
    rank = max(1, -(-len(xs) * p // 100))
    return xs[int(rank) - 1]


class Timings:
    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = defaultdict(list)

    def wrap(self, name: str, fn: Callable) -> Callable:
        def timed(*a, **kw):
            start = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                self.samples[name].append(time.perf_counter() - start)
        return timed

    def instrument_journal(self, journal: ExecutionJournal) -> None:
        """Time every outermost write transaction (BEGIN IMMEDIATE ... COMMIT) of this journal connection."""
        original = journal._transaction
        samples = self.samples["journal_write"]

        @contextmanager
        def timed():
            outer = journal._depth == 0
            start = time.perf_counter()
            with original() as conn:
                yield conn
            if outer:
                samples.append(time.perf_counter() - start)

        journal._transaction = timed

    def summary(self, name: str, scale: float = 1000.0) -> dict:
        xs = self.samples.get(name, [])
        return {"n": len(xs), "p50": round(percentile(xs, 50) * scale, 3), "p95": round(percentile(xs, 95) * scale, 3),
                "p99": round(percentile(xs, 99) * scale, 3), "max": round(max(xs) * scale, 3) if xs else None}


def journal_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in (path, Path(str(path) + "-wal")) if p.exists())


def max_seq(journal: ExecutionJournal) -> int:
    return int(journal._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0])


# ---------------------------------------------------------------------------------------------- process death


def kill_child_main(journal_path: str, state_path: str, plan_json: str) -> None:
    """Boot a fresh orchestrator on the shared store and venue state, then run `plan["cycles"]` workload cycles with
    the operator arming after each COMPLETE one. Die (`os._exit(19)`) at kill point number `plan["kill_at"]`: a kill
    point is every outermost journal commit (just before COMMIT: the transaction is lost) and every venue write
    (before the venue acts, and after it acted but before the reply is recorded). The venue's state is saved at the
    moment of death: it outlives the process. With `plan["label"]` ("before_commit", "before_send" or "after_send")
    only the points of that kind are counted. Exit 3 means the plan ended before the kill point; it prints the counts
    of every kind (a dry run on a copy of the store uses that to draw a kill point)."""
    plan = json.loads(plan_json)
    adapter = ChaosAdapter.load(state_path)
    adapter.journal_path = journal_path
    clock = adapter.clock
    clock.at = m.parse_utc_text(plan["at"])
    points: dict[str, int] = defaultdict(int)
    only = plan.get("label")  # count (and kill at) only the points with this label, if given

    def point(label: str) -> None:
        points["all"] += 1
        points[label] += 1
        if points[only or "all"] == plan["kill_at"] and (only is None or label == only):
            adapter.save(state_path)
            print(f"KILLED {points['all']} {label}", flush=True)
            os._exit(19)

    adapter.kill_point = point
    journal = ExecutionJournal.open(journal_path)
    journal._fault_hook = lambda where: point(where)
    rig = Rig.__new__(Rig)  # reuse the rig's operator and step on the loaded state (no new venue)
    rig.tmp_path, rig.markets, rig.config_kw = Path(journal_path).parent, tuple(plan["markets"]), {}
    rig.jpath, rig.clock, rig.adapter, rig.http, rig.send = Path(journal_path), clock, adapter, None, adapter
    rig.journal, rig.reports, rig.operator, rig.grant_digest = journal, [], [], None
    rig.orch = rig.boot()
    workload = Workload(plan["seed"], tuple(plan["markets"]), prefix="k")  # its own signal ids
    for _ in range(plan["cycles"]):
        rig.step(workload, check=False)
    adapter.save(state_path)
    print("SURVIVED " + json.dumps(dict(points), sort_keys=True), flush=True)
    os._exit(3)


CHILD = """
import sys
sys.path[:0] = [{tests!r}, {src!r}]
import chaos_support as cs
cs.kill_child_main(*sys.argv[1:])
"""


def kill_command(journal_path: Path, state_path: Path, plan: dict) -> list[str]:
    here = Path(__file__).resolve().parent
    src = here.parents[1] / "src"
    return [sys.executable, "-c", CHILD.format(tests=str(here), src=str(src)), str(journal_path), str(state_path),
            json.dumps(plan, sort_keys=True)]


def hardware() -> dict:
    import platform
    return {"python": platform.python_version(), "platform": platform.platform(), "machine": platform.machine(),
            "processor": platform.processor(), "cpus": os.cpu_count(), "sqlite": sqlite3.sqlite_version}


def at_text(clock: h.Clock) -> str:
    return m.utc_text(clock())
