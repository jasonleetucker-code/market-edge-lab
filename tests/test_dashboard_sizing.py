"""RESEARCH SIZING / SHADOW SIZING CHALLENGER panel (directive 2026-09-24, Deliverable 2).

The panel renders Lane A's read-only contract `sizing_counterfactual.panel_for_market` exactly:
every number is the contract's string, only formatted. These tests check the label, the absence
of any stake input or order action, each named unavailable reason, the computed-zero case, the
policy comparison, the data-layer states and the ledger-head cache.
"""

from __future__ import annotations

import dataclasses
import re
import shutil
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import components as c
from edge_lab.dashboard import data as d
from edge_lab.dashboard import fixtures
from edge_lab.dashboard.demo import build_demo
from edge_lab.dashboard.views import markets

REPO = Path(__file__).resolve().parents[1]


def plain(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def call(app, path):
    query = ""
    if "?" in path:
        path, query = path.split("?", 1)
    out = {}
    body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query,
                         "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s)))
    return out["status"], body.decode("utf-8")


@pytest.fixture(scope="module")
def panels():
    return fixtures.synthetic_sizing_panels()


@pytest.fixture(scope="module")
def demo():
    cfg, root = build_demo(experiments_root=REPO / "experiments")
    frozen = datetime.now(timezone.utc)
    yield dataclasses.replace(cfg, clock=lambda: frozen)
    shutil.rmtree(root)


@pytest.fixture
def fake_contract(monkeypatch):
    """Install a stand-in for `edge_lab.sizing_counterfactual` that counts calls."""
    module = types.ModuleType(d.RESEARCH_SIZING_MODULE)
    module.calls = []

    def panel_for_market(store, ledger, market_id, **kw):
        module.calls.append(market_id)
        return {**fixtures.synthetic_sizing_panels()["sized"], "market_id": market_id}
    module.panel_for_market = panel_for_market
    monkeypatch.setitem(sys.modules, d.RESEARCH_SIZING_MODULE, module)
    monkeypatch.setattr(d, "_SIZING_CACHE", {})
    return module


# --------------------------------------------------------------------------- component


def test_label_is_research_never_a_recommendation(panels):
    for panel in panels.values():
        html = c.research_sizing(panel)
        text = plain(html)
        assert "RESEARCH SIZING - SHADOW SIZING CHALLENGER" in text
        assert "Recommended bet" not in text and "recommended bet" not in text.lower()
        assert "not a bet" in text


def test_no_stake_input_slider_submit_or_order_action(panels):
    for panel in panels.values():
        html = c.research_sizing(panel).lower()
        for tag in ("<input", "<form", "<button", "<select", "<textarea", 'type="range"'):
            assert tag not in html
        assert "place order" not in html and "submit" not in html


def test_sized_side_shows_the_contract_figures_only_formatted(panels):
    text = plain(c.research_sizing(panels["sized"]))
    for needle in ("Challenger size (research) 3 contracts · $1.08 cost", "Verdict Sized (research)",
                   "Binding constraint POSITION_CAP", "Model probability 41.0%", "Conservative probability 38.0%",
                   "Expected net edge / contract +5.12¢", "Entry price 34¢", "Estimated fee $0.06",
                   "Full-Kelly amount $4.32", "Policy amount before caps $1.44", "Bankroll basis $1,000.00",
                   "Capital horizon Within starter horizon", "cash horizon cap —"):
        assert needle in text, needle
    assert "every liquidity cap is top-of-book-limited" in text


def test_policy_comparison_lists_every_policy(panels):
    html = c.research_sizing(panels["sized"])
    table = html[html.index("Research sizing by policy"):]
    for letter in "ABCDEFGH":
        assert f"{letter} · sizing-v2-" in table
    assert "0.22%" in plain(table)  # fraction_of_bankroll as the contract gives it, formatted


def test_one_side_unavailable_names_its_reason(panels):
    html = c.research_sizing(panels["sized"])
    no_side = html[html.index("NO side"):]
    assert "No model" in plain(no_side) and "SYNTHETIC engine detail for: No model" in plain(no_side)
    assert 'class="empty k-warn"' in no_side


def test_computed_zero_is_available_not_missing(panels):
    text = plain(c.research_sizing(panels["zero"]))
    assert "Challenger size (research) 0 contracts · $0.00 cost" in text
    assert "Zero: no edge after costs" in text and "Unavailable" not in text


@pytest.mark.parametrize("reason", fixtures.SIZING_UNAVAILABLE)
def test_each_unavailable_reason_is_named(panels, reason):
    html = c.research_sizing(panels[reason])
    assert f'<span>{reason}</span>' in html and f"SYNTHETIC detail for: {reason}" in html
    assert "Challenger size" not in html  # no figure when the engine could not compute


def test_every_directive_reason_is_covered():
    assert set(fixtures.SIZING_UNAVAILABLE) >= {"No model", "Fees unsupported", "Stale quote", "Rules unresolved",
                                                 "Insufficient uncertainty evidence", "Risk state unavailable",
                                                 "Unsupported payoff"}


# --------------------------------------------------------------------------- data layer and states


@pytest.mark.parametrize("status,title,kind", [(d.NO_DATA, "Research sizing not available", "nd"),
                                               (d.ERROR, "Research sizing unavailable", "err")])
def test_slot_states(status, title, kind):
    html = markets.sizing_body(d.Loaded(status, message="some reason"))
    assert title in html and f'class="empty k-{kind}"' in html and "some reason" in html.lower()
    if status == d.ERROR:
        assert "not a zero size" in html


def test_contract_not_installed_is_no_data(monkeypatch, demo):
    monkeypatch.setitem(sys.modules, d.RESEARCH_SIZING_MODULE, None)  # import raises ImportError
    result = d.research_sizing(d.Context(demo), "kalshi:DEMO-B71.5")
    assert result.status == d.NO_DATA and "not installed" in result.message


def test_no_ledger_is_no_data_and_a_broken_ledger_is_error(fake_contract, tmp_path):
    assert d.research_sizing(d.Context(Config()), "kalshi:X").status == d.NO_DATA
    bad = tmp_path / "ledger.sqlite3"
    bad.write_bytes(b"not a sqlite database")
    result = d.research_sizing(d.Context(Config(ledger=bad)), "kalshi:X")
    assert result.status == d.ERROR and str(tmp_path) not in result.message
    assert fake_contract.calls == []


def test_panel_is_cached_by_ledger_head(fake_contract, demo):
    first = d.research_sizing(d.Context(demo), "kalshi:DEMO-B71.5")
    again = d.research_sizing(d.Context(demo), "kalshi:DEMO-B71.5")
    other = d.research_sizing(d.Context(demo), "kalshi:DEMO-B73.5")
    assert first.status == d.OK and again is first and other is not first
    assert fake_contract.calls == ["kalshi:DEMO-B71.5", "kalshi:DEMO-B73.5"]


def test_a_new_ledger_entry_misses_the_cache(fake_contract, tmp_path):
    from edge_lab.shadow_ledger import ShadowLedger
    cfg, root = build_demo(experiments_root=REPO / "experiments")
    try:
        d.research_sizing(d.Context(cfg), "kalshi:DEMO-B71.5")
        account = d.OPERATIONAL_ACCOUNT_ID
        ledger = ShadowLedger(cfg.ledger)
        dec = dict(d.Context(cfg).account(account).decisions[0])
        dec.pop("_meta", None)
        dec["decision_id"] = dec["decision_id"] + "-again"
        dec["slot"] = dec["slot"] + "-again"
        ledger.record_decision(account, dec)
        d.research_sizing(d.Context(cfg), "kalshi:DEMO-B71.5")
    finally:
        shutil.rmtree(root)
    assert fake_contract.calls == ["kalshi:DEMO-B71.5", "kalshi:DEMO-B71.5"]


def test_contract_failures_are_errors_never_raised(monkeypatch, demo):
    module = types.ModuleType(d.RESEARCH_SIZING_MODULE)
    module.panel_for_market = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setitem(sys.modules, d.RESEARCH_SIZING_MODULE, module)
    monkeypatch.setattr(d, "_SIZING_CACHE", {})
    assert d.research_sizing(d.Context(demo), "kalshi:DEMO-B71.5").status == d.ERROR
    module.panel_for_market = lambda *a, **k: None
    assert d.research_sizing(d.Context(demo), "kalshi:DEMO-B71.5").status == d.ERROR


def test_detail_page_has_the_research_sizing_section(fake_contract, demo):
    status, body = call(make_app(demo), "/market?venue=kalshi&id=DEMO-B71.5&side=YES")
    assert status == "200 OK"
    section = body[body.index('aria-labelledby="rs-h"'):]
    section = section[:section.index("</section>")]
    assert "RESEARCH SIZING - SHADOW SIZING CHALLENGER" in section and "<input" not in section
    assert body.index('aria-labelledby="xv-h"') < body.index('aria-labelledby="rs-h"')


def test_real_contract_renders_on_the_demo_store(demo, monkeypatch):
    pytest.importorskip(d.RESEARCH_SIZING_MODULE)
    monkeypatch.setattr(d, "_SIZING_CACHE", {})
    result = d.research_sizing(d.Context(demo), "kalshi:DEMO-B71.5")
    assert result.status == d.OK and isinstance(result.value, dict)
    html = markets.sizing_body(result)
    assert "RESEARCH SIZING" in html and "Recommended bet" not in html


def test_gallery_shows_the_sizing_states(demo):
    status, body = call(make_app(demo), "/gallery")
    text = plain(body)
    assert status == "200 OK"
    for needle in ("ResearchSizing (sized", "Zero: no edge after costs", "Research sizing not available",
                   "Research sizing unavailable", *fixtures.SIZING_UNAVAILABLE):
        assert needle in text, needle
