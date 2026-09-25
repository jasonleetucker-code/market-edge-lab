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
    """Visible text: tags removed and entities decoded (an owner text may carry an apostrophe)."""
    import html as html_lib

    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", html)).split())


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
    assert f"{n} of {n} sources listed are external schedules the fabric only supervises" in text
    assert "network: none" in text and "controls schedules: no" in text
    summary = doc["summary"]
    assert f"Fresh at evaluation {len(summary['fresh'])} of {summary['sources']}" in text
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
            assert f"data {pr.duration_text(src['data_age_s'])} old then" in text
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
    assert "Partial: a provider failed" in text and "RuntimeError: SYNTHETIC provider failure" in text
    doc = dict(populated.value.doc)
    doc["sources"] = [{**doc["sources"][0], "schedule_state": "SOMETHING_NEW", "health": "ODD", "freshness": "WEIRD"}]
    html = research.freshness_body(d.Loaded(d.OK, d.FreshnessReport(doc, "FRESH", ff.SUPERVISOR_MAX_AGE)), NOW)
    for code in ("SOMETHING_NEW", "ODD", "WEIRD"):
        assert f'title="code: {code}"' in html, code


def test_missed_and_disagreements_are_visible():
    text = plain(research.freshness_body(fixtures.synthetic_freshness()["populated"], NOW))
    assert "Missed 1" in text and "Disagreements 1 with the canonical scheduler" in text
    assert "Usable for Research and decision, at evaluation" in text
    assert "SYNTHETIC: the timer tick falls outside" in text


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
                       "Not decision-grade: report stale",
                       "Supervisor deferred: protected window", "no recent evaluation could be carried",
                       "has not written freshness.json", "Source freshness unavailable (read error)"):
            assert needle in text, needle
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _section_under(current: Config, now: datetime, doc_edit=None) -> str:
    if doc_edit is not None:
        path = current.status_dir / d.FRESHNESS_FILE
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc_edit(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")
    return section(page(replace(current, clock=lambda: now)))


@pytest.mark.parametrize("why", ["stale", "undated"])
def test_a_stale_or_undated_report_never_reads_as_current(current, why):
    """Review BLOCKER 1: under a report that is not fresh, nothing is green and nothing is decision-usable."""
    generated = datetime.fromisoformat(_artifact(current)["generated_at_utc"].replace("Z", "+00:00"))
    if why == "stale":
        assert "k-ok" in _section_under(current, generated)  # the same report, fresh, may show its verdicts
        html = _section_under(current, generated + timedelta(hours=2))
        assert "Freshness report is stale" in plain(html) and "Not decision-grade: report stale" in plain(html)
    else:
        html = _section_under(current, generated, lambda doc: doc.pop("generated_at_utc"))
        assert "Freshness report time unknown" in plain(html)
        assert "Not decision-grade: report time unknown" in plain(html)
    assert "k-ok" not in html and "Research and decision" not in plain(html)


def test_verdicts_are_labelled_at_evaluation(current):
    """Review SF-2: a fresh report still says when each verdict was made, never implying now."""
    doc = _artifact(current)
    text = plain(section(page(current)))
    at = pr.datetime_et(doc["sources"][0]["as_of_utc"])
    assert f"at evaluation, {at}" in text and "Fresh at evaluation" in text and "Due next (at evaluation)" in text


@pytest.mark.parametrize("edit", [
    lambda doc: doc["summary"].update(due_now="x", missed=5, blocked=None, fresh={"a": 1}),
    lambda doc: doc["summary"].update(next_due=[{"source_id": ["a"], "next_due_utc": 7}]),
    lambda doc: doc.update(summary=[1, 2]),
    lambda doc: doc["sources"][0].update(source_id=["a", "b"], disagreements="one text", notes="note",
                                         recent_misses=3, details=[1], data_age_s="x", mode=["EXTERNAL"]),
    lambda doc: doc["policies"][0].update(source_id=["list"], protected_windows="17:40-18:35"),
    lambda doc: doc["supervisor"].update(problems="one problem", providers="x", state=["weird"]),
])
def test_malformed_values_never_break_the_page(current, edit):
    """Review SF-3: odd JSON types render as unknown or error, never a 500 of the Data sources tab."""
    path = current.status_dir / d.FRESHNESS_FILE
    doc = json.loads(path.read_text(encoding="utf-8"))
    edit(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")
    body = page(current)  # asserts 200
    html = section(body)
    assert 'aria-labelledby="odds-h"' in body  # the rest of the tab still renders
    assert "<li>o</li><li>n</li>" not in html  # a string is never listed character by character


def test_a_malformed_report_that_breaks_the_view_is_an_error_state(current, monkeypatch):
    monkeypatch.setattr(research, "_freshness_view", lambda report, now: 1 / 0)
    body = page(current)
    html = section(body)
    assert "Source freshness unavailable (malformed report)" in plain(html) and 'role="alert"' in html
    assert 'aria-labelledby="ven-h"' in body


def test_texts_are_scrubbed_and_listed_whole(current):
    path = current.status_dir / d.FRESHNESS_FILE
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["sources"][0].update(notes=["read /etc/market-edge-lab/secret.env failed"], disagreements="just one")
    doc["supervisor"].update(state="PARTIAL", problems="provider x: /var/lib/secret/file missing")
    path.write_text(json.dumps(doc), encoding="utf-8")
    text = plain(section(page(current)))
    assert "/etc/market-edge-lab" not in text and "/var/lib/secret" not in text
    assert "<path>" in text and "America/New_York" in text  # the fabric's scrub keeps time zones intact
    assert "just one" in text and "Disagreements 1 with the canonical scheduler" in text


def test_unknown_namespaced_codes_are_neutral_and_a_missing_state_is_said():
    assert pr.prefixed_word("SCHEDULE", "OK").kind == pr.ND_K  # never the global green OK
    assert pr.prefixed_word("HEALTH", "FRESH").kind == pr.ND_K
    assert pr.prefixed_word("HEALTH", None).label == "Not recorded"
    report = fixtures.synthetic_freshness()["populated"].value
    doc = {**report.doc, "supervisor": {k: v for k, v in report.doc["supervisor"].items() if k != "state"}}
    text = plain(research.freshness_body(d.Loaded(d.OK, d.FreshnessReport(doc, "FRESH", report.max_age)), NOW))
    assert "Supervisor state not recorded" in text


def test_an_oversized_artifact_is_not_the_supervisors(current):
    path = current.status_dir / d.FRESHNESS_FILE
    path.write_text(json.dumps({"schema": ff.SCHEMA, "pad": "x" * (ff.MAX_ARTIFACT_BYTES + 1)}), encoding="utf-8")
    result = d.Context(current).freshness_status
    assert result.status == d.ERROR and "bound" in result.message


def test_a_trimmed_report_says_what_it_counts_and_lists(current):
    path = current.status_dir / d.FRESHNESS_FILE
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["sources"] = doc["sources"][:5]
    path.write_text(json.dumps(doc), encoding="utf-8")
    text = plain(section(page(current)))
    assert f"The report counts {doc['summary']['sources']} sources and lists 5." in text


def test_due_next_without_a_reason_shows_a_dash(current):
    path = current.status_dir / d.FRESHNESS_FILE
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["summary"]["next_due"] = [{"source_id": "x.y", "next_due_utc": "2026-09-24T21:45:00Z"}]
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert "x.y: —" in plain(section(page(current)))


def test_gallery_fixtures_come_from_the_supervisor():
    """Review SF-4: the SYNTHETIC source is counted by the fabric's own summary; the stale report is backdated."""
    fx = fixtures.synthetic_freshness()
    doc = fx["populated"].value.doc
    assert "synthetic.demo_source" in doc["summary"]["fresh"] and "synthetic.demo_source" in doc["summary"]["missed"]
    assert doc["summary"]["sources"] == len(doc["sources"]) and doc["summary"]["disagreements"] >= 1
    assert fx["stale"].value.report_freshness == "STALE"
    carried = fx["deferred_carried"].value.doc
    assert carried["sources_evaluated_at_utc"] and all(s.get("carried_from_utc") for s in carried["sources"])
