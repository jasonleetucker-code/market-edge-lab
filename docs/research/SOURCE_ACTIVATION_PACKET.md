# Source activation: owner decision packet for change and crawler intelligence (#181 E, 2026-10-08)

Prepared by writer SE under the 2026-10-08 directive (`docs/owner/2026-10-08-jev-crawler-wallet-directive.md`,
EXECUTION_PLAN entry E). **This packet asks for decisions. It grants nothing, and no option below is chosen by an
agent.** Every source here is **NOT ACTIVATED** for change detection. No request was made to any data route while
writing it.

Evidence used: only what the repository already records, with its read dates. That covers `src/edge_lab/sources.py`
`license_notes`, `docs/NEWS_WEB_INGESTION.md`, `docs/research/ACQUISITION_PORTFOLIO.md`,
`docs/research/INPLAY_SOURCE_FEASIBILITY.md`, `docs/research/SOURCE_READINESS.md`,
`docs/research/WALLET_SOURCE_MATRIX.md` and `docs/research/NINE_LINK_AUDIT_2026-10-05.md`. Anything those
documents do not establish is marked **UNVERIFIED**. Terms read on an earlier date may have changed, so each
activation re-reads them first. Free-first does not waive terms.

## What exists now (no decision needed)

- **The contract.** `edge_lab.source_changes` (`source-change-v1`, ADR 0041 addendum 2026-10-08) holds:
  - the change/event envelope;
  - the change ledger (duplicate, echo, supersession, late arrival, order unknown, sequence conflict and
    contradiction);
  - fail-closed key freshness;
  - fetch-cost basis (unknown is never zero);
  - observation-to-market response windows;
  - conditional first-report leadership.

  It is fixture-fed. Its reports refuse RECORDED input.
- **Collection.** No new collector, poll, stream, scraper, timer or budget change exists. The deployed collectors
  keep their current authority and budgets.
- **What a future collector must record** for the contract to give anything but UNKNOWN:
  - its **request time** as well as receipt (without both, two polls of one source never order);
  - the source's documented sequence or publication field, where one exists;
  - native ids, so identity is known;
  - read coverage;
  - the actual fetch cost from the provider's own accounting.

## Summary

| # | Candidate | Route | Auth | Terms state | Money | Verdict for change detection |
|---|---|---|---|---|---|---|
| 1 | Kalshi stored snapshots (`kalshi_public`, `kalshi_settlement`) | already-stored rows, offline | none | Kalshi data-rights question UNRESOLVED | 0 new requests | **Cheapest first step**; needs an experiment id and an evidence-use record |
| 2 | Kalshi public REST, change polling at a new cadence | `GET /markets`, `/events`, `/series` | none | same question | free (documented `security: []`) | Needs a new budget; shares the public IP rate limit |
| 3 | Kalshi WebSocket public channels | `market_lifecycle_v2`, `ticker`, `trade` | **signed API key** | same question; Developer Agreement unread | free | **BLOCKED**: credential with account-read scope |
| 4 | Kalshi public trade tape | `GET /markets/trades` | none | same question | free | Market-response side only; no trader identity |
| 5 | NWS products and alerts | `api.weather.gov/products/...`, `/alerts` | User-Agent | public domain | free | Products already collected; alerts DO NOT COLLECT YET |
| 6 | Federal Reserve RSS | `federalreserve.gov/feeds/*.xml` | none | open | free | READY TO IMPLEMENT in the portfolio, but no family is allocated |
| 7 | SEC EDGAR | `data.sec.gov/submissions`, latest-filings feed | User-Agent | fair access, no crawling | free | Strong timestamps; needs a named family (#88) |
| 8 | Nasdaq Trader halts RSS | `nasdaqtrader.com/rss.aspx?feed=tradehalts` | none | **T&C PDF not read** | free | NEEDS TERMS REVIEW |
| 9 | GDELT DOC 2.0 | public API | none | attribution | free | Discovery only; never evidence of facts |
| 10 | X / social | none approved | n/a | **no terms review**; tools get 403 | UNVERIFIED (paid API) | **BLOCKED** |
| 11 | Licensed news APIs and wires | vendor APIs | vendor keys | per vendor, UNVERIFIED | paid (UNVERIFIED $29–$449+/month) | Owner decision with cost |
| 12 | Polymarket US public gateway listings | `GET /v1/events` | none | Terms do **not** clear unattended collection | free | Only under the 2026-09-24 risk decision's conditions |

Wallet watches (Polymarket Data API v2) belong to the wallet lane's W10 approval (`WALLET_SOURCE_MATRIX.md`). The
Odds API stays on its joint 450-credit pilot ledger. Neither is re-decided here.

## Per-source detail

### 1. Kalshi stored snapshots (offline derivation)

- **Routes.** Envelopes derived from rows already in the evidence store: `snapshots` (`source_id` `kalshi_public`
  and `kalshi_settlement`) and `document_retrievals` (contract PDFs).
- **Rights.** The repository's API-collected Kalshi data is governed by terms that are UNRESOLVED
  (`INPLAY_SOURCE_FEASIBILITY.md` §1.9):
  - the website Data Terms restrict systematic collection, software development and any AI/ML use;
  - the Developer Agreement returned HTTP 429 on 2026-09-24 and 2026-09-28 and is **not read**.
- **Auth.** None.
- **Polling bounds.** None: no request is made.
- **Cost.** Zero new requests. CPU and storage are small but not measured (ESTIMATE).
- **Missing fields.** The markets payload carries `updated_time` (used by `settlement_audit.py`). Whether it is a
  per-change publication time is **UNVERIFIED**. Order books carry no timestamp or sequence (§1.6). Stored rows have
  no request time, so most consecutive polls stay ORDER_UNKNOWN unless their fetch windows can be reconstructed from
  `fetch_duration_ms` (UNVERIFIED that this is sufficient).
- **Truncation and retention.**
  - Canonical JSON is kept, not the exact bytes (ADR 0002).
  - Rows are immutable and kept indefinitely.
  - Batch order books may be truncated (no depth parameter).
- **Risks.**
  - Reading stored KXHIGHNY or NFL/NHL rows touches protected label scopes. EXP-001's pipeline is a known unlogged
    consumer, and the EXP-002 holdout boundary is 2026-10-22.
  - Rules-change history could leak outcome information into research if misused.
- **Expected information advantage.** UNMEASURED. It measures how often rules, status or close times change, and
  how often our current views were stale. It is a data-integrity gain, not a trading signal.
- **Owner questions.**
  - **Q1.1** May agents derive RECORDED change envelopes offline from already-stored `kalshi_public` /
    `kalshi_settlement` rows? If yes: under which experiment id and evidence-use record, excluding which label
    scopes (at least KXHIGHNY outcomes and any EXP-002 holdout window)?
  - **Q1.2** Does the open Kalshi data-rights question (Data Terms vs Developer Agreement, §1.9) block this
    derivation until answered?

### 2. Kalshi public REST at a new change-polling cadence

- **Routes.** `GET /markets` (cursor-paginated), `/events`, `/series`, with `security: []`.
- **Rights.** As in 1.
- **Auth.** None.
- **Polling bounds.**
  - Unauthenticated limits are not documented. The repository's probe saw HTTP 429 at about 4 requests/s
    (2026-09-22).
  - The existing pacer is 0.6 s.
  - Any new poll shares the one public IP with routine, settlement, forward and NHL collection, and must defer
    inside the protected windows (Kalshi observe window 17:40–18:50 ET).
- **Cost.** Money: free. Requests: a new budget the owner would set.
- **Missing fields.** As in 1. Without request times recorded by the collector, polls never order.
- **Truncation and retention.** Listings are complete only when every page succeeded and the last page came back
  empty (`discovery.CatalogCoverage`).
- **Risks.**
  - Rate-limit interference with EXP-001 and the NFL/NHL captures.
  - The rights question.
  - A new timer needs EXECUTION_PLAN authority.
- **Expected information advantage.** UNMEASURED. A finer view of listing and rules changes; probably small for
  daily-settling families.
- **Owner questions.**
  - **Q2.1** Is any new Kalshi change-polling cadence wanted at all? If yes: request ceiling per day, families,
    protected-window deferral, review date and stop date.
  - **Q2.2** Confirm that the collector must record request time and that it may not run as a new timer without a
    separate EXECUTION_PLAN entry.

### 3. Kalshi WebSocket public channels

- **Routes.** `wss://external-api-ws.kalshi.com/trade-api/ws/v2`, public channels `market_lifecycle_v2`, `ticker`
  and `trade`. Messages are sequenced (`sid`, `seq`); the scope of `seq` is UNVERIFIED.
- **Rights.** As in 1, plus the unread Developer Agreement.
- **Auth.** Every connection must be signed with an API key. No market-data-only scope is documented, and `read`
  includes account reads (§1.2).
- **Polling bounds.** Push stream. No documented connection or message limits. Error 27 is a command rate limit.
- **Cost.** Free data. It needs a credential.
- **Missing fields.** The gap-recovery procedure is not documented. `ticker` is top of book only.
- **Truncation and retention.** No server-side history. A missed message is lost unless a snapshot resync is taken.
- **Risks.**
  - A residual account-read permission on the VPS.
  - The rights question.
  - A long-lived process.
- **Expected information advantage.** The only route with per-change sequencing, so the most honest ordering and
  latency. UNMEASURED.
- **Owner questions.**
  - **Q3.1** Not proposed now. Confirm it stays BLOCKED until:
    - a credential whose documented scope includes account reads is explicitly approved;
    - a security review of key handling is done;
    - the rights question is answered.

### 4. Kalshi public trade tape

- **Routes.** `GET /markets/trades` with `limit` 1–1000, `cursor`, and `min_ts`/`max_ts` windows (read
  2026-10-07). No authentication.
- **Rights.** As in 1.
- **Auth.** None.
- **Polling bounds.** Shares the public IP limit, as in 2.
- **Cost.** Free.
- **Missing fields.**
  - It carries no user, account or wallet identity.
  - Correction behaviour is not stated (UNVERIFIED).
  - `created_time` is per trade, and its clock precision is UNVERIFIED.
- **Truncation and retention.** Cursor paging. How far back history goes is UNVERIFIED.
- **Risks.** As in 2.
- **Expected information advantage.** It is the *market-response* side of `response_latency`: trades show when a
  market reacted. UNMEASURED.
- **Owner questions.**
  - **Q4.1** May a one-off, bounded backfill of trades for already-settled, non-protected markets be proposed
    (with a request ceiling) to measure response windows? This needs its own approval and an experiment id.

### 5. NWS products and alerts

- **Routes.**
  - `api.weather.gov/products/types/{CLI,PFM}/locations/...` (already collected; ACTIVE);
  - `/alerts` (not collected).
- **Rights.** US government work, public domain. An identifying User-Agent is required.
- **Auth.** User-Agent only.
- **Polling bounds.** Existing cadences only. The CLI list is read at least daily before the API drops issuances.
  The NWS pacer is 0.5 s.
- **Cost.** Free.
- **Missing fields.**
  - Products carry `issuanceTime` (used by `forward.py`), which is a usable claimed publication field.
  - Corrections are new issuances.
  - Alerts: the API keeps only seven days.
- **Truncation and retention.** Product lists drop old issuances, which is why they are archived. Alerts keep
  seven days.
- **Risks.** Low. Alerts are low value for daily maxima (`SOURCE_READINESS.md`).
- **Expected information advantage.**
  - Products: correction detection (preliminary vs final CLI). The envelope can now represent this offline from
    stored rows; it is an integrity gain.
  - Alerts: none shown.
- **Owner questions.**
  - **Q5.1** Same as Q1.1 for stored NWS CLI and PFM rows. They touch EXP-001 inputs and labels, so they need an
    evidence-use record under EXP-001's rules.
  - **Q5.2** Confirm alerts stay DO NOT COLLECT YET.

### 6. Federal Reserve RSS

- **Routes.** `federalreserve.gov/feeds/press_monetary.xml`, `/feeds/prates.xml` and `/feeds/h15.xml` (feeds page
  read 2026-09-24).
- **Rights.** Open.
- **Auth.** None.
- **Polling bounds.**
  - The rate is not stated.
  - The portfolio proposal is every 15 minutes around 14:00 ET on FOMC days and hourly otherwise, with a conditional
    GET, storing changed bytes only.
  - That is about 72 requests a day, mostly 304 Not Modified.
- **Cost.** Free. Under 0.1 MB a day (ESTIMATE).
- **Missing fields.**
  - Per-item publication times in the feed are UNVERIFIED.
  - Our first-seen time is the only certain clock (grade C).
- **Truncation and retention.** Press releases stay online. Feed length is UNVERIFIED.
- **Risks.**
  - No macro family has a #96 slot.
  - A new timer needs EXECUTION_PLAN authority.
- **Expected information advantage.** Release timing for KXFED-type families. UNMEASURED, and no family is
  allocated.
- **Owner questions.**
  - **Q6.1** Is a macro family (KXFED or similar) wanted? Without one, this source stays unactivated.

### 7. SEC EDGAR

- **Routes.**
  - `data.sec.gov/submissions/CIK##########.json` per watched CIK;
  - the latest-filings feed as the change signal;
  - the filing index and primary document.
- **Rights.** Fair-access policy: "does not allow botnets or automated tools to crawl the site"; download only
  what you need (read 2026-09-24).
- **Auth.** None. A declared User-Agent is required.
- **Polling bounds.** At most 10 requests/s. The portfolio proposal is about 215–415 requests a day for a bounded
  universe.
- **Cost.** Free. About 1–4 MB a day changed-only (ESTIMATE).
- **Missing fields.** `acceptanceDateTime` is authoritative (grade A), but its zone semantics are **not verified**.
- **Truncation and retention.** Full filing history.
- **Risks.**
  - No Kalshi family settles on filings.
  - #88's public-markets family has no #96 slot.
- **Expected information advantage.** The best-timestamped source on this list. A clean test bed for
  `first_report_leadership` (filing acceptance vs relays). UNMEASURED for trading.
- **Owner questions.**
  - **Q7.1** Is the #88 SEC-filing-reaction family to be given a slot? If not, EDGAR stays unactivated.

### 8. Nasdaq Trader trade-halt RSS

- **Routes.** `nasdaqtrader.com/rss.aspx?feed=tradehalts`.
- **Rights.** Terms PDF `THRSSFeedTermsCond.pdf` **not read**.
- **Auth.** None.
- **Polling bounds.** "not query the data more than once a minute"; about 390 requests per market day.
- **Cost.** Free ("free service").
- **Missing fields.** History is not documented; the feed shows current halts only.
- **Truncation and retention.** Current only.
- **Risks.** Unread terms.
- **Expected information advantage.** Context for #88 only. UNMEASURED.
- **Owner questions.**
  - **Q8.1** None until an agent reads the terms PDF and a #88 family exists.

### 9. GDELT DOC 2.0

- **Routes.** The public API and files.
- **Rights.** Free, with attribution (`NEWS_WEB_INGESTION.md`).
- **Auth.** None.
- **Polling bounds.** UNVERIFIED.
- **Cost.** Free.
- **Missing fields.** URLs and metadata only. Timestamps are GDELT's, not the publisher's.
- **Truncation and retention.** UNVERIFIED.
- **Risks.**
  - Noise.
  - The prompt-injection surface if any text is fetched.
  - Treating discovery as fact.
- **Expected information advantage.** Discovery of stories only. The portfolio rates news and social "not tier 1"
  and NOT CURRENTLY WORTH COLLECTING.
- **Owner questions.**
  - **Q9.1** Confirm news discovery stays off until a named experiment needs it.

### 10. X (Twitter) and other social

- **Routes.** No official route has been reviewed in the repository. Pricing and terms of the X API are
  **UNVERIFIED**.
- **Rights.**
  - No terms review exists.
  - Scraping is out of bounds: no bypassing access controls (`DATA_PROVENANCE.md` §1), and "no celebrity or social
    scrapers".
- **Auth.** An account and key would be needed (UNVERIFIED).
- **Polling bounds.** Not applicable.
- **Cost.** UNVERIFIED (paid).
- **Missing fields.** Publication times are platform stamps on the copy, never proof of origin.
- **Truncation and retention.** UNVERIFIED.
- **Risks.**
  - Terms.
  - Prompt injection.
  - Rumour amplification.
  - The 2026-10-05 audit could not even read nine status pages (HTTP 403 and cache misses).
- **Expected information advantage.** Claimed by the JEV/GROKBOT material. **Not established**: the claimed
  $100 → $15,220 is unreconciled to trading records (#181).
- **Owner questions.**
  - **Q10.1** Confirm social stays BLOCKED, with no scraping and no account, unless the owner first approves:
    - a paid official API with a terms review;
    - a named experiment.

### 11. Licensed news APIs and wires

- **Routes.** NewsAPI.org, Marketaux, Alpha Vantage news, Benzinga, Reuters/AP/Dow Jones.
- **Rights.** Storage, ML and redistribution rights vary by vendor and are UNVERIFIED.
- **Auth.** Vendor keys.
- **Polling bounds.** Per vendor.
- **Cost.** UNVERIFIED as of 2026-09-22. NewsAPI's free tier is dev-only with a 24-hour delay; others run roughly
  $29–$449+ a month, and enterprise wires far more.
- **Missing fields.** Original publication vs syndication time varies by vendor.
- **Truncation and retention.** Per vendor.
- **Risks.**
  - Cost.
  - Licence limits on storage and model use.
- **Expected information advantage.** UNMEASURED.
- **Owner questions.**
  - **Q11.1** No decision now. Any vendor needs a priced proposal and a terms review first.

### 12. Polymarket US public gateway listings

- **Routes.** `GET /v1/events` and markets on `gateway.polymarket.us` (keyless).
- **Rights.** The Terms (reviewed 2026-09-24) do **not** clear unattended collection. The NFL pilot runs on the
  owner's recorded risk decision, honouring:
  - at most 100 requests a minute;
  - attribution;
  - no redistribution.
- **Auth.** None.
- **Polling bounds.** At most 20 requests/s per IP (docs). Pilot: discovery at most every 6 hours.
- **Cost.** Free.
- **Missing fields.** A filtered listing is never COMPLETE. Absence is not evidence.
- **Truncation and retention.** Paged. Coverage is PARTIAL when filtered.
- **Risks.** The terms. An owner risk acceptance is not a terms clearance.
- **Expected information advantage.** Listing-change detection for cross-venue relative value. UNMEASURED.
- **Owner questions.**
  - **Q12.1** Should listing-change envelopes be derived offline from the pilot's already-stored `nfl_events` pages
    (no new requests) under the existing risk decision? Or is that a new use needing its own decision?

## Consolidated owner questions

| # | Question | Default if no decision |
|---|---|---|
| Q1.1 | Derive RECORDED change envelopes offline from stored Kalshi rows? Under which experiment id, evidence-use record and excluded label scopes? | No |
| Q1.2 | Does the unresolved Kalshi data-rights question block Q1.1 until answered? | Yes (treated as blocking) |
| Q2.1 | Any new Kalshi change-polling cadence? If so: ceiling, families, protected-window deferral, review and stop dates | No |
| Q2.2 | Require request-time recording and a separate EXECUTION_PLAN entry for any such poll | Yes |
| Q3.1 | Kalshi WebSocket stays BLOCKED (credential with account-read scope, key-handling review, rights) | Yes |
| Q4.1 | Allow a bounded proposal for a one-off trade-tape backfill of settled, non-protected markets? | No |
| Q5.1 | Derive envelopes from stored NWS CLI/PFM rows under EXP-001's evidence-use rules? | No |
| Q5.2 | NWS alerts stay DO NOT COLLECT YET | Yes |
| Q6.1 | Allocate a macro (KXFED-type) family? | No (Fed RSS stays off) |
| Q7.1 | Give #88 SEC-filing reaction a #96 slot? | No (EDGAR stays off) |
| Q8.1 | Nasdaq halts: read the terms PDF first; no decision now | — |
| Q9.1 | News discovery (GDELT) stays off until a named experiment needs it | Yes |
| Q10.1 | Social (X and others) stays BLOCKED; no scraping, no account | Yes |
| Q11.1 | Licensed news: priced proposal and terms review first; no decision now | — |
| Q12.1 | Derive listing envelopes from stored Polymarket US pilot pages under the existing risk decision, or require a new decision? | Requires a new decision |

The cheapest useful step, if the owner wants one, is Q1.1 with Q5.1. Both are offline over rows already stored,
make zero new requests, and only need an experiment id and an evidence-use record. Every other route adds requests,
terms exposure or a credential.

## UNVERIFIED items carried forward

- Whether Kalshi `updated_time` is a per-change publication time.
- The scope of Kalshi WebSocket `seq`.
- Correction behaviour and history depth of the trade tape.
- Per-item times and feed length of the Fed RSS feeds.
- The zone of EDGAR `acceptanceDateTime`.
- The Nasdaq halts terms.
- GDELT limits and retention.
- X API price and terms.
- Licensed-news prices and rights.
- Whether `fetch_duration_ms` is enough to reconstruct fetch windows for stored rows.
