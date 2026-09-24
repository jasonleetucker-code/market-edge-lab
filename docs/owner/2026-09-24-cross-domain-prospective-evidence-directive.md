# Owner directive / idea, 2026-09-24 (evening): cross-domain prospective evidence expansion

Source: the owner's message to the laptop Claude Code session, 2026-09-24 about 18:35 ET: "OWNER
DIRECTIVE / OWNER IDEA — CROSS-DOMAIN PROSPECTIVE EVIDENCE EXPANSION". Canonical idea issue: #86
(extends #7, #50, #74 and #82, and serves #30; it duplicates none of them). Recorded in substance,
section by section. Every authorization, prohibition, bound and acceptance criterion keeps the
owner's wording. A later owner decision wins, and is recorded in `docs/EXECUTION_PLAN.md`.

## Owner intent (verbatim)

> I would rather start collecting useful prospective evidence months before we need it than discover
> months later that the most important training information can no longer be reconstructed.

> Market Edge should eventually have a deep, point-in-time history across the markets we genuinely
> plan to study, even when no model was ready and no trade was taken at the time.

> We should collect broadly enough to discover edges, but not so indiscriminately that storage,
> cost, maintenance and noise become the project.

**Principle.** COLLECT BROADLY → MODEL CAREFULLY → VALIDATE NARROWLY → TRADE ONLY AFTER EVIDENCE.
Also: COLLECT ≠ MODEL, MODEL ≠ VALIDATED, VALIDATED ≠ ACTIONABLE, and MORE DATA ≠ MORE EDGE. A later
conclusion that "this source adds nothing" is valuable.

## Concepts (§3–§6)

- **Three kinds of information.**
  - **(A) Reconstructible history:** official series, settled observations, filings, final outcomes.
  - **(B) Partially reconstructible point-in-time data:** vintages, revisions, forecast issuance
    history, publication timestamps.
  - **(C) Irrecoverable prospective information:** order books and depth at an instant; spreads;
    source latency as Market Edge saw it; bookmaker availability; temporary failures; quote changes
    around an announcement; what Market Edge knew before a release; rejected opportunities;
    freshness failures; a market briefly becoming actionable.

  **Category C gets collection priority: every missed day is lost for good.** A backfill is never
  represented as a prospective observation.
- **Universal market-side evidence (§4).** For every supported venue and market, aim to preserve:
  - identity: venue, route or liquidity pool, market and event ids, domain, title;
  - rules: exact rules and their hash, settlement source;
  - lifecycle: status; open, close, event and resolution times;
  - terms: payoff structure, price grid, fees and fee-claim state;
  - trading: volume and open interest where published, best bid/ask, depth;
  - timing: receipt and source timestamps, freshness;
  - later: later and near-close prices, settlement.

  Unknown stays unknown.
- **Catalog discovery across planned domains (§5).** Domains: WEATHER, SPORTS, ECONOMICS/MACRO,
  CRYPTO, ENERGY/COMMODITIES, BUSINESS/TECHNOLOGY, POLITICS/GOVERNMENT, CULTURE/ENTERTAINMENT,
  OTHER/LONG-TAIL. States: DISCOVERED / DATA_COLLECTION / RESEARCH_READY / MODEL_UNSUPPORTED /
  MODEL_AVAILABLE. Discovery never makes a market actionable.
- **Prioritization (§6).** Irreplaceability × future research value × likelihood of domain entry ×
  incremental information × access legitimacy, set against cost, quota, storage and maintenance. This
  uses reasoned states, not a fake numerical score. Volume without demonstrated value is not a reason
  to collect.

## Domains (§7–§31)

- **Tier 0, market data (§7).**
  - Kalshi, Polymarket US and future approved venues: catalogs, rules, quotes, books, status,
    volume, close, settlement.
  - Never conflate a prediction market, sportsbook, broker, aggregator and underlying exchange.
  - No authenticated trading API.
- **Weather (§8–§10, §46, §67).** Multi-City Weather v1, the first new non-sports expansion.
  - **Cities:** about 8–12 recurring weather-market cities, chosen by:
    - actual recurring market availability, with verifiable rules and an official settlement
      station;
    - climate diversity;
    - liquidity;
    - NWS/NOAA coverage;
    - sustainability.
  - **What to preserve:** market evidence (catalog, brackets, rules, station, prices, depth,
    volume, status, horizon and later/close observations, settlement); forecast evidence (product,
    issuance, valid and receipt times, high, revisions, hourly/grid where useful, alerts, office);
    observations and settlement publication.
  - **Horizons:** candidates D-3, D-2, D-1 morning and afternoon, an EXP-001-comparable window, event
    morning, later, near close and settlement, deduplicated by issuance.
  - **Status:** new cities start as DATA_COLLECTION, not as EXP-001 clones. No EXP-001 change.
- **Sports (§11–§12).**
  - Continue NFL. Stage NBA / MLB / NHL / NCAAF / NCAAB only after verifying provider coverage and
    the monthly credit impact against the free-tier budget, or finding another legitimate free
    source. No props.
  - Preserve identity, lines, timestamps, consensus, dispersion, movement, prediction-market
    price/depth, approved injury/availability data, weather for outdoor games, outcomes, and
    push/tie/void and overtime rules.
- **Macro (§13–§16, §47; the next structured domain).**
  - Sources: official BLS, BEA, Federal Reserve, FRED/ALFRED, Census, Treasury/FiscalData.
  - Releases: CPI, core CPI, PPI, payrolls, unemployment, claims, JOLTS, GDP, PCE and core PCE,
    retail sales, industrial production, Fed decisions and target range, projections,
    Treasury/fiscal, trade balance. Each must have a plausible market or experiment.
  - **Vintages are critical:** keep the initial value, release and receipt times, the prior value as
    then known, revisions, and vintage identity.
  - Market reaction windows (candidates): T-24h, T-6h, T-60m, T-15m, pre-release, T+1m, T+5m,
    T+30m, T+2h, close.
- **Crypto (§17–§19, §48).**
  - BTC and ETH from a small number of reputable public exchange endpoints after terms review. No
    credentials.
  - Preserve spot, bid/ask, bounded depth, trades, volume, spread, timestamps, exchange identity,
    dispersion across exchanges, and related prediction-market prices. Perpetuals and futures are
    separate instruments.
  - Store periodic, bounded, event-triggered snapshots, not every tick forever. Hot/warm/cool
    cadence belongs to Freshness Fabric.
- **Energy (§20–§22).**
  - EIA fundamentals: inventories, natural gas storage, production, electricity demand and
    generation, STEO, officially published prices. NOAA context where relevant.
  - Record release timing and initial vs revised values.
  - Futures prices only where legitimately free; a licensed feed stays blocked under the #7 ROI
    process.
- **Business (§23–§25).**
  - SEC EDGAR public data, following its automated-access guidance: 8-K, 10-Q, 10-K, company facts
    and XBRL, acceptance timestamps, form, CIK, hash. We are a reader, never a filer.
  - Company IR only when a market justifies it.
  - Equity and ETF benchmarks only after a licensing review. A paid real-time feed goes through #7.
- **Politics (§26–§28).**
  - Structured official data: FEC candidate and committee aggregates, election calendars, certified
    results, Congress.gov, agency actions.
  - Avoid individual-donor PII.
  - Market-side evidence for selected markets. No recommendations.
  - Polling only after a source-specific terms and methodology decision.
- **Culture and long-tail (§29–§30).** Market data first. The authoritative outcome source only for
  an actual market family. No celebrity or social scrapers. Long-tail: discover, then rank.
- **News, text and social (§31).** Not a tier-1 universal collection. Only when an experiment needs
  it, the terms are clear, timestamps are trustworthy, and the value can be measured.

## Contracts (§32–§44, §50–§56, §71–§72)

- **Source registry entry for every collector (§32).**
  - identity: source_id, domain, publisher, class;
  - access: method, auth, terms/licensing state;
  - limits: freshness max age, pacing, quota, cost;
  - data: types, timestamp semantics, parser version;
  - state: connectivity, last verified.

  No hidden one-off scripts.
- **Access tiers (§33).** Official streaming API → official REST → official bulk/archive → official
  RSS → permitted structured endpoint → permitted page. Browser automation is a fallback that needs a
  terms review. Never bypass auth, CAPTCHA, paywalls, geoblocks, rate limits or access control.
- **Free keys (§34, §58).**
  - Agents never create accounts, solve CAPTCHAs or handle keys in chat or Git.
  - Such sources are READY_FOR_OWNER_KEY, recorded with their value, cost (free), volume, storage,
    and the exact secret name and location.
  - Keyless sources come first (§69).
- **Point-in-time contract (§35–§36).**
  - Every observation records: source and entity identity; intended, request, receipt and source
    times; payload hash; parser, schema and policy versions; freshness; result; failure/miss reason.
  - A missed observation stays MISSED.
  - HISTORICAL_BACKFILL is always separate from PROSPECTIVE_CAPTURE.
- **No selection bias (§37–§38).** Collect every day and market in a supported family: boring,
  volatile, qualifying and rejected alike. Non-actionable states are first-class evidence.
- **Outcomes (§39, §72).** Each domain has a settlement or label plan. With no plan, the state is
  DISCOVERY_ONLY. Settlement is never inferred from headlines.
- **Failures are data (§40).** Timeout, HTTP error, schema change, empty, stale, quota or budget
  block, partial pagination, late publication, outage.
- **Freshness Fabric owns scheduling (§41–§42).** Canonical modes (STREAM / POLL / EVENT_RELATIVE /
  RELEASE_DRIVEN / MANUAL / EXTERNAL_SCHEDULE). No per-domain generic scheduler.
  - Cadence is deterministic at first.
  - Adaptive cadence (#82) may only propose within fixed limits, never overriding terms, quota,
    cost, rate limits, protected windows or resource caps.
- **Resource budget (§43–§44).**
  - Before enabling any collector, estimate requests per run and per day (worst case), network and
    stored bytes per day and month, CPU, memory, DB growth and retries.
  - Then the **combined** VPS footprint. Existing Market Edge and Brisket workloads stay isolated.
  - A storage policy per stream: raw, periodic or derived; compression; retention; archive.
- **Readiness matrix (§50).** Per domain: market catalog history, point-in-time price,
  depth/liquidity, rules/settlement, external features, feature vintages, model, rejected decisions,
  later prices, outcome labels, source failures, learning-ready. States NO_DATA / COLLECTING /
  PARTIAL / RESEARCH_READY / MODEL_AVAILABLE. No numeric score.
- **Completeness (§51).** Each source defines "complete". Partial stays PARTIAL and never implies
  absence.
- **Timing (§52–§53).** Store enough to study lead/lag. Canonical UTC instants plus the source's own
  zone and representation. Handled in deterministic code.
- **Anomalies (§54).** Future timestamps, impossible values, crossed books, negative sizes, schema,
  duplicates, units, revisions, pagination loops, moved times, changed stations or rules. Preserved,
  never silently fixed.
- **Model-independent collection (§55).** Collectors keep canonical source evidence and don't need
  to know which features the model favours.
- **Market relevance (§56).** Every stream names the future market family or hypothesis it could
  support. If none can be named: DO NOT COLLECT YET.
- **Release/event calendar (§71).** One shared primitive (event id, domain, scheduled and actual
  times, source, expected fields, related markets, capture targets), not one per domain.

## Tiers and waves (§45, §63–§65)

- **Tier A (start or expand soon):** prediction-market catalogs, books and rules; multi-city
  weather; NFL odds; Polymarket US sports; macro releases and vintages; BTC/ETH public data; EIA;
  SEC EDGAR.
- **Tier B (readiness, then selective activation):** more sports; equity/ETF benchmarks; more crypto;
  official political and campaign-finance data; legislative events; company IR; more commodities.
- **Tier C (market data now, specialized sources later):** culture; generic business feeds; polls;
  news and social sentiment; specialty long-tail.
- **Waves, after the active lanes reconcile:**
  1. universal source/market inventory;
  2. multi-city weather;
  3. macro foundation;
  4. crypto foundation;
  5. EIA and SEC;
  6. other domain-specific sources only where markets or hypotheses justify them.

  Parallel where the code paths don't conflict.
- **Rollout per source (§64):** fixture → historical or sample validation → bounded smoke →
  low-frequency prospective collection → source-health evidence → several clean runs → higher
  cadence if justified. One failing source never invalidates the others.
- **Expected roadmap (§63):**
  - **NOW:** #50 completeness, #74, market-side evidence across planned domains, multi-city weather
    data, existing sports data, source-readiness design for macro/crypto/energy/business.
  - **NEXT:** macro collection, BTC/ETH, EIA, SEC, more weather markets, broader sports as quota
    permits.
  - **LATER:** specialized culture sources, broad news, polling, social sentiment, licensed feeds,
    obscure long-tail.
  - The 2026-10-22 date is not extended automatically.

## Deliverables (§66–§68, §73–§75, §82)

1. **Cross-domain data acquisition plan.** A portfolio table covering: domain; source; endpoint or
   feed class; official or third-party; auth; cost; rate/quota; terms state; data collected;
   publication cadence; desired capture cadence; why it matters; historical archive;
   point-in-time irrecoverability; storage and requests per day; implementation status; owner
   action.
2. **Multi-City Weather v1.** Acceptance:
   1. candidate recurring cities identified;
   2. each market's settlement semantics verified independently;
   3. exact station mapped;
   4. NWS forecast source mapped;
   5. market and forecast evidence preserved prospectively;
   6. no EXP-001 change;
   7. bounded resource estimate;
   8. sources isolated from each other;
   9. freshness visible;
   10. settlement captured.
3. **Future-domain source readiness.** Each source classified as ACTIVE NOW / READY TO IMPLEMENT /
   NEEDS FREE OWNER KEY / NEEDS TERMS REVIEW / NEEDS SPECIFIC EXPERIMENT / PAID/ROI BLOCKED / NOT
   CURRENTLY WORTH COLLECTING. The highest-value free, keyless sources are implemented first.
4. **Later, in Terminal:** domain, sources, freshness, coverage, history since, misses, readiness,
   outcome coverage, storage, quota/cost; an owner-facing data inventory; watchdogs (source stopped,
   missed observation, schema change, data stopped changing, quota near limit, storage growth). No
   "green wall".

## Still not authorized (§57–§59, §77, §80)

- **Paid data or accounts:** buying data or paid APIs (ROI case and owner decision first); agents
  creating external accounts or handling or exposing credentials.
- **Trading:** orders, bets, trading-account auth, deposits, withdrawals, funded accounts, Gate 8+;
  risk-limit changes.
- **Models:** changing EXP-001 or the current sports model status; new operational models or
  strategy rules for new domains.
- **Collection excesses:** scraping the internet or social media broadly; unnecessary donor PII;
  storing every crypto tick without justification.
- **Integrity and architecture:** inferring missing values; fabricating point-in-time history;
  overloading the VPS; one scheduler or one evidence database per domain.

## Coordinator re-plan against active work (2026-09-24 ~18:45 ET)

- **Lanes still active:**
  - Freshness Fabric: PR #81 merged, not yet deployed.
  - Consensus: #79 merged.
  - Terminal: #80 merged, #85 in review, phases 2 and 4 pending.
  - Polymarket US NFL: Lane B, not delivered.
- **Queued behind those lanes (no forked abstraction):**
  - new collectors register as #74 fabric providers;
  - new market-side evidence reuses the venue adapters and SnapshotStore;
  - readiness extends `research_readiness.py` (#79);
  - the calendar primitive is designed once, in the Wave 1 plan.
- **Started now (non-overlapping, docs and research only, no production change):**
  - Lane F: the acquisition portfolio and source-readiness classification (Deliverables 1 and 3),
    including the combined resource budget;
  - Lane G: the Multi-City Weather v1 design, with live verification of recurring Kalshi weather
    market families, rules and stations (Deliverable 2, design stage).

  Implementation of Multi-City Weather v1 starts once the current mission's lanes are merged and
  deployed.
