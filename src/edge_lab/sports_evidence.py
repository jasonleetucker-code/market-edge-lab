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
received at or before the cutoff (and at or before the report's `as_of`) is used. The Kalshi book is chosen
prospectively (join v2, `pick_book`): the latest book received at or before the odds receipt and no more than
`max_book_before_odds` (5 min) before it; if there is none, the first book received after the odds receipt and
no more than `max_book_after_odds` (10 min) after it. A later book never displaces a qualifying earlier choice.
A book of the horizon outside that window is PAIR_SKEW_EXCEEDED, and a book after the cutoff is never
substituted for a missing one. Each side records `book_timing`: AT_OR_AFTER_ODDS pairs are executable-price
candidates; BEFORE_ODDS pairs are comparability-only (markout and calibration), and they get no size ladder and
no economics episode, because their book is older than the decision time. The pair's decision time is the later
of the two receipts; both inputs' freshness is judged there
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

**Attrition and economics** are a thin adapter over the shared contracts (PR A, ADR 0034): the protocol
waterfalls come from `research_evidence.attrition_report` (EVENT / MARKET / HORIZON / OPPORTUNITY levels
with separate denominators; SIGNAL, FILL and CAPITAL are NOT_APPLICABLE while no rule or capital is
registered, so they are None, never 0); each paired side's size ladder is
`research_economics.size_ladder_from_depth` (complete vs truncated depth; KXNFLGAME fees are on Kalshi's
non-standard list, so FEE_UNSUPPORTED and no all-in cost; no value per unit, so no EV); episodes and the
screen are `research_economics.build_episodes` / `economic_screen` under EXP-002's episode definition
(UNKNOWN today, so no episode and INSUFFICIENT_EVIDENCE). Nothing is annualised; visible depth is never
capacity. This module's own join-stage table stays as a diagnostic of where the join failed.

Clusters for later statistics: the game (Odds event id) and the NFL week (Tuesday-anchored ET week).
Delayed-signal and placebo control references are listed per row for the protocol to use; this module
computes no statistic from them.

**EXP-002 measurement** (`measure_exp002`, `exp002-measurement-v2`): the label-free pre-freeze noise gates v2 and v3 (they
never load a T-60m book) and the cross-book markout endpoint (it reads the first T-60m book of each market, a
label, so it runs only in a logged results path). See the section "EXP-002 measurement" below.

CLI (read-only): `python -m edge_lab.sports_evidence report --db <path> [--as-of ISO] [--out FILE]` and
`python -m edge_lab.sports_evidence exp002 --db <path> [--as-of ISO] [--min-effect D] [--with-results
--evidence-log <EXP-002 evidence_use.jsonl> --actor NAME --code-version SHA] [--out FILE]`.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import statistics
import sys
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlsplit

from . import experiments as registry
from . import fee_schedules, kalshi_quotes, odds_consensus
from . import research_economics as rec
from . import research_evidence as rev
from .forward import eastern_offset
from .freshness import Freshness, assess, combine, parse_utc
from .odds_schedule import CaptureTarget, PilotConfig, deadline, effective_due
from .provenance import canonical_json, sha256_hex
from .sources import get_source

UTC = timezone.utc
SCHEMA = "sports-paired-evidence/1"
VIEW_SCHEMA = "sports-evidence-view/1"
# v2 (2026-09-25): prospective book choice with an asymmetric window (docs/research/RESEARCH_UNBLOCKING_DECISIONS.md
# A.C). v1 took the book closest to the odds receipt within a symmetric 5-minute skew, which compares distances
# to books received after the odds (a mild look-ahead).
JOIN_VERSION = "sports-paired-join-v2"
BOOK_CHOICE = ("prospective-v2: the latest book of this horizon at or before the odds receipt within "
               "max_book_before_odds, else the first book after it within max_book_after_odds")
# Pair use by book timing (docs/research/RESEARCH_UNBLOCKING_DECISIONS.md A.C "Pair use").
BOOK_BEFORE_ODDS, BOOK_AT_OR_AFTER_ODDS = "BEFORE_ODDS", "AT_OR_AFTER_ODDS"
PAIR_USE = {
    BOOK_AT_OR_AFTER_ODDS: "EXECUTABLE_PRICE_CANDIDATE: the book is fresh at the decision time; size ladder and "
                           "economics inputs allowed",
    BOOK_BEFORE_ODDS: "COMPARABILITY_ONLY: the book was received before the odds, so it is older than the decision "
                      "time; markout and calibration only, no size ladder and no economics episode",
}
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
MAX_KALSHI_META = 200_000  # metadata rows read (newest first) before filtering by as_of
MAX_LISTING_PARSES = 600
PARSE_CACHE = 8
STALE_AFTER = timedelta(days=8)  # no new evidence for longer than an NFL week while targets fell due

# Relation tiers and probability meanings. PR B's shared contract now exists (opportunity.ContractSemantics,
# RelationTier incl. CONDITIONAL_EQUIVALENT; ADR 0036); mapping these local labels onto it is not done yet.
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

    # Join v2 pair window (asymmetric). A book before the odds is the stale input at the decision time, so it is
    # bounded by the Kalshi book max age (5 min); a book after the odds makes the odds the older input, bounded by
    # the odds max age (10 min).
    max_book_before_odds: timedelta = KALSHI_BOOK_MAX_AGE
    max_book_after_odds: timedelta = odds_consensus.ODDS_MAX_AGE
    # Declared protocol inputs, UNKNOWN (None) by default: the probability bounds of a tie and of a game
    # not started within Kalshi's postponement window. Without both, no tie-adjusted comparison exists.
    tie_probability_bound: Decimal | None = None
    postponement_probability_bound: Decimal | None = None
    # Size ladder in contracts: scenario rungs (EXP-002 [size_capital] size_ladder is UNKNOWN), never a
    # recommendation or a bankroll.
    size_ladder: tuple[Decimal, ...] = (Decimal(1), Decimal(10), Decimal(25), Decimal(100), Decimal(250))
    # EXP-002 [universe] excludes a two-way de-vig whose tie / void state is unmapped. The KXNFLGAME contract
    # pays $0.50 on a tie and a fair price when not played, while the books' tie rules are unverified, so a
    # CONDITIONAL_MAPPING pair is excluded (RULES_UNRESOLVED) from the protocol's attrition unless the
    # protocol explicitly accepts the conditional mapping. The paired evidence is kept either way.
    conditional_mapping_accepted: bool = False
    version: str = JOIN_VERSION

    def __post_init__(self) -> None:
        if self.max_book_before_odds < timedelta(0) or self.max_book_after_odds <= timedelta(0):
            raise ValueError("max_book_before_odds must be >= 0 and max_book_after_odds positive")
        for name in ("tie_probability_bound", "postponement_probability_bound"):
            v = getattr(self, name)
            if v is not None and not (isinstance(v, Decimal) and Decimal(0) <= v <= Decimal(1)):
                raise ValueError(f"{name} must be a Decimal in [0, 1] or None")
        if not self.size_ladder or any(not isinstance(q, Decimal) or q <= 0 for q in self.size_ladder):
            raise ValueError("size_ladder needs positive Decimal sizes")

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "book_choice": BOOK_CHOICE,
                "max_book_before_odds_seconds": int(self.max_book_before_odds.total_seconds()),
                "max_book_after_odds_seconds": int(self.max_book_after_odds.total_seconds()),
                "tie_probability_bound": _s(self.tie_probability_bound),
                "postponement_probability_bound": _s(self.postponement_probability_bound),
                "size_ladder": [_s(q) for q in self.size_ladder],
                "conditional_mapping_accepted": self.conditional_mapping_accepted,
                "cutoff_rule": "odds_schedule.deadline (effective due + late tolerance, <= kickoff - min lead)",
                "odds_max_age_seconds": int(odds_consensus.ODDS_MAX_AGE.total_seconds()),
                "kalshi_book_max_age_seconds": int(KALSHI_BOOK_MAX_AGE.total_seconds())}


# Fill modes are research_economics.FillMode, applied to episodes (never to single observations here). The ids
# stay the enum values; each text starts with its research_economics label (labels v2, ADR 0037). Neither mode
# is executable performance.
FILL_MODES = (
    {"id": rec.FillMode.CONSERVATIVE.value, "basis": ESTIMATED,
     "text": "FIRST_DETECTION_ZERO_LATENCY: an episode fills from its first qualifying observation at its receipt "
             "time, with no decision or submission delay (not delay-adjusted; the quote may be gone by then); "
             "not executable performance"},
    {"id": rec.FillMode.LESS_CONSERVATIVE.value, "basis": ESTIMATED,
     "text": "HINDSIGHT_UPPER_BOUND: an episode fills from its best single observation (never a sum), chosen after "
             "the whole episode was seen: an oracle upper bound that may only rule a family out, never an "
             "achievable policy or executable performance; captured depth is an instantaneous ceiling, not "
             "capacity"},
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


META_PAGE = 10_000  # metadata rows per page (SnapshotStore.snapshot_metadata keyset paging)
_KALSHI_KINDS = ("orderbook", *LISTING_KINDS)


def _is_nfl_entity(kind: str, entity: str) -> bool:
    """A KXNFLGAME row: books are per market ("KXNFLGAME-..."); listings per series ("KXNFLGAME") or event.
    An exact prefix, never a look-alike series such as "KXNFLGAMEX"."""
    return entity.startswith(f"{KALSHI_SERIES}-") or (kind != "orderbook" and entity == KALSHI_SERIES)


def _nfl_metadata(store: Any, *, after_id: int | None = None, keep: int | None = None) -> tuple[list[Any], bool]:
    """KXNFLGAME snapshot metadata (no payloads) through the store's public, bounded read
    (`SnapshotStore.snapshot_metadata`, exact prefix, keyset pages). Keeps the newest `keep` rows; returns
    (rows oldest first, truncated)."""
    rows: deque[Any] = deque(maxlen=keep)
    seen = 0
    cursor = after_id
    while True:
        page = store.snapshot_metadata(source=KALSHI, kinds=_KALSHI_KINDS, entity_prefix=KALSHI_SERIES,
                                       limit=META_PAGE, after_id=cursor)
        for r in page:
            if _is_nfl_entity(str(r["kind"]), str(r["entity_id"])):
                rows.append(r)
                seen += 1
        if len(page) < META_PAGE:
            return list(rows), keep is not None and seen > keep
        cursor = int(page[-1]["id"])


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


SETTLED_LISTING_FIELDS = ("result", "settlement_value_dollars", "expiration_value")


def kalshi_catalog(store: Any, as_of: datetime, payloads: _Payloads,
                   drop_fields: Sequence[str] = ()) -> KalshiCatalog:
    """Every stored KXNFLGAME listing and book received by `as_of`: metadata by SQL, listings parsed
    (bounded), books left unparsed until the join selects one."""
    meta, meta_truncated = _nfl_metadata(store, keep=MAX_KALSHI_META)
    listings: dict[str, list[KalshiMarketObs]] = {}
    books: dict[str, list[tuple[datetime, int, str, str]]] = {}
    problems: list[str] = []
    if meta_truncated:
        problems.append(f"KALSHI_META_TRUNCATED: only the newest {MAX_KALSHI_META} KXNFLGAME rows were read")
    known = [(received, r) for r in meta if (received := parse_utc(r["fetched_at_utc"])) is not None
             and received <= as_of]  # rows received after as_of are neither used nor counted
    known.sort(key=lambda x: (x[0], int(x[1]["id"])))
    truncated = len(known) > MAX_KALSHI_ROWS or meta_truncated
    if len(known) > MAX_KALSHI_ROWS:
        problems.append(f"KALSHI_ROWS_TRUNCATED: only the newest {MAX_KALSHI_ROWS} of {len(known)} KXNFLGAME rows "
                        "received by as_of were read")
    listing_rows = []
    for received, r in known[-MAX_KALSHI_ROWS:]:
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
                complete, {k: m.get(k) for k in _MARKET_FIELDS if k in m and k not in drop_fields}, srcs))
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
              known_by: datetime) -> dict[str, Any]:
    """Map one Odds API event to a Kalshi KXNFLGAME event from listings received at or before `known_by`
    (the join passes the pair's decision time). Deterministic."""
    base: dict[str, Any] = {"version": MAPPING_VERSION, "event_ticker": None, "markets": {}, "checks": {},
                            "candidates": []}
    names = [n for n in (home, away) if n]
    unknown = [n for n in names if n not in NFL_TEAMS]
    if len(names) != 2 or unknown:
        return {**base, "state": "UNMATCHED", "reasons": [f"team name(s) not in the NFL table: {unknown or names}"]}
    want = {NFL_TEAMS[home][0]: home, NFL_TEAMS[away][0]: away}  # type: ignore[index]
    events = catalog.events_known(known_by)
    if not events:
        return {**base, "state": "NO_LISTING", "reasons": ["no KXNFLGAME listing was received by the decision time"]}
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
        complete = catalog.complete_listing_known(known_by)
        return {**base, "state": "UNMATCHED" if complete else "NOT_IN_LISTINGS_READ",
                "reasons": ["no Kalshi event lists both teams in a complete series listing" if complete else
                            "no listing read by the decision time names this game (the listings read were partial: this is "
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
              cutoff: datetime, before: timedelta = KALSHI_BOOK_MAX_AGE,
              after: timedelta = odds_consensus.ODDS_MAX_AGE) -> tuple[tuple[datetime, int, str, str] | None,
                                                                       str | None, int]:
    """(book, problem, later books not used), by the prospective rule of join v2 (`BOOK_CHOICE`).

    - The latest book received at or before the odds receipt and at most `before` earlier (ties: the higher
      snapshot id, the one written last). A decision-maker at the odds receipt holds the latest book already
      received, so no book received after the odds can displace it.
    - Otherwise the first book received after the odds receipt and at most `after` later (ties: the lower
      snapshot id). Waiting for the next book never looks past the first one that qualifies.
    - Never a book after the cutoff. A book of this horizon (received from `window_start` to the cutoff) outside
      the window is PAIR_SKEW_EXCEEDED; a book of another horizon is never substituted, so without one of this
      horizon the book is missing."""
    admissible = [b for b in books if b[0] <= cutoff]
    later = len(books) - len(admissible)
    # Only books of this horizon (received from `window_start`): an ad-hoc capture of another horizon that happens
    # to land within `before` of the odds receipt is never picked.
    earlier = [b for b in admissible if max(odds_received - before, window_start) <= b[0] <= odds_received]
    if earlier:
        return max(earlier, key=lambda b: (b[0], b[1])), None, later
    following = [b for b in admissible if odds_received < b[0] <= odds_received + after]
    if following:
        return min(following, key=lambda b: (b[0], b[1])), None, later
    horizon = [b for b in admissible if b[0] >= window_start]
    if horizon:
        nearest = min(horizon, key=lambda b: abs(b[0] - odds_received))
        gap = int((nearest[0] - odds_received).total_seconds())
        return None, f"PAIR_SKEW_EXCEEDED: this horizon's nearest book is {gap:+d} s from the odds receipt " \
                     f"(window -{int(before.total_seconds())} s to +{int(after.total_seconds())} s)", later
    notes = []
    if admissible:
        notes.append(f"{len(admissible)} earlier book(s) of other horizons are not substituted")
    if later:
        notes.append(f"{later} later book(s) are never substituted")
    return None, "KALSHI_BOOK_MISSING: no book of this horizon received by the cutoff" + (
        f" ({'; '.join(notes)})" if notes else ""), later


def capacity(ladder: Any, grid: Any, policy: JoinPolicy) -> tuple[Any, ...]:
    """The size ladder over one captured YES ladder: `research_economics.size_ladder_from_depth` (the canonical
    depth walk and fee schedule; fees counted once). The value per unit is None: the consensus is a benchmark
    under a conditional mapping, not a probability of this contract's payoff, so no EV is estimated. KXNFLGAME
    fees are unsupported, so no rung has an all-in cost; the depth status is still stated."""
    return rec.size_ladder_from_depth(ladder, policy.size_ladder, fee_schedule(),
                                      value_per_unit=None, price_grid=grid)


def fee_schedule() -> Any:
    return fee_schedules.schedule_for(KALSHI, KALSHI_SERIES)


def _rung(point: Any, schedule: Any) -> dict[str, Any]:
    if isinstance(schedule, fee_schedules.UnsupportedFeeSchedule):
        fee_status = "FEE_UNSUPPORTED"
    else:
        fee_status = "PRICED" if point.all_in_cost_per_unit is not None else "NOT_PRICED"
    return {"size": point.quantity, "depth_status": point.depth_status,
            "all_in_cost_per_unit": point.all_in_cost_per_unit, "gross_edge_per_unit": point.gross_edge_per_unit,
            "net_edge_per_unit": point.net_edge_per_unit, "fillable": point.fillable, "detail": point.detail,
            "fee_status": fee_status}


def _listing(out: dict[str, Any], obs: KalshiMarketObs, known_by: str) -> None:
    clauses = rules_clauses(obs.fields.get("rules_primary"), obs.fields.get("rules_secondary"))
    out.update(listing_snapshot_id=obs.snapshot_id, listing_sha256=obs.payload_sha256,
               listing_received_utc=_iso(obs.received), listing_known_by=known_by,
               status_at_listing=obs.fields.get("status"), rules_sha256=kalshi_quotes.rules_sha256(obs.fields),
               rules=clauses, settlement_sources=list(obs.settlement_sources), relation=relation_for(obs.fields, clauses))


def kalshi_side(team: str, ticker: str, game: tuple[str | None, str | None, datetime], catalog: KalshiCatalog,
                payloads: _Payloads, odds_received: datetime, window_start: datetime, cutoff: datetime,
                as_of: datetime, policy: JoinPolicy) -> dict[str, Any]:
    """One team's market at one horizon. The book is chosen first (it fixes the pair's decision time); the
    mapping and the rules are then judged only from listings received at or before that decision time, so a
    listing captured after the decision is never used. Without a book there is no decision time: the rules
    read by the cutoff are reported as a diagnostic only."""
    out: dict[str, Any] = {"team": team, "ticker": ticker, "market_id": kalshi_quotes.market_id(ticker),
                           "reasons": []}
    book, problem, later = pick_book(catalog.books.get(ticker, []), odds_received, window_start, cutoff,
                                     policy.max_book_before_odds, policy.max_book_after_odds)
    out["later_books_not_used"] = later
    if book is None:
        obs = catalog.latest(ticker, cutoff)
        if obs is not None:
            _listing(out, obs, "CUTOFF (diagnostic: no book, so no decision time)")
        if obs is not None and out["relation"]["tier"] in (REL_RULES_UNRESOLVED, REL_PAYOFF_UNSUPPORTED):
            out.update(stage=Stage.KALSHI_RULES_UNRESOLVED, reasons=list(out["relation"]["reasons"]) + [problem])
            return out
        out["stage"] = Stage.PAIR_SKEW_EXCEEDED if problem and problem.startswith("PAIR_SKEW") else Stage.KALSHI_BOOK_MISSING
        out["reasons"].append(problem)
        return out
    received, sid, url, sha = book
    decision = max(received, odds_received)
    out.update(book_snapshot_id=sid, book_sha256=sha, book_received_utc=_iso(received),
               pair_skew_seconds=int((received - odds_received).total_seconds()), decision_utc=_iso(decision),
               book_timing=BOOK_BEFORE_ODDS if received < odds_received else BOOK_AT_OR_AFTER_ODDS,
               depth_limit=_depth_limit(url))
    mapping = map_event(game[0], game[1], game[2], catalog, decision)
    obs = mapping["markets"].get(team) if mapping["state"] == "MAPPED" else None
    if obs is None or obs.ticker != ticker:
        out.update(stage=Stage.KALSHI_NOT_MAPPED, reasons=[
            f"NOT_MAPPED_AT_DECISION ({mapping['state']}): the listings received by the decision time "
            f"{_iso(decision)} do not map this market; a later listing is never used"])
        return out
    _listing(out, obs, "DECISION")
    if out["relation"]["tier"] in (REL_RULES_UNRESOLVED, REL_PAYOFF_UNSUPPORTED):
        out["stage"] = Stage.KALSHI_RULES_UNRESOLVED
        out["reasons"] += out["relation"]["reasons"]
        return out
    payload, bad = payloads.payload(sid)
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
    out["pair_use"] = PAIR_USE[out["book_timing"]]
    if out["book_timing"] == BOOK_AT_OR_AFTER_ODDS:
        # Only an executable-price candidate feeds the size ladder and the economics episodes (`_observations`).
        grid = kalshi_quotes.price_grid_from_kalshi(obs.fields)
        points = capacity(ladder, grid, policy)
        out["_points"] = points
        out["_release"] = obs.fields.get("latest_expiration_time")  # the latest cash release the listing states
        schedule = fee_schedule()
        out["capacity"] = [_rung(p, schedule) for p in points]
    else:
        out["capacity"] = None  # comparability-only: never an executable price, so no ladder (None, not empty)
    exp, latest = parse_utc(obs.fields.get("expected_expiration_time")), parse_utc(obs.fields.get("latest_expiration_time"))
    out["lockup_hours"] = {"expected": None if exp is None else round((exp - decision).total_seconds() / 3600, 2),
                           "latest": None if latest is None else round((latest - decision).total_seconds() / 3600, 2),
                           "basis": OBSERVED if exp is not None or latest is not None else UNKNOWN,
                           "detail": "listing expiration times minus the decision time; expected is not guaranteed"}
    # The next book at ANY horizon after the decision (a label reference, not an endpoint). The A.B / A.A markout
    # endpoint, when implemented, uses the first book of the T-60m horizon instead; this field is not changed here.
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
    # Targets planned after as_of are not knowable then and are neither used nor counted; beyond the bound the
    # newest (by intended time) are kept.
    rows = [dict(r) for r in store.odds_targets(sport=SPORT)
            if (parse_utc(r["planned_at_utc"]) or as_of) <= as_of]
    truncated = len(rows) > MAX_TARGETS
    rows = rows[-MAX_TARGETS:]
    out = []
    for r in rows:
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


OUTCOMES_HIDDEN = "HIDDEN (holdout protection: outcome labels are shown only by a logged --with-results run)"


def _row(r: Mapping[str, Any], catalog: KalshiCatalog, payloads: _Payloads, consensus: _Consensus,
         pm: Mapping[str, list], as_of: datetime, policy: JoinPolicy, results: bool = False) -> dict[str, Any]:
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
    # Candidate mapping from listings known by the cutoff; each side is re-mapped at its own decision time.
    mapping = map_event(t.home_team, t.away_team, t.commence_utc, catalog, cutoff)
    row["kalshi"] = {k: v for k, v in mapping.items() if k != "markets"}
    row["kalshi"]["tickers"] = {team: o.ticker for team, o in mapping["markets"].items()}
    row["kalshi"]["known_by"] = "cutoff (candidate); every side is confirmed from listings known by its decision time"
    if mapping["state"] != "MAPPED":
        stages.append(Stage.KALSHI_NOT_MAPPED)
        row["reasons"] += [f"KALSHI_NOT_MAPPED ({mapping['state']}): {x}" for x in mapping["reasons"]]
    elif odds.get("_received") is not None:
        for team, obs in mapping["markets"].items():
            side = kalshi_side(team, obs.ticker, (t.home_team, t.away_team, t.commence_utc), catalog, payloads,
                               odds["_received"], effective_due(t, PILOT_CONFIG) - PILOT_CONFIG.early_tolerance,
                               cutoff, as_of, policy)
            if not results and "markout_label_ref" in side:
                side["markout_label_ref"] = OUTCOMES_HIDDEN  # a later price is a label too (EXP-002 labels)
            p = (odds.get("probabilities") or {}).get(team)
            side["consensus_probability"] = p
            tie = _dec((side.get("rules") or {}).get("tie_payout"))
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
        row["all_stages"] = sorted({s.value for s in side_stages if s is not None},
                                   key=lambda v: STAGE_ORDER.index(Stage(v)))  # the failing side's stage is kept
    else:
        failing = stages + [s for s in side_stages if s is not None]
        primary = min(failing, key=STAGE_ORDER.index) if failing else Stage.KALSHI_NOT_MAPPED
        row.update(status="EXCLUDED", primary=primary.value)
        row["all_stages"] = sorted({s.value for s in failing}, key=lambda v: STAGE_ORDER.index(Stage(v)))
    if mapping["state"] == "MAPPED":
        row["outcome"] = ({team: outcome_for(o.ticker, catalog, as_of) for team, o in mapping["markets"].items()}
                          if results else OUTCOMES_HIDDEN)
    return row


def _by_book_timing(paired_sides: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out = {BOOK_BEFORE_ODDS: 0, BOOK_AT_OR_AFTER_ODDS: 0, "UNKNOWN": 0}
    for s in paired_sides:
        timing = s.get("book_timing")
        out[timing if timing in (BOOK_BEFORE_ODDS, BOOK_AT_OR_AFTER_ODDS) else "UNKNOWN"] += 1
    return out


def _attrition(rows: list[dict[str, Any]], results: bool = False) -> dict[str, Any]:
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
    outcomes: dict[str, int] | None = None
    final_evaluable: int | None = None
    if results:  # outcome states are labels: counted only in a logged --with-results run
        outcomes, final_evaluable = {o.value: 0 for o in Outcome}, 0
        for r in paired_rows:
            recorded = r.get("outcome") if isinstance(r.get("outcome"), dict) else {}
            states = {v["state"] for v in recorded.values()}
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
            # Paired sides by book timing (join v2). BEFORE_ODDS pairs stay in every denominator (markout and
            # calibration); they are only kept out of the economics (economics.episodes.excluded_from_economics).
            "sides_paired_by_book_timing": _by_book_timing([s for s in sides if s.get("stage") is None]),
            "odds_snapshots_used": len({r["odds"].get("snapshot_id") for r in due if r["odds"].get("snapshot_id")}),
            "kalshi_books_used": len({s["book_snapshot_id"] for s in sides if s.get("book_snapshot_id")}),
        },
        "primary": buckets, "raw_reasons": raw, "waterfall": waterfall,
        "paired_targets": buckets[PAIRED], "partial_targets": buckets[PARTIAL_PAIR],
        "paired_games": len({r["event_id"] for r in paired_rows}),
        "paired_weeks": len({r["week_cluster"] for r in paired_rows}),
        "outcomes": outcomes if results else OUTCOMES_HIDDEN, "final_evaluable_targets": final_evaluable,
        # No signal rule is registered (the protocol owns it): these are NOT_EVALUATED, never 0.
        "signal": None, "no_signal": None, "fill": None, "no_fill": None,
        "signal_note": "no Family A signal or episode rule is registered, so signal, fill and episode counts are "
                       "not evaluated (None), not zero; a paired observation is not an episode",
        "reconciles": True,
    }


def _gaps(catalog: KalshiCatalog, attrition: Mapping[str, Any], rows: list[dict[str, Any]], policy: JoinPolicy,
          protocol: Mapping[str, Any], results: bool = False) -> list[dict[str, Any]]:
    due = [r for r in rows if r["status"] not in (SUPERSEDED, NOT_YET_DUE)]
    by_h: dict[str, int] = {}
    for r in due:
        if r["primary"] in (Stage.KALSHI_NOT_MAPPED.value, Stage.KALSHI_BOOK_MISSING.value):
            by_h[r["horizon"]] = by_h.get(r["horizon"], 0) + 1
    schedule = fee_schedule()
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
    if not results:
        # Whether any resolution is stored would itself hint at outcomes: always the same neutral entry.
        gap("G3", "Kalshi KXNFLGAME resolutions (outcome labels)", "WITHHELD",
            "outcome labels are withheld (holdout protection); whether resolutions are stored is shown only by a "
            "logged --with-results run",
            "one settled-markets listing read per game day after expected expiration (existing settlement path)")
    elif not any(str(o.fields.get("status") or "").lower() in ("settled", "finalized", "determined")
                 for obs in catalog.listings.values() for o in obs):
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
    state = protocol.get("state")
    if state == "NOT_REGISTERED" or state == "UNKNOWN":
        gap("G7", "Family A protocol (signal, episode, horizons, controls, futility)",
            "NOT_REGISTERED" if state == "NOT_REGISTERED" else "UNKNOWN",
            str(protocol.get("detail") or "no registered protocol") + ": signal, fill and episode counts cannot be "
            "evaluated", "a Family A protocol in the experiment registry, frozen before outcomes are viewed")
    elif not protocol.get("frozen"):
        unsettled = protocol.get("unsettled_fields") or []
        gap("G7", f"{protocol.get('experiment_id')} protocol decisions (endpoint, cutoffs, episode, size ladder, "
            "futility)", "DRAFT",
            f"{len(unsettled)} decision field(s) are UNKNOWN or MISSING (for example "
            f"{', '.join(unsettled[:4]) or 'none listed'}): no signal, episode or screen can be evaluated",
            "settle and freeze them before any outcome is viewed (the protocol is Writer 1's file; via the coordinator)",
            unsettled=len(unsettled))
    if not policy.conditional_mapping_accepted:
        gap("G8", "Payoff mapping for ties and not-played games (EXP-002 universe)", "UNRESOLVED",
            "KXNFLGAME pays $0.50 on a tie and a fair price if not started within 48 h (rules read 2026-09-25); "
            "EXP-002 excludes a two-way de-vig whose tie / void state is unmapped, so every paired horizon is "
            "RULES_UNRESOLVED in the protocol attrition",
            "the protocol decides the treatment (declared bounds and acceptance of the conditional mapping, or "
            "exclusion) before outcomes are viewed")
    return out


REPO_EXPERIMENTS = Path(__file__).resolve().parents[2] / "experiments"


def _settled_decimal(value: Any) -> Decimal | None:
    """A protocol value as a number, or None while it is an honest placeholder ("UNKNOWN: ...")."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return _dec(value)
    return None if not isinstance(value, str) or registry._unsettled(value) else _dec(value.strip())


def protocol_status(root: Path | None = None) -> dict[str, Any]:
    """The Family A protocol as the experiment registry holds it (PR A: `experiments.load_protocol`): the
    experiment whose `protocol.toml` says `family = "A"`. NOT_REGISTERED when there is none; UNKNOWN when
    the registry cannot be read or holds more than one. Nothing is inferred from a file name."""
    root = root or REPO_EXPERIMENTS
    found = []
    try:
        for path in registry.discover(root):
            exp = registry.load(path)
            if registry.protocol_state(exp) != "PRESENT":
                continue
            proto = registry.load_protocol(exp)
            if isinstance(proto, dict) and proto.get("family") == FAMILY_ID:
                found.append((exp, proto))
    except Exception as exc:  # noqa: BLE001 - an unreadable registry is unknown, never "not registered"
        return {"state": "UNKNOWN", "detail": f"experiment registry unreadable: {type(exc).__name__}"}
    if not found:
        return {"state": "NOT_REGISTERED", "detail": "no experiment declares a Family A protocol"}
    if len(found) > 1:
        return {"state": "UNKNOWN", "detail": f"{len(found)} experiments declare Family A: " +
                ", ".join(sorted(e.id for e, _ in found))}
    exp, proto = found[0]
    episode = proto.get("episode") if isinstance(proto.get("episode"), dict) else {}
    endpoints = proto.get("endpoints") if isinstance(proto.get("endpoints"), dict) else {}
    unsettled = sorted(p for p in registry._unsettled_paths({k: v for k, v in proto.items() if k != "knowledge"}, "")
                       if p)
    return {"state": exp.status or "UNKNOWN", "experiment_id": exp.id, "slot_status": proto.get("slot_status"),
            "protocol_sha256": registry.frozen_hash(proto), "frozen": exp.status in registry.LOCKED,
            "primary_endpoint": str(endpoints.get("primary") or "")[:200] or None,
            "episode": {k: episode.get(k) for k in ("start_threshold", "end_merge_gap", "minimum_size")},
            "unsettled_fields": [p.lstrip(".") for p in unsettled],
            "detail": f"{exp.id} {exp.status}: {len(unsettled)} decision field(s) still UNKNOWN or MISSING"}


def screen_minimums(protocol: Mapping[str, Any]) -> dict[str, Any]:
    """The screen minimums from the canonical helper (`research_economics.protocol_minimums`, the committed
    protocol); never chosen here. No registered protocol: both UNKNOWN."""
    experiment_id = protocol.get("experiment_id")
    if not experiment_id:
        return {k: rec.Labeled.unknown("no Family A protocol registered") for k in rec.PROTOCOL_MINIMUMS}
    return rec.protocol_minimums(str(experiment_id))


def episode_definition(protocol: Mapping[str, Any]) -> Any:
    """EXP-002's episode definition for `research_economics.build_episodes`: every field None while the
    protocol says UNKNOWN, and frozen only once the experiment is locked (PREREGISTERED or later)."""
    ep = protocol.get("episode") if isinstance(protocol.get("episode"), dict) else {}
    gap = _settled_decimal(ep.get("end_merge_gap"))
    return rec.EpisodeDefinition(version=f"{protocol.get('experiment_id') or 'UNREGISTERED'}-episode",
                                 start_threshold=_settled_decimal(ep.get("start_threshold")),
                                 end_merge_gap_seconds=None if gap is None else int(gap),
                                 minimum_size=_settled_decimal(ep.get("minimum_size")),
                                 frozen=bool(protocol.get("frozen")))


def _row_reasons(row: Mapping[str, Any]) -> list[str]:
    """Row-level join failures as `research_evidence.Exclusion` values."""
    out = []
    for stage in row.get("all_stages") or []:
        if stage == Stage.ODDS_NOT_CAPTURED.value:
            out.append("COLLECTION_FAILURE" if row["odds"].get("target_state") == "FAILED" else "MISSED_TARGET")
        elif stage in (Stage.ODDS_CAPTURE_UNUSABLE.value, Stage.CONSENSUS_NOT_SUPPORTED.value):
            out.append("PARTIAL_EVIDENCE")
        elif stage == Stage.ODDS_NOT_FRESH.value:
            out.append("STALE")
        elif stage == Stage.KALSHI_NOT_MAPPED.value and (row.get("kalshi") or {}).get("state") != "MAPPED":
            # Row-level only when the game itself did not map. A side that failed to map at its own decision time
            # (NOT_MAPPED_AT_DECISION) is that side's reason (_side_reasons), never a reason for the other side.
            out.append("RULES_UNRESOLVED" if row["kalshi"].get("state") == "AMBIGUOUS" else "MISSING_SOURCE")
    return out


def _side_reasons(side: Mapping[str, Any], policy: JoinPolicy) -> list[str]:
    stage = side.get("stage")
    tier = (side.get("relation") or {}).get("tier")
    if stage == Stage.KALSHI_RULES_UNRESOLVED:
        return ["UNSUPPORTED_PAYOFF" if tier == REL_PAYOFF_UNSUPPORTED else "RULES_UNRESOLVED"]
    if stage in (Stage.KALSHI_BOOK_MISSING, Stage.KALSHI_NOT_MAPPED):
        return ["MISSING_SOURCE"]
    if stage == Stage.PAIR_SKEW_EXCEEDED:
        return ["STALE"]
    if stage == Stage.KALSHI_BOOK_UNUSABLE:
        return ["STALE" if any("stale" in str(r).lower() for r in side.get("reasons") or []) else "PARTIAL_EVIDENCE"]
    out = []
    if tier == REL_CONDITIONAL and not policy.conditional_mapping_accepted:
        out.append("RULES_UNRESOLVED")  # EXP-002 [universe]: tie / not-played states unmapped
    first = (side.get("capacity") or [{}])[0]
    if first.get("depth_status") in ("DEPTH_UNKNOWN", "INSUFFICIENT_DEPTH"):
        out.append(first["depth_status"])
    return out


def _outcome_reason(outcome: Mapping[str, Any] | None) -> list[str]:
    state = (outcome or {}).get("state")
    if state in (Outcome.FINAL.value, Outcome.CORRECTED.value):
        return []
    if state == Outcome.UNKNOWN.value and (outcome or {}).get("status") in ("settled", "finalized", "determined"):
        return ["OUTCOME_VOID"]  # resolved, but not as a win / loss (a tie at $0.50 or a fair price)
    return ["OUTCOME_PENDING"]


PROTOCOL_NOT_APPLICABLE = (rev.Stage.SIGNAL, rev.Stage.FILL, rev.Stage.CAPITAL)


def _market_units(rows: Sequence[Mapping[str, Any]], catalog: KalshiCatalog, as_of: datetime,
                  policy: JoinPolicy) -> list[Any]:
    """MARKET units: every KXNFLGAME market listed by `as_of` (not only the sides the join evaluated). A market
    whose game has no Odds capture target has no sportsbook side (MISSING_SOURCE); one whose targets are all
    still ahead is PENDING_TARGET until its first cutoff; otherwise its latest listing's rules decide."""
    games: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        if r["status"] != SUPERSEDED:
            games.setdefault(r["event_id"], []).append(r)
    targeting: dict[str, list[Mapping[str, Any]]] = {}
    for event_rows in games.values():  # every targeted game, due or not, mapped from listings known by as_of
        first = event_rows[0]
        mapped = map_event(first.get("home_team"), first.get("away_team"), parse_utc(first["commence_utc"]),
                           catalog, as_of)
        for obs in mapped["markets"].values():
            targeting.setdefault(obs.ticker, []).extend(event_rows)
    units = []
    for ticker in sorted(catalog.listings):
        obs = catalog.latest(ticker, as_of)
        if obs is None:
            continue
        mine = targeting.get(ticker, [])
        deadline_utc = None
        if not mine:
            reasons = ["MISSING_SOURCE"]
        elif all(r["status"] == NOT_YET_DUE for r in mine):
            reasons = ["PENDING_TARGET"]
            deadline_utc = min(r["cutoff_utc"] for r in mine)
        else:
            clauses = rules_clauses(obs.fields.get("rules_primary"), obs.fields.get("rules_secondary"))
            tier = relation_for(obs.fields, clauses)["tier"]
            reasons = (["UNSUPPORTED_PAYOFF"] if tier == REL_PAYOFF_UNSUPPORTED else
                       ["RULES_UNRESOLVED"] if tier == REL_RULES_UNRESOLVED or (
                           tier == REL_CONDITIONAL and not policy.conditional_mapping_accepted) else [])
        units.append(rev.AttritionUnit(rev.Level.MARKET, ticker, tuple(reasons), deadline_utc, obs.event_ticker))
    return units


def protocol_attrition(rows: Sequence[Mapping[str, Any]], *, as_of: datetime, policy: JoinPolicy,
                       catalog: KalshiCatalog, results: bool = False) -> dict[str, Any]:
    """`research_evidence.attrition_report` over the join: EVENT (games), MARKET (every listed KXNFLGAME market;
    not enumerated, so None, when no listing is stored), HORIZON (capture targets) and OPPORTUNITY (target x
    team side). SIGNAL, FILL and CAPITAL are NOT_APPLICABLE while no rule or capital scenario is registered, and
    OUTCOME is withheld unless outcome results were asked for (a logged run): None, never 0. Superseded
    (rescheduled) targets are left out of every level and counted in the join's own table."""
    units: list[Any] = []
    by_event: dict[str, list[list[str]]] = {}
    week: dict[str, str] = {}
    for r in rows:
        if r["status"] == SUPERSEDED:
            continue
        week[r["event_id"]] = r["week_cluster"]
        base = ["PENDING_TARGET"] if r["status"] == NOT_YET_DUE else _row_reasons(r)
        teams = sorted(r["sides"]) or sorted(t for t in (r.get("home_team"), r.get("away_team")) if t)
        horizon_reasons: list[str] = list(base)
        outcomes = r.get("outcome") if isinstance(r.get("outcome"), dict) else {}
        for team in teams:
            side = r["sides"].get(team)
            reasons = list(base)
            if side is not None and r["status"] != NOT_YET_DUE:
                reasons += _side_reasons(side, policy)
                if results:
                    reasons += _outcome_reason(outcomes.get(team))
            elif r["status"] != NOT_YET_DUE and not base:
                reasons.append("MISSING_SOURCE")
            units.append(rev.AttritionUnit(rev.Level.OPPORTUNITY, f"{r['target_id']}|{team}",
                                           tuple(dict.fromkeys(reasons)), r["cutoff_utc"], r["event_id"]))
            horizon_reasons += reasons
            by_event.setdefault(r["event_id"], []).append(reasons)
        if not teams:
            by_event.setdefault(r["event_id"], []).append(base or ["MISSING_SOURCE"])
        units.append(rev.AttritionUnit(rev.Level.HORIZON, r["target_id"], tuple(dict.fromkeys(horizon_reasons)),
                                       r["cutoff_utc"], r["event_id"]))
    for event, reason_sets in sorted(by_event.items()):
        survived = any(not rs for rs in reason_sets)
        merged = () if survived else tuple(dict.fromkeys(x for rs in reason_sets for x in rs))
        units.append(rev.AttritionUnit(rev.Level.EVENT, event, merged, None, week.get(event)))
    markets_enumerated = catalog.listing_snapshots > 0
    if markets_enumerated:
        units += _market_units(rows, catalog, as_of, policy)
    levels = [rev.Level.EVENT, rev.Level.HORIZON, rev.Level.OPPORTUNITY] + ([rev.Level.MARKET] if markets_enumerated
                                                                            else [])
    not_applicable = PROTOCOL_NOT_APPLICABLE + (() if results else (rev.Stage.OUTCOME,))
    report = rev.attrition_report(units, as_of_utc=_iso(as_of), levels_enumerated=levels,
                                  not_applicable_stages=not_applicable)
    out = report.to_dict()
    out["notes"] = [
        "SIGNAL, FILL and CAPITAL are NOT_APPLICABLE until the protocol registers a signal rule and a capital "
        "scenario: they read None, never 0",
        "OUTCOME is " + ("included (a logged --with-results run)" if results else
                         "withheld for holdout protection: outcome states are labels, so final-evaluable reads None"),
        "SNAPSHOT is not enumerated here (None): books and odds responses are inputs, counted in the join table",
        "MARKET counts every KXNFLGAME market listed by as_of, including games no Odds target covers",
        "a CONDITIONAL_MAPPING pair is RULES_UNRESOLVED under EXP-002's universe unless the protocol accepts it",
        "LIQUIDITY is judged at the smallest size-ladder rung only (DEPTH_UNKNOWN / INSUFFICIENT_DEPTH)",
    ]
    return out


def economics(rows: Sequence[Mapping[str, Any]], observations: Sequence[Any], protocol: Mapping[str, Any],
              join: Mapping[str, Any], policy: JoinPolicy, as_of: datetime, gaps: Sequence[str]) -> dict[str, Any]:
    """The shared screen (`research_economics`): episodes under the protocol's episode definition, a replay
    with NO capital scenario supplied (the owner sets any amount; nothing here is a bankroll), fixed cash costs
    OBSERVED at zero, owner inputs UNKNOWN. With today's DRAFT protocol the verdict is INSUFFICIENT_EVIDENCE."""
    definition = episode_definition(protocol)
    minimums = screen_minimums(protocol)
    # Comparability-only pairs are paired evidence but never economics inputs; count them so that
    # observations + excluded == paired sides (nothing drops out silently).
    comparability_only = sum(1 for r in rows for s in r["sides"].values()
                             if s.get("stage") is None and s.get("book_timing") == BOOK_BEFORE_ODDS)
    episodes = rec.build_episodes(observations, definition)
    due = [parse_utc(r["cutoff_utc"]) for r in rows if r["status"] not in (SUPERSEDED, NOT_YET_DUE)]
    start = min((d for d in due if d is not None), default=None)
    screen = None
    screen_problem = None
    if start is None or start >= as_of:
        screen_problem = "no due horizon, so there is no replay window"
    else:
        screen = rec.economic_screen(rec.ScreenInputs(
            family=FAMILY_ID, experiment_id=str(protocol.get("experiment_id") or "UNREGISTERED"), episodes=episodes,
            scenario=rec.CapitalScenario(label="no capital scenario supplied", capital_by_venue={}, reserve_by_venue={}),
            primary_size=policy.size_ladder[0], sizes=tuple(policy.size_ladder),
            window_start_utc=_iso(start), window_end_utc=_iso(as_of),
            fixed_cash_costs_annual=rec.Labeled(Decimal(0), rec.Basis.OBSERVED,
                                                "The Odds API free tier and Kalshi public data: no incremental cash"),
            owner_hours_annual=rec.Labeled.unknown("MISSING_OWNER_INPUT (EXP-002 [budget] owner_hours)"),
            owner_hourly_cost=rec.Labeled.unknown("MISSING_OWNER_INPUT"),
            minimum_useful_annual=rec.Labeled.unknown("MISSING_OWNER_INPUT (EXP-002 [economics])"),
            min_episodes_for_scenario=minimums["min_episodes_for_scenario"],
            min_independent_clusters=minimums["min_independent_clusters"],
            stationarity_assumption="none: no annual scenario is produced from this evidence",
            data_gaps=tuple(gaps),
            assumptions=("value per unit is None: the consensus is a benchmark under a conditional mapping, so no "
                         "EV is estimated", "KXNFLGAME fees are unsupported: no rung has an all-in cost")))
    reasons = []
    if join["paired_targets"] + join["partial_targets"] == 0:
        reasons.append("NO_PAIRED_EVIDENCE: no horizon has both a usable consensus and a Kalshi book")
    reasons += ["FEE_UNSUPPORTED: KXNFLGAME is on Kalshi's non-standard fee list; no all-in cost",
                "RELATION_CONDITIONAL: tie and not-played states differ; bounds are " +
                ("declared" if policy.tie_probability_bound is not None and policy.postponement_probability_bound
                 is not None else "not declared"),
                "NO_EPISODE_DEFINITION: " + ("; ".join(definition.problems()) or "defined"),
                "BENCHMARK_NOT_TRUTH: the consensus is a research benchmark, not a calibrated probability"]
    screen_dict = None if screen is None else screen.to_dict()
    return {
        "state": screen_dict["verdict"] if screen_dict else rec.Verdict.INSUFFICIENT_EVIDENCE.value,
        "contract": {"module": "edge_lab.research_economics", "state": "WIRED", "version": rec.ECONOMICS_VERSION,
                     "detail": "size ladder, episodes and screen from the shared contract (PR A)"},
        "edge_at_size": {"state": "NOT_DEFENSIBLE", "reasons": reasons},
        "episodes": {"definition": _plain(definition), "problems": list(episodes.problems),
                     "observations": episodes.observations,
                     "excluded_from_economics": {"count": comparability_only,
                                                 "reason": f"{BOOK_BEFORE_ODDS}: comparability-only"},
                     # an undefined episode rule makes episodes NOT EVALUABLE (None), never "0 episodes"
                     "qualifying": None if episodes.problems else episodes.qualifying_observations,
                     "episodes": None if episodes.problems else len(episodes.episodes),
                     "note": "a paired observation is not an episode; repeated looks at one book are one episode"},
        "screen": screen_dict, "screen_problem": screen_problem,
        "inputs": [
            {"name": "eligible episodes per year", "value": None, "basis": UNKNOWN,
             "detail": "EXP-002's episode definition is UNKNOWN; never annualised from a few observations"},
            {"name": "capital scenario", "value": None, "basis": OWNER_INPUT,
             "detail": "none supplied: no bankroll is assumed (an illustrative scenario is never an approved bankroll)"},
            {"name": "reserve and per-venue cash", "value": None, "basis": OWNER_INPUT, "detail": "not supplied"},
            {"name": "variable fees", "value": None, "basis": UNKNOWN, "detail": "KXNFLGAME fee schedule unsupported"},
            {"name": "fill modes", "value": [m["id"] for m in FILL_MODES], "basis": ESTIMATED,
             "detail": "research_economics.FillMode, applied to episodes: FIRST_DETECTION_ZERO_LATENCY and "
                       "HINDSIGHT_UPPER_BOUND (labels v2); no fill is claimed and neither is executable performance"},
            {"name": "lockup", "value": "per paired side", "basis": OBSERVED,
             "detail": "listing expected / latest expiration minus decision time"},
            {"name": "minimum useful annual contribution", "value": None, "basis": OWNER_INPUT,
             "detail": "MISSING_OWNER_INPUT; the long-term aspiration is not a per-experiment minimum"},
        ],
        "fill_modes": list(FILL_MODES),
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


def _observations(rows: Sequence[dict[str, Any]]) -> list[Any]:
    """One `research_economics.Observation` per paired side (its size ladder, decision time, game cluster,
    release at the listing's latest expiration). The private ladder objects are removed from the rows."""
    out = []
    for r in rows:
        for team, side in sorted(r["sides"].items()):
            points = side.pop("_points", None)
            release = side.pop("_release", None)
            if side.get("stage") is not None or points is None:
                continue
            out.append(rec.Observation(
                observation_id=f"{r['target_id']}|{side['ticker']}", liquidity_keys=(f"{side['market_id']}:YES",),
                venue=KALSHI, observed_at_utc=side["decision_utc"], cluster_id=r["event_id"],
                edge_kind=rec.EdgeKind.EXPECTED_VALUE, ladder=points, release_at_utc=release,
                outer_cluster_id=r["week_cluster"],
                evidence_ids=tuple(x for x in (f"snapshot:{r['odds'].get('snapshot_id')}",
                                               f"snapshot:{side.get('book_snapshot_id')}") if x)))
    return out


def _join(store: Any, as_of: datetime, policy: JoinPolicy, results: bool,
          horizons: Sequence[str] | None = None, drop_settled: bool = False
          ) -> tuple[list[dict[str, Any]], KalshiCatalog, _Payloads, list[dict[str, Any]], bool]:
    """(rows, catalog, payloads, targets, targets truncated): the join rows, optionally for some horizons only
    (the gate builds T-24h and T-6h rows only, so no T-60m book is loaded for it) and with the settled listing
    fields dropped from the catalog (`drop_settled`, the gate path: no settlement label is held in memory)."""
    payloads = _Payloads(store)
    consensus = _Consensus(payloads)
    catalog = kalshi_catalog(store, as_of, payloads, SETTLED_LISTING_FIELDS if drop_settled else ())
    targets, targets_truncated = _targets(store, as_of)
    pm = _pm_related(store, as_of)
    chosen = [r for r in targets if horizons is None or r["offset_label"] in horizons]
    rows = [_row(r, catalog, payloads, consensus, pm, as_of, policy, results) for r in chosen]
    rows.sort(key=lambda r: (r["commence_utc"] or "", r["event_id"], r["nominal_utc"] or ""))
    _week_placebo(rows)
    return rows, catalog, payloads, targets, targets_truncated


def build_report(store: Any, *, as_of: datetime, policy: JoinPolicy = JoinPolicy(),
                 experiments_root: Path | None = None, results: bool = False) -> dict[str, Any]:
    """The Family A paired-evidence report over one read-only store. Deterministic for the same stored
    inputs, `as_of`, policy and registry. Never writes; never touches the network.

    Outcome states and results are labels (EXP-002 [data_roles]), so by default they are hidden everywhere:
    rows, join counts and the protocol OUTCOME stage. `results=True` is for a run whose viewing is logged in
    the experiment's evidence-use log (the CLI's `--with-results` records it before printing)."""
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise ValueError("as_of must be a timezone-aware datetime")
    as_of = as_of.astimezone(UTC)
    rows, catalog, payloads, _, targets_truncated = _join(store, as_of, policy, results)
    observations = _observations(rows)  # also removes the private ladder objects from the rows
    join = _attrition(rows, results)
    protocol = protocol_status(experiments_root)
    receipts = sorted([x for r in rows for x in (r["odds"].get("received_utc"),) if x]
                      + [s.get("book_received_utc") for r in rows for s in r["sides"].values() if s.get("book_received_utc")])
    gaps = _gaps(catalog, join, rows, policy, protocol, results)
    body = {
        "schema": SCHEMA, "label": LABEL, "family": FAMILY_ID, "title": FAMILY_TITLE,
        "join_version": JOIN_VERSION, "mapping_version": MAPPING_VERSION, "rules_parser_version": RULES_PARSER_VERSION,
        "consensus_version": odds_consensus.CONSENSUS_VERSION, "policy": policy.to_dict(), "as_of_utc": _iso(as_of),
        "window": {"first_receipt_utc": receipts[0] if receipts else None,
                   "last_receipt_utc": receipts[-1] if receipts else None},
        "protocol": protocol,
        "outcome_labels": "INCLUDED (a logged --with-results run)" if results else OUTCOMES_HIDDEN,
        "bounds": {"targets_truncated": targets_truncated, "kalshi_truncated": catalog.truncated,
                   "listing_snapshots": catalog.listing_snapshots, "listing_parsed": catalog.parsed_listings,
                   "book_snapshots": catalog.book_snapshots, "payload_loads": payloads.loads,
                   "problems": catalog.problems[:20]},
        "sampling": {"horizons": [o.label for o in PILOT_CONFIG.offsets],
                     "resolution": "defined pregame horizons (T-24h / T-6h / T-60m) with the book from "
                                   f"{int(policy.max_book_before_odds.total_seconds())} s before to "
                                   f"{int(policy.max_book_after_odds.total_seconds())} s after the odds receipt "
                                   "(prospective choice, join v2); Kalshi books carry no source timestamp (receipt "
                                   "only); nothing here can establish seconds-level lag"},
        "clusters": {"game": "Odds API event id", "week": "Tuesday-anchored America/New_York NFL week",
                     "note": "books, sides and snapshots are not independent observations"},
        "attrition": protocol_attrition(rows, as_of=as_of, policy=policy, catalog=catalog, results=results),
        "join": join, "gaps": gaps,
        "economics": economics(rows, observations, protocol, join, policy, as_of, [g["stream"] for g in gaps]),
        "rows": rows,
    }
    plain = _plain(body)
    plain["output_sha256"] = sha256_hex(canonical_json(plain))
    return plain


# --------------------------------------------------------------------------- EXP-002 measurement
#
# docs/research/RESEARCH_UNBLOCKING_DECISIONS.md A.A-A.C and A.G. Two parts, kept apart on purpose:
#
# - The label-free pre-freeze gate (`noise_gate`). It reads only the T-24h and T-6h paired books and repeat
#   books of the same market received within 15 min after them (inside the same horizon). It never loads a
#   T-60m book, which is a label for the T-6h markout. From same-capture cross-book dispersion and repeat-book
#   noise it estimates the book-noise correlation rho, bounds it with a week-cluster bootstrap, and compares the
#   upper bound with rho_max = (1/4 * delta_min) / b_hat. delta_min stays UNKNOWN until the protocol freezes it,
#   so the verdict is given per candidate delta_min, or for one supplied by the caller.
# - The cross-book markout endpoint (`markout_endpoint`). It reads the first T-60m book of each team market, a
#   label, so it runs only in a logged results path (`measure_exp002(results=True)`; the CLI's
#   `exp002 --with-results` records the view first). Nothing here is an edge claim or a frozen statistic.

# v2 (2026-09-28): the output adds `gate_v3` beside the unchanged v2 gate; v1 outputs keep their own version.
MEASUREMENT_VERSION = "exp002-measurement-v2"
GATE_VERSION = "exp002-noise-gate-v2"
MARKOUT_VERSION = "exp002-cross-book-markout-v1"
GATE_HORIZONS = ("T-24h", "T-6h")
PRIOR_HORIZON, SIGNAL_HORIZON, TARGET_HORIZON = "T-24h", "T-6h", "T-60m"
SAME_CAPTURE_MAX = timedelta(seconds=120)  # both team books of one capture run
REPEAT_WINDOW = timedelta(minutes=15)
# Sufficiency floors of the gate's estimator (implementation parameters, not research thresholds): below them
# the verdict is INSUFFICIENT_DATA, never PASS.
# v2 (review of #119): four weeks (two gave only three distinct week resamples), and a game-cluster bound too.
GATE_MIN_PAIRS, GATE_MIN_REPEATS, GATE_MIN_WEEKS, GATE_MIN_GAPS = 20, 10, 4, 10
CANDIDATE_MIN_EFFECTS = (0.0025, 0.005, 0.01)  # candidates for display only; the protocol freezes delta_min
TOLERABLE_FRACTION = 0.25
GATE_BOOTSTRAP_SEED, GATE_BOOTSTRAP_RESAMPLES = 20260926, 2000
MIRROR_VARIANCE = 1e-10  # a cross-book dispersion variance at or below this is mirror quoting (rho = 1)
MEASUREMENT_LABEL = "EXP-002 MEASUREMENT (DEVELOPMENT) — NOT AN EDGE CLAIM, NOT A FROZEN STATISTIC"
# Gate v2 never authorizes a freeze (review of #119): with repeat books, moderate stickiness still biases rho_hat
# and b_hat low without a misfit, so a v2 PASS is named for what it is and carries freeze_eligible = False.
PASS, FAIL, INSUFFICIENT = "PASS_REPEAT_ONLY_NOT_FREEZE_ELIGIBLE", "FAIL", "INSUFFICIENT_DATA"
FREEZE_INELIGIBLE_REASON = ("gate v2 cannot bound moderate stickiness; freeze requires reviewed gate v3 "
                            "(docs/research/RESEARCH_UNBLOCKING_DECISIONS.md A.I)")


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _mid(bid: Any, ask: Any) -> float | None:
    b, a = _dec(bid), _dec(ask)
    if b is None or a is None or b >= a:
        return None
    return float((b + a) / 2)


def _spread(bid: Any, ask: Any) -> float | None:
    b, a = _dec(bid), _dec(ask)
    return None if b is None or a is None else float(a - b)


class BookMids:
    """Reads one stored Kalshi book and returns its YES mid (None when it has no two-sided book). Every snapshot
    id read is recorded in `read`, so a caller (and a test) can prove which books a computation touched."""

    def __init__(self, payloads: _Payloads) -> None:
        self.payloads = payloads
        self.read: list[int] = []

    def __call__(self, ticker: str, sid: int, received: datetime) -> tuple[float | None, float | None]:
        self.read.append(sid)
        payload, bad = self.payloads.payload(sid)
        if bad:
            return None, None
        yes = kalshi_quotes.quotes_from_orderbook(ticker, payload, received_at_utc=_iso(received),
                                                  evidence_id=f"snapshot:{sid}").get("YES")
        if yes is None or yes.anomaly:
            return None, None
        return _mid(yes.best_bid, yes.best_ask), _spread(yes.best_bid, yes.best_ask)


@dataclass(frozen=True)
class GateObservations:
    """Label-free inputs of the gate: (week, game, value) triples."""

    dispersions: tuple[tuple[str, str, float], ...]  # d = H - (1 - away mid), same capture, T-24h and T-6h
    repeats_home: tuple[tuple[str, str, float], ...]  # home market: repeat mid - paired mid, within 15 min
    repeats_away: tuple[tuple[str, str, float], ...]
    gaps: tuple[tuple[str, str, float], ...]  # T-6h: consensus home probability - H
    repeat_gap_seconds: tuple[int, ...]
    counts: dict[str, int]
    books_read: tuple[int, ...]
    # Bid-ask spreads of the paired books (both roles): the PROPOSED single-capture noise scale, diagnostic only.
    spreads: tuple[tuple[str, str, float], ...] = ()


def gate_observations(rows: Sequence[Mapping[str, Any]], catalog: KalshiCatalog,
                      mids: Callable[[str, int, datetime], tuple[float | None, float | None]]) -> GateObservations:
    """Collect the gate's inputs from T-24h / T-6h rows only. Paired books' mids come from the rows (already read
    as features); `mids` is called only for repeat books of those markets, received after the paired book, within
    `REPEAT_WINDOW` and at or before the row's cutoff (so inside the same horizon)."""
    counts = {"rows_seen": 0, "rows_other_horizon_ignored": 0, "rows_not_fully_paired": 0, "no_two_sided_book": 0,
              "not_same_capture": 0, "dispersion_pairs": 0, "repeat_candidates": 0, "repeat_home": 0,
              "repeat_away": 0, "repeat_without_mid": 0, "gaps": 0}
    disp, rep_h, rep_a, gaps, gap_s, spreads = [], [], [], [], [], []
    read: list[int] = []

    def reader(ticker: str, sid: int, received: datetime) -> tuple[float | None, float | None]:
        read.append(sid)
        return mids(ticker, sid, received)

    for r in rows:
        if r.get("horizon") not in GATE_HORIZONS:
            counts["rows_other_horizon_ignored"] += 1
            continue
        counts["rows_seen"] += 1
        sides = r.get("sides") or {}
        home, away = sides.get(r.get("home_team")), sides.get(r.get("away_team"))
        if r.get("status") != PAIRED or home is None or away is None:
            counts["rows_not_fully_paired"] += 1
            continue
        h, am = _mid(home.get("yes_bid"), home.get("yes_ask")), _mid(away.get("yes_bid"), away.get("yes_ask"))
        if h is None or am is None:
            counts["no_two_sided_book"] += 1
            continue
        week, game = r["week_cluster"], r["event_id"]
        rh, ra = parse_utc(home.get("book_received_utc")), parse_utc(away.get("book_received_utc"))
        if rh is None or ra is None or abs(rh - ra) > SAME_CAPTURE_MAX:
            counts["not_same_capture"] += 1
        else:
            disp.append((week, game, h - (1 - am)))
            counts["dispersion_pairs"] += 1
            for s in (home, away):
                sp = _spread(s.get("yes_bid"), s.get("yes_ask"))
                if sp is not None:
                    spreads.append((week, game, sp))
        cutoff = parse_utc(r.get("cutoff_utc"))
        for role, side, paired_mid, out in (("home", home, h, rep_h), ("away", away, am, rep_a)):
            received = parse_utc(side.get("book_received_utc"))
            if received is None or cutoff is None:
                continue
            later = [b for b in catalog.books.get(side["ticker"], [])
                     if received < b[0] <= min(received + REPEAT_WINDOW, cutoff) and b[1] != side.get("book_snapshot_id")]
            if not later:
                continue
            counts["repeat_candidates"] += 1
            first = min(later, key=lambda b: (b[0], b[1]))
            m, _ = reader(side["ticker"], first[1], first[0])
            if m is None:
                counts["repeat_without_mid"] += 1
                continue
            out.append((week, game, m - paired_mid))
            counts[f"repeat_{role}"] += 1
            gap_s.append(int((first[0] - received).total_seconds()))
        p = _dec(home.get("consensus_probability"))
        if r["horizon"] == SIGNAL_HORIZON and p is not None:
            gaps.append((week, game, float(p) - h))
            counts["gaps"] += 1
    return GateObservations(tuple(disp), tuple(rep_h), tuple(rep_a), tuple(gaps), tuple(gap_s), counts, tuple(read),
                            tuple(spreads))


def _noise_components(disp: Sequence[float], rep_h: Sequence[float],
                      rep_a: Sequence[float]) -> tuple[float | None, float | None, float | None, float | None]:
    """(rho_hat, var_d, sigma2_home, sigma2_away). sigma2 = 1/2 * mean(repeat difference^2): latent drift inside
    the repeat gap inflates it, which errs toward failing."""
    var_d = statistics.variance(disp) if len(disp) >= 2 else None
    s2h = 0.5 * sum(x * x for x in rep_h) / len(rep_h) if rep_h else None
    s2a = 0.5 * sum(x * x for x in rep_a) / len(rep_a) if rep_a else None
    if var_d is None or not s2h or not s2a:
        return None, var_d, s2h, s2a
    rho = (s2h + s2a - var_d) / (2 * math.sqrt(s2h * s2a))
    return max(-1.0, min(1.0, rho)), var_d, s2h, s2a


def naive_bias(sigma2: float, gap_sd: float) -> float:
    """The v1 same-book markout bias, sigma^2 * sqrt(2/pi) / sd(gap) (scripts/research_power_sensitivity.py)."""
    return sigma2 * math.sqrt(2 / math.pi) / gap_sd


def rho_max(min_effect: float, b_hat: float | None) -> float | None:
    """(TOLERABLE_FRACTION * min_effect) / b_hat, capped at 1; None when b_hat is unknown."""
    if b_hat is None:
        return None
    return 1.0 if b_hat <= 0 else min(1.0, TOLERABLE_FRACTION * min_effect / b_hat)


def _cluster_upper(obs: GateObservations, *, key: int, seed: int, resamples: int, q: float = 0.9) -> float | None:
    """One-sided upper `q` bound of rho_hat, resampling whole clusters (`key` 0: NFL weeks, 1: games), each with
    all of its dispersions and repeats. None with fewer than two clusters or when no resample is estimable."""
    clusters = sorted({x[key] for x in obs.dispersions} | {x[key] for x in obs.repeats_home}
                      | {x[key] for x in obs.repeats_away})
    if len(clusters) < 2:
        return None
    by = {c: ([x[2] for x in obs.dispersions if x[key] == c], [x[2] for x in obs.repeats_home if x[key] == c],
              [x[2] for x in obs.repeats_away if x[key] == c]) for c in clusters}
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        d, h, a = [], [], []
        for _ in clusters:
            wd, wh, wa = by[clusters[rng.randrange(len(clusters))]]
            d += wd
            h += wh
            a += wa
        rho, *_ = _noise_components(d, h, a)
        if rho is not None:
            values.append(rho)
    if not values:
        return None
    values.sort()
    return values[min(len(values) - 1, max(0, math.ceil(q * len(values)) - 1))]


def noise_gate(obs: GateObservations, *, min_effect: float | None = None,
               candidates: Sequence[float] = CANDIDATE_MIN_EFFECTS, seed: int = GATE_BOOTSTRAP_SEED,
               resamples: int = GATE_BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    """The label-free pre-freeze gate (A.A): PASS only when the week-cluster bootstrap upper 90% bound of the
    book-noise correlation is below rho_max for delta_min; FAIL on mirror quoting or a bound at or above
    rho_max; INSUFFICIENT_DATA otherwise. delta_min UNKNOWN (None): the verdict is given per candidate only."""
    disp = [x[2] for x in obs.dispersions]
    rep_h = [x[2] for x in obs.repeats_home]
    rep_a = [x[2] for x in obs.repeats_away]
    gaps = [x[2] for x in obs.gaps]
    weeks = sorted({x[0] for x in obs.dispersions})
    rho, var_d, s2h, s2a = _noise_components(disp, rep_h, rep_a)
    upper_week = _cluster_upper(obs, key=0, seed=seed, resamples=resamples)
    upper_game = _cluster_upper(obs, key=1, seed=seed, resamples=resamples)
    # The gate uses the larger (more conservative) of the two bounds.
    upper = None if upper_week is None or upper_game is None else max(upper_week, upper_game)
    gap_sd = statistics.stdev(gaps) if len(gaps) >= 2 else None
    # The noise scale behind b_hat is floored at var(d)/2: sticky quotes make repeat books understate the noise,
    # while the same-capture dispersion carries it (sigma2 >= var(d)/2 whenever rho >= 0).
    sigma2_repeat = None if s2h is None or s2a is None else (s2h + s2a) / 2
    sigma2 = None if sigma2_repeat is None else max(sigma2_repeat, (var_d or 0.0) / 2)
    b_hat = None if sigma2 is None or not gap_sd else naive_bias(sigma2, gap_sd)
    spreads = [x[2] for x in obs.spreads]
    sigma2_spread = sum(s * s for s in spreads) / len(spreads) / 12 if spreads else None
    rho_spread = (None if not sigma2_spread or var_d is None
                  else max(-1.0, min(1.0, 1 - var_d / (2 * sigma2_spread))))
    mirror = var_d is not None and len(disp) >= GATE_MIN_PAIRS and var_d <= MIRROR_VARIANCE
    insufficient = []
    if len(disp) < GATE_MIN_PAIRS:
        insufficient.append(f"{len(disp)} same-capture cross-book pairs < {GATE_MIN_PAIRS}")
    if min(len(rep_h), len(rep_a)) < GATE_MIN_REPEATS:
        insufficient.append(f"repeat pairs home {len(rep_h)} / away {len(rep_a)} < {GATE_MIN_REPEATS} each")
    if len(weeks) < GATE_MIN_WEEKS:
        insufficient.append(f"{len(weeks)} NFL week(s) < {GATE_MIN_WEEKS}: no week-cluster bound")
    if len(gaps) < GATE_MIN_GAPS:
        insufficient.append(f"{len(gaps)} T-6h consensus gaps < {GATE_MIN_GAPS}: no b_hat")
    if (s2h == 0 or s2a == 0) and rep_h and rep_a:
        insufficient.append("REPEAT_NOISE_ZERO: repeat books never changed within 15 min, so the repeat estimator "
                            "cannot scale the noise (persistent quotes); the gate cannot certify")
    if rho is not None and (rho < 0 or (upper is not None and upper < 0)):
        insufficient.append(f"MODEL_MISFIT: repeat noise inconsistent with dispersion (rho_hat {rho:.3f}, upper "
                            f"{'n/a' if upper is None else f'{upper:.3f}'}): repeat books understate the noise "
                            "(sticky quotes), so rho cannot be bounded from them")
    if upper is None and not insufficient:
        insufficient.append("the week- or game-cluster bound is not estimable")

    def verdict(delta: float) -> dict[str, Any]:
        limit = rho_max(delta, b_hat)
        if mirror:
            return {"min_effect": delta, "rho_max": limit, "verdict": FAIL, "freeze_eligible": False,
                    "why": "MIRROR_QUOTING: same-capture cross-book dispersion is zero (rho = 1)"}
        if insufficient or limit is None or upper is None:
            return {"min_effect": delta, "rho_max": limit, "verdict": INSUFFICIENT, "freeze_eligible": False,
                    "why": "; ".join(insufficient)}
        ok = upper < limit
        return {"min_effect": delta, "rho_max": limit, "verdict": PASS if ok else FAIL, "freeze_eligible": False,
                "why": f"upper 90% bound {upper:.4f} {'<' if ok else '>='} rho_max {limit:.4f}"
                       + (f"; {FREEZE_INELIGIBLE_REASON}" if ok else "")}

    table = [verdict(d) for d in candidates]
    chosen = verdict(min_effect) if min_effect is not None else None
    if chosen is not None:
        overall = chosen["verdict"]
    elif mirror:
        overall = FAIL
    elif insufficient:
        overall = INSUFFICIENT
    else:
        overall = "BY_MIN_EFFECT"  # delta_min is UNKNOWN until the freeze: read the candidate table
    gap_sorted = sorted(obs.repeat_gap_seconds)
    return {
        "version": GATE_VERSION, "label_free": True,
        "reads": "only the T-24h and T-6h paired books and repeat books of the same market within 15 min inside "
                 "that horizon; never a T-60m book (a label for the markout); the catalog it runs on carries no "
                 "settled listing field (result, settlement value, expiration value)",
        "verdict": overall, "min_effect": min_effect,
        # Nothing in gate v2 authorizes a freeze, whatever the verdict.
        "freeze_eligible": False, "freeze_ineligible_reason": FREEZE_INELIGIBLE_REASON,
        "min_effect_state": "SUPPLIED" if min_effect is not None else "UNKNOWN: frozen only at preregistration",
        "verdict_for_min_effect": chosen, "by_candidate_min_effect": table,
        "estimates": {"rho_hat": rho, "rho_upper_90": upper, "rho_upper_90_week": upper_week,
                      "rho_upper_90_game": upper_game, "var_dispersion": var_d, "sigma2_home": s2h,
                      "sigma2_away": s2a, "sigma2_repeat": sigma2_repeat, "sigma2_for_b_hat": sigma2,
                      "gap_sd": gap_sd, "b_hat": b_hat, "mirror_quoting": mirror},
        "diagnostic_spread_estimator": {
            "state": "DIAGNOSTIC ONLY: the PROPOSED single-capture noise scale (docs/research/"
                     "RESEARCH_UNBLOCKING_DECISIONS.md A.I); not used for the verdict",
            "sigma2_spread_uniform": sigma2_spread, "rho_hat_spread": rho_spread, "books": len(spreads),
            "model": "the fair value lies uniformly inside the quoted spread: sigma2 = mean(spread^2) / 12"},
        "counts": {**obs.counts, "weeks": len(weeks), "books_read": len(obs.books_read)},
        "repeat_gap_seconds": {"n": len(gap_sorted), "median": statistics.median(gap_sorted) if gap_sorted else None,
                               "max": gap_sorted[-1] if gap_sorted else None},
        "insufficient": insufficient,
        "method": {"rho_hat": "(sigma2_home + sigma2_away - var(d)) / (2 sqrt(sigma2_home sigma2_away)), clipped to "
                              "[-1, 1]; sigma2 = 1/2 mean(repeat difference^2); a negative rho_hat or bound is "
                              "MODEL_MISFIT (INSUFFICIENT_DATA), so the gate prefers a false INSUFFICIENT_DATA to a "
                              "false PASS",
                   "bound": f"one-sided 90% percentile of a week-cluster and a game-cluster bootstrap (seed {seed}, "
                            f"{resamples} resamples each); the larger is used",
                   "rho_max": "(1/4 * delta_min) / b_hat, b_hat = sigma2 * sqrt(2/pi) / sd(consensus - H at T-6h), "
                              "sigma2 = max(repeat sigma2, var(d)/2)",
                   "floors": {"pairs": GATE_MIN_PAIRS, "repeats_each": GATE_MIN_REPEATS, "weeks": GATE_MIN_WEEKS,
                              "gaps": GATE_MIN_GAPS},
                   "limitation": "noise that persists across the repeat gap understates sigma2 and rho_hat. Severe "
                                 "stickiness shows as MODEL_MISFIT; moderate stickiness still biases rho_hat and b_hat "
                                 "low, so read the repeat-gap and repeat counts with the verdict"},
    }


def cross_book_markout(c: float, c_prime: float, h6: float, a6: float, h1: float, a1: float) -> float:
    """y = 1/2 [sign(c - H6)(A1 - A6) + sign(c' - A6)(H1 - H6)], all in home-team units (A = 1 - away mid):
    each half takes its sign from one book and its markout from the other."""
    return 0.5 * (_sign(c - h6) * (a1 - a6) + _sign(c_prime - a6) * (h1 - h6))


def kalshi_only_placebo(h24: float, a24: float, h6: float, a6: float, h1: float, a1: float) -> float:
    """The same statistic with the consensus replaced by each signal book's own T-24h mid (no consensus
    information). Supplementary: it also reacts to Kalshi's own momentum or reversal."""
    return 0.5 * (_sign(h24 - h6) * (a1 - a6) + _sign(a24 - a6) * (h1 - h6))


def _contract_value(side: Mapping[str, Any], policy: JoinPolicy) -> tuple[float | None, str]:
    """The consensus value of this side's YES contract for the sign: the tie-adjusted interval midpoint when the
    protocol's tie and non-standard-resolution bounds are declared, else the unadjusted consensus (flagged)."""
    p = _dec(side.get("consensus_probability"))
    if p is None:
        return None, "NO_CONSENSUS"
    interval = tie_adjusted_interval(p, _dec((side.get("rules") or {}).get("tie_payout")),
                                     policy.tie_probability_bound, policy.postponement_probability_bound)
    if interval is None:
        return float(p), "UNADJUSTED: tie and non-standard-resolution bounds are not declared (sign only)"
    return float((interval[0] + interval[1]) / 2), "TIE_ADJUSTED_MIDPOINT"


def _first_book(catalog: KalshiCatalog, ticker: str, start: datetime, end: datetime) -> tuple[datetime, int, str, str] | None:
    books = [b for b in catalog.books.get(ticker, []) if start <= b[0] <= end]
    return min(books, key=lambda b: (b[0], b[1])) if books else None


def _cluster_interval(values_by_week: Mapping[str, list[float]], *, seed: int, resamples: int) -> list[float] | None:
    weeks = sorted(values_by_week)
    if len(weeks) < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        pooled = [v for _ in weeks for v in values_by_week[weeks[rng.randrange(len(weeks))]]]
        if pooled:
            means.append(sum(pooled) / len(pooled))
    means.sort()
    return [means[int(0.05 * (len(means) - 1))], means[int(0.95 * (len(means) - 1))]] if means else None


def markout_endpoint(rows: Sequence[Mapping[str, Any]], targets: Sequence[Mapping[str, Any]], catalog: KalshiCatalog,
                     mids: Callable[[str, int, datetime], tuple[float | None, float | None]], *, as_of: datetime,
                     policy: JoinPolicy, seed: int = GATE_BOOTSTRAP_SEED,
                     resamples: int = GATE_BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    """Per game: the cross-book markout from the T-6h pair to the FIRST T-60m book of each team market, the
    Kalshi-only placebo from the T-24h pair, week summaries and the A.G pilot outputs. Reads labels (the T-60m
    books): call it only from a logged results path."""
    by_game: dict[str, dict[str, Mapping[str, Any]]] = {}
    for r in rows:
        by_game.setdefault(r["event_id"], {})[r["horizon"]] = r
    target_of: dict[tuple[str, str], Mapping[str, Any]] = {}
    for t in targets:
        if t.get("state") != "SUPERSEDED":
            target_of[(t["event_id"], t["offset_label"])] = t
    counts = {"games": 0, "t6_due": 0, "t6_paired": 0, "t60_due": 0, "t60_pending": 0, "t60_books_found": 0,
              "no_t6_pair": 0, "no_t6_mid": 0, "no_t60_target": 0, "no_t60_book": 0, "no_t60_mid": 0,
              "no_consensus": 0, "evaluated": 0, "with_placebo": 0}
    games, by_timing = [], {BOOK_BEFORE_ODDS: 0, BOOK_AT_OR_AFTER_ODDS: 0, "UNKNOWN": 0}
    for event_id in sorted(by_game):
        horizons = by_game[event_id]
        r6 = horizons.get(SIGNAL_HORIZON)
        if r6 is None or r6.get("status") in (SUPERSEDED, NOT_YET_DUE):
            continue
        counts["games"] += 1
        counts["t6_due"] += 1
        home_team, away_team = r6.get("home_team"), r6.get("away_team")
        sides = r6.get("sides") or {}
        hs, as_ = sides.get(home_team), sides.get(away_team)
        if r6.get("status") != PAIRED or hs is None or as_ is None:
            counts["no_t6_pair"] += 1
            continue
        counts["t6_paired"] += 1
        h6, am6 = _mid(hs.get("yes_bid"), hs.get("yes_ask")), _mid(as_.get("yes_bid"), as_.get("yes_ask"))
        if h6 is None or am6 is None:
            counts["no_t6_mid"] += 1
            continue
        a6 = 1 - am6
        c, c_basis = _contract_value(hs, policy)
        c_away, _ = _contract_value(as_, policy)
        if c is None or c_away is None:
            counts["no_consensus"] += 1
            continue
        c_prime = 1 - c_away
        t60 = target_of.get((event_id, TARGET_HORIZON))
        if t60 is None:
            counts["no_t60_target"] += 1
            continue
        target = _capture_target(t60)
        start, end = effective_due(target, PILOT_CONFIG) - PILOT_CONFIG.early_tolerance, deadline(target, PILOT_CONFIG)
        if end > as_of:
            counts["t60_pending"] += 1
            continue
        counts["t60_due"] += 1
        books = {role: _first_book(catalog, s["ticker"], start, end) for role, s in (("home", hs), ("away", as_))}
        if books["home"] is None or books["away"] is None:
            counts["no_t60_book"] += 1
            continue
        counts["t60_books_found"] += 1
        h1, sp_h1 = mids(hs["ticker"], books["home"][1], books["home"][0])
        am1, sp_a1 = mids(as_["ticker"], books["away"][1], books["away"][0])
        if h1 is None or am1 is None:
            counts["no_t60_mid"] += 1
            continue
        a1 = 1 - am1
        y = cross_book_markout(c, c_prime, h6, a6, h1, a1)
        counts["evaluated"] += 1
        for s in (hs, as_):
            timing = s.get("book_timing")
            by_timing[timing if timing in by_timing else "UNKNOWN"] += 1
        game = {"event_id": event_id, "week": r6["week_cluster"], "commence_utc": r6.get("commence_utc"),
                "home_team": home_team, "consensus_value_home": c, "consensus_value_home_from_away": c_prime,
                "consensus_basis": c_basis, "H6": h6, "A6": a6, "H1": h1, "A1": a1,
                "spreads": {"H6": _spread(hs.get("yes_bid"), hs.get("yes_ask")),
                            "A6": _spread(as_.get("yes_bid"), as_.get("yes_ask")), "H1": sp_h1, "A1": sp_a1},
                "t6_book_timing": {"home": hs.get("book_timing"), "away": as_.get("book_timing")},
                "t6_decision_utc": max(hs.get("decision_utc") or "", as_.get("decision_utc") or ""),
                "t60_books": {"home": {"snapshot_id": books["home"][1], "received_utc": _iso(books["home"][0])},
                              "away": {"snapshot_id": books["away"][1], "received_utc": _iso(books["away"][0])}},
                "y": y, "y_placebo": None, "H24": None, "A24": None}
        # The placebo needs only the Kalshi books: the first book of each market in the T-24h window, whether or
        # not the T-24h odds capture paired.
        t24 = target_of.get((event_id, PRIOR_HORIZON))
        if t24 is not None:
            prior = _capture_target(t24)
            p_start = effective_due(prior, PILOT_CONFIG) - PILOT_CONFIG.early_tolerance
            p_end = min(deadline(prior, PILOT_CONFIG), as_of)
            b24 = {role: _first_book(catalog, s["ticker"], p_start, p_end) for role, s in (("home", hs), ("away", as_))}
            if b24["home"] is not None and b24["away"] is not None:
                h24, _ = mids(hs["ticker"], b24["home"][1], b24["home"][0])
                am24, _ = mids(as_["ticker"], b24["away"][1], b24["away"][0])
                if h24 is not None and am24 is not None:
                    game.update(H24=h24, A24=1 - am24, y_placebo=kalshi_only_placebo(h24, 1 - am24, h6, a6, h1, a1))
                    counts["with_placebo"] += 1
        games.append(game)
    ys = [g["y"] for g in games]
    pls = [g for g in games if g["y_placebo"] is not None]
    weeks: dict[str, list[float]] = {}
    diffs: dict[str, list[float]] = {}
    for g in games:
        weeks.setdefault(g["week"], []).append(g["y"])
        if g["y_placebo"] is not None:
            diffs.setdefault(g["week"], []).append(g["y"] - g["y_placebo"])
    pl_by_week: dict[str, list[float]] = {}
    for g in pls:
        pl_by_week.setdefault(g["week"], []).append(g["y_placebo"])
    week_rows = [{"week": w, "games": len(v), "mean_y": sum(v) / len(v),
                  "mean_y_placebo": sum(pl_by_week[w]) / len(pl_by_week[w]) if w in pl_by_week else None}
                 for w, v in sorted(weeks.items())]
    roll = _roll_sensitivity(games)
    return {
        "version": MARKOUT_VERSION, "label_reads": "the FIRST book of each team market in the T-60m horizon window "
                                                   "(a label for the T-6h decision); logged results path only",
        "statistic": "y = 1/2 [sign(c - H6)(A1 - A6) + sign(c' - A6)(H1 - H6)], home-team units, A = 1 - away mid",
        "placebo": "y_pl = 1/2 [sign(H24 - H6)(A1 - A6) + sign(A24 - A6)(H1 - H6)] (supplementary)",
        "games": games, "counts": counts, "t6_book_timing": by_timing,
        "summary": {
            "state": "PILOT DESCRIPTIVE — NOT A TEST (development data; no frozen endpoint, no inference)",
            "games": len(games), "weeks": len(weeks), "mean_y": sum(ys) / len(ys) if ys else None,
            "sd_y": statistics.stdev(ys) if len(ys) >= 2 else None,
            "mean_y_placebo": sum(g["y_placebo"] for g in pls) / len(pls) if pls else None,
            "mean_y_minus_placebo": (sum(g["y"] - g["y_placebo"] for g in pls) / len(pls)) if pls else None,
            "week_cluster_90_interval_mean_y": _cluster_interval(weeks, seed=seed, resamples=resamples),
            "week_cluster_90_interval_mean_y_minus_placebo": _cluster_interval(diffs, seed=seed, resamples=resamples),
            "by_week": week_rows},
        "pilot_outputs": {
            "t6_pairing_yield": None if not counts["t6_due"] else counts["t6_paired"] / counts["t6_due"],
            "t60_book_yield": None if not counts["t60_due"] else counts["t60_books_found"] / counts["t60_due"],
            "markout_sd": statistics.stdev(ys) if len(ys) >= 2 else None,
            "post_label_roll_sensitivity": roll},
    }


def _roll_sensitivity(games: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """POST-LABEL sensitivity only (it needs the T-60m book), never the gate: sigma2 = -cov(X6 - X24, X1 - X6)
    per market role, and rho from the T-6h cross-book dispersion. Biased toward passing under Kalshi momentum."""
    full = [g for g in games if g["H24"] is not None]
    if len(full) < 3:
        return {"state": "INSUFFICIENT_DATA", "games": len(full)}

    def neg_cov(a: list[float], b: list[float]) -> float:
        return -statistics.covariance(a, b)

    s2h = neg_cov([g["H6"] - g["H24"] for g in full], [g["H1"] - g["H6"] for g in full])
    s2a = neg_cov([g["A6"] - g["A24"] for g in full], [g["A1"] - g["A6"] for g in full])
    var_d = statistics.variance([g["H6"] - g["A6"] for g in full])
    rho = None if s2h <= 0 or s2a <= 0 else max(-1.0, min(1.0, (s2h + s2a - var_d) / (2 * math.sqrt(s2h * s2a))))
    return {"state": "POST_LABEL_SENSITIVITY (not the gate; logged DEVELOPMENT data)", "games": len(full),
            "sigma2_home": s2h, "sigma2_away": s2a, "var_dispersion_t6": var_d, "rho_hat": rho}


# --------------------------------------------------------------------------- EXP-002 gate v3 (2026-09-28)
#
# Owner directive 2026-09-28 §7 (docs/owner/2026-09-28-exp002-validation-inplay-foundation-directive.md) and
# docs/research/EXP002_GATE_V3.md. The spread-based noise scale of A.I option (ii) was a CANDIDATE needing
# validation. The adversarial simulation (`scripts/research_power_sensitivity.py --gate-v3-validation`) shows
# that it passes at far more than 10% while the true bias exceeds the tolerable level (sticky, stale and
# shared-upstream quotes), because a quoted spread is not a bound on latent error, staleness or common
# market-maker noise. So gate v3 does not estimate a noise scale from spreads. It computes the one bound that
# spreads CAN support, and only under a stated, untestable assumption:
#
#   (W) within-spread: each book's reverting mid error |e| = |mid - V| is at most half its quoted spread, where V
#       is the value the book's price later reverts around (the latent martingale of the A.A null);
#   (I) the consensus deviation w = c - V is independent of the books' errors at the decision time;
#   (R) the T-60m error is mean-zero given the T-6h information, or persists with a coefficient in [0, 1].
#
# Under (W), (I), (R) and the A.A null (the latent value is a martingale that the consensus does not predict), the
# bias of one half of the cross-book statistic, E[sign(c - H6)(A1 - A6)], is at most E[s_A * 1{|c - H6| <= s_H}]:
# sign(w - e_H) differs from sign(w) only when w lies between 0 and e_H, E[sign(w) e_A] = 0 under (I), |e_A| <=
# s_A / 2 under (W), and |w| <= |e_H| implies |c - H6| = |w - e_H| <= s_H. No distribution, density or noise
# correlation is assumed (the worst case, perfectly shared error, is allowed). The bound is label-free: T-6h
# features only.
#
# (W) cannot be checked from these observations. A stale or sticky quote, or an error shared by both team books
# (one market maker, one upstream source), puts V outside the quoted spread without changing any spread, any
# same-capture dispersion or any T-6h gap. Hence the verdict is never PASS:
#   FAIL                  the data refute the cross-book premise (mirror quoting: the two books are one quote);
#   INSUFFICIENT_DATA     the sample floors are not met;
#   INSUFFICIENT_EVIDENCE otherwise. Its bound state says whether even the conditional bound reaches the tolerable
#                         bias (then spreads cannot bound it at all) or stays below it (then it rests on (W),
#                         which the data cannot identify).
# A diagnostic below the tolerable level is never freeze eligibility. v2 (`noise_gate`) and its results stay as
# they were.

GATE_V3_VERSION = "exp002-noise-gate-v3"
GATE_V3_HORIZONS = (SIGNAL_HORIZON, PRIOR_HORIZON)  # T-6h: the bound; T-24h: dispersion diagnostics only
# Sample floors (implementation parameters, not research thresholds; they gate INSUFFICIENT_DATA only):
# 20 admissible T-6h games as in v2, and four NFL weeks so the week-cluster bootstrap has more than 27 distinct
# resamples (three weeks give 3^3 = 27).
GATE_V3_MIN_GAMES, GATE_V3_MIN_WEEKS = 20, 4
V3_FAIL, V3_INSUFFICIENT_DATA, V3_INSUFFICIENT_EVIDENCE = "FAIL", "INSUFFICIENT_DATA", "INSUFFICIENT_EVIDENCE"
V3_BOUND_AT_OR_ABOVE = "CONDITIONAL_BOUND_AT_OR_ABOVE_TOLERABLE"
V3_BOUND_BELOW = "CONDITIONAL_BOUND_BELOW_TOLERABLE_BUT_ASSUMPTION_W_UNIDENTIFIED"
V3_BOUND_UNKNOWN = "CONDITIONAL_BOUND_NOT_ESTIMABLE"
WIDE_SPREAD = 0.03  # display only: a book at or above 3 cents is counted as wide; nothing is excluded for it
V3_NOT_A_BOUND = ("A quoted spread is not a bound on latent pricing error, staleness or common market-maker noise: "
                  "a stale, sticky or commonly mispriced quote can be 1 cent wide while the value it later reverts "
                  "around lies outside it.")
V3_ASSUMPTIONS = {
    "W": "within-spread: |mid - V| <= spread / 2 for each T-6h book (V = the value the price later reverts around); "
         "NOT identified from these observations",
    "I": "the consensus deviation c - V is independent of the T-6h book errors; not testable without V",
    "R": "the T-60m book error is mean-zero given T-6h information, or persists with a coefficient in [0, 1]; "
         "needs later prices (labels) to check",
    "N": "the A.A null: the latent value is a martingale the consensus does not predict (the hypothesis under test)",
}
V3_UNIDENTIFIED = (
    "a reverting error shared by both team books (one market maker or one upstream source): it cancels in the "
    "same-capture dispersion H - (1 - away mid) and leaves every spread unchanged",
    "staleness: Kalshi books carry no per-level update time, so one capture cannot tell a current quote from a stale "
    "one (receipt time is the only clock)",
    "latent error beyond the quoted spread: only later prices (T-60m books, labels) or dense repeats show it",
    "the split between reversion and momentum between T-6h and T-60m (needs later prices)",
    "the distribution of the error inside the spread (uniform, two-point or skewed): v3 assumes none",
    "week-level dependence (ICC) from four or fewer weeks: the bootstrap reflects it only as far as the weeks allow",
)
V3_PERMITTED = ("diagnostic reporting of the label-free spread, gap and dispersion distributions",
                "stating the size of the conditional bound under assumption W, labelled conditional",
                "planning a smaller question, an altered design or a bounded acquisition proposal")
V3_NOT_PERMITTED = ("freeze eligibility or a freeze decision", "promotion of any EXP-002 state",
                    "a claim that the markout is unbiased", "tuning an estimator, floor or multiplier until it passes")


@dataclass(frozen=True)
class GateV3Game:
    """One admissible T-6h game, in home-team units (A = 1 - away mid): the inputs of the markout's sign."""

    week: str
    game: str
    h_mid: float
    h_spread: float
    a_mid: float
    a_spread: float
    c: float  # consensus value of the home YES contract (the markout's `c`)
    c_prime: float  # 1 - consensus value of the away YES contract (the markout's `c'`)
    timing: tuple[str | None, str | None]
    capture_skew_seconds: int | None


@dataclass(frozen=True)
class GateV3Observations:
    games: tuple[GateV3Game, ...]
    dispersions: tuple[tuple[str, str, str, float], ...]  # (horizon, week, game, H - A) same capture
    spreads: tuple[tuple[str, float], ...]  # (horizon, spread) of every two-sided paired book
    counts: dict[str, int]


def _book_state(side: Mapping[str, Any]) -> str:
    b, a = _dec(side.get("yes_bid")), _dec(side.get("yes_ask"))
    if b is None or a is None:
        return "ONE_SIDED_OR_EMPTY"
    if b == a:
        return "LOCKED"
    if b > a:
        return "CROSSED"
    return "TWO_SIDED"


def gate_v3_observations(rows: Sequence[Mapping[str, Any]], policy: JoinPolicy = JoinPolicy()) -> GateV3Observations:
    """The gate's inputs from T-6h and T-24h rows only (the join's own feature fields; no book is read here).
    Every due T-6h row lands in exactly one count; nothing outside `GATE_V3_HORIZONS` is looked at."""
    counts = {"rows_other_horizon_ignored": 0, "t6_due": 0, "t6_not_yet_due_or_superseded": 0,
              "t6_not_paired": 0, "t6_book_one_sided_or_empty": 0, "t6_book_locked": 0, "t6_book_crossed": 0,
              "t6_no_consensus": 0, "t6_admissible": 0, "t6_admissible_book_at_or_after_odds": 0,
              "t6_admissible_book_before_odds": 0, "t6_admissible_book_timing_unknown": 0,
              "t24_due_paired": 0, "dispersion_pairs": 0, "not_same_capture": 0, "wide_books": 0}
    games: list[GateV3Game] = []
    disp: list[tuple[str, str, str, float]] = []
    spreads: list[tuple[str, float]] = []
    for r in rows:
        horizon = r.get("horizon")
        if horizon not in GATE_V3_HORIZONS:
            counts["rows_other_horizon_ignored"] += 1
            continue
        if r.get("status") in (SUPERSEDED, NOT_YET_DUE):
            if horizon == SIGNAL_HORIZON:
                counts["t6_not_yet_due_or_superseded"] += 1
            continue
        if horizon == SIGNAL_HORIZON:
            counts["t6_due"] += 1
        sides = r.get("sides") or {}
        home, away = sides.get(r.get("home_team")), sides.get(r.get("away_team"))
        if r.get("status") != PAIRED or home is None or away is None:
            if horizon == SIGNAL_HORIZON:
                counts["t6_not_paired"] += 1
            continue
        states = (_book_state(home), _book_state(away))
        if states != ("TWO_SIDED", "TWO_SIDED"):
            if horizon == SIGNAL_HORIZON:
                worst = next(s for s in ("CROSSED", "LOCKED", "ONE_SIDED_OR_EMPTY") if s in states)
                counts[f"t6_book_{worst.lower()}"] += 1
            continue
        h, am = _mid(home.get("yes_bid"), home.get("yes_ask")), _mid(away.get("yes_bid"), away.get("yes_ask"))
        sh, sa = _spread(home.get("yes_bid"), home.get("yes_ask")), _spread(away.get("yes_bid"), away.get("yes_ask"))
        a = 1 - am
        week, game = r["week_cluster"], r["event_id"]
        for s in (sh, sa):
            spreads.append((horizon, s))
            counts["wide_books"] += s >= WIDE_SPREAD - 1e-12
        rh, ra = parse_utc(home.get("book_received_utc")), parse_utc(away.get("book_received_utc"))
        skew = None if rh is None or ra is None else int(abs((rh - ra).total_seconds()))
        if skew is None or skew > SAME_CAPTURE_MAX.total_seconds():
            counts["not_same_capture"] += 1
        else:
            disp.append((horizon, week, game, h - a))
            counts["dispersion_pairs"] += 1
        if horizon == PRIOR_HORIZON:
            counts["t24_due_paired"] += 1
            continue
        c, _ = _contract_value(home, policy)
        c_away, _ = _contract_value(away, policy)
        if c is None or c_away is None:
            counts["t6_no_consensus"] += 1
            continue
        timing = (home.get("book_timing"), away.get("book_timing"))
        for t in timing:
            key = {BOOK_AT_OR_AFTER_ODDS: "at_or_after_odds", BOOK_BEFORE_ODDS: "before_odds"}.get(t, "timing_unknown")
            counts[f"t6_admissible_book_{key}"] += 1
        counts["t6_admissible"] += 1
        games.append(GateV3Game(week, game, h, sh, a, sa, c, 1 - c_away, timing, skew))
    return GateV3Observations(tuple(games), tuple(disp), tuple(spreads), counts)


def v3_bias_bound_terms(games: Sequence[GateV3Game]) -> list[tuple[str, str, float]]:
    """Per game: 1/2 [s_A 1{|c - H6| <= s_H} + s_H 1{|c' - A6| <= s_A}], the conditional bound on the bias of the
    two halves of the cross-book statistic under (W), (I) and (R). Probability units; (week, game, term)."""
    eps = 1e-12  # float guard: a gap equal to the spread counts as inside
    return [(g.week, g.game, 0.5 * (g.a_spread * (abs(g.c - g.h_mid) <= g.h_spread + eps)
                                     + g.h_spread * (abs(g.c_prime - g.a_mid) <= g.a_spread + eps))) for g in games]


def _mean_upper(terms: Sequence[tuple[str, str, float]], *, key: int, seed: int, resamples: int,
                q: float = 0.9) -> float | None:
    """One-sided upper `q` percentile of the mean of `terms`, resampling whole clusters (`key` 0: weeks, 1: games).
    None with fewer than two clusters."""
    clusters = sorted({t[key] for t in terms})
    if len(clusters) < 2:
        return None
    by = {c: [t[2] for t in terms if t[key] == c] for c in clusters}
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        pooled = [v for _ in clusters for v in by[clusters[rng.randrange(len(clusters))]]]
        means.append(sum(pooled) / len(pooled))
    means.sort()
    return means[min(len(means) - 1, max(0, math.ceil(q * len(means)) - 1))]


def _quantiles(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "min": None, "median": None, "max": None}
    v = sorted(values)
    return {"n": len(v), "min": v[0], "median": statistics.median(v), "max": v[-1]}


def noise_gate_v3(obs: GateV3Observations, *, min_effect: float | None = None,
                  candidates: Sequence[float] = CANDIDATE_MIN_EFFECTS, seed: int = GATE_BOOTSTRAP_SEED,
                  resamples: int = GATE_BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    """Gate v3 (see the section comment). Never PASS; `freeze_eligible` is always False; `diagnostic_only` True."""
    games = obs.games
    weeks = sorted({g.week for g in games})
    terms = v3_bias_bound_terms(games)
    bound = sum(t[2] for t in terms) / len(terms) if terms else None
    upper_week = _mean_upper(terms, key=0, seed=seed, resamples=resamples)
    upper_game = _mean_upper(terms, key=1, seed=seed, resamples=resamples)
    upper = None if upper_week is None or upper_game is None else max(upper_week, upper_game)
    disp6 = [d[3] for d in obs.dispersions if d[0] == SIGNAL_HORIZON]
    disp_all = [d[3] for d in obs.dispersions]
    var_d = statistics.variance(disp_all) if len(disp_all) >= 2 else None
    mirror = var_d is not None and len(disp_all) >= GATE_MIN_PAIRS and var_d <= MIRROR_VARIANCE
    gaps = [g.c - g.h_mid for g in games] + [g.c_prime - g.a_mid for g in games]
    inside = sum(abs(g.c - g.h_mid) <= g.h_spread + 1e-12 for g in games) + sum(
        abs(g.c_prime - g.a_mid) <= g.a_spread + 1e-12 for g in games)
    insufficient = []
    if len(games) < GATE_V3_MIN_GAMES:
        insufficient.append(f"{len(games)} admissible T-6h games < {GATE_V3_MIN_GAMES}")
    if len(weeks) < GATE_V3_MIN_WEEKS:
        insufficient.append(f"{len(weeks)} NFL week(s) < {GATE_V3_MIN_WEEKS}: no week-cluster bound")
    if upper is None and not insufficient:
        insufficient.append("the week- or game-cluster bound is not estimable")
    due = obs.counts.get("t6_due", 0)
    admissible_share = None if not due else len(games) / due

    def verdict(delta: float) -> dict[str, Any]:
        tolerable = TOLERABLE_FRACTION * delta
        state = V3_BOUND_UNKNOWN if upper is None else (V3_BOUND_BELOW if upper < tolerable else V3_BOUND_AT_OR_ABOVE)
        row = {"min_effect": delta, "tolerable_bias": tolerable, "bound_upper_90": upper, "bound_state": state,
               "freeze_eligible": False}
        if mirror:
            return {**row, "verdict": V3_FAIL, "why": "MIRROR_QUOTING: same-capture cross-book dispersion is zero, so "
                                                      "the two team books are one quote and the cross-book design "
                                                      "removes none of the reversion bias"}
        if insufficient:
            return {**row, "verdict": V3_INSUFFICIENT_DATA, "why": "; ".join(insufficient)}
        if state == V3_BOUND_AT_OR_ABOVE:
            why = (f"even under assumption W the spread-based bias bound (upper 90% {upper:.4f}) is at or above the "
                   f"tolerable {tolerable:.4f} (1/4 of delta_min): spreads cannot bound the bias at this delta_min")
        else:
            why = (f"the spread-based bias bound (upper 90% {upper:.4f}) is below the tolerable {tolerable:.4f} ONLY "
                   "under assumption W (value within the quoted spread), which these observations cannot identify; "
                   + V3_NOT_A_BOUND)
        return {**row, "verdict": V3_INSUFFICIENT_EVIDENCE, "why": why}

    table = [verdict(d) for d in candidates]
    chosen = verdict(min_effect) if min_effect is not None else None
    overall = V3_FAIL if mirror else (V3_INSUFFICIENT_DATA if insufficient else V3_INSUFFICIENT_EVIDENCE)
    return {
        "version": GATE_V3_VERSION, "label_free": True, "diagnostic_only": True,
        "reads": "the join's T-6h paired rows (bid, ask, consensus, book timing and receipt) and T-24h paired rows "
                 "(dispersion and spreads only); no book payload beyond the join's features, never a T-60m book, and "
                 "a catalog without settled listing fields",
        "input_horizons": {"bound": SIGNAL_HORIZON, "diagnostics": list(GATE_V3_HORIZONS)},
        "verdict": overall, "min_effect": min_effect,
        "min_effect_state": "SUPPLIED" if min_effect is not None else "UNKNOWN: frozen only at preregistration",
        "freeze_eligible": False,
        "freeze_ineligible_reason": ("gate v3 has no PASS state: spreads cannot identify latent, stale or common "
                                     "book error (docs/research/EXP002_GATE_V3.md); a diagnostic is never freeze "
                                     "eligibility"),
        "verdict_for_min_effect": chosen, "by_candidate_min_effect": table,
        "estimates": {"bias_bound_mean": bound, "bias_bound_upper_90": upper, "bias_bound_upper_90_week": upper_week,
                      "bias_bound_upper_90_game": upper_game,
                      "share_gaps_within_spread": None if not gaps else inside / len(gaps),
                      "gap_sd": statistics.stdev(gaps) if len(gaps) >= 2 else None,
                      "var_dispersion": var_d, "var_dispersion_t6": statistics.variance(disp6) if len(disp6) >= 2
                      else None, "mirror_quoting": mirror,
                      "share_dispersion_zero": None if not disp_all else sum(abs(x) < 1e-9 for x in disp_all) / len(disp_all),
                      "spreads_t6": _quantiles([s for h, s in obs.spreads if h == SIGNAL_HORIZON]),
                      "spreads_t24": _quantiles([s for h, s in obs.spreads if h == PRIOR_HORIZON]),
                      "admissible_share_of_due_t6": admissible_share},
        "counts": {**obs.counts, "weeks": len(weeks), "admissible_games": len(games)},
        "insufficient": insufficient,
        "not_a_bound": V3_NOT_A_BOUND,
        "assumptions": V3_ASSUMPTIONS, "unidentified": list(V3_UNIDENTIFIED),
        "permitted_uses": list(V3_PERMITTED), "not_permitted": list(V3_NOT_PERMITTED),
        "method": {
            "bound": "B = mean over admissible T-6h games of 1/2 [s_A 1{|c - H6| <= s_H} + s_H 1{|c' - A6| <= s_A}] "
                     "(probability units; H, A home-team mids, s their quoted spreads, c and c' the markout's consensus "
                     "values). Under W, I, R and the null, |bias of the cross-book markout| <= B. No distribution, "
                     "density or noise correlation is assumed; a shared (perfectly correlated) error is allowed",
            "uncertainty": f"one-sided 90% percentile of a week-cluster and a game-cluster bootstrap of B (seed {seed}, "
                           f"{resamples} resamples each); the larger is used",
            "tolerable": f"{TOLERABLE_FRACTION} x delta_min (A.A); delta_min UNKNOWN until the protocol freezes it",
            "floors": {"admissible_games": GATE_V3_MIN_GAMES, "weeks": GATE_V3_MIN_WEEKS,
                       "mirror_min_pairs": GATE_MIN_PAIRS},
            "books": "locked, crossed and one-sided T-6h books are excluded and counted (no mid); a book missing a "
                     "side or a horizon without a pair is counted as not paired (join stages keep the reason); stale "
                     "books never pair (the join's 5-min book age at the decision time); BEFORE_ODDS pairs enter, as "
                     "they enter the markout (comparability-only: never an executable price)",
            "validation": "scripts/research_power_sensitivity.py --gate-v3-validation (independent simulation seeds; "
                          "false-pass rates in docs/research/EXP002_GATE_V3.md)",
        },
    }


def exp002_gate_line(store: Any, *, as_of: datetime, rows: Sequence[Mapping[str, Any]] | None = None,
                     policy: JoinPolicy = JoinPolicy(), protocol: Mapping[str, Any] | None = None,
                     experiments_root: Path | None = None, resamples: int = GATE_BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    """The EXP-002 gate line for the Terminal (UI_CONTRACT §8 Family A): gate v3 over the T-6h / T-24h rows of an
    existing report (or a gate-only join), the evidence-use log's outcome-access status, and freeze eligibility
    kept separate. Label-free. Never raises: an error is a state."""
    try:
        if rows is None:
            rows = _join(store, as_of, policy, results=False, horizons=GATE_HORIZONS, drop_settled=True)[0]
        gate = noise_gate_v3(gate_v3_observations([r for r in rows if r.get("horizon") in GATE_V3_HORIZONS], policy),
                             resamples=resamples)
    except Exception as exc:  # noqa: BLE001 - shown as an error state
        return {"state": "ERROR", "version": GATE_V3_VERSION, "as_of_utc": _iso(as_of),
                "detail": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160] if str(exc) else ''}"}
    protocol = protocol if protocol is not None else protocol_status(experiments_root)
    return {"state": "OK", "version": GATE_V3_VERSION, "as_of_utc": _iso(as_of), "verdict": gate["verdict"],
            "input_horizons": gate["input_horizons"], "counts": gate["counts"], "estimates": gate["estimates"],
            "by_candidate_min_effect": gate["by_candidate_min_effect"], "insufficient": gate["insufficient"],
            "diagnostic_only": True, "label_free": True, "not_a_bound": gate["not_a_bound"],
            "unidentified": gate["unidentified"],
            "outcome_access": outcome_access(protocol, experiments_root),
            "freeze": freeze_eligibility(gate, protocol)}


def outcome_access(protocol: Mapping[str, Any], experiments_root: Path | None = None) -> dict[str, Any]:
    """EXP-002's logged label access (its own evidence-use log): how many logged views showed labels or results,
    the latest, and the roles. It records declared access only (the log's own limitation)."""
    experiment_id = protocol.get("experiment_id")
    if not experiment_id:
        return {"state": "NO_PROTOCOL", "detail": "no Family A experiment is registered, so there is no log to read"}
    try:
        log_path = None
        for path in registry.discover(experiments_root or REPO_EXPERIMENTS):
            exp = registry.load(path)
            if exp.id == experiment_id:
                log_path = exp.path.parent / rev.LOG_NAME
        if log_path is None or not log_path.exists():
            return {"state": "NO_LOG", "detail": f"{experiment_id} has no evidence-use log: access is UNKNOWN"}
        log = rev.read_log(log_path)
    except Exception as exc:  # noqa: BLE001 - an unreadable log is unknown access, never "none"
        return {"state": "UNREADABLE", "detail": f"evidence-use log unreadable: {type(exc).__name__}"}
    views = [u for u in log.uses if u.viewed_labels or u.viewed_results or u.action is rev.Action.LABEL_RESULT_INSPECTION]
    latest = max(views, key=lambda u: u.action_time_utc, default=None)
    return {"state": "LABEL_VIEWS_LOGGED" if views else "NO_LABEL_VIEW_LOGGED", "experiment_id": experiment_id,
            "log_started_utc": log.started_at_utc, "logged_uses": len(log.uses), "label_views": len(views),
            "latest_label_view_utc": None if latest is None else latest.action_time_utc,
            "latest_label_view_role": None if latest is None else latest.role.value,
            "roles": sorted({u.role.value for u in views}),
            "limitation": "declared access only: a log cannot prove nobody viewed the data another way"}


def freeze_eligibility(gate: Mapping[str, Any], protocol: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze eligibility, kept apart from the gate's diagnostic verdict. Always NOT_ELIGIBLE today: gate v3 has no
    PASS state; the reasons list every open blocker the repository itself records."""
    reasons = [f"gate {gate.get('version')} verdict {gate.get('verdict')}: no gate state authorizes a freeze"]
    state = protocol.get("state")
    if state != "DRAFT":
        reasons.append(f"protocol state {state}")
    else:
        reasons.append(f"{protocol.get('experiment_id')} is DRAFT with {len(protocol.get('unsettled_fields') or [])} "
                       "decision field(s) UNKNOWN or MISSING (delta_min, episode, tie bounds among them)")
    reasons.append("KXNFLGAME fees FEE_UNSUPPORTED (fee_schedules non-standard series)")
    reasons.append("freeze needs an owner-reviewed design that can identify the bias (docs/research/EXP002_GATE_V3.md)")
    return {"state": "NOT_ELIGIBLE", "reasons": reasons}


def measure_exp002(store: Any, *, as_of: datetime, results: bool = False, min_effect: float | None = None,
                   policy: JoinPolicy = JoinPolicy(), experiments_root: Path | None = None) -> dict[str, Any]:
    """The EXP-002 measurement over one read-only store. The gate always runs and is label-free: the join is
    built for the T-24h and T-6h horizons only, so no T-60m book is loaded for it. The markout endpoint runs only
    with `results=True` (its T-60m books are labels): the CLI records the view in EXP-002's evidence log first."""
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise ValueError("as_of must be a timezone-aware datetime")
    as_of = as_of.astimezone(UTC)
    rows, catalog, payloads, targets, _ = _join(store, as_of, policy, results=False, horizons=GATE_HORIZONS,
                                                drop_settled=True)
    reader = BookMids(payloads)
    gate = noise_gate(gate_observations(rows, catalog, reader), min_effect=min_effect)
    gate_reads = list(reader.read)
    gate_v3 = noise_gate_v3(gate_v3_observations(rows, policy), min_effect=min_effect)
    markout: dict[str, Any]
    if results:
        markout = markout_endpoint(rows, targets, catalog, reader, as_of=as_of, policy=policy)
    else:
        markout = {"state": "HIDDEN", "detail": "the markout reads the first T-60m book (an EXP-002 label); it is "
                                                "shown only by a logged run (exp002 --with-results)"}
    protocol = protocol_status(experiments_root)
    body = {"schema": "exp002-measurement/1", "label": MEASUREMENT_LABEL, "version": MEASUREMENT_VERSION,
            "join_version": JOIN_VERSION, "consensus_version": odds_consensus.CONSENSUS_VERSION,
            "policy": policy.to_dict(), "as_of_utc": _iso(as_of), "protocol": protocol,
            "labels": "INCLUDED (a logged --with-results run)" if results else "HIDDEN",
            "gate": gate, "gate_books_read": gate_reads, "gate_v3": gate_v3, "markout": markout,
            "economics_note": "economics inputs are unchanged: only book-at-or-after-odds pairs feed them "
                              "(build_report); BEFORE_ODDS pairs are comparability-only and counted"}
    plain = _plain(body)
    plain["output_sha256"] = sha256_hex(canonical_json(plain))
    return plain


# --------------------------------------------------------------------------- Terminal view

_VIEW_CACHE: "OrderedDict[tuple, dict[str, Any]]" = OrderedDict()  # key -> {"report": ..., "gate": ...}
VIEW_CACHE_MAX = 8


def _registry_key(root: Path | None) -> tuple:
    root = root or REPO_EXPERIMENTS
    try:
        return tuple((str(p), p.stat().st_mtime_ns) for p in sorted(root.glob("*/protocol.toml")))
    except OSError:
        return ("unreadable",)


_MARKERS: dict[str, tuple[int | None, int | None]] = {}  # db path -> newest NFL odds / KXNFLGAME snapshot id seen


def _newest_id(store: Any, *, source: str, kinds: Sequence[str], prefix: str | None, after: int | None,
               nfl: bool = False) -> int | None:
    """The newest matching snapshot id, paging only rows after the last marker (usually none)."""
    newest, cursor = after, after
    while True:
        page = store.snapshot_metadata(source=source, kinds=kinds, entity_prefix=prefix, limit=META_PAGE,
                                       after_id=cursor)
        for r in page:
            if not nfl or _is_nfl_entity(str(r["kind"]), str(r["entity_id"])):
                newest = int(r["id"])
        if len(page) < META_PAGE:
            return newest
        cursor = int(page[-1]["id"])


def _view_key(store: Any, now: datetime, root: Path | None) -> tuple:
    """Everything a report depends on grows monotonically: a new NFL odds snapshot, KXNFLGAME listing or book,
    odds transition or Polymarket observation changes its max id; newly due targets change the due count; a
    protocol edit changes its file time. Writes by other collectors (KXHIGHNY, NWS, ...) never invalidate it.
    Only the store's public reads (`snapshot_metadata`, `max_row_id`) are used."""
    path = str(store.path)
    odds_seen, kalshi_seen = _MARKERS.get(path, (None, None))
    top = store.max_row_id("snapshots")
    if top is None or any(m is not None and m > top for m in (odds_seen, kalshi_seen)):
        odds_seen = kalshi_seen = None  # a replaced or restored store: re-read from the start
    odds = _newest_id(store, source=ODDS_SOURCE, kinds=(odds_consensus.KIND,), prefix=None, after=odds_seen)
    kalshi = _newest_id(store, source=KALSHI, kinds=_KALSHI_KINDS, prefix=KALSHI_SERIES, after=kalshi_seen, nfl=True)
    _MARKERS[path] = (odds, kalshi)
    trans = store.max_row_id("odds_capture_transitions")
    pm = store.max_row_id("pm_sports_observations")
    due = sum(1 for r in store.odds_targets(sport=SPORT)
              if deadline(_capture_target(dict(r)), PILOT_CONFIG) <= now)
    return (path, odds, kalshi, trans, pm, due, _registry_key(root))


def _family_state(report: Mapping[str, Any], now: datetime) -> str:
    a = report["join"]
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
    if not a["paired_targets"] and not a["partial_targets"]:
        return "UNPAIRED"  # horizons fell due and none paired: not "partial"
    return "PARTIAL"


def _next_action(report: Mapping[str, Any]) -> tuple[str, str | None]:
    gaps = {g["id"]: g for g in report["gaps"]}
    if gaps.get("G2", {}).get("state") == "MISSING":
        return ("Owner decision: authorize the bounded Kalshi KXNFLGAME capture at the Odds horizons "
                "(docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md); no new timer is authorized today",
                "no Kalshi NFL books are stored")
    if "G7" in gaps:
        pid = report["protocol"].get("experiment_id") or "the Family A protocol"
        return (f"Settle and freeze {pid}'s endpoint, cutoffs, episode definition and tie treatment before any "
                "outcome is viewed", f"{pid} is {report['protocol'].get('state')}")
    if "G8" in gaps:
        return "Decide the tie / not-played treatment in the protocol", "payoff mapping unresolved"
    if "G4" in gaps:
        return "Re-verify the KXNFLGAME fee schedule", "fees unsupported"
    return "Continue stored-evidence research under the protocol", None


def view_from_report(report: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """A compact, display-ready summary: every figure is the report's own; nothing is recomputed."""
    rows = report["rows"]
    join = report["join"]
    paired = [(r, t, s) for r in rows for t, s in r["sides"].items() if s.get("stage") is None]
    # A T-60m book is EXP-002's markout label (a later price is an outcome too): the Terminal is not a logged
    # consumer of labels, so the "latest paired book" shown is the latest pre-label (T-24h / T-6h) one.
    shown = [x for x in paired if x[0].get("horizon") != TARGET_HORIZON]
    latest = max(shown, key=lambda x: (x[2]["decision_utc"], x[2]["ticker"]), default=None)
    sides = [s for r in rows for s in r["sides"].values()]
    rel = next((s["relation"] for s in sides if s.get("relation", {}).get("tier")), None)
    books = [s for s in sides if s.get("book_snapshot_id")]
    action, blocker = _next_action(report)
    econ = report["economics"]
    screen = econ.get("screen") or {}
    return {
        "state": _family_state(report, now), "family": report["family"], "title": report["title"],
        "label": report["label"], "protocol": report["protocol"], "as_of_utc": report["as_of_utc"],
        "window": report["window"], "denominators": join["denominators"],
        "join_stages": join["waterfall"], "paired_targets": join["paired_targets"],
        "partial_targets": join["partial_targets"], "paired_games": join["paired_games"],
        "paired_weeks": join["paired_weeks"], "outcome_labels": report["outcome_labels"],
        "protocol_attrition": {"denominators": report["attrition"]["denominators"],
                               "waterfalls": report["attrition"]["waterfalls"],
                               "not_applicable_stages": report["attrition"]["not_applicable_stages"],
                               "notes": report["attrition"]["notes"]},
        "relation": rel or {"tier": None, "reasons": ["no Kalshi market mapped yet: the relation is not established"]},
        "provenance": {
            "odds": f"The Odds API h2h · consensus {report['consensus_version']} (median of two-way de-vig)",
            "kalshi_rules": sorted({s["rules_sha256"] for s in sides if s.get("rules_sha256")}),
            "fee": next((g["why"] for g in report["gaps"] if g["id"] == "G4"), "priced by the registry"),
            "join": f"{report['join_version']} · {report['mapping_version']} · {report['rules_parser_version']}",
            "policy": report["policy"]},
        "edge_at_size": econ["edge_at_size"],
        "screen": {"verdict": econ["state"], "reasons": list(screen.get("verdict_reasons") or
                                                            ([econ["screen_problem"]] if econ.get("screen_problem")
                                                             else [])),
                   "episodes": econ["episodes"], "not_an_edge_claim": screen.get("not_an_edge_claim"),
                   "report_sha256": screen.get("report_sha256")},
        "capacity": {"sides_with_book": len(books), "truncated": sum(bool(s.get("depth_truncated")) for s in books),
                     "latest": None if latest is None else {
                         "team": latest[1], "ticker": latest[2]["ticker"], "decision_utc": latest[2]["decision_utc"],
                         "horizon": latest[0]["horizon"], "ladder": latest[2].get("capacity") or [],
                         "depth_truncated": latest[2].get("depth_truncated"),
                         "book_timing": latest[2].get("book_timing"), "pair_use": latest[2].get("pair_use"),
                         "visible_depth": latest[2].get("visible_depth"),
                         "lockup_hours": latest[2].get("lockup_hours")},
                     "fill_modes": econ["fill_modes"]},
        "economics_contract": econ["contract"], "fixed_costs": econ["fixed_costs"],
        "inputs": econ["inputs"], "gaps": report["gaps"], "sampling": report["sampling"],
        "next_action": action, "blocker": blocker, "report_sha256": report["output_sha256"],
    }


def terminal_view(db_path: str | Path, *, now: datetime, experiments_root: Path | None = None) -> dict[str, Any]:
    """Family A for the Terminal: the store opened read-only, outcome labels hidden (no state, no result, no
    count: the Terminal is not a logged consumer of EXP-002 labels), the report memoized until the evidence, the due set or a protocol changes. Never raises: NO_STORE / ERROR
    carry a short detail."""
    from .storage import ReadOnlyStoreError, SnapshotStore

    base = {"schema": VIEW_SCHEMA, "label": LABEL}
    path = Path(db_path)
    if not path.exists():
        return {**base, "state": "NO_STORE", "detail": f"{path.name} does not exist"}
    try:
        store = SnapshotStore.open_readonly(path)
        key = _view_key(store, now, experiments_root)
        cached = _VIEW_CACHE.get(key)
        if cached is None:
            report = build_report(store, as_of=now, experiments_root=experiments_root, results=False)
            # The EXP-002 gate line reads only the report's T-6h / T-24h rows (label-free), memoized with it.
            gate = exp002_gate_line(store, as_of=now, rows=report["rows"], protocol=report["protocol"],
                                    experiments_root=experiments_root)
            gate.pop("outcome_access", None)
            cached = _VIEW_CACHE[key] = {"report": report, "gate": gate}
            while len(_VIEW_CACHE) > VIEW_CACHE_MAX:
                _VIEW_CACHE.popitem(last=False)
        else:
            _VIEW_CACHE.move_to_end(key)
        report = cached["report"]
        family = view_from_report(report, now)
        # Outcome access is read from the evidence-use log on every view: a newly logged label view must show.
        gate = dict(cached["gate"])
        if gate.get("state") == "OK":
            gate["outcome_access"] = outcome_access(report["protocol"], experiments_root)
        family["exp002_gate"] = gate
        return {**base, "state": "OK", "family_a": family}
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


OUTCOME_SCOPE = "sports:nfl:moneyline"  # EXP-002's outcome scope (its evidence log covers it)


def _clock() -> datetime:
    """The wall clock (tests replace it: fixture stores live in the future)."""
    return datetime.now(UTC)


def record_results_view(report: Mapping[str, Any], *, log: Path, actor: str, code_version: str,
                        experiments_root: Path | None = None, now: datetime | None = None) -> str:
    """Log a report run that shows outcome labels, before anything is printed: one LABEL_RESULT_INSPECTION
    event in the given evidence-use log (`research_evidence.record_use`), with the protocol's prohibited
    inputs and label scopes enforced. Raises `research_evidence.EvidenceError` (ProhibitedInput included)
    when it cannot be logged; the caller then shows nothing."""
    shown = sorted(r["commence_utc"] for r in report["rows"]
                   if isinstance(r.get("outcome"), dict) and r.get("commence_utc"))
    return _record_label_view(
        report.get("protocol") or {}, shown, as_of_utc=report["as_of_utc"], sha=report["output_sha256"], log=log,
        actor=actor, code_version=code_version, experiments_root=experiments_root, now=now,
        dataset_id="sports_evidence:nfl_paired_report", dataset_version=JOIN_VERSION,
        tool="python -m edge_lab.sports_evidence report --with-results",
        note=f"paired-evidence report as of {report['as_of_utc']}; outcome states and results shown")


def record_markout_view(measurement: Mapping[str, Any], *, log: Path, actor: str, code_version: str,
                        experiments_root: Path | None = None, now: datetime | None = None) -> str:
    """Log an `exp002 --with-results` run before anything is printed: its markout reads the first T-60m book of
    each market (a label). Same checks as `record_results_view`."""
    games = (measurement.get("markout") or {}).get("games") or []
    shown = sorted(g["commence_utc"] for g in games if g.get("commence_utc"))
    return _record_label_view(
        measurement.get("protocol") or {}, shown, as_of_utc=measurement["as_of_utc"], sha=measurement["output_sha256"],
        log=log, actor=actor, code_version=code_version, experiments_root=experiments_root, now=now,
        dataset_id="sports_evidence:exp002_markout", dataset_version=f"{MEASUREMENT_VERSION}/{JOIN_VERSION}",
        tool="python -m edge_lab.sports_evidence exp002 --with-results",
        note=f"EXP-002 measurement as of {measurement['as_of_utc']}; cross-book markout (first T-60m books) and "
             "placebo shown; development data", role=rev.DatasetRole.DEVELOPMENT)


def _record_label_view(protocol: Mapping[str, Any], shown: Sequence[str], *, as_of_utc: str, sha: str, log: Path,
                       actor: str, code_version: str, experiments_root: Path | None, now: datetime | None,
                       dataset_id: str, dataset_version: str, tool: str, note: str,
                       role: "rev.DatasetRole" = rev.DatasetRole.UNASSIGNED) -> str:
    experiment_id = protocol.get("experiment_id")
    if not experiment_id:
        raise rev.EvidenceError("no Family A protocol is registered, so there is no evidence log to record in")
    start, end = (shown[0], shown[-1]) if shown else (as_of_utc, as_of_utc)
    exp = None
    for path in registry.discover(experiments_root or REPO_EXPERIMENTS):
        candidate = registry.load(path)
        if candidate.id == experiment_id:
            exp = candidate
    if exp is None:
        raise rev.EvidenceError(f"{experiment_id} is not in the experiment registry, so its evidence log is unknown")
    own = (exp.path.parent / rev.LOG_NAME).resolve()
    if Path(log).resolve() != own:
        raise rev.EvidenceError(f"the view must be recorded in {experiment_id}'s own log ({own.parent.name}/"
                                f"{rev.LOG_NAME}), not in {Path(log).name}")
    use = rev.EvidenceUse(
        experiment_id=experiment_id, family=FAMILY_ID, dataset_id=dataset_id,
        dataset_version=dataset_version, dataset_sha256=sha, role=role,
        window=rev.InformationWindow(OUTCOME_SCOPE, start, end), actor=actor, tool=tool,
        action_time_utc=_iso(now or _clock()), action=rev.Action.LABEL_RESULT_INSPECTION,
        code_version=code_version, model_version=None, prompt_version=None, viewed_features=True,
        viewed_labels=True, viewed_results=True, influenced_tuning=None, note=note)
    return rev.record_use(own, use, prohibited_prefixes=registry.prohibited_inputs(exp),
                          prohibited_label_scopes=registry.prohibited_label_scopes(exp))


def main(argv: list[str] | None = None) -> int:
    """`python -m edge_lab.sports_evidence report --db PATH`: read-only, network-free, bounded. Outcome labels
    are hidden unless `--with-results`, which first records the view in an explicit evidence-use log."""
    from .storage import ReadOnlyStoreError, SnapshotStore

    parser = argparse.ArgumentParser(prog="python -m edge_lab.sports_evidence",
                                     description=f"{LABEL}. Family A paired evidence from stored data only.")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="the paired-evidence report (JSON); opens the store read-only")
    rep.add_argument("--db", default="data/edge_lab.sqlite3")
    rep.add_argument("--as-of", help="point in time (ISO-8601 with zone); default and maximum: now")
    rep.add_argument("--out", help="write the JSON artifact here (atomically) instead of stdout")
    rep.add_argument("--summary", action="store_true", help="print denominators, attrition and gaps only")
    rep.add_argument("--with-results", action="store_true",
                     help="show outcome states and results (EXP-002 labels); requires --evidence-log, --actor and "
                          "a code version, and records the view there before anything is printed")
    rep.add_argument("--evidence-log", help="the experiment's evidence_use.jsonl to record a --with-results view in")
    rep.add_argument("--actor", help="who views the results (recorded in the evidence-use event)")
    rep.add_argument("--code-version", default=os.getenv("EDGE_LAB_CODE_VERSION"),
                     help="git commit of the code that runs (default: $EDGE_LAB_CODE_VERSION)")
    rep.add_argument("--experiments", help="experiment registry root (default: the repository's experiments/)")
    ms = sub.add_parser("exp002", help="EXP-002 measurement: the label-free noise gate (always) and the cross-book "
                                       "markout (labels: only with --with-results, logged first)")
    ms.add_argument("--db", default="data/edge_lab.sqlite3")
    ms.add_argument("--as-of", help="point in time (ISO-8601 with zone); default and maximum: now")
    ms.add_argument("--min-effect", type=float,
                    help="a candidate delta_min (probability units, e.g. 0.005) for the gate verdict; UNKNOWN until "
                         "the protocol freezes it, so without it the verdict is given per candidate")
    ms.add_argument("--out", help="write the JSON artifact here (atomically) instead of stdout")
    ms.add_argument("--with-results", action="store_true",
                    help="also compute the markout (it reads the first T-60m book, an EXP-002 label); requires "
                         "--evidence-log, --actor and a code version, and records the view there before printing")
    ms.add_argument("--evidence-log", help="EXP-002's evidence_use.jsonl to record a --with-results view in")
    ms.add_argument("--actor", help="who views the results (recorded in the evidence-use event)")
    ms.add_argument("--code-version", default=os.getenv("EDGE_LAB_CODE_VERSION"),
                    help="git commit of the code that runs (default: $EDGE_LAB_CODE_VERSION)")
    ms.add_argument("--experiments", help="experiment registry root (default: the repository's experiments/)")
    args = parser.parse_args(argv)
    if args.command == "exp002":
        return _main_exp002(args, parser)
    if args.with_results and not (args.evidence_log and args.actor and args.code_version):
        print(json.dumps({"command": "sports_evidence report", "state": "REFUSED",
                          "detail": "--with-results shows EXP-002 outcome labels: give --evidence-log, --actor and "
                                    "--code-version (or $EDGE_LAB_CODE_VERSION) so the view is recorded first"}))
        return 2
    now = _clock()
    as_of = now
    if args.as_of:
        as_of = parse_utc(args.as_of)  # type: ignore[assignment]
        if as_of is None:
            parser.error("--as-of must be an ISO-8601 time with a zone")
        if as_of > now:
            print(f"--as-of {args.as_of} is in the future; clamped to now ({_iso(now)})", file=sys.stderr)
            as_of = now
    try:
        store = SnapshotStore.open_readonly(args.db)
    except ReadOnlyStoreError as exc:
        print(json.dumps({"command": "sports_evidence report", "state": "NO_STORE", "detail": str(exc)}))
        return 1
    root = Path(args.experiments) if args.experiments else None
    report = build_report(store, as_of=as_of, results=args.with_results, experiments_root=root)
    if args.with_results:
        try:
            logged = record_results_view(report, log=Path(args.evidence_log), actor=args.actor,
                                         code_version=args.code_version, experiments_root=root)
        except (rev.EvidenceError, OSError) as exc:
            print(json.dumps({"command": "sports_evidence report", "state": "REFUSED",
                              "detail": f"the results view could not be recorded, so nothing is shown: {exc}"}))
            return 2
        report = {**report, "evidence_use": logged}
    if args.summary:
        report = {k: report[k] for k in ("schema", "label", "as_of_utc", "window", "protocol", "outcome_labels",
                                          "bounds", "sampling", "attrition", "join", "gaps", "economics",
                                          "output_sha256", "evidence_use") if k in report}
    text = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False)
    if args.out:
        _write_atomic(Path(args.out), text + "\n")
        print(json.dumps({"command": "sports_evidence report", "state": "WRITTEN", "out": args.out,
                          "output_sha256": report["output_sha256"]}))
    else:
        sys.stdout.write(text + "\n")
    return 0


def _main_exp002(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from .storage import ReadOnlyStoreError, SnapshotStore

    name = "sports_evidence exp002"
    if args.with_results and not (args.evidence_log and args.actor and args.code_version):
        print(json.dumps({"command": name, "state": "REFUSED",
                          "detail": "--with-results reads EXP-002 labels (the first T-60m books): give --evidence-log, "
                                    "--actor and --code-version (or $EDGE_LAB_CODE_VERSION) so the view is recorded "
                                    "first"}))
        return 2
    now = _clock()
    as_of = now
    if args.as_of:
        as_of = parse_utc(args.as_of)  # type: ignore[assignment]
        if as_of is None:
            parser.error("--as-of must be an ISO-8601 time with a zone")
        if as_of > now:
            print(f"--as-of {args.as_of} is in the future; clamped to now ({_iso(now)})", file=sys.stderr)
            as_of = now
    try:
        store = SnapshotStore.open_readonly(args.db)
    except ReadOnlyStoreError as exc:
        print(json.dumps({"command": name, "state": "NO_STORE", "detail": str(exc)}))
        return 1
    root = Path(args.experiments) if args.experiments else None
    out = measure_exp002(store, as_of=as_of, results=args.with_results, min_effect=args.min_effect,
                         experiments_root=root)
    if args.with_results:
        try:
            logged = record_markout_view(out, log=Path(args.evidence_log), actor=args.actor,
                                         code_version=args.code_version, experiments_root=root)
        except (rev.EvidenceError, OSError) as exc:
            print(json.dumps({"command": name, "state": "REFUSED",
                              "detail": f"the results view could not be recorded, so nothing is shown: {exc}"}))
            return 2
        out = {**out, "evidence_use": logged}
    text = json.dumps(out, sort_keys=True, indent=2, ensure_ascii=False)
    if args.out:
        _write_atomic(Path(args.out), text + "\n")
        print(json.dumps({"command": name, "state": "WRITTEN", "out": args.out, "output_sha256": out["output_sha256"],
                          "gate_verdict": out["gate"]["verdict"], "gate_v3_verdict": out["gate_v3"]["verdict"],
                          "freeze_eligible": False}))
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
