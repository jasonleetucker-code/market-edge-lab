"""Alerts by notification origin, the unit-failure / verification split, and the Odds API card.

Directive 2026-09-24, Deliverables 5 and 6 (UI parts). Origins never mix: only production can
need attention; a verification record is a check only when root confirmed it; The Odds API
never reads as active or connected before a stored live read that held offers.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import notifications as n
from edge_lab import verification
from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import components as c
from edge_lab.dashboard import data as d
from edge_lab.dashboard import presentation as pr
from edge_lab.dashboard.server import build_parser, config_from_args
from edge_lab.dashboard.views import common as cm
from edge_lab.dashboard.views import research

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
INVOCATION = "0123456789abcdef0123456789abcdef"


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def call(app, path):
    out = {}
    body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "",
                         "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s)))
    return out["status"], body.decode("utf-8")


def section(body: str, sid: str) -> str:
    if f'aria-labelledby="{sid}"' not in body:
        return ""
    part = body[body.index(f'aria-labelledby="{sid}"'):]
    return part[:part.index("</section>")]


def _event(summary: str, origin: n.Origin | None, severity=n.Severity.CRITICAL, minutes=10) -> dict:
    kw = {} if origin is None else {"origin": origin}
    event = n.make_event(n.EventType.SOURCE_FAILURE, severity, created_at=NOW - timedelta(minutes=minutes),
                         summary=summary, dedupe_key=summary, **kw)
    return event.to_dict()


def _status_dir(tmp_path: Path, *, failure: dict | None = None, verification: dict | None = None,
                events: list[dict] = ()) -> Config:
    status = tmp_path / "status"
    status.mkdir()
    if failure is not None:
        (status / d.FAILURE_FILE).write_text(json.dumps(failure), encoding="utf-8")
    if verification is not None:
        (status / d.VERIFICATION_FILE).write_text(json.dumps(verification), encoding="utf-8")
    if events:
        (status / d.NOTIFICATIONS_FILE).write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return Config(status_dir=status, clock=lambda: NOW)


def _record(unit="edgelab-decision.service", origin=None) -> dict:
    rec = {"unit": unit, "failed_at_utc": "2026-09-24T11:30:00Z", "invocation_id": INVOCATION}
    if origin is not None:
        rec["origin"] = origin
    return rec


# --------------------------------------------------------------------------- alerts by origin


@pytest.fixture
def mixed(tmp_path):
    events = [_event("PROD critical", n.Origin.PRODUCTION), _event("LEGACY line without origin", None),
              _event("TEST critical", n.Origin.TEST), _event("MANUAL check", n.Origin.MANUAL_DIAGNOSTIC),
              _event("REPLAY row", n.Origin.REPLAY), _event("DEMO row", n.Origin.DEMO)]
    bogus = _event("BOGUS origin", n.Origin.PRODUCTION)
    bogus["origin"] = "SOMETHING_NEW"
    events.append(bogus)
    return _status_dir(tmp_path, failure=_record(), verification=_record("edgelab-shadow.service",
                                                                         "DEPLOYMENT_VERIFICATION"), events=events)


def test_only_production_needs_attention_and_origins_never_mix(mixed):
    status, body = call(make_app(mixed), "/alerts")
    assert status == "200 OK"
    attention, checks = plain(section(body, "al-attention")), plain(section(body, "al-checks"))
    for needle in ("PROD critical", "LEGACY line without origin", "BOGUS origin",
                   "Production incident: unit failed: edgelab-decision.service"):
        assert needle in attention and needle not in checks, needle
    for needle in ("TEST critical", "MANUAL check", "REPLAY row", "DEMO row"):
        assert needle in checks and needle not in attention, needle
    assert "Origin unrecognised" in attention  # an unknown origin fails closed, labelled
    assert "never counted as attention" in plain(body)


def test_an_unconfirmed_verification_record_is_a_production_incident(mixed):
    _, body = call(make_app(mixed), "/alerts")
    attention = plain(section(body, "al-attention"))
    assert "Production incident: unit failed: edgelab-shadow.service" in attention
    assert "claims origin DEPLOYMENT_VERIFICATION, but no root confirmation" in attention
    assert "Verification check:" not in plain(body)


def test_a_root_confirmed_verification_is_a_check_not_an_incident(tmp_path, monkeypatch):
    monkeypatch.setattr(verification, "verification_confirmed", lambda record, **k: record.get("invocation_id") == INVOCATION)
    cfg = _status_dir(tmp_path, verification=_record("edgelab-shadow.service", "DEPLOYMENT_VERIFICATION"))
    app = make_app(cfg)
    _, body = call(app, "/alerts")
    checks = plain(section(body, "al-checks"))
    assert "Verification check: edgelab-shadow.service refused as expected" in checks
    assert "Production incident" not in plain(section(body, "al-attention"))
    assert not any("edgelab-shadow" in a.title for a in cm.alerts(d.Context(cfg)) if a.group == "attention")
    _, home = call(app, "/")
    assert "Verification check: edgelab-shadow.service" in home and "Production incident" not in home


def test_the_bell_counts_production_attention_only(mixed):
    ctx = d.Context(mixed)
    items = cm.alerts(ctx)
    attention = [a for a in items if a.group == "attention"]
    assert cm.attention_count(ctx) == len(attention)
    assert all(a.origin in ("PRODUCTION", None) for a in attention)
    assert {a.origin for a in items if a.group == "checks"} == {"TEST", "MANUAL_DIAGNOSTIC", "REPLAY", "DEMO"}


def test_delivery_wording_follows_the_origin_policy(mixed):
    by_title = {a.title: a for a in cm.alerts(d.Context(mixed))}
    assert "phone delivery not recorded" in by_title["PROD critical"].delivery
    assert "pushed only when explicitly requested" in by_title["TEST critical"].delivery
    assert "never pushed" in by_title["REPLAY row"].delivery and "never pushed" in by_title["DEMO row"].delivery
    assert "origin unrecognised" in by_title["BOGUS origin"].delivery


def test_an_unreadable_verification_record_is_an_error_needing_attention(tmp_path):
    cfg = _status_dir(tmp_path)
    (cfg.status_dir / d.VERIFICATION_FILE).write_text("{not json", encoding="utf-8")
    items = cm.alerts(d.Context(cfg))
    assert any(a.group == "attention" and "last_verification.json" in a.title and a.kind == "err" for a in items)


def test_system_evidence_shows_both_records_with_how_they_are_shown(mixed):
    _, home = call(make_app(mixed), "/")
    text = plain(home)
    assert "Last production unit failure (last_failure.json)" in text
    assert "Last deployment verification record (last_verification.json)" in text
    assert "shown as Production incident" in text


def test_demo_notifications_carry_the_demo_origin():
    from edge_lab.dashboard.demo import build_demo
    import shutil
    cfg, root = build_demo(experiments_root=Path(__file__).resolve().parents[1] / "experiments")
    try:
        rows = d.Context(cfg).notifications.value
        assert rows and all(r.get("origin") == "DEMO" for r in rows)
    finally:
        shutil.rmtree(root)


# --------------------------------------------------------------------------- The Odds API card


def _odds(state: str, verified: bool = False, **extra) -> dict:
    return {"schema": "test", "state": state, "detail": f"detail for {state}", "label": "OFFERED ODDS - RESEARCH ONLY, "
            "NOT EXECUTABLE", "executable": False, "live_read_verified": verified,
            "latest_successful_capture": {"received_at_utc": "2026-09-24T11:00:00Z", "offers": 42,
                                          "freshness": "fresh"} if verified else None,
            "quota": {"state": "OK", "used_local": 12, "ceiling": 450, "provider_remaining": "438"},
            "markets_observed": ["h2h"] if verified else [], "bookmakers_observed": [], "discovery": None,
            "targets": None, "next_capture": None, "cost_block": None, "pilot_state_file": "OK", "problems": [],
            "timer": "NOT_OBSERVABLE_HERE", **extra}


@pytest.mark.parametrize("state,title", [
    ("SETUP_NEEDED", "The Odds API — SETUP NEEDED"), ("KEY_REJECTED", "The Odds API — KEY REJECTED"),
    ("COST_BLOCKED", "The Odds API — COST BLOCKED"), ("DEGRADED", "The Odds API — DEGRADED"),
    ("QUOTA_EXHAUSTED", "The Odds API — QUOTA EXHAUSTED"), ("ERROR", "The Odds API — ERROR"),
])
def test_the_card_names_its_state_and_is_never_connected(state, title):
    text = plain(c.odds_status_card(_odds(state)))
    assert text.startswith(title) and "detail for" in text
    assert "CONNECTED" not in text.upper() and "Active" not in text
    assert "No live read yet" in text and "Never · research only" in text


def test_active_only_with_a_verified_live_read():
    active = plain(c.odds_status_card(_odds("ACTIVE", verified=True)))
    assert active.startswith("The Odds API — ACTIVE · LIVE READ VERIFIED") and "42 offers" in active
    claimed = plain(c.odds_status_card(_odds("ACTIVE", verified=False)))
    assert claimed.startswith("The Odds API — UNVERIFIED") and "ACTIVE · LIVE" not in claimed
    assert pr.odds_state({"state": "ACTIVE", "live_read_verified": "yes"}) == "UNVERIFIED"


def test_odds_status_reads_the_real_contract_and_shows_setup_needed(tmp_path):
    # No store file and no quota ledger yet: the real contract reports SETUP_NEEDED (nothing was paid for).
    ctx = d.Context(Config(db=tmp_path / "edge_lab.sqlite3", clock=lambda: NOW))
    result = ctx.odds_status
    assert result.status == d.OK and result.value["state"] == "SETUP_NEEDED"
    assert result.value["live_read_verified"] is False
    html = research.odds_body(result)
    assert "The Odds API — " in plain(html) and "CONNECTED" not in html.upper()


def test_odds_status_states(tmp_path, monkeypatch):
    assert d.Context(Config(clock=lambda: NOW)).odds_status.status == d.NO_DATA
    from edge_lab import odds_pilot
    seen = {}

    def fake(db, ledger, state, *, now):
        seen.update(db=db, ledger=ledger, state=state)
        raise RuntimeError(f"boom at {tmp_path}")
    monkeypatch.setattr(odds_pilot, "dashboard_status", fake)
    db = tmp_path / "edge_lab.sqlite3"
    result = d.Context(Config(db=db, clock=lambda: NOW)).odds_status
    assert result.status == d.ERROR and str(tmp_path) not in result.message
    assert seen["ledger"] == tmp_path / "odds_quota_ledger.json"
    assert seen["state"] == tmp_path / "odds_quota_ledger.json.pilot.json"
    html = research.odds_body(result)
    assert "not a healthy or empty feed" in html and 'class="empty k-err"' in html
    other = tmp_path / "elsewhere" / "ledger.json"
    d.Context(Config(db=db, odds_ledger=other, clock=lambda: NOW)).odds_status
    assert seen["ledger"] == other and seen["state"] == other.with_name("ledger.json.pilot.json")


def test_odds_ledger_flag_reaches_the_config(tmp_path):
    args = build_parser().parse_args(["--db", str(tmp_path / "x.sqlite3"), "--odds-ledger", str(tmp_path / "q.json")])
    cfg, _ = config_from_args(args)
    assert cfg.odds_ledger == tmp_path / "q.json"


def test_data_sources_tab_shows_the_odds_card(tmp_path):
    from edge_lab.dashboard.demo import build_demo
    import shutil
    cfg, root = build_demo(experiments_root=Path(__file__).resolve().parents[1] / "experiments")
    try:
        app = make_app(cfg)
        out = {}
        raw = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": "/experiments", "QUERY_STRING": "tab=sources",
                            "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s))).decode()
        card = plain(section(raw, "odds-h"))
        assert out["status"] == "200 OK" and "The Odds API (NFL pilot)" in card
        assert "The Odds API — SETUP NEEDED" in card and "OFFERED ODDS - RESEARCH ONLY, NOT EXECUTABLE" in card
    finally:
        shutil.rmtree(root)


def test_file_names_match_the_verification_owner():
    assert (d.FAILURE_FILE, d.VERIFICATION_FILE) == (verification.FAILURE_NAME, verification.VERIFICATION_NAME)

