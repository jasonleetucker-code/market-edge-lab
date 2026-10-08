"""Track B offline evaluation harness: calibration, executable entries, bankroll ladder, depth (#184, ADR 0047).

The canonical owner of the *diagnostic* questions a Track B candidate asks before any economic screen:
how well do market prices forecast outcomes by bucket, what would an entry really cost against a
captured book, how much can a small (illustrative $100) bankroll deploy, and how much liquidity and
no-trade-filter attrition is there. It composes the existing owners and re-implements none of them:

- depth walks and taker fees: `opportunity.walk_ladder` / `price_depth_fill`, `fee_schedules`
  (`verification_at`, `claim_adjusted_net`); maker fees: `fee_schedules.maker_fee`;
- cluster uncertainty: `research_economics.cluster_bootstrap_mean`; fill-mode honesty:
  `research_economics.EXECUTABLE_PERFORMANCE`; the illustrative-bankroll label: `research_economics.ILLUSTRATIVE`;
- attrition waterfalls and separate denominators: `research_evidence.attrition_report`;
- evidence governance: `experiments` (protocols) and `research_evidence` (evidence-use logs).

It is not an engine, registry, ledger, collector or trading path. Nothing here reads a store or the
network: callers pass typed rows built from fixtures or from data the owner has approved.

**Evidence classes.** Every output carries a `Stamp`: SYNTHETIC / FIXTURE / RETROSPECTIVE_EXPLORATORY /
PROSPECTIVE, the sha256 of its canonical inputs, the caller's code version and this module's version.
`edge_claim` is always NONE. A profitable SYNTHETIC or FIXTURE result is a code test: its label says so
in capitals. RETROSPECTIVE_EXPLORATORY and PROSPECTIVE outputs need an experiment id and an evidence-use
event id, and refuse rows whose outcome scope is a protected label scope (`TRACK_B_PROHIBITED_LABEL_SCOPES`).
The CLI additionally checks the experiment's protocol and evidence-use log (`protocol_guard_problems`).

**Rules.**
- Unknown stays unknown: an unknown outcome is excluded and counted, never 0; an unknown fee makes every
  net figure None; an unknown trade size makes the trade-weighted view None.
- Only a captured ask ladder is fillable. A mid or a last trade price (`ReferencePrice`) is context:
  `evaluate_entries` refuses it as a book, and it is never priced.
- Rows are not independent. Contracts of one event or game share a `cluster_id`; every band is a
  cluster bootstrap, and every report states clusters beside rows.
- Decimal arithmetic throughout (50 significant digits inside, results quantized to 1e-12).

Pure, deterministic, stdlib-only and network-free, except `main`, which reads local JSONL files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation, localcontext
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .fee_schedules import FeeScheduleStatus, claim_adjusted_net, verification_at
from .freshness import Freshness, parse_utc
from .opportunity import (
    SIDES, DepthFill, DepthLadder, DepthStatus, FeeSchedule, Market, _freshness, price_depth_fill, walk_ladder,
)
from .provenance import canonical_json, sha256_hex
from .research_economics import EXECUTABLE_PERFORMANCE, ILLUSTRATIVE, cluster_bootstrap_mean
from .research_evidence import AttritionReport, AttritionUnit, Exclusion, Level, Stage, attrition_report, scope_matches

HARNESS_VERSION = "research-diagnostics-v1"
_Q = Decimal("1e-12")
_PREC = 50
ONE = Decimal(1)
ZERO = Decimal(0)

# Scope review of #185 (2026-10-08): what any Track B candidate protocol must declare, using the exact
# strings of EXP-003's protocol and of `research_evidence` scopes (compared case-insensitively).
TRACK_B_PROHIBITED_INPUTS = ("exp001:", "shadow_ledger:", "nws_pfm:", "nws_cli:", "kalshi_settlement:")
TRACK_B_PROHIBITED_LABEL_SCOPES = ("kalshi:KXHIGHNY", "sports:nfl:moneyline", "kalshi:KXNFLGAME", "kalshi:KXNHLGAME")
TRACK_B_PROHIBITED_FIELDS = ("result", "expiration_value", "settlement_value", "settlement_value_dollars",
                             "settlement_ts")


# =========================================================================== evidence stamp


class EvidenceClass(str, Enum):
    SYNTHETIC = "SYNTHETIC"  # made-up numbers: a code test
    FIXTURE = "FIXTURE"  # committed example data: a code test
    RETROSPECTIVE_EXPLORATORY = "RETROSPECTIVE_EXPLORATORY"  # held data, outcomes already happened
    PROSPECTIVE = "PROSPECTIVE"  # a preregistered forward evaluation input


EVIDENCE_LABELS: dict[EvidenceClass, str] = {
    EvidenceClass.SYNTHETIC: "SYNTHETIC INPUT - CODE TEST ONLY - NOT DATA AND NOT AN EDGE. A profitable synthetic "
                             "result proves only that the arithmetic adds up.",
    EvidenceClass.FIXTURE: "FIXTURE INPUT - CODE TEST ONLY - NOT AN EDGE. Committed example data exercising the code "
                           "path; no research conclusion may rest on it.",
    EvidenceClass.RETROSPECTIVE_EXPLORATORY: "RETROSPECTIVE EXPLORATORY - NOT PROSPECTIVE AND NOT AN EDGE. The "
                                             "outcome window is consumed once viewed and can never support an "
                                             "untouched or prospective claim.",
    EvidenceClass.PROSPECTIVE: "PROSPECTIVE - preregistered evaluation input. One result is still not an edge; the "
                               "research ladder (docs/RESEARCH_PRINCIPLES.md) decides what it supports.",
}
_GOVERNED = (EvidenceClass.RETROSPECTIVE_EXPLORATORY, EvidenceClass.PROSPECTIVE)
_EXP_ID = re.compile(r"^EXP-\d{3}$")
_EVENT_ID = re.compile(r"^eu-[0-9a-f]{32}$")


@dataclass(frozen=True)
class Stamp:
    harness_version: str
    evidence_class: str
    label: str
    code_version: str
    input_sha256: str
    experiment_id: str | None
    evidence_use_event_id: str | None
    edge_claim: str = "NONE"  # no output of this harness is an edge claim, whatever the class


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, timedelta):
        return f"{value.total_seconds()}s"
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"cannot fingerprint {type(value).__name__}")


def input_sha256(payload: Any) -> str:
    """sha256 of the canonical JSON of the inputs (dataclasses, Decimals and enums included)."""
    return sha256_hex(canonical_json(_jsonable(payload)))


def make_stamp(evidence_class: EvidenceClass, *, code_version: str, inputs: Any, experiment_id: str | None = None,
               evidence_use_event_id: str | None = None) -> Stamp:
    """The stamp every output carries. RETROSPECTIVE_EXPLORATORY and PROSPECTIVE need a registered experiment id
    and an evidence-use event id (the use must be logged before the first look); the CLI checks both exist."""
    if not isinstance(evidence_class, EvidenceClass):
        raise ValueError("evidence_class must be an EvidenceClass")
    if not isinstance(code_version, str) or not code_version.strip():
        raise ValueError("code_version is required (the git commit of the code that ran)")
    if evidence_class in _GOVERNED:
        if not (isinstance(experiment_id, str) and _EXP_ID.match(experiment_id)):
            raise ValueError(f"{evidence_class.value} output needs a registered experiment id (EXP-NNN)")
        if not (isinstance(evidence_use_event_id, str) and _EVENT_ID.match(evidence_use_event_id)):
            raise ValueError(f"{evidence_class.value} output needs the evidence-use event id (eu-...) logged before "
                             "the first look")
    return Stamp(HARNESS_VERSION, evidence_class.value, EVIDENCE_LABELS[evidence_class], code_version,
                 input_sha256(inputs), experiment_id, evidence_use_event_id)


def _series(native_id: str | None) -> str:
    return (native_id or "").split("-", 1)[0].upper()


def _guard_labels(evidence_class: EvidenceClass, scope: str, venue: str, native_id: str | None) -> None:
    """Outcome-bearing rows in a protected label scope are refused outside SYNTHETIC/FIXTURE code tests. A Kalshi
    market is also checked by its series, whatever scope the caller declared."""
    if evidence_class not in _GOVERNED:
        return
    series_scope = f"kalshi:{_series(native_id)}" if venue == "kalshi" and native_id else None
    for protected in TRACK_B_PROHIBITED_LABEL_SCOPES:
        if scope_matches(scope, protected) or (series_scope and scope_matches(series_scope, protected)):
            raise ValueError(f"outcomes in {scope!r} ({native_id}) are in the protected label scope {protected!r}: "
                             "Track B may not view them")


def _plain(value: Any) -> Any:
    return _jsonable(value)


def _hashed(report: Any) -> str:
    body = _jsonable(report)
    body.pop("report_sha256", None)
    return sha256_hex(canonical_json(body))


def _q(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(_Q)


def _dec(value: Any, what: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise ValueError(f"{what} must be a Decimal (or int), not {type(value).__name__}")
    out = Decimal(value)
    if not out.is_finite():
        raise ValueError(f"{what} must be finite")
    return out


# =========================================================================== 1. calibration by bucket


@dataclass(frozen=True)
class PredictionRow:
    """One market-implied price read as a forecast of one side's payout. The price is never a fill.

    `outcome` is the realized payout of `side` per $1 contract (0, 1, or a documented partial such as a
    0.5 tie); None is UNKNOWN and the row is excluded from every statistic (counted, never coerced).
    `cluster_id` is the dependence unit (the event or game): contracts of one event are not independent."""

    row_id: str
    market_id: str
    cluster_id: str
    scope: str  # the outcome scope, e.g. "sports:nba:moneyline" (research_evidence scope strings)
    category: str
    side: str
    price: Decimal
    time_to_close_seconds: Decimal | None
    outcome: Decimal | None
    trade_size: Decimal | None  # contracts; None = UNKNOWN
    price_basis: str = "UNSPECIFIED"  # what the price is (TRADE_PRICE, ASK, ...): descriptive only

    def validate(self) -> None:
        for name in ("row_id", "market_id", "cluster_id", "scope", "category"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"row {self.row_id!r}: {name} is required")
        if self.side not in SIDES:
            raise ValueError(f"row {self.row_id}: side must be YES or NO")
        p = _dec(self.price, f"row {self.row_id} price")
        if not ZERO < p < ONE:
            raise ValueError(f"row {self.row_id}: price {p} must lie strictly inside (0, 1)")
        if self.outcome is not None and not ZERO <= _dec(self.outcome, "outcome") <= ONE:
            raise ValueError(f"row {self.row_id}: outcome {self.outcome} must lie in [0, 1]")
        if self.time_to_close_seconds is not None and _dec(self.time_to_close_seconds, "time to close") < 0:
            raise ValueError(f"row {self.row_id}: time to close is negative (after close)")
        if self.trade_size is not None and _dec(self.trade_size, "trade size") <= 0:
            raise ValueError(f"row {self.row_id}: trade size must be positive")


@dataclass(frozen=True)
class CalibrationCell:
    weight_total: Decimal
    mean_price: Decimal
    realized_frequency: Decimal
    deviation: Decimal  # realized frequency - mean price; negative = the side paid less often than priced
    brier: Decimal
    log_loss: Decimal


@dataclass(frozen=True)
class Band:
    """95% cluster bootstrap (research_economics.cluster_bootstrap_mean) of the per-cluster deviation."""

    mean: Decimal
    lower: Decimal
    upper: Decimal
    clusters: int


@dataclass(frozen=True)
class CalibrationBucket:
    price_bucket: str
    tte_bucket: str
    category: str
    side: str
    rows: int  # rows with a known outcome
    unknown_outcome_rows: int  # excluded from every statistic
    markets: int
    clusters: int  # the independent units; never the row count
    market_weighted: CalibrationCell | None  # each market weighs 1 (its rows share it equally)
    trade_weighted: CalibrationCell | None  # each row weighs its trade size
    trade_weighted_reason: str
    deviation_band: Band | None
    band_reason: str


@dataclass(frozen=True)
class FavoriteLongshotRow:
    side: str
    price_bucket: str
    rows: int
    markets: int
    clusters: int
    market_weighted: CalibrationCell | None
    deviation_band: Band | None


@dataclass(frozen=True)
class CalibrationReport:
    stamp: Stamp
    version: str
    price_edges: tuple[Decimal, ...]
    tte_edges_seconds: tuple[Decimal, ...]
    rows_total: int
    rows_known_outcome: int
    rows_unknown_outcome: int
    markets: int
    clusters: int
    buckets: tuple[CalibrationBucket, ...]
    favorite_longshot: tuple[FavoriteLongshotRow, ...]
    notes: tuple[str, ...]
    report_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


CALIBRATION_NOTES = (
    "A price is read here as a probability forecast. It is not a fill and not an executable price.",
    "Clusters (events, games), not rows, are the independent units: every band resamples whole clusters.",
    "Market-weighted and trade-weighted views are kept separate: trade weighting lets a few large trades dominate "
    "(the deviations reported in arXiv 2607.14430 were trade-size weighted).",
    "Rows with an unknown outcome are counted and excluded; they are never scored as 0.",
    "Favorite/longshot rows pool time-to-close buckets and categories within one side; a negative deviation at low "
    "prices means longshots paid less often than priced. A pattern needs bands that exclude 0, and is still not an "
    "after-cost edge (see evaluate_entries).",
)


def _check_edges(edges: Sequence[Decimal], what: str, *, unit_interval: bool) -> tuple[Decimal, ...]:
    out = tuple(_dec(e, f"{what} edge") for e in edges)
    if len(out) < 2 or any(b <= a for a, b in zip(out, out[1:])):
        raise ValueError(f"{what} edges must be at least two strictly increasing values")
    if out[0] < 0 or (unit_interval and out[-1] > 1):
        raise ValueError(f"{what} edges are out of range")
    return out


def _price_bucket(p: Decimal, edges: tuple[Decimal, ...]) -> str:
    if not edges[0] <= p <= edges[-1]:
        raise ValueError(f"price {p} lies outside the bucket edges {edges[0]}..{edges[-1]}")
    for i, (lo, hi) in enumerate(zip(edges, edges[1:])):
        last = i == len(edges) - 2
        if lo <= p < hi or (last and p == hi):
            return f"[{lo},{hi}]" if last else f"[{lo},{hi})"
    raise AssertionError("unreachable")


def _tte_bucket(t: Decimal | None, edges: tuple[Decimal, ...]) -> str:
    if t is None:
        return "UNKNOWN"
    if t < edges[0]:
        raise ValueError(f"time to close {t} lies below the first edge {edges[0]}")
    for lo, hi in zip(edges, edges[1:]):
        if lo <= t < hi:
            return f"[{lo},{hi})"
    return f"[{edges[-1]},inf)"


def _cell(points: Sequence[tuple[Decimal, Decimal, Decimal]]) -> CalibrationCell | None:
    """(price, outcome, weight) points -> weighted mean price, frequency, Brier and log loss."""
    if not points:
        return None
    with localcontext() as ctx:
        ctx.prec = _PREC
        total = sum((w for _, _, w in points), ZERO)
        if total <= 0:
            return None
        mean_p = sum((w * p for p, _, w in points), ZERO) / total
        freq = sum((w * o for _, o, w in points), ZERO) / total
        brier = sum((w * (p - o) ** 2 for p, o, w in points), ZERO) / total
        loss = ZERO
        for p, o, w in points:
            term = ZERO
            if o != 0:
                term += o * p.ln()
            if o != 1:
                term += (ONE - o) * (ONE - p).ln()
            loss -= w * term
        loss = loss / total
        return CalibrationCell(_q(total), _q(mean_p), _q(freq), _q(freq - mean_p), _q(brier), _q(loss))


def _market_points(rows: Sequence[PredictionRow]) -> list[tuple[Decimal, Decimal, Decimal]]:
    """Each market weighs 1 in total: its rows share 1/n each."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.market_id] = counts.get(r.market_id, 0) + 1
    with localcontext() as ctx:
        ctx.prec = _PREC
        return [(r.price, r.outcome, ONE / counts[r.market_id]) for r in rows]


def _band(rows: Sequence[PredictionRow]) -> tuple[Band | None, str]:
    by_cluster: dict[str, list[PredictionRow]] = {}
    for r in rows:
        by_cluster.setdefault(r.cluster_id, []).append(r)
    values = {c: _cell(_market_points(rs)).deviation for c, rs in by_cluster.items()}
    band = cluster_bootstrap_mean(values)
    if band is None:
        return None, f"{len(values)} cluster(s): no band is estimable with fewer than two independent clusters"
    return Band(band[0], band[1], band[2], len(values)), f"cluster bootstrap over {len(values)} clusters"


def calibration_report(rows: Iterable[PredictionRow], *, price_edges: Sequence[Decimal],
                       tte_edges_seconds: Sequence[Decimal], evidence_class: EvidenceClass, code_version: str,
                       experiment_id: str | None = None, evidence_use_event_id: str | None = None) -> CalibrationReport:
    """Calibration of market-implied prices by price bucket x time-to-close bucket x category x side."""
    rows = list(rows)
    p_edges = _check_edges(price_edges, "price", unit_interval=True)
    t_edges = _check_edges(tte_edges_seconds, "time-to-close", unit_interval=False)
    ids = [r.row_id for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("row ids must be unique")
    cluster_of: dict[str, str] = {}
    for r in rows:
        r.validate()
        venue, _, native = r.market_id.partition(":")
        _guard_labels(evidence_class, r.scope, venue, native or None)
        if cluster_of.setdefault(r.market_id, r.cluster_id) != r.cluster_id:
            raise ValueError(f"market {r.market_id} appears in two clusters: a market belongs to one event")
    stamp = make_stamp(evidence_class, code_version=code_version,
                       inputs={"rows": rows, "price_edges": p_edges, "tte_edges": t_edges},
                       experiment_id=experiment_id, evidence_use_event_id=evidence_use_event_id)
    groups: dict[tuple[str, str, str, str], list[PredictionRow]] = {}
    for r in rows:
        key = (_price_bucket(r.price, p_edges), _tte_bucket(r.time_to_close_seconds, t_edges), r.category, r.side)
        groups.setdefault(key, []).append(r)
    buckets = []
    for key in sorted(groups):
        members = groups[key]
        known = [r for r in members if r.outcome is not None]
        unknown_sizes = sum(1 for r in known if r.trade_size is None)
        if not known:
            trade, trade_reason = None, "no row with a known outcome"
        elif unknown_sizes:
            trade, trade_reason = None, f"TRADE_SIZE_UNKNOWN: {unknown_sizes} row(s) have no trade size"
        else:
            trade, trade_reason = _cell([(r.price, r.outcome, r.trade_size) for r in known]), "weighted by trade size"
        band, band_reason = _band(known) if known else (None, "no row with a known outcome")
        buckets.append(CalibrationBucket(
            key[0], key[1], key[2], key[3], len(known), len(members) - len(known),
            len({r.market_id for r in known}), len({r.cluster_id for r in known}),
            _cell(_market_points(known)), trade, trade_reason, band, band_reason))
    fl_groups: dict[tuple[str, str], list[PredictionRow]] = {}
    for r in rows:
        if r.outcome is not None:
            fl_groups.setdefault((r.side, _price_bucket(r.price, p_edges)), []).append(r)
    favorite_longshot = tuple(
        FavoriteLongshotRow(side, bucket, len(rs), len({r.market_id for r in rs}), len({r.cluster_id for r in rs}),
                            _cell(_market_points(rs)), _band(rs)[0])
        for (side, bucket), rs in sorted(fl_groups.items(), key=lambda kv: (kv[0][0], _edge_key(kv[0][1]))))
    known_all = [r for r in rows if r.outcome is not None]
    report = CalibrationReport(
        stamp, HARNESS_VERSION, p_edges, t_edges, len(rows), len(known_all), len(rows) - len(known_all),
        len({r.market_id for r in rows}), len({r.cluster_id for r in rows}), tuple(buckets), favorite_longshot,
        CALIBRATION_NOTES)
    return _with_hash(report)


def _edge_key(label: str) -> Decimal:
    return Decimal(label[1:].split(",", 1)[0])


def _with_hash(report: Any) -> Any:
    return replace(report, report_sha256=_hashed(report))


# =========================================================================== 2. executable-price evaluation


class FillStatus(str, Enum):
    FULL = "FULL"  # the captured ladder covers the requested quantity
    PARTIAL = "PARTIAL"  # a complete capture offers less: only the captured part is priced
    PARTIAL_DEPTH_UNKNOWN = "PARTIAL_DEPTH_UNKNOWN"  # a truncated capture offers less; more may exist (unknown)
    MISSED = "MISSED"  # nothing fillable
    INVALID_BOOK = "INVALID_BOOK"  # anomaly, malformed or off-grid ladder, or the wrong market/side
    STALE_BOOK = "STALE_BOOK"  # older than the declared maximum age, or of unknown age: never priced
    LOOKAHEAD = "LOOKAHEAD"  # received after the decision time: never priced


class ReferenceKind(str, Enum):
    MID = "MID"
    LAST_TRADE = "LAST_TRADE"


@dataclass(frozen=True)
class ReferencePrice:
    """A midpoint or a last trade price: context beside an entry, never a price anyone could fill at."""

    kind: ReferenceKind
    value: Decimal

    @property
    def fillable(self) -> bool:
        return False


@dataclass(frozen=True)
class EntryRequest:
    """Buy `quantity` of `side` of `market` against the captured ask ladder `book`, at `as_of_utc`.

    `settlement_payout` is the realized payout per contract of `side` (RETROSPECTIVE only; None = UNKNOWN).
    Selling YES on a bid-only binary book is buying NO against the NO ask ladder (kalshi_quotes)."""

    entry_id: str
    cluster_id: str
    scope: str
    market: Market
    side: str
    quantity: Decimal
    book: DepthLadder
    fee_schedule: FeeSchedule
    as_of_utc: str
    settlement_payout: Decimal | None = None
    reference: ReferencePrice | None = None


@dataclass(frozen=True)
class EntryEvaluation:
    entry_id: str
    cluster_id: str
    venue: str
    market_id: str
    side: str
    requested: Decimal
    filled: Decimal
    unfilled: Decimal
    status: str
    takes: tuple[tuple[Decimal, Decimal], ...]  # (price, size) actually walked, cheapest first
    top_of_book_ask: Decimal | None
    gross_cost: Decimal | None
    average_price: Decimal | None
    limit_price: Decimal | None
    fee: Decimal | None  # None: the fee is UNKNOWN (unsupported scope or not priceable)
    total_cost: Decimal | None
    all_in_per_contract: Decimal | None
    fee_schedule_id: str
    fee_status: str
    claim_basis: str
    claimable: bool
    settlement_payout: Decimal | None
    gross_pnl: Decimal | None  # GROSS_DIAGNOSTIC: before fees
    net_pnl: Decimal | None  # None when the fee or the payout is unknown
    claim_adjusted_net: Decimal | None  # fee claim basis applied (ADR 0017); None: no claim possible
    reference_kind: str | None
    reference_value: Decimal | None
    reference_fillable: bool  # always False
    reasons: tuple[str, ...]
    priced_from: str = "CAPTURED_ASK_LADDER"
    executable_performance: str = EXECUTABLE_PERFORMANCE


@dataclass(frozen=True)
class EntrySummary:
    entries: int
    status_counts: dict[str, int]
    filled_entries: int
    contracts_filled: Decimal
    known_net_entries: int
    unknown_net_entries: int  # filled entries whose fee or payout is unknown
    wins: int  # filled entries with a known net P&L > 0
    win_rate: Decimal | None  # wins / known-net entries
    average_all_in_per_contract: Decimal | None  # the break-even payout rate for $1 contracts
    total_gross_pnl: Decimal | None
    total_net_pnl: Decimal | None  # None when any filled entry's net is unknown
    net_per_contract: Decimal | None
    clusters: int
    net_band: Band | None  # cluster bootstrap of per-cluster net P&L
    sign_after_costs: str  # NEGATIVE / NON_NEGATIVE_POINT_ESTIMATE_NOT_AN_EDGE / UNKNOWN
    reading: str


@dataclass(frozen=True)
class EntryReport:
    stamp: Stamp
    version: str
    max_book_age_seconds: Decimal
    evaluations: tuple[EntryEvaluation, ...]
    summary: EntrySummary
    report_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


def _step(quantity: Decimal) -> Decimal:
    return ONE if quantity == quantity.to_integral_value() else Decimal("0.01")


def _walk_for_entry(book: DepthLadder, market: Market, side: str,
                    qty: Decimal) -> tuple[FillStatus, DepthFill | None, list[str]]:
    if (book.venue, book.market_id, book.side) != (market.venue, market.market_id, side):
        return FillStatus.INVALID_BOOK, None, [f"book is for {book.venue}/{book.market_id}/{book.side}, not "
                                               f"{market.venue}/{market.market_id}/{side}"]
    fill = walk_ladder(book, qty, price_grid=market.price_grid)
    if fill.status is DepthStatus.FILLABLE:
        return FillStatus.FULL, fill, []
    if fill.status is DepthStatus.INVALID_BOOK:
        return FillStatus.INVALID_BOOK, None, [fill.detail]
    step = _step(qty)
    partial = (fill.available / step).to_integral_value(rounding=ROUND_DOWN) * step if fill.available else ZERO
    if partial <= 0:
        return FillStatus.MISSED, None, [f"{fill.status.value}: {fill.detail}"]
    status = FillStatus.PARTIAL_DEPTH_UNKNOWN if fill.status is DepthStatus.DEPTH_UNKNOWN else FillStatus.PARTIAL
    return status, walk_ladder(book, partial, price_grid=market.price_grid), [f"{fill.status.value}: {fill.detail}"]


def _evaluate_entry(req: EntryRequest, max_book_age: timedelta) -> EntryEvaluation:
    if isinstance(req.book, ReferencePrice) or not isinstance(req.book, DepthLadder):
        raise TypeError("only a captured ask ladder (DepthLadder) is fillable; a mid or a last trade price never is")
    if req.side not in SIDES:
        raise ValueError(f"entry {req.entry_id}: side must be YES or NO")
    qty = _dec(req.quantity, f"entry {req.entry_id} quantity")
    if qty <= 0:
        raise ValueError(f"entry {req.entry_id}: quantity must be positive")
    if req.settlement_payout is not None and not ZERO <= _dec(req.settlement_payout, "payout") <= ONE:
        raise ValueError(f"entry {req.entry_id}: settlement payout must lie in [0, 1]")
    at = parse_utc(req.as_of_utc)
    if at is None:
        raise ValueError(f"entry {req.entry_id}: as_of_utc must be timezone-aware")
    reasons: list[str] = []
    received = parse_utc(req.book.received_at_utc)
    fresh, why = _freshness(req.book.received_at_utc, max_age=max_book_age, as_of=at)
    fill: DepthFill | None = None
    if received is not None and received > at:
        status = FillStatus.LOOKAHEAD
        reasons.append(f"LOOKAHEAD: {why}")
    elif fresh is not Freshness.FRESH:
        status = FillStatus.STALE_BOOK
        reasons.append(f"STALE_BOOK: {fresh.value}: {why}")
    else:
        status, fill, notes = _walk_for_entry(req.book, req.market, req.side, qty)
        reasons += notes
    state = verification_at(req.fee_schedule, at, req.market.native_id)
    fee = total = None
    if fill is not None:
        if state.status is FeeScheduleStatus.UNSUPPORTED:
            reasons.append(f"FEE_UNSUPPORTED: {req.fee_schedule.schedule_id}: net is UNKNOWN, never fee-free")
        else:
            cost, why_cost = price_depth_fill(fill, req.fee_schedule)
            if cost is None:
                reasons.append(f"FEE_NOT_PRICED: {why_cost}: net is UNKNOWN")
            else:
                fee, total = cost.fee, cost.total_cost
    filled = fill.quantity if fill is not None else ZERO
    payout = req.settlement_payout
    gross_pnl = None if fill is None or payout is None else filled * payout - fill.gross_cost
    net = None if total is None or payout is None else filled * payout - total
    if fill is not None and payout is None:
        reasons.append("OUTCOME_UNKNOWN: no settlement payout; P&L is UNKNOWN")
    adjusted = None if net is None else claim_adjusted_net(net, filled, state)
    if fill is not None and not state.claimable:
        reasons.append(f"FEE_NOT_CLAIMABLE: claim basis {state.claim_basis.value} ({state.status.value})")
    ref = req.reference
    return EntryEvaluation(
        req.entry_id, req.cluster_id, req.market.venue, req.market.market_id, req.side, qty, filled, qty - filled,
        status.value, tuple((t.price, t.size) for t in fill.takes) if fill is not None else (),
        req.book.asks[0].price if req.book.asks else None,
        None if fill is None else fill.gross_cost, None if fill is None else fill.average_price,
        None if fill is None else fill.limit_price, fee, total,
        None if total is None or not filled else _q(total / filled),
        req.fee_schedule.schedule_id, state.status.value, state.claim_basis.value, state.claimable,
        payout, gross_pnl, net, adjusted,
        None if ref is None else ref.kind.value, None if ref is None else ref.value, False, tuple(reasons))


def _summary(evals: Sequence[EntryEvaluation]) -> EntrySummary:
    counts: dict[str, int] = {}
    for e in evals:
        counts[e.status] = counts.get(e.status, 0) + 1
    filled = [e for e in evals if e.filled > 0]
    known = [e for e in filled if e.net_pnl is not None]
    wins = sum(1 for e in known if e.net_pnl > 0)
    contracts = sum((e.filled for e in filled), ZERO)
    priced = [e for e in filled if e.total_cost is not None]
    with localcontext() as ctx:
        ctx.prec = _PREC
        avg_cost = (_q(sum((e.total_cost for e in priced), ZERO) / sum((e.filled for e in priced), ZERO))
                    if priced and len(priced) == len(filled) else None)
        win_rate = _q(Decimal(wins) / len(known)) if known else None
        all_known = bool(filled) and len(known) == len(filled)
        total_net = sum((e.net_pnl for e in known), ZERO) if all_known else None
        gross_known = all(e.gross_pnl is not None for e in filled) and bool(filled)
        total_gross = sum((e.gross_pnl for e in filled), ZERO) if gross_known else None
        per_contract = _q(total_net / contracts) if total_net is not None and contracts else None
    clusters: dict[str, Decimal] = {}
    for e in filled:
        if e.net_pnl is not None:
            clusters[e.cluster_id] = clusters.get(e.cluster_id, ZERO) + e.net_pnl
    band = cluster_bootstrap_mean(clusters) if all_known else None
    if total_net is None:
        sign, reading = "UNKNOWN", "a filled entry's fee or payout is unknown, so the total is UNKNOWN"
    elif total_net < 0:
        sign = "NEGATIVE"
        reading = (f"net {total_net} after costs although {wins} of {len(known)} entries won: a win rate is not a "
                   f"return; the break-even payout rate is the average all-in cost {avg_cost} per $1 contract")
    else:
        sign = "NON_NEGATIVE_POINT_ESTIMATE_NOT_AN_EDGE"
        reading = "a non-negative point estimate; see the cluster band and the stamp: this is not an edge"
    return EntrySummary(len(evals), dict(sorted(counts.items())), len(filled), contracts, len(known),
                        len(filled) - len(known), wins, win_rate, avg_cost, total_gross, total_net, per_contract,
                        len({e.cluster_id for e in filled}),
                        None if band is None else Band(band[0], band[1], band[2], len(clusters)), sign, reading)


def evaluate_entries(requests: Iterable[EntryRequest], *, max_book_age: timedelta, evidence_class: EvidenceClass,
                     code_version: str, experiment_id: str | None = None,
                     evidence_use_event_id: str | None = None) -> EntryReport:
    """Each entry priced against its point-in-time captured ladder, with partial and missed fills, fees through
    the fee owner (unknown fee -> net UNKNOWN), the payout at settlement, and a summary that sets the win rate
    beside the break-even rate. Zero-latency replay of captured books: never executable performance."""
    if not isinstance(max_book_age, timedelta) or max_book_age < timedelta(0):
        raise ValueError("max_book_age must be a non-negative timedelta")
    requests = list(requests)
    ids = [r.entry_id for r in requests]
    if len(ids) != len(set(ids)):
        raise ValueError("entry ids must be unique")
    for r in requests:
        if r.settlement_payout is not None:
            _guard_labels(evidence_class, r.scope, r.market.venue, r.market.native_id)
    evals = tuple(_evaluate_entry(r, max_book_age) for r in requests)
    stamp = make_stamp(evidence_class, code_version=code_version,
                       inputs={"requests": [_entry_inputs(r) for r in requests], "max_book_age": max_book_age},
                       experiment_id=experiment_id, evidence_use_event_id=evidence_use_event_id)
    report = EntryReport(stamp, HARNESS_VERSION, Decimal(str(max_book_age.total_seconds())), evals, _summary(evals))
    return _with_hash(report)


def _entry_inputs(r: EntryRequest) -> dict[str, Any]:
    return {"entry_id": r.entry_id, "cluster_id": r.cluster_id, "scope": r.scope, "market": r.market, "side": r.side,
            "quantity": r.quantity, "book": r.book, "fee_schedule_id": r.fee_schedule.schedule_id,
            "as_of_utc": r.as_of_utc, "settlement_payout": r.settlement_payout, "reference": r.reference}


# =========================================================================== 3. $100 bankroll ladder


@dataclass(frozen=True)
class BankrollRung:
    bankroll: Decimal  # ILLUSTRATIVE: never an approved bankroll
    quantity: Decimal | None  # the most whole contracts whose all-in cost fits; None when the fee is unknown
    quantity_upper_bound_gross: Decimal | None  # fee unknown: the gross-only bound (the true figure is <= it)
    limited_by: str  # BANKROLL / DEPTH / DEPTH_UNKNOWN / NOTHING_FILLABLE
    total_cost: Decimal | None
    gross_cost: Decimal | None
    fee: Decimal | None
    average_price: Decimal | None
    idle_cash: Decimal | None
    lockup_days_expected: Decimal | None
    lockup_days_latest: Decimal | None
    capital_days_expected: Decimal | None  # total cost x lock-up days
    capital_days_latest: Decimal | None
    turnover_per_year_scenario: Decimal | None  # 365 / latest lock-up days: SCENARIO, never a forecast
    net_pnl: Decimal | None  # with a known settlement payout and a known fee
    net_per_capital_day: Decimal | None


@dataclass(frozen=True)
class BankrollLadder:
    stamp: Stamp
    version: str
    status: str  # ILLUSTRATIVE_SCENARIO_NOT_APPROVED_BANKROLL
    market_id: str
    side: str
    as_of_utc: str
    book_state: str  # FRESH, or why no rung was computed
    release_expected_utc: str | None
    release_latest_utc: str | None
    fee_schedule_id: str
    fee_status: str
    rungs: tuple[BankrollRung, ...]
    notes: tuple[str, ...]
    report_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


def _release(at: str | None, timer: int | None) -> datetime | None:
    t = parse_utc(at)
    if t is None:
        return None
    return t + timedelta(seconds=timer or 0) if timer is not None else None


def bankroll_ladder(market: Market, side: str, book: DepthLadder, fee_schedule: FeeSchedule, *, as_of_utc: str,
                    max_book_age: timedelta, bankrolls: Sequence[Decimal] = (Decimal(100),),
                    settlement_payout: Decimal | None = None, evidence_class: EvidenceClass, code_version: str,
                    experiment_id: str | None = None, evidence_use_event_id: str | None = None) -> BankrollLadder:
    """What a hypothetical bankroll can deploy into one captured ladder: whole contracts whose all-in cost fits,
    the cash left idle, and the capital lock-up until the cash comes back (expected and latest settlement)."""
    at = parse_utc(as_of_utc)
    if at is None:
        raise ValueError("as_of_utc must be timezone-aware")
    if not isinstance(book, DepthLadder):
        raise TypeError("only a captured ask ladder (DepthLadder) is fillable; a mid or a last trade price never is")
    budgets = tuple(_dec(b, "bankroll") for b in bankrolls)
    if not budgets or any(b <= 0 for b in budgets):
        raise ValueError("bankrolls must be positive")
    stamp = make_stamp(evidence_class, code_version=code_version,
                       inputs={"market": market, "side": side, "book": book, "fee": fee_schedule.schedule_id,
                               "as_of": as_of_utc, "max_book_age": max_book_age, "bankrolls": budgets,
                               "payout": settlement_payout},
                       experiment_id=experiment_id, evidence_use_event_id=evidence_use_event_id)
    timing = market.timing
    timer = None if timing is None else timing.settlement_timer_seconds
    rel_exp = None if timing is None else _release(timing.expected_resolution_utc, timer)
    rel_late = None if timing is None else _release(timing.latest_resolution_utc, timer)
    state = verification_at(fee_schedule, at, market.native_id)
    notes = [f"{ILLUSTRATIVE}: the bankrolls are illustrative scenarios, never approved amounts",
             "observed depth is a ceiling, not a guaranteed fill; zero-latency replay of one captured book",
             "turnover is a SCENARIO: as if equally good opportunities recurred back to back"]
    received = parse_utc(book.received_at_utc)
    fresh, why = _freshness(book.received_at_utc, max_age=max_book_age, as_of=at)
    book_state = "FRESH"
    if received is not None and received > at:
        book_state = f"LOOKAHEAD: {why}"
    elif fresh is not Freshness.FRESH:
        book_state = f"STALE_BOOK: {fresh.value}: {why}"
    elif (book.venue, book.market_id, book.side) != (market.venue, market.market_id, side):
        book_state = "INVALID_BOOK: the ladder is for another market or side"
    elif walk_ladder(book, ONE, price_grid=market.price_grid).status is DepthStatus.INVALID_BOOK:
        book_state = "INVALID_BOOK: " + walk_ladder(book, ONE, price_grid=market.price_grid).detail
    rungs: list[BankrollRung] = []
    if book_state == "FRESH":
        available = sum((lv.size for lv in book.asks), ZERO).to_integral_value(rounding=ROUND_DOWN)
        days_exp = None if rel_exp is None else Decimal(str((rel_exp - at).total_seconds())) / Decimal(86400)
        days_late = None if rel_late is None else Decimal(str((rel_late - at).total_seconds())) / Decimal(86400)
        for budget in budgets:
            rungs.append(_rung(market, book, fee_schedule, state.status, budget, available, days_exp, days_late,
                               settlement_payout))
    ladder = BankrollLadder(stamp, HARNESS_VERSION, ILLUSTRATIVE, market.market_id, side, at.isoformat(), book_state,
                            None if rel_exp is None else rel_exp.isoformat(),
                            None if rel_late is None else rel_late.isoformat(), fee_schedule.schedule_id,
                            state.status.value, tuple(rungs), tuple(notes))
    return _with_hash(ladder)


def _cost_at(book: DepthLadder, market: Market, schedule: FeeSchedule, q: Decimal, *, gross_only: bool):
    fill = walk_ladder(book, q, price_grid=market.price_grid)
    if fill.status is not DepthStatus.FILLABLE:
        return None, fill
    if gross_only:
        return fill.gross_cost, fill
    cost, _ = price_depth_fill(fill, schedule)
    return (None if cost is None else cost), fill


def _max_quantity(book, market, schedule, budget: Decimal, available: Decimal, *, gross_only: bool) -> Decimal:
    """The largest whole q in [0, available] whose cost fits the budget (cost is increasing in q)."""
    lo, hi = ZERO, available
    while lo < hi:
        mid = (lo + hi + 1) // 2
        cost, _ = _cost_at(book, market, schedule, mid, gross_only=gross_only)
        value = cost if gross_only else (None if cost is None else cost.total_cost)
        if value is not None and value <= budget:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _rung(market, book, schedule, fee_status: FeeScheduleStatus, budget: Decimal, available: Decimal,
          days_exp: Decimal | None, days_late: Decimal | None, payout: Decimal | None) -> BankrollRung:
    fee_known = fee_status is not FeeScheduleStatus.UNSUPPORTED and (
        available == 0 or _cost_at(book, market, schedule, ONE, gross_only=False)[0] is not None)
    if available == 0:
        return BankrollRung(budget, ZERO, None, "NOTHING_FILLABLE", None, None, None, None, budget, days_exp,
                            days_late, None, None, None, None, None)
    gross_q = _max_quantity(book, market, schedule, budget, available, gross_only=True)
    q = _max_quantity(book, market, schedule, budget, available, gross_only=False) if fee_known else None
    shown = q if q is not None else gross_q
    limit = "BANKROLL"
    if shown == available:
        limit = "DEPTH_UNKNOWN" if book.truncated else "DEPTH"
    if shown == 0:
        return BankrollRung(budget, q, None if fee_known else gross_q, "BANKROLL" if available else "NOTHING_FILLABLE",
                            None, None, None, None, budget, days_exp, days_late, None, None, None, None, None)
    if q is None:
        gross, fill = _cost_at(book, market, schedule, gross_q, gross_only=True)
        return BankrollRung(budget, None, gross_q, limit, None, gross, None, fill.average_price, None, days_exp,
                            days_late, None, None, None, None, None)
    cost, fill = _cost_at(book, market, schedule, q, gross_only=False)
    total = cost.total_cost
    cap_exp = None if days_exp is None else _q(total * days_exp)
    cap_late = None if days_late is None else _q(total * days_late)
    turnover = None if days_late is None or days_late <= 0 else _q(Decimal(365) / days_late)
    net = None if payout is None else q * payout - total
    per_day = None if net is None or not cap_late else _q(net / cap_late)
    return BankrollRung(budget, q, gross_q, limit, total, fill.gross_cost, cost.fee, fill.average_price,
                        budget - total, None if days_exp is None else _q(days_exp),
                        None if days_late is None else _q(days_late), cap_exp, cap_late, turnover, net, per_day)


# =========================================================================== 4. depth / spread and no-trade attrition


@dataclass(frozen=True)
class BookSnapshot:
    """One point-in-time capture of one binary market: its YES and NO ask ladders (None = not captured).
    On a bid-only binary book the YES bid is 1 - the best NO ask, so the spread needs both ladders."""

    snapshot_id: str
    market: Market
    cluster_id: str
    group: str  # how the aggregate is cut, e.g. "nba|T-60m"
    yes_asks: DepthLadder | None
    no_asks: DepthLadder | None
    fee_schedule: FeeSchedule


@dataclass(frozen=True)
class NoTradeFilters:
    """Declared before any look; a change is a new filter set, never a tuned one."""

    filter_id: str
    max_book_age: timedelta
    probe_quantity: Decimal  # the size a candidate would need
    max_spread: Decimal | None  # None: no spread filter
    require_fee_model: bool = True


class FilterReason(str, Enum):
    """Precedence = declaration order (earliest stage first)."""

    BOOK_MISSING = "BOOK_MISSING"
    INVALID_BOOK = "INVALID_BOOK"
    STALE_BOOK = "STALE_BOOK"
    FEE_UNSUPPORTED = "FEE_UNSUPPORTED"
    SPREAD_UNKNOWN = "SPREAD_UNKNOWN"
    WIDE_SPREAD = "WIDE_SPREAD"
    DEPTH_UNKNOWN = "DEPTH_UNKNOWN"
    INSUFFICIENT_DEPTH = "INSUFFICIENT_DEPTH"


# research_evidence.Exclusion has no FEE_UNSUPPORTED / spread reasons, and changing that shared contract would
# change every existing waterfall. The detailed census below is primary; the coarse waterfall uses this map.
EXCLUSION_MAP: dict[FilterReason, Exclusion] = {
    FilterReason.BOOK_MISSING: Exclusion.MISSING_SOURCE,
    FilterReason.INVALID_BOOK: Exclusion.PARTIAL_EVIDENCE,
    FilterReason.STALE_BOOK: Exclusion.STALE,
    FilterReason.FEE_UNSUPPORTED: Exclusion.UNSUPPORTED_PAYOFF,
    FilterReason.SPREAD_UNKNOWN: Exclusion.PARTIAL_EVIDENCE,
    FilterReason.WIDE_SPREAD: Exclusion.NO_SIGNAL,
    FilterReason.DEPTH_UNKNOWN: Exclusion.DEPTH_UNKNOWN,
    FilterReason.INSUFFICIENT_DEPTH: Exclusion.INSUFFICIENT_DEPTH,
}
_FILTER_ORDER = {r: i for i, r in enumerate(FilterReason)}


@dataclass(frozen=True)
class SnapshotMetrics:
    snapshot_id: str
    market_id: str
    cluster_id: str
    group: str
    freshness: str
    yes_ask: Decimal | None
    no_ask: Decimal | None
    yes_bid: Decimal | None  # 1 - best NO ask
    spread: Decimal | None  # yes ask + no ask - 1: the cost of a round trip per contract, before fees
    top_depth: Decimal | None  # contracts at the best YES ask
    captured_depth: Decimal | None  # every captured YES ask contract (a lower bound when truncated)
    captured_depth_truncated: bool | None
    probe_status: str | None  # DepthStatus at the probe quantity (YES side)
    probe_all_in_per_contract: Decimal | None  # fees included; None when not fillable or the fee is unknown
    reasons: tuple[str, ...]  # FilterReason values; empty = passes every filter


@dataclass(frozen=True)
class Distribution:
    count: int
    minimum: Decimal | None
    p10: Decimal | None
    median: Decimal | None
    p90: Decimal | None
    maximum: Decimal | None
    mean: Decimal | None


@dataclass(frozen=True)
class GroupDepth:
    group: str
    snapshots: int  # fresh, valid YES books only
    markets: int
    clusters: int
    spread: Distribution
    spread_unknown: int  # one-sided books: unknown, never 0
    top_depth: Distribution
    truncated_share: Decimal | None
    probe_fillable_share: Decimal | None
    probe_all_in: Distribution


@dataclass(frozen=True)
class DepthReport:
    stamp: Stamp
    version: str
    as_of_utc: str
    filters: NoTradeFilters
    snapshots: tuple[SnapshotMetrics, ...]
    groups: tuple[GroupDepth, ...]
    filter_census_raw: dict[str, int]  # every reason, so it may sum past the snapshot count
    filter_census_primary: dict[str, int]  # one per excluded snapshot (FilterReason order)
    exclusion_map: dict[str, str]
    attrition: AttritionReport  # SNAPSHOT, MARKET and EVENT (cluster) denominators, never pooled
    notes: tuple[str, ...]
    report_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


def _nearest_rank(values: Sequence[Decimal], pct: int) -> Decimal:
    k = max(1, -(-pct * len(values) // 100))  # ceil(pct/100 x n), at least 1
    return values[k - 1]


def _distribution(values: Sequence[Decimal]) -> Distribution:
    vals = sorted(values)
    if not vals:
        return Distribution(0, None, None, None, None, None, None)
    with localcontext() as ctx:
        ctx.prec = _PREC
        mean = _q(sum(vals, ZERO) / len(vals))
    return Distribution(len(vals), vals[0], _nearest_rank(vals, 10), _nearest_rank(vals, 50), _nearest_rank(vals, 90),
                        vals[-1], mean)


def _snapshot(s: BookSnapshot, f: NoTradeFilters, at: datetime) -> SnapshotMetrics:
    reasons: list[FilterReason] = []
    m = s.market
    yes, no = s.yes_asks, s.no_asks
    freshness = "UNKNOWN"
    if yes is None:
        reasons.append(FilterReason.BOOK_MISSING)
    else:
        received = parse_utc(yes.received_at_utc)
        state, _ = _freshness(yes.received_at_utc, max_age=f.max_book_age, as_of=at)
        freshness = "LOOKAHEAD" if received is not None and received > at else state.value
        if freshness != Freshness.FRESH.value:
            reasons.append(FilterReason.STALE_BOOK)
        if (yes.venue, yes.market_id, yes.side) != (m.venue, m.market_id, "YES") or \
                walk_ladder(yes, ONE, price_grid=m.price_grid).status is DepthStatus.INVALID_BOOK:
            reasons.append(FilterReason.INVALID_BOOK)
    valid_yes = yes is not None and FilterReason.INVALID_BOOK not in reasons
    valid_no = no is not None and (no.venue, no.market_id, no.side) == (m.venue, m.market_id, "NO") and \
        walk_ladder(no, ONE, price_grid=m.price_grid).status is not DepthStatus.INVALID_BOOK
    yes_ask = yes.asks[0].price if valid_yes and yes.asks else None
    no_ask = no.asks[0].price if valid_no and no.asks else None
    spread = None if yes_ask is None or no_ask is None else yes_ask + no_ask - ONE
    if verification_at(s.fee_schedule, at, m.native_id).status is FeeScheduleStatus.UNSUPPORTED \
            and f.require_fee_model:
        reasons.append(FilterReason.FEE_UNSUPPORTED)
    if f.max_spread is not None and valid_yes:
        if spread is None:
            reasons.append(FilterReason.SPREAD_UNKNOWN)
        elif spread > f.max_spread:
            reasons.append(FilterReason.WIDE_SPREAD)
    probe_status = probe_cost = None
    if valid_yes:
        fill = walk_ladder(yes, f.probe_quantity, price_grid=m.price_grid)
        probe_status = fill.status.value
        if fill.status is DepthStatus.DEPTH_UNKNOWN:
            reasons.append(FilterReason.DEPTH_UNKNOWN)
        elif fill.status is DepthStatus.INSUFFICIENT_DEPTH:
            reasons.append(FilterReason.INSUFFICIENT_DEPTH)
        elif fill.status is DepthStatus.FILLABLE:
            cost, _ = price_depth_fill(fill, s.fee_schedule)
            probe_cost = None if cost is None else cost.cost_per_contract
    ordered = sorted(set(reasons), key=_FILTER_ORDER.__getitem__)
    return SnapshotMetrics(
        s.snapshot_id, m.market_id, s.cluster_id, s.group, freshness, yes_ask, no_ask,
        None if no_ask is None else ONE - no_ask, spread,
        yes.asks[0].size if valid_yes and yes.asks else None,
        sum((lv.size for lv in yes.asks), ZERO) if valid_yes else None,
        yes.truncated if valid_yes else None, probe_status, probe_cost, tuple(r.value for r in ordered))


def depth_report(snapshots: Iterable[BookSnapshot], filters: NoTradeFilters, *, as_of_utc: str,
                 evidence_class: EvidenceClass, code_version: str, experiment_id: str | None = None,
                 evidence_use_event_id: str | None = None) -> DepthReport:
    """Spread and depth per group (fresh, valid books only) and the no-trade-filter attrition, with separate
    denominators for snapshots, markets and events (clusters). Feature-only: no outcome is read."""
    at = parse_utc(as_of_utc)
    if at is None:
        raise ValueError("as_of_utc must be timezone-aware")
    probe = _dec(filters.probe_quantity, "probe quantity")
    if probe <= 0:
        raise ValueError("probe quantity must be positive")
    snaps = list(snapshots)
    ids = [s.snapshot_id for s in snaps]
    if len(ids) != len(set(ids)):
        raise ValueError("snapshot ids must be unique")
    metrics = tuple(_snapshot(s, filters, at) for s in snaps)
    stamp = make_stamp(evidence_class, code_version=code_version,
                       inputs={"snapshots": [{"id": s.snapshot_id, "market": s.market, "cluster": s.cluster_id,
                                              "group": s.group, "yes": s.yes_asks, "no": s.no_asks,
                                              "fee": s.fee_schedule.schedule_id} for s in snaps],
                               "filters": filters, "as_of": as_of_utc},
                       experiment_id=experiment_id, evidence_use_event_id=evidence_use_event_id)
    usable = [x for x in metrics if x.freshness == Freshness.FRESH.value and x.yes_ask is not None
              and FilterReason.INVALID_BOOK.value not in x.reasons]
    groups = []
    for g in sorted({x.group for x in usable}):
        members = [x for x in usable if x.group == g]
        n = len(members)
        with localcontext() as ctx:
            ctx.prec = _PREC
            trunc = _q(Decimal(sum(1 for x in members if x.captured_depth_truncated)) / n)
            fillable = _q(Decimal(sum(1 for x in members if x.probe_status == DepthStatus.FILLABLE.value)) / n)
        groups.append(GroupDepth(
            g, n, len({x.market_id for x in members}), len({x.cluster_id for x in members}),
            _distribution([x.spread for x in members if x.spread is not None]),
            sum(1 for x in members if x.spread is None),
            _distribution([x.top_depth for x in members if x.top_depth is not None]), trunc, fillable,
            _distribution([x.probe_all_in_per_contract for x in members if x.probe_all_in_per_contract is not None])))
    raw: dict[str, int] = {}
    primary: dict[str, int] = {}
    for x in metrics:
        for r in x.reasons:
            raw[r] = raw.get(r, 0) + 1
        if x.reasons:
            primary[x.reasons[0]] = primary.get(x.reasons[0], 0) + 1
    report = DepthReport(stamp, HARNESS_VERSION, at.isoformat(), filters, metrics, tuple(groups),
                         dict(sorted(raw.items())), dict(sorted(primary.items())),
                         {k.value: v.value for k, v in EXCLUSION_MAP.items()}, _attrition(metrics, as_of_utc),
                         ("Spreads and depths are from fresh, valid books only; stale is not current.",
                          "A one-sided book has an UNKNOWN spread, never 0.",
                          "Captured depth of a truncated capture is a lower bound.",
                          "Feature-only diagnostic: no outcome, no P&L, no edge."))
    return _with_hash(report)


def _attrition(metrics: Sequence[SnapshotMetrics], as_of_utc: str) -> AttritionReport:
    def mapped(reasons: Sequence[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(EXCLUSION_MAP[FilterReason(r)].value for r in reasons))

    units = [AttritionUnit(Level.SNAPSHOT, x.snapshot_id, mapped(x.reasons), None, x.cluster_id) for x in metrics]
    for level, key in ((Level.MARKET, "market_id"), (Level.EVENT, "cluster_id")):
        grouped: dict[str, list[SnapshotMetrics]] = {}
        for x in metrics:
            grouped.setdefault(getattr(x, key), []).append(x)
        for unit_id, xs in sorted(grouped.items()):
            survives = any(not x.reasons for x in xs)
            reasons = () if survives else tuple(dict.fromkeys(r for x in xs for r in mapped(x.reasons[:1])))
            units.append(AttritionUnit(level, unit_id, reasons, None, xs[0].cluster_id))
    return attrition_report(units, as_of_utc=as_of_utc,
                            levels_enumerated=(Level.SNAPSHOT, Level.MARKET, Level.EVENT),
                            not_applicable_stages=(Stage.CAPITAL, Stage.FILL, Stage.OUTCOME))


# =========================================================================== governance (CLI)


def protocol_guard_problems(experiment_id: str, evidence_use_event_id: str, *, root: Path) -> list[str]:
    """Why a governed (RETROSPECTIVE_EXPLORATORY / PROSPECTIVE) run may not proceed: the experiment must be
    registered with a protocol declaring Track B's prohibitions, and the evidence-use event must already be in
    its log, logged for that experiment."""
    from . import experiments
    from .research_evidence import LOG_NAME, EvidenceError, norm_scope, read_log

    matches = [p for p in experiments.discover(root) if p.parent.name.startswith(experiment_id + "-")]
    if len(matches) != 1:
        return [f"{experiment_id} is not registered exactly once under {root}"]
    exp = experiments.load(matches[0])
    problems = []
    if experiments.load_protocol(exp) is None:
        return [f"{experiment_id} has no protocol.toml"]
    missing_inputs = [p for p in TRACK_B_PROHIBITED_INPUTS if p not in experiments.prohibited_inputs(exp)]
    declared_scopes = {norm_scope(s) for s in experiments.prohibited_label_scopes(exp)}
    missing_scopes = [s for s in TRACK_B_PROHIBITED_LABEL_SCOPES if norm_scope(s) not in declared_scopes]
    missing_fields = [f for f in TRACK_B_PROHIBITED_FIELDS if f not in experiments.prohibited_fields(exp)]
    for what, missing in (("prohibited_inputs", missing_inputs), ("prohibited_label_scopes", missing_scopes),
                          ("prohibited_fields", missing_fields)):
        if missing:
            problems.append(f"{experiment_id} protocol [data_roles] {what} lacks {missing}")
    try:
        log = read_log(exp.path.parent / LOG_NAME)
    except EvidenceError as exc:
        return problems + [f"evidence-use log unreadable: {exc}"]
    event = next((u for u in log.uses if u.event_id == evidence_use_event_id), None)
    if event is None:
        problems.append(f"{evidence_use_event_id} is not in {experiment_id}'s evidence-use log: log the use first")
    elif event.experiment_id != experiment_id:
        problems.append(f"{evidence_use_event_id} was logged for {event.experiment_id}, not {experiment_id}")
    return problems


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                out.append(json.loads(line, parse_float=Decimal))
            except ValueError as exc:
                raise ValueError(f"{path}:{number}: not JSON: {exc}") from None
    return out


def _row_from(d: Mapping[str, Any]) -> PredictionRow:
    def dec(key: str) -> Decimal | None:
        value = d.get(key)
        return None if value is None else Decimal(str(value))

    return PredictionRow(str(d["row_id"]), str(d["market_id"]), str(d["cluster_id"]), str(d["scope"]),
                         str(d["category"]), str(d["side"]), Decimal(str(d["price"])), dec("time_to_close_seconds"),
                         dec("outcome"), dec("trade_size"), str(d.get("price_basis", "UNSPECIFIED")))


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m edge_lab.research_diagnostics calibration --rows FILE.jsonl ...`: one JSON report on stdout."""
    parser = argparse.ArgumentParser(prog="python -m edge_lab.research_diagnostics",
                                     description="Track B offline harness (local files only; no network).")
    sub = parser.add_subparsers(dest="command", required=True)
    cal = sub.add_parser("calibration", help="calibration by price x time-to-close x category x side")
    cal.add_argument("--rows", required=True, type=Path, help="JSONL of PredictionRow fields (numbers as strings)")
    cal.add_argument("--price-edges", required=True, help="comma-separated, e.g. 0,0.1,0.2,...,1")
    cal.add_argument("--tte-edges", required=True, help="comma-separated seconds, e.g. 0,600,3600,86400")
    for p in (cal,):
        p.add_argument("--evidence-class", required=True, choices=[c.value for c in EvidenceClass])
        p.add_argument("--code-version", required=True, help="git commit of the code that runs")
        p.add_argument("--experiment", default=None)
        p.add_argument("--evidence-use-event", default=None)
        p.add_argument("--experiments-root", type=Path, default=Path(__file__).resolve().parents[2] / "experiments")
    args = parser.parse_args(argv)
    klass = EvidenceClass(args.evidence_class)
    if klass in _GOVERNED:
        if not args.experiment or not args.evidence_use_event:
            print(f"{klass.value} needs --experiment and --evidence-use-event", file=sys.stderr)
            return 2
        problems = protocol_guard_problems(args.experiment, args.evidence_use_event, root=args.experiments_root)
        if problems:
            print("refused:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 2
    try:
        rows = [_row_from(d) for d in _read_jsonl(args.rows)]
        report = calibration_report(
            rows, price_edges=[Decimal(x) for x in args.price_edges.split(",")],
            tte_edges_seconds=[Decimal(x) for x in args.tte_edges.split(",")], evidence_class=klass,
            code_version=args.code_version, experiment_id=args.experiment,
            evidence_use_event_id=args.evidence_use_event)
    except (KeyError, ValueError, InvalidOperation) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(canonical_json(report.to_dict()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
