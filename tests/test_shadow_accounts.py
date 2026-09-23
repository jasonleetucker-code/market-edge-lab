"""Research vs operational accounts, pre-fill risk enforcement, point-in-time cash, fee flags."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from edge_lab import exp001_shadow as shadow, exp001_stageb as stageb
from edge_lab.shadow_ledger import LedgerError, ShadowLedger
from edge_lab.storage import SnapshotStore
from test_exp001_shadow import CLOSED, _result, _settled
from test_forward import D, _full_day

UTC = timezone.utc


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path / "fwd.sqlite3")


@pytest.fixture
def ledger(tmp_path):
    return ShadowLedger(tmp_path / "ledger.sqlite3")


@pytest.fixture(scope="module")
def model():
    return stageb.load_model()


def _payloads(ledger, account, kind):
    return [json.loads(r["payload_json"]) for r in ledger.entries(account) if r["kind"] == kind]


def test_research_account_records_the_frozen_rule(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    summary = shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    research = summary["accounts"][shadow.RESEARCH_ACCOUNT_ID]
    assert research["qualified"] == research["filled"] == 3 and research["no_fill"] == {}
    for d in _payloads(ledger, shadow.RESEARCH_ACCOUNT_ID, "decision"):
        if d["qualification"] == "QUALIFY":
            assert d["sizing"] == {"policy_id": shadow.RESEARCH_SIZING_ID, "final_size": 1,
                                   "binding_constraint": "FROZEN_RULE_ONE_CONTRACT"}
    assert ledger.state(shadow.RESEARCH_ACCOUNT_ID).starting_bankroll == shadow.RESEARCH_BANKROLL


def test_zero_capacity_vetoes_operational_fills_and_never_the_research_record(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    tight = replace(shadow.RISK_POLICY, policy_id="tight", daily_loss_limit=Decimal("0"))
    operational = replace(shadow.OPERATIONAL, risk_policy=tight)
    summary = shadow.run_day(store, ledger, D, model=model, now=CLOSED, accounts=(shadow.RESEARCH, operational))
    op = summary["accounts"][shadow.ACCOUNT_ID]
    assert op["filled"] == 0 and op["no_fill"] == {"RISK_VETO": 3} and len(op["vetoes"]) == 3
    fills = _payloads(ledger, shadow.ACCOUNT_ID, "fill")
    assert all(f["status"] == "NO_FILL" and f["risk_veto"]["binding"] == "REMAINING_RISK_CAPACITY"
               and f["risk_veto"]["remaining_risk_capacity"] == "0" for f in fills)
    assert summary["accounts"][shadow.RESEARCH_ACCOUNT_ID]["filled"] == 3
    assert ledger.state(shadow.ACCOUNT_ID).settled_cash == shadow.STARTING_BANKROLL


def test_consecutive_candidates_are_vetoed_once_the_event_cap_is_used(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    capped = replace(shadow.RISK_POLICY, policy_id="event-cap", max_event_risk=Decimal("1.00"))
    operational = replace(shadow.OPERATIONAL, risk_policy=capped)
    summary = shadow.run_day(store, ledger, D, model=model, now=CLOSED, accounts=(operational,))
    op = summary["accounts"][shadow.ACCOUNT_ID]
    state = ledger.state(shadow.ACCOUNT_ID)
    assert op["filled"] >= 1 and op["no_fill"].get("RISK_VETO", 0) >= 1
    assert state.event_exposure(state.positions[0].event_id) <= Decimal("1.00")
    assert {v["binding"] for v in op["vetoes"]} <= {"MAX_EVENT_RISK", "MAX_CLUSTER_RISK", "REMAINING_RISK_CAPACITY"}


def test_risk_veto_boundaries(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    evaluation = stageb.evaluate_day(store, D, model=model)
    opp = next(o for o in evaluation.opportunities if o.qualification == "QUALIFY")
    shadow.ensure_account(ledger)
    state = ledger.state(shadow.ACCOUNT_ID)
    at = datetime(2026, 9, 22, 22, 10, tzinfo=UTC)
    cost = Decimal("0.50")
    at_limit = replace(shadow.RISK_POLICY, max_position_risk=cost)
    assert shadow.risk_veto(state, cost, opp, at_limit, at) is None  # exactly at the limit: allowed
    veto = shadow.risk_veto(state, cost + Decimal("0.01"), opp, at_limit, at)
    assert veto["binding"] == "MAX_POSITION_RISK" and veto["limit"] == "0.50"
    reserve = replace(shadow.RISK_POLICY, reserve_floor=shadow.STARTING_BANKROLL)  # cash == reserve: capacity 0
    assert shadow.risk_veto(state, cost, opp, reserve, at)["binding"] == "REMAINING_RISK_CAPACITY"
    breached = replace(shadow.RISK_POLICY, reserve_floor=shadow.STARTING_BANKROLL + 1)
    assert shadow.risk_veto(state, cost, opp, breached, at)["binding"] == "RESERVE_FLOOR"


def test_fills_are_stamped_at_confirmation_and_carry_fee_status(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    for acct in (shadow.ACCOUNT_ID, shadow.RESEARCH_ACCOUNT_ID):
        for f in _payloads(ledger, acct, "fill"):
            assert f["fee_status"] == "UNVERIFIED_CURRENT_SCHEDULE" and f["claimable"] is False
            if f["status"] == "FILLED":
                assert f["filled_at_utc"] > f["decision_as_of_utc"]
    _settled(store, 67, _result(67))
    shadow.settle_open_positions(store, ledger, now=datetime(2026, 9, 24, 15, tzinfo=UTC))
    for acct in (shadow.ACCOUNT_ID, shadow.RESEARCH_ACCOUNT_ID):
        for s in _payloads(ledger, acct, "settlement"):
            ev = s["evidence"]
            assert s["claimable"] is False and s["fee_status"] == "UNVERIFIED_CURRENT_SCHEDULE"
            assert ev["evidence_available_utc"] == "2026-09-24T14:00:00+00:00"
            assert "processed_at_utc" not in ev  # processing time is the row's appended_at_utc


def test_settlement_evidence_received_later_is_ignored_in_catch_up(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    _settled(store, 67, _result(67))  # received 2026-09-24T14:00Z
    early = shadow.settle_open_positions(store, ledger, known_by=datetime(2026, 9, 24, 13, tzinfo=UTC))
    assert early["settled"] == [] and early["pending"]
    later = shadow.settle_open_positions(store, ledger, known_by=datetime(2026, 9, 24, 14, tzinfo=UTC))
    assert later["settled"]


ACCT = dict(starting_bankroll=Decimal("1.00"), strategy="t", opened_at_utc="2026-09-01T00:00:00+00:00",
            sizing_policy_id="s", fill_policy_id="f", fee_schedule_id="x")


def _decision(did, as_of):
    return {"decision_id": did, "opportunity_id": did, "as_of_utc": as_of, "qualification": "QUALIFY",
            "reason": None, "market_id": f"kalshi:{did}", "side": "YES", "event_id": "E"}


def _fill(did, at, cost="0.60"):
    return {"fill_id": f"f-{did}", "decision_id": did, "status": "FILLED", "reason": "FILLED", "filled_at_utc": at,
            "venue": "kalshi", "market_id": f"kalshi:{did}", "event_id": "E", "outcome_cluster": "C", "side": "YES",
            "quantity": 1, "price": "0.55", "total_cost": cost}


def test_a_settlement_learned_later_never_funds_an_earlier_fill(tmp_path):
    lg = ShadowLedger(tmp_path / "l.sqlite3")
    lg.open_account("A", **ACCT)
    lg.record_decision("A", _decision("a", "2026-09-02T22:00:00+00:00"))
    lg.record_fill("A", _fill("a", "2026-09-02T22:10:00+00:00"))
    lg.record_settlement("A", fill_id="f-a", outcome="YES", settled_at_utc="2026-09-03T12:00:00+00:00",
                         evidence={"evidence_available_utc": "2026-09-05T00:00:00+00:00"})
    # Catch-up: a position decided on 09-04, before the win above was known on 09-05.
    lg.record_decision("A", _decision("b", "2026-09-04T22:00:00+00:00"))
    assert lg.state("A").settled_cash == Decimal("1.40")
    assert lg.state_as_of("A", datetime(2026, 9, 4, 22, 10, tzinfo=UTC)).settled_cash == Decimal("0.40")
    with pytest.raises(LedgerError, match="out-of-order fill"):
        lg.record_fill("A", _fill("b", "2026-09-04T22:10:00+00:00"))
    lg.record_fill("A", _fill("b", "2026-09-05T00:10:00+00:00"))  # once the win was known, it is spendable


def test_cash_from_a_later_settlement_cannot_reach_back_even_via_in_order_times(tmp_path):
    """The reviewer's B1 scenario: F2 at t2, S2 known after t2, then F1 at t1 < t2 is refused."""
    lg = ShadowLedger(tmp_path / "b1.sqlite3")
    lg.open_account("A", **{**ACCT, "starting_bankroll": Decimal("11.50")})  # full-state cash covers F1
    lg.record_decision("A", _decision("f2", "2026-01-05T22:00:00+00:00"))
    lg.record_fill("A", _fill("f2", "2026-01-05T22:10:00+00:00", cost="6.00"))
    lg.record_settlement("A", fill_id="f-f2", outcome="YES", settled_at_utc="2026-01-06T12:00:00+00:00",
                         evidence={"evidence_available_utc": "2026-01-06T15:00:00+00:00"})
    lg.record_decision("A", _decision("f1", "2026-01-03T22:00:00+00:00"))
    with pytest.raises(LedgerError, match="out-of-order fill"):
        lg.record_fill("A", _fill("f1", "2026-01-03T22:10:00+00:00", cost="6.00"))
    for t in ("2026-01-03T23:00:00+00:00", "2026-01-05T23:00:00+00:00", "2026-01-06T16:00:00+00:00"):
        lg.state_as_of("A", datetime.fromisoformat(t))  # every instant stays consistent


def test_settlement_evidence_before_the_fill_or_settlement_time_is_refused(tmp_path):
    lg = ShadowLedger(tmp_path / "n2.sqlite3")
    lg.open_account("A", **ACCT)
    lg.record_decision("A", _decision("a", "2026-09-02T22:00:00+00:00"))
    lg.record_fill("A", _fill("a", "2026-09-02T22:10:00+00:00"))
    with pytest.raises(LedgerError, match="evidence must be received"):
        lg.record_settlement("A", fill_id="f-a", outcome="YES", settled_at_utc="2026-09-03T12:00:00+00:00",
                             evidence={"evidence_available_utc": "2026-09-03T11:00:00+00:00"})
