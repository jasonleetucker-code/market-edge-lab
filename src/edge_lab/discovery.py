"""Broad market discovery: classify what a catalog shows without inventing what it does not.

Directive 2026-09-23 section 12: discover broadly, model narrowly. The pipeline is

    catalog discovery -> data / settlement / horizon screen -> model supported?
    -> validated research -> shadow -> eventual live eligibility

and this module is the first two steps plus the "model supported?" question. It is shared
by every venue adapter (Kalshi, Polymarket US, Novig later) through the generic `Market` and
`Event` contracts. There is no per-venue discovery engine.

Rules:
- **No model, no probability.** A market without a validated model estimate is
  MODEL_UNSUPPORTED and its record carries `probability=None`. Nothing is fabricated.
- **A title match is not rule equivalence.** MATCHED_EQUIVALENT needs equal
  `Event.settlement_identity`, captured and resolved rules on both sides (`rules_resolved`,
  `rules_sha256`), and the same contract: payoff kind, amount, YES condition and outcome.
  Anything else a caller offers as a candidate is at most RELATED_NOT_EQUIVALENT.
- **Uniqueness is only claimed within verified coverage.** UNIQUE_WITHIN_VERIFIED_COVERAGE
  needs every searched venue's catalog coverage to be COMPLETE and no candidate at all. The
  record names the venues and the as-of time. A failed or partial catalog is never
  evidence that a market does not exist elsewhere.
- **The starter policy is applied as-is.** New venues usually have no settlement-lag or
  cash-timing evidence, so `STARTER_MAX_7D_V1` fails closed (SETTLEMENT_TIMING_UNVERIFIED).
  That is the correct answer, not a bug to work around.
- **Execution is disabled** for every record (`venues`: execution is never authorized).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Sequence

from . import starter_policy, venues
from .freshness import parse_utc
from .opportunity import Event, Market, ModelEstimate


class DiscoveryStatus(str, Enum):
    CATALOG_ONLY = "CATALOG_ONLY"
    DATA_PARTIAL = "DATA_PARTIAL"
    MODEL_UNSUPPORTED = "MODEL_UNSUPPORTED"
    RULES_UNRESOLVED = "RULES_UNRESOLVED"
    SOURCE_COVERAGE_UNKNOWN = "SOURCE_COVERAGE_UNKNOWN"
    MATCHED_EQUIVALENT = "MATCHED_EQUIVALENT"
    RELATED_NOT_EQUIVALENT = "RELATED_NOT_EQUIVALENT"
    UNIQUE_WITHIN_VERIFIED_COVERAGE = "UNIQUE_WITHIN_VERIFIED_COVERAGE"
    RESEARCHING = "RESEARCHING"
    SHADOW_TESTING = "SHADOW_TESTING"
    VALIDATED_FOR_SCOPE = "VALIDATED_FOR_SCOPE"
    MANUAL_ONLY = "MANUAL_ONLY"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"


# Statuses a caller may assert from the research lifecycle; the rest are derived here.
LIFECYCLE_STATUSES = frozenset({DiscoveryStatus.RESEARCHING, DiscoveryStatus.SHADOW_TESTING,
                                DiscoveryStatus.VALIDATED_FOR_SCOPE, DiscoveryStatus.MANUAL_ONLY})


class CoverageState(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CatalogCoverage:
    """How much of one venue's catalog listing was actually read.

    Only COMPLETE supports a claim that a market is not listed. Venue adapters produce these
    (for example `polymarket_us.read_catalog`)."""

    venue: str
    endpoint: str
    state: CoverageState
    pages_ok: int
    items: int
    as_of_utc: str | None
    detail: str

    @property
    def complete(self) -> bool:
        return self.state is CoverageState.COMPLETE


WEATHER_EXP001_ONLY = "WEATHER_EXP001_ONLY"  # only the frozen EXP-001 KXHIGHNY scope has a model
MODEL_UNSUPPORTED = "MODEL_UNSUPPORTED"


@dataclass(frozen=True)
class DomainTarget:
    domain: str
    label: str
    model_support: str


# The owner's discovery targets (directive section 12). They are research targets, not models.
DOMAIN_INVENTORY: tuple[DomainTarget, ...] = tuple(
    DomainTarget(domain, label, WEATHER_EXP001_ONLY if domain == "weather" else MODEL_UNSUPPORTED)
    for domain, label in (
        ("weather", "Weather"),
        ("nfl", "NFL"),
        ("college_football", "College football"),
        ("nba", "NBA"),
        ("wnba", "WNBA"),
        ("college_basketball", "College basketball"),
        ("nhl", "NHL"),
        ("mlb", "MLB"),
        ("ufc_mma", "UFC / MMA"),
        ("boxing", "Boxing"),
        ("soccer", "Soccer"),
        ("tennis", "Tennis"),
        ("golf", "Golf"),
        ("motorsports", "Motorsports"),
        ("cricket", "Cricket"),
        ("rugby", "Rugby"),
        ("esports", "Esports"),
        ("politics", "Politics"),
        ("economic_releases", "Economic releases"),
        ("other", "Other well-defined near-term event markets"),
    )
)
_DOMAINS = {t.domain: t for t in DOMAIN_INVENTORY}


def domain_target(domain: str | None) -> DomainTarget:
    return _DOMAINS.get((domain or "").strip().lower(), _DOMAINS["other"])


@dataclass(frozen=True)
class Candidate:
    """A market on another venue (or the same one) offered as a possible match."""

    event: Event
    market: Market


@dataclass(frozen=True)
class DiscoveryRecord:
    market_id: str
    venue: str
    event_id: str
    domain: str
    model_support: str
    statuses: tuple[str, ...]
    probability: float | None  # only ever from a model estimate; never fabricated
    model_id: str | None
    starter: dict[str, Any]
    equivalents: tuple[str, ...]
    related: tuple[str, ...]
    coverage_venues: tuple[str, ...]
    coverage_as_of_utc: str | None
    execution_authorized: bool = False
    detail: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        out = dict(self.__dict__)
        for key in ("statuses", "equivalents", "related", "coverage_venues", "detail"):
            out[key] = list(out[key])
        return out


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def is_equivalent(a_event: Event | None, a: Market, b_event: Event, b: Market) -> bool:
    """Same settlement identity **and** the same contract; never a title comparison.

    Both sides need resolved, captured rules (`rules_resolved`, a `rules_sha256`), and the
    same payoff (kind, amount, normalized YES condition) and outcome. Equal event identity
    alone is not enough: sibling brackets of one event settle on the same source but pay
    on different outcomes."""
    return (a_event is not None and a.rules_resolved and b.rules_resolved
            and a.rules_sha256 is not None and b.rules_sha256 is not None
            and a_event.settlement_identity == b_event.settlement_identity
            and a.event_id == a_event.event_id and b.event_id == b_event.event_id
            and a.payoff.kind == b.payoff.kind and a.payoff.amount == b.payoff.amount
            and _norm(a.payoff.yes_condition) == _norm(b.payoff.yes_condition)
            and _norm(a.outcome) == _norm(b.outcome))


def _series_scope(market: Market) -> str | None:
    # Settlement-lag evidence is registered per Kalshi series; other venues have none yet.
    if market.venue == "kalshi" and market.native_id:
        return market.native_id.split("-", 1)[0]
    return None


def classify(market: Market, *, estimate: ModelEstimate | None, coverage: Sequence[CatalogCoverage],
             candidates: Iterable[Candidate], now: datetime | str, event: Event | None = None,
             has_quote: bool = False, lifecycle: Iterable[DiscoveryStatus] = ()) -> DiscoveryRecord:
    """Classify one discovered market as of `now` (also the hypothetical commitment time for
    the starter policy)."""
    at = parse_utc(now)
    if at is None:
        raise ValueError("now must be a timezone-aware time")
    statuses: list[DiscoveryStatus] = []
    detail: list[str] = []

    has_model = estimate is not None and estimate.probability is not None
    if estimate is not None and (estimate.market_id != market.market_id):
        detail.append(f"estimate is for {estimate.market_id}, not this market: ignored")
        has_model = False
    if not has_model:
        statuses.append(DiscoveryStatus.MODEL_UNSUPPORTED)
        detail.append("no validated model estimate for this market; no probability is given")
    if not has_model and not has_quote:
        statuses.append(DiscoveryStatus.CATALOG_ONLY)
    if not market.rules_resolved:
        statuses.append(DiscoveryStatus.RULES_UNRESOLVED)
        detail.append(market.rules_detail)

    coverage = list(coverage)
    if not coverage:
        statuses.append(DiscoveryStatus.SOURCE_COVERAGE_UNKNOWN)
        detail.append("no catalog coverage record: other venues were not searched")
    else:
        if any(c.state is CoverageState.FAILED for c in coverage):
            statuses.append(DiscoveryStatus.SOURCE_COVERAGE_UNKNOWN)
        if any(not c.complete for c in coverage):
            statuses.append(DiscoveryStatus.DATA_PARTIAL)
            detail += [f"{c.venue} catalog {c.state.value}: {c.detail}" for c in coverage if not c.complete]

    equivalents: list[str] = []
    related: list[str] = []
    for cand in candidates:
        if cand.market.market_id == market.market_id:
            continue
        if is_equivalent(event, market, cand.event, cand.market):
            equivalents.append(cand.market.market_id)
        else:
            related.append(cand.market.market_id)
    if equivalents:
        statuses.append(DiscoveryStatus.MATCHED_EQUIVALENT)
    if related:
        statuses.append(DiscoveryStatus.RELATED_NOT_EQUIVALENT)
        detail.append("related candidates lack equal settlement identity or resolved rules on both sides")

    coverage_venues = tuple(sorted({c.venue for c in coverage}))
    as_of_values = [parse_utc(c.as_of_utc) for c in coverage]
    as_of = None if not coverage or any(v is None for v in as_of_values) else min(as_of_values).isoformat()
    if coverage and all(c.complete for c in coverage) and not equivalents and not related and as_of is not None:
        statuses.append(DiscoveryStatus.UNIQUE_WITHIN_VERIFIED_COVERAGE)
        detail.append(f"no candidate within complete catalogs of {', '.join(coverage_venues)} as of {as_of}")

    for status in lifecycle:
        status = DiscoveryStatus(status)
        if status not in LIFECYCLE_STATUSES:
            raise ValueError(f"{status.value} is derived, not asserted")
        if status is DiscoveryStatus.VALIDATED_FOR_SCOPE and not has_model:
            raise ValueError("VALIDATED_FOR_SCOPE needs a model estimate")
        statuses.append(status)

    spec = venues.VENUES.get(market.venue)
    if spec is None or not spec.execution_authorized:
        statuses.append(DiscoveryStatus.EXECUTION_DISABLED)

    verdict = starter_policy.assess(
        commitment=at, timing=market.timing,
        lag=starter_policy.lag_evidence(market.venue, _series_scope(market)),
        cash=venues.cash_timing(market.venue))

    target = domain_target(event.domain if event is not None else None)
    ordered = tuple(dict.fromkeys(s.value for s in statuses))
    return DiscoveryRecord(
        market_id=market.market_id, venue=market.venue, event_id=market.event_id, domain=target.domain,
        model_support=target.model_support, statuses=ordered,
        probability=estimate.probability if has_model else None,
        model_id=estimate.model_id if has_model else None,
        starter=verdict.to_dict(), equivalents=tuple(equivalents), related=tuple(related),
        coverage_venues=coverage_venues, coverage_as_of_utc=as_of, detail=tuple(detail),
    )
