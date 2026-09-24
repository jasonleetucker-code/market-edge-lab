"""Issue #50 P0-2: every daily receipt is also appended to an append-only history, so the per-run
provenance (code_version, settlement refresh status and errors, missing days, problems) is not
lost when shadow_daily.json is replaced. The receipt itself, its state and exit code are unchanged."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from edge_lab import daily, exp001_stageb as stageb
from edge_lab.storage import SnapshotStore
from test_exp001_shadow import CLOSED
from test_forward import _full_day


@pytest.fixture(scope="module")
def model():
    return stageb.load_model()


def _lines(status_dir):
    return [json.loads(line) for line in (status_dir / daily.HISTORY_NAME).read_text(encoding="utf-8").splitlines()]


def test_each_run_appends_exactly_its_receipt(tmp_path, monkeypatch, model):
    store = SnapshotStore(tmp_path / "edge.sqlite3")
    _full_day(store, monkeypatch)
    status_dir = tmp_path / "status"
    receipts = []
    for i, code_version in enumerate(("sha-one", "sha-two")):
        receipt, code = daily.run(store.path, tmp_path / "ledger.sqlite3", status_dir=status_dir, model=model,
                                  now=CLOSED + timedelta(hours=i), code_version=code_version)
        assert (receipt["state"], code) == ("PENDING_SETTLEMENT", 0) and receipt["exit_code"] == code
        latest = json.loads((status_dir / daily.RECEIPT_NAME).read_text(encoding="utf-8"))
        assert latest == json.loads(json.dumps(receipt))  # the latest receipt is exactly what the run returned
        receipts.append(latest)
    history = _lines(status_dir)
    assert history == receipts  # one line per run, in order, identical to each run's receipt
    assert [h["code_version"] for h in history] == ["sha-one", "sha-two"]
    assert "shadow_daily_history" not in json.dumps(receipts[-1])  # the receipt schema itself is unchanged


def test_history_is_never_truncated_and_covers_early_exits(tmp_path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    (status_dir / daily.HISTORY_NAME).write_text('{"earlier": "line"}\n', encoding="utf-8")
    receipt, code = daily.run(tmp_path / "missing.sqlite3", tmp_path / "l.sqlite3", status_dir=status_dir, now=CLOSED)
    assert (receipt["state"], code) == ("NO_CAPTURE", 0)
    history = _lines(status_dir)
    assert history[0] == {"earlier": "line"} and history[1]["state"] == "NO_CAPTURE" and len(history) == 2


def test_a_history_that_cannot_be_appended_never_changes_the_run(tmp_path, capsys):
    status_dir = tmp_path / "status"
    (status_dir / daily.HISTORY_NAME).mkdir(parents=True)  # a directory: every append fails
    receipt, code = daily.run(tmp_path / "missing.sqlite3", tmp_path / "l.sqlite3", status_dir=status_dir, now=CLOSED)
    assert (receipt["state"], code, receipt["exit_code"]) == ("NO_CAPTURE", 0, 0)
    stored = json.loads((status_dir / daily.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert stored == json.loads(json.dumps(receipt))  # the latest receipt is still written, unchanged
    assert "receipt history not appended" in capsys.readouterr().err


def test_no_status_dir_writes_nothing(tmp_path):
    receipt, code = daily.run(tmp_path / "missing.sqlite3", tmp_path / "l.sqlite3", status_dir=None, now=CLOSED)
    assert code == 0 and not list(tmp_path.rglob(daily.HISTORY_NAME))
