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
                   "Fresh at capture within its target window", "RESEARCH BOOK CAPTURE — NOT AN EXECUTABLE PRICE CLAIM",
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
                   "Partial listing · absence is not evidence", "T-6h Overdue · not captured", "Failed",
                   "BOOK_FAILED"):
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
                       "Polymarket US related markets unavailable (read error)",
                       "EXP-002 label proxy: T-60m capture hidden", "Hidden · EXP-002 label proxy"):
            assert needle in text, needle
        assert "41.25" not in body and "41.75" not in body  # the synthetic T-60m figures never render
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _body(view_key: str, histories=None, ids=("DEMO-NFL-1", "DEMO-NFL-2", "DEMO-NFL-3"), edit=None) -> str:
    loaded, _ = fixtures.synthetic_pm_views()[view_key]
    view = loaded.value
    if edit is not None:
        view = edit(view)
    return research.pm_related_body(d.Loaded(d.OK, view), NOW, ids, histories)


def test_history_not_loaded_is_its_own_state_never_none_planned():
    """Review BLOCKER 2: an unread history never reads "no capture target planned"."""
    html = _body("populated", histories=None)
    assert "Not loaded on this page" in plain(html)
    assert 'aria-label="no capture target planned for this market"' not in html
    assert "Capture attempts are not loaded on this page" in plain(html)


def test_history_is_loaded_for_the_events_actually_rendered(pm, monkeypatch):
    """With the Odds targets unreadable the section falls back to the soonest events and still reads
    their history (bounded), so ATL@GB shows its T-6h capture."""
    monkeypatch.setattr(d, "odds_capture_targets", lambda ctx: d.Loaded(d.ERROR, message="boom"))
    seen = []
    real = ps.market_history
    monkeypatch.setattr(ps, "market_history", lambda store, slug: seen.append(slug) or real(store, slug))
    text = plain(section(page(pm)))
    assert "T-6h Captured" in text and "Not loaded on this page" not in text
    assert 0 < len(seen) <= 2 * d.PM_EVENTS_SHOWN
    monkeypatch.setattr(d, "pm_market_history", lambda ctx, slugs: d.Loaded(d.ERROR, message="store gone"))
    html = section(page(pm))
    assert "Not loaded on this page" in plain(html)
    assert 'aria-label="no capture target planned for this market"' not in html


def test_an_open_target_past_its_deadline_is_overdue(pm):
    """Review SF-1: the pilot's own rule; a planned target after kickoff never still reads "Planned"."""
    text = plain(section(page(replace(pm, clock=lambda: datetime(2026, 9, 25, 1, 0, tzinfo=timezone.utc)))))
    assert "T-60m Overdue · not captured" in text and "T-60m Planned" not in text
    assert "T-6h Captured" in text


@pytest.mark.parametrize("catalog,expected", [
    ("FILTER_COMPLETE", "NO_RELATED_MARKET"), ("PARTIAL_CATALOG", "PM_EVENT_NONE_IN_PARTIAL"),
    ("STALE", "PM_EVENT_NONE_IN_PARTIAL"), ("NO_SCAN", "PM_EVENT_NOT_CHECKED"), ("FAILED", "PM_EVENT_NOT_CHECKED"),
    (None, "PM_EVENT_NOT_CHECKED"), ("SOMETHING_NEW", "PM_EVENT_NOT_CHECKED"),
])
def test_only_a_complete_listing_can_say_no_related_market(catalog, expected):
    """Review SF-2."""
    code, word = research.pm_event_state({"state": "NO_RELATED_MARKET"}, catalog)
    assert code == expected
    if expected != "NO_RELATED_MARKET":
        assert "No related market in the listing read" not in word.label


def test_an_unrecognised_catalog_state_is_said():
    html = _body("populated", edit=lambda v: {**v, "status": {**v["status"], "catalog": {
        **v["status"]["catalog"], "state": "SOMETHING_NEW"}}})
    text = plain(html)
    assert "Polymarket US listing state not recognised" in text and "No related market in the listing read" not in text


def test_every_polymarket_table_carries_attribution_label_and_freshness(pm):
    """Review SF-3: the owner-attested attribution on all Polymarket data, tables included."""
    html = section(page(pm))
    for table in re.findall(r"<table.*?</table>", html, re.S):
        if "YES bid" in table or "YES ask" in table:
            assert ps.ATTRIBUTION in table and "not an executable price claim" in table
            assert "freshness at capture" in table
    everything = html[html.index("All Odds API events"):]
    assert ps.ATTRIBUTION in plain(everything[:everything.index("<table")])
    assert "Fresh at capture" in plain(everything)


def test_a_malformed_view_is_an_error_state_not_a_failed_page(pm, monkeypatch):
    monkeypatch.setattr(ps, "terminal_view", lambda db, now: {"state": "FILTER_COMPLETE", "related": {"events": ["x"]}})
    body = page(pm)  # 200: the rest of the tab renders
    assert 'aria-labelledby="src-h"' in body
    html = section(body)
    assert "Polymarket US related markets unavailable (malformed view)" in plain(html) and 'role="alert"' in html
    odd = {"state": "FILTER_COMPLETE", "status": {"catalog": "x"},
           "related": {"events": {"e": {"markets": "x", "state": 3, "odds_event_id": "e"}}}}
    monkeypatch.setattr(ps, "terminal_view", lambda db, now: odd)
    text = plain(section(page(pm)))  # odd types inside are shown as unknown, never a failed page
    assert "Polymarket US listing state not recognised" in text


def test_a_failed_latest_attempt_with_an_older_usable_listing_is_said():
    html = _body("populated", edit=lambda v: {**v, "status": {**v["status"], "catalog": {
        **v["status"]["catalog"], "last_attempt_utc": "2026-09-24T20:00:00Z"}}})
    assert "The latest scan attempt was not usable" in plain(html)


def test_the_coverage_code_is_translated(pm):
    text = plain(section(page(pm)))
    assert "coverage: a filtered listing (never the full catalog)" in text



# --------------------------------------------------------------------------- EXP-002 label proxy
#
# A related market's capture at T-60m (or after the T-6h decision cutoff) is a proxy for EXP-002's Kalshi T-60m
# label books (docs/research/EXP002_FREEZE_PROPOSAL.md §4): the Terminal shows that it was read, never its figures.

ATL_GB = "aec-nfl-atl-gb-2026-09-24"
PROXY_BID, PROXY_ASK, PROXY_QTY = "0.4125", "0.4175", "777.0000"  # SYNTHETIC: absent from every recorded body
PROXY_SHOWN = ("41.25", "41.75", "0.4125", "0.4175", "777")  # how those figures would render, raw or formatted
AFTER_T60M = datetime(2026, 9, 24, 23, 30, tzinfo=timezone.utc)  # ATL@GB kicks off at 00:15Z on Sep 25


def _t60m_capture(cfg) -> None:
    """The fixture's ATL@GB T-6h capture (real bytes) plus its T-60m capture at 23:15Z (19:15 ET): the
    recorded book with SYNTHETIC top levels, through the pilot's own capture entry point."""
    import json

    from edge_lab import http as pm_http

    raw = json.loads((fixture_states.PM_FIX / f"book_{ATL_GB}_2026-09-24T205959Z.json").read_bytes())
    data = {k: v for k, v in raw["marketData"].items() if k != "stats"}
    data["bids"] = [{"px": {"value": PROXY_BID, "currency": "USD"}, "qty": PROXY_QTY}]
    data["offers"] = [{"px": {"value": PROXY_ASK, "currency": "USD"}, "qty": PROXY_QTY}]
    at = datetime(2026, 9, 24, 23, 15, tzinfo=timezone.utc)

    class _At(datetime):
        @classmethod
        def now(cls, tz=None):
            return at + timedelta(seconds=20)
    wall, pm_http.datetime = pm_http.datetime, _At
    try:
        code, report = ps.run_capture(cfg.db, clock=lambda: at, sleep=lambda s: None,
                                      opener=fixture_states._Recorded(json.dumps({"marketData": data}).encode()),
                                      access_decision=fixture_states.PM_ACCESS)
    finally:
        pm_http.datetime = wall
    assert code == 0 and report["by_status"] == {"CAPTURED": 1}, report


@pytest.fixture
def pm_t60m(pm):
    _t60m_capture(pm)
    return replace(pm, clock=lambda: AFTER_T60M)


def _atl_gb(view: dict) -> dict:
    return next(m for e in view["related"]["events"].values() for m in e["markets"] if m["market_slug"] == ATL_GB)


def test_the_view_model_withholds_the_t60m_capture(pm_t60m):
    ctx = d.Context(pm_t60m)
    latest = _atl_gb(ctx.pm_sports.value)["latest_capture"]
    assert latest["offset"] == "T-60m" and latest["label_proxy"] == ps.LABEL_PROXY_HIDDEN
    assert not set(ps.LABEL_PROXY_FIELDS) & set(latest) and latest["received_at_utc"].startswith("2026-09-24T23:15")
    history = {t["offset"]: t for t in d.pm_market_history(ctx, [ATL_GB]).value[ATL_GB]}
    shown = history["T-6h"]["attempts"][-1]
    assert shown["yes_bid"] == "0.3050" and shown["yes_ask"] == "0.3100" and "label_proxy" not in shown
    hidden = history["T-60m"]["attempts"][-1]
    assert hidden["status"] == "CAPTURED" and hidden["label_proxy"] == ps.LABEL_PROXY_HIDDEN
    assert not set(ps.LABEL_PROXY_FIELDS) & set(hidden)


def test_the_data_sources_page_never_shows_t60m_figures(pm_t60m):
    body = page(pm_t60m)
    for figure in PROXY_SHOWN:
        assert figure not in body, figure  # anywhere on the tab: section, tables, disclosures
    html = section(body)
    text = plain(html)
    latest = html[html.index("Latest research book"):html.index("Capture targets")]
    assert "Hidden · EXP-002 label proxy" in plain(latest) and "T-60m capture" in plain(latest)
    assert "¢" not in latest and "contracts" not in plain(latest)  # no price and no size line
    assert "received Sep 24, 7:15 PM EDT" in plain(latest) and "Fresh at capture" in plain(latest)
    assert ps.ATTRIBUTION in plain(latest)
    rows = {r: plain(r) for r in re.findall(r"<tr>.*?</tr>", html, re.S)}
    t6h = [p for p in rows.values() if f"nfl:{ATL_GB}:T-6h" in p]
    t60 = [(h, p) for h, p in rows.items() if f"nfl:{ATL_GB}:T-60m" in p]
    assert t6h and "30.5¢" in t6h[0] and "31¢" in t6h[0]  # the pre-decision capture stays visible
    assert t60 and all("¢" not in p and p.count("Hidden") == 2 for _, p in t60)
    assert all('title="code: PM_CAPTURE_LABEL_PROXY"' in h for h, _ in t60)
    everything = html[html.index("All Odds API events"):]
    assert "Hidden · EXP-002 label proxy" in plain(everything)
    assert "T-6h Captured" in text and "T-60m Captured" in text
    assert "k-ok" not in html


def test_hiding_changes_figures_only_never_counts_or_states(pm_t60m, monkeypatch):
    """The same page with the rule switched off shows the T-60m figures (so the fixture would leak) and
    otherwise the same targets, attempts, states and receipts."""
    hidden = section(page(pm_t60m))
    monkeypatch.setattr(ps, "is_label_proxy", lambda *a: False)
    shown = section(page(pm_t60m))
    assert "41.25¢" in shown and "41.75¢" in shown
    assert len(re.findall(r"<tr>", hidden)) == len(re.findall(r"<tr>", shown))
    for pattern in (r"T-\d+[hm] [A-Z][a-z]+(?: · [a-z ]+)?", r"Sep \d+, \d+:\d+ [AP]M EDT", r"Fresh at capture"):
        found = re.findall(pattern, plain(hidden))
        assert found and found == re.findall(pattern, plain(shown)), pattern


@pytest.mark.parametrize("key", ["populated", "partial", "no_scan", "stale", "blocked", "error", "unavailable"])
def test_the_other_states_are_unchanged(key):
    """Pre-decision captures (the synthetic T-6h one) and the empty, stale, blocked and error states carry no
    hidden marker; the stale capture still shows its figures."""
    loaded, history = fixtures.synthetic_pm_views()[key]
    text = plain(research.pm_related_body(loaded, NOW, ("DEMO-NFL-1", "DEMO-NFL-2", "DEMO-NFL-3"), history))
    assert "EXP-002 label proxy" not in text
    if key in ("populated", "partial", "stale", "blocked"):
        assert "YES bid 30.5¢ · YES ask 31¢" in text


def test_the_label_proxy_fixture_state():
    loaded, history = fixtures.synthetic_pm_views()["label_proxy"]
    now = datetime.fromisoformat(fixtures.PM_PROXY_NOW)
    html = research.pm_related_body(loaded, now, ("DEMO-NFL-1",), history)
    text = plain(html)
    for needle in ("Hidden · EXP-002 label proxy", "T-60m capture", "30.5¢", "32.5¢",
                   "BOOK_ANOMALY: withheld (EXP-002 label proxy)", "T-24h Captured", "T-6h Captured", "T-60m Captured"):
        assert needle in text, needle
    for figure in ("41.25", "41.75", "42.25", "0.42", "0.41"):
        assert figure not in html, figure
