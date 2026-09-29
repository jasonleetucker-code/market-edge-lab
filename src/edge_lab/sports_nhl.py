"""NHL identity, rules and schedule for the Kalshi KXNHLGAME prospective evidence collector (NHL-B, ADR 0040).

**DATA_COLLECTION / DEVELOPMENT_ONLY.** NHL is not EXP-002 and not a research family (owner directive
2026-09-29, issue #134). Nothing here joins NHL rows into `sports_evidence`, models a winner or compares a
price with anything. Pure functions and read-only store reads: no network, no writes.

What lives here (the planner and capture live in `price_observations`, the per-series sports policy):

- **Scope.** `KXNHLGAME` (full-game winner) only. Every other hockey family (`KXNHL...`: totals, periods,
  props, futures, next-team) fails closed (`hockey_family`), and so does anything that is not a hockey ticker.
- **Identity.** A versioned 32-team table: The Odds API full name -> (Kalshi ticker abbreviation, Kalshi
  market label). The abbreviations and labels are Kalshi's, as its public KXNHLGAME listing showed them on
  2026-09-29 (all 32 teams listed; `tests/fixtures/sports_nhl/`). Kalshi's abbreviations differ from
  NHL.com's for four teams (LA/LAK, SJ/SJS, TB/TBL, NJ/NJD). The Odds API names are **not yet verified**
  against a stored `icehockey_nhl` discovery (none existed when this was written): a name outside the table
  (or its listed aliases) is UNMAPPED and counted, never guessed.
- **Tickers.** `KXNHLGAME-<YY><MON><DD><AWAY><HOME>-<TEAM>`: the game's originally scheduled America/New_York
  date, then the away and home abbreviations run together (lengths 2-3 vary, e.g. `LASJ`, `TBNYR`), then
  the market's team. The pair is split only when exactly one split into two known abbreviations exists;
  otherwise the ticker is UNKNOWN_TEAM or AMBIGUOUS_SPLIT.
- **Rules.** Matched literally from the market's rules text (`nhl_rules_clauses`), never interpreted
  further; the contract-terms reading (overtime, shootout, ties) is recorded separately in
  `CONTRACT_TERMS_READING` with its VERIFIED / RULES_UNRESOLVED status.
- **Schedule.** The stored The Odds API quota-free `events` discovery for `icehockey_nhl`, read the way
  `odds_pilot` reads the NFL one (source `the_odds_api`, kind `events`, entity the sport key), point in time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from . import odds_api
from .forward import eastern_offset
from .freshness import parse_utc
from .odds_schedule import ScheduledEvent

UTC = timezone.utc

NHL_SERIES = "KXNHLGAME"
NHL_SPORT = "icehockey_nhl"
HOCKEY_SERIES_PREFIX = "KXNHL"  # every Kalshi NHL series: KXNHLGAME is the only admitted one
MAPPING_VERSION = "kalshi-nhl-mapping-v1"
RULES_PARSER_VERSION = "kalshi-nhl-rules-v1"
ODDS_SOURCE = odds_api.get_source(odds_api.SOURCE_ID).legacy_name  # "the_odds_api": where discoveries are stored
DISCOVERY_KIND = "events"

# The Odds API full name -> (Kalshi ticker abbreviation, Kalshi market label). Kalshi side: its public KXNHLGAME
# listing of 2026-09-29 (yes_sub_title of each team market). A name not in this table (or in the aliases below)
# never maps.
NHL_TEAMS: dict[str, tuple[str, str]] = {
    "Anaheim Ducks": ("ANA", "Anaheim"), "Boston Bruins": ("BOS", "Boston"),
    "Buffalo Sabres": ("BUF", "Buffalo"), "Calgary Flames": ("CGY", "Calgary"),
    "Carolina Hurricanes": ("CAR", "Carolina"), "Chicago Blackhawks": ("CHI", "Chicago"),
    "Colorado Avalanche": ("COL", "Colorado"), "Columbus Blue Jackets": ("CBJ", "Columbus"),
    "Dallas Stars": ("DAL", "Dallas"), "Detroit Red Wings": ("DET", "Detroit"),
    "Edmonton Oilers": ("EDM", "Edmonton"), "Florida Panthers": ("FLA", "Florida"),
    "Los Angeles Kings": ("LA", "Los Angeles"), "Minnesota Wild": ("MIN", "Minnesota"),
    "Montréal Canadiens": ("MTL", "Montreal"), "Nashville Predators": ("NSH", "Nashville"),
    "New Jersey Devils": ("NJ", "New Jersey"), "New York Islanders": ("NYI", "New York I"),
    "New York Rangers": ("NYR", "New York R"), "Ottawa Senators": ("OTT", "Ottawa"),
    "Philadelphia Flyers": ("PHI", "Philadelphia"), "Pittsburgh Penguins": ("PIT", "Pittsburgh"),
    "San Jose Sharks": ("SJ", "San Jose"), "Seattle Kraken": ("SEA", "Seattle"),
    "St Louis Blues": ("STL", "St. Louis"), "Tampa Bay Lightning": ("TB", "Tampa Bay"),
    "Toronto Maple Leafs": ("TOR", "Toronto"), "Utah Mammoth": ("UTA", "Utah"),
    "Vancouver Canucks": ("VAN", "Vancouver"), "Vegas Golden Knights": ("VGK", "Vegas"),
    "Washington Capitals": ("WSH", "Washington"), "Winnipeg Jets": ("WPG", "Winnipeg"),
}
# Other spellings of the same franchise (accents, punctuation, the pre-2025 Utah name). Each maps to exactly one
# table entry, so an alias can never make a match ambiguous.
NHL_TEAM_ALIASES: dict[str, str] = {
    "Montreal Canadiens": "Montréal Canadiens", "St. Louis Blues": "St Louis Blues",
    "Utah Hockey Club": "Utah Mammoth",
}
# NHL.com abbreviations that differ from Kalshi's (the schedule API uses NHL.com's).
NHL_COM_TO_KALSHI = {"LAK": "LA", "SJS": "SJ", "TBL": "TB", "NJD": "NJ"}
KALSHI_ABBRS = frozenset(abbr for abbr, _ in NHL_TEAMS.values())
_BY_ABBR = {abbr: name for name, (abbr, _) in NHL_TEAMS.items()}
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_EVENT = re.compile(r"^KXNHLGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z]{4,6})$")

assert len(NHL_TEAMS) == 32 and len(KALSHI_ABBRS) == 32
assert all(v in NHL_TEAMS for v in NHL_TEAM_ALIASES.values())


def et_date(instant: datetime) -> date:
    return (instant + eastern_offset(instant)).date()


def team(name: Any) -> tuple[str, str] | None:
    """(Kalshi abbreviation, Kalshi label) of an Odds API team name, or None (UNMAPPED, never guessed)."""
    if not isinstance(name, str):
        return None
    return NHL_TEAMS.get(NHL_TEAM_ALIASES.get(name, name))


def hockey_family(ticker: Any) -> str | None:
    """"ADMITTED" for a KXNHLGAME ticker (series exactly KXNHLGAME), "NOT_ADMITTED" for any other Kalshi NHL
    family (KXNHLTOTAL, KXNHLGOAL, period, props, futures, a look-alike such as KXNHLGAMEX), None when it is not a
    Kalshi NHL ticker at all. Unknown hockey families fail closed: only ADMITTED is ever collected."""
    text = str(ticker or "")
    if not text.startswith(HOCKEY_SERIES_PREFIX):
        return None
    return "ADMITTED" if text.split("-", 1)[0] == NHL_SERIES else "NOT_ADMITTED"


def split_teams(letters: str) -> tuple[tuple[str, str] | None, str | None]:
    """((away, home), None) when exactly one split of `letters` into two known Kalshi abbreviations exists,
    else (None, "UNKNOWN_TEAM" | "AMBIGUOUS_SPLIT")."""
    splits = [(letters[:i], letters[i:]) for i in range(1, len(letters))
              if letters[:i] in KALSHI_ABBRS and letters[i:] in KALSHI_ABBRS]
    if len(splits) == 1:
        return splits[0], None
    return None, "UNKNOWN_TEAM" if not splits else "AMBIGUOUS_SPLIT"


def parse_ticker(ticker: Any) -> tuple[dict[str, Any] | None, str | None]:
    """A KXNHLGAME market (`...-NYR`) or event ticker -> (parsed, None), or (None, problem code). Honest failure:
    NOT_HOCKEY, FAMILY_NOT_ADMITTED, MALFORMED, BAD_DATE, UNKNOWN_TEAM, AMBIGUOUS_SPLIT, SIDE_NOT_IN_GAME."""
    text = str(ticker or "")
    family = hockey_family(text)
    if family is None:
        return None, "NOT_HOCKEY"
    if family != "ADMITTED":
        return None, "FAMILY_NOT_ADMITTED"
    parts = text.split("-")
    if len(parts) not in (2, 3):
        return None, "MALFORMED"
    event = "-".join(parts[:2])
    m = _EVENT.match(event)
    if not m or m.group(2) not in _MONTHS:
        return None, "MALFORMED"
    try:
        day = date(2000 + int(m.group(1)), _MONTHS.index(m.group(2)) + 1, int(m.group(3)))
    except ValueError:
        return None, "BAD_DATE"
    pair, problem = split_teams(m.group(4))
    if pair is None:
        return None, problem
    side = parts[2] if len(parts) == 3 else None
    if side is not None and side not in pair:
        return None, "SIDE_NOT_IN_GAME"
    return {"event_ticker": event, "date": day, "away": pair[0], "home": pair[1], "team": side,
            "away_team": _BY_ABBR[pair[0]], "home_team": _BY_ABBR[pair[1]]}, None


def event_ticker(away_abbr: str, home_abbr: str, day: date) -> str:
    """KXNHLGAME-<YY><MON><DD><AWAY><HOME>, the date being the game's originally scheduled New York date."""
    ticker = f"{NHL_SERIES}-{day:%y}{_MONTHS[day.month - 1]}{day.day:02d}{away_abbr}{home_abbr}"
    parsed, problem = parse_ticker(ticker)
    if parsed is None:  # a hard scope guard: never plan a ticker this module cannot read back
        raise ValueError(f"not a parseable {NHL_SERIES} ticker: {ticker} ({problem})")
    return ticker


# --------------------------------------------------------------------------- rules (literal)

_WINS = re.compile(r"\bIf\s+(.+?)\s+wins\s+the\s+(.+?)\s+NHL\s+game\b", re.IGNORECASE)
_ORIGINAL = re.compile(r"originally\s+scheduled\s+for\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})")
_POSTPONE = re.compile(r"postponed\s+but\s+begins\s+within\s+(\d+)\s+hours", re.IGNORECASE)
_FINAL = re.compile(r"official\s+final\s+result", re.IGNORECASE)
_FALLBACK = re.compile(r"cancelled\s+or\s+not\s+started\s+within\s+(\d+)\s+hours[^.]*?resolve\s+to\s+a\s+fair\s+price",
                       re.IGNORECASE)
_OVERTIME = re.compile(r"overtime", re.IGNORECASE)
_SHOOTOUT = re.compile(r"shoot-?out", re.IGNORECASE)
_TIE = re.compile(r"\btie\b|\bdraw", re.IGNORECASE)


def nhl_rules_clauses(primary: str | None, secondary: str | None) -> dict[str, Any]:
    """What a KXNHLGAME market's rules text states, matched literally. A clause not found stays None; `resolved`
    needs the win condition, the official-final-result basis, the postponement window and the fair-price fallback.

    Overtime, shootout and ties are **not stated** in the market rules text (checked on all 86 open markets on
    2026-09-29): each is UNSTATED here, whatever the contract terms say (`CONTRACT_TERMS_READING`)."""
    text = f"{primary or ''}\n{secondary or ''}"
    wins, post, fb, orig = _WINS.search(primary or ""), _POSTPONE.search(text), _FALLBACK.search(text), \
        _ORIGINAL.search(text)
    clauses: dict[str, Any] = {
        "win_condition": "TEAM_WINS_GAME" if wins else None,
        "official_final_result": True if _FINAL.search(text) else None,
        "postponement_window_hours": int(post.group(1)) if post else None,
        "not_started_fallback": f"FAIR_PRICE_AFTER_{fb.group(1)}H" if fb else None,
        "originally_scheduled": orig.group(1) if orig else None,
        "overtime": "MENTIONED" if _OVERTIME.search(text) else "UNSTATED",
        "shootout": "MENTIONED" if _SHOOTOUT.search(text) else "UNSTATED",
        "tie": "MENTIONED" if _TIE.search(text) else "UNSTATED",
        "parser_version": RULES_PARSER_VERSION,
    }
    missing = [k for k in ("win_condition", "official_final_result", "postponement_window_hours",
                           "not_started_fallback") if clauses[k] is None]
    clauses["missing"] = missing
    clauses["resolved"] = not missing
    return clauses


# The series' contract terms (GET /series/KXNHLGAME contract_terms_url, read 2026-09-29, 3 pages, sha256
# 4243633b6c7f2b19ccf67384d3a79bab1a497cd64fbc4730a0de689e8f6d2983). The document is the generic
# "HOCKEYWINNINGINPERIOD" rulebook. Recorded as readings with a status; nothing here resolves a payoff.
CONTRACT_TERMS_URL = "https://assets.kalshi.com/contract_terms/HOCKEYWINNINGINPERIOD.pdf"
CONTRACT_TERMS_SHA256 = "4243633b6c7f2b19ccf67384d3a79bab1a497cd64fbc4730a0de689e8f6d2983"
CONTRACT_TERMS_READING: dict[str, dict[str, str]] = {
    "overtime": {
        "status": "VERIFIED",
        "reading": "INCLUDED: the terms define the entire game (the default time period) as regulation time plus "
                   "overtime, and goals in regulation and overtime count",
        "source": "contract terms, <time period> and Underlying"},
    "shootout": {
        "status": "RULES_UNRESOLVED",
        "reading": "The market rule says the team 'wins the ... game' on the official final result; the terms define "
                   "winning by goals within regulation plus overtime and never mention a shootout. Whether a "
                   "shootout winner resolves Yes is the likely reading, not a stated rule",
        "source": "market rules_primary / rules_secondary; contract terms, Payout Criterion"},
    "tie": {
        "status": "RULES_UNRESOLVED",
        "reading": "No tie payout is stated for KXNHLGAME. The terms say a drawn team's contract 'may' resolve No; "
                   "a regular-season NHL game has no tie under league rules, which is a league fact, not a Kalshi "
                   "statement",
        "source": "contract terms, Payout Criterion"},
    "postponement": {
        "status": "VERIFIED",
        "reading": "stays open and resolves on the official final result if the game begins within 48 h of its "
                   "originally scheduled start",
        "source": "market rules_secondary"},
    "not_started_or_cancelled": {
        "status": "VERIFIED",
        "reading": "all markets resolve to a fair price if the game is cancelled or not started within 48 h",
        "source": "market rules_secondary"},
    "official_final_result": {
        "status": "VERIFIED",
        "reading": "the event and series metadata list NHL and ESPN without an order; the order (the governing "
                   "league first, then ESPN, then Fox Sports and the official broadcaster) is the contract terms' "
                   "Source Agency list, stated as hierarchical",
        "source": "event and series settlement_sources; contract terms, Source Agency"},
}
# Fees: the series metadata says fee_type quadratic_with_maker_fees, fee_multiplier 1 (2026-09-29). No verification
# record covers KXNHLGAME, so NHL evidence records FEE_UNSUPPORTED and prices nothing; never a zero fee.
FEE_STATE = "FEE_UNSUPPORTED"
FEE_DETAIL = ("KXNHLGAME fees are unverified: the series metadata reads fee_type quadratic_with_maker_fees, "
              "fee_multiplier 1 (2026-09-29), but no fee verification record covers the series; nothing is priced "
              "and no fee is ever set to 0")
NATIVE_UNITS = "Kalshi contracts: $1.00 notional binary (notional_value_dollars), prices in dollars, linear_cent grid"


# --------------------------------------------------------------------------- schedule (stored discovery)


@dataclass(frozen=True)
class NhlSchedule:
    """The newest stored `icehockey_nhl` discovery received at or before `as_of` (point in time).

    `state`: OK, STALE (older than `max_age`: planning refuses it), NO_DISCOVERY or UNREADABLE."""

    state: str
    as_of: datetime
    snapshot_id: int | None = None
    received_utc: datetime | None = None
    events: tuple[ScheduledEvent, ...] = ()
    problems: tuple[str, ...] = ()
    detail: str | None = None
    # The discovery's requested commence window (its stored `request` context), or None when not recorded. Only
    # inside a known window does an event's absence mean anything (a dropped or moved game).
    window_from: datetime | None = None
    window_to: datetime | None = None

    @property
    def usable(self) -> bool:
        return self.state == "OK"

    def covers(self, commence: datetime) -> bool:
        """Whether this discovery's requested window is known and contains `commence`."""
        if self.window_from is None or self.window_to is None:
            return False
        return self.window_from <= commence <= self.window_to


SCHEDULE_PAGE = 1000


def read_schedule(store: Any, now: datetime, *, max_age: timedelta) -> NhlSchedule:
    """The newest NHL discovery received at or before `now`. Read-only; one payload parsed."""
    cursor, newest = None, None
    while True:
        page = store.snapshot_metadata(source=ODDS_SOURCE, kinds=(DISCOVERY_KIND,), entity_prefix=NHL_SPORT,
                                       limit=SCHEDULE_PAGE, after_id=cursor)
        for r in page:
            at = parse_utc(r["fetched_at_utc"])
            if r["entity_id"] == NHL_SPORT and at is not None and at <= now:
                newest = r
        if len(page) < SCHEDULE_PAGE:
            break
        cursor = int(page[-1]["id"])
    if newest is None:
        return NhlSchedule("NO_DISCOVERY", now, detail="no icehockey_nhl discovery stored at or before now")
    sid = int(newest["id"])
    received = parse_utc(newest["fetched_at_utc"])
    row = store.snapshots_by_id([sid]).get(sid)
    try:
        payload = json.loads(row["payload_json"]) if row is not None else None
    except ValueError:
        payload = None
    if not isinstance(payload, Mapping):
        return NhlSchedule("UNREADABLE", now, sid, received, detail=f"discovery snapshot {sid} is not a JSON object")
    if not isinstance(payload.get("events"), list):
        return NhlSchedule("UNREADABLE", now, sid, received, detail=f"discovery snapshot {sid} holds no events list")
    events, problems = odds_api.parse_events(payload.get("events"), sport=NHL_SPORT)
    request = payload.get("request") if isinstance(payload.get("request"), Mapping) else {}
    lo, hi = parse_utc(request.get("commence_from")), parse_utc(request.get("commence_to"))
    # Age on the discovering tick's clock (`request.tick_utc`) when recorded, else the receipt: the rule
    # `odds_pilot._discovered_at` uses for its own planning (the two agree in production).
    stamped = parse_utc(request.get("tick_utc"))
    if stamped is not None and stamped <= now:
        received = stamped
    state = "OK" if now - received <= max_age else "STALE"
    detail = None if state == "OK" else (f"newest discovery {sid} received {received.isoformat()} is older than "
                                         f"{int(max_age.total_seconds() // 3600)} h")
    return NhlSchedule(state, now, sid, received, events, problems, detail, lo, hi)


# --------------------------------------------------------------------------- listings (stored, point in time)


def listing_problem(markets: Mapping[str, Mapping[str, Any]], expected: Mapping[str, str], commence: datetime,
                    *, occurrence_offset: timedelta, tolerance: timedelta) -> str | None:
    """Why a stored KXNHLGAME event listing does not identify the Odds event, or None. `expected` is
    {market ticker: Kalshi label}. The listing's occurrence_datetime was the start + 3 h for every game listed
    on 2026-09-29 (an observation, not documentation): a listing whose occurrence is further than `tolerance`
    from commence + `occurrence_offset` is a different game, so the match is AMBIGUOUS (never guessed)."""
    for ticker in expected:
        occ = parse_utc((markets.get(ticker) or {}).get("occurrence_datetime"))
        if occ is not None and abs(occ - (commence + occurrence_offset)) > tolerance:
            minutes, hours = int(tolerance.total_seconds() // 60), int(occurrence_offset.total_seconds() // 3600)
            return (f"COMMENCE_MISMATCH: {ticker} occurrence {occ.isoformat()} is not within {minutes} min of "
                    f"commence + {hours} h")
    return None


__all__ = [
    "CONTRACT_TERMS_READING", "FEE_STATE", "HOCKEY_SERIES_PREFIX", "NHL_SERIES", "NHL_SPORT", "NHL_TEAMS", "NhlSchedule",
    "event_ticker", "hockey_family", "nhl_rules_clauses", "parse_ticker", "read_schedule", "split_teams", "team",
]

