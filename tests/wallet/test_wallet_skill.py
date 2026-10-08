"""Deliverable C: the price-relative skill diagnostic beside the 50%-null binomial screen (ADR 0045 amendment C).

Every fixture here is SYNTHETIC. A synthetic success is a unit test, not observed strategy alpha.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from wallet_support import D, acct, at, obs

from edge_lab.wallet_intel.accounting import Mark, MarkKind, MarketState, reconstruct
from edge_lab.wallet_intel.events import Action
from edge_lab.wallet_intel.exact import Labeled
from edge_lab.wallet_intel.identity import IdentityBasis
from edge_lab.wallet_intel.skill import (SKILL_VERSION, EvaluationMode, EvaluationWindow, HindsightError,
                                         PositionStatus, SkillCohort, SkillRule, SkillVerdict,
                                         check_holdout_sequence, price_relative_report)
from edge_lab.wallet_intel.stats import kish_effective_size, price_benchmark_null_p, shrink_toward_zero

A, B = acct(101), acct(102)
AS_OF = at(days=60)
RULE = SkillRule("skill-fixture", "1", at(-1), min_effective_clusters=10, min_eligible_share=D("0.8"),
                 pseudo_clusters=20, fdr_q=0.10, screen_alpha=0.05, null_resamples=2000, seed=20261008)


def cohort(*accounts, selected_at=None, ref="synthetic-cohort"):  # type: ignore[no-untyped-def]
    return SkillCohort(selected_at or at(-1), tuple(a.key for a in accounts), ref)


def entries(account, n_win: int, n_lose: int, price: str, *, prefix: str = "m", start_day: float = 1,  # type: ignore[no-untyped-def]
            same_event: str | None = None, fee: Decimal | None = D(0), qty: int = 1, resolve_after_days: float = 2):
    """SYNTHETIC: one buy of `qty` YES contracts at `price` in each of n_win + n_lose markets, then a final
    payout of 1 (winners) or 0 (losers). Returns (observations, marks)."""
    rows, marks = [], {}
    for i in range(n_win + n_lose):
        market = f"{prefix}{i:03d}"
        token = f"{market}-yes"
        when = at(days=start_day + i * 0.1)
        rows.append(obs(account, Action.TRADE_BUY, token, qty, price, when, market=market,
                        event=same_event or f"evt-{market}", fee=fee))
        marks[token] = Mark(token, MarkKind.RESOLVED_PAYOUT, D(1) if i < n_win else D(0), None,
                            when + timedelta(days=resolve_after_days))
    return rows, marks


def report(rows_by_account, marks, *, accounts=None, rule=RULE, trials=1, mode=EvaluationMode.DESCRIPTIVE,  # type: ignore[no-untyped-def]
           window=None, coh=None, complete=None, identity=None, roles=None, as_of=AS_OF, label="SYNTHETIC"):
    accounts = accounts or [A]
    return price_relative_report(
        {a.key: rows for a, rows in rows_by_account.items()}, as_of=as_of, rule=rule,
        cohort=coh or cohort(*accounts), marks=marks,
        history_complete=complete if complete is not None else {a.key: True for a in accounts},
        identity=identity if identity is not None else {a.key: IdentityBasis.SYNTHETIC for a in accounts},
        trials=trials, data_label=label, mode=mode, window=window, roles=roles)


# --- Fixture 1: 98% wins at $0.99 is a loss ---------------------------------------------------------

def test_fixture_1_high_win_rate_at_99c_is_negative_while_the_binomial_screen_flags_it():
    rows, marks = entries(A, 98, 2, "0.99")
    acc = report({A: rows}, marks).account(A.key)
    assert acc.cost.value == D(99) and acc.payout.value == D(98) and acc.gross_excess.value == D(-1)
    assert acc.position_win_rate == D("0.98")
    assert acc.verdict is SkillVerdict.NEGATIVE
    screen = acc.binomial_screen
    assert screen is not None and screen.flags_high_win_rate and screen.wins == 98 and screen.trials == 100
    assert screen.p_value < 1e-20 and screen.label == "SMALL_SAMPLE_SCREEN_NOT_ALPHA"
    assert acc.net_excess.value == D(-1)  # fees observed as zero
    assert acc.effective_clusters == pytest.approx(100) and acc.clusters == 100
    assert acc.benchmark_p_value is not None and acc.benchmark_p_value > 0.5
    assert not acc.survives_fdr and acc.hidden_hedges == "UNOBSERVABLE"


# --- Fixture 2: lower hit rate, positive price-relative return --------------------------------------

def test_fixture_2_lower_hit_rate_with_positive_price_relative_return():
    rows, marks = entries(A, 16, 24, "0.20")
    acc = report({A: rows}, marks).account(A.key)
    assert acc.position_win_rate == D("0.4") and acc.gross_excess.value == D(8) and acc.cost.value == D(8)
    assert acc.binomial_screen is not None and not acc.binomial_screen.flags_high_win_rate
    assert acc.benchmark_p_value is not None and acc.benchmark_p_value < 0.01
    assert acc.verdict is SkillVerdict.POSITIVE_SCREEN and acc.survives_fdr
    assert acc.excess_return_raw == D(1)
    assert acc.excess_return_shrunk == pytest.approx(40 / 60)  # n / (n + k), toward zero excess
    assert "not persistence" in acc.verdict_reasons[0]


# --- Fixture 3: market-matched null -----------------------------------------------------------------

def test_fixture_3_market_matched_outcomes_are_not_distinguishable_from_the_benchmark():
    low, m1 = entries(A, 3, 7, "0.30", prefix="lo")
    high, m2 = entries(A, 7, 3, "0.70", prefix="hi", start_day=3)
    acc = report({A: low + high}, {**m1, **m2}).account(A.key)
    assert acc.gross_excess.value == D(0) and acc.position_win_rate == D("0.5")
    assert acc.verdict is SkillVerdict.NOT_DISTINGUISHABLE_FROM_BENCHMARK
    assert acc.binomial_screen is not None and not acc.binomial_screen.flags_high_win_rate
    assert acc.benchmark_p_value is not None and acc.benchmark_p_value > 0.3


# --- Fixture 4: one correlated event repeated across contracts --------------------------------------

def test_fixture_4_one_event_across_contracts_shrinks_the_effective_sample():
    rows, marks = entries(A, 20, 0, "0.50", same_event="evt-one-storm")
    acc = report({A: rows}, marks).account(A.key)
    assert acc.clusters == 1 and acc.effective_clusters == pytest.approx(1.0)
    assert acc.verdict is SkillVerdict.INSUFFICIENT_EVIDENCE
    assert acc.concentration == D(1) and acc.cluster_excess_band is None
    assert acc.position_win_rate == D(1) and acc.binomial_screen is not None and acc.binomial_screen.trials == 1
    # Comonotone outcomes inside the cluster: 20 correlated wins are one coin flip, not 20.
    assert acc.benchmark_p_value is not None and acc.benchmark_p_value > 0.4
    spread, m2 = entries(A, 20, 0, "0.50")
    independent = report({A: spread}, m2).account(A.key)
    assert independent.effective_clusters == pytest.approx(20) and independent.benchmark_p_value < 0.001


def test_effective_sample_follows_cluster_cost_weights():
    assert kish_effective_size([1.0] * 10) == pytest.approx(10)
    assert kish_effective_size([9.0, 1.0]) == pytest.approx(100 / 82)
    assert kish_effective_size([]) is None
    assert shrink_toward_zero(1.0, 0, 0) == 0.0 and shrink_toward_zero(2.0, 10, 10) == pytest.approx(1.0)


# --- Fixture 5: hindsight-selected winner -----------------------------------------------------------

def test_fixture_5_hindsight_selected_winner_is_refused_in_holdout_and_flagged_in_description():
    rows, marks = entries(A, 16, 24, "0.20")  # every outcome is known by day 7
    late = cohort(A, selected_at=at(days=10), ref="picked-after-the-wins")
    window = EvaluationWindow(at(days=1), at(days=9))
    with pytest.raises(HindsightError, match="cohort was selected after"):
        report({A: rows}, marks, mode=EvaluationMode.HOLDOUT, window=window, coh=late)
    late_rule = SkillRule(**{**RULE.__dict__, "frozen_at": at(days=5)})
    with pytest.raises(HindsightError, match="rule was frozen after"):
        report({A: rows}, marks, mode=EvaluationMode.HOLDOUT, window=window, rule=late_rule)
    acc = report({A: rows}, marks, coh=late).account(A.key)
    assert acc.hindsight_flags == ("SELECTED_AFTER_OUTCOMES",) and acc.verdict is SkillVerdict.HINDSIGHT_FLAGGED
    assert acc.benchmark_p_value is not None and acc.benchmark_p_value < 0.01  # the p-value cannot launder it
    # A proper holdout after that selection sees none of the selecting wins.
    later = report({A: rows}, marks, mode=EvaluationMode.HOLDOUT, coh=late,
                   window=EvaluationWindow(at(days=10), at(days=40))).account(A.key)
    assert later.verdict is SkillVerdict.NO_ELIGIBLE_POSITIONS
    assert dict(later.excluded) == {"OVERLAPS_SELECTION": 40}


def test_holdout_counts_only_positions_entered_after_selection_inside_the_window():
    before, m1 = entries(A, 16, 24, "0.20")
    after, m2 = entries(A, 16, 24, "0.20", prefix="h", start_day=20)
    rep = report({A: before + after}, {**m1, **m2}, mode=EvaluationMode.HOLDOUT,
                 coh=cohort(A, selected_at=at(days=15)), window=EvaluationWindow(at(days=15), at(days=59)))
    acc = rep.account(A.key)
    assert acc.eligible == 40 and dict(acc.excluded) == {"OVERLAPS_SELECTION": 40}
    assert rep.persistence_evidence == "ONE_NON_OVERLAPPING_WINDOW"
    # Half the account's positions overlap selection, so coverage is below the rule's 0.8 minimum.
    assert acc.verdict is SkillVerdict.INSUFFICIENT_EVIDENCE and acc.verdict_reasons[0].startswith("COVERAGE")


def test_holdout_sequence_needs_one_frozen_rule_and_non_overlapping_windows():
    rows, marks = entries(A, 4, 4, "0.50", start_day=20)
    coh = cohort(A, selected_at=at(days=15))
    first = report({A: rows}, marks, mode=EvaluationMode.HOLDOUT, coh=coh,
                   window=EvaluationWindow(at(days=15), at(days=30))).closure
    second = report({A: rows}, marks, mode=EvaluationMode.HOLDOUT, coh=coh,
                    window=EvaluationWindow(at(days=30), at(days=45))).closure
    check_holdout_sequence([first, second])
    overlap = report({A: rows}, marks, mode=EvaluationMode.HOLDOUT, coh=coh,
                     window=EvaluationWindow(at(days=25), at(days=45))).closure
    with pytest.raises(HindsightError, match="overlap"):
        check_holdout_sequence([first, overlap])
    tuned = SkillRule(**{**RULE.__dict__, "min_effective_clusters": 3})
    retuned = report({A: rows}, marks, mode=EvaluationMode.HOLDOUT, coh=coh, rule=tuned,
                     window=EvaluationWindow(at(days=30), at(days=45))).closure
    with pytest.raises(HindsightError, match="rule changed"):
        check_holdout_sequence([first, retuned])
    with pytest.raises(HindsightError, match="only HOLDOUT"):
        check_holdout_sequence([first, report({A: rows}, marks).closure])


# --- Fixture 6: unknown fee -------------------------------------------------------------------------

def test_fixture_6_unknown_fee_makes_net_unknown_never_zero():
    rows, marks = entries(A, 16, 24, "0.20", fee=None)
    rep = report({A: rows}, marks)
    acc = rep.account(A.key)
    assert acc.gross_excess.value == D(8)
    assert not acc.net_excess.known and acc.net_excess.value is None
    assert acc.verdict_basis == "GROSS_ONLY_NET_UNKNOWN" and "gross only" in acc.verdict_reasons[-1]
    assert all(not p.net_excess.known and not p.fees.known for p in rep.positions)
    assert acc.to_dict()["net_excess"] == {"value": None, "basis": "UNKNOWN",
                                           "note": "a fee is unknown: net excess is unknown, never zero"}
    paid, m2 = entries(A, 16, 24, "0.20", fee=D("0.01"))
    known = report({A: paid}, m2).account(A.key)
    assert known.net_excess.value == D("7.6") and known.verdict_basis == "GROSS_AND_NET"
    assert known.verdict is SkillVerdict.POSITIVE_SCREEN
    # Fees that eat the whole gross excess leave nothing after costs.
    costly, m3 = entries(A, 16, 24, "0.20", fee=D("0.2"))
    eaten = report({A: costly}, m3).account(A.key)
    assert eaten.gross_excess.value == D(8) and eaten.net_excess.value == D(0)
    assert eaten.verdict is SkillVerdict.NOT_DISTINGUISHABLE_FROM_BENCHMARK


# --- Exclusions: classified, never priced -----------------------------------------------------------

def _one(rows, marks=None, **kw):  # type: ignore[no-untyped-def]
    if marks is None:
        marks = {"m1-yes": Mark("m1-yes", MarkKind.RESOLVED_PAYOUT, D(1), None, at(days=5))}
    rep = report({A: rows}, marks, **kw)
    return [p for p in rep.positions if p.market_id == "m1"][0]


def test_every_ambiguous_position_is_classified_and_carries_no_number():
    buy = obs(A, Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0))
    cases = {
        PositionStatus.EARLY_OR_MIXED_EXIT: [buy, obs(A, Action.TRADE_SELL, "m1-yes", 10, "0.60", at(60))],
        PositionStatus.INCOMPLETE_TRANSFER: [obs(A, Action.TRANSFER_IN, "m1-yes", 10, "0", at(0))],
        PositionStatus.UNSUPPORTED_CONVERSION: [buy, obs(A, Action.SPLIT, "m1-yes", 5, "0", at(10))],
        PositionStatus.UNKNOWN_ACTION: [buy, obs(A, Action.UNKNOWN, "m1-yes", 1, "0", at(10))],
        PositionStatus.BOTH_SIDES_HELD: [buy, obs(A, Action.TRADE_BUY, "m1-no", 10, "0.60", at(10))],
        PositionStatus.ENTRY_ECONOMICS_UNVERIFIED: [obs(A, Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0),
                                                        cash="3.99")],
        PositionStatus.NO_ENTRY: [obs(A, Action.REDEEM, "m1-yes", 10, "0", at(days=6), cash="10")],
    }
    for status, rows in cases.items():
        row = _one(rows)
        assert row.status is status, (status, row.reason)
        assert not row.gross_excess.known and not row.net_excess.known and row.cost is None
    assert _one([buy], {}).status is PositionStatus.UNRESOLVED
    void = {"m1-yes": Mark("m1-yes", MarkKind.RESOLVED_PAYOUT, D("0.5"), None, at(days=5))}
    assert _one([buy], void).status is PositionStatus.AMBIGUOUS_RESOLUTION
    bid = {"m1-yes": Mark("m1-yes", MarkKind.EXECUTABLE_BID, D("0.9"), D(100), at(days=5))}
    assert _one([buy], bid).status is PositionStatus.UNRESOLVED  # a bid is not a resolution
    good_redeem = obs(A, Action.REDEEM, "m1-yes", 10, "0", at(days=6), cash="10")
    assert _one([buy, good_redeem]).status is PositionStatus.ELIGIBLE
    bad_redeem = obs(A, Action.REDEEM, "m1-yes", 10, "0", at(days=6), cash="9")
    assert _one([buy, bad_redeem]).status is PositionStatus.REDEMPTION_MISMATCH
    assert _one([buy], complete={A.key: False}).status is PositionStatus.COVERAGE_INCOMPLETE
    assert _one([buy], identity={A.key: IdentityBasis.HEURISTIC}).status is PositionStatus.IDENTITY_UNVERIFIED
    assert _one([buy], identity={}).status is PositionStatus.IDENTITY_UNVERIFIED


def test_exclusions_lower_coverage_and_block_a_verdict():
    rows, marks = entries(A, 16, 24, "0.20")
    exits = [obs(A, Action.TRADE_SELL, f"m{i:03d}-yes", 1, "0.10", at(days=1 + i * 0.1, hours=1), market=f"m{i:03d}")
             for i in range(16, 26)]
    acc = report({A: rows + exits}, marks).account(A.key)
    assert dict(acc.excluded) == {"EARLY_OR_MIXED_EXIT": 10} and acc.eligible_share == D("0.75")
    assert acc.verdict is SkillVerdict.INSUFFICIENT_EVIDENCE


def test_gross_excess_agrees_with_leader_accounting_for_held_to_resolution_positions():
    rows, marks = entries(A, 16, 24, "0.20", qty=3)
    acc = report({A: rows}, marks).account(A.key)
    leader = reconstruct(rows, as_of=AS_OF, history_complete=True, cash_flows_observed=False,
                         opening_balance=Labeled.unknown(), marks=marks, mark_max_age=timedelta(minutes=5))
    assert all(m.state is MarketState.SETTLED for m in leader.markets)
    assert leader.realized_trading_pnl_gross.value == acc.gross_excess.value == D(24)


# --- Denominators and multiple testing --------------------------------------------------------------

def test_losing_and_inactive_accounts_stay_in_the_denominator():
    win, m1 = entries(A, 16, 24, "0.20")
    lose, m2 = entries(B, 4, 36, "0.20", prefix="b")
    inactive = [acct(200 + i) for i in range(30)]
    everyone = [A, B, *inactive]
    rep = report({A: win, B: lose}, {**m1, **m2}, accounts=everyone)
    assert rep.hypotheses == 32 and len(rep.accounts) == 32
    assert rep.account(B.key).verdict is SkillVerdict.NEGATIVE
    assert rep.account(inactive[0].key).verdict is SkillVerdict.NO_ELIGIBLE_POSITIONS
    assert rep.account(inactive[0].key).verdict_reasons == ("no observation: inactive",)
    # Re-running rules on the same data (trials) raises m and makes survival harder, never easier.
    many = report({A: win, B: lose}, {**m1, **m2}, accounts=everyone, trials=50)
    assert many.hypotheses == 1600 and A.key not in many.survivors
    assert many.account(A.key).verdict is SkillVerdict.NOT_DISTINGUISHABLE_FROM_BENCHMARK


def test_role_is_unknown_without_evidence_and_reported_when_supplied():
    rows, marks = entries(A, 16, 24, "0.20")
    assert report({A: rows}, marks).account(A.key).roles == (("UNKNOWN", 40),)
    roles = {o.observation_id: ("MAKER" if i % 2 else "TAKER") for i, o in enumerate(rows)}
    assert report({A: rows}, marks, roles=roles).account(A.key).roles == (("MAKER", 20), ("TAKER", 20))
    with pytest.raises(ValueError):
        report({A: rows}, marks, roles={rows[0].observation_id: "WHALE"})


# --- Point in time and inputs -----------------------------------------------------------------------

def test_future_marks_observations_and_strangers_are_refused():
    rows, marks = entries(A, 2, 2, "0.50")
    with pytest.raises(HindsightError):
        report({A: rows}, marks, as_of=at(days=2))  # marks resolve after as_of
    with pytest.raises(HindsightError):
        report({A: [obs(A, Action.TRADE_BUY, when=at(days=61))]}, {})
    with pytest.raises(ValueError, match="outside the cohort"):
        report({A: rows, B: []}, marks)
    with pytest.raises(ValueError, match="OBSERVED"):
        report({A: rows}, marks, label="OBSERVED")
    with pytest.raises(ValueError):
        report({A: rows}, marks, label="PROFITABLE")


def _closure_inputs():  # type: ignore[no-untyped-def]
    rows, marks = entries(A, 6, 6, "0.40")
    return rows, marks


def test_closure_digest_binds_every_input_and_ignores_input_order():
    rows, marks = _closure_inputs()
    base = report({A: rows}, marks)
    assert base.closure.version == SKILL_VERSION
    assert report({A: list(reversed(rows))}, dict(reversed(list(marks.items())))).closure.digest == base.closure.digest
    assert report({A: rows}, marks).digest == base.digest  # deterministic, seeded statistics
    variants = {
        "rule_id": SkillRule(**{**RULE.__dict__, "rule_id": "other"}),
        "version": SkillRule(**{**RULE.__dict__, "version": "2"}),
        "frozen_at": SkillRule(**{**RULE.__dict__, "frozen_at": at(-2)}),
        "min_effective_clusters": SkillRule(**{**RULE.__dict__, "min_effective_clusters": 11}),
        "min_eligible_share": SkillRule(**{**RULE.__dict__, "min_eligible_share": D("0.81")}),
        "pseudo_clusters": SkillRule(**{**RULE.__dict__, "pseudo_clusters": 21}),
        "fdr_q": SkillRule(**{**RULE.__dict__, "fdr_q": 0.05}),
        "screen_alpha": SkillRule(**{**RULE.__dict__, "screen_alpha": 0.01}),
        "null_resamples": SkillRule(**{**RULE.__dict__, "null_resamples": 1999}),
        "seed": SkillRule(**{**RULE.__dict__, "seed": 1}),
    }
    digests = {base.closure.digest}
    for name, rule in variants.items():
        d = report({A: rows}, marks, rule=rule).closure.digest
        assert d not in digests, name
        digests.add(d)
    others = [
        report({A: rows[:-1]}, marks),
        report({A: rows}, {**marks, "x-yes": Mark("x-yes", MarkKind.RESOLVED_PAYOUT, D(0), None, at(days=3))}),
        report({A: rows}, marks, identity={A.key: IdentityBasis.SOURCE_FIELD}),
        report({A: rows}, marks, complete={A.key: False}),
        report({A: rows}, marks, roles={rows[0].observation_id: "MAKER"}),
        report({A: rows}, marks, trials=2),
        report({A: rows}, marks, label="FIXTURE"),
        report({A: rows}, marks, coh=cohort(A, ref="another-manifest")),
        report({A: rows}, marks, coh=cohort(A, selected_at=at(-2))),
        report({A: rows}, marks, accounts=[A, B]),
        report({A: rows}, marks, as_of=at(days=59)),
        report({A: rows}, marks, window=EvaluationWindow(at(0), at(days=50))),
        report({A: rows}, marks, mode=EvaluationMode.HOLDOUT, window=EvaluationWindow(at(0), at(days=50))),
    ]
    for i, other in enumerate(others):
        assert other.closure.digest not in digests, i
        digests.add(other.closure.digest)


def test_closure_is_a_plain_serializable_value():
    import json
    rows, marks = _closure_inputs()
    closure = report({A: rows}, marks).closure
    text = json.dumps(closure.to_dict(), sort_keys=True)
    assert json.loads(text) == closure.to_dict()
    assert dict(closure.rule)["min_eligible_share"] == "0.8" and dict(closure.rule)["fdr_q"] == "0.1"
    assert closure.coverage == ((A.key, 12, 12),)


def test_benchmark_null_is_deterministic_and_validates_its_inputs():
    legs = [[(0.5, 1.0)] for _ in range(10)]
    assert price_benchmark_null_p(legs, 0.0) == price_benchmark_null_p(legs, 0.0)
    assert price_benchmark_null_p(legs, 100.0) == pytest.approx(1 / 2001)
    with pytest.raises(ValueError):
        price_benchmark_null_p([[(1.0, 1.0)]], 0.0)
    with pytest.raises(ValueError):
        price_benchmark_null_p([], 0.0)
