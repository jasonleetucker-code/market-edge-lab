"""Pure same-venue payoff evaluator (EXP-003): a valid complete set, and every required counterexample."""

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from edge_lab.fee_schedules import get_fee_schedule
from edge_lab.opportunity import (
    KALSHI_BINARY_UNITS, NOVIG_V3_UNITS, DepthLadder, DepthLevel, Event, Market, MarketStatus, MarketTiming, Payoff,
)
from edge_lab.payoff_constraints import (
    ACTUAL_RESULT, PROHIBITED_MARKET_FIELDS, SIMULATED_EXECUTION, Cell, Claim, Leg, RelationshipSet, SettlementState,
    StateKind, StateProof, evaluate, fair_price_fallback, fallback_cell, integer_value_states, kalshi_partition_set,
    numeric_cells, numeric_contract, refund_price_and_fees, refund_purchase_price, rules_template_sha256,
    scan_kalshi_store, size_points, zero_cost,
)

FIXTURES = Path(__file__).parent / "fixtures" / "forward"
T = "2026-09-24T12:00:00Z"
AS_OF = "2026-09-24T12:00:30Z"
AGE, SKEW = timedelta(minutes=5), timedelta(seconds=60)
FEES = get_fee_schedule("kalshi-quadratic-taker-v1")
EVENT = Event("weather", "kalshi:KXHIGHNY-26SEP24", "2026-09-24", None, "KXHIGHNY-26SEP24", "twc-central-park-v1")
ALL_EXCLUDED = StateProof({k: "fixture: excluded by construction" for k in StateKind if k is not StateKind.NORMAL})
CONTRACTS = {  # a complete integer partition: <65, 65-66, 67-68, >68
    "T65": numeric_contract("less", None, 65),
    "B65.5": numeric_contract("between", 65, 66),
    "B67.5": numeric_contract("between", 67, 68),
    "T68": numeric_contract("greater", 68, None),
}


def market(code):
    native = f"KXHIGHNY-26SEP24-{code}"
    return Market("kalshi", f"kalshi:{native}", native, EVENT.event_id, code, Payoff("binary", D(1), code),
                  f"rules-{code}", MarketStatus.OPEN, True, "fixture rules",
                  timing=MarketTiming(expected_resolution_utc="2026-09-25T12:00:00Z",
                                      latest_resolution_utc="2026-12-25T15:00:00Z"))


def ladder(code, side, *levels, t=T, truncated=False):
    m = market(code)
    return DepthLadder("kalshi", m.market_id, side, tuple(DepthLevel(D(p), D(s)) for p, s in levels), truncated, t,
                       None, f"snap:{code}:{side}")


def partition(prices=None, contracts=None, states_extra=(), proof=ALL_EXCLUDED, legs_over=None, **kw):
    contracts = contracts or CONTRACTS
    prices = prices or {c: "0.20" for c in contracts}
    normal = integer_value_states(contracts.values())
    states = tuple(normal) + tuple(states_extra)
    legs = []
    for code, contract in contracts.items():
        payouts = numeric_cells(contract, "YES", normal)
        for s in states_extra:
            payouts[s.state_id] = Cell(D(0)) if not s.variables else fallback_cell(market(code).market_id, "YES")
        leg = Leg(EVENT, market(code), "YES", ladder(code, "YES", (prices[code], 50)), FEES, KALSHI_BINARY_UNITS,
                  payouts, structured_contract=contract, rules_contract=contract, settlement_cost=zero_cost)
        if legs_over:
            leg = legs_over(code, leg)
        legs.append(leg)
    return RelationshipSet("set", "PARTITION", tuple(legs), states, proof, basket_settlement_cost=lambda s, f: D(0),
                           **kw)


def run(rel, sizes=(1,), as_of=AS_OF):
    return evaluate(rel, sizes=[D(s) for s in sizes], as_of_utc=as_of, max_quote_age=AGE, max_leg_skew=SKEW)


# --------------------------------------------------------------------------- the valid set


def test_a_genuinely_valid_complete_set_has_a_conditional_full_fill_surplus():
    ev = run(partition())
    assert ev.relationship == "PROVEN" and ev.quote_validity == "VALID"
    assert ev.observed_quote_inconsistency == D("0.20")  # 1 - 4 x 0.20, pre-fee, top of book
    (row,) = ev.sizes
    # Each leg: 1 contract at 0.20; fee 0.07*0.2*0.8 = 0.0112 -> cash floor-to-cent 0.22 (fees once, per fill).
    assert row.acquisition_cost == D("0.88") and row.fees == D("0.08")  # fees plus cent rounding
    assert row.min_full_fill_payout == D(1) and row.worst_state_surplus == D("0.12")
    assert row.claim == Claim.CONDITIONAL_FULL_FILL_SURPLUS.value
    assert row.claim_adjusted_surplus == D("0.12") - D("0.0101") * 4  # CONSERVATIVE_BOUND allowance (ADR 0017)
    assert all(v < 0 for v in row.orphan_exposure.values())  # one leg alone can lose everything it paid
    assert row.orphan_exposure["kalshi:KXHIGHNY-26SEP24-T65/YES"] == D("-0.22")
    assert ev.simulated_execution == SIMULATED_EXECUTION and ev.actual_result == ACTUAL_RESULT
    assert "not captured arbitrage" in " ".join(row.claim_reasons)
    assert run(partition()).evaluation_sha256 == ev.evaluation_sha256  # deterministic


def test_size_points_feed_the_economic_screen_without_inflating_a_bound():
    points = size_points(run(partition(), sizes=(1, 100)))
    assert points[0].net_edge_per_unit == (D("0.12") - D("0.0404")) and points[0].all_in_cost_per_unit == D("0.88")
    assert points[1].depth_status == "NOT_EVALUATED" and points[1].net_edge_per_unit is None  # 100 > 50 offered


# --------------------------------------------------------------------------- counterexamples


def test_missing_tail_is_not_exhaustive():
    contracts = {k: v for k, v in CONTRACTS.items() if k != "T68"}
    ev = run(partition(contracts=contracts))
    assert ev.relationship == "UNSUPPORTED" and ev.sizes == ()
    assert any("not exhaustive" in r for r in ev.relationship_reasons)


def test_overlapping_ranges_are_not_exclusive():
    contracts = dict(CONTRACTS, **{"B65.5": numeric_contract("between", 65, 67)})
    ev = run(partition(contracts=contracts))
    assert ev.relationship == "UNSUPPORTED" and any("overlap" in r for r in ev.relationship_reasons)


def test_wrong_threshold_inclusivity_is_refused():
    wrong = replace(CONTRACTS["T68"], low_inclusive=True)  # ">= 68" instead of Kalshi's strict "> 68"

    def bad(code, leg):
        return replace(leg, structured_contract=wrong, rules_contract=wrong) if code == "T68" else leg

    ev = run(partition(legs_over=bad))
    assert ev.relationship == "UNSUPPORTED" and any("inclusivity" in r for r in ev.relationship_reasons)

    def disagree(code, leg):
        return replace(leg, rules_contract=numeric_contract("between", 67, 69)) if code == "B67.5" else leg

    ev2 = run(partition(legs_over=disagree))
    assert any("disagree with the captured rules" in r for r in ev2.relationship_reasons)


def test_changed_station_window_or_rules_breaks_the_set():
    def moved(code, leg):
        return replace(leg, event=replace(EVENT, settlement_identity="twc-laguardia-v1")) if code == "B67.5" else leg

    ev = run(partition(legs_over=moved))
    assert ev.relationship == "UNSUPPORTED" and any("settlement identities" in r for r in ev.relationship_reasons)

    def unresolved(code, leg):
        return replace(leg, market=replace(leg.market, rules_resolved=False)) if code == "T65" else leg

    assert run(partition(legs_over=unresolved)).relationship == "UNSUPPORTED"


@pytest.mark.parametrize("t, as_of, why", [
    ("2026-09-24T11:50:00Z", AS_OF, "stale"),
    ("2026-09-24T12:05:00Z", AS_OF, "lookahead"),
])
def test_stale_or_future_quotes_are_invalid(t, as_of, why):
    def aged(code, leg):
        return replace(leg, ladder=replace(leg.ladder, received_at_utc=t)) if code == "B65.5" else leg

    ev = run(partition(legs_over=aged), as_of=as_of)
    assert ev.quote_validity == "INVALID" and ev.sizes == () and any(why in r for r in ev.quote_reasons)


def test_non_overlapping_quote_times_are_invalid():
    def skewed(code, leg):
        return replace(leg, ladder=replace(leg.ladder, received_at_utc="2026-09-24T11:58:00Z")) if code == "T68" else leg

    ev = run(partition(legs_over=skewed))
    assert ev.quote_validity == "INVALID" and any("do not overlap" in r for r in ev.quote_reasons)


def test_incomplete_or_truncated_depth_is_not_evaluated():
    def thin(code, leg):
        if code == "T65":
            return replace(leg, ladder=ladder(code, "YES", ("0.20", 3), truncated=True))
        if code == "B65.5":
            return replace(leg, ladder=ladder(code, "YES", ("0.20", 4)))
        return leg

    ev = run(partition(legs_over=thin), sizes=(1, 5))
    small, big = ev.sizes
    assert small.claim == Claim.CONDITIONAL_FULL_FILL_SURPLUS.value
    assert big.claim == Claim.NOT_EVALUATED.value and not big.evaluated
    reasons = " ".join(big.claim_reasons)
    assert "DEPTH_UNKNOWN" in reasons and "INSUFFICIENT_DEPTH" in reasons
    assert big.limiting_leg == "kalshi:KXHIGHNY-26SEP24-T65/YES"


def test_one_cent_and_dollar_contracts_are_never_mixed():
    def cents(code, leg):
        return replace(leg, units=NOVIG_V3_UNITS) if code == "T65" else leg

    ev = run(partition(legs_over=cents))
    assert ev.relationship == "UNSUPPORTED" and any("differs" in r for r in ev.relationship_reasons)
    all_cents = run(partition(legs_over=lambda code, leg: replace(leg, units=NOVIG_V3_UNITS)))
    assert any("not $1 contracts" in r for r in all_cents.relationship_reasons)


def test_fees_can_erase_a_pre_fee_surplus():
    ev = run(partition(prices={"T65": "0.24", "B65.5": "0.24", "B67.5": "0.24", "T68": "0.25"}))
    (row,) = ev.sizes
    assert ev.observed_quote_inconsistency == D("0.03") and row.worst_state_surplus_before_fees == D("0.03")
    assert row.worst_state_surplus < 0 and row.claim == Claim.NO_SURPLUS_AFTER_FEES.value


def test_duplicated_synthetic_liquidity_is_refused():
    rel = partition()
    dup = replace(rel, legs=rel.legs + (rel.legs[0],))
    ev = run(dup)
    assert ev.relationship == "UNSUPPORTED" and any("duplicate synthetic liquidity" in r for r in ev.relationship_reasons)


def test_a_refund_state_breaks_the_naive_proof():
    void = SettlementState("void", StateKind.VOID, "market voided: purchase price refunded")
    proof = StateProof({k: "fixture" for k in StateKind if k not in (StateKind.NORMAL, StateKind.VOID)})

    def refunds(fn):
        return lambda code, leg: replace(leg, refunds={"void": fn})

    price_only = run(partition(states_extra=(void,), proof=proof, legs_over=refunds(refund_purchase_price)))
    (row,) = price_only.sizes
    assert row.worst_state == "void" and row.worst_state_surplus == -row.fees == D("-0.08")  # fees lost in a void
    assert row.claim == Claim.NO_SURPLUS_EVEN_BEFORE_FEES.value  # a void returns only the price: never a profit
    full = run(partition(states_extra=(void,), proof=proof, legs_over=refunds(refund_price_and_fees)))
    assert full.sizes[0].worst_state_surplus == 0 and full.sizes[0].claim != Claim.CONDITIONAL_FULL_FILL_SURPLUS.value
    unknown = run(partition(states_extra=(void,), proof=proof))  # no refund rule: the proof is incomplete
    assert unknown.relationship == "INCOMPLETE" and unknown.sizes[0].states_skipped == ("void",)
    assert unknown.sizes[0].claim == Claim.SURPLUS_NOT_CLAIMABLE.value  # positive elsewhere, never claimed


def test_a_discretionary_fair_price_fallback_leaves_no_guaranteed_surplus():
    fallback = fair_price_fallback([market(c).market_id for c in CONTRACTS], description="last fair price")
    proof = StateProof({k: "fixture" for k in StateKind if k not in (StateKind.NORMAL, StateKind.FALLBACK)})
    ev = run(partition(states_extra=(fallback,), proof=proof))
    (row,) = ev.sizes
    assert ev.relationship == "PROVEN" and row.worst_state == "fallback_fair_price"
    assert row.min_full_fill_payout == 0 and row.claim == Claim.NO_SURPLUS_EVEN_BEFORE_FEES.value


def test_only_one_leg_filling_is_reported_as_orphan_exposure():
    (row,) = run(partition()).sizes
    assert set(row.orphan_exposure) == {f"kalshi:KXHIGHNY-26SEP24-{c}/YES" for c in CONTRACTS}
    assert max(row.orphan_exposure.values()) < 0


def test_an_unknown_settlement_cost_blocks_the_claim_but_keeps_an_upper_bound():
    ev = run(partition(legs_over=lambda code, leg: replace(leg, settlement_cost=None)))
    (row,) = ev.sizes
    assert row.worst_state_surplus is None and row.upper_bound_if_unknown_settlement_costs_zero == D("0.12")
    assert row.claim == Claim.SURPLUS_NOT_CLAIMABLE.value


def test_sell_legs_and_non_allowlisted_kinds_are_refused():
    rel = partition()
    short = replace(rel, legs=(replace(rel.legs[0], ratio=D(-1)),) + rel.legs[1:])
    assert run(short).relationship == "UNSUPPORTED"
    assert run(replace(rel, kind="OPTIMIZER")).relationship == "UNSUPPORTED"


def test_complement_on_kalshi_cannot_beat_the_spread():
    normal = integer_value_states([CONTRACTS["B65.5"]])
    code = "B65.5"
    yes = Leg(EVENT, market(code), "YES", ladder(code, "YES", ("0.45", 10)), FEES, KALSHI_BINARY_UNITS,
              numeric_cells(CONTRACTS[code], "YES", normal), structured_contract=CONTRACTS[code],
              rules_contract=CONTRACTS[code], settlement_cost=zero_cost)
    no = replace(yes, side="NO", ladder=ladder(code, "NO", ("0.56", 10)),
                 payouts=numeric_cells(CONTRACTS[code], "NO", normal))
    rel = RelationshipSet("c", "COMPLEMENT", (yes, no), tuple(normal), ALL_EXCLUDED,
                          basket_settlement_cost=lambda s, f: D(0))
    ev = run(rel)
    assert ev.relationship == "PROVEN" and ev.observed_quote_inconsistency == D("-0.01")
    assert ev.sizes[0].claim == Claim.NO_SURPLUS_EVEN_BEFORE_FEES.value


def test_complement_under_fallback_relies_on_a_recorded_assumption():
    code = "B65.5"
    normal = integer_value_states([CONTRACTS[code]])
    fallback = fair_price_fallback([market(code).market_id], description="fair price")
    cells_yes = dict(numeric_cells(CONTRACTS[code], "YES", normal), fallback_fair_price=fallback_cell(
        market(code).market_id, "YES"))
    cells_no = dict(numeric_cells(CONTRACTS[code], "NO", normal), fallback_fair_price=fallback_cell(
        market(code).market_id, "NO"))
    yes = Leg(EVENT, market(code), "YES", ladder(code, "YES", ("0.40", 10)), FEES, KALSHI_BINARY_UNITS, cells_yes,
              settlement_cost=zero_cost)
    no = replace(yes, side="NO", ladder=ladder(code, "NO", ("0.50", 10)), payouts=cells_no)
    proof = StateProof({k: "fixture" for k in StateKind if k not in (StateKind.NORMAL, StateKind.FALLBACK)},
                       assumptions=("a Kalshi NO position receives 1 - v under a fair-price settlement",))
    ev = run(RelationshipSet("c", "COMPLEMENT", (yes, no), tuple(normal) + (fallback,), proof,
                             basket_settlement_cost=lambda s, f: D(0)))
    assert ev.relationship == "INCOMPLETE" and ev.sizes[0].min_full_fill_payout == 1  # v and 1 - v cancel
    assert ev.sizes[0].claim == Claim.SURPLUS_NOT_CLAIMABLE.value


def test_nested_thresholds_pay_at_least_one_unit_everywhere():
    above70, above72 = numeric_contract("greater", 70, None), numeric_contract("greater", 72, None)
    normal = integer_value_states([above70, above72])
    a = Leg(EVENT, market("T70"), "YES", ladder("T70", "YES", ("0.30", 10)), FEES, KALSHI_BINARY_UNITS,
            numeric_cells(above70, "YES", normal), structured_contract=above70, rules_contract=above70,
            settlement_cost=zero_cost)
    b = Leg(EVENT, market("T72"), "NO", ladder("T72", "NO", ("0.60", 10)), FEES, KALSHI_BINARY_UNITS,
            numeric_cells(above72, "NO", normal), structured_contract=above72, rules_contract=above72,
            settlement_cost=zero_cost)
    ev = run(RelationshipSet("n", "NESTED_THRESHOLD", (a, b), tuple(normal), ALL_EXCLUDED,
                             basket_settlement_cost=lambda s, f: D(0)))
    assert ev.relationship == "PROVEN" and ev.sizes[0].min_full_fill_payout == 1
    reversed_nest = replace(b, payouts=numeric_cells(above72, "YES", normal), side="YES",
                            ladder=ladder("T72", "YES", ("0.10", 10)))
    bad = run(RelationshipSet("n", "NESTED_THRESHOLD", (a, reversed_nest), tuple(normal), ALL_EXCLUDED,
                              basket_settlement_cost=lambda s, f: D(0)))
    assert bad.relationship == "UNSUPPORTED"  # YES(>70) + YES(>72) leaves values <= 70 unpaid


# --------------------------------------------------------------------------- stored Kalshi evidence


def _markets():
    return json.loads((FIXTURES / "markets_KXHIGHNY-26SEP23.json").read_text(encoding="utf-8"))["markets"]


def test_real_kxhighny_rules_form_a_partition_that_stays_incomplete():
    raws = _markets()
    assert len({rules_template_sha256(m["rules_primary"], m["rules_secondary"]) for m in raws}) == 1
    ladders = {m["ticker"]: DepthLadder("kalshi", f"kalshi:{m['ticker']}", "YES", (DepthLevel(D("0.15"), D(5)),),
                                        False, "2026-09-23T21:58:00Z", None, "snap") for m in raws}
    rel = kalshi_partition_set("KXHIGHNY-26SEP23", raws, ladders, fee_schedule=FEES)
    ev = evaluate(rel, sizes=[D(1)], as_of_utc="2026-09-23T21:58:10Z", max_quote_age=AGE, max_leg_skew=SKEW)
    assert ev.relationship == "INCOMPLETE"
    assert all(k in " ".join(ev.relationship_reasons) for k in ("VOID", "REFUND", "CANCELLATION"))
    assert not any("not exhaustive" in r or "overlap" in r for r in ev.relationship_reasons)
    (row,) = ev.sizes  # 6 x 0.15 = 0.90 < 1, yet the fair-price fallback can pay 0
    assert ev.observed_quote_inconsistency == D("0.10")
    assert row.worst_state == "fallback_fair_price" and row.claim == Claim.NO_SURPLUS_EVEN_BEFORE_FEES.value


def _store(tmp_path, markets, books):
    path = tmp_path / "evidence.sqlite3"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, source TEXT, kind TEXT, entity_id TEXT, "
                    "fetched_at_utc TEXT, url TEXT, payload_json TEXT, payload_sha256 TEXT)")
        con.execute("INSERT INTO snapshots VALUES (1,'kalshi','markets','KXHIGHNY',?, 'u', ?, 'm')",
                    ("2026-09-23T21:57:00Z", json.dumps({"markets": markets})))
        for i, (ticker, t, bids) in enumerate(books, start=2):
            con.execute("INSERT INTO snapshots VALUES (?,'kalshi','orderbook',?,?,?,?,?)",
                        (i, ticker, t, f"https://x/markets/{ticker}/orderbook?depth=100",
                         json.dumps({"orderbook_fp": {"yes_dollars": [], "no_dollars": bids}}), f"b{i}"))
    return path


def test_scan_reads_market_side_books_only_and_skips_post_close(tmp_path):
    markets = [dict(m, result="yes", expiration_value="70") for m in _markets()]  # settled fields present...
    books = [(m["ticker"], "2026-09-23T21:58:00Z", [["0.8500", "5.00"]]) for m in markets]  # YES ask 0.15
    books += [(m["ticker"], "2026-09-24T05:30:00Z", [["0.9900", "5.00"]]) for m in markets]  # after the close
    report = scan_kalshi_store(str(_store(tmp_path, markets, books)), series="KXHIGHNY", sizes=[D(1)],
                               max_quote_age=AGE, max_leg_skew=SKEW)
    assert report["sets_evaluated"] == 1 and report["relationship_counts"] == {"INCOMPLETE": 1}
    assert report["claim_counts_by_size_row"] == {"NO_SURPLUS_EVEN_BEFORE_FEES": 1}
    assert any("post-close" in s["reason"] for s in report["sets_skipped"])
    assert set(PROHIBITED_MARKET_FIELDS) >= {"result", "expiration_value"}  # ...but never read
    again = scan_kalshi_store(str(tmp_path / "evidence.sqlite3"), series="KXHIGHNY", sizes=[D(1)],
                              max_quote_age=AGE, max_leg_skew=SKEW)
    assert again["report_sha256"] == report["report_sha256"]  # deterministic replay


def test_exp003_prohibited_fields_are_dropped_before_use():
    from edge_lab.experiments import load, prohibited_fields
    from edge_lab.payoff_constraints import sanitized

    registry = Path(__file__).resolve().parents[1] / "experiments"
    fields = prohibited_fields(load(registry / "EXP-003-same-venue-payoff-consistency" / "experiment.toml"))
    raw = dict(_markets()[0], **{f: "SETTLED" for f in fields}, custom_label="x")
    clean = sanitized(raw, fields + ("custom_label",))
    assert not set(fields) & set(clean) and "custom_label" not in clean and "rules_primary" in clean


def test_cli_payoff_scan_needs_explicit_windows_and_writes_a_report(tmp_path, capsys):
    from edge_lab.cli import main

    markets = _markets()
    books = [(m["ticker"], "2026-09-23T21:58:00Z", [["0.8500", "5.00"]]) for m in markets]
    db = _store(tmp_path, markets, books)
    out = tmp_path / "report.json"
    with pytest.raises(SystemExit):
        main(["research", "payoff-scan", "--db", str(db), "--sizes", "1"])  # windows are never defaulted
    assert main(["research", "payoff-scan", "--db", str(db), "--sizes", "1", "--max-quote-age-seconds", "300",
                 "--max-leg-skew-seconds", "60", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["sets_evaluated"] == 1 and "result" in report["prohibited_fields_never_read"]
    assert '"relationship_counts"' in capsys.readouterr().out
