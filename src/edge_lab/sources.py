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


class CredentialKind(str, Enum):
    """What kind of credential a source needs. There is deliberately no trading kind.

    READ_ONLY_DATA_FEED is a key that can only read a data feed (The Odds API free key,
    directive 2026-09-23 section 10, issue #29). Only the owner installs it, in environment
    configuration; agents never create, request, see or commit it. A credential that can
    trade, withdraw or touch an account is out of scope for this registry altogether.
    """

    NONE = "none"
    READ_ONLY_DATA_FEED = "read_only_data_feed"


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
    # Credential contract (ADR 0019 adapters addendum). A source with a credential names the
    # environment variable the owner installs it in and how it travels (never a header:
    # `edge_lab.http` refuses credential-bearing headers), plus the owner approval on record.
    credential_kind: CredentialKind = CredentialKind.NONE
    credential_env_var: str | None = None
    credential_transport: str | None = None  # "query_param" is the only transport allowed
    owner_approval_ref: str | None = None


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
            # Forward captures also fetch these endpoints, but they are judged by
            # `forward_captures` (cadence-aware), not by this source's health rows.
            collected_by=("routine",),
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
                "event_settlement_markets": timedelta(hours=36),
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
        SourceSpec(
            source_id="polymarket_us_public",
            legacy_name="polymarket_us",
            description=(
                "Polymarket US public gateway (the US CFTC-regulated exchange, not Polymarket "
                "International): markets, events, order books, BBO and settlement prices. "
                "Adapter: edge_lab.polymarket_us (fixtures plus one bounded smoke read)."
            ),
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://gateway.polymarket.us",
            status=SourceStatus.PLANNED,
            max_age={
                "markets": timedelta(minutes=15),
                "events": timedelta(minutes=15),
                "book": timedelta(minutes=5),
            },
            license_notes=(
                "docs.polymarket.us API Introduction (read 2026-09-23): the public API at "
                "gateway.polymarket.us needs no key and is meant for reading and displaying "
                "market data. Rate Limits page: public endpoints 20 requests/s per IP; on 429 "
                "stop, wait >= 1 s, back off. The docs publish no separate data licence. The Terms "
                "(the document polymarket.us/tos embeds) were reviewed on 2026-09-24 "
                "(experiments/multi_venue/polymarket_us_sports_terms_2026-09-24.md): they do NOT clear "
                "unattended collection (license for the user's own trading; no scraping or bulk "
                "downloads). The NFL pilot (ADR 0032) runs on the owner's recorded RISK DECISION of "
                "2026-09-24, not on a Polymarket grant; an owner-attested permission text is UNVERIFIED, "
                "but its conditions are honoured (<= 100 requests/min, Polymarket US attribution, no "
                "redistribution). Research storage only. No authenticated endpoint (api.polymarket.us) "
                "is used. No VPN or geolocation circumvention."
            ),
        ),
        SourceSpec(
            # Health-only identity for the Polymarket US NFL pilot's catalog discovery (ADR 0032).
            # The page snapshots themselves are stored under polymarket_us_public (legacy name
            # "polymarket_us", kind "nfl_events"); this id keeps discovery health apart from book health.
            source_id="polymarket_us_nfl_discovery",
            legacy_name="polymarket_us_nfl_discovery",
            description=(
                "Polymarket US public gateway, NFL game (moneyline) discovery for the research pilot "
                "(edge_lab.polymarket_sports, ADR 0032): GET /v1/events filtered to tagSlug=nfl, closed=false, "
                "sportsMarketTypes=football_team_full_game_winner, paged to an empty page at most every 6 h. "
                "A filtered listing: its coverage is never a full-catalog COMPLETE. Still PLANNED: the timer "
                "is not enabled."
            ),
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://gateway.polymarket.us",
            status=SourceStatus.PLANNED,
            # Discovery runs every 6 h; older than that means a run was missed. Captures stop
            # planning from a scan older than 24 h (polymarket_sports.DISCOVERY_MAX_AGE).
            max_age={"nfl_events": timedelta(hours=6, minutes=30)},
            license_notes=(
                "Terms/access review 2026-09-24 (experiments/multi_venue/polymarket_us_sports_terms_2026-09-24.md): "
                "the API docs offer the keyless public gateway for reading and displaying market data, 20 "
                "requests/s per IP. The Polymarket App Terms (effective 2025-09-25; cover 'related websites, "
                "portals, and APIs') permit bots/automation only 'through authorized APIs', license market data "
                "for personal, non-commercial use in connection with the user's trading, and prohibit "
                "redistribution, scraping and bulk downloads unless expressly licensed. No geographic rule beyond "
                "illegal-location and sanctions clauses. Verdict: NOT CLEARED by the Terms themselves; the pilot "
                "runs on the owner's recorded risk decision of 2026-09-24 (polymarket_sports.OWNER_ACCESS_DECISION), "
                "honouring an unverified attested permission's conditions: <= 100 requests/min, Polymarket US "
                "attribution, no redistribution. Research storage only. No account, no authenticated endpoint, "
                "no VPN or geolocation circumvention."
            ),
        ),
        SourceSpec(
            # Health-only identity for the pilot's target-based research book captures (ADR 0032).
            # Book snapshots are stored under polymarket_us_public (kind "book").
            source_id="polymarket_us_nfl_book",
            legacy_name="polymarket_us_nfl_book",
            description=(
                "Polymarket US public gateway, research book captures (GET /v1/markets/{slug}/book) of NFL "
                "moneyline markets related (never equivalent) to an Odds API event, at T-24h / T-6h / T-60m "
                "(edge_lab.polymarket_sports, ADR 0032). Research evidence only, never an executable price "
                "claim. Still PLANNED: the timer is not enabled."
            ),
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://gateway.polymarket.us",
            status=SourceStatus.PLANNED,
            # Event-relative: freshness is judged per target against its due window, not a fixed age.
            max_age={"book": timedelta(minutes=5)},
            license_notes="Same source, terms review and verdict as polymarket_us_nfl_discovery.",
        ),
        SourceSpec(
            # Health-only identity for the Kalshi KXNHLGAME prospective evidence collector (NHL-B, ADR 0040).
            # Its listings, books and settled reads are stored under kalshi_public (legacy name "kalshi"); this
            # id keeps NHL health apart from EXP-001 and from the NFL pairing, so neither can vouch for the other.
            source_id="kalshi_public_nhl_game",
            legacy_name="kalshi_public_nhl_game",
            description=(
                "Kalshi public market data, KXNHLGAME (NHL game winner) only: both team markets' books at T-6h and "
                "T-60m before puck drop, planned from the stored The Odds API icehockey_nhl schedule, plus one "
                "settled-markets read per game day (edge_lab.price_observations, ADR 0040). DATA_COLLECTION / "
                "DEVELOPMENT_ONLY, never EXP-002. Still PLANNED: EDGE_LAB_KALSHI_NHL_CAPTURE defaults off."
            ),
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://external-api.kalshi.com/trade-api/v2",
            status=SourceStatus.PLANNED,
            # Event-relative: a book is current for minutes (the kalshi_public orderbook objective); the settled
            # read is once a game day.
            max_age={"orderbook": timedelta(minutes=5), "settled_markets": timedelta(hours=26)},
            license_notes="Same source and terms as kalshi_public: unauthenticated public endpoints only, no "
                          "redistribution before a terms review.",
        ),
        SourceSpec(
            source_id="the_odds_api",
            legacy_name="the_odds_api",
            description=(
                "The Odds API v4 (free tier): sportsbook odds per bookmaker, sports list and "
                "scores. Offered odds are never executable prices. Adapter: edge_lab.odds_api; "
                "game-relative NFL pilot runner: edge_lab.odds_pilot (ADR 0029). Still PLANNED: no "
                "live read has been verified; the key is not installed."
            ),
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://api.the-odds-api.com",
            status=SourceStatus.PLANNED,
            # "events" is the quota-free schedule discovery; the pilot plans from it only while
            # it is at most a day old (edge_lab.odds_pilot.RunnerSettings.discovery_max_age).
            max_age={"odds": timedelta(minutes=10), "sports": timedelta(days=1), "events": timedelta(days=1)},
            requires_credentials=True,
            credential_kind=CredentialKind.READ_ONLY_DATA_FEED,
            credential_env_var="EDGE_LAB_ODDS_API_KEY",
            credential_transport="query_param",
            owner_approval_ref="docs/owner/2026-09-23-integration-production-directive.md",
            license_notes=(
                "Issue #29 (as summarized by the coordinator): the free tier allows storing "
                "responses and deriving analytics; raw data must not be redistributed; historical "
                "odds are not in the free tier (the v4 guide, read 2026-09-23, says historical "
                "endpoints are paid plans only). 500 credits a month on the free tier; this "
                "repository keeps a protective ceiling below it (edge_lab.odds_api.QuotaLedger). "
                "The key travels only as the apiKey query parameter and is redacted everywhere."
            ),
        ),
        SourceSpec(
            # Health-only identity for the pilot's quota-free schedule discovery (issue #50; PR
            # #67 review). The discovery snapshots themselves are stored under the_odds_api
            # (legacy name "the_odds_api", kind "events"); this id exists so source_health for a
            # free discovery is never read as health of the paid odds feed.
            source_id="the_odds_api_discovery",
            legacy_name="the_odds_api_discovery",
            description=(
                "The Odds API v4 quota-free schedule discovery (GET /v4/sports/{sport}/events) "
                "for the game-relative NFL pilot (edge_lab.odds_pilot, ADR 0029). Proves the key "
                "reaches the provider, never that odds arrive; odds-feed health is the_odds_api. "
                "Still PLANNED: no live read has been verified; the key is not installed."
            ),
            access_tier=AccessTier.OFFICIAL_API,
            base_url="https://api.the-odds-api.com",
            status=SourceStatus.PLANNED,
            # The runner refreshes discovery every 6 h on a 15-minute timer; older than that
            # means a refresh was missed. (Planning itself tolerates a discovery up to 24 h old.)
            max_age={"events": timedelta(hours=6, minutes=30)},
            requires_credentials=True,
            credential_kind=CredentialKind.READ_ONLY_DATA_FEED,
            credential_env_var="EDGE_LAB_ODDS_API_KEY",  # the same single key as the_odds_api
            credential_transport="query_param",
            owner_approval_ref="docs/owner/2026-09-23-integration-production-directive.md",
            license_notes=(
                "Same provider, key and terms as the_odds_api. The v4 guide documents the events "
                "endpoint as not counting against the usage quota (re-read 2026-09-24; "
                "experiments/multi_venue/odds_api_credit_rules_2026-09-24.md). It still needs the "
                "key, so it is paced politely (at most every 6 h). The key travels only as the "
                "apiKey query parameter and is redacted everywhere."
            ),
        ),
        SourceSpec(
            source_id="novig_public_data",
            legacy_name="novig_data",
            description=(
                "Novig exchange data: anonymized end-of-day CSVs per trading day (trades.csv, "
                "markets.csv) and their index.json manifest at data.novig.com. End of day, "
                "research only, never executable. Adapter: edge_lab.novig_data."
            ),
            access_tier=AccessTier.OFFICIAL_DOWNLOAD,
            base_url="https://data.novig.com/reporting/trade-data",
            status=SourceStatus.PLANNED,
            max_age={"index": timedelta(hours=36), "trades": timedelta(hours=36),
                     "markets": timedelta(hours=36)},
            license_notes=(
                "docs.novig.com Exchange Data (read 2026-09-23): static files behind a CDN, no "
                "API, no authentication; each day publishes shortly after midnight Eastern; a "
                "day that fails validation is withheld; past files are immutable except "
                "announced corrections. No licence terms are stated on that page: research use "
                "only, no redistribution. The live NBX API needs OAuth client credentials "
                "(NEEDS_ACCESS)."
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
