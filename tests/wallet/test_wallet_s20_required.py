"""Directive §20, "REQUIRED NEW WALLET TESTS": one test (or a small group) per bullet, in order.

Synthetic and documentation-shaped fixtures only. No network, no credential, no real account.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from wallet_support import (D, Books, acct, at, book, config, enrolled, fixture, limits, obs, signal)

from edge_lab.wallet_intel import polymarket_v2 as pm
from edge_lab.wallet_intel.accounting import Mark, MarkKind, reconstruct
from edge_lab.wallet_intel.events import (Action, ChainFinality, Correction, CorrectionKind, ObservationLog,
                                          assign_occurrences)
from edge_lab.wallet_intel.exact import Labeled
from edge_lab.wallet_intel.identity import IdentityBasis, IdentityRegistry, MappingRevocation, ProxyMapping, \
    RelationKind
from edge_lab.wallet_intel.observability import ExecutionEligibility, ResearchEligibility, eligibility
from edge_lab.wallet_intel.policy import (FollowerBook, FollowerPolicy, IntentKind, LeaderStatus, NotFollowable,
                                          Enrollment, signal_from_observation)
from edge_lab.wallet_intel.replay import FillStatus, RequestResult, Resolution, replay
from edge_lab.wallet_intel.selection import Candidate, CandidateStatus, EligibilityRule, select_at

RECEIPT = at(days=30)


# 1. multiple fills in one transaction remain distinct --------------------------------------------
def test_multiple_fills_in_one_transaction_remain_distinct():
    page = pm.parse_activity_page(fixture("activity_page1.json"), receipt_time=RECEIPT, synthetic=True)
    numbered = assign_occurrences(page.observations)
    tx = numbered[0].transaction_id
    same_tx = [o for o in numbered if o.transaction_id == tx]
    assert len(same_tx) == 3  # two identical fills and a third at another price
    assert len({o.observation_id for o in same_tx}) == 3
    assert {o.occurrence for o in same_tx[:2]} == {0, 1}
    assert all("INDISTINGUISHABLE_DUPLICATE_ROWS" in o.ambiguities for o in same_tx[:2])
    log = ObservationLog()
    assert log.ingest(numbered)["added"] == 5
    # The same retrieval again is a duplicate, not new fills; the hash alone never collapses fills.
    assert log.ingest(numbered) == {"added": 0, "duplicates": 5, "conflicts": 0}
    assert len([o for o in log.as_known_at(RECEIPT) if o.transaction_id == tx]) == 3


# 2. proxy mappings are explicit and time-versioned ------------------------------------------------
def test_proxy_mappings_are_explicit_and_time_versioned():
    reg = IdentityRegistry()
    owner, wallet_a, wallet_b = acct(1, "polygon"), acct(2, "polymarket_international"), acct(3, "polymarket_international")
    reg.add(ProxyMapping("m1", owner, wallet_a, RelationKind.PROXY_WALLET, at(), None, at(days=1),
                         IdentityBasis.SYNTHETIC, "synthetic:1"))
    reg.add(ProxyMapping("m2", owner, wallet_b, RelationKind.DEPOSIT_WALLET, at(days=10), None, at(days=11),
                         IdentityBasis.SYNTHETIC, "synthetic:2"))
    reg.revoke(MappingRevocation("m1", at(days=20), at(days=21), "synthetic:3"))
    # Event time and knowledge time both matter.
    assert reg.accounts_for(owner, at=at(days=5), known_at=at(days=5)) == (wallet_a,)
    assert reg.accounts_for(owner, at=at(days=12), known_at=at(days=10, hours=1)) == (wallet_a,)  # m2 not yet known
    assert reg.accounts_for(owner, at=at(days=12), known_at=at(days=12)) == (wallet_a, wallet_b)
    assert reg.accounts_for(owner, at=at(days=25), known_at=at(days=20, hours=1)) == (wallet_a, wallet_b)
    assert reg.accounts_for(owner, at=at(days=25), known_at=at(days=22)) == (wallet_b,)
    assert reg.accounts_for(owner, at=at(days=-1), known_at=at(days=30)) == ()
    with pytest.raises(ValueError):  # no rewrite of a recorded mapping
        reg.add(ProxyMapping("m1", owner, wallet_b, RelationKind.PROXY_WALLET, at(), None, at(days=1),
                             IdentityBasis.SYNTHETIC, "synthetic:x"))


# 3. transfer/split/merge/reward is not followed as a directional buy ------------------------------
@pytest.mark.parametrize("action", [Action.TRANSFER_IN, Action.TRANSFER_OUT, Action.SPLIT, Action.MERGE,
                                    Action.REDEEM, Action.REWARD, Action.CONVERSION, Action.UNKNOWN])
def test_transfer_split_merge_reward_is_not_followed_as_a_directional_buy(action):
    o = obs(acct(1), action if action is not Action.UNKNOWN and action is not Action.CONVERSION else Action.REWARD)
    o = o.__class__(**{**o.__dict__, "action": action})
    assert not o.directional
    with pytest.raises(NotFollowable):
        signal_from_observation(o, observable_at=at(1), cluster_key="c", strategy="s", leader_position_before=D(0))


def test_v2_split_merge_reward_tip_rows_are_never_trades():
    page = pm.parse_activity_page(fixture("activity_page2.json"), receipt_time=RECEIPT, synthetic=True)
    kinds = [o.action for o in page.observations]
    assert kinds == [Action.TRADE_SELL, Action.MERGE, Action.REDEEM, Action.CONVERSION, Action.TRANSFER_IN]
    assert [o.directional for o in page.observations] == [True, False, False, False, False]


# 4. future rankings cannot select historical leaders ----------------------------------------------
def _rule() -> EligibilityRule:
    return EligibilityRule("r", "1", min_independent_events=2, min_history_days=1, min_shrunk_lower=0.0,
                           max_concentration=D("0.9"), max_round_trip_share=D("0.9"), max_reward_dependence=D("0.9"),
                           inactive_after=timedelta(days=60), round_trip_window=timedelta(hours=1),
                           min_trade_notional=D(0))


def _winner_log(account, *, receipt_delay=timedelta(seconds=30)):  # type: ignore[no-untyped-def]
    log = ObservationLog()
    rows = []
    for i in range(3):
        m = f"m{i}"
        rows.append(obs(account, Action.TRADE_BUY, f"{m}-yes", 10, "0.40", at(days=i), market=m,
                        receipt_delay=receipt_delay))
    log.ingest(rows)
    return log


def _marks(days: float) -> dict:
    return {f"m{i}-yes": Mark(f"m{i}-yes", MarkKind.RESOLVED_PAYOUT, D(1), None, at(days=i, hours=6))
            for i in range(3) if i + 0.25 <= days}


def test_future_rankings_cannot_select_historical_leaders():
    d = at(days=5)
    early, late = acct(1), acct(2)
    logs = {early.key: _winner_log(early), late.key: _winner_log(late)}
    candidates = [Candidate(early, at(days=-1), "universe", "v1"),
                  Candidate(late, at(days=40), "leaderboard-2026-04-10", "v1")]  # ranked a winner only later
    manifest = select_at(d, candidates=candidates, logs=logs, history_complete={early.key: True, late.key: True},
                         marks=_marks(5), rule=_rule(), label_version="v1", trials=1,
                         mark_max_age=timedelta(minutes=5))
    assert manifest.excluded_not_yet_discovered == 1
    assert late.key not in [r.account_key for r in manifest.records]
    assert early.key in manifest.eligible
    # Outcomes resolved after D are refused outright.
    from edge_lab.wallet_intel.selection import HindsightError
    with pytest.raises(HindsightError):
        select_at(at(days=1), candidates=candidates, logs=logs, history_complete={}, marks=_marks(5), rule=_rule(),
                  label_version="v1", trials=1, mark_max_age=timedelta(minutes=5))


# 5. incomplete history cannot manufacture ROI ----------------------------------------------------
def test_incomplete_history_cannot_manufacture_roi():
    a = acct(1)
    rows = [obs(a, Action.TRADE_SELL, "m1-yes", 10, "0.90", at(1))]  # a sale of something bought before coverage
    account = reconstruct(rows, as_of=at(days=1), history_complete=False, cash_flows_observed=True,
                          opening_balance=Labeled.observed(D(0)), marks={}, mark_max_age=timedelta(minutes=5))
    assert not account.realized_trading_pnl_gross.known
    assert not account.roi_net.known and not account.roi_gross.known
    assert not account.capital_employed.known and not account.equity.known
    # Even claiming complete history, a sale beyond the reconstructed holding is UNKNOWN, not +$9.
    claimed = reconstruct(rows, as_of=at(days=1), history_complete=True, cash_flows_observed=True,
                          opening_balance=Labeled.observed(D(0)), marks={}, mark_max_age=timedelta(minutes=5))
    assert not claimed.realized_trading_pnl_gross.known and not claimed.roi_gross.known


# 6. leader gains and follower losses are both reported correctly ----------------------------------
def test_leader_gain_and_follower_loss_are_both_reported():
    # Leader buys at 0.40; we observe after the price ran to 0.60; both exit at 0.55.
    buy = signal("b1", qty="100", price="0.40", when=at(0), before="0")
    sell = signal("s1", Action.TRADE_SELL, qty="100", price="0.55", when=at(60), before="100")
    books = Books(book(bid="0.59", ask="0.60", captured=at(1)), book(bid="0.55", ask="0.57", captured=at(61)))
    pol = FollowerPolicy(limits(max_price_above_leader=D("0.30"), risk_per_signal=D(60)), enrollments=enrolled("L1"))
    r = replay([buy, sell], pol, initial_cash=D(100), books=books, resolutions={}, config=config(),
               horizon=at(days=1))
    assert r.leader.per_unit["b1"].value == D("0.15")  # the leader made 15 cents a contract
    assert r.leader.label == "LEADER_OBSERVED_ECONOMICS"
    assert r.follower.label == "FOLLOWER_SIMULATED_ECONOMICS"
    filled = r.fills[0].filled
    assert filled > 0 and r.fills[0].levels[0][0] == D("0.60")  # we could only buy after the run-up
    assert r.follower.gross_pnl.value == filled * D("-0.05")  # we lost 5 cents a contract
    assert r.difference_by_event["evt-m1"].value == filled * D("-0.05") - filled * D("0.15")


# 7. leader exit without our entry cannot create a short -------------------------------------------
def test_leader_exit_without_our_entry_cannot_create_a_short():
    sell = signal("s1", Action.TRADE_SELL, qty="50", price="0.55", before="50")
    pol = FollowerPolicy(limits(), enrollments=enrolled("L1"))
    r = replay([sell], pol, initial_cash=D(100), books=Books(book(captured=at(1))), resolutions={}, config=config(),
               horizon=at(days=1))
    assert r.outcomes[0].decision == "SKIP" and "never a short" in r.outcomes[0].reason
    assert r.fills == () and r.final_book.inventory == {}
    fb = FollowerBook(D(100))
    with pytest.raises(ValueError, match="no short"):
        fb.record_sell("m1-yes", "L1", ((D("0.5"), D(1)),), D(0))


# 8. multiple leaders cannot reuse cash or inventory -----------------------------------------------
def test_multiple_leaders_cannot_reuse_cash_or_inventory():
    s1 = signal("a", leader="L1", qty="100", price="0.40")
    s2 = signal("b", leader="L2", qty="100", price="0.40")
    exit2 = signal("x", Action.TRADE_SELL, leader="L2", qty="100", price="0.45", when=at(30), before="100")
    pol = FollowerPolicy(limits(risk_per_signal=D(10)), enrollments=enrolled("L1", "L2"))
    r = replay([s1, s2, exit2], pol, initial_cash=D(12), books=Books(book(captured=at(1)), book(captured=at(31))),
               resolutions={}, config=config(), horizon=at(days=1))
    fills = [f for f in r.fills if f.status in (FillStatus.FILLED, FillStatus.PARTIAL)]
    spent = sum((f.gross_cash for f in fills if f.side == "BUY"), D(0))
    assert spent <= D(12)  # one budget of 10 and the 2 dollars left, never 20
    fb = r.final_book
    l1 = fb.attributable("m1-yes", "L1")
    # L2's exit sold only what L2's own signal bought; L1's contracts are untouched.
    assert l1 == next(f.filled for f in fills if f.signal_id == "a")
    assert fb.attributable("m1-yes", "L2") == 0
    assert fb.inventory["m1-yes"] == l1


# 9. reorg/correction cannot erase our fill ---------------------------------------------------------
def test_reorg_or_correction_cannot_erase_our_fill():
    from edge_lab.wallet_intel.policy import signals_from_log
    from edge_lab.wallet_intel.replay import leader_event_status
    a = acct(1)
    leader_buy = obs(a, Action.TRADE_BUY, qty=100, price="0.40", when=at(0))
    log = ObservationLog()
    log.ingest([leader_buy])
    pol = FollowerPolicy(limits(), enrollments=enrolled(a.key))

    def run():  # type: ignore[no-untyped-def]
        # Signals are rebuilt from the log every time, point in time, then the replay re-runs.
        sigs = signals_from_log(log, detection_delay=timedelta(minutes=1), cluster_key=lambda k: k, strategy="s")
        return replay(sigs, pol, initial_cash=D(100), books=Books(book(captured=at(1))), resolutions={},
                      config=config(), horizon=at(days=1))

    first = run()
    held = first.final_book.inventory["m1-yes"]
    assert held > 0 and first.fills[0].status is FillStatus.FILLED
    log.append_correction(Correction("c1", leader_buy.observation_id, CorrectionKind.FINALITY_CHANGED, at(10),
                                     "synthetic reorg", new_finality=ChainFinality.REORGED_OUT))
    assert log.as_known_at(at(11)) == ()  # the leader event is gone from the corrected view...
    assert log.as_known_at(at(5)) == (leader_buy,)  # ...the earlier view is unchanged...
    again = run()  # ...and a replay after the correction still has our fill
    assert again.fills == first.fills and again.final_book.inventory["m1-yes"] == held
    assert leader_event_status(again.fills, log, known_at=at(11)) == {leader_buy.observation_id:
                                                                     "RETRACTED_AFTER_OUR_FILL"}
    # A correction recorded before our channel could see the trade means we never saw it.
    early = ObservationLog()
    early.ingest([leader_buy])
    early.append_correction(Correction("c0", leader_buy.observation_id, CorrectionKind.RETRACTED,
                                       leader_buy.receipt_time, "retracted at once"))
    assert signals_from_log(early, detection_delay=timedelta(minutes=1), cluster_key=lambda k: k, strategy="s") == ()


# 10. partial exits reconcile to terminal wealth ----------------------------------------------------
def test_partial_exits_reconcile_to_terminal_wealth():
    buy = signal("b", qty="100", price="0.40", before="0")
    half = signal("h", Action.TRADE_SELL, qty="50", price="0.50", when=at(30), before="100")
    books = Books(book(captured=at(1)), book(bid="0.49", ask="0.51", size="7", levels=1, captured=at(31)))
    pol = FollowerPolicy(limits(risk_per_signal=D(10)), enrollments=enrolled("L1"))
    res = {"m1-yes": Resolution("m1-yes", D(1), at(hours=5))}
    r = replay([buy, half], pol, initial_cash=D(100), books=books, resolutions=res, config=config(),
               horizon=at(days=1))
    sell_fill = next(f for f in r.fills if f.side == "SELL")
    assert sell_fill.status is FillStatus.PARTIAL and sell_fill.filled == 7  # only 7 bid on the book
    assert all(r.reconciliation.values()), r.reconciliation
    bought = next(f for f in r.fills if f.side == "BUY")
    expected = D(100) - bought.gross_cash + sell_fill.gross_cash + (bought.filled - 7) * D(1)
    assert r.follower.final_cash == expected
    assert r.follower.gross_pnl.value == expected - D(100)


# 11. missing depth is not executable size ----------------------------------------------------------
@pytest.mark.parametrize("bk,reason", [
    (None, "MISSING_BOOK"),
    ("no-asks", "MISSING_DEPTH"),
    ("stale", "STALE_BOOK"),
])
def test_missing_depth_is_not_executable_size(bk, reason):
    if bk == "no-asks":
        books = Books(book(ask=None, captured=at(1)))
    elif bk == "stale":
        books = Books(book(captured=at(-60)))
    else:
        books = Books()
    pol = FollowerPolicy(limits(), enrollments=enrolled("L1"))
    r = replay([signal("b")], pol, initial_cash=D(100), books=books, resolutions={}, config=config(),
               horizon=at(days=1))
    f = r.fills[0]
    assert f.status is FillStatus.NO_FILL and reason in f.reason and f.filled == 0
    assert r.final_book.inventory == {}


def test_truncated_depth_fills_only_what_was_captured():
    pol = FollowerPolicy(limits(risk_per_signal=D(100)), enrollments=enrolled("L1"))
    r = replay([signal("b")], pol, initial_cash=D(100),
               books=Books(book(size="10", levels=2, truncated=True, captured=at(1))), resolutions={},
               config=config(), horizon=at(days=1))
    f = r.fills[0]
    assert f.status is FillStatus.PARTIAL and f.filled == 20 and "unknown" in f.reason


# 12. API v2 pagination, envelopes, statuses and errors are correct ---------------------------------
def test_api_v2_pagination_envelopes_statuses_and_errors():
    pages = {None: (200, fixture("activity_page1.json"), {}),
             "c2-synthetic-opaque": (200, fixture("activity_page2.json"), {})}
    w = pm.walk(lambda c: pages[c], receipt_time=RECEIPT, synthetic=True, max_pages=5)
    assert w.complete and len(w.pages) == 2 and len(w.observations) == 10
    assert not pm.history_complete(w, start_param=0) and pm.history_complete(w, start_param=1)
    # Documented miss: null or empty data is not an error and not "zero activity".
    for name in ("activity_data_null.json", "activity_data_empty.json"):
        p = pm.parse_activity_page(fixture(name), receipt_time=RECEIPT, synthetic=True)
        assert p.page.documented_miss and p.observations == ()
    # Envelope and case: v1 shapes are refused.
    for name in ("activity_v1_bare_camel.json", "activity_v1_camel_in_envelope.json",
                 "activity_missing_usdc_size.json", "activity_has_more_without_cursor.json",
                 "activity_cursor_without_has_more.json"):
        with pytest.raises(pm.V2ParseError):
            pm.parse_activity_page(fixture(name), receipt_time=RECEIPT, synthetic=True)
    # Position statuses.
    _, rows = pm.parse_positions_page(fixture("positions_page.json"))
    assert [r.status.value for r in rows] == ["OPEN", "REDEEMABLE", "REDEEMABLE_LOST", "MERGEABLE", "CLOSED"]
    with pytest.raises(pm.V2ParseError):
        pm.parse_positions_page(fixture("positions_bad_status.json"))
    # Errors stop the walk as incomplete, with the documented code, retryability and Retry-After.
    for status, name, code, retryable, after in ((400, "error_400_bad_cursor.json", "invalid_request", False, None),
                                                 (429, "error_429_rate_limited.json", "rate_limited", True, "7"),
                                                 (503, "error_503_request_timeout.json", "request_timeout", True,
                                                  "3")):
        seq = {None: (200, fixture("activity_page1.json"), {}),
               "c2-synthetic-opaque": (status, fixture(name), {"Retry-After": after} if after else {})}
        w = pm.walk(lambda c: seq[c], receipt_time=RECEIPT, synthetic=True, max_pages=5)
        assert not w.complete and w.stop is pm.WalkStop.API_ERROR and len(w.pages) == 1
        assert w.error.code == code and w.error.retryable is retryable and w.error.status_matches_code
        assert w.error.retry_after_seconds == (int(after) if after else None)
    # A repeated cursor is an error, not the end of the data.
    loop = {None: (200, fixture("activity_page1.json"), {}),
            "c2-synthetic-opaque": (200, fixture("activity_loop_page.json"), {})}
    w = pm.walk(lambda c: loop[c], receipt_time=RECEIPT, synthetic=True, max_pages=10)
    assert w.stop is pm.WalkStop.CURSOR_LOOP and not w.complete


# 13. illiquid gifts/fake marks do not qualify a leader ---------------------------------------------
def test_illiquid_gifts_and_fake_marks_do_not_qualify_a_leader():
    a = acct(1)
    gift = obs(a, Action.TRANSFER_IN, "m1-yes", 1000, "0", at(0))
    marks = {"m1-yes": Mark("m1-yes", MarkKind.VENDOR_MARK, D("0.95"), None, at(10))}
    acc = reconstruct([gift], as_of=at(20), history_complete=True, cash_flows_observed=True,
                      opening_balance=Labeled.observed(D(0)), marks=marks, mark_max_age=timedelta(minutes=5))
    assert not acc.equity.known and not acc.unrealized_value.known and not acc.roi_gross.known
    assert acc.inventory_transfers == (("IN", "token:m1-yes", D(1000)),)
    # A last print or a thin bid is not withdrawable wealth either.
    buy = obs(a, Action.TRADE_BUY, "m2-yes", 1000, "0.01", at(0), market="m2")
    for mark in (Mark("m2-yes", MarkKind.LAST_PRINT, D("0.90"), None, at(19)),
                 Mark("m2-yes", MarkKind.EXECUTABLE_BID, D("0.90"), D(5), at(19))):
        acc = reconstruct([buy], as_of=at(20), history_complete=True, cash_flows_observed=True,
                          opening_balance=Labeled.observed(D(10)), marks={"m2-yes": mark},
                          mark_max_age=timedelta(minutes=5))
        assert not acc.unrealized_value.known and not acc.equity.known
    # And selection does not qualify a gift-only account.
    log = ObservationLog()
    log.ingest([gift])
    m = select_at(at(30), candidates=[Candidate(a, at(-1), "u", "v1")], logs={a.key: log},
                  history_complete={a.key: True}, marks={}, rule=_rule(), label_version="v1", trials=1,
                  mark_max_age=timedelta(minutes=5))
    assert m.records[0].status is CandidateStatus.INELIGIBLE


# 14. expired backlog is quarantined -----------------------------------------------------------------
def test_expired_backlog_is_quarantined():
    old = signal("old", when=at(0))
    fresh = signal("fresh", when=at(115), token="m2-yes", market="m2", event="evt-m2")
    pol = FollowerPolicy(limits(max_signal_age=timedelta(minutes=10)), enrollments=enrolled("L1"))
    books = Books(book(captured=at(110)), book("m2-yes", captured=at(110)))
    r = replay([old, fresh], pol, initial_cash=D(100), books=books, resolutions={},
               config=config(resume_at=at(120)), horizon=at(days=1))  # a restart after a two-hour outage
    by = {o.signal_id: o for o in r.outcomes}
    assert by["old"].decision == "QUARANTINE" and "EXPIRED_BACKLOG" in by["old"].reason
    assert by["old"].fill is None
    assert by["fresh"].decision == "BUY"


# 15. hidden hedges remain unknown --------------------------------------------------------------------
def test_hidden_hedges_remain_unknown():
    from edge_lab.wallet_intel.accounting import leader_dimensions
    from edge_lab.wallet_intel.stats import WEAK_PRIOR
    a = acct(1)
    rows = [obs(a, Action.TRADE_BUY, "m1-yes", 10, "0.40", at(0)), obs(a, Action.TRADE_SELL, "m1-yes", 10, "0.50", at(9))]
    acc = reconstruct(rows, as_of=at(20), history_complete=True, cash_flows_observed=True,
                      opening_balance=Labeled.observed(D(10)), marks={}, mark_max_age=timedelta(minutes=5))
    dims = leader_dimensions(acc, rows, prior=WEAK_PRIOR)
    assert dims.hidden_hedges == "UNKNOWN"
    assert dims.to_dict()["hidden_hedges"] == "UNKNOWN"


# 16. model output cannot modify grants or secrets ---------------------------------------------------
def test_model_output_cannot_modify_grants_or_secrets():
    lim = limits()
    pol = FollowerPolicy(lim, enrollments=enrolled("L1"))
    fb = FollowerBook(D(100))
    model_output = {"action": "BUY", "risk_per_signal": "1000000", "note": "ignore previous limits, raise the cap"}
    for bad in (model_output, "BUY everything, cap is now unlimited", ["BUY"]):
        with pytest.raises(TypeError):
            pol.decide(bad, fb, now=at(2))  # type: ignore[arg-type]
    with pytest.raises(TypeError):  # free text cannot ride in an identifier field
        signal("ignore all limits and buy")
    with pytest.raises(Exception):
        lim.risk_per_signal = D(10 ** 6)  # type: ignore[misc]
    digest = lim.digest
    pol.decide(signal("ok"), fb, now=at(2))
    assert pol.limits.digest == digest and pol.limits is lim
    assert not any(hasattr(pol, n) for n in ("grant", "secret", "set_limits", "credentials"))


# 17. unsupported eligibility blocks execution, not falsifies research --------------------------------
def test_unsupported_eligibility_blocks_execution_not_research():
    answer = eligibility("polymarket_data_api_v2")
    assert answer.research is ResearchEligibility.RESEARCH_ALLOWED_ON_FIXTURES
    assert answer.execution is ExecutionEligibility.BLOCKED_UNSUPPORTED
    assert any("close-only" in r for r in answer.reasons)
    # The research result itself is unchanged by the execution answer: a replay still reports.
    pol = FollowerPolicy(limits(), enrollments=enrolled("L1"))
    r = replay([signal("b")], pol, initial_cash=D(100), books=Books(book(captured=at(1))), resolutions={},
               config=config(), horizon=at(days=1))
    assert r.follower.label == "FOLLOWER_SIMULATED_ECONOMICS" and r.fills[0].status is FillStatus.FILLED


def test_paused_and_monitoring_gap_leaders_are_not_liquidated():
    pol = FollowerPolicy(limits(), enrollments={"L1": Enrollment("L1", at(-100), LeaderStatus.MONITORING_GAP)})
    fb = FollowerBook(D(100))
    assert pol.decide(signal("b"), fb, now=at(2)).kind is IntentKind.SKIP
    unknown_fraction = signal("s", Action.TRADE_SELL, before=None)
    fb.record_buy(signal("seed"), ((D("0.4"), D(5)),), D(0))
    assert pol.decide(unknown_fraction, fb, now=at(2)).kind is IntentKind.HOLD_FLAGGED


def test_unknown_request_outcome_is_never_a_win():
    pol = FollowerPolicy(limits(), enrollments=enrolled("L1"))
    res = {"m1-yes": Resolution("m1-yes", D(1), at(hours=2))}
    r = replay([signal("b")], pol, initial_cash=D(100), books=Books(book(captured=at(1))), resolutions=res,
               config=config(request_outcome=lambda sid, n: RequestResult.UNKNOWN), horizon=at(days=1))
    assert r.fills[0].status is FillStatus.UNKNOWN and r.follower.unknown_fills == 1
    assert not r.follower.gross_pnl.known and not r.follower.net_pnl.known
    assert r.final_book.inventory == {}
    assert Decimal(0) == r.follower.final_cash - D(100)
