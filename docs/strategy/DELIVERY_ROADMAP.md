# Market Edge — Integrated Delivery Roadmap

Owner directive and new research requirement: **#145**. Planning date: **2026-09-29 America/New_York**. Audit base: `73b54cab8a3e383961550ef3086df6235b1e03b4` (#144).

This is the **current dependency-ordered delivery plan for the entire indexed Market roadmap**, not a new authorization file. Read [OWNER_IDEAS](../OWNER_IDEAS.md) for issue traceability and canonical owners; `EXECUTION_PLAN.md` alone defines permitted runtime work. The [next Claude handoff](CLAUDE_SPORTS_INTELLIGENCE_RFQ_V1.md) executes the next bounded batch. The previous index/roadmap is [archived byte-for-byte](archive/OWNER_IDEAS_pre_podcast_2026-09-29.md).

## 1. What the owner is asking us to finish

Build a coherent system that can discover, test and eventually capture a genuine after-cost edge; know the useful size, risks and source of that edge; then add another supported strategy. The owner wants the **whole roadmap accounted for and worked through in a sensible order**, not endless idea intake, duplicated infrastructure or fifteen unfinished experiments.

Software completion, permission readiness, data availability, statistical support and actual live profit are different. A code package may finish while its evidence window remains open. A research package may finish with NO_EDGE, ECONOMICALLY_UNVIABLE or ACCESS_BLOCKED. An idea can remain explicitly deferred without disappearing.

The long-term $50k–$100k annual after-cost trading-profit objective is aspirational. Actual starting bankroll is not specified by old shadow accounts or examples. Owner deposits, investor capital, software revenue, rebates and trading profits are separate. Do not use leverage, return targets or daily quotas to bridge an economic shortfall. Owner effort is recorded in hours, not priced without a new decision.

## 2. Repository truth at the audit

GitHub showed no open PRs and an empty work-claim table before this documentation branch (later: #147 records the 2026-09-30 directive scope in EXECUTION_PLAN). Local/unpushed work and VPS state were not directly inspected. `HANDOFF.md` reports production `23b7b3b`, thirteen timers and the following completed work; these are dated coordinator records, not new operational verification by this audit.

| Existing foundation | Reuse / remaining boundary |
|---|---|
| Protected NYC EXP-001, settlement, immutable shadow ledger, checkpoints | Preserve all frozen artifacts, decisions, fees/fills, evaluation schedule and journals. No extra statistical looks |
| NFL sportsbook pilot, consensus, Kalshi/Polymarket paired research | Raw/derived/source distinctions, joint quota and label protection already exist. No new consensus engine |
| EXP-002 E1 round-trip measurement and outcome-proxy closures | Implemented, proposed/gross-only where fees unsupported, DRAFT. Do not resurrect abandoned spread-noise gates or expose T-60m labels |
| Tie/not-played source study | Proposed t_max/u_max values exist; not approved physical-probability truth or permission to alter protocol |
| A.C timing calibration tool (#142/#143) | Built/deployed; one logged run once, after the last pilot-week target (kickoffs through 2026-10-19 ET) has passed and before the 2026-10-21 freeze, not an immediate redo. Unavailable now is a date/evidence prerequisite, not missing code |
| NHL discovery/odds/books/freshness/Terminal (#134) | Active collection/development only. Opening-night capture completed for eligible horizons. NFL sample remains separate |
| In-play evidence contract, position_policy, replay and Terminal/ADR 0038 (#122) | Offline foundation built. Inspect before additions; real source-quality capture and empirical policy tests still need scope/rights/slot |
| Economics, consumed-evidence logs, attrition, sizing challenger | Reuse. Do not create a second learning/risk/ledger subsystem |
| Backup retention/manual apply, verified laptop copy, F09 | Already performed under recorded approval. Maintain exact safe policy, not another initial destructive run |
| One-venue execution ticket/ADR | No complete live authorization. One real lifecycle and atomic reservations still need appropriate implementation/review |

Current operational/owner blockers remain: Kalshi message revision/channel, signed-in data-rights review, NFL/NHL fee and rule facts, NHL protected-window alignment and October quota choices, E1 review and October 22 owner freeze review. Existing default NHL budget policy continues unless the owner changes it. An apparently stale statement in an older roadmap is not a new approval request.

## 3. Podcast intake: evidence versus useful hypothesis

**POD-01**: user-supplied Inside Prediction Markets interview with Steven / Even Steven. No episode URL/date or independently audited performance was supplied. Repeated words and name spellings are transcript artifacts; do not invent a publication date, verified identity or missing context.

| Transcript content | Treatment | Product/research consequence |
|---|---|---|
| Reported large P&L and taking/making ROI | Self-report; denominator, bankroll, expenses and attribution not established | No forecast. Require explicit ROI denominators and total portfolio economics |
| Shift from taking toward RFQ/making | Experience of one participant, not proof of a universal best route | Separate taker, order-book maker and RFQ modes; study each economics/capability |
| Books appeared ahead one weekend, PMs another | Testable observation, not causal proof | Conditional bidirectional source leadership, phase/regime and clock/state controls |
| Pregame/rotation/personnel assumptions affect live numbers | Plausible mechanism to test | Version pregame context and challenge it prospectively against simple baselines |
| Same-game combos need correlation | Joint-pricing requirement | Logical constraints are not estimated joint probabilities; preserve model uncertainty |
| Best-price copying can receive a different subset of trades | Useful adverse-selection hypothesis | Conditional-on-own-fill analysis; no imported portfolio P&L or private-flow assumptions |
| World Cup demand followed by competition | Anecdotal regime/capacity change | Season/event segmentation; do not extrapolate peak demand year-round |
| Short live windows and developer improvement | Anecdotal latency value | Measure upstream, transport, processing, risk and venue delays before optimizing |
| NASCAR fallback loss | Unverified amount, valuable failure example | Contract-exception explanation, rule proof and unknown exposure refusals |
| Niche expertise and relationships | Candidate selection/operating lesson | Screen domain competence and small capacity; propose expert review when justified, no hiring/spend implied |
| Offshore withdrawals, intentional delays/manipulation, taxes, firm profitability | Unverified/alleged or time-sensitive | Not evidence for access, tax treatment, investment returns or accusations; no evasion/tactics adopted |

**Independent primary-document checks (DOC-01..04, checked at this intake):**
- DOC-01: https://docs.kalshi.com/getting_started/rfqs . RFQs are a negotiation/execution workflow, including combination markets; acceptance, maker confirmation and actual orders/fills are different stages. Sizes, costs and timing are product-specific and must be versioned before implementation.
- DOC-02: https://docs.kalshi.com/websockets/communications . Authentication is required; request events are broadly visible but quote events are participant-private. Market filtering is not promised by the channel; receiving all messages then filtering locally still consumes bandwidth/compute. Recheck available sharding/filter behavior and delivered rights before any recorder.
- DOC-03: https://the-odds-api.com/sports-odds-data/update-intervals.html . Published cadence differs by product, including 40-second in-play featured-bookmaker updates. Local speed does not establish upstream timeliness.
- DOC-04: https://docs.kalshi.com/getting_started/maintenance_and_pauses . Trading and exchange pauses have different cancellation behavior. A kill switch cannot guarantee liquidation or cancellation through every outage.

These checks are documentation, not endpoint smoke tests, eligibility, a storage/training license or an SLA. Exact messages, fields, fees and timing must be reverified when building. No source is promoted to true/faster/profitable because it appears in the interview.

## 4. Governing sequencing rules

1. **Operate and preserve evidence continuously within existing authority.** A confirmed safety or rights failure stops the affected use and collection at once (EXECUTION_PLAN: each source's terms respected) and is escalated to the owner; an unresolved question does not by itself stop other approved collection.
2. **Two active new empirical families at most beside frozen EXP-001.** Current EXP-002 remains protected; paused EXP-003 does not silently assign a slot to #122/RFQ. Offline fixtures and bounded feasibility do not certify an active strategy. New empirical studies need registry, budget and slot decisions.
3. **Build once; integrate many uses.** Source-state provenance, fees/units, execution quality, capital reservations and operator UI are shared, not duplicated for every sport or RFQ.
4. **New data needs purpose, rights, timestamp contract, outcome/evaluation use, cost, stop/review date and explicit acquisition authority.** Preserve the existing 450-credit joint Odds ceiling, NFL priority, NFL 295-GET/week and NHL separate bounds; default policy does not become unlimited free access.
5. **No mandatory giant refactor.** Keep the measured SQLite/stdlib deployment unless workload and recovery evidence justify migration. No Kafka/Kubernetes/general optimizer for its own sake.
6. **No idle waiting as delivery.** When a future analysis window, owner decision or provider answer blocks a row, finish its safe code/tests/docs and work on a dependency-ready row. Never run a protected analysis early or invent an answer to remove a blocker.
7. **User interface and operations are acceptance criteria in every relevant package.** Real/empty/stale/error/unsupported/blocked states, mobile/desktop accessibility and no label leaks; no isolated aesthetics lane inventing new themes.
8. **Live may be *proposed* once a specific strategy clears its preregistered evidence bar and the operational gate; it starts only on an explicit owner approval recorded in EXECUTION_PLAN (Gate 9), not when every domain below is built.** Conversely, finishing all code does not force trading. No new live authority is granted here.

## 5. The complete ordered work packages

Priority order is not a serial barrier: the dependency list determines which independent work can proceed. `NOW` below always means only the portions already permitted by EXECUTION_PLAN; new scope is recorded as a proposal until authorized.

### R0 — Maintain trustworthy operation (continuous P0)

**Serves:** #10 #11 #33 #47 #50 #74 and all experiments. **Owners:** current deploy, backup, ledger, freshness, source and Terminal components.

Maintain protected collection, shared quota, actual receipt/sequence truth, schema/head verification, backups/restores, safe retention, laptop copies, manual checkpoints, source isolation and rollback. Preserve old completed first-settlement/capture/backup evidence rather than repeating it. Do not restore/write-probe live stores. Use recorded routine dates; ntfy remains owner-deferred for research, but demonstrable alert/incident delivery becomes a prerequisite for unattended live use.

**Exit/acceptance per release:** attributable SHA, safe preflight, verified restore/rollback path, protected flows unaffected, exact request budget, no unexplained failed Market unit. An old test unit or unrelated application is not a license to change another project. Code/CI/production evidence remain distinct.

### R1 — Finish current pricing, rights and experimental blockers (P0)

**Serves:** #5 #9 #29 #30 #96 #122 #134. **Dependencies:** current main and owner decisions; **owners:** fee/rules/provenance/sports modules, no replacement experiment.

1. Close document-derived fee/rule facts where possible; map remaining disputes precisely. NFL/NHL series, fractional quantities, maker/taker/RFQ scope, cancellation/refund and fallback paths stay separate. Current unsupported scopes never become zero-fee or generic-fee claims.
2. Keep source-derived tie/not-played bounds PROPOSED until legitimate review. Fix narrower venue-change semantics without inventing new probabilities.
3. A.C tool is already built: preserve its one-run timing (once, after the last pilot-week target (kickoffs through 2026-10-19 ET) has passed and before the 2026-10-21 freeze). E1 design/economics/freeze remain separately reviewed; no more attempts to force a rejected noise gate to pass.
4. NHL timing mismatches, actual commence/lead differences, unknown shootout rules and October budget options are in the existing `docs/owner/2026-09-29-nhl-decision-packet.md` (default option (a)); extend it, do not create another. Do not change protected windows or NFL reservation to improve apparent pairing without approval.
5. Signed-in agreement and final message/channel are owner/access actions; the questions are already drafted (`docs/research/KALSHI_QUESTIONS_2026-09-26.md`, revision 2, NOT SENT); do not redraft or send twice, and record answers verbatim when legitimately obtained.

**Acceptance:** scope-specific capability/fee/rule matrix with sources/effective dates and explicit refusals; safe current code fixes tested; no altered EXP-001/EXP-002 holdout; exact blocker owner and next trigger. This package may be code-complete and evidence-blocked. It does not block offline R2/R4 merely because a provider has not answered.

### R2 — Shared source, game-state and execution-economics intelligence (next build)

**Serves:** #9 #50 #74 #82 #93 #122 #145. **Dependencies:** R1 semantic boundaries; **owners:** existing in-play evidence/provenance, freshness, research_evidence/research_economics and a subordinate report if needed.

Add only demonstrated missing metadata: information clock origins/precision, source-family ID or UNKNOWN, sport/market/phase/regime, game-state version as observed, whether a quote's incorporated state is known/unknown, decision validity/revalidation reason, transport/parse/model/risk/venue latency stages, taking/making/RFQ mode and evidence class. Keep wall-clock time separate from game clock and pending corrections. Do not claim a latest-received book reflects a particular play without evidence.

Research direction: compare both lead/lag directions by context. No permanent sharp-source rankings, current-baseline weighting changes, causal claims from simple correlation or inference finer than the data supports. Feature-inspection and later markout outcomes retain their existing exposure controls. Sparse pregame data produces a data-gap report for second-level lead/lag, not an answer.

Extend economics for actual versus simulated fills, fill-conditioned markouts, shared exposure, capital-days, total/deployed return, turnover with a defined denominator, fees/rebates/promotions and fixed cash cost separately, phase/season/event regime. Owner hours remain hours. Own accepted flow and unknown private competitor flow are distinct.

**Tests/acceptance:** late/corrected state invalidates a dependent recommendation; unresolved incorporated state is UNKNOWN; timestamps do not establish false source leadership; fake fair-price and sticky/correlated-source fixtures do not manufacture alpha; no-fill and residual losses remain in denominators; fees/turnover/capital are not double-counted. UI shows evidence status and assumptions, not a score or automatic tradability.

### R3 — Extend the existing in-play foundation; prepare one source-quality pilot

**Serves:** #122 #145 #6 #32. **Dependencies:** R2; **owners:** position_policy and inplay_* already built.

Do not rebuild hold/full-exit/partial-exit replay. Add state-version invalidation and latency/attribution only where missing. Preserve identical entries and capital, residual-inventory settlement, fees and terminal wealth. Released cash is initially idle to isolate exit value; re-entry/additions are a different later experiment. Existing first-detection zero-latency and hindsight bounds remain labeled and cannot pass as executable returns.

Refresh the existing `inplay-source-pilot-1` proposal (`docs/owner/2026-09-29-vf-decision-packet.md` §C) rather than drafting a new one, comparing NFL/NHL/NBA readiness without adding all sports. State-only richer feeds are not mandatory for a simple price-exit policy. Document raw-source rights, auth scopes, whole-message input load, hard cap, selected games chosen ex ante, protected jobs, reconnect/gaps, overtime/end rules, retention, cost and stop date. No recorder activation merely because code merges.

**Acceptance:** offline regression/null/accounting tests pass; one minimum source-quality approval packet; existing Terminal shows fixture/replay versus captured evidence and actual-size exit economics. No label leaks or actual account claims.

### R4 — RFQ/combination capability, visibility and economic feasibility (parallel read-only priority)

**Serves:** #145 #30 #7 #93. **Dependencies:** R1 for authoritative fact status; may run alongside R2/R3.

Document per venue/product: request visibility, own versus others' quotes, account/permission requirements, combo definitions, native quantities, fee-inclusive versus principal-only targets, quote-full-size obligations, timing, expiry/replacement/confirmation, subaccount attribution, collateral and eligible metadata. Preserve DOCUMENTED, OBSERVED_AUTHORIZED and UNKNOWN distinctions.

A *future* passive observer, which needs an authenticated connection and therefore credentials and owner approval (not part of R4's first packet), could at most count visible requests and inspect permitted combo definitions. It cannot infer private competitor quotes, win rates, rejected/accepted prices or realized profitability. Broad stream input can be high even if output is filtered to one sport; budget the input. Do not issue live RFQs or executable quotes for data gathering.

Economic screen: request count is an upper demand signal, not fill rate; proposed capturing-share and margin scenarios remain assumptions. Include unknown collateral/costs, sparse opportunities, competition, seasonal change and venue cash fragmentation. Bounded toy fixtures can demonstrate observability and infeasibility; no new empirical family is activated.

**Acceptance:** a source-cited visibility matrix, one protocol/replay contract, illustrative lifecycle tests without transport, and a proceed/narrow/defer decision with exact permission/cost gaps. No generic market-making engine yet.

### R5 — One-venue order, inventory and capital lifecycle (technical branch; do not wait for every strategy)

**Serves:** #6 #30 #32 #33 #93 #122 #145. **Dependencies:** R1 semantic proof, R2 data contracts and reviewed exact test-only authority (test-only means in-process fakes and fixtures, with no network transport and no credentials; any venue demo/sandbox account, key or authenticated paper order needs a separate owner approval recorded in EXECUTION_PLAN). ADR 0035 is the design being implemented; RFQ-specific extension additionally depends on R4.

Extend execution_ticket/current ADR, not a second risk owner. Durable intents, atomic cash AND inventory reservation, fencing/single execution authority, actual/unknown account state, duplicate/out-of-order event reconciliation, pending/ack/partial/fill/cancel-request/cancel-confirmed/unknown/settled semantics, restart recovery and outstanding native/manual orders. Restrict credentials/withdrawals and isolate model/research processes. No transport initially.

RFQ confirmation and ordinary resting orders have different binding points. Recheck data/state and risk before any future allowed acceptance/confirmation. Reserve plausible simultaneous obligations and prevent stale quote reuse; do not assume the ability to hedge, cancel or accept only part. Shared players/games across many combos create common exposure.

**Tests/acceptance:** two workers cannot spend/sell the same assets; lost responses do not cause blind retries; stale lease holder cannot trade; unknown states retain conservative reservations; partial/manual exits cannot open opposite exposure; counterparty/exchange outage and orphan-leg losses are modeled. Fixture canary is not a venue order or live fill validation.

### R6 — Approved in-play evidence and a narrow empirical policy study

**Serves:** #122 #145. **Dependencies:** R3 plus source/recorder approval, rights and a research-slot decision; actual live use later needs R5/R10.

Only after the owner approves `inplay-source-pilot-1` (vf decision packet §C) and a slot/budget decision, run that selected-game pilot, not high-frequency all-sports ingestion. Preserve game/book corrections and absence. Data inspected for engineering are development evidence. Freeze a modest exit comparison and primary risk/economic endpoint before its evaluation. Game/slate clustering, delayed controls, fill bounds, latency, capacity and tail loss determine usefulness; one exciting comeback does not.

Later, only after incremental evidence: a game-state/fair-value challenger with versioned pregame priors; next re-entry or additions with cumulative risk/turnover limits. Do not choose the later historical maximum as an exit or reset losses after a rebound. State-aware market-making is not implied.

**Acceptance:** honest sample/attrition/cost report, hold-versus-policy total wealth, size ladder, source quality, uncertainty and continue/stop decision. No edge is a successful research result. Do not increase feeds or capital because initial gross P&L looks good.

### R7 — Scoped RFQ pricing and maker research (not prerequisite for taker live readiness)

**Serves:** #145 #6 #30 #82 #93. **Dependencies:** viable R4, rights/observational approval, slot/budget and appropriate R5 semantics before any real quoting.

Start with a small supported set and transparent models. Separate deterministic payoff relations from estimated probabilities. For two events, P(A and B)=P(A)P(B|A); cross-game independence is a disclosed assumption, same-game independence is not the default. Use logical constraints, probability bounds and uncertainty; void/dead-heat/tie/refund mechanics alter the payoff, not merely probability. No joint-price claim with missing states.

Stage joint pricing: toy fixtures and conditional bounds → small supported combo research → out-of-sample calibration → simulated quote selection under explicit observability limits → only separately authorized own-flow evaluation. Do not reverse-engineer an entire private maker book from a few public requests.

Evaluate E[profit | our fills], not an average over every quote we would like to fill. Retain nonquotes, expiry, nonacceptance where observable, adverse selection, inventory hedging and all overlapping exposure. A copied best price does not acquire the original maker's inventory, rebates, timing or complete portfolio.

**Acceptance:** claim-limited joint model and risk tests, observed/unknown request-to-fill denominators, cost/collateral and capacity scenarios, seasonal sensitivity. Maker/RFQ live eligibility needs its own reviewed risk plan, not inheritance from a successful taker pilot.

### R8 — Evidence-driven learning and portfolio capital use

**Serves:** #82 #93 #6 #50 #145. **Dependencies:** actual informative labeled evidence from whichever scoped families mature; registry lineage can be developed earlier.

Prioritize calibration, simple baselines, hypothesis/variant registry, feature/dataset/model hashes, standardized champion/challenger review, source-value ablation, data/model/execution/fees/opportunity/capacity drift. Source leadership and fair value can change by regime; do not retrain as the reflex answer to a broken feed or fee change.

Later consider ensembles, bounded hyperparameter search, incremental/online challengers and contextual query/cadence allocation in simulation. General RL with real capital remains deferred. Model creation/promotion and live-risk authorization are separate. Separate peak-event economics, recurring economics, rebates and subsidy from durable alpha.

**Acceptance:** reproducible why/when comparison and no-promotion result when evidence is weak; capital allocation respects correlated tails, idle cash and marginal useful capacity. No decorative edge score or hidden changing champion.

### R9 — Remaining domains and data expansion (slot-budgeted branch, not deleted)

**Serves:** #86 #88 #5 #7 #27 #30. **Dependencies:** a specific economic hypothesis, rights/data budget, operational headroom and empirical slot; not completion of RFQ.

Retained queue with default ordering, revisable only with documented economics/access evidence:
1. Weather revision/information-accumulation and bounded multi-city collection from existing twelve-city design; verify each station/rule, no EXP-001 clones.
2. Slower SEC/earnings/guidance/IR first-seen equity/ETF studies; liquid bounded universe and corporate-action/calendar correctness. LLM historical training contamination is explicit.
3. Exact-fixing BTC/ETH and narrowly defined basis/cross-market studies; spot/reference/derivative identity and settlement window preserved.
4. Options volatility/replication/bounds; risk-neutral prices are not physical probabilities, no midpoint-fill backtests, exercise/assignment/multi-leg risk and licensed data required.
5. Macro/EIA and futures: initial versus revised releases, expectation-source rights, slower reaction/cross-asset/curve research; exact contracts/rolls and margin/fees, no continuous-synthetic executable claims.
6. Additional sports including NBA/MLB/NCAAF/NCAAB/UFC/soccer/tennis/NASCAR only with a specific mechanism, domain competence and cost case. NHL raw collection does not grant a new model slot; no props firehose.
7. Official political/government and business-event sources; culture/entertainment and long-tail markets market-data-first. News/transcripts/social/polling/alternative data only by bounded source-value test; no unnecessary personal data, broad licensing assumption or sentiment platform.

Venue queue retains Kalshi, Polymarket US, Novig and other genuinely useful routes. Broker brands sharing liquidity are not independent exchanges. Further brokers/data feeds are selected for the specific strategy; paid SIP/OPRA/CME or odds needs explicit marginal value and owner approval. Do not hard-code remembered tax/day-trading rules.

The general instrument selector is built only once two actual expressions justify it, reusing best_price and risk: stock/ETF/option/spread/future/event contract/cash. It is not a gate that must be completed before the first simple trade.

Free keys (FRED/ALFRED, BEA, EIA, Census, Alpaca/Tradier data) are installed by the owner only; broker keys only after the security ADR. SIP, OPRA, CME, CF Benchmarks and paid Odds tiers need the #7 case and owner approval. Funding, margin, shorting, derivatives permissions and order-write credentials are Gates 8–10. Admission uses `research_readiness.py` plus the owner-directed Domain Readiness matrix (states only, no score; last scored 2026-09-24, archive), re-scored at the next gate transition.

**Acceptance per admitted domain:** clean source/outcome lineage, economic screen and chosen protocol, capability-specific execution path, clear stop rule. Unsupported or uneconomic domains are recorded and removed from active effort rather than endlessly engineered.

### R10 — First authorized live validation and controlled scaling (readiness-triggered branch)

**Serves:** #11 #6 #32 #93 #96; **dependencies:** one legitimately supported strategy, R0/R1/R5, specific account/security/venue/risk/pilot approvals. **Not dependent on:** finishing RFQ, R8 automation, R9 all domains or investor features.

Separate an explicitly authorized operational canary from a strategy pilot. The first proves actual account/order/fee/reconciliation behavior; it does not prove alpha or justify bypassing the research gate. Freeze capital/order/loss/position/timing scope and stop conditions with owner approval. Start tiny, compare live fills/costs to shadow, reconcile before additional exposure, increase only when marginal capital remains productive. No fixed dollar amount or start date is selected here. No domain is pre-selected as first live: EXP-001 weather, sports, public markets or another strategy may go first. The first to clear its own preregistered bar and the common operational gate goes first, and research criteria are never weakened to make one win.

**Acceptance:** verified permissions/units/fees/settlements, actual balances/positions, reliable alert/kill/recovery paths, real execution evidence, acceptable drawdown/correlation/capacity and owner approval for any scaling. Gates remain the repository's 8 paper/shadow, 9 tiny real money, 10 scaling.

### R11 — Outside capital and optional commercial product (explicitly later)

**Serves:** #83 and eventual product value. **Dependencies:** supported capacity, lawful entity/custody/account/tax/fee structure, investor eligibility and explicit owner decisions. Not a prerequisite for personal tiny-live or bootstrap growth.

Preserve simulated append-only unit/NAV accounting, fair contribution/redemption timing, high-water/equalization research, expenses/fees/transparency, manager capital versus compensation, reconciled statements, investor-level access controls and possible fund-admin integration. Do not take friends' money into a personal account or select a fee merely from common practice. A small simulation can later validate arithmetic without accepting money, but is not current critical-path implementation.

Commercial research/analytics/data/software possibilities stay secondary and licensing-aware. Software revenue must not be presented as proof of trading alpha. Professional advice or engineering may be proposed where justified, but no contract, hiring, fee or payment is authorized by this roadmap.

## 6. Dependencies and next batch

```
R0 ongoing protection
  + R1 current correctness/rights
       ├─ R2 shared state/latency/economics → R3 existing in-play extensions
       │                                     └─ approvals + slot → R6 empirical study
       ├─ R4 RFQ feasibility → viable scope + slot → R7 joint-pricing/maker research
       └─ R5 one-venue mock lifecycle (then separately authorized account readiness)

one supported strategy + R0/R1/R5 + explicit owner approval → R10 tiny live/scale
informative evidence → R8 learning
available research slot + value/rights/budget → R9 next domain
proven capacity + professional structure + owner decision → R11 outside capital
```

No circular dependency requires a successful live strategy before testing its proposed execution, and no technical readiness is mistaken for strategy proof.

### Immediate batch: Sports Intelligence & RFQ Feasibility v1

**A — Shared intelligence/attribution contracts and fixtures.** Inspect current inplay_* and research_economics first. Implement only missing state/quote association, decision invalidation, latency and maker/taker/RFQ attribution within current permission or a recorded scoped directive. No empirical source-weight changes or early A.C run.

**B — RFQ feasibility packet and synthetic lifecycle.** Primary docs, visibility/permissions/size/fee/collateral matrix; no network participant. Account for broad channel input, private quote data, acceptance/confirmation binding and actual fill evidence. Return a narrow proceed/block decision, not a quote bot.

**C — Integration and existing-blocker closure.** Fee/rule/schedule conflict documentation and safe tests, minimal Terminal fields for A/B, canonical readiness/decision packet. Changes to source schedules/windows/budget and messages remain separate approvals.

Maximum two writers with disjoint paths, plus an independent reviewer. One writer owns shared types. Keep the UI active as a bounded contract-driven integration, not a competing design lane. Finish each coherent PR with regression tests, current-head CI/review and exact implementation state. When a real permission/date blocker appears, work the next independent package; do not create a background promise or wait loop.

## 7. Checkpoints, delivery definition and remaining decisions

**Oct 3 routine window:** follow current approved O1/F09 and retention policy when actually due; do not rerun completed actions just to claim progress. **After the pilot:** the existing single timing calibration, run once, after the last pilot-week target (kickoffs through 2026-10-19 ET) has passed and before the 2026-10-21 freeze, with logged FEATURE_INSPECTION under its protocol. **Oct 22:** owner research/freeze and platform-readiness checkpoint, not an automatic pass, live launch or deadline for finishing every future domain. Preserve the existing EXP-003 review deadline/paused status unless an explicit later decision supersedes it.

**Dated checkpoints and owner-only gates (carried from the archive):**
- Fee re-checks: Kalshi by 2026-10-23T13:39:48Z, Polymarket US by 2026-10-24T01:39Z.
- `close_tick_alignment` DST check after 2026-11-01.
- EXP-003 current scope is rejected on 2026-11-15 if Q1 or Q4 is unresolved.
- The Kalshi questions (`docs/research/KALSHI_QUESTIONS_2026-09-26.md`, revision 2) are drafted and NOT SENT; sending needs the owner to confirm the exact final text and channel.

By the October 22 checkpoint, target a fully reconciled current roadmap, current-family decision materials, trustworthy pricing/rights states, complete offline in-play extensions, a scoped RFQ feasibility result, useful operator states and an explicit next authorized evidence step. Unknowns are valid deliverables when their exact resolution/cost is identified.

Current owner decisions are carried forward, not reinvented: signed-in data rights, final Kalshi message/channel, NHL October policy/window options, #122 capture/slot/budget, and later account/live permissions. Existing approved EXP-002 $1,000/year continuation bar and six hours remain its own scope; no dollar price for hours or automatic extension. Default free quota and protected windows remain until changed.

**Completion ledger for every package:** status; issue(s); owner/paths; dependency; authority; acceptance/test; current evidence; review/PR/head/CI; deployed versus not applicable; blocker and resolver; next trigger; stop/defer reason. No percentage based on API counts. No item vanishes because it is not in the immediate batch.

## 8. Validation of this documentation update

Repository and current source-document reads were performed. No server/account/stream was accessed and no runtime/model/protocol/credential changed. A local checkout attempt failed because the execution environment could not resolve github.com; local pytest was therefore **not run**. Do not call this change tested locally. Require the exact-head CI and independent coordinator review before merging, particularly because this consolidates planning/ownership history.

The archive must match original blob `b0689cc48dfc8dd127636b67f7b0a3dc1d0e323d`; the final work-claims blob must return to its original value; only the index and new strategy files should differ. Current HANDOFF and EXECUTION_PLAN are deliberately unchanged: production evidence and financial/scheduling authority are not edited by this planning consolidation.
