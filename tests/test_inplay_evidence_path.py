"""End-to-end offline evidence path (#122 R2/R3; 2026-09-30 architecture-reconciliation directive).

journal file -> `inplay_evidence.replay_book_journal` (normalized, sequenced evidence and coverage)
-> `inplay_view.build_view` (freshness, source/state validity, the policy proposal, the replay comparison)
-> the `inplay-view/1` dict the Terminal formats.

These tests go through the consumer, not only a helper. Every journal is written by the test into its
own temporary directory: no protected, pilot or production evidence is read, and nothing is written
anywhere else.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from edge_lab import inplay_evidence as ev
from edge_lab import inplay_replay as rp
from edge_lab import inplay_view as iv
from edge_lab import position_policy as pp
from edge_lab.freshness import Freshness

FIXTURE = Path(__file__).parent / "fixtures" / "inplay" / "ws_orderbook_journal_fixture.jsonl"
TICKER = "KXNFLGAME-FIXTURE-HOME"
T0 = datetime.fromisoformat("2026-10-04T17:00:00+00:00")


def _at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def _ms(seconds: float) -> int:
    return int((T0 + timedelta(seconds=seconds)).timestamp() * 1000)


def _snap(sid: int, seq: int, yes=(("0.3000", "100.00"),)) -> dict:
    return {"type": "orderbook_snapshot", "sid": sid, "seq": seq,
            "msg": {"market_ticker": TICKER, "yes_dollars_fp": [list(x) for x in yes], "no_dollars_fp": []}}


def _delta(sid: int, seq: int, *, ts: float | None, price: str = "0.3000", qty: str = "1.00") -> dict:
    body = {"market_ticker": TICKER, "price_dollars": price, "delta_fp": qty, "side": "yes"}
    if ts is not None:
        body["ts_ms"] = _ms(ts)
    return {"type": "orderbook_delta", "sid": sid, "seq": seq, "msg": body}


def _journal(tmp_path: Path, kind: str, rows: list[tuple[float, str, dict]], name: str = "j.jsonl") -> Path:
    p = tmp_path / name
    lines = [{"journal": "inplay-journal-v1", "data_kind": kind, "note": "written by this test"}]
    lines += [{"receipt_utc": _at(t), "kind": k, "body": b} for t, k, b in rows]
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return p


def _view(path: Path, *, as_of_seconds: float, state_variant: str | None = None,
          cohort: rp.Cohort | None = None) -> dict:
    """The consumer, fed from the file exactly as a future reviewed caller would feed it."""
    _, transitions, failures, parse_failures, kind = ev.replay_book_journal(path, TICKER)
    as_of = T0 + timedelta(seconds=as_of_seconds)
    policy = pp.PositionPolicy("inplay-fixed-target-v1", "1", pp.PolicyKind.FIXED_TARGET_FULL_EXIT,
                               pp.ExecutionAssumption.BOT_TRIGGERED_IOC, target_price=D("0.70"),
                               max_book_age=timedelta(seconds=15))
    inventory = pp.Inventory(f"kalshi:{TICKER}", "YES", D(100), D(100), pp.InventoryKind.SIMULATED,
                             as_of.isoformat(), "test:simulated-entry")
    fee_model = pp.UnknownFeeModel("none", "evidence-path test")
    cfg = None if cohort is None else rp.ReplayConfig(target_price=D("0.70"), partial_fraction=D("0.5"),
                                                      fee_model=fee_model)
    return iv.build_view(mode=iv.Mode.FIXTURE, market_ticker=TICKER, game_label="FIXTURE home team to win",
                         transitions=transitions, failures=failures, parse_failures=parse_failures, as_of=as_of,
                         window_start=T0, trading=ev.TradingState.OPEN, inventory=inventory, orders=(),
                         policy=policy, fee_model=fee_model, rules_version="fixture-rules-v1", cohort=cohort,
                         replay_config=cfg, data_kind=kind, state_variant=state_variant)


# ------------------------------------------------------------------ the whole path, attributable and reproducible


def test_the_fixture_journal_reaches_the_view_with_its_label_coverage_and_refusals():
    view = _view(FIXTURE, as_of_seconds=16)
    assert view["mode"] == "FIXTURE" and view["contract"]["data_kind"] == "FIXTURE"
    src = view["source"]
    # every failure and unusable interval from the file survives into the consumer's coverage
    assert src["gaps"] == 1 and src["resyncs"] == 1 and src["duplicates"] == 1 and src["parse_failures"] == 2
    assert {f["kind"] for f in src["failures"]} == {"DISCONNECTED", "PARSE_ERROR"}
    reasons = {u["reason"] for u in src["unusable"]}
    assert {"NO_VALID_START", "GAP_AWAITING_RESYNC"} <= reasons
    assert view["state"] == "PARTIAL"  # gaps and failures are kept, not dropped
    # the policy saw the book as FIXTURE evidence at the configured as-of, and authorizes nothing
    assert view["policy"]["authorizes_execution"] is False
    assert view["as_of_utc"] == _at(16) and view["after_cost_claim"] is False


def test_the_same_pinned_journal_config_and_as_of_reproduce_the_same_view(tmp_path):
    cohort = rp.synthetic_martingale_cohort(seed=11, games=6, step_seconds=5, games_per_cluster=3,
                                            entry_fee_known=False)
    first = _view(FIXTURE, as_of_seconds=16, state_variant="populated", cohort=cohort)
    copy = tmp_path / "copy.jsonl"
    copy.write_bytes(FIXTURE.read_bytes())
    again = _view(copy, as_of_seconds=16, state_variant="populated", cohort=cohort)
    assert first == again
    assert first["comparison"]["cohort_sha256"] == cohort.sha256 and first["comparison"]["data_kind"] == "SYNTHETIC"
    later = _view(FIXTURE, as_of_seconds=40, state_variant="populated", cohort=cohort)
    assert later["as_of_utc"] != first["as_of_utc"] and later["state"] == "STALE"  # the as-of is the replay clock


# ------------------------------------------------------------------ data kind: never inferred, never defaulted


@pytest.mark.parametrize("kind", [k.value for k in ev.DataKind])
def test_a_journal_with_no_lines_keeps_its_header_data_kind(tmp_path, kind):
    path = _journal(tmp_path, kind, [])
    *_, got = ev.replay_book_journal(path, TICKER)
    assert got is ev.DataKind(kind)


def test_an_empty_recorded_journal_is_refused_by_the_consumer_not_relabelled_synthetic(tmp_path):
    path = _journal(tmp_path, "RECORDED", [])
    with pytest.raises(ValueError, match="recorded in-play evidence"):
        _view(path, as_of_seconds=5)


def test_a_journal_without_a_known_data_kind_is_refused(tmp_path):
    p = tmp_path / "nokind.jsonl"
    p.write_text(json.dumps({"journal": "inplay-journal-v1"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ev.replay_book_journal(p, TICKER)


# ------------------------------------------------------------------ source stamps: never carried to other content


def test_a_resynced_book_does_not_inherit_a_venue_stamp_from_before_the_gap(tmp_path):
    rows = [(0, "book", _snap(1, 1)),
            (1, "book", _delta(1, 2, ts=0.95)),
            (2, "book", _delta(1, 5, ts=1.95)),  # seq 3-4 lost: unusable until a snapshot
            (600, "book", _snap(2, 1, yes=(("0.6000", "50.00"),)))]  # a new subscription; snapshots carry no ts_ms
    view = _view(_journal(tmp_path, "FIXTURE", rows), as_of_seconds=605, state_variant="populated")
    assert view["source"]["book_status"] == "VALID" and view["source"]["last_receipt_utc"] == _at(600)
    # the book now holds sid 2's snapshot, whose publication time the venue did not send
    assert view["source"]["last_source_ts_utc"] is None
    ss = view["source_state"]
    assert ss["published_utc"] is None and ss["published_uncertainty"] is None
    assert ss["content_freshness"] == Freshness.UNKNOWN.value  # received 5 s ago; its content age is not known
    transport = next(r for r in ss["latency"] if r["stage"] == "TRANSPORT")
    assert transport["measured"] is False and transport["seconds"] is None  # not a 599 s "transport latency"


def test_a_delta_without_a_venue_stamp_leaves_the_book_stamp_unknown():
    msgs = [ev.parse_book_message(_snap(1, 1), receipt_utc=_at(0)),
            ev.parse_book_message(_delta(1, 2, ts=0.95), receipt_utc=_at(1)),
            ev.parse_book_message(_delta(1, 3, ts=None), receipt_utc=_at(2))]
    states = [t.state for t in ev.reconstruct(TICKER, msgs)[1]]
    assert [s.last_source_ts_utc for s in states] == [None, _at(0.95), None]
    assert states[-1].last_applied_receipt_utc == _at(2)  # the receipt is never promoted to a source time


def test_a_stamped_message_after_resync_carries_its_own_stamp(tmp_path):
    rows = [(0, "book", _snap(1, 1)), (1, "book", _delta(1, 3, ts=0.95)),
            (10, "book", _snap(2, 1)), (11, "book", _delta(2, 2, ts=10.9))]
    view = _view(_journal(tmp_path, "FIXTURE", rows), as_of_seconds=12, state_variant="populated")
    assert view["source"]["last_source_ts_utc"] == _at(10.9)
    transport = next(r for r in view["source_state"]["latency"] if r["stage"] == "TRANSPORT")
    assert transport["measured"] is True and D(transport["seconds"]) == D("0.1")
