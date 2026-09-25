"""Economic evidence · B: the EXP-003 payoff-scan result file on the Research tab (Economic Evidence v1).

Read-only: the newest `experiments/EXP-003-*/results/payoff_scan_*.json` by evaluation as-of, checked only with
`payoff_constraints.verify_result_provenance` against EXP-003's own evidence-use log; nothing is evaluated per
request and no page view writes anything. Fixtures copy the repository's EXP-003 into a temporary registry
(`sports_fixtures.payoff_registry`); the repository's files are never written.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard import sports_fixtures as sf
from edge_lab.dashboard.views import research

sys.path.insert(0, str(Path(__file__).resolve().parent / "browser"))
import fixture_states  # noqa: E402

NOW = sf.PAYOFF_NOW


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the dashboard attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).replace("&#x27;", "'").replace("&lt;", "<").split())


def load(root: Path, now=NOW) -> d.Loaded:
    return d.Context(Config(experiments_root=root, clock=lambda: now)).economic_b


def body(root: Path, now=NOW) -> str:
    return research.family_b_body(load(root, now), now)


def test_the_committed_laptop_result_is_shown_and_labelled_not_production(tmp_path):
    root = sf.payoff_registry(tmp_path)
    loaded = load(root)
    assert loaded.status == d.OK and loaded.value["state"] == "POPULATED"
    assert loaded.value["file"] == "payoff_scan_laptop_store_2026-09-22.json"
    assert loaded.value["verification"].startswith("verify_result_provenance")
    text = plain(body(root))
    for needle in ("PAYOFF RESEARCH — NOT A CAPTURED RESULT", "Laptop store · not production evidence",
                   "Not production evidence", "Proof completeness", "incomplete 2", "Proof incomplete",
                   "Claims (set × size)", "not evaluated 5", "no surplus even before fees 1",
                   "Settlement costs", "Unknown", "Positive claims", "INSUFFICIENT_DEPTH (complete capture offers 0 < 1)",
                   "No surplus, even before fees", "Orphan-leg exposure", "−$0.49", "As of Sep 22, 6:38 PM EDT",
                   "evidence-use event", "eu-374acc98ca83fac9d86ed28643e2bc54", "writes no evidence-use event"):
        assert needle in text, needle
    assert "k-ok" not in body(root)  # nothing green
    assert "$1.14" in text  # an all-in acquisition cost is a cost, not a surplus


def test_the_newest_result_by_evaluation_as_of_wins_and_only_its_positive_claim_shows_a_figure(tmp_path):
    root = sf.payoff_registry(tmp_path, production=True, positive=True)
    loaded = load(root)
    assert loaded.status == d.OK and loaded.value["file"] == "payoff_scan_SYNTHETIC_production_2026-09-24.json"
    html = body(root)
    text = plain(html)
    assert "Production store" in text and "Not production evidence" not in text
    assert "Conditional full-fill surplus · not captured" in text
    assert "$0.03" in text and "conditional on every leg filling · not captured arbitrage" in text
    assert html.count("conditional on every leg filling") == 1  # one positive claim, one figure (claim-adjusted)
    # every other claim shows no figure: the surplus column is unavailable with its reason
    # (the unavailable marker carries its reason twice: title and aria-label)
    assert html.count("no positive claim: the evaluator made none at this size") == 2 * 5


def test_no_positive_figure_without_a_positive_claim(tmp_path):
    text = plain(body(sf.payoff_registry(tmp_path)))
    assert "Positive claims 0" in text and "Conditional full-fill surplus · not captured" not in text
    assert "−$1.06" not in text and "−$1.14" not in text  # before-fees and upper-bound surpluses never shown


def test_stale_empty_blocked_error_and_unavailable_states(tmp_path):
    stale = plain(body(sf.payoff_registry(tmp_path / "s"), NOW + timedelta(days=10)))
    assert "Result is stale" in stale and "older than 8 days" in stale and "Stale · not current" in stale
    fresh = load(sf.payoff_registry(tmp_path / "f"), NOW + timedelta(days=5))  # 7.6 days after its books
    assert fresh.value["state"] == "POPULATED"  # 8 days is the threshold
    empty = plain(body(sf.payoff_registry(tmp_path / "e", results=False)))
    assert "No EXP-003 result recorded yet" in empty
    blocked = plain(body(sf.payoff_registry(tmp_path / "b", slot_status="QUEUED")))
    assert "EXP-003 results not shown" in blocked and "QUEUED" in blocked and "Proof" not in blocked
    error = body(sf.payoff_registry(tmp_path / "x", tamper=True))
    assert "Family B unavailable (read error)" in plain(error) and "does not verify" in plain(error)
    assert 'role="alert"' in error and "Proof complete" not in plain(error)  # a tampered PROVEN is never shown
    unavailable = plain(research.family_b_body(d.Loaded(d.NO_DATA, message="no experiment registry configured"), NOW))
    assert "Not yet available" in unavailable


def test_a_newer_file_that_does_not_verify_is_an_error_not_a_silent_fallback(tmp_path):
    root = sf.payoff_registry(tmp_path, production=True)
    newest = next(root.glob("EXP-003-*/results/payoff_scan_SYNTHETIC_production_*.json"))
    obj = json.loads(newest.read_text(encoding="utf-8"))
    obj["provenance"]["source_store"] = "production"
    obj["provenance"]["evidence_use_event_id"] = "eu-" + "0" * 32  # not in the log
    newest.write_text(json.dumps(obj), encoding="utf-8")
    loaded = load(root)
    assert loaded.status == d.ERROR and newest.name in loaded.message


def test_unreadable_files_and_the_file_bound(tmp_path, monkeypatch):
    root = sf.payoff_registry(tmp_path)
    results = next(root.glob("EXP-003-*/results"))
    (results / "payoff_scan_broken.json").write_text("{not json", encoding="utf-8")
    loaded = load(root)
    assert loaded.status == d.OK and any("payoff_scan_broken.json" in u for u in loaded.value["unreadable"])
    assert "payoff_scan_broken.json" in plain(body(root))
    monkeypatch.setattr(d, "PAYOFF_RESULT_MAX_FILES", 1)
    assert load(root).status == d.ERROR


def test_page_views_write_nothing_and_never_touch_the_repository(tmp_path):
    root = sf.payoff_registry(tmp_path)
    log = next(root.glob("EXP-003-*/evidence_use.jsonl"))
    before = hashlib.sha256(log.read_bytes()).hexdigest()
    repo_log = next((sf.REPO_EXPERIMENTS).glob("EXP-003-*/evidence_use.jsonl"))
    repo_before = hashlib.sha256(repo_log.read_bytes()).hexdigest()
    for _ in range(3):
        body(root)
    assert hashlib.sha256(log.read_bytes()).hexdigest() == before
    assert hashlib.sha256(repo_log.read_bytes()).hexdigest() == repo_before


@pytest.mark.parametrize("name", ["payoff", "payoff_laptop"])
def test_the_research_tab_renders_section_b(name):
    cfg, root = fixture_states.BUILDERS[name]()
    try:
        out = {}
        page = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/experiments", "QUERY_STRING": "",
                                       "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("s", s))).decode()
        assert out["s"] == "200 OK"
        part = page[page.index('aria-labelledby="ev-b-h"'):]
        text = plain(part[:part.index("</section>")])
        assert ("Production store" in text) == (name == "payoff")
        assert ("Not production evidence" in text) == (name == "payoff_laptop")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_gallery_shows_every_family_b_state():
    cfg, root = fixture_states.demo()
    out = {}
    page = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/gallery", "QUERY_STRING": "",
                                   "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("s", s))).decode()
    assert out["s"] == "200 OK"
    for sid in ("g-evb-production", "g-evb-laptop", "g-evb-states"):
        assert f'aria-labelledby="{sid}"' in page
    part = page[page.index('aria-labelledby="g-evb-states"'):]
    text = plain(part[:part.index("</section>")])
    for needle in ("Result is stale", "No EXP-003 result recorded yet", "EXP-003 results not shown",
                   "Family B unavailable (read error)", "Not yet available"):
        assert needle in text, needle
