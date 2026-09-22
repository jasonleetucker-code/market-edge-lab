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
    BLOCKED = "blocked"  # must not be collected automatically (terms, access controls)


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
    # Which collection jobs own this source (health profiles, issue #16):
    #   routine    - `edge-lab collect --source all`
    #   settlement - `edge-lab settlement collect`
    #   forward    - `edge-lab forward capture` (EXP-001 Stage B, ADR 0012)
    # `edge-lab health` checks one profile at a time, so a successful routine run is not
    # reported unhealthy because a deliberately separate collector has not run.
    collected_by: tuple[str, ...] = ()


HEALTH_PROFILES = ("routine", "settlement", "forward")


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
            collected_by=("routine", "forward"),
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
            collected_by=("routine",),
        ),
        SourceSpec(
            source_id="kalshi_settlement",
            legacy_name="kalshi_settlement",
            description=(
                "Kalshi settlement evidence: series rules and contract URLs, every page of "
                "settled and historical markets (rules text, strikes, result, "
                "expiration_value), and contract documents as exact bytes."
            ),
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://external-api.kalshi.com/trade-api/v2",
            status=SourceStatus.ACTIVE,
            max_age={
                "series": timedelta(days=7),
                "settled_markets": timedelta(hours=36),
                "historical_markets": timedelta(days=31),
            },
            license_notes="Public market data and published contract documents; research use.",
            collected_by=("settlement",),
        ),
        SourceSpec(
            source_id="kalshi_settlement_weather_company",
            legacy_name="twc_kalshi",
            description=(
                "The Weather Company page named in KXHIGHNY rules_primary from 2026-08-14 "
                "(weather.com/kalshi, station CLINYC). Not collected: see license_notes."
            ),
            access_tier=AccessTier.HTTP_FETCH,
            base_url="https://weather.com/kalshi",
            status=SourceStatus.BLOCKED,
            license_notes=(
                "weather.com Terms of Use (last updated 2026-04-16, reviewed 2026-09-22) forbid "
                "monitoring/copying the Services 'through bots, spiders, scrapers, crawlers, or "
                "other automated means' for unauthorized or commercial purposes without TWC's "
                "express written permission. The page is a JS app with no documented public "
                "API. Do not automate without written permission; do not bypass."
            ),
        ),
        SourceSpec(
            source_id="nws_cli_central_park",
            legacy_name="nws_cli",
            description=(
                "NWS Daily Climate Report (CLI) for Central Park (CLINYC) via api.weather.gov. "
                "Named settlement source for KXHIGHNY through 2026-08-13 and first Source Agency "
                "in Kalshi's GLOBALTEMPERATURE contract terms."
            ),
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://api.weather.gov/products/types/CLI/locations/NYC",
            status=SourceStatus.ACTIVE,
            # Final CLI is issued once per morning; the list must be re-read at least daily
            # to keep every issuance before the API drops it.
            max_age={"cli_list": timedelta(hours=26), "cli_product": timedelta(hours=36)},
            license_notes="US government work; public domain. Identifying User-Agent required.",
            collected_by=("routine",),
        ),
        SourceSpec(
            source_id="nws_pfm_okx",
            legacy_name="nws_pfm",
            description=(
                "NWS OKX Point Forecast Matrices (PFMOKX) as published by api.weather.gov: the "
                "product list and each product's full text. EXP-001 Stage B forecast input "
                "(Central Park NYZ072 daytime max), captured before each decision time."
            ),
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://api.weather.gov/products/types/PFM/locations/OKX",
            status=SourceStatus.ACTIVE,
            # Captured once a day before the 18:00 ET decision; PFMOKX is issued about twice
            # a day. Decision code applies the stricter EXP-001 cutoff/age rule itself.
            max_age={"pfm_list": timedelta(hours=26), "pfm_product": timedelta(hours=30)},
            license_notes="US government work; public domain. Identifying User-Agent required.",
            collected_by=("forward",),
        ),
        SourceSpec(
            source_id="iem_afos_clinyc",
            legacy_name="iem_cli",
            description=(
                "Iowa Environmental Mesonet AFOS archive of NWS CLINYC text products "
                "(historical backfill of the same NWS product)."
            ),
            access_tier=AccessTier.PERMITTED_PUBLIC_ENDPOINT,
            base_url="https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py",
            status=SourceStatus.PLANNED,
            license_notes=(
                "Free academic service; re-serves public-domain NWS products. Be polite "
                "(about one request per second); cite IEM."
            ),
        ),
        SourceSpec(
            source_id="iem_afos_pfmokx",
            legacy_name="iem_pfm",
            description=(
                "Iowa Environmental Mesonet AFOS archive of NWS OKX Point Forecast Matrices "
                "(PFMOKX), the official NWS forecast as issued; EXP-001 uses the Central "
                "Park (NYZ072) daytime maximum. Point-in-time forecast history."
            ),
            access_tier=AccessTier.PERMITTED_PUBLIC_ENDPOINT,
            base_url="https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py",
            status=SourceStatus.PLANNED,
            license_notes=(
                "Free academic service; re-serves public-domain NWS products. Be polite "
                "(about one request per second); cite IEM. One-time manual backfill only."
            ),
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
