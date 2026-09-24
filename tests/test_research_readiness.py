"""Per-domain research-readiness report (#50, ADR 0033). Computed from real (test) stores only."""

from __future__ import annotations

import hashlib
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import cli
from edge_lab import research_readiness as rr
from edge_lab.fee_schedules import KALSHI_QUADRATIC_TAKER_V1 as FEES
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.storage import SnapshotStore

UTC = timezone.utc
T0 = datetime(2026, 9, 24, 21, 55, tzinfo=UTC)
NOW = T0 + timedelta(days=2)
ACC = "EXP-001-stage-b-shadow"  # the operational account the weather items describe
RES = "EXP-001-stage-b-research"
SPORT = "americanfootball_nfl"
Y, P, N, U, NA = (rr.Readiness.YES, rr.Readiness.PARTIAL, rr.Readiness.NOT_YET, rr.Readiness.UNKNOWN,
                  rr.Readiness.NOT_APPLICABLE)


def iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.fixture
def experiments(tmp_path):
    root = tmp_path / "experiments" / "EXP-001-x"
    root.mkdir(parents=True)
    (root / "experiment.toml").write_text('id = "EXP-001"\nstatus = "RUNNING"\n', encoding="utf-8")
    return root.parent


@pytest.fixture
def store(tmp_path):
    s = SnapshotStore(tmp_path / "evidence.sqlite3")
    s.start_run("run-1")
    return s


@pytest.fixture
def ledger(tmp_path):
    lg = ShadowLedger(tmp_path / "ledger.sqlite3")
    for account in (ACC, RES):
        lg.open_account(account, starting_bankroll=Decimal("100.00"), strategy="test",
                        opened_at_utc=iso(T0 - timedelta(days=1)), sizing_policy_id="s", fill_policy_id="f",
                        fee_schedule_id="kalshi-quadratic-taker-v1")
    return lg


def report(store=None, ledger=None, experiments=None, tmp_path=None):
    db = store.path if store is not None else (tmp_path / "absent.sqlite3")
    return rr.build_report(db, ledger.path if ledger is not None else None, now=NOW, experiments_root=experiments)


def states(domain: rr.DomainReadiness) -> dict[str, rr.Readiness]:
    return {p.key: p.state for p in (*domain.prerequisites, domain.research_ready)}


def by_domain(rep: rr.ReadinessReport) -> dict[str, rr.DomainReadiness]:
    return {d.domain: d for d in rep.domains}


# ------------------------------------------------------------------ fixtures in the stores' real shapes


def forward(store, phase: str, status: str = "complete", day: str = "2026-09-24") -> None:
    store.record_forward_capture(run_id="run-1", experiment="EXP-001", phase=phase, mode="live", target_date=day,
                                 event_ticker="KXHIGHNY-26SEP24", started_at_utc=iso(T0), completed_at_utc=iso(T0),
                                 window_start_utc=iso(T0), window_end_utc=iso(T0), status=status,
                                 reasons=[] if status == "complete" else ["x"], links={})


def snapshot(store, source: str, kind: str, payload: dict | None = None, *, url: str = "https://example.test/x",
             at: datetime = T0) -> int:
    return store.save_snapshot(run_id="run-1", source=source, kind=kind, entity_id="e", url=url,
                               payload=payload or {"x": 1}, fetched_at_utc=iso(at))


def decide(lg, n: int, *, qualification: str = "REJECT", market: str | None = None, model: bool = True,
           event: str = "weather:us-nyc-central-park:daily-max-temp-f:2026-09-24", account: str = ACC,
           day: str = "2026-09-24") -> None:
    lg.record_decision(account, {
        "decision_id": f"d{n}", "opportunity_id": f"o{n}", "as_of_utc": iso(T0), "qualification": qualification,
        "reason": "QUALIFY" if qualification == "QUALIFY" else "NO_EDGE", "event_id": event,
        "market_id": market or f"kalshi:KXHIGHNY-26SEP24-B{n}", "side": "YES", "outcome_cluster": event,
        "slot": f"{day}|kalshi:KXHIGHNY-26SEP24-B{n}|YES",
        "opportunity": {"model_probability": "0.42" if model else None}})


def fill_and_settle(lg, n: int, *, event: str = "weather:us-nyc-central-park:daily-max-temp-f:2026-09-24",
                    account: str = ACC, settle: bool = True) -> None:
    cost = FEES.taker_buy(1, Decimal("0.40"))
    market = f"kalshi:KXHIGHNY-26SEP24-B{n}"
    lg.record_fill(account, {"fill_id": f"f{n}", "decision_id": f"d{n}", "venue": "kalshi", "market_id": market,
                         "event_id": event, "outcome_cluster": event, "side": "YES", "filled_at_utc": iso(T0),
                         "status": "FILLED", "reason": "FILLED", "quantity": 1, "price": "0.40",
                         "fee": str(cost.fee), "total_cost": str(cost.total_cost)})
    if settle:
        lg.record_settlement(account, fill_id=f"f{n}", outcome="NO", evidence={"test": n},
                             settled_at_utc=iso(T0 + timedelta(hours=14)))


def later(store, market: str, phase: str = "pre_close", status: str = "CAPTURED") -> None:
    captured = status == "CAPTURED"
    store.record_price_observations([{
        "run_id": "run-1", "attempt_id": f"a-{market}-{phase}", "target_id": None, "phase": phase, "venue": "kalshi",
        "market_id": market, "native_market_id": market.split(":", 1)[1], "event_id": "kalshi:KXHIGHNY-26SEP24",
        "side": "YES", "observed_at_utc": iso(T0) if captured else None,
        "snapshot_id": snapshot(store, "kalshi", "observation_book") if captured else None,
        "close_label": "LATEST_PRE_CLOSE" if phase == "close" and captured else None,
        "miss_reason": None if captured else "missed", "freshness": "fresh", "collection_status": status,
        "recorded_at_utc": iso(T0), "policy_version": "v1"}])


def odds_event(eid: str, books=("draftkings", "fanduel")) -> dict:
    return {"id": eid, "sport_key": SPORT, "sport_title": "NFL", "commence_time": "2026-10-04T17:00:00Z",
            "home_team": "Home", "away_team": "Away", "bookmakers": [
                {"key": b, "last_update": "2026-10-04T15:59:00Z", "markets": [
                    {"key": "h2h", "outcomes": [{"name": "Home", "price": -150}, {"name": "Away", "price": 130}]}]}
                for b in books]}


def odds_snapshot(store, events: list[dict], at: datetime = T0) -> int:
    return snapshot(store, "the_odds_api", "odds", {"sport": SPORT, "events": events,
                                                     "request": {"odds_format": "american"}},
                    url="https://api.the-odds-api.com/v4/sports/x/odds/?apiKey=REDACTED&oddsFormat=american", at=at)


def target(store, tid: str, event: str, offset: str, when: datetime, state: str | None) -> None:
    store.plan_odds_target(target_id=tid, sport=SPORT, event_id=event, offset_label=offset, priority=1,
                           commence_time_utc="2026-10-04T17:00:00Z", target_utc=iso(when), planned_at_utc=iso(T0),
                           policy_version="p1")
    if state == "CAPTURED":
        store.record_odds_transition(target_id=tid, state=state, at_utc=iso(when), snapshot_id=1,
                                     captured_at_utc=iso(when))
    elif state is not None:
        store.record_odds_transition(target_id=tid, state=state, at_utc=iso(when), reason="test")


# ------------------------------------------------------------------ tests


def test_missing_stores_are_unknown_never_yes(tmp_path, experiments):
    rep = report(tmp_path=tmp_path, experiments=experiments)
    assert rep.evidence_store == "MISSING" and rep.shadow_ledger == "NOT_GIVEN"
    for domain in rep.domains:
        got = states(domain)
        assert Y not in got.values() and got["research_ready"] is U
    assert by_domain(rep)["weather"].lifecycle == "RUNNING"  # read from the registry file, not hard-coded
    assert states(by_domain(rep)["weather"])["consensus"] is NA
    assert by_domain(rep)["sports"].lifecycle == "UNKNOWN"


def test_unreadable_ledger_and_store_are_unknown(tmp_path, experiments):
    bad = tmp_path / "bad.sqlite3"
    bad.write_bytes(b"not a database at all" * 50)
    rep = rr.build_report(bad, bad, now=NOW, experiments_root=experiments)
    assert rep.evidence_store.startswith("UNREADABLE") and rep.shadow_ledger.startswith("UNREADABLE")
    assert all(p.state in (U, NA) for d in rep.domains for p in d.prerequisites)


def test_empty_stores_are_not_yet(store, ledger, experiments):
    rep = report(store, ledger, experiments)
    for domain in rep.domains:
        got = states(domain)
        assert Y not in got.values() and got["research_ready"] is N, domain.domain
        assert all(p.evidence_count in (0, None) for p in domain.prerequisites)
    assert by_domain(rep)["sports"].lifecycle == "NO_EVIDENCE_YET"


def test_weather_counts_come_from_the_stores(store, ledger, experiments):
    for phase in rr.FORWARD_PHASES:
        forward(store, phase)
    forward(store, "decision", status="partial", day="2026-09-23")
    snapshot(store, "kalshi", "orderbook")
    decide(ledger, 1, qualification="QUALIFY")
    decide(ledger, 2)
    decide(ledger, 3, model=False)
    fill_and_settle(ledger, 1)
    later(store, "kalshi:KXHIGHNY-26SEP24-B1")
    later(store, "kalshi:KXHIGHNY-26SEP24-B2", status="MISSED")
    later(store, "kalshi:KXHIGHNY-26SEP24-B3", phase="recheck")  # not a later phase
    w = by_domain(report(store, ledger, experiments))["weather"]
    got = {p.key: p for p in w.prerequisites}
    # 2026-09-23 had a live attempt (partial decision) and nothing complete: a gap, not ignored (SF-4)
    raw = got["raw_evidence"]
    assert raw.state is P and raw.reason.startswith("3 of 6") and dict(raw.counts)["not_complete_decision"] == 1
    assert dict(raw.counts)["capture_days"] == 2 and dict(raw.counts)["complete_days_pfm"] == 1
    assert got["market_quote_history"].state is P and got["market_quote_history"].reason.startswith("1 of 2")
    assert got["model_estimate"].state is P and got["model_estimate"].evidence_count == 2
    assert got["decisions"].state is Y and dict(got["decisions"].counts) == {
        "decisions": 3, "qualified": 1, "rejected": 2, "research_decisions": 0, "research_qualified": 0,
        "research_rejected": 0, "decision_capture_days": 1, "days_without_decision": 0}
    assert got["later_price"].state is P and got["later_price"].reason.startswith("1 of 3")
    assert dict(got["later_price"].counts)["later_missed_or_failed"] == 1 and got["later_price"].coverage_ref == "P0-1"
    assert got["settlement_linkage"].state is Y  # the one decided event was settled through a held position
    assert got["consensus"].state is NA
    assert w.research_ready.state is N and "model_estimate" in w.research_ready.reason
    assert w.research_ready.state is N and "raw_evidence" in w.research_ready.reason


def test_weather_rejected_only_events_are_not_linked_and_no_rejects_is_partial(store, ledger, experiments):
    decide(ledger, 1, qualification="QUALIFY")
    decide(ledger, 2, event="weather:us-nyc-central-park:daily-max-temp-f:2026-09-25")
    got = {p.key: p for p in by_domain(report(store, ledger, experiments))["weather"].prerequisites}
    assert got["settlement_linkage"].state is N  # nothing held, nothing settled: no linkage
    assert dict(got["settlement_linkage"].counts)["events_without_position"] == 2
    lg2 = ShadowLedger(Path(ledger.path).with_name("l2.sqlite3"))
    lg2.open_account(ACC, starting_bankroll=Decimal("100"), strategy="t", opened_at_utc=iso(T0 - timedelta(days=1)),
                     sizing_policy_id="s", fill_policy_id="f", fee_schedule_id="k")
    forward(store, "decision")
    decide(lg2, 1, qualification="QUALIFY", account=ACC)
    got = {p.key: p for p in by_domain(report(store, lg2, experiments))["weather"].prerequisites}
    assert got["decisions"].state is P  # no rejected decision: cannot show rejects are kept


def test_every_weather_prerequisite_yes_only_when_all_present(store, ledger, experiments):
    for phase in rr.FORWARD_PHASES:
        forward(store, phase)
    snapshot(store, "kalshi", "orderbook")
    decide(ledger, 1, qualification="QUALIFY")
    decide(ledger, 2)
    fill_and_settle(ledger, 1)
    later(store, "kalshi:KXHIGHNY-26SEP24-B1")
    later(store, "kalshi:KXHIGHNY-26SEP24-B2", phase="close")
    w = by_domain(report(store, ledger, experiments))["weather"]
    assert {k: s for k, s in states(w).items()} == {
        "raw_evidence": Y, "market_quote_history": Y, "model_estimate": Y, "decisions": Y, "later_price": Y,
        "consensus": NA, "settlement_linkage": Y, "research_ready": Y}
    # Remove one prerequisite (a new decided market with no later observation): never YES.
    decide(ledger, 3)
    w = by_domain(report(store, ledger, experiments))["weather"]
    assert states(w)["later_price"] is P and w.research_ready.state is N


def test_sports_from_odds_targets_consensus_and_polymarket(store, ledger, experiments):
    odds_snapshot(store, [odds_event("g1"), odds_event("g2", books=("draftkings",))])
    odds_snapshot(store, [])  # an empty read holds no offers
    snapshot(store, "the_odds_api", "events")
    start = datetime(2026, 10, 4, 17, tzinfo=UTC)
    target(store, "g1-24h", "g1", "24h", start - timedelta(hours=24), "CAPTURED")
    target(store, "g1-60m", "g1", "60m", start - timedelta(minutes=60), "CAPTURED")
    target(store, "g2-24h", "g2", "24h", start - timedelta(hours=24), "MISSED")
    target(store, "g2-60m", "g2", "60m", start - timedelta(minutes=60), None)  # still PLANNED: not due
    s = by_domain(report(store, ledger, experiments))["sports"]
    got = {p.key: p for p in s.prerequisites}
    # one of the two stored paid reads held no offers: PARTIAL, not YES (SF-4)
    assert got["raw_evidence"].state is P and dict(got["raw_evidence"].counts)["odds_snapshots"] == 2
    assert dict(got["raw_evidence"].counts)["odds_snapshots_with_offers"] == 1
    assert got["market_quote_history"].state is P and "Polymarket US" in got["market_quote_history"].reason
    assert "1 targets missed" in got["market_quote_history"].reason
    assert got["later_price"].state is Y and dict(got["later_price"].counts)["latest_target_final"] == 1
    assert got["consensus"].state is Y and dict(got["consensus"].counts)["supported_propositions"] == 1
    assert got["model_estimate"].state is N and got["decisions"].state is N
    assert got["settlement_linkage"].state is N and got["settlement_linkage"].coverage_ref == "P1-5"
    assert s.lifecycle == "DATA_COLLECTION" and s.research_ready.state is N
    snapshot(store, "polymarket_us", "book")
    got = {p.key: p for p in by_domain(report(store, ledger, experiments))["sports"].prerequisites}
    assert got["market_quote_history"].state is P  # still one missed target: never YES


def test_sports_single_book_snapshot_is_no_consensus(store, ledger, experiments):
    odds_snapshot(store, [odds_event("g1", books=("draftkings",))])
    got = {p.key: p for p in by_domain(report(store, ledger, experiments))["sports"].prerequisites}
    assert got["raw_evidence"].state is Y and got["consensus"].state is N


def test_sports_decisions_in_the_ledger_are_counted_and_never_mixed_with_weather(store, ledger, experiments):
    decide(ledger, 1, qualification="QUALIFY", event="the_odds_api:g1", market="the_odds_api:draftkings:g1:h2h:Home")
    rep = by_domain(report(store, ledger, experiments))
    assert {p.key: p for p in rep["sports"].prerequisites}["decisions"].state is P  # none rejected
    assert {p.key: p for p in rep["weather"].prerequisites}["decisions"].state is N


def test_report_is_read_only_and_the_cli_prints_json_and_text(store, ledger, experiments):
    for phase in rr.FORWARD_PHASES:
        forward(store, phase)
    odds_snapshot(store, [odds_event("g1")])
    before = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (store.path, ledger.path)]
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["readiness", "report", "--db", str(store.path), "--ledger", str(ledger.path),
                         "--experiments", str(experiments)])
    out = json.loads(buf.getvalue())
    assert code == 0 and out["schema"] == rr.SCHEMA and out["version"] == rr.READINESS_VERSION
    assert [d["domain"] for d in out["domains"]] == ["weather", "sports"]
    raw = out["domains"][0]["prerequisites"][0]
    assert raw["key"] == "raw_evidence" and raw["state"] == "YES" and raw["counts"]["complete_days_pfm"] == 1
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert rr.main(["--db", str(store.path), "--text", "--experiments", str(experiments)],
                       clock=lambda: NOW) == 0
    text = buf.getvalue()
    assert "WEATHER" in text and "SPORTS" in text and "UNKNOWN" in text  # no ledger given -> UNKNOWN rows
    after = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (store.path, ledger.path)]
    assert before == after


def test_nothing_is_hard_coded_green_and_the_lifecycle_is_the_registry_value():
    rep = rr.build_report(Path("does-not-exist.sqlite3"), None, now=NOW, experiments_root=None)
    assert all(p.state is not Y for d in rep.domains for p in (*d.prerequisites, d.research_ready))
    assert by_domain(rep)["weather"].lifecycle == "UNKNOWN"
    with pytest.raises(ValueError):
        rr.build_report(Path("x"), None, now=datetime(2026, 9, 24))
    import tomllib

    real = next(rr.REPO_EXPERIMENTS.glob("EXP-001*/experiment.toml"))
    expected = tomllib.loads(real.read_text(encoding="utf-8"))["status"]
    assert by_domain(rr.build_report(Path("x"), None, now=NOW))["weather"].lifecycle == expected


def test_a_recorded_model_unavailable_counts_but_a_silent_gap_does_not(store, ledger, experiments):
    decide(ledger, 1)
    ledger.record_decision(ACC, {"decision_id": "d2", "opportunity_id": "o2", "as_of_utc": iso(T0),
                                 "qualification": "REJECT", "reason": "MODEL_UNAVAILABLE",
                                 "reasons": ["MODEL_UNAVAILABLE"], "event_id": "weather:x", "market_id": "kalshi:M2",
                                 "opportunity": {"model_probability": None}})
    got = {p.key: p for p in by_domain(report(store, ledger, experiments))["weather"].prerequisites}
    assert got["model_estimate"].state is Y and dict(got["model_estimate"].counts)["model_unavailable_recorded"] == 1
    decide(ledger, 3, model=False)  # no probability and no recorded reason: a silent gap
    got = {p.key: p for p in by_domain(report(store, ledger, experiments))["weather"].prerequisites}
    assert got["model_estimate"].state is P


def test_a_read_with_a_parse_problem_still_counts_as_holding_offers(store, ledger, experiments):
    bad = odds_event("g1")
    bad["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = "abc"
    odds_snapshot(store, [bad])
    got = {p.key: p for p in by_domain(report(store, ledger, experiments))["sports"].prerequisites}
    assert got["raw_evidence"].state is Y and got["consensus"].state is N  # one clean book left: no consensus


def test_accounts_are_never_pooled_and_settlement_matches_within_the_account(store, ledger, experiments):
    forward(store, "decision")
    for account in (ACC, RES):  # the same opportunity is recorded in both accounts
        decide(ledger, 1, qualification="QUALIFY", account=account)
        decide(ledger, 2, account=account)
    fill_and_settle(ledger, 1, account=RES)  # only the research account holds and settles B1
    fill_and_settle(ledger, 1, account=ACC, settle=False)  # the operational account holds it, unsettled
    got = {p.key: p for p in by_domain(report(store, ledger, experiments))["weather"].prerequisites}
    counts = dict(got["decisions"].counts)
    assert counts["decisions"] == 2 and counts["research_decisions"] == 2  # not 4
    link = got["settlement_linkage"]
    assert link.state is N and dict(link.counts)["events_settled"] == 0  # the research settlement is not borrowed
    assert dict(link.counts)["events_with_filled_position"] == 1


def test_decisions_missing_for_a_capture_day_are_partial(store, ledger, experiments):
    forward(store, "decision")
    forward(store, "decision", day="2026-09-25")
    decide(ledger, 1, qualification="QUALIFY")
    decide(ledger, 2)
    got = {p.key: p for p in by_domain(report(store, ledger, experiments))["weather"].prerequisites}
    assert got["decisions"].state is P and "1 of 2 complete decision-capture days" in got["decisions"].reason
    no_store = {p.key: p for p in by_domain(rr.build_report(Path(store.path).with_name("none.sqlite3"),
                                                            ledger.path, now=NOW, experiments_root=experiments)
                                            )["weather"].prerequisites}
    assert no_store["decisions"].state is P and "capture days unknown" in no_store["decisions"].reason


def test_readiness_parses_a_bounded_sample_of_odds_reads(store, ledger, experiments, monkeypatch):
    from edge_lab import odds_consensus

    for i in range(rr.CONSENSUS_SAMPLE + 7):
        odds_snapshot(store, [odds_event(f"g{i}")], at=T0 + timedelta(minutes=i))
    calls = []
    real = odds_consensus.consensus_for_snapshot
    monkeypatch.setattr(odds_consensus, "consensus_for_snapshot",
                        lambda st, sid, **kw: calls.append(sid) or real(st, sid, **kw))
    got = {p.key: p for p in by_domain(report(store, ledger, experiments))["sports"].prerequisites}
    assert len(calls) == rr.CONSENSUS_SAMPLE and max(calls) == rr.CONSENSUS_SAMPLE + 7  # the newest ones only
    assert got["raw_evidence"].state is Y and dict(got["raw_evidence"].counts)["odds_snapshots_with_offers"] == rr.CONSENSUS_SAMPLE + 7
    assert got["consensus"].state is Y and f"the newest {rr.CONSENSUS_SAMPLE} of {rr.CONSENSUS_SAMPLE + 7}" in got["consensus"].reason
