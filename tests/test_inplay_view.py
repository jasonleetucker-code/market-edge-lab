"""The in-play research view contract inplay-view/1 (#122 §21B)."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal as D

import pytest

from edge_lab import inplay_evidence as ev
from edge_lab import inplay_view as iv
from edge_lab import position_policy as pp


@pytest.fixture(scope="module")
def views():
    return {k: iv.fixture_view(k) for k in iv.FIXTURE_VARIANTS}


def test_every_variant_has_its_state(views):
    assert {k: v["state"] for k, v in views.items()} == {
        "populated": "POPULATED", "empty": "EMPTY", "stale": "STALE", "partial": "PARTIAL", "resync": "PARTIAL",
        "unsupported": "UNSUPPORTED", "paused": "PAUSED", "error": "ERROR", "not_authorized": "NOT_AUTHORIZED",
        "invalidated": "POPULATED", "state_unknown": "POPULATED"}
    for v in views.values():
        assert v["schema"] == iv.VIEW_SCHEMA and v["mode"] != "LIVE" and "NOT LIVE" in v["label"]
        json.dumps(v)  # plain data: the Terminal only formats it


def test_populated_view_is_honest(views):
    v = views["populated"]
    assert v["mode"] == "FIXTURE" and v["contract"]["data_kind"] == "FIXTURE"
    assert v["inventory"]["kind"] == "SIMULATED" and "balance" not in json.dumps(v).lower()
    assert v["policy"]["action"] == "EXIT" and v["policy"]["authorizes_execution"] is False
    # KXNFLGAME fees are unverified: no after-cost figure anywhere
    assert v["policy"]["net_proceeds"] is None and v["exit_estimate"]["net"] is None
    assert v["exit_estimate"]["gross"] is not None and "not a fill" in v["exit_estimate"]["note"]
    assert all(a["pnl_net"] is None and a["change_vs_hold_net"] is None for a in v["comparison"]["arms"])
    assert v["after_cost_claim"] is False
    assert {d["label"] for d in v["diagnostics"]} == {"FIRST_DETECTION_ZERO_LATENCY", "HINDSIGHT_UPPER_BOUND"}
    assert v["comparison"]["data_kind"] == "SYNTHETIC" and "edge" not in {k.lower() for k in v}


def test_stale_paused_and_resync_views_never_propose_a_sale(views):
    for name in ("stale", "paused", "resync"):
        v = views[name]
        assert v["policy"]["status"] == "BLOCKED" and v["policy"]["action"] is None
        assert v["exit_estimate"]["gross"] is None  # no proceeds from a stale, paused or unusable book


def test_partial_view_keeps_gaps_and_failures(views):
    v = views["partial"]
    assert v["source"]["gaps"] == 1 and v["source"]["resyncs"] == 1
    assert [f["kind"] for f in v["source"]["failures"]] == ["DISCONNECTED"]
    assert D(v["source"]["coverage_fraction"]) < 1


def test_empty_and_unsupported_views(views):
    assert views["empty"]["source"]["book_status"] == "NO_VALID_START" and views["empty"]["comparison"] is None
    assert views["unsupported"]["policy"]["status"] == "UNSUPPORTED"


def test_not_authorized_and_error_views_hold_no_figures(views):
    for name in ("not_authorized", "error"):
        v = views[name]
        assert v["policy"] is None and v["comparison"] is None and v["exit_estimate"] is None
        assert "NOT APPROVED" in v["pilot"] and "EXECUTION_NOT_AUTHORIZED" in v["authority"]


def test_the_view_refuses_recorded_data_and_actual_inventory():
    base = dict(mode=iv.Mode.FIXTURE, market_ticker="X", game_label="g", transitions=(),
                as_of=iv._T0, window_start=iv._T0, trading=ev.TradingState.OPEN, orders=(),
                policy=iv._policy_for(), fee_model=pp.UnknownFeeModel("u", "r"), rules_version="r", cohort=None,
                replay_config=None)
    sim = pp.Inventory("kalshi:X", "YES", D(1), D(1), pp.InventoryKind.SIMULATED, iv._T0.isoformat(), "e")
    with pytest.raises(ValueError, match="experiment id"):
        iv.build_view(**base, inventory=sim, data_kind=ev.DataKind.RECORDED)
    actual = pp.Inventory("kalshi:X", "YES", D(1), D(1), pp.InventoryKind.ACTUAL, iv._T0.isoformat(), "e")
    with pytest.raises(ValueError, match="simulated"):
        iv.build_view(**base, inventory=actual, data_kind=ev.DataKind.FIXTURE)
    with pytest.raises(ValueError):
        iv.build_view(**{**base, "mode": iv.Mode.NOT_AUTHORIZED}, inventory=sim, data_kind=ev.DataKind.FIXTURE)


def test_fixture_view_is_deterministic():
    assert iv.fixture_view("populated") == iv.fixture_view("populated")
    with pytest.raises(ValueError):
        iv.fixture_view("live")
    assert iv._policy_for().max_book_age == timedelta(seconds=15)
