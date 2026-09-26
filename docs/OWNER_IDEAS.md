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
| Freshness orchestration / collection scheduling | `src/edge_lab/freshness.py` | **v1 BUILT and DEPLOYED 2026-09-24** (ADR 0031, PR #81; production c6e0dd9): shared types, read-only EXTERNAL_SCHEDULE providers for every existing schedule, network-free 5-minute supervisor writing `freshness.json` (0 disagreements at first run). It observes and explains; it controls nothing yet. Migration of a schedule into the fabric needs parity evidence and owner approval, one source at a time. Every new collector (#86, #88) is a fabric provider, never its own scheduler | #74 #86 #88 #7 #9 #29 #50 |
| Rules / settlement equivalence | `src/edge_lab/opportunity.py` | BUILT (`Event.settlement_identity`, `Market.rules_resolved`); cross-venue classification in `discovery.py` (title match is never equivalence); no equivalence proven across venues yet | #30 #9 |
| Shadow / live ledger boundary | `src/edge_lab/shadow_ledger.py` | BUILT (shadow only; no live ledger). Head checkpoints: `ledger_anchor.py`; the first independent checkpoint is stored off-host and in Git and verified (F09 closed for the anchored history, 2026-09-23) | #6 #3 #32 |
| Risk engine | `src/edge_lab/risk.py` | BUILT (limits, capital release, withdrawal contract) | #6 #3 |
| Stake sizing (research challenger) | `src/edge_lab/sizing_v2.py` (evaluation in sizing_eval.py) | BUILT 2026-09-24, research only (ADR 0026): robust log-growth optimizer over the payoff's admissible uncertainty set, reusing risk, starter policy, depth and fees. The counterfactual runner `sizing_counterfactual.py` (PR #64) replays every recorded decision through policies A-H into a derived artifact, and Terminal v1 shows it read-only as RESEARCH SIZING (PR #69). `sizing.py` remains the frozen operational path; v2 influences fills only after its own experiment passes | #6 #3 #32 |
| Best-price-for-size comparator | `src/edge_lab/best_price.py` | BUILT 2026-09-24 (ADR 0027): one comparator over the shared depth, grid, fee, equivalence, freshness and venue primitives; honest claim ladder; cross-venue "cheaper" only on proven order. Shown in the market detail "Across venues" slot (PR #65), with no arithmetic in the UI | #30 #9 |
| Sportsbook consensus research benchmark | `src/edge_lab/odds_consensus.py` | BUILT (math in the odds_api.py consensus section) 2026-09-24 (ADR 0033, PR #79), shown in Terminal (PR #85): exact-line two-way de-vig, median, dispersion, book counts, combined freshness, point-in-time; RESEARCH BENCHMARK — NOT EXECUTABLE; offered price and consensus probability never conflated | #9 #5 #29 #82 |
| Per-domain research readiness | `src/edge_lab/research_readiness.py` | BUILT 2026-09-24 (PR #79): YES / PARTIAL / NOT_YET / UNKNOWN per prerequisite from real stores; explicit YES rules; never green by default. #86 §50 extends it to every domain (market history, depth, rules, external features, vintages, model, rejections, later prices, labels, source failures) | #50 #86 #88 #82 |
| Release / event calendar | `src/edge_lab/event_calendar.py` | PLANNED (contract in docs/research/SOURCE_READINESS.md §9). ONE shared calendar (event id, domain, scheduled and actual times, source, expected fields, related markets, capture targets, exchange sessions and holidays), mapped onto fabric RELEASE_DRIVEN / EVENT_RELATIVE modes. Never one per domain | #86 #88 #74 #82 |
| Instrument selection (how to express an edge) | `src/edge_lab/instrument_selection.py` | PLANNED; **DEFERRED 2026-09-25 by #96** (no general instrument optimizer before two concrete expressions exist). #88 §6: separate "we found an edge" from "how to express it": stock, ETF, option, option spread, future, prediction-market contract, or nothing, compared on payoff, spread, depth, slippage, fees, convexity, leverage, capital, downside, horizon, permissions and capacity. Builds on the best-price comparator and sizing v2; integrates with #82 | #88 #30 #82 #6 |
| Sports odds capture scheduling | `src/edge_lab/odds_schedule.py` (runner odds_pilot.py; adapter odds_api.py) | BUILT 2026-09-24 (ADR 0029): game-relative T-24h/T-6h/T-60m targets, persisted with intended times, worst-case budget proof under 450 credits. ACTIVE on production since 2026-09-24 13:40Z (budget PROVEN, one smoke read CAPTURED, redaction verified; runbook §5b activation record) | #29 #5 #9 #50 |
| Later / closing price observations | `src/edge_lab/price_observations.py` | BUILT 2026-09-24 (ADR 0030, PR #68). **Option A schedule approved 2026-09-24 11:24 ET**; PR #76 merged (9d66c90) and DEPLOYED 2026-09-24 20:31Z, timers enabled 20:32Z, first scheduled plan 20:35Z (42 targets; close tick ALIGNED). First scheduled network capture pending. "Close" remains only within the stored tolerance; missed point-in-time targets remain MISSED | #74 #50 #30 #9 #29 |
| Capital-eligibility policies | `src/edge_lab/starter_policy.py` | BUILT (`STARTER_MAX_7D_V1`, ADR 0018); enforced prospectively in the operational shadow account | #32 #6 |
| Notification system | `src/edge_lab/notifications.py` | BUILT (contract, local outbox, SMS sink disabled; ADR 0020). ntfy relay is ACTIVE, but the first TEST was only SUBMITTED by ntfy and **did not arrive on the owner's phone** (confirmed 2026-09-24 11:24 ET); end-to-end delivery is unresolved. Secrets remain only in `/etc/market-edge-lab/secrets.env` (root:root 0600). Origin controls remain unchanged | #33 #3 #32 |
| Execution-ticket contract | `src/edge_lab/execution_ticket.py` | BUILT (data contract plus an ordered pre-submit control chain, PR #43; `EXECUTION_NOT_AUTHORIZED` always fails) | #32 #33 #30 |
| Operator views | `src/edge_lab/dashboard/` | BUILT (read-only; on chaseupside reachable only on the owner's tailnet via Tailscale Serve, ADR 0024) | #3 #6 #10 |
| Design system (Market Edge Terminal v1) | `docs/design/UI_CONTRACT.md` | BUILT (implemented in dashboard presentation.py, components.py, html.py and static/tokens.css; shell, tokens, fonts, components, honest states, gallery; ADR 0025, issue #47). Every user-visible feature reuses it per docs/design/FEATURE_INTEGRATION.md | #47 #3 #6 #9 #10 #29 #30 #32 #33 |
| Experiment registry, research-protocol sidecar and family slots | `src/edge_lab/experiments.py` | BUILT (TOML manifests, preregistration freeze, ADR 0004/0009). **Extended 2026-09-25 (EE v1 PR A):** an additive `protocol.toml` sidecar for new experiments (mechanism, universe, clusters, endpoints, cutoffs, data roles, variants, cost/fill, size/capital, untouched window, budget, review date, futility, minimum useful effect, frozen episode definition), frozen with the baseline; at most two new ACTIVE families (#96). EXP-001 is read as LEGACY and is unchanged | #96 #82 #5 #9 |
| Research-evidence lineage (evidence consumption, attrition) | `src/edge_lab/research_evidence.py` | BUILT 2026-09-25 (EE v1 PR A): append-only per-experiment `evidence_use.jsonl` (role, window, actor, action, features/labels/results viewed, tuning influence); holdout identity by outcome window as well as hash; legacy access UNKNOWN; protocol `prohibited_inputs` enforced; attrition waterfalls with separate denominators and one primary reason per unit. Not a second registry or memory store | #96 #82 #50 |
| Research economics (episodes, capital-constrained replay, size ladder, screen) | `src/edge_lab/research_economics.py` | BUILT 2026-09-25 (EE v1 PR A): distinct episodes under a frozen definition; chronological replay with finite per-venue capital, reserve, settlement release and one shared pool; size ladder over the canonical depth walk and fees (fees once); OBSERVED/ESTIMATED/OWNER_INPUT/UNKNOWN inputs; verdicts INSUFFICIENT_EVIDENCE / ECONOMICALLY_UNVIABLE / BELOW_MINIMUM_USEFUL / CONTINUE. No amount is an approved bankroll | #96 #93 #6 #32 |
| Same-venue payoff-constraint evaluator | `src/edge_lab/payoff_constraints.py` | BUILT 2026-09-25 (EE v1 PR B, ADR 0036): a pure, allowlisted evaluator (complements, exhaustive partitions, nested thresholds; long legs only) over the opportunity, depth, fee and settlement contracts. It enumerates states (including discretionary fallbacks), keeps the proof, observed inconsistency, conditional full-fill surplus and orphan-leg exposure separate, and never claims captured arbitrage. `edge-lab research payoff-scan` reads stored books read-only, market side only. Not a general optimizer | #96 #5 #9 #30 |
| Longitudinal learning history | `docs/DATA_PROVENANCE.md` | FOUNDATION BUILT in immutable snapshots/documents, forward captures, experiment records, opportunity reasons and the shadow ledger; issue #50 makes prospective learning-history completeness a cross-domain acceptance rule. A generalized derived learning/reporting layer is NEXT only when additional domains produce data; do not create a duplicate evidence store | #50 #5 #7 #9 #27 #29 #30 |

## Index

| Issue | Idea | Readiness | Why / prerequisites |
|---|---|---|---|
| #4 | Durable idea intake and readiness backlog (process) | **Implemented** 2026-09-22 (Gate 3 PR) | `AI_INSTRUCTIONS.md` rule + this index |
| #3 | Outcome Board / What Matters Today dashboard | **BACKEND + LOCAL VIEW IMPLEMENTED** 2026-09-23 (PR #28); hosting NOT READY | `edge_lab.outcome_board` (ADR 0015) plus the `/outcome-board` view of the local read-only dashboard (127.0.0.1 only). Hosting, auth and live marks are unauthorized and not built. |
| #5 | Sports prediction-market and sports-modeling expansion | **LATER** (discovery and data foundations NEXT via #29/#30; any sports model BLOCKED on a preregistered experiment) | Core framework is proving out on weather. Needs the shared identity, venue and equivalence layers; the 2026-09-23 directive authorizes data foundations only, not sports models. **2026-09-25 (#96):** Family A (EXP-002, DRAFT) is narrow stored-evidence research on NFL pregame moneyline consensus vs executable event-market prices. It is not a sports model or strategy; any winner model stays BLOCKED on its own preregistered experiment. |
| #9 | Sportsbook odds aggregation, consensus pricing, best-venue comparison | **NEXT** (The Odds API data foundation via #29); comparison LATER | Sub-idea of #5. Needs market equivalence and verified access terms. Offered odds are never executable prices. **2026-09-25 (#96):** the consensus benchmark is Family A's frozen baseline (EXP-002); a de-vig/weighting/filter change is a registered variant, never a quiet improvement. |
| #6 | Dynamic bankroll, position sizing, withdrawal guidance | **P0 FOUNDATION IMPLEMENTED** 2026-09-23 (shadow only); **sizing v2 research challenger IMPLEMENTED** 2026-09-24 (ADR 0026; no effect on fills) | Shadow ledger (ADR 0014), `suggest_position_size`, and the risk/capital report with a withdrawal contract (ADR 0015). The withdrawal contract never recommends a draw. Since PR #26 the operational shadow account enforces the risk limits **before** each fill (NO_FILL RISK_VETO); the frozen research account is separate. A real-money policy, a verified edge and verified fees are all still missing. |
| #10 | Host privately on existing Chase Upside infrastructure (separate service/subdomain, real access control) | **IMPLEMENTED, private** 2026-09-23: collector, daily shadow and settlement deployed and verified (`docs/deploy/PRODUCTION_ACTIVATION_2026-09-23.md`); the dashboard is tailnet-only via Tailscale Serve (PR #46, ADR 0024) | A separate service with its own user, slice and stores on the VPS. Access control is tailnet membership. A public subdomain, DNS/TLS and public exposure remain unauthorized and are not planned. |
| #7 | Free-first multi-domain ingestion with paid-source ROI gate | APPLY SELECTIVELY NOW | Gate 3 applied it: the free IEM archive of NWS forecasts was chosen and paid weather data was not considered. The general ingestion platform is not built. **2026-09-25 (#96):** paid data needs a hypothesis-specific value case (which active family, which decision it changes, marginal value vs cost), not a general ROI argument. |
| #32 | Starter policy: 7-day capital-release limit, broad discovery, API-first execution preference | **Policy IMPLEMENTED** 2026-09-23 (PR #38, ADR 0018; enforced prospectively in the operational shadow account; no deployment known or verified from this session); discovery foundation IMPLEMENTED (PR #39); execution BLOCKED (no live authority) | Governing clock: venue-tradable cash within 168 h. The ticket contract carries the verdict with execution disabled. **2026-09-25 (#96):** preserved unchanged; the economic screen reports lockup and capital-days against it and never assumes an early resale satisfies the 168-hour policy. |
| #33 | SMS-first alerting through one shared notification layer | **Contract IMPLEMENTED; ntfy relay ACTIVE; PHONE DELIVERY FAILED FIRST TEST** (owner confirmed 2026-09-24 11:24 ET) | Provider acceptance was SUBMITTED, but the phone showed nothing. Investigate subscription/client delivery without exposing the topic. Do not claim end-to-end delivery until a later owner-observed test succeeds. SMS delivery remains BLOCKED on provider approval. |
| #30 | Multi-venue coverage, best-price comparison, unique-market discovery | **Foundation IMPLEMENTED**; **best-price-for-size comparator IMPLEMENTED** 2026-09-24 (PR #58, ADR 0027) with Polymarket US fee evidence (unverified estimate) and split-cancel refusal; comparator UI NEXT; Novig live API BLOCKED (credentials) | Cross-venue "cheaper" is impossible until rules equivalence and claim-grade fees are proven (Polymarket US rules stay unresolved). |
| #29 | The Odds API free tier (quota-capped sports odds pilot) | **LIVE / ACTIVE** 2026-09-24: free key installed privately, budget PROVEN, smoke read verified, `edgelab-odds.timer` enabled | Sportsbook-consensus input for #5/#9 under the 450-credit monthly ceiling. Offered odds and de-vigged values are never executable prices; broader/faster collection remains constrained by quota and #7 ROI discipline. |
| #27 | Action PRO permission and comparative sports-data subscription value | **LATER / BLOCKED** (no purchase authorized) | Paid source; needs the #7 ROI gate and a sports experiment that would use it. **2026-09-25 (#96):** still BLOCKED; a purchase case would have to come from an active family's data-gap report. |
| #50 | Longitudinal learning dataset across every domain, including rejected opportunities | **NOW as a permanent data-design rule; NEXT for a generalized cross-domain learning/reporting layer** | Existing provenance, opportunity/rejection, experiment and shadow-ledger primitives already preserve much of the required history. Every new domain should preserve point-in-time observations, model/version context, decisions and rejections, later outcomes and failures before it is called research-ready. No automatic retraining or self-modifying decision policy is authorized. |
| #74 | Always-on freshness fabric — staggered 24/7 adaptive collection | **NOW as a P0 data-design/operational rule; NEXT for the generalized orchestrator** | One shared freshness supervisor should eventually own source cadence, staggering, streaming/polling choice, quotas, missed-target accounting and decision-time freshness. Immediate action: ADR 0030 Option A is approved so currently lost later/closing depth begins being preserved without waiting for the full orchestrator. |
| #86 | Cross-domain prospective evidence — collect learning-ready data before models exist | **NOW: portfolio + Multi-City Weather v1 design; gated collectors one source at a time** (2026-09-24 evening directive) | Extends #7/#50/#74/#82 and serves #30; duplicates none. Irrecoverable point-in-time evidence first; every source registered, market-relevant, outcome-labelled, budgeted, and scheduled through #74. Record: `docs/owner/2026-09-24-cross-domain-prospective-evidence-directive.md`. COLLECT ≠ MODEL ≠ VALIDATED ≠ ACTIONABLE. **Narrowed 2026-09-25 (#96):** purpose-budgeted collection only. Existing legitimate flows continue; a *new* stream needs a named hypothesis/purpose, outcome plan, rights record, request/storage cost, review/stop date and operational headroom. The automatic twelve-city Multi-City Weather rollout is **no longer the next build** (design #90 kept; queued). Nothing is deleted. |
| #88 | Public Markets Edge — equities, options, futures and intraday research | **First-class domain. NOW: source and licensing research, SEC/official-source planning, paper/sandbox evaluation (no signup), architecture compatibility. NEXT: bounded equity/event data, SEC/macro event studies, liquid ETF/mega-cap universe, paper/sandbox integration. NEXT/LATER by data access: options surfaces, futures cross-asset. GATED: paid data, funding, margin, shorting, derivatives permissions, order-write credentials, live trading** (owner directive 2026-09-24 evening) | Event-driven and relative-value first; options as a volatility/distribution market; futures from a small liquid universe; day trading is a horizon, not an edge. Portfolio rows in `docs/research/ACQUISITION_PORTFOLIO.md` §1.7 (PR #89). Competes on equal terms for first tiny-live. **Queued and narrowed 2026-09-25 (#96):** still first-class, but no public-markets family is active until a research slot opens; the next candidates are slower SEC/earnings events, then exact-fixing crypto, options replication/bounds and slower macro/EIA. The unconditional rule "equity quotes are never duplicated prospectively" (roadmap item 14) is **superseded**: historical products may not reproduce the observed bid/ask/latency, so prospective quote capture may be proposed with a hypothesis-specific value case (still no paid data without approval). |
| #96 | Evidence-to-economics reset: two active research families, capacity-first delivery (owner directive) | **NOW (2026-09-25): Economic Evidence v1** (`docs/owner/2026-09-25-economic-evidence-v1-directive.md`; strategy `docs/strategy/`) | Beside protected EXP-001, at most two new ACTIVE families: **A** narrow sportsbook information vs executable event-market pricing (EXP-002, DRAFT) and **B** same-venue payoff relationships (EXP-003, DRAFT). Economics, capacity, attrition and consumed evidence before model work. Authorizes no order, account, credential, paid service, timer or gate advance. |
| #82 | Adaptive Learning Engine: continuous edge preservation, champion/challenger lifecycle | **Simplified 2026-09-25 (#96): NOW = lineage, evaluation and governance only** (experiment/dataset/model lineage, evidence-consumption records, attrition, standardized challenger review, separate data/model/execution/economic/capacity drift). Autonomous RL, general AutoML and live promotion are **LATER** | Built on `experiments.py` and `research_evidence.py`; no second memory database; no automatic promotion. |
| #83 | External capital: investor unit/NAV accounting and fee governance | **LATER / deferred 2026-09-25 (#96)** | Durable intent kept. Outside investor capital is not authorized; no implementation until an edge and a legal structure exist. |
| #93 | Bootstrap Capital Mode: grow a small bankroll without reckless leverage | **Preserved 2026-09-25 (#96); principles NOW inside the economic screen** | Capital-days, return on deployed vs total capital, lockup, idle cash and capacity are reported by `research_economics.py`. No strategy class is assigned without evidence; no amount is an approved bankroll; #32's 168-hour policy stays intact. |

## Roadmap re-run 2026-09-25: #96 evidence-to-economics reset (Economic Evidence v1)

Dates labelled 2026-09-25 here are UTC. The owner's directive arrived on 2026-09-24 at about
22:10 America/New_York.

This ordering authorizes nothing; `docs/EXECUTION_PLAN.md` does (its 2026-09-25 entry records
the owner's Economic Evidence v1 scope). Re-prioritizing never authorizes implementation. Gate 7
is unchanged and **not passed**. The 2026-09-24 roadmap below stays as the dated record. Where
the two disagree, this re-run wins, and each changed item is named here. Nothing is deleted.

**Research slots.** Protected EXP-001 plus **at most two new ACTIVE families** (validator-enforced;
an exception needs an owner decision document):
- **A:** EXP-002 (DRAFT), NFL pregame moneyline consensus vs executable event-market prices;
- **B:** EXP-003 (DRAFT), same-venue payoff consistency.

Passive bounded collection is not a family, but a *new* stream needs a purpose, budget and
review/stop date. Existing authorized collectors continue until an explicit review.

**NOW** (critical path; authorized by the 2026-09-25 entry)
1. Keep production collecting and verified; EXP-001 Stage B days; first settlement and F09
   (items 1–3 below are unchanged).
2. **Economic Evidence v1:**
   - PR A: the directive record, canonical integration, two DRAFT protocols, evidence
     consumption, attrition and the economic screen;
   - PR B: semantic conformance, the pure same-venue payoff evaluator and the execution-package
     ADR (design only);
   - PR C: paired sports evidence from stored data, a data-gap report, economics/capacity and a
     compact Terminal view.
3. Backup growth and retention (item 4 below). **2026-09-25 update:** an amendment of the
   blanket "before any new collector" prerequisite to byte-based triggers is PROPOSED
   (`docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md` §C, #113). The prerequisite stands until the
   owner decides; the owner's explicit NFL approval governs that stream. The owner decision on retention `proposed-v1` and an off-host copy is
   due by about 2026-10-08 (decision packet Decision 2).
4. W0 operating verification (coordinator lane).

**NEXT** (named prerequisite)
5. **Kalshi NFL game-market books** (old item 12): **APPROVED by the owner 2026-09-25** (#110,
   bounded by SPORTS_PAIRED_EVIDENCE_GAPS §6), implemented (#112) and DEPLOYED (`c05bd8a`,
   2026-09-25 23:23Z). The EXP-002 development pilot runs on kickoffs 2026-09-27 to 2026-10-19.
6. **Preregistration of A and/or B.** Technical settings are PROPOSED and reviewed
   (`docs/research/RESEARCH_UNBLOCKING_DECISIONS.md`, #111). Remaining owner inputs: the minimum
   useful effect and owner hours (decision packet Decision 1). EXP-002 freezes after the pilot, by
   2026-10-21. EXP-003 is recommended PAUSED: the KXHIGHNY partition cannot be proven under the
   current rules. The recommendation is a bounded Kalshi fact-check if the owner approves sending the
   drafted questions, with rejection on 2026-11-15 if unresolved.
7. Sizing v2 evidence (old item 15), unchanged.

**QUEUED (waits for a research slot; re-evaluated on economics and access, not sunk effort)**
8. Weather forecast-revision / information-accumulation.
9. #88: slower SEC/earnings event studies, then exact-fixing BTC/ETH, options
   replication/bounds, slower macro/EIA.
10. Multi-City Weather v1 collection (old item 11). The automatic twelve-city rollout is **no
    longer the next build**. The design (#90) is kept, and a city starts only with a named purpose
    and budget.
11. Conditional liquidity provision.

**DEFERRED** (#96): #83 investor/fund implementation; the general instrument-selection engine;
broad AutoML/RL (#82 beyond lineage); every other sport and props; full options surfaces;
multiple brokerage adapters; HFT-style macro response; social/news firehoses.

**Superseded (dated, kept below as history):**
- the old item 11 "Multi-City Weather v1 collection" as the next automatic build;
- the old item 14 rule that equity bars and quotes are "never duplicated prospectively". It is now
  proposable with a hypothesis-specific value case;
- the idea that many simultaneous domain and model races maximize progress.

## Roadmap (re-run 2026-09-24 evening; superseded in part 2026-09-25, see the re-run above: Freshness Fabric + sports mission, #86 cross-domain evidence, #88 public markets)

This ordering authorizes nothing; `docs/EXECUTION_PLAN.md` does. Re-prioritizing never authorizes
implementation. Gate 7 is unchanged and **not passed**.

**First-live competition (owner, #88 §7).** No domain is pre-selected as the first live strategy.
Weather, sports, public markets, macro, crypto or another legitimate strategy may become the first
tiny-live candidate. The first to clear its own preregistered evidence bar **and** the common
operational live-readiness gate goes first. Research criteria are never weakened to make one win.

**NOW** (critical path; authorized)
1. **Keep production collecting and verified** (#10, #11). Production runs the merged `main` SHA
   recorded in `HANDOFF.md`. Deploys stay outside 17:40–18:50 ET and the 11:15 / 16:15 ET settlement
   runs. **Preflight must PASS before every install.** On 2026-09-24 one install proceeded after a
   load FAIL; the deploy helper now refuses.
2. **EXP-001 Stage B days and shadow bookkeeping.** 2 valid days (2026-09-24, 2026-09-25). No
   retuning, sizing change or criteria change.
3. **First real settlement and F09.**
   - The first positions are due from 2026-09-25T03:50Z, so settlement is possible in the
     2026-09-25 11:15 ET run.
   - Verify fully, then take the manual F09 checkpoint.
   - F09 stays manual: roughly weekly plus notable ledger events. **No F09 timer.**
4. **Backup growth and retention (#86 prerequisite; found by Lanes F and G).**
   - `edgelab-backup` writes a full uncompressed copy of both stores every day and deletes nothing,
     so backup disk grows quadratically. It fills about 64 GB in about 400 days today, and in about
     85–180 days with the proposed collectors.
   - The fixed 30 s backup timeout will also fail once the DB reaches about 0.5–1 GB.
   - Required before any new collector: compression, a size-aware timeout, and a retention or
     off-host policy.
   - **Deleting old backups is an owner decision.**
   - **Re-measured 2026-09-25** (`docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md` B2–B3, §C):
     - backups total 48 MB and 67 GB is free;
     - growth is driven by deploys, which write two full copies each;
     - backups reach 10 GB around 2026-10-14 at the build-out pace;
     - the binding limit is the code's 30 s per step, at about 600 MB, around April 2027.

     The "about 400 days" premise is stale. PROPOSED amendment: byte-based triggers replace the
     blanket prerequisite. A dry-run retention planner is merged (#113); it cannot delete.
5. **#74 Freshness Fabric v1, live** (DEPLOYED 2026-09-24, c6e0dd9).
   - Watch the supervisor, disagreements and missed targets.
   - Terminal "Source freshness" view is live (#91). Read-only units may create SQLite WAL side
     files (#95), so the supervisor no longer goes blind when no writer holds the DB.
   - Migrating an existing schedule into the fabric needs parity evidence and owner approval, one
     source at a time.
6. **Sports prospective data (domain 2) and #9 consensus.**
   - The Odds API pilot is live: 3 captures on 2026-09-24, 491 credits remaining.
   - The consensus benchmark and the target table are live in Terminal.
   - Polymarket US NFL pilot (#84): **ACTIVE** since 2026-09-24 20:40 ET under the **owner's risk
     decision** (not a grant). The first discovery was FILTER_COMPLETE: 33 games, 32
     RELATED_NOT_EQUIVALENT. The first capture is due 2026-09-26. Terminal shows related markets
     (#94).
7. **Later/closing observations (ADR 0030).**
   - Live: the first scheduled +1 h captures (12 rows) at 19:05 ET on 2026-09-24.
   - Verify the close capture (04:57:45Z tick).
   - Re-check `close_tick_alignment` after the 2026-11-01 DST change. Lane G found city closes at
     midnight local *standard* time.
8. **#86 cross-domain prospective evidence, Wave 1: done** (PRs #89 and #90). Acquisition portfolio,
   source readiness, combined budget and the Multi-City Weather v1 design (12 cities). Next is Wave 2
   (item 11), after item 4.
9. **#88 public markets: research and architecture (no signup, no data purchase).**
   - Licensing research per source.
   - EDGAR filing-event planning for a bounded mega-cap universe (keyless).
   - A security ADR for broker-data keys: header transport and order-scoped paper keys.
   - Paper/sandbox route evaluation (Alpaca paper-only first).
   - Instrument/contract identity in the shared primitives (options OCC symbols, futures months,
     sessions via the calendar).
10. **Fee re-checks:** Kalshi by 2026-10-23T13:39:48Z (add SETTLEMENT_AND_TRANSFER_FEES); Polymarket
    US by 2026-10-24T01:39Z.

**NEXT** (ready once the named prerequisite lands)
11. **Multi-City Weather v1 collection** (#86 Wave 2).
    - Needs item 4.
    - Rollout: 12 cities in six bounded PRs (`docs/research/MULTI_CITY_WEATHER_V1.md`); starts with
      the historical Kalshi-vs-NWS settlement agreement check.
    - Every city starts as DATA_COLLECTION, never as an EXP-001 clone.
12. **Kalshi NFL/NCAAF game-market books at the existing Odds capture times.** Lane F's
    recommended next stream: keyless, about 10 requests a day, and it completes the sports series.
    **NFL part APPROVED and deployed 2026-09-25 (#110, #112); NCAAF is not approved.**
13. **Macro release markets and vintages** (#86 Wave 3). Keyless BLS v1, release calendars and Fed
    RSS first; FRED/ALFRED, BEA and EIA need free owner keys. Kalshi macro markets close before the
    release (CPI 08:25 ET), so any reaction window exists only in other open markets.
14. **#88 bounded equity/event data.**
    - EDGAR filing events (keyless) plus the versioned exchange calendar.
    - Then SEC/macro event studies on a liquid ETF and mega-cap universe (SPY, QQQ, IWM, DIA, sector
      ETFs, selected mega-caps). Equity bars and quotes are fetched historically on demand, never
      duplicated prospectively.
    - Then paper/sandbox integration after the security ADR and the owner's free key.
15. **Sizing v2 evidence** (#6): settled decisions under STARTER_MAX_7D_V1, then the preregistered
    sizing experiment.
16. **BTC/ETH bounded public data** (#86 Wave 4), after an exchange terms review. EIA and SEC
    EDGAR for energy and corporate events (Wave 5).

**NEXT / LATER, depending on data access**
17. **#88 options:** volatility and distribution research (implied vs realized, event moves, term
    structure, skew) on INDICATIVE snapshots after the owner's key and the ADR. INDICATIVE is never
    OPRA or execution-grade.
18. **#88 futures:** macro-release and cross-asset studies. CME real-time and historical data are
    PAID/ROI BLOCKED, CFTC COT is slow context only, and synthetic continuous history is never
    executable evidence.
19. **Instrument-selection layer** (#88 §6), once two instruments share a thesis.

**LATER** (wanted; not on the 2026-10-22 path)
20. Sports baseline and preregistered models (#5, #9), each its own experiment. More sports only
    within the free Odds budget: at most one more, moneyline at T-60m.
21. Politics (structured official data only), culture (market data first), long-tail discovery.
    News, social and polling are not tier 1.
22. #27 Action PRO; #32 execution modes (gate 8+); #33 SMS provider; broader venues.
23. **Security task, separate:** root SSH hardening. Out of scope for Market Edge missions.
24. **Brisket follow-ups** (other repository): riskittogetthebrisket#1409; PRs #1406 and #1407 are
    paused.

**GATED / BLOCKED** (named blocker)
- **Paid data:** SIP, OPRA, CME, CF Benchmarks, paid Odds tiers. Needs the #7 ROI case and owner
  approval.
- **Accounts and orders:** brokerage funding, margin, short selling, derivatives permissions,
  order-write credentials, live trading or paper orders. Gates 8–10.
- **Free keys, owner-only** (READY_FOR_OWNER_KEY): FRED/ALFRED, BEA, EIA, Census, Alpaca/Tradier
  data. The broker keys also need the security ADR first.
- **Backup deletion or retention:** owner decision (item 4; decision packet Decision 2, due about
  2026-10-08).
- **ntfy phone delivery:** the phone was subscribed to a different topic. Owner action; out of
  scope for the current mission.
- **Polymarket US claim-grade totals:** settlement/transfer fees, debit rounding and account type
  are unverified.

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
| 11 Public markets (#88: equities/ETFs, options, futures) | E (exchange-defined) | P (EDGAR keyless; IEX single-venue via owner key; SIP/OPRA/CME paid) | E | E continuous | E (bounded liquid universe) | P (commissions/fees per broker; not verified) | E (equities/ETFs) / P (derivatives) | U | P (research-grade feeds only) | P | P (history via vendor APIs; not executable) | E low | **Research and architecture (NOW); data collection NEXT** |
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

- **2026-09-26: owner decisions and first real NFL paired evidence: next batch.**
  - **Decided (owner):**
    - EXP-002: $1,000/yr continuation bar, 6 h to 2026-10-22;
    - EXP-003: paused; the Kalshi questions approved subject to the final text;
    - retention proposed-v1 with manual apply (first cycle done: 3 bundles, 507,904 B);
    - O1 laptop pulls (first pull VERIFIED).
  - **Observed:**
    - #107 same-run settlement verified;
    - the first Polymarket US capture (9/9);
    - the first Kalshi NFL pairs (9 games, 18 sides, all book-at-or-after-odds, about 5 min skew,
      1¢ spreads).
  - **Next implementation batch (dependency order; all within existing authority):**
    1. **NOW:** EXP-002 gate v3.
       - A spread-based noise floor from single captures, which need no new requests. The first
         real books all show 1¢ spreads, a σ floor of about 0.29¢.
       - Combine it into the correlation bound, re-simulate the stickiness grid (false-pass ≤ 10%
         at bias > tolerable), and get an independent review.
       - Needed before any freeze.
    2. **NOW:** EXP-002 freeze inputs, as PROPOSED protocol values for review:
       - tie/not-played bounds (A.D), which clears RULES_UNRESOLVED for the paired events;
       - the episode definition (A.F);
       - the δ_min candidates.
       Freeze only by 2026-10-21 with holdout windows, after the pilot report (owner hours).
    3. **NEXT:** KXNFLGAME fee verification record (G4; `fee_schedules`), from the fee PDF
       re-check and/or Kalshi Q7. Until then economics stay FEE_UNSUPPORTED.
    4. **NEXT:** a Terminal line for the EXP-002 gate state (UI_CONTRACT; small).
    5. **ROUTINE:**
       - O1 weekly (about 2026-10-03);
       - F09 weekly (an apply refuses after 8 days);
       - the next retention dry run and apply at the owner's cadence;
       - settle and verify the 26SEP26 positions.
  - **Classification:**
    - NOW: 1, 2;
    - NEXT: 3, 4;
    - BLOCKED (owner): CI billing, the Kalshi send;
    - BLOCKED (facts): EXP-003 until Kalshi answers or 2026-11-15.

- **2026-09-25 (evening): Research Unblocking directive re-plan** (`docs/owner/2026-09-25-research-unblocking-directive.md`;
  decision packet `docs/owner/2026-09-25-research-unblocking-decision-packet.md`).
  - **Priority:** NOW. Unblock EXP-002/EXP-003 evidence; no new family, subsystem or migration.
  - **Owner decision in the session:** Kalshi NFL capture APPROVED (#110), then implemented and
    deployed (#112, `c05bd8a`).
  - **Recommended and reviewed (PROPOSED):**
    - the EXP-002 protocol: a cross-book markout endpoint, prospective pairing (join v2), a
      label-free correlation gate, and a pilot-based power analysis (#111, #115);
    - EXP-003 paused, pending facts;
    - economics and effort scenarios;
    - backup retention `proposed-v1` with a dry-run planner (#113).
  - **Shared infrastructure:** existing owners only:
    - `price_observations` (NFL planner);
    - `sports_evidence` (join v2);
    - `research_economics` (fill-mode labels v2, ADR 0037);
    - `backup` (dry-run retention plan).
  - **Remaining owner decisions:**
    - Decision 1, research economics and effort, including whether to send the Kalshi questions;
    - Decision 2, backup retention and the off-host copy.

    ntfy stays deferred.
  - **Roadmap effect (2026-10-22 plan):** the EXP-002 pilot runs on kickoffs 2026-09-27 to
    2026-10-19, with the freeze by 2026-10-21 and untouched evaluation from 2026-10-22.
    Classification:
    - NOW: EXP-002 pilot;
    - NEXT: EXP-002 freeze;
    - BLOCKED (on facts): EXP-003;
    - BLOCKED (owner, by 2026-10-08): backup retention.

- **2026-09-25: #96 evidence-to-economics reset and the Economic Evidence v1 directive
  (canonical integration, EE v1 PR A).**
  - **Priority:** NOW. Two DRAFT families (A: EXP-002, B: EXP-003) beside protected EXP-001.
    Economics, capacity, attrition and consumed evidence come before model work.
  - **Dependencies:** the existing registry, consensus benchmark, depth/fee/settlement contracts,
    Terminal. Family A also needs paired Kalshi NFL books (not collected). Preregistration needs
    owner inputs (minimum useful effect, owner hours).
  - **Overlap and supersession:**
    - #82 is simplified to lineage, evaluation and governance;
    - #86 is narrowed to purpose-budgeted collection;
    - #88 stays first-class but is queued and narrower;
    - #83 is deferred;
    - #93 and #32 are preserved;
    - the automatic twelve-city rollout and the unconditional equity-quote rule are superseded
      (dated, not deleted).
  - **Shared infrastructure:**
    - the registry is extended with a protocol sidecar and family slots;
    - new canonical owners: `research_evidence.py`, `research_economics.py`;
    - `payoff_constraints.py` (BUILT in PR B, #102; see the Shared primitives table).

    No second registry, ledger or memory store.
  - **Safe parallel lanes:**
    - EE Writer 1 owns the shared contracts and canonical docs (PR A, PR B);
    - EE Writer 2 owns sports pairing and the Terminal (PR C) and consumes the attrition and
      economics contracts;
    - the coordinator owns W0 and the final HANDOFF.
  - **Roadmap effect:** re-run 2026-09-25 above. The 2026-10-22 checkpoint now emphasizes two
    budgeted protocols, their evidence reports, the semantic/unit/fee proof, paired-data gaps,
    dollar/capacity scenarios, a restore result and one disabled order-lifecycle specification.
    It is not a scheduled alpha verdict. The date is unchanged.
  - **Classification:** #96 NOW; #82 NOW (lineage only) and LATER (autonomy); #83 LATER; #86 NOW
    (existing flows) and NEXT/QUEUED (new streams); #88 QUEUED; #93 NOW (inside the screen).
  - No gate change. No paid source. No order, account, credential or timer.


- **2026-09-24 (night): canonical reconciliation after the Freshness Fabric + sports mission,
  #86 and #88.**
  - **#88 Public Markets Edge** becomes a first-class domain: an index row, a Domain Readiness row,
    and NOW/NEXT/LATER/GATED placement.
  - **First-live competition:** no domain is pre-selected.
  - **New canonical owners:** the consensus benchmark, research readiness, a planned release/event
    calendar, and a planned instrument-selection layer.
  - **#74 v1 deployed:** it observes and controls nothing yet.
  - **Backup growth/retention** is a NOW prerequisite before any new collector. Deletion is an owner
    decision.
  - **#86 Wave 1 is done;** Multi-City Weather v1 (Wave 2) is NEXT.
  - **Polymarket US pilot:** owner risk decision recorded, not a verified grant.
  - No gate change. No paid source. The 2026-10-22 date is unchanged.

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
