"""Terminal: the Kalshi NHL coverage block on Research & Data › Data sources (NHL-B, ADR 0040; UI_CONTRACT 2026-09-29
(e)). Every state renders; counts, times and states only; never a price or a settled result."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from wsgiref.util import setup_testing_defaults

sys.path.insert(0, str(Path(__file__).parent / "browser"))

import fixture_states  # noqa: E402
from edge_lab.dashboard import data as d  # noqa: E402
from edge_lab.dashboard import fixtures, make_app  # noqa: E402
from edge_lab.dashboard.views import research  # noqa: E402
from edge_lab.freshness import parse_utc  # noqa: E402


def get(cfg, path: str) -> str:
    env: dict = {}
    setup_testing_defaults(env)
    env["PATH_INFO"], _, env["QUERY_STRING"] = path.partition("?")
    out: dict = {}
    body = b"".join(make_app(cfg)(env, lambda status, headers: out.update(status=status)))
    assert out["status"].startswith("200"), out
    return body.decode("utf-8")


def test_every_synthetic_state_renders():
    states = fixtures.synthetic_nhl_coverage()
    now = parse_utc(fixtures.NHL_NOW)
    populated = research.nhl_body(states["populated"], now)
    assert "Kalshi mapped" in populated and "past the deadline" in populated and "Hidden · NHL outcome" in populated
    assert "No fee model" in populated and "Rules not verified" in populated
    assert "T-60m nominal · read T-85m (protected window)" in populated
    assert "Not collecting · off by default" in research.nhl_body(states["idle"], now)
    assert "Schedule stale · nothing new planned" in research.nhl_body(states["stale"], now)
    assert "Kalshi NHL coverage unavailable" in research.nhl_body(states["unavailable"], now)
    assert "read error" in research.nhl_body(states["error"], now)


def test_the_sources_tab_shows_the_nhl_block_from_a_real_store():
    cfg, root = fixture_states.nhl()
    page = get(cfg, "/experiments?tab=sources")
    assert "Kalshi NHL coverage" in page and "KXNHLGAME · nominal T-6h / T-60m before puck drop" in page
    assert "T-60m nominal · read T-85m (protected window)" in page
    cov = d.Context(cfg).nhl_coverage
    assert cov.status == d.OK
    text = json.dumps(cov.value)
    assert '"bid"' not in text and '"ask"' not in text  # counts only
    assert cov.value["targets"]["game_horizons_captured"] == 3 and cov.value["games"]["unmapped"] == 2
    assert "SUPERSEDED_RESCHEDULED" in cov.value["missed_reasons"]


def test_an_empty_store_says_not_collecting(tmp_path):
    from edge_lab.dashboard import Config
    from edge_lab.storage import SnapshotStore

    store = SnapshotStore(tmp_path / "edge.sqlite3")
    page = get(Config(db=store.path), "/experiments?tab=sources")
    assert "No NHL schedule stored" in page and "Not collecting · off by default" in page


def test_the_gallery_shows_the_nhl_states():
    cfg, root = fixture_states.demo()
    page = get(cfg, "/gallery")
    assert "Kalshi NHL coverage (populated" in page and "Kalshi NHL coverage (not collecting" in page
