"""Complete account reads and reconciliation (#160 package G). FIXTURE only; nothing is sent anywhere.

A fixture venue serves the documentation-shaped pages in `tests/fixtures/kalshi_exec/account/` by endpoint,
subaccount and cursor, and each test scripts its scenario on top of them.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from edge_lab.execution import account as a
from edge_lab.execution import conformance as c
from edge_lab.execution import kalshi_wire as w
from edge_lab.execution import model as m
from edge_lab.execution.kalshi_wire import Endpoint
from edge_lab.execution.reservations import CashBasis, ExternalOrigin

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "kalshi_exec" / "account"
UTC = timezone.utc
NOW = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
SCOPE = m.AccountScope(m.Environment.FIXTURE, "fixture-acct")
T_OPEN, T_SETTLED, T_ARCH = "KXHIGHNY-26OCT08-T60", "KXHIGHNY-26OCT01-T55", "KXHIGHNY-26AUG01-T50"
O1, O2, O3, O9 = ("a1b2c3d4-0000-4000-8000-00000000000%d" % i for i in (1, 2, 3, 9))
LOCAL_CID = "8c35ecb3-328f-4f52-8c7c-0f4b9862f8d1"
ALL = frozenset(a.AccountEndpoint)


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Reply:
    outcome: str
    status: int | None
    body: bytes | None


def ok(obj: dict) -> Reply:
    return Reply("OK", 200, json.dumps(obj).encode())


class Venue:
    """Serves pages per (endpoint, subaccount): `streams[(name, sub)]` maps a request cursor (None for the first page)
    to a page document. `single[name]` (per subaccount for balance) is one document. `hooks` run before each request
    with (venue, endpoint name, query) and may mutate anything, or return a Reply to serve instead."""

    def __init__(self, subaccounts=(0,)):
        self.streams: dict = {}
        self.single: dict = {"GET_USER_DATA_TIMESTAMP": load("user_data_timestamp.json"),
                             "GET_HISTORICAL_CUTOFF": load("historical_cutoff.json")}
        for n in subaccounts:
            self.add_subaccount(n)
        self.requests: list[tuple[str, dict]] = []
        self.wire: list[w.WireRequest] = []
        self.hooks: list = []

    def add_subaccount(self, n: int) -> None:
        self.single[("GET_BALANCE", n)] = load("balance.json")
        self.streams[("GET_POSITIONS", n)] = {None: load("positions_live_page1.json"),
                                              "positions-page-2": load("positions_live_page2_settled.json")}
        self.streams[("GET_HISTORICAL_POSITIONS", n)] = {None: load("positions_historical.json")}
        self.streams[("GET_ORDERS", n)] = {None: load("orders_live_page1.json"),
                                           "orders-page-2": load("orders_live_page2_manual.json")}
        self.streams[("GET_HISTORICAL_ORDERS", n)] = {None: load("orders_historical.json")}
        self.streams[("GET_FILLS", n)] = {None: load("fills_live_page1.json"), "fills-page-2": load("fills_live_page2.json")}
        self.streams[("GET_HISTORICAL_FILLS", n)] = {None: load("fills_historical.json")}
        self.streams[("GET_SETTLEMENTS", n)] = {None: load("settlements.json")}

    def count(self, name: str) -> int:
        return sum(1 for e, _ in self.requests if e == name)

    def serve(self, name: str, query: dict) -> Reply:
        self.requests.append((name, query))
        for hook in list(self.hooks):
            replaced = hook(self, name, query)
            if replaced is not None:
                return replaced
        if name in self.single:
            return ok(self.single[name])
        sub = int(query["subaccount"]) if "subaccount" in query else 0
        if (name, sub) in self.single:
            return ok(self.single[(name, sub)])
        pages = self.streams.get((name, sub))
        if pages is None:
            return Reply("REJECTED", 403, b'{"error":"subaccount not accessible"}')
        cursor = query.get("cursor")
        if cursor not in pages:
            return Reply("REJECTED", 400, b'{"error":"bad cursor"}')
        page = copy.deepcopy(pages[cursor])
        if name == "GET_POSITIONS" and query.get("settlement_status", "unsettled") == "unsettled":
            # The venue default (ACC-07): settled rows are left out unless asked for.
            page["market_positions"] = [p for p in page["market_positions"] if p["ticker"] != T_SETTLED]
        return ok(page)

    def __call__(self, request: w.WireRequest) -> Reply:
        assert isinstance(request, w.WireRequest) and not request.is_write()
        self.wire.append(request)
        return self.serve(request.endpoint.name, dict(request.query))


def plan(**kw) -> a.AccountReadPlan:
    base = dict(scope=SCOPE, subaccounts=(0,), endpoints=ALL, page_limit=100, max_pages=10, max_requests=500,
                deadline=NOW + timedelta(minutes=1))
    base.update(kw)
    return a.AccountReadPlan(**base)


def local(**kw) -> a.LocalOrder:
    base = dict(reservation_id="res-1", scope_key=SCOPE.key(), client_order_id=LOCAL_CID, provider_order_id=O1,
                market_ticker=T_OPEN, side=m.Side.YES, kind=m.IntentKind.ENTRY, limit_price=Decimal("0.56"),
                quantity=Decimal("10"), filled_quantity=Decimal("2.50"))
    base.update(kw)
    return a.LocalOrder(**base)


def run(venue=None, *, locals_=(local(),), clock=lambda: NOW, **plan_kw) -> a.AccountReconciliation:
    return a.reconcile_account(plan(**plan_kw), venue if venue is not None else Venue(), clock=clock,
                               local_orders=locals_)


def codes(result) -> set[str]:
    return {p.split(":")[0] for p in result.problems}


def page_of(venue, name, sub=0, cursor=None) -> dict:
    return venue.streams[(name, sub)][cursor]


# ---------------------------------------------------------------- the complete, quiet account


def test_a_quiet_fixture_account_reconciles_completely():
    venue = Venue()
    r = run(venue)
    assert r.status is a.ReconciliationStatus.COMPLETE, r.problems
    assert r.usable_for_new_risk and not r.problems
    (s,) = r.subaccounts
    assert s.stability is a.Stability.STABLE and s.samples == 2
    assert s.balance.balance_dollars == Decimal("100.0000")
    assert {p.ticker for p in s.positions} == {T_OPEN, T_SETTLED}
    assert {o.order_id for o in s.orders} == {O1, O2, O3, O9} and {o.order_id for o in s.open_orders} == {O1, O3}
    assert {f.fill_id for f in s.fills} == {"f-0001", "f-0002", "f-0003"}
    assert dict(s.fills_by_order) == {O1: Decimal("2.50"), O2: Decimal("3.00"), O9: Decimal("1.00")}
    assert s.matched_orders == {"res-1": O1} and s.unlisted_local == ()
    # The snapshot inputs: cash with an explicit basis (UNKNOWN: ACC-02), holdings per (ticker, side), the local
    # order attributed by reservation id, and the manual order as an external obligation.
    snap = s.snapshot
    assert snap.scope == SCOPE and snap.cash == Decimal("100.0000") and snap.cash_basis is CashBasis.UNKNOWN
    assert dict(snap.positions) == {(T_OPEN, m.Side.YES): Decimal("5.50")}
    (att,) = snap.attributed_open_orders
    assert (att.reservation_id, att.client_order_id, att.remaining_quantity, att.limit_price, att.unreflected_cash) \
        == ("res-1", LOCAL_CID, Decimal("7.50"), Decimal("0.56"), None)
    (ext,) = snap.external_open_orders
    assert (ext.order_ref, ext.origin, ext.market_ticker, ext.side, ext.action, ext.remaining_quantity,
            ext.unreflected_cash) == (O3, ExternalOrigin.UNKNOWN, T_OPEN, None, None, Decimal("4.00"), None)
    assert snap.observed_at == datetime(2026, 10, 7, 14, 59, 58, tzinfo=UTC)  # the venue's as_of, before our start
    # The manifest says exactly what was read.
    man = r.manifest
    assert man.requests == len(venue.requests) == 23
    assert all(man.coverage[(0, e)] for e in a.AccountEndpoint)
    assert [x.market_settled for x in man.cutoffs] == [datetime(2026, 9, 1, tzinfo=UTC)] * 2
    assert all(st.complete for st in man.streams)
    assert {(p.endpoint, p.tier, p.sample) for p in man.pages if p.page == 2} >= {
        ("GET_POSITIONS", a.Tier.LIVE, 0), ("GET_ORDERS", a.Tier.LIVE, 1), ("GET_FILLS", a.Tier.LIVE, 0)}
    assert any(o.startswith("EXTERNAL_ORDER") for o in r.observations)
    assert any(g.startswith("SETTLEMENT_DETAIL_ARCHIVED") for g in r.gaps)


def test_every_request_is_a_get_with_an_explicit_subaccount_and_nothing_is_written():
    venue = Venue()
    run(venue)
    assert venue.wire and all(not req.is_write() and req.endpoint in a.READ_ENDPOINTS for req in venue.wire)
    for req in venue.wire:
        if "subaccount" in req.endpoint.value.query_keys:
            assert dict(req.query)["subaccount"] == "0", req
    # The module's own guard refuses writes and implicit subaccounts before anything reaches `send`.
    with pytest.raises(a.AccountReadError, match="not a read"):
        a.check_read_request(w.build_cancel(SCOPE, O1, exchange_index=0))
    implicit = w.WireRequest(Endpoint.GET_FILLS, SCOPE, "/portfolio/fills", (("limit", "100"),))
    with pytest.raises(a.AccountReadError, match="must name its subaccount"):
        a.check_read_request(implicit)
    with pytest.raises(a.AccountReadError):
        a.check_read_request("GET /portfolio/balance")


def test_the_cash_basis_follows_the_conformance_pack():
    acc02 = next(f for f in c.PROFILE_FACTS if f.id == "ACC-02")
    assert acc02.support is c.Support.UNKNOWN  # if this changes, review a.CASH_BASIS in the same change
    assert a.CASH_BASIS is CashBasis.UNKNOWN


# ---------------------------------------------------------------- default-unsettled omission


def test_positions_are_read_with_settlement_status_all_so_settled_rows_are_not_omitted():
    venue = Venue()
    r = run(venue)
    positions = [q for e, q in venue.requests if e == "GET_POSITIONS"]
    assert positions and all(q["settlement_status"] == "all" for q in positions)
    assert T_SETTLED in {p.ticker for p in r.subaccounts[0].positions}
    # The venue default would have left the settled row out; such a read is refused before it is sent.
    default_read = w.WireRequest(Endpoint.GET_POSITIONS, SCOPE, "/portfolio/positions", (("subaccount", "0"),))
    assert T_SETTLED not in json.dumps(json.loads(venue(default_read).body))
    with pytest.raises(a.AccountReadError, match="settlement_status"):
        a.check_read_request(default_read)


# ---------------------------------------------------------------- archive movement mid-read


def _move_fill_to_history_after_first_historical_read(advance_cutoff: bool):
    def hook(venue, name, query):
        if name == "GET_HISTORICAL_FILLS" and venue.count(name) == 1:
            live = page_of(venue, "GET_FILLS")
            moved = live["fills"].pop(0)  # f-0002
            hist = page_of(venue, "GET_HISTORICAL_FILLS")
            if advance_cutoff:
                cutoff = venue.single["GET_HISTORICAL_CUTOFF"]
                cutoff["trades_created_ts"] = "2026-10-07T14:05:00Z"

            def later(v, n, q):  # after this historical read, the archive holds the moved fill
                if n == "GET_HISTORICAL_FILLS" and moved not in hist["fills"]:
                    hist["fills"].append(moved)

            venue.hooks.append(later)
        return None

    return hook


def test_a_fill_archived_mid_read_is_found_once_by_rereading_the_historical_tier():
    venue = Venue()
    venue.hooks.append(_move_fill_to_history_after_first_historical_read(advance_cutoff=True))
    r = run(venue)
    assert r.status is a.ReconciliationStatus.COMPLETE, r.problems
    s = r.subaccounts[0]
    assert [f.fill_id for f in s.fills].count("f-0002") == 1
    assert s.fills_by_order[O1] == Decimal("2.50")
    assert venue.count("GET_HISTORICAL_FILLS") == 2 and venue.count("GET_HISTORICAL_CUTOFF") == 3
    assert any(o.startswith("CUTOFF_ADVANCED_DURING_READ") for o in r.observations)
    assert s.samples == 3  # the live tier changed under the read, then held still


def test_a_record_that_leaves_the_live_tier_without_the_cutoff_moving_is_a_vanished_record():
    venue = Venue()
    venue.hooks.append(_move_fill_to_history_after_first_historical_read(advance_cutoff=False))
    r = run(venue)
    assert r.status is a.ReconciliationStatus.PARTIAL and "RECORD_VANISHED" in codes(r)
    s = r.subaccounts[0]
    assert s.fills is None and s.fills_by_order is None  # unknown, not a smaller total
    assert s.snapshot.cash is None


def test_a_cutoff_that_keeps_moving_or_goes_backwards_leaves_the_partition_unproven():
    venue = Venue()
    stamps = iter(["2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z"])

    def moving(v, name, q):
        if name == "GET_HISTORICAL_CUTOFF":
            ts = next(stamps)
            return ok({"market_settled_ts": ts, "trades_created_ts": ts, "orders_updated_ts": ts})
        return None

    venue.hooks.append(moving)
    r = run(venue)
    assert r.status is a.ReconciliationStatus.PARTIAL and "CUTOFF_MOVING" in codes(r)
    venue = Venue()
    back = iter(["2026-09-02T00:00:00Z", "2026-09-01T00:00:00Z"])
    venue.hooks.append(lambda v, n, q: ok({"market_settled_ts": (t := next(back)), "trades_created_ts": t,
                                           "orders_updated_ts": t}) if n == "GET_HISTORICAL_CUTOFF" else None)
    r = run(venue)
    assert "CUTOFF_REGRESSED" in codes(r) and r.status is a.ReconciliationStatus.PARTIAL


def test_a_historical_record_newer_than_the_cutoff_violates_the_partition():
    venue = Venue()
    page_of(venue, "GET_HISTORICAL_FILLS")["fills"][0]["created_time"] = "2026-09-15T00:00:00Z"
    r = run(venue)
    assert "TIER_PARTITION_VIOLATION" in codes(r) and r.status is a.ReconciliationStatus.PARTIAL


# ---------------------------------------------------------------- duplicates


def test_identical_duplicate_fills_collapse_across_pages_and_tiers():
    venue = Venue()
    page1 = page_of(venue, "GET_FILLS")
    page_of(venue, "GET_FILLS", cursor="fills-page-2")["fills"].append(copy.deepcopy(page1["fills"][0]))
    page1["fills"].append(copy.deepcopy(page_of(venue, "GET_HISTORICAL_FILLS")["fills"][0]))  # also archived
    r = run(venue)
    assert r.status is a.ReconciliationStatus.COMPLETE, r.problems
    s = r.subaccounts[0]
    assert sorted(f.fill_id for f in s.fills) == ["f-0001", "f-0002", "f-0003"]
    assert s.fills_by_order[O1] == Decimal("2.50")  # counted once, not twice
    assert any(o.startswith("DUPLICATES_COLLAPSED") for o in r.observations)
    assert any(o.startswith("TIER_DUPLICATES_COLLAPSED") for o in r.observations)


def test_a_conflicting_duplicate_fill_is_a_problem_and_fills_become_unknown():
    venue = Venue()
    twin = copy.deepcopy(page_of(venue, "GET_FILLS")["fills"][0])
    twin["count_fp"] = "9.00"
    page_of(venue, "GET_FILLS", cursor="fills-page-2")["fills"].append(twin)
    r = run(venue)
    assert r.status is a.ReconciliationStatus.PARTIAL and "CONFLICTING_DUPLICATE" in codes(r)
    s = r.subaccounts[0]
    assert s.fills is None and s.fills_by_order is None and s.snapshot.cash is None


def test_a_fill_that_differs_between_tiers_is_a_conflict():
    venue = Venue()
    twin = copy.deepcopy(page_of(venue, "GET_FILLS")["fills"][0])
    twin["fee_cost"] = "0.500000"
    page_of(venue, "GET_HISTORICAL_FILLS")["fills"].append(twin)
    r = run(venue)
    assert "CONFLICTING_DUPLICATE" in codes(r) and r.subaccounts[0].fills is None


def test_a_conflicting_duplicate_order_makes_open_orders_unknown():
    venue = Venue()
    twin = copy.deepcopy(page_of(venue, "GET_ORDERS")["orders"][0])
    twin["remaining_count_fp"] = "1.00"
    page_of(venue, "GET_ORDERS", cursor="orders-page-2")["orders"].append(twin)
    r = run(venue)
    s = r.subaccounts[0]
    assert "CONFLICTING_DUPLICATE" in codes(r)
    assert s.snapshot.external_open_orders is None and s.snapshot.attributed_open_orders == ()


# ---------------------------------------------------------------- pagination: loops, gaps, budgets


def test_a_cursor_that_points_back_is_a_loop_and_the_stream_is_incomplete():
    venue = Venue()
    page_of(venue, "GET_FILLS", cursor="fills-page-2")["cursor"] = "fills-page-2"
    r = run(venue)
    assert r.status is a.ReconciliationStatus.PARTIAL
    assert any(p.startswith("STREAM_INCOMPLETE") and "CURSOR_LOOP" in p for p in r.problems)
    assert r.subaccounts[0].fills is None
    venue = Venue()  # a two-page cycle: page 2 sends us back to page 1's cursor
    pages = venue.streams[("GET_FILLS", 0)]
    pages["fills-page-3"] = copy.deepcopy(pages["fills-page-2"])
    pages["fills-page-2"]["cursor"] = "fills-page-3"
    pages["fills-page-3"]["cursor"] = "fills-page-2"
    r = run(venue)
    assert any("CURSOR_LOOP" in p for p in r.problems) and venue.count("GET_FILLS") <= 10


def test_a_missing_page_is_never_an_empty_list():
    venue = Venue()

    def second_page_down(v, name, q):
        if name == "GET_ORDERS" and q.get("cursor") == "orders-page-2":
            return Reply("UNAVAILABLE", 503, None)
        return None

    venue.hooks.append(second_page_down)
    r = run(venue)
    s = r.subaccounts[0]
    assert r.status is a.ReconciliationStatus.PARTIAL
    assert any("ORDERS LIVE: NOT_OK: UNAVAILABLE 503" in p for p in r.problems)
    assert s.open_orders is None and s.orders is None
    assert s.snapshot.external_open_orders is None  # unknown: blocks new risk, never "no open orders"
    assert s.snapshot.cash is None and not r.manifest.coverage[(0, a.AccountEndpoint.ORDERS)]


def test_a_malformed_page_or_a_send_that_raises_is_incomplete():
    venue = Venue()
    del page_of(venue, "GET_ORDERS")["cursor"]  # orders pages must carry a cursor
    r = run(venue)
    assert any("MALFORMED_PAGE" in p for p in r.problems)
    venue = Venue()

    def boom(v, name, q):
        if name == "GET_BALANCE":
            raise RuntimeError("secret detail that must not leak")
        return None

    venue.hooks.append(boom)
    r = run(venue)
    assert any("SEND_RAISED: RuntimeError" in p for p in r.problems)
    assert not any("secret" in p for p in r.problems) and r.subaccounts[0].balance is None


def test_the_request_budget_bounds_the_read_and_the_rest_is_unknown():
    venue = Venue()
    r = run(venue, max_requests=5)
    assert len(venue.requests) == 5 and r.status is a.ReconciliationStatus.PARTIAL
    assert any("REQUEST_BUDGET_EXHAUSTED" in p for p in r.problems)
    s = r.subaccounts[0]
    assert s.orders is None and s.fills is None and s.snapshot.cash is None
    r = run(Venue(), max_requests=2)  # only the global reads: nothing about the subaccount is known
    assert r.status is a.ReconciliationStatus.FAILED and not r.usable_for_new_risk


def test_the_page_budget_and_the_deadline_bound_the_read():
    r = run(Venue(), max_pages=1)
    assert any("PAGE_BUDGET_EXHAUSTED" in p for p in r.problems)
    assert r.subaccounts[0].positions is None
    ticks = iter(range(1000))
    late = lambda: NOW + timedelta(seconds=next(ticks))  # noqa: E731 - one second per call
    venue = Venue()
    r = run(venue, clock=late, deadline=NOW + timedelta(seconds=6))
    assert any("DEADLINE_EXCEEDED" in p for p in r.problems) and len(venue.requests) < 23


# ---------------------------------------------------------------- stale updates


def test_stale_user_data_is_partial_and_positions_are_not_used():
    venue = Venue()
    venue.single["GET_USER_DATA_TIMESTAMP"] = {"as_of_time": "2026-10-07T14:50:00Z"}
    r = run(venue)
    assert "STALE_USER_DATA" in codes(r) and r.status is a.ReconciliationStatus.PARTIAL
    snap = r.subaccounts[0].snapshot
    assert snap.cash is None and snap.positions is None and snap.external_open_orders is None


def test_user_data_time_going_backwards_or_ahead_of_our_clock_is_refused():
    venue = Venue()
    stamps = iter(["2026-10-07T14:59:58Z", "2026-10-07T14:59:00Z"])
    venue.hooks.append(lambda v, n, q: ok({"as_of_time": next(stamps)}) if n == "GET_USER_DATA_TIMESTAMP" else None)
    assert "USER_DATA_AS_OF_REGRESSED" in codes(run(venue))
    venue = Venue()
    venue.single["GET_USER_DATA_TIMESTAMP"] = {"as_of_time": "2026-10-07T15:10:00Z"}
    assert "USER_DATA_AS_OF_IN_FUTURE" in codes(run(venue))
    venue = Venue()
    venue.hooks.append(lambda v, n, q: Reply("UNAVAILABLE", 503, None) if n == "GET_USER_DATA_TIMESTAMP" else None)
    assert "USER_DATA_AS_OF_UNAVAILABLE" in codes(run(venue))


def test_an_update_stamp_that_goes_backwards_between_samples_is_a_stale_update():
    venue = Venue()

    def older_balance(v, name, q):
        if name == "GET_BALANCE" and v.count(name) == 2:
            v.single[("GET_BALANCE", 0)]["updated_ts"] = 1791385100
        return None

    venue.hooks.append(older_balance)
    r = run(venue)
    assert "STALE_UPDATE" in codes(r) and r.status is a.ReconciliationStatus.PARTIAL
    venue = Venue()

    def older_position(v, name, q):
        if name == "GET_POSITIONS" and q.get("cursor") is None and v.count(name) == 3:
            page_of(v, "GET_POSITIONS")["market_positions"][0]["last_updated_ts"] = "2026-10-07T13:00:00Z"
        return None

    venue.hooks.append(older_position)
    assert "STALE_UPDATE" in codes(run(venue))


# ---------------------------------------------------------------- subaccounts


def test_an_inaccessible_subaccount_is_partial_never_empty():
    venue = Venue(subaccounts=(0,))  # the key cannot read subaccount 5 (SUB-02): every read is refused
    r = run(venue, subaccounts=(0, 5))
    assert r.status is a.ReconciliationStatus.PARTIAL
    s0, s5 = r.subaccounts
    assert s0.snapshot.positions is not None
    assert any("subaccount 5" in p and "ACCESS_DENIED" in p for p in r.problems)
    assert (s5.balance, s5.positions, s5.orders, s5.fills, s5.settlements) == (None,) * 5
    assert s5.snapshot.cash is None and s5.snapshot.positions is None and s5.snapshot.external_open_orders is None
    assert s5.scope == m.AccountScope(m.Environment.FIXTURE, "fixture-acct", 5)
    assert all(dict(req.query).get("subaccount") in ("0", "5") for req in venue.wire if req.query)


def test_a_record_of_another_subaccount_is_refused():
    venue = Venue()
    page_of(venue, "GET_FILLS", cursor="fills-page-2")["fills"][0]["subaccount_number"] = 7
    r = run(venue)
    assert any("UNKNOWN_SUBACCOUNT_RECORD" in p for p in r.problems) and r.subaccounts[0].fills is None


def test_subaccounts_outside_the_documented_range_or_repeated_are_refused():
    for bad in ((), (64,), (-1,), (0, 0), (True,), [0]):
        with pytest.raises(a.AccountReadError):
            plan(subaccounts=bad)
    with pytest.raises(a.AccountReadError, match="names no subaccount"):
        plan(scope=m.AccountScope(m.Environment.FIXTURE, "fixture-acct", 3))
    assert plan(subaccounts=(3, 0)).subaccounts == (0, 3)
    assert plan().scope_for(0).subaccount is None  # one canonical scope for the primary


def test_a_local_order_keyed_to_subaccount_zero_is_a_scope_alias():
    alias = m.AccountScope(m.Environment.FIXTURE, "fixture-acct", 0).key()
    r = run(locals_=(local(scope_key=alias),))
    assert "LOCAL_SCOPE_ALIAS" in codes(r)
    assert any(o.startswith("LOCAL_ORDERS_OUTSIDE_PLAN") and alias in o for o in r.observations)
    (ext_a, ext_b) = r.subaccounts[0].snapshot.external_open_orders  # the venue order is not attributed
    assert {ext_a.order_ref, ext_b.order_ref} == {O1, O3}


# ---------------------------------------------------------------- units


def test_a_cents_versus_dollars_mismatch_is_a_unit_error_and_cash_is_unknown():
    venue = Venue()
    venue.single[("GET_BALANCE", 0)]["balance_dollars"] = "1.0000"  # 10000 cents is 100 dollars, not 1
    r = run(venue)
    assert "UNIT_MISMATCH" in codes(r) and r.subaccounts[0].snapshot.cash is None
    venue = Venue()
    venue.single[("GET_BALANCE", 0)]["balance_dollars"] = "100.0099"  # within a cent: the same amount
    assert run(venue).status is a.ReconciliationStatus.COMPLETE


def test_cash_on_shards_that_were_not_enumerated_is_never_complete():
    venue = Venue()
    venue.single[("GET_BALANCE", 0)]["balance_breakdown"].append({"exchange_index": 1, "balance": "5.0000"})
    r = run(venue)
    assert "SHARDS_NOT_ENUMERATED" in codes(r) and r.subaccounts[0].snapshot.cash is None
    venue = Venue()
    del venue.single[("GET_BALANCE", 0)]["balance_breakdown"]
    assert "SHARDS_UNKNOWN" in codes(run(venue))


def test_a_settlement_revenue_off_by_a_factor_of_a_hundred_is_a_unit_error():
    venue = Venue()
    page_of(venue, "GET_SETTLEMENTS")["settlements"][0]["revenue"] = 1  # 1.00 winning contract pays 100 cents
    r = run(venue)
    assert any(p.startswith("UNIT_MISMATCH") and T_SETTLED in p for p in r.problems)


# ---------------------------------------------------------------- settlements


def test_missing_old_settlement_fields_are_a_documented_gap_not_zero():
    venue = Venue()
    venue.streams[("GET_SETTLEMENTS", 0)] = {None: load("settlements_missing_old_fields.json")}
    r = run(venue)
    assert r.status is a.ReconciliationStatus.COMPLETE, r.problems  # a gap is recorded, not a failure
    by_ticker = {s.ticker: s for s in r.subaccounts[0].settlements}
    old = by_ticker["KXHIGHNY-26SEP02-T58"]
    assert old.source is a.SettlementSource.VENUE_RECORD_INCOMPLETE
    assert old.revenue_cents is None and old.fee_cost is None and old.yes_total_cost is None
    assert old.yes_count == Decimal("2.00") and old.market_result == "yes"
    assert set(old.missing) == {"yes_total_cost_dollars", "no_total_cost_dollars", "revenue", "value", "fee_cost"}
    archived = by_ticker[T_ARCH]  # archived market: only its position history exists (ACC-12)
    assert archived.source is a.SettlementSource.HISTORICAL_POSITION_ONLY and archived.revenue_cents is None
    assert archived.realized_pnl == Decimal("-0.5000")
    assert any(g.startswith("SETTLEMENT_FIELDS_MISSING") for g in r.gaps)
    assert any(g.startswith("SETTLEMENT_DETAIL_UNAVAILABLE") and T_ARCH in g for g in r.gaps)


def test_a_settlement_field_that_is_present_but_malformed_is_not_tolerated():
    venue = Venue()
    page = load("settlements_missing_old_fields.json")
    page["settlements"][0]["revenue"] = "200"  # a string where integer cents are documented
    venue.streams[("GET_SETTLEMENTS", 0)] = {None: page}
    r = run(venue)
    assert any("MALFORMED_PAGE" in p for p in r.problems) and r.subaccounts[0].settlements is None
    page["settlements"][0].pop("ticker")
    page["settlements"][0]["revenue"] = 200
    assert any("cannot be identified" in p for p in run(venue).problems)


# ---------------------------------------------------------------- resampling


def test_live_reads_that_never_agree_are_unstable_after_a_bounded_number_of_samples():
    venue = Venue()

    def moving_balance(v, name, q):
        if name == "GET_BALANCE":
            bal = v.single[("GET_BALANCE", 0)]
            bal["balance"] += 1
            bal["balance_dollars"] = f"{Decimal(bal['balance']) / 100:.4f}"
            bal["updated_ts"] += 1
        return None

    venue.hooks.append(moving_balance)
    r = run(venue, max_resamples=2)
    s = r.subaccounts[0]
    assert s.stability is a.Stability.UNSTABLE and s.samples == 3 and venue.count("GET_BALANCE") == 3
    assert "UNSTABLE" in codes(r) and r.status is a.ReconciliationStatus.PARTIAL
    assert s.snapshot.cash is None and s.snapshot.positions is None and s.snapshot.external_open_orders is None


def test_a_change_during_the_read_is_resampled_until_two_samples_agree():
    venue = Venue()

    def one_fill(v, name, q):
        if name == "GET_FILLS" and q.get("cursor") is None and v.count(name) == 3:  # sample 1 starts
            extra = copy.deepcopy(page_of(v, "GET_FILLS", cursor="fills-page-2")["fills"][0])
            extra.update(fill_id="f-0004", trade_id="f-0004", created_time="2026-10-07T14:59:00Z")
            page_of(v, "GET_FILLS", cursor="fills-page-2")["fills"].append(extra)
        return None

    venue.hooks.append(one_fill)
    r = run(venue)
    s = r.subaccounts[0]
    assert r.status is a.ReconciliationStatus.COMPLETE and s.samples == 3
    assert "f-0004" in {f.fill_id for f in s.fills} and s.fills_by_order[O2] == Decimal("6.00")


# ---------------------------------------------------------------- attribution and external orders


def test_a_manual_order_is_an_external_obligation_that_consumes_capacity_under_policy():
    r = a.reconcile_account(plan(), Venue(), clock=lambda: NOW, local_orders=(),
                            external_cash_policy=a.ExternalCashPolicy.FULL_NOTIONAL)
    s = r.subaccounts[0]
    assert s.unlisted_local == () and s.attributed == ()
    refs = {e.order_ref: e for e in s.snapshot.external_open_orders}
    assert set(refs) == {O1, O3}  # with no local attempts, even the order we placed is external: never dropped
    assert refs[O3].unreflected_cash == Decimal("4.40")  # 4 contracts x 1.10 worst case
    assert refs[O1].unreflected_cash == Decimal("8.25")


@pytest.mark.parametrize("change,why", [
    (dict(limit_price=Decimal("0.55")), "YES price"),
    (dict(side=m.Side.NO, limit_price=Decimal("0.44")), "book side"),
    (dict(market_ticker="KXOTHER-26OCT08-T60"), "ticker"),
    (dict(client_order_id="00000000-0000-4000-8000-000000000000"), "client order id differs"),
    (dict(provider_order_id="ffffffff-0000-4000-8000-000000000000"), "acknowledged as venue order"),
])
def test_an_attribution_that_does_not_hold_keeps_the_order_external(change, why):
    r = run(locals_=(local(**change),))
    s = r.subaccounts[0]
    assert r.status is a.ReconciliationStatus.PARTIAL
    assert any(p.startswith("ATTRIBUTION_MISMATCH") and why in p for p in r.problems), r.problems
    assert s.snapshot.attributed_open_orders == ()
    assert O1 in {e.order_ref for e in s.snapshot.external_open_orders}


def test_two_venue_orders_for_one_local_attempt_are_not_both_attributed():
    venue = Venue()
    dup = copy.deepcopy(page_of(venue, "GET_ORDERS")["orders"][0])
    dup["order_id"] = "a1b2c3d4-0000-4000-8000-000000000005"
    page_of(venue, "GET_ORDERS", cursor="orders-page-2")["orders"].append(dup)
    r = run(venue, locals_=(local(provider_order_id=None),))  # unacknowledged: matched by client id only
    assert any(p.startswith("ATTRIBUTION_MISMATCH") and "already matched" in p for p in r.problems)
    snap = r.subaccounts[0].snapshot
    assert len(snap.attributed_open_orders) == 1 and len(snap.external_open_orders) == 2


def test_a_held_local_order_the_venue_does_not_list_is_reported():
    venue = Venue()
    page_of(venue, "GET_ORDERS")["orders"][0]["status"] = "canceled"
    r = run(venue)
    s = r.subaccounts[0]
    assert s.unlisted_local == ("res-1",) and s.matched_orders == {"res-1": O1}
    assert s.snapshot.attributed_open_orders == ()


# ---------------------------------------------------------------- the plan


def test_a_plan_is_bounded_and_explicit():
    for kw in (dict(page_limit=0), dict(page_limit=101), dict(max_pages=0), dict(max_requests=0),
               dict(max_resamples=0), dict(max_resamples=a.MAX_RESAMPLES + 1), dict(deadline=datetime(2026, 10, 7)),
               dict(endpoints=frozenset()), dict(endpoints={a.AccountEndpoint.BALANCE}),
               dict(max_data_lag=timedelta(0)), dict(page_limit=True)):
        with pytest.raises(a.AccountReadError):
            plan(**kw)
    with pytest.raises(a.AccountReadError, match="not authorized"):
        plan(scope=m.AccountScope(m.Environment.DEMO, "fixture-acct"))


def test_a_narrower_plan_is_partial_and_names_what_it_left_out():
    venue = Venue()
    r = run(venue, endpoints=frozenset({a.AccountEndpoint.BALANCE, a.AccountEndpoint.POSITIONS}))
    assert r.status is a.ReconciliationStatus.PARTIAL
    assert {p for p in r.problems if p.startswith("ENDPOINT_NOT_IN_PLAN")} == {
        "ENDPOINT_NOT_IN_PLAN: ORDERS", "ENDPOINT_NOT_IN_PLAN: FILLS", "ENDPOINT_NOT_IN_PLAN: SETTLEMENTS"}
    s = r.subaccounts[0]
    assert s.orders is None and s.snapshot.external_open_orders is None and s.snapshot.cash is None
    assert not any(e in ("GET_ORDERS", "GET_FILLS", "GET_SETTLEMENTS") for e, _ in venue.requests)


def test_local_orders_must_be_exact():
    with pytest.raises(m.ExactValueError):
        local(limit_price=0.56)
    with pytest.raises(ValueError):
        local(provider_order_id="")


# ---------------------------------------------------------------- into the reservation authority


def test_the_snapshot_inputs_record_into_the_reservation_authority(tmp_path):
    import test_journal_fixtures as f
    from edge_lab.execution.journal import ExecutionJournal
    from edge_lab.execution.reservations import ReceiptKind

    journal, token = f.ready(tmp_path / "g.execution.sqlite3")
    intent = f.entry()
    attempt = f.prepare(journal, intent, token)
    journal.mark_sent(attempt.attempt_id, now=NOW)
    journal.mark_acknowledged(attempt.attempt_id, provider_order_id=O1,
                              receipt_id=f.receipt(journal, "ack-1", ReceiptKind.ORDER_ACK, attempt.attempt_id),
                              now=NOW)
    locals_ = a.local_orders_from_journal(journal, [f.SCOPE])
    assert [(lo.reservation_id, lo.provider_order_id, lo.client_order_id) for lo in locals_] == [
        (attempt.reservation_id, O1, intent.client_order_id())]
    venue = Venue()
    venue.single["GET_USER_DATA_TIMESTAMP"] = {"as_of_time": "2026-10-07T15:00:01Z"}  # after the last snapshot
    ours = page_of(venue, "GET_ORDERS")["orders"][0]
    ours.update(client_order_id=intent.client_order_id(), ticker=f.MARKET, yes_price_dollars="0.4200",
                no_price_dollars="0.5800", fill_count_fp="0.00", remaining_count_fp="10.00")
    later = NOW + timedelta(seconds=2)
    r = a.reconcile_account(plan(), venue, clock=lambda: later, local_orders=locals_)
    assert r.status is a.ReconciliationStatus.COMPLETE, r.problems
    snap = r.subaccounts[0].snapshot.record(journal.reservations, 2, now=later)
    assert snap.consistent, snap.problems
    assert set(snap.attributed) == {attempt.reservation_id} and snap.cash_basis is CashBasis.UNKNOWN
    assert {e.order_ref for e in snap.external_orders} == {O3}
    assert journal.reservations.reservation(attempt.reservation_id).provider_held
    decision = journal.reservations.evaluate(f.entry("EXP-TEST:next"), later, snapshot_max_age=f.MAX_AGE)
    assert not decision.allowed and any("CASH_BASIS_UNKNOWN" in x for x in decision.reasons)
    journal.close()
    assert isinstance(journal, ExecutionJournal)


def test_a_partial_reconciliation_records_a_snapshot_that_allows_no_new_risk(tmp_path):
    import test_journal_fixtures as f

    journal, _ = f.ready(tmp_path / "p.execution.sqlite3")
    venue = Venue()
    venue.single["GET_USER_DATA_TIMESTAMP"] = {"as_of_time": "2026-10-07T15:00:01Z"}
    venue.hooks.append(lambda v, n, q: Reply("UNAVAILABLE", 503, None) if n == "GET_ORDERS" else None)
    later = NOW + timedelta(seconds=2)
    r = a.reconcile_account(plan(), venue, clock=lambda: later, local_orders=())
    assert r.status is a.ReconciliationStatus.PARTIAL
    snap = r.subaccounts[0].snapshot.record(journal.reservations, 2, now=later)
    assert snap.consistent  # nothing contradicts itself: the block below comes from what is unknown
    # Orders were unreadable, so the live sample could not be checked for agreement: positions are unproven too.
    assert snap.cash is None and snap.external_orders is None and snap.positions is None
    assert r.subaccounts[0].stability is a.Stability.NOT_CHECKED
    decision = journal.reservations.evaluate(f.entry(), later, snapshot_max_age=f.MAX_AGE)
    assert not decision.allowed
    assert any("EXTERNAL_ORDERS_UNKNOWN" in x for x in decision.reasons)
    assert any("CASH_UNKNOWN" in x for x in decision.reasons)
    journal.close()


# ---------------------------------------------------------------- through the real FIXTURE transport


def test_the_reply_contract_is_the_fixture_transports_result():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from edge_lab.execution import signer as sg
    from edge_lab.execution import transport as t

    venue = Venue()

    class Response:
        def __init__(self, reply, url):
            self.status, self._body, self._url = reply.status, reply.body or b"", url

        def read(self, n=-1):
            return self._body

        def geturl(self):
            return self._url

    def opener(request, timeout):
        parts = urlsplit(request.full_url)
        path = parts.path.removeprefix(c.API_PATH_PREFIX)
        (endpoint,) = [e for e in Endpoint if e.value.method.value == request.get_method() and e.value.matches(path)]
        assert request.get_method() == "GET" and request.data is None
        return Response(venue.serve(endpoint.name, dict(parse_qsl(parts.query))), request.full_url)

    signer = sg.Signer(key_id="fixture-key-id", private_key=ed25519.Ed25519PrivateKey.generate(),
                       environment=m.Environment.FIXTURE, account_ref="fixture-acct")
    transport = t.Transport(m.Environment.FIXTURE, signer, opener, lambda: NOW, sleep=lambda s: None,
                            budget=t.RateBudget(tier="prestige"))
    r = a.reconcile_account(plan(), lambda req: transport.send(req, priority=t.Priority.PROTECTIVE), clock=lambda: NOW,
                            local_orders=(local(),))
    assert r.status is a.ReconciliationStatus.COMPLETE, r.problems
    assert r.manifest.requests == 23
