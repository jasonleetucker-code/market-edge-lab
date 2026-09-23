"""Daily orchestration: states, idempotency, read-only evidence, locks, catch-up, settlement refresh."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from edge_lab import daily, exp001_shadow as shadow, exp001_stageb as stageb, forward, kalshi
from edge_lab.http import FetchResult, HttpFetchError
from edge_lab.shadow_ledger import LedgerConflict, ShadowLedger
from edge_lab.storage import SnapshotStore
from test_exp001_shadow import CLOSED, _result, _settled
from test_forward import BRACKETS, MARKETS, D, _full_day, default_routes

UTC = timezone.utc


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path / "edge.sqlite3")


@pytest.fixture(scope="module")
def model():
    return stageb.load_model()


def _hashes(db):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(db.parent.glob(db.name + "*"))
            if not p.name.endswith((".lock", "-shm"))}  # -shm: WAL read-mark index, holds no data


def _run(store, tmp_path, model, **kw):
    kw.setdefault("now", CLOSED)
    return daily.run(store.path, tmp_path / "ledger.sqlite3", status_dir=tmp_path / "status", model=model, **kw)


def test_no_evidence_store_yet_is_no_capture(tmp_path):
    receipt, code = daily.run(tmp_path / "missing.sqlite3", tmp_path / "l.sqlite3", status_dir=tmp_path / "s",
                              now=CLOSED)
    assert (receipt["state"], code) == ("NO_CAPTURE", 0)
    assert not (tmp_path / "missing.sqlite3").exists() and not (tmp_path / "l.sqlite3").exists()
    assert json.loads((tmp_path / "s" / daily.RECEIPT_NAME).read_text())["state"] == "NO_CAPTURE"


def test_valid_signal_day_is_recorded_pending_and_evidence_untouched(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)
    before = _hashes(store.path)
    receipt, code = _run(store, tmp_path, model)
    assert code == 0 and receipt["state"] == "PENDING_SETTLEMENT"
    (day,) = receipt["days"]
    assert day["target_date"] == D.isoformat() and day["capture_status"] == "VALID"
    assert day["result"] == "HEALTHY_TRADED" and day["decision_time_utc"] == "2026-09-22T22:00:00+00:00"
    assert day["accounts"][shadow.RESEARCH_ACCOUNT_ID]["fills"] == 3
    assert receipt["accounts"][shadow.ACCOUNT_ID]["equity_basis"].startswith("cost basis")
    assert receipt["fee"] == {"schedule_id": "kalshi-quadratic-taker-v1", "status": "UNVERIFIED_CURRENT_SCHEDULE",
                              "claimable": False}
    assert receipt["generated_at_utc"] == CLOSED.isoformat() and receipt["valid_days"] == 1
    assert _hashes(store.path) == before  # analysis never changes the evidence store
    stored = json.loads((tmp_path / "status" / daily.RECEIPT_NAME).read_text())
    assert stored["state"] == "PENDING_SETTLEMENT" and stored["exit_code"] == 0


def test_rerun_is_idempotent_and_settles_when_evidence_exists(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)
    _run(store, tmp_path, model)
    ledger = ShadowLedger(tmp_path / "ledger.sqlite3")
    n = {a: len(ledger.entries(a)) for a in ledger.accounts()}
    _run(store, tmp_path, model, now=CLOSED + timedelta(hours=1))
    assert {a: len(ledger.entries(a)) for a in ledger.accounts()} == n
    _settled(store, 67, _result(67))  # evidence received 2026-09-24T14:00Z
    receipt, code = _run(store, tmp_path, model, now=datetime(2026, 9, 24, 15, tzinfo=UTC))
    assert code == 0, receipt["problems"] + [d["problems"] for d in receipt["days"]]
    assert receipt["state"] == "HEALTHY_TRADED" and receipt["settlement"]["settled"] == 6
    assert receipt["settlement"]["pending"] == []
    assert receipt["accounts"][shadow.RESEARCH_ACCOUNT_ID]["settlements"] == 3


def test_no_signal_valid_day(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)
    monkeypatch.setattr(stageb, "evaluate_day", _no_qualify(stageb.evaluate_day))
    receipt, code = _run(store, tmp_path, model)
    assert (receipt["state"], code) == ("HEALTHY_NO_SIGNAL", 0)
    assert receipt["days"][0]["result"] == "HEALTHY_NO_SIGNAL"


def _no_qualify(real):
    from dataclasses import replace

    def wrapped(*a, **kw):
        ev = real(*a, **kw)
        return replace(ev, opportunities=[replace(o, qualification="REJECT", rejection_reason="EDGE_BELOW_THRESHOLD")
                                          for o in ev.opportunities])
    return wrapped


def test_invalid_capture_day_exits_3_and_fills_nothing(store, tmp_path, monkeypatch, model):
    routes = {f"/markets/{BRACKETS[0]}/orderbook": HttpFetchError("HTTP 500", status=500, attempts=3),
              **default_routes()}
    _full_day(store, monkeypatch, routes)
    receipt, code = _run(store, tmp_path, model)
    assert (receipt["state"], code) == ("INVALID_CAPTURE", 3)
    assert all(a["fills"] == 0 for a in receipt["days"][0]["accounts"].values())


def test_lock_busy_is_explicit(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)
    with forward.exclusive_lock(store.path.with_name(store.path.name + ".forward.lock")):
        receipt, code = _run(store, tmp_path, model, lock_timeout_s=0.2)
    assert (receipt["state"], code) == ("LOCK_BUSY", 1)
    assert not (tmp_path / "ledger.sqlite3").exists()


def test_ledger_conflict_is_failed_not_a_crash(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)

    def boom(*a, **kw):
        raise LedgerConflict("decision dec-x already recorded with different content")
    monkeypatch.setattr(shadow, "run_day", boom)
    receipt, code = _run(store, tmp_path, model)
    assert (receipt["state"], code) == ("FAILED", 1)
    assert receipt["days"][0]["result"] == "FAILED" and "LedgerConflict" in receipt["days"][0]["problems"][0]


def test_open_day_is_not_processed(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)
    receipt, code = _run(store, tmp_path, model, now=datetime(2026, 9, 22, 22, 3, tzinfo=UTC))
    assert (receipt["state"], code) == ("NOT_CLOSED", 0) and receipt["days"] == []


def test_settlement_refresh_is_targeted_and_settles(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)
    _run(store, tmp_path, model)
    urls = []

    def fake_json(url, **kwargs):
        urls.append(url)
        markets = [dict(m, status="settled", expiration_value="67", result=_result(67)(m)) for m in MARKETS["markets"]]
        return ({"markets": markets, "cursor": ""},
                FetchResult(url, url, 200, "application/json", b"{}", "2026-09-24T15:00:00+00:00", 1, 1))
    monkeypatch.setattr(kalshi, "fetch_json_result", fake_json)
    early = datetime(2026, 9, 23, 3, tzinfo=UTC)  # before settlement is due: no request at all
    receipt, _ = _run(store, tmp_path, model, now=early, refresh_settlements=True)
    assert urls == [] and receipt["settlement"]["refresh"]["status"] == "skipped"
    due = datetime(2026, 9, 24, 16, tzinfo=UTC)
    receipt, code = _run(store, tmp_path, model, now=due, refresh_settlements=True)
    assert len(urls) == 1 and "event_ticker=KXHIGHNY-26SEP23" in urls[0]
    assert receipt["settlement"]["refresh"]["status"] == "ok" and receipt["settlement"]["settled"] == 6
    assert (receipt["state"], code) == ("HEALTHY_TRADED", 0)


def test_failed_refresh_keeps_bookkeeping_and_reports_failed(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)

    def down(url, **kwargs):
        raise HttpFetchError("HTTP 503", status=503, attempts=3)
    monkeypatch.setattr(kalshi, "fetch_json_result", down)
    receipt, code = _run(store, tmp_path, model, now=datetime(2026, 9, 24, 16, tzinfo=UTC), refresh_settlements=True)
    assert (receipt["state"], code) == ("FAILED", 1)
    assert receipt["settlement"]["refresh"]["status"] == "failed"
    assert receipt["days"][0]["result"] == "HEALTHY_TRADED"  # decisions and fills were still recorded
    assert len(receipt["settlement"]["pending"]) == 6
