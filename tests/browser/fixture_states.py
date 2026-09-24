"""Fixture states for browser and screenshot tests (UI_CONTRACT.md §23). Never production data.

Each builder writes into a fresh temporary directory through the real ledger, evidence-store
and status-file shapes, and returns a dashboard Config with a fixed clock:

- early: the production-shaped early state from the owner's screenshots (a fresh status report,
  an INVALID last capture, no decisions, both shadow accounts opened with no activity);
- demo: the synthetic populated demo (`edge_lab.dashboard.demo.build_demo`), watermarked;
- broken: malformed and unreadable sources (corrupt JSON, a non-SQLite ledger and evidence DB);
- odds: The Odds API pilot as production held it on 2026-09-24 (95 targets, one captured);
- odds_issues: the same with a missed, a failed, a budget-skipped and an overdue target and an
  exhausted quota.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from edge_lab import exp001_shadow as shadow
from edge_lab.dashboard import Config
from edge_lab.dashboard.demo import build_demo
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.storage import SnapshotStore

REPO = Path(__file__).resolve().parents[2]
# 2026-09-23 14:40 EDT: the moment of the owner's before-state screenshots.
EARLY_NOW = datetime(2026, 9, 23, 18, 40, tzinfo=timezone.utc)


def early(root: Path | None = None) -> tuple[Config, Path]:
    root = root or Path(tempfile.mkdtemp(prefix="edge-ui-early-"))
    status = root / "status"
    status.mkdir(parents=True, exist_ok=True)
    (status / "latest.json").write_text(json.dumps({
        "generated_at_utc": "2026-09-23T18:28:53.790755+00:00", "last_closed_target_date": "2026-09-23",
        "last_closed_status": "INVALID",
        "last_closed_reasons": ["forecast: no complete pfm capture (a newer issuance may be missing)",
                                "forecast: NO_PFM_BEFORE_CUTOFF", "no complete decision capture"],
        "valid_days": 0, "first_valid_day": None, "days_with_captures": 1, "invalid_days": ["2026-09-23"]}),
        encoding="utf-8")
    ledger = ShadowLedger(root / "shadow_ledger.sqlite3")
    for account in (shadow.RESEARCH, shadow.OPERATIONAL):
        shadow.ensure_account(ledger, account)
    store = SnapshotStore(root / "edge_lab.sqlite3")
    store.start_run("early-run")
    for source, status_word, error in (("kalshi_public", "ok", None), ("nws_pfm_okx", "ok", None)):
        store.record_source_health(run_id="early-run", source_id=source, started_at_utc="2026-09-23T18:28:40+00:00",
                                   completed_at_utc="2026-09-23T18:28:50+00:00", duration_ms=10000,
                                   status=status_word, records=3, error=error)
    store.finish_run("early-run", status="succeeded")
    cfg = Config(db=store.path, ledger=ledger.path, status_dir=status, experiments_root=REPO / "experiments",
                 clock=lambda: EARLY_NOW)
    return cfg, root


def demo() -> tuple[Config, Path]:
    return build_demo(experiments_root=REPO / "experiments")


def broken(root: Path | None = None) -> tuple[Config, Path]:
    root = root or Path(tempfile.mkdtemp(prefix="edge-ui-broken-"))
    status = root / "status"
    status.mkdir(parents=True, exist_ok=True)
    (status / "latest.json").write_text("{not json", encoding="utf-8")
    (status / "shadow_daily.json").write_text("[1, 2]", encoding="utf-8")
    bad = root / "shadow_ledger.sqlite3"
    bad.write_bytes(b"this is not a sqlite database at all" * 20)
    bad_db = root / "edge_lab.sqlite3"
    bad_db.write_bytes(b"this is not an evidence database either" * 20)
    cfg = Config(db=bad_db, ledger=bad, status_dir=status, experiments_root=REPO / "experiments",
                 clock=lambda: EARLY_NOW + timedelta(hours=40))
    return cfg, root


# ----------------------------------------------------------------------------- The Odds API pilot
# 2026-09-24 17:00 EDT. Production on that day: 95 targets, one CAPTURED (T-6h of an evening game,
# nine books, 3 credits), every other one PLANNED. The teams and prices below are fixture values.
ODDS_NOW = datetime(2026, 9, 24, 21, 0, tzinfo=timezone.utc)
_TEAMS = ["Atlanta Falcons", "Green Bay Packers", "Jacksonville Jaguars", "Houston Texans", "Buffalo Bills",
          "Miami Dolphins", "New England Patriots", "New York Jets", "Baltimore Ravens", "Cincinnati Bengals",
          "Cleveland Browns", "Pittsburgh Steelers", "Indianapolis Colts", "Tennessee Titans", "Denver Broncos",
          "Kansas City Chiefs", "Las Vegas Raiders", "Los Angeles Chargers", "Dallas Cowboys", "New York Giants",
          "Philadelphia Eagles", "Washington Commanders", "Chicago Bears", "Detroit Lions", "Minnesota Vikings",
          "Carolina Panthers", "New Orleans Saints", "Tampa Bay Buccaneers", "Arizona Cardinals",
          "Los Angeles Rams", "San Francisco 49ers", "Seattle Seahawks"]
_BOOKS = ["betmgm", "betonlineag", "betrivers", "bovada", "draftkings", "fanduel", "lowvig", "mybookieag",
          "williamhill_us"]


def _kickoffs() -> list[datetime]:
    """32 kickoffs (UTC): the Thursday game, the rest of week 3 and week 4 to its Monday night."""
    out = [datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc)]
    for week, early in ((0, 10), (7, 9)):
        sunday = datetime(2026, 9, 27, tzinfo=timezone.utc) + timedelta(days=week)
        out += ([sunday.replace(hour=17)] * early + [sunday.replace(hour=20, minute=5)] * 2
                + [sunday.replace(hour=20, minute=25)] * 2 + [sunday + timedelta(days=1, minutes=20)]
                + [sunday + timedelta(days=2, minutes=15)])
    return out


def _odds_event(native: str, home: str, away: str, commence: datetime) -> dict:
    def outcome(name: str, price: int, point: float | None = None) -> dict:
        return {"name": name, "price": price, **({"point": point} if point is not None else {})}
    books = [{"key": b, "title": b, "last_update": "2026-09-24T18:14:00Z", "markets": [
        {"key": "h2h", "outcomes": [outcome(home, -180 - i), outcome(away, 150 + i)]},
        {"key": "spreads", "outcomes": [outcome(home, -110, -3.5), outcome(away, -110, 3.5)]},
        {"key": "totals", "outcomes": [outcome("Over", -108, 47.5), outcome("Under", -112, 47.5)]}]}
        for i, b in enumerate(_BOOKS)]
    return {"id": native, "sport_key": "americanfootball_nfl", "sport_title": "NFL",
            "commence_time": commence.strftime("%Y-%m-%dT%H:%M:%SZ"), "home_team": home, "away_team": away,
            "bookmakers": books}


def odds_pilot(root: Path | None = None, *, issues: bool = False) -> tuple[Config, Path]:
    """The pilot's evidence as the runner writes it (targets, transitions, a captured odds response, a
    discovery snapshot, the quota ledger and runner state). `issues` adds a missed, a failed, a
    budget-skipped and an overdue target and an exhausted quota."""
    from edge_lab import odds_api
    from edge_lab.odds_schedule import DEFAULT_OFFSETS, ScheduledEvent, iso_z, plan_targets

    root = root or Path(tempfile.mkdtemp(prefix="edge-ui-odds-"))
    store = SnapshotStore(root / "edge_lab.sqlite3")
    sport = "americanfootball_nfl"
    events = [ScheduledEvent(f"fx{i:03d}evt", sport, k, home_team=_TEAMS[(2 * i + 1 + (4 if i >= 16 else 0)) % 32],
                             away_team=_TEAMS[(2 * i) % 32])
              for i, k in enumerate(_kickoffs())]
    store.start_run("odds-discovery")
    disc = store.save_snapshot(run_id="odds-discovery", source="the_odds_api", kind="events", entity_id=sport,
                               url="https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events?apiKey=REDACTED",
                               payload={"sport": sport, "events": [
                                   {"id": e.event_id, "sport_key": sport, "commence_time": iso_z(e.commence_utc),
                                    "home_team": e.home_team, "away_team": e.away_team} for e in events],
                                   "request": {"purpose": "discovery", "tick_utc": iso_z(ODDS_NOW - timedelta(hours=2))}},
                               fetched_at_utc=iso_z(ODDS_NOW - timedelta(hours=2)), source_id="the_odds_api")
    store.finish_run("odds-discovery", status="succeeded")
    planned_at = iso_z(datetime(2026, 9, 24, 13, 0, tzinfo=timezone.utc))
    first = events[0]
    targets = [t for t in plan_targets(events, DEFAULT_OFFSETS)
               if not (t.event_id == first.event_id and t.offset_label == "T-24h")]  # planned after its time
    for t in targets:
        store.plan_odds_target(target_id=t.target_id, sport=sport, event_id=t.event_id, offset_label=t.offset_label,
                               priority=t.priority, commence_time_utc=iso_z(t.commence_utc),
                               target_utc=iso_z(t.target_utc), planned_at_utc=planned_at,
                               policy_version="game_relative_v1", home_team=t.home_team, away_team=t.away_team,
                               discovery_snapshot_id=disc)
    six = next(t for t in targets if t.event_id == first.event_id and t.offset_label == "T-6h")
    received = six.target_utc + timedelta(seconds=41)
    store.start_run("odds-capture")
    sid = store.save_snapshot(run_id="odds-capture", source="the_odds_api", kind="odds", entity_id=sport,
                              url="https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds?apiKey=REDACTED",
                              payload={"sport": sport, "events": [_odds_event(first.event_id, first.home_team,
                                                                              first.away_team, first.commence_utc)],
                                       "request": {"purpose": "capture", "odds_format": "american",
                                                   "markets": ["h2h", "spreads", "totals"], "regions": ["us"],
                                                   "slot_id": f"{sport}:{iso_z(six.target_utc)}"},
                                       "quota_headers": {"x-requests-last": "3"}},
                              fetched_at_utc=iso_z(received), source_id="the_odds_api")
    store.finish_run("odds-capture", status="succeeded")
    stamp = iso_z(received)
    slot = f"{sport}:{iso_z(six.target_utc)}"
    store.record_odds_transition(target_id=six.target_id, state="CAPTURING", at_utc=stamp, slot_id=slot)
    parsed = odds_api.parse_odds([_odds_event(first.event_id, first.home_team, first.away_team, first.commence_utc)],
                                 odds_format="american")
    store.record_odds_transition(
        target_id=six.target_id, state="CAPTURED", at_utc=stamp, slot_id=slot, snapshot_id=sid,
        captured_at_utc=stamp, credits_last=3,
        detail={"event_present": True, "bookmakers": sorted({o.bookmaker for o in parsed.offers}),
                "markets": ["h2h", "spreads", "totals"], "missing_markets": [], "offers": len(parsed.offers),
                "offset": "T-6h", "target_utc": iso_z(six.target_utc), "deviation_minutes": 0.7,
                "lead_minutes": 359.3, "parse_problems": 0})
    ledger_path = root / "odds_quota_ledger.json"
    ledger = odds_api.QuotaLedger(ledger_path, clock=lambda: ODDS_NOW)
    if issues:
        ledger.reconcile({"x-requests-remaining": "0", "x-requests-used": "500", "x-requests-last": "0"})
        # Last Monday's game: two targets missed and one failed call, all before the capture above
        # (so the card is not DEGRADED); a game whose kickoff moved (superseded); a budget-skipped
        # target; and the T-60m above left open past its deadline (a runner that stopped).
        mnf = ScheduledEvent("fx900evt", sport, datetime(2026, 9, 22, 0, 15, tzinfo=timezone.utc),
                             home_team="Seattle Seahawks", away_team="Arizona Cardinals")
        for t in plan_targets([mnf], DEFAULT_OFFSETS):
            store.plan_odds_target(target_id=t.target_id, sport=sport, event_id=t.event_id,
                                   offset_label=t.offset_label, priority=t.priority,
                                   commence_time_utc=iso_z(t.commence_utc), target_utc=iso_z(t.target_utc),
                                   planned_at_utc="2026-09-20T12:00:00Z", policy_version="game_relative_v1",
                                   home_team=t.home_team, away_team=t.away_team)
            at = iso_z(t.target_utc + timedelta(minutes=31))
            if t.offset_label == "T-6h":
                store.record_odds_transition(target_id=t.target_id, state="CAPTURING", at_utc=iso_z(t.target_utc),
                                             slot_id=f"{sport}:{iso_z(t.target_utc)}")
                store.record_odds_transition(target_id=t.target_id, state="FAILED", at_utc=iso_z(t.target_utc),
                                             slot_id=f"{sport}:{iso_z(t.target_utc)}",
                                             reason="paid call failed (not retried): HTTP 500 from the provider")
            else:
                store.record_odds_transition(target_id=t.target_id, state="MISSED", at_utc=at,
                                             reason="expired while PLANNED")
        moved = next(t for t in targets if t.event_id == events[5].event_id and t.offset_label == "T-24h")
        store.record_odds_transition(target_id=moved.target_id, state="SUPERSEDED",
                                     at_utc=iso_z(ODDS_NOW - timedelta(hours=1)),
                                     reason="commence time changed from 2026-09-27T17:00:00Z to 2026-09-27T20:25:00Z")
        skipped = max(targets, key=lambda t: t.target_utc)
        store.record_odds_transition(target_id=skipped.target_id, state="SKIPPED_BUDGET",
                                     at_utc=iso_z(ODDS_NOW - timedelta(minutes=10)),
                                     reason="monthly credit proof: no headroom for this slot")
    else:
        ledger.reconcile({"x-requests-remaining": "482", "x-requests-used": "18", "x-requests-last": "0"})
    (root / "odds_quota_ledger.json.pilot.json").write_text(json.dumps({
        "discovery_outcome": "OK", "last_discovery_attempt_utc": iso_z(ODDS_NOW - timedelta(hours=2))}),
        encoding="utf-8")
    now = ODDS_NOW + (timedelta(hours=3) if issues else timedelta(0))  # issues: T-60m overdue
    cfg = Config(db=store.path, experiments_root=REPO / "experiments", clock=lambda: now)
    return cfg, root


def odds_issues() -> tuple[Config, Path]:
    return odds_pilot(issues=True)


BUILDERS = {"early": early, "demo": demo, "broken": broken, "odds": odds_pilot, "odds_issues": odds_issues}
