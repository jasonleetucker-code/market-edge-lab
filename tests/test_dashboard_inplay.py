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
                 "Proposed · not sent", "Hold versus exit", "synthetic cohort of 12 games", "not evidence of an edge",
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


# ------------------------------------------------------------------ review of #127 (NITs 1-4, 6)


def test_the_replay_cohort_is_labelled_as_not_this_contract(demo):
    view = iv.fixture_view("populated")
    note = view["comparison"]["scope_note"]
    assert note == "A synthetic cohort of 12 games, not this contract (KXNFLGAME-FIXTURE-HOME)."
    body = get(demo, "/experiments/inplay")[1]
    assert note in body
    # the note sits in the Hold versus exit section, before its first arm
    section = body[body.index("Hold versus exit"):]
    assert section.index(note) < section.index("Hold to settlement")


def test_primary_reason_is_the_decisions_own_reason_not_the_fee_caveat():
    view = iv.fixture_view("populated")
    reasons = view["policy"]["reasons"]
    assert reasons[0].startswith("FEE_UNKNOWN")  # the evaluator lists the caveat first
    assert ip.primary_reason(reasons).startswith("TARGET_REACHED")
    body = ip.inplay_body(view)
    facts = body[body.index("Primary reason"):body.index("Other reasons")]
    assert "TARGET_REACHED" in facts and "FEE_UNKNOWN" not in facts
    assert f"{len(reasons) - 1} more in Policy details" in body
    for r in reasons:  # every reason stays visible in the disclosure
        assert r.split(":")[0] in body
    stale = iv.fixture_view("stale")["policy"]["reasons"]
    assert ip.primary_reason(stale).startswith("BOOK_STALE")  # a block reads its blocking reason
    assert ip.primary_reason(["FEE_UNKNOWN: only"]) == "FEE_UNKNOWN: only"
    assert ip.primary_reason([]) is None


@pytest.mark.parametrize("mode,label", [("FIXTURE", "Fixture evidence"), ("SYNTHETIC_REPLAY", "Synthetic evidence"),
                                        ("RECORDED", "Recorded evidence"), ("SOMETHING_ELSE",
                                                                            "Evidence of unknown origin")])
def test_the_populated_capsule_follows_the_mode(mode, label):
    view = {**iv.fixture_view("populated"), "mode": mode}
    head = ip.header(view)
    capsule = re.search(r'title="code: INPLAY_STATE_POPULATED">.*?</svg>([^<]*)</span>', head)
    assert capsule and capsule.group(1) == label
    status = re.search(r'class="statusline-text">.*?</div>', head, re.S).group(0)
    assert label in status  # the status line's title follows the mode too
    assert "Fixture evidence" not in iv.fixture_view("populated")["detail"]  # no fixed word in the contract


def test_header_source_has_no_spacing_nit():
    import inspect
    assert "clock =(" not in inspect.getsource(ip.header)


def test_rendering_every_inplay_page_makes_no_network_call_and_writes_nothing(monkeypatch, tmp_path, demo, prod):
    import socket
    import edge_lab.http as http_module

    def boom(*a, **k):
        raise AssertionError("network attempted while rendering")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(http_module, "_default_opener", boom)
    monkeypatch.chdir(tmp_path)
    repo = __import__("pathlib").Path(__file__).resolve().parents[1]
    watched = [repo / "experiments", repo / "src" / "edge_lab"]
    before = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()
              and "__pycache__" not in p.parts}
    for app, path in [(prod, "/experiments/inplay"), (prod, "/experiments"), (demo, "/experiments/inplay"),
                      (demo, "/gallery/inplay")]:
        assert get(app, path)[0].startswith("200"), path
    assert list(tmp_path.iterdir()) == []
    after = {p: p.stat().st_mtime_ns for d in watched for p in d.rglob("*") if p.is_file()
             and "__pycache__" not in p.parts}
    assert after == before


def test_the_research_tab_links_the_page(prod):
    status, body = get(prod, "/experiments")
    assert status.startswith("200") and 'href="/experiments/inplay"' in body and "In-play research" in body


def test_only_get_and_head(prod):
    assert get(prod, "/experiments/inplay", method="POST")[0].startswith("405")
    assert get(prod, "/experiments/inplay", method="HEAD")[0].startswith("200")


# ------------------------------------------------------------------ source/state validity and fill economics (PR C)


def _sec(html: str, sid: str) -> str:
    m = re.search(rf'aria-labelledby="{sid}".*?</section>', html, re.S)
    assert m, sid
    return m.group(0)


def test_source_state_section_populated_is_simulated_fixture_evidence_and_valid():
    html = ip.source_state_section(iv.fixture_view("populated"))
    for text in ("Simulated · not actual", "Fixture input", "fixture:kalshi-book", "FIXTURE_EXCHANGE",
                 "Unknown age: source clock bound unknown", "Unknown: not declared by the source",
                 "Valid at replay clock", "no later material state", "Latency stages (unmeasured is not zero)",
                 "in game", "game time, not UTC"):
        assert text in html, text
    assert "LIVE" not in html and _no_live(html)


def test_an_invalidated_decision_is_blocked_with_its_reason():
    v = iv.fixture_view("invalidated")
    ss = ip.source_state_section(v)
    assert "Invalidated · recompute" in ss and "MATERIAL_STATE_CHANGE" in ss
    pol = ip.policy_section(v)
    assert "Blocked · no new risk" in pol and "STATE_INVALIDATED" in pol and "Exit · proposal only" not in pol


def test_an_unreadable_state_update_needs_review():
    v = iv.fixture_view("state_unknown")
    assert "Review required" in ip.source_state_section(v) and "STATE_UNKNOWN" in ip.source_state_section(v)
    assert "STATE_REVIEW_REQUIRED" in ip.policy_section(v)


def test_stale_content_and_not_evaluated_states():
    assert "Stale — not actionable" in ip.source_state_section(iv.fixture_view("stale"))
    unevaluated = dict(iv.fixture_view("populated"), source_state=None, fill_economics=None)
    assert "Not evaluated" in ip.source_state_section(unevaluated)
    assert "Not evaluated" in ip.economics_section(unevaluated)
    assert "Not evaluated" in ip.economics_section(iv.fixture_view("unsupported"))  # no cohort replayed


def test_fill_economics_keeps_modes_apart_and_names_missing_denominators():
    html = ip.economics_section(iv.fixture_view("populated"))
    for text in ("Hold to settlement", "Full exit · bot-triggered (taker)", "Full exit · preplaced limit (book maker)",
                 "book maker", "taker", "fees unknown: net blocked", "after-cost figure unavailable: fee unknown",
                 "Simulated fills only", "RFQ: not evaluated", "Not a real fill, not an edge"):
        assert text in html, text
    assert 'class="num pos"' not in html and 'class="num neg"' not in html and _no_live(html)
    _read_only(html)


def test_a_refused_economics_row_is_an_error_state():
    v = iv.fixture_view("populated")
    fe = dict(v["fill_economics"], rows=[{"arm": "Hold to settlement", "state": "ERROR",
                                          "detail": "CAPITAL_OVERCOMMITTED at 2026-10-04: cash balance -1 < 0"}],
              state="PARTIAL")
    html = ip.economics_section(dict(v, fill_economics=fe))
    assert "Economics refused" in html and "CAPITAL_OVERCOMMITTED" in html and "Refused" in html


def test_the_demo_page_shows_both_new_sections_in_order(demo):
    body = get(demo, "/experiments/inplay")[1]
    order = [body.index(x) for x in ('id="ip-pos"', 'id="ip-ss"', 'id="ip-pol"', 'id="ip-cmp"', 'id="ip-econ"',
                                     'id="ip-auth"')]
    assert order == sorted(order)
    assert "Source and state validity" in _sec(body, "ip-ss") and "Fill-conditioned economics" in _sec(body, "ip-econ")


def test_production_shows_no_state_or_economics_sections(prod):
    body = get(prod, "/experiments/inplay")[1]
    assert "Not authorized" in body and 'id="ip-ss"' not in body and 'id="ip-econ"' not in body
