"""#160 package I: the pre-send risk gate. Pure inputs, so each check is triggered by changing one thing."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from edge_lab.execution import model as m
from edge_lab.execution import risk_gate as g
from edge_lab.execution.risk_gate import (AccountProjection, BookLevel, BookState, Commitment, CommitmentOrigin,
                                          DecisionEvidence, GateLimits, HeldPosition, InventoryLine, LedgerEntry,
                                          LedgerKind, MarketState, OrderHistoryEntry, Reason as R, SourceStamp)
from edge_lab.execution_ticket import ObligationState as S, TicketLimits
from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1
from edge_lab.risk import RiskPolicy

UTC = timezone.utc
NOW = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
TICKER = "KXHIGHNY-26OCT08-B70"
OTHER = "KXHIGHNY-26OCT08-B72"
EVENT, CLUSTER = "KXHIGHNY-26OCT08", "nyc-weather"
CENT = m.Grid(step=Decimal("0.01"), minimum=Decimal("0.01"), maximum=Decimal("0.99"))
WHOLE = m.Grid(step=Decimal("1"), minimum=Decimal("1"), maximum=Decimal("1000"))
SCOPE = m.AccountScope(m.Environment.FIXTURE, "fixture-acct")
YES, NO = m.Side.YES, m.Side.NO

POLICY = RiskPolicy("gate-test-policy", reserve_floor=Decimal("20"), max_position_risk=Decimal("10"),
                    max_event_risk=Decimal("15"), max_cluster_risk=Decimal("20"), max_portfolio_risk=Decimal("50"),
                    daily_loss_limit=Decimal("10"), weekly_loss_limit=Decimal("20"), max_drawdown=Decimal("30"))
WIDE = replace(POLICY, daily_loss_limit=Decimal("40"), weekly_loss_limit=Decimal("40"), max_drawdown=Decimal("40"))
LIMITS = GateLimits(limits_id="gate-test-limits", risk_policy_id="gate-test-policy",
                    owner_approval_ref="test-fixture-only", max_quantity_per_order=Decimal("100"),
                    max_slippage=Decimal("0.02"), max_decision_age=timedelta(minutes=5),
                    max_source_age=timedelta(minutes=10), daily_new_risk=Decimal("25"),
                    max_strategy_risk=Decimal("30"))
GENESIS = (NOW - timedelta(days=60)).isoformat()
TICKET = TicketLimits(max_book_age=timedelta(seconds=30), max_order_state_age=timedelta(seconds=60),
                      max_orders_per_window=10, order_window=timedelta(hours=1), market_cooldown=timedelta(minutes=1))


def intent(**kw) -> m.OrderIntent:
    base = dict(intent_key="EXP-TEST:gate-0001", strategy_id="synthetic-demo", strategy_version="v1", scope=SCOPE,
                market_ticker=TICKER, kind=m.IntentKind.ENTRY, side=YES, action=m.Action.BUY,
                quantity=Decimal("10"), limit_price=Decimal("0.42"), time_in_force=m.TimeInForce.IMMEDIATE_OR_CANCEL,
                max_total_cost=Decimal("4.60"), expires_at_utc=(NOW + timedelta(minutes=10)).isoformat(),
                price_grid=CENT, quantity_grid=WHOLE, profile_version="kalshi-ordinary-v0",
                risk_policy_version="gate-test-policy", fee_schedule_version="kalshi-quadratic-taker-v1",
                reduce_only=False, evidence=("ev-1",))
    base.update(kw)
    return m.OrderIntent(**base)


def reduction(**kw) -> m.OrderIntent:
    base = dict(kind=m.IntentKind.REDUCTION, action=m.Action.SELL, reduce_only=True, quantity=Decimal("5"),
                limit_price=Decimal("0.40"), max_total_cost=Decimal("0.20"))
    base.update(kw)
    return intent(**base)


def lv(price: str, size: str) -> BookLevel:
    return BookLevel(Decimal(price), Decimal(size))


def book(**kw) -> BookState:
    base = dict(snapshot_id="book-1", as_of_utc=NOW.isoformat(), yes_asks=(lv("0.41", "4"), lv("0.42", "6")),
                yes_bids=(lv("0.40", "5"), lv("0.39", "20")), no_asks=(lv("0.60", "5"),), no_bids=(lv("0.57", "5"),))
    base.update(kw)
    return BookState(**base)


def market(**kw) -> MarketState:
    base = dict(state_id="mkt-1", ticker=TICKER, as_of_utc=NOW.isoformat(), market_type="binary",
                settlement_bounds_type="default", status="active", exchange_active=True, trading_active=True,
                exchange_index=0, price_bands=(CENT,), event_key=EVENT, cluster_key=CLUSTER, fee_scope="KXHIGHNY",
                fee_schedule_id="kalshi-quadratic-taker-v1", book=book())
    base.update(kw)
    return MarketState(**base)


def account(**kw) -> AccountProjection:
    base = dict(projection_id="proj-1", scope_key=SCOPE.key(), snapshot_revision=1, observed_at_utc=NOW.isoformat(),
                consistent=True, problems=(), cash=Decimal("100"), positions=(), commitments=(),
                external_orders_known=True, inventory=(), pnl_history=(),
                pnl_history_since_utc=GENESIS, order_history=(), order_history_since_utc=GENESIS,
                account_genesis_utc=GENESIS)
    base.update(kw)
    return AccountProjection(**base)


def evidence(**kw) -> DecisionEvidence:
    base = dict(evidence_id="ev-1", strategy_id="synthetic-demo", strategy_version="v1", model_version="m1",
                decided_at_utc=(NOW - timedelta(minutes=1)).isoformat(),
                sources=(SourceStamp("nws-obs", (NOW - timedelta(minutes=2)).isoformat()),))
    base.update(kw)
    return DecisionEvidence(**base)


def held(qty: str = "10", side=YES, ticker=TICKER, event=EVENT, cluster=CLUSTER) -> HeldPosition:
    return HeldPosition(ticker, side, Decimal(qty), event, cluster)


def local(cid: str, *, kind=m.IntentKind.ENTRY, ticker=OTHER, side=YES, cash="5", risk="5", event=EVENT,
          cluster=CLUSTER, state=S.OUTSTANDING, quarantined=False, strategy="synthetic-demo") -> Commitment:
    return Commitment(cid, CommitmentOrigin.LOCAL, state, kind, ticker, side,
                      m.Action.BUY if kind is m.IntentKind.ENTRY else m.Action.SELL, Decimal("10"),
                      None if cash is None else Decimal(cash), None if risk is None else Decimal(risk), event, cluster,
                      strategy, quarantined)


def external(cid: str, *, ticker=OTHER, side=YES, action=m.Action.BUY, qty="2", cash="0", event=EVENT,
             cluster=CLUSTER) -> Commitment:
    q = None if qty is None else Decimal(qty)
    return Commitment(cid, CommitmentOrigin.EXTERNAL, S.OUTSTANDING, None, ticker, side, action, q,
                      None if cash is None else Decimal(cash), q, event, cluster, None)


def pnl(amount: str, ago: timedelta, kind=LedgerKind.REALIZED_PNL, ref: str | None = None) -> LedgerEntry:
    return LedgerEntry(ref or f"l-{amount}-{ago.total_seconds()}", (NOW - ago).isoformat(), kind, Decimal(amount))


def order(ref: str, ago: timedelta, *, ticker=OTHER, kind=m.IntentKind.ENTRY, risk="0") -> OrderHistoryEntry:
    return OrderHistoryEntry(ref, ticker, kind, (NOW - ago).isoformat(), Decimal(risk))


def run(i=None, *, acct="default", mkt="default", policy=POLICY, limits=LIMITS, ticket=TICKET, ev="default", now=NOW):
    return g.evaluate(intent() if i is None else i, account=account() if acct == "default" else acct,
                      market=market() if mkt == "default" else mkt, policy=policy, limits=limits,
                      ticket_limits=ticket, evidence=evidence() if ev == "default" else ev, now=now)


def codes(decision) -> tuple[R, ...]:
    return decision.codes()


# ---------------------------------------------------------------- the clean case and its figures


def test_a_complete_current_order_within_every_limit_is_allowed():
    d = run()
    assert d.allowed and d.reasons == () and d.primary is None, d.reasons
    fee = KALSHI_QUADRATIC_TAKER_V1.taker_buy(10, Decimal("0.42")).total_cost  # 4.38
    assert d.fee_required == fee + Decimal("0.0101") * 10 == Decimal("4.481")
    assert d.candidate_risk == Decimal("4.60") and d.cash_required == Decimal("4.60")
    assert d.risk_capacity == Decimal("10")  # min(50, 100 - 20, daily 10, weekly 20, drawdown 30)
    assert dict(d.inputs) == {"intent": intent().digest(), "policy": "gate-test-policy", "limits": "gate-test-limits",
                              "evidence": "ev-1", "market": "mkt-1", "book": "book-1",
                              "fee_schedule": "kalshi-quadratic-taker-v1",
                              "fee_verification": "kalshi-kxhighny-fee-verification-2026-09-23", "projection": "proj-1",
                              "account_genesis": GENESIS, "pnl_history": account().history_digest("pnl"),
                              "order_history": account().history_digest("orders")}


def test_a_clean_reduction_is_allowed():
    d = run(reduction(), acct=account(positions=(held("10"),), inventory=(InventoryLine(TICKER, YES, Decimal("10")),)))
    assert d.allowed, d.reasons
    assert d.candidate_risk == 0
    # The largest fee at any sale price >= 0.40 is at 0.50: 0.07 x 5 x 0.25, plus the 0.0101 allowance per contract.
    assert d.fee_required == KALSHI_QUADRATIC_TAKER_V1.taker_buy(5, Decimal("0.5")).fee + Decimal("0.0505")


# ---------------------------------------------------------------- each code, triggered alone

ALONE = [
    ("limits not set", dict(limits=replace(LIMITS, owner_approval_ref=None)), R.LIMITS_NOT_SET_BY_OWNER),
    ("intent names another policy", dict(i=intent(risk_policy_version="risk-v0")), R.POLICY_VERSION_MISMATCH),
    ("limits name another policy", dict(limits=replace(LIMITS, risk_policy_id="other")), R.POLICY_VERSION_MISMATCH),
    ("no evidence", dict(ev=None), R.EVIDENCE_MISSING),
    ("other strategy version", dict(ev=evidence(strategy_version="v2")), R.EVIDENCE_MISMATCH),
    ("uncited evidence", dict(ev=evidence(evidence_id="ev-9")), R.EVIDENCE_MISMATCH),
    ("old decision", dict(ev=evidence(decided_at_utc=(NOW - timedelta(minutes=5, seconds=1)).isoformat())),
     R.DECISION_STALE),
    ("decision from the future", dict(ev=evidence(decided_at_utc=(NOW + timedelta(seconds=1)).isoformat())),
     R.DECISION_STALE),
    ("stale source", dict(ev=evidence(sources=(SourceStamp("nws", (NOW - timedelta(minutes=11)).isoformat()),))),
     R.SOURCE_STALE),
    ("no source evidence", dict(ev=evidence(sources=())), R.SOURCE_STALE),
    ("expired intent", dict(i=intent(expires_at_utc=NOW.isoformat())), R.INTENT_EXPIRED),
    ("unknown profile", dict(i=intent(profile_version="other-profile-v1")), R.PROFILE_UNSUPPORTED),
    ("quantity limit", dict(limits=replace(LIMITS, max_quantity_per_order=Decimal("9"))), R.QUANTITY_LIMIT),
    ("scalar market", dict(mkt=market(market_type="scalar")), R.MARKET_TYPE_UNSUPPORTED),
    ("unknown market type", dict(mkt=market(market_type="mystery")), R.MARKET_TYPE_UNSUPPORTED),
    ("floor settlement bounds", dict(mkt=market(settlement_bounds_type="floor")), R.MARKET_TYPE_UNSUPPORTED),
    ("stale market state", dict(mkt=market(as_of_utc=(NOW - timedelta(seconds=31)).isoformat())),
     R.MARKET_STATE_STALE),
    ("closed market", dict(mkt=market(status="closed")), R.MARKET_NOT_OPEN),
    ("trading state unknown", dict(mkt=market(trading_active=None)), R.EXCHANGE_NOT_OPEN),
    ("exchange paused", dict(mkt=market(exchange_active=False)), R.EXCHANGE_NOT_OPEN),
    ("off the market grid", dict(mkt=market(price_bands=(m.Grid(step=Decimal("0.05"), minimum=Decimal("0.05"),
                                                                maximum=Decimal("0.95")),))), R.PRICE_OFF_GRID),
    ("no book", dict(mkt=market(book=None)), R.BOOK_MISSING),
    ("side not observed", dict(mkt=market(book=book(yes_asks=None))), R.BOOK_MISSING),
    ("stale book", dict(mkt=market(book=book(as_of_utc=(NOW - timedelta(seconds=31)).isoformat()))), R.BOOK_STALE),
    ("thin book", dict(mkt=market(book=book(yes_asks=(lv("0.41", "4"), lv("0.42", "5"))))),
     R.BOOK_DEPTH_INSUFFICIENT),
    ("slippage", dict(mkt=market(book=book(yes_asks=(lv("0.39", "4"), lv("0.42", "6"))))), R.SLIPPAGE_LIMIT),
    ("market fee id differs", dict(mkt=market(fee_schedule_id="kalshi-quadratic-taker-v0")), R.FEE_SCHEDULE_MISMATCH),
    ("fee scope is another series", dict(mkt=market(fee_scope="KXHIGHCHI")), R.FEE_SCHEDULE_MISMATCH),
    ("short of fees", dict(i=intent(max_total_cost=Decimal("4.48"))), R.FEE_HEADROOM_INSUFFICIENT),
    ("no account", dict(acct=None), R.ACCOUNT_UNKNOWN),
    ("another account", dict(acct=account(scope_key="FIXTURE:other-acct:primary")), R.ACCOUNT_SCOPE_MISMATCH),
    ("stale snapshot", dict(acct=account(observed_at_utc=(NOW - timedelta(seconds=61)).isoformat())),
     R.ACCOUNT_SNAPSHOT_STALE),
    ("no snapshot", dict(acct=account(snapshot_revision=None, observed_at_utc=None)), R.ACCOUNT_SNAPSHOT_STALE),
    ("held item on this market names another event",
     dict(acct=account(positions=(held("1", event="WRONG-EVENT"),))), R.EXPOSURE_KEY_CONFLICT),
    ("P&L history shorter than the account", dict(acct=account(
        pnl_history_since_utc=(NOW - timedelta(minutes=1)).isoformat())), R.PNL_HISTORY_UNKNOWN),
    ("order history shorter than the account", dict(acct=account(
        order_history_since_utc=(NOW - timedelta(minutes=1)).isoformat())), R.ORDER_HISTORY_UNKNOWN),
    ("inconsistent snapshot", dict(acct=account(consistent=False, problems=("NEGATIVE_CASH: -1",))),
     R.RECONCILIATION_UNHEALTHY),
    ("external orders not listed", dict(acct=account(external_orders_known=False)), R.RECONCILIATION_UNHEALTHY),
    ("cash unknown", dict(acct=account(cash=None)), R.CASH_UNKNOWN),
    ("opposite side held", dict(acct=account(positions=(held("3", side=NO),))), R.FLIP_FORBIDDEN),
    ("pending opposite entry", dict(acct=account(commitments=(local("l1", ticker=TICKER, side=NO, risk="1",
                                                                    cash="1"),))), R.FLIP_FORBIDDEN),
    ("external order could flip", dict(acct=account(commitments=(external("e1", ticker=TICKER, side=YES,
                                                                          action=m.Action.SELL),))), R.FLIP_FORBIDDEN),
    ("external order on an unknown market", dict(acct=account(commitments=(external("e1", ticker=None, side=None,
                                                                                   action=None),))),
     R.FLIP_FORBIDDEN),
    ("exposure unknown", dict(acct=account(commitments=(external("e1", qty=None),))), R.EXPOSURE_UNKNOWN),
    ("candidate event unknown", dict(mkt=market(event_key=None)), R.EXPOSURE_UNKNOWN),
    ("held positions and pending order over the market limit",
     dict(policy=WIDE, acct=account(positions=(held("6"),))), R.EXPOSURE_PER_MARKET),
    ("strategy", dict(limits=replace(LIMITS, max_strategy_risk=Decimal("4"))), R.EXPOSURE_PER_STRATEGY),
    ("reserve floor", dict(acct=account(cash=Decimal("19.99"))), R.RESERVE_FLOOR),
    ("cash committed elsewhere", dict(acct=account(commitments=(
        local("l1", kind=m.IntentKind.REDUCTION, cash="75.41", risk="0"),))), R.CASH_CAPACITY_INSUFFICIENT),
    ("P&L history unknown", dict(acct=account(pnl_history=None)), R.PNL_HISTORY_UNKNOWN),
    ("P&L from the future", dict(acct=account(pnl_history=(pnl("1", -timedelta(seconds=1)),))),
     R.PNL_HISTORY_UNKNOWN),
    ("P&L before inception", dict(acct=account(pnl_history=(pnl("1", timedelta(days=61)),))), R.PNL_HISTORY_UNKNOWN),
    ("daily loss", dict(acct=account(pnl_history=(pnl("-10.01", timedelta(hours=1)),))), R.DAILY_LOSS_LIMIT),
    ("weekly loss", dict(acct=account(pnl_history=(pnl("-20.5", timedelta(days=3)),))), R.WEEKLY_LOSS_LIMIT),
    ("drawdown", dict(acct=account(pnl_history=(pnl("50", timedelta(days=30)), pnl("-31", timedelta(days=10))))),
     R.MAX_DRAWDOWN),
    ("loss headroom", dict(acct=account(pnl_history=(pnl("-6", timedelta(hours=1)),))), R.RISK_CAPACITY_INSUFFICIENT),
    ("daily new risk", dict(acct=account(order_history=(order("o1", timedelta(hours=23), risk="20.41"),))),
     R.DAILY_NEW_RISK_LIMIT),
    ("order history unknown", dict(acct=account(order_history=None)), R.ORDER_HISTORY_UNKNOWN),
    ("order time unknown", dict(acct=account(order_history=(OrderHistoryEntry("o1", OTHER, m.IntentKind.ENTRY, None,
                                                                              Decimal(0)),))), R.ORDER_HISTORY_UNKNOWN),
    ("trade count", dict(acct=account(order_history=tuple(order(f"o{n}", timedelta(minutes=5 + n))
                                                          for n in range(10)))), R.TRADE_COUNT_LIMIT),
    ("cooldown", dict(acct=account(order_history=(order("o1", timedelta(seconds=59), ticker=TICKER),))),
     R.COOLDOWN_ACTIVE),
]


@pytest.mark.parametrize("label,change,code", ALONE, ids=[a[0] for a in ALONE])
def test_each_check_fails_alone_with_its_own_code(label, change, code):
    d = run(**change)
    assert not d.allowed
    assert codes(d) == (code,), (label, d.reasons)
    assert d.primary.code is code and d.primary.detail


def test_every_reachable_code_is_exercised():
    """Codes not in ALONE are exercised by a named test below (they cannot fail alone, or need revalidate)."""
    elsewhere = {R.APPROVAL_INVALID, R.APPROVAL_DIGEST_MISMATCH, R.APPROVAL_SCOPE_MISMATCH, R.APPROVAL_FROM_FUTURE,
                 R.APPROVAL_EXPIRED, R.POLICY_INVALID, R.ENVIRONMENT_NOT_AUTHORIZED, R.QUANTITY_OFF_GRID,
                 R.REDUCE_ONLY_REQUIRES_IOC, R.MARKET_UNKNOWN, R.FEE_SCHEDULE_UNSUPPORTED, R.FEE_SCHEDULE_UNVERIFIED,
                 R.POSITIONS_UNKNOWN, R.INVENTORY_UNKNOWN, R.INVENTORY_INSUFFICIENT, R.EXPOSURE_PER_ORDER,
                 R.EXPOSURE_PER_EVENT, R.EXPOSURE_PER_CLUSTER, R.EXPOSURE_ACCOUNT}
    # Not reachable through valid inputs: every documented time in force is supported (ORD-08), and the bounded,
    # exact inputs keep every sum exact.
    unreachable = {R.TIF_UNSUPPORTED, R.ARITHMETIC_NOT_EXACT}
    assert {c for _, _, c in ALONE} | elsewhere | unreachable == set(R)


# ---------------------------------------------------------------- boundaries: exact equality is allowed


@pytest.mark.parametrize("change", [
    dict(i=intent(max_total_cost=Decimal("4.481"))),  # exactly the fee requirement
    dict(limits=replace(LIMITS, max_quantity_per_order=Decimal("10"))),
    dict(ev=evidence(decided_at_utc=(NOW - timedelta(minutes=5)).isoformat())),
    dict(ev=evidence(sources=(SourceStamp("nws", (NOW - timedelta(minutes=10)).isoformat()),))),
    dict(mkt=market(as_of_utc=(NOW - timedelta(seconds=30)).isoformat())),
    dict(mkt=market(book=book(as_of_utc=(NOW - timedelta(seconds=30)).isoformat()))),
    dict(mkt=market(book=book(yes_asks=(lv("0.40", "4"), lv("0.42", "6"))))),  # slippage exactly 0.02
    dict(acct=account(observed_at_utc=(NOW - timedelta(seconds=60)).isoformat())),
    dict(acct=account(cash=Decimal("24.60"))),  # cash above the floor exactly covers the order
    dict(policy=replace(POLICY, max_position_risk=Decimal("4.60"))),  # per order and per market exactly at the cap
    dict(limits=replace(LIMITS, max_strategy_risk=Decimal("4.60"))),
    dict(acct=account(pnl_history=(pnl("-5.40", timedelta(hours=1)),))),  # capacity 10 - 5.40 = 4.60 exactly
    dict(acct=account(order_history=(order("o1", timedelta(hours=23), risk="20.40"),))),  # 20.40 + 4.60 = 25
    dict(acct=account(order_history=(order("o1", timedelta(hours=24), risk="1000"),))),  # 24 h old: out of the window
    dict(acct=account(order_history=tuple(order(f"o{n}", timedelta(minutes=5 + n)) for n in range(9))
                      + (order("o9", timedelta(hours=1)),))),  # exactly the window old has left it
    dict(acct=account(order_history=(order("o1", timedelta(minutes=1), ticker=TICKER),))),  # exactly the cooldown
])
def test_exact_equality_at_a_documented_boundary_is_allowed(change):
    d = run(**change)
    assert d.allowed, d.reasons


def test_daily_loss_exactly_at_the_limit_is_not_a_breach_but_leaves_no_headroom():
    d = run(acct=account(pnl_history=(pnl("-10", timedelta(hours=1)),)))
    assert codes(d) == (R.RISK_CAPACITY_INSUFFICIENT,)


def test_depth_exactly_the_quantity_is_enough_and_one_hundredth_less_is_not():
    assert run(mkt=market(book=book(yes_asks=(lv("0.41", "4"), lv("0.42", "6"))))).allowed
    thin = run(mkt=market(book=book(yes_asks=(lv("0.41", "4"), lv("0.42", "5.99")))))
    assert codes(thin) == (R.BOOK_DEPTH_INSUFFICIENT,)


def test_a_resting_order_needs_no_depth_and_an_empty_side_has_no_slippage():
    gtc = intent(time_in_force=m.TimeInForce.GOOD_TILL_CANCELED)
    assert run(gtc, mkt=market(book=book(yes_asks=()))).allowed
    assert codes(run(mkt=market(book=book(yes_asks=())))) == (R.BOOK_DEPTH_INSUFFICIENT,)  # IOC into nothing


# ---------------------------------------------------------------- codes that come with others, or need setup


def test_market_unknown_fails_closed_on_everything_that_needs_it():
    d = run(mkt=None)
    assert codes(d) == (R.MARKET_UNKNOWN, R.EXPOSURE_UNKNOWN)
    d = run(mkt=market(ticker=OTHER))
    assert d.primary.code is R.MARKET_UNKNOWN and not d.allowed


def test_unsupported_fee_schedule_is_rejected_never_assumed():
    """KXNFLGAME is on Kalshi's non-standard list: no schedule prices it."""
    t = "KXNFLGAME-26OCT12KCBUF-KC"
    d = run(intent(market_ticker=t), mkt=market(ticker=t, fee_scope="KXNFLGAME"))
    assert codes(d) == (R.FEE_SCHEDULE_UNSUPPORTED,) and "unsupported" in d.primary.detail
    assert d.fee_required is None
    d = run(intent(market_ticker=t), mkt=market(ticker=t, fee_scope=None))  # unknown series
    assert codes(d) == (R.FEE_SCHEDULE_UNSUPPORTED,)


def test_an_unverified_schedule_is_rejected():
    """KXHIGHCHI routes to the general schedule, but no verification record covers it."""
    t = "KXHIGHCHI-26OCT08-B70"
    d = run(intent(market_ticker=t), mkt=market(ticker=t, fee_scope="KXHIGHCHI"))
    assert codes(d) == (R.FEE_SCHEDULE_UNVERIFIED,)
    # The KXHIGHNY record stops supporting claims after its re-check date: the same order is then refused.
    late = NOW + timedelta(days=17)
    stamp = late.isoformat()
    d = run(intent(expires_at_utc=(late + timedelta(minutes=5)).isoformat()),
            mkt=market(as_of_utc=stamp, book=book(as_of_utc=stamp)),
            acct=account(observed_at_utc=stamp), ev=evidence(decided_at_utc=stamp, sources=(SourceStamp("n", stamp),)),
            now=late)
    assert codes(d) == (R.FEE_SCHEDULE_UNVERIFIED,), d.reasons


def test_a_no_side_entry_uses_the_no_book_and_the_yes_price_grid():
    no = intent(side=NO, quantity=Decimal("5"), limit_price=Decimal("0.60"), max_total_cost=Decimal("3.20"))
    d = run(no)
    assert d.allowed, d.reasons
    assert d.fee_required == KALSHI_QUADRATIC_TAKER_V1.taker_buy(5, Decimal("0.60")).total_cost + Decimal("0.0505")
    assert codes(run(no, acct=account(positions=(held("1", side=YES),)))) == (R.FLIP_FORBIDDEN,)
    # A NO price of 0.585 is a YES price of 0.415: off the market's one-cent YES grid.
    half = m.Grid(step=Decimal("0.005"), minimum=Decimal("0.005"), maximum=Decimal("0.995"))
    off = replace(no, limit_price=Decimal("0.585"), price_grid=half)
    d = run(off, mkt=market(book=book(no_asks=(lv("0.585", "5"),))))
    assert codes(d) == (R.PRICE_OFF_GRID,) and "0.415" in d.primary.detail


def test_a_price_the_fee_schedule_cannot_price_is_refused_not_raised():
    fine = m.Grid(step=Decimal("0.00001"), minimum=Decimal("0.00001"), maximum=Decimal("0.99999"))
    d = run(intent(limit_price=Decimal("0.42005"), price_grid=fine), mkt=market(price_bands=(fine,)))
    assert codes(d) == (R.FEE_SCHEDULE_UNSUPPORTED,) and "cannot price" in d.primary.detail


def test_fractional_quantity_is_off_the_grid_or_unpriced():
    fine = m.Grid(step=Decimal("0.001"), minimum=Decimal("0.001"), maximum=Decimal("1000"))
    d = run(intent(quantity=Decimal("9.995"), quantity_grid=fine))
    assert d.primary.code is R.QUANTITY_OFF_GRID and R.FEE_SCHEDULE_UNSUPPORTED in codes(d)
    hundredths = m.Grid(step=Decimal("0.01"), minimum=Decimal("0.01"), maximum=Decimal("1000"))
    d = run(intent(quantity=Decimal("9.99"), quantity_grid=hundredths))  # on the venue grid, but not whole contracts
    assert codes(d) == (R.FEE_SCHEDULE_UNSUPPORTED,)


def test_reduce_only_requires_ioc():
    d = run(reduction(time_in_force=m.TimeInForce.GOOD_TILL_CANCELED),
            acct=account(positions=(held("10"),), inventory=(InventoryLine(TICKER, YES, Decimal("10")),)))
    assert codes(d) == (R.REDUCE_ONLY_REQUIRES_IOC,)


def test_an_unauthorized_environment_is_refused_whatever_the_account_says():
    demo = m.AccountScope(m.Environment.DEMO, "fixture-acct")
    d = run(intent(scope=demo), acct=account(scope_key=demo.key()))
    assert codes(d) == (R.ENVIRONMENT_NOT_AUTHORIZED,)


def test_positions_unknown_blocks_both_kinds():
    assert codes(run(acct=account(positions=None))) == (R.POSITIONS_UNKNOWN, R.EXPOSURE_UNKNOWN)
    assert codes(run(reduction(), acct=account(positions=None))) == (R.POSITIONS_UNKNOWN,)


def test_quarantined_or_unknown_commitments_mean_no_new_risk():
    q = local("l1", quarantined=True, cash=None, risk=None, state=S.UNKNOWN)
    d = run(acct=account(commitments=(q,)))
    assert d.primary.code is R.RECONCILIATION_UNHEALTHY
    assert {R.EXPOSURE_UNKNOWN, R.CASH_CAPACITY_INSUFFICIENT} <= set(codes(d))
    unknown = local("l2", state=S.UNKNOWN)  # an answer was lost, worst case still known
    assert codes(run(acct=account(commitments=(unknown,)))) == (R.RECONCILIATION_UNHEALTHY,)
    # A reduction is blocked too: inventory and cash cannot be trusted.
    d = run(reduction(), acct=account(positions=(held("10"),), commitments=(unknown,),
                                      inventory=(InventoryLine(TICKER, YES, Decimal("10")),)))
    assert codes(d) == (R.RECONCILIATION_UNHEALTHY,)


def test_inventory_rules_for_a_reduction():
    def red(available, qty="5"):
        lines = () if available == "absent" else (InventoryLine(TICKER, YES, None if available is None
                                                                else Decimal(available)),)
        return run(reduction(quantity=Decimal(qty)), acct=account(positions=(held("10"),), inventory=lines))

    assert red("5").allowed  # exactly the inventory
    assert codes(red("4.99", qty="5")) == (R.INVENTORY_INSUFFICIENT,)
    assert codes(red(None)) == (R.INVENTORY_UNKNOWN,)
    assert codes(red("absent")) == (R.INVENTORY_INSUFFICIENT,)  # a complete listing without it: nothing held


def test_a_reduction_is_not_held_to_exposure_or_loss_limits():
    """Cutting risk is never blocked by the limits on taking it."""
    acct = account(positions=(held("45"),), inventory=(InventoryLine(TICKER, YES, Decimal("45")),),
                   pnl_history=(pnl("-35", timedelta(hours=1)),))
    assert run(reduction(), acct=acct).allowed
    assert {R.EXPOSURE_PER_MARKET, R.DAILY_LOSS_LIMIT} <= set(codes(run(acct=acct)))


def test_per_order_cap_implies_the_market_cap():
    d = run(policy=replace(POLICY, max_position_risk=Decimal("4.59")))
    assert codes(d) == (R.EXPOSURE_PER_ORDER, R.EXPOSURE_PER_MARKET)


def test_correlated_simultaneous_commitments_count_toward_the_event_limit():
    """Two pending entries on other markets of the same event bind at once with this order: 5.5 + 5.5 + 4.6."""
    pending = (local("l1", cash="5.5", risk="5.5"), local("l2", ticker="KXHIGHNY-26OCT08-B74", cash="5.5",
                                                          risk="5.5"))
    d = run(policy=WIDE, acct=account(commitments=pending))
    assert codes(d) == (R.EXPOSURE_PER_EVENT,) and "15.60" in d.primary.detail
    # The same commitments on another event are within the limit.
    elsewhere = tuple(replace(c, event_key="KXHIGHNY-26OCT09") for c in pending)
    assert run(policy=WIDE, acct=account(commitments=elsewhere)).allowed


def test_cluster_limit_counts_other_events_in_the_cluster():
    pending = (local("l1", cash="8", risk="8", event="E1"), local("l2", cash="8", risk="8", event="E2"))
    d = run(policy=WIDE, acct=account(commitments=pending))
    assert codes(d) == (R.EXPOSURE_PER_CLUSTER,)


def test_an_exposure_with_an_unknown_event_counts_toward_the_candidates_event():
    unknown_event = (local("l1", cash="5.5", risk="5.5", event=None), local("l2", cash="5.5", risk="5.5", event=None,
                                                                             ticker="KXHIGHNY-26OCT09-B70"))
    d = run(policy=WIDE, acct=account(commitments=tuple(replace(c, cluster_key="other") for c in unknown_event)))
    assert codes(d) == (R.EXPOSURE_PER_EVENT,)


def test_account_exposure():
    far = tuple(HeldPosition(f"KXBTC-26OCT08-T{n}", YES, Decimal("9.5"), f"E{n}", f"C{n}", "other-strategy")
                for n in range(5))
    d = run(policy=WIDE, acct=account(positions=far))
    assert codes(d) == (R.EXPOSURE_ACCOUNT, R.RISK_CAPACITY_INSUFFICIENT)  # capacity includes the portfolio cap


def test_held_positions_count_one_dollar_per_contract_not_their_purchase_cost():
    """Six contracts bought at 0.05 still put up to $6 at risk from here: 6 + 4.60 > 10."""
    d = run(policy=WIDE, acct=account(positions=(held("6"),)))
    assert codes(d) == (R.EXPOSURE_PER_MARKET,) and "10.60" in d.primary.detail


def test_an_existing_breach_elsewhere_blocks_new_risk_as_risk_assess_does():
    over = held("16", ticker="KXBTC-26OCT08-T1", event="E-btc", cluster="C-btc")
    d = run(policy=WIDE, acct=account(positions=(over,)))
    assert set(codes(d)) == {R.EXPOSURE_PER_MARKET, R.EXPOSURE_PER_EVENT}
    assert "already breaches" in dict((v.code, v.detail) for v in d.reasons)[R.EXPOSURE_PER_EVENT]


# ---------------------------------------------------------------- losses: deposits are not P&L


def test_deposits_do_not_reset_or_offset_a_loss_limit():
    loss = pnl("-10.01", timedelta(hours=1))
    before = run(acct=account(pnl_history=(loss,)))
    after = run(acct=account(pnl_history=(loss, pnl("1000", timedelta(minutes=30), LedgerKind.DEPOSIT, "dep-1")),
                             cash=Decimal("1100")))
    assert codes(before) == codes(after) == (R.DAILY_LOSS_LIMIT,)


def test_a_withdrawal_is_not_a_loss_and_a_deposit_does_not_lift_the_drawdown_peak():
    assert run(acct=account(pnl_history=(pnl("80", timedelta(hours=2), LedgerKind.WITHDRAWAL, "wd-1"),))).allowed
    dd = (pnl("50", timedelta(days=30)), pnl("-31", timedelta(days=10)))
    d = run(acct=account(pnl_history=dd + (pnl("500", timedelta(days=5), LedgerKind.DEPOSIT, "dep-1"),)))
    assert codes(d) == (R.MAX_DRAWDOWN,)


def test_a_win_inside_the_window_offsets_a_loss_as_risk_assess_defines_net_realized_loss():
    d = run(acct=account(pnl_history=(pnl("-10.01", timedelta(hours=2)), pnl("6", timedelta(hours=1)))))
    assert d.allowed and d.risk_capacity == Decimal("5.99")  # net 4.01 lost in the trailing 24 h: 10 - 4.01


# ---------------------------------------------------------------- restart and ordering


def test_counts_come_from_the_persisted_history_not_process_memory():
    history = tuple(order(f"o{n}", timedelta(minutes=5 + n)) for n in range(9))
    first = run(acct=account(order_history=history))
    assert first.allowed
    # "Restart": nothing is remembered between calls; the tenth order is only visible through the history.
    again = run(acct=account(order_history=history))
    assert again == first
    after_send = run(acct=account(order_history=history + (order("o-sent", timedelta(seconds=1), ticker=OTHER),)))
    assert codes(after_send) == (R.TRADE_COUNT_LIMIT,)
    risk = run(acct=account(order_history=(order("o-big", timedelta(hours=2), risk="21"),)))
    assert codes(risk) == (R.DAILY_NEW_RISK_LIMIT,)


def test_reasons_follow_declaration_order_and_the_first_is_primary():
    d = run(intent(max_total_cost=Decimal("4.48")), mkt=market(status="closed", book=book(yes_asks=None)),
            acct=account(cash=None, order_history=None), ev=None, limits=replace(LIMITS, owner_approval_ref=None))
    order_ = tuple(R)
    assert list(codes(d)) == sorted(codes(d), key=order_.index)
    assert codes(d) == (R.LIMITS_NOT_SET_BY_OWNER, R.EVIDENCE_MISSING, R.MARKET_NOT_OPEN, R.BOOK_MISSING,
                        R.FEE_HEADROOM_INSUFFICIENT, R.CASH_UNKNOWN, R.ORDER_HISTORY_UNKNOWN)
    assert d.primary.code is R.LIMITS_NOT_SET_BY_OWNER
    assert len(set(codes(d))) == len(codes(d))  # one entry per code


def test_placeholder_limits_block_every_order():
    for i in (intent(risk_policy_version=g.PLACEHOLDER_ID), reduction(risk_policy_version=g.PLACEHOLDER_ID)):
        d = g.evaluate(i, account=account(positions=(held("10"),),
                                          inventory=(InventoryLine(TICKER, YES, Decimal("10")),)),
                       market=market(), policy=g.PLACEHOLDER_POLICY, limits=g.PLACEHOLDER_LIMITS,
                       ticket_limits=g.PLACEHOLDER_TICKET_LIMITS, evidence=evidence(), now=NOW)
        assert not d.allowed and d.primary.code is R.LIMITS_NOT_SET_BY_OWNER
        assert R.QUANTITY_LIMIT in codes(d) and R.TRADE_COUNT_LIMIT in codes(d)
    # Zero caps alone, with an owner reference, still allow nothing.
    zero = replace(g.PLACEHOLDER_LIMITS, owner_approval_ref="x")
    d = g.evaluate(intent(risk_policy_version=g.PLACEHOLDER_ID), account=account(), market=market(),
                   policy=g.PLACEHOLDER_POLICY, limits=zero, ticket_limits=g.PLACEHOLDER_TICKET_LIMITS,
                   evidence=evidence(), now=NOW)
    assert not d.allowed and R.EXPOSURE_PER_ORDER in codes(d)


# ---------------------------------------------------------------- malformed reused policy, and construction


@pytest.mark.parametrize("bad", [0.5, True, Decimal("-1"), Decimal("Infinity")])
def test_a_reused_policy_with_a_float_bool_or_non_finite_value_is_refused(bad):
    try:
        policy = replace(POLICY, max_event_risk=bad)
    except Exception:  # the legacy RiskPolicy refuses some values itself (negative)
        return
    d = run(policy=policy)
    assert codes(d) == (R.POLICY_INVALID,) and "max_event_risk" in d.primary.detail


def test_a_nan_policy_value_cannot_even_be_built():
    with pytest.raises(Exception):
        replace(POLICY, max_event_risk=Decimal("NaN"))


def test_malformed_ticket_limits_are_refused():
    d = run(ticket=replace(TICKET, max_orders_per_window=True))
    assert codes(d) == (R.POLICY_INVALID,)
    d = run(ticket=replace(TICKET, max_book_age=-timedelta(seconds=1)))
    assert codes(d) == (R.POLICY_INVALID,)


@pytest.mark.parametrize("build", [
    lambda: HeldPosition(TICKER, YES, Decimal("-1"), EVENT, CLUSTER),
    lambda: HeldPosition(TICKER, YES, Decimal("0"), EVENT, CLUSTER),
    lambda: HeldPosition(TICKER, YES, Decimal("NaN"), EVENT, CLUSTER),
    lambda: HeldPosition(TICKER, YES, True, EVENT, CLUSTER),
    lambda: HeldPosition(TICKER, YES, 1.5, EVENT, CLUSTER),
    lambda: HeldPosition(TICKER, "yes", Decimal("1"), EVENT, CLUSTER),
    lambda: BookLevel(Decimal("0.5"), Decimal("-1")),
    lambda: BookLevel(0.5, Decimal("1")),
    lambda: BookLevel(Decimal("1"), Decimal("1")),
    lambda: BookLevel(Decimal("NaN"), Decimal("1")),
    lambda: book(yes_asks=(lv("0.42", "1"), lv("0.41", "1"))),  # asks must ascend
    lambda: book(yes_bids=(lv("0.40", "1"), lv("0.40", "1"))),
    lambda: LedgerEntry("x", NOW.isoformat(), LedgerKind.REALIZED_PNL, Decimal("NaN")),
    lambda: LedgerEntry("x", NOW.isoformat(), LedgerKind.REALIZED_PNL, 1.0),
    lambda: LedgerEntry("x", NOW.isoformat(), LedgerKind.DEPOSIT, Decimal("-5")),
    lambda: LedgerEntry("x", "2026-10-07T15:00:00", LedgerKind.REALIZED_PNL, Decimal("1")),  # naive time
    lambda: OrderHistoryEntry("o", TICKER, m.IntentKind.ENTRY, NOW.isoformat(), Decimal("-1")),
    lambda: OrderHistoryEntry("o", TICKER, m.IntentKind.ENTRY, NOW.isoformat(), False),
    lambda: Commitment("c", CommitmentOrigin.LOCAL, S.RELEASED, m.IntentKind.ENTRY, TICKER, YES, m.Action.BUY,
                       Decimal(1), Decimal(1), Decimal(1), EVENT, CLUSTER, None),
    lambda: Commitment("c", CommitmentOrigin.LOCAL, S.OUTSTANDING, m.IntentKind.ENTRY, TICKER, YES, m.Action.BUY,
                       Decimal(1), True, Decimal(1), EVENT, CLUSTER, None),
    lambda: Commitment("c", CommitmentOrigin.LOCAL, S.OUTSTANDING, None, TICKER, YES, m.Action.BUY,
                       Decimal(1), Decimal(1), Decimal(1), EVENT, CLUSTER, None),
    lambda: Commitment("c", CommitmentOrigin.EXTERNAL, S.OUTSTANDING, None, TICKER, YES, m.Action.BUY,
                       Decimal("-2"), Decimal(1), Decimal(1), EVENT, CLUSTER, None),
    lambda: replace(LIMITS, max_slippage=Decimal("-0.01")),
    lambda: replace(LIMITS, max_slippage=True),
    lambda: replace(LIMITS, daily_new_risk=Decimal("NaN")),
    lambda: replace(LIMITS, max_strategy_risk=10.0),
    lambda: replace(LIMITS, max_decision_age=-timedelta(seconds=1)),
    lambda: replace(LIMITS, schema="edge-lab-risk-gate-limits/0"),
    lambda: account(cash=Decimal("NaN")),
    lambda: account(cash=1.5),
    lambda: account(commitments=(local("dup"), local("dup"))),
    lambda: account(positions=(held("1"), held("2"))),
    lambda: account(positions=None, inventory=(InventoryLine(TICKER, YES, Decimal(1)),)),
    lambda: account(snapshot_revision=True),
    lambda: account(snapshot_revision=None),  # a fresh observed_at without a revision is not one snapshot
    lambda: account(observed_at_utc=None),
    lambda: account(consistent=True, problems=("NEGATIVE_CASH: -1",)),
    lambda: account(pnl_history=(pnl("50", timedelta(days=1), ref="gain"), pnl("50", timedelta(days=2), ref="gain"))),
    lambda: account(schema="edge-lab-risk-account-projection/0"),
    lambda: market(exchange_active="yes"),
    lambda: market(price_bands=()),
    lambda: market(exchange_index=-1),
    lambda: market(schema="edge-lab-risk-market-state/9"),
    lambda: evidence(sources=[SourceStamp("a", NOW.isoformat())]),
])
def test_negative_nan_bool_float_and_unknown_schema_are_refused_at_construction(build):
    with pytest.raises((ValueError, m.ExactValueError, TypeError)):
        build()


def test_a_naive_now_raises_and_nothing_else_does():
    with pytest.raises(ValueError):
        run(now=datetime(2026, 10, 7, 15, 0))
    assert not run(acct=None, mkt=None, ev=None).allowed  # missing inputs fail checks, they do not raise


def test_a_decision_cannot_claim_allowed_with_reasons():
    with pytest.raises(ValueError):
        g.GateDecision(True, (g.Violation(R.CASH_UNKNOWN, "x"),), "d", NOW.isoformat(), ())
    with pytest.raises(ValueError):
        g.GateDecision(False, (), "d", NOW.isoformat(), ())


# ---------------------------------------------------------------- approval binding


def grant(i: m.OrderIntent, *, approved=NOW - timedelta(minutes=1), expires=NOW + timedelta(minutes=5),
          scope_key=None) -> m.ApprovalGrant:
    return m.ApprovalGrant(intent_digest=i.digest(), scope_key=scope_key or i.scope.key(),
                           method=m.ApprovalMethod.HUMAN, approver_ref="owner", approved_at_utc=approved.isoformat(),
                           expires_at_utc=expires.isoformat(), nonce="nonce-1")


def revalidate(i, gr, **kw):
    base = dict(account=account(), market=market(), policy=POLICY, limits=LIMITS, ticket_limits=TICKET,
                evidence=evidence(), now=NOW)
    base.update(kw)
    return g.revalidate(i, gr, **base)


def test_revalidate_passes_for_the_approved_intent():
    i = intent()
    d = revalidate(i, grant(i))
    assert d.allowed and d == g.evaluate(i, account=account(), market=market(), policy=POLICY, limits=LIMITS,
                                         ticket_limits=TICKET, evidence=evidence(), now=NOW)


@pytest.mark.parametrize("field,value", [("quantity", Decimal("9")), ("limit_price", Decimal("0.43")),
                                         ("max_total_cost", Decimal("5.00"))])
def test_a_change_after_approval_is_a_digest_mismatch(field, value):
    approved = intent()
    changed = replace(approved, **{field: value})
    d = revalidate(changed, grant(approved))
    assert codes(d) == (R.APPROVAL_DIGEST_MISMATCH,), d.reasons


def test_approval_scope_time_and_type_problems():
    i = intent()
    assert codes(revalidate(i, grant(i, scope_key="FIXTURE:other-acct:primary"))) == (R.APPROVAL_SCOPE_MISMATCH,)
    assert codes(revalidate(i, grant(i, approved=NOW + timedelta(seconds=5),
                                     expires=NOW + timedelta(minutes=5)))) == (R.APPROVAL_FROM_FUTURE,)
    assert codes(revalidate(i, grant(i, approved=NOW - timedelta(minutes=10),
                                     expires=NOW))) == (R.APPROVAL_EXPIRED,)
    assert codes(revalidate(i, "not-a-grant")) == (R.APPROVAL_INVALID,)


def test_revalidate_lists_approval_and_risk_problems_together_in_order():
    approved = intent()
    changed = replace(approved, quantity=Decimal("11"), max_total_cost=Decimal("5.00"))  # also too deep for the book
    d = revalidate(changed, grant(approved))
    assert codes(d) == (R.APPROVAL_DIGEST_MISMATCH, R.BOOK_DEPTH_INSUFFICIENT)
    assert d.primary.code is R.APPROVAL_DIGEST_MISMATCH and not d.allowed
    expired = intent(expires_at_utc=NOW.isoformat())
    assert codes(revalidate(expired, grant(expired, expires=NOW + timedelta(minutes=1)))) == (R.INTENT_EXPIRED,)


# ---------------------------------------------------------------- review round 1 regressions


def test_review_probe_contradictory_event_keys_do_not_hide_exposure():
    """Finding 2: 5 held on TICKER tagged WRONG-EVENT plus 7 on OTHER in EVENT, event cap 12. The true event exposure
    with this 4.60 order is 16.60; trusting the held tag would see 11.60 and allow it."""
    acct = account(positions=(held("5", event="WRONG-EVENT"), held("7", ticker=OTHER)))
    d = run(policy=replace(WIDE, max_event_risk=Decimal("12"), max_cluster_risk=Decimal("40")), acct=acct)
    assert not d.allowed and codes(d) == (R.EXPOSURE_KEY_CONFLICT,), d.reasons
    # A conflicting cluster tag, or a pending commitment on this market, is the same conflict.
    assert codes(run(acct=account(positions=(held("1", cluster="other-cluster"),)))) == (R.EXPOSURE_KEY_CONFLICT,)
    pending = local("l1", ticker=TICKER, event="WRONG-EVENT", cash="1", risk="1")
    assert codes(run(acct=account(commitments=(pending,)))) == (R.EXPOSURE_KEY_CONFLICT,)
    # Matching or unknown tags are not a conflict (unknown counts toward the candidate's keys).
    assert run(acct=account(positions=(held("1"),))).allowed
    assert run(acct=account(positions=(held("1", event=None, cluster=None),))).allowed


def test_a_short_history_cannot_reset_losses_or_counts_and_the_decision_records_what_it_saw():
    """Finding 4: an empty history 'since one minute ago' is not complete since the account's genesis."""
    recent = (NOW - timedelta(minutes=1)).isoformat()
    d = run(acct=account(pnl_history=(), pnl_history_since_utc=recent, order_history=(),
                         order_history_since_utc=recent))
    assert codes(d) == (R.PNL_HISTORY_UNKNOWN, R.ORDER_HISTORY_UNKNOWN)
    # An unknown genesis means neither history can be shown complete.
    assert codes(run(acct=account(account_genesis_utc=None))) == (R.PNL_HISTORY_UNKNOWN, R.ORDER_HISTORY_UNKNOWN)
    # A reduction is not held to the P&L history, but its order counts still need a complete history.
    assert codes(run(reduction(), acct=account(account_genesis_utc=None, positions=(held("10"),),
                                               inventory=(InventoryLine(TICKER, YES, Decimal("10")),)))) == \
        (R.ORDER_HISTORY_UNKNOWN,)
    # Even a genesis moved forward to match is recorded, so a replay can see the claim.
    moved = account(account_genesis_utc=recent, pnl_history_since_utc=recent, order_history_since_utc=recent)
    assert dict(run(acct=moved).inputs)["account_genesis"] == recent
    # The digests change with the content and with the completeness claim.
    base = account()
    loss = account(pnl_history=(pnl("-1", timedelta(hours=1)),))
    assert base.history_digest("pnl") != loss.history_digest("pnl")
    assert base.history_digest("pnl") != moved.history_digest("pnl")
    assert base.history_digest("orders") != account(order_history=(order("o1", timedelta(hours=2)),)) \
        .history_digest("orders")
    assert account(pnl_history=None).history_digest("pnl") is None
    assert dict(run(acct=loss).inputs)["pnl_history"] == loss.history_digest("pnl")
    # An order before the genesis contradicts the claim.
    early = account(order_history=(order("o0", timedelta(days=61)),))
    assert codes(run(acct=early)) == (R.ORDER_HISTORY_UNKNOWN,)
