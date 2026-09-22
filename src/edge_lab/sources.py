"""Registry of data sources and their access, provenance and freshness contract.

Every collector writes snapshots under a registered `source_id`. The registry
answers "where does this come from, how were we allowed to get it, and how old
may it be before it stops counting as current?" in one place, instead of
scattering those facts across collectors.

Adding a source: see docs/DATA_PROVENANCE.md → "Adding a source".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum


class AccessTier(int, Enum):
    """Preferred ingestion mechanisms, best first. Use the lowest number available."""

    OFFICIAL_API = 1
    OFFICIAL_DOWNLOAD = 2
    PERMITTED_PUBLIC_ENDPOINT = 3
    FEED = 4  # RSS/Atom or another legitimate machine-readable feed
    HTTP_FETCH = 5
    BROWSER_AUTOMATION = 6  # last resort; never to bypass access controls


class SourceStatus(str, Enum):
    ACTIVE = "active"  # a collector exists and runs
    PLANNED = "planned"  # documented, not yet collected


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    # Short name stored in `snapshots.source` (kept for Milestone 1 compatibility).
    legacy_name: str
    description: str
    access_tier: AccessTier
    base_url: str
    status: SourceStatus
    # Maximum age of the latest successful retrieval, per payload kind, before
    # that kind counts as stale. Kinds absent here are UNKNOWN, not fresh.
    max_age: dict[str, timedelta] = field(default_factory=dict)
    requires_credentials: bool = False
    # Bump when the collector's parsing/interpretation of the payload changes.
    parser_version: str = "1"
    # Bump when the upstream schema we rely on changes.
    schema_version: str = "1"
    license_notes: str = ""


REGISTRY: dict[str, SourceSpec] = {
    spec.source_id: spec
    for spec in (
        SourceSpec(
            source_id="kalshi_public",
            legacy_name="kalshi",
            description="Kalshi public market data: series, markets, events, order books.",
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://external-api.kalshi.com/trade-api/v2",
            status=SourceStatus.ACTIVE,
            max_age={
                "series": timedelta(days=1),
                "markets": timedelta(minutes=15),
                "event": timedelta(hours=1),
                "orderbook": timedelta(minutes=5),
            },
            license_notes=(
                "Unauthenticated public market-data endpoints only. Review Kalshi "
                "terms before any redistribution of stored data."
            ),
        ),
        SourceSpec(
            source_id="nws_api",
            legacy_name="nws",
            description="National Weather Service API: points, forecasts, raw grid data.",
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://api.weather.gov",
            status=SourceStatus.ACTIVE,
            max_age={
                "points": timedelta(days=7),
                "forecast": timedelta(hours=3),
                "forecast_hourly": timedelta(hours=2),
                "forecast_grid": timedelta(hours=2),
            },
            license_notes=(
                "US government work; public domain. NWS requires an identifying "
                "User-Agent with contact information."
            ),
        ),
        SourceSpec(
            source_id="kalshi_settlement_weather_company",
            legacy_name="twc_kalshi",
            description=(
                "The Weather Company page named as the KXHIGHNY settlement source in "
                "live Kalshi market rules (series.settlement_sources and "
                "markets[].rules_primary, captured 2026-09-22). Access mechanism and "
                "terms of use not yet reviewed."
            ),
            access_tier=AccessTier.HTTP_FETCH,
            base_url="https://weather.com/kalshi",
            status=SourceStatus.PLANNED,
            license_notes="UNREVIEWED: read weather.com terms before any automated retrieval.",
        ),
        SourceSpec(
            source_id="nws_cli_central_park",
            legacy_name="nws_cli",
            description=(
                "NWS Daily Climate Report (CLI) for Central Park (CLINYC). Official "
                "observed maximum. Live rules reference station CLINYC but name The "
                "Weather Company as the settlement source; whether CLI and the "
                "settlement value agree must be measured, not assumed."
            ),
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://api.weather.gov/products/types/CLI/locations/NYC",
            status=SourceStatus.PLANNED,
            license_notes="US government work; public domain.",
        ),
    )
}

_BY_LEGACY_NAME = {spec.legacy_name: spec for spec in REGISTRY.values()}


def get_source(source_id: str) -> SourceSpec:
    try:
        return REGISTRY[source_id]
    except KeyError:
        raise KeyError(f"Unregistered source: {source_id!r}") from None


def by_legacy_name(name: str) -> SourceSpec:
    try:
        return _BY_LEGACY_NAME[name]
    except KeyError:
        raise KeyError(f"No registered source with legacy name {name!r}") from None
