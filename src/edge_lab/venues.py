"""Venue and account capability registry: the one owner of what each venue or route can do
(ADR 0019).

A capability records what a documented interface *could* do. `stage` records what this
repository has actually shown with evidence. The two are kept apart:
- code existing is IMPLEMENTED;
- passing fixture tests is TESTED;
- only a real, recorded read is LIVE_DATA_VERIFIED.

Nothing here connects, authenticates or trades. `execution_authorized` is False for every
entry and cannot be set True by constructing a spec. Real execution needs a later owner
decision recorded in `docs/EXECUTION_PLAN.md` and a code change reviewed under it.

A venue's cash timing (`VenueCashTiming`) belongs here too. It says when settled proceeds
can be used again for trading, for withdrawal and in a bank account.
`edge_lab.starter_policy` uses only the first of these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ConnectivityStage(str, Enum):
    PLANNED = "PLANNED"
    NEEDS_ACCESS = "NEEDS_ACCESS"  # an owner-provided credential or approval is required first
    IMPLEMENTED = "IMPLEMENTED"  # code exists
    TESTED = "TESTED"  # fixture tests pass; no live read recorded
    LIVE_DATA_VERIFIED = "LIVE_DATA_VERIFIED"  # a real read is recorded as evidence
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNSUPPORTED = "UNSUPPORTED"  # not offered, not permitted, or out of scope


class Capability(str, Enum):
    CATALOG_READ = "catalog_read"
    QUOTE_READ = "quote_read"
    DEPTH_READ = "depth_read"
    HISTORY_READ = "history_read"
    SETTLEMENT_READ = "settlement_read"
    ACCOUNT_READ = "account_read"
    ORDER_WRITE = "order_write"


class VenueKind(str, Enum):
    EXCHANGE = "EXCHANGE"  # an order book with its own liquidity
    AGGREGATOR = "AGGREGATOR"  # republishes other venues' prices; not a place to trade
    ROUTE = "ROUTE"  # a broker/app route onto another venue's liquidity


@dataclass(frozen=True)
class CapabilityState:
    stage: ConnectivityStage
    auth_required: bool | None  # None: not established from documentation
    evidence: str | None = None  # a doc URL, fixture or evidence path
    last_verified_utc: str | None = None


@dataclass(frozen=True)
class Units:
    """How a venue expresses price, quantity and payout. `verified` means from its docs."""

    price_unit: str
    quantity_unit: str
    payout_unit: str
    verified: bool


@dataclass(frozen=True)
class VenueCashTiming:
    """When settled proceeds are usable again. None means unknown and is never assumed.

    `tradable_hold` counts from settlement to cash that can fund a new trade on this venue;
    it is the only clock `STARTER_MAX_7D_V1` uses. `status` is DOCUMENTED when the venue's
    own documentation supports the figure, UNVERIFIED otherwise."""

    tradable_hold: timedelta | None
    withdrawable_hold: timedelta | None
    bank_receipt: timedelta | None
    status: str  # "DOCUMENTED" | "DOCUMENTED_INFERRED" | "UNVERIFIED"
    evidence: str | None
    detail: str


@dataclass(frozen=True)
class VenueSpec:
    venue_id: str
    kind: VenueKind
    route_id: str  # the access route (the venue itself, a broker, an aggregator)
    liquidity_pool_id: str  # the underlying book; two routes onto one pool are not independent
    capabilities: Mapping[Capability, CapabilityState]
    units: Units | None
    cash_timing: VenueCashTiming | None
    notes: str
    execution_authorized: bool = field(default=False)

    def __post_init__(self) -> None:
        if self.execution_authorized:
            raise ValueError("execution is not authorized for any venue (docs/EXECUTION_PLAN.md)")
        missing = set(Capability) - set(self.capabilities)
        if missing:
            raise ValueError(f"{self.venue_id}: capabilities not stated: {sorted(c.value for c in missing)}")
        object.__setattr__(self, "capabilities", MappingProxyType(dict(self.capabilities)))

    def stage(self, capability: Capability) -> ConnectivityStage:
        return self.capabilities[capability].stage


def _caps(**states: CapabilityState) -> dict[Capability, CapabilityState]:
    return {Capability(name): state for name, state in states.items()}


_P, _N, _U = ConnectivityStage.PLANNED, ConnectivityStage.NEEDS_ACCESS, ConnectivityStage.UNSUPPORTED
_TIMING_DIR = "experiments/EXP-001-kxhighny-nws-vs-market/venue_timing"

KALSHI = VenueSpec(
    venue_id="kalshi", kind=VenueKind.EXCHANGE, route_id="kalshi:direct", liquidity_pool_id="kalshi",
    capabilities=_caps(
        catalog_read=CapabilityState(ConnectivityStage.LIVE_DATA_VERIFIED, False,
                                     "forward collector captures (KXHIGHNY events/markets), Gate 2/3 fixtures",
                                     "2026-09-22T22:00:00Z"),
        quote_read=CapabilityState(ConnectivityStage.LIVE_DATA_VERIFIED, False,
                                   "forward collector order-book captures (tests/fixtures/forward)",
                                   "2026-09-22T22:00:00Z"),
        depth_read=CapabilityState(ConnectivityStage.LIVE_DATA_VERIFIED, False,
                                   "order-book levels are captured; `evaluate` prices the best level, "
                                   "`walk_ladder`/`price_depth_fill` price a quantity across levels "
                                   "(best_price comparator, ADR 0027)"),
        history_read=CapabilityState(ConnectivityStage.LIVE_DATA_VERIFIED, False,
                                     "settled-market history (tests/fixtures/gate3/kalshi_markets_all_2026-09-22.json.gz)"),
        settlement_read=CapabilityState(ConnectivityStage.LIVE_DATA_VERIFIED, False,
                                        "settlement evidence collector (edge-lab settlement collect)"),
        account_read=CapabilityState(_N, True, "docs.kalshi.com Get Balance (API key, read scope)"),
        order_write=CapabilityState(_N, True, "docs.kalshi.com Create Order (authenticated); not authorized"),
    ),
    units=Units("USD per contract, 0.0001 grid", "whole contracts", "USD 1 per contract", True),
    cash_timing=VenueCashTiming(
        tradable_hold=timedelta(0), withdrawable_hold=None, bank_receipt=None, status="DOCUMENTED_INFERRED",
        evidence=f"{_TIMING_DIR}/docs_kalshi_market_settlement_2026-09-23T133134Z.md",
        detail=("Kalshi docs: at settlement 'Positions are automatically resolved and funds transferred'. That the "
                "transferred funds can fund a new trade at once is an INFERENCE (no post-settlement trading hold "
                "is documented), not an explicit statement. Withdrawal and bank timing are not modelled. An "
                "account-level hold cannot be seen without an account read, which is not authorized."),
    ),
    notes="Existing weather integration. Reads are public and unauthenticated.",
)

POLYMARKET_US = VenueSpec(
    venue_id="polymarket_us", kind=VenueKind.EXCHANGE, route_id="polymarket_us:direct",
    liquidity_pool_id="polymarket_us",
    capabilities=_caps(
        catalog_read=CapabilityState(ConnectivityStage.TESTED, False, "edge_lab.polymarket_us + tests/test_polymarket_us.py; one live smoke "
                                     "read recorded in experiments/multi_venue/polymarket_us_smoke_2026-09-23.md "
                                     "(stage left at TESTED: LIVE_DATA_VERIFIED is for the coordinator to set)"),
        quote_read=CapabilityState(ConnectivityStage.TESTED, False, "GET /v1/markets/{slug}/book -> ExecutableQuote (documented example "
                                   "fixture); BBO has no size at the best price and is never a quote"),
        depth_read=CapabilityState(ConnectivityStage.TESTED, False, "book levels parsed and validated; "
                                   "`walk_ladder`/`price_depth_fill` price a quantity across levels "
                                   "(best_price comparator, ADR 0027); ladders are truncated unless proven complete"),
        history_read=CapabilityState(_P, False, "public gateway price history (docs); not implemented"),
        settlement_read=CapabilityState(ConnectivityStage.TESTED, False, "GET /v1/markets/{slug}/settlement parser (documented example)"),
        account_read=CapabilityState(_N, True, "api.polymarket.us portfolio endpoints (authenticated)"),
        order_write=CapabilityState(_N, True, "api.polymarket.us trading endpoints (authenticated); not authorized"),
    ),
    units=None, cash_timing=None,
    notes="Polymarket US (a CFTC-regulated US exchange). Not Polymarket International. Fee schedule "
          "captured (fee_schedules.POLYMARKET_US_TAKER_V1, a conservative bound with claim basis NONE, ADR 0027); "
          "units unverified.",
)

POLYMARKET_INTERNATIONAL = VenueSpec(
    venue_id="polymarket_international", kind=VenueKind.EXCHANGE, route_id="polymarket_international:direct",
    liquidity_pool_id="polymarket_international",
    capabilities=_caps(**{c.value: CapabilityState(_U, None, "docs.polymarket.com geoblock: the US is close-only")
                          for c in Capability}),
    units=None, cash_timing=None,
    notes="A separate venue from Polymarket US. Not usable for new positions from the US; no circumvention.",
)

NOVIG = VenueSpec(
    venue_id="novig", kind=VenueKind.EXCHANGE, route_id="novig:direct", liquidity_pool_id="novig",
    capabilities=_caps(
        catalog_read=CapabilityState(_N, True, "https://docs.novig.com/api-reference/authentication (OAuth client credentials)"),
        quote_read=CapabilityState(_N, True, "Novig REST/WebSocket books (authenticated)"),
        depth_read=CapabilityState(_N, True, "Novig WebSocket order books (authenticated)"),
        history_read=CapabilityState(ConnectivityStage.TESTED, False, "edge_lab.novig_data + tests/test_novig_data.py (public daily CSVs; end of "
                                     "day, not executable); one manual read recorded in "
                                     "experiments/multi_venue/novig_daily_data_capture_2026-09-23.md"),
        settlement_read=CapabilityState(_N, True, "authenticated API"),
        account_read=CapabilityState(_N, True, "authenticated API"),
        order_write=CapabilityState(_N, True, "authenticated API; not authorized"),
    ),
    units=Units("cost/qty is a probability in (0, 1)", "qty in Novig reporting units (UNVERIFIED vs $1 contracts)",
                "unverified", False),
    cash_timing=None,
    notes="Developer credentials must be requested by the owner. Public daily files are research data only.",
)

THE_ODDS_API = VenueSpec(
    venue_id="the_odds_api", kind=VenueKind.AGGREGATOR, route_id="the_odds_api:v4",
    liquidity_pool_id="none (republishes sportsbook prices)",
    capabilities=_caps(
        catalog_read=CapabilityState(ConnectivityStage.LIVE_DATA_VERIFIED, True,
                                     "free events endpoint: 32 NFL events discovered on production (odds plan, "
                                     "runbook 5b activation record, 2026-09-24)", "2026-09-24T13:38:30Z"),
        quote_read=CapabilityState(ConnectivityStage.LIVE_DATA_VERIFIED, True,
                                   "one smoke read on production: snapshot 22, 16 events, 856 offers from 9 books "
                                   "(runbook 5b activation record); offered odds per bookmaker, never executable "
                                   "and not fillable here", "2026-09-24T13:38:54Z"),
        depth_read=CapabilityState(_U, None, "no depth or size is published"),
        history_read=CapabilityState(_U, None, "historical odds are not in the free tier"),
        settlement_read=CapabilityState(_N, True, "scores endpoint (free-tier key)"),
        account_read=CapabilityState(_U, None, "not a trading venue"),
        order_write=CapabilityState(_U, None, "not a trading venue"),
    ),
    units=Units("American or decimal odds as offered", "none", "per-book rules", True),
    cash_timing=None,
    notes="Sportsbook-consensus research input (#29). Each bookmaker is a route onto its own book.",
)

VENUES: Mapping[str, VenueSpec] = MappingProxyType({
    v.venue_id: v for v in (KALSHI, POLYMARKET_US, POLYMARKET_INTERNATIONAL, NOVIG, THE_ODDS_API)
})


def get_venue(venue_id: str) -> VenueSpec:
    try:
        return VENUES[venue_id]
    except KeyError:
        raise KeyError(f"unknown venue {venue_id!r}") from None


def cash_timing(venue_id: str) -> VenueCashTiming | None:
    spec = VENUES.get(venue_id)
    return None if spec is None else spec.cash_timing


def coverage_rows() -> list[dict[str, object]]:
    """One row per venue and capability, for reports and the dashboard."""
    return [{"venue_id": v.venue_id, "kind": v.kind.value, "route_id": v.route_id,
             "liquidity_pool_id": v.liquidity_pool_id, "capability": c.value,
             "stage": v.stage(c).value, "auth_required": v.capabilities[c].auth_required,
             "evidence": v.capabilities[c].evidence, "execution_authorized": v.execution_authorized}
            for v in VENUES.values() for c in Capability]
