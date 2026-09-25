"""Related Polymarket US markets per Odds API event (Research & Data -> Data sources).

Owner directive 2026-09-24 (evening), Terminal v1 and contract C4; Lane B's pilot (#84, ADR 0032):
`polymarket_sports.terminal_view` (schema pm-sports-status/1). Shown as "RELATED MARKET — NOT
ECONOMICALLY EQUIVALENT", never ranked or "cheaper"; a partial, stale or missing scan never reads as
"no market exists"; the access gate is an owner risk decision, not a grant; every Polymarket figure
carries the source attribution.
"""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import polymarket_sports as ps
from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard import fixtures
from edge_lab.dashboard.views import research

sys.path.insert(0, str(Path(__file__).resolve().parent / "browser"))
import fixture_states  # noqa: E402

NOW = datetime(2026, 9, 24, 21, 0, tzinfo=timezone.utc)


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def page(cfg: Config) -> str:
    out = {}
    body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/experiments", "QUERY_STRING": "tab=sources",
                                   "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s)))
    assert out["status"] == "200 OK"
    return body.decode("utf-8")


def section(body: str, sid: str = "pm-h") -> str:
    part = body[body.index(f'aria-labelledby="{sid}"'):]
    return part[:part.index("</section>")]


@pytest.fixture
def pm():
    cfg, root = fixture_states.polymarket()
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def pm_issues():
    cfg, root = fixture_states.polymarket_issues()
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


def test_labels_are_the_contracts():
    assert research.PM_LABEL == ps.LABEL == "RELATED MARKET — NOT ECONOMICALLY EQUIVALENT"
    assert ps.ATTRIBUTION == "Polymarket US (gateway.polymarket.us public API)"


def test_the_related_market_its_capture_and_attribution(pm):
    body = page(pm)
    assert body.index('aria-labelledby="odds-t-h"') < body.index('aria-labelledby="pm-h"') \
        < body.index('aria-labelledby="src-h"')
    html = section(body)
    text = plain(html)
    for needle in ("RELATED MARKET — NOT ECONOMICALLY EQUIVALENT", "Atlanta Falcons @ Green Bay Packers",
                   "same league, both teams and kickoff; contract terms not proven equal",
                   "YES bid 30.5¢ · YES ask 31¢", "received Sep 24, 2:15 PM EDT", "research capture, not current",
                   "Fresh at capture (its target window)", "RESEARCH BOOK CAPTURE — NOT AN EXECUTABLE PRICE CLAIM",
                   "T-6h Captured", "T-60m Planned", "Allowed by an owner risk decision · not a terms clearance",
                   "Filtered listing read in full · not a full catalog", "payout structure Differs",
                   "equivalent never (by construction)", "absence is not evidence"):
        assert needle in text, needle
    capture = html[html.index("Latest research book"):html.index("Capture targets")]
    assert ps.ATTRIBUTION in plain(capture)  # attribution on the Polymarket figures themselves
    assert "k-ok" not in html  # nothing about a related market is green
    shown = plain(html[:html.rindex('<p class="note">')]).lower()  # everything but the caveat note itself
    for word in ("cheaper", "best price", "rank", "equivalent market", "executable price"):
        assert word not in shown.replace("not an executable price claim", "").replace("never ranked", ""), word


def test_the_odds_target_rows_name_the_relationship(pm):
    targets = plain(section(page(pm), "odds-t-h"))
    assert "Polymarket US RELATED MARKET — NOT ECONOMICALLY EQUIVALENT" in targets
    assert "Polymarket US Ambiguous match · not resolved" in targets


def test_ambiguous_matches_list_their_reasons(pm):
    text = plain(section(page(pm)))
    assert "Ambiguous match · not resolved" in text and "share exactly one team" in text


def test_a_partial_listing_and_a_failed_capture(pm_issues):
    html = section(page(pm_issues))
    text = plain(html)
    for needle in ("Partial Polymarket US listing", "A market missing below may exist",
                   "Partial listing · absence is not evidence", "T-6h Failed", "BOOK_FAILED"):
        assert needle in text, needle
    assert 'aria-label="no research book captured yet"' in html  # unknown, never a price of 0


def test_no_scan_never_reads_as_no_market(tmp_path):
    cfg, root = fixture_states.odds_pilot(tmp_path / "x")
    try:
        text = plain(section(page(cfg)))
        assert "No Polymarket US scan yet" in text and "Not checked · no usable scan" in text
        assert "No related market in the listing read" not in text
        assert "This says nothing about whether a market exists" in text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_stale_listing(pm):
    text = plain(section(page(replace(pm, clock=lambda: NOW + timedelta(days=2)))))
    assert "Polymarket US listing is stale" in text and "Listing stale" in text


def test_the_terms_gate_blocked(pm, monkeypatch):
    monkeypatch.setattr(ps, "OWNER_ACCESS_DECISION", None)
    text = plain(section(page(pm)))
    assert "Polymarket US pilot blocked: terms review" in text and "Blocked · terms review" in text
    assert "Allowed by" not in text


def test_error_unavailable_and_not_installed(tmp_path, pm, monkeypatch):
    assert d.Context(Config(clock=lambda: NOW)).pm_sports.status == d.NO_DATA
    text = plain(section(page(Config(clock=lambda: NOW))))
    assert "Polymarket US related markets unavailable" in text and "read error" not in text
    missing = d.Context(Config(db=tmp_path / "none.sqlite3", clock=lambda: NOW)).pm_sports
    assert missing.status == d.NO_DATA and str(tmp_path) not in missing.message
    monkeypatch.setattr(ps, "terminal_view", lambda db, now: {"state": "ERROR", "detail": f"broken at {tmp_path}/x"})
    result = d.Context(pm).pm_sports
    assert result.status == d.ERROR and str(tmp_path) not in result.message
    html = section(page(pm))
    assert "Polymarket US related markets unavailable (read error)" in plain(html) and 'role="alert"' in html
    assert "not an empty listing" in plain(html)
    monkeypatch.setattr(ps, "terminal_view", lambda db, now: 1 / 0)
    assert d.Context(pm).pm_sports.status == d.ERROR


def test_history_is_read_only_for_the_markets_shown(pm, monkeypatch):
    seen = []
    real = ps.market_history
    monkeypatch.setattr(ps, "market_history", lambda store, slug: seen.append(slug) or real(store, slug))
    page(pm)
    view = d.Context(pm).pm_sports.value
    total = sum(len(e["markets"]) for e in view["related"]["events"].values())
    assert 0 < len(seen) <= 2 * d.PM_EVENTS_SHOWN < total and len(seen) == len(set(seen))


def test_untrusted_text_is_escaped():
    loaded, history = fixtures.synthetic_pm_views()["populated"]
    evil = "<script>alert(1)</script>"
    view = loaded.value
    ev = view["related"]["events"]["DEMO-NFL-1"]
    bad = {**view, "related": {**view["related"], "events": {"DEMO-NFL-1": {
        **ev, "home_team": evil, "markets": [{**ev["markets"][0], "title": evil, "reasons": [evil]}]}}}}
    html = research.pm_related_body(d.Loaded(d.OK, bad), NOW, ("DEMO-NFL-1",), history)
    assert evil not in html and "&lt;script&gt;" in html


@pytest.mark.parametrize("key,needles", [
    ("populated", ("RELATED MARKET — NOT ECONOMICALLY EQUIVALENT", "Ambiguous match", "No related market in the listing read",
                   "T-24h Missed", "BOOK_FAILED", "absence is not evidence")),
    ("partial", ("Partial Polymarket US listing", "None seen · listing partial or stale")),
    ("no_scan", ("No Polymarket US scan yet", "Not checked · no usable scan")),
    ("stale", ("Polymarket US listing is stale", "Stale at capture")),
    ("blocked", ("Polymarket US pilot blocked: terms review",)),
    ("error", ("(read error)",)),
    ("unavailable", ("Polymarket US related markets unavailable",)),
])
def test_every_state_renders(key, needles):
    loaded, history = fixtures.synthetic_pm_views()[key]
    text = plain(research.pm_related_body(loaded, NOW, ("DEMO-NFL-1", "DEMO-NFL-2", "DEMO-NFL-3"), history))
    for needle in needles:
        assert needle in text, (key, needle)


def test_gallery_shows_the_polymarket_states():
    from edge_lab.dashboard.demo import build_demo
    cfg, root = build_demo(experiments_root=Path(__file__).resolve().parents[1] / "experiments")
    try:
        out = {}
        body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/gallery", "QUERY_STRING": "",
                                       "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("s", s))).decode()
        text = plain(body)
        for needle in ("Polymarket US related markets (related with a capture", "Partial listing · absence is not evidence",
                       "No Polymarket US scan yet", "Polymarket US listing is stale",
                       "Polymarket US pilot blocked: terms review",
                       "Polymarket US related markets unavailable (read error)"):
            assert needle in text, needle
    finally:
        shutil.rmtree(root, ignore_errors=True)
