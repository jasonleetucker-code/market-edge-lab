"""SYNTHETIC paired-evidence fixtures for Family A (tests, browser states and the demo gallery only).

Writes an evidence store through the real store APIs, in the shapes the collectors write: Odds API
capture targets, transitions and odds snapshots (`odds_pilot`), and Kalshi KXNFLGAME listings and order
books (`forward._save` / `price_observations`: source `kalshi`, kinds `events` / `markets` / `orderbook`).
Team names are real (the mapping needs them); every price, size, time, id and bookmaker is synthetic and
the run ids say SYNTHETIC. The rules text follows the wording Kalshi's KXNFLGAME listing showed on
2026-09-25 (recorded in tests/fixtures/sports_evidence/). Never production data.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from ..odds_schedule import DEFAULT_OFFSETS, PilotConfig, ScheduledEvent, deadline, effective_due, iso_z, plan_targets
from ..sports_evidence import KALSHI, KALSHI_SERIES, NFL_TEAMS, SPORT, et_date
from ..storage import SnapshotStore

UTC = timezone.utc
KALSHI_API = "https://external-api.kalshi.com/trade-api/v2"
ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds?apiKey=REDACTED&oddsFormat=american"
BOOKS = ("synthetic_book_a", "synthetic_book_b", "synthetic_book_c")
RULES_PRIMARY = "If {team} wins the {away} vs {home} Pro Football game originally scheduled for {day}, then the " \
                "market resolves to Yes."
RULES_SECONDARY = ("The following market refers to the team who wins the {away} vs {home} Pro Football game "
                   "originally scheduled for {day}. If the game ends in a tie, the market will resolve to $0.50 for "
                   "each team. If the game is postponed but begins within 48 hours from its originally scheduled "
                   "start time, the market will remain open and resolve based on the official final result. If the "
                   "game is not started within 48 hours, the market will resolve to a fair price.")
_MON = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


@dataclass(frozen=True)
class Game:
    event_id: str
    home: str
    away: str
    commence: datetime
    home_p: Decimal = Decimal("0.62")  # the synthetic de-vigged home probability the books imply


# Real team names, synthetic everything else. Dates match the tickers Kalshi listed on 2026-09-25.
GAMES = (
    Game("fxsyn001", "Green Bay Packers", "Atlanta Falcons", datetime(2026, 9, 25, 0, 15, tzinfo=UTC), Decimal("0.78")),
    Game("fxsyn002", "Miami Dolphins", "Kansas City Chiefs", datetime(2026, 9, 27, 17, 0, tzinfo=UTC), Decimal("0.41")),
    Game("fxsyn003", "Washington Commanders", "Seattle Seahawks", datetime(2026, 9, 27, 20, 25, tzinfo=UTC),
         Decimal("0.55")),
    Game("fxsyn004", "Las Vegas Raiders", "Kansas City Chiefs", datetime(2026, 10, 4, 20, 5, tzinfo=UTC), Decimal("0.35")),
)
NOW = datetime(2026, 9, 27, 21, 0, tzinfo=UTC)  # G1-G3 due, G4 next week (not yet due)


def event_ticker(g: Game) -> str:
    d = et_date(g.commence)
    return f"{KALSHI_SERIES}-{d.year % 100:02d}{_MON[d.month - 1]}{d.day:02d}{NFL_TEAMS[g.away][0]}{NFL_TEAMS[g.home][0]}"


def _american(p: Decimal) -> int:
    """A synthetic American price with about 2.5% margin on each side."""
    q = min(p * Decimal("1.025"), Decimal("0.97"))
    return int(-(q / (1 - q)) * 100) if q >= Decimal("0.5") else int((1 - q) / q * 100)


def _odds_event(g: Game, received: datetime) -> dict[str, Any]:
    stamp = iso_z(received - timedelta(minutes=2))
    books = []
    for i, key in enumerate(BOOKS):
        ph = g.home_p + Decimal(i - 1) / 100
        books.append({"key": key, "title": key, "last_update": stamp, "markets": [{"key": "h2h", "last_update": stamp,
                      "outcomes": [{"name": g.home, "price": _american(ph)}, {"name": g.away, "price": _american(1 - ph)}]}]})
    return {"id": g.event_id, "sport_key": SPORT, "sport_title": "NFL", "commence_time": iso_z(g.commence),
            "home_team": g.home, "away_team": g.away, "bookmakers": books}


def _market(g: Game, team: str, *, status: str = "active", result: str = "", market_type: str = "binary",
            tie_clause: bool = True) -> dict[str, Any]:
    day = et_date(g.commence).strftime("%b %d, %Y").replace(" 0", " ")
    labels = {n: NFL_TEAMS[n][1] for n in (g.home, g.away)}
    secondary = RULES_SECONDARY.format(away=labels[g.away], home=labels[g.home], day=day)
    if not tie_clause:
        secondary = secondary.replace("If the game ends in a tie, the market will resolve to $0.50 for each team. ", "")
    return {"ticker": f"{event_ticker(g)}-{NFL_TEAMS[team][0]}", "event_ticker": event_ticker(g), "status": status,
            "result": result, "market_type": market_type, "notional_value_dollars": "1.0000",
            "rules_primary": RULES_PRIMARY.format(team=labels[team], away=labels[g.away], home=labels[g.home], day=day),
            "rules_secondary": secondary, "yes_sub_title": labels[team], "no_sub_title": labels[team],
            "title": f"{labels[team]} wins", "expected_expiration_time": iso_z(g.commence + timedelta(hours=6)),
            "latest_expiration_time": iso_z(g.commence + timedelta(hours=48)),
            "close_time": iso_z(g.commence + timedelta(hours=48)), "can_close_early": True,
            "price_ranges": [{"start": "0.0000", "end": "1.0000", "step": "0.0100"}],
            "price_level_structure": "linear_cent"}


def _event(g: Game, **market_kw: Any) -> dict[str, Any]:
    labels = {n: NFL_TEAMS[n][1] for n in (g.home, g.away)}
    return {"event_ticker": event_ticker(g), "series_ticker": KALSHI_SERIES,
            "title": f"{labels[g.away]} vs {labels[g.home]}", "mutually_exclusive": True,
            "settlement_sources": [{"name": "the Governing League", "url": "https://www.nfl.com/"}],
            "markets": [_market(g, g.home, **market_kw), _market(g, g.away, **market_kw)]}


def _levels(ask: Decimal, depth: int, base_size: int) -> list[list[str]]:
    """Bids on the opposite side that make a YES ask ladder starting at `ask` (one cent apart)."""
    return [[f"{(1 - ask - Decimal(i) / 100):.4f}", f"{base_size * (i + 1)}.00"] for i in range(depth)]


def _book(yes_ask: Decimal, *, depth: int = 3, size: int = 40, crossed: bool = False) -> dict[str, Any]:
    no_ask = 1 - yes_ask + Decimal("0.02")
    yes_bids = _levels(no_ask, depth, size)  # the YES bids are the NO side's asks
    no_bids = _levels(yes_ask, depth, size)
    if crossed:
        yes_bids = [[f"{(yes_ask + Decimal('0.01')):.4f}", "10.00"]]  # YES bid + NO bid = 1.01: crossed
    return {"orderbook_fp": {"yes_dollars": yes_bids, "no_dollars": no_bids}}


def write_pairing_fixture(store: SnapshotStore, *, games: Sequence[Game] = GAMES, now: datetime = NOW,
                          kalshi: bool = True, books: bool = True, issues: bool = False, settle: bool = True,
                          market_type: str = "binary", complete_listing: bool = True,
                          tie_clause: bool = True) -> dict[str, Any]:
    """Plan and capture every due Odds target of `games` and, with `kalshi`, write one Kalshi series listing
    before the first target and a book per team market 60 s after each capture. `issues` adds a missed
    Odds target, a skewed book, a missing book, a crossed book and a truncated shallow book. Returns ids."""
    cfg = PilotConfig()
    run = "SYNTHETIC-pairing-fixture"
    store.start_run(run)
    events = [ScheduledEvent(g.event_id, SPORT, g.commence, g.home, g.away) for g in games]
    by_id = {g.event_id: g for g in games}
    targets = plan_targets(events, DEFAULT_OFFSETS)
    first = min(t.target_utc for t in targets)
    planned = iso_z(first - timedelta(days=1, hours=1))
    for t in targets:
        store.plan_odds_target(target_id=t.target_id, sport=SPORT, event_id=t.event_id, offset_label=t.offset_label,
                               priority=t.priority, commence_time_utc=iso_z(t.commence_utc), target_utc=iso_z(t.target_utc),
                               planned_at_utc=planned, policy_version="game_relative_v1", home_team=t.home_team,
                               away_team=t.away_team)
    out: dict[str, Any] = {"targets": [t.target_id for t in targets], "books": {}, "odds": {}}
    if kalshi:
        listing_at = first - timedelta(hours=1)
        store.save_snapshot(run_id=run, source=KALSHI, kind="events", entity_id=KALSHI_SERIES,
                            url=f"{KALSHI_API}/events?series_ticker={KALSHI_SERIES}&status=open&with_nested_markets=true",
                            payload={"events": [_event(g, market_type=market_type, tie_clause=tie_clause) for g in games],
                                     "cursor": "" if complete_listing else "SYNTHETICNEXTPAGE"},
                            fetched_at_utc=iso_z(listing_at), source_id="kalshi_public")
    skewed = missing = crossed = shallow = missed = None
    if issues:
        due = [t for t in targets if deadline(t, cfg) <= now]
        missed = next(t for t in due if t.event_id == games[1].event_id and t.offset_label == "T-24h")
        skewed = next(t for t in due if t.event_id == games[1].event_id and t.offset_label == "T-6h")
        missing = next(t for t in due if t.event_id == games[2].event_id and t.offset_label == "T-60m")
        crossed = next(t for t in due if t.event_id == games[2].event_id and t.offset_label == "T-6h")
        shallow = next(t for t in due if t.event_id == games[0].event_id and t.offset_label == "T-60m")
    for t in targets:
        if deadline(t, cfg) > now:
            continue
        if t is missed:
            store.record_odds_transition(target_id=t.target_id, state="MISSED", at_utc=iso_z(deadline(t, cfg)),
                                         reason="SYNTHETIC: expired while PLANNED")
            continue
        g = by_id[t.event_id]
        received = effective_due(t, cfg) + timedelta(seconds=40)
        slot = f"{SPORT}:{iso_z(effective_due(t, cfg))}"
        sid = store.save_snapshot(run_id=run, source="the_odds_api", kind="odds", entity_id=SPORT, url=ODDS_URL,
                                  payload={"sport": SPORT, "events": [_odds_event(g, received)],
                                           "request": {"purpose": "capture", "odds_format": "american", "slot_id": slot,
                                                       "targets": [{"target_id": t.target_id, "event_id": t.event_id,
                                                                    "offset": t.offset_label,
                                                                    "target_utc": iso_z(t.target_utc)}]}},
                                  fetched_at_utc=iso_z(received), source_id="the_odds_api")
        store.record_odds_transition(target_id=t.target_id, state="CAPTURING", at_utc=iso_z(received), slot_id=slot)
        store.record_odds_transition(target_id=t.target_id, state="CAPTURED", at_utc=iso_z(received), slot_id=slot,
                                     snapshot_id=sid, captured_at_utc=iso_z(received), credits_last=1,
                                     detail={"event_present": True, "offset": t.offset_label})
        out["odds"][t.target_id] = sid
        if not (kalshi and books) or t is missing:
            continue
        for team, p in ((g.home, g.home_p), (g.away, 1 - g.home_p)):
            ticker = f"{event_ticker(g)}-{NFL_TEAMS[team][0]}"
            at = received + (timedelta(minutes=12) if t is skewed else timedelta(seconds=60))
            ask = (p + Decimal("0.01")).quantize(Decimal("0.01"))
            depth = 3
            url = f"{KALSHI_API}/markets/{ticker}/orderbook?depth=100"
            if t is shallow:
                url = f"{KALSHI_API}/markets/{ticker}/orderbook?depth=3"
            book = _book(ask, depth=depth, crossed=t is crossed)
            bid = store.save_snapshot(run_id=run, source=KALSHI, kind="orderbook", entity_id=ticker, url=url,
                                      payload=book, fetched_at_utc=iso_z(at), source_id="kalshi_public")
            out["books"].setdefault(t.target_id, {})[team] = bid
    if kalshi and settle:
        g = games[0]
        at = g.commence + timedelta(hours=5)
        if at <= now:
            store.save_snapshot(run_id=run, source=KALSHI, kind="markets", entity_id=event_ticker(g),
                                url=f"{KALSHI_API}/markets?event_ticker={event_ticker(g)}",
                                payload={"markets": [_market(g, g.home, status="finalized", result="yes"),
                                                     _market(g, g.away, status="finalized", result="no")], "cursor": ""},
                                fetched_at_utc=iso_z(at), source_id="kalshi_public")
    store.finish_run(run, status="succeeded")
    return out


def fixture_store(root: Path | None = None, **kw: Any) -> tuple[Path, datetime]:
    """A fresh SYNTHETIC store written by `write_pairing_fixture`; returns (path, now)."""
    root = root or Path(tempfile.mkdtemp(prefix="edge-sports-pairing-"))
    store = SnapshotStore(root / "edge_lab.sqlite3")
    write_pairing_fixture(store, **kw)
    return store.path, kw.get("now", NOW)


_VIEWS: dict[str, Any] = {}


def synthetic_economic_views() -> dict[str, Any]:
    """name -> (Family A `data.Loaded`, Family B `data.Loaded`) for the gallery, each through the real
    `sports_evidence.terminal_view` over a SYNTHETIC store. Built once per process (demo only)."""
    from .. import sports_evidence as se
    from . import data as d

    if _VIEWS:
        return _VIEWS
    b_missing = d.Loaded(d.NO_DATA, message="the same-venue payoff evaluator (payoff_constraints, PR B) is not in this "
                                            "build")

    def a(path: Path, now: datetime) -> Any:
        view = se.terminal_view(path, now=now)
        return d.Loaded(d.OK, view["family_a"]) if view["state"] == "OK" else d.Loaded(d.ERROR, message=view["detail"])
    populated, now = fixture_store()
    partial, _ = fixture_store(issues=True)
    gap, _ = fixture_store(kalshi=False)
    unsupported, _ = fixture_store(market_type="scalar")
    empty_root = Path(tempfile.mkdtemp(prefix="edge-sports-empty-"))
    SnapshotStore(empty_root / "edge_lab.sqlite3")
    _VIEWS.update({
        "populated": (a(populated, now), b_missing),
        "partial": (a(partial, now), b_missing),
        "gap": (a(gap, now), b_missing),
        "stale": (a(populated, now + timedelta(days=12)), b_missing),
        "unsupported": (a(unsupported, now), b_missing),
        "empty": (a(empty_root / "edge_lab.sqlite3", now), b_missing),
        "unknown": (d.Loaded(d.NO_DATA, message="no evidence database configured (--db)"), b_missing),
        "error": (d.Loaded(d.ERROR, message="OperationalError: database disk image is malformed"), b_missing),
    })
    return _VIEWS


# --------------------------------------------------------------------------- Family B (EXP-003 result files)

REPO_EXPERIMENTS = Path(__file__).resolve().parents[3] / "experiments"
PAYOFF_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)  # three days after the committed laptop scan's books


def payoff_registry(root: Path | None = None, *, production: bool = False, positive: bool = False,
                    slot_status: str | None = None, results: bool = True, tamper: bool = False,
                    keep: str | None = None) -> Path:
    """A throwaway experiment registry holding a copy of the repository's EXP-003 (protocol, evidence-use log,
    the committed result files and their `.source.json` sidecars). `keep` (a glob) removes every other result
    file; `production` adds a newer SYNTHETIC production-labelled result, logged in the copy's own log exactly
    as the payoff-scan CLI logs one; `positive` gives it one conditional full-fill surplus row; `slot_status`
    rewrites the protocol's slot; `results=False` removes every result file; `tamper` edits the newest result
    (by evaluation as-of) after it was hashed. The repository's files are never written."""
    import copy
    import json
    import shutil

    from .. import payoff_constraints as pc
    from .. import research_evidence as rev
    from ..provenance import canonical_json, sha256_hex

    root = root or Path(tempfile.mkdtemp(prefix="edge-payoff-registry-"))
    src = next(REPO_EXPERIMENTS.glob("EXP-003-*"))
    exp = root / src.name
    shutil.copytree(src, exp)
    if slot_status is not None:
        proto = exp / "protocol.toml"
        proto.write_text(proto.read_text(encoding="utf-8").replace('slot_status = "ACTIVE"',
                                                                   f'slot_status = "{slot_status}"'),
                         encoding="utf-8", newline="\n")
    results_dir = exp / "results"
    if not results:
        shutil.rmtree(results_dir)
        return root
    if keep is not None:
        for f in results_dir.glob("payoff_scan_*"):
            if not f.match(keep):
                f.unlink()

    def as_of(f: Path) -> str:
        return max(str(e.get("as_of_utc")) for e in json.loads(f.read_text(encoding="utf-8"))["report"]["evaluations"])
    newest = max((f for f in results_dir.glob("payoff_scan_*.json") if not f.name.endswith(".source.json")), key=as_of)
    if production:
        base = json.loads(newest.read_text(encoding="utf-8"))
        report = copy.deepcopy(base["report"])
        report.pop("report_sha256", None)
        report["set_construction"] = pc.SET_CONSTRUCTION  # the current formats (PR 105)
        report["input_hash_definition"] = pc.INPUT_HASH_DEFINITION
        for i, e in enumerate(report["evaluations"]):
            e["set_id"] = f"SYNTHETIC-{e['set_id']}"
            # newer than every committed result; the last set is the newest (and carries any positive claim)
            e["as_of_utc"] = (datetime(2026, 9, 25, 10, 0, tzinfo=UTC) + timedelta(minutes=i)).isoformat()
        if positive:
            row = report["evaluations"][-1]["sizes"][0]
            row.update(claim="CONDITIONAL_FULL_FILL_SURPLUS", claim_adjusted_surplus="0.0300",
                       worst_state_surplus="0.0400", claim_reasons=["SYNTHETIC: proven partition, costed"])
            report["claim_counts_by_size_row"] = {"CONDITIONAL_FULL_FILL_SURPLUS": 1, "NOT_EVALUATED": 5}
        report["report_sha256"] = sha256_hex(canonical_json(report))
        window = report["event_window"]
        use = rev.EvidenceUse(
            experiment_id="EXP-003", family="B", dataset_id="kalshi:KXHIGHNY-books", dataset_version="SYNTHETIC",
            dataset_sha256=report["input_snapshot_sha256"], role=rev.DatasetRole.DEVELOPMENT,
            window=rev.InformationWindow("kalshi:KXHIGHNY", f"{window[0]}T00:00:00Z", f"{window[1]}T23:59:59Z"),
            actor="SYNTHETIC fixture", tool="dashboard.sports_fixtures.payoff_registry",
            action_time_utc="2026-09-25T00:00:00Z", action=rev.Action.FEATURE_INSPECTION, code_version="SYNTHETIC",
            model_version=None, prompt_version=None, viewed_features=True, viewed_labels=False, viewed_results=True,
            influenced_tuning=False, note=f"SYNTHETIC fixture. report_sha256={report['report_sha256']}")
        rev.record_use(exp / "evidence_use.jsonl", use)
        envelope = pc.result_envelope(report, generated_at_utc="2026-09-25T00:00:00+00:00", source_store="production",
                                      code_version="SYNTHETIC", evidence_use_event_id=use.event_id)
        newest = results_dir / "payoff_scan_SYNTHETIC_production_2026-09-25.json"
        newest.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if tamper:
        obj = json.loads(newest.read_text(encoding="utf-8"))
        obj["report"]["evaluations"][0]["relationship"] = "PROVEN"
        newest.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return root


_PAYOFF_VIEWS: dict[str, Any] = {}


def synthetic_payoff_views() -> dict[str, Any]:
    """name -> Family B `data.Loaded` for the gallery, each through the real loader over a copied registry."""
    from . import data as d
    from .data import Config, Context

    if _PAYOFF_VIEWS:
        return _PAYOFF_VIEWS

    def load(root: Path, now: datetime = PAYOFF_NOW) -> Any:
        return Context(Config(experiments_root=root, clock=lambda: now)).economic_b
    _PAYOFF_VIEWS.update({
        "committed": load(payoff_registry()),
        "laptop": load(payoff_registry(keep="payoff_scan_laptop_*")),
        "production": load(payoff_registry(production=True, positive=True)),
        "stale": load(payoff_registry(), PAYOFF_NOW + timedelta(days=10)),
        "empty": load(payoff_registry(results=False)),
        "blocked": load(payoff_registry(slot_status="QUEUED")),
        "error": load(payoff_registry(tamper=True)),
        "unavailable": d.Loaded(d.NO_DATA, message="no experiment registry configured (--experiments-root), so the "
                                                   "EXP-003 result files cannot be found"),
    })
    return _PAYOFF_VIEWS
