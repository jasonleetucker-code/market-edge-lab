# Owner Ideas

Durable owner ideas live in GitHub issues titled `[Owner Idea] …`. This file is an
**index**, not a copy: the issue body is the record. The process authority is issue #4
([Owner Process] Durable idea intake and readiness backlog). The canonical rule is in
`AI_INSTRUCTIONS.md` → Owner ideas.

- **Capture:** create or update an issue in seconds. Link related ideas. Do not invent
  details the owner did not give.
- **An issue is not authorization.** `docs/EXECUTION_PLAN.md` alone says what may be built.
- **Review:** at every gate transition, or when an idea's prerequisites appear, the
  coordinating agent reclassifies each open idea below and dates the review.

- **Re-plan on every material idea.** In the same session, record its priority,
  dependencies, overlap, shared primitive, parallel lanes and roadmap effect, and put it in
  **NOW / NEXT / LATER / BLOCKED** (`AI_INSTRUCTIONS.md` → Owner ideas).

Roadmap vocabulary: **NOW** (on the current critical path and authorized) · **NEXT**
(ready once a named prerequisite lands) · **LATER** (wanted; not on the 2026-10-22 path) ·
**BLOCKED** (waiting on an owner decision, access or evidence, which is named).

Newly classified ideas use the roadmap vocabulary in the Readiness column. Older rows
keep the readiness vocabulary until their next review: **NOT READY** (prerequisites absent) · **READY FOR RESEARCH** ·
**APPLY SELECTIVELY** (use the principle where current work already needs it) ·
**READY FOR IMPLEMENTATION** (prerequisites exist and there is an authorization path) ·
**SUPERSEDED / NOT PLANNED**.

## Shared primitives (one canonical owner each)

Every idea is built on these primitives. Extend the owner named here, and never fork it into
a feature-specific copy. `PLANNED` means the owner is chosen but not yet built. The ideas
column lists which issues each primitive serves.

| Primitive | Canonical owner | State | Serves |
|---|---|---|---|
| Event / market identity | `src/edge_lab/opportunity.py` | BUILT (Event, Market, settlement_identity) | #5 #9 #30 #32 |
| Venue and account capability registry | `src/edge_lab/venues.py` | BUILT (stages per capability, cash timing; execution never authorized; ADR 0019) | #30 #32 #29 #9 |
| Quote / order-book normalization | `src/edge_lab/opportunity.py` | BUILT (ExecutableQuote and DepthLadder / `walk_ladder` / `price_depth_fill` for Kalshi and Polymarket US, PRs #40 and #42; per-market `PriceGrid`, ADR 0023; sportsbook odds and Novig daily files are never executable) | #30 #9 #29 |
| Fee models and fee verification | `src/edge_lab/fee_schedules.py` | BUILT (Kalshi, with dated component-level verification records, ADR 0017; Polymarket US taker schedule from official US docs with its own record, UNVERIFIED estimate that never supports a claim, ADR 0027; other venues unsupported). It reuses the hash-frozen EXP-001 cost model in `fees.py`, never forks it | #6 #30 #9 |
| Model estimates | `src/edge_lab/opportunity.py` | BUILT (ModelEstimate; EXP-001 only) | #5 #9 #32 |
| Source ingestion and provenance | `src/edge_lab/sources.py` | BUILT: the registry (with a read-only data-feed credential kind), fronting `storage.py`, `provenance.py` and the shared `redaction.py` | #7 #29 #30 #27 |
| Freshness orchestration / collection scheduling | `src/edge_lab/freshness.py` | **NOW design rule / NEXT generalized primitive** (orchestrator PLANNED under #74, beside the `sources.py` registry). Existing specialized schedules remain canonical for their current domains: forward weather, ADR 0029 odds targets, and ADR 0030 scheduled later/closing observations. The future orchestrator must absorb these contracts rather than fork them | #74 #7 #9 #29 #50 |
| Rules / settlement equivalence | `src/edge_lab/opportunity.py` | BUILT (`Event.settlement_identity`, `Market.rules_resolved`); cross-venue classification in `discovery.py` (title match is never equivalence); no equivalence proven across venues yet | #30 #9 |
| Shadow / live ledger boundary | `src/edge_lab/shadow_ledger.py` | BUILT (shadow only; no live ledger). Head checkpoints: `ledger_anchor.py`; the first independent checkpoint is stored off-host and in Git and verified (F09 closed for the anchored history, 2026-09-23) | #6 #3 #32 |
| Risk engine | `src/edge_lab/risk.py` | BUILT (limits, capital release, withdrawal contract) | #6 #3 |
| Stake sizing (research challenger) | `src/edge_lab/sizing_v2.py` (evaluation in sizing_eval.py) | BUILT 2026-09-24, research only (ADR 0026): robust log-growth optimizer over the payoff's admissible uncertainty set, reusing risk, starter policy, depth and fees. The counterfactual runner `sizing_counterfactual.py` (PR #64) replays every recorded decision through policies A-H into a derived artifact, and Terminal v1 shows it read-only as RESEARCH SIZING (PR #69). `sizing.py` remains the frozen operational path; v2 influences fills only after its own experiment passes | #6 #3 #32 |
| Best-price-for-size comparator | `src/edge_lab/best_price.py` | BUILT 2026-09-24 (ADR 0027): one comparator over the shared depth, grid, fee, equivalence, freshness and venue primitives; honest claim ladder; cross-venue "cheaper" only on proven order. Shown in the market detail "Across venues" slot (PR #65), with no arithmetic in the UI | #30 #9 |
| Sports odds capture scheduling | `src/edge_lab/odds_schedule.py` (runner odds_pilot.py; adapter odds_api.py) | BUILT 2026-09-24 (ADR 0029): game-relative T-24h/T-6h/T-60m targets, persisted with intended times, worst-case budget proof under 450 credits. ACTIVE on production since 2026-09-24 13:40Z (budget PROVEN, one smoke read CAPTURED, redaction verified; runbook §5b activation record) | #29 #5 #9 #50 |
| Later / closing price observations | `src/edge_lab/price_observations.py` | BUILT 2026-09-24 (ADR 0030, PR #68). **Option A schedule approved 2026-09-24 11:24 ET**; PR #76 merged (9d66c90) and DEPLOYED 2026-09-24 20:31Z, timers enabled 20:32Z, first scheduled plan 20:35Z (42 targets; close tick ALIGNED). First scheduled network capture pending. "Close" remains only within the stored tolerance; missed point-in-time targets remain MISSED | #74 #50 #30 #9 #29 |
| Capital-eligibility policies | `src/edge_lab/starter_policy.py` | BUILT (`STARTER_MAX_7D_V1`, ADR 0018); enforced prospectively in the operational shadow account | #32 #6 |
| Notification system | `src/edge_lab/notifications.py` | BUILT (contract, local outbox, SMS sink disabled; ADR 0020). ntfy relay is ACTIVE, but the first TEST was only SUBMITTED by ntfy and **did not arrive on the owner's phone** (confirmed 2026-09-24 11:24 ET); end-to-end delivery is unresolved. Secrets remain only in `/etc/market-edge-lab/secrets.env` (root:root 0600). Origin controls remain unchanged | #33 #3 #32 |
| Execution-ticket contract | `src/edge_lab/execution_ticket.py` | BUILT (data contract plus an ordered pre-submit control chain, PR #43; `EXECUTION_NOT_AUTHORIZED` always fails) | #32 #33 #30 |
| Operator views | `src/edge_lab/dashboard/` | BUILT (read-only; on chaseupside reachable only on the owner's tailnet via Tailscale Serve, ADR 0024) | #3 #6 #10 |
| Design system (Market Edge Terminal v1) | `docs/design/UI_CONTRACT.md` | BUILT (implemented in dashboard presentation.py, components.py, html.py and static/tokens.css; shell, tokens, fonts, components, honest states, gallery; ADR 0025, issue #47). Every user-visible feature reuses it per docs/design/FEATURE_INTEGRATION.md | #47 #3 #6 #9 #10 #29 #30 #32 #33 |
| Longitudinal learning history | `docs/DATA_PROVENANCE.md` | FOUNDATION BUILT in immutable snapshots/documents, forward captures, experiment records, opportunity reasons and the shadow ledger; issue #50 makes prospective learning-history completeness a cross-domain acceptance rule. A generalized derived learning/reporting layer is NEXT only when additional domains produce data; do not create a duplicate evidence store | #50 #5 #7 #9 #27 #29 #30 |

## Index

| Issue | Idea | Readiness | Why / prerequisites |
|---|---|---|---|
| #4 | Durable idea intake and readiness backlog (process) | **Implemented** 2026-09-22 (Gate 3 PR) | `AI_INSTRUCTIONS.md` rule + this index |
| #3 | Outcome Board / What Matters Today dashboard | **BACKEND + LOCAL VIEW IMPLEMENTED** 2026-09-23 (PR #28); hosting NOT READY | `edge_lab.outcome_board` (ADR 0015) plus the `/outcome-board` view of the local read-only dashboard (127.0.0.1 only). Hosting, auth and live marks are unauthorized and not built. |
| #5 | Sports prediction-market and sports-modeling expansion | **LATER** (discovery and data foundations NEXT via #29/#30; any sports model BLOCKED on a preregistered experiment) | Core framework is proving out on weather. Needs the shared identity, venue and equivalence layers; the 2026-09-23 directive authorizes data foundations only, not sports models. |
| #9 | Sportsbook odds aggregation, consensus pricing, best-venue comparison | **NEXT** (The Odds API data foundation via #29); comparison LATER | Sub-idea of #5. Needs market equivalence and verified access terms. Offered odds are never executable prices. |
| #6 | Dynamic bankroll, position sizing, withdrawal guidance | **P0 FOUNDATION IMPLEMENTED** 2026-09-23 (shadow only); **sizing v2 research challenger IMPLEMENTED** 2026-09-24 (ADR 0026; no effect on fills) | Shadow ledger (ADR 0014), `suggest_position_size`, and the risk/capital report with a withdrawal contract (ADR 0015). The withdrawal contract never recommends a draw. Since PR #26 the operational shadow account enforces the risk limits **before** each fill (NO_FILL RISK_VETO); the frozen research account is separate. A real-money policy, a verified edge and verified fees are all still missing. |
| #10 | Host privately on existing Chase Upside infrastructure (separate service/subdomain, real access control) | **IMPLEMENTED, private** 2026-09-23: collector, daily shadow and settlement deployed and verified (`docs/deploy/PRODUCTION_ACTIVATION_2026-09-23.md`); the dashboard is tailnet-only via Tailscale Serve (PR #46, ADR 0024) | A separate service with its own user, slice and stores on the VPS. Access control is tailnet membership. A public subdomain, DNS/TLS and public exposure remain unauthorized and are not planned. |
| #7 | Free-first multi-domain ingestion with paid-source ROI gate | APPLY SELECTIVELY NOW | Gate 3 applied it: the free IEM archive of NWS forecasts was chosen and paid weather data was not considered. The general ingestion platform is not built. |
| #32 | Starter policy: 7-day capital-release limit, broad discovery, API-first execution preference | **Policy IMPLEMENTED** 2026-09-23 (PR #38, ADR 0018; enforced prospectively in the operational shadow account; no deployment known or verified from this session); discovery foundation IMPLEMENTED (PR #39); execution BLOCKED (no live authority) | Governing clock: venue-tradable cash within 168 h. The ticket contract carries the verdict with execution disabled. |
| #33 | SMS-first alerting through one shared notification layer | **Contract IMPLEMENTED; ntfy relay ACTIVE; PHONE DELIVERY FAILED FIRST TEST** (owner confirmed 2026-09-24 11:24 ET) | Provider acceptance was SUBMITTED, but the phone showed nothing. Investigate subscription/client delivery without exposing the topic. Do not claim end-to-end delivery until a later owner-observed test succeeds. SMS delivery remains BLOCKED on provider approval. |
| #30 | Multi-venue coverage, best-price comparison, unique-market discovery | **Foundation IMPLEMENTED**; **best-price-for-size comparator IMPLEMENTED** 2026-09-24 (PR #58, ADR 0027) with Polymarket US fee evidence (unverified estimate) and split-cancel refusal; comparator UI NEXT; Novig live API BLOCKED (credentials) | Cross-venue "cheaper" is impossible until rules equivalence and claim-grade fees are proven (Polymarket US rules stay unresolved). |
| #29 | The Odds API free tier (quota-capped sports odds pilot) | **LIVE / ACTIVE** 2026-09-24: free key installed privately, budget PROVEN, smoke read verified, `edgelab-odds.timer` enabled | Sportsbook-consensus input for #5/#9 under the 450-credit monthly ceiling. Offered odds and de-vigged values are never executable prices; broader/faster collection remains constrained by quota and #7 ROI discipline. |
| #27 | Action PRO permission and comparative sports-data subscription value | **LATER / BLOCKED** (no purchase authorized) | Paid source; needs the #7 ROI gate and a sports experiment that would use it. |
| #50 | Longitudinal learning dataset across every domain, including rejected opportunities | **NOW as a permanent data-design rule; NEXT for a generalized cross-domain learning/reporting layer** | Existing provenance, opportunity/rejection, experiment and shadow-ledger primitives already preserve much of the required history. Every new domain should preserve point-in-time observations, model/version context, decisions and rejections, later outcomes and failures before it is called research-ready. No automatic retraining or self-modifying decision policy is authorized. |
| #74 | Always-on freshness fabric — staggered 24/7 adaptive collection | **NOW as a P0 data-design/operational rule; NEXT for the generalized orchestrator** | One shared freshness supervisor should eventually own source cadence, staggering, streaming/polling choice, quotas, missed-target accounting and decision-time freshness. Immediate action: ADR 0030 Option A is approved so currently lost later/closing depth begins being preserved without waiting for the full orchestrator. |
| #86 | Cross-domain prospective evidence — collect learning-ready data before models exist | **NOW: portfolio + Multi-City Weather v1 design; gated collectors one source at a time** (2026-09-24 evening directive) | Extends #7/#50/#74/#82 and serves #30; duplicates none. Irrecoverable point-in-time evidence first; every source registered, market-relevant, outcome-labelled, budgeted, and scheduled through #74. Record: `docs/owner/2026-09-24-cross-domain-prospective-evidence-directive.md`. COLLECT ≠ MODEL ≠ VALIDATED ≠ ACTIONABLE. |

## Roadmap (re-run 2026-09-24 after the next-build-chunk directive and the Odds / ntfy activation)

This ordering authorizes nothing; `docs/EXECUTION_PLAN.md` does. Re-prioritizing never
authorizes implementation. The owner's domain sequence (directive, "Domain expansion") is
recorded below and in the Domain Readiness matrix. Gate 7 is unchanged and **not passed**.

**NOW** (critical path; authorized)
1. **Keep production collecting and verified** (#10, #11). Every day lost is a Stage B day lost.
   Production runs the merged `main` SHA recorded in `HANDOFF.md`. Deploys stay outside
   17:40–18:50 ET and away from the 11:15 / 16:15 ET settlement runs.
2. **Accumulate valid Stage B days and real shadow bookkeeping** (EXP-001). The first valid day
   is 2026-09-24, and its first settlement is due. One valid day is pipeline evidence only: no
   retuning, no sizing change, no criteria change.
3. **F09 manual checkpoints** (owner decision 2026-09-24). Roughly weekly, and additionally
   after a notable ledger event:
   - the first settlement;
   - a settlement conflict;
   - a significant ledger or risk-schema migration;
   - before and after a recovery that affects ledger durability.

   **No F09 timer.**
4. **Re-check Kalshi scheduled fee changes by 2026-10-23.** At the same re-check, add the
   `SETTLEMENT_AND_TRANSFER_FEES` component to the Kalshi record (ADR 0027). Also re-check
   Polymarket US fees by 2026-10-24T01:39Z.
5. **#50 learning-history completeness** applies from the first prospective observation of
   every domain. See the audit in `docs/DATA_PROVENANCE.md`.
6. **#29 Odds API pilot: live.** Activated 2026-09-24 13:40Z. Snapshots accrue under the
   game-relative policy, within 450 credits a month and never above the provider's remaining
   quota. Watch the first paid slots (14:15 and 19:15 ET on 2026-09-24): CAPTURED or MISSED
   with a reason, 3 credits each. Nothing about this authorizes a sports model or a bet.
7. **#33 ntfy.** The topic was rotated by the owner on 2026-09-24 after exposure. One TEST was
   SUBMITTED by ntfy, but the owner confirmed at 11:24 ET that **nothing arrived on the phone**.
   End-to-end delivery is unresolved; diagnose before claiming the alert path works.
8. **Scheduled later/closing observations** (ADR 0030; #74/#50). Option A is deployed (PR #76,
   9d66c90; both timers enabled 2026-09-24 20:32Z). Verify the first real captures from stored
   rows. Re-check `close_tick_alignment` after the 2026-11-01 DST change.
9. **#74 freshness fabric.** Treat continuous freshness, staggered collection, explicit missed-target
   accounting and fail-closed decision freshness as permanent design rules now. The generalized
   cross-domain orchestrator is NEXT; do not destabilize the running weather/Odds pipelines to rush
   a refactor.

9a. **#86 cross-domain prospective evidence: Wave 1.** Produce the acquisition portfolio,
   the source-readiness classification and the combined resource budget. Design Multi-City
   Weather v1, including verification of recurring Kalshi weather families, rules and stations.
   Its implementation starts after the Freshness Fabric + sports lanes are merged and deployed.
   Queued behind those lanes, with no forked abstraction: new collectors become #74 providers;
   readiness extends `research_readiness.py`; one shared release/event calendar primitive.

**NEXT** (ready once the named prerequisite lands)
10. **Sizing v2 evidence** (#6). The counterfactual runner and the read-only RESEARCH SIZING
   panel are built. What remains is evidence: settled decisions under `STARTER_MAX_7D_V1`
   (every decision before 2026-09-24T00:00Z is CAPITAL_HORIZON), an evidence-based n_eff, and
   the preregistered sizing experiment. Operational fills change only after it passes.
11. **Sports prospective data** (domain 2). Odds snapshots accrue under the game-relative
    policy. Add Polymarket US sports catalog reads, which are related-only until rules are
    resolved. The split-cancel and alternative-settlement payoffs stay refused until the
    generic payoff engine supports them.
12. **#30 cross-venue weather comparison** (Kalshi vs a Polymarket US weather market). It
    waits on resolved Polymarket rules and fees that reach claim grade.
13. **Odds capture targets in Terminal v1** (CAPTURED / MISSED / SKIPPED_BUDGET). The
    status card and the alerts-by-origin view are live (PR #70); a per-target table follows.

**LATER** (wanted; not on the 2026-10-22 path)
14. Sports baseline / preregistered models (domain 3; #5, #9), each as its own preregistered
    experiment.
15. Economics/macro (4), crypto (5), energy/commodities (6), business/technology (7),
    culture/entertainment (8), politics/government (9), long-tail discovery (10). The owner's
    order. No broad implementation in this mission.
16. #27 Action PRO; #32 execution modes (gate 8+); #33 SMS provider; broader venues.
17. **Security task, separate:** root SSH hardening. It stays out of scope for Market Edge
    missions (owner decision 2026-09-24; no key, sshd, sudo or root-login changes here).
18. **Brisket follow-ups** (other repository; not Market Edge work): the six failing refresh
    units are handed off in riskittogetthebrisket#1409 (PRs #1406 and #1407 are paused). Also
    `public-league-warmup` should accept 503.

**BLOCKED** (named blocker)
- ntfy end-to-end phone delivery: the TEST was SUBMITTED, and ntfy.sh holds it on the configured
  topic (server path proven clean 2026-09-24). The remaining problem is the phone/subscription side,
  which needs an owner check. Proving a fix needs one more TEST, with the owner's OK.
- SMS: provider choice and approval. Novig live API: developer credentials.
- Polymarket US claim-grade totals: settlement/transfer fees, debit rounding, account type and
  scheduled changes are all unverified.
- Any execution: gates 8–10.

### Domain Readiness matrix (states, not scores)

Deliberately no numerical score: no weights have been validated. States:
- **E** evidence in hand;
- **P** partial or plausible;
- **U** unknown;
- **N** known negative.

| Domain (owner order) | Settlement clarity | Point-in-time public data | Quantifiable | Event frequency | Liquidity | Fees known | 7-day capital | Model independence | Data latency | Venue coverage | Historical evidence | Rule ambiguity | Readiness |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 Weather (KXHIGHNY) | E (Gate 2) | E (NWS, IEM) | E | E daily | P | P (Kalshi bound) | E | E (NWS vs market) | E | P (Kalshi; Polymarket related) | E (Gate 3) | E low | **Running (EXP-001 Stage B)** |
| 2 Sports (NFL first) | P (void/push/split rules) | P (odds snapshots from 2026-09-24) | E | E weekly | P | U (Polymarket US unverified) | P | P | P | P (Kalshi, Polymarket US, books) | N (no provider history on free tier) | P | **Data collection** |
| 3 Sports models | as above | needs weeks of snapshots | E | E | P | U | P | U | P | P | N | P | **Needs a preregistered experiment** |
| 4 Economics / macro | P | P (release calendars, vintages) | E | P monthly | P | P | P | U | E | P | P | P (revisions) | Not started |
| 5 Crypto | P | E | E | E | P | P | E | U (efficient market) | E | P | P | P | Not started |
| 6 Energy / commodities | P | P | E | P | U | U | P | U | P | U | U | P | Not started |
| 7 Business / technology | U | U | P | P | U | U | U | U | U | U | U | U | Not started |
| 8 Culture / entertainment | U | U | P | P | U | U | U | U | U | U | U | U | Not started |
| 9 Politics / government | P | P | P | N rare | P | P | N (long horizons) | U | P | P | P | P | Not started |
| 10 Long-tail discovery | U | U | U | U | U | U | U | U | U | U | U | U | Discovery only |

**Why priorities moved (2026-09-24, second re-run).**
- **All seven next-build-chunk deliverables are built, merged and deployed** (production
  6497af3). The counterfactual runner, the sizing panel, the
  comparator UI, manual price observations, the notification origin and the coverage audit
  moved out of NEXT.
- **The Odds API is no longer blocked.** The key is installed, the budget is PROVEN, and the
  timer runs. Sports data collection is now prospective.
- **What remains is evidence and owner decisions,** not code: settlements under the starter
  policy, the price-capture schedule, and phone confirmation.
- The 2026-10-22 date is unchanged.

**Why priorities moved (2026-09-24, first re-run).**
- **Build work is done.** The comparator, Polymarket US fee evidence, split-cancel refusal,
  sizing v2 (research), the Odds API pilot code and ntfy activation all moved from NEXT/BLOCKED
  to built.
- **The two remaining blockers are owner actions:** the Odds API key and the ntfy phone
  subscription.
- **Sports becomes the second domain.** It has data collection only; no sports model or
  betting is authorized.
- The 2026-10-22 date is unchanged.

**UI foundation (2026-09-23, owner directive, issue #47).** The Market Edge Terminal v1 design
system is NOW / P0: one shell, token set, component layer and state vocabulary that every later
page reuses. Order: shared shell and components first (done), integration of the existing pages
second (done), future domains third (sports, politics, economics and new venues feed the same
`MarketRow`, detail, source list, comparison and Alerts contracts; no new global navigation for
a new sport or source). Deferred behind it: discretionary new feature screens. Not deferred:
collection, correctness repairs and the fee re-check. Oct 22 is unchanged. Shared-primitive
row: "Design system" above.

Related owner records that are not ideas:
- **#11 [Owner Directive] 30-day delivery plan (target 2026-10-22).** This is the active
  roadmap: deadline fixed, scope adapts, P0/P1/P2 change control. Gates still govern:
  "a gate does not pass because the calendar says it should".
- **#12 [Infrastructure] Brisket portability audit.** An owner-authorized parallel lane with
  its own branch and file claim. It does not touch Gate 3 files.

## Review log

- **2026-09-24 (evening, later): #86 cross-domain prospective evidence intake.**
  - One new canonical idea (#86). It extends #7, #50, #74 and #82 and serves #30; it duplicates none.
  - **NOW:** Wave 1 planning and the Multi-City Weather v1 design (non-overlapping with the active
    Freshness/sports lanes).
  - **NEXT:** Multi-City Weather v1 collection after those lanes deploy; then macro with vintages,
    BTC/ETH, EIA, SEC EDGAR.
  - **LATER:** specialized culture sources, broad news, polling, social, licensed feeds.
  - **Shared primitives reused:**
    - scheduling: #74 providers;
    - venue evidence: SnapshotStore and the venue adapters;
    - readiness: `research_readiness.py`;
    - a new shared release/event calendar, to be designed once.
  - No gate change. No paid source. The 2026-10-22 date is unchanged.

- **2026-09-24 11:24 ET: freshness / notification follow-up.**
  - New owner idea #74: always-on staggered freshness is NOW as a permanent P0 design rule;
    the generalized cross-domain orchestrator is NEXT.
  - ADR 0030 Option A is explicitly approved; scheduled later/closing-price capture moves from
    BLOCKED/NEXT to NOW. It is the first practical #74 implementation, not a competing scheduler.
  - The first ntfy TEST did not reach the phone. The relay remains provider-SUBMITTED only;
    end-to-end delivery is unresolved.
  - No gate change, no execution authority, no paid-service authority, and no 2026-10-22 extension.


- **2026-09-24 (morning): next-build-chunk directive and activation re-plan.**
  - New primitive: later/closing price observations (ADR 0030).
  - Extended owners, with no fork: sizing v2 (counterfactual runner and panel), the comparator
    (UI), notifications (origin), and odds scheduling (live activation).
  - #29 moved from BLOCKED to NOW (live). #33 phone delivery is OWNER_CONFIRMATION_PENDING.
  - The price-capture schedule is BLOCKED on an owner decision.
  - No gate change. EXP-001 is frozen. The 2026-10-22 date is unchanged.

- **2026-09-24: Brisket-health and next-phase directive re-plan.** New primitives: sizing v2 (research), best-price comparator, odds capture scheduling. #6, #29, #30 and #33 were reclassified. The domain sequence and the Domain Readiness matrix (states only) were added. F09 stays manual, and root SSH is a separate security task. No new idea required a new primitive: every lane extended an existing owner.

- **2026-09-23: issue #50 longitudinal learning-history intake.**
  - Classification: **NOW as a permanent data-design rule; NEXT for a generalized derived learning/reporting layer once multiple domains have prospective data**.
  - Dependencies/overlap: extends the existing provenance store, event/market identity, opportunity reason codes, experiment registry and shadow ledger; it does not create a second memory database.
  - Shared leverage: the same history supports weather, sports, macro, crypto and later domains, plus source-ROI analysis for #27/#29 and venue-quality analysis for #30.
  - Safe parallel lane: coverage/schema audits may run independently, but any new scheduled collection still needs its own authorization. No automatic retraining, live execution or gate advancement is authorized.
  - Roadmap effect: no 2026-10-22 extension; prospective storage is required before sophisticated modeling so rejected opportunities, failures and point-in-time inputs are not lost.

- **2026-09-23 (evening): production activation directive and GitHub audit follow-ups
  (PRs #42, #43, #44, #45; #46 from the parallel Tailscale session).**
  - The roadmap above was re-run with the reasons it moved. #10 is IMPLEMENTED (private);
    #33 ntfy is built but disabled; #30 depth and the grid are built.
  - Shared primitives: one depth abstraction serves both book venues; the ticket control
    chain reads `risk.RiskPolicy` (one owner), not its own limits.
  - No idea was dropped. #27, #29 live, SMS and Novig live stay BLOCKED on named owner
    decisions.

- **2026-09-23: final portfolio review of the integration directive (PRs #34, #35, #37, #38, #39).**
  - The roadmap above replaces the chronological ordering.
  - #32 policy, #33 contract, #30 foundation and #29 adapter moved to IMPLEMENTED at their
    stated scope; the remaining parts are NEXT or BLOCKED with named blockers.
  - The shared primitives table now lists every built owner. None is duplicated.
  - Parallel lanes this session: fees, F09 and production tooling, then the policy and
    notifications, then the adapters. Each had one writer and built on shared contracts.

- **2026-09-23: integration and production directive (intake of #27, #29, #30, #32, #33).**
  - The re-planning rule was added to `AI_INSTRUCTIONS.md`, and the Shared primitives table
    was added here.
  - Shared-primitive analysis: #32's policy, #33's alerts, #30's venues and #29's odds source
    all sit on primitives that already exist or are planned once. None needs its own engine.
    - The starter policy extends the risk engine.
    - Notifications are one contract for #33, #3 and #32 exceptions.
    - Venues are one registry for #30, #29 and #32 execution capability.
    - The odds source uses the existing source registry and snapshots.
  - Parallel build: one shared contract per primitive, written by the coordinator. The
    venue-specific adapters (Polymarket US, Odds API, Novig) are then independent bounded
    lanes.
  - Roadmap: #32's policy and #33's contract are NOW. #30 and #29 are NEXT. #27 is
    LATER/BLOCKED. The final portfolio review of this directive updates this entry.

- **2026-09-23: daily-shadow directive (PRs #25, #26, #28).**
  - #3: the local read-only view now exists; hosting is still not authorized.
  - #6: risk limits are now enforced before each fill; still no real-money policy.
  - #10: units are staged but not installed. Dashboard hosting is NOT READY (no DNS/TLS or
    exposure authorization).
  - #5, #7 and #9 unchanged. There was no sports work and no paid source.

- **2026-09-23: Gate 4 → 5 → 6 and the risk foundation (overnight directive, PRs #21–#24).**
  - #6 and #3 moved to foundation-implemented (shadow and backend only).
  - #5 and #9 stay outside scope. The directive says no sports tonight.
  - #7 unchanged: no paid sources.
  - #10 unchanged: headless collector only; no subdomain or dashboard.

- **2026-09-22, Gate 2 → Gate 3 / Gate 3 PR.**
  - Classifications as above. None change Gate 3 scope.
  - #7's free-first principle drove the forecast-source choice (IEM PFMOKX).
  - The Kalshi fee-schedule PDF sits behind a bot checkpoint and is not bypassed, which
    is consistent with #7's "no circumvention".
- **2026-09-22, Gate 4 exit criteria met (PR #18); Gate 5 awaits the owner.**
  - #10 is partly authorized: the headless read-only collector only (ADR 0012).
  - No other classification changes.
  - #3 and #6 stay NOT READY until a shadow ledger with real forward data exists.
  - #5 and #9 stay outside scope: no sports work.
- **2026-09-22, Gate 3 → Gate 4 (Gate 3 PR, effective on merge).**
  - No classification changes: #3, #6, #9 and #10 stay NOT READY, #5 READY FOR RESEARCH,
    #7 APPLY SELECTIVELY.
  - #10 captured and indexed.
  - Per #11, the next P0 steps are Gate 4 (the frozen baseline) and forward market
    collection. That collection is the owner's scheduled-collection decision (ADR 0008),
    and #10 is a candidate host for it.
  - #6's risk foundation and #3's Outcome Board are #11 P0 items for later in the month.
    They stay NOT READY until a shadow ledger exists.
