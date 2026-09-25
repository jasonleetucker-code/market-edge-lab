"""Sportsbook consensus at a capture (Research & Data -> Data sources -> Odds capture targets).

Owner directive 2026-09-24 (evening), Terminal v1 and contract C4; Lane C's research benchmark
(`odds_consensus`, ADR 0033). The Terminal formats the contract's result and never recomputes it:
"RESEARCH BENCHMARK — NOT EXECUTABLE", exact lines only, offered prices apart from consensus
probabilities, `freshness_as_of` displayed, unsupported groups with reason codes. States: populated,
no captures yet, unsupported / insufficient, stale / unknown freshness, this capture unusable
(newer_unusable), none, not installed, error, source unavailable.
"""

from __future__ import annotations

import importlib
import re
import shutil
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge_lab import odds_consensus
from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard import fixtures
from edge_lab.dashboard import presentation as pr
from edge_lab.dashboard.views import research
from edge_lab.freshness import Freshness

sys.path.insert(0, str(Path(__file__).resolve().parent / "browser"))
import fixture_states  # noqa: E402


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def get(cfg: Config) -> str:
    out = {}
    body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/experiments", "QUERY_STRING": "tab=sources",
                                   "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s)))
    assert out["status"] == "200 OK"
    part = body.decode("utf-8")
    part = part[part.index('aria-labelledby="odds-t-h"'):]
    return part[:part.index("</section>")]


def _disclosures(html: str) -> list[str]:
    """Each "Consensus at this capture" disclosure body (its own details element)."""
    out = []
    for m in re.finditer(r"<details class=\"disclosure\"><summary>(?:(?!</summary>).)*Consensus at this capture", html):
        start, depth, i = m.start(), 0, m.start()
        while True:
            nxt_open, nxt_close = html.find("<details", i + 1), html.find("</details>", i + 1)
            if nxt_open != -1 and nxt_open < nxt_close:
                depth, i = depth + 1, nxt_open
            elif depth:
                depth, i = depth - 1, nxt_close
            else:
                out.append(html[start:nxt_close])
                break
    return out


@pytest.fixture
def production():
    cfg, root = fixture_states.odds_pilot()
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def issues():
    cfg, root = fixture_states.odds_issues()
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


def test_the_label_is_the_contracts():
    assert research.CONSENSUS_LABEL == odds_consensus.LABEL == "RESEARCH BENCHMARK — NOT EXECUTABLE"


def test_production_shape_shows_the_contracts_consensus_at_the_capture(production, monkeypatch):
    seen = []
    real = odds_consensus.consensus_for_event
    monkeypatch.setattr(odds_consensus, "consensus_for_event",
                        lambda store, event_id, as_of: seen.append((event_id, as_of)) or real(store, event_id, as_of))
    targets = d.Context(production).odds_targets.value
    (cap,) = [t for t in targets.rows if t.state == "CAPTURED"]
    assert seen == [("fx000evt", datetime(2026, 9, 24, 18, 15, 41, tzinfo=timezone.utc))]  # only the row shown
    result = cap.consensus.value
    assert cap.consensus.status == d.OK and result.snapshot_id == cap.snapshot_id and not result.newer_unusable
    html = get(production)
    (body,) = _disclosures(html)
    text = plain(body)
    for needle in ("Consensus at this capture · RESEARCH BENCHMARK — NOT EXECUTABLE", "Snapshot 2",
                   "Freshness at this capture Fresh (worst of books)", "Books quoting this event 9",
                   "Consensus version odds-consensus-v1", "Moneyline (h2h) · Atlanta Falcons / Green Bay Packers",
                   "Spread (spreads) · Atlanta Falcons +3.5 / Green Bay Packers -3.5",
                   "Total (totals) · Over 47.5 / Under 47.5", "Books 9 contributing 9 quoting this market (any line)", "range_and_unscaled_mad_v1",
                   "Offered prices as received (18)", "not probabilities and not executable"):
        assert needle in text, needle
    # Every consensus figure shown is the contract's value, only formatted.
    for prop in result.events[0].propositions:
        for o in prop.consensus:
            assert pr.percent(o.consensus_probability) in text
            assert pr.pp_size(o.range) in text and pr.pp_size(o.mad) in text


def test_offered_prices_and_consensus_probabilities_are_never_in_one_block(production):
    (body,) = _disclosures(get(production))
    blocks = re.findall(r'<div role="group" aria-label="Consensus probability.*?</div></dl></div>', body, re.S)
    offered = [t for t in re.findall(r"<table.*?</table>", body, re.S) if "Offered prices," in t]
    assert len(blocks) == len(offered) == 3
    for block in blocks:
        assert "Consensus probability" in block and "(american)" not in block and "margin" not in block
    for t in offered:
        assert "consensus" not in t.lower() and "(american)" in t


def test_fallback_newer_unusable_insufficient_unsupported_and_stale(issues):
    bodies = _disclosures(get(issues))
    text = " ".join(plain(b) for b in bodies)
    for needle in ("1 newer capture of this event unusable", "EVENT_ABSENT", "This capture is not used",
                   "the latest usable earlier capture is shown: snapshot 2", "Freshness at this capture Stale",
                   "Status Insufficient books", "a consensus needs 2", "Not in any consensus (unsupported)",
                   "MISSING_COMPLEMENT", "betus", "Spread (spreads) · Arizona Cardinals +4.5 / Seattle Seahawks -4.5"):
        assert needle in text, needle


def test_the_display_uses_freshness_as_of_not_the_receipt_age_alone():
    loaded, sid = fixtures.synthetic_consensus()["fresh"]
    shown = replace(loaded.value, receipt_freshness_as_of=Freshness.FRESH, freshness_as_of=Freshness.STALE)
    text = plain(research.consensus_body(d.Loaded(d.OK, shown), sid))
    assert "Freshness at this capture Stale (worst of books)" in text and "Fresh (worst of books)" not in \
        text.split("Freshness at this capture")[1].split("Books quoting")[0]


@pytest.mark.parametrize("key,needles", [
    ("populated", ("Unknown (worst of books)", "Stale", "Insufficient books", "NOT_TWO_WAY", "MISSING_COMPLEMENT")),
    ("fresh", ("Freshness at this capture Fresh (worst of books)",)),
    ("fallback", ("1 newer capture of this event unusable", "This capture is not used")),
    ("failed_closed", ("No usable consensus at this capture", "PAYLOAD_HASH_MISMATCH")),
    ("none", ("No consensus for this capture",)),
    ("missing", ("No consensus found for this capture", "records snapshot 905", "inconsistent")),
    ("unavailable", ("Consensus unavailable", "not installed")),
    ("error", ("Consensus unavailable (read error)", "This is not an empty benchmark")),
])
def test_every_state_renders(key, needles):
    loaded, sid = fixtures.synthetic_consensus()[key]
    html = research.consensus_body(loaded, sid)
    text = plain(html)
    for needle in needles:
        assert needle in text, (key, needle)
    if key == "error":
        assert 'role="alert"' in html
    if key in ("populated", "fresh", "fallback"):
        assert "RESEARCH BENCHMARK — NOT EXECUTABLE" in text


def test_no_captures_means_no_consensus_call(tmp_path, monkeypatch):
    from edge_lab.odds_schedule import DEFAULT_OFFSETS, ScheduledEvent, iso_z, plan_targets
    from edge_lab.storage import SnapshotStore

    store = SnapshotStore(tmp_path / "edge_lab.sqlite3")
    event = ScheduledEvent("evt1", "americanfootball_nfl", datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc), "H", "A")
    for t in plan_targets([event], DEFAULT_OFFSETS):
        store.plan_odds_target(target_id=t.target_id, sport=t.sport, event_id=t.event_id, offset_label=t.offset_label,
                               priority=t.priority, commence_time_utc=iso_z(t.commence_utc),
                               target_utc=iso_z(t.target_utc), planned_at_utc="2026-09-23T12:00:00Z",
                               policy_version="game_relative_v1")
    called = []
    monkeypatch.setattr(odds_consensus, "consensus_for_event", lambda *a: called.append(a))
    cfg = Config(db=store.path, clock=lambda: datetime(2026, 9, 24, 21, 0, tzinfo=timezone.utc))
    html = get(cfg)
    assert called == [] and "No captures yet" in plain(html) and "Consensus at this capture" not in html


def test_a_consensus_failure_is_an_error_on_that_row_only(production, monkeypatch):
    def boom(store, event_id, as_of):
        raise RuntimeError(f"broken at {production.db}")
    monkeypatch.setattr(odds_consensus, "consensus_for_event", boom)
    result = d.Context(production).odds_targets
    assert result.status == d.OK
    (cap,) = [t for t in result.value.rows if t.state == "CAPTURED"]
    assert cap.consensus.status == d.ERROR and str(production.db) not in cap.consensus.message
    text = plain(get(production))
    assert "Consensus unavailable (read error)" in text and "Books returned 9" in text


def test_the_contract_not_installed_is_its_own_state(production, monkeypatch):
    real = importlib.import_module

    def missing(name, *a, **k):
        if name == d.ODDS_CONSENSUS_MODULE:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real(name, *a, **k)
    monkeypatch.setattr(importlib, "import_module", missing)
    (cap,) = [t for t in d.Context(production).odds_targets.value.rows if t.state == "CAPTURED"]
    assert cap.consensus.status == d.NO_DATA and "not installed" in cap.consensus.message


def test_source_unavailable_and_unknown_receipt_time(tmp_path):
    none = d.odds_consensus_at_capture(d.Context(Config(clock=lambda: datetime.now(timezone.utc))), "e", "x")
    assert none.status == d.NO_DATA
    cfg, root = fixture_states.odds_pilot(tmp_path / "y")
    try:
        unknown = d.odds_consensus_at_capture(d.Context(cfg), "fx000evt", None)
        assert unknown.status == d.NO_DATA and "receipt time is not recorded" in unknown.message
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_untrusted_text_is_escaped():
    loaded, sid = fixtures.synthetic_consensus()["populated"]
    r = loaded.value
    event = r.events[0]
    evil = "<script>alert(1)</script>"
    prop = replace(event.propositions[0], offered=tuple(replace(o, bookmaker=evil) for o in event.propositions[0].offered))
    shown = replace(r, events=(replace(event, propositions=(prop,) + event.propositions[1:]),), problems=(evil,))
    html = research.consensus_body(d.Loaded(d.OK, shown), sid)
    assert evil not in html and "&lt;script&gt;" in html


def test_gallery_shows_the_consensus_states():
    from edge_lab.dashboard.demo import build_demo
    cfg, root = build_demo(experiments_root=Path(__file__).resolve().parents[1] / "experiments")
    try:
        out = {}
        body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/gallery", "QUERY_STRING": "",
                                       "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("s", s))).decode()
        assert out["s"] == "200 OK"
        text = plain(body)
        for needle in ("Consensus at a capture (populated", "every book fresh at receipt", "this capture unusable",
                       "No usable consensus at this capture", "No consensus for this capture",
                       "Consensus unavailable (read error)"):
            assert needle in text, needle
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_memo_key_is_the_newest_odds_snapshot_known_by_the_capture(production, monkeypatch):
    """Review SF-1: other sources' writes never invalidate; an odds snapshot received by as_of does."""
    from edge_lab.storage import SnapshotStore

    calls = []
    real = odds_consensus.consensus_for_event
    monkeypatch.setattr(odds_consensus, "consensus_for_event",
                        lambda store, event_id, as_of: calls.append(as_of) or real(store, event_id, as_of))
    d.Context(production).odds_targets
    assert len(calls) == 1
    store = SnapshotStore(production.db)
    store.start_run("other-sources")
    store.save_snapshot(run_id="other-sources", source="kalshi", kind="orderbook", entity_id="X", url="u", payload={})
    store.save_snapshot(run_id="other-sources", source="the_odds_api", kind="odds", entity_id="americanfootball_nfl",
                        url="u", payload={"events": []}, fetched_at_utc="2026-09-24T20:00:00Z")  # after the capture
    d.Context(production).odds_targets
    assert len(calls) == 1  # neither a Kalshi write nor a later odds receipt can change this capture's result
    store.save_snapshot(run_id="other-sources", source="the_odds_api", kind="odds", entity_id="americanfootball_nfl",
                        url="u", payload={"events": []}, fetched_at_utc="2026-09-24T18:00:00Z")  # known by then
    d.Context(production).odds_targets
    assert len(calls) == 2

