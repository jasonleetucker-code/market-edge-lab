"""Deterministic hold-vs-exit replay and isolated accounting (#122 §16-§18, §20, §23 in-play)."""

from __future__ import annotations

import statistics
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from edge_lab import inplay_replay as R
from edge_lab.inplay_evidence import BookStatus, DataKind, TradingState
from edge_lab.inplay_replay import Arm, EntryStatus, FillRule, ReplayLedger, Semantics
from edge_lab.position_policy import UnknownFeeModel

from tests.test_position_policy import FIXTURE_FEES, FIXTURE_SCHEDULE

T0 = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
ENTRY_COST = FIXTURE_SCHEDULE.taker_buy(100, D("0.30")).total_cost  # 31.47: 30.00 + 1.47 fee, cent-floored


def at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def bk(seconds, bids, *, status=BookStatus.VALID, state=TradingState.OPEN, truncated=False):
    return R.TimedBook(at(seconds), tuple((D(p), D(s)) for p, s in bids), status, state, truncated,
                       f"fixture:{seconds}")


def entry(books, settle="0", *, final=True, game="G1", cluster="W05", cost=ENTRY_COST):
    return R.CohortEntry(game, cluster, f"kalshi:KXNFLGAME-FIXTURE-{game}", D(100), D("0.30"), cost, at(0),
                         tuple(books), R.Settlement(None if settle is None else D(settle), final, at(3600)))


def cohort(*entries, kind=DataKind.FIXTURE):
    return R.Cohort("fixture-cohort", kind, f"{kind.value} hand-written in-play fixture", tuple(entries), D(1000),
                    at(4000), "rules-sha-fixture")


def cfg(**kw):
    base = dict(target_price=D("0.70"), partial_fraction=D("0.5"), fee_model=FIXTURE_FEES)
    base.update(kw)
    return R.ReplayConfig(**base)


def res(report, game, arm, sem):
    return next(r for r in report.entries if r.game_id == game and r.arm is arm and r.semantics is sem)


REACH = [bk(10, [("0.50", "500")]), bk(60, [("0.70", "100")]), bk(62, [("0.70", "100")]),
         bk(70, [("0.75", "100")])]


# ------------------------------------------------------------------ the owner's 30c / 70c example


def test_30c_entry_70c_filled_exit_with_fees_and_hold_comparison():
    assert ENTRY_COST == D("31.47")
    rep = R.replay(cohort(entry(REACH, "0")), cfg())
    hold = res(rep, "G1", Arm.HOLD, None)
    bot = res(rep, "G1", Arm.FULL_EXIT, Semantics.BOT_TRIGGERED)
    assert hold.pnl_gross == D("-30.00") and hold.pnl_net == D("-31.47") and hold.residual == D(100)
    assert bot.sold == D(100) and bot.gross_proceeds == D("70.00") and bot.fees == D("1.470000")
    assert bot.net_proceeds == D("68.53")  # proceeds, cent-floored; not profit
    assert bot.pnl_gross == D("40.00") and bot.pnl_net == D("37.06")
    assert bot.residual == 0 and bot.settlement_cash == 0 and bot.reconciliation == ()
    summary = rep.arm(Arm.FULL_EXIT, Semantics.BOT_TRIGGERED)
    assert summary.change_vs_hold_net == D("68.53") and summary.terminal_wealth_net == D("1037.06")
    assert rep.after_cost_claim is False and "fee basis NONE" in rep.after_cost_reason


def test_bot_fills_only_on_the_book_received_after_arrival():
    # detection at 60s (bid 0.70); the book at arrival (62s) shows only 0.65: no fill at detection
    books = [bk(60, [("0.70", "100")]), bk(62, [("0.65", "100")]), bk(3000, [("0.10", "100")])]
    rep = R.replay(cohort(entry(books)), cfg())
    bot = res(rep, "G1", Arm.FULL_EXIT, Semantics.BOT_TRIGGERED)
    assert bot.sold == 0 and any(n.startswith("IOC_NO_FILL") for n in bot.notes)
    diag = next(d for d in rep.diagnostics if d.label == "FIRST_DETECTION_ZERO_LATENCY" and d.arm is Arm.FULL_EXIT)
    assert diag.gross_proceeds == D("70.00")  # the zero-latency oracle would have sold: kept apart


def test_target_never_reached_equals_hold():
    rep = R.replay(cohort(entry([bk(10, [("0.65", "500")]), bk(20, [("0.60", "500")])], "1")), cfg())
    hold = res(rep, "G1", Arm.HOLD, None)
    for arm in (Arm.FULL_EXIT, Arm.PARTIAL_EXIT):
        for sem in Semantics:
            r = res(rep, "G1", arm, sem)
            assert r.sold == 0 and r.pnl_gross == hold.pnl_gross == D("70.00")


def test_partial_exit_then_residual_loss_settles_the_residual_exactly_once():
    rep = R.replay(cohort(entry(REACH, "0")), cfg())
    part = res(rep, "G1", Arm.PARTIAL_EXIT, Semantics.BOT_TRIGGERED)
    assert part.sold == D(50) and part.residual == D(50) and part.settlement_cash == 0
    assert part.gross_proceeds == D("35.00") and part.pnl_gross == D("5.00")
    fee = FIXTURE_SCHEDULE.taker_buy(50, D("0.70")).fee
    assert part.pnl_net == (D("35.00") - fee).quantize(D("0.01"), rounding="ROUND_FLOOR") - ENTRY_COST
    win = R.replay(cohort(entry(REACH, "1")), cfg())
    part_win = res(win, "G1", Arm.PARTIAL_EXIT, Semantics.BOT_TRIGGERED)
    assert part_win.settlement_cash == D(50)  # only the 50 unsold contracts are paid


# ------------------------------------------------------------------ gaps, jumps, reconnects, pauses


def test_no_fill_is_interpolated_through_a_gap():
    books = [bk(60, [("0.60", "100")]), bk(70, [("0.90", "100")], status=BookStatus.GAP_AWAITING_RESYNC),
             bk(80, [("0.60", "100")]), bk(82, [("0.60", "100")])]
    rep = R.replay(cohort(entry(books)), cfg(fill_rule=FillRule.TOUCH_UPPER_BOUND))
    for sem in Semantics:
        assert res(rep, "G1", Arm.FULL_EXIT, sem).sold == 0
    hind = next(d for d in rep.diagnostics if d.label == "HINDSIGHT_UPPER_BOUND" and d.arm is Arm.FULL_EXIT)
    assert hind.gross_proceeds == D("60.00")  # the unusable 0.90 book is not even an oracle price


def test_reconnect_after_price_movement():
    books = [bk(0, [("0.30", "500")]), bk(60, [("0.60", "100")]), bk(70, [], status=BookStatus.GAP_AWAITING_RESYNC),
             bk(90, [("0.80", "100")]), bk(92, [("0.80", "100")])]
    rep = R.replay(cohort(entry(books)), cfg())
    bot = res(rep, "G1", Arm.FULL_EXIT, Semantics.BOT_TRIGGERED)
    assert bot.sold == D(100) and bot.gross_proceeds == D("80.00")  # sold into the new bids at arrival
    rest = res(rep, "G1", Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT)
    # bids strictly above the resting limit prove it would have traded, at its own limit price
    assert rest.sold == D(100) and rest.gross_proceeds == D("70.00")


def test_touch_is_not_a_fill_under_strict_through():
    books = [bk(0, [("0.30", "500")]), bk(60, [("0.70", "500")]), bk(90, [("0.70", "500")]),
             bk(120, [("0.60", "500")])]
    strict = R.replay(cohort(entry(books)), cfg())
    rest = res(strict, "G1", Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT)
    assert rest.sold == 0 and rest.touches_not_filled == 2
    assert any(n.startswith("TOUCHES_NOT_FILLS") for n in rest.notes)
    touch = R.replay(cohort(entry(books)), cfg(fill_rule=FillRule.TOUCH_UPPER_BOUND))
    assert res(touch, "G1", Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT).sold == D(100)
    assert touch.fill_rule == "TOUCH_UPPER_BOUND"


def test_visible_liquidity_is_not_multiplied_across_snapshots():
    # the same 30 contracts bid at 0.75 in three snapshots fill 30, not 90
    books = [bk(0, [("0.30", "500")]), bk(60, [("0.75", "30")]), bk(90, [("0.75", "30")]),
             bk(120, [("0.75", "30")])]
    rep = R.replay(cohort(entry(books)), cfg())
    assert res(rep, "G1", Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT).sold == D(30)


def test_truncated_or_empty_depth_at_arrival():
    books = [bk(60, [("0.70", "100")]), bk(62, [("0.70", "40")], truncated=True), bk(80, [])]
    rep = R.replay(cohort(entry(books)), cfg(max_attempts=1))
    bot = res(rep, "G1", Arm.FULL_EXIT, Semantics.BOT_TRIGGERED)
    assert bot.sold == D(40) and any(n.startswith("IOC_PARTIAL") for n in bot.notes)


def test_paused_market_neither_fills_nor_triggers():
    books = [bk(60, [("0.90", "100")], state=TradingState.TRADING_PAUSED),
             bk(62, [("0.90", "100")], state=TradingState.EXCHANGE_PAUSED)]
    rep = R.replay(cohort(entry(books)), cfg())
    for sem in Semantics:
        assert res(rep, "G1", Arm.FULL_EXIT, sem).sold == 0
    cancel = R.replay(cohort(entry([bk(0, [("0.50", "10")])] + books)), cfg(cancel_on_pause=True))
    rest = res(cancel, "G1", Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT)
    assert rest.sold == 0 and any(n.startswith("CANCELLED_ON_PAUSE") for n in rest.notes)


def test_a_resting_sale_needs_an_admissible_book_to_be_placed():
    rep = R.replay(cohort(entry([bk(60, [("0.80", "100")])])), cfg())
    rest = res(rep, "G1", Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT)
    assert rest.sold == 0 and rest.placed is False and rest.notes[0] == "NOT_PLACED: BOOK_MISSING"
    # the arm summary counts it, so a never-placed arm cannot pass for HOLD
    assert rep.arm(Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT).not_placed == 1
    assert rep.arm(Arm.FULL_EXIT, Semantics.BOT_TRIGGERED).not_placed == 0


def test_a_book_received_just_before_entry_can_place_the_resting_sale():
    books = [bk(-10, [("0.30", "500")]), bk(60, [("0.80", "100")])]
    rest = res(R.replay(cohort(entry(books)), cfg()), "G1", Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT)
    assert rest.placed is True and rest.sold == D(100) and rest.gross_proceeds == D("70.00")
    too_old = [bk(-30, [("0.30", "500")]), bk(60, [("0.80", "100")])]  # older than max_book_age at placement
    stale = res(R.replay(cohort(entry(too_old)), cfg()), "G1", Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT)
    assert stale.placed is False and stale.notes[0] == "NOT_PLACED: BOOK_MISSING"  # outside the look-back


def test_fills_are_keyed_by_book_identity_and_duplicate_receipts_are_reported():
    # two distinct books share one receipt time: each is its own evidence, so neither fill is lost
    twin_a = R.TimedBook(at(62), ((D("0.75"), D("30")),), evidence_id="seq-41")
    twin_b = R.TimedBook(at(62), ((D("0.76"), D("50")),), evidence_id="seq-42")
    books = [bk(0, [("0.30", "500")]), twin_a, twin_b]
    rep = R.replay(cohort(entry(books)), cfg())
    rest = res(rep, "G1", Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT)
    assert rest.duplicate_receipts == 1 and any(n.startswith("DUPLICATE_RECEIPT_TIMES") for n in rest.notes)
    assert rest.sold == D(50) and rest.reconciliation == ()  # the larger crossing, never 30 + 50
    same = R.TimedBook(at(62), ((D("0.75"), D("30")),), evidence_id="seq-41")
    rep2 = R.replay(cohort(entry([bk(0, [("0.30", "500")]), twin_a, same])), cfg())
    assert res(rep2, "G1", Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT).sold == D(30)  # a true duplicate fills once


def test_unknown_arrival_latency_means_no_fill():
    rep = R.replay(cohort(entry(REACH)), cfg(arrival_latency=None))
    for sem in Semantics:
        r = res(rep, "G1", Arm.FULL_EXIT, sem)
        assert r.sold == 0 and any("ARRIVAL_UNKNOWN" in n for n in r.notes)


def test_latency_beyond_the_arrival_gap_is_no_fill_not_a_stale_fill():
    books = [bk(60, [("0.70", "100")]), bk(100, [("0.70", "100")])]  # sparse: nothing near arrival
    rep = R.replay(cohort(entry(books)), cfg(max_attempts=1))
    bot = res(rep, "G1", Arm.FULL_EXIT, Semantics.BOT_TRIGGERED)
    assert bot.sold == 0 and any(n.startswith("NO_BOOK_AT_ARRIVAL") for n in bot.notes)


# ------------------------------------------------------------------ incompleteness, fees, labels


def test_suspended_game_without_final_settlement_is_incomplete_never_zero():
    rep = R.replay(cohort(entry(REACH, None), entry(REACH, "0", game="G2")), cfg())
    hold = res(rep, "G1", Arm.HOLD, None)
    assert hold.status is EntryStatus.INCOMPLETE and hold.pnl_gross is None and hold.residual is None
    s = rep.arm(Arm.HOLD, None)
    assert s.incomplete == 1 and s.pnl_gross is None and s.terminal_wealth_gross is None
    assert s.complete_only_pnl_gross == D("-30.00")  # a labelled subtotal, not the total
    not_final = R.replay(cohort(entry(REACH, "1", final=False)), cfg())
    assert res(not_final, "G1", Arm.HOLD, None).status is EntryStatus.INCOMPLETE


def test_missing_fees_block_after_cost_but_keep_gross():
    rep = R.replay(cohort(entry(REACH)), cfg(fee_model=UnknownFeeModel("unsupported:kalshi:KXNFLGAME", "Q7")))
    bot = res(rep, "G1", Arm.FULL_EXIT, Semantics.BOT_TRIGGERED)
    assert bot.pnl_gross == D("40.00") and bot.pnl_net is None and bot.fees is None
    assert rep.arm(Arm.FULL_EXIT, Semantics.BOT_TRIGGERED).change_vs_hold_net is None
    assert rep.after_cost_claim is False
    unknown_settle = R.replay(cohort(entry(REACH)), cfg(settlement_fee_per_contract=None))
    assert res(unknown_settle, "G1", Arm.HOLD, None).pnl_net is None


def test_unknown_entry_cost_blocks_net_for_every_arm():
    rep = R.replay(cohort(entry(REACH, cost=None)), cfg())
    assert all(r.pnl_net is None for r in rep.entries)


def test_recorded_cohorts_are_refused_and_labels_must_say_synthetic():
    with pytest.raises(ValueError, match="experiment id"):
        R.Cohort("x", DataKind.RECORDED, "RECORDED", (), D(0), at(1), "r")
    with pytest.raises(ValueError, match="label"):
        R.Cohort("x", DataKind.SYNTHETIC, "LIVE in-play", (), D(0), at(1), "r")


def test_every_arm_sees_the_identical_cohort_and_diagnostics_stay_apart():
    c = cohort(entry(REACH, "1"), entry(REACH, "0", game="G2", cluster="W06"))
    rep = R.replay(c, cfg())
    assert rep.cohort_sha256 == c.sha256 == R.replay(c, cfg()).cohort_sha256
    per_arm = {}
    for r in rep.entries:
        per_arm.setdefault((r.arm, r.semantics), []).append(r.game_id)
    assert len(per_arm) == 5 and all(v == ["G1", "G2"] for v in per_arm.values())
    assert {d.label for d in rep.diagnostics} == set(R.DIAGNOSTIC_LABELS)
    assert all(a.clusters == 2 for a in rep.arms)
    assert rep.to_dict()["arms"][0]["arm"] == "HOLD"


def test_sensitivities_report_every_variant():
    c = cohort(entry(REACH))
    reports = R.sensitivity(c, cfg(), latencies=[timedelta(seconds=30), None], haircuts=[1, 5],
                            fill_rules=[FillRule.TOUCH_UPPER_BOUND])
    assert len(reports) == 6 and len({r.config_variant for r in reports}) == 6
    by_haircut = {r.config_variant: r for r in reports}
    assert all(r.cohort_sha256 == c.sha256 for r in by_haircut.values())


# ------------------------------------------------------------------ the isolated ledger


def ledger():
    lg = ReplayLedger()
    lg.acquire(D(100), D("0.30"), D("31.47"))
    return lg


def test_ledger_refuses_overselling_and_double_reservation():
    lg = ledger()
    lg.reserve("auto", D(60))
    with pytest.raises(R.LedgerError, match="DOUBLE_RESERVATION"):
        lg.reserve("auto", D(10))
    with pytest.raises(R.LedgerError, match="OVERSELL_RESERVATION"):
        lg.reserve("bot", D(41))
    with pytest.raises(R.LedgerError, match="OVERSELL"):
        lg.fill(fill_id="f1", quantity=D(41), price=D("0.70"), fee=D(0))
    with pytest.raises(R.LedgerError, match="ACQUIRE_TWICE"):
        lg.acquire(D(1), D("0.30"), D("0.31"))


def test_ledger_applies_each_fill_and_fee_once():
    lg = ledger()
    assert lg.fill(fill_id="f1", quantity=D(10), price=D("0.70"), fee=D("0.147"))
    assert not lg.fill(fill_id="f1", quantity=D(10), price=D("0.70"), fee=D("0.147"))
    assert lg.sold == D(10) and lg.duplicate_fills == 1 and lg.fees == [D("0.147")]
    assert lg.reconcile() == []


def test_cancel_fill_race_releases_only_the_unfilled_remainder_after_confirmation():
    lg = ledger()
    lg.reserve("rest", D(100))
    lg.request_cancel("rest")
    assert lg.reserved == D(100)  # a request releases nothing
    lg.fill(fill_id="late", quantity=D(30), price=D("0.70"), fee=D(0), order_id="rest")  # late fill still lands
    assert lg.confirm_cancel("rest") == D(70) and lg.reserved == 0
    with pytest.raises(R.LedgerError, match="RELEASE_TWICE"):
        lg.confirm_cancel("rest")
    with pytest.raises(R.LedgerError, match="FILL_EXCEEDS_ORDER"):
        lg.fill(fill_id="later", quantity=D(1), price=D("0.70"), fee=D(0), order_id="rest")


def test_residual_settles_exactly_once_and_sold_contracts_get_nothing():
    lg = ledger()
    lg.fill(fill_id="f", quantity=D(40), price=D("0.70"), fee=D("0.8232"))
    lg.settle(D(1), fee_per_contract=D(0))
    assert lg.settled_quantity == D(60) and lg.settlement_cash == D(60)
    with pytest.raises(R.LedgerError, match="SETTLE_TWICE"):
        lg.settle(D(1), fee_per_contract=D(0))
    with pytest.raises(R.LedgerError, match="FILL_AFTER_SETTLEMENT|OVERSELL"):
        lg.fill(fill_id="g", quantity=D(1), price=D("0.70"), fee=D(0))
    assert lg.reconcile() == []
    assert lg.pnl_gross() == D("28.00") + D(60) - D("30.00")


def test_resting_reservation_expires_at_close_on_settlement():
    lg = ledger()
    lg.reserve("rest", D(50))
    lg.settle(D(0), fee_per_contract=D(0))
    assert lg.reserved == 0 and any(e.startswith("EXPIRED_AT_CLOSE") for e in lg.events)


# ------------------------------------------------------------------ calibrated-price synthetic nulls

NULL_SEED, NULL_GAMES = 20260928, 800  # fixed before the first run; not tuned


@pytest.fixture(scope="module")
def null_cohort():
    return R.synthetic_martingale_cohort(seed=NULL_SEED, games=NULL_GAMES)


def _diff_bound(report, arm, sem):
    hold = {r.game_id: r.pnl_gross for r in report.entries if r.arm is Arm.HOLD}
    diffs = [float(r.pnl_gross - hold[r.game_id]) for r in report.entries if r.arm is arm and r.semantics is sem]
    mean = statistics.fmean(diffs)
    se = statistics.stdev(diffs) / len(diffs) ** 0.5
    return mean, se


def test_take_profit_does_not_manufacture_alpha_on_a_calibrated_null(null_cohort):
    assert null_cohort.data_kind is DataKind.SYNTHETIC and null_cohort.label.startswith("SYNTHETIC")
    frictionless = cfg(fee_model=UnknownFeeModel("none", "frictionless null"), decision_latency=timedelta(0),
                       arrival_latency=timedelta(0), fill_rule=FillRule.TOUCH_UPPER_BOUND,
                       diagnostic_mode="FIRST_DETECTION_ZERO_LATENCY")
    rep = R.replay(null_cohort, frictionless)
    assert any(n.startswith("DIAGNOSTIC_MODE FIRST_DETECTION_ZERO_LATENCY") for n in rep.notes)
    assert rep.diagnostic_mode == "FIRST_DETECTION_ZERO_LATENCY" and not rep.after_cost_claim
    hold = [float(r.pnl_gross) / 100 + 0.30 for r in rep.entries if r.arm is Arm.HOLD]
    se_hold = statistics.stdev(hold) / len(hold) ** 0.5
    assert abs(statistics.fmean(hold) - 0.30) < 4 * se_hold  # calibrated: P(YES) = price
    for arm in (Arm.FULL_EXIT, Arm.PARTIAL_EXIT):
        for sem in Semantics:
            mean, se = _diff_bound(rep, arm, sem)
            assert se > 0 and abs(mean) < 4 * se, (arm, sem, mean, se)


def test_with_spread_and_fees_take_profit_only_loses_on_the_null(null_cohort):
    costly = cfg(decision_latency=timedelta(0), arrival_latency=timedelta(0), fill_rule=FillRule.TOUCH_UPPER_BOUND,
                 diagnostic_mode="FIRST_DETECTION_ZERO_LATENCY",
                 spread_haircut_ticks=1)
    rep = R.replay(null_cohort, costly)
    for arm in (Arm.FULL_EXIT, Arm.PARTIAL_EXIT):
        s = rep.arm(arm, Semantics.BOT_TRIGGERED)
        assert s.change_vs_hold_net is not None and s.change_vs_hold_net < 0
        mean, se = _diff_bound(rep, arm, Semantics.BOT_TRIGGERED)
        assert mean < 4 * se  # no gross gain either, beyond noise
    assert rep.after_cost_claim is False  # synthetic evidence never supports a claim


def test_strict_through_is_conservative_on_the_null(null_cohort):
    strict = cfg(fee_model=UnknownFeeModel("none", "frictionless null"), decision_latency=timedelta(0),
                 arrival_latency=timedelta(0), diagnostic_mode="FIRST_DETECTION_ZERO_LATENCY")
    rep = R.replay(null_cohort, strict)
    mean, se = _diff_bound(rep, Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT)
    assert mean < 4 * se  # selling at the limit only after the price is already through it cannot gain


@pytest.fixture(scope="module")
def realistic_null_cohort():
    # books every 5 s, so the default 1 s + 1 s latency finds a book at arrival (review of #125)
    return R.synthetic_martingale_cohort(seed=NULL_SEED, games=NULL_GAMES, step_seconds=5)


def test_no_pre_cost_alpha_at_realistic_latency(realistic_null_cohort):
    base = cfg(fee_model=UnknownFeeModel("none", "frictionless null"))  # defaults: 1 s decision + 1 s arrival
    assert base.diagnostic_mode is None and not base.zero_latency
    rep = R.replay(realistic_null_cohort, base)
    fills = [r for r in rep.entries if r.arm is Arm.FULL_EXIT and r.semantics is Semantics.BOT_TRIGGERED and r.sold]
    assert fills  # the latency path really fills; the null is not vacuous
    for arm in (Arm.FULL_EXIT, Arm.PARTIAL_EXIT):
        for sem in Semantics:
            mean, se = _diff_bound(rep, arm, sem)
            assert se > 0 and mean < 4 * se, (arm, sem, mean, se)  # no positive pre-cost alpha beyond noise


def test_zero_latency_is_refused_outside_the_labelled_diagnostic():
    with pytest.raises(ValueError, match="FIRST_DETECTION_ZERO_LATENCY"):
        R.replay(cohort(entry(REACH)), cfg(decision_latency=timedelta(0), arrival_latency=timedelta(0)))
    with pytest.raises(ValueError, match="diagnostic mode"):
        R.replay(cohort(entry(REACH)), cfg(diagnostic_mode="HINDSIGHT"))
    with pytest.raises(ValueError, match="negative"):
        R.replay(cohort(entry(REACH)), cfg(arrival_latency=-timedelta(seconds=1)))
    assert R.replay(cohort(entry(REACH)), cfg()).diagnostic_mode is None


def test_synthetic_generator_is_deterministic_and_labelled():
    a = R.synthetic_martingale_cohort(seed=1, games=5)
    b = R.synthetic_martingale_cohort(seed=1, games=5)
    assert a.sha256 == b.sha256 and a.sha256 != R.synthetic_martingale_cohort(seed=2, games=5).sha256
    assert all(e.settlement.value in (D(0), D(1)) for e in a.entries)
    with pytest.raises(ValueError):
        R.synthetic_martingale_cohort(seed=1, games=1, start=D("0.35"))
    assert replace(a).sha256 == a.sha256


# ------------------------------------------------------------------ game-state validity (source-state-v1, ADR 0041)


def _state(seconds, home=0, away=0, event="e0"):
    from edge_lab.inplay_evidence import GameState, GameStateStatus, Stamps

    return GameState("G1", "scores", event, Stamps(at(seconds), at(seconds)), GameStateStatus.OBSERVED,
                     f"raw-{event}-{seconds}", home_score=home, away_score=away, period="Q4")


def _journal(*states):
    from edge_lab.inplay_evidence import GameJournal

    j = GameJournal("G1")
    for s in states:
        j = j.append(s)
    return j


def test_a_recommendation_invalidated_before_submission_sends_nothing():
    # The bot sees the 0.70 bid at 60 s; a touchdown against YES is first seen at 60.5 s, before its order
    # would leave at 61 s. The book at 62 s has not caught up yet (0.72).
    books = [bk(0, [("0.30", "100")]), bk(60, [("0.70", "100")]), bk(62, [("0.72", "100")]),
             bk(90, [("0.30", "100")])]
    touchdown = _journal(_state(-5), _state(60.5, away=7, event="td"))
    plain = R.replay(cohort(entry(books)), cfg())
    with_state = R.replay(cohort(replace(entry(books), state_journal=touchdown)), cfg())
    blind = res(plain, "G1", Arm.FULL_EXIT, Semantics.BOT_TRIGGERED)
    aware = res(with_state, "G1", Arm.FULL_EXIT, Semantics.BOT_TRIGGERED)
    assert blind.sold == D(100) and blind.invalidated_before_submit == 0  # no journal: exactly as before
    assert aware.invalidated_before_submit == 1 and aware.sold == 0
    assert any(n.startswith("RECOMMENDATION_INVALIDATED_BEFORE_SUBMIT") and "MATERIAL_STATE_CHANGE" in n
               for n in aware.notes)
    assert aware.reconciliation == () and with_state.cohort_sha256 != plain.cohort_sha256


def test_a_state_change_after_the_order_left_cannot_recall_it():
    books = [bk(0, [("0.30", "100")]), bk(60, [("0.70", "100")]), bk(62, [("0.70", "100")])]
    late = _journal(_state(-5), _state(61.5, away=7, event="td"))  # seen after submission (61 s)
    rep = R.replay(cohort(replace(entry(books), state_journal=late)), cfg())
    bot = res(rep, "G1", Arm.FULL_EXIT, Semantics.BOT_TRIGGERED)
    assert bot.state_changed_in_flight == 1 and bot.invalidated_before_submit == 0
    assert bot.sold == D(100)  # it had already left: the IOC meets the book at arrival
    assert any(n.startswith("STATE_CHANGED_IN_FLIGHT") for n in bot.notes)


def test_a_preplaced_limit_is_not_a_bot_reactive_exit():
    # A touchdown for YES at 60.5 s moves the bids to 0.85. The resting sale at 0.70 cannot react and is
    # lifted (adverse selection); the bot decides on the new state and sells at the price at arrival.
    books = [bk(0, [("0.30", "100")]), bk(62, [("0.85", "100")]), bk(64, [("0.86", "100")])]
    td_for = _journal(_state(-5), _state(60.5, home=7, event="td"))
    rep = R.replay(cohort(replace(entry(books, "1"), state_journal=td_for)), cfg())
    rest = res(rep, "G1", Arm.FULL_EXIT, Semantics.PREPLACED_LIMIT)
    bot = res(rep, "G1", Arm.FULL_EXIT, Semantics.BOT_TRIGGERED)
    hold = res(rep, "G1", Arm.HOLD, None)
    assert rest.placed and rest.sold == D(100) and rest.gross_proceeds == D("70.00")
    assert rest.fills_after_state_change == 1
    assert any(n.startswith("RESTING_FILL_AFTER_STATE_CHANGE") for n in rest.notes)
    assert bot.sold == D(100) and bot.gross_proceeds == D("86.00") and bot.fills_after_state_change == 0
    assert hold.pnl_gross == D("70.00") and rest.pnl_gross == D("40.00") and bot.pnl_gross == D("56.00")
    # the two semantics stay separate arms; neither is a HINDSIGHT figure
    oracle = next(d for d in rep.diagnostics if d.label == "HINDSIGHT_UPPER_BOUND" and d.arm is Arm.FULL_EXIT)
    assert oracle.gross_proceeds == D("86.00") and all(a.arm is not None for a in rep.arms)


def test_a_state_journal_with_no_change_leaves_every_arm_unchanged():
    quiet = _journal(_state(-5))
    base = R.replay(cohort(entry(REACH, "0")), cfg())
    same = R.replay(cohort(replace(entry(REACH, "0"), state_journal=quiet)), cfg())
    for a, b in zip(base.entries, same.entries):
        assert (a.sold, a.pnl_gross, a.pnl_net) == (b.sold, b.pnl_gross, b.pnl_net)
        assert b.invalidated_before_submit == b.state_changed_in_flight == b.fills_after_state_change == 0



def test_the_cohort_hash_covers_the_parsed_state_and_is_unchanged_without_a_journal():
    from edge_lab.inplay_evidence import GameJournal, GameState, GameStateStatus, Stamps

    def g(first, home, raw):
        return GameState("G1", "scores", f"e{first}", Stamps(at(first), at(first)), GameStateStatus.OBSERVED, raw,
                         home_score=home, away_score=0, period="Q1")

    same_raw_0 = GameJournal("G1").append(g(5, 0, "rawA")).append(g(61, 0, "rawB"))
    same_raw_7 = GameJournal("G1").append(g(5, 0, "rawA")).append(g(61, 7, "rawB"))  # same raw hash, new score
    c0 = cohort(replace(entry(REACH, "0"), state_journal=same_raw_0))
    c7 = cohort(replace(entry(REACH, "0"), state_journal=same_raw_7))
    assert c0.sha256 != c7.sha256
    # no journal: the hash is exactly the pre-R2 one (books and entries only)
    import hashlib
    import json as _json

    plain = cohort(entry(REACH, "0"))
    h = hashlib.sha256(_json.dumps([plain.cohort_id, plain.data_kind.value, plain.label, str(plain.starting_capital),
                                    plain.horizon_utc, plain.rules_version]).encode())
    for e in plain.entries:
        h.update(_json.dumps([e.game_id, e.cluster_id, e.market_id, str(e.quantity), str(e.entry_price),
                              str(e.entry_cost), e.entry_at_utc, e.side, str(e.settlement.value), e.settlement.final,
                              e.settlement.at_utc]).encode())
        for b in e.books:
            h.update(f"{b.receipt_utc}|{b.status.value}|{b.trading_state.value}|{b.truncated}|{b.evidence_id}|"
                     f"{';'.join(f'{p}:{q}' for p, q in b.bids)}\n".encode())
    assert plain.sha256 == h.hexdigest()


def test_the_first_state_after_placement_is_chosen_by_first_observed_time():
    from edge_lab.inplay_evidence import GameJournal

    late, early = _state(40, event="late"), _state(20, event="early")
    j = GameJournal("G1").append(late).append(early)  # appended out of first-observed order
    assert R._first_state_after(j, parse_dt(at(10))).observation_id == early.observation_id


def parse_dt(value):
    from edge_lab.freshness import parse_utc

    return parse_utc(value)
