# Owner Ideas

Durable owner requirements live in GitHub `[Owner Idea]` / `[Owner Directive]` issues. This is the current index and canonical shared-owner map, not a replacement for the issue bodies. The process authority is issue #4; the canonical rule is `AI_INSTRUCTIONS.md` → Owner ideas. **An issue is not authorization**, and re-prioritizing never authorizes implementation.

## Current delivery order

**Read [the integrated delivery roadmap](strategy/DELIVERY_ROADMAP.md) for the full dependency order, completion criteria, evidence gates and next batch.** It incorporates #145's podcast lessons and all ideas indexed below. The companion [Claude handoff](strategy/CLAUDE_SPORTS_INTELLIGENCE_RFQ_V1.md) specifies the next bounded implementation mission.

This consolidation is dated **2026-09-29 America/New_York**, audited against main `73b54cab8a3e383961550ef3086df6235b1e03b4` (#144). Runtime facts remain in `HANDOFF.md`; **only `docs/EXECUTION_PLAN.md` records implementation/operational authority**. A roadmap item, issue, proposal or podcast claim grants no account, trading, data-license, spending, schedule or gate permission.

The previous complete index, shared-owner table, roadmap reruns, domain-readiness matrix and review log are preserved **byte-for-byte** in [the historical archive](strategy/archive/OWNER_IDEAS_pre_podcast_2026-09-29.md), using original Git blob `b0689cc48dfc8dd127636b67f7b0a3dc1d0e323d`. This is an explicit consolidation of stale duplicated current-state prose, not deletion of owner intent. The archived schedules/statuses are historical; where a dated ordering conflicts, the ordering here and in DELIVERY_ROADMAP wins for sequencing only. Owner decisions recorded in EXECUTION_PLAN, `docs/owner/` and the archived review log are not superseded by this consolidation.

## Intake and readiness rules

- Capture material owner ideas in a canonical issue; search for overlap first. Record enough context for a fresh model and link related requirements.
- Re-plan material additions in the same session: priority, dependencies, overlap/supersession, shared owners, safe lanes, October 22 effect and authority.
- NOW means within the current critical path **and** existing authority. NEXT means a named prerequisite remains. LATER retains wanted scope off the immediate path. BLOCKED names evidence, access or owner authority still needed. DONE/MAINTAIN is an implementation status, not proof of edge.
- Preserve protected EXP-001 and the #96 limit of two new ACTIVE hypothesis families. An offline fixture or passive, authorized source is not a new hypothesis. Do not hide an empirical strategy behind those labels. EXP-003's pause does not silently assign a slot to #122 or RFQ.
- Never infer TESTED, CI_GREEN, MERGED, DEPLOYED, PRODUCTION_VERIFIED or research success from an earlier state.
- Use one canonical owner per concept. New modules below are planned only where no implementation is established; inspect current code before creating one.

## Complete current idea index

| Issue | Requirement | Current placement / next dependency |
|---|---|---|
| #4 | Durable idea intake / readiness process | DONE/MAINTAIN; keep this index, issue truth and roadmap aligned |
| #11 | October 22 delivery / live-readiness goal | Cross-cutting checkpoint; software/evidence readiness, not a promised positive verdict or trade date |
| #3 | Outcome Board / what matters today | Existing backend/view; integrate readable event identity, inventory/risk, outcomes and actual unavailable states; no separate app; hosting beyond the tailnet and live marks remain unauthorized |
| #47 | Market Edge Terminal design system | Existing shell/tokens/components; mobile, desktop, accessibility, empty/stale/unsupported/error states accompany every user-visible package |
| #10 | Private hosting on existing infrastructure | DONE/MAINTAIN; current deployment/runbooks and isolation, no public site exposure implied |
| #12 | Brisket portability audit (other repository) | Out of Market scope; root SSH hardening is a separate security task, also out of scope for Market missions (archive items 23–24) |
| #5 | Sports expansion and modeling | NFL EXP-002 (DRAFT, family A); NHL collection separate; later sport/model experiments need budget, protocol and slot |
| #9 | Sportsbook consensus / cross-market comparison | Baseline implemented; finish current fee/timing/rules questions. #145 adds future conditional source leadership, not a retroactive baseline rewrite |
| #29 | The Odds API pilot | NFL and NHL use one joint 450-credit monthly proof/ledger, NFL reservation first; no extra paid plan or ceiling assumed |
| #134 | NHL prospective evidence | BUILT/ACTIVE per latest handoff (DATA_COLLECTION / DEVELOPMENT_ONLY; Odds `icehockey_nhl` h2h under the joint 450 ledger after NFL's reservation; Kalshi KXNHLGAME only, own request bound). NEXT: coverage review and the NHL decision packet (October coverage, default (a); protected-window contract); fee/shootout rules (2026-09-30, PR C: KXNHLGAME fees now FEE_UNSUPPORTED in code as well, consistent with KXNFLGAME; shootout and tie remain RULES_UNRESOLVED; `docs/research/CURRENT_BLOCKERS.md`). LATER: a separately allocated, preregistered hockey experiment. BLOCKED (owner): paid tier or ceiling change. Not EXP-002; no slot claimed |
| #122 | In-play positions: HOLD/REDUCE/EXIT, then REENTER/ADD | Offline evidence/policy/replay/Terminal foundation BUILT; state-version invalidation, in-flight changes and resting fills after a state change BUILT (#149, ADR 0041); the in-play page shows source/state validity and simulated fill-conditioned economics (PR C). NEXT: scoped recorder approval and source-quality evidence; state-aware models/re-entry later; live actions BLOCKED. The 295/week pregame approval does not extend to in-play, and EXP-002's budget is not #122's |
| #145 | Conditional price discovery, RFQ/combos, adverse selection and full roadmap integration | 2026-09-30: R2 shared source/state/latency and fill-conditioned economics DONE (#149, `04bf78c`); R4 RFQ feasibility DONE, decision NARROW, owner decisions D1–D6 open (#148, `519580d`); R1 blockers PARTIAL (PR C: explicit fee map, `current_blockers` register, Terminal displays). NEXT: R3 pilot-proposal refresh. RFQ observation/quoting/empirical joint pricing require separate access/slot/authority |
| #30 | Multi-venue identity, best price and unique markets | Existing Kalshi/Polymarket foundations and best-size comparator; fees/rights/equivalence gaps remain. Novig and further routes follow a specific need; one execution route deeply before many; Novig live API BLOCKED (credentials); Polymarket US NFL pilot ACTIVE under the owner's risk decision (not a verified grant) |
| #6 | Bankroll, risk, sizing and withdrawal guidance | Shadow foundation and sizing-v2 challenger exist; evidence/review before operational promotion. Extend one risk owner, never a live shortcut; the withdrawal contract never recommends a draw |
| #32 | Starter capital horizon / execution preference | Keep STARTER_MAX_7D_V1 and 168-hour venue-tradable-cash meaning; hoped-for early sale does not satisfy it. One-venue order/reservation rehearsal before live |
| #93 | Bootstrap Capital Mode | NOW inside economics/capacity; separate total/deployed return, turnover, lockup, drawdown and fixed cash cost; actual bankroll not inferred from examples |
| #50 | Longitudinal evidence, including rejected opportunities | Existing immutable provenance and lineage; extend denominators, no-fill/unknown records, revisions and evidence-consumption logs |
| #74 | Always-on Freshness Fabric | Existing supervisor and sport-specific identities; conditional game-state validity extends it. Migrating a schedule into the fabric needs parity evidence and owner approval, one source at a time; no duplicate schedulers |
| #7 | Free-first / paid-source value | Permanent constraint: marginal research/execution value case before a purchase; free is not automatically sufficient and paid is not automatically better |
| #27 | Action PRO / subscription comparisons | LATER/BLOCKED on a named hypothesis, rights, incremental value and owner spending approval |
| #36 | Selective external implementation reuse | Reuse only after current audit/license/compatibility review; no other-repository edits in a Market mission |
| #86 | Cross-domain prospective evidence | Acquisition and multi-city design exist. Purpose-budgeted streams only; preserve all intended domains in R9 without automatic firehose rollout |
| #88 | Equities/ETFs, options, futures and intraday research | Retained first-class domain, queued by slot/economics. Slower SEC/earnings first; later volatility/replication, exact contract futures/macro; data/broker prerequisites explicit |
| #82 | Adaptive Learning Engine | Existing lineage/evaluation first; source value, calibration, execution/economic/capacity drift, champion/challenger review. AutoML/online/RL later; auto-train never auto-live |
| #83 | Outside capital, unit/NAV accounting and fee governance | LATER/BLOCKED; simulated design then legal/entity/custody/tax/venue and owner approval. Separate investor gains from manager compensation; no friend-money pooling now |
| #33 | Notifications / SMS / ntfy | Existing outbox/relay; SMS blocked on provider approval; phone delivery unresolved and owner-deferred for current research. Reliable alert/incident path required before unattended live; no new test/send from this plan |
| #96 | Evidence-to-economics reset | Governing strategy: evidence, after-cost dollars, executable size, capacity and survival before breadth. Full roadmap does not mean every experiment active together |
| #160 | Kalshi ordinary-event automation core (owner directive 2026-10-07) | Packages A–T in `strategy/KALSHI_EXECUTION_LEDGER.md`. A/C, D/E (#164, #165) MERGED; H and B/F in review/merge; I in progress. All offline in the ADR 0043 package, FIXTURE only. NEXT: G, J–Q, orchestration. BLOCKED (owner): demo and production-read access (activation packet); LIVE and UNATTENDED stay false |
| #168 | Wallet intelligence and copyability research (owner directive 2026-10-07 evening) | NOW, offline research lane outside the execution package: event model, point-in-time selection, leader vs follower reconstruction and replay on synthetic plus Polymarket Data API v2 documentation fixtures; no network. BLOCKED (owner): any live source read, paid feed, empirical slot or budget, and venue eligibility for execution. Feeds execution only through a reviewed typed bridge |
| #152 | Architecture reconciliation and bounded evidence-path hardening (owner directive, 2026-09-30) | Existing architecture kept. External ideas classified by access and usefulness in [the reconciliation note](engineering/ARCHITECTURE_RECONCILIATION_2026-09-30.md); only the controlled defect loop is adopted (AGENT_OPERATING_SYSTEM §1). The in-play file → consumer path is verified, and two provenance gaps are fixed in `inplay_evidence.py` (PR pending owner merge). NEXT: R3 as recorded (scope entry, then the pilot-proposal refresh); R3a, in-play journal identity and point-in-time slicing, is *proposed* for that scope entry. Rejected without a measured need: memory DB, second scheduler, graph framework, agent platform, Steward transplant, behavioural-eval harness (ADR 0006). Not runtime authority |

## Shared primitives (one canonical owner each)

Extend the owner named here; never fork it into a feature-specific copy. `PLANNED` means the owner is chosen but not built; inspect current code before creating it. Ownership is not a production-state claim. Dated detail is in the archive.

| Primitive | Canonical owner | State | Serves |
|---|---|---|---|
| Event / market identity | `src/edge_lab/opportunity.py` | BUILT (Event, Market, settlement_identity; native quantities and probability/payoff types explicit) | #5 #9 #30 #32 #134 |
| Rules / settlement equivalence | `src/edge_lab/opportunity.py` | BUILT (Event.settlement_identity, Market.rules_resolved; cross-venue classification in discovery.py; title match is never equivalence; none proven across venues yet) | #30 #9 |
| Venue and account capability registry | `src/edge_lab/venues.py` | BUILT (per-capability stages, cash timing, ADR 0019; execution never authorized). #145 book-making, RFQ-observe and RFQ-quote capabilities are added here, each verified separately, not in a second registry | #30 #32 #29 #9 #145 |
| Quote / order-book normalization | `src/edge_lab/opportunity.py` | BUILT (ExecutableQuote, DepthLadder, walk_ladder, PriceGrid, ADR 0023; sportsbook odds are never executable) | #30 #9 #29 |
| Best-price-for-size comparator | `src/edge_lab/best_price.py` | BUILT (ADR 0027; cross-venue cheaper only on proven equivalence and fees) | #30 #9 |
| Fee models and fee verification | `src/edge_lab/fee_schedules.py` | BUILT (ADR 0017; Polymarket US UNVERIFIED estimate, ADR 0027; KXNFLGAME FEE_UNSUPPORTED by the captured list; KXNHLGAME and KXMVE* combination series FEE_UNSUPPORTED by the explicit not-proven-standard map, `not_proven_standard`, PR C). Reuses frozen fees.py; taker, maker and RFQ scopes stay separate | #6 #30 #9 #145 |
| Model estimates | `src/edge_lab/opportunity.py` | BUILT (ModelEstimate; available models are not inferred from a domain enum) | #5 #9 #32 |
| Source ingestion, provenance and rights | `src/edge_lab/sources.py` | BUILT (registry fronting storage.py, provenance.py, redaction.py; no second evidence database) | #7 #29 #30 #27 |
| Freshness orchestration and state validity | `src/edge_lab/freshness.py` | BUILT (v1, ADR 0031; freshness_fabric.py supervisor observes, controls nothing). #145 state-version records and decision validity are BUILT in inplay_evidence.py (source-state-v1, ADR 0041); freshness.py consumes them for validity, never a second scheduler | #74 #86 #88 #7 #9 #29 #50 #145 |
| Sportsbook consensus benchmark | `src/edge_lab/odds_consensus.py` | BUILT (ADR 0033; RESEARCH BENCHMARK, NOT EXECUTABLE; EXP-002 frozen baseline, variants are registered) | #9 #5 #29 #82 |
| Sports odds capture scheduling | `src/edge_lab/odds_schedule.py` | BUILT, ACTIVE (ADR 0029; sport-aware NFL+NHL, one joint 450-credit proof and ledger, NFL first, ADR 0039) | #29 #5 #9 #50 #134 |
| Later / closing price observations | `src/edge_lab/price_observations.py` | BUILT, ACTIVE (ADR 0030; Kalshi NFL and KXNHLGAME targets, ADR 0040; MISSED stays MISSED) | #74 #50 #30 #9 #29 #134 |
| Paired sports evidence | `src/edge_lab/sports_evidence.py` | BUILT (join v2; T-60m label-proxy withholding; exp002_timing.py subordinate) | #5 #9 #96 |
| Per-domain research readiness | `src/edge_lab/research_readiness.py` | BUILT (YES / PARTIAL / NOT_YET / UNKNOWN from real stores; never green by default) | #50 #86 #88 #82 |
| Release / event calendar | `src/edge_lab/event_calendar.py` | PLANNED (one shared calendar, never one per domain; docs/research/SOURCE_READINESS.md §9) | #86 #88 #74 #82 |
| Instrument selection | `src/edge_lab/instrument_selection.py` | PLANNED; DEFERRED by #96 until two concrete expressions exist; not a pre-live gate | #88 #30 #82 #6 |
| Experiment registry, protocol sidecar and family slots | `src/edge_lab/experiments.py` | BUILT (EXP-001 LEGACY and unchanged; at most two new ACTIVE families, #96) | #96 #82 #5 #9 |
| Research-evidence lineage | `src/edge_lab/research_evidence.py` | BUILT (evidence use, attrition). The #145 bidirectional source-leadership report and latency stages are BUILT in inplay_evidence.py (source-state-v1, ADR 0041), fixture- and synthetic-fed; real series would record their evidence use here; not a second learning engine | #96 #82 #50 #145 |
| Research economics | `src/edge_lab/research_economics.py` | BUILT (episodes, capital-days, deployed vs total return, fixed cash cost, fill-mode labels v2 ADR 0037). #145 taker/maker/RFQ modes, actual vs simulated fills, fill-conditioned markouts, the funnel and seasonal scenarios are BUILT (fill-conditioned-economics-v1, ADR 0041); owner hours stay unpriced unless the owner supplies a rate | #96 #93 #6 #32 #145 |
| Same-venue payoff-constraint evaluator | `src/edge_lab/payoff_constraints.py` | BUILT (ADR 0036; deterministic logical relations, not a joint-probability model; EXP-003 PAUSED) | #96 #5 #9 #30 #145 |
| In-play position policy | `src/edge_lab/position_policy.py` | BUILT offline (ADR 0038; HOLD/REDUCE/EXIT; no account transport) | #122 #6 #145 |
| In-play evidence and replay | `src/edge_lab/inplay_evidence.py` | BUILT offline (ADR 0038; inplay_replay.py and inplay_view.py subordinate; no recorder). #145 state-version, source-family, clock-uncertainty and latency fields BUILT (source-state-v1, ADR 0041). A journal's data kind comes from its header, and a book's venue stamp is its last applied message's own (#152). Journal content identity through the consumer: proposed for the R3 scope entry (R3a) | #122 #145 #50 #152 |
| RFQ research and lifecycle fixtures (joint pricing PLANNED later) | `src/edge_lab/rfq_research.py` | BUILT (PR B, ADR 0042: pure, fixture-fed observation and exposure contract; reuses venues (execution never authorized), provenance and freshness, and reserves through execution_ticket's canonical obligation primitive; RFQ stages stay separate from execution_ticket orders; payoff_constraints stays the logical-relation owner; joint pricing PLANNED later (R7); no gateway or generic pricing engine) | #145 #30 |
| Shadow / live ledger boundary | `src/edge_lab/shadow_ledger.py` | BUILT (shadow only; ledger_anchor.py checkpoints, F09) | #6 #3 #32 |
| Isolated execution package (Kalshi ordinary-event profile) | `src/edge_lab/execution/` | BUILT in part (ADR 0043; model, journal, reservations merged; lifecycle, wire, signer, transport in review; FIXTURE only) | #160 #6 #32 |
| Autonomous orchestration (one supervised service, DISARMED → BOUNDED_AUTO) | `src/edge_lab/execution/orchestrator.py` | PLANNED (2026-10-07 evening directive; no second scheduler; starts DISARMED) | #160 #168 #82 |
| Wallet / trader intelligence and copyability | `src/edge_lab/wallet_intel.py` | PLANNED (#168; extends sources/provenance; no second ledger, graph platform or scheduler; outside the execution package) | #168 #50 #82 #30 |
| Risk engine | `src/edge_lab/risk.py` | BUILT (limits, capital release, withdrawal contract) | #6 #3 |
| Stake sizing (research challenger) | `src/edge_lab/sizing_v2.py` | BUILT, research only (ADR 0026); sizing.py stays the frozen operational path | #6 #3 #32 |
| Capital-eligibility policies | `src/edge_lab/starter_policy.py` | BUILT (STARTER_MAX_7D_V1, 168-hour venue-tradable cash, ADR 0018) | #32 #6 #93 |
| Notification system | `src/edge_lab/notifications.py` | BUILT (ADR 0020; ntfy relay ACTIVE; phone delivery unresolved and owner-deferred) | #33 #3 #32 |
| Execution-ticket contract | `src/edge_lab/execution_ticket.py` | BUILT (data contract and pre-submit chain; EXECUTION_NOT_AUTHORIZED always fails; ADR 0035). Durable lifecycle, reservations, fencing and RFQ binding points extend it | #32 #33 #30 #122 #145 |
| Simultaneous obligation reservation | `src/edge_lab/execution_ticket.py` | BUILT (#149, ADR 0041; reserve_simultaneous_obligations, pure; no netting, no partial acceptance, unknown stays reserved); the one reservation primitive, which `rfq_research` (#148) calls | #145 #30 #93 |
| Current research-blocker register | `src/edge_lab/current_blockers.py` | BUILT (PR C; generates the register block of `docs/research/CURRENT_BLOCKERS.md`; the Terminal shows it; grants nothing) | #145 #134 #122 #9 |
| Backup and restore | `src/edge_lab/backup.py` | BUILT (proposed-v1 manual reviewed retention; O1 weekly laptop pull keeps 4; no paid cloud) | #10 #50 |
| Operator views | `src/edge_lab/dashboard/` | BUILT (read-only; tailnet-only, ADR 0024) | #3 #6 #10 #122 #134 |
| Design system (Market Edge Terminal v1) | `docs/design/UI_CONTRACT.md` | BUILT (ADR 0025, issue #47) | #47 #3 #6 #9 #10 #29 #30 #32 #33 |
| Longitudinal learning history | `docs/DATA_PROVENANCE.md` | FOUNDATION BUILT (immutable snapshots, captures, experiment records, rejections, shadow ledger); no duplicate evidence store | #50 #5 #7 #9 #27 #29 #30 |

## Review log

Entries before 2026-09-29 (evening), with their classifications and supersessions, are in [the archive](strategy/archive/OWNER_IDEAS_pre_podcast_2026-09-29.md) §Review log. Dated references elsewhere to sections of this file ("item 4", "roadmap re-run 2026-09-25", "Domain Readiness matrix") resolve there.

- **2026-09-29 (evening): #145 podcast / RFQ intake and roadmap consolidation: re-plan.**
  - **Priority:** below R0 protected operations and R1 EXP-002/NHL blockers; the next build is R2 (shared source/state/latency/economics) with R4 (RFQ feasibility, documentation only) in parallel.
  - **Dependencies:** R1 fee/rule facts; the existing `inplay_*`, `position_policy`, `research_economics`, `venues` and `execution_ticket` owners; scope record EXECUTION_PLAN 2026-09-30 entry (PR #147).
  - **Overlap / supersession:** conditional source leadership extends #9/#74/#82 without touching the EXP-002 baseline; state validity extends #74/#122; fill-conditioned economics extends #93/#96; RFQ is new (#145). Supersedes only the stale current-state prose of the archived file, not any owner decision.
  - **Shared infrastructure:** no new owner except `rfq_research.py` (Shared primitives table; built by PR B, ADR 0042); no second scheduler, ledger, risk engine, learning engine or evidence store.
  - **Safe parallel lanes:** two writers (PR A shared contracts; PR B RFQ packet), PR C after both; independent reviewer.
  - **Roadmap effect (2026-10-22 plan):** date unchanged; the checkpoint adds a scoped RFQ feasibility result and offline in-play extensions; no freeze, verdict or live date promised.
  - **Classification:** NOW: PR A/B/C offline scope. NEXT: `inplay-source-pilot-1` decision; R5 offline-only lifecycle (needs its own scope entry). LATER: R6–R9, R11. BLOCKED (owner/access): authenticated RFQ observation, any quote/acceptance, empirical joint pricing and in-play evaluation (slot, rights, budget), paid data, live (R10).
  - No gate change. No order, credential, stream, schedule, budget change, paid service or message.

- **2026-09-30: #152 architecture reconciliation and bounded hardening: re-plan.**
  - **Priority:** R0 evidence integrity on the R2/R3 in-play path. Below the R1 owner and venue blockers. No new package.
  - **Dependencies:**
    - the existing `inplay_evidence`, `inplay_view`, `position_policy`, `inplay_replay`, `research_economics` and
      `freshness` owners;
    - `docs/AGENT_OPERATING_SYSTEM.md`;
    - ADR 0006.
    - Scope record: EXECUTION_PLAN, 2026-09-30 architecture-reconciliation entry.
  - **Overlap / supersession:** overlaps #36 (selective external reuse) for idea intake, without superseding it. It
    extends the #122 offline foundation and the #4 process through AOS §1, "Defects". It supersedes nothing.
  - **Shared infrastructure:** none new. It extends existing owners only: no memory database, second scheduler,
    graph framework, agent platform or eval harness.
  - **Can this ride an already-needed shared primitive?** Yes. R3a (journal identity through `inplay_view`) is the
    same attribution the future recorder (R3 → R6) and the #50 learning history need. Building it once in
    `inplay_evidence` serves all three.
  - **Safe parallel lanes:** one writer (this PR), plus a read-only researcher and a read-only reviewer.
  - **Roadmap effect (2026-10-22 plan):** date unchanged. The checkpoint gains verified provenance on the offline
    in-play path. No freeze, verdict or live date is promised.
  - **Classification:**
    - NOW: this bounded slice.
    - NEXT: R3 (a new scope entry, then the `inplay-source-pilot-1` refresh); R3a is proposed for that entry, unordered.
    - LATER: behavioural agent evals (ADR 0006 triggers).
    - BLOCKED (owner): any recorder, capture, rights change or research slot.
  - No gate change. No order, credential, stream, schedule, budget change, paid service or message.

### 2026-10-07 (evening): Market v1 + controlled autonomy + wallet intelligence (#160, #168)

- **Source:** the owner adopted the pasted 25-section directive
  (`docs/owner/2026-10-07-market-v1-autonomy-wallet-directive.md`). Scope is in EXECUTION_PLAN.
- **Overlap search:** no existing issue covered wallet, copy or leader following. #168 was created. #160 already
  covers the execution core and is extended, not duplicated.
- **Priority:**
  - The Kalshi execution core comes first: H, B/F, I, then G/J/K/L, the orchestrator and M/N/O/P/Q.
  - The wallet lane runs alongside it as offline research.
  - UI journeys follow once the schemas stabilize.
- **Dependencies:**
  - wallet → execution only through a reviewed typed bridge, after the orchestrator and risk gate exist;
  - any empirical wallet result needs a #96 slot and budget;
  - any live source read or execution venue needs the activation packet.
- **Shared infrastructure:**
  - one orchestrator inside the execution package (no second scheduler);
  - `wallet_intel.py` extends `sources`/provenance (no second ledger);
  - the Terminal shell for every journey.
- **Can this ride an already-needed primitive?** Yes:
  - follower replay reuses `research_economics` (fill-conditioned economics) and the execution package's exact
    arithmetic;
  - selection manifests reuse `research_evidence` lineage;
  - leader and follower accounting reuses the risk/obligation primitives rather than a parallel P&L.
- **Safe parallel lanes:** execution/account/recovery, wallet data/analytics/replay, UI/operations after the
  schemas, and an independent read-only reviewer. One writer per shared owner.
- **Roadmap effect (2026-10-22 checkpoint):** software readiness advances. No strategy qualification, demo
  verification or live date is promised.
- **Classification:**
  - NOW: Kalshi packages H–Q offline, the orchestrator, the wallet research lane on fixtures, the v1 manifest and
    the unblock packet.
  - NEXT: operator journeys on canonical data; the typed wallet → execution bridge.
  - LATER: on-chain execution profiles (a separate conformance profile) and the paid wallet feeds' value case.
  - BLOCKED (owner): demo and production keys, live source reads, rights, slots and budgets, the risk profile and
    real-money activation.
- No gate change. No order, credential, stream, schedule, budget change, paid service or message.
