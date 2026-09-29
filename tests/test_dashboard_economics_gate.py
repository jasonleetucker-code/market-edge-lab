"""The EXP-002 gate line on Research & Data -> Research, Family A (owner directive 2026-09-28 §21A; UI_CONTRACT §8).

Gate version, as-of, input horizons, admissible count, diagnostics, outcome-access status, the insufficiency or
failure reason and a diagnostic-only flag; freeze eligibility shown separately; never green and never "ready to
freeze". States: insufficient evidence, insufficient data, fail (mirror quoting), error, not computed, stale, labels
logged, no protocol.
"""

from __future__ import annotations

import re
from html import unescape
import shutil
import socket
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from edge_lab import sports_evidence as se
from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard import sports_fixtures as sf
from edge_lab.dashboard.views import research

sys.path.insert(0, str(Path(__file__).resolve().parent / "browser"))
import fixture_states  # noqa: E402

FORBIDDEN = ("ready to freeze", "freeze eligible: yes", "eligible to freeze", "k-ok", "passed", "pass_repeat")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the dashboard attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def plain(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def page(cfg: Config) -> str:
    out = {}
    body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/experiments", "QUERY_STRING": "",
                                   "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s)))
    assert out["status"] == "200 OK"
    return body.decode("utf-8")


def _line(verdict: str = se.V3_INSUFFICIENT_EVIDENCE, **over) -> dict:
    base = {"state": "OK", "version": se.GATE_V3_VERSION, "as_of_utc": "2026-10-19T15:00:00Z", "verdict": verdict,
            "input_horizons": {"bound": "T-6h", "diagnostics": ["T-6h", "T-24h"]},
            "counts": {"t6_due": 60, "admissible_games": 54, "weeks": 4, "t6_not_paired": 4, "t6_book_locked": 0,
                       "t6_book_crossed": 1, "t6_book_one_sided_or_empty": 1, "t6_no_consensus": 0,
                       "t6_admissible_book_before_odds": 2, "wide_books": 3, "dispersion_pairs": 100},
            "estimates": {"share_gaps_within_spread": 0.41, "gap_sd": 0.018, "share_dispersion_zero": 0.6,
                          "mirror_quoting": False, "spreads_t6": {"n": 108, "min": 0.01, "median": 0.01, "max": 0.03}},
            "by_candidate_min_effect": [
                {"min_effect": 0.005, "tolerable_bias": 0.00125, "bound_upper_90": 0.0042,
                 "bound_state": se.V3_BOUND_AT_OR_ABOVE, "verdict": verdict, "freeze_eligible": False}],
            "insufficient": [], "diagnostic_only": True, "label_free": True, "not_a_bound": se.V3_NOT_A_BOUND,
            "unidentified": list(se.V3_UNIDENTIFIED),
            "outcome_access": {"state": "NO_LABEL_VIEW_LOGGED", "label_views": 0},
            "freeze": {"state": "NOT_ELIGIBLE", "reasons": ["gate exp002-noise-gate-v3 verdict X: no gate state "
                                                            "authorizes a freeze", "EXP-002 is DRAFT"]}}
    base.update(over)
    return base


def _assert_safe(html: str) -> str:
    text = plain(html)
    low = text.lower() + " " + html.lower()
    for word in FORBIDDEN:
        assert word not in low, word
    return text


def test_insufficient_evidence_line_shows_every_required_field_and_freeze_separately():
    html = research._ev_exp002_gate(_line(), "POPULATED")
    text = _assert_safe(html)
    for needed in ("EXP-002 pre-freeze gate", "exp002-noise-gate-v3", "diagnostic only", "as of", "T-6h (bound)",
                   "T-24h (diagnostics)", "54 admissible T-6h game(s) of 60 due", "4 NFL week(s)",
                   "Insufficient evidence", "Spreads cannot bound latent, stale or shared book error",
                   "Outcome access", "No logged label view", "the gate reads no label",
                   "Freeze eligibility", "Not eligible", "a diagnostic is never freeze eligibility",
                   "0.42¢", "0.125¢", "why a spread is not a bound", "not identifiable here", "freeze blockers",
                   "book-before-odds sides 2 (comparability only)"):
        assert needed in text, needed
    assert text.index("EXP-002 pre-freeze gate") < text.index("Freeze eligibility")


def test_insufficient_data_fail_error_and_missing_states():
    thin = plain(research._ev_exp002_gate(_line(se.V3_INSUFFICIENT_DATA, insufficient=[
        "9 admissible T-6h games < 20", "1 NFL week(s) < 4: no week-cluster bound"]), "PARTIAL"))
    assert "Insufficient data" in thin and "9 admissible T-6h games < 20" in thin and "Not eligible" in thin
    mirror = plain(research._ev_exp002_gate(_line(se.V3_FAIL), "POPULATED"))
    assert "Fail" in mirror and "mirror quoting" in mirror and "Not eligible" in mirror
    error = _assert_safe(research._ev_exp002_gate({"state": "ERROR", "version": se.GATE_V3_VERSION,
                                                   "detail": "RuntimeError: boom"}, "POPULATED"))
    assert "Gate error" in error and "could not be computed" in error and "RuntimeError: boom" in error
    assert "Not eligible" in error
    missing = plain(research._ev_exp002_gate(None, "POPULATED"))
    assert "gate status not available" in missing and "—" in missing  # unavailable, never zero or a verdict


def test_stale_evidence_and_logged_labels_are_named():
    stale = plain(research._ev_exp002_gate(_line(), "STALE"))
    assert "evidence stale: nothing here is current" in stale
    logged = plain(research._ev_exp002_gate(_line(outcome_access={
        "state": "LABEL_VIEWS_LOGGED", "label_views": 2, "latest_label_view_utc": "2026-10-20T01:00:00Z",
        "roles": ["DEVELOPMENT"]}), "POPULATED"))
    assert "2 logged label view(s)" in logged and "DEVELOPMENT" in logged
    unknown = plain(research._ev_exp002_gate(_line(outcome_access={"state": "NO_LOG"}), "POPULATED"))
    assert "access unknown" in unknown
    blocked = plain(research._ev_exp002_gate(_line(outcome_access={"state": "NO_PROTOCOL"}), "POPULATED"))
    assert "No protocol registered" in blocked


def test_the_gate_line_renders_on_the_page_from_the_real_view(tmp_path):
    cfg, root = fixture_states.economics(tmp_path / "econ")
    try:
        html = page(cfg)
        part = html[html.index('aria-labelledby="ev-h"'):]
        part = part[:part.index("</section>")]
        text = _assert_safe(part)
        assert "EXP-002 pre-freeze gate" in text and "exp002-noise-gate-v3" in text
        assert "Insufficient data" in text  # the fixture holds fewer than four NFL weeks
        assert "Freeze eligibility" in text and "Not eligible" in text
        assert text.index("EXP-002 pre-freeze gate") < text.index("Join diagnostics")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_gate_error_detail_loses_local_paths(tmp_path, monkeypatch):
    path, now = sf.fixture_store(tmp_path / "p")
    real = se.terminal_view

    def with_error(db, *, now, experiments_root=None):
        view = real(db, now=now, experiments_root=experiments_root)
        view["family_a"]["exp002_gate"] = {"state": "ERROR", "version": se.GATE_V3_VERSION,
                                           "detail": f"OSError: cannot read {tmp_path}/secret/x.sqlite3"}
        return view

    monkeypatch.setattr(se, "terminal_view", with_error)
    loaded = d.economic_evidence_a(d.Context(Config(db=path, clock=lambda: now)))
    assert loaded.status == d.OK and str(tmp_path) not in loaded.value["exp002_gate"]["detail"]


def test_the_stale_family_view_carries_the_gate_line(tmp_path):
    path, now = sf.fixture_store(tmp_path / "s")
    view = se.terminal_view(path, now=now + timedelta(days=12))["family_a"]
    assert view["state"] == "STALE" and view["exp002_gate"]["state"] == "OK"
    html = research.economics_body(d.Loaded(d.OK, view), d.Loaded(d.NO_DATA, message="x"), now)
    assert "evidence stale: nothing here is current" in plain(html)
