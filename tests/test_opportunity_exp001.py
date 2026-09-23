"""Gate 5: EXP-001 probabilities and forward Kalshi books plugged into the opportunity engine."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from edge_lab import cli, exp001_baseline as base, exp001_stageb as stageb, fees, forward, settlement
from edge_lab.http import HttpFetchError
from edge_lab.storage import SnapshotStore
from test_forward import BOOK, BRACKETS, MARKETS, D, _full_day, default_routes


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path / "fwd.sqlite3")


@pytest.fixture(scope="module")
def model():
    return stageb.load_model()


def test_stage_b_model_is_the_frozen_refit(model):
    days = base.load_fit_window(stageb.DATASET, base.FIT_SPLITS) + base.load_test_for_reproduction(
        stageb.DATASET, stageb.GATE4)
    days = [d for d in days if d.target_date <= "2026-09-21"]
    assert model.variant == "V1"  # Stage A's selection
    assert model.n_fit == len(days) == 3551
    assert model.pmfs["ALL"] == base.fit_model("V1", days).pmfs["ALL"]
    assert math.isclose(math.fsum(model.pmfs["ALL"]), 1.0)
    assert stageb.load_model() is model  # the refit is computed once per process


def test_stage_b_refuses_without_a_stage_a_pass(tmp_path):
    (tmp_path / base.STAGE_A_FILE).write_text(json.dumps({"verdict": "FAIL", "selected_variant": "V1"}))
    with pytest.raises(stageb.StageBUnavailable):
        stageb.load_model.__wrapped__(stageb.DATASET, tmp_path)
    with pytest.raises(stageb.StageBUnavailable):
        stageb.load_model.__wrapped__(stageb.DATASET, tmp_path / "missing")


def test_bracket_probabilities_partition_the_pmf(model):
    f = 67
    probs = []
    for raw in MARKETS["markets"]:
        p, why = stageb.bracket_probability(model, raw, f, D)
        assert why is None
        probs.append(p)
    # The six brackets (<65, 65-66, 67-68, 69-70, 71-72, >72) cover every integer once.
    assert math.isclose(math.fsum(probs), 1.0, abs_tol=1e-12)
    b675 = next(m for m in MARKETS["markets"] if m["ticker"].endswith("B67.5"))
    pmf = model.pmfs["ALL"]
    assert stageb.bracket_probability(model, b675, f, D)[0] == pytest.approx(pmf[20] + pmf[21])


def test_unresolvable_bracket_has_no_probability(model):
    bad = dict(MARKETS["markets"][0], floor_strike=1)
    p, why = stageb.bracket_probability(model, bad, 67, D)
    assert p is None and "resolver" in why


def test_full_forward_day_plugs_into_the_engine(store, monkeypatch, model):
    _full_day(store, monkeypatch)
    result = stageb.evaluate_day(store, D, model=model)
    assert result.day_status["status"] == "VALID" and result.problems == []
    opps = result.opportunities
    assert len(opps) == 2 * len(BRACKETS)  # every bracket and side, nothing dropped
    assert {o.market_id for o in opps} == {f"kalshi:{t}" for t in BRACKETS}
    assert result.forecast["forecast_max_f"] == 67 and result.as_of_utc == "2026-09-22T22:00:00+00:00"

    # Executable prices from the captured book (the fixture serves one real book for every bracket).
    no_bids = [(Decimal(p), Decimal(s)) for p, s in BOOK["orderbook_fp"]["no_dollars"]]
    yes_bids = [(Decimal(p), Decimal(s)) for p, s in BOOK["orderbook_fp"]["yes_dollars"]]
    best_no, best_yes = max(no_bids), max(yes_bids)
    for o in opps:
        if o.side == "YES":
            assert o.executable_price == 1 - best_no[0] and o.displayed_size == best_no[1]
        else:
            assert o.executable_price == 1 - best_yes[0] and o.displayed_size == best_yes[1]
        assert o.quote_evidence_id.startswith("snapshot:")
        assert o.book_freshness == "fresh" and o.model_freshness == "fresh"
        assert o.fee_status == "UNVERIFIED_CURRENT_SCHEDULE" and not o.claimable
        assert o.policy_id == "EXP-001-stage-b-frozen-v1" and o.model_version == model.version
        assert o.all_in_cost is not None and o.rejection_reason in ("QUALIFY", "NO_EDGE")
    # The frozen signal: qualify iff p_side - cost_per_contract(1, ask) >= 0.05.
    for o in opps:
        cost = fees.cost_per_contract(1, o.executable_price)
        assert o.all_in_cost == cost
        assert (o.qualification == "QUALIFY") == (o.model_probability - cost >= Decimal("0.05"))
    # YES probabilities of the event sum to one.
    assert math.isclose(sum(float(o.model_probability) for o in opps if o.side == "YES"), 1.0, abs_tol=1e-9)


def test_evaluation_is_repeatable_from_evidence(store, monkeypatch, model):
    _full_day(store, monkeypatch)
    a = stageb.evaluate_day(store, D, model=model).to_dict()
    b = stageb.evaluate_day(store, D, model=model).to_dict()
    assert a == b


def test_missing_bracket_book_is_book_missing_not_zero(store, monkeypatch, model):
    missing = BRACKETS[0]
    routes = {f"/markets/{missing}/orderbook": HttpFetchError("HTTP 500", status=500, attempts=3),
              **default_routes()}
    _full_day(store, monkeypatch, routes)
    result = stageb.evaluate_day(store, D, model=model)
    assert result.day_status["status"] == "INVALID"
    gone = [o for o in result.opportunities if o.market_id == f"kalshi:{missing}"]
    assert len(gone) == 2 and all(o.rejection_reason == "BOOK_MISSING" for o in gone)
    assert all(o.executable_price is None and o.net_edge is None for o in gone)
    others = [o for o in result.opportunities if o.market_id != f"kalshi:{missing}"]
    assert all(o.rejection_reason != "BOOK_MISSING" for o in others)


def test_no_decision_capture_means_no_opportunities(store, model):
    result = stageb.evaluate_day(store, D, model=model)
    assert result.opportunities == [] and result.day_status["status"] == "INVALID"
    assert any("no complete decision capture" in p for p in result.problems)


def test_market_of_another_event_fails_closed(store, monkeypatch, model):
    # One listed market belongs to the next day's event. The capture is partial (no books),
    # and the adapter still evaluates it for research: the foreign market can never match.
    foreign = BRACKETS[0]
    markets = {"cursor": None, "markets": [dict(m, event_ticker="KXHIGHNY-26SEP24") if m["ticker"] == foreign else m
                                           for m in MARKETS["markets"]]}
    routes = default_routes()
    routes["/markets?event_ticker=KXHIGHNY-26SEP23"] = markets
    _full_day(store, monkeypatch, routes)
    result = stageb.evaluate_day(store, D, model=model)
    assert result.day_status["status"] == "INVALID"
    assert any("partial capture" in p for p in result.problems)
    by_market = {o.market_id: o for o in result.opportunities}
    assert by_market[f"kalshi:{foreign}"].rejection_reason == "EVENT_MISMATCH"
    assert all(o.rejection_reason == "BOOK_MISSING" for o in result.opportunities
               if o.market_id != f"kalshi:{foreign}")


def test_wrong_event_payload_fails_closed(store, monkeypatch, model):
    _full_day(store, monkeypatch)
    monkeypatch.setattr(stageb, "check_event_identity", lambda *a: "captured event is not the target")
    result = stageb.evaluate_day(store, D, model=model)
    assert all(o.rejection_reason == "EVENT_MISMATCH" for o in result.opportunities)
    assert any("event:" in p for p in result.problems)


def test_stale_forecast_is_model_stale(store, monkeypatch, model):
    _full_day(store, monkeypatch)
    monkeypatch.setattr(stageb.forward, "select_pfm", lambda *a, **k: (None, "PFM_STALE_AT_CUTOFF"))
    result = stageb.evaluate_day(store, D, model=model)
    assert all(o.rejection_reason == "MODEL_STALE" for o in result.opportunities)
    assert all(o.model_probability is None for o in result.opportunities)


def test_no_forecast_is_model_unavailable(store, monkeypatch, model):
    _full_day(store, monkeypatch)
    monkeypatch.setattr(stageb.forward, "select_pfm", lambda *a, **k: (None, "NO_PFM_BEFORE_CUTOFF"))
    result = stageb.evaluate_day(store, D, model=model)
    assert all(o.rejection_reason == "MODEL_UNAVAILABLE" for o in result.opportunities)


def test_policy_is_the_frozen_stage_b_rule():
    p = stageb.STAGE_B_POLICY
    assert (p.edge_basis, p.min_net_edge, p.quantity) == ("point", Decimal("0.05"), 1)
    assert p.max_book_age == timedelta(minutes=5)
    assert p.max_model_input_age == timedelta(hours=24, minutes=30)
    assert p.fee_verification == "flag"  # evaluated, but never claimable on unverified fees


def test_cli_opportunities_report(store, monkeypatch, tmp_path, capsys):
    _full_day(store, monkeypatch)
    out = tmp_path / "opps.json"
    assert cli.main(["forward", "opportunities", "--db", str(store.path), "--date", D.isoformat(),
                     "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["stage_b_day_status"] == "VALID"
    assert report["counts"]["opportunities"] == 12
    assert report["fee_schedule"]["status"] == "UNVERIFIED_CURRENT_SCHEDULE"
    assert json.loads(capsys.readouterr().out) == report
    assert cli.main(["forward", "opportunities", "--db", str(tmp_path / "nope.sqlite3"), "--date", "2026-09-23"]) == 2
    assert cli.main(["forward", "opportunities", "--db", str(store.path), "--date", "Sep 23"]) == 2


def test_resolver_is_the_frozen_one():
    assert stageb.settlement is settlement and stageb.forward is forward
