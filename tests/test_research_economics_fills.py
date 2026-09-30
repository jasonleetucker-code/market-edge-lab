"""Fill-conditioned economics (fill-conditioned-economics-v1, R2 / #145, ADR 0041). Seeded synthetic data only."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from edge_lab import research_economics as E
from edge_lab.inplay_evidence import DataKind, EvidenceStatus, Phase, SourceContext
from edge_lab.research_economics import (
    Basis, ExecutionMode, Fill, FunnelRecord, Labeled, MarkoutSpec, Resolution, TurnoverBasis,
)

W0 = datetime(2026, 10, 4, tzinfo=timezone.utc)
CTX = SourceContext("NFL", "moneyline", Phase.LIVE, "REGULAR_SEASON")
FIXED = Labeled(D("100"), Basis.OWNER_INPUT, "fixture fixed cash costs")
HOURS = Labeled(D("6"), Basis.OWNER_INPUT, "fixture owner hours")


def at(minutes: float) -> str:
    return (W0 + timedelta(minutes=minutes)).isoformat()


def fill(fid, inst, side, q, p, *, fee="0", mode=ExecutionMode.TAKER, minute=0.0, peak=False, keys=(), rebate="0",
         promotion="0", evidence=EvidenceStatus.SIMULATED, kind=DataKind.SYNTHETIC, **kw):
    return Fill(fid, mode, evidence, kind, inst, side, D(q), D(p), None if fee is None else D(fee), at(minute), CTX,
                exposure_keys=tuple(keys), season="2026-REG", peak=peak, rebate=D(rebate), promotion=D(promotion),
                **kw)


def settle(value, minute):
    return Resolution(None if value is None else D(value), at(minute))


def econ(fills, resolutions, *, capital="10000", days=30, basis=TurnoverBasis.TOTAL_CAPITAL, fixed=FIXED):
    return E.fill_economics(fills, resolutions=resolutions, window_start_utc=at(0),
                            window_end_utc=at(days * 1440), total_capital=D(capital), fixed_cash_costs=fixed,
                            owner_hours=HOURS, turnover_basis=basis)


def _price(rng, lo=20, hi=80):
    return D(rng.randint(lo, hi)) / 100


# ------------------------------------------------------------------ 1. fair-price, no-alpha null


def _fair_null(seed, n, fee):
    """We make at exactly the true probability; takers are uninformed and outcomes follow the probability."""
    rng = random.Random(seed)
    fills, res, var = [], {}, D(0)
    for i in range(n):
        p = _price(rng)
        side = "SELL" if rng.random() < 0.5 else "BUY"
        fills.append(fill(f"s{seed}-f{i}", f"s{seed}-M{i}", side, "10", p, fee=fee, mode=ExecutionMode.BOOK_MAKER,
                          minute=i))
        res[f"s{seed}-M{i}"] = settle(1 if rng.random() < float(p) else 0, i + 60)
        var += D(100) * p * (1 - p)
    return fills, res, var


def test_fair_price_no_alpha_null_has_no_gross_edge_and_loses_its_fees():
    total_gross = total_net = total_var = D(0)
    for seed in range(8):
        fills, res, var = _fair_null(seed, 1500, "0.02")
        r = econ(fills, res, days=2)
        assert r.total_gross is not None and r.fees == D("0.02") * 1500
        assert r.net_contribution == r.total_gross - r.fees  # each fee once
        total_gross += r.total_gross
        total_net += r.net_contribution
        total_var += var
    sd = D(math.sqrt(float(total_var)))
    assert abs(total_gross) < 4 * sd, (total_gross, sd)  # fair prices: no edge before costs
    assert total_net < 0  # expected -fees (-240): costs make a no-alpha maker lose


# ------------------------------------------------------------------ 2. informed flow selects our quotes


def _informed(seed, n):
    rng = random.Random(seed)
    fills, res, bench, funnel, hypothetical_edge = [], {}, {}, [], D(0)
    for i in range(n):
        p = _price(rng, 25, 75)
        m = p + D(rng.randint(-8, 8)) / 100  # our estimate is noisy
        bid, ask = m - D("0.02"), m + D("0.02")
        hypothetical_edge += D(10) * D("0.02")  # every quote looks attractive against our own estimate
        inst = f"M{i}"
        side = "SELL" if p > ask else ("BUY" if p < bid else None)  # the informed taker picks us off
        funnel.append(FunnelRecord(inst, ExecutionMode.BOOK_MAKER, CTX, EvidenceStatus.SIMULATED, DataKind.SYNTHETIC,
                                   eligible=True, hypothetical_quote=True, own_quote=True, filled=side is not None))
        if side is None:
            continue
        price = ask if side == "SELL" else bid
        fills.append(fill(f"f{i}", inst, side, "10", price, mode=ExecutionMode.BOOK_MAKER, minute=i))
        res[inst] = settle(1 if rng.random() < float(p) else 0, i + 60)
        bench[f"f{i}"] = p  # synthetic fair value at the horizon
    return fills, res, bench, funnel, hypothetical_edge


def test_informed_traders_accepting_attractive_quotes_produce_a_loss():
    fills, res, bench, funnel, hypothetical_edge = _informed(7, 6000)
    assert hypothetical_edge > 0
    r = econ(fills, res, days=6)
    assert r.fills > 0 and r.total_gross < 0  # E[profit | our fills] is negative: adverse selection
    marks = E.markouts(fills, bench, MarkoutSpec(timedelta(minutes=60), "SYNTHETIC_TRUE_PROBABILITY"))
    assert all(m.value < 0 for m in marks) and all(not m.is_liquidation_profit for m in marks)
    f = E.funnel_report(funnel)
    assert f.stages["FILLED"]["no"] > 0
    assert f.own_fill_rate is None  # no ACTUAL own quote: a simulator's rate is not an execution probability
    assert f.simulated_own_fill_rate == (D(len(fills)) / 6000).quantize(D("1e-12"))
    assert "not an execution probability" in f.simulated_own_fill_rate_reason


# ------------------------------------------------------------------ 3. a nonfill earns no spread; unknown is not a nonfill


def test_a_nonfill_cannot_earn_spread_and_hypothetical_quotes_are_not_fills():
    with pytest.raises(ValueError, match="not a fill"):
        fill("h", "M", "SELL", "10", "0.55", evidence=EvidenceStatus.HYPOTHETICAL)
    with pytest.raises(ValueError, match="not a fill"):
        fill("u", "M", "SELL", "10", "0.55", evidence=EvidenceStatus.UNAVAILABLE, kind=None)
    r = econ([], {})
    assert r.fills == 0 and r.total_gross == 0 and r.net_contribution == 0 and r.notional == 0
    hyp = (EvidenceStatus.HYPOTHETICAL, DataKind.SYNTHETIC)
    records = [FunnelRecord("r1", ExecutionMode.RFQ, CTX, *hyp, eligible=True, hypothetical_quote=True, own_quote=False),
               FunnelRecord("r2", ExecutionMode.RFQ, CTX, *hyp, eligible=True, hypothetical_quote=True, own_quote=None)]
    f = E.funnel_report(records)
    assert f.own_fill_rate is None and f.own_fill_rate_reason.startswith("NO_ACTUAL_OWN_QUOTES")
    assert "hypothetical" not in f.own_fill_rate_reason
    with pytest.raises(ValueError, match="has no own quote"):
        FunnelRecord("r3", ExecutionMode.RFQ, CTX, *hyp, own_quote=True)
    assert f.stages["ACCEPTED"] == {"yes": 0, "no": 0, "unknown": 2}  # unobservable, never "not accepted"


def test_unknown_outcomes_give_no_execution_probability():
    act = (EvidenceStatus.ACTUAL, DataKind.RECORDED)
    records = [FunnelRecord("a", ExecutionMode.BOOK_MAKER, CTX, *act, own_quote=True, filled=True),
               FunnelRecord("b", ExecutionMode.BOOK_MAKER, CTX, *act, own_quote=True, filled=None)]
    f = E.funnel_report(records)
    assert f.own_fill_rate is None and f.own_fill_rate_reason.startswith("UNKNOWN_OUTCOMES")
    assert f.stages["FILLED"] == {"yes": 1, "no": 0, "unknown": 1}
    with pytest.raises(ValueError, match="someone else's flow"):
        FunnelRecord("c", ExecutionMode.RFQ, CTX, *act, own_quote=False, accepted=True)
    with pytest.raises(ValueError, match="accepted is not filled"):
        FunnelRecord("d", ExecutionMode.RFQ, CTX, *act, own_quote=True, accepted=True, confirmed=False, filled=True)
    with pytest.raises(ValueError, match="cannot be ACTUAL"):
        FunnelRecord("e", ExecutionMode.RFQ, CTX, EvidenceStatus.ACTUAL, DataKind.FIXTURE)
    observed = E.funnel_report([FunnelRecord("a", ExecutionMode.BOOK_MAKER, CTX, *act, own_quote=True, filled=True),
                                FunnelRecord("b", ExecutionMode.BOOK_MAKER, CTX, *act, own_quote=True, filled=False)])
    assert observed.own_fill_rate == D("0.5") and observed.by_evidence == {"ACTUAL": 2}


# ------------------------------------------------------------------ 4. a copied price is not the original portfolio


def test_a_copied_price_subset_does_not_inherit_the_complete_portfolio():
    rng = random.Random(11)
    original, copied, res = [], [], {}
    for i in range(500):
        home_wins = rng.random() < 0.40
        game = f"game:{i}"
        res[f"HOME{i}"] = settle(1 if home_wins else 0, i + 120)
        res[f"AWAY{i}"] = settle(0 if home_wins else 1, i + 120)  # complements: exactly one pays
        original += [fill(f"o-h{i}", f"HOME{i}", "BUY", "10", "0.50", minute=i, keys=(game,)),
                     fill(f"o-a{i}", f"AWAY{i}", "BUY", "10", "0.45", minute=i, keys=(game,))]
        copied.append(fill(f"c-h{i}", f"HOME{i}", "BUY", "10", "0.50", minute=i, keys=(game,)))  # hedge price gone
    whole = econ(original, res, days=2)
    subset = econ(copied, {k: v for k, v in res.items() if k.startswith("HOME")}, days=2)
    assert whole.total_gross == D("0.05") * 10 * 500  # the complete portfolio: +0.05 per pair, every time
    assert subset.total_gross < 0  # the copied leg alone: -0.10 per contract in expectation


# ------------------------------------------------------------------ 5. incentives cannot hide unsubsidized losses


def test_incentives_cannot_hide_negative_unsubsidized_trading():
    fills = [fill("f1", "M1", "BUY", "10", "0.50", fee="0.10", rebate="3", promotion="3")]
    r = econ(fills, {"M1": settle(0, 60)})
    assert r.net_contribution == D("-5.10") and r.unsubsidized_negative is True
    assert r.subsidized_net == D("0.90") and r.rebates == D(3) and r.promotions == D(3)
    assert any(x.startswith("SUBSIDY_MASKS_LOSS") for x in r.reasons)
    assert r.net_after_fixed.value == D("-105.10")  # fixed costs come off the unsubsidized figure
    assert r.owner_hours.value == D(6) and r.owner_hours_priced is False


# ------------------------------------------------------------------ 6. peak throughput is not annualized


def test_peak_event_throughput_is_not_annualized_year_round():
    fills = [fill("f1", "M1", "BUY", "10", "0.40", peak=True)]
    r = econ(fills, {"M1": settle(1, 60)})
    s = E.seasonal_scenario(r, active_days_per_year=D(365))
    assert s.value is None and "PEAK_NOT_ANNUALIZED" in s.note
    off = econ([fill("f1", "M1", "BUY", "10", "0.40", peak=False)], {"M1": settle(1, 60)})
    s2 = E.seasonal_scenario(off, active_days_per_year=D(120))
    assert s2.value == (D(6) * 120 / 30).quantize(D("1e-12"))  # scaled to the season, not to 365
    unknown = econ([fill("f1", "M1", "BUY", "10", "0.40", peak=None)], {"M1": settle(1, 60)})
    assert "SEASON_UNKNOWN" in E.seasonal_scenario(unknown, active_days_per_year=D(120)).note


# ------------------------------------------------------------------ 7. residual inventory and common exposure


def test_residual_inventory_and_common_exposure_stay_accounted_for():
    fills = [fill("x1", "X-HOME", "BUY", "10", "0.40", keys=("game:X",)),
             fill("x2", "X-OVER", "BUY", "10", "0.30", minute=1, keys=("game:X",)),
             fill("y1", "Y", "BUY", "10", "0.40", minute=2), fill("y2", "Y", "SELL", "10", "0.50", minute=3)]
    r = econ(fills, {})
    assert r.realized_gross == D("1.00") and r.total_gross is None and r.net_contribution is None
    assert {p.instrument_id for p in r.open_positions} == {"X-HOME", "X-OVER"}
    assert r.open_worst_case_loss == D("7.00") and r.exposure_by_key == {"game:X": D("7.00")}
    assert r.peak_collateral == D("11.00")  # both open legs plus Y before it closed
    assert r.capital_days > D("7") * 29  # the open legs hold their collateral to the window end
    assert any(x.startswith("RESIDUAL_INVENTORY") for x in r.reasons)
    assert r.return_on_deployed is None and r.return_on_total is None  # no return while P&L is incomplete


# ------------------------------------------------------------------ accounting guards


def test_recycled_principal_is_not_profit():
    fills = []
    for k in range(5):
        fills += [fill(f"b{k}", "M", "BUY", "10", "0.40", minute=10 * k),
                  fill(f"s{k}", "M", "SELL", "10", "0.50", minute=10 * k + 5)]
    r = econ(fills, {}, basis=TurnoverBasis.AVERAGE_DEPLOYED)
    assert r.total_gross == D("5.00")  # five round trips of +1, not 25 of proceeds
    assert r.peak_collateral == D("4.00")  # the same 4 dollars reused in sequence, never at once
    assert r.notional == D("45.00") and r.turnover_basis == "AVERAGE_DEPLOYED"
    assert r.turnover == (r.notional / r.average_deployed).quantize(D("1e-12"))
    total = econ(fills, {}, basis=TurnoverBasis.TOTAL_CAPITAL)
    assert total.turnover == (D("45") / D("10000")).quantize(D("1e-12")) and total.turnover_denominator == D(10000)


def test_each_fee_is_subtracted_once():
    with pytest.raises(ValueError, match="DOUBLE_FEE"):
        fill("f", "M", "BUY", "10", "0.40", fee="0.10", fee_included_in_price=True)
    one = fill("f", "M", "BUY", "10", "0.40", fee="0.10")
    r = econ([one, one], {"M": settle(1, 60)})  # the same fill reported twice
    assert r.fills == 1 and r.duplicate_fills_ignored == 1 and r.fees == D("0.10")
    assert r.net_contribution == D("5.90")
    with pytest.raises(ValueError, match="DUPLICATE_FILL_ID"):
        econ([one, fill("f", "M", "BUY", "10", "0.41", fee="0.10")], {})


def test_shared_depth_and_capital_are_never_used_twice():
    a = fill("a", "M", "BUY", "60", "0.40", liquidity_ref="book:M:0.40", liquidity_available=D(100))
    b = fill("b", "M2", "BUY", "60", "0.40", minute=1, liquidity_ref="book:M:0.40", liquidity_available=D(100))
    with pytest.raises(ValueError, match="SHARED_DEPTH_REUSED"):
        econ([a, b], {})
    with pytest.raises(ValueError, match="CAPITAL_OVERCOMMITTED"):
        econ([fill("a", "M", "BUY", "60", "0.50"), fill("b", "M2", "BUY", "60", "0.50", minute=1)], {}, capital="50")
    econ([fill("a", "M", "BUY", "60", "0.50"), fill("b", "M2", "BUY", "60", "0.50", minute=1)], {}, capital="60")


def test_unknown_fee_scope_blocks_net_but_keeps_labelled_gross():
    r = econ([fill("f", "M", "BUY", "10", "0.40", fee=None)], {"M": settle(1, 60)})
    assert r.total_gross == D("6.00") and r.fees is None and r.net_contribution is None
    assert r.subsidized_net is None and r.net_after_fixed.value is None and r.return_on_total is None
    assert r.gross_label.startswith("GROSS_DIAGNOSTIC") and any(x.startswith("FEE_SCOPE_UNKNOWN") for x in r.reasons)


def test_actual_and_simulated_fills_are_never_mixed():
    actual = fill("a", "M", "BUY", "10", "0.40", evidence=EvidenceStatus.ACTUAL, kind=DataKind.RECORDED)
    sim = fill("s", "M2", "BUY", "10", "0.40")
    with pytest.raises(ValueError, match="never mixed"):
        econ([actual, sim], {})
    with pytest.raises(ValueError, match="cannot be ACTUAL"):
        fill("x", "M", "BUY", "10", "0.40", evidence=EvidenceStatus.ACTUAL, kind=DataKind.SYNTHETIC)
    assert econ([actual], {"M": settle(1, 60)}).evidence == "ACTUAL"


def test_modes_are_reported_separately_and_mixed_instruments_are_not_split_by_guess():
    fills = [fill("t", "M", "BUY", "10", "0.40", mode=ExecutionMode.TAKER),
             fill("m", "M", "SELL", "10", "0.50", mode=ExecutionMode.BOOK_MAKER, minute=5),
             fill("r", "R", "SELL", "10", "0.60", mode=ExecutionMode.RFQ, minute=6)]
    r = econ(fills, {"R": settle(0, 60)})
    groups = {g.key[0]: g for g in r.groups}
    assert set(groups) == {"TAKER", "BOOK_MAKER", "RFQ"}
    assert groups["TAKER"].gross_pnl is None and groups["BOOK_MAKER"].gross_pnl is None  # one trade, two modes
    assert groups["RFQ"].gross_pnl == D("6.00") and any(x.startswith("MODES_SEPARATE") for x in r.reasons)
    assert r.total_gross == D("7.00")


def test_a_favourable_markout_is_not_liquidation_profit():
    buy, sell = fill("b", "M", "BUY", "10", "0.40"), fill("s", "M", "SELL", "10", "0.40", minute=1)
    marks = E.markouts([buy, sell], {"b": D("0.45"), "s": D("0.45")}, MarkoutSpec(timedelta(minutes=5), "MID"))
    assert [m.value for m in marks] == [D("0.50"), D("-0.50")]  # signed by trade direction
    thin_bids = ((D("0.30"), D("5")), (D("0.35"), D("5")))
    assert E.liquidation_value(D(10), thin_bids) == D("3.25") < D("4.50")  # the mark is not what selling gets
    assert E.liquidation_value(D(20), thin_bids) is None
    assert E.markouts([buy], {}, MarkoutSpec(timedelta(minutes=5), "MID"))[0].value is None
    with pytest.raises(ValueError):
        MarkoutSpec(timedelta(0), "MID")
    with pytest.raises(ValueError):
        MarkoutSpec(timedelta(minutes=5), "")



# ------------------------------------------------------------------ review fixes


def test_capital_lost_at_settlement_is_not_spent_again():
    fills = [fill("f1", "M1", "BUY", "200", "0.50", minute=0), fill("f2", "M2", "BUY", "200", "0.50", minute=120)]
    with pytest.raises(ValueError, match="CAPITAL_OVERCOMMITTED"):
        econ(fills, {"M1": settle(0, 60), "M2": settle(0, 180)}, capital="100", days=1)
    # the same second buy is fine when the first position won its capital back
    r = econ(fills, {"M1": settle(1, 60), "M2": settle(0, 180)}, capital="100", days=1)
    assert r.total_gross == D("0")


def test_a_realized_loss_is_the_same_by_settlement_or_by_closing_trade():
    round_trip = [fill("g1", "M1", "BUY", "100", "0.50", minute=0), fill("g2", "M1", "SELL", "100", "0.10", minute=60)]
    settled = [fill("h1", "M1", "BUY", "100", "0.50", minute=0)]
    a = econ(round_trip, {}, capital="100", days=1)
    b = econ(settled, {"M1": Resolution(D("0.10"), at(60))}, capital="100", days=1)
    assert a.net_contribution == b.net_contribution == D("-40.00")
    assert a.capital_days == b.capital_days and a.average_deployed == b.average_deployed
    assert a.return_on_deployed == b.return_on_deployed and a.return_on_total == b.return_on_total
    assert a.open_positions == b.open_positions == ()
    for base, extra in ((round_trip, {}), (settled, {"M1": Resolution(D("0.10"), at(60))})):
        with pytest.raises(ValueError, match="CAPITAL_OVERCOMMITTED"):  # 60 left, a 95 buy does not fit
            econ(base + [fill("z", "M3", "BUY", "190", "0.50", minute=120)], extra, capital="100", days=1)
        econ(base + [fill("z", "M3", "BUY", "120", "0.50", minute=120)], extra, capital="100", days=1)


def test_resolution_is_a_binary_payout_and_a_fee_inside_the_price_is_known():
    for bad in ("5", "-0.1", "1.01"):
        with pytest.raises(ValueError, match="between 0 and 1"):
            Resolution(D(bad), at(1))
    inside = fill("f", "M", "BUY", "10", "0.41", fee=None, fee_included_in_price=True)
    assert inside.fee == D(0)
    r = econ([inside], {"M": settle(1, 60)})
    assert r.fees == D(0) and r.net_contribution == D("5.90")


def test_adverse_selection_holds_in_a_mixed_informed_and_uninformed_population():
    rng = random.Random(3)
    fills, res, bench = [], {}, {}
    for i in range(6000):
        p = _price(rng, 25, 75)
        m = p + D(rng.randint(-8, 8)) / 100
        bid, ask = m - D("0.02"), m + D("0.02")
        if rng.random() < 0.5:  # informed: trades only when our quote is wrong in its favour
            side = "SELL" if p > ask else ("BUY" if p < bid else None)
        else:  # uninformed: hits either side at random
            side = rng.choice(("SELL", "BUY"))
        if side is None:
            continue
        fills.append(fill(f"f{i}", f"M{i}", side, "10", ask if side == "SELL" else bid, minute=i))
        res[f"M{i}"] = settle(1 if rng.random() < float(p) else 0, i + 60)
        bench[f"f{i}"] = p
    marks = E.markouts(fills, bench, MarkoutSpec(timedelta(minutes=60), "SYNTHETIC_TRUE_PROBABILITY"))
    assert sum(m.value for m in marks) < 0  # the informed half costs more than the spread earns on the rest
    assert econ(fills, res, days=6).total_gross < 0



def test_a_zero_simulated_fill_rate_is_still_labelled_as_a_simulator_output():
    sim = (EvidenceStatus.SIMULATED, DataKind.SYNTHETIC)
    f = E.funnel_report([FunnelRecord("a", ExecutionMode.BOOK_MAKER, CTX, *sim, own_quote=True, filled=False),
                         FunnelRecord("b", ExecutionMode.BOOK_MAKER, CTX, *sim, own_quote=True, filled=False)])
    assert f.simulated_own_fill_rate == D(0) and f.own_fill_rate is None
    assert f.simulated_own_fill_rate_reason.endswith("SIMULATED: a simulator's output, not an execution probability")
