"""Current blockers on Data sources and the Terminal; contract exceptions on market detail (PR C, UI_CONTRACT §14)."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from edge_lab import current_blockers as cb
from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard.views import markets

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def get(app, path, query=""):
    out = {}

    def start(status, headers):
        out["status"] = status
    body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query,
                         "HTTP_HOST": "localhost"}, start))
    return out["status"], body.decode("utf-8")


def _section(body: str) -> str:
    m = re.search(r'aria-labelledby="blk-h".*?</section>', body, re.S)
    assert m, "Current blockers section missing"
    return m.group(0)


def _clean(html: str) -> None:
    assert "<form" not in html and "<button" not in html and ' style="' not in html
    for word in ("Buy", "Place order", "Submit", "Edge score", "LIVE"):
        assert word not in html


@pytest.fixture()
def app():
    return make_app(Config(clock=lambda: NOW))


def test_populated_register_on_data_sources(app):
    status, body = get(app, "/experiments", "tab=sources")
    assert status.startswith("200")
    sec = _section(body)
    for text in ("Current blockers", "KXNHLGAME fees", "Fee unsupported", "owner approval needed",
                 "Not sent · owner", "Rules unresolved", "Next: Weekly off-host pull", "current-blockers-v2",
                 "last reconciled 2026-09-30", "owner action needed"):
        assert text in sec, text
    assert "Odds API NHL commence times" not in sec.split("Verified, unknown and sources")[0]  # RECORDED: not open
    _clean(sec)


def test_terminal_names_the_next_blocker_in_system_and_evidence(app):
    status, body = get(app, "/")
    assert status.startswith("200") and "Next research blocker or approval" in body
    assert "Weekly off-host pull (O1) and F09" in body and 'href="/experiments?tab=sources#blk-h"' in body


def test_overdue_items_say_overdue_since_and_are_stale():
    app = make_app(Config(clock=lambda: datetime(2026, 10, 10, tzinfo=timezone.utc)))
    sec = _section(get(app, "/experiments", "tab=sources")[1])
    assert "overdue since Oct 3" in sec and "1 overdue" in sec and "Register needs re-checking" in sec
    terminal = get(app, "/")[1]
    assert "Weekly off-host pull (O1) and F09 — overdue since Oct 3" in terminal and "stale: re-check" in terminal
    assert "owner action needed" in terminal  # a routine is an action, not an approval


def test_a_missing_register_module_is_unavailable_not_empty(app, monkeypatch):
    monkeypatch.setattr(d, "current_blockers", lambda ctx: d.Loaded(d.NO_DATA, message="not installed in this build"))
    sec = _section(get(app, "/experiments", "tab=sources")[1])
    assert "Blocker register unavailable" in sec and "No research blocker recorded" not in sec
    terminal = get(app, "/")[1]
    assert "Blocker register unavailable" in terminal and "No open research blocker" not in terminal


def test_stale_register_says_so():
    app = make_app(Config(clock=lambda: datetime(2026, 10, 20, tzinfo=timezone.utc)))
    sec = _section(get(app, "/experiments", "tab=sources")[1])
    assert "Register needs re-checking" in sec and "stale is not current" in sec
    assert "stale: re-check" in get(app, "/")[1]


def test_error_state_when_the_register_is_inconsistent(app, monkeypatch):
    monkeypatch.setattr(cb, "validate", lambda *a: ["duplicate blocker ids"])
    sec = _section(get(app, "/experiments", "tab=sources")[1])
    assert "Blocker register unavailable" in sec and "duplicate blocker ids" in sec
    assert "Blocker register unavailable" in get(app, "/")[1]


def test_empty_and_all_closed_states(app, monkeypatch):
    first = cb.BLOCKERS[0]
    monkeypatch.setattr(cb, "BLOCKERS", ())  # loads fine and holds nothing
    assert "No research blocker recorded" in _section(get(app, "/experiments", "tab=sources")[1])
    assert "No open research blocker is recorded" in get(app, "/")[1]
    monkeypatch.setattr(cb, "BLOCKERS", (replace(first, status=cb.Status.RECORDED),))
    assert "No open blocker" in _section(get(app, "/experiments", "tab=sources")[1])
    assert "No open research blocker is recorded" in get(app, "/")[1]


def test_an_unrecognized_status_renders_neutral_with_its_code():
    from edge_lab.dashboard.views import research

    html = research.blocker_word("SOMETHING_NEW")
    assert "Unrecognized status (SOMETHING_NEW)" in html and "BLOCKER_SOMETHING_NEW" in html


def test_market_detail_rules_show_contract_exceptions_for_sports_series_only():
    def row(native):
        return SimpleNamespace(title="t", outcome="o", rules_primary="r", venue="kalshi", market_id=f"kalshi:{native}",
                               native_id=native, event_id="e", payoff_kind="BINARY", status="active",
                               close_time_utc=None, target_date=None, quotes={})
    nhl = markets.rules_section(row("KXNHLGAME-26OCT04BOSTOR-BOS"))
    assert "contract exceptions (recorded summary, not the rules)" in nhl
    assert "Shootout — rules unresolved" in nhl and "Tie — rules unresolved" in nhl
    nfl = markets.rules_section(row("KXNFLGAME-26OCT04BUFNE-BUF"))
    assert "Tie after overtime — verified" in nfl and "no fallback-F settlement has been observed" in nfl
    assert "contract exceptions" not in markets.rules_section(row("KXHIGHNY-26SEP30-T70"))
    assert d.contract_exceptions("KXHIGHNY-26SEP30-T70") is None


# ------------------------------------------------------------------ RFQ feasibility (R4 display)


def _rfq(body: str) -> str:
    m = re.search(r'aria-labelledby="rfq-h".*?</section>', body, re.S)
    assert m, "RFQ feasibility section missing"
    return m.group(0)


def test_rfq_feasibility_is_populated_blocked_and_private(app):
    sec = _rfq(get(app, "/experiments", "tab=sources")[1])
    for text in ("RFQ feasibility", "Decision: Narrow · no RFQ participation", "Documented", "Private to the parties",
                 "Unavailable to us", "Unknown", "Owner decisions open", "D1: Data rights", "D6: Budget",
                 "Our quotes vs other makers&#x27;", "never shown", "RFQ_FEASIBILITY_2026-09.md"):
        assert text in sec, text
    _clean(sec)
    assert "$" not in sec.split("Owner decisions")[0]  # no price, profit or competitor figure anywhere above


def test_rfq_feasibility_stale_error_unavailable_and_unrecognized_states(monkeypatch):
    late = make_app(Config(clock=lambda: datetime(2026, 11, 15, tzinfo=timezone.utc)))
    assert "Documentation needs re-reading" in _rfq(get(late, "/experiments", "tab=sources")[1])
    app = make_app(Config(clock=lambda: NOW))
    monkeypatch.setattr(d, "rfq_feasibility", lambda ctx: d.Loaded(d.ERROR, message="summary incomplete"))
    assert "RFQ feasibility unavailable" in _rfq(get(app, "/experiments", "tab=sources")[1])
    monkeypatch.setattr(d, "rfq_feasibility", lambda ctx: d.Loaded(d.NO_DATA, message="not installed"))
    sec = _rfq(get(app, "/experiments", "tab=sources")[1])
    assert "RFQ feasibility unavailable" in sec and "not installed" in sec
    from edge_lab.dashboard.views import research
    assert "Unrecognized state (SOMETHING)" in research.rfq_word("SOMETHING")


def test_rfq_section_refuses_to_render_the_decision_if_execution_is_ever_authorized(monkeypatch):
    from edge_lab import rfq_research

    app = make_app(Config(clock=lambda: NOW))
    # venues.VenueSpec itself refuses execution_authorized=True; a stand-in simulates a broken record
    monkeypatch.setattr(rfq_research, "KALSHI", SimpleNamespace(execution_authorized=True))
    sec = _rfq(get(app, "/experiments", "tab=sources")[1])
    assert "Unexpected: execution authorized, review" in sec
    assert "Decision: Narrow" not in sec and "no RFQ participation" not in sec
    assert d.rfq_feasibility(d.Context(Config(clock=lambda: NOW))).value["participation_authorized"] is True


def test_owner_decisions_carry_no_markdown():
    from edge_lab import rfq_research

    assert not any("`" in text for _, text in rfq_research.OWNER_DECISIONS)
