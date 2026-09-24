"""Source freshness on Research & Data -> Data sources, from the Freshness Fabric supervisor's artifact.

Owner directive 2026-09-24 (evening), Terminal v1 and contract C4; Lane A's contract (#81, ADR 0031):
`freshness.json`, schema `freshness-fabric-status/1`. The Terminal shows what is fresh, what is due
next and why, makes EXTERNAL_SCHEDULE supervision explicit (mode and schedule owner), shows a
carried evaluation inside a protected window (carried_from_utc, sources_evaluated_at_utc, the Kalshi
close-tick guard), judges the artifact's own age by generated_at_utc and never re-derives a figure.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from edge_lab import freshness_fabric as ff
from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard import fixtures
from edge_lab.dashboard import presentation as pr
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


def section(body: str, sid: str = "fresh-h") -> str:
    part = body[body.index(f'aria-labelledby="{sid}"'):]
    return part[:part.index("</section>")]


@pytest.fixture
def current():
    cfg, root = fixture_states.freshness()
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def deferred():
    cfg, root = fixture_states.freshness_deferred()
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


def _artifact(cfg: Config) -> dict:
    return json.loads((cfg.status_dir / d.FRESHNESS_FILE).read_text(encoding="utf-8"))


def test_the_file_name_is_the_supervisors():
    assert d.FRESHNESS_FILE == ff.ARTIFACT_NAME


def test_the_view_is_first_on_data_sources_and_shows_every_source(current):
    body = page(current)
    assert body.index('aria-labelledby="fresh-h"') < body.index('aria-labelledby="ven-h"')
    doc = _artifact(current)
    html = section(body)
    text = plain(html)
    every = html[html.index("Every source by domain"):]
    assert every.count('class="row"') == len(doc["sources"]) == doc["summary"]["sources"]
    attention = html[html.index("Needs attention"):html.index("Every source by domain")]
    flagged = [s["source_id"] for s in doc["sources"] if research.needs_attention(s)]
    assert attention.count('class="row"') == len(flagged) and all(f in attention for f in flagged)
    assert all(s["schedule_state"] in ("MISSED",) or s["health"] in ("FAILING", "DEGRADED") or s["disagreements"]
               or s["schedule_state"] in research.ATTENTION_SCHEDULE for s in doc["sources"]
               if s["source_id"] in flagged)
    for src in doc["sources"]:
        assert src["source_id"] in text
        if src["mode"] == "EXTERNAL_SCHEDULE":  # supervision is explicit, with who actually runs it
            assert f"External schedule · supervised only · run by {src['schedule_owner']}" in text
    n = len(doc["sources"])
    assert f"{n} of {n} sources are external schedules the fabric only supervises" in text
    assert "network: none" in text and "controls schedules: no" in text
    summary = doc["summary"]
    assert f"Fresh {summary['by_freshness'].get('FRESH', 0)} of {n}" in text
    assert f"Missed {len(summary['missed'])}" in text and f"Due now {len(summary['due_now'])}" in text
    for due in summary["next_due"]:
        assert f"{pr.datetime_et(due['next_due_utc'])} · {due['source_id']}" in text
    assert "Freshness report is stale" not in text and "Supervisor deferred" not in text


def test_every_figure_is_the_artifacts_own(current):
    """No UI arithmetic: ages are the artifact's data_age_s (as of its evaluation), not now minus receipt."""
    doc = _artifact(current)
    text = plain(section(page(current)))
    for src in doc["sources"]:
        if src["data_age_s"] is not None:
            assert f"data {pr.duration_text(src['data_age_s'])} old at evaluation" in text
        if src["next_due_utc"]:
            assert pr.datetime_et(src["next_due_utc"]) in text
    odds = next(s for s in doc["sources"] if s["source_id"] == "the_odds_api.nfl_odds")
    assert odds["usable_for_research"] and not odds["usable_for_decision"]
    row = text[text.index("the_odds_api.nfl_odds sports"):]
    assert "Usable for Research only" in row[:600]


def test_a_deferred_report_names_the_guard_and_the_carried_evaluation(deferred):
    doc = _artifact(deferred)
    assert doc["supervisor"]["state"] == "DEFERRED_PROTECTED_WINDOW"
    assert doc["supervisor"]["deferred"]["window"] == "kalshi_close_tick"
    text = plain(section(page(deferred)))
    evaluated = pr.datetime_et(doc["sources_evaluated_at_utc"])
    for needle in ("Supervisor deferred: protected window", "Kalshi close-tick guard",
                   f"Sources are carried from the {evaluated} evaluation", "none is decision-grade",
                   f"Sources evaluated {evaluated}", f"as of {pr.datetime_et(doc['sources'][0]['carried_from_utc'])}"):
        assert needle in text, needle
    assert "Research and decision" not in text  # carried records are never decision-grade


def test_a_deferred_report_with_nothing_carried_says_every_source_is_unknown():
    loaded = fixtures.synthetic_freshness()["deferred_empty"]
    text = plain(research.freshness_body(loaded, NOW))
    assert "no recent evaluation could be carried" in text and "Sources evaluated —" in text  # not evaluated, never a time


def test_the_report_is_judged_by_its_own_generation_time(current):
    generated = datetime.fromisoformat(_artifact(current)["generated_at_utc"].replace("Z", "+00:00"))
    fresh = d.Context(replace(current, clock=lambda: generated + ff.SUPERVISOR_MAX_AGE)).freshness_status.value
    stale = d.Context(replace(current, clock=lambda: generated + ff.SUPERVISOR_MAX_AGE + timedelta(seconds=1))
                      ).freshness_status.value
    assert (fresh.report_freshness, stale.report_freshness) == ("FRESH", "STALE")
    text = plain(section(page(replace(current, clock=lambda: generated + timedelta(hours=2)))))
    assert "Freshness report is stale" in text and "not now" in text


def test_source_unavailable_and_error_states(tmp_path):
    none = d.Context(Config(clock=lambda: NOW)).freshness_status
    assert none.status == d.NO_DATA
    status = tmp_path / "status"
    status.mkdir()
    cfg = Config(status_dir=status, clock=lambda: NOW)
    missing = d.Context(cfg).freshness_status
    assert missing.status == d.NO_DATA and "has not written freshness.json" in missing.message
    text = plain(section(page(cfg)))
    assert "Source freshness unavailable" in text and "read error" not in text
    for content, why in (("{broken", "cannot be read"), (json.dumps({"schema": "other/1"}), "has schema"),
                         (json.dumps({"schema": ff.SCHEMA}), "lacks its sources")):
        (status / d.FRESHNESS_FILE).write_text(content, encoding="utf-8")
        result = d.Context(cfg).freshness_status
        assert result.status == d.ERROR and why in result.message, content
        html = section(page(cfg))
        assert "Source freshness unavailable (read error)" in plain(html) and 'role="alert"' in html


def test_partial_supervisor_and_unknown_codes():
    populated = fixtures.synthetic_freshness()["populated"]
    text = plain(research.freshness_body(fixtures.synthetic_freshness()["partial"], NOW))
    assert "Partial: a provider failed" in text and "SYNTHETIC provider: RuntimeError: boom" in text
    doc = dict(populated.value.doc)
    doc["sources"] = [{**doc["sources"][0], "schedule_state": "SOMETHING_NEW", "health": "ODD", "freshness": "WEIRD"}]
    html = research.freshness_body(d.Loaded(d.OK, d.FreshnessReport(doc, "FRESH", ff.SUPERVISOR_MAX_AGE)), NOW)
    for code in ("SOMETHING_NEW", "ODD", "WEIRD"):
        assert f'title="code: {code}"' in html, code


def test_missed_and_disagreements_are_visible():
    text = plain(research.freshness_body(fixtures.synthetic_freshness()["populated"], NOW))
    assert "Missed 1" in text and "Disagreements 1 with the canonical scheduler" in text
    assert "Usable for Research and decision" in text and "SYNTHETIC: the timer tick falls outside" in text


def test_untrusted_text_is_escaped():
    evil = "<script>alert(1)</script>"
    populated = fixtures.synthetic_freshness()["populated"].value
    doc = {**populated.doc, "sources": [{**populated.doc["sources"][0], "why_due": evil, "notes": [evil]}]}
    html = research.freshness_body(d.Loaded(d.OK, d.FreshnessReport(doc, "FRESH", ff.SUPERVISOR_MAX_AGE)), NOW)
    assert evil not in html and "&lt;script&gt;" in html


def test_gallery_shows_the_freshness_states():
    from edge_lab.dashboard.demo import build_demo
    cfg, root = build_demo(experiments_root=Path(__file__).resolve().parents[1] / "experiments")
    try:
        out = {}
        body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": "/gallery", "QUERY_STRING": "",
                                       "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("s", s))).decode()
        text = plain(body)
        for needle in ("Source freshness (populated", "Freshness report is stale", "Partial: a provider failed",
                       "Supervisor deferred: protected window", "no recent evaluation could be carried",
                       "has not written freshness.json", "Source freshness unavailable (read error)"):
            assert needle in text, needle
    finally:
        shutil.rmtree(root, ignore_errors=True)
