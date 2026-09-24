"""Polymarket US NFL research pilot (ADR 0032): bounded public discovery, relationship mapping to
The Odds API schedule, and target-based research book captures. Read-only; research evidence only.

Scope and authority (owner directive 2026-09-24 evening, `docs/owner/2026-09-24-freshness-fabric-sports-directive.md`):
NFL only; the public, unauthenticated gateway only (`polymarket_us.BASE_URL`); no account, no
credential, no order path, no Polymarket International, no VPN or geoblock circumvention, no paid
service, no Odds API credit. The adapter is `edge_lab.polymarket_us`; this module adds no second one.

**Access gate.** The terms/access review
(`experiments/multi_venue/polymarket_us_sports_terms_2026-09-24.md`) did not clear unattended
collection: the Polymarket App Terms license market data for personal, non-commercial use in
connection with the user's own trading and prohibit bulk downloads unless expressly licensed. So
`OWNER_ACCESS_DECISION` is None and every networked run stops before the network with
BLOCKED_TERMS_REVIEW (exit 0, nothing written). Only a recorded owner decision, referenced here in
a reviewed change, lifts it.

**Discovery** (`discover`, at most every 6 h). GET /v1/events filtered to the NFL tag, open events
and the full-game winner (moneyline) market type, paged by limit/offset until an empty page, under
the completeness contract of `polymarket_us.read_events_listing`. It is a FILTERED listing, so its
coverage is at most PARTIAL ("filter complete" when every page was read to an empty page), and a
market missing from it is never evidence that it does not exist. Every page is an immutable
snapshot; the scan row records coverage and the derived NFL moneyline catalog. Filtering the
market types keeps a page near 0.35 MB; the unfiltered NFL league listing measured 40 MB per page
(2026-09-24), which is not a bounded research read.

**Relationships** (`relate`). A Polymarket US moneyline is compared with the Odds API NFL schedule
(the latest stored quota-free discovery). The result is RELATED_NOT_EQUIVALENT, UNMATCHED or
AMBIGUOUS, never equivalent: same teams and kickoff do not make the contracts equal. The checks
(teams, date, start time, league, overtime, ties, postponement / cancellation / no-contest,
participant start, settlement source, alternative / last-fair-market-price settlement, payout
structure) are recorded with their state; PAYOFF_UNSUPPORTED and RULES_UNRESOLVED are kept as flags.

**Targets and captures** (`plan`, `capture`). Each RELATED_NOT_EQUIVALENT market gets targets at
T-24h / T-6h / T-60m before its `gameStartTime` (`odds_schedule.DEFAULT_OFFSETS`), moved out of the
protected windows (`price_observations.PROTECTED_WINDOWS_ET`). A target is written once with its
intended time and due window; each attempt is an append-only row. A target not captured by its
deadline becomes MISSED with its reason; nothing is fetched late and nothing is fabricated. Caps:
20 markets per slot (overflow SKIPPED_CAP, visible), 20 books and 50 HTTP requests (retries
included) per run, a 1 s pacer, a 3-minute run deadline (the unit's hard limit is 5 minutes), one
retry per request. A captured book is research evidence: never an executable price claim, never
compared with or ranked against a sportsbook offer.

**Lock.** Runs hold `<db>.pm-sports.lock`, not the Kalshi collector lock: this pilot uses no
Kalshi pacer, and sharing that lock would make NFL reads queue behind (or delay) EXP-001 captures.

**Exit codes.** Only a genuine, non-retryable failure exits non-zero: a capture whose FAILED target
no later scheduled tick can retry before its deadline, a discovery failure that has just made the
catalog stale (once, on that transition), or an unexpected error. Refusals (terms gate, protected
window, lock busy, not due, budget, deadline) exit 0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.request import Request

from . import http, odds_api, polymarket_us
from .discovery import CoverageState
from .forward import MIN_REQUEST_BUDGET, REQUEST_TIMEOUT_S, DeadlineExceeded, LockBusy, eastern_offset, exclusive_lock
from .freshness import Freshness, parse_utc
from .odds_schedule import DEFAULT_OFFSETS, ScheduledEvent, iso_z
from .price_observations import protected_window_at
from .provenance import bytes_sha256
from .sources import get_source
from .storage import PM_SPORTS_FINAL_STATUSES, ReadOnlyStoreError, SnapshotStore

UTC = timezone.utc
POLICY_VERSION = "pm-sports-nfl-v1"
RELATIONSHIP_VERSION = "pm-odds-relationship-v1"
LEAGUE = "nfl"
ODDS_SPORT = "americanfootball_nfl"
MONEYLINE_TYPE = "football_team_full_game_winner"  # sportsMarketType of the full-game winner market
MONEYLINE_TYPE_V2 = "SPORTS_MARKET_TYPE_MONEYLINE"
ODDS_MARKET_KEY = "h2h"  # the Odds API market a moneyline relates to (never equals)
DISCOVERY_FILTER: tuple[tuple[str, str], ...] = (
    ("tagSlug", LEAGUE), ("closed", "false"), ("sportsMarketTypes", MONEYLINE_TYPE))

# Recorded owner decision that clears unattended networked runs (a repo reference), or None.
# The 2026-09-24 terms review did not clear it: see the module docstring and ADR 0032.
OWNER_ACCESS_DECISION: str | None = None
TERMS_REVIEW = "experiments/multi_venue/polymarket_us_sports_terms_2026-09-24.md"

# Bounds (ADR 0032 has the worst-case arithmetic). Lower than the directive's caps where noted.
PAGE_LIMIT = 50
MAX_DISCOVERY_PAGES = 6  # 300 events; a full NFL regular season is 272 games
DISCOVERY_INTERVAL = timedelta(hours=6)
DISCOVERY_SLACK = timedelta(minutes=15)  # timer jitter: a run this close to the interval counts as due
DISCOVERY_MAX_AGE = timedelta(hours=24)  # no capture from an older catalog
ODDS_SCHEDULE_MAX_AGE = timedelta(hours=24)  # odds_pilot.RunnerSettings.discovery_max_age
OFFSETS = DEFAULT_OFFSETS  # T-24h, T-6h, T-60m (priority 1 = T-60m)
EARLY = timedelta(minutes=7)  # a target is due from 7 min before its (effective) time ...
LATE = timedelta(minutes=30)  # ... until 30 min after it
MIN_LEAD = timedelta(minutes=5)  # ... and never within 5 min of kickoff
MAX_MARKETS_PER_SLOT = 20
MAX_BOOKS_PER_RUN = 20
MAX_HTTP_REQUESTS_PER_RUN = 50  # every HTTP attempt counts, retries included
RETRIES = 1  # one retry per request, only for transient failures (edge_lab.http)
PACER_INTERVAL_S = 1.0  # the docs allow 20/s per IP; 1/s is deliberate politeness
MAX_RUN = timedelta(minutes=3)  # run deadline; edgelab-pm-sports*.service TimeoutStartSec=5min is the hard stop
TICK_INTERVAL = timedelta(minutes=15)  # edgelab-pm-sports.timer (tests pin the two together)
LOCK_TIMEOUT_S = 5.0
START_TOLERANCE = timedelta(minutes=15)  # kickoff agreement for RELATED_NOT_EQUIVALENT
SAME_GAME_WINDOW = timedelta(hours=36)  # beyond this the same teams are a different game

LABEL = "RELATED MARKET — NOT ECONOMICALLY EQUIVALENT"
RESEARCH_LABEL = "RESEARCH BOOK CAPTURE — NOT AN EXECUTABLE PRICE CLAIM"
DASHBOARD_SCHEMA = "pm-sports-status/1"

SOURCE = get_source(polymarket_us.SOURCE_ID)  # page and book snapshots are stored under it
HEALTH_DISCOVERY = get_source("polymarket_us_nfl_discovery").source_id
HEALTH_BOOK = get_source("polymarket_us_nfl_book").source_id
ODDS_SOURCE = odds_api.get_source(odds_api.SOURCE_ID).legacy_name

RELATED = "RELATED_NOT_EQUIVALENT"
UNMATCHED = "UNMATCHED"
AMBIGUOUS = "AMBIGUOUS"
RELATIONSHIP_STATES = (RELATED, UNMATCHED, AMBIGUOUS)  # there is deliberately no equivalent state

Clock = Callable[[], datetime]
Sleep = Callable[[float], None]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _t(value: Any) -> datetime | None:
    return parse_utc(value)


# --------------------------------------------------------------------------- catalog


_OT_INCLUDED = re.compile(r"overtime\s+is\s+included", re.IGNORECASE)
_OT_EXCLUDED = re.compile(r"overtime\s+is\s+not\s+included|regulation\s+(?:time\s+)?only|excluding\s+overtime",
                          re.IGNORECASE)
_TIE = re.compile(r"ends\s+in\s+a\s+tie[^.]*?settle\s+to\s+\$?\s*(0?\.\d+)", re.IGNORECASE)
_POSTPONE = re.compile(r"not\s+rescheduled\s+to\s+a\s+date\s+within\s+([a-z0-9 ]{1,30}?)\s+of\s+the\s+originally",
                       re.IGNORECASE)
_LFMP = re.compile(r"last[\s-]+fair[\s-]+market[\s-]+price|\bLFMP\b", re.IGNORECASE)
_OUTCOME_SOURCE = re.compile(r"outcome\s+sourced\s+from\s+([^.]{1,80})", re.IGNORECASE)
_PARTICIPANT = re.compile(r"\b(?:must\s+start|starting\s+(?:pitcher|quarterback|player)|does\s+not\s+play)\b",
                          re.IGNORECASE)


def rules_clauses(text: str | None) -> dict[str, Any]:
    """What the market's rules text states, matched literally (never interpreted further).
    Anything not stated stays None / UNSTATED."""
    text = text if isinstance(text, str) else ""
    ot = "INCLUDED" if _OT_INCLUDED.search(text) else "EXCLUDED" if _OT_EXCLUDED.search(text) else "UNSTATED"
    tie = _TIE.search(text)
    post = _POSTPONE.search(text)
    src = _OUTCOME_SOURCE.search(text)
    return {"overtime": ot, "tie_settlement": tie.group(1) if tie else None,
            "postponement_window": post.group(1).strip() if post else None,
            "last_fair_market_price": bool(_LFMP.search(text)),
            "outcome_source": src.group(1).strip() if src else None,
            "participant_start_condition": bool(_PARTICIPANT.search(text))}


@dataclass(frozen=True)
class NflMarket:
    """One Polymarket US NFL full-game winner market, as a scan saw it (raw fields kept)."""

    market_slug: str
    pm_event_slug: str | None
    pm_event_id: str | None
    game_id: str | None
    title: str | None
    question: str | None
    game_start_utc: str | None
    teams: tuple[str, ...]
    long_team: str | None
    short_team: str | None
    status_raw: str | None
    rules_sha256: str | None
    payoff_kind: str
    payoff_why: str
    fee_scope: str | None
    clauses: dict[str, Any] = field(default_factory=dict)
    sports_market_type: str | None = None
    price_tick_raw: str | None = None
    minimum_trade_qty_raw: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["teams"] = list(self.teams)
        return out

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "NflMarket":
        return cls(**{**d, "teams": tuple(d.get("teams") or ())})


def _team_name(side: Mapping[str, Any]) -> str | None:
    team = side.get("team")
    name = team.get("name") if isinstance(team, Mapping) else None
    return name if isinstance(name, str) and name.strip() else None


def _has_tag(raw: Mapping[str, Any], slug: str) -> bool:
    return any(isinstance(t, Mapping) and t.get("slug") == slug for t in raw.get("tags") or [])


def catalog_from_events(events: Sequence[Mapping[str, Any]]) -> tuple[list[NflMarket], list[str]]:
    """NFL moneyline markets from listed events. Anything the filter should have excluded is
    dropped and reported (the server's filter is checked, never trusted)."""
    markets: list[NflMarket] = []
    anomalies: list[str] = []
    seen: set[str] = set()
    for ev in events:
        if not isinstance(ev, Mapping):
            anomalies.append("event entry is not an object")
            continue
        slug = ev.get("slug") if isinstance(ev.get("slug"), str) else None
        if not _has_tag(ev, LEAGUE):
            anomalies.append(f"event {slug or ev.get('id')!r} has no '{LEAGUE}' tag: filter not honoured; dropped")
            continue
        teams = tuple(t["name"] for t in ev.get("teams") or []
                      if isinstance(t, Mapping) and isinstance(t.get("name"), str) and t["name"].strip())
        for m in ev.get("markets") or []:
            if not isinstance(m, Mapping) or not isinstance(m.get("slug"), str):
                anomalies.append(f"event {slug!r}: market entry without a slug skipped")
                continue
            if m.get("sportsMarketType") != MONEYLINE_TYPE:
                anomalies.append(f"{m['slug']}: sportsMarketType {m.get('sportsMarketType')!r} is not {MONEYLINE_TYPE}; "
                                 "filter not honoured; dropped")
                continue
            if m["slug"] in seen:
                anomalies.append(f"{m['slug']}: listed twice; the later copy skipped")
                continue
            seen.add(m["slug"])
            long_team = short_team = None
            for side in m.get("marketSides") or []:
                if isinstance(side, Mapping) and side.get("long") is True and long_team is None:
                    long_team = _team_name(side)
                elif isinstance(side, Mapping) and side.get("long") is False and short_team is None:
                    short_team = _team_name(side)
            kind, why = polymarket_us.payoff_kind(m)
            tick = m.get("orderPriceMinTickSize")
            qty = m.get("minimumTradeQty")
            markets.append(NflMarket(
                market_slug=m["slug"], pm_event_slug=slug, pm_event_id=None if ev.get("id") is None else str(ev["id"]),
                game_id=None if ev.get("gameId") is None else str(ev["gameId"]),
                title=m.get("title") if isinstance(m.get("title"), str) else None,
                question=m.get("question") if isinstance(m.get("question"), str) else None,
                game_start_utc=m.get("gameStartTime") if isinstance(m.get("gameStartTime"), str) else None,
                teams=teams, long_team=long_team, short_team=short_team,
                status_raw=m.get("status") if isinstance(m.get("status"), str) else None,
                rules_sha256=polymarket_us.rules_sha256(m), payoff_kind=kind, payoff_why=why,
                fee_scope=polymarket_us.fee_scope(m), clauses=rules_clauses(m.get("description")),
                sports_market_type=m.get("sportsMarketType"),
                price_tick_raw=None if tick is None else str(tick), minimum_trade_qty_raw=None if qty is None else str(qty)))
    return markets, anomalies


# --------------------------------------------------------------------------- relationships


@dataclass(frozen=True)
class Relationship:
    """How one Polymarket US market relates to the Odds API schedule. Never equivalence."""

    status: str  # RELATED_NOT_EQUIVALENT | UNMATCHED | AMBIGUOUS
    market_slug: str
    odds_event_id: str | None
    odds_market_key: str | None
    reasons: tuple[str, ...]
    checks: dict[str, dict[str, Any]]
    flags: tuple[str, ...]
    candidates: tuple[str, ...] = ()
    version: str = RELATIONSHIP_VERSION
    equivalent: bool = False  # by construction; never True in this mission

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key in ("reasons", "flags", "candidates"):
            out[key] = list(out[key])
        return out


def _norm_team(name: str | None) -> str:
    return " ".join((name or "").replace(".", " ").split()).casefold()


def _check(state: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"state": state, "detail": detail, **extra}


def _et_date(instant: datetime) -> str:
    return (instant + eastern_offset(instant)).date().isoformat()


def _rule_checks(market: NflMarket) -> dict[str, dict[str, Any]]:
    """Rule dimensions: what Polymarket US states, and why the book side stays unverified. The
    Odds API offers carry no rules text, so no dimension can be proven equal (fail closed)."""
    c = market.clauses
    books = "the Odds API offers carry no rules text; each sportsbook's rule is unknown here"
    return {
        "regulation_vs_overtime": _check("UNVERIFIED", f"Polymarket US overtime {c.get('overtime', 'UNSTATED')}; {books}"),
        "ties": _check("UNVERIFIED", (f"Polymarket US settles a tie at ${c['tie_settlement']}" if c.get("tie_settlement")
                                      else "Polymarket US tie settlement not stated in the rules text")
                       + f"; two-way book moneylines usually void or push a tie, but {books}"),
        "postponement_cancellation_no_contest": _check(
            "UNVERIFIED", (f"Polymarket US: last fair market price unless rescheduled within {c['postponement_window']}"
                           if c.get("postponement_window") else
                           "Polymarket US: " + ("last-fair-market-price settlement stated" if c.get("last_fair_market_price")
                                                else "no postponement rule found in the rules text"))
            + f"; {books}"),
        "participant_start": _check("UNVERIFIED", ("Polymarket US rules text names a participant-start condition"
                                                   if c.get("participant_start_condition")
                                                   else "Polymarket US rules text names no participant-start condition")
                                    + f"; {books}"),
        "settlement_provider": _check("UNVERIFIED", f"Polymarket US outcome source: {c.get('outcome_source') or 'not stated'}"
                                                    f"; {books}"),
        "alternative_settlement": _check("DIFFERS" if market.payoff_kind != polymarket_us.PAYOFF_BINARY else "UNVERIFIED",
                                         f"Polymarket US payoff kind {market.payoff_kind}: {market.payoff_why}"),
        "payout_structure": _check("DIFFERS", "Polymarket US pays $1.00 per winning contract (alternative settlement per "
                                              "its rules); a sportsbook pays stake x odds with its own void rules"),
    }


def relate(market: NflMarket, odds_events: Sequence[ScheduledEvent]) -> Relationship:
    """Relate one Polymarket US NFL moneyline to the Odds API NFL schedule. Deterministic.

    RELATED_NOT_EQUIVALENT needs: exactly one Odds API event with the same two teams (exact
    full names) within `SAME_GAME_WINDOW`, and its commence time within `START_TOLERANCE` of the
    market's `gameStartTime`. Several such events, one team only, or the same teams at a
    kickoff that differs by more than the tolerance is AMBIGUOUS; no event with both teams
    (or only a far-away rematch) is UNMATCHED. The rule dimensions are recorded; none is ever
    proven equal, so nothing is ever called equivalent."""
    flags = ["RULES_UNRESOLVED"]  # polymarket_us.market_from_polymarket: rules_resolved=False, always
    if market.payoff_kind != polymarket_us.PAYOFF_BINARY:
        flags.append("PAYOFF_UNSUPPORTED")
    checks: dict[str, dict[str, Any]] = {
        "league": _check("MATCH", f"Polymarket US listing filtered to tag '{LEAGUE}' and the event carries it; "
                                  f"Odds API sport {ODDS_SPORT}")}

    def result(status: str, reasons: list[str], event: ScheduledEvent | None = None,
               candidates: Sequence[ScheduledEvent] = ()) -> Relationship:
        return Relationship(status=status, market_slug=market.market_slug,
                            odds_event_id=event.event_id if event is not None else None,
                            odds_market_key=ODDS_MARKET_KEY if event is not None else None,
                            reasons=tuple(reasons), checks={**checks, **_rule_checks(market)}, flags=tuple(flags),
                            candidates=tuple(sorted(c.event_id for c in candidates)))

    start = _t(market.game_start_utc)
    teams = {_norm_team(t) for t in market.teams if _norm_team(t)}
    if start is None:
        checks["start_time"] = _check("UNKNOWN", f"gameStartTime {market.game_start_utc!r} is not a zoned timestamp")
        return result(AMBIGUOUS, ["Polymarket US game start time unknown"])
    if len(teams) != 2:
        checks["teams"] = _check("UNKNOWN", f"event lists {len(market.teams)} named team(s): {list(market.teams)}")
        return result(AMBIGUOUS, ["the Polymarket US event does not name exactly two teams"])
    both = [e for e in odds_events if {_norm_team(e.home_team), _norm_team(e.away_team)} == teams]
    near = [e for e in both if abs(e.commence_utc - start) <= SAME_GAME_WINDOW]
    one = [e for e in odds_events if e not in both and len(teams & {_norm_team(e.home_team), _norm_team(e.away_team)}) == 1
           and abs(e.commence_utc - start) <= SAME_GAME_WINDOW]
    if not near:
        checks["teams"] = _check("DIFFERS" if not both else "MATCH",
                                 "no Odds API event names both teams" if not both else
                                 "same teams only in Odds API events more than 36 h away (a different game)")
        if one:
            return result(AMBIGUOUS, [f"{len(one)} Odds API event(s) within 36 h share exactly one team "
                                      "(a team-name mismatch or a schedule change)"], candidates=one)
        return result(UNMATCHED, ["no Odds API NFL event with both teams within 36 h of the Polymarket US start"],
                      candidates=both)
    checks["teams"] = _check("MATCH", f"exact full-name team set {sorted(market.teams)}")
    close = [e for e in near if abs(e.commence_utc - start) <= START_TOLERANCE]
    if len(near) > 1:
        return result(AMBIGUOUS, [f"{len(near)} Odds API events with both teams within 36 h"], candidates=near)
    event = near[0]
    delta = (event.commence_utc - start).total_seconds()
    checks["date"] = _check("MATCH" if _et_date(event.commence_utc) == _et_date(start) else "DIFFERS",
                            f"America/New_York dates {_et_date(start)} (Polymarket US) and {_et_date(event.commence_utc)} "
                            "(Odds API)")
    checks["start_time"] = _check("MATCH" if close else "DIFFERS",
                                  f"kickoffs {iso_z(start)} and {iso_z(event.commence_utc)} differ by {delta:+.0f} s "
                                  f"(tolerance {int(START_TOLERANCE.total_seconds())} s)", delta_s=delta)
    checks["home_away"] = _check("UNVERIFIED", f"Odds API home {event.home_team!r}, away {event.away_team!r}; Polymarket "
                                               "US publishes no documented home/away field")
    if not close:
        return result(AMBIGUOUS, [f"same teams, but the kickoffs differ by {delta / 60:+.0f} min (rescheduled?)"],
                      event=None, candidates=near)
    if checks["date"]["state"] != "MATCH":
        return result(AMBIGUOUS, ["kickoffs agree within tolerance but fall on different New York dates"],
                      candidates=near)
    return result(RELATED, ["same league, both teams and kickoff; contract terms not proven equal "
                            "(payout structure differs; rule dimensions unverified)"], event=event, candidates=near)


# --------------------------------------------------------------------------- odds schedule (stored)


def odds_schedule(store: SnapshotStore) -> tuple[tuple[ScheduledEvent, ...], dict[str, Any] | None]:
    """The latest stored Odds API NFL discovery (quota-free events endpoint), read only.
    (events, provenance) or ((), None) when there is none."""
    row = store.latest_snapshot(source=ODDS_SOURCE, kind="events", entity_id=ODDS_SPORT)
    if row is None:
        return (), None
    payload = json.loads(row["payload_json"])
    events, problems = odds_api.parse_events(payload.get("events"), sport=ODDS_SPORT)
    request = payload.get("request") or {}
    at = _t(request.get("tick_utc")) or _t(row["fetched_at_utc"])
    return events, {"snapshot_id": int(row["id"]), "discovered_at_utc": _iso(at) if at else None,
                    "events": len(events), "problems": list(problems)[:10]}


# --------------------------------------------------------------------------- scans


def _scan_markets(scan: Mapping[str, Any]) -> list[NflMarket]:
    return [NflMarket.from_dict(d) for d in json.loads(scan["catalog_json"] or "[]")]


def latest_usable_scan(store: SnapshotStore) -> Any | None:
    """The newest scan that read at least one page (FAILED scans hold no catalog)."""
    for row in store.pm_sports_scans(league=LEAGUE):
        if int(row["pages_ok"]) > 0:
            return row
    return None


def _scan_age(scan: Any, now: datetime) -> timedelta | None:
    at = _t(scan["completed_at_utc"]) if scan is not None else None
    return None if at is None else now - at


# --------------------------------------------------------------------------- requests


class RequestBudgetExhausted(RuntimeError):
    """This run has used its HTTP request allowance (retries included)."""


@dataclass
class _Requests:
    """Bounded public GETs: at most `limit` HTTP attempts (a retry counts), none started too close
    to the run deadline, paced by `pacer`, one retry for transient failures only."""

    limit: int
    deadline: datetime
    clock: Clock
    sleep: Sleep
    pacer: http.Pacer
    opener: http.Opener | None = None
    attempts: int = 0
    calls: int = 0

    def _open(self, request: Request, timeout: float) -> Any:
        if self.attempts >= self.limit:
            raise RequestBudgetExhausted(f"HTTP request budget of {self.limit} used")
        self.attempts += 1
        # The package's default opener, looked up per call (the test suite's no-network guard patches it).
        return (self.opener or http._default_opener)(request, timeout)

    def get(self, url: str) -> tuple[dict[str, Any], http.FetchResult]:
        if self.attempts >= self.limit:
            raise RequestBudgetExhausted(f"HTTP request budget of {self.limit} used")
        remaining = self.deadline - self.clock()
        if remaining < MIN_REQUEST_BUDGET:
            raise DeadlineExceeded(f"{remaining.total_seconds():.1f}s left before {url}")

        def bounded_sleep(seconds: float) -> None:
            if self.deadline - self.clock() - timedelta(seconds=seconds) < MIN_REQUEST_BUDGET:
                raise DeadlineExceeded(f"retry backoff of {seconds:.1f}s would pass the run deadline")
            self.sleep(seconds)

        self.calls += 1
        timeout = min(REQUEST_TIMEOUT_S, max(remaining.total_seconds() - 1.0, 1.0))
        return http.fetch_json_result(url, headers={"User-Agent": polymarket_us.USER_AGENT}, timeout=timeout,
                                      retries=RETRIES, opener=self._open, pacer=self.pacer, sleep=bounded_sleep)


class _LazyRun:
    """A collection_runs row only when something is written: idle ticks add nothing."""

    def __init__(self, store: SnapshotStore, prefix: str) -> None:
        self.store, self.prefix, self.run_id = store, prefix, None

    def id(self) -> str:
        if self.run_id is None:
            self.run_id = f"{self.prefix}-{uuid.uuid4()}"
            self.store.start_run(self.run_id)
        return self.run_id

    def finish(self, status: str, error: str | None = None) -> None:
        if self.run_id is not None:
            self.store.finish_run(self.run_id, status=status, error=error)


def _health(store: SnapshotStore, run: _LazyRun, *, source_id: str, started: datetime, now: datetime, status: str,
            records: int = 0, payload_bytes: int = 0, http_errors: int = 0, retries: int = 0,
            anomalies: Sequence[str] = (), error: str | None = None) -> None:
    """One source_health row, written last; it never changes what was stored or the exit code."""
    try:
        store.record_source_health(run_id=run.id(), source_id=source_id, started_at_utc=_iso(started),
                                   completed_at_utc=_iso(now), duration_ms=max(0, int((now - started).total_seconds() * 1000)),
                                   status=status, records=0 if status == "failed" else records,
                                   payload_bytes=payload_bytes, http_errors=http_errors, retries=retries,
                                   anomalies=list(anomalies)[:20], error=None if error is None else error[:500])
    except Exception as exc:  # noqa: BLE001 - a health row must not break the evidence already stored
        print(f"pm-sports: source_health row not written: {type(exc).__name__}: {exc}", file=sys.stderr)


# --------------------------------------------------------------------------- discovery


def discovery_due(store: SnapshotStore, now: datetime) -> tuple[bool, str | None]:
    """(due, next due time). Paced on the last ATTEMPT, successful or not."""
    scans = store.pm_sports_scans(league=LEAGUE, limit=1)
    if not scans:
        return True, None
    last = _t(scans[0]["started_at_utc"])
    if last is None:
        return True, None
    nxt = last + DISCOVERY_INTERVAL
    return now >= nxt - DISCOVERY_SLACK, _iso(nxt)


def discover(store: SnapshotStore, *, clock: Clock | None = None, sleep: Sleep = time.sleep,
             opener: http.Opener | None = None, force: bool = False) -> tuple[int, dict[str, Any]]:
    """One bounded discovery scan, then (network-free) planning. The caller holds the lock and has
    checked the access gate and protected windows."""
    clock = clock or _now
    now = clock()
    report: dict[str, Any] = {"command": "pm-sports discover", "now_utc": _iso(now), "policy_version": POLICY_VERSION,
                              "league": LEAGUE, "requests": 0}
    due, next_due = discovery_due(store, now)
    if not due and not force:
        report.update(state="NOT_DUE", next_due_utc=next_due)
        return 0, report
    last_attempt = (store.pm_sports_scans(league=LEAGUE, limit=1) or [None])[0]
    # Was the catalog already stale when the previous attempt finished? (The alert is for the
    # transition only: one non-zero exit when a failure first leaves captures without a catalog.)
    previous_usable = latest_usable_scan(store)
    at_last = _t(last_attempt["completed_at_utc"]) if last_attempt is not None else None
    previous_age = _scan_age(previous_usable, at_last) if at_last is not None else None
    was_stale = last_attempt is None or previous_age is None or previous_age > DISCOVERY_MAX_AGE
    run = _LazyRun(store, "pm-sports-discover")
    run_id = run.id()
    req = _Requests(2 * MAX_DISCOVERY_PAGES, now + MAX_RUN, clock, sleep, http.Pacer(PACER_INTERVAL_S, sleep=sleep), opener)
    page_ids: list[int] = []
    sizes: list[int] = []
    payload_bytes = 0

    def on_page(payload: dict[str, Any], result: http.FetchResult, url: str) -> None:
        nonlocal payload_bytes
        sid = store.save_snapshot(run_id=run_id, source=SOURCE.legacy_name, kind="nfl_events", entity_id=LEAGUE, url=url,
                                  payload=payload, fetch=result, source_id=SOURCE.source_id,
                                  parser_version=polymarket_us.PARSER_VERSION, schema_version=SOURCE.schema_version)
        page_ids.append(sid)
        sizes.append(len(payload.get("events") or []))
        payload_bytes += len(result.body)

    try:
        events, coverage = polymarket_us.read_events_listing(extra=DISCOVERY_FILTER, limit=PAGE_LIMIT,
                                                             max_pages=MAX_DISCOVERY_PAGES, get=req.get, on_page=on_page)
        markets, anomalies = catalog_from_events(events)
        filter_complete = bool(sizes) and sizes[-1] == 0 and coverage.state is not CoverageState.FAILED
        end = clock()
        scan_id = f"pm-scan-{uuid.uuid4()}"
        store.record_pm_sports_scan({
            "scan_id": scan_id, "run_id": run_id, "league": LEAGUE, "endpoint": coverage.endpoint,
            "started_at_utc": _iso(now), "completed_at_utc": _iso(end), "coverage_state": coverage.state.value,
            "filter_complete": int(filter_complete), "pages_ok": coverage.pages_ok, "requests": req.attempts,
            "events": len(events), "markets": len(markets), "coverage_detail": coverage.detail,
            "page_snapshot_ids_json": json.dumps(page_ids),
            "catalog_json": json.dumps([m.to_dict() for m in markets], sort_keys=True),
            "anomalies_json": json.dumps(anomalies[:50]), "parser_version": polymarket_us.PARSER_VERSION,
            "policy_version": POLICY_VERSION})
        failed = coverage.state is CoverageState.FAILED
        partial = not filter_complete and not failed
        _health(store, run, source_id=HEALTH_DISCOVERY, started=now, now=end,
                status="failed" if failed else ("partial" if partial or anomalies else "ok"), records=len(page_ids),
                payload_bytes=payload_bytes, http_errors=0, retries=max(0, req.attempts - req.calls),
                anomalies=anomalies + ([coverage.detail] if partial else []),
                error=coverage.detail if failed or partial else None)
        report.update(scan_id=scan_id, coverage=coverage.state.value, filter_complete=filter_complete,
                      coverage_detail=coverage.detail, pages=coverage.pages_ok, events=len(events), markets=len(markets),
                      anomalies=anomalies[:20], requests=req.attempts)
        report["plan"] = plan(store, now=end, run=run)
    except BaseException:
        run.finish("failed", "pm-sports discover aborted")
        raise
    run.finish("failed" if failed else ("partial" if partial else "succeeded"),
               coverage.detail if failed or partial else None)
    report["state"] = "FAILED" if failed else ("PARTIAL" if partial else "FILTER_COMPLETE")
    # Alert once, when this failure has just left captures without a usable catalog.
    usable_age = _scan_age(latest_usable_scan(store), clock())
    stale_now = usable_age is None or usable_age > DISCOVERY_MAX_AGE
    newly = stale_now and (last_attempt is None or int(last_attempt["pages_ok"]) > 0 or not was_stale)
    report["catalog_stale"] = stale_now
    return (1 if (failed and newly) else 0), report


# --------------------------------------------------------------------------- planning


def _shift_out_of_protected(t: datetime, latest: datetime) -> tuple[datetime, str | None]:
    """Move a target out of a protected window: to its end when that still leaves the lead, else
    to just before it (price_observations uses the same rule)."""
    hit = protected_window_at(t, t + MAX_RUN)
    if hit is None:
        return t, None
    name, w0, w1 = hit
    if w1 <= latest:
        return w1, name
    return w0 - MAX_RUN - timedelta(minutes=1), name


def target_id(market_slug: str, offset_label: str, target_utc: datetime) -> str:
    """Includes the intended time: a rescheduled game gets new targets; the old ones are superseded."""
    return f"{LEAGUE}:{market_slug}:{offset_label}:{iso_z(target_utc)}"


def targets_for(market: NflMarket, rel: Relationship, *, scan_id: str, now: datetime
                ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """(new target rows, not planned with reasons) for one related market."""
    start = _t(market.game_start_utc)
    out: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    if rel.status != RELATED or start is None:
        return [], [{"market_slug": market.market_slug, "reason": f"NOT_RELATED: {rel.status}"}]
    latest = start - MIN_LEAD
    for off in OFFSETS:
        intended = (start - off.before).astimezone(UTC)
        eff, shifted = _shift_out_of_protected(intended, latest)
        due, deadline = eff - EARLY, min(eff + LATE, latest)
        if eff > deadline:
            skipped.append({"market_slug": market.market_slug, "offset": off.label,
                            "reason": f"NO_WINDOW: {iso_z(eff)} is not before kickoff - {int(MIN_LEAD.total_seconds() // 60)} min"})
            continue
        if deadline <= now:
            skipped.append({"market_slug": market.market_slug, "offset": off.label,
                            "reason": f"PAST_DEADLINE: planned at {iso_z(now)}, deadline {iso_z(deadline)}"})
            continue
        detail = {"shifted_out_of_protected_window": shifted} if shifted else {}
        detail.update(title=market.title, teams=list(market.teams), payoff_kind=market.payoff_kind,
                      fee_scope=market.fee_scope, clauses=market.clauses)
        out.append({"target_id": target_id(market.market_slug, off.label, intended), "league": LEAGUE,
                    "market_slug": market.market_slug, "pm_event_slug": market.pm_event_slug,
                    "odds_event_id": rel.odds_event_id, "relationship": rel.status,
                    "relationship_json": json.dumps(rel.to_dict(), sort_keys=True), "offset_label": off.label,
                    "priority": off.priority, "game_start_utc": _iso(start), "target_utc": _iso(intended),
                    "effective_utc": _iso(eff), "due_from_utc": _iso(due), "deadline_utc": _iso(deadline),
                    "planned_at_utc": _iso(now), "scan_id": scan_id, "planned_rules_sha256": market.rules_sha256,
                    "policy_version": POLICY_VERSION, "detail_json": json.dumps(detail, sort_keys=True)})
    return out, skipped


def _attempt_id(run_id: str, tid: str) -> str:
    return f"{run_id}:{tid}:{uuid.uuid4().hex[:12]}"


def _row(run: _LazyRun, target: Mapping[str, Any], status: str, now: datetime, *, reason: str | None = None,
         **extra: Any) -> dict[str, Any]:
    run_id = run.id()
    return {"run_id": run_id, "attempt_id": _attempt_id(run_id, target["target_id"]), "target_id": target["target_id"],
            "status": status, "reason": reason, "freshness": Freshness.UNKNOWN.value, "recorded_at_utc": _iso(now),
            "policy_version": POLICY_VERSION, **extra}


def plan(store: SnapshotStore, *, now: datetime, run: _LazyRun | None = None) -> dict[str, Any]:
    """Network-free, idempotent planning from the latest usable scan and the latest stored Odds
    API schedule: relate every market, plan new targets for related ones (slot cap applied),
    and supersede open targets whose game start moved. Writes only what is new."""
    report: dict[str, Any] = {"planned": 0, "superseded": 0, "skipped_cap": 0, "not_planned": [],
                              "relationships": {}}
    scan = latest_usable_scan(store)
    if scan is None:
        report["state"] = "NO_CATALOG"
        return report
    age = _scan_age(scan, now)
    report["scan_id"] = scan["scan_id"]
    if age is None or age > DISCOVERY_MAX_AGE:
        report["state"] = "CATALOG_STALE"
        return report
    events, odds_meta = odds_schedule(store)
    report["odds_schedule"] = odds_meta
    odds_at = _t((odds_meta or {}).get("discovered_at_utc"))
    if odds_at is None or now - odds_at > ODDS_SCHEDULE_MAX_AGE or not events:
        report["state"] = "ODDS_SCHEDULE_MISSING_OR_STALE"
        return report
    run = run or _LazyRun(store, "pm-sports-plan")
    markets = _scan_markets(scan)
    targets = {t["target_id"]: t for t in store.pm_sports_targets()}
    slot_counts: dict[tuple[str, str], int] = {}
    for t in targets.values():
        if t["state"] not in ("SKIPPED_CAP", "SUPERSEDED"):
            key = (t["offset_label"], t["effective_utc"])
            slot_counts[key] = slot_counts.get(key, 0) + 1
    # Supersede open targets whose market now shows another game start.
    starts = {m.market_slug: _t(m.game_start_utc) for m in markets}
    for t in targets.values():
        if t["state"] not in (None, "FAILED"):
            continue
        new_start = starts.get(t["market_slug"])
        if new_start is not None and new_start != _t(t["game_start_utc"]):
            store.record_pm_sports_observation(_row(run, t, "SUPERSEDED", now, reason=(
                f"GAME_START_CHANGED: {t['game_start_utc']} -> {_iso(new_start)} in scan {scan['scan_id']}")))
            report["superseded"] += 1
    counts: dict[str, int] = {}
    new_rows: list[dict[str, Any]] = []
    for market in sorted(markets, key=lambda m: (m.game_start_utc or "", m.market_slug)):
        rel = relate(market, events)
        counts[rel.status] = counts.get(rel.status, 0) + 1
        rows, skipped = targets_for(market, rel, scan_id=scan["scan_id"], now=now)
        report["not_planned"] += [s for s in skipped if not s["reason"].startswith("NOT_RELATED")][:50]
        new_rows += [r for r in rows if r["target_id"] not in targets]
    report["relationships"] = dict(sorted(counts.items()))
    for row in sorted(new_rows, key=lambda r: (r["effective_utc"], r["priority"], r["game_start_utc"], r["market_slug"])):
        key = (row["offset_label"], row["effective_utc"])
        if not store.plan_pm_sports_target(row):
            continue
        report["planned"] += 1
        if slot_counts.get(key, 0) >= MAX_MARKETS_PER_SLOT:
            store.record_pm_sports_observation(_row(run, row, "SKIPPED_CAP", now, reason=(
                f"SLOT_CAP: {MAX_MARKETS_PER_SLOT} markets already planned for {row['offset_label']} at "
                f"{row['effective_utc']}")))
            report["skipped_cap"] += 1
        else:
            slot_counts[key] = slot_counts.get(key, 0) + 1
    report["state"] = "OK"
    return report


# --------------------------------------------------------------------------- capture


def expire(store: SnapshotStore, run: _LazyRun, now: datetime, *, catalog_stale: bool) -> list[dict[str, str]]:
    """Every open target past its deadline becomes MISSED, with why. Never fetched late."""
    missed = []
    for t in store.pm_sports_targets():
        if t["state"] not in (None, "FAILED"):
            continue
        deadline = _t(t["deadline_utc"])
        if deadline is None or now <= deadline:
            continue
        if t["state"] == "FAILED":
            reason = f"NOT_CAPTURED_BY_DEADLINE: last attempt failed ({t['state_reason']})"
        else:
            reason = f"NOT_CAPTURED_BY_DEADLINE: no capture in [{t['due_from_utc']}, {t['deadline_utc']}]"
        if catalog_stale:
            reason += "; captures paused while the NFL catalog was older than 24 h"
        hit = protected_window_at(_t(t["due_from_utc"]), deadline)
        if hit is not None:
            reason += f"; the due window overlaps protected window {hit[0]}"
        store.record_pm_sports_observation(_row(run, t, "MISSED", now, reason=reason))
        missed.append({"target_id": t["target_id"], "reason": reason})
    return missed


def _freshness(received: datetime | None, target: Mapping[str, Any]) -> str:
    if received is None:
        return Freshness.UNKNOWN.value
    due, deadline = _t(target["due_from_utc"]), _t(target["deadline_utc"])
    if due is None or deadline is None:
        return Freshness.UNKNOWN.value
    return (Freshness.FRESH if due <= received <= deadline else Freshness.STALE).value


def _levels_json(payload: Mapping[str, Any]) -> str | None:
    data = payload.get("marketData") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        return None

    def side(key: str) -> list[list[str]]:
        return [[str((lv.get("px") or {}).get("value")), str(lv.get("qty"))] for lv in data.get(key) or []
                if isinstance(lv, Mapping)]

    return json.dumps({"yes_bids": side("bids"), "yes_offers": side("offers"), "truncated": True,
                       "note": "YES book levels as the venue listed them; the docs do not say every level is returned"},
                      sort_keys=True)


def _capture_one(store: SnapshotStore, run: _LazyRun, t: Mapping[str, Any], req: _Requests, clock: Clock
                 ) -> dict[str, Any] | None:
    """One book GET for one due target. None when the request budget or deadline defers it."""
    slug = t["market_slug"]
    url = polymarket_us.book_url(slug)
    try:
        payload, result = req.get(url)
    except (RequestBudgetExhausted, DeadlineExceeded):
        return None
    except http.HttpFetchError as exc:
        now = clock()
        if exc.status == 404:
            return _row(run, t, "NOT_EXECUTABLE", now, reason=f"BOOK_NOT_FOUND: HTTP 404 for {slug} (delisted or renamed)")
        return _row(run, t, "FAILED", now, reason=f"BOOK_FAILED: {type(exc).__name__}: {exc}")
    now = clock()
    snap = store.save_snapshot(run_id=run.id(), source=SOURCE.legacy_name, kind="book", entity_id=slug, url=url,
                               payload=payload, fetch=result, source_id=SOURCE.source_id,
                               parser_version=polymarket_us.PARSER_VERSION, schema_version=SOURCE.schema_version)
    received = _t(result.received_at_utc)
    target_at = _t(t["target_utc"])
    data = payload.get("marketData") if isinstance(payload.get("marketData"), Mapping) else {}
    common = dict(snapshot_id=snap, received_at_utc=result.received_at_utc, source_sha256=bytes_sha256(result.body),
                  source_timestamp_utc=data.get("transactTime") if isinstance(data.get("transactTime"), str) else None,
                  book_state=data.get("state") if isinstance(data.get("state"), str) else None,
                  deviation_s=(received - target_at).total_seconds() if received and target_at else None,
                  freshness=_freshness(received, t))
    quotes = polymarket_us.quotes_from_book(slug, payload, received_at_utc=result.received_at_utc,
                                            evidence_id=f"snapshot:{snap}")
    if not quotes:
        return _row(run, t, "NOT_EXECUTABLE", now, reason="BOOK_MISSING: no marketData in the payload", **common)
    yes = quotes["YES"]
    if yes.anomaly:
        return _row(run, t, "NOT_EXECUTABLE", now, reason=f"BOOK_ANOMALY: {yes.anomaly}", **common)
    no = quotes["NO"]
    return _row(run, t, "CAPTURED", now, yes_bid=None if yes.best_bid is None else str(yes.best_bid),
                yes_bid_size=None if yes.best_bid is None else str(no.displayed_size),
                yes_ask=None if yes.best_ask is None else str(yes.best_ask),
                yes_ask_size=None if yes.best_ask is None else str(yes.displayed_size),
                depth_json=_levels_json(payload), **common)


def _retry_tick_before(deadline: datetime, after: datetime) -> bool:
    """Whether a later scheduled tick outside every protected window can still run before `deadline`."""
    tick = after + TICK_INTERVAL
    while tick < deadline:
        if protected_window_at(tick, tick + MAX_RUN) is None:
            return True
        tick += TICK_INTERVAL
    return False


def capture(store: SnapshotStore, *, clock: Clock | None = None, sleep: Sleep = time.sleep,
            opener: http.Opener | None = None, max_books: int = MAX_BOOKS_PER_RUN,
            max_requests: int = MAX_HTTP_REQUESTS_PER_RUN) -> tuple[int, dict[str, Any]]:
    """One bounded capture tick: plan (no network), expire, then book GETs for due targets. The
    caller holds the lock and has checked the access gate and protected windows."""
    if not 0 < max_books <= MAX_BOOKS_PER_RUN or not 0 < max_requests <= MAX_HTTP_REQUESTS_PER_RUN:
        raise ValueError(f"max_books must be in 1..{MAX_BOOKS_PER_RUN}, max_requests in 1..{MAX_HTTP_REQUESTS_PER_RUN}")
    clock = clock or _now
    now = clock()
    report: dict[str, Any] = {"command": "pm-sports capture", "now_utc": _iso(now), "policy_version": POLICY_VERSION,
                              "requests": 0, "attempted": 0, "by_status": {}, "deferred": [], "missed": []}
    run = _LazyRun(store, "pm-sports-capture")
    started = now
    try:
        report["plan"] = plan(store, now=now, run=run)
        scan = latest_usable_scan(store)
        age = _scan_age(scan, now)
        catalog_stale = age is None or age > DISCOVERY_MAX_AGE
        report["missed"] = expire(store, run, now, catalog_stale=catalog_stale)
        due = [t for t in store.pm_sports_targets() if t["state"] in (None, "FAILED")
               and _t(t["due_from_utc"]) <= now <= _t(t["deadline_utc"])]
        due.sort(key=lambda t: (t["effective_utc"], t["priority"], t["market_slug"]))
        if catalog_stale and due:
            report["deferred"] = [t["target_id"] for t in due]
            report["state"] = "CATALOG_STALE"
            run.finish("succeeded")
            return 0, report
        report["deferred"] = [t["target_id"] for t in due[max_books:]]
        due = due[:max_books]
        req = _Requests(max_requests, now + MAX_RUN, clock, sleep, http.Pacer(PACER_INTERVAL_S, sleep=sleep), opener)
        failed_targets: dict[str, Mapping[str, Any]] = {}
        for t in due:
            if clock() > _t(t["deadline_utc"]):  # never fetched late: the next tick records it MISSED
                report["deferred"].append(t["target_id"])
                continue
            row = _capture_one(store, run, t, req, clock)
            if row is None:
                report["deferred"].append(t["target_id"])
                continue
            store.record_pm_sports_observation(row)
            report["attempted"] += 1
            report["by_status"][row["status"]] = report["by_status"].get(row["status"], 0) + 1
            if row["status"] == "FAILED":
                failed_targets[t["target_id"]] = t
        report["requests"] = req.attempts
        end = clock()
        if report["attempted"]:
            failed = report["by_status"].get("FAILED", 0)
            ok = report["attempted"] - failed
            _health(store, run, source_id=HEALTH_BOOK, started=started, now=end,
                    status="failed" if failed and not ok else ("partial" if failed else "ok"), records=ok,
                    http_errors=failed, retries=max(0, req.attempts - req.calls),
                    anomalies=[f"{failed} book GET(s) failed"] if failed and ok else [],
                    error=f"{failed} of {report['attempted']} book GET(s) failed" if failed else None)
    except BaseException:
        run.finish("failed", "pm-sports capture aborted")
        raise
    failed = report["by_status"].get("FAILED", 0)
    run.finish("partial" if failed else "succeeded", f"{failed} FAILED book attempt(s)" if failed else None)
    final = sorted(i for i, t in failed_targets.items() if not _retry_tick_before(_t(t["deadline_utc"]), end))
    report["failed_final"] = final
    report["failed_retrying"] = sorted(set(failed_targets) - set(final))
    report["state"] = ("PARTIAL" if final else "PARTIAL_RETRYING") if failed else (
        "CAPTURED" if report["attempted"] else ("DEFERRED" if report["deferred"] else "NOTHING_DUE"))
    return (1 if final else 0), report


# --------------------------------------------------------------------------- runners (CLI)


def _lock_path(db: Path) -> Path:
    """The pilot's own lock (not the Kalshi collector lock; see the module docstring)."""
    return db.with_name(db.name + ".pm-sports.lock")


def protected_refusal(now: datetime, command: str) -> dict[str, Any] | None:
    hit = protected_window_at(now, now + MAX_RUN)
    if hit is None:
        return None
    return {"command": command, "now_utc": _iso(now), "state": "DEFERRED_PROTECTED_WINDOW", "requests": 0,
            "detail": f"[{iso_z(now)}, +{int(MAX_RUN.total_seconds())} s] overlaps {hit[0]} "
                      f"({iso_z(hit[1])} to {iso_z(hit[2])}): no network, no writes"}


def access_refusal(command: str, access_decision: str | None) -> dict[str, Any] | None:
    if access_decision:
        return None
    return {"command": command, "state": "BLOCKED_TERMS_REVIEW", "requests": 0,
            "detail": (f"unattended Polymarket US collection is not cleared by the terms review ({TERMS_REVIEW}); "
                       "an owner decision must be recorded and referenced in polymarket_sports.OWNER_ACCESS_DECISION. "
                       "No network, no writes.")}


def _run(command: str, db: Path, body: Callable[[SnapshotStore], tuple[int, dict[str, Any]]], *, clock: Clock,
         access_decision: str | None) -> tuple[int, dict[str, Any]]:
    refusal = access_refusal(command, access_decision)
    if refusal is not None:
        return 0, refusal
    refusal = protected_refusal(clock(), command)
    if refusal is not None:  # before the lock: nothing is opened inside a protected window
        return 0, refusal
    if not db.is_file():
        return 0, {"command": command, "state": "NO_STORE", "detail": f"{db} does not exist; nothing created"}
    try:
        with exclusive_lock(_lock_path(db), timeout_s=LOCK_TIMEOUT_S):
            code, report = body(SnapshotStore(db))
    except LockBusy as exc:
        return 0, {"command": command, "state": "LOCK_BUSY", "detail": str(exc)}
    report["access_decision"] = access_decision
    return code, report


def run_discover(db: str | Path, *, clock: Clock | None = None, sleep: Sleep = time.sleep,
                 opener: http.Opener | None = None, force: bool = False,
                 access_decision: str | None = OWNER_ACCESS_DECISION) -> tuple[int, dict[str, Any]]:
    """`pm-sports discover`: access gate, protected windows, lock, cadence, one bounded scan."""
    clock = clock or _now
    return _run("pm-sports discover", Path(db),
                lambda store: discover(store, clock=clock, sleep=sleep, opener=opener, force=force),
                clock=clock, access_decision=access_decision)


def run_capture(db: str | Path, *, clock: Clock | None = None, sleep: Sleep = time.sleep,
                opener: http.Opener | None = None, max_books: int = MAX_BOOKS_PER_RUN,
                max_requests: int = MAX_HTTP_REQUESTS_PER_RUN,
                access_decision: str | None = OWNER_ACCESS_DECISION) -> tuple[int, dict[str, Any]]:
    """`pm-sports capture`: access gate, protected windows, lock, one bounded capture tick."""
    clock = clock or _now
    return _run("pm-sports capture", Path(db),
                lambda store: capture(store, clock=clock, sleep=sleep, opener=opener, max_books=max_books,
                                      max_requests=max_requests),
                clock=clock, access_decision=access_decision)


# --------------------------------------------------------------------------- read-only views


def _latest_capture(store: SnapshotStore, target_ids: Sequence[str]) -> dict[str, Any] | None:
    best = None
    for tid in target_ids:
        for r in store.pm_sports_observations(target_id=tid):
            if r["status"] == "CAPTURED" and (best is None or r["received_at_utc"] > best["received_at_utc"]):
                best = r
    if best is None:
        return None
    return {"target_id": best["target_id"], "received_at_utc": best["received_at_utc"],
            "source_timestamp_utc": best["source_timestamp_utc"], "yes_bid": best["yes_bid"],
            "yes_bid_size": best["yes_bid_size"], "yes_ask": best["yes_ask"], "yes_ask_size": best["yes_ask_size"],
            "book_state": best["book_state"], "snapshot_id": best["snapshot_id"], "freshness": best["freshness"],
            "label": RESEARCH_LABEL, "executable": False}


def related_markets(store: SnapshotStore, *, now: datetime) -> dict[str, Any]:
    """Read-only: for every Odds API NFL event in the latest stored schedule, the related Polymarket
    US market(s) from the latest usable scan. The public function the Terminal calls (Lane D).

    Per event `state` is RELATED_NOT_EQUIVALENT, AMBIGUOUS or NO_RELATED_MARKET. NO_RELATED_MARKET
    is never evidence of absence: `absence_is_evidence` is always False, and the catalog state says
    how much was read. Nothing here is executable, ranked or compared with a sportsbook price."""
    scan = latest_usable_scan(store)
    events, odds_meta = odds_schedule(store)
    out: dict[str, Any] = {"label": LABEL, "executable": False, "ranked": False, "absence_is_evidence": False,
                           "odds_schedule": odds_meta, "catalog": catalog_state(store, now=now), "events": {}}
    markets = _scan_markets(scan) if scan is not None else []
    targets_by_market: dict[str, list[str]] = {}
    for t in store.pm_sports_targets():
        targets_by_market.setdefault(t["market_slug"], []).append(t["target_id"])
    by_event: dict[str, list[dict[str, Any]]] = {}
    for m in markets:
        rel = relate(m, events)
        entry = {"market_slug": m.market_slug, "title": m.title, "game_start_utc": m.game_start_utc,
                 "long_side": m.long_team, "short_side": m.short_team, "relationship": rel.status,
                 "reasons": list(rel.reasons), "flags": list(rel.flags), "checks": rel.checks,
                 "payoff_kind": m.payoff_kind, "rules_sha256": m.rules_sha256, "label": LABEL, "equivalent": False,
                 "latest_capture": _latest_capture(store, targets_by_market.get(m.market_slug, []))}
        keys = [rel.odds_event_id] if rel.status == RELATED else (list(rel.candidates) if rel.status == AMBIGUOUS else [])
        for key in keys:
            by_event.setdefault(key, []).append(entry)
    for e in events:
        rows = by_event.get(e.event_id, [])
        state = (RELATED if any(r["relationship"] == RELATED for r in rows)
                 else AMBIGUOUS if rows else "NO_RELATED_MARKET")
        out["events"][e.event_id] = {"odds_event_id": e.event_id, "commence_utc": iso_z(e.commence_utc),
                                     "home_team": e.home_team, "away_team": e.away_team, "state": state,
                                     "markets": rows}
    return out


def catalog_state(store: SnapshotStore, *, now: datetime) -> dict[str, Any]:
    """The discovery state for display: NO_SCAN, FAILED, PARTIAL_CATALOG, STALE or FILTER_COMPLETE."""
    scans = store.pm_sports_scans(league=LEAGUE, limit=1)
    usable = latest_usable_scan(store)
    if not scans:
        return {"state": "NO_SCAN", "detail": "no discovery scan yet"}
    last = scans[0]
    age = _scan_age(usable, now) if usable is not None else None
    if usable is None:
        state = "FAILED"
    elif age is None or age > DISCOVERY_MAX_AGE:
        state = "STALE"
    elif not int(usable["filter_complete"]):
        state = "PARTIAL_CATALOG"
    else:
        state = "FILTER_COMPLETE"
    return {"state": state, "last_attempt_utc": last["completed_at_utc"], "last_attempt_coverage": last["coverage_state"],
            "last_attempt_detail": last["coverage_detail"],
            "usable_scan_id": usable["scan_id"] if usable is not None else None,
            "usable_scan_utc": usable["completed_at_utc"] if usable is not None else None,
            "age_minutes": None if age is None else round(age.total_seconds() / 60, 1),
            "filter": dict(DISCOVERY_FILTER), "markets": int(usable["markets"]) if usable is not None else None,
            "coverage_note": "filtered NFL moneyline listing: never a full-catalog COMPLETE; absence is not evidence"}


def market_history(store: SnapshotStore, market_slug: str) -> list[dict[str, Any]]:
    """Every target and attempt of one market, by intended time (research evidence, not prices to act on)."""
    out = []
    for t in store.pm_sports_targets(market_slug=market_slug):
        attempts = [dict(r) for r in store.pm_sports_observations(target_id=t["target_id"])]
        out.append({"target_id": t["target_id"], "offset": t["offset_label"], "target_utc": t["target_utc"],
                    "effective_utc": t["effective_utc"], "due_from_utc": t["due_from_utc"],
                    "deadline_utc": t["deadline_utc"], "state": t["state"] or "PLANNED",
                    "relationship": t["relationship"], "odds_event_id": t["odds_event_id"], "attempts": attempts,
                    "label": RESEARCH_LABEL})
    return out


def status(store: SnapshotStore, *, now: datetime, access_decision: str | None = OWNER_ACCESS_DECISION) -> dict[str, Any]:
    """Read-only summary: gate, catalog, targets by offset and state, next due, recent misses."""
    by_offset: dict[str, dict[str, int]] = {}
    upcoming, misses = [], []
    for t in store.pm_sports_targets():
        state = t["state"] or "PLANNED"
        if state in ("PLANNED", "FAILED") and _t(t["deadline_utc"]) < now:
            state = "OVERDUE"
        by_offset.setdefault(t["offset_label"], {})
        by_offset[t["offset_label"]][state] = by_offset[t["offset_label"]].get(state, 0) + 1
        if state in ("PLANNED", "FAILED"):
            upcoming.append({"target_id": t["target_id"], "due_from_utc": t["due_from_utc"],
                             "deadline_utc": t["deadline_utc"], "state": state})
        if state == "MISSED":
            misses.append({"target_id": t["target_id"], "reason": t["state_reason"], "at_utc": t["state_at_utc"]})
    due, next_due = discovery_due(store, now)
    return {"command": "pm-sports status", "now_utc": _iso(now), "policy_version": POLICY_VERSION,
            "access": "CLEARED" if access_decision else "BLOCKED_TERMS_REVIEW", "access_decision": access_decision,
            "catalog": catalog_state(store, now=now), "discovery_due": due, "discovery_next_due_utc": next_due,
            "targets_by_offset": dict(sorted(by_offset.items())),
            "next_due": sorted(upcoming, key=lambda u: u["due_from_utc"])[:10],
            "recent_misses": sorted(misses, key=lambda m: m["at_utc"] or "")[-10:]}


def terminal_view(db_path: str | Path, *, now: datetime,
                  access_decision: str | None = OWNER_ACCESS_DECISION) -> dict[str, Any]:
    """What the Terminal shows (read-only, network-free, never raises): schema pm-sports-status/1.
    `state`: BLOCKED_TERMS_REVIEW, NO_STORE, ERROR, NO_SCAN, or the catalog state."""
    out: dict[str, Any] = {"schema": DASHBOARD_SCHEMA, "as_of_utc": iso_z(now), "label": LABEL,
                           "access": "CLEARED" if access_decision else "BLOCKED_TERMS_REVIEW", "executable": False}
    try:
        store = SnapshotStore.open_readonly(db_path)
    except ReadOnlyStoreError as exc:
        out.update(state="NO_STORE", detail=str(exc))
        return out
    except Exception as exc:  # noqa: BLE001 - an unreadable file is shown as ERROR, never raised
        out.update(state="ERROR", detail=f"evidence store unreadable: {type(exc).__name__}")
        return out
    try:
        out["status"] = status(store, now=now, access_decision=access_decision)
        out["related"] = related_markets(store, now=now)
    except Exception as exc:  # noqa: BLE001 - shown, never repaired here
        out.update(state="ERROR", detail=f"{type(exc).__name__}: {exc}")
        return out
    out["state"] = "BLOCKED_TERMS_REVIEW" if not access_decision else out["status"]["catalog"]["state"]
    return out


# --------------------------------------------------------------------------- Freshness Fabric provider


def _discovery_health(scans: Sequence[Any]) -> str:
    if not scans:
        return "UNKNOWN"
    last = scans[0]
    if last["coverage_state"] == "FAILED":
        return "FAILING"
    return "OK" if int(last["filter_complete"]) else "DEGRADED"


def freshness_records(store: SnapshotStore, *, now: datetime,
                      access_decision: str | None = OWNER_ACCESS_DECISION) -> list[dict[str, Any]]:
    """The two sources this pilot owns, one record each at `now`, as plain values: discovery
    (acquired by POLL) and research book captures (EVENT_RELATIVE), both run by their own timers
    (fabric mode EXTERNAL_SCHEDULE). `fabric_provider` turns them
    into `freshness.SourceFreshness` (contract C1). Unknown stays None; missing is never zero."""
    due, next_due = discovery_due(store, now)
    cat = catalog_state(store, now=now)
    scans = store.pm_sports_scans(league=LEAGUE, limit=1)
    usable = latest_usable_scan(store)
    blocked = not access_decision
    protected = protected_window_at(now, now + MAX_RUN)
    disc_received = usable["completed_at_utc"] if usable is not None else None
    disc_age = None if usable is None else now - _t(disc_received)
    disc_max_age = get_source(HEALTH_DISCOVERY).max_age["nfl_events"]
    disc_fresh = (Freshness.UNKNOWN if disc_age is None else
                  Freshness.FRESH if disc_age <= disc_max_age else Freshness.STALE)
    if blocked:
        disc_state, disc_why = "PAUSED", f"BLOCKED_TERMS_REVIEW: {TERMS_REVIEW}"
    elif due and protected is not None:
        disc_state, disc_why = "PROTECTED_WINDOW", f"due, but inside {protected[0]}: runs refuse it"
    elif due:
        disc_state, disc_why = "DUE", ("no scan on record" if not scans else
                                       f"the last attempt is at least {int(DISCOVERY_INTERVAL.total_seconds() // 3600)} h old")
    else:
        disc_state, disc_why = "NOT_DUE", f"next scan after {next_due} (paced on the last attempt)"
    discovery = {
        "source_id": HEALTH_DISCOVERY, "domain": "sports", "mode": "EXTERNAL_SCHEDULE", "acquisition_mode": "POLL",
        "policy": {"max_useful_age_s": int(disc_max_age.total_seconds()),
                   "min_safe_cadence_s": int(DISCOVERY_INTERVAL.total_seconds()),
                   "max_useful_cadence_s": int(DISCOVERY_INTERVAL.total_seconds()), "policy_version": POLICY_VERSION},
        "intended_utc": next_due, "next_due_utc": None if blocked else next_due,
        "last_attempt_utc": scans[0]["completed_at_utc"] if scans else None,
        "last_success_utc": disc_received, "upstream_utc": None, "receipt_utc": disc_received,
        "data_age_s": None if disc_age is None else int(disc_age.total_seconds()),
        "health": _discovery_health(scans), "catalog_state": cat["state"], "freshness": disc_fresh.value,
        "schedule_state": disc_state, "why": disc_why, "missed_count": None, "recent_misses": [],
        "controls": {"pacer_s": PACER_INTERVAL_S, "max_http_requests": 2 * MAX_DISCOVERY_PAGES,
                     "max_pages": MAX_DISCOVERY_PAGES, "retries": RETRIES, "protected_windows": "price_observations",
                     "lock": "<db>.pm-sports.lock", "run_deadline_s": int(MAX_RUN.total_seconds())}}
    targets = store.pm_sports_targets()
    open_targets = sorted((t for t in targets if t["state"] in (None, "FAILED") and _t(t["deadline_utc"]) >= now),
                          key=lambda t: t["due_from_utc"])
    overdue = [t for t in targets if t["state"] in (None, "FAILED") and _t(t["deadline_utc"]) < now]
    nxt = open_targets[0] if open_targets else None
    captured = [t for t in targets if t["state"] == "CAPTURED"]
    last_capture = max((t["state_at_utc"] for t in captured), default=None)
    attempted = sorted((t for t in targets if t["state"] in ("CAPTURED", "FAILED", "NOT_EXECUTABLE", "MISSED")),
                       key=lambda t: t["state_at_utc"] or "")
    missed = sorted((t for t in targets if t["state"] == "MISSED"), key=lambda t: t["state_at_utc"] or "")
    if blocked:
        sched, why = "PAUSED", f"BLOCKED_TERMS_REVIEW: {TERMS_REVIEW}"
    elif nxt is not None and _t(nxt["due_from_utc"]) <= now and protected is not None:
        sched, why = "PROTECTED_WINDOW", f"{nxt['target_id']} is due, but inside {protected[0]}: runs refuse it"
    elif nxt is not None and _t(nxt["due_from_utc"]) <= now:
        sched, why = "DUE", f"{nxt['target_id']} is inside its due window"
    elif overdue:
        sched, why = "MISSED", f"{len(overdue)} open target(s) passed their deadline (the next tick marks them MISSED)"
    else:
        sched, why = "NOT_DUE", (f"next target {nxt['target_id']} due from {nxt['due_from_utc']}" if nxt is not None
                                 else "no open target; targets come from discovery and the Odds API schedule")
    last_status = attempted[-1]["state"] if attempted else None
    book_max_age = get_source(HEALTH_BOOK).max_age["book"]
    capture_age = None if last_capture is None else now - _t(last_capture)
    capture = {
        "source_id": HEALTH_BOOK, "domain": "sports", "mode": "EXTERNAL_SCHEDULE",
        "acquisition_mode": "EVENT_RELATIVE",
        "policy": {"max_useful_age_s": int(book_max_age.total_seconds()),
                   "min_safe_cadence_s": int(TICK_INTERVAL.total_seconds()),
                   "max_useful_cadence_s": int(TICK_INTERVAL.total_seconds()), "policy_version": POLICY_VERSION,
                   "offsets": [o.label for o in OFFSETS]},
        "intended_utc": nxt["target_utc"] if nxt is not None else None,
        "next_due_utc": None if blocked or nxt is None else nxt["due_from_utc"],
        "last_attempt_utc": attempted[-1]["state_at_utc"] if attempted else None, "last_attempt_status": last_status,
        "last_success_utc": last_capture, "upstream_utc": None, "receipt_utc": last_capture,
        "data_age_s": None if capture_age is None else int(capture_age.total_seconds()),
        "health": "UNKNOWN" if last_status is None else "DEGRADED" if last_status in ("FAILED", "MISSED") else "OK",
        # Event-relative: each capture is judged against its own due window (the row's freshness);
        # this rolling age against the registered book max_age says only how old the newest book is.
        "freshness": (Freshness.UNKNOWN if capture_age is None else
                      Freshness.FRESH if capture_age <= book_max_age else Freshness.STALE).value,
        "schedule_state": sched, "why": why, "missed_count": len(missed),
        "recent_misses": [f"{t['target_id']}: {t['state_reason']}" for t in missed[-5:]],
        "controls": {"pacer_s": PACER_INTERVAL_S, "max_books_per_run": MAX_BOOKS_PER_RUN,
                     "max_http_requests_per_run": MAX_HTTP_REQUESTS_PER_RUN, "max_markets_per_slot": MAX_MARKETS_PER_SLOT,
                     "retries": RETRIES, "protected_windows": "price_observations", "lock": "<db>.pm-sports.lock",
                     "run_deadline_s": int(MAX_RUN.total_seconds())}}
    return [discovery, capture]


def fabric_policies() -> tuple[Any, Any]:
    """The two `freshness.SourcePolicy` records this provider declares (discovery, capture).
    Built on call, so this module imports without the Freshness Fabric types.

    Fabric v1 rule (ADR 0031): a registered source is observed as EXTERNAL_SCHEDULE, because its
    own systemd timer runs it; the acquisition style is the `underlying_mode` (POLL for discovery,
    EVENT_RELATIVE for the captures)."""
    from .freshness import AcquisitionMode, SourcePolicy
    from .price_observations import PROTECTED_WINDOWS_ET

    windows = tuple(f"{name} {a:%H:%M}-{b:%H:%M} America/New_York" for name, a, b in PROTECTED_WINDOWS_ET)
    gate = f"; disabled until an owner access decision ({TERMS_REVIEW})"
    return (
        SourcePolicy(
            source_id=HEALTH_DISCOVERY, domain="sports", mode=AcquisitionMode.EXTERNAL_SCHEDULE,
            underlying_mode=AcquisitionMode.POLL,
            description="Polymarket US NFL moneyline discovery (a filtered /v1/events listing, never a full-catalog "
                        "COMPLETE); objective: the registered nfl_events max_age" + gate,
            policy_version=POLICY_VERSION,
            schedule_owner="systemd edgelab-pm-sports-discover.timer (proposed, not installed) + "
                           "edge_lab.polymarket_sports.discover",
            max_useful_age=get_source(HEALTH_DISCOVERY).max_age["nfl_events"],
            min_safe_cadence=DISCOVERY_INTERVAL, max_useful_cadence=DISCOVERY_INTERVAL,
            pacing=f"{PACER_INTERVAL_S:g} s between requests; at most {MAX_DISCOVERY_PAGES} pages per scan",
            budget=f"at most {2 * MAX_DISCOVERY_PAGES} HTTP requests per scan, retries included",
            protected_windows=windows,
            retry=f"{RETRIES} retry per request (429, 5xx, network); a failed scan is retried after 6 h"),
        SourcePolicy(
            source_id=HEALTH_BOOK, domain="sports", mode=AcquisitionMode.EXTERNAL_SCHEDULE,
            underlying_mode=AcquisitionMode.EVENT_RELATIVE,
            description="Polymarket US NFL research book captures at T-24h / T-6h / T-60m for markets related (never "
                        "equivalent) to an Odds API event; objective: the registered book max_age" + gate,
            policy_version=POLICY_VERSION,
            schedule_owner="systemd edgelab-pm-sports.timer :10/:25/:40/:55 America/New_York (proposed, not "
                           "installed) + edge_lab.polymarket_sports.capture",
            max_useful_age=get_source(HEALTH_BOOK).max_age["book"],
            min_safe_cadence=TICK_INTERVAL, max_useful_cadence=TICK_INTERVAL,
            pacing=f"{PACER_INTERVAL_S:g} s between requests; own lock <db>.pm-sports.lock",
            budget=(f"at most {MAX_BOOKS_PER_RUN} books and {MAX_HTTP_REQUESTS_PER_RUN} HTTP requests per run; "
                    f"{MAX_MARKETS_PER_SLOT} markets per slot"),
            protected_windows=windows,
            retry="a FAILED target is retried by a later tick until its deadline, then MISSED; never fetched late"),
    )


FABRIC_PROVIDER_NAME = "polymarket_us_nfl_pilot"  # the registry entry's name


def fabric_provider(context: Any, now: datetime) -> list[Any]:
    """Freshness Fabric provider (contract C1: `provider(context, now) -> list[SourceFreshness]`).
    Reads `context.db` read-only: no network, no lock, no write. A missing or unreadable store is
    reported as UNKNOWN, never raised into the supervisor."""
    from .freshness import Freshness as F, ScheduleState, SourceFreshness, SourceHealth, policy_freshness

    disc_policy, cap_policy = fabric_policies()
    db = getattr(context, "db", None)

    def unknown(policy: Any, why: str) -> Any:
        return SourceFreshness(policy=policy, as_of=now, freshness=F.UNKNOWN, schedule_state=ScheduleState.UNKNOWN,
                               health=SourceHealth.UNKNOWN, why_due=why)

    if db is None or not Path(db).is_file():
        why = "evidence store not configured" if db is None else "evidence store does not exist"
        return [unknown(disc_policy, why), unknown(cap_policy, why)]
    try:
        disc, cap = freshness_records(SnapshotStore.open_readonly(db), now=now)
    except Exception as exc:  # noqa: BLE001 - reported as UNKNOWN; the supervisor must not fail on it
        why = f"evidence store unreadable ({type(exc).__name__})"
        return [unknown(disc_policy, why), unknown(cap_policy, why)]
    out = []
    for policy, rec, label in ((disc_policy, disc, LABEL), (cap_policy, cap, RESEARCH_LABEL)):
        receipt = _t(rec["receipt_utc"])
        out.append(SourceFreshness(
            policy=policy, as_of=now, freshness=policy_freshness(policy, receipt, now),
            schedule_state=ScheduleState(rec["schedule_state"]), health=SourceHealth(rec["health"]),
            why_due=rec["why"][:300], intended_at=_t(rec["intended_utc"]), next_due=_t(rec["next_due_utc"]),
            last_attempt=_t(rec["last_attempt_utc"]), last_success_receipt=_t(rec["last_success_utc"]),
            receipt_ts=receipt, missed_count=rec["missed_count"],
            recent_misses=tuple(m[:200] for m in rec["recent_misses"]),
            usable_for_research=receipt is not None, usable_for_decision=False,
            notes=(label, "the pilot timers are proposed and not installed; their state is not observable here"),
            details={k: rec[k] for k in ("catalog_state", "last_attempt_status") if k in rec}))
    return out


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    """`edge-lab pm-sports {discover,capture,status}`. Prints one JSON report."""
    parser = argparse.ArgumentParser(prog="edge-lab pm-sports",
                                     description="Polymarket US NFL research pilot (ADR 0032): read-only, bounded.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover", help="One bounded NFL moneyline discovery scan (at most every 6 h), then planning.")
    d.add_argument("--db", default="data/edge_lab.sqlite3")
    d.add_argument("--force", action="store_true", help="ignore the 6-hour cadence (never the gate or windows)")
    c = sub.add_parser("capture", help="One bounded capture tick of due research book targets.")
    c.add_argument("--db", default="data/edge_lab.sqlite3")
    c.add_argument("--max-books", type=int, default=MAX_BOOKS_PER_RUN)
    c.add_argument("--max-requests", type=int, default=MAX_HTTP_REQUESTS_PER_RUN)
    s = sub.add_parser("status", help="Read-only: gate, catalog, targets, related markets.")
    s.add_argument("--db", default="data/edge_lab.sqlite3")
    s.add_argument("--market", help="also print one market's targets and attempts (Polymarket US slug)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.cmd == "discover":
        code, report = run_discover(args.db, force=args.force)
    elif args.cmd == "capture":
        code, report = run_capture(args.db, max_books=args.max_books, max_requests=args.max_requests)
    else:
        now = _now()
        try:
            store = SnapshotStore.open_readonly(args.db)
        except ReadOnlyStoreError as exc:
            print(json.dumps({"command": "pm-sports status", "state": "NO_STORE", "detail": str(exc)}))
            return 1
        report = status(store, now=now)
        report["related"] = related_markets(store, now=now)
        if args.market:
            report["market_history"] = market_history(store, args.market)
        code = 0
    print(json.dumps(report, sort_keys=True, indent=2, default=str))
    return code


__all__ = [
    "AMBIGUOUS", "LABEL", "NflMarket", "RELATED", "Relationship", "UNMATCHED", "capture", "catalog_from_events",
    "catalog_state", "discover", "fabric_policies", "fabric_provider", "freshness_records", "main", "market_history", "plan",
    "related_markets", "relate", "rules_clauses", "run_capture", "run_discover", "status", "terminal_view",
]
