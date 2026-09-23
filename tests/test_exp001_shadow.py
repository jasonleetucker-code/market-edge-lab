"""Gate 6: EXP-001 Stage B shadow lifecycle end to end, from forward evidence to settlement."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from edge_lab import cli, exp001_shadow as shadow, exp001_stageb as stageb
from edge_lab.http import FetchResult, HttpFetchError
from edge_lab.kalshi import SETTLEMENT_SOURCE, _save
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.storage import SnapshotStore
from test_forward import BRACKETS, MARKETS, D, _full_day, at, default_routes

CLOSED = at(23, 0)  # D's re-check windows closed (2026-09-22 23:00Z)


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path / "fwd.sqlite3")


@pytest.fixture
def ledger(tmp_path):
    return ShadowLedger(tmp_path / "ledger.sqlite3")


@pytest.fixture(scope="module")
def model():
    return stageb.load_model()


def _settled(store, value, result_for):
    """Store a settled-markets page as Kalshi would return it (expiration_value + result)."""
    markets = [dict(m, status="settled", expiration_value=str(value), result=result_for(m)) for m in MARKETS["markets"]]
    payload = {"markets": markets, "cursor": None}
    fetch = FetchResult("u", "u", 200, "application/json", json.dumps(payload).encode(), "2026-09-24T14:00:00+00:00", 1, 1)
    store.start_run("settle-run")
    _save(store, run_id="settle-run", kind="settled_markets", entity_id="KXHIGHNY", url="u", payload=payload,
          fetch=fetch, spec=SETTLEMENT_SOURCE)
    store.finish_run("settle-run", status="succeeded")


def _result(value):
    from edge_lab import settlement
    return lambda m: settlement.resolve(m, value).outcome.value


def test_full_lifecycle_decision_fill_settle(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    summary = shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    evaluation = stageb.evaluate_day(store, D, model=model)
    qualified = [o for o in evaluation.opportunities if o.qualification == "QUALIFY"]
    assert summary["stage_b_day_status"] == "VALID"
    assert summary["decisions"] == 12 and summary["qualified"] == len(qualified) == summary["filled"]
    state = ledger.state(shadow.ACCOUNT_ID)
    assert state.decisions == 12 and state.fills == len(qualified)
    assert all(p.quantity == 1 and p.status == "OPEN" for p in state.positions)
    for p in state.positions:  # entry at the decision ask, fees from the schedule
        opp = next(o for o in qualified if f"fill-{o.opportunity_id}" == p.position_id)
        assert p.price == opp.executable_price and p.cost_basis == opp.all_in_cost
    assert state.committed_capital == sum(o.all_in_cost for o in qualified)
    assert state.equity == shadow.STARTING_BANKROLL

    # Settle on 67°F: B67.5 YES wins, B65.5 YES loses, T72 NO wins.
    _settled(store, 67, _result(67))
    report = shadow.settle_open_positions(store, ledger)
    assert len(report["settled"]) == 2 * len(qualified) and report["pending"] == []  # research + operational
    assert {r["account_id"] for r in report["settled"]} == {shadow.ACCOUNT_ID, shadow.RESEARCH_ACCOUNT_ID}
    state = ledger.state(shadow.ACCOUNT_ID)
    expected = sum((Decimal(1) if (o.side == "YES") == o.market_id.endswith("B67.5") else Decimal(0)) - o.all_in_cost
                   for o in qualified)
    assert state.realized_pnl == expected and state.committed_capital == 0
    assert state.equity == shadow.STARTING_BANKROLL + expected == state.settled_cash


def test_rerun_and_restart_are_idempotent(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    before = ledger.state(shadow.ACCOUNT_ID).to_dict()
    n = len(ledger.entries(shadow.ACCOUNT_ID))
    shadow.run_day(store, ShadowLedger(ledger.path), D, model=model, now=CLOSED)  # restart: new handle, same file
    assert len(ledger.entries(shadow.ACCOUNT_ID)) == n
    assert ledger.state(shadow.ACCOUNT_ID).to_dict() == before
    _settled(store, 67, _result(67))
    shadow.settle_open_positions(store, ledger)
    m = len(ledger.entries(shadow.ACCOUNT_ID))
    shadow.settle_open_positions(store, ledger)
    assert len(ledger.entries(shadow.ACCOUNT_ID)) == m


def test_deterministic_replay_across_ledgers(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)
    a, b = ShadowLedger(tmp_path / "a.sqlite3"), ShadowLedger(tmp_path / "b.sqlite3")
    for lg in (a, b):
        shadow.run_day(store, lg, D, model=model, now=CLOSED)
    assert a.verify_chain(shadow.ACCOUNT_ID) == b.verify_chain(shadow.ACCOUNT_ID)
    assert a.state(shadow.ACCOUNT_ID).to_dict() == b.state(shadow.ACCOUNT_ID).to_dict()


def test_invalid_day_is_excluded_never_traded(store, ledger, monkeypatch, model):
    routes = {f"/markets/{BRACKETS[0]}/orderbook": HttpFetchError("HTTP 500", status=500, attempts=3),
              **default_routes()}
    _full_day(store, monkeypatch, routes)
    summary = shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    state = ledger.state(shadow.ACCOUNT_ID)
    assert summary["stage_b_day_status"] == "INVALID" and summary["filled"] == 0 and state.fills == 0
    assert summary["qualified"] == 0 and state.qualified_decisions == 0  # EVIDENCE_INCOMPLETE
    assert state.decisions == 12  # rejected and qualified decisions are all kept as evidence


def test_missing_recheck_is_invalid_day_no_fill(store, ledger, monkeypatch, model):
    from test_forward import Clock, FakeApi, _run, at
    clock = Clock(at(21, 45))
    api = FakeApi(clock)
    _run(store, "pfm", clock, api, monkeypatch)
    clock.now = at(21, 55, 5)
    _run(store, "decision", clock, api, monkeypatch)  # no recheck
    summary = shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    assert summary["stage_b_day_status"] == "INVALID" and ledger.state(shadow.ACCOUNT_ID).fills == 0


def test_price_moved_away_at_recheck_is_no_fill(store, ledger, monkeypatch, model):
    from test_forward import BOOK
    worse = {"orderbook_fp": {"yes_dollars": [["0.0100", "5"]], "no_dollars": [["0.0100", "5"]]}}
    calls = {"n": 0}

    def book(url):
        calls["n"] += 1
        return BOOK if calls["n"] <= len(BRACKETS) else worse  # decision books, then worse rechecks

    routes = default_routes()
    routes["/orderbook"] = book
    _full_day(store, monkeypatch, routes)
    summary = shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    assert summary["stage_b_day_status"] == "VALID" and summary["filled"] == 0
    assert set(summary["no_fill"]) == {"PRICE_MOVED_AWAY"}
    assert ledger.state(shadow.ACCOUNT_ID).settled_cash == shadow.STARTING_BANKROLL


def test_conflicting_settlement_evidence_stays_pending(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    _settled(store, 67, lambda m: "yes")  # Kalshi says YES everywhere: contradicts the resolver
    report = shadow.settle_open_positions(store, ledger)
    state = ledger.state(shadow.ACCOUNT_ID)
    assert state.settlements < state.fills and report["pending"]
    assert any("Kalshi recorded" in p["reason"] for p in report["pending"])


def test_no_settlement_evidence_stays_open(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    report = shadow.settle_open_positions(store, ledger)
    assert report["settled"] == [] and all(p["reason"] == "no settlement evidence yet" for p in report["pending"])


def test_decisions_carry_sizing_and_fee_status(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    rows = [json.loads(r["payload_json"]) for r in ledger.entries(shadow.ACCOUNT_ID) if r["kind"] == "decision"]
    for d in rows:
        assert d["claimable"] is False and d["opportunity"]["fee_status"] == "UNVERIFIED_CURRENT_SCHEDULE"
        if d["qualification"] == "QUALIFY":
            s = d["sizing"]
            assert s["final_size"] == 1 and s["binding_constraint"] == "SIZING_RULE"
            assert {"raw_size", "risk_adjusted_size", "liquidity_capped_size"} <= set(s)
        else:
            assert d["sizing"] is None


def test_cli_shadow_commands(store, tmp_path, monkeypatch, capsys):
    _full_day(store, monkeypatch)
    lg = tmp_path / "cli-ledger.sqlite3"
    assert cli.main(["shadow", "run", "--db", str(store.path), "--ledger", str(lg), "--date", D.isoformat()]) == 0
    assert json.loads(capsys.readouterr().out)["decisions"] == 12
    assert cli.main(["shadow", "account", "--ledger", str(lg)]) == 0
    account = json.loads(capsys.readouterr().out)
    assert account["equity"] == "1000.00" and account["decisions"] == 12
    assert cli.main(["shadow", "settle", "--db", str(store.path), "--ledger", str(lg)]) == 0
    assert cli.main(["shadow", "account", "--ledger", str(tmp_path / "none.sqlite3")]) == 2
    assert cli.main(["shadow", "run", "--db", str(tmp_path / "none.sqlite3"), "--ledger", str(lg),
                     "--date", D.isoformat()]) == 2


def test_starting_bankroll_is_notional():
    assert shadow.STARTING_BANKROLL == Decimal("1000.00")
    assert shadow.SIZING_POLICY.fixed_contracts == 1 and shadow.SIZING_POLICY.kelly_fraction is None
    assert timedelta(minutes=10) == shadow.LATENCY_CONFIRMED_V1.confirm_min


def test_open_day_is_refused_and_a_day_is_never_traded_twice(store, ledger, monkeypatch, model):
    from test_forward import Clock, FakeApi, _run, at
    clock = Clock(at(21, 45))
    api = FakeApi(clock)
    _run(store, "pfm", clock, api, monkeypatch)
    clock.now = at(21, 55, 5)
    _run(store, "decision", clock, api, monkeypatch)
    early = shadow.run_day(store, ledger, D, model=model, now=at(22, 3))  # recheck window still open
    assert early["stage_b_day_status"] == "NOT_CLOSED" and early["decisions"] == 0
    assert not ledger.accounts()  # nothing recorded at all
    clock.now = at(22, 5)
    _run(store, "recheck", clock, api, monkeypatch)
    done = shadow.run_day(store, ledger, D, model=model, now=at(23, 0))
    assert done["stage_b_day_status"] == "VALID" and done["filled"] == 3
    # A later engine/model change would give new opportunity ids; the slots still refuse them.
    import edge_lab.opportunity as op
    monkeypatch.setattr(op, "ENGINE_VERSION", "999")
    again = shadow.run_day(store, ledger, D, model=model, now=at(23, 0))
    state = ledger.state(shadow.ACCOUNT_ID)
    assert state.decisions == 12 and state.fills == 3 and again["decisions"] == 0
    assert len([p for p in again["problems"] if "already decided" in p and p.startswith(shadow.ACCOUNT_ID)]) == 12
    assert len([p for p in again["problems"] if "already decided" in p]) == 24  # both accounts refuse


def test_settlement_time_missing_stays_pending(store, ledger, monkeypatch, model):
    _full_day(store, monkeypatch)
    shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    markets = [dict(m, status="settled", expiration_value="67", result=_result(67)(m)) for m in MARKETS["markets"]]
    for m in markets:
        for k in ("settlement_ts", "expiration_time", "close_time"):
            m.pop(k, None)
    payload = {"markets": markets, "cursor": None}
    fetch = FetchResult("u", "u", 200, "application/json", json.dumps(payload).encode(), "2026-09-24T14:00:00+00:00", 1, 1)
    store.start_run("s2")
    _save(store, run_id="s2", kind="settled_markets", entity_id="KXHIGHNY", url="u", payload=payload, fetch=fetch,
          spec=SETTLEMENT_SOURCE)
    store.finish_run("s2", status="succeeded")
    report = shadow.settle_open_positions(store, ledger)
    assert report["settled"] == [] and all(p["reason"] == "settlement time missing" for p in report["pending"])
