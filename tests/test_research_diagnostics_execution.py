"""Track B harness: executable entries, the $100 bankroll ladder, depth/spread and no-trade attrition (#184)."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from edge_lab import research_diagnostics as rd
from edge_lab.fee_schedules import schedule_for
from edge_lab.opportunity import (
    DepthLadder, DepthLevel, Market, MarketStatus, MarketTiming, Payoff, PriceGrid, PriceRange, price_depth_fill,
    walk_ladder,
)
from edge_lab.research_diagnostics import (
    BookSnapshot, EntryRequest, EvidenceClass, NoTradeFilters, ReferenceKind, ReferencePrice, bankroll_ladder,
    depth_report, evaluate_entries,
)

AS_OF = "2026-10-01T12:00:00Z"
FRESH = "2026-10-01T11:59:00Z"
AGE = timedelta(minutes=5)
GRID = PriceGrid((PriceRange(D("0"), D("1"), D("0.01")),), source="test cent grid")


def market(native="KXSYN-26OCT02-A", venue="kalshi", timing=None):
    return Market(venue, f"{venue}:{native}", native, f"{venue}:event", "A", Payoff("binary", D(1), "A wins"), "r" * 64,
                  MarketStatus.OPEN, True, "synthetic", timing=timing, price_grid=GRID)


def ladder(m, levels, *, side="YES", truncated=False, received=FRESH):
    return DepthLadder(m.venue, m.market_id, side, tuple(DepthLevel(D(p), D(s)) for p, s in levels), truncated,
                       received, received, "synthetic")


def fee(m, at=AS_OF):
    return schedule_for(m.venue, m.native_id.split("-", 1)[0] if m.venue == "kalshi" else None, as_of=at)


def entry(eid, m, levels, qty, payout, *, cluster="c1", side="YES", truncated=False, received=FRESH, ref=None):
    return EntryRequest(eid, cluster, "sports:synthetic", m, side, D(qty), ladder(m, levels, side=side,
                        truncated=truncated, received=received), fee(m), AS_OF,
                        None if payout is None else D(payout), ref)


def run(reqs, klass=EvidenceClass.SYNTHETIC):
    return evaluate_entries(reqs, max_book_age=AGE, evidence_class=klass, code_version="test")


# --------------------------------------------------------------------------- entries: exactness


def test_full_fill_walks_depth_and_prices_each_take_through_the_fee_owner():
    m = market()
    e = run([entry("e1", m, [("0.40", "5"), ("0.42", "10")], 10, 1)]).evaluations[0]
    # 5 @ 0.40: fee 0.084, debit floor(-2.084) = 2.09; 5 @ 0.42: fee 0.08526, debit 2.19
    assert e.status == "FULL" and e.filled == D(10) and e.takes == ((D("0.40"), D(5)), (D("0.42"), D(5)))
    assert (e.gross_cost, e.fee, e.total_cost, e.limit_price) == (D("4.10"), D("0.16926"), D("4.28"), D("0.42"))
    assert (e.gross_pnl, e.net_pnl) == (D("5.90"), D("5.72"))
    assert e.fee_status == "UNVERIFIED_CURRENT_SCHEDULE" and e.claimable is False and e.claim_adjusted_net is None
    assert e.priced_from == "CAPTURED_ASK_LADDER" and "no figure here is executable performance" in \
        e.executable_performance


def test_claimable_fee_applies_the_rounding_allowance():
    m = market("KXHIGHNY-26OCT02-T70")
    e = run([entry("e1", m, [("0.40", "10")], 10, 1)]).evaluations[0]
    assert e.claim_basis == "CONSERVATIVE_BOUND"
    assert e.claim_adjusted_net == e.net_pnl - D("0.0101") * 10


# --------------------------------------------------------------------------- mid / trade price never fillable


def test_a_mid_or_trade_price_is_never_fillable():
    m = market()
    ref = ReferencePrice(ReferenceKind.MID, D("0.30"))
    assert ref.fillable is False
    bad = EntryRequest("x", "c", "s", m, "YES", D(1), ref, fee(m), AS_OF)
    with pytest.raises(TypeError, match="never"):
        run([bad])
    e = run([entry("e1", m, [("0.40", "5")], 5, 1, ref=ReferencePrice(ReferenceKind.LAST_TRADE, D("0.30")))])
    ev = e.evaluations[0]
    assert ev.average_price == D("0.40") and ev.reference_value == D("0.30") and ev.reference_fillable is False
    with pytest.raises(TypeError):
        bankroll_ladder(m, "YES", ref, fee(m), as_of_utc=AS_OF, max_book_age=AGE,
                        evidence_class=EvidenceClass.SYNTHETIC, code_version="test")
    assert not hasattr(DepthLadder, "mid") and "mid" not in rd.SnapshotMetrics.__dataclass_fields__


# --------------------------------------------------------------------------- partial, missed, stale


def test_partial_missed_stale_and_lookahead_fills():
    m = market()
    rep = run([
        entry("partial", m, [("0.40", "5")], 10, 1),
        entry("trunc", m, [("0.40", "5")], 10, 1, truncated=True),
        entry("missed", m, [], 10, 1),
        entry("stale", m, [("0.40", "50")], 10, 1, received="2026-10-01T11:00:00Z"),
        entry("ahead", m, [("0.40", "50")], 10, 1, received="2026-10-01T12:00:01Z"),
        entry("wrong", m, [("0.40", "50")], 10, 1, side="NO"),
    ])
    by = {e.entry_id: e for e in rep.evaluations}
    assert (by["partial"].status, by["partial"].filled, by["partial"].unfilled) == ("PARTIAL", D(5), D(5))
    assert by["trunc"].status == "PARTIAL_DEPTH_UNKNOWN" and by["trunc"].filled == D(5)
    for k, status in (("missed", "MISSED"), ("stale", "STALE_BOOK"), ("ahead", "LOOKAHEAD")):
        assert by[k].status == status and by[k].filled == 0 and by[k].net_pnl is None and by[k].total_cost is None
    assert by["wrong"].status == "FULL"  # a NO ladder for a NO request is valid
    assert rep.summary.status_counts["MISSED"] == 1


def test_wrong_book_is_invalid():
    m, other = market(), market("KXSYN-26OCT02-B")
    req = EntryRequest("x", "c", "s", m, "YES", D(1), ladder(other, [("0.4", "5")]), fee(m), AS_OF, D(1))
    assert run([req]).evaluations[0].status == "INVALID_BOOK"


# --------------------------------------------------------------------------- unknowns propagate


def test_unknown_fee_gives_unknown_net_never_fee_free():
    m = market("nv-1", venue="novig")
    e = run([entry("e1", m, [("0.40", "10")], 10, 1)])
    ev = e.evaluations[0]
    assert ev.fee is None and ev.total_cost is None and ev.net_pnl is None
    assert ev.gross_pnl == D("6.00")  # labelled diagnostic only
    assert any(r.startswith("FEE_UNSUPPORTED") for r in ev.reasons)
    assert e.summary.total_net_pnl is None and e.summary.sign_after_costs == "UNKNOWN"


def test_unknown_payout_gives_unknown_pnl():
    ev = run([entry("e1", market(), [("0.40", "10")], 10, None)]).evaluations[0]
    assert ev.total_cost == D("4.17") and ev.net_pnl is None and ev.gross_pnl is None


# --------------------------------------------------------------------------- negative EV with a great win rate


def test_98_percent_wins_at_99_cents_is_negative_after_costs():
    m = market()
    reqs = [entry(f"e{i}", m, [("0.99", "100")], 100, 1 if i >= 2 else 0, cluster=f"g{i // 2}") for i in range(100)]
    s = run(reqs).summary
    assert (s.entries, s.filled_entries, s.wins, s.win_rate) == (100, 100, 98, D("0.980000000000"))
    # each fill: 100 @ 0.99, fee 0.0693, debit floor(-99.0693) = 99.07; win +0.93, loss -99.07
    assert s.average_all_in_per_contract == D("0.990700000000")
    assert s.total_net_pnl == D("-107.00") and s.total_gross_pnl == D(-100)
    assert s.sign_after_costs == "NEGATIVE" and "a win rate is not a return" in s.reading
    assert s.clusters == 50 and s.clusters != s.entries  # contracts of one game are not independent
    assert s.net_band is not None and s.net_band.clusters == 50 and s.net_band.lower < 0


def test_synthetic_profit_is_labelled_a_code_test():
    rep = run([entry("e1", market(), [("0.10", "10")], 10, 1)])
    assert rep.summary.sign_after_costs == "NON_NEGATIVE_POINT_ESTIMATE_NOT_AN_EDGE"
    assert rep.stamp.edge_claim == "NONE" and "SYNTHETIC INPUT - CODE TEST ONLY - NOT DATA AND NOT AN EDGE" in \
        rep.stamp.label


def test_governed_entries_refuse_protected_outcomes():
    m = market("KXNFLGAME-26OCT11ATLGB-GB")
    with pytest.raises(ValueError, match="protected label scope"):
        evaluate_entries([entry("e1", m, [("0.4", "1")], 1, 1)], max_book_age=AGE,
                         evidence_class=EvidenceClass.RETROSPECTIVE_EXPLORATORY, code_version="t",
                         experiment_id="EXP-010", evidence_use_event_id="eu-" + "1" * 32)


# --------------------------------------------------------------------------- $100 bankroll ladder


def _brute_max(m, book, sched, budget):
    best = D(0)
    for q in range(1, 1000):
        fill = walk_ladder(book, D(q), price_grid=m.price_grid)
        cost, _ = price_depth_fill(fill, sched)
        if cost is None or cost.total_cost > budget:
            break
        best = D(q)
    return best


def test_bankroll_ladder_is_exact_and_reports_lockup():
    timing = MarketTiming(expected_resolution_utc="2026-10-03T12:00:00Z", latest_resolution_utc="2026-10-08T12:00:00Z",
                          settlement_timer_seconds=300)
    m = market(timing=timing)
    book = ladder(m, [("0.40", "100"), ("0.50", "500")])
    lad = bankroll_ladder(m, "YES", book, fee(m), as_of_utc=AS_OF, max_book_age=AGE,
                          bankrolls=(D(100), D(25), D(1000)), settlement_payout=D(1),
                          evidence_class=EvidenceClass.SYNTHETIC, code_version="test")
    assert lad.status == "ILLUSTRATIVE_SCENARIO_NOT_APPROVED_BANKROLL" and lad.book_state == "FRESH"
    r100, r25, r1000 = lad.rungs
    assert r100.quantity == _brute_max(m, book, fee(m), D(100)) and r100.limited_by == "BANKROLL"
    assert r100.total_cost <= D(100) and r100.idle_cash == D(100) - r100.total_cost
    assert r25.quantity == _brute_max(m, book, fee(m), D(25))
    assert (r1000.quantity, r1000.limited_by) == (D(600), "DEPTH")
    days_exp = D(2) + D(300) / D(86400)
    assert r100.lockup_days_expected == days_exp.quantize(D("1e-12"))
    assert r100.capital_days_expected == (r100.total_cost * days_exp).quantize(D("1e-12"))
    assert r100.turnover_per_year_scenario is not None and r100.net_pnl == r100.quantity - r100.total_cost


def test_bankroll_ladder_unknowns():
    m = market()  # no timing: lock-up UNKNOWN
    lad = bankroll_ladder(m, "YES", ladder(m, [("0.40", "10")], truncated=True), fee(m), as_of_utc=AS_OF,
                          max_book_age=AGE, evidence_class=EvidenceClass.SYNTHETIC, code_version="test")
    r = lad.rungs[0]
    assert r.limited_by == "DEPTH_UNKNOWN" and r.lockup_days_latest is None and r.capital_days_latest is None
    assert r.net_pnl is None  # no payout given
    nv = market("nv-1", venue="novig")
    r = bankroll_ladder(nv, "YES", ladder(nv, [("0.40", "1000")]), fee(nv), as_of_utc=AS_OF, max_book_age=AGE,
                        evidence_class=EvidenceClass.SYNTHETIC, code_version="test").rungs[0]
    assert r.quantity is None and r.total_cost is None and r.quantity_upper_bound_gross == D(250)
    stale = bankroll_ladder(m, "YES", ladder(m, [("0.4", "10")], received="2026-10-01T10:00:00Z"), fee(m),
                            as_of_utc=AS_OF, max_book_age=AGE, evidence_class=EvidenceClass.SYNTHETIC,
                            code_version="test")
    assert stale.rungs == () and stale.book_state.startswith("STALE_BOOK")


# --------------------------------------------------------------------------- depth / spread / attrition


def snap(sid, m, yes, no, *, cluster, group="g", received=FRESH, truncated=False):
    return BookSnapshot(sid, m, cluster, group,
                        None if yes is None else ladder(m, yes, truncated=truncated, received=received),
                        None if no is None else ladder(m, no, side="NO", received=received), fee(m))


def test_depth_report_spreads_filters_and_separate_denominators():
    a, b, c = market("KXSYN-1-A"), market("KXSYN-1-B"), market("KXSYN-2-A")
    nv = market("nv-9", venue="novig")
    snaps = [
        snap("s1", a, [("0.52", "20")], [("0.52", "20")], cluster="e1"),  # spread 0.04
        snap("s2", a, [("0.50", "20")], None, cluster="e1"),  # one-sided: spread UNKNOWN
        snap("s3", b, [("0.30", "20")], [("0.75", "20")], cluster="e1", received="2026-10-01T10:00:00Z"),  # stale
        snap("s4", c, [("0.60", "20")], [("0.60", "20")], cluster="e2"),  # spread 0.20: wide
        snap("s5", c, [("0.40", "3")], [("0.62", "20")], cluster="e2"),  # probe 10 > depth 3
        snap("s6", nv, [("0.40", "20")], [("0.62", "20")], cluster="e3"),  # fee unsupported
        snap("s7", c, None, None, cluster="e2"),
    ]
    filters = NoTradeFilters("tb-filters-v1", AGE, D(10), D("0.10"))
    rep = depth_report(snaps, filters, as_of_utc=AS_OF, evidence_class=EvidenceClass.SYNTHETIC, code_version="t")
    by = {x.snapshot_id: x for x in rep.snapshots}
    assert by["s1"].spread == D("0.04") and by["s1"].yes_bid == D("0.48") and by["s1"].reasons == ()
    assert by["s1"].yes_ask + by["s1"].no_ask > 1  # buying both sides costs more than the $1 they pay
    assert by["s2"].spread is None and by["s2"].reasons == ("SPREAD_UNKNOWN",)
    assert by["s3"].reasons[0] == "STALE_BOOK"
    assert by["s4"].reasons == ("WIDE_SPREAD",)
    assert by["s5"].reasons == ("INSUFFICIENT_DEPTH",)
    assert by["s6"].reasons == ("FEE_UNSUPPORTED",)
    assert by["s7"].reasons == ("BOOK_MISSING",)
    assert rep.filter_census_primary == {"BOOK_MISSING": 1, "FEE_UNSUPPORTED": 1, "INSUFFICIENT_DEPTH": 1,
                                         "SPREAD_UNKNOWN": 1, "STALE_BOOK": 1, "WIDE_SPREAD": 1}
    d = rep.attrition.denominators
    assert (d["snapshots"], d["markets"], d["events"]) == (7, 4, 3)  # never pooled
    snap_wf = next(w for w in rep.attrition.waterfalls if w.level == "SNAPSHOT")
    market_wf = next(w for w in rep.attrition.waterfalls if w.level == "MARKET")
    event_wf = next(w for w in rep.attrition.waterfalls if w.level == "EVENT")
    assert (snap_wf.survivors, market_wf.survivors, event_wf.survivors) == (1, 1, 1)
    assert snap_wf.reconciled and snap_wf.clusters == 3
    g = rep.groups[0]
    # fresh, valid books only: the stale s3 and the missing s7 are excluded; s2's spread is UNKNOWN, not 0
    assert g.snapshots == 5 and g.spread_unknown == 1 and g.spread.count == 4
    assert (g.spread.minimum, g.spread.median, g.spread.maximum) == (D("0.02"), D("0.02"), D("0.20"))
    assert rep.stamp.evidence_class == "SYNTHETIC"


def test_depth_report_on_nothing_is_zero_not_missing_at_enumerated_levels():
    rep = depth_report([], NoTradeFilters("f", AGE, D(1), None), as_of_utc=AS_OF,
                       evidence_class=EvidenceClass.FIXTURE, code_version="t")
    assert rep.attrition.denominators["snapshots"] == 0 and rep.attrition.denominators["opportunities"] is None
    assert rep.groups == ()
