import json
from datetime import datetime, timezone

from edge_lab import cli
from edge_lab.http import HttpFetchError
from edge_lab.storage import SnapshotStore


def _save(store, run_id, source="kalshi", kind="series"):
    store.save_snapshot(
        run_id=run_id, source=source, kind=kind, entity_id="E",
        url="https://example.test", payload={"x": 1},
    )


def test_failing_source_does_not_abort_others_and_run_is_partial(tmp_path, monkeypatch, capsys):
    def good_kalshi(store, *, run_id, anomalies, **kwargs):
        _save(store, run_id)
        return {"series": 1}

    def bad_nws(store, *, run_id, **kwargs):
        raise HttpFetchError("HTTP 503 fetching https://api.weather.gov/points", status=503)

    monkeypatch.setattr(cli, "collect_series", good_kalshi)
    monkeypatch.setattr(cli, "collect_reference_forecast", bad_nws)
    db = tmp_path / "edge.sqlite3"

    code = cli.main(["collect", "--db", str(db), "--nws-user-agent", "test"])

    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["status"] == "partial"
    assert out["sources"]["kalshi_public"]["status"] == "ok"
    assert out["sources"]["nws_api"]["status"] == "failed"
    health = {row["source_id"]: row for row in SnapshotStore(db).latest_source_health()}
    assert health["nws_api"]["http_errors"] == 1
    assert health["nws_api"]["records"] == 0
    assert health["kalshi_public"]["records"] == 1


def test_error_after_some_records_is_partial_not_failed(tmp_path, monkeypatch, capsys):
    def half_kalshi(store, *, run_id, anomalies, **kwargs):
        _save(store, run_id)
        raise HttpFetchError("HTTP 500 fetching orderbook", status=500)

    monkeypatch.setattr(cli, "collect_series", half_kalshi)
    code = cli.main(["collect", "--source", "kalshi", "--db", str(tmp_path / "e.sqlite3")])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["sources"]["kalshi_public"]["status"] == "partial"


def test_all_ok_exits_zero(tmp_path, monkeypatch, capsys):
    def good_kalshi(store, *, run_id, anomalies, **kwargs):
        _save(store, run_id)
        return {"series": 1}

    monkeypatch.setattr(cli, "collect_series", good_kalshi)
    assert cli.main(["collect", "--source", "kalshi", "--db", str(tmp_path / "e.sqlite3")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "succeeded"


def test_health_report_marks_uncollected_kinds_unknown(tmp_path):
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    store.start_run("r")
    store.save_snapshot(
        run_id="r", source="kalshi", kind="orderbook", entity_id="E", url="u",
        payload={}, fetched_at_utc="2026-09-22T17:59:00+00:00",
    )
    now = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)

    report = {item["source_id"]: item for item in cli.health_report(store, now=now)}

    kalshi = report["kalshi_public"]["freshness"]
    assert kalshi["orderbook"] == "fresh"
    assert kalshi["markets"] == "unknown"  # never collected is not fresh
    assert set(report["nws_api"]["freshness"].values()) == {"unknown"}
    assert report["kalshi_public"]["last_status"] is None


def test_failed_fetch_retries_are_counted(tmp_path, monkeypatch, capsys):
    def flaky(store, *, run_id, anomalies, **kwargs):
        raise HttpFetchError("HTTP 503 fetching x", status=503, attempts=3)

    monkeypatch.setattr(cli, "collect_series", flaky)
    db = tmp_path / "e.sqlite3"
    cli.main(["collect", "--source", "kalshi", "--db", str(db)])
    (row,) = SnapshotStore(db).latest_source_health()
    assert row["retries"] == 2 and row["http_errors"] == 1


def test_aborted_collection_never_leaves_run_running(tmp_path, monkeypatch):
    import sqlite3

    import pytest

    def boom(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_run_source", boom)
    db = tmp_path / "e.sqlite3"
    with pytest.raises(KeyboardInterrupt):
        cli.main(["collect", "--source", "kalshi", "--db", str(db)])
    with sqlite3.connect(db) as conn:
        (status,) = conn.execute("SELECT status FROM collection_runs").fetchone()
    assert status == "failed"
