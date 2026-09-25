"""Family A paired evidence: sportsbook consensus vs Kalshi NFL moneyline books (Economic Evidence v1).

PAIRED RESEARCH EVIDENCE — NOT AN EDGE CLAIM. Read-only, network-free and bounded. Nothing here makes a
request, spends an Odds credit, writes to a store, models a winner or recommends a trade.

**What it joins.** For every NFL Odds capture target (`odds_capture_targets`, ADR 0029: T-24h / T-6h /
T-60m before kickoff) it pairs:

- the sportsbook side: the stored Odds API snapshot the runner recorded for *that* target, read through
  the canonical consensus (`odds_consensus.build_snapshot_consensus`: exact-line two-way proportional
  de-vig, median across books). Only the h2h (moneyline) proposition is used. It is a RESEARCH BENCHMARK:
  a two-way de-vig whose books' tie/void rules are not in the data, so it is read as a probability
  conditional on a decided game (tie treatment UNVERIFIED), never as an unconditional team-win probability;
- the exchange side: stored Kalshi `KXNFLGAME` listings (rules, tickers, status, result) and order books
  (`snapshots`, source `kalshi`, kinds `markets` / `event` / `events` / `settled_markets` / `orderbook`,
  the shapes `forward._save` and `price_observations` already write). None exist in production today;
  the report then says exactly what is missing (`gaps`) instead of inventing a dataset;
- related, never equivalent: Polymarket US captures of markets `polymarket_sports` related to the same
  Odds event are listed with their relationship (RELATED_NOT_EQUIVALENT) and are excluded from every
  comparison.

**Point in time.** A horizon's decision cutoff is the pilot's own canonical capture deadline
(`odds_schedule.deadline`: effective due + 30 min, never later than kickoff - 5 min). Only evidence
received at or before the cutoff (and at or before the report's `as_of`) is used. The Kalshi book is the
one received closest to the odds receipt within `max_pair_skew` (ties: the earlier one); a book outside
that window is PAIR_SKEW_EXCEEDED and a book after the cutoff is never substituted for a missing one. The
pair's decision time is the later of the two receipts; both inputs' freshness is judged there
(`freshness.assess` / `combine`, the rule `odds_consensus` uses). Source update times (book
`last_update` bounds) are kept apart from receipt times and from the pair skew.

**Mapping and rules.** An Odds event maps to a Kalshi event only when the exact team set (a versioned
32-team table) and the America/New_York game date in the ticker agree; anything else is UNMATCHED,
AMBIGUOUS or NOT_IN_LISTINGS_READ (a partial listing never implies "no market"). Kalshi's rules text is
matched literally (tie payout, postponement window, fair-price fallback, official final result). With
those clauses the relation is CONDITIONAL_MAPPING: the same game and team, but the payoffs differ in the
tie and not-played states, so it supports calibration / markout research with an explicit declared bound
and never an equivalent-payoff edge claim. Missing clauses are RULES_UNRESOLVED.

**Denominators and attrition.** Events, Kalshi markets, horizon targets and snapshots are counted
separately. Each due target falls in exactly one primary bucket (a fixed stage order), and keeps every
raw reason. Targets whose cutoff is after `as_of` are NOT_YET_DUE, never missed; superseded (rescheduled)
targets are their own bucket. No signal rule is registered, so signal / fill counts are NOT_EVALUATED
(None), not zero.

**Outcomes** are labels attached at `as_of` from stored Kalshi listings: PENDING, PRELIMINARY
(determined), FINAL (settled / finalized), CORRECTED (a later capture disagrees), UNKNOWN. A final winner
never says whether an order would have filled.

**Economics** stay a thin, honest adapter until Writer 1's research_economics contract lands: a size
ladder over the captured depth (complete vs truncated, `opportunity.walk_ladder`), two named fill
assumptions (ESTIMATED), fees from `fee_schedules` (KXNFLGAME is on Kalshi's non-standard list, so
FEE_UNSUPPORTED and no all-in cost), lockup from the listing's expiration times. Edge at a size is
NOT_DEFENSIBLE with its reasons; visible depth is never capacity; nothing is annualised.

Clusters for later statistics: the game (Odds event id) and the NFL week (Tuesday-anchored ET week).
Delayed-signal and placebo control references are listed per row for the protocol to use; this module
computes no statistic from them.

CLI (read-only): `python -m edge_lab.sports_evidence report --db <path> [--as-of ISO] [--out FILE]`.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import uuid
from collections import OrderedDict
from contextlib import closing
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qs, urlsplit

from . import fee_schedules, kalshi_quotes, odds_consensus
from .forward import eastern_offset
from .freshness import Freshness, assess, combine, parse_utc
from .odds_schedule import CaptureTarget, PilotConfig, deadline, effective_due
from .opportunity import DepthStatus, price_depth_fill, walk_ladder
from .provenance import canonical_json, sha256_hex
from .sources import get_source

UTC = timezone.utc
SCHEMA = "sports-paired-evidence/1"
VIEW_SCHEMA = "sports-evidence-view/1"
JOIN_VERSION = "sports-paired-join-v1"
MAPPING_VERSION = "kalshi-nfl-mapping-v1"
RULES_PARSER_VERSION = "kalshi-nfl-rules-v1"
LABEL = "PAIRED RESEARCH EVIDENCE — NOT AN EDGE CLAIM"
FAMILY_ID = "A"
FAMILY_TITLE = "Sportsbook consensus vs Kalshi NFL moneyline (pregame)"
SPORT = "americanfootball_nfl"
ODDS_MARKET = "h2h"
KALSHI_SERIES = "KXNFLGAME"
KALSHI_SOURCE = get_source("kalshi_public")
KALSHI = KALSHI_SOURCE.legacy_name
KALSHI_BOOK_MAX_AGE = KALSHI_SOURCE.max_age["orderbook"]
ODDS_SOURCE = odds_consensus.SOURCE
LISTING_KINDS = ("markets", "event", "events", "settled_markets")
PILOT_CONFIG = PilotConfig()  # the runner's defaults (odds_pilot.RunnerSettings().config)

# Bounds: a whole NFL season is about 285 games x 3 horizons.
MAX_TARGETS = 1500
MAX_KALSHI_ROWS = 50_000
MAX_LISTING_PARSES = 600
PARSE_CACHE = 8
STALE_AFTER = timedelta(days=8)  # no new evidence for longer than an NFL week while targets fell due

# Relation tiers and probability meanings (to be mapped onto Writer 1's shared contract, PR B).
REL_CONDITIONAL = "CONDITIONAL_MAPPING"
REL_RULES_UNRESOLVED = "RULES_UNRESOLVED"
REL_PAYOFF_UNSUPPORTED = "PAYOFF_UNSUPPORTED"
REL_RELATED = "RELATED_NOT_EQUIVALENT"
PROB_CONSENSUS = "SPORTSBOOK_CONSENSUS_TWO_WAY_DEVIG"
PROB_MARKET = "MARKET_EXECUTABLE_ASK"

# Evidence classes for every economics input (strategy §6).
OBSERVED, ESTIMATED, OWNER_INPUT, UNKNOWN = "OBSERVED", "ESTIMATED", "OWNER_INPUT", "UNKNOWN"


class Stage(str, Enum):
    """Primary exclusion order for a due target (the first failing stage wins; every reason is kept)."""

    ODDS_NOT_CAPTURED = "ODDS_NOT_CAPTURED"
    ODDS_CAPTURE_UNUSABLE = "ODDS_CAPTURE_UNUSABLE"
    CONSENSUS_NOT_SUPPORTED = "CONSENSUS_NOT_SUPPORTED"
    ODDS_NOT_FRESH = "ODDS_NOT_FRESH"
    KALSHI_NOT_MAPPED = "KALSHI_NOT_MAPPED"
    KALSHI_RULES_UNRESOLVED = "KALSHI_RULES_UNRESOLVED"
    KALSHI_BOOK_MISSING = "KALSHI_BOOK_MISSING"
    PAIR_SKEW_EXCEEDED = "PAIR_SKEW_EXCEEDED"
    KALSHI_BOOK_UNUSABLE = "KALSHI_BOOK_UNUSABLE"


STAGE_ORDER = tuple(Stage)
DATA_GAP_STAGES = (Stage.ODDS_NOT_CAPTURED, Stage.KALSHI_NOT_MAPPED, Stage.KALSHI_BOOK_MISSING)
PAIRED, PARTIAL_PAIR = "PAIRED", "PARTIAL_PAIR"
NOT_YET_DUE, SUPERSEDED = "NOT_YET_DUE", "SUPERSEDED"
STAGE_TEXT = {
    Stage.ODDS_NOT_CAPTURED: "no Odds capture recorded for this horizon",
    Stage.ODDS_CAPTURE_UNUSABLE: "the recorded Odds capture cannot be used (hash, format, absent game or late)",
    Stage.CONSENSUS_NOT_SUPPORTED: "no two-book moneyline consensus at this capture",
    Stage.ODDS_NOT_FRESH: "a contributing book was stale or undated at receipt",
    Stage.KALSHI_NOT_MAPPED: "no Kalshi KXNFLGAME event mapped from listings known by the cutoff",
    Stage.KALSHI_RULES_UNRESOLVED: "the Kalshi rules text lacks a recognised tie / postponement clause",
    Stage.KALSHI_BOOK_MISSING: "no Kalshi book received by the cutoff for this game",
    Stage.PAIR_SKEW_EXCEEDED: "Kalshi books exist, but none within the pair-skew limit of the odds receipt",
    Stage.KALSHI_BOOK_UNUSABLE: "the paired Kalshi book is malformed, crossed, empty or stale at decision time",
}


class Outcome(str, Enum):
    PENDING = "OUTCOME_PENDING"
    PRELIMINARY = "OUTCOME_PRELIMINARY"
    FINAL = "OUTCOME_FINAL"
    CORRECTED = "OUTCOME_CORRECTED"
    UNKNOWN = "OUTCOME_UNKNOWN"


FINAL_OUTCOMES = (Outcome.FINAL, Outcome.CORRECTED)

# The 32 NFL teams: The Odds API full name -> (Kalshi ticker abbreviation, Kalshi market label).
# Abbreviations and labels as Kalshi's KXNFLGAME listing showed them on 2026-09-25 (docs/research/
# SPORTS_PAIRED_EVIDENCE_GAPS.md, "Verification reads"). A name not in this table never maps.
NFL_TEAMS: dict[str, tuple[str, str]] = {
    "Arizona Cardinals": ("ARI", "Arizona"), "Atlanta Falcons": ("ATL", "Atlanta"),
    "Baltimore Ravens": ("BAL", "Baltimore"), "Buffalo Bills": ("BUF", "Buffalo"),
    "Carolina Panthers": ("CAR", "Carolina"), "Chicago Bears": ("CHI", "Chicago"),
    "Cincinnati Bengals": ("CIN", "Cincinnati"), "Cleveland Browns": ("CLE", "Cleveland"),
    "Dallas Cowboys": ("DAL", "Dallas"), "Denver Broncos": ("DEN", "Denver"),
    "Detroit Lions": ("DET", "Detroit"), "Green Bay Packers": ("GB", "Green Bay"),
    "Houston Texans": ("HOU", "Houston"), "Indianapolis Colts": ("IND", "Indianapolis"),
    "Jacksonville Jaguars": ("JAC", "Jacksonville"), "Kansas City Chiefs": ("KC", "Kansas City"),
    "Las Vegas Raiders": ("LV", "Las Vegas"), "Los Angeles Chargers": ("LAC", "Los Angeles C"),
    "Los Angeles Rams": ("LAR", "Los Angeles R"), "Miami Dolphins": ("MIA", "Miami"),
    "Minnesota Vikings": ("MIN", "Minnesota"), "New England Patriots": ("NE", "New England"),
    "New Orleans Saints": ("NO", "New Orleans"), "New York Giants": ("NYG", "New York G"),
    "New York Jets": ("NYJ", "New York J"), "Philadelphia Eagles": ("PHI", "Philadelphia"),
    "Pittsburgh Steelers": ("PIT", "Pittsburgh"), "San Francisco 49ers": ("SF", "San Francisco"),
    "Seattle Seahawks": ("SEA", "Seattle"), "Tampa Bay Buccaneers": ("TB", "Tampa Bay"),
    "Tennessee Titans": ("TEN", "Tennessee"), "Washington Commanders": ("WAS", "Washington"),
}
_BY_ABBR = {abbr: name for name, (abbr, _) in NFL_TEAMS.items()}
_MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
                                           "NOV", "DEC"))}
_TICKER = re.compile(r"^KXNFLGAME-(\d{2})([A-Z]{3})(\d{2})([A-Z]{4,6})-([A-Z]{2,3})$")


# --------------------------------------------------------------------------- policy


@dataclass(frozen=True)
class JoinPolicy:
    """Every parameter of the join; a change is a registered variant, never a quiet improvement."""

    max_pair_skew: timedelta = KALSHI_BOOK_MAX_AGE  # the stricter of the two sources' max ages (5 min)
    # Declared protocol inputs, UNKNOWN (None) by default: the probability bounds of a tie and of a game
    # not started within Kalshi's postponement window. Without both, no tie-adjusted comparison exists.
    tie_probability_bound: Decimal | None = None
    postponement_probability_bound: Decimal | None = None
    # Size ladder in contracts: scenario sizes, not a recommendation or a bankroll.
    size_ladder: tuple[Decimal, ...] = (Decimal(1), Decimal(10), Decimal(25), Decimal(100), Decimal(250))
    conservative_top_fraction: Decimal = Decimal("0.5")
    version: str = JOIN_VERSION

    def __post_init__(self) -> None:
        if self.max_pair_skew <= timedelta(0):
            raise ValueError("max_pair_skew must be positive")
        for name in ("tie_probability_bound", "postponement_probability_bound"):
            v = getattr(self, name)
            if v is not None and not (isinstance(v, Decimal) and Decimal(0) <= v <= Decimal(1)):
                raise ValueError(f"{name} must be a Decimal in [0, 1] or None")
        if not self.size_ladder or any(not isinstance(q, Decimal) or q <= 0 for q in self.size_ladder):
            raise ValueError("size_ladder needs positive Decimal sizes")
        if not Decimal(0) < self.conservative_top_fraction <= Decimal(1):
            raise ValueError("conservative_top_fraction must be in (0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "max_pair_skew_seconds": int(self.max_pair_skew.total_seconds()),
                "tie_probability_bound": _s(self.tie_probability_bound),
                "postponement_probability_bound": _s(self.postponement_probability_bound),
                "size_ladder": [_s(q) for q in self.size_ladder],
                "conservative_top_fraction": _s(self.conservative_top_fraction),
                "cutoff_rule": "odds_schedule.deadline (effective due + late tolerance, <= kickoff - min lead)",
                "odds_max_age_seconds": int(odds_consensus.ODDS_MAX_AGE.total_seconds()),
                "kalshi_book_max_age_seconds": int(KALSHI_BOOK_MAX_AGE.total_seconds())}


FILL_ASSUMPTIONS = (
    {"id": "visible_full_depth_v1", "basis": ESTIMATED, "kind": "LESS_CONSERVATIVE",
     "text": "every captured level at the book's receipt fills at its own price (an optimistic, instantaneous "
             "ceiling: visible depth is not capacity; impact and queue position are unknown)"},
    {"id": "top_level_fraction_v1", "basis": ESTIMATED, "kind": "CONSERVATIVE",
     "text": "only the best ask level fills, at most the policy fraction of its displayed size; nothing deeper"},
)


# --------------------------------------------------------------------------- small helpers


def _s(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return "0" if value == 0 else format(value.normalize() if value == value.to_integral_value() else value, "f")
    return str(value)


def _iso(value: Any) -> str | None:
    parsed = value if isinstance(value, datetime) else parse_utc(value)
    return None if parsed is None else parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return _s(value)
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, timedelta):
        return int(value.total_seconds())
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_plain(v) for v in value]
        return sorted(items, key=lambda x: json.dumps(x, sort_keys=True)) if isinstance(value, (set, frozenset)) \
            else items
    return value


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def et_date(instant: datetime) -> date:
    return (instant + eastern_offset(instant)).date()


def week_cluster(commence: datetime) -> str:
    """The NFL week a kickoff belongs to: the America/New_York week starting on Tuesday (Thursday to
    Monday games, plus any Tuesday/Wednesday game, share one week)."""
    d = et_date(commence)
    return f"nfl-week-of-{(d - timedelta(days=(d.weekday() - 1) % 7)).isoformat()}"


def parse_ticker(ticker: str) -> dict[str, Any] | None:
    """KXNFLGAME-26SEP24ATLGB-GB -> event ticker, ticker date, team letters and this market's team."""
    m = _TICKER.match(ticker or "")
    if not m or m.group(2) not in _MONTHS:
        return None
    try:
        day = date(2000 + int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)))
    except ValueError:
        return None
    return {"event_ticker": ticker.rsplit("-", 1)[0], "date": day, "letters": m.group(4), "team": m.group(5)}


# --------------------------------------------------------------------------- Kalshi rules (literal)

_TIE = re.compile(r"ends\s+in\s+a\s+tie[^.]*?resolve\s+to\s+\$?\s*(\d*\.\d+|\d+)", re.IGNORECASE)
_POSTPONE = re.compile(r"postponed\s+but\s+begins\s+within\s+(\d+)\s+hours", re.IGNORECASE)
_FALLBACK = re.compile(r"not\s+started\s+within\s+(\d+)\s+hours[^.]*?resolve\s+to\s+a\s+fair\s+price", re.IGNORECASE)
_FINAL = re.compile(r"official\s+final\s+result", re.IGNORECASE)
_OVERTIME = re.compile(r"overtime", re.IGNORECASE)
_ORIGINAL = re.compile(r"originally\s+scheduled\s+for\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})")
_WINS = re.compile(r"\bwins\b", re.IGNORECASE)


def rules_clauses(primary: str | None, secondary: str | None) -> dict[str, Any]:
    """What a KXNFLGAME market's rules text states, matched literally (never interpreted further). A
    clause not found stays None; `resolved` needs the win condition, the tie payout, the postponement
    window and the not-started fallback."""
    text = f"{primary or ''}\n{secondary or ''}"
    tie, post, fb = _TIE.search(text), _POSTPONE.search(text), _FALLBACK.search(text)
    orig = _ORIGINAL.search(text)
    clauses = {
        "win_condition": "TEAM_WINS_GAME" if primary and _WINS.search(primary) else None,
        "tie_payout": _s(_dec(tie.group(1))) if tie else None,
        "postponement_window_hours": int(post.group(1)) if post else None,
        "not_started_fallback": f"FAIR_PRICE_AFTER_{fb.group(1)}H" if fb else None,
        "official_final_result": bool(_FINAL.search(text)),
        "overtime": "MENTIONED" if _OVERTIME.search(text) else "UNSTATED",
        "originally_scheduled": orig.group(1) if orig else None,
        "parser_version": RULES_PARSER_VERSION,
    }
    missing = [k for k in ("win_condition", "tie_payout", "postponement_window_hours", "not_started_fallback")
               if clauses[k] is None]
    clauses["missing"] = missing
    clauses["resolved"] = not missing
    return clauses


def relation_for(market: Mapping[str, Any] | None, clauses: Mapping[str, Any] | None) -> dict[str, Any]:
    """How a KXNFLGAME YES contract relates to the sportsbook moneyline consensus for the same team."""
    if market is None:
        return {"tier": None, "equivalent": False, "reasons": ["no Kalshi market mapped"]}
    notional = _dec(market.get("notional_value_dollars"))
    if str(market.get("market_type") or "").lower() != "binary" or (notional is not None and notional != 1):
        return {"tier": REL_PAYOFF_UNSUPPORTED, "equivalent": False,
                "reasons": [f"market_type {market.get('market_type')!r}, notional {market.get('notional_value_dollars')!r}: "
                            "not a $1 binary contract"]}
    if not clauses or not clauses.get("resolved"):
        return {"tier": REL_RULES_UNRESOLVED, "equivalent": False,
                "reasons": ["rules clauses not found: " + ", ".join((clauses or {}).get("missing") or ["rules text"])]}
    return {
        "tier": REL_CONDITIONAL, "equivalent": False,
        "consensus_meaning": PROB_CONSENSUS + " (tie/void treatment of the books UNVERIFIED: read as P(win | game "
                                              "decided))",
        "market_meaning": PROB_MARKET + f" (YES pays $1 on a win, ${clauses['tie_payout']} on a tie, a fair price if "
                                        f"not started within {clauses['postponement_window_hours']} h)",
        "reasons": ["same game and team; payoffs differ in the tie and not-played states, so the consensus is not the "
                    "contract's fair value without declared tie and postponement bounds",
                    "supports calibration / markout research only; never an equivalent-payoff edge claim"]}


def tie_adjusted_interval(p: Decimal | None, tie_payout: Decimal | None, tie_bound: Decimal | None,
                          post_bound: Decimal | None) -> tuple[Decimal, Decimal] | None:
    """The contract fair value implied by consensus p under declared bounds, exactly: YES pays 1 on a win
    (probability (1 - t - u) p), `tie_payout` on a tie (t), an unknown fair price F in [0, 1] if not played
    (u). Linear in t, u and F, so the corners give the interval. None when any input is unknown."""
    if p is None or tie_payout is None or tie_bound is None or post_bound is None:
        return None
    if tie_bound + post_bound > 1:
        return None
    values = [(1 - t - u) * p + tie_payout * t + u * f
              for t in (Decimal(0), tie_bound) for u in (Decimal(0), post_bound) for f in (Decimal(0), Decimal(1))]
    return min(values), max(values)


# --------------------------------------------------------------------------- store reads (metadata first)


def _meta_rows(store: Any, sql: str, params: Sequence[Any]) -> list[Any]:
    """Metadata-only reads over the store's own read-only connection (`open_readonly`: mode=ro,
    query_only), as `odds_consensus._index` does: the store has no public metadata read and storage.py is
    another writer's file (a shared-contract request is recorded in the PR)."""
    with closing(store._connect()) as conn:
        return conn.execute(sql, list(params)).fetchall()


@dataclass
class _Payloads:
    """One payload in memory at a time per lookup; a small LRU of parsed payloads by snapshot id."""

    store: Any
    cache: "OrderedDict[int, Any]" = field(default_factory=OrderedDict)
    loads: int = 0

    def row(self, sid: int) -> Any:
        return self.store.snapshots_by_id([sid]).get(sid)

    def payload(self, sid: int) -> tuple[Any, str | None]:
        """(parsed payload or None, problem). The stored hash is checked; a mismatch is never used."""
        if sid in self.cache:
            self.cache.move_to_end(sid)
            return self.cache[sid]
        row = self.row(sid)
        self.loads += 1
        if row is None:
            out: tuple[Any, str | None] = (None, f"SNAPSHOT_MISSING: snapshot {sid} not found")
        elif sha256_hex(row["payload_json"]) != row["payload_sha256"]:
            out = (None, f"PAYLOAD_HASH_MISMATCH: snapshot {sid} does not match its stored sha256; not used")
        else:
            try:
                out = (json.loads(row["payload_json"]), None)
            except ValueError:
                out = (None, f"PAYLOAD_UNPARSEABLE: snapshot {sid}")
        self.cache[sid] = out
        while len(self.cache) > PARSE_CACHE:
            self.cache.popitem(last=False)
        return out


@dataclass(frozen=True)
class KalshiMarketObs:
    """One KXNFLGAME market as one stored listing snapshot saw it (only the fields the join reads)."""

    ticker: str
    event_ticker: str
    received: datetime
    snapshot_id: int
    payload_sha256: str
    kind: str
    complete_series_listing: bool
    fields: dict[str, Any]
    settlement_sources: tuple[str, ...]


_MARKET_FIELDS = ("status", "result", "market_type", "notional_value_dollars", "rules_primary", "rules_secondary",
                  "yes_sub_title", "no_sub_title", "expected_expiration_time", "latest_expiration_time",
                  "close_time", "can_close_early", "price_ranges", "price_level_structure", "settlement_value_dollars",
                  "expiration_value", "occurrence_datetime")


@dataclass
class KalshiCatalog:
    listings: dict[str, list[KalshiMarketObs]]  # ticker -> observations, oldest first
    books: dict[str, list[tuple[datetime, int, str, str]]]  # ticker -> (received, id, url, sha), oldest first
    listing_snapshots: int
    book_snapshots: int
    parsed_listings: int
    truncated: bool
    problems: list[str]

    def known(self, ticker: str, by: datetime) -> list[KalshiMarketObs]:
        return [o for o in self.listings.get(ticker, []) if o.received <= by]

    def latest(self, ticker: str, by: datetime) -> KalshiMarketObs | None:
        known = self.known(ticker, by)
        return known[-1] if known else None

    def events_known(self, by: datetime) -> dict[str, dict[str, KalshiMarketObs]]:
        out: dict[str, dict[str, KalshiMarketObs]] = {}
        for ticker in sorted(self.listings):
            obs = self.latest(ticker, by)
            if obs is not None:
                out.setdefault(obs.event_ticker, {})[ticker] = obs
        return out

    def complete_listing_known(self, by: datetime) -> bool:
        return any(o.complete_series_listing and o.received <= by for obs in self.listings.values() for o in obs)


def _markets_in(payload: Any) -> tuple[list[tuple[Mapping[str, Any], tuple[str, ...]]], bool]:
    """(markets with their event's settlement-source names, cursor exhausted) from any listing shape."""
    out: list[tuple[Mapping[str, Any], tuple[str, ...]]] = []
    if not isinstance(payload, Mapping):
        return out, False

    def sources(ev: Any) -> tuple[str, ...]:
        rows = ev.get("settlement_sources") if isinstance(ev, Mapping) else None
        return tuple(str(s.get("name")) for s in rows or [] if isinstance(s, Mapping) and s.get("name"))
    top = sources(payload.get("event"))
    for m in payload.get("markets") or []:
        if isinstance(m, Mapping):
            out.append((m, top))
    for ev in payload.get("events") or []:
        if isinstance(ev, Mapping):
            for m in ev.get("markets") or []:
                if isinstance(m, Mapping):
                    out.append((m, sources(ev)))
    return out, not payload.get("cursor")


def kalshi_catalog(store: Any, as_of: datetime, payloads: _Payloads) -> KalshiCatalog:
    """Every stored KXNFLGAME listing and book received by `as_of`: metadata by SQL, listings parsed
    (bounded), books left unparsed until the join selects one."""
    kinds = ",".join("?" * len(LISTING_KINDS))
    rows = _meta_rows(store, f"""
        SELECT id, kind, entity_id, fetched_at_utc, url, payload_sha256 FROM snapshots
        WHERE source = ? AND ((kind = 'orderbook' AND entity_id LIKE ?) OR (kind IN ({kinds}) AND entity_id LIKE ?))
        ORDER BY id LIMIT ?""", [KALSHI, f"{KALSHI_SERIES}-%", *LISTING_KINDS, f"{KALSHI_SERIES}%",
                                 MAX_KALSHI_ROWS + 1])
    truncated = len(rows) > MAX_KALSHI_ROWS
    rows = rows[:MAX_KALSHI_ROWS]
    listings: dict[str, list[KalshiMarketObs]] = {}
    books: dict[str, list[tuple[datetime, int, str, str]]] = {}
    problems: list[str] = []
    listing_rows = []
    for r in rows:
        received = parse_utc(r["fetched_at_utc"])
        if received is None or received > as_of:
            continue
        if r["kind"] == "orderbook":
            books.setdefault(str(r["entity_id"]), []).append((received, int(r["id"]), str(r["url"] or ""),
                                                              str(r["payload_sha256"])))
        else:
            listing_rows.append((received, r))
    parsed = 0
    for received, r in sorted(listing_rows, key=lambda x: (x[0], int(x[1]["id"])))[-MAX_LISTING_PARSES:]:
        payload, problem = payloads.payload(int(r["id"]))
        parsed += 1
        if problem:
            problems.append(problem)
            continue
        markets, exhausted = _markets_in(payload)
        complete = str(r["entity_id"]) == KALSHI_SERIES and exhausted and r["kind"] in ("events", "markets")
        for m, srcs in markets:
            ticker = m.get("ticker")
            parsed_ticker = parse_ticker(ticker) if isinstance(ticker, str) else None
            if parsed_ticker is None:
                continue
            listings.setdefault(ticker, []).append(KalshiMarketObs(
                ticker, parsed_ticker["event_ticker"], received, int(r["id"]), str(r["payload_sha256"]), str(r["kind"]),
                complete, {k: m.get(k) for k in _MARKET_FIELDS if k in m}, srcs))
    if len(listing_rows) > MAX_LISTING_PARSES:
        truncated = True
        problems.append(f"LISTINGS_TRUNCATED: only the newest {MAX_LISTING_PARSES} of {len(listing_rows)} listing "
                        "snapshots were parsed")
    for obs in listings.values():
        obs.sort(key=lambda o: (o.received, o.snapshot_id))
    for b in books.values():
        b.sort()
    return KalshiCatalog(listings, books, len(listing_rows), sum(len(b) for b in books.values()), parsed, truncated,
                         problems)


# --------------------------------------------------------------------------- mapping


def map_event(home: str | None, away: str | None, commence: datetime, catalog: KalshiCatalog,
              cutoff: datetime) -> dict[str, Any]:
    """Map one Odds API event to a Kalshi KXNFLGAME event from listings known by `cutoff`. Deterministic."""
    base: dict[str, Any] = {"version": MAPPING_VERSION, "event_ticker": None, "markets": {}, "checks": {},
                            "candidates": []}
    names = [n for n in (home, away) if n]
    unknown = [n for n in names if n not in NFL_TEAMS]
    if len(names) != 2 or unknown:
        return {**base, "state": "UNMATCHED", "reasons": [f"team name(s) not in the NFL table: {unknown or names}"]}
    want = {NFL_TEAMS[home][0]: home, NFL_TEAMS[away][0]: away}  # type: ignore[index]
    events = catalog.events_known(cutoff)
    if not events:
        return {**base, "state": "NO_LISTING", "reasons": ["no KXNFLGAME listing was received by the cutoff"]}
    game_day = et_date(commence)
    exact, near = [], []
    for ev_ticker, markets in sorted(events.items()):
        sides = {parse_ticker(t)["team"]: o for t, o in markets.items()}  # type: ignore[index]
        if set(sides) != set(want):
            continue
        ticker_day = parse_ticker(next(iter(markets)))["date"]  # type: ignore[index]
        if ticker_day == game_day:
            exact.append((ev_ticker, sides))
        elif abs((ticker_day - game_day).days) <= 7:
            near.append((ev_ticker, sides))
    if len(exact) > 1:
        return {**base, "state": "AMBIGUOUS", "candidates": [e for e, _ in exact],
                "reasons": [f"{len(exact)} Kalshi events list both teams on {game_day}"]}
    if not exact:
        if near:
            return {**base, "state": "AMBIGUOUS", "candidates": [e for e, _ in near],
                    "reasons": ["Kalshi lists both teams within 7 days but not on the game's New York date "
                                "(rescheduled or a different game)"]}
        complete = catalog.complete_listing_known(cutoff)
        return {**base, "state": "UNMATCHED" if complete else "NOT_IN_LISTINGS_READ",
                "reasons": ["no Kalshi event lists both teams in a complete series listing" if complete else
                            "no listing read by the cutoff names this game (the listings read were partial: this is "
                            "not evidence that no market exists)"]}
    ev_ticker, sides = exact[0]
    letters = parse_ticker(next(iter(sides.values())).ticker)["letters"]  # type: ignore[index]
    home_abbr, away_abbr = NFL_TEAMS[home][0], NFL_TEAMS[away][0]  # type: ignore[index]
    checks = {
        "teams": {"state": "MATCH", "detail": f"ticker teams {sorted(sides)} = Odds API {sorted(want)}"},
        "date": {"state": "MATCH", "detail": f"ticker date {game_day} = kickoff New York date"},
        "home_away": {"state": "MATCH" if letters == away_abbr + home_abbr else
                      "DIFFERS" if letters == home_abbr + away_abbr else "UNKNOWN",
                      "detail": f"ticker lists {letters}; Odds API away {away_abbr}, home {home_abbr}"},
    }
    markets = {}
    for abbr, obs in sorted(sides.items()):
        label = obs.fields.get("yes_sub_title")
        expected = NFL_TEAMS[want[abbr]][1]
        checks[f"label_{abbr}"] = {"state": "MATCH" if label == expected else "UNKNOWN" if label is None else "DIFFERS",
                                   "detail": f"yes_sub_title {label!r}, expected {expected!r}"}
        markets[want[abbr]] = obs
    bad = [k for k, v in checks.items() if v["state"] == "DIFFERS" and k.startswith("label_")]
    if bad:
        return {**base, "state": "AMBIGUOUS", "event_ticker": ev_ticker, "checks": checks,
                "reasons": [f"market labels differ from the team table: {bad}"]}
    return {**base, "state": "MAPPED", "event_ticker": ev_ticker, "markets": markets, "checks": checks,
            "reasons": ["exact team set and New York game date"]}


# --------------------------------------------------------------------------- consensus


@dataclass
class _Consensus:
    payloads: _Payloads
    cache: "OrderedDict[int, Any]" = field(default_factory=OrderedDict)

    def snapshot(self, sid: int) -> Any:
        """The canonical benchmark for one stored odds snapshot (every event), memoized per report."""
        if sid in self.cache:
            self.cache.move_to_end(sid)
            return self.cache[sid]
        row = self.payloads.row(sid)
        result = None
        if row is not None and row["source"] == ODDS_SOURCE and row["kind"] == odds_consensus.KIND:
            result = odds_consensus.build_snapshot_consensus(row)
        self.cache[sid] = result
        while len(self.cache) > PARSE_CACHE:
            self.cache.popitem(last=False)
        return result


def _h2h(event: Any, home: str | None, away: str | None) -> tuple[Any, list[str]]:
    props = [p for p in event.propositions if p.market_key == ODDS_MARKET]
    names = {home, away}
    exact = [p for p in props if {o[0] for o in p.outcomes} == names]
    if exact:
        return exact[0], []
    reasons = [f"UNSUPPORTED {g.status}: {', '.join(g.reasons)}" for g in event.unsupported if g.market_key == ODDS_MARKET]
    if props:
        reasons.append("the moneyline outcome names differ from the target's teams")
    return None, reasons or ["NO_MONEYLINE: no h2h offers for this game in the capture"]


def odds_side(target: Mapping[str, Any], consensus: _Consensus, cutoff: datetime) -> dict[str, Any]:
    """The sportsbook observation of one horizon: the capture the runner recorded for this target."""
    state = target.get("state")
    out: dict[str, Any] = {"target_state": state, "snapshot_id": target.get("snapshot_id"), "reasons": []}
    if state != "CAPTURED" or target.get("snapshot_id") is None:
        out["stage"] = Stage.ODDS_NOT_CAPTURED
        out["reasons"].append(f"target state {state}" + (f": {target.get('reason')}" if target.get("reason") else ""))
        return out
    sid = int(target["snapshot_id"])
    result = consensus.snapshot(sid)
    if result is None:
        out.update(stage=Stage.ODDS_CAPTURE_UNUSABLE, reasons=[f"snapshot {sid} is missing or is not an odds snapshot"])
        return out
    received = parse_utc(result.received_at_utc)
    out.update(received_utc=result.received_at_utc, payload_sha256=result.payload_sha256,
               input_sha256=result.input_sha256, output_sha256=result.output_sha256,
               consensus_version=result.consensus_version)
    if result.failed_closed:
        out.update(stage=Stage.ODDS_CAPTURE_UNUSABLE, reasons=list(result.problems))
        return out
    if received is None or received > cutoff:
        out.update(stage=Stage.ODDS_CAPTURE_UNUSABLE,
                   reasons=[f"RECEIVED_AFTER_CUTOFF: received {result.received_at_utc}, cutoff {_iso(cutoff)}"])
        return out
    event = next((e for e in result.events if e.event_id == target["event_id"]), None)
    if event is None:
        out.update(stage=Stage.ODDS_CAPTURE_UNUSABLE, reasons=["EVENT_ABSENT: the captured response lacks this game"])
        return out
    prop, why = _h2h(event, target.get("home_team"), target.get("away_team"))
    if prop is None:
        out.update(stage=Stage.CONSENSUS_NOT_SUPPORTED, reasons=why)
        return out
    out.update(status=prop.status.value, contributing_books=prop.contributing_book_count,
               quoting_books=prop.market_bookmaker_count, freshness_at_receipt=prop.freshness_at_receipt.value,
               market_update=_plain(prop.market_update),
               probabilities={c.outcome_name: c.consensus_probability for c in prop.consensus},
               dispersion={c.outcome_name: {"range": c.range, "mad": c.mad} for c in prop.consensus})
    if prop.status is not odds_consensus.ConsensusStatus.SUPPORTED:
        out.update(stage=Stage.CONSENSUS_NOT_SUPPORTED, reasons=[prop.reason or prop.status.value])
        return out
    if prop.freshness_at_receipt is not Freshness.FRESH:
        out["stage"] = Stage.ODDS_NOT_FRESH
        out["reasons"].append(f"freshness at receipt {prop.freshness_at_receipt.value}: a contributing book was stale "
                              "or undated")
        return out
    out["_prop_freshness"] = prop.freshness_at_receipt
    out["_received"] = received
    out["stage"] = None
    return out


# --------------------------------------------------------------------------- Kalshi side


def _depth_limit(url: str) -> int | None:
    values = parse_qs(urlsplit(url or "").query).get("depth") or []
    try:
        return int(values[0]) if len(values) == 1 else None
    except ValueError:
        return None


def pick_book(books: Sequence[tuple[datetime, int, str, str]], odds_received: datetime, window_start: datetime,
              cutoff: datetime, skew: timedelta) -> tuple[tuple[datetime, int, str, str] | None, str | None, int]:
    """(book, problem, later books not used). The book closest to the odds receipt within `skew`, never
    after the cutoff; ties go to the earlier book. A book of this horizon (received from `window_start` to
    the cutoff) that is too far from the odds receipt is PAIR_SKEW_EXCEEDED; a book of another horizon is
    never substituted, so without one of this horizon the book is missing."""
    admissible = [b for b in books if b[0] <= cutoff]
    later = len(books) - len(admissible)
    window = [b for b in admissible if abs(b[0] - odds_received) <= skew]
    if window:
        return min(window, key=lambda b: (abs(b[0] - odds_received), b[0], b[1])), None, later
    horizon = [b for b in admissible if b[0] >= window_start]
    if horizon:
        nearest = min(horizon, key=lambda b: abs(b[0] - odds_received))
        gap = int(abs(nearest[0] - odds_received).total_seconds())
        return None, f"PAIR_SKEW_EXCEEDED: this horizon's nearest book is {gap} s from the odds receipt (limit " \
                     f"{int(skew.total_seconds())} s)", later
    notes = []
    if admissible:
        notes.append(f"{len(admissible)} earlier book(s) of other horizons are not substituted")
    if later:
        notes.append(f"{later} later book(s) are never substituted")
    return None, "KALSHI_BOOK_MISSING: no book of this horizon received by the cutoff" + (
        f" ({'; '.join(notes)})" if notes else ""), later


def capacity(ladder: Any, grid: Any, policy: JoinPolicy) -> list[dict[str, Any]]:
    """The size ladder over one captured YES ladder under both named fill assumptions. Fees come from the
    registry (KXNFLGAME: unsupported), so no all-in cost is stated when the schedule cannot price it."""
    schedule = fee_schedules.schedule_for(KALSHI, KALSHI_SERIES)
    top = ladder.asks[0] if ladder.asks else None
    rows = []
    for q in policy.size_ladder:
        fill = walk_ladder(ladder, q, price_grid=grid)
        cost, why = price_depth_fill(fill, schedule)
        less = {"assumption": FILL_ASSUMPTIONS[0]["id"], "status": fill.status.value, "available": fill.available,
                "gross_cost": fill.gross_cost, "average_price": fill.average_price, "worst_price": fill.limit_price,
                "fee": None if cost is None else cost.fee, "all_in_cost": None if cost is None else cost.total_cost,
                "fee_status": "PRICED" if cost is not None else "FEE_UNSUPPORTED" if isinstance(
                    schedule, fee_schedules.UnsupportedFeeSchedule) else "NOT_PRICED", "fee_detail": why}
        if top is None or ladder.anomaly:
            cons = {"assumption": FILL_ASSUMPTIONS[1]["id"], "status": DepthStatus.INVALID_BOOK.value if ladder.anomaly
                    else DepthStatus.INSUFFICIENT_DEPTH.value, "available": None if ladder.anomaly else Decimal(0),
                    "gross_cost": None, "price": None}
        else:
            cap = top.size * policy.conservative_top_fraction
            ok = q <= cap
            cons = {"assumption": FILL_ASSUMPTIONS[1]["id"],
                    "status": DepthStatus.FILLABLE.value if ok else "CONSERVATIVE_CAP",
                    "available": cap, "gross_cost": top.price * q if ok else None, "price": top.price}
        rows.append({"size": q, "less_conservative": less, "conservative": cons})
    return rows


def kalshi_side(team: str, obs: KalshiMarketObs, catalog: KalshiCatalog, payloads: _Payloads,
                odds_received: datetime, window_start: datetime, cutoff: datetime, as_of: datetime,
                policy: JoinPolicy) -> dict[str, Any]:
    ticker = obs.ticker
    clauses = rules_clauses(obs.fields.get("rules_primary"), obs.fields.get("rules_secondary"))
    out: dict[str, Any] = {
        "team": team, "ticker": ticker, "market_id": kalshi_quotes.market_id(ticker),
        "listing_snapshot_id": obs.snapshot_id, "listing_sha256": obs.payload_sha256,
        "listing_received_utc": _iso(obs.received), "status_at_listing": obs.fields.get("status"),
        "rules_sha256": kalshi_quotes.rules_sha256(obs.fields), "rules": clauses,
        "settlement_sources": list(obs.settlement_sources),
        "relation": relation_for(obs.fields, clauses), "reasons": []}
    if out["relation"]["tier"] in (REL_RULES_UNRESOLVED, REL_PAYOFF_UNSUPPORTED):
        out["stage"] = Stage.KALSHI_RULES_UNRESOLVED
        out["reasons"] += out["relation"]["reasons"]
        return out
    book, problem, later = pick_book(catalog.books.get(ticker, []), odds_received, window_start, cutoff,
                                     policy.max_pair_skew)
    out["later_books_not_used"] = later
    if book is None:
        out["stage"] = Stage.PAIR_SKEW_EXCEEDED if problem and problem.startswith("PAIR_SKEW") else Stage.KALSHI_BOOK_MISSING
        out["reasons"].append(problem)
        return out
    received, sid, url, sha = book
    payload, bad = payloads.payload(sid)
    decision = max(received, odds_received)
    out.update(book_snapshot_id=sid, book_sha256=sha, book_received_utc=_iso(received),
               pair_skew_seconds=int((received - odds_received).total_seconds()), decision_utc=_iso(decision),
               depth_limit=_depth_limit(url))
    if bad:
        out.update(stage=Stage.KALSHI_BOOK_UNUSABLE, reasons=[bad])
        return out
    evidence = f"snapshot:{sid}"
    quotes = kalshi_quotes.quotes_from_orderbook(ticker, payload, received_at_utc=_iso(received), evidence_id=evidence)
    ladders = kalshi_quotes.ladders_from_orderbook(ticker, payload, received_at_utc=_iso(received), evidence_id=evidence,
                                                   depth_limit=out["depth_limit"])
    yes = quotes.get("YES")
    fresh = assess(_iso(received), max_age=KALSHI_BOOK_MAX_AGE, now=decision)
    out["book_freshness_at_decision"] = fresh.value
    if yes is None:
        out.update(stage=Stage.KALSHI_BOOK_UNUSABLE, reasons=["BOOK_ABSENT: the payload holds no order book"])
        return out
    ladder = ladders.get("YES")
    out.update(yes_bid=yes.best_bid, yes_ask=yes.best_ask, yes_ask_size=yes.displayed_size, anomaly=yes.anomaly,
               depth_levels=len(ladder.asks) if ladder else None, depth_truncated=bool(ladder and ladder.truncated),
               visible_depth=sum((lv.size for lv in ladder.asks), Decimal(0)) if ladder else None)
    if yes.anomaly:
        out.update(stage=Stage.KALSHI_BOOK_UNUSABLE, reasons=[yes.anomaly])
        return out
    if yes.best_ask is None:
        out.update(stage=Stage.KALSHI_BOOK_UNUSABLE, reasons=["NO_ASK: nobody offered YES in the captured book"])
        return out
    if fresh is not Freshness.FRESH:
        out.update(stage=Stage.KALSHI_BOOK_UNUSABLE, reasons=[f"book {fresh.value} at the pair's decision time"])
        return out
    grid = kalshi_quotes.price_grid_from_kalshi(obs.fields)
    out["capacity"] = capacity(ladder, grid, policy)
    exp, latest = parse_utc(obs.fields.get("expected_expiration_time")), parse_utc(obs.fields.get("latest_expiration_time"))
    out["lockup_hours"] = {"expected": None if exp is None else round((exp - decision).total_seconds() / 3600, 2),
                           "latest": None if latest is None else round((latest - decision).total_seconds() / 3600, 2),
                           "basis": OBSERVED if exp is not None else UNKNOWN,
                           "detail": "listing expiration times minus the decision time; expected is not guaranteed"}
    nxt = [b for b in catalog.books.get(ticker, []) if decision < b[0] <= as_of]
    out["markout_label_ref"] = None if not nxt else {
        "book_snapshot_id": nxt[0][1], "received_utc": _iso(nxt[0][0]),
        "seconds_after_decision": int((nxt[0][0] - decision).total_seconds()),
        "use": "LABEL_ONLY: a later book is an outcome label, never an entry feature; its resolution is the sampling "
               "gap, not seconds-level latency"}
    out["stage"] = None
    return out


# --------------------------------------------------------------------------- outcomes


def outcome_for(ticker: str, catalog: KalshiCatalog, as_of: datetime) -> dict[str, Any]:
    """The contract resolution a stored listing shows at `as_of` (a label, attached after the fact)."""
    known = catalog.known(ticker, as_of)
    if not known:
        return {"state": Outcome.UNKNOWN.value, "detail": "no listing of this market stored"}
    results = [(o, str(o.fields.get("result") or "").lower()) for o in known]
    stated = [(o, r) for o, r in results if r in ("yes", "no")]
    latest, status = known[-1], str(known[-1].fields.get("status") or "").lower()
    ref = {"listing_snapshot_id": latest.snapshot_id, "received_utc": _iso(latest.received), "status": status or None}
    if len({r for _, r in stated}) > 1:
        return {"state": Outcome.CORRECTED.value, "result": stated[-1][1].upper(), **ref,
                "detail": "stored listings disagree over time: " + ", ".join(f"{_iso(o.received)} {r}" for o, r in stated)}
    result = str(latest.fields.get("result") or "").lower()
    if status in ("settled", "finalized") and result in ("yes", "no"):
        return {"state": Outcome.FINAL.value, "result": result.upper(), **ref}
    if status == "determined" and result in ("yes", "no"):
        return {"state": Outcome.PRELIMINARY.value, "result": result.upper(), **ref}
    if status in ("settled", "finalized", "determined"):
        return {"state": Outcome.UNKNOWN.value, **ref,
                "detail": f"status {status} with result {latest.fields.get('result')!r} (a tie at $0.50 or a fair-price "
                          "resolution is not parsed): not a win/loss label"}
    return {"state": Outcome.PENDING.value, **ref}


# --------------------------------------------------------------------------- targets


def _targets(store: Any, as_of: datetime) -> tuple[list[dict[str, Any]], bool]:
    rows = [dict(r) for r in store.odds_targets(sport=SPORT)]
    truncated = len(rows) > MAX_TARGETS
    rows = rows[:MAX_TARGETS]
    out = []
    for r in rows:
        if (parse_utc(r.get("planned_at_utc")) or as_of) > as_of:
            continue  # planned after as_of: not knowable then
        at = parse_utc(r.get("state_at_utc"))
        if at is not None and at > as_of:  # replay: the state as it stood at as_of
            known = [dict(x) for x in store.odds_transitions(r["target_id"]) if (parse_utc(x["at_utc"]) or as_of) <= as_of]
            last = known[-1] if known else {}
            r.update(state=last.get("state"), reason=last.get("reason"), snapshot_id=last.get("snapshot_id"),
                     captured_at_utc=last.get("captured_at_utc"), state_at_utc=last.get("at_utc"))
        out.append(r)
    return out, truncated


def _capture_target(r: Mapping[str, Any]) -> CaptureTarget:
    return CaptureTarget(r["target_id"], r["sport"], r["event_id"], r["offset_label"], int(r["priority"]),
                         parse_utc(r["commence_time_utc"]), parse_utc(r["target_utc"]),  # type: ignore[arg-type]
                         r.get("home_team"), r.get("away_team"))


def _pm_related(store: Any, as_of: datetime) -> dict[str, list[dict[str, Any]]]:
    """Polymarket US captures of markets related (never equivalent) to each Odds event, by event."""
    by_target = {}
    for t in store.pm_sports_targets():
        t = dict(t)
        if t.get("odds_event_id"):
            by_target[t["target_id"]] = t
    out: dict[str, list[dict[str, Any]]] = {}
    for o in store.pm_sports_observations():
        o = dict(o)
        t = by_target.get(o["target_id"])
        received = parse_utc(o.get("received_at_utc"))
        if t is None or o.get("status") != "CAPTURED" or received is None or received > as_of:
            continue
        native = str(t["odds_event_id"]).split(":", 1)[-1]
        out.setdefault(native, []).append({
            "market_slug": t["market_slug"], "observation_id": o["id"], "received_utc": _iso(received),
            "snapshot_id": o.get("snapshot_id"), "yes_ask": o.get("yes_ask"), "relation": REL_RELATED,
            "use": "stored, listed, never compared: a related market cannot support an equivalent-payoff claim"})
    return out


# --------------------------------------------------------------------------- report


def _week_placebo(rows: list[dict[str, Any]]) -> None:
    """Control references for the protocol: the previous horizon of the same game (delayed signal) and the
    same horizon of the next game in the same NFL week (placebo). References only; nothing is computed."""
    by_event: dict[str, dict[str, dict[str, Any]]] = {}
    for r in rows:
        by_event.setdefault(r["event_id"], {})[r["horizon"]] = r
    order = {"T-24h": 0, "T-6h": 1, "T-60m": 2}
    weeks: dict[str, list[str]] = {}
    for r in rows:
        if r["event_id"] not in weeks.setdefault(r["week_cluster"], []):
            weeks[r["week_cluster"]].append(r["event_id"])
    for r in rows:
        earlier = [h for h in by_event[r["event_id"]] if order.get(h, 9) < order.get(r["horizon"], 9)]
        prev = max(earlier, key=lambda h: order.get(h, 9)) if earlier else None
        prev_row = by_event[r["event_id"]].get(prev) if prev else None
        events = sorted(weeks[r["week_cluster"]])
        other = events[(events.index(r["event_id"]) + 1) % len(events)] if len(events) > 1 else None
        placebo = by_event.get(other, {}).get(r["horizon"]) if other else None
        r["controls"] = {
            "delayed_signal_target": prev_row["target_id"] if prev_row and prev_row["odds"].get("snapshot_id") else None,
            "placebo_target": placebo["target_id"] if placebo else None,
            "use": "references for the protocol's delayed-signal and placebo controls; no statistic is computed here"}


def _row(r: Mapping[str, Any], catalog: KalshiCatalog, payloads: _Payloads, consensus: _Consensus,
         pm: Mapping[str, list], as_of: datetime, policy: JoinPolicy) -> dict[str, Any]:
    t = _capture_target(r)
    cutoff = deadline(t, PILOT_CONFIG)
    row: dict[str, Any] = {
        "target_id": t.target_id, "event_id": t.event_id, "horizon": t.offset_label, "home_team": t.home_team,
        "away_team": t.away_team, "commence_utc": _iso(t.commence_utc), "nominal_utc": _iso(effective_due(t, PILOT_CONFIG)),
        "cutoff_utc": _iso(cutoff), "game_cluster": t.event_id, "week_cluster": week_cluster(t.commence_utc),
        "reasons": [], "sides": {}, "related_not_equivalent": [
            x for x in pm.get(t.event_id, []) if (parse_utc(x["received_utc"]) or as_of) <= cutoff]}
    if r.get("state") == "SUPERSEDED":
        row.update(status=SUPERSEDED, primary=SUPERSEDED, odds={"target_state": "SUPERSEDED"},
                   reasons=[r.get("reason") or "superseded"])
        return row
    if cutoff > as_of:
        row.update(status=NOT_YET_DUE, primary=NOT_YET_DUE, odds={"target_state": r.get("state")},
                   reasons=[f"cutoff {_iso(cutoff)} is after as_of: not missed, not yet due"])
        return row
    odds = odds_side(r, consensus, cutoff)
    row["odds"] = {k: v for k, v in odds.items() if not k.startswith("_")}
    stages: list[Stage] = []
    if odds.get("stage") is not None:
        stages.append(odds["stage"])
        row["reasons"] += [f"{odds['stage'].value}: {x}" for x in odds["reasons"]]
    mapping = map_event(t.home_team, t.away_team, t.commence_utc, catalog, cutoff)
    row["kalshi"] = {k: v for k, v in mapping.items() if k != "markets"}
    row["kalshi"]["tickers"] = {team: o.ticker for team, o in mapping["markets"].items()}
    if mapping["state"] != "MAPPED":
        stages.append(Stage.KALSHI_NOT_MAPPED)
        row["reasons"] += [f"KALSHI_NOT_MAPPED ({mapping['state']}): {x}" for x in mapping["reasons"]]
    elif odds.get("_received") is not None:
        for team, obs in mapping["markets"].items():
            side = kalshi_side(team, obs, catalog, payloads, odds["_received"],
                               effective_due(t, PILOT_CONFIG) - PILOT_CONFIG.early_tolerance, cutoff, as_of, policy)
            p = (odds.get("probabilities") or {}).get(team)
            side["consensus_probability"] = p
            tie = _dec(side["rules"].get("tie_payout"))
            if side.get("stage") is None:
                side["decision_freshness_odds"] = combine(
                    assess(_iso(odds["_received"]), max_age=odds_consensus.ODDS_MAX_AGE, now=parse_utc(side["decision_utc"])),
                    odds["_prop_freshness"]).value
                side["observed_gap_unadjusted"] = None if p is None else side["yes_ask"] - p  # a fraction, not pp
                interval = tie_adjusted_interval(p, tie, policy.tie_probability_bound, policy.postponement_probability_bound)
                side["tie_adjusted_fair_interval"] = None if interval is None else list(interval)
                side["comparison_claim"] = ("NONE: the unadjusted gap mixes a conditional benchmark with a tie-paying "
                                            "contract; it is research data, not an edge" if interval is None else
                                            "NONE: a bounded research comparison, not an edge (fees unsupported)")
            else:
                row["reasons"] += [f"{side['stage'].value} [{team}]: {x}" for x in side["reasons"]]
            row["sides"][team] = side
        rules_stage = [s["stage"] for s in row["sides"].values() if s.get("stage") is Stage.KALSHI_RULES_UNRESOLVED]
        if rules_stage:
            stages.append(Stage.KALSHI_RULES_UNRESOLVED)
    side_stages = [s.get("stage") for s in row["sides"].values()]
    paired = [s for s in side_stages if s is None]
    if not stages and row["sides"] and len(paired) == len(side_stages):
        row.update(status=PAIRED, primary=PAIRED)
    elif not stages and paired:
        row.update(status=PARTIAL_PAIR, primary=PARTIAL_PAIR)
    else:
        failing = stages + [s for s in side_stages if s is not None]
        primary = min(failing, key=STAGE_ORDER.index) if failing else Stage.KALSHI_NOT_MAPPED
        row.update(status="EXCLUDED", primary=primary.value)
        row["all_stages"] = sorted({s.value for s in failing}, key=lambda v: STAGE_ORDER.index(Stage(v)))
    if mapping["state"] == "MAPPED":
        row["outcome"] = {team: outcome_for(o.ticker, catalog, as_of) for team, o in mapping["markets"].items()}
    return row


def _attrition(rows: list[dict[str, Any]]) -> dict[str, Any]:
    planned = len(rows)
    superseded = sum(r["status"] == SUPERSEDED for r in rows)
    future = sum(r["status"] == NOT_YET_DUE for r in rows)
    due = [r for r in rows if r["status"] not in (SUPERSEDED, NOT_YET_DUE)]
    buckets: dict[str, int] = {s.value: 0 for s in STAGE_ORDER}
    buckets[PARTIAL_PAIR] = buckets[PAIRED] = 0
    raw: dict[str, int] = {s.value: 0 for s in STAGE_ORDER}
    for r in due:
        buckets[r["primary"]] += 1
        for s in r.get("all_stages") or []:
            raw[s] += 1
    waterfall, remaining = [], len(due)
    for s in STAGE_ORDER:
        n = buckets[s.value]
        waterfall.append({"stage": s.value, "excluded": n, "remaining_after": remaining - n, "of": remaining,
                          "kind": "DATA_GAP" if s in DATA_GAP_STAGES else "QUALITY", "text": STAGE_TEXT[s]})
        remaining -= n
    paired_rows = [r for r in due if r["status"] in (PAIRED, PARTIAL_PAIR)]
    outcomes: dict[str, int] = {o.value: 0 for o in Outcome}
    final_evaluable = 0
    for r in paired_rows:
        states = {v["state"] for v in (r.get("outcome") or {}).values()}
        worst = next((o.value for o in (Outcome.UNKNOWN, Outcome.PENDING, Outcome.PRELIMINARY, Outcome.CORRECTED,
                                        Outcome.FINAL) if o.value in states), Outcome.UNKNOWN.value)
        outcomes[worst] += 1
        final_evaluable += worst in (Outcome.FINAL.value, Outcome.CORRECTED.value)
    assert sum(buckets.values()) == len(due), "attrition does not reconcile"  # invariant, tested
    sides = [s for r in due for s in r["sides"].values()]
    return {
        "denominators": {
            "targets_planned": planned, "targets_superseded": superseded, "targets_not_yet_due": future,
            "targets_due": len(due), "events": len({r["event_id"] for r in rows}),
            "events_due": len({r["event_id"] for r in due}), "weeks_due": len({r["week_cluster"] for r in due}),
            "kalshi_markets_mapped": len({s["ticker"] for s in sides}),
            "sides_evaluated": len(sides), "sides_paired": sum(s.get("stage") is None for s in sides),
            "odds_snapshots_used": len({r["odds"].get("snapshot_id") for r in due if r["odds"].get("snapshot_id")}),
            "kalshi_books_used": len({s["book_snapshot_id"] for s in sides if s.get("book_snapshot_id")}),
        },
        "primary": buckets, "raw_reasons": raw, "waterfall": waterfall,
        "paired_targets": buckets[PAIRED], "partial_targets": buckets[PARTIAL_PAIR],
        "paired_games": len({r["event_id"] for r in paired_rows}),
        "paired_weeks": len({r["week_cluster"] for r in paired_rows}),
        "outcomes": outcomes, "final_evaluable_targets": final_evaluable,
        # No signal rule is registered (the protocol owns it): these are NOT_EVALUATED, never 0.
        "signal": None, "no_signal": None, "fill": None, "no_fill": None,
        "signal_note": "no Family A signal or episode rule is registered, so signal, fill and episode counts are "
                       "not evaluated (None), not zero; a paired observation is not an episode",
        "reconciles": True,
    }


def _gaps(catalog: KalshiCatalog, attrition: Mapping[str, Any], rows: list[dict[str, Any]], policy: JoinPolicy,
          protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    due = [r for r in rows if r["status"] not in (SUPERSEDED, NOT_YET_DUE)]
    by_h: dict[str, int] = {}
    for r in due:
        if r["primary"] in (Stage.KALSHI_NOT_MAPPED.value, Stage.KALSHI_BOOK_MISSING.value):
            by_h[r["horizon"]] = by_h.get(r["horizon"], 0) + 1
    schedule = fee_schedules.schedule_for(KALSHI, KALSHI_SERIES)
    out = []

    def gap(gid: str, stream: str, state: str, why: str, fix: str, **counts: Any) -> None:
        out.append({"id": gid, "stream": stream, "state": state, "why": why, "smallest_fix": fix, **counts})
    if catalog.listing_snapshots == 0:
        gap("G1", "Kalshi KXNFLGAME listings (tickers, rules, status, result)", "MISSING",
            "no KXNFLGAME listing is stored: no market can be mapped and no rule version is on record",
            "bounded listing read per capture slot through price_observations (docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md)",
            stored=0)
    if catalog.book_snapshots == 0:
        gap("G2", "Kalshi KXNFLGAME order books at the Odds horizons", "MISSING",
            "no exchange price exists at any sportsbook capture time; a later book is never substituted",
            "two book GETs per game per horizon at the existing Odds target times (custom observation targets)",
            stored=0, due_targets_without_book=sum(by_h.values()), by_horizon=dict(sorted(by_h.items())))
    elif by_h:
        gap("G2", "Kalshi KXNFLGAME order books at the Odds horizons", "PARTIAL",
            "some due horizons have no mapped market or book by their cutoff",
            "complete the custom observation targets for the missing horizons (never back-filled)",
            stored=catalog.book_snapshots, due_targets_without_book=sum(by_h.values()), by_horizon=dict(sorted(by_h.items())))
    settled = sum(1 for obs in catalog.listings.values() for o in obs
                  if str(o.fields.get("status") or "").lower() in ("settled", "finalized", "determined"))
    if settled == 0:
        gap("G3", "Kalshi KXNFLGAME resolutions (outcome labels)", "MISSING",
            "no settled / determined KXNFLGAME listing is stored, so no outcome label exists",
            "one settled-markets listing read per game day after expected expiration (existing settlement path)",
            stored=0)
    if isinstance(schedule, fee_schedules.UnsupportedFeeSchedule):
        gap("G4", "KXNFLGAME fee schedule", "UNSUPPORTED",
            schedule.reason + "; the series listing read on 2026-09-25 reported fee_type quadratic_with_maker_fees, "
            "multiplier 1, which conflicts with the registry and is UNVERIFIED",
            "re-verify against Kalshi's current fee PDF and record it in fee_schedules (Writer 1's file)")
    if policy.tie_probability_bound is None or policy.postponement_probability_bound is None:
        gap("G5", "Tie and not-played probability bounds (protocol inputs)", "UNKNOWN",
            "the consensus is conditional on a decided game; the contract pays $0.50 on a tie and a fair price if not "
            "played, so no fair-value comparison exists without declared bounds",
            "declare both bounds in the Family A protocol before any outcome is viewed")
    gap("G6", "Sportsbook rules for ties and voids", "UNVERIFIED",
        "The Odds API carries no rules text; each book's tie/void treatment is assumed, not evidenced",
        "document the assumption in the protocol; do not treat the consensus as unconditional")
    if protocol.get("state") != "REGISTERED":
        gap("G7", "Family A protocol (signal, episode, horizons, controls, futility)", "NOT_REGISTERED",
            "no registered signal or episode rule: signal, fill and episode counts cannot be evaluated",
            "Writer 1's DRAFT protocol (PR A), frozen before outcomes are viewed")
    return out


def protocol_status() -> dict[str, Any]:
    """Writer 1's Family A protocol status, when PR A exposes it (`research_evidence.family_protocol_status`);
    otherwise NOT_REGISTERED. Never inferred from a file name."""
    try:
        module = importlib.import_module("edge_lab.research_evidence")
    except ModuleNotFoundError:
        return {"state": "NOT_REGISTERED", "detail": "no research-evidence contract in this build (PR A)"}
    except Exception as exc:  # noqa: BLE001 - a broken contract is not a registered protocol
        return {"state": "UNKNOWN", "detail": f"research_evidence failed to import: {type(exc).__name__}"}
    fn = getattr(module, "family_protocol_status", None)
    if not callable(fn):
        return {"state": "NOT_REGISTERED", "detail": "research_evidence exposes no family_protocol_status"}
    try:
        value = fn(FAMILY_ID)
    except Exception as exc:  # noqa: BLE001
        return {"state": "UNKNOWN", "detail": f"family_protocol_status failed: {type(exc).__name__}"}
    return dict(value) if isinstance(value, Mapping) else {"state": "UNKNOWN", "detail": "not a mapping"}


def economics(attrition: Mapping[str, Any], policy: JoinPolicy) -> dict[str, Any]:
    """The thin adapter: explicit inputs with their evidence class; no annualised figure, no profit."""
    try:
        importlib.import_module("edge_lab.research_economics")
        contract = {"module": "edge_lab.research_economics", "state": "INSTALLED_NOT_WIRED",
                    "detail": "the screen is wired once the coordinator confirms the contract's API"}
    except ModuleNotFoundError:
        contract = {"module": "edge_lab.research_economics", "state": "NOT_INSTALLED",
                    "detail": "Writer 1's economics / size-ladder / attrition contract is not in this build (PR A)"}
    except Exception as exc:  # noqa: BLE001
        contract = {"module": "edge_lab.research_economics", "state": "BROKEN", "detail": type(exc).__name__}
    reasons = []
    if attrition["paired_targets"] + attrition["partial_targets"] == 0:
        reasons.append("NO_PAIRED_EVIDENCE: no horizon has both a usable consensus and a Kalshi book")
    reasons += ["FEE_UNSUPPORTED: KXNFLGAME is on Kalshi's non-standard fee list; no all-in cost",
                "RELATION_CONDITIONAL: tie and not-played states differ; bounds are " +
                ("declared" if policy.tie_probability_bound is not None and policy.postponement_probability_bound
                 is not None else "not declared"),
                "NO_REGISTERED_PROTOCOL_SIGNAL: no signal or episode rule",
                "BENCHMARK_NOT_TRUTH: the consensus is a research benchmark, not a calibrated probability"]
    return {
        "state": "INSUFFICIENT_EVIDENCE", "contract": contract,
        "edge_at_size": {"state": "NOT_DEFENSIBLE", "reasons": reasons},
        "inputs": [
            {"name": "eligible episodes per year", "value": None, "basis": UNKNOWN,
             "detail": "no episode definition is registered; paired observations are not episodes"},
            {"name": "capital scenario", "value": None, "basis": OWNER_INPUT, "detail": "not supplied; no bankroll assumed"},
            {"name": "reserve and per-venue cash", "value": None, "basis": OWNER_INPUT, "detail": "not supplied"},
            {"name": "variable fees", "value": None, "basis": UNKNOWN, "detail": "KXNFLGAME fee schedule unsupported"},
            {"name": "fill assumptions", "value": [a["id"] for a in FILL_ASSUMPTIONS], "basis": ESTIMATED,
             "detail": "named scenarios, not observations; no fill is claimed"},
            {"name": "lockup", "value": "per paired side", "basis": OBSERVED,
             "detail": "listing expected / latest expiration minus decision time"},
            {"name": "concentration and overlapping commitments", "value": None, "basis": UNKNOWN,
             "detail": "needs the capital replay (research_economics); games in one NFL week overlap"},
        ],
        "fill_assumptions": list(FILL_ASSUMPTIONS),
        "fixed_costs": [
            {"item": "The Odds API free tier (450-credit project cap)", "cash_per_month": "0", "basis": OBSERVED,
             "detail": "free plan; the cap is unchanged by this work"},
            {"item": "Kalshi public market data", "cash_per_month": "0", "basis": OBSERVED, "detail": "keyless"},
            {"item": "owner hours", "cash_per_month": None, "basis": UNKNOWN, "detail": "shown separately from cash"},
        ],
        "notes": ["visible depth is an instantaneous ceiling, never capacity; a small fill is never extrapolated",
                  "no-signal and no-fill observations stay in every denominator",
                  "the EXP-001 fill model is not used or changed"],
    }


def build_report(store: Any, *, as_of: datetime, policy: JoinPolicy = JoinPolicy()) -> dict[str, Any]:
    """The Family A paired-evidence report over one read-only store. Deterministic for the same stored
    inputs, `as_of` and policy. Never writes; never touches the network."""
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise ValueError("as_of must be a timezone-aware datetime")
    as_of = as_of.astimezone(UTC)
    payloads = _Payloads(store)
    consensus = _Consensus(payloads)
    catalog = kalshi_catalog(store, as_of, payloads)
    targets, targets_truncated = _targets(store, as_of)
    pm = _pm_related(store, as_of)
    rows = [_row(r, catalog, payloads, consensus, pm, as_of, policy) for r in targets]
    rows.sort(key=lambda r: (r["commence_utc"] or "", r["event_id"], r["nominal_utc"] or ""))
    _week_placebo(rows)
    attrition = _attrition(rows)
    protocol = protocol_status()
    receipts = sorted([x for r in rows for x in (r["odds"].get("received_utc"),) if x]
                      + [s.get("book_received_utc") for r in rows for s in r["sides"].values() if s.get("book_received_utc")])
    body = {
        "schema": SCHEMA, "label": LABEL, "family": FAMILY_ID, "title": FAMILY_TITLE,
        "join_version": JOIN_VERSION, "mapping_version": MAPPING_VERSION, "rules_parser_version": RULES_PARSER_VERSION,
        "consensus_version": odds_consensus.CONSENSUS_VERSION, "policy": policy.to_dict(), "as_of_utc": _iso(as_of),
        "window": {"first_receipt_utc": receipts[0] if receipts else None,
                   "last_receipt_utc": receipts[-1] if receipts else None},
        "protocol": protocol,
        "bounds": {"targets_truncated": targets_truncated, "kalshi_truncated": catalog.truncated,
                   "listing_snapshots": catalog.listing_snapshots, "listing_parsed": catalog.parsed_listings,
                   "book_snapshots": catalog.book_snapshots, "payload_loads": payloads.loads,
                   "problems": catalog.problems[:20]},
        "sampling": {"horizons": [o.label for o in PILOT_CONFIG.offsets],
                     "resolution": "defined pregame horizons (T-24h / T-6h / T-60m) with a pair skew of at most "
                                   f"{int(policy.max_pair_skew.total_seconds())} s; Kalshi books carry no source "
                                   "timestamp (receipt only); nothing here can establish seconds-level lag"},
        "clusters": {"game": "Odds API event id", "week": "Tuesday-anchored America/New_York NFL week",
                     "note": "books, sides and snapshots are not independent observations"},
        "attrition": attrition, "gaps": [], "economics": economics(attrition, policy), "rows": rows,
    }
    body["gaps"] = _gaps(catalog, attrition, rows, policy, protocol)
    plain = _plain(body)
    plain["output_sha256"] = sha256_hex(canonical_json(plain))
    return plain


# --------------------------------------------------------------------------- Terminal view

_VIEW_CACHE: "OrderedDict[tuple, dict[str, Any]]" = OrderedDict()
VIEW_CACHE_MAX = 8


def _view_key(store: Any, now: datetime) -> tuple:
    """Everything a report depends on grows monotonically: new snapshots, transitions or Polymarket
    observations change their max ids; newly due targets change the due count."""
    snap = _meta_rows(store, "SELECT MAX(id) FROM snapshots", [])[0][0]
    trans = _meta_rows(store, "SELECT MAX(id) FROM odds_capture_transitions", [])[0][0]
    pm = _meta_rows(store, "SELECT MAX(id) FROM pm_sports_observations", [])[0][0]
    due = sum(1 for r in store.odds_targets(sport=SPORT)
              if deadline(_capture_target(dict(r)), PILOT_CONFIG) <= now)
    return (str(store.path), snap, trans, pm, due)


def _family_state(report: Mapping[str, Any], now: datetime) -> str:
    a = report["attrition"]
    den = a["denominators"]
    if den["targets_planned"] == 0:
        return "EMPTY"
    sides = [s for r in report["rows"] for s in r["sides"].values()]
    tiers = {s.get("relation", {}).get("tier") for s in sides}
    if sides and tiers <= {REL_PAYOFF_UNSUPPORTED}:
        return "UNSUPPORTED"
    last = parse_utc(report["window"]["last_receipt_utc"])
    if den["targets_due"] and (last is None or now - last > STALE_AFTER):
        return "STALE"
    if den["targets_due"] == 0:
        return "EMPTY"
    if a["paired_targets"] and a["paired_targets"] == den["targets_due"]:
        return "POPULATED"
    return "PARTIAL"


def _next_action(report: Mapping[str, Any]) -> tuple[str, str | None]:
    ids = {g["id"] for g in report["gaps"]}
    if "G2" in ids and any(g["id"] == "G2" and g["state"] == "MISSING" for g in report["gaps"]):
        return ("Owner decision: authorize the bounded Kalshi KXNFLGAME capture at the Odds horizons "
                "(docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md); no new timer is authorized today",
                "no Kalshi NFL books are stored")
    if "G7" in ids:
        return "Register the Family A DRAFT protocol (PR A) before any outcome is viewed", "no registered protocol"
    if "G4" in ids:
        return "Re-verify the KXNFLGAME fee schedule", "fees unsupported"
    return "Continue stored-evidence research under the protocol", None


def view_from_report(report: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """A compact, display-ready summary: every figure is the report's own; nothing is recomputed."""
    rows = report["rows"]
    paired = [(r, t, s) for r in rows for t, s in r["sides"].items() if s.get("stage") is None]
    latest = max(paired, key=lambda x: (x[2]["decision_utc"], x[2]["ticker"]), default=None)
    sides = [s for r in rows for s in r["sides"].values()]
    rel = next((s["relation"] for s in sides if s.get("relation", {}).get("tier")), None)
    books = [s for s in sides if s.get("book_snapshot_id")]
    action, blocker = _next_action(report)
    return {
        "state": _family_state(report, now), "family": report["family"], "title": report["title"],
        "label": report["label"], "protocol": report["protocol"], "as_of_utc": report["as_of_utc"],
        "window": report["window"], "denominators": report["attrition"]["denominators"],
        "waterfall": report["attrition"]["waterfall"], "paired_targets": report["attrition"]["paired_targets"],
        "partial_targets": report["attrition"]["partial_targets"], "paired_games": report["attrition"]["paired_games"],
        "paired_weeks": report["attrition"]["paired_weeks"], "outcomes": report["attrition"]["outcomes"],
        "final_evaluable_targets": report["attrition"]["final_evaluable_targets"],
        "signal_note": report["attrition"]["signal_note"],
        "relation": rel or {"tier": None, "reasons": ["no Kalshi market mapped yet: the relation is not established"]},
        "provenance": {
            "odds": f"The Odds API h2h · consensus {report['consensus_version']} (median of two-way de-vig)",
            "kalshi_rules": sorted({s["rules_sha256"] for s in sides if s.get("rules_sha256")}),
            "fee": next((g["why"] for g in report["gaps"] if g["id"] == "G4"), "priced by the registry"),
            "join": f"{report['join_version']} · {report['mapping_version']} · {report['rules_parser_version']}",
            "policy": report["policy"]},
        "edge_at_size": report["economics"]["edge_at_size"],
        "capacity": {"sides_with_book": len(books), "truncated": sum(bool(s.get("depth_truncated")) for s in books),
                     "latest": None if latest is None else {
                         "team": latest[1], "ticker": latest[2]["ticker"], "decision_utc": latest[2]["decision_utc"],
                         "horizon": latest[0]["horizon"], "ladder": latest[2].get("capacity") or [],
                         "depth_truncated": latest[2].get("depth_truncated"),
                         "lockup_hours": latest[2].get("lockup_hours")},
                     "fill_assumptions": report["economics"]["fill_assumptions"]},
        "economics_contract": report["economics"]["contract"], "fixed_costs": report["economics"]["fixed_costs"],
        "inputs": report["economics"]["inputs"], "gaps": report["gaps"], "sampling": report["sampling"],
        "next_action": action, "blocker": blocker, "report_sha256": report["output_sha256"],
    }


def terminal_view(db_path: str | Path, *, now: datetime) -> dict[str, Any]:
    """Family A for the Terminal: the store opened read-only, the report memoized until the evidence or
    the set of due targets changes. Never raises: NO_STORE / ERROR carry a short detail."""
    from .storage import ReadOnlyStoreError, SnapshotStore

    base = {"schema": VIEW_SCHEMA, "label": LABEL}
    path = Path(db_path)
    if not path.exists():
        return {**base, "state": "NO_STORE", "detail": f"{path.name} does not exist"}
    try:
        store = SnapshotStore.open_readonly(path)
        key = _view_key(store, now)
        report = _VIEW_CACHE.get(key)
        if report is None:
            report = build_report(store, as_of=now)
            _VIEW_CACHE[key] = report
            while len(_VIEW_CACHE) > VIEW_CACHE_MAX:
                _VIEW_CACHE.popitem(last=False)
        else:
            _VIEW_CACHE.move_to_end(key)
        return {**base, "state": "OK", "family_a": view_from_report(report, now)}
    except ReadOnlyStoreError as exc:
        return {**base, "state": "NO_STORE", "detail": str(exc).splitlines()[0][:200] if str(exc) else "unreadable"}
    except Exception as exc:  # noqa: BLE001 - shown as an error state, never raised into the page
        return {**base, "state": "ERROR", "detail": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160] if str(exc) else ''}"}


# --------------------------------------------------------------------------- CLI


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    """`python -m edge_lab.sports_evidence report --db PATH`: read-only, network-free, bounded."""
    from .storage import ReadOnlyStoreError, SnapshotStore

    parser = argparse.ArgumentParser(prog="python -m edge_lab.sports_evidence",
                                     description=f"{LABEL}. Family A paired evidence from stored data only.")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="the paired-evidence report (JSON); opens the store read-only")
    rep.add_argument("--db", default="data/edge_lab.sqlite3")
    rep.add_argument("--as-of", help="point in time (ISO-8601 with zone); default: now")
    rep.add_argument("--out", help="write the JSON artifact here (atomically) instead of stdout")
    rep.add_argument("--summary", action="store_true", help="print denominators, attrition and gaps only")
    args = parser.parse_args(argv)
    as_of = datetime.now(UTC)
    if args.as_of:
        as_of = parse_utc(args.as_of)  # type: ignore[assignment]
        if as_of is None:
            parser.error("--as-of must be an ISO-8601 time with a zone")
    try:
        store = SnapshotStore.open_readonly(args.db)
    except ReadOnlyStoreError as exc:
        print(json.dumps({"command": "sports_evidence report", "state": "NO_STORE", "detail": str(exc)}))
        return 1
    report = build_report(store, as_of=as_of)
    if args.summary:
        report = {k: report[k] for k in ("schema", "label", "as_of_utc", "window", "protocol", "bounds", "sampling",
                                          "attrition", "gaps", "economics", "output_sha256")}
    text = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False)
    if args.out:
        _write_atomic(Path(args.out), text + "\n")
        print(json.dumps({"command": "sports_evidence report", "state": "WRITTEN", "out": args.out,
                          "output_sha256": report["output_sha256"]}))
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
