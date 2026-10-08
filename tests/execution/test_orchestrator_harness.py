"""Shared test harness for the orchestrator (#160 package K). It holds no tests. FIXTURE only; nothing leaves the
process.

- `VenueAdapter`: the `send` the orchestrator is given. It turns each `WireRequest` into a `FakeVenue` call (writes)
  or builds a venue-shaped page from the fake's state (reads), in the documented response shapes, and replies with
  `outcome`/`status`/`body` like `transport.TransportResult`. Settlement, realized P&L, positions and the balance are
  kept here, because the fake venue deliberately has none. The fake venue is imported by tests only.
- `Feed`: market states (book, grid, fee identity) from the fake's book.
- `DemoStrategy`: a synthetic policy that turns ENTRY and EXIT signals into intents. It has no edge and is not a
  strategy: it only drives the chain.
- `child_main`: the out-of-process worker for the process-death scenarios (`os._exit` at a kill point).

The balance this adapter reports is the fake's cash minus what its resting buys hold: "available after venue
holds". That is the FIXTURE assumption the tests declare with `fixture_cash_basis`.
"""

from __future__ import annotations

import json
import os
import pickle
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal
from enum import Enum
from pathlib import Path

from edge_lab.execution import control as ctl
from edge_lab.execution import model as m
from edge_lab.execution import orchestrator as o
from edge_lab.execution import risk_gate as g
from edge_lab.execution.account import ExternalCashPolicy
from edge_lab.execution.fake_venue import FakeVenue
from edge_lab.execution.journal import ExecutionJournal
from edge_lab.execution.kalshi_wire import Endpoint, WireRequest, yes_terms
from edge_lab.execution.lifecycle import Liquidity
from edge_lab.execution.reservations import CashBasis
from edge_lab.execution_ticket import TicketLimits
from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1
from edge_lab.risk import RiskPolicy

UTC = timezone.utc
T0 = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
SCOPE = m.AccountScope(m.Environment.FIXTURE, "fixture-acct")
EVENT, CLUSTER = "KXHIGHNY-26OCT08", "nyc-weather"
MARKETS = ("KXHIGHNY-26OCT08-B70", "KXHIGHNY-26OCT08-B72", "KXHIGHNY-26OCT08-B74")
CENT = m.Grid(step=Decimal("0.01"), minimum=Decimal("0.01"), maximum=Decimal("0.99"))
WHOLE = m.Grid(step=Decimal("1"), minimum=Decimal("1"), maximum=Decimal("1000"))
VENUE_LAG = timedelta(minutes=10)  # the fake venue's clock trails ours: its stamps are never ahead of a read
CUTOFF = "2026-09-01T00:00:00Z"
STRATEGY_ID = "synthetic-demo"
MODEL_HASH, POLICY_HASH = "a" * 64, "b" * 64

# Explicit TEST limits, passed as typed inputs. They are not owner limits and never replace the placeholders.
POLICY = RiskPolicy("orchestrator-test-policy", reserve_floor=Decimal("10"), max_position_risk=Decimal("15"),
                    max_event_risk=Decimal("60"), max_cluster_risk=Decimal("80"), max_portfolio_risk=Decimal("80"),
                    daily_loss_limit=Decimal("30"), weekly_loss_limit=Decimal("60"), max_drawdown=Decimal("60"))
LIMITS = g.GateLimits(limits_id="orchestrator-test-limits", risk_policy_id=POLICY.policy_id,
                      owner_approval_ref="test-fixture-only-not-owner", max_quantity_per_order=Decimal("10"),
                      max_slippage=Decimal("0.05"), max_decision_age=timedelta(minutes=2),
                      max_source_age=timedelta(minutes=5), daily_new_risk=Decimal("60"),
                      max_strategy_risk=Decimal("60"))
TICKET = TicketLimits(max_book_age=timedelta(seconds=30), max_order_state_age=timedelta(minutes=2),
                      max_orders_per_window=8, order_window=timedelta(minutes=10), market_cooldown=timedelta(seconds=30))
TEST_RISK = o.RiskInputs(POLICY, LIMITS, TICKET)
BOUNDS = o.CycleBounds(max_queued_signals=20, max_signals_per_cycle=6, max_proposals_per_cycle=10,
                       max_intents_per_cycle=3, max_requests_per_cycle=80, cycle_deadline=timedelta(seconds=30),
                       max_signal_validity=timedelta(minutes=10))


def money(value: Decimal, places: int = 4) -> str:
    q = Decimal(1).scaleb(-places)
    return f"{value.quantize(q):f}"


def count(value: Decimal) -> str:
    return f"{Decimal(value).quantize(Decimal('0.01')):f}"


def fee_hook(price: Decimal, quantity: Decimal, liquidity: Liquidity) -> Decimal:
    """Taker fills pay the verified Kalshi quadratic fee; maker fills pay nothing (maker fee 0 for KXHIGHNY)."""
    if liquidity is Liquidity.MAKER:
        return Decimal(0)
    return KALSHI_QUADRATIC_TAKER_V1.taker_buy(int(quantity), price).fee


class Clock:
    """The injected clock. Frozen unless advanced; `sleep` advances it (no real waiting)."""

    def __init__(self, at: datetime = T0):
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at = self.at + timedelta(seconds=seconds)

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)


@dataclass(frozen=True)
class Reply:
    outcome: str
    status: int | None
    body: bytes | None = None


def ok(obj: dict, status: int = 200) -> Reply:
    return Reply("OK", status, json.dumps(obj, sort_keys=True).encode())


@dataclass
class _Basis:
    quantity: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)


@dataclass
class VenueAdapter:
    """The orchestrator's `send`. See the module docstring."""

    clock: Clock
    venue: FakeVenue = field(default=None)  # type: ignore[assignment]
    reads_fail: bool = False  # source loss: every read is UNAVAILABLE
    die: str | None = None  # "before_send" / "after_send": os._exit at that point of the next write (child only)
    state_path: str | None = None
    competitor: list = field(default_factory=list)  # (ticker, side, price, qty) taken from the book before our order
    requests: list = field(default_factory=list)
    settlements: list = field(default_factory=list)
    settled: dict = field(default_factory=dict)  # ticker -> result
    realized: dict = field(default_factory=dict)
    fees: dict = field(default_factory=dict)
    traded: dict = field(default_factory=dict)
    touched: dict = field(default_factory=dict)  # ticker -> last change (venue time)
    basis: dict = field(default_factory=dict)
    expiries: dict = field(default_factory=dict)  # order id -> expiration (our time)
    fills_seen: int = 0
    writes: list = field(default_factory=list)
    positions_served: dict = field(default_factory=dict)  # the venue positions at the last positions read

    def __post_init__(self) -> None:
        if self.venue is None:
            self.venue = FakeVenue(fee=fee_hook, price_grid=CENT, quantity_grid=WHOLE, cash="100",
                                   start=self.clock() - VENUE_LAG, tick_seconds=1)

    # ---------------------------------------------------------------- bookkeeping

    def venue_now(self) -> datetime:
        return m.parse_utc_text(self.venue.now_text())

    def sync(self) -> None:
        target = self.clock() - VENUE_LAG
        gap = int((target - self.venue_now()).total_seconds())
        if gap > 0:
            self.venue.advance(gap)
        for order_id, expires in sorted(self.expiries.items()):
            if expires <= self.clock() and self.venue.expire(order_id):
                self.touched[self.venue.get_order(order_id)["ticker"]] = self.venue.now_text()
        fills = self.venue.list_fills()
        for f in fills[self.fills_seen:]:
            self._book_fill(f)
        self.fills_seen = len(fills)

    def _book_fill(self, f: dict) -> None:
        ticker, side, qty, price = f["ticker"], m.Side(f["side"]), Decimal(f["count"]), Decimal(f["price"])
        b = self.basis.setdefault((ticker, side), _Basis())
        self.fees[ticker] = self.fees.get(ticker, Decimal(0)) + (f["fee"] or Decimal(0))
        self.traded[ticker] = self.traded.get(ticker, Decimal(0)) + price * qty
        if f["action"] == "buy":
            b.quantity += qty
            b.cost += price * qty
        else:
            unit = (b.cost / b.quantity) if b.quantity else Decimal(0)
            removed = (unit * qty).quantize(Decimal("0.000001"))
            self.realized[ticker] = self.realized.get(ticker, Decimal(0)) + price * qty - removed
            b.quantity -= qty
            b.cost -= removed
        self.touched[ticker] = f["created_time"]

    def settle(self, ticker: str, result: m.Side) -> None:
        """The market settles (the fake has no settlement): resting orders end, holdings pay $1 or nothing."""
        self.sync()
        for order in self.venue.list_orders(ticker):
            if order["status"] == "resting":
                self.venue.expire(order["order_id"])
        self.sync()
        held = {s: self.venue.positions.get((ticker, s), Decimal(0)) for s in m.Side}
        cost = {s: self.basis.get((ticker, s), _Basis()).cost for s in m.Side}
        payout = held[result]
        self.venue.cash += payout
        self.realized[ticker] = self.realized.get(ticker, Decimal(0)) + payout - cost[m.Side.YES] - cost[m.Side.NO]
        for s in m.Side:
            self.venue.positions[(ticker, s)] = Decimal(0)
            self.basis[(ticker, s)] = _Basis()
        self.settled[ticker] = result.value
        at = self.venue.now_text()
        self.touched[ticker] = at
        self.settlements.append({
            "ticker": ticker, "exchange_index": 0, "event_ticker": EVENT, "market_result": result.value,
            "yes_count_fp": count(held[m.Side.YES]), "yes_total_cost_dollars": money(cost[m.Side.YES]),
            "no_count_fp": count(held[m.Side.NO]), "no_total_cost_dollars": money(cost[m.Side.NO]),
            "revenue": int(payout * 100), "settled_time": at, "fee_cost": "0.0000", "value": 100})

    # ---------------------------------------------------------------- venue-shaped records

    def _order_json(self, order: dict) -> dict:
        side, action = m.Side(order["side"]), m.Action(order["action"])
        book, yes = yes_terms(side, action, Decimal(order["price"]))
        fills = self.venue.list_fills(order["order_id"])
        taker = [f for f in fills if f["is_taker"]]
        maker = [f for f in fills if not f["is_taker"]]
        return {"order_id": order["order_id"], "user_id": "fixture-user", "client_order_id": order["client_order_id"],
                "ticker": order["ticker"], "outcome_side": "yes" if book == "bid" else "no", "book_side": book,
                "type": "limit", "status": order["status"], "yes_price_dollars": money(yes),
                "no_price_dollars": money(1 - yes), "fill_count_fp": count(order["fill_count"]),
                "remaining_count_fp": count(order["remaining_count"]),
                "initial_count_fp": count(order["initial_count"]),
                "taker_fees_dollars": money(sum((f["fee"] for f in taker), Decimal(0)), 6),
                "maker_fees_dollars": money(sum((f["fee"] for f in maker), Decimal(0)), 6),
                "taker_fill_cost_dollars": money(sum((f["price"] * f["count"] for f in taker), Decimal(0))),
                "maker_fill_cost_dollars": money(sum((f["price"] * f["count"] for f in maker), Decimal(0))),
                "expiration_time": None, "created_time": order["created_time"],
                "last_update_time": order["last_update_time"], "self_trade_prevention_type": "taker_at_cross",
                "order_group_id": None, "cancel_order_on_pause": True, "subaccount_number": 0, "exchange_index": 0}

    def _fill_json(self, f: dict) -> dict:
        side, action = m.Side(f["side"]), m.Action(f["action"])
        book, _ = yes_terms(side, action, Decimal(f["price"]))
        yes = Decimal(f["price"]) if side is m.Side.YES else 1 - Decimal(f["price"])
        return {"fill_id": f["fill_id"], "trade_id": f["fill_id"], "order_id": f["order_id"], "ticker": f["ticker"],
                "market_ticker": f["ticker"], "outcome_side": "yes" if book == "bid" else "no", "book_side": book,
                "count_fp": count(f["count"]), "yes_price_dollars": money(yes), "no_price_dollars": money(1 - yes),
                "is_taker": f["is_taker"], "fee_cost": money(f["fee"], 6), "exchange_index": 0,
                "created_time": f["created_time"], "subaccount_number": 0}

    def _positions(self) -> list[dict]:
        rows = []
        for ticker in sorted(self.touched):
            yes = self.venue.positions.get((ticker, m.Side.YES), Decimal(0))
            no = self.venue.positions.get((ticker, m.Side.NO), Decimal(0))
            exposure = self.basis.get((ticker, m.Side.YES), _Basis()).cost + self.basis.get(
                (ticker, m.Side.NO), _Basis()).cost
            rows.append({"ticker": ticker, "exchange_index": 0, "total_traded_dollars": money(self.traded.get(
                ticker, Decimal(0))), "position_fp": count(yes - no), "market_exposure_dollars": money(exposure),
                "realized_pnl_dollars": money(self.realized.get(ticker, Decimal(0)), 6),
                "fees_paid_dollars": money(self.fees.get(ticker, Decimal(0)), 6),
                "last_updated_ts": self.touched[ticker]})
        return rows

    @staticmethod
    def _page(key: str, items: list, query: dict, limit_default: int = 100) -> dict:
        start = int(query.get("cursor", "o:0").split(":")[1])
        limit = int(query.get("limit", limit_default))
        chunk = items[start:start + limit]
        nxt = f"o:{start + limit}" if start + limit < len(items) else None
        return {key: chunk, "cursor": nxt}

    # ---------------------------------------------------------------- the send

    def __call__(self, request: WireRequest) -> Reply:
        assert isinstance(request, WireRequest) and request.scope == SCOPE
        self.sync()
        name = request.endpoint.name
        self.requests.append(name)
        if request.is_write():
            return self._write(request)
        if self.reads_fail:
            return Reply("UNAVAILABLE", None)
        q = dict(request.query)
        if name == "GET_USER_DATA_TIMESTAMP":
            return ok({"as_of_time": m.utc_text(self.clock() - timedelta(seconds=1))})
        if name == "GET_HISTORICAL_CUTOFF":
            return ok({"market_settled_ts": CUTOFF, "trades_created_ts": CUTOFF, "orders_updated_ts": CUTOFF})
        if name == "GET_BALANCE":
            available = self.venue.cash - self.venue.account()["reserved"]
            return ok({"balance": int((available * 100).to_integral_value(rounding=ROUND_FLOOR)),
                       "balance_dollars": money(available, 6), "portfolio_value": 0,
                       "updated_ts": len(self.venue.list_fills()) + len(self.venue.list_orders()),
                       "balance_breakdown": [{"exchange_index": 0, "balance": money(available, 6)}]})
        if name == "GET_POSITIONS":
            self.positions_served = {k: q for k, q in self.venue.positions.items() if q != 0}
            page = self._page("market_positions", self._positions(), q)
            return ok({**page, "event_positions": []})
        if name == "GET_HISTORICAL_POSITIONS":
            return ok({"market_positions": [], "event_positions": [], "cursor": None})
        if name == "GET_ORDERS":
            return ok(self._page("orders", [self._order_json(x) for x in self.venue.list_orders()], q))
        if name in ("GET_HISTORICAL_ORDERS", "GET_HISTORICAL_FILLS"):
            return ok({"orders" if "ORDERS" in name else "fills": [], "cursor": None})
        if name == "GET_FILLS":
            return ok(self._page("fills", [self._fill_json(f) for f in self.venue.list_fills()], q))
        if name == "GET_SETTLEMENTS":
            return ok(self._page("settlements", list(self.settlements), q))
        return Reply("REJECTED", 404, b'{"error":"not served by the fixture"}')

    def _write(self, request: WireRequest) -> Reply:
        if self.die == "before_send":
            os._exit(17)  # after prepare_attempt committed, before anything reached the venue
        if request.endpoint is Endpoint.ORDER_CREATE:
            reply = self._create(json.loads(request.body))
        elif request.endpoint is Endpoint.ORDER_CANCEL:
            reply = self._cancel(request.path.rsplit("/", 1)[1])
        else:
            reply = Reply("REJECTED", 400, b'{"error":"unsupported by the fixture"}')
        self.writes.append((request.endpoint.name, reply.outcome))
        if self.die == "after_send":
            self.sync()
            self.save()
            os._exit(18)  # the venue acted; the reply is never recorded
        return reply

    def _create(self, body: dict) -> Reply:
        ticker, book, yes = body["ticker"], body["side"], Decimal(body["price"])
        reduce_only = body["reduce_only"]
        # The profile's entries are buys and its reductions sells (never a flip), so book side + reduce_only give
        # the outcome side and action without the legacy fields (DIR-04).
        if book == "bid":
            side, action, price = (m.Side.NO, m.Action.SELL, 1 - yes) if reduce_only else (m.Side.YES, m.Action.BUY,
                                                                                            yes)
        else:
            side, action, price = (m.Side.YES, m.Action.SELL, yes) if reduce_only else (m.Side.NO, m.Action.BUY,
                                                                                        1 - yes)
        for c_ticker, c_side, c_price, c_qty in self.competitor:  # someone else trades first (latency)
            if c_ticker == ticker:
                self.venue.add_liquidity(c_ticker, c_side, c_price, c_qty)
        self.competitor = [c for c in self.competitor if c[0] != ticker]
        reply = self.venue.new_order(ticker=ticker, side=side, action=action, count=Decimal(body["count"]),
                                     price=price.quantize(Decimal("0.01")), time_in_force=m.TimeInForce(
                                         body["time_in_force"]), client_order_id=body["client_order_id"],
                                     post_only=body["post_only"], reduce_only=reduce_only)
        self.sync()
        if reply.outcome in ("timeout", "lost"):
            return Reply("AMBIGUOUS", None)
        if reply.outcome == "error":
            return Reply("REJECTED", 400, json.dumps({"error": reply.error}).encode())
        order = reply.body["order"]
        self.touched[ticker] = order["last_update_time"]
        if "expiration_time" in body:
            self.expiries[order["order_id"]] = datetime.fromtimestamp(body["expiration_time"], UTC)
        fills = self.venue.list_fills(order["order_id"])
        filled = Decimal(order["fill_count"])
        ack = {"order_id": order["order_id"], "client_order_id": order["client_order_id"],
               "fill_count": count(filled), "remaining_count": count(order["remaining_count"]),
               "ts_ms": int(self.clock().timestamp() * 1000)}
        if filled > 0:
            ack["average_fill_price"] = money(sum((f["price"] * f["count"] for f in fills), Decimal(0)) / filled)
            ack["average_fee_paid"] = money(sum((f["fee"] for f in fills), Decimal(0)) / filled, 6)
        return ok(ack, 201)

    def _cancel(self, order_id: str) -> Reply:
        reply = self.venue.cancel(order_id)
        self.sync()
        if reply.outcome in ("timeout", "lost"):
            return Reply("AMBIGUOUS", None)
        if reply.outcome == "error":
            return Reply("REJECTED", 400, json.dumps({"error": reply.error}).encode())
        order = reply.body["order"]
        return ok({"order_id": order_id, "client_order_id": order["client_order_id"],
                   "reduced_by": count(reply.body["reduced_by"]), "ts_ms": int(self.clock().timestamp() * 1000)})

    # ---------------------------------------------------------------- persistence across processes

    def save(self, path: str | None = None) -> None:
        with open(path or self.state_path, "wb") as fh:
            _Pickler(fh).dump(self)

    @staticmethod
    def load(path: str) -> "VenueAdapter":
        with open(path, "rb") as fh:
            return pickle.load(fh)


def _rebuild(cls: type, state: dict) -> object:
    obj = object.__new__(cls)
    obj.__dict__.update(state)
    return obj


class _Pickler(pickle.Pickler):
    """Pickles package and harness objects from their instance dict. The default path (`copyreg._slotnames`) caches a
    `__slotnames__` list on each class, a mutable class value the runtime-immutability invariant would then find."""

    def reducer_override(self, obj: object):
        cls = type(obj)
        if isinstance(obj, (type, Enum, types.FunctionType)) or not hasattr(obj, "__dict__")                 or not cls.__module__.startswith(("edge_lab.", "test_orchestrator")):
            return NotImplemented
        return _rebuild, (cls, dict(vars(obj)))


class Feed:
    """Market states from the fake's book. `down` simulates source loss: every market is unknown."""

    def __init__(self, adapter: VenueAdapter):
        self.adapter = adapter
        self.down = False

    def market_state(self, ticker: str, now: datetime) -> g.MarketState | None:
        if self.down:
            return None
        self.adapter.sync()
        book = self.adapter.venue.book(ticker)
        yes_bids = tuple(g.BookLevel(p, q) for p, q in book["yes"])
        no_bids = tuple(g.BookLevel(p, q) for p, q in book["no"])
        yes_asks = tuple(g.BookLevel(1 - lv.price, lv.size) for lv in no_bids)
        no_asks = tuple(g.BookLevel(1 - lv.price, lv.size) for lv in yes_bids)
        stamp = m.utc_text(now)
        status = "finalized" if ticker in self.adapter.settled else "active"
        return g.MarketState(state_id=f"feed:{ticker}:{stamp}", ticker=ticker, as_of_utc=stamp, market_type="binary",
                             settlement_bounds_type="default", status=status, exchange_active=True,
                             trading_active=True, exchange_index=0, price_bands=(CENT,), event_key=EVENT,
                             cluster_key=CLUSTER, fee_scope="KXHIGHNY", fee_schedule_id="kalshi-quadratic-taker-v1",
                             book=g.BookState(f"book:{ticker}:{stamp}", stamp, yes_asks, yes_bids, no_asks, no_bids))


class DemoStrategy:
    """Synthetic: ENTRY signals become buys and EXIT signals become reduce-only IOC sells of what is sellable."""

    strategy_id = STRATEGY_ID
    strategy_version = "v1"
    model_hash = MODEL_HASH
    policy_hash = POLICY_HASH

    def __init__(self, strategy_id: str = STRATEGY_ID):
        self.strategy_id = strategy_id

    def propose(self, ctx: o.StrategyContext) -> tuple[o.Proposal, ...]:
        out = []
        for s in ctx.signals:
            side = m.Side(s.get("side"))
            limit = Decimal(s.get("limit"))
            qty = Decimal(s.get("qty"))
            ev = g.DecisionEvidence(evidence_id=f"sig:{s.signal_id}", strategy_id=self.strategy_id,
                                    strategy_version=self.strategy_version, model_version="m1",
                                    decided_at_utc=m.utc_text(ctx.now),
                                    sources=(g.SourceStamp(s.source_id, s.issued_at_utc),))
            base = dict(strategy_id=self.strategy_id, strategy_version=self.strategy_version, scope=ctx.scope,
                        market_ticker=s.market_ticker, side=side, limit_price=limit,
                        expires_at_utc=m.utc_text(ctx.now + timedelta(minutes=10)), price_grid=CENT,
                        quantity_grid=WHOLE, profile_version="kalshi-ordinary-v0",
                        risk_policy_version=POLICY.policy_id, fee_schedule_version="kalshi-quadratic-taker-v1",
                        evidence=(ev.evidence_id,))
            if s.get("kind") == "ENTRY":
                intent = m.OrderIntent(intent_key=f"{self.strategy_id}:{s.signal_id}", kind=m.IntentKind.ENTRY,
                                       action=m.Action.BUY, quantity=qty, max_total_cost=qty * (limit + Decimal(
                                           "0.04")), time_in_force=m.TimeInForce(s.get("tif")), reduce_only=False,
                                       **base)
            else:
                sellable = ctx.sellable.get((s.market_ticker, side))
                if not sellable or sellable <= 0:
                    continue
                qty = min(qty, sellable)
                intent = m.OrderIntent(intent_key=f"{self.strategy_id}:{s.signal_id}", kind=m.IntentKind.REDUCTION,
                                       action=m.Action.SELL, quantity=qty, max_total_cost=qty * Decimal("0.04"),
                                       time_in_force=m.TimeInForce.IMMEDIATE_OR_CANCEL, reduce_only=True, **base)
            out.append(o.Proposal(intent, ev))
        return tuple(out)


def signal(signal_id: str, ticker: str, *, at: datetime, kind: str = "ENTRY", side: str = "yes",
           limit: str = "0.45", qty: str = "2", tif: str = "immediate_or_cancel", strategy: str = STRATEGY_ID,
           valid: timedelta = timedelta(minutes=3), scope: m.AccountScope = SCOPE,
           source: str = "fixture-signals") -> o.Signal:
    return o.Signal(signal_id, source, strategy, scope.key(), ticker, m.utc_text(at), m.utc_text(at + valid),
                    (("kind", kind), ("side", side), ("limit", limit), ("qty", qty), ("tif", tif)))


def grant(**kw) -> ctl.AutomationGrant:
    """A TEST-issued automation grant. Source code never issues one."""
    base = dict(environment=m.Environment.FIXTURE, scope_key=SCOPE.key(), venue="kalshi", strategy_id=STRATEGY_ID,
                strategy_version="v1", model_hash=MODEL_HASH, policy_hash=POLICY_HASH,
                risk_policy_version=POLICY.policy_id, fee_schedule_version="kalshi-quadratic-taker-v1",
                profile_version="kalshi-ordinary-v0", universe=frozenset({"KXHIGHNY-*"}),
                allowed_kinds=frozenset({m.IntentKind.ENTRY, m.IntentKind.REDUCTION}),
                limits=ctl.GrantLimits(max_order_cost=Decimal("10"), max_event_exposure=Decimal("80"),
                                       max_total_exposure=Decimal("100"), max_daily_turnover=Decimal("300"),
                                       max_daily_loss=Decimal("30"), max_drawdown=Decimal("60")),
                issued_at_utc=m.utc_text(T0 - timedelta(hours=1)), expires_at_utc=m.utc_text(T0 + timedelta(days=1)),
                issuer_ref="TEST-FIXTURE-GRANT-not-an-owner-grant")
    base.update(kw)
    return ctl.AutomationGrant(**base)


def config(**kw) -> o.OrchestratorConfig:
    base = dict(scope=SCOPE, worker_id="worker-k", bounds=BOUNDS, lease_ttl=timedelta(minutes=5),
                snapshot_max_age=timedelta(minutes=2), cycle_interval=timedelta(seconds=60), risk=TEST_RISK,
                grants=(grant(),), external_cash_policy=ExternalCashPolicy.FULL_NOTIONAL,
                fixture_cash_basis=CashBasis.AVAILABLE_AFTER_VENUE_HOLDS)
    base.update(kw)
    return o.OrchestratorConfig(**base)


def build(journal: ExecutionJournal, adapter: VenueAdapter, *, feed: Feed | None = None, strategies=None,
          **config_kw) -> tuple[o.Orchestrator, Feed]:
    feed = feed or Feed(adapter)
    orch = o.Orchestrator(journal, config(**config_kw), send=adapter, feed=feed,
                          strategies=strategies if strategies is not None else (DemoStrategy(),),
                          clock=adapter.clock, sleep=adapter.clock.sleep)
    return orch, feed


def arm(orch: o.Orchestrator, mode: ctl.Mode, clock: Clock, *, grant_digest: str | None = None):
    """The operator's arm request: every open incident is named (acknowledged) explicitly."""
    if mode is ctl.Mode.BOUNDED_AUTO and grant_digest is None:
        grant_digest = grant().digest()
    return orch.request_arm(ctl.ArmRequest(mode, "owner", tuple(orch.state.open_incidents), m.utc_text(clock()),
                                           grant_digest))


def seed_books(adapter: VenueAdapter) -> None:
    """Two-sided books on every market: YES bids at 0.40-0.42 and NO bids at 0.54-0.56 (YES asks 0.44-0.46)."""
    for ticker in MARKETS:
        for p, q in (("0.40", "5"), ("0.41", "5"), ("0.42", "4")):
            adapter.venue.add_liquidity(ticker, m.Side.YES, p, q)
        for p, q in (("0.54", "6"), ("0.55", "5"), ("0.56", "4")):
            adapter.venue.add_liquidity(ticker, m.Side.NO, p, q)
    adapter.sync()


# ---------------------------------------------------------------- the out-of-process worker (process death)


def child_main(journal_path: str, state_path: str, at_iso: str, die: str, signal_json: str) -> None:
    """Boot a fresh orchestrator on the shared journal and venue state, reconcile, arm (the operator), queue one
    signal and run the cycle that sends it, dying at `die`. Exit 17/18 is the planned death; anything else fails."""
    adapter = VenueAdapter.load(state_path)
    adapter.clock.at = m.parse_utc_text(at_iso)
    adapter.state_path = state_path
    journal = ExecutionJournal.open(journal_path)
    orch, _ = build(journal, adapter)
    orch.run_cycle()
    outcome = arm(orch, ctl.Mode.BOUNDED_AUTO, adapter.clock)
    if not isinstance(outcome, ctl.ArmAccepted):
        print("ARM_REFUSED", outcome, file=sys.stderr)
        os._exit(4)
    adapter.clock.advance(1)
    admission = orch.submit_signal(o.Signal.from_dict(json.loads(signal_json)))
    if not admission.accepted:
        print("SIGNAL_REFUSED", admission, file=sys.stderr)
        os._exit(5)
    adapter.die = die
    report = orch.run_cycle()
    print("NO_DEATH", report.decisions, file=sys.stderr)
    os._exit(3)


CHILD = """
import sys
import types
sys.path[:0] = [{tests!r}, {src!r}]
import test_orchestrator_harness as h
h.child_main(*sys.argv[1:])
"""


def child_command(journal_path: Path, state_path: Path, at: datetime, die: str, sig: o.Signal) -> list[str]:
    here = Path(__file__).resolve().parent
    src = here.parents[1] / "src"
    return [sys.executable, "-c", CHILD.format(tests=str(here), src=str(src)), str(journal_path), str(state_path),
            m.utc_text(at), die, json.dumps(sig.to_dict())]
