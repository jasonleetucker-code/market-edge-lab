"""Operator journeys of Market v1 (docs/strategy/MARKET_V1_ACCEPTANCE.md §2), second set: J2 sources, J3 opportunities,
J7 research stages and J8 the outcome board's integration with the execution status export. Each journey renders
real, empty, stale, missing, error, blocked, paused and incomplete states, with no silent zero, no fake readiness
badge, no mock balance shown as real and nothing stale shown as current.

J2 extends Data sources (the Freshness Fabric rows and Collected sources); J3 extends the Markets board and market
detail; J7 adds "Research stages" to the Research tab; J8 adds "Execution positions by outcome" to the outcome board,
read from `execution_status.json` (ADR 0043: the dashboard imports nothing from the execution package).
"""

from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from edge_lab.dashboard import Config, make_app
from edge_lab.dashboard import data as d
from edge_lab.dashboard import presentation as pr
from edge_lab.dashboard.views import common as cm
from edge_lab.dashboard.views import markets, outcomes, research

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "browser"))

import fixture_states  # noqa: E402
import journey_fixtures as jf  # noqa: E402


def plain(body: str) -> str:
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", body)).split())


def get(cfg: Config, path: str, query: str = "") -> tuple[str, str]:
    out = {}
    body = b"".join(make_app(cfg)({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query,
                                   "HTTP_HOST": "127.0.0.1:8765"}, lambda s, h: out.setdefault("status", s)))
    return out["status"], body.decode("utf-8")


def main(body: str) -> str:
    return body[body.index('<main id="main"'):body.index('<footer class="foot">')]


def section(body: str, sid: str) -> str:
    part = body[body.index(f'aria-labelledby="{sid}"'):]
    return part[:part.index("</section>")]


def page_text(cfg: Config, path: str, query: str = "") -> str:
    status, body = get(cfg, path, query)
    assert status == "200 OK", (path, status)
    return plain(main(body))


def na_reasons(html: str) -> list[str]:
    return [html_lib.unescape(x) for x in re.findall(r'class="na" title="[^"]*" aria-label="([^"]*)"', html)]


# ================================================================ J2 sources (Data sources)


@pytest.fixture(scope="module")
def fresh_cfg():
    cfg, root = fixture_states.freshness()
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


def _fresh_doc(cfg: Config) -> dict:
    return json.loads((cfg.status_dir / d.FRESHNESS_FILE).read_text(encoding="utf-8"))


def _fresh_html(doc: dict, now, *, later: timedelta = timedelta(0)) -> str:
    return research.freshness_body(d.Loaded(d.OK, d.report_from_doc(doc, now + later)), now + later)


def _row_of(html: str, source_id: str) -> str:
    """One source's row inside "Every source by domain"."""
    every = html[html.index("Every source by domain"):]
    start = every.index(f">{source_id}<")
    return every[start:every.index("</li>", start)]


def test_j2_real_every_source_shows_the_eight_fields(fresh_cfg):
    doc = _fresh_doc(fresh_cfg)
    now = fresh_cfg.clock()
    html = _fresh_html(doc, now)
    for src in doc["sources"]:
        text = plain(_row_of(html, src["source_id"]))
        for label in ("Schedule", "Next due", "Last attempt", "Last successful receipt", "Freshness",
                      "Health · completeness",
                      "Latest failure", "Provenance", "Cost"):
            assert label in text, (src["source_id"], label)
        if src["last_attempt_utc"]:
            assert pr.datetime_et(src["last_attempt_utc"]) in text
    odds = plain(_row_of(html, "the_odds_api.nfl_odds"))
    assert "credit monthly ceiling" in odds and "policy " in odds  # the policy's own budget words and version
    discovery = plain(_row_of(html, "the_odds_api.discovery"))
    assert "Cost quota-free" in discovery


def test_j2_cost_never_reads_zero_when_not_recorded(fresh_cfg):
    doc = _fresh_doc(fresh_cfg)
    html = _fresh_html(doc, fresh_cfg.clock())
    row = _row_of(html, "exp001.forward.pfm")
    assert research.NO_COST in na_reasons(row)
    assert "$0" not in plain(row) and "Cost 0" not in plain(row)


def test_j2_collected_sources_show_provenance_and_unknown_cost():
    cfg, root = fixture_states.early()
    try:
        status, body = get(cfg, "/experiments", "tab=sources")
        assert status == "200 OK"
        part = section(body, "src-h")
        text = plain(part)
        assert "Provenance Official API · Active · no credential" in text and "Records 3" in text
        assert research.REGISTRY_NO_COST in na_reasons(part)
        assert "not scheduled in this record: see Source freshness" in na_reasons(part)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_j2_empty(fresh_cfg):
    doc = _fresh_doc(fresh_cfg)
    doc["sources"] = []
    assert "No sources in the report" in plain(_fresh_html(doc, fresh_cfg.clock()))


def test_j2_stale_report_is_never_current(fresh_cfg):
    doc = _fresh_doc(fresh_cfg)
    html = _fresh_html(doc, fresh_cfg.clock(), later=timedelta(hours=2))
    text = plain(html)
    assert "Freshness report is stale" in text and "Not decision-grade: report stale" in text
    assert "k-ok" not in html  # no positive verdict is green under a stale report


def test_j2_missing_and_error(tmp_path, fresh_cfg):
    now = fresh_cfg.clock()
    for cfg in (Config(clock=lambda: now), Config(status_dir=tmp_path, clock=lambda: now)):
        text = plain(section(get(cfg, "/experiments", "tab=sources")[1], "fresh-h"))
        assert "Source freshness unavailable" in text and "Last attempt" not in text
    (tmp_path / d.FRESHNESS_FILE).write_text("{not json", encoding="utf-8")
    text = plain(section(get(Config(status_dir=tmp_path, clock=lambda: now), "/experiments", "tab=sources")[1],
                         "fresh-h"))
    assert "read error" in text and "This is not a healthy or empty report" in text


def test_j2_blocked_and_paused(fresh_cfg):
    doc = _fresh_doc(fresh_cfg)
    odds = next(s for s in doc["sources"] if s["source_id"] == "the_odds_api.nfl_odds")
    odds["schedule_state"] = "BUDGET_BLOCKED"
    disc = next(s for s in doc["sources"] if s["source_id"] == "the_odds_api.discovery")
    disc["schedule_state"] = "PAUSED"
    html = _fresh_html(doc, fresh_cfg.clock())
    attention = plain(html[html.index("Needs attention"):html.index("Every source by domain")])
    assert "the_odds_api.nfl_odds" in attention and "Budget blocked" in attention
    assert "the_odds_api.discovery" in attention and "Paused" in attention


def test_j2_paused_supervisor_deferred():
    cfg, root = fixture_states.freshness_deferred()
    try:
        text = plain(section(get(cfg, "/experiments", "tab=sources")[1], "fresh-h"))
        assert "Supervisor deferred: protected window" in text and "Last attempt" in text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_j2_incomplete_partial_and_unknown(fresh_cfg):
    doc = _fresh_doc(fresh_cfg)
    src = next(s for s in doc["sources"] if s["source_id"] == "exp001.forward.decision")
    src.update(health="DEGRADED", why_due="partial capture: 2 of 7 books missing", recent_misses=[])
    unknown = next(s for s in doc["sources"] if s["source_id"] == "exp001.forward.recheck")
    unknown.update(health="UNKNOWN", recent_misses=[], last_attempt_utc=None)
    html = _fresh_html(doc, fresh_cfg.clock())
    row = plain(_row_of(html, "exp001.forward.decision"))
    # Completeness is the canonical health word, labelled as such; the schedule text is never a failure reason.
    assert "Health · completeness Degraded no separate completeness record" in row
    assert "Latest failure Reason not recorded health degraded; the report records no failure reason" in row
    assert "Latest failure partial capture" not in row
    raw = _row_of(html, "exp001.forward.recheck")
    reasons = na_reasons(raw)
    assert "no attempt recorded" in reasons and "not recorded in the report" in reasons
    assert "Health · completeness Health unknown" in plain(raw)
    assert "None recorded at evaluation" not in plain(raw)  # unknown health is never "no failure"


def test_j2_failure_texts():
    # freshness_fabric writes recent_misses oldest first: the latest failure is the last one.
    assert "None recorded" in research.source_failure({"health": "OK", "recent_misses": []})
    newest = plain(research.source_failure({"health": "OK", "recent_misses": ["2026-09-20: old", "2026-09-23: new"]}))
    assert newest.startswith("2026-09-23: new") and "2026-09-20" not in newest
    assert "newest of 2 recent misses" in newest
    failing = plain(research.source_failure({"health": "FAILING", "why_due": "next at the 18:00 tick"}))
    assert failing.startswith("Reason not recorded") and "18:00 tick" not in failing
    assert 'aria-label="not recorded in the report"' in research.source_failure({})
    assert "report not current" in plain(research.source_failure({"health": "OK", "recent_misses": []}, False))
    assert "report not current" in plain(research.source_failure({"health": "OK", "recent_misses": ["m"]}, False))


def test_j2_untrusted_report_qualifies_failure_and_health(fresh_cfg):
    doc = _fresh_doc(fresh_cfg)
    html = _fresh_html(doc, fresh_cfg.clock(), later=timedelta(hours=2))
    healthy = [s["source_id"] for s in doc["sources"] if s["health"] == "OK" and not s["recent_misses"]]
    assert healthy
    row = plain(_row_of(html, healthy[0]))
    assert "None recorded at evaluation report not current" in row


# ================================================================ J3 opportunities (Markets and market detail)


@pytest.fixture(scope="module")
def demo_cfg():
    cfg, root = fixture_states.demo()
    yield cfg
    shutil.rmtree(root, ignore_errors=True)


def test_j3_real_detail_shows_fee_size_and_case(demo_cfg):
    text = page_text(demo_cfg, "/market", "venue=kalshi&id=DEMO-B71.5&side=YES")
    assert "Fee / contract 1.28¢" in text and "Evaluated size 1" in text
    assert "Rejection reasons None: qualified at decision time" in text
    # The demo's policy is not a registered experiment's rule: no other experiment's mechanism is borrowed.
    status, body = get(demo_cfg, "/market", "venue=kalshi&id=DEMO-B71.5&side=YES")
    assert "the decision's policy demo is not linked to a registered experiment" in na_reasons(section(body, "as-h"))
    assert "Retail-heavy weather markets" not in text


def test_j3_fee_is_per_contract_only_for_quantity_one(demo_cfg):
    ctx = d.Context(demo_cfg)
    row = next(r for r in cm.board_rows(ctx, pr.Params()) if r.native_id == "DEMO-B71.5")
    a = row.for_side("YES")
    assert plain(markets.fee_per_contract(a)) == "1.28¢"
    for quantity, why in ((3, "(3), not one contract"), (None, "(not recorded)"), ("2", "(2), not one contract")):
        opp = {**a.raw["opportunity"], "quantity": quantity}
        if quantity is None:
            opp.pop("quantity")
        html = markets.fee_per_contract(replace(a, raw={**a.raw, "opportunity": opp}))
        assert na_reasons(html) == [f"the recorded fee covers the decision's quantity {why}"], quantity
    assert na_reasons(markets.fee_per_contract(replace(a, fee=None))) == ["fee not recorded with the decision"]


def test_j3_mechanism_and_evidence_come_from_the_registry():
    from edge_lab import exp001_stageb

    ctx = d.Context(Config(experiments_root=REPO / "experiments"))
    exp, why = d.experiment_for_policy(ctx, exp001_stageb.STAGE_B_POLICY.policy_id)
    assert exp["id"] == "EXP-001" and why == ""
    a = SimpleNamespace(reasons=(), reason="QUALIFY", qualification="QUALIFY")
    html = markets.case_block(a, exp, why)
    text = plain(html)
    assert "Retail-heavy weather markets" in text and "economic rationale (legacy manifest) · EXP-001 · unproven" in text
    assert "a historical validation is not an edge" in text
    assert "k-ok" not in html  # a research stage or a historical pass never reads as readiness here
    for exp_id, phrase in (("EXP-002", "Sportsbook lines aggregate"), ("EXP-003", "Related contracts on one venue")):
        entry = next(e for e in ctx.experiments.value if e["id"] == exp_id)
        assert entry["mechanism"].startswith(phrase) and entry["mechanism_basis"] == "protocol mechanism"


def test_j3_blocked_rejection_reasons_are_listed(demo_cfg):
    text = page_text(demo_cfg, "/market", "venue=kalshi&id=DEMO-NFL-KCBUF")
    assert "Rejection reasons No model for this market (MODEL_UNAVAILABLE)" in text
    assert "Evaluated size —" in text  # a rejected decision has no size: unknown, never 0
    a = SimpleNamespace(reasons=("EDGE_BELOW_THRESHOLD", "BOOK_STALE"), reason="EDGE_BELOW_THRESHOLD",
                        qualification="REJECT")
    text = plain(markets.case_block(a, None, "no link"))
    assert "(EDGE_BELOW_THRESHOLD)" in text and "Stale quote — not actionable (BOOK_STALE)" in text
    none = markets.case_block(SimpleNamespace(reasons=(), reason=None, qualification="REJECT"), None, "x")
    assert "no reason recorded with the decision" in na_reasons(none)


def test_j3_missing_side_and_registry(demo_cfg):
    text = page_text(demo_cfg, "/market", "venue=kalshi&id=DEMO-B69.5&side=YES")
    assert "Not evaluated yet" in text and "Decisions for earlier target days (1)" in text  # stale: earlier day only
    assert "Fee / contract" not in text
    ctx = d.Context(Config())
    from edge_lab import exp001_stageb

    exp, why = d.experiment_for_policy(ctx, exp001_stageb.STAGE_B_POLICY.policy_id)
    assert exp is None and why.startswith("experiment registry not readable")
    assert d.experiment_for_policy(ctx, None) == (None, "the decision records no policy")


def test_j3_empty_and_error():
    cfg, root = fixture_states.early()
    try:
        assert "Waiting for first capture" in page_text(cfg, "/opportunities")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    cfg, root = fixture_states.broken()
    try:
        text = page_text(cfg, "/opportunities")
        assert "Market data unavailable" in text and "No matches" not in text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_j3_stale_quote_is_not_actionable(demo_cfg):
    later = replace(demo_cfg, clock=lambda: demo_cfg.clock() + timedelta(days=2))
    text = page_text(later, "/market", "venue=kalshi&id=DEMO-B71.5&side=YES")
    assert "Stale quote — not actionable" in text


def _view_with_risk(monkeypatch, loaded):
    view = d.AccountView(d.OPERATIONAL_ACCOUNT_ID, None, d.OK, risk=loaded)
    monkeypatch.setattr(cm, "account_view", lambda ctx, p: view)


def test_j3_paused_when_new_risk_is_halted(monkeypatch):
    p = pr.Params()
    _view_with_risk(monkeypatch, d.Loaded(d.OK, SimpleNamespace(breaches=[], new_risk_allowed=False)))
    text = plain(markets.halted_line(None, p))
    assert "New positions halted · paused" in text and "remaining risk capacity is zero" in text
    _view_with_risk(monkeypatch, d.Loaded(d.OK, SimpleNamespace(breaches=["MAX_DRAWDOWN"], new_risk_allowed=False)))
    assert "MAX_DRAWDOWN" in plain(markets.halted_line(None, p))
    _view_with_risk(monkeypatch, d.Loaded(d.ERROR, message="ValueError: bad"))
    assert "Risk capacity unavailable (read error)" in plain(markets.halted_line(None, p))
    _view_with_risk(monkeypatch, d.Loaded(d.OK, SimpleNamespace(breaches=[], new_risk_allowed=True)))
    assert markets.halted_line(None, p) == ""
    _view_with_risk(monkeypatch, d.Loaded(d.NO_DATA, message="no policy"))
    assert markets.halted_line(None, p) == ""


def test_j3_incomplete_capture_and_unknown_fee(demo_cfg):
    ctx = d.Context(demo_cfg)
    rows = cm.board_rows(ctx, pr.Params())
    row = next(r for r in rows if r.native_id == "DEMO-B71.5")
    a = replace(row.for_side("YES"), fee=None, size=None)
    html = markets.assessment_section(replace(row, assessments=(a,)), "YES", ctx)
    reasons = na_reasons(html)
    assert "fee not recorded with the decision" in reasons and "size not evaluated" in reasons
    q = replace(row.quotes["YES"], phase="decision", capture_status="partial")
    assert "Capture incomplete" in plain(markets.quote_freshness(q, ctx.now))


# ================================================================ J7 research stages (Research tab)


def _stages_text(cfg: Config) -> tuple[str, str]:
    status, body = get(cfg, "/experiments")
    assert status == "200 OK"
    part = section(body, "stg-h")
    return part, plain(part)


def test_j7_real_stages_from_the_registry():
    cfg, root = fixture_states.early()
    try:
        html, text = _stages_text(cfg)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    for title in ("Candidate", "Development", "Shadow", "Qualified", "Rejected"):
        assert title in text
    assert "Shadow · 1" in text and "EXP-001" in text and "Registry status Running" in text
    assert "Development · 2" in text and "Active family slot" in text
    assert "No strategy is qualified" in text and "STRATEGY_QUALIFIED is NONE" in text
    assert "Rejected · 0" in text
    assert "k-ok" not in html  # nothing is green: a stage is not a result


def test_j7_protected_evidence_stays_protected(monkeypatch):
    """The stages read protocol configuration only: no outcome source is touched (the Context properties, the data
    loaders and the evidence modules' views all record any call, even one a caller would swallow) and no result is
    shown."""
    from edge_lab import payoff_constraints, sports_evidence

    reads: list[str] = []

    def recorder(name):
        def read(*args, **kwargs):
            reads.append(name)
            raise AssertionError(f"J7 must not read protected evidence ({name})")
        return read
    monkeypatch.setattr(d.Context, "economic_a", property(recorder("Context.economic_a")))
    monkeypatch.setattr(d.Context, "economic_b", property(recorder("Context.economic_b")))
    monkeypatch.setattr(d, "economic_evidence_a", recorder("data.economic_evidence_a"))
    monkeypatch.setattr(d, "economic_evidence_b", recorder("data.economic_evidence_b"))
    monkeypatch.setattr(sports_evidence, "terminal_view", recorder("sports_evidence.terminal_view"))
    monkeypatch.setattr(payoff_constraints, "verify_result_provenance", recorder("payoff_constraints.verify"))
    ctx = d.Context(Config(experiments_root=REPO / "experiments"))
    try:
        text = plain(research.stages_body(ctx))
    finally:
        assert reads == [], reads
    exp002 = text[text.index("EXP-002"):text.index("EXP-003")]
    assert "Outcome labels hidden on this Terminal (holdout protection" in exp002
    assert "May never view the outcome labels of" in text[text.index("EXP-003"):]
    for word in ("resolved", "won", "lost", "settled YES", "result count"):
        assert word not in text


def test_j7_empty_missing_error(tmp_path, monkeypatch):
    empty = tmp_path / "experiments"
    empty.mkdir()
    assert "No experiment registered" in plain(research.stages_body(d.Context(Config(experiments_root=empty))))
    assert "NO DATA / NOT STARTED" in plain(research.stages_body(d.Context(Config())))
    from edge_lab import experiments as registry

    def boom(root):
        raise ValueError("registry broken")
    monkeypatch.setattr(registry, "validate_all", boom)
    text = plain(research.stages_body(d.Context(Config(experiments_root=REPO / "experiments"))))
    assert "Data unavailable" in text and "registry broken" in text


def test_j7_stale_forward_days_are_never_current():
    cfg, root = fixture_states.early()
    try:
        later = replace(cfg, clock=lambda: cfg.clock() + timedelta(days=3))
        html, text = _stages_text(later)
        assert "stale, not current" in text
        full = page_text(later, "/experiments")
        assert full.count("stale, not current") >= 3  # the stage row, the card fact and the progress line
        _, now_text = _stages_text(cfg)
        assert "stale, not current" not in now_text
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _fake(**kw) -> dict:
    base = {"key": "EXP-9/experiment.toml", "id": "EXP-9", "title": "fake", "status": "DRAFT", "problems": [],
            "protocol": "PRESENT", "slot_status": "ACTIVE", "family": "Z", "protected_scopes": (),
            "holdout_windows": [], "protocol_error": None, "stage_a": None}
    return {**base, **kw}


def _stage_html(entries: list[dict]) -> str:
    ctx = SimpleNamespace(experiments=d.Loaded(d.OK, entries))
    return research.stages_body(ctx)


def test_j7_blocked_paused_rejected_and_incomplete():
    html = _stage_html([
        _fake(id="EXP-91", title="queued", slot_status="QUEUED"),
        _fake(id="EXP-92", title="failed", status="CONCLUDED_FAIL"),
        _fake(id="EXP-93", title="abandoned", status="ABANDONED"),
        _fake(id="EXP-94", title="passed", status="CONCLUDED_PASS"),
        _fake(id="EXP-95", title="odd", status="WEIRD"),
        _fake(id="EXP-96", title="broken", problems=["bad field"], protocol="MISSING", slot_status=None),
        _fake(id="EXP-97", title="unreadable", protocol_error="TOMLDecodeError: x", holdout_windows=None),
        _fake(id="EXP-98", title="frozen", status="PREREGISTERED", holdout_windows=[("s", "a", "b")]),
        {"key": "EXP-99-bad/experiment.toml", "id": None, "title": None, "status": None, "problems": ["TOMLDecodeError"],
         "stage_a": None, "reports": [], "manifest_error": True},
    ])
    text = plain(html)
    candidate = text[text.index("Candidate ·"):text.index("Development ·")]
    assert "queued" in candidate and "Queued · waiting for a family slot" in candidate  # paused / blocked
    assert "broken" in candidate and "1 manifest problem(s)" in candidate  # incomplete
    rejected = text[text.index("Rejected ·"):]
    assert "Rejected · 2" in text and "Concluded · fail" in rejected and "Abandoned" in rejected
    assert "Concluded · not a qualification · 1" in text and "No strategy is qualified" in text
    assert "Status unrecognized · 2" in text and "Registry status Weird" in text  # the unreadable manifest too
    assert "Registry status Concluded · pass" in text  # the canonical word, shown neutral (never green)
    assert "Protocol unreadable · treated as protected" in text
    assert "1 holdout window(s) declared, never shown" in text
    bad = text[text.index("Unreadable manifest"):]
    assert bad.startswith("Unreadable manifest EXP-99-bad/experiment.toml")  # title and subtitle differ
    assert "Manifest unreadable · treated as protected" in bad[:400]
    assert "settled in prose" not in bad[:400]
    assert "k-ok" not in html


def test_j7_a_changed_qualification_track_is_shown_as_recorded(monkeypatch):
    from edge_lab.dashboard.views import ops_manifest

    tracks = tuple((n, "EXP-9 strategy", q) if n == "STRATEGY_QUALIFIED" else (n, s, q)
                   for n, s, q in ops_manifest.TRACKS)
    monkeypatch.setattr(ops_manifest, "TRACKS", tracks)
    html = _stage_html([_fake()])
    text = plain(html)
    assert "STRATEGY_QUALIFIED is EXP-9 strategy" in text and "No strategy is qualified" not in text
    assert "k-ok" not in html


# ================================================================ J8 outcome board integration (execution export)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("journeys2")
    return {s: jf.build(s, root / s) for s in jf.SCENARIOS}


def cfg_for(built, scenario: str, *, later: timedelta = timedelta(minutes=1)) -> Config:
    path, at = built[scenario]
    return Config(status_dir=path.parent, clock=lambda: at + later)


def doc_of(built, scenario: str) -> dict:
    return json.loads(built[scenario][0].read_text(encoding="utf-8"))


def with_doc(tmp_path: Path, doc: dict | None = None, raw: str | None = None) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / d.EXECUTION_STATUS_FILE).write_text(raw if raw is not None else json.dumps(doc), encoding="utf-8")
    return tmp_path


def _board(cfg: Config) -> tuple[str, str]:
    status, body = get(cfg, "/outcome-board")
    assert status == "200 OK"
    part = section(body, "oc-x")
    return part, plain(part)


def test_j8_real_groups_fixture_positions_by_event(built):
    html, text = _board(cfg_for(built, "populated"))
    # The actual-holdings state is the execution portfolio's own, with the code's environments from the export.
    assert "Actual positions Access not connected" in text
    assert "Authorized environments in code (from the export): FIXTURE" in text
    assert "FIXTURE · fake venue · not a real account" in text and "Reconciled at export" in text
    assert "KXHIGHNY-26OCT08 FIXTURE venue · not a real position · 3 market(s) Partly settled" in text
    assert "KXHIGHNY-26OCT08-B74 — — yes $2.00 $0.00 +$1.12" in text  # settled: result, revenue, venue P&L
    assert "KXHIGHNY-26OCT08-B72 YES 4" in text  # held now
    assert "KXHIGHNY-26OCT08-B70 — — — — — −$0.06" in text  # exited before settlement: its P&L still belongs
    assert outcomes.EXEC_NO_BOUND in na_reasons(html) and outcomes.EXEC_NO_SETTLE_TIME in na_reasons(html)
    assert 'class="num pos"' not in html and 'class="num neg"' not in html and "k-ok" not in html


def test_j8_the_shadow_board_still_renders_beside_it(built):
    text = page_text(cfg_for(built, "populated"), "/outcome-board")
    assert "Linked outcomes" in text and "Execution positions by outcome" in text


def test_j8_empty(built):
    text = _board(cfg_for(built, "idle"))[1]
    assert "No FIXTURE positions or settlements" in text and "Partly settled" not in text


def test_j8_missing_export(tmp_path, built):
    now = built["idle"][1]
    for cfg in (Config(clock=lambda: now), Config(status_dir=tmp_path, clock=lambda: now)):
        text = _board(cfg)[1]
        assert "No execution export" in text and "This is not an empty portfolio" in text
        assert "Actual positions Access not connected" in text and "No FIXTURE positions" not in text
        assert "EXECUTION_PLAN records FIXTURE only" in text


def test_j8_error_and_blocked(tmp_path, built):
    now = built["populated"][1]
    text = _board(Config(status_dir=with_doc(tmp_path / "bad", raw="{not json"), clock=lambda: now))[1]
    assert "Execution export unavailable" in text and "KXHIGHNY" not in text
    doc = doc_of(built, "populated")
    doc["environment"] = "PRODUCTION"
    text = _board(Config(status_dir=with_doc(tmp_path / "prod", doc), clock=lambda: now))[1]
    assert "Export refused: environment not shown here" in text and "KXHIGHNY" not in text
    doc = doc_of(built, "populated")
    doc["journal"] = {"state": "ERROR", "detail": "JournalCorrupt: seq 4"}
    for key in ("control", "account", "attempts"):
        doc.pop(key)
    text = _board(Config(status_dir=with_doc(tmp_path / "je", doc), clock=lambda: now))[1]
    assert "Execution journal unreadable" in text and "KXHIGHNY" not in text


def test_j8_stale_export_is_never_current(built):
    text = _board(cfg_for(built, "populated", later=timedelta(hours=2)))[1]
    assert "Stale export — not current" in text and "every figure below is as of then, not now" in text
    assert "Execution export · FIXTURE" not in text


def test_j8_paused_and_incomplete(tmp_path, built):
    text = _board(cfg_for(built, "paused"))[1]
    assert "Paused · no new risk" in text and "Reconciliation incomplete — holdings may be wrong" in text
    # The failed read left no position list: what is held is unknown, never 0 held and never "Settled".
    assert "Open holdings unknown" in text and "Holdings unknown Positions held —" in text
    assert "Positions held 0" not in text and "Settled Positions" not in text
    doc = doc_of(built, "populated")
    doc["account"].update(snapshot=None, positions=None)
    doc["pnl"].update(baseline_recorded=False, realized_total=None)
    html, text = _board(Config(status_dir=with_doc(tmp_path / "nosnap", doc), clock=lambda: built["populated"][1]))
    assert "Open holdings unknown" in text and "No account snapshot yet — holdings unknown" in text
    assert "P&L baseline not recorded yet: unknown, not zero" in na_reasons(html)
    assert "+$1.12" not in text
    doc["settlements"]["rows"] = []
    doc["pnl"]["by_market"] = []
    text = _board(Config(status_dir=with_doc(tmp_path / "none", doc), clock=lambda: built["populated"][1]))[1]
    assert "Holdings unknown" in text and "No FIXTURE positions" not in text


def test_j8_overdue_shadow_groups_are_named():
    assert outcomes.HORIZON_LABELS["overdue"].startswith("Overdue")


def test_j8_untrusted_text_is_escaped(tmp_path, built):
    doc = doc_of(built, "populated")
    doc["settlements"]["rows"][0]["market_result"] = "<script>x</script>"
    _, body = get(Config(status_dir=with_doc(tmp_path, doc), clock=lambda: built["populated"][1]), "/outcome-board")
    assert "<script>x" not in body and "&lt;script&gt;" in body


# ================================================================ every changed page: read-only, both modes


@pytest.mark.parametrize("path,query", [("/experiments", ""), ("/experiments", "tab=sources"), ("/outcome-board", ""),
                                        ("/market", "venue=kalshi&id=DEMO-B71.5&side=YES")])
@pytest.mark.parametrize("demo", [False, True])
def test_changed_pages_have_no_control(demo_cfg, built, path, query, demo):
    cfg = demo_cfg if demo else cfg_for(built, "populated")
    status, body = get(cfg, path, query)
    assert status == ("404 Not Found" if path == "/market" and not demo else "200 OK")
    for tag in ("<form", "<button", "<input", "<select", "<textarea"):
        assert tag not in main(body), (path, tag)
    assert "SHADOW · NO REAL MONEY" in body and ("SYNTHETIC UI DEMO" in body) == demo
