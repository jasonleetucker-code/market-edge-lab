"""Economic evidence on Research & Data -> Research (Economic Evidence v1, PR C; UI_CONTRACT §8 and §14).

One compact section in the existing Terminal for the two research families: Family A from
`sports_evidence.terminal_view`, Family B "not yet available" until PR B's evaluator lands. No new
navigation, no edge score, no profit shown for missing outcomes, no "arbitrage captured", no funded state.
States: populated, partial, stale, empty, unsupported, unknown, error, malformed; Family B unavailable.
"""

from __future__ import annotations

import re
import shutil
import socket
import sys
import types
from datetime import timedelta
from pathlib import Path

import pytest

from edge_lab import sports_evidence as se
from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard import sports_fixtures as sf
from edge_lab.dashboard.html import NAV
from edge_lab.dashboard.views import research

sys.path.insert(0, str(Path(__file__).resolve().parent / "browser"))
import fixture_states  # noqa: E402

FORBIDDEN = ("arbitrage", "captured profit", "profit captured", "edge score", "daily profit", "funded", "ready to submit",
             "recommended bet", "place order", "$0.00 profit")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the dashboard attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).replace("&#x27;", "'").split())


def page(cfg: Config, query: str = "") -> str:
    out = {}
    body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/experiments", "QUERY_STRING": query,
                                   "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s)))
    assert out["status"] == "200 OK"
    return body.decode("utf-8")


def one_section(body: str, sid: str) -> str:
    part = body[body.index(f'aria-labelledby="{sid}"'):]
    return part[:part.index("</section>")]


def section(body: str, sid: str | None = None) -> str:
    """One gallery section by id, or (page) both family sections: Family A (ev-h) then Family B (ev-b-h)."""
    if sid is not None:
        return one_section(body, sid)
    assert body.index('aria-labelledby="ev-h"') < body.index('aria-labelledby="ev-b-h"')
    return one_section(body, "ev-h") + one_section(body, "ev-b-h")


@pytest.fixture
def state(request):
    cfg, root = fixture_states.BUILDERS[request.param]()
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


def test_the_label_is_the_contracts_and_no_new_navigation_exists():
    assert research.EV_LABEL == se.LABEL == "PAIRED RESEARCH EVIDENCE — NOT AN EDGE CLAIM"
    assert [n.label for n in NAV] == ["Terminal", "Markets", "Portfolio", "Outcomes", "Risk", "Research & Data",
                                      "Alerts"]


@pytest.mark.parametrize("state", ["economics"], indirect=True)
def test_populated_section_sits_in_the_research_tab_after_the_experiments(state):
    body = page(state)
    assert body.index('aria-labelledby="ex-EXP-001-h"') < body.index('aria-labelledby="ev-h"')
    text = plain(section(body))
    for needle in ("Economic evidence", "PAIRED RESEARCH EVIDENCE — NOT AN EDGE CLAIM", "Paired evidence",
                   "3 games · 1 NFL weeks · 3 not yet due · 0 superseded", "9 of 9",
                   "Hidden · holdout protection", "episodes not evaluable", "Conditional mapping · not equivalent",
                   "YES pays $0.50 on a tie", "Not defensible", "FEE_UNSUPPORTED", "signals and fills not evaluated",
                   "Settle and freeze EXP-002", "Draft",
                   "Economic evidence · B", "Same-venue payoff consistency", "Not yet available",
                   "No payoff proof, conditional surplus or captured result is shown",
                   "Size ladder over the latest paired book", "Fee unsupported", "Insufficient evidence", "Protocol-eligible", "Protocol attrition (EXP-002)",
                   "Visible depth is an instantaneous ceiling, not capacity"):
        assert needle in text, needle
    lower = text.replace(plain(research.EV_NOTE), "").lower()  # the note negates these words on purpose
    for word in FORBIDDEN:
        assert word not in lower, word
    assert "k-ok" not in section(body)  # nothing green in this section
    # EXP-002 outcome labels never reach the Terminal: no state, count or result (holdout protection)
    for label in ("final 3", "pending 6", "Outcome final", "OUTCOME_FINAL", "OUTCOME_PENDING", "final-evaluable 3"):
        assert label not in text, label
    assert "0 episodes" not in text


@pytest.mark.parametrize("state", ["economics_issues"], indirect=True)
def test_partial_section_names_what_is_missing(state):
    text = plain(section(page(state)))
    for needle in ("Partial evidence", "Evidence incomplete", "5 of 9", "Odds not captured",
                   "Kalshi book missing", "Pair skew exceeded", "Kalshi book unusable", "Missing evidence (6)",
                   "Kalshi KXNFLGAME order books at the Odds horizons", "Partial"):
        assert needle in text, needle


@pytest.mark.parametrize("state", ["odds"], indirect=True)
def test_production_like_state_shows_the_gap_and_the_owner_decision(state):
    text = plain(section(page(state)))
    for needle in ("No paired evidence", "No paired evidence yet", "0 of 1", "Kalshi not mapped", "Missing evidence (8)",
                   "Kalshi KXNFLGAME listings (tickers, rules, status, result)", "no new timer is authorized today",
                   "blocker: no Kalshi NFL books are stored", "Capacity not measured", "Not established"):
        assert needle in text, needle
    assert "$" not in text.split("Costs and inputs")[0].replace("$0.50", "")  # no money figure before the costs


@pytest.mark.parametrize("state", ["early"], indirect=True)
def test_empty_state(state):
    text = plain(section(page(state)))
    assert "No targets yet" in text and "No NFL capture targets yet" in text


def test_stale_unsupported_unknown_error_and_malformed(tmp_path):
    path, now = sf.fixture_store(tmp_path / "p")
    stale = research.economics_body(d.Loaded(d.OK, se.terminal_view(path, now=now + timedelta(days=12))["family_a"]),
                                    d.Loaded(d.NO_DATA, message="not in this build"), now)
    assert "Stale · not current" in plain(stale) and "Nothing here is current" in plain(stale)
    path2, _ = sf.fixture_store(tmp_path / "u", market_type="scalar")
    unsupported = research.economics_body(d.Loaded(d.OK, se.terminal_view(path2, now=now)["family_a"]),
                                          d.Loaded(d.NO_DATA, message="x"), now)
    assert "Unsupported payoff" in plain(unsupported) and "Kalshi payoff unsupported" in plain(unsupported)
    unknown = plain(research.economics_body(d.Loaded(d.NO_DATA, message="no evidence database configured (--db)"),
                                            d.Loaded(d.NO_DATA, message="x"), now))
    assert "Family A evidence unknown" in unknown and "not the same as nothing recorded" in unknown
    error = research.economics_body(d.Loaded(d.ERROR, message="OperationalError: disk image is malformed"),
                                    d.Loaded(d.ERROR, message="boom"), now)
    assert "Family A unavailable (read error)" in plain(error) and 'role="alert"' in error
    assert "Family B unavailable (read error)" in plain(error)
    malformed = research.economics_body(d.Loaded(d.OK, {"state": "PARTIAL", "denominators": "not a dict",
                                                        "waterfall": [None, 3], "gaps": "x"}),
                                        d.Loaded(d.NO_DATA, message="x"), now)
    assert "Partial evidence" in plain(malformed)  # tolerated, never a failed page
    broken = research.economics_body(d.Loaded(d.OK, {"state": "OK", "outcomes": {"a": object()}}),
                                     d.Loaded(d.NO_DATA, message="x"), now)
    assert "malformed view" in plain(broken) or "Family A" in plain(broken)


def test_family_b_view_is_rendered_when_the_evaluator_is_installed(tmp_path, monkeypatch):
    fake = types.ModuleType(d.PAYOFF_EVIDENCE_MODULE)
    fake.terminal_view = lambda db, now: {"state": "PARTIAL", "as_of_utc": "2026-09-27T21:00:00Z",
                                          "label": "SYNTHETIC evaluator view", "detail": "SYNTHETIC detail"}
    monkeypatch.setitem(sys.modules, d.PAYOFF_EVIDENCE_MODULE, fake)
    path, now = sf.fixture_store(tmp_path)
    cfg = Config(db=path, clock=lambda: now)
    ctx = d.Context(cfg)
    assert ctx.economic_b.status == d.OK
    text = plain(research.economics_body(ctx.economic_a, ctx.economic_b, now))
    assert "SYNTHETIC evaluator view" in text and "is not arbitrage captured" in text


def test_loaders_report_absence_honestly(tmp_path):
    ctx = d.Context(Config(db=None))
    assert ctx.economic_a.status == d.NO_DATA and "no evidence database configured" in ctx.economic_a.message
    assert ctx.economic_b.status == d.NO_DATA and "PR B" in ctx.economic_b.message
    missing = d.Context(Config(db=tmp_path / "missing.sqlite3"))
    assert missing.economic_a.status == d.NO_DATA and "not readable" in missing.economic_a.message
    assert str(tmp_path) not in missing.economic_a.message  # no path leaks


def test_gallery_renders_every_state():
    cfg, root = fixture_states.demo()
    out = {}
    body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/gallery", "QUERY_STRING": "",
                                   "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s))).decode()
    assert out["status"] == "200 OK"
    for sid in ("g-ev-populated", "g-ev-partial", "g-ev-gap", "g-ev-states"):
        assert f'aria-labelledby="{sid}"' in body
    text = plain(section(body, "g-ev-states"))
    for needle in ("Stale · not current", "Unsupported payoff", "No targets yet", "Family A evidence unknown",
                   "Family A unavailable (read error)"):
        assert needle in text, needle
