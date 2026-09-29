"""In-play research page (/experiments/inplay) and its demo-only state gallery (#122 §21B, UI_CONTRACT)."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard.views import inplay as ip
from edge_lab import inplay_view as iv

NOW = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)


def get(app, path, method="GET"):
    out = {}

    def start(status, headers):
        out["status"], out["headers"] = status, dict(headers)
    body = b"".join(app({"REQUEST_METHOD": method, "PATH_INFO": path, "HTTP_HOST": "localhost"}, start))
    return out["status"], body.decode("utf-8")


@pytest.fixture(scope="module")
def prod():
    return make_app(Config(clock=lambda: NOW))


@pytest.fixture(scope="module")
def demo():
    return make_app(Config(demo=True, clock=lambda: NOW))


def _no_live(body: str) -> bool:
    return "LIVE" not in re.sub(r"(?i)not live", "", body)


def _read_only(body: str) -> None:
    assert "<form" not in body and "<button" not in body and "<input" not in body
    assert ' style="' not in body and " onclick" not in body.lower()
    assert "<script>" not in body  # CSP: no inline script
    for word in ("Buy", "Sell now", "Place order", "Submit", "Edge score"):
        assert word not in body


def test_production_shows_not_authorized_and_no_figures(prod):
    status, body = get(prod, "/experiments/inplay")
    assert status.startswith("200")
    assert "No in-play source is authorized" in body and "PROPOSED, NOT APPROVED" in body
    assert "Replay P&amp;L" not in body and "Hold versus exit" not in body
    assert _no_live(body) and "SHADOW · NO REAL MONEY" in body
    _read_only(body)


def test_the_gallery_is_demo_only(prod, demo):
    assert get(prod, "/gallery/inplay")[0].startswith("404")
    status, body = get(demo, "/gallery/inplay")
    assert status.startswith("200") and "FIXTURE STATES" in body
    for name in iv.FIXTURE_VARIANTS:
        assert f"State · {name}" in body
    _read_only(body)
    assert _no_live(body)


def test_demo_page_renders_the_fixture_replay(demo):
    status, body = get(demo, "/experiments/inplay")
    assert status.startswith("200")
    for text in ("Fixture replay · not live", "Position · simulated", "Policy proposal", "Exit · proposal only",
                 "Proposed · not sent", "Hold versus exit", "SYNTHETIC cohort", "not evidence of an edge",
                 "Net proceeds (not profit)", "a displayed bid is not a fill", "Blocker and approval",
                 "Resting sale never placed", "none: a policy replay with modelled latency"):
        assert text in body, text
    assert "after-cost figure unavailable: fee unknown" in body  # KXNFLGAME fees: never shown as a number
    assert 'class="num pos"' not in body and 'class="num neg"' not in body  # nothing coloured as a result
    _read_only(body)
    assert _no_live(body)


@pytest.mark.parametrize("variant,words", [
    ("empty", ["No book messages", "No replay"]),
    ("stale", ["Stale book — not actionable", "Blocked · no new risk"]),
    ("partial", ["Partial evidence", "DISCONNECTED"]),
    ("resync", ["Gap · awaiting resync", "Blocked · no new risk"]),
    ("unsupported", ["Policy unsupported", "Unsupported"]),
    ("paused", ["Market paused", "Trading paused"]),
    ("error", ["In-play evidence unavailable"]),
    ("not_authorized", ["No in-play source is authorized"]),
])
def test_each_state_renders_its_own_words(variant, words):
    body = ip.inplay_body(iv.fixture_view(variant))
    for w in words:
        assert w in body, (variant, w)
    _read_only(body)


def test_missing_values_render_unavailable_never_zero():
    body = ip.inplay_body(iv.fixture_view("stale"))
    assert "no usable book" in body  # the exit estimate's reason, not $0.00
    assert "$0.00" not in body


def test_a_live_mode_or_foreign_schema_is_refused_as_an_error(monkeypatch):
    ctx = d.Context(Config(clock=lambda: NOW))
    monkeypatch.setattr(iv, "not_authorized_view", lambda: {**iv._base(iv.ViewState.POPULATED, iv.Mode.FIXTURE,
                                                                        None, "x"), "mode": "LIVE"})
    assert d.inplay_view(ctx).status == d.ERROR
    monkeypatch.setattr(iv, "not_authorized_view", lambda: {"schema": "other"})
    assert d.inplay_view(ctx).status == d.ERROR

    def boom():
        raise RuntimeError("C:/secret/path/journal.jsonl unreadable")
    monkeypatch.setattr(iv, "not_authorized_view", boom)
    loaded = d.inplay_view(ctx)
    assert loaded.status == d.ERROR and "C:/secret" not in loaded.message


def test_error_state_renders_on_the_page(monkeypatch, prod):
    monkeypatch.setattr(iv, "not_authorized_view", lambda: {"schema": "other"})
    status, body = get(prod, "/experiments/inplay")
    assert status.startswith("200") and "Data unavailable" in body


def test_only_get_and_head(prod):
    assert get(prod, "/experiments/inplay", method="POST")[0].startswith("405")
    assert get(prod, "/experiments/inplay", method="HEAD")[0].startswith("200")
