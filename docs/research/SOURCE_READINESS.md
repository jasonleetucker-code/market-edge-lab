# Future-domain source readiness (issue #86, Deliverable 3)

**Date:** 2026-09-24. **Author:** Lane F (docs and research only).
**Authority:** directive `docs/owner/2026-09-24-cross-domain-prospective-evidence-directive.md`:
- §5 and §39: outcomes;
- §50: the readiness matrix;
- §51: completeness;
- §52–§53: timing;
- §54: anomalies;
- §56: market relevance;
- §69: keyless first;
- §71: the calendar;
- §72: DISCOVERY_ONLY without a label plan.

**Companion:** `docs/research/ACQUISITION_PORTFOLIO.md`, which holds the per-source rows, the
verification URLs, the combined budget and the activation order. This file authorizes nothing.
Readiness classes and irrecoverability classes (A/B/C) mean what they mean there.

## 0. Rules that apply to every domain

- **Point-in-time contract (§35–§36).** Every observation records:
  - source and entity identity;
  - the **intended**, **request**, **receipt** and **source** times;
  - the payload hash;
  - the parser, schema and policy versions;
  - freshness, the result, and the miss or failure reason.

  A missed observation stays `MISSED`. Rows come from `HISTORICAL_BACKFILL` or
  `PROSPECTIVE_CAPTURE` and never mix: a backfill is never presented as prospective.
- **Timestamps (§53).**
  - Store the canonical UTC instant (`…Z`), and also the source's own representation and zone
    exactly as served: a local wall time string, an offset, or a date with no time.
  - A date-only source value stays date-only. It is never promoted to midnight UTC.
  - Zone conversion is deterministic code (`zoneinfo`), never an LLM. A naive or unparseable time
    is `UNKNOWN` (`freshness.parse_utc`).
- **Completeness (§51).** Each source states what "complete" means (below). `PARTIAL` never
  implies absence (`discovery.CatalogCoverage`).
- **Anomalies (§54).** Common to all domains, preserved and never silently fixed. The source
  stays `partial` with the anomaly in `source_health.anomalies_json`:
  - a future timestamp (beyond a stated skew);
  - an impossible value (a negative price or size, a price off the grid, an inverted bracket);
  - a crossed book (bid ≥ ask on one side);
  - a schema change (`shape_sha256` differs);
  - a duplicate id with different content;
  - a unit change;
  - a revision without a vintage;
  - a pagination loop (repeated cursor), or a page cap hit;
  - a moved scheduled time;
  - a changed station, settlement source or rules hash;
  - an empty response where content is expected.
- **Labels (§39, §72).** A domain without a settlement or label plan is **DISCOVERY_ONLY**.
  Settlement is never inferred from a headline, a market title or an LLM summary.

## 1. Readiness matrix (§50): state today, per domain

States: NO_DATA / COLLECTING / PARTIAL / RESEARCH_READY / MODEL_AVAILABLE. There is no numeric
score. The canonical computed owner for weather and sports is `edge_lab.research_readiness`
(ADR 0033). This table is the planning view for domains that module does not yet cover.
**Extend that module; do not fork it.**

| Domain | Catalog history | PIT price | Depth / liquidity | Rules / settlement | External features | Feature vintages | Model | Rejected decisions | Later prices | Outcome labels | Source failures | Learning-ready |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WEATHER (KXHIGHNY) | PARTIAL (one family) | COLLECTING | COLLECTING | COLLECTING | COLLECTING (PFM) | COLLECTING (PFM issuance) | MODEL_AVAILABLE (EXP-001, frozen) | COLLECTING | COLLECTING (ADR 0030) | PARTIAL (held positions; U-1, P1-1) | COLLECTING | PARTIAL |
| WEATHER (other cities) | NO_DATA | NO_DATA | NO_DATA | NO_DATA (Lane G verifying) | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA |
| SPORTS (NFL) | PARTIAL (the Odds schedule) | COLLECTING (sportsbook, non-executable) | NO_DATA (prediction markets) | PARTIAL (the Polymarket rules read; Kalshi not captured) | NO_DATA | N/A | NO_DATA | N/A | COLLECTING (T-60m, not the close) | NO_DATA (P1-5) | COLLECTING | PARTIAL |
| ECONOMICS / MACRO | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA |
| CRYPTO | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA |
| ENERGY | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA |
| PUBLIC MARKETS (#88) | NO_DATA | NO_DATA | NO_DATA | NO_DATA (session calendar and contract specs not yet encoded) | NO_DATA (EDGAR) | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA |
| BUSINESS | NO_DATA (DISCOVERY_ONLY) | — | — | — | — | — | — | — | — | — | — | NO_DATA |
| POLITICS | NO_DATA (DISCOVERY_ONLY) | — | — | — | — | — | — | — | — | — | — | NO_DATA |
| CULTURE / LONG-TAIL | NO_DATA (DISCOVERY_ONLY) | — | — | — | — | — | — | — | — | — | — | NO_DATA |

## 2. WEATHER

**Sources and readiness:**
- **ACTIVE NOW:** Kalshi KXHIGHNY, PFMOKX.
- **READY TO IMPLEMENT** (Lane G): Kalshi city families; PFM for other WFOs; gridpoint forecasts;
  station observations; CLI per station; the IEM backfill.
- **NEEDS TERMS REVIEW:** The Weather Company, which is BLOCKED.
- **NOT CURRENTLY WORTH COLLECTING:** alerts.

**Outcome and label plan.**
1. Kalshi's own settled result (`result`, `expiration_value`) with its settlement time, through the
   existing `kalshi_settlement` path. This is the label. Its knowledge time is the settlement time
   Kalshi reports, or our receipt if that is later.
2. An independent cross-check against the station's NWS CLI, prospective or from the IEM backfill.
3. Where a family's rules name The Weather Company, which is not collectable, the CLI check is
   `CROSS_CHECK_ONLY` and the venue result stays the label. **Each city's rules and station are
   verified independently by Lane G.** No city inherits KXHIGHNY's semantics.

**Completeness.**
- A city-day is COMPLETE when every planned horizon has a terminal state (`CAPTURED`,
  `NOT_EXECUTABLE` or `MISSED` with a reason), every open bracket in each capture was booked or
  listed, the forecast selected at each horizon is recorded (or recorded as missing), and
  settlement is captured.
- For forecasts: every issuance the API listed between two reads is stored (list vs products
  diff). A gap between product ids is an anomaly.

**Timestamps.**
- Kalshi `close_time`, `expected_expiration_time` and `updated_time` are UTC.
- The weather *day* is whatever day the family's rules define. NWS climate days are normally
  local standard time midnight to midnight, not the DST wall day; Lane G verifies this per family.
  Store the rule's zone and the day as a date, never as a UTC instant.
- PFM issuance: the WMO header time (UTC) plus the product's local issuance line; availability =
  issuance + 30 min for EXP-001 (ADR 0010) and per experiment elsewhere.
- Gridpoints: `updateTime`/`generatedAt` in UTC, and each `validTime` interval in ISO 8601
  duration form.
- Observations: `timestamp` in UTC; the station id is stored per row.

**Anomalies, domain-specific:**
- a station change in the rules;
- a bracket set that does not tile (a gap or an overlap);
- a CLI correction (`CCA`/`CCB`) arriving after settlement;
- a PFM with no block for the settlement zone;
- a gridpoint `updateTime` older than the previous read (a regression);
- an observation QC flag;
- a Kalshi close convention change (the August 2026 precedent).

## 3. SPORTS

**Sources and readiness:**
- **ACTIVE NOW:** The Odds API NFL.
- **READY TO IMPLEMENT:** Kalshi KXNFLGAME and KXNCAAFGAME.
- **NEEDS TERMS REVIEW:** Polymarket US (ADR 0032, disabled); injury reports.
- **NEEDS SPECIFIC EXPERIMENT:** one extra Odds sport (h2h at T-60m); Novig; outdoor-game weather.
- **NOT CURRENTLY WORTH COLLECTING:** Odds MLB, NCAAB, props and `/scores`.

**Outcome and label plan.**
- Venue settlement for prediction markets: Kalshi `result` for game markets, and Polymarket US
  settlement prices.
- Final scores come from a public results source joined at analysis time. P1-5; the source is still
  to be chosen, and `/scores` stays out of the budget.
- Push, tie, void, overtime and postponement follow **each venue's own rules**. For example,
  Polymarket US settles a tie at $0.50 while sportsbooks void (ADR 0032).
- A sportsbook line is never a label.

**Completeness.**
- Odds: a target is complete when it reaches a final transition (ADR 0029); coverage per target
  names the books, markets and missing markets.
- Kalshi game markets: every Odds event with a RELATED_NOT_EQUIVALENT Kalshi market has a terminal
  state at every horizon. AMBIGUOUS or NO_RELATED_MARKET is recorded, never forced.
- A filtered listing is PARTIAL by definition.

**Timestamps.**
- Odds `commence_time` and `last_update` are UTC.
- Kalshi times are UTC.
- Offsets are computed in UTC, so a DST change cannot shift a target (ADR 0029).
- The local kickoff time is shown for display only.

**Anomalies:**
- a moved kickoff (targets become SUPERSEDED);
- an event absent from a fresh discovery;
- the same teams with a different start (never linked);
- an overcharge (`x-requests-last` above the estimate), which is a COST_ANOMALY;
- a book with stale `last_update`;
- a line format change (American vs decimal).

## 4. ECONOMICS / MACRO

**Sources and readiness:**
- **READY TO IMPLEMENT** (keyless): the Kalshi macro families; BLS API v1; the BLS ICS; the BEA
  release JSON; the Fed RSS feeds; DOL claims.
- **NEEDS FREE OWNER KEY:** FRED/ALFRED (`EDGE_LAB_FRED_API_KEY`); BEA (`EDGE_LAB_BEA_USER_ID`);
  Census (`EDGE_LAB_CENSUS_API_KEY`); BLS v2 (optional).
- **NEEDS SPECIFIC EXPERIMENT:** FiscalData.
- **NOT CURRENTLY WORTH COLLECTING:** the Fed DDP (retiring).

**Outcome and label plan.**
- The label is Kalshi's settled result per market.
- Kalshi's rules name the settlement source; for example, KXCPI names BLS. **Read each family's
  rules first.** The series metadata lists implausible sources for several families (portfolio
  §0).
- The official first print (BLS/BEA/DOL/EIA) is stored as the independent check. Kalshi's rules
  normally settle on the *initial* release, not a revision: confirm per family.
- Revisions are features, never labels.
- No plan exists yet for Fed-speech or mention families: DISCOVERY_ONLY.

**Completeness.**
- A release event is complete when:
  - its calendar entry has a scheduled time and an observed first-seen time (or UNKNOWN);
  - every planned pre-release market horizon has a terminal state;
  - the official value was read at least once after the release;
  - the venue settlement is captured.
- For vintages: ALFRED observations cover the realtime interval requested, and a missing vintage
  is recorded as missing.

**Timestamps.**
- Releases are scheduled in America/New_York wall time (08:30, 10:00, 14:00 ET). Store the wall
  time with its zone, and the UTC instant.
- ALFRED `realtime_start`/`realtime_end` are **dates**. They are stored as dates, and a
  day-granular vintage must not be read as known at 08:30 on that day.
- The official value's "first seen" time is our receipt time. It is labelled as such, never as the
  source's publication instant.
- The Kalshi macro markets observed close **1–5 minutes before** the release (portfolio §0), so a
  pre-release book is by construction before the number. Any "post-release" price belongs to a
  different, still-open family.

**Anomalies:**
- a release delayed or cancelled (for example a government shutdown), which is a moved or cancelled
  calendar entry;
- a value published and then withdrawn;
- a benchmark or seasonal-factor revision that changes history;
- a series id discontinued;
- BLS or BEA returning the prior value after the scheduled time (not yet updated), which must not
  be recorded as the new print;
- a vintage date later than the receipt date.

## 5. CRYPTO

**Sources and readiness:**
- **READY TO IMPLEMENT:** Kalshi hourly families, sampled.
- **NEEDS TERMS REVIEW:** Coinbase Exchange public; Kraken public.
- **PAID/ROI BLOCKED:** CF Benchmarks (the settlement index).

**Outcome and label plan.**
- The label is Kalshi's settled result. Kalshi's metadata names CF Benchmarks' real-time index,
  which is licensed and not collected.
- Exchange spot is a **feature**, never a label, because the settlement index is a multi-exchange
  aggregate. Perpetuals and futures are separate instruments and are not mixed with spot.
- Without the exchange data the domain is still labelled (by the venue); it has no external
  feature yet.

**Completeness.**
- A sampled hour is complete when the ladder listing (with every strike) and the planned
  near-the-money books have terminal states.
- A listing whose market count differs from the event's is PARTIAL.
- Exchange snapshots are complete when every configured product and exchange returned a book or a
  recorded failure.

**Timestamps.**
- Kalshi hourly events close on the hour in UTC (the observed close 23:00Z for
  `KXBTCD-26SEP2419`).
- Exchange book and trade times are the exchange's (Coinbase ISO 8601 UTC; Kraken Unix seconds
  with fractions). Both are stored raw and converted deterministically.
- Candles are keyed by their start time, and the start/end convention is recorded.

**Anomalies:**
- a crossed book;
- a stale sequence (Coinbase book `sequence` not increasing between reads);
- an exchange halt;
- a product delisted or renamed;
- a strike ladder whose spacing changes within an event;
- exchange dispersion beyond a stated bound (kept as data, never treated as an error).

## 6. ENERGY

**Sources and readiness:**
- **NEEDS FREE OWNER KEY:** EIA API v2 (`EDGE_LAB_EIA_API_KEY`).
- **READY TO IMPLEMENT:** the WPSR schedule page, as a calendar input.
- **PAID/ROI BLOCKED:** futures.
- **NEEDS TERMS REVIEW:** AAA.

**Outcome and label plan.**
- The label is Kalshi's settled result for KXEIACRUDEW and KXNGASW, once each family's rules are
  read. KXEIACRUDEW's metadata names FRBNY, which is implausible and must be verified.
- The EIA first print is the independent check.
- Families that settle on Pyth, ICE or AAA are DISCOVERY_ONLY until their source is legitimately
  collectable.

**Completeness.** A weekly release is complete when the expected series ids returned the new
period. The period is compared against the calendar, so a stale prior week is not the new print.
EIA's 5,000-row cap means a truncated response is PARTIAL.

**Timestamps.**
- The WPSR is Wednesday "after 10:30 a.m." ET, with holiday shifts to Thursday.
- EIA periods are dates (the week ending) and are stored as dates.

**Anomalies:** a holiday shift not in the calendar; a revision to the prior week; a unit
(thousand barrels) change.

## 6a. PUBLIC MARKETS: equities/ETFs, listed options, futures (issue #88)

A first-class domain. It is not part of business/technology. Research-grade and execution-grade
data are never mixed. Paper orders are Gate 8 and are not authorized.

**Sources and readiness** (portfolio §1.7 has the licensing table):
- **READY TO IMPLEMENT** (keyless): SEC EDGAR filing events for a bounded universe; exchange
  calendars and sessions.
- **NEEDS FREE OWNER KEY, plus a security ADR** (header transport; an order-scoped paper key):
  Alpaca Basic (IEX equities; indicative options); the Tradier sandbox.
- **NEEDS TERMS REVIEW:** IEX HIST (offline only); the Nasdaq halts RSS; Cboe statistics; CME
  settlements.
- **NEEDS SPECIFIC EXPERIMENT:** CFTC COT (archive, A).
- **PAID/ROI BLOCKED:** SIP, OPRA, CME real-time/delayed API and DataMine, Cboe DataShop, Alpaca
  Algo Trader Plus.

**Outcome and label plan.** There is no venue settlement, so a label is a realized quantity
computed deterministically from a named feed over a preregistered window. Examples:
- the return from the 09:30 open to 10:00, from feed F;
- realized volatility over [T, T+Δ].

The label records its feed identity: IEX, SIP, or indicative.
- A label from an IEX-only or indicative feed is **research-grade** and says so.
- Options: realized move vs the pre-event implied move. The implied move uses bid/ask, never the
  midpoint by default, and states whether the IV and Greeks are vendor-derived or computed
  internally (with model and version).
- Futures: exchange daily settlement prices for the exact contract month. A continuous series
  needs a **versioned roll rule** and is **never executable** evidence.
- Filing events: `acceptanceDateTime` from EDGAR is the event time.

Without a named family and window, a stream is DISCOVERY_ONLY.

**Completeness.**
- Equities: a symbol-window is complete when every expected bar or quote interval in the session
  has data or an explicit gap reason (a halt, no IEX quote, or a feed outage). The session comes
  from the versioned calendar.
- Options: a snapshot is complete when every contract in the bounded chain spec (expiries ×
  strike band) is present. A paged chain whose last page was not reached is PARTIAL.
- EDGAR: every accession for a watched CIK between two change-signal reads (submissions diff).
- Futures: every contract in the spec, with the contract month explicit.

**Timestamps.**
- US equity and option sessions run in America/New_York: pre-market, regular 09:30–16:00, post;
  early closes come from the calendar.
- Futures sessions follow CME's Central-time sessions with breaks; store the zone.
- Store the feed's own timestamp semantics:
  - SIP vs participant (exchange) timestamps;
  - Alpaca's time field and feed id;
  - the OCC option symbol and expiration date (a date, not an instant);
  - the futures contract month code and last trade date.
- Our receipt time is always separate from the source time.

**Anomalies:**
- a halt or LULD pause inside a window;
- a split or dividend (the adjustment version is recorded, and raw prices are never overwritten);
- a symbol change;
- a crossed or locked quote;
- a stale IEX quote (IEX has no displayed interest);
- an option with a zero bid;
- IV or Greeks missing or non-finite;
- a strike ladder change after a corporate action;
- an expired or rolled futures contract;
- a session-calendar mismatch (data during a holiday);
- a delayed feed labelled real time.

**Paper/sandbox route, first data, first experiment.** See portfolio §1.7:
- research **Alpaca paper-only** first (no funding; explicit feed identity);
- the first prospective data are EDGAR filing events (keyless) and indicative SPY/QQQ option
  snapshots around scheduled macro events (after the key and the ADR);
- the safest first family is **macro-release reaction in SPY/QQQ/IWM/TLT**, with event windows,
  conservative spreads, and no midpoint fills.

## 7. BUSINESS, POLITICS, CULTURE, NEWS (DISCOVERY_ONLY until a family is named)

- **Business.** SEC EDGAR is keyless and a strong source: acceptance timestamps are authoritative
  (A). But no Kalshi family has been named that settles on a filing: **NEEDS SPECIFIC EXPERIMENT** for
  Kalshi-side use. For #88 (SEC filing reaction), see §6a, where it is READY TO IMPLEMENT.
  - When one is named: completeness is every accession for the watched CIKs between two reads
    (submissions `filings.recent` diff). The timestamp is `acceptanceDateTime`. Its zone semantics are
    **not verified** here; check them against the filing index page on the first fixture, and
    store the value raw plus UTC.
  - Anomalies: amendments (`/A`), a changed CIK or ticker.
- **Politics.**
  - Election markets need an owner choice before 2026-11-03. The label is Kalshi settlement, with
    certified results as the check.
  - FEC and Congress.gov need the api.data.gov key (owner) and a named family.
  - Individual-donor PII is never collected.
- **Culture and long-tail.** Catalog only. Settlement sources (charts and streaming platforms) are
  not collected (§29).
- **News and social.** Not tier 1 (§31): see `docs/NEWS_WEB_INGESTION.md`.

## 8. Keyless-first order (§69)

Every READY TO IMPLEMENT source above is keyless. The owner-key sources add:

| Source | Adds | Cost | Volume | Storage |
|---|---|---|---|---|
| FRED/ALFRED | the vintages | free | about 300 requests/month | about 5 MB/month |
| BEA | GDP/PCE first prints | free | about 40 requests/month | under 1 MB/month |
| EIA | the energy first prints | free | about 60 requests/month | about 3 MB/month |

Every key's secret goes in `/etc/market-edge-lab/secrets.env` (root:root 0600, ADR 0028). It is
loaded only by the unit that needs it, and travels only as a query parameter. Agents never create,
see or handle it.

## 9. One shared release/event calendar primitive (§71): contract only

**Problem.** Scheduled anchors are scattered today:
- kickoffs live in `odds_capture_targets` (ADR 0029) and `pm_sports_targets` (ADR 0032);
- trading closes live in `price_observation_targets` (ADR 0030);
- the EXP-001 decision time lives in `forward.windows`.

Each new domain (macro releases, EIA weeks, crypto hourly closes, weather horizons) would otherwise
add a fifth private calendar.

**Recommended canonical owner.** A new module, `src/edge_lab/event_calendar.py`, owns the concept
"what is scheduled to happen, when, as we knew it at each moment".
- Persistence: two additive, append-only tables in the evidence store, through `storage.py`'s
  additive-schema discipline.
- Why a new module: `freshness.py` owns freshness and scheduling *types*, not event facts, and
  keeping them separate is the one-owner rule.
- `sources.py` keeps each input source's registry entry.
- The calendar **never schedules and never fetches**:
  - collectors (one per source) write calendar observations;
  - Freshness Fabric providers read them.

**Record (one row per observation of an event's schedule; append-only):**

| Field | Meaning |
|---|---|
| `event_id` | deterministic: `<domain>:<source_id>:<native_id>` (for example `macro:bls_ics:CPI-2026-10`, `kalshi:KXCPI-26SEP`, `sports:the_odds_api:<event id>`). A reschedule keeps the id |
| `domain`, `kind` | `RELEASE`, `KICKOFF`, `MARKET_CLOSE`, `MARKET_EXPIRATION`, `SETTLEMENT`, `FORECAST_ISSUANCE`, `DECISION`, `FILING` (EDGAR acceptance; #88), `SESSION` (exchange open/close/early close; #88), `CONTRACT_EXPIRY` (option/futures expiration, last trade date; #88) |
| `title` | display only; never evidence |
| `source_id`, `snapshot_id` / `document_retrieval_id` | where this schedule fact came from (provenance) |
| `scheduled_utc`, `scheduled_source_repr`, `scheduled_tz` | the canonical instant, plus exactly what the source said (for example `08:30 AM` with America/New_York, or a date-only value, kept date-only) |
| `schedule_confidence` | `CONFIRMED` (official calendar), `SOURCE_STATED` (venue field), `ESTIMATED` (derived by a stated rule), `UNKNOWN` |
| `observed_at_utc` | when *we* learned this schedule (knowledge time; point-in-time) |
| `status` | `SCHEDULED`, `MOVED`, `POSTPONED`, `CANCELLED`, `OCCURRED`, `UNKNOWN` |
| `actual_utc`, `actual_basis` | the occurrence instant and how it is known: `SOURCE_STATED` (for example an EDGAR acceptance time or a Kalshi `close_time` confirmed after the close), `FIRST_RECEIPT` (our receipt of the new value; labelled as such), `UNKNOWN` |
| `expected_fields` | what should appear (series ids, market ids), for the completeness check |
| `related_markets` | (venue, market_id, relationship): `SETTLES_ON`, `RELATED_NOT_EQUIVALENT`, `AMBIGUOUS`. Relationship rules stay with their owners (ADR 0032, `discovery.is_equivalent`) |
| `capture_policy_ref` | the fabric `SourcePolicy.source_id`s that anchor targets on this event (the targets themselves stay with their capture owners) |

**Rules.**
- The current view of an event is its latest observation by `observed_at_utc`.
- History is never rewritten. A moved time is a new row with `status=MOVED`, and every downstream
  target anchored on the old time becomes SUPERSEDED under its owner's rules (the same semantics as
  ADR 0029).
- Unknown stays unknown: no inferred release time, no midnight-UTC default for a date-only value.
- A backfilled calendar row carries `HISTORICAL_BACKFILL` and is never a prospective observation.
- Anomalies are §0 plus these: a scheduled time moved after it passed; two sources disagreeing
  (BLS ICS vs BEA JSON vs venue); an event occurring with no calendar row. Each is recorded, never
  resolved silently.

**Mapping onto Freshness Fabric (`src/edge_lab/freshness.py` on main, `AcquisitionMode`).**

- **`EVENT_RELATIVE`** ("fetched at offsets from an event"). A policy anchors on calendar `kind`s
  `KICKOFF`, `MARKET_CLOSE`, `DECISION` and `MARKET_EXPIRATION`.
  - Target time = current `scheduled_utc` + offset, in UTC arithmetic.
  - `SourceFreshness.intended_at` is that target, and `next_due` is the minimum over open targets.
  - `ScheduleState.MISSED` follows the owner's deadline rules.
  - A `MOVED` calendar row is how a provider shows why targets were superseded.
  - `why_due` names the `event_id` and the offset.
- **`RELEASE_DRIVEN`** ("fetched after an upstream publication"). A policy anchors on
  `kind=RELEASE` or `FORECAST_ISSUANCE`.
  - DUE opens at `scheduled_utc` (plus a stated grace) and stays DUE until the expected fields are
    received (`actual_basis=FIRST_RECEIPT`) or the deadline passes (`MISSED`).
  - Pre-release market captures on the same event are `EVENT_RELATIVE` policies with negative
    offsets; they use the same anchor and are a separate policy.
  - `upstream_ts` is the source-stated publication time when one exists, else None. It is never
    our receipt relabelled.
- **`EXTERNAL_SCHEDULE`.** Stays exactly as in v1 for the deployed timers. The calendar gives
  providers the *why* (the anchor event) without changing who runs what.
- **Reads.** Providers read calendar rows read-only through `FabricContext` (the evidence DB opened
  `mode=ro`). No network call, lock or write is added (the ADR 0031 provider rules).

**Migration (no fork, no silent takeover).**
1. **v0.** The contract and fixtures, plus writers for the new sources: BLS ICS, BEA JSON, Kalshi
   close/expiration from listings already stored, and the EIA WPSR table.
2. **Mirror.** A read-only mirror populates calendar rows from `odds_capture_targets`,
   `price_observation_targets` and `pm_sports_targets` anchors. Their owners keep planning. Parity
   is tested, and any disagreement is reported in `disagreements`.
3. **Adoption.** A domain's planner adopts the calendar as its anchor source only in its own
   reviewed ADR, one domain at a time (as ADR 0031's migration path requires).

Decide this in an ADR before the first Wave 3 (macro) collector, because macro is the first domain
whose anchors are external releases, not venue fields. The same primitive serves #88: filings,
sessions and contract expiries are calendar kinds, not a second public-markets calendar.

## 10. Sources

As listed in `docs/research/ACQUISITION_PORTFOLIO.md` §6 (all read 2026-09-24).
