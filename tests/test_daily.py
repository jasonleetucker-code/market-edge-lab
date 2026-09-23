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
    # 2026-09-24's own window has closed with no capture stored: that day is lost -> INVALID.
    assert receipt["state"] == "INVALID_CAPTURE" and code == 3 and receipt["settlement"]["settled"] == 6
    assert receipt["missing_capture_days"] == ["2026-09-24"]
    assert receipt["latest_day"] == {"target_date": "2026-09-24", "result": "INVALID_CAPTURE",
                                     "capture_status": "MISSING_CAPTURE"}
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
    assert receipt["settlement"]["pending"] == []


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


def test_evidence_received_after_now_is_not_used_yet(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)
    _settled(store, 67, _result(67))  # stored with receipt time 2026-09-24T14:00Z
    receipt, code = _run(store, tmp_path, model, now=datetime(2026, 9, 23, 21, tzinfo=UTC))
    assert (receipt["state"], code) == ("PENDING_SETTLEMENT", 0) and receipt["missing_capture_days"] == []
    assert receipt["settlement"]["settled"] == 0


def test_invalid_day_alerts_once_not_every_run(store, tmp_path, monkeypatch, model):
    routes = {f"/markets/{BRACKETS[0]}/orderbook": HttpFetchError("HTTP 500", status=500, attempts=3),
              **default_routes()}
    _full_day(store, monkeypatch, routes)
    first, code1 = _run(store, tmp_path, model)
    again, code2 = _run(store, tmp_path, model, now=CLOSED + timedelta(hours=12))
    assert (first["state"], code1) == ("INVALID_CAPTURE", 3)
    assert (again["state"], code2) == ("INVALID_CAPTURE", 0) and again["repeat_of_previous_alert"] is True


def test_unexpected_errors_still_write_a_failed_receipt(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)
    monkeypatch.setattr(daily, "closed_capture_days", lambda *a, **k: (_ for _ in ()).throw(KeyError("boom")))
    receipt, code = _run(store, tmp_path, model)
    assert (receipt["state"], code) == ("FAILED", 1) and "KeyError" in receipt["problems"][0]
    assert json.loads((tmp_path / "status" / daily.RECEIPT_NAME).read_text())["state"] == "FAILED"


def test_crash_between_decision_and_fill_is_completed_later(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)
    ledger = ShadowLedger(tmp_path / "ledger.sqlite3")
    real = ShadowLedger.record_fill
    calls = {"n": 0}

    def crash_once(self, account, payload):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated crash mid-day")
        return real(self, account, payload)
    monkeypatch.setattr(ShadowLedger, "record_fill", crash_once)
    first, _ = _run(store, tmp_path, model)
    assert first["state"] == "FAILED"
    monkeypatch.setattr(ShadowLedger, "record_fill", real)
    assert daily.incomplete_days(ledger, shadow.RESEARCH_ACCOUNT_ID) | daily.incomplete_days(ledger, shadow.ACCOUNT_ID)
    second, code = _run(store, tmp_path, model, now=CLOSED + timedelta(minutes=30))
    assert code == 0 and not (daily.incomplete_days(ledger, shadow.RESEARCH_ACCOUNT_ID)
                              | daily.incomplete_days(ledger, shadow.ACCOUNT_ID))
    assert ledger.state(shadow.RESEARCH_ACCOUNT_ID).fills == 3


def test_a_transient_failure_never_wedges_the_pipeline(store, tmp_path, monkeypatch, model):
    """Review NB1: a failed day must not let later-received settlements be recorded before its
    fills, or the knowledge-time rule would refuse those fills forever."""
    _full_day(store, monkeypatch)
    _settled(store, 67, _result(67))  # evidence received 2026-09-24T14:00Z, already on file
    ledger = ShadowLedger(tmp_path / "ledger.sqlite3")
    real = ShadowLedger.record_fill
    calls = {"n": 0}

    def flaky(self, account, payload):
        calls["n"] += 1
        if calls["n"] == 5:  # the operational account's second fill
            from edge_lab.shadow_ledger import LedgerError
            raise LedgerError("ledger shadow_ledger.sqlite3 is locked or busy (waited 5s)")
        return real(self, account, payload)
    monkeypatch.setattr(ShadowLedger, "record_fill", flaky)
    at = datetime(2026, 9, 24, 15, tzinfo=UTC)
    first, _ = _run(store, tmp_path, model, now=at)
    assert first["state"] == "FAILED"
    assert first["settlement"]["evidence_cutoff_utc"] == "2026-09-22T22:00:00+00:00"  # held back
    assert first["settlement"]["settled"] == 0
    monkeypatch.setattr(ShadowLedger, "record_fill", real)
    second, _ = _run(store, tmp_path, model, now=at + timedelta(minutes=5))
    assert second["days"][0]["result"] == "HEALTHY_TRADED" and second["settlement"]["settled"] == 6
    assert not (daily.incomplete_days(ledger, shadow.RESEARCH_ACCOUNT_ID) | daily.incomplete_days(ledger, shadow.ACCOUNT_ID))


def test_formatting_differences_are_not_settlement_conflicts(store, tmp_path, monkeypatch, model):
    _full_day(store, monkeypatch)
    _settled(store, 67, _result(67))
    _settled_run(store, "67.00", _result(67), "again")  # the same outcome, formatted differently
    receipt, _ = _run(store, tmp_path, model, now=datetime(2026, 9, 24, 15, tzinfo=UTC))
    assert receipt["settlement"]["conflicts"] == [] and receipt["settlement"]["settled"] == 6


def test_contradicting_settlement_evidence_alerts_once(store, tmp_path, monkeypatch, model):
    # Evidence received before D+1's window closes, so no missed day interferes.
    _full_day(store, monkeypatch)
    _settled_run(store, 67, _result(67), "first", received="2026-09-23T12:00:00+00:00")
    _run(store, tmp_path, model, now=datetime(2026, 9, 23, 20, tzinfo=UTC))
    _settled_run(store, 70, _result(70), "later", received="2026-09-23T13:00:00+00:00")
    receipt, code = _run(store, tmp_path, model, now=datetime(2026, 9, 23, 21, tzinfo=UTC))
    assert (receipt["state"], code) == ("SETTLEMENT_CONFLICT", 1) and receipt["settlement"]["conflicts"]
    again, code2 = _run(store, tmp_path, model, now=datetime(2026, 9, 23, 21, 30, tzinfo=UTC))
    assert (again["state"], code2) == ("SETTLEMENT_CONFLICT", 0) and again["repeat_of_previous_alert"]
    # Once D+1's window closes with no capture, the invalid day wins (and alerts); conflicts stay listed.
    later, code3 = _run(store, tmp_path, model, now=datetime(2026, 9, 24, 16, tzinfo=UTC))
    assert (later["state"], code3) == ("INVALID_CAPTURE", 3) and later["settlement"]["conflicts"]


def _settled_run(store, value, result_for, run_id, received="2026-09-24T14:30:00+00:00"):
    from edge_lab.kalshi import SETTLEMENT_SOURCE, _save
    markets = [dict(m, status="settled", expiration_value=str(value), result=result_for(m)) for m in MARKETS["markets"]]
    payload = {"markets": markets, "cursor": None}
    fetch = FetchResult("u", "u", 200, "application/json", json.dumps(payload).encode(), received, 1, 1)
    store.start_run(run_id)
    _save(store, run_id=run_id, kind="settled_markets", entity_id="KXHIGHNY", url="u", payload=payload,
          fetch=fetch, spec=SETTLEMENT_SOURCE)
    store.finish_run(run_id, status="succeeded")


def test_a_day_that_can_never_fill_does_not_hold_settlement_back(store, tmp_path, monkeypatch, model):
    from test_forward import Clock, FakeApi, _run as capture
    # An earlier day whose only capture is the forecast (no markets, no opportunities).
    early = Clock(datetime(2026, 9, 21, 21, 45, tzinfo=UTC))
    capture(store, "pfm", early, FakeApi(early), monkeypatch)
    _full_day(store, monkeypatch)
    _settled(store, 67, _result(67))
    receipt, _ = _run(store, tmp_path, model, now=datetime(2026, 9, 24, 15, tzinfo=UTC))
    assert receipt["settlement"]["settled"] == 6
    assert receipt["settlement"]["evidence_cutoff_utc"] == "2026-09-24T15:00:00+00:00"


def test_sigterm_during_shadow_daily_writes_a_failed_receipt(store, tmp_path, monkeypatch, model):
    import os
    import signal

    from edge_lab import cli
    _full_day(store, monkeypatch)

    def killed(*a, **k):
        os.kill(os.getpid(), signal.SIGTERM)
    monkeypatch.setattr(daily, "_run_locked", killed)
    old = signal.getsignal(signal.SIGTERM)
    try:
        with pytest.raises(SystemExit):
            cli.main(["shadow", "daily", "--db", str(store.path), "--ledger", str(tmp_path / "l.sqlite3"),
                      "--status-dir", str(tmp_path / "st")])
    finally:
        signal.signal(signal.SIGTERM, old)
    receipt = json.loads((tmp_path / "st" / daily.RECEIPT_NAME).read_text())
    assert receipt["state"] == "FAILED" and "interrupted" in receipt["problems"][-1]
