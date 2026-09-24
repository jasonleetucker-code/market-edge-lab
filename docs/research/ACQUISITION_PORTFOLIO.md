# Cross-domain data acquisition portfolio (issue #86, Deliverable 1)

**Date:** 2026-09-24 (reads made 21:50–22:46Z).
**Author:** Lane F (laptop Claude session), docs/research only.
**Authority:** owner directive `docs/owner/2026-09-24-cross-domain-prospective-evidence-directive.md`
(issue #86), §3, §6, §43–§44, §56, §63–§69; `docs/EXECUTION_PLAN.md`, 2026-09-24 (evening, later)
entry. At the time of writing, both were on PR #87 and not yet merged. **Owner idea #88** (Public
Markets Edge: equities, options, futures) is included as a first-class domain (§1.7), at the
coordinator's direction of 2026-09-24.
**Companion:** `docs/research/SOURCE_READINESS.md` (Deliverable 3: per-domain readiness, labels,
completeness, timestamps, anomalies, and the shared release/event calendar contract).

This document authorizes nothing. A row marked READY TO IMPLEMENT still goes through the gated,
one-source-at-a-time rollout in `docs/EXECUTION_PLAN.md`:
- a registry entry, a terms review and a worst-case budget;
- a #74 fabric provider;
- fixture → sample → bounded smoke → low-frequency collection;
- review and exact-head CI.

Enabling any timer remains an owner decision (`AI_INSTRUCTIONS.md`, Authority). **Unknown stays
unknown.** Every number marked *(est.)* is an estimate from fixtures or single reads, not a
production measurement.

## 0. How this was verified

- **Official documents.** Each was read with a web fetch on 2026-09-24. The URL is recorded
  beside the claim, with at most a short quoted phrase. When a page could not be read (HTTP 403,
  404 or 429, or a JavaScript-only page), the cell says so, and the claim stays UNVERIFIED.
- **Kalshi catalog measurements.** These are keyless, paced public GETs (1 s apart, identifying
  User-Agent), made 2026-09-24 about 22:40Z to size the streams. Nothing was stored in any evidence
  store. Only the figures below were kept.

  | Read | Result |
  |---|---|
  | `GET /trade-api/v2/series` (no filter) | 200. **17,633,417 bytes** (1,622,207 gzipped). 14,378 series. SHA-256 `703541b4…6d12` |
  | `GET /events?status=open&limit=200`, cursor-paged, capped at 40 pages | **8,000 open events in 4,545,423 bytes, cursor still non-empty: PARTIAL.** The open catalog is larger than 8,000 events, and its true size is unknown |
  | `GET /markets?event_ticker=KXBTCD-26SEP2419` | 188 markets, **351,549 bytes** (one hourly BTC above/below event) |
  | `…KXCPI-26SEP` | 14 markets, 26,493 bytes, close_time **2026-10-14T12:25:00Z** (08:25 ET) |
  | `…KXPAYROLLS-26SEP` | 13 markets, 20,443 bytes, close_time 2026-10-02T12:29:00Z (08:29 ET) |
  | `…KXJOBLESSCLAIMS-26OCT01` | 11 markets, 17,219 bytes, close_time 2026-10-01T12:25:00Z |
  | `…KXEIACRUDEW-26SEP30` | 13 markets, 28,014 bytes, close_time 2026-09-30T14:29:00Z (10:29 ET) |

  **Finding that shapes the macro design.** The market that settles on a release closes
  **before** the release: CPI and claims at 08:25 ET, payrolls at 08:29 ET, EIA crude at 10:29 ET,
  against releases at 08:30 and 10:30 ET. Post-release reaction windows (T+1m, T+5m, …) therefore
  exist only in *other*, still-open related families (Fed funds, annual CPI and the like). They do
  not exist in the family that settles on the number (§5 below).
- **Series metadata is not settlement documentation.** Several recurring economics series list
  settlement sources that look wrong:
  - `KXEIACRUDEW`: "Federal Reserve Bank of New York";
  - `KXUSRETAIL` and `KXJOLTSOPEN`: "Bureau of Labor Statistics- Employment Situation";
  - `KXUSPPI` and `KXUSISMSERV`: "Trading Economics".

  Each family's captured `rules_primary`/`rules_secondary` must be read before any label plan is
  called verified (`AI_INSTRUCTIONS.md`: a title is not settlement documentation).

**Readiness classes** (Deliverable 3), shown in the *implementation status* column:
- ACTIVE NOW;
- READY TO IMPLEMENT;
- NEEDS FREE OWNER KEY (= READY_FOR_OWNER_KEY);
- NEEDS TERMS REVIEW;
- NEEDS SPECIFIC EXPERIMENT;
- PAID/ROI BLOCKED;
- NOT CURRENTLY WORTH COLLECTING.

**Irrecoverability** (§3):
- **A:** reconstructible history;
- **B:** partially reconstructible (vintages, issuance history, day-level timing);
- **C:** irrecoverable point-in-time evidence.

A row can carry several classes, one per data part.

## 1. Portfolio table

Each domain has its own table, with the same 18 columns in the order the directive gives. Byte
figures are payload bytes as canonical JSON. For database growth, add about 30% for rows and
indexes *(est., unmeasured)*.

### 1.1 Tier 0: market data (prediction-market venues)

| domain | source | exact endpoint/feed class | official/third-party | auth | cost | rate/quota | terms state | data collected | publication/update cadence | desired capture cadence | why it matters | historical archive availability | point-in-time irrecoverability | storage/day estimate | requests/day estimate | implementation status | owner action needed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WEATHER | Kalshi (KXHIGHNY) | `external-api.kalshi.com/trade-api/v2` `/events/{t}`, `/markets?event_ticker=`, `/markets/{t}/orderbook` (depth 100); settlement pages | official | none (public) | free | repo pacer 0.6 s; public host returned 429 at about 4 req/s (probe 2026-09-22, `DATA_PROVENANCE.md` §2). The Basic tier (authenticated) is 200 tokens/s at a default of 10 tokens per request (docs.kalshi.com/getting_started/rate_limits, read 2026-09-24) | public endpoints need no keys ("public endpoints that don't require API keys", docs.kalshi.com quick_start_market_data). The Developer Agreement (kalshi.com/developer-agreement) returned **HTTP 429** to our fetch: not re-read. Research storage only, no redistribution (registry note) | event, brackets, rules text, books, status, close time, settlement | continuous; close 05:00Z | as deployed: decision, recheck, +1 h, +6 h, pre-close, close, settlement-preceding | EXP-001 (frozen); later/close prices for #50 | settled markets and events stay retrievable. Candlesticks (1-minute `yes_bid`/`yes_ask` OHLC) and trades are public and move to `/historical` after a cutoff (docs historical_data, read 2026-09-24). **No historical order books are documented** | depth: **C**; top-of-book path: B (candlesticks, P1-8, not yet proven by a stored read); settlement: A | about 0.4 MB (est.: 75 KB PFM + 40 KB decision/recheck + ≤250 KB observations + ≤35 KB settlement) | about 57 typical, about 170 worst | **ACTIVE NOW** (`kalshi_public`, `kalshi_settlement`, forward and observe timers) | none |
| ALL | Kalshi series catalog | `GET /series` (all 14,378 series: rules URLs, `settlement_sources`, `fee_type`, `frequency`, `last_updated_ts`) | official | none | free | as above; one 17.6 MB response | as above | series identity, category, frequency, contract URLs, named settlement sources | changes continuously (`last_updated_ts`) | weekly full read, stored compressed. Daily reads only for the watched families (next row) | §5 discovery across every planned domain: new recurring families, and fee or source changes. Named families: all of §1.1 | series stay available ("Old Events and Series will always still be available", historical_data doc). **Metadata changes over time are not versioned publicly** | series existence: A; *when* a rule, source or fee changed: **C** | 17.6 MB raw per read → about 2.5 MB/day averaged; 1.6 MB/week gzipped (**about 0.23 MB/day**) | 1 a week | READY TO IMPLEMENT, with a memory caveat (§3.4). Parsing 17.6 MB of JSON in one unit is estimated at 90–180 MB of Python objects. Store the bytes as a compressed blob; parse streamed or in bounded chunks | approve the timer when the collector is proposed |
| ALL | Kalshi recurring-family inventory | `GET /events?series_ticker=<S>&status=open` (plus `/markets?event_ticker=` for new events) for about 30 watched recurring series | official | none | free | shared Kalshi pacer | as above | open events, market lists with `rules_primary`/`secondary` (hashed), `close_time`, `can_close_early`, top-of-book (`yes_bid`/`yes_ask` and sizes are in every listing row) | continuous | daily per family, plus the per-family streams below | §4 universal market-side evidence: lifecycle, rules-hash changes and early closes for every family named in this table | events: A; rules and lifecycle changes: **C** | rules and lifecycle: **C**; listing: A | about 0.3–0.6 MB (30 families × 10–20 KB) | about 30 (plus listings for new events) | READY TO IMPLEMENT (Wave 1) | none |
| WEATHER | Kalshi multi-city highs/lows (KXHIGH*, KXLOWT*, 121 daily weather series in the catalog; settlement sources in the metadata are mostly "The Weather Company", 22 "National Weather Service") | same endpoints, per city event | official | none | free | shared pacer | as above. Lane G verifies each family's rules and station | brackets, rules, station, listing top-of-book, books, status, close, settlement | daily events | Lane G design: D-3…close horizons, deduplicated. Placeholder budget here: listings at 6 horizons, books at 3 horizons | Multi-City Weather v1 (§8–§10): the NWS forecast vs market, per city | as for KXHIGHNY | depth: **C**; top-of-book: B; outcome: A | about 1.3 MB for 10 cities (est.: 60 listings × 17 KB plus 180 books × 1.5 KB) | about 240 (worst about 720 with retries) | READY TO IMPLEMENT (design: Lane G, `docs/research/MULTI_CITY_WEATHER_V1.md`) | the timer, when proposed |
| ECONOMICS | Kalshi macro release families: KXCPI, KXCPIYOY, KXCPICORE, KXCPICOREYOY, KXPAYROLLS, KXU3, KXJOBLESSCLAIMS (weekly), KXPCECORE, KXGDP, KXFED, KXFEDDECISION, KXEIACRUDEW (weekly) | same endpoints | official | none | free | shared pacer | as above; each family's rules must be read (metadata anomalies, §0) | listing (all strikes, top-of-book), books for every strike (11–14 markets measured), rules hash, close time, settlement value | monthly or weekly events; each closes 1–5 min before its release (§0) | per release event: listings at T-24h, T-6h, T-60m, T-15m and close−1 min; books for every strike at T-60m and close−1 min; settlement after the release. Post-release T+1m/T+5m/T+30m/T+2h **only for still-open related families** (for example KXFED after CPI or payrolls) | §13–§16: market-implied distribution vs the consensus/nowcast before official releases; the release-surprise study | events and settled values: A | pre-release depth and top-of-book at an instant: **C** (candlesticks give B for top-of-book) | about 0.18 MB per event × about 19 events a month ≈ **0.11 MB/day** on average | about 21 a day on average; **peak day about 165** (CPI family plus claims) | READY TO IMPLEMENT (Wave 3) | the timer, when proposed |
| CRYPTO | Kalshi hourly crypto: KXBTCD, KXETHD (above/below), KXBTC, KXETH (range), KXBTC15M (15 min); settlement source "CF Benchmarks" (metadata) | same endpoints | official | none | free | shared pacer | as above | ladder listing (188 markets, 351 KB measured for one hourly BTC event), near-the-money books | new events hourly; 15-min series | **sampled**: 6 hourly events a day per asset, each with the listing at T-5m plus books for the 5 strikes nearest the money. Never every hour's full ladder (§3.4) | §17–§19: the hourly ladder vs exchange spot and dispersion | settled markets and candlesticks: A/B | ladder depth and cross-venue state at an instant: **C** | about 4.3 MB raw (about 0.5 MB compressed, est. from JSON ratios) | about 72 | READY TO IMPLEMENT (Kalshi side, Wave 4). The exchange side needs a terms review (§1.5) | the timer; a compression decision |
| SPORTS | Kalshi game markets: KXNFLGAME, KXNCAAFGAME (115 open NCAAF game events seen) | same endpoints | official | none | free | shared pacer | as above | game market listing and books, rules (tie/OT/postponement), settlement | per game | at the Odds API targets (T-24h, T-6h, T-60m, ADR 0029), reusing the event-relationship contract of ADR 0032 (RELATED_NOT_EQUIVALENT, never forced) | #9/ADR 0033: the prediction-market price vs the sportsbook consensus *at the same instant*. The Odds series is already being collected | settled markets: A | book at the Odds horizons: **C**, and NFL weeks are season-bound | NFL about 0.06 MB/day; NCAAF about 0.3 MB/day (est.) | NFL about 10/day on average (Sunday about 50); NCAAF about 80/day on average (Saturday about 400) | READY TO IMPLEMENT (recommended next after Multi-City Weather v1, §6) | the timer |
| FINANCIALS / COMMODITIES / ENERGY | Kalshi index, commodity and gas families: KXINX/KXINXU, KXNASDAQ100(U), KXWTI, KXNGASW, KXAAAGASW, KXTSAW | same endpoints | official | none | free | shared pacer | as above; their settlement sources are third-party ("For example, Google Finance", ICE, Pyth, AAA, TSA) | market data only | daily, hourly or weekly | none until a hypothesis names one | **DO NOT COLLECT YET**: no named hypothesis. The underlying settlement data is licensed or not reviewed | market: A/B | depth: C (accepted loss) | 0 | 0 | NEEDS SPECIFIC EXPERIMENT | name a hypothesis first |
| POLITICS / ELECTIONS | Kalshi election families (KXHOUSERACE 350, KXVOTEGENERAL 1,036, KXMIDTERMMOV 603 open events seen; midterms 2026-11-03) | same endpoints | official | none | free | shared pacer | as above | market data only; labels from Kalshi settlement and certified results | one-off | if chosen: a daily listing for the top-N most liquid races only | a one-shot, correlated event set: weak for learning a *repeatable* edge. The directive allows "market-side evidence for selected markets" | settled: A; candlesticks: B | pre-election depth: **C**, and it expires 2026-11-03 | about 0.5 MB (est., 25 races) | about 25 | NEEDS SPECIFIC EXPERIMENT (owner choice before 2026-11-03) | decide whether elections are a planned domain |
| CULTURE / LONG-TAIL | Kalshi entertainment and mentions families (Luminate, Spotify, Billboard, Netflix settlement sources) | covered by the series catalog row | official | none | free | shared pacer | as above | catalog only | varies | catalog only (weekly) | DISCOVERY_ONLY (§29–§30) | as the catalog | as the catalog | inside the catalog row | 0 extra | NOT CURRENTLY WORTH COLLECTING (beyond the catalog) | none |
| ALL | Kalshi candlesticks and trades (backfill) | `GET /series/{s}/markets/{t}/candlesticks` (period 1, 60 or 1440; `yes_bid`/`yes_ask`/`price` OHLC, volume, OI; `security: []`), `GET /markets/trades` (cursor, ≤1000 per page) | official | none | free | shared pacer | as above | top-of-book and trade path after the fact | historical | on demand, per closed capture day, labelled HISTORICAL_BACKFILL | P1-8 (does top-of-book survive after the re-check?); later-price studies for rejected brackets | documented as historical after the cutoff | B (top-of-book only, never depth) | measure on the first read (unknown) | about 1–10 per study day | READY TO IMPLEMENT (manual backfill; one stored read closes P1-8) | none |
| ALL | Kalshi WebSocket | `wss` market-data channels | official | **account API key and signature** ("use the same API key authentication and signing path", docs websockets, read 2026-09-24) | free | per tier | an account-bound credential, not a read-only data key | — | push | none | STREAM mode would need a trading-account credential, which the registry forbids | — | — | 0 | 0 | NOT CURRENTLY WORTH COLLECTING (not authorized: account credential) | none |
| SPORTS | Polymarket US public gateway | `gateway.polymarket.us` `/v1/events` (`tagSlug=nfl`, filtered), `/v1/markets/{slug}/book` | official | none | free | 20 req/s per IP (registry, docs read 2026-09-23) | **not cleared**: the terms review did not clear unattended collection, and bulk download is prohibited (ADR 0032 on PR #84) | NFL moneyline books at the Odds horizons | per game | ADR 0032 targets | #9 cross-venue relationship | no documented book history | books: **C** | about 1.5 MB (typical scans) to 14.5 MB (worst; ADR 0032) | about 50 per run cap; about 7/day on average | **NEEDS TERMS REVIEW** (implemented, disabled; owner access decision) | the owner decides access (ADR 0032) |
| SPORTS | Novig exchange data | `data.novig.com/reporting/trade-data` daily CSVs and `index.json` | official | none | free | none stated | no licence stated; research only (registry) | end-of-day trades and markets | daily, after midnight ET | on demand | exchange trade prices vs sportsbook consensus (research) | every date listed in the index; retention not promised | A while hosted | about 0.1 MB (est.) | 2 | NEEDS SPECIFIC EXPERIMENT (fetch on demand, P1-6) | none |

### 1.2 Weather (official NWS/NOAA and archives)

| domain | source | exact endpoint/feed class | official/third-party | auth | cost | rate/quota | terms state | data collected | publication/update cadence | desired capture cadence | why it matters | historical archive availability | point-in-time irrecoverability | storage/day estimate | requests/day estimate | implementation status | owner action needed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WEATHER | NWS PFMOKX | `api.weather.gov/products/types/PFM/locations/OKX` plus `/products/{id}` | official | User-Agent ("A User Agent is required", weather.gov services-web-api, read 2026-09-24) | free ("free to use for any purpose") | "not public information, but allows a generous amount"; retry after about 5 s | public domain | full product text | about 2 a day | the 17:45 ET capture (deployed) | EXP-001 input | IEM AFOS archive (`iem_afos_pfmokx`) | B (the archive has the issuance; receipt time is ours) | about 75 KB | about 3 | **ACTIVE NOW** | none |
| WEATHER | NWS PFM for other WFOs | same, per city's office | official | User-Agent | free | as above | public domain | per-city daytime max forecast | about 2 a day per office | each new issuance (deduplicated by product id), within the Lane G horizons | Multi-City Weather v1 | IEM AFOS archive | B | about 75 KB per office → about 0.75 MB for 10 | about 30 | READY TO IMPLEMENT (Lane G) | the timer |
| WEATHER | NWS gridpoint forecasts | `/points/{lat},{lon}` → `/gridpoints/{wfo}/{x},{y}/forecast`, `/forecast/hourly`, `/forecastGridData` ("raw forecast data over the next seven days") | official | User-Agent | free | as above | public domain | issuance `updateTime`, periods, hourly temperature grid | several updates a day | every 6 h plus the Lane G horizons, stored only when `updateTime` changes | Multi-City Weather v1; P0-cond for NYC (`LEARNING_HISTORY_COVERAGE.md` §4b) | **the API serves only the current forecast.** NDFD archives exist elsewhere, not evaluated | **C** (the vintage as served) | 0.5–3 MB for 10 cities (est.; gridData is the large one) | about 40–80 | READY TO IMPLEMENT (Lane G) | the timer |
| WEATHER | NWS station observations | `/stations/{id}/observations`, `/observations/latest` | official | User-Agent | free | as above | public domain | METAR-derived observations, QC flags | hourly or more often | every 6 h, the window since the last read | intraday path; settlement cross-check | IEM ASOS archive (not evaluated here). How long the API keeps history is **not documented** on the page read | B | about 0.3–0.7 MB (est.) | about 40 | READY TO IMPLEMENT (Lane G) | the timer |
| WEATHER | NWS CLI per settlement station | `/products/types/CLI/locations/{loc}` plus the product | official | User-Agent | free | as above | public domain | daily climate report (max/min), corrections | about 1–3 issuances a day | twice a day (every issuance kept) | the independent settlement check. KXHIGHNY now names The Weather Company, which is BLOCKED | IEM AFOS (A) | A (issuance history via IEM); first-seen time: C | about 0.2 MB for 10 | about 30 | READY TO IMPLEMENT. For NYC: `nws_cli_central_park` is ACTIVE in the registry but **not scheduled** (U-1) | the timer |
| WEATHER | IEM AFOS archive | `mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py` | third-party (academic, re-serves NWS) | none | free | registry: about 1 req/s, polite | "in the public domain and may be used freely" (IEM disclaimer, read 2026-09-24); attribution appreciated | CLI/PFM text history | archive | on demand (HISTORICAL_BACKFILL) | backfill and U-1 labels for rejected-only days | yes (back to about 2008 for CLI) | A | on demand | on demand | READY TO IMPLEMENT (manual backfill) | none |
| WEATHER | The Weather Company (`weather.com/kalshi`) | page | third-party | — | — | — | **BLOCKED**: its terms forbid automated access without written permission (registry, reviewed 2026-09-22) | — | — | none | named in KXHIGHNY rules since 2026-08-14 | — | — | 0 | 0 | NEEDS TERMS REVIEW (written permission only; stays BLOCKED) | only the owner could seek permission |
| WEATHER | NWS alerts | `/alerts` | official | User-Agent | free | as above | public domain | alerts | event | none | no named family: **DO NOT COLLECT YET** | the API keeps 7 days ("alerts issued over the past seven days") | C (accepted) | 0 | 0 | NOT CURRENTLY WORTH COLLECTING | none |

### 1.3 Sports (odds and outcomes)

The Odds API credit math reuses ADR 0029: one `/odds` call costs `markets × regions` credits
(guide re-read 2026-09-24: "number of markets specified × number of regions specified").
`/events` and `/sports` are free, and an empty response is free.
- **One sport's cost:** credits/month = G × O × M × R, where G is the distinct kickoff groups a
  month after 20-minute coalescing, O the offsets, M the markets and R the regions.
- **NFL:** expected **222 (Oct), 252 (Nov), 270 (Dec)** credits, with worst-case proofs of 225,
  255 and 273 (ADR 0029 addendum).
- **Headroom under the 450 ceiling:** about **225 (Oct), 195 (Nov), 177 (Dec)**. The provider cap
  is 500, but 450 is the owner's ceiling.
- **Group counts for other sports are estimates.** They are enumerable at zero credit cost from
  `/events` once the owner approves another sport.

| domain | source | exact endpoint/feed class | official/third-party | auth | cost | rate/quota | terms state | data collected | publication/update cadence | desired capture cadence | why it matters | historical archive availability | point-in-time irrecoverability | storage/day estimate | requests/day estimate | implementation status | owner action needed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPORTS | The Odds API, NFL pilot | `/v4/sports/americanfootball_nfl/odds` (h2h, spreads, totals; us), `/events` (free) | third-party aggregator | read-only key `EDGE_LAB_ODDS_API_KEY` (installed) | free tier (500 credits/month; ceiling 450) | budget proof (ADR 0029) | store and derive; no redistribution; historical odds on paid plans only (registry) | offered odds per book, `last_update`, quota headers | continuous | T-24h, T-6h, T-60m (deployed) | #9, ADR 0033 consensus benchmark | **historical odds need a paid plan** | **C** | about 0.2 MB (est.) | about 7 (about 3 paid, 4 free) | **ACTIVE NOW** | none |
| SPORTS | The Odds API, NCAAF (`americanfootball_ncaaf`, "In-season", sports-apis page, read 2026-09-24) | same | third-party | same key | inside 450 only if reduced | G ≈ 35–50 groups/month (est.). The full 3×3 at 3 offsets costs about 315–450 a month: **does not fit**. h2h only at T-60m costs about 35–50 a month: **fits** | same | h2h at T-60m | in season | T-60m, h2h only | Kalshi KXNCAAFGAME has the deepest sports list seen (115 open events) | paid only | **C** | about 0.1 MB | about 2 | NEEDS SPECIFIC EXPERIMENT (and owner approval for "more sports"). Needs a joint multi-sport budget proof in `odds_schedule` | approve the sport and the reduced markets |
| SPORTS | The Odds API, NBA (`basketball_nba`), NHL (`icehockey_nhl`) | same | third-party | same key | as above | NBA G ≈ 100–150 groups/month (est.). The full 3×3 at 3 offsets costs about 900–1,350 a month: **does not fit**. h2h at T-60m costs about 100–150 a month: fits alone, but not together with NCAAF in December (headroom 177) | same | h2h at T-60m | in season (the NBA starts late October; date not verified) | T-60m, h2h only | Kalshi KXNBAGAME/KXNHLGAME exist | paid only | **C** | about 0.1–0.2 MB | about 4–5 | NEEDS SPECIFIC EXPERIMENT. **At most one extra sport fits the free tier**, h2h only, T-60m only | choose at most one |
| SPORTS | The Odds API: MLB, NCAAB, props, `/scores` | same | third-party | same key | MLB and NCAAB exceed the budget; `/scores` costs 1 or 2 credits ("With daysFrom … 2") | — | same | — | — | none | outcomes are public elsewhere; props are excluded by the owner | — | — | 0 | 0 | NOT CURRENTLY WORTH COLLECTING (a paid tier would be PAID/ROI BLOCKED under #7) | none |
| SPORTS | Official injury and availability reports; outdoor-game weather | league pages (not reviewed); NWS gridpoints for stadium points | official (league: terms unknown) | none | free | — | league terms **not reviewed** | availability status; forecast at kickoff | weekly or per game | not before a sports hypothesis names them | §11–§12 list them as "approved" data | league archives unknown; weather forecast vintages: C | C | small | small | NEEDS SPECIFIC EXPERIMENT (injury: NEEDS TERMS REVIEW) | none now |

### 1.4 Macro / economics (official)

| domain | source | exact endpoint/feed class | official/third-party | auth | cost | rate/quota | terms state | data collected | publication/update cadence | desired capture cadence | why it matters | historical archive availability | point-in-time irrecoverability | storage/day estimate | requests/day estimate | implementation status | owner action needed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ECONOMICS | BLS Public Data API v1 | `api.bls.gov/publicAPI/v1/timeseries/data/` | official | **none** (v1 "does not require registration") | free | **25 queries/day, 25 series/query, 10 years, 50 requests per 10 s** (bls.gov/developers/api_faqs.htm, read 2026-09-24) | US government; open | CPI, core CPI, payrolls, U-3, JOLTS series values as served | at the release (08:30 ET) | release-driven: T+2m, T+10m, T+60m reads on release days (well under 25/day) | the settlement value and first print for KXCPI*/KXPAYROLLS/KXU3; the prior value as known | ALFRED holds vintages (key); the BLS API serves current values | first-print receipt time and API latency: **C**; value: B | about 20 KB | about 3–6 on release days | READY TO IMPLEMENT (Wave 3) | none |
| ECONOMICS | BLS API v2 | `…/v2/…` with `registrationkey` | official | free registration key | free | 500 queries/day, 50 series, 20 years, 50 per 10 s (same page) | open | as v1, more series | as v1 | only if v1's 25/day binds | headroom only | as v1 | as v1 | as v1 | as v1 | NEEDS FREE OWNER KEY (**optional**: v1 suffices for Wave 3). Secret `EDGE_LAB_BLS_API_KEY` in `/etc/market-edge-lab/secrets.env`. v2 GET key transport not verified (the client is GET-only) | register only if needed |
| ECONOMICS | BLS release calendar | `www.bls.gov/schedule/news_release/bls.ics` (read 2026-09-24; CPI and Employment Situation "08:30 AM") | official | none | free | as for the site | open | scheduled release dates and times | updated ahead of time | daily; store only on change (hash) | the calendar primitive (§71): scheduled time for every BLS family | older calendars are not archived by BLS (not verified) | the scheduled-time history: **C** (a moved date is visible only if seen) | about 0.1 MB when changed, else a retrieval row | 1 | READY TO IMPLEMENT (Wave 1/3). The BLS site's handling of automated clients is untested: one bounded smoke read first | none |
| ECONOMICS | BEA API | `apps.bea.gov/api/data?UserID=…` (NIPA: GDP, PCE, core PCE) | official | **36-character UserID** ("users must obtain a unique 36-character UserID by registering", BEA API user guide PDF, read 2026-09-24) | free | **100 requests/min, 100 MB/min, 30 errors/min** (same guide) | registration terms apply | GDP, PCE, core PCE values | at the release, 08:30 ET | release-driven, as for BLS | KXGDP, KXPCECORE settlement values and first print | ALFRED vintages | first print and receipt: **C**; value: B | about 20 KB | about 2–4 on release days | **NEEDS FREE OWNER KEY**: free; about 5 requests per release, about 40 a month, under 1 MB a month. Secret `EDGE_LAB_BEA_USER_ID` in `/etc/market-edge-lab/secrets.env` (query-param transport) | register and install the UserID |
| ECONOMICS | BEA release schedule (machine-readable) | `apps.bea.gov/API/signup/release_dates.json` and an ICS (bea.gov/news/schedule, read 2026-09-24) | official | none stated for the JSON (verify on the first read) | free | as the API | open | release dates and times | ahead of time | daily; store on change | calendar primitive | not archived (not verified) | schedule-change history: **C** | about 50 KB when changed | 1 | READY TO IMPLEMENT | none |
| ECONOMICS | FRED / ALFRED API | `api.stlouisfed.org/fred/series/observations?realtime_start=&realtime_end=` | official (St. Louis Fed; some series are third-party owned) | **API key** ("All web service requests require an API key") | free (not stated as a price on the page read; the key is issued with a free account) | **not stated** on the pages read (the terms reserve the right to limit transactions) | terms: attribution notice required; third-party series need the owner's permission to redistribute; no FRED marks (fred terms_of_use, read 2026-09-24) | vintages (`realtime_start`/`realtime_end`) for every macro series | ALFRED vintages are **day-granular** | weekly vintage refresh for about 30 series, plus a release-day read | §13 "vintages are critical": the prior value as known and the revision history for every macro family | **yes: ALFRED is the vintage archive** | B (day-level vintages; not the minute of publication) | about 0.2 MB | about 10 | **NEEDS FREE OWNER KEY**: free; about 300 requests a month; about 5 MB a month. Secret `EDGE_LAB_FRED_API_KEY` in `/etc/market-edge-lab/secrets.env` (the `api_key` query param) | create the account and key; install it |
| ECONOMICS | Census Data API / economic indicators (retail sales, housing starts) | `api.census.gov/data/timeseries/eits/...` | official | **key required** ("An API key must be used with all data queries", census Query_Limits, read 2026-09-24) | free | not stated on the page read | open | advance retail sales, housing starts | release (08:30 or 10:00 ET) | release-driven | KXUSRETAIL, KXHOUSINGSTART (**rules must confirm Census**: metadata says BLS, §0) | ALFRED vintages | B/C as for BEA | about 20 KB | about 2 on release days | NEEDS FREE OWNER KEY, but only after the rules confirm the source. Secret `EDGE_LAB_CENSUS_API_KEY` | later |
| ECONOMICS | Federal Reserve Board RSS | `federalreserve.gov/feeds/press_monetary.xml`, `/feeds/prates.xml`, `/feeds/h15.xml` (feeds page, read 2026-09-24) | official | none | free | not stated; poll with a conditional GET | open | FOMC statements, policy-rate announcements, H.15 | FOMC about 8 a year at 14:00 ET; H.15 daily | every 15 min on FOMC days around 14:00; hourly otherwise; conditional GET; store changed bytes only | KXFED, KXFEDDECISION settlement and release timing | press releases stay online | first-seen time: **C**; content: A | under 0.1 MB (changed-only) | about 72 (mostly 304 Not Modified) | READY TO IMPLEMENT (Wave 3) | none |
| ECONOMICS | Fed Data Download Program | `federalreserve.gov/datadownload/` | official | not stated | not stated | — | **being retired**: "the eventual retirement of the DDP" (read 2026-09-24); points to FRED | — | — | none | superseded by FRED | — | — | 0 | 0 | NOT CURRENTLY WORTH COLLECTING | none |
| ECONOMICS | DOL weekly UI claims | `oui.doleta.gov/unemploy/claims.asp` (HTML, spreadsheet or XML output) | official | none stated | free | not stated | open | initial and continuing claims | Thursday 08:30 ET | release-driven Thursday reads | KXJOBLESSCLAIMS ("Department of Labor" in the metadata) | the full history is served | first print: B/C; value: A | about 20 KB a week | about 1 a week | READY TO IMPLEMENT (Wave 3). Confirm that the XML output is the same series the rules name | none |
| ECONOMICS | Treasury FiscalData | `api.fiscaldata.treasury.gov/services/api/fiscal_service/...` | official | **none** ("does not require a user account or registration for a token", read 2026-09-24) | free | not stated | open | DTS, debt, auctions and more | daily or monthly | none yet | no named Kalshi family depends on it (Treasury-sourced families are yields, which settle elsewhere): **DO NOT COLLECT YET** | the full history is served | A | 0 | 0 | NEEDS SPECIFIC EXPERIMENT | none |

### 1.5 Crypto (exchange market data)

| domain | source | exact endpoint/feed class | official/third-party | auth | cost | rate/quota | terms state | data collected | publication/update cadence | desired capture cadence | why it matters | historical archive availability | point-in-time irrecoverability | storage/day estimate | requests/day estimate | implementation status | owner action needed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CRYPTO | Coinbase Exchange public REST | `api.exchange.coinbase.com/products/{BTC-USD,ETH-USD}/book?level=2`, `/ticker`, `/candles`, `/trades` (`security: []`; book "NOT paginated") | official (exchange) | none | free | **10 req/s per IP, bursts to 15** (docs.cdp.coinbase.com rate limits, read 2026-09-24). Level-3 polling "can cause your access to be limited or blocked" | **not verified**: `coinbase.com/legal/market_data` returned **HTTP 403**. A secondary search summary says redistribution outside your organization is prohibited. Internal research use is unconfirmed | L2 book (bounded depth), 1-min candles, ticker | continuous | 1-min candles backfilled in 5 calls a day; an L2 top-50 snapshot at the sampled Kalshi hours (T-5m, T-0) | the BTC/ETH spot and dispersion vs the Kalshi hourly ladders (whose settlement is CF Benchmarks, not Coinbase) | candles and trades are retrievable later (paged) | depth and dispersion at an instant: **C**; candles: A/B | about 0.3–0.5 MB | about 30 | **NEEDS TERMS REVIEW** | the owner reads and accepts the Market Data Terms, or declines |
| CRYPTO | Kraken public REST | `api.kraken.com/0/public/Depth`, `Ticker`, `OHLC`, `Trades` | official (exchange) | none (public endpoints are "rate limited by IP address") | free | about **1 req/s** stays within the limits (support article, read 2026-09-24) | **not cleared**: the global terms restrict bots and "data extraction methods" and require consent for commercial exploitation (kraken.com/legal/global-terms, read 2026-09-24). The API terms URL returned 404 | as Coinbase | continuous | as Coinbase | a second venue for dispersion | OHLC is limited (not verified) | as Coinbase | about 0.3 MB | about 30 | **NEEDS TERMS REVIEW** (likely prior written permission) | the owner decides |
| CRYPTO | CF Benchmarks BRTI / ETH RTI (the Kalshi crypto settlement source) | cfbenchmarks.com | official index (licensed) | licence | **licensed** ("If you require access to real time or historic data … please contact", read 2026-09-24) | — | licensed | index values | 1 s | none | the settlement label comes from Kalshi's settled result (A), not the index | licensed | — | 0 | 0 | **PAID/ROI BLOCKED** (#7) | none |

### 1.6 Energy, business, politics, culture, news

| domain | source | exact endpoint/feed class | official/third-party | auth | cost | rate/quota | terms state | data collected | publication/update cadence | desired capture cadence | why it matters | historical archive availability | point-in-time irrecoverability | storage/day estimate | requests/day estimate | implementation status | owner action needed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ENERGY | EIA API v2 | `api.eia.gov/v2/petroleum/...` (WPSR stocks), `/natural-gas/stor/...`, `/steo/...`, `/electricity/...` | official | **API key, required in the URL** ("must always appear in the URL", eia.gov/opendata/documentation.php, read 2026-09-24) | free ("EIA data is provided free of charge") | throttling per second and per hour, values **not published** (exceeding "temporarily suspended"); 5,000 rows per JSON response | EIA terms: attribution to "EIA"; no false representation (terms-of-service.php, read 2026-09-24) | crude and gas stocks, storage, STEO | WPSR Wednesday "after 10:30 a.m." ET (holiday shifts); natural gas storage Thursday (time not verified); STEO monthly | release-driven reads after the release | KXEIACRUDEW (rules must be read), KXNGASW ("Energy Information Administration") | the API serves history; revisions are not versioned by EIA (not verified) | first print and receipt: **C**; value: B | about 0.1 MB | about 3 on average (about 15 on release days) | **NEEDS FREE OWNER KEY**: free; about 60 requests a month; about 3 MB a month. Secret `EDGE_LAB_EIA_API_KEY` in `/etc/market-edge-lab/secrets.env` (query param) | register and install the key (Wave 5) |
| ENERGY | EIA WPSR schedule page | `eia.gov/petroleum/supply/weekly/schedule.php` | official | none | free | — | open | the release-date table (holiday delays) | yearly | weekly, on change | calendar primitive | — | C (the schedule as seen) | small | 1 a week | READY TO IMPLEMENT (with the calendar) | none |
| ENERGY | Futures (NYMEX/ICE) and AAA gas prices | exchange feeds; the AAA page | third-party | licence (futures); AAA terms not reviewed | paid (futures) | — | not reviewed | — | — | none | KXWTI (ICE), KXAAAGASW (AAA) | licensed | — | 0 | 0 | futures: **PAID/ROI BLOCKED**; AAA: **NEEDS TERMS REVIEW** | none |
| BUSINESS | SEC EDGAR APIs | `data.sec.gov/submissions/CIK##########.json`, `/api/xbrl/companyfacts/…`, frames; nightly ZIPs | official | **none** ("do not require any authentication or API keys"); a declared User-Agent is required | free | **10 requests/s** ("Current max request rate: 10 requests/second", sec.gov accessing-edgar-data, read 2026-09-24) | fair access; "does not allow botnets or automated tools to crawl the site"; download only what you need | filings, form, accession, acceptance time, XBRL facts | submissions under 1 s of processing delay, XBRL under 1 min | per watched CIK: a conditional read every 10–15 min in the market's window | No Kalshi family has been named that settles on a filing; the "Companies" and "Mentions" families mostly settle on transcripts or third parties. **#88 names a public-market family: SEC filing reaction. See the PUBLIC MARKETS row in §1.7, which supersedes this row for EDGAR collection** | full filing history (A); acceptance time is in the filing | A (the acceptance timestamp is authoritative) | see §1.7 | see §1.7 | for Kalshi-side use: NEEDS SPECIFIC EXPERIMENT. For #88: READY TO IMPLEMENT (§1.7) | see §1.7 |
| BUSINESS | Equity and ETF benchmarks (KXINX "For example, Google Finance") | vendors | third-party | licence | paid (real time) | — | licensing review | — | — | none | index families | licensed | — | 0 | 0 | PAID/ROI BLOCKED (#7) | none |
| POLITICS | OpenFEC API | `api.open.fec.gov/v1/…` | official | **api.data.gov key** (search summary: "Signing up for an OpenFEC API key will enable you to place up to 1,000 calls an hour"; developers page not readable) | free | api.data.gov default **1,000/hour**; DEMO_KEY 30/hour and 50/day (api.data.gov developer manual, read 2026-09-24) | public; **avoid individual-donor PII** (directive §26) | candidate and committee aggregates only | FEC filing deadlines | none before a family is chosen | KXHOUSERACE etc. only if elections are chosen (§1.1) | full history | A | 0 now | 0 now | NEEDS FREE OWNER KEY **and** NEEDS SPECIFIC EXPERIMENT. Secret `EDGE_LAB_API_DATA_GOV_KEY` (one api.data.gov key *likely* serves both FEC and Congress.gov; **not verified**) | only if the owner picks elections |
| POLITICS | Congress.gov API | `api.congress.gov/v3/…` | official | **key required** ("An API key is required for access"), via api.data.gov | free | **5,000 requests/hour** (github LibraryOfCongress/api.congress.gov, read 2026-09-24) | public | bills, actions, votes | continuous | none yet | Kalshi bill-passage families are one-off: **DO NOT COLLECT YET** | full history | A | 0 | 0 | NEEDS FREE OWNER KEY + NEEDS SPECIFIC EXPERIMENT | later |
| POLITICS | Polling | various | third-party | varies | varies | — | methodology and terms decision required (§28) | — | — | none | — | — | — | 0 | 0 | NOT CURRENTLY WORTH COLLECTING | none |
| CULTURE | Luminate, Spotify, Billboard, Netflix, YouTube (the settlement sources of entertainment families) | pages or charts | third-party | varies | varies | — | not reviewed; "No celebrity or social scrapers" (§29) | — | — | none | DISCOVERY_ONLY | — | — | 0 | 0 | NOT CURRENTLY WORTH COLLECTING | none |
| NEWS / SOCIAL | GDELT, news APIs, social media | various | third-party | varies | free to paid | — | `docs/NEWS_WEB_INGESTION.md` | — | — | none | §31: **not tier 1**. It needs a named experiment, clear terms, trustworthy timestamps and measurable value. None is named. Noise, prompt-injection surface and licensing cost outweigh the value today | — | C (accepted) | 0 | 0 | NOT CURRENTLY WORTH COLLECTING | none |

### 1.7 PUBLIC MARKETS: equities/ETFs, listed options, futures (issue #88, first-class domain)

Owner idea #88 (2026-09-24) is included in #86 as its own domain. It authorizes no live order,
paper order, paid data, brokerage funding, derivatives permission, margin, short selling or
Gate 8+.
- **Paper trading** is Gate 8 (PAPER/SHADOW), and is **not** authorized.
- **Data only.** Every row below is data acquisition only. Research-grade and execution-grade are
  kept apart: free feeds here are **research-grade** (IEX single-venue, indicative options,
  delayed). **No execution-grade conclusion may rest on them.**
- **No quote-page scraping** (Cboe, CME, exchange or vendor quote pages).

Two security facts shape every keyed broker row:
- **Header transport.** Alpaca authenticates with `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY`
  headers, and Tradier with an OAuth bearer token. `edge_lab.http` refuses credential headers, and
  the registry allows only `credential_transport="query_param"`.
- **Order scope.** A broker paper-account key can also place (paper) orders. The registry's only
  credential kind is `READ_ONLY_DATA_FEED`, and `tests/invariants/test_no_execution_paths.py`
  forbids order paths.

So a broker market-data key needs **an owner decision plus a security ADR** before any code uses
it. That ADR covers the header transport, an order-scoped key used only against data hosts, and
separate secrets. Owner-installed only, never handled by agents.

| domain | source | exact endpoint/feed class | official/third-party | auth | cost | rate/quota | terms state | data collected | publication/update cadence | desired capture cadence | why it matters | historical archive availability | point-in-time irrecoverability | storage/day estimate | requests/day estimate | implementation status | owner action needed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PUBLIC MARKETS (equities) | SEC EDGAR: filing events for the bounded universe | `data.sec.gov/submissions/CIK##########.json` (per watched CIK), filing index and primary document; the EDGAR "latest filings" feed as the change signal | official | none; declared User-Agent | free | 10 req/s (fair access) | fair-access policy; no crawling; "download only what you need" | form, items, accession, `acceptanceDateTime`, primary document bytes and hash, XBRL facts | submissions update in under 1 s of processing | market hours: poll the change signal every 1–2 min; per new filing in the universe, index plus primary document once | #88 family 1 (**SEC filing reaction**) and 2 (earnings/guidance 8-K). The universe: SPY/QQQ/IWM/DIA constituents' mega-caps (about 20–30 CIKs) | full filing history (A) | content: A; **our receipt latency: C** | about 1–4 MB (changed-only feed plus about 5 filings × about 200–600 KB of exact bytes; est.) | about 200–400 (mostly unchanged) + about 15 | READY TO IMPLEMENT (keyless). This names the family SEC EDGAR lacked in §1.6 | name the CIK universe (bounded) |
| PUBLIC MARKETS (equities) | Alpaca Market Data API, Basic (free) | `data.alpaca.markets` stocks bars, quotes, trades, snapshots; feed `iex` | third-party broker/data vendor | **account keys in headers** (`APCA-API-KEY-ID`, `APCA-API-SECRET-KEY`); a paper-only account "with your email" | free (Basic); Algo Trader Plus $99/month (SIP + OPRA) | **200 calls/min** (Basic) | "IEX" only in real time; SIP history available except the "latest 15 minutes" (docs.alpaca.markets about-market-data-api, read 2026-09-24). Storage and redistribution terms: the Alpaca T&C PDF was **not read**; a subscriber-agreement summary suggests no redistribution | IEX trades/quotes/bars; SIP historical bars delayed | real time (IEX) | none prospectively for bars and quotes: **they are fetchable historically since 2016**, so collect on demand for studies | #88 families 3–4 (macro-release and opening-gap reactions in SPY/QQQ/IWM/DIA/sector ETFs) | **since 2016** (bars, quotes, trades) | A/B (history via the API); IEX-only is not NBBO | on demand | on demand (≤200/min) | NEEDS FREE OWNER KEY **plus a security ADR** (header transport, order-scoped paper key). Secrets `EDGE_LAB_ALPACA_DATA_KEY_ID` / `EDGE_LAB_ALPACA_DATA_SECRET` | the owner creates a paper-only account (no funding) only after the ADR |
| PUBLIC MARKETS (options) | Alpaca options, Indicative feed (free) | `data.alpaca.markets` options chain/snapshots (IV and Greeks, vendor-computed), bars, trades | third-party | as above | free (indicative); OPRA needs a subscription | as above | "Indicative Pricing Feed is a free derivative of the original OPRA feed … not actual OPRA quotes"; trades delayed 15 min; history "since February 2024" (historical-option-data doc, read 2026-09-24) | per contract: OCC symbol, strike, expiry, type, bid/ask (indicative), IV and Greeks (**vendor-derived; provenance recorded**), underlying quote | real time (indicative) | bounded snapshots: SPY and QQQ, the nearest 3 expiries, strikes within ±10%. Taken at the prior close and at T-15m / T+30m around FOMC (14:00 ET) and CPI/NFP (measured from the 09:30 open), plus a daily 15:45 ET snapshot | #88 options angle: implied vs realized move around scheduled macro events; cross-check against the Kalshi macro families (§1.1) | bars and trades since Feb 2024; **instantaneous chain quotes, IV and Greeks: not documented as historical** | chain state at an instant: **C** | about 0.5 MB (est.: about 400 contracts × about 300 B × about 4 snapshots) | about 10–20 (paged chains) | NEEDS FREE OWNER KEY + security ADR (as above). Research-grade: INDICATIVE, never OPRA or execution-grade | as above |
| PUBLIC MARKETS (equities, options) | Tradier: sandbox and brokerage API | `api.tradier.com` / `sandbox.tradier.com` markets quotes, options chains (`greeks=true`, ORATS), timesales, history, calendar | third-party broker | OAuth bearer token (header); sandbox token from a developer account; production needs a brokerage account | sandbox free; production data is tied to a brokerage account (funding requirement **not verified**) | **production 120 req/min, sandbox 60 req/min** (docs.tradier.com rate-limiting, read 2026-09-24) | sandbox equities and options "Delayed" (15 min); **Greeks "Not Available" in sandbox**, "Hourly" in production (docs.tradier.com market-data, read 2026-09-24). Terms not read | quotes, chains, timesales, the market calendar | real time (production) or delayed 15 min (sandbox) | none until the route is chosen | a second options route with ORATS Greeks provenance; the market calendar | history endpoints (daily/intraday; depth of history not verified) | chain at an instant: C | — | — | NEEDS FREE OWNER KEY (sandbox) + security ADR; the production route is **PAID/ROI BLOCKED**-adjacent (a brokerage account) | none now (research Alpaca first, §7) |
| PUBLIC MARKETS (equities) | IEX HIST (DEEP/TOPS pcap) | IEX historical data downloads | official (the exchange) | none stated | free | not stated | the IEX Historical Data Terms of Use apply (**not read**; the page moved: HTTP 404 at the old URL); T+1 availability per a search summary | IEX-only depth and top-of-book, every message | daily, T+1 | none on the VPS; on demand, offline, symbol-filtered | IEX microstructure for the bounded universe (single venue, **not NBBO**) | archive (search summary: over 17 TB) | A for IEX-venue data | multi-GB per day unfiltered (not measured): **unsafe on the VPS** | — | NEEDS TERMS REVIEW (and laptop/offline only) | none now |
| PUBLIC MARKETS (equities) | Nasdaq Trader trade-halt RSS | `nasdaqtrader.com/rss.aspx?feed=tradehalts` | official (Nasdaq) | none | free ("free service") | "not query the data more than once a minute" | terms PDF `THRSSFeedTermsCond.pdf` **not read** | halts and resumptions (Nasdaq-listed and other exchange-listed) | once a minute while trading | ≤1/min in market hours, changed-only | halts and LULD context for every event window; an anomaly source | current halts only (history not documented) | C | under 0.2 MB (changed-only) | about 390 in market hours (mostly unchanged) | NEEDS TERMS REVIEW (read the T&C PDF) | none |
| PUBLIC MARKETS (all) | Exchange trading calendars and sessions (NYSE/Nasdaq holidays and early closes; CME sessions) | published holiday and early-close tables (exchange pages), encoded as versioned deterministic data | official | none | free | — | reading a published schedule is not quote scraping; the rows are transcribed and versioned in code | holidays, early closes, session hours (pre, regular, post; futures sessions and breaks) | yearly | manual annual update (versioned), with a CI test | every event window needs the session phase | archive | A | 0 | 0 | READY TO IMPLEMENT (goes into the §9 calendar primitive in `SOURCE_READINESS.md`) | none |
| PUBLIC MARKETS (futures) | CFTC Commitments of Traders | `publicreporting.cftc.gov` (Socrata; CSV, RSS, TSV, XML) | official | none ("not providing tokens … if usage remains reasonable") | free | "reasonable" usage | public | positioning by trader class per contract market | "each Friday at 3:30 pm Eastern" for Tuesday data (cftc.gov COT page, read 2026-09-24) | weekly, on demand | #88 futures: positioning as slow context (never intraday) | history "dating back to 1986–2006" | A (reconstructible; no prospective urgency) | about 0.1 MB a week | 1–5 a week | NEEDS SPECIFIC EXPERIMENT (A: fetch when a futures hypothesis exists) | none |
| PUBLIC MARKETS (futures) | CME Group: delayed quotes, real-time, DataMine, settlements | cmegroup.com delayed-quote pages; the licensed delayed API; DataMine (S3, API, SFTP) | official (the exchange) | licence | **paid** (the 10-minute-delay developer data is sold as "low-cost access"; DataMine historical is priced on request) | — | CME pages **timed out** to our fetch (not read). Public quote pages: **no automated extraction** (#88) | ES/MES, NQ/MNQ, SOFR/Treasury, CL/micro, GC/micro: contract identity, tick size and value, multiplier, expiry, sessions, depth, settlement | continuous | none | #88 futures families (macro-release reaction, index futures vs ETF lead-lag) | licensed (DataMine) | **C** (real-time depth); settlements: not verified | 0 | 0 | **PAID/ROI BLOCKED** (#7); settlement-data access: NEEDS TERMS REVIEW | an ROI case first |
| PUBLIC MARKETS (all) | Consolidated SIP (CTA/UTP), OPRA, Cboe DataShop, CME real-time | vendor or exchange feeds | official or licensed | licence | paid | — | licensed | NBBO, consolidated trades, OPRA quotes | real time | none | execution-grade evidence for any future live test | licensed | C | 0 | 0 | **PAID/ROI BLOCKED** (#7). Alpaca Algo Trader Plus ($99/month) is the cheapest verified SIP and OPRA route | ROI case |
| PUBLIC MARKETS (options) | Cboe public quote and statistics pages | cboe.com quote pages and market statistics | official | none | free to view | — | "Use of Content" terms not read. **Do not automate quote pages** (#88) | — | — | none | — | DataShop (licensed) | — | 0 | 0 | NEEDS TERMS REVIEW (statistics only); quote pages are never automated | none |

**Licensing detail for every public-market source** (#88: feed, timeliness, venue scope, history,
auth, cost, rate, retention, storage, redistribution, grade). "Not read" means the governing terms
were not readable on 2026-09-24, and the right is **UNKNOWN**. It is not assumed.

| Source | Feed | Real-time vs delayed | Single venue vs consolidated | Historical availability | Auth | Cost | Rate limits | Retention rights | Storage rights | Redistribution rights | Research-grade vs execution-grade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SEC EDGAR | official filings APIs | real time (under 1 s of processing) | n/a (the primary source) | full | none (User-Agent) | free | 10 req/s | public records | yes (public records) | public records (no SEC endorsement implied) | authoritative for filing content and acceptance time |
| Alpaca Basic, equities | IEX via Alpaca | real time for IEX; SIP delayed/historical | **single venue (IEX)** in real time | since 2016 | account keys (headers) | free | 200/min | UNKNOWN (T&C not read) | UNKNOWN | UNKNOWN (likely no redistribution) | research-grade only (not NBBO) |
| Alpaca Algo Trader Plus | SIP + OPRA | real time | consolidated | since 2016 (equities), Feb 2024 (options) | account keys | $99/month | 10,000/min | UNKNOWN | UNKNOWN | UNKNOWN | closer to execution-grade (SIP/OPRA); PAID/ROI BLOCKED |
| Alpaca Indicative options | derived from OPRA | real-time quotes are indicative; trades delayed 15 min | derived, not OPRA | since Feb 2024 (bars and trades) | account keys | free | 200/min | UNKNOWN | UNKNOWN | UNKNOWN | **indicative: research-grade only** |
| Tradier sandbox | Tradier | delayed 15 min | consolidated (delayed) | history endpoints (depth not verified) | bearer token | free (developer account) | 60/min | not read | not read | not read | research-grade (delayed, no Greeks) |
| Tradier brokerage | Tradier | real time | consolidated; Greeks from ORATS (hourly) | as above | bearer token (brokerage account) | account-tied (not verified) | 120/min | not read | not read | not read | execution-adjacent; account needed |
| IEX HIST | IEX DEEP/TOPS pcap | T+1 | single venue (IEX) | long archive | none stated | free | not stated | per the IEX HIST terms (not read) | not read | not read | research-grade (IEX microstructure only) |
| Nasdaq halts RSS | Nasdaq | once a minute | all US listings (halts) | current only | none | free | ≤1/min | T&C PDF not read | not read | not read | context only |
| CFTC COT | official reports | weekly (Tuesday data, Friday 15:30 ET) | all reporting markets | since 1986–2006 | none | free | reasonable | public | public | public | slow context only |
| CME delayed, real time, DataMine | CME | ≥10 min delayed / real time | exchange (CME) | DataMine | licence | paid | per licence | per licence | per licence | per licence | licensed; PAID/ROI BLOCKED |
| SIP / OPRA / Cboe DataShop | consolidated or licensed | real time or historical | consolidated | licensed | licence | paid | per licence | per licence | per licence | per licence | execution-grade; PAID/ROI BLOCKED |

**Paper/sandbox broker route comparison** (research only; no signup; paper orders are Gate 8 and
not authorized):

| Route | Account needed | Data it gives | Fill model (paper) | Order-scope risk of its key | Verdict |
|---|---|---|---|---|---|
| **Alpaca paper-only** | email signup, no funding ("Paper Only Account … sign up with your email") | IEX real time, SIP history, indicative options (OPRA paid) | matched against NBBO; partial fills "10% of the time"; **no slippage, no regulatory fees** (paper-trading doc, read 2026-09-24) | the paper key can place paper orders; the live key is separate | **Research first.** No funding is needed, feed identity is explicit (IEX vs SIP, indicative vs OPRA), and it has the most documentation. Its fill model is optimistic, so it is never evidence of executable cost |
| Tradier sandbox | a developer account | delayed 15 min, no Greeks in the sandbox | not researched | bearer token for the sandbox | second: useful for ORATS Greeks provenance only on the production route |
| Interactive Brokers paper | an IBKR account (the paper page returned **HTTP 403**, not verified) | per live subscriptions (not verified) | not researched | the account credential | not researched; likely needs a live account |

**First public-market prospective data to collect** (category C first, keyless first):
1. **EDGAR filing events for a bounded mega-cap universe** (keyless; READY TO IMPLEMENT).
   - The content is reconstructible. *Our* receipt time and the event anchor for the §9 calendar
     are not.
   - Market data for the reaction can be fetched historically later (A via Alpaca history, once
     keyed).
2. **Indicative SPY/QQQ option-chain snapshots around scheduled macro events** (FOMC, CPI, NFP)
   and a daily 15:45 ET snapshot.
   - This is the one free public-market signal documented as *not* historical: chain quotes, IV and
     Greeks at an instant.
   - Needs the owner's Alpaca key **after** the security ADR. Labelled INDICATIVE, with Greeks
     marked vendor-derived.
3. **Not prospectively:** equity bars, quotes and trades (fetchable since 2016); COT (archive);
   futures (licensed).

**Safest first experiment family** (event windows, not indicator mining): **scheduled
macro-release reaction in SPY, QQQ, IWM and TLT** (TLT is added as the rates proxy).
- **Windows:** FOMC 14:00 ET measured intraday; CPI and NFP (08:30 ET, pre-market) measured from
  the 09:30 open, because pre-market liquidity is thin and IEX-only.
- **Paired evidence:** the Kalshi macro-family pre-close prices (§1.1) and the option-implied
  move (item 2 above).
- **Costs:** from a conservative spread model, **not** the IEX quote alone (single venue) and never
  from midpoints. Sessions come from the versioned calendar. No execution claim until SIP/OPRA
  evidence exists (PAID/ROI BLOCKED).
- **Why this family:** about 12–20 events a year, fixed times, official sources already in Wave 3,
  and no latency race.

## 2. What we are losing every day (category C gaps, ranked)

**Production today** (HANDOFF 2026-09-24; `LEARNING_HISTORY_COVERAGE.md`):
- KXHIGHNY: decision and recheck books, plus ADR 0030 later/close observations for evaluated
  brackets;
- PFMOKX;
- Kalshi settlement for held positions;
- NFL odds at T-24h, T-6h and T-60m;
- the freshness artifact.

**Nothing else is collected prospectively.** Ranked by irreplaceability × research value ×
likelihood of domain entry × readiness (§6; reasoned, no numeric score):

1. **Other cities' Kalshi weather books and NWS forecast vintages.**
   - Irrecoverable: depth, and the forecast as served. api.weather.gov keeps no past gridpoint
     forecast.
   - About 20 recurring daily city families exist, and each day not captured is a lost
     forecast-vs-market pair.
   - Top-of-book may be recoverable from candlesticks (B, P1-8). PFM issuance is recoverable from
     IEM (B).
   - Fix: Multi-City Weather v1 (Lane G).
2. **Kalshi NFL (and NCAAF) game-market books at the Odds API horizons.** We already pay credits
   for the sportsbook side of each horizon. The prediction-market price *at the same instant* is
   not captured, and the NFL season is finite (about 18 regular-season weeks). It is keyless, needs
   about 10 GETs a day, and reuses the ADR 0032 relationship contract.
3. **Pre-release books in the macro release families** (CPI family, payrolls/U-3, claims,
   PCE, GDP, EIA crude, Fed). Each monthly release not captured is one lost observation of
   market-implied distributions before the number, and there are about 12 a year per family.
   Top-of-book: B via candlesticks.
4. **Rules, lifecycle and catalog changes across recurring families.** Kalshi keeps series and
   events, but not *when* a rule text, settlement source, fee or close convention changed.
   KXHIGHNY's settlement source changed on 2026-08-14 and its close convention in August 2026. We
   know this only because it was captured. A daily rules-hash inventory costs about 30 GETs.
5. **Crypto hourly ladders together with exchange spot and dispersion.** The Kalshi side is
   keyless. The exchange side is gated by the terms review. Candles are reconstructible; the book
   and the cross-venue state at the decision instant are not.
6. **Election-market books before 2026-11-03** (one-shot; weak for a repeatable edge; owner
   choice).
7. **The NYC gridpoint and hourly forecast vintage** (P0-cond, `LEARNING_HISTORY_COVERAGE.md` §4b)
   and prospective NWS CLI for NYC (U-1, P1 via IEM).
8. **First-print receipt times for official releases** (BLS/BEA/DOL/EIA/Fed). ALFRED restores
   values by *day* (B); the minute we could first have read the number is C. It matters only once a
   post-release study exists.
9. **Public markets (#88).**
   - Indicative SPY/QQQ option-chain state (quotes, IV and Greeks) at scheduled macro instants: C.
     It needs an owner key and a security ADR first.
   - Our EDGAR receipt time for filings in the bounded universe: C. It is keyless.
   - Equity bars and quotes are **not** on this list: they are fetchable historically (A for IEX,
     and SIP history via Alpaca).

   Futures depth is C, but licensed (PAID/ROI BLOCKED).

**Never recoverable by any purchase within our means:** our own receipt times, our freshness
failures and misses, and rejected opportunities. These are already stored where production
collects (#50).

## 3. Combined resource budget (§43)

### 3.1 Current production (from the unit files, ADRs 0029–0031 and the fixtures; not measured on the VPS in this lane)

| Collector (unit) | runs/day | requests/run | requests/day (typical) | worst-case requests/day (retries) | network bytes/day | stored bytes/day | CPU | memory cap |
|---|---|---|---|---|---|---|---|---|
| `edgelab-pfm` | 1 | 2–4 | about 3 | about 9 | about 0.1 MB | about 75 KB | under 2 s | 256M |
| `edgelab-decision` | 1 | about 8 (event, markets, 6 books) | 8 | 24 | about 40 KB | about 30 KB | under 2 s | 256M |
| `edgelab-recheck` | 1 | 6 | 6 | 18 | 9 KB | 9 KB | under 2 s | 256M |
| `edgelab-observe` + `-close` | 96 + 1 (about 5 with network) | ≤40 (hard bound) | about 30 | about 90 (ADR 0030: about 3× on a bad day) | about 0.2 MB | under 250 KB (payloads plus about 60 rows) | idle ticks under 1 s each; about 90–150 s/day | 256M |
| `edgelab-settlement` | 2 | 0 when nothing is due; ≤ about 10 | 0–10 | about 30 | ≤ 50 KB | ≤ 35 KB | seconds | 256M |
| `edgelab-odds` | 96 | ≤1 free discovery (every 6 h) + ≤1 paid | about 7 (4 free + about 3 paid on average; about 9 paid on a Sunday) | 96 ticks × ≤2 is the theoretical ceiling; paid calls are bounded by the 450-credit proof (≤150 a month) | about 0.2 MB | about 0.2 MB (est.) | about 100–200 s/day | 256M, CPU 10% |
| `edgelab-freshness` | 288 | 0 (network-free) | 0 | 0 | 0 | 0 (29 KB replaced); journal about 90 KB | 5–15 CPU-min/day (ADR 0031) | 128M, CPU 10% |
| `edgelab-status`, `-shadow` | 1 + 1 | 0 | 0 | 0 | 0 | history jsonl 10–30 KB | seconds | 256M |
| `edgelab-notify` | event-driven | 0–few POSTs to ntfy | ≤5 | ≤10 | small | small | seconds | 256M, CPU 10% |
| `edgelab-dashboard` | always on | 0 outbound | 0 | 0 | 0 | 0 | light | 128M, CPU 10% |
| `edgelab-backup` | 1 | 0 | 0 | 0 | 0 | **a full copy of both stores every day, never deleted** (unit description: "no automatic deletion") | about the DB size read and written | 256M |
| **Total** | | | **about 55–70 external requests/day** | **about 300** (excluding theoretical ceilings) | **about 0.8 MB** | **about 0.6 MB payload → about 0.6–1.0 MB/day of evidence DB growth (est.), about 20–30 MB/month**, plus the backups (§3.3) | about 0.5–1.2 CPU-hours/day of the slice's 6 CPU-hours (25% of one core × 24 h) | slice 384M |

Measure before the first new collector (owner/root, read-only):
- `du -sb /var/lib/market-edge-lab/db /var/lib/market-edge-lab/backups`;
- `systemd-cgtop -1 edgelab.slice`;
- `systemctl show edgelab.slice -p MemoryPeak`.

Recorded peaks so far: slice MemoryPeak 31–49 MiB of 384 MiB (`PRODUCTION_ACTIVATION_2026-09-23.md`).

### 3.2 Proposed streams at their proposed cadence

| Stream | runs/day | requests/run | requests/day | worst/day (×3 retries) | network/day | stored/day | stored/month | CPU/day (est.) | peak memory (est.) | DB growth |
|---|---|---|---|---|---|---|---|---|---|---|
| K-catalog: series weekly | 1/7 | 1 | 0.14 | 0.4 | 2.5 MB avg (17.6 MB per read) | 0.23 MB compressed (2.5 MB raw) | 7 MB compressed (75 MB raw) | about 5 s per read | **90–180 MB if parsed whole** (unsafe beside another unit); about 20 MB streamed | one blob a week |
| K-inventory: 30 families | 1–4 | 30 | about 30 | 90 | 0.5 MB | 0.3–0.6 MB | 9–18 MB | under 30 s | under 40 MB | rows plus snapshots |
| Multi-City Weather v1, market side (10 cities; Lane G sets the final numbers) | about 6 horizons | about 40 | about 240 | about 720 | 1.3 MB | 1.3 MB | 40 MB | about 60 s | under 60 MB | |
| Multi-City Weather v1, NWS side (PFM, gridpoint, observations, CLI) | several | 5–20 | about 140 | about 420 | 2–4 MB | 1.5–4 MB (changed-only for gridpoints) | 45–120 MB | about 60 s | under 60 MB | |
| Kalshi sports game markets (NFL; +NCAAF) | per target | 2–4 | 10 (+80) | 30 (+240) | 0.1 (+0.3) MB | 0.06 (+0.3) MB | 2 (+9) MB | small | under 40 MB | |
| Kalshi macro families | release-driven | 1–15 | 21 avg / **165 peak** | 500 peak | 0.15 MB avg | 0.11 MB avg | 3.4 MB | small | under 40 MB | |
| Official macro keyless (BLS v1, ICS, BEA JSON, Fed RSS, DOL) | many (RSS) | 1 | about 80 (mostly 304) | about 240 | under 1 MB | under 0.3 MB (changed-only) | under 9 MB | small | under 40 MB | document retrievals |
| FRED/ALFRED + BEA (after keys) | about 2 | about 5 | about 10 | 30 | 0.3 MB | 0.2 MB | 6 MB | small | under 40 MB | |
| Kalshi crypto (sampled) | 6 per asset | about 6 | about 72 | about 216 | 4.3 MB | 4.3 MB raw / about 0.5 MB compressed | 130 MB raw / 15 MB compressed | about 30 s | under 60 MB per listing | |
| Exchange spot (after terms) | about 12 | about 5 | about 60 | 180 | 0.8 MB | 0.6–0.8 MB | 20–25 MB | small | under 40 MB | |
| Odds API, one extra sport (h2h, T-60m) | per group | 1 | about 4 | 4 (the paid call is never retried) | 0.2 MB | 0.1–0.2 MB | 3–6 MB | small | as odds | |
| EIA (after the key) | release-driven | 1–5 | about 3 avg | 45 peak | 0.1 MB | 0.1 MB | 3 MB | small | under 40 MB | |
| Public markets: EDGAR universe (keyless) | about 200–400 polls | 1 (+3 per new filing) | about 215–415 (mostly unchanged) | about 1,200 | about 5–15 MB (unchanged feed polls) | 1–4 MB (changed-only plus filing bytes) | 30–120 MB | about 5–10 min of CPU (Python start-up per poll run; batch polls in one process per 15 min to cut it) | under 60 MB | document blobs |
| Public markets: indicative option snapshots (after the key and ADR) | about 4 plus event windows | 3–5 (paged) | about 10–20 | about 60 | about 1 MB | about 0.5 MB | 15 MB | small | under 60 MB | |
| Public markets: halts RSS (after the terms) | about 390 (market hours) | 1 | about 390 | about 390 | about 4 MB | under 0.2 MB (changed-only) | under 6 MB | about 5 min | under 40 MB | |

### 3.3 Combined footprint and what would be unsafe

| Scenario | requests/day (typical / worst) | DB growth/day | DB after 180 days | uncompressed daily backups after 180 days (never deleted) |
|---|---|---|---|---|
| A: production today | about 65 / about 300 | about 0.8 MB | about 145 MB | about **13 GB** |
| B: A + catalog + inventory + Multi-City Weather v1 | about 475 / about 1,500 | about 4–7 MB | 0.7–1.3 GB | about **65–115 GB: exceeds the about 64 GB free** |
| C: B + Kalshi NFL game markets + macro (market and keyless official) + one extra Odds sport | about 590 / about 2,300 (macro peak day) | about 5–8 MB | 0.9–1.45 GB | about 80–130 GB: **exceeds** |
| D: C + crypto (Kalshi sampled plus exchanges) + keyed macro + EIA | about 735 / about 2,750 | about 7–13.5 MB (the low end has the crypto ladders compressed) | 1.25–2.4 GB | about 115–220 GB: **exceeds** |
| E: D + public markets (EDGAR universe, option snapshots, halts) | about 1,450 / about 4,400 | about 8–18 MB | 1.5–3.2 GB | about 130–290 GB: **exceeds** |

The backup total is the sum of daily full copies, g × N²/2 (g = growth per day, N = days).
64 GB is exhausted at N ≈ √(128,000 MB / g). At the growth rates above, the disk fills in:

| Scenario | Days until 64 GB is full |
|---|---|
| A | about 400 |
| B | about 135–180 |
| C | about 125–160 |
| D | about 95–135 |
| E | about 85–125 |

**Explicitly unsafe:**
1. **Any scenario beyond A, while `edgelab-backup` keeps a full, uncompressed, never-deleted copy
   of the evidence DB every day.**
   - **Disk.** The backups, not the collectors, are the binding disk constraint.
   - **Time budget.** `edge_lab.backup` uses one 30 s deadline for copy, inspect and hash
     (`--timeout` default 30; the unit passes none). `copy_online` copies 128 pages per step with
     a 10 ms sleep: at 4 KiB pages that is about 20 s of sleep alone per GB (est.). An evidence DB
     of about **0.5–1 GB** is therefore expected to exceed the budget and fail the backup (alert)
     *(est., unmeasured)*. Scenario B reaches that size in about 2.5–8 months; Scenario D in about
     1–5 months. Scenario A reaches it in about 1.7–3.4 years.
   - **Prerequisites before Scenario B's collectors are enabled:**
     - compressed backup bundles (not destructive);
     - a timeout proportional to size;
     - a retention or rotation policy. Deleting old backups deletes copies of evidence, so it
       **needs owner approval** (Authority: destructive operations);
     - or an off-host copy.
2. **The full hourly Kalshi crypto ladders** (every hour, both assets, whole listing). That is
   about 17 MB/day (about 0.5 GB/month) raw, which alone breaches the constraint above. Keep them
   sampled and compressed.
3. **Parsing the full 17.6 MB series catalog in-process** inside a 256M unit while another
   edgelab unit runs. Two 256M-capped units can together exceed the 384M slice, and the kernel
   then kills inside the slice. Store the bytes and parse them streamed or filtered, and schedule
   outside other units' windows.
4. **Unfiltered Polymarket US catalogs, or the NFL league endpoint** (40 MB per page; ADR 0032).
   These are prohibited by the terms as well as the size.
5. **Level-3 or tick-level crypto polling.** Coinbase warns it may block, and the directive forbids
   unbounded ticks.
6. **More than one extra Odds API sport, or the full 3 markets × 3 offsets for any extra sport.**
   This breaks the 450-credit proof in November or December.
7. **Kalshi request peaks placed together.** Every Kalshi stream shares one host pacing budget
   (0.6 s, ≤1.7 req/s) and the collector lock (`<db>.forward.lock`; a busy lock is `LOCK_BUSY`).
   A 08:30 ET macro peak (about 165 GETs, about 100 s of pacing) is safe. The same peak inside
   17:40–18:50 ET, 11:13–11:30 ET or 16:13–16:30 ET is not: those are protected windows, and every
   new Kalshi stream must refuse them as `observe capture` does.

8. **IEX HIST full-day pcaps, or any tick-level public-market archive, on the VPS.** These are
   multi-GB per day unfiltered. Process them offline (on the laptop), symbol-filtered, if the terms
   allow at all.
9. **Unbounded EDGAR polling.** Keep the universe bounded (about 20–30 CIKs), use one change-signal
   poll per 1–2 minutes, and never crawl. The SEC "does not allow botnets or automated tools to
   crawl the site".

**Safe with the prerequisite in item 1 met:**
- **CPU.** Scenario D adds about 480 fifteen-minute ticks at about 1.5 s of Python start-up, about
  12 CPU-min/day, plus work. The slice allows about 6 CPU-hours/day, and today uses about 0.5–1.2.
- **Network.** Under 25 MB/day (about 40 MB/day in Scenario E).
- **Memory.** Under 100 MB per unit if listings are processed one at a time.

The Brisket workloads stay outside `edgelab.slice`, and nothing here changes their caps.

### 3.4 Storage policy per stream (§44)

| Stream | Policy | Compression | Retention | Archive |
|---|---|---|---|---|
| Kalshi books (every family) | raw, every captured event (C evidence) | not at the row level; compressed backups | indefinite (evidence is immutable) | off-host copy, owner-approved |
| Kalshi listings (inventory, families) | raw periodic; the rules text is hashed per market. A listing whose canonical hash equals the previous one may be stored as a retrieval row only (`document_*` dedupe pattern) | yes for crypto ladders (8–10× expected) | indefinite | as above |
| Kalshi series catalog | raw periodic (weekly) as an exact-bytes blob, plus a derived per-series change log | gzip (measured 10.9×) | indefinite (compressed) | as above |
| NWS products (PFM, CLI) | raw, every new issuance (dedupe by product id) | none needed (text) | indefinite | IEM also archives |
| NWS gridpoints and observations | raw, only when `updateTime` changes; observations periodic | optional | indefinite for the forecast vintage (C); observations 1 year (B via IEM), owner decision | — |
| Official macro and energy values | raw at each release read; ALFRED vintages periodic | none | indefinite | ALFRED is the archive |
| RSS and calendars | changed-only exact bytes (`document_blobs`), plus a retrieval row per poll | none | indefinite | — |
| Crypto exchange | periodic bounded snapshots (L2 top-50) at sampled instants; candles as derived-reconstructible (re-fetchable) | yes | books indefinite; candles re-fetchable (short retention acceptable) | — |
| The Odds API | raw every paid call (C, paid) | none | indefinite | — |
| Public markets: EDGAR | changed-only feed polls (retrieval rows); each new universe filing's index and primary document as exact bytes | none (text); XBRL optional | indefinite | EDGAR itself |
| Public markets: indicative option snapshots | raw periodic (bounded chain) with the vendor and Greek provenance | yes | indefinite (C) | — |
| Public markets: equity bars and quotes | **derived or on demand only** (re-fetchable history); never a prospective duplicate | — | per the vendor terms (UNKNOWN until read) | — |
| Freshness, status, receipts | derived only (replaced) plus the append-only history | — | history indefinite | — |

## 4. Implementation status summary

| Class | Sources |
|---|---|
| **ACTIVE NOW** | Kalshi KXHIGHNY (forward, observe, settlement); NWS PFMOKX; The Odds API NFL pilot (and its discovery) |
| **READY TO IMPLEMENT** (keyless) | Kalshi series catalog; the recurring-family inventory; multi-city weather families; macro families; hourly crypto (sampled); NFL/NCAAF game markets; candlestick and trade backfill. NWS PFM (other WFOs), gridpoints, observations and CLI; the IEM backfill. BLS API v1; the BLS ICS; the BEA release JSON; the Fed RSS feeds; DOL claims; the EIA WPSR schedule page. **Public markets:** SEC EDGAR filing events for a bounded universe; exchange calendars and sessions |
| **NEEDS FREE OWNER KEY** | FRED/ALFRED (`EDGE_LAB_FRED_API_KEY`); BEA (`EDGE_LAB_BEA_USER_ID`); EIA (`EDGE_LAB_EIA_API_KEY`); Census (`EDGE_LAB_CENSUS_API_KEY`, after the rules check); BLS v2 (`EDGE_LAB_BLS_API_KEY`, optional); api.data.gov for OpenFEC and Congress.gov (`EDGE_LAB_API_DATA_GOV_KEY`, only if politics is chosen). **Public markets, each also needing a security ADR** (header transport; an order-scoped paper key): Alpaca Basic data and indicative options (`EDGE_LAB_ALPACA_DATA_KEY_ID`, `EDGE_LAB_ALPACA_DATA_SECRET`); Tradier sandbox (`EDGE_LAB_TRADIER_SANDBOX_TOKEN`) |
| **NEEDS TERMS REVIEW** | Polymarket US (owner access decision, ADR 0032); Coinbase Exchange market data; Kraken public; AAA; league injury reports; The Weather Company (BLOCKED; written permission only). **Public markets:** IEX HIST; the Nasdaq halts RSS; Cboe statistics; CME settlement data |
| **NEEDS SPECIFIC EXPERIMENT** | Kalshi index, commodity and gas families; election markets; SEC EDGAR for Kalshi-side use; Treasury FiscalData; Novig daily files; extra Odds API sports (NCAAF or NBA, h2h at T-60m, at most one); weather for outdoor games. **Public markets:** CFTC COT (archive; A) |
| **PAID/ROI BLOCKED** | CF Benchmarks indices; futures (NYMEX/ICE); equity/ETF real-time benchmarks; paid Odds API tiers. **Public markets:** consolidated SIP, OPRA, CME real-time/delayed API and DataMine, Cboe DataShop, Alpaca Algo Trader Plus ($99/month), the Tradier brokerage route |
| **NOT CURRENTLY WORTH COLLECTING** | Kalshi WebSocket (account credential); entertainment-chart and social sources; polling; news and social (§31); NWS alerts; the Fed DDP (retiring); Odds MLB, NCAAB, props and `/scores` |

**Keys: keyless vs owner key vs paid.**
- **Keyless:** every Tier 0 market source, NWS, IEM, BLS v1, the BLS/BEA calendars, the Fed RSS
  feeds, DOL, FiscalData and SEC EDGAR (User-Agent only).
- **Free owner key:** FRED/ALFRED, BEA, EIA, Census, BLS v2 (optional) and api.data.gov. Also
  the Alpaca paper-only data key and the Tradier sandbox token, each after a security ADR.
- **Paid:** CF Benchmarks, futures and equity real time, paid Odds tiers, SIP, OPRA, CME data and
  Cboe DataShop.

**Secret names.**
- `EDGE_LAB_<PROVIDER>_…` follows the deployed precedent `EDGE_LAB_ODDS_API_KEY`.
- `docs/SECURITY.md` still reserves the older pattern `EDGE_LAB_RESEARCH_<PROVIDER>_KEY`. The
  coordinator, who owns SECURITY.md, should reconcile the two before the first owner key.
- Each key would travel as a query parameter, which `edge_lab.http` supports while refusing
  credential headers. BLS v2's GET transport is not verified.

## 5. Recommended activation order

Waves follow directive §65, after the active lanes reconcile. Parallel lanes are marked.

1. **Wave 1: universal inventory.**
   - The Kalshi series catalog (weekly, compressed).
   - The recurring-family inventory with rules hashes and lifecycle (daily).
   - The shared release/event calendar primitive (contract in `SOURCE_READINESS.md` §9), fed first
     by Kalshi `close_time`/`expected_expiration_time`, the BLS ICS and the BEA JSON.
   - **Prerequisite for everything after Wave 1:** compressed backups, a size-aware timeout, and an
     owner-approved retention or off-host policy (§3.3 item 1).
2. **Wave 2: Multi-City Weather v1** (Lane G design). NWS PFM, gridpoints, observations and CLI,
   plus the Kalshi city families.
3. **Next stream after Multi-City Weather v1 (recommended): Kalshi NFL game-market books at the
   existing Odds API horizons.**
   - It is the cheapest (about 10 GETs/day) and keyless. It completes an already-paid-for series
     (the sportsbook side exists and ADR 0033 consensus is merged).
   - It is **season-bound**: every NFL week lost is permanent and there are about 18.
   - It reuses ADR 0032's relationship contract. It is Tier 0 market-side evidence, so it belongs
     to Wave 1's scope, which is why it may precede Wave 3.
   - Then add NCAAF game markets the same way.
4. **Wave 3: macro foundation.**
   - Kalshi macro families: pre-release books, closing ≤5 min before 08:30 ET, and post-release
     reads only for still-open related families.
   - BLS v1, DOL claims and the Fed RSS feeds (keyless).
   - FRED/ALFRED and BEA once the owner installs the keys (parallel lane; no shared code path with
     the weather or sports collectors).
5. **Wave 4: crypto foundation.**
   - The Kalshi hourly ladders, sampled (keyless).
   - Coinbase/Kraken only after the owner's terms decision.
   - CF Benchmarks stays paid-blocked.
6. **Wave 5: EIA and SEC, plus the public-markets foundation (#88).**
   - EIA after the key (KXEIACRUDEW, KXNGASW, once the rules are read).
   - SEC EDGAR filing events for the bounded #88 universe (keyless). They share the §9 calendar
     and the exchange-session calendar.
   - A security ADR for broker market-data keys, then (owner key) indicative SPY/QQQ option
     snapshots at the Wave 3 macro instants.
   - Equity bars and quotes on demand only.
   - Futures, SIP and OPRA stay PAID/ROI BLOCKED.
   - The safest first public-market experiment family is macro-release reaction in
     SPY/QQQ/IWM/TLT (§1.7).
7. **Wave 6: everything else, only where a market or hypothesis justifies it.**
   - Elections are an owner choice before 2026-11-03.
   - Index and commodity families.
   - Politics APIs.
   - Culture stays catalog-only.
   - News and social stay out.

**What cannot be reconstructed historically, whatever we do later:**
- order-book depth at any instant, on any venue (Kalshi documents no historical books; neither
  do Polymarket US or the exchanges);
- the forecast *as served* by api.weather.gov gridpoints;
- the time we first saw a release, rule, schedule or fee change;
- cross-venue state at one instant (prediction market vs sportsbook vs exchange);
- sportsbook odds (historical odds need a paid plan);
- public markets: an options chain's quotes, IV and Greeks at an instant (free indicative feed);
  consolidated NBBO and futures depth without a licence;
- our own freshness failures, misses and rejected opportunities.

**What can be reconstructed:**
- settled outcomes and values (A);
- day-level macro vintages via ALFRED (B);
- NWS text-product issuance via IEM (B);
- Kalshi top-of-book and trade paths via candlesticks and trades (B; P1-8 still needs one stored
  read to prove it);
- exchange candles (A/B).

## 6. Sources read (2026-09-24)

Kalshi:
- docs.kalshi.com: quick_start_market_data, rate_limits, historical_data, websockets, and
  get-market-candlesticks / get-trades;
- kalshi.com/developer-agreement: HTTP 429, not read.

Sports:
- the-odds-api.com: liveapi/guides/v4 and sports-odds-data/sports-apis.

Weather:
- weather.gov/documentation/services-web-api;
- mesonet.agron.iastate.edu/disclaimer.php.

Macro:
- bls.gov: developers, developers/api_faqs.htm, schedule/news_release;
- bea.gov: apps.bea.gov/API/docs, the BEA API user guide PDF, bea.gov/news/schedule;
- fred.stlouisfed.org: docs/api/api_key.html, terms_of_use.html, realtime_period.html;
- census.gov: api-user-guide Query_Limits;
- federalreserve.gov: feeds/feeds.htm, datadownload;
- oui.doleta.gov/unemploy/claims.asp;
- fiscaldata.treasury.gov/api-documentation.

Energy:
- eia.gov: opendata, opendata/documentation.php, opendata/terms-of-service.php,
  petroleum/supply/weekly/schedule.php.

Business:
- sec.gov: search-filings/edgar-search-assistance/accessing-edgar-data and
  edgar-application-programming-interfaces.

Politics:
- api.data.gov/docs/developer-manual;
- github.com/LibraryOfCongress/api.congress.gov;
- api.open.fec.gov/developers: the page content was not readable; the key and limit come from a
  search summary.

Public markets (#88):
- docs.alpaca.markets: about-market-data-api, paper-trading, historical-option-data;
- docs.tradier.com: market-data, rate-limiting, llms.txt;
- cftc.gov COT page; publicreporting.cftc.gov;
- nasdaqtrader.com trade-halt RSS page;
- cboe.com market statistics;
- CME pages timed out (search summaries only, marked as such);
- IEX historical-data page: HTTP 404 (search summary only);
- the IBKR paper-trading page: HTTP 403.

Crypto:
- docs.cdp.coinbase.com: exchange rate-limits and get-product-book;
- coinbase.com/legal/market_data: HTTP 403, not read;
- support.kraken.com API rate limits article;
- kraken.com/legal/global-terms;
- cfbenchmarks.com/data/indices/BRTI.
