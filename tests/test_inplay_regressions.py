"""#122 offline boundary: no network, no order transport, no writes to production evidence."""

from __future__ import annotations

import ast
import socket
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from edge_lab import inplay_evidence, inplay_replay, position_policy

SRC = Path(__file__).resolve().parents[1] / "src" / "edge_lab"
MODULES = {"inplay_evidence": inplay_evidence, "inplay_replay": inplay_replay, "position_policy": position_policy}
FIXTURE = Path(__file__).parent / "fixtures" / "inplay" / "ws_orderbook_journal_fixture.jsonl"

NETWORK = {"socket", "ssl", "http", "urllib", "asyncio", "websockets", "websocket", "requests", "httpx", "aiohttp",
           "edge_lab.http", "edge_lab.kalshi", "edge_lab.forward", "edge_lab.odds_api", "edge_lab.polymarket_us",
           "edge_lab.notify_ntfy"}
STORAGE = {"sqlite3", "shelve", "edge_lab.storage", "edge_lab.shadow_ledger", "edge_lab.ledger_anchor",
           "edge_lab.backup", "edge_lab.research_evidence", "edge_lab.daily"}


def _imports(name: str) -> set[str]:
    tree = ast.parse((SRC / f"{name}.py").read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = ("edge_lab." if node.level else "") + (node.module or "")
            out.add(base)
    return out


def _top(names: set[str]) -> set[str]:
    return names | {n.split(".")[0] for n in names}


@pytest.mark.parametrize("name", sorted(MODULES))
def test_no_network_or_transport_imports(name):
    found = _top(_imports(name))
    assert not found & NETWORK, found & NETWORK


@pytest.mark.parametrize("name", sorted(MODULES))
def test_no_production_storage_or_ledger_imports(name):
    found = _top(_imports(name))
    assert not found & STORAGE, found & STORAGE
    text = (SRC / f"{name}.py").read_text(encoding="utf-8")
    assert "/var/lib" not in text and "edge_lab.sqlite3" not in text and ".write_text(" not in text


@pytest.mark.parametrize("name", sorted(MODULES))
def test_no_order_submission_or_signing_surface(name):
    tree = ast.parse((SRC / f"{name}.py").read_text(encoding="utf-8"))
    defs = {n.name.lower() for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    for word in ("submit", "sign", "send", "transport", "connect", "authenticate", "credential"):
        assert not [d for d in defs if word in d], (name, word)


def test_importing_the_modules_opens_no_socket():
    code = ("import socket\n"
            "def boom(*a, **k):\n    raise SystemExit('socket opened on import')\n"
            "socket.socket = boom\nsocket.create_connection = boom\n"
            "import edge_lab.inplay_evidence, edge_lab.inplay_replay, edge_lab.position_policy\nprint('ok')\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={"PYTHONPATH": str(SRC.parent), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr


def test_running_the_offline_foundation_opens_no_socket_and_writes_nothing(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("network attempted")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.chdir(tmp_path)
    repo = Path(__file__).resolve().parents[1]
    watched = [repo / "experiments", repo / "tests" / "fixtures" / "inplay"]
    before = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}

    state, ts, failures, pf, _ = inplay_evidence.replay_book_journal(FIXTURE, "KXNFLGAME-FIXTURE-HOME")
    inplay_evidence.coverage_report("KXNFLGAME-FIXTURE-HOME", ts, window_start="2026-10-04T17:00:00Z",
                                    window_end="2026-10-04T17:01:00Z", max_silence=timedelta(seconds=5),
                                    failures=failures, parse_failures=pf)
    cohort = inplay_replay.synthetic_martingale_cohort(seed=3, games=20)
    cfg = inplay_replay.ReplayConfig(target_price=D("0.70"), partial_fraction=D("0.5"),
                                     fee_model=position_policy.UnknownFeeModel("none", "offline test"))
    report = inplay_replay.replay(cohort, cfg)
    assert report.data_kind == "SYNTHETIC" and not report.after_cost_claim

    assert list(tmp_path.iterdir()) == []
    after = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()}
    assert after == before


def test_execution_stays_not_authorized():
    from edge_lab.execution_ticket import Control

    assert list(Control)[-1] is Control.EXECUTION_NOT_AUTHORIZED
    decision = position_policy.evaluate(
        as_of=__import__("datetime").datetime(2026, 10, 4, tzinfo=__import__("datetime").timezone.utc),
        inventory=None, orders=(), book=None, fee_model=None,
        policy=position_policy.PositionPolicy("p", "1", position_policy.PolicyKind.HOLD_TO_SETTLEMENT,
                                              position_policy.ExecutionAssumption.NONE),
        rules_version="r")
    assert decision.authorizes_execution is False
