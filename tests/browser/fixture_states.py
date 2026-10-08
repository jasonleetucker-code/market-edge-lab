"""Fixture states for browser and screenshot tests (UI_CONTRACT.md §23). Never production data.

Each builder writes into a fresh temporary directory through the real ledger, evidence-store
and status-file shapes, and returns a dashboard Config with a fixed clock:

- early: the production-shaped early state from the owner's screenshots (a fresh status report,
  an INVALID last capture, no decisions, both shadow accounts opened with no activity);
- demo: the synthetic populated demo (`edge_lab.dashboard.demo.build_demo`), watermarked;
- broken: malformed and unreadable sources (corrupt JSON, a non-SQLite ledger and evidence DB);
- odds: The Odds API pilot as production held it on 2026-09-24 (95 targets, one captured);
- odds_issues: the same with a missed, a failed, a budget-skipped and an overdue target and an
  exhausted quota;
- economics / economics_issues: SYNTHETIC NFL Odds captures and Kalshi KXNFLGAME books (Economic
  Evidence v1 Family A), complete or with a missed capture and skewed, missing and crossed books;
- payoff / payoff_production / payoff_laptop: Family B over a copied EXP-003 registry: a newer SYNTHETIC
  production result (one conditional surplus), the committed production result, or only the committed laptop
  result (not production evidence);
- freshness / freshness_deferred: the Freshness Fabric artifact over the odds fixture, current or
  carried through the Kalshi close-tick guard;
- polymarket / polymarket_issues: the odds fixture plus the Polymarket US NFL pilot (recorded gateway
  bytes), complete or with a partial listing and a failed book call;
- polymarket_label_proxy: `polymarket` plus a T-60m capture with SYNTHETIC prices (an EXP-002 label proxy,
  shown hidden);
- odds_label_proxy: `odds` plus the first game's T-60m sportsbook capture with SYNTHETIC prices (an EXP-002
  label proxy: its consensus is shown hidden).
- journeys / journeys_paused / journeys_idle / journeys_stale / journeys_none: the operator journeys (Market v1 J1, J5,
  J6) over a FIXTURE execution status export (`journey_fixtures`): armed with a TEST grant and an unknown order;
  disarmed by an incident with a latch; never armed with an empty account; the populated export two hours old; and no
  export at all.
- nhl: Kalshi KXNHLGAME prospective evidence (ADR 0040) for the 2026-10-01 games: the recorded listing, T-6h books
  captured through a fake fetch (recorded order book), one failed game-horizon, one rescheduled game, one unmapped
  team; viewed at 17:00 ET.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
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


def _mixed_event(native: str, home: str, away: str, commence: datetime, received: datetime) -> dict:
    """An event whose books disagree on freshness and completeness: two books stale at receipt, a
    book with a lone alternate spread (one book: no consensus) and a one-sided total (unsupported)."""
    def outcome(name: str, price: int, point: float | None = None) -> dict:
        return {"name": name, "price": price, **({"point": point} if point is not None else {})}

    def stamp(minutes: int) -> str:
        return (received - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    books = [{"key": b, "last_update": stamp(25 if i < 2 else 2), "markets": [
        {"key": "h2h", "outcomes": [outcome(home, -130 - 3 * i), outcome(away, 110 + 3 * i)]},
        {"key": "spreads", "outcomes": [outcome(home, -108, -2.5), outcome(away, -112, 2.5)]},
        {"key": "totals", "outcomes": [outcome("Over", -110, 44.5), outcome("Under", -110, 44.5)]}]}
        for i, b in enumerate(_BOOKS[:5])]
    books.append({"key": "betus", "last_update": stamp(3), "markets": [
        {"key": "spreads", "outcomes": [outcome(home, -105, -4.5), outcome(away, -115, 4.5)]},
        {"key": "totals", "outcomes": [outcome("Over", -105, 44.5)]}]})
    return {"id": native, "sport_key": "americanfootball_nfl", "sport_title": "NFL",
            "commence_time": commence.strftime("%Y-%m-%dT%H:%M:%SZ"), "home_team": home, "away_team": away,
            "bookmakers": books}


def _history_with_issues(store: SnapshotStore, sport: str) -> None:
    """Last week, before the capture of the current game (so the card is not DEGRADED): a Sunday game
    with two missed targets and a failed call; a Monday game whose T-6h capture is usable (stale and
    unsupported books) and whose T-60m response did not include it (the consensus falls back)."""
    from edge_lab.odds_schedule import DEFAULT_OFFSETS, ScheduledEvent, iso_z, plan_targets

    def plan(event: ScheduledEvent) -> dict:
        out = {}
        for t in plan_targets([event], DEFAULT_OFFSETS):
            store.plan_odds_target(target_id=t.target_id, sport=sport, event_id=t.event_id,
                                   offset_label=t.offset_label, priority=t.priority,
                                   commence_time_utc=iso_z(t.commence_utc), target_utc=iso_z(t.target_utc),
                                   planned_at_utc="2026-09-18T12:00:00Z", policy_version="game_relative_v1",
                                   home_team=t.home_team, away_team=t.away_team)
            out[t.offset_label] = t
        return out
    sun = plan(ScheduledEvent("fx901evt", sport, datetime(2026, 9, 20, 17, 0, tzinfo=timezone.utc),
                              home_team="San Francisco 49ers", away_team="Los Angeles Rams"))
    for label in ("T-24h", "T-60m"):
        store.record_odds_transition(target_id=sun[label].target_id, state="MISSED",
                                     at_utc=iso_z(sun[label].target_utc + timedelta(minutes=31)),
                                     reason="expired while PLANNED")
    fail = sun["T-6h"]
    store.record_odds_transition(target_id=fail.target_id, state="CAPTURING", at_utc=iso_z(fail.target_utc),
                                 slot_id=f"{sport}:{iso_z(fail.target_utc)}")
    store.record_odds_transition(target_id=fail.target_id, state="FAILED", at_utc=iso_z(fail.target_utc),
                                 slot_id=f"{sport}:{iso_z(fail.target_utc)}",
                                 reason="paid call failed (not retried): HTTP 500 from the provider")
    mnf_event = ScheduledEvent("fx900evt", sport, datetime(2026, 9, 22, 0, 15, tzinfo=timezone.utc),
                               home_team="Seattle Seahawks", away_team="Arizona Cardinals")
    mnf = plan(mnf_event)
    store.record_odds_transition(target_id=mnf["T-24h"].target_id, state="MISSED",
                                 at_utc=iso_z(mnf["T-24h"].target_utc + timedelta(minutes=31)),
                                 reason="expired while PLANNED")
    for label, present in (("T-6h", True), ("T-60m", False)):
        t = mnf[label]
        received, slot = t.target_utc + timedelta(seconds=20), f"{sport}:{iso_z(t.target_utc)}"
        events = [_mixed_event("fx900evt", mnf_event.home_team, mnf_event.away_team, mnf_event.commence_utc,
                               received)] if present else []
        store.start_run(f"odds-{label}")
        sid = store.save_snapshot(run_id=f"odds-{label}", source="the_odds_api", kind="odds", entity_id=sport,
                                  url="https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds?apiKey=REDACTED",
                                  payload={"sport": sport, "events": events,
                                           "request": {"purpose": "capture", "odds_format": "american",
                                                       "slot_id": slot, "targets": [
                                                           {"target_id": t.target_id, "event_id": "fx900evt",
                                                            "offset": label, "target_utc": iso_z(t.target_utc)}]}},
                                  fetched_at_utc=iso_z(received), source_id="the_odds_api")
        store.finish_run(f"odds-{label}", status="succeeded")
        store.record_odds_transition(target_id=t.target_id, state="CAPTURING", at_utc=iso_z(received), slot_id=slot)
        store.record_odds_transition(target_id=t.target_id, state="CAPTURED", at_utc=iso_z(received), slot_id=slot,
                                     snapshot_id=sid, captured_at_utc=iso_z(received), credits_last=3,
                                     detail={"event_present": present, "offset": label, "parse_problems": 0,
                                             "bookmakers": sorted(b["key"] for e in events for b in e["bookmakers"]),
                                             "offers": sum(len(m["outcomes"]) for e in events
                                                           for b in e["bookmakers"] for m in b["markets"])})


def odds_pilot(root: Path | None = None, *, issues: bool = False) -> tuple[Config, Path]:
    """The pilot's evidence as the runner writes it (targets, transitions, a captured odds response, a
    discovery snapshot, the quota ledger and runner state). `issues` adds last week's missed, failed
    and captured targets (one capture usable with stale and unsupported books, one whose response
    lacked the game), a superseded, a budget-skipped and an overdue target and an exhausted quota."""
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
    if issues:
        _history_with_issues(store, sport)
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
        # A game whose kickoff moved (superseded), a budget-skipped target, and the T-60m above left
        # open past its deadline (a runner that stopped).
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


# EXP-002 label proxy (The Odds API): SYNTHETIC sportsbook prices for the first game's T-60m capture, distinct from
# every other fixture's, so a leak of its consensus, prices or lines is detectable.
ODDS_PROXY_H2H = (-237, 197)  # home, away (american)
ODDS_PROXY_SPREAD = 6.5
ODDS_PROXY_TOTAL = 41.5
ODDS_PROXY_NOW = datetime(2026, 9, 24, 23, 30, tzinfo=timezone.utc)  # after the 19:15 ET (23:15Z) T-60m capture


def _proxy_event(native: str, home: str, away: str, commence: datetime) -> dict:
    def outcome(name: str, price: int, point: float | None = None) -> dict:
        return {"name": name, "price": price, **({"point": point} if point is not None else {})}
    books = [{"key": b, "title": b, "last_update": "2026-09-24T23:14:00Z", "markets": [
        {"key": "h2h", "outcomes": [outcome(home, ODDS_PROXY_H2H[0]), outcome(away, ODDS_PROXY_H2H[1])]},
        {"key": "spreads", "outcomes": [outcome(home, -115, -ODDS_PROXY_SPREAD),
                                        outcome(away, -105, ODDS_PROXY_SPREAD)]},
        {"key": "totals", "outcomes": [outcome("Over", -104, ODDS_PROXY_TOTAL),
                                       outcome("Under", -116, ODDS_PROXY_TOTAL)]}]}
        for b in _BOOKS]
    return {"id": native, "sport_key": "americanfootball_nfl", "sport_title": "NFL",
            "commence_time": commence.strftime("%Y-%m-%dT%H:%M:%SZ"), "home_team": home, "away_team": away,
            "bookmakers": books}


def odds_t60m_capture(cfg: Config) -> str:
    """Adds the first game's T-60m capture (23:15:20Z, 60 min before its 00:15Z kickoff) to an `odds_pilot`
    store exactly as the runner records one: the stored response (SYNTHETIC prices, `ODDS_PROXY_*`) and the
    CAPTURING / CAPTURED transitions. Returns the target id."""
    from edge_lab import odds_api
    from edge_lab.odds_schedule import iso_z

    store = SnapshotStore(cfg.db)
    sport = "americanfootball_nfl"
    target = next(dict(r) for r in store.odds_targets(sport=sport)
                  if r["offset_label"] == "T-60m" and r["commence_time_utc"] == "2026-09-25T00:15:00Z")
    intended = datetime.fromisoformat(target["target_utc"].replace("Z", "+00:00"))
    received, slot = intended + timedelta(seconds=20), f"{sport}:{iso_z(intended)}"
    event = _proxy_event(target["event_id"], target["home_team"], target["away_team"],
                         datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc))
    store.start_run("odds-capture-t60m")
    sid = store.save_snapshot(run_id="odds-capture-t60m", source="the_odds_api", kind="odds", entity_id=sport,
                              url="https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds?apiKey=REDACTED",
                              payload={"sport": sport, "events": [event],
                                       "request": {"purpose": "capture", "odds_format": "american",
                                                   "markets": ["h2h", "spreads", "totals"], "regions": ["us"],
                                                   "slot_id": slot, "targets": [
                                                       {"target_id": target["target_id"],
                                                        "event_id": target["event_id"], "offset": "T-60m",
                                                        "target_utc": iso_z(intended)}]},
                                       "quota_headers": {"x-requests-last": "3"}},
                              fetched_at_utc=iso_z(received), source_id="the_odds_api")
    store.finish_run("odds-capture-t60m", status="succeeded")
    parsed = odds_api.parse_odds([event], odds_format="american")
    store.record_odds_transition(target_id=target["target_id"], state="CAPTURING", at_utc=iso_z(received), slot_id=slot)
    store.record_odds_transition(
        target_id=target["target_id"], state="CAPTURED", at_utc=iso_z(received), slot_id=slot, snapshot_id=sid,
        captured_at_utc=iso_z(received), credits_last=3,
        detail={"event_present": True, "bookmakers": sorted({o.bookmaker for o in parsed.offers}),
                "markets": ["h2h", "spreads", "totals"], "missing_markets": [], "offers": len(parsed.offers),
                "offset": "T-60m", "target_utc": iso_z(intended), "deviation_minutes": 0.3, "lead_minutes": 59.7,
                "parse_problems": 0})
    return str(target["target_id"])


def odds_label_proxy() -> tuple[Config, Path]:
    """`odds` plus the first game's T-60m capture with SYNTHETIC prices, viewed at 19:30 ET: an EXP-002 label proxy,
    so its "Consensus at this capture" is hidden beside the visible T-6h one."""
    cfg, root = odds_pilot()
    odds_t60m_capture(cfg)
    return replace(cfg, clock=lambda: ODDS_PROXY_NOW), root


def _with_freshness(cfg: Config, root: Path, evaluated: datetime, now: datetime, window=None) -> Config:
    """Write the supervisor's artifact exactly as `edge-lab freshness status --write` does, over this
    fixture's evidence (the real providers), then serve the dashboard with `status_dir` pointing at it."""
    from dataclasses import replace as _replace

    from edge_lab import freshness_fabric as ff
    from edge_lab.freshness import FabricContext

    status = root / "status"
    status.mkdir(exist_ok=True)
    ctx = FabricContext(db=cfg.db, odds_ledger=root / "odds_quota_ledger.json", status_dir=status)
    ff.write_status(ff.render(ff.build_status(ctx, evaluated)), status)
    if window is not None:  # the next supervisor tick falls inside a protected window: carried forward
        ff.write_status(ff.render(ff.deferred_status(ctx, window[1] + timedelta(minutes=2), window)), status)
    return _replace(cfg, status_dir=status, clock=lambda: now)


def freshness() -> tuple[Config, Path]:
    """The Freshness Fabric's artifact over the production-shaped odds fixture, written 3 minutes ago."""
    cfg, root = odds_pilot()
    return _with_freshness(cfg, root, ODDS_NOW - timedelta(minutes=3), ODDS_NOW), root


def freshness_deferred() -> tuple[Config, Path]:
    """Inside the Kalshi close-tick guard: the supervisor carried its previous evaluation forward."""
    from edge_lab import freshness_fabric as ff

    cfg, root = odds_pilot()
    guard = ff.close_guard_at(datetime(2026, 9, 25, 4, 58, tzinfo=timezone.utc))
    return _with_freshness(cfg, root, guard[1] - timedelta(minutes=4), guard[1] + timedelta(minutes=3),
                           window=guard), root



# ----------------------------------------------------------------------------- Polymarket US NFL pilot
# The real recorded gateway bytes (tests/fixtures/polymarket_us, captured 2026-09-24) replayed through
# the pilot's own public entry points (`run_discover`, `run_capture`): no network.
PM_FIX = REPO / "tests" / "fixtures" / "polymarket_us"
PM_ACCESS = "fixture: the owner's recorded risk decision"


class _Recorded:
    """An opener that replays recorded response bodies in order."""

    def __init__(self, *bodies: bytes) -> None:
        self.bodies = list(bodies)

    def __call__(self, request, timeout):
        body, url = self.bodies.pop(0), request.full_url

        class _Response:
            status = 200
            headers = {"Content-Type": "application/json"}

            def read(self) -> bytes:
                return body

            def geturl(self) -> str:
                return url

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        return _Response()


def polymarket(root: Path | None = None, *, issues: bool = False) -> tuple[Config, Path]:
    """The odds fixture plus the Polymarket US pilot: a discovery of the recorded NFL listing at 14:00
    ET and the ATL@GB T-6h research book capture at 14:15 ET. `issues` makes the scan partial (the
    second listing page failed) and records a failed book call."""
    from edge_lab import polymarket_sports as ps

    cfg, root = odds_pilot(root)
    pages = [(PM_FIX / "nfl_events_moneyline_p0_2026-09-24T205921Z.json").read_bytes()]
    if not issues:
        pages.append((PM_FIX / "nfl_events_moneyline_p1_2026-09-24T205942Z.json").read_bytes())
    discover_at = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)
    opener = _Recorded(*pages) if not issues else _FailAfter(*pages)
    ps.run_discover(cfg.db, clock=lambda: discover_at, sleep=lambda s: None, opener=opener,
                    access_decision=PM_ACCESS)
    book = (PM_FIX / "book_aec-nfl-atl-gb-2026-09-24_2026-09-24T205959Z.json").read_bytes()
    capture_at = datetime(2026, 9, 24, 18, 15, 30, tzinfo=timezone.utc)
    from edge_lab import http as pm_http

    class _At(datetime):  # the fetch layer stamps receipt with the wall clock: pin it to the fixture's time
        @classmethod
        def now(cls, tz=None):
            return capture_at + timedelta(seconds=0.4)
    wall, pm_http.datetime = pm_http.datetime, _At
    try:
        ps.run_capture(cfg.db, clock=lambda: capture_at, sleep=lambda s: None,
                       opener=_Recorded(book) if not issues else _FailAfter(), access_decision=PM_ACCESS)
    finally:
        pm_http.datetime = wall
    return cfg, root


class _FailAfter(_Recorded):
    """Replays the given bodies, then answers every further request with HTTP 503."""

    def __call__(self, request, timeout):
        if self.bodies:
            return super().__call__(request, timeout)
        from urllib.error import HTTPError

        raise HTTPError(request.full_url, 503, "Service Unavailable", {}, None)


def polymarket_issues() -> tuple[Config, Path]:
    return polymarket(issues=True)


# EXP-002 label proxy: SYNTHETIC top-of-book figures absent from every recorded body, so a leak is detectable.
PM_PROXY_BID, PM_PROXY_ASK, PM_PROXY_QTY = "0.4125", "0.4175", "777.0000"
PM_PROXY_AT = datetime(2026, 9, 24, 23, 15, tzinfo=timezone.utc)  # ATL@GB T-60m (19:15 ET; kickoff 00:15Z)
PM_PROXY_NOW = datetime(2026, 9, 24, 23, 30, tzinfo=timezone.utc)


def pm_t60m_capture(cfg: Config) -> None:
    """Adds the ATL@GB T-60m research book capture at 19:15 ET to a `polymarket` store: the recorded book with
    SYNTHETIC top levels (`PM_PROXY_*`), through the pilot's own capture entry point."""
    from edge_lab import http as pm_http
    from edge_lab import polymarket_sports as ps

    raw = json.loads((PM_FIX / "book_aec-nfl-atl-gb-2026-09-24_2026-09-24T205959Z.json").read_bytes())
    data = {k: v for k, v in raw["marketData"].items() if k != "stats"}
    data["bids"] = [{"px": {"value": PM_PROXY_BID, "currency": "USD"}, "qty": PM_PROXY_QTY}]
    data["offers"] = [{"px": {"value": PM_PROXY_ASK, "currency": "USD"}, "qty": PM_PROXY_QTY}]

    class _At(datetime):  # the fetch layer stamps receipt with the wall clock: pin it to the fixture's time
        @classmethod
        def now(cls, tz=None):
            return PM_PROXY_AT + timedelta(seconds=20)
    wall, pm_http.datetime = pm_http.datetime, _At
    try:
        code, report = ps.run_capture(cfg.db, clock=lambda: PM_PROXY_AT, sleep=lambda s: None,
                                      opener=_Recorded(json.dumps({"marketData": data}).encode()),
                                      access_decision=PM_ACCESS)
    finally:
        pm_http.datetime = wall
    if code != 0 or report.get("by_status") != {"CAPTURED": 1}:
        raise RuntimeError(f"the T-60m fixture capture did not record one book: {report}")


def polymarket_label_proxy(root: Path | None = None) -> tuple[Config, Path]:
    """`polymarket` plus the ATL@GB T-60m capture (SYNTHETIC prices), viewed at 19:30 ET: an EXP-002 label proxy,
    so Data sources shows it as "Hidden · EXP-002 label proxy" beside the visible T-6h capture."""
    cfg, root = polymarket(root)
    pm_t60m_capture(cfg)
    return replace(cfg, clock=lambda: PM_PROXY_NOW), root


def economics(root: Path | None = None, *, issues: bool = False) -> tuple[Config, Path]:
    """Economic Evidence v1, Family A: a SYNTHETIC store of NFL Odds captures and Kalshi KXNFLGAME books
    (`edge_lab.dashboard.sports_fixtures`, real store shapes; real team names, synthetic prices), viewed on
    Sunday 2026-09-27 17:00 ET. `issues` adds a missed capture, a skewed, a missing and a crossed book."""
    from edge_lab.dashboard import sports_fixtures

    root = root or Path(tempfile.mkdtemp(prefix="edge-ui-economics-"))
    path, now = sports_fixtures.fixture_store(root, issues=issues)
    return Config(db=path, experiments_root=REPO / "experiments", clock=lambda: now), root


def economics_issues() -> tuple[Config, Path]:
    return economics(issues=True)


def payoff() -> tuple[Config, Path]:
    """Family B: a copy of the repository's EXP-003 registry plus a newer SYNTHETIC production-labelled result
    (one conditional full-fill surplus row), logged in the copy's own evidence-use log; the odds store."""
    from edge_lab.dashboard import sports_fixtures

    cfg, root = odds_pilot()
    registry = sports_fixtures.payoff_registry(root / "experiments", production=True, positive=True)
    now = sports_fixtures.PAYOFF_NOW
    return replace(cfg, experiments_root=registry, clock=lambda: now), root


def payoff_laptop() -> tuple[Config, Path]:
    """Family B with only the committed laptop result (not production evidence)."""
    from edge_lab.dashboard import sports_fixtures

    cfg, root = odds_pilot()
    registry = sports_fixtures.payoff_registry(root / "experiments", keep="payoff_scan_laptop_*")
    now = sports_fixtures.PAYOFF_NOW
    return replace(cfg, experiments_root=registry, clock=lambda: now), root


def payoff_production() -> tuple[Config, Path]:
    """Family B as production shows it after #103: the committed production result (and its sidecar)."""
    from edge_lab.dashboard import sports_fixtures

    cfg, root = odds_pilot()
    registry = sports_fixtures.payoff_registry(root / "experiments")
    now = sports_fixtures.PAYOFF_NOW
    return replace(cfg, experiments_root=registry, clock=lambda: now), root



# Kalshi NHL prospective evidence (NHL-B, ADR 0040): the recorded 2026-09-29 KXNHLGAME listing, a stored
# icehockey_nhl discovery of the 2026-10-01 games, planned with the switch on, the T-6h books captured through a
# fake fetch (recorded order book), one game-horizon failed, and a later game rescheduled. Viewed at 17:00 ET.
NHL_NOW = datetime(2026, 10, 1, 21, 0, tzinfo=timezone.utc)


def nhl(root: Path | None = None) -> tuple[Config, Path]:
    from edge_lab import price_observations as po
    from edge_lab import sports_nhl
    from edge_lab.http import FetchResult, HttpFetchError

    root = root or Path(tempfile.mkdtemp(prefix="edge-ui-nhl-"))
    fix = REPO / "tests" / "fixtures"
    listing = json.loads((fix / "sports_nhl" / "kalshi_events_KXNHLGAME_open_2026-09-29.json")
                         .read_text(encoding="utf-8"))
    book = json.loads((fix / "forward" / "orderbook_KXHIGHNY-26SEP23-B69.5.json").read_text(encoding="utf-8"))
    events = {e["event_ticker"]: e for e in listing["events"] if e["event_ticker"].startswith("KXNHLGAME-26OCT01")}
    by_abbr = {abbr: name for name, (abbr, _) in sports_nhl.NHL_TEAMS.items()}
    store = SnapshotStore(root / "edge_lab.sqlite3")

    def odds_events(shift_last: bool = False) -> list:
        out = []
        for i, (ticker, e) in enumerate(sorted(events.items())):
            parsed, _ = sports_nhl.parse_ticker(ticker)
            occ = datetime.fromisoformat(e["markets"][0]["occurrence_datetime"].replace("Z", "+00:00"))
            start = occ - timedelta(hours=3) + (timedelta(days=1) if shift_last and i == 0 else timedelta(0))
            out.append({"id": f"nhl_fixture_{i}", "sport_key": sports_nhl.NHL_SPORT,
                        "commence_time": start.isoformat().replace("+00:00", "Z"),
                        "home_team": by_abbr[parsed["home"]], "away_team": by_abbr[parsed["away"]]})
        out.append({"id": "nhl_fixture_unmapped", "sport_key": sports_nhl.NHL_SPORT,
                    "commence_time": "2026-10-01T23:30:00Z", "home_team": "Hartford Whalers",
                    "away_team": "Boston Bruins"})
        return out

    def discover(at: datetime, shift_last: bool = False) -> None:
        run = f"nhl-discovery-{at.isoformat()}"
        store.start_run(run)
        store.save_snapshot(run_id=run, source="the_odds_api", kind="events", entity_id=sports_nhl.NHL_SPORT,
                            url="https://api.the-odds-api.com/v4/sports/icehockey_nhl/events?apiKey=REDACTED",
                            payload={"sport": sports_nhl.NHL_SPORT, "events": odds_events(shift_last),
                                     "request": {"purpose": "discovery", "tick_utc": at.isoformat()}},
                            fetched_at_utc=at.isoformat(), source_id="the_odds_api")
        store.finish_run(run, status="succeeded")

    clock = [datetime(2026, 10, 1, 17, 5, 20, tzinfo=timezone.utc)]
    failing = "KXNHLGAME-26OCT01MINNSH"  # its T-6h book request fails at 14:05 ET

    def fake(url, **_kw):
        clock[0] += timedelta(seconds=0.3)
        if f"event_ticker={failing}&" in url:
            raise HttpFetchError("HTTP 503", status=503, attempts=1)
        if "/orderbook" in url:
            payload = book
        else:
            ticker = url.split("event_ticker=")[1].split("&")[0]
            payload = {"cursor": "", "markets": events[ticker]["markets"]}
        return payload, FetchResult(url, url, 200, "application/json", json.dumps(payload).encode(),
                                    clock[0].isoformat(), 1, 1)

    env = {po.NHL_SWITCH: "on"}
    discover(datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc))
    po.run_plan(store.path, None, now=datetime(2026, 10, 1, 12, 5, tzinfo=timezone.utc), environ=env)
    original = po.fetch_json_result
    po.fetch_json_result = fake
    try:
        po.run_capture(store.path, clock=lambda: clock[0], sleep=lambda s: None, environ=env)
        clock[0] = datetime(2026, 10, 1, 18, 5, 20, tzinfo=timezone.utc)
        po.run_capture(store.path, clock=lambda: clock[0], sleep=lambda s: None, environ=env)
    finally:
        po.fetch_json_result = original
    discover(datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc), shift_last=True)
    po.run_plan(store.path, None, now=datetime(2026, 10, 1, 20, 5, tzinfo=timezone.utc), environ=env)
    cfg = Config(db=store.path, experiments_root=REPO / "experiments", clock=lambda: NHL_NOW)
    return cfg, root


def _journeys(scenario: str | None, *, later: timedelta = timedelta(minutes=1)) -> tuple[Config, Path]:
    """The operator journeys (J1, J5, J6) over a FIXTURE execution export written by the real exporter from a journal
    the real orchestrator wrote against the test FakeVenue (`journey_fixtures`). `scenario` None writes no export."""
    import journey_fixtures as jf

    root = Path(tempfile.mkdtemp(prefix="edge-ui-journeys-"))
    if scenario is None:
        at = jf.h.T0 + timedelta(minutes=10)
    else:
        _, at = jf.build(scenario, root)
    return Config(status_dir=root, experiments_root=REPO / "experiments", clock=lambda: at + later), root


def journeys() -> tuple[Config, Path]:
    return _journeys("populated")


def journeys_paused() -> tuple[Config, Path]:
    return _journeys("paused")


def journeys_idle() -> tuple[Config, Path]:
    return _journeys("idle")


def journeys_none() -> tuple[Config, Path]:
    return _journeys(None)


def journeys_stale() -> tuple[Config, Path]:
    return _journeys("populated", later=timedelta(hours=2))


BUILDERS = {"early": early, "demo": demo, "broken": broken, "odds": odds_pilot, "odds_issues": odds_issues,
            "journeys": journeys, "journeys_paused": journeys_paused, "journeys_idle": journeys_idle,
            "journeys_none": journeys_none, "journeys_stale": journeys_stale,
            "freshness": freshness, "freshness_deferred": freshness_deferred,
            "polymarket": polymarket, "polymarket_issues": polymarket_issues,
            "polymarket_label_proxy": polymarket_label_proxy, "odds_label_proxy": odds_label_proxy,
            "economics": economics, "economics_issues": economics_issues,
            "payoff": payoff, "payoff_laptop": payoff_laptop, "payoff_production": payoff_production,
            "nhl": nhl}
