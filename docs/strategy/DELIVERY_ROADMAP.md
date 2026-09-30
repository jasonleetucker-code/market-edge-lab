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
| A.C timing calibration tool (#142/#143) | Built/deployed, not yet run. It runs once, logged, on production after the pilot's T-6h weeks (kickoffs 2026-09-27 through 2026-10-19 ET; about 2026-10-19) and before any pilot markout or E1 result is viewed (A.G step 5). Its output is a PROPOSED input to the owner's 2026-10-22 freeze review, not a freeze. Not an immediate redo. Unavailable now is a date/evidence prerequisite, not missing code |
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

1. **Operate and preserve evidence continuously within existing authority.** A confirmed safety or rights failure stops the affected use and collection at once (EXECUTION_PLAN: each source's terms respected) and is escalated to the owner; an unresolved rights question does not by itself stop already-approved collection, which continues until the owner decides otherwise (vf decision packet §B), but it blocks new uses such as `inplay-source-pilot-1`.
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
3. A.C tool is already built: preserve its one-run timing (once, logged, after the pilot's T-6h weeks (kickoffs through 2026-10-19 ET; about 2026-10-19) and before any pilot markout or E1 result is viewed; its output is a PROPOSED input to the owner's 2026-10-22 freeze review; no freeze is promised). E1 design/economics/freeze remain separately reviewed; no more attempts to force a rejected noise gate to pass.
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

**Serves:** #6 #30 #32 #33 #93 #122 #145. **Dependencies:** R1 semantic proof, R2 data contracts and a directive entry scoping R5 as offline-only work (offline-only means in-process fakes and fixtures, no network transport, no credentials; it changes runtime code, so it is not a 'test-only PR' under the standing merge rule; any venue demo/sandbox account, key or authenticated paper order needs separate owner approval recorded in EXECUTION_PLAN). ADR 0035 is the design being implemented; RFQ-specific extension additionally depends on R4.

Extend execution_ticket/current ADR, not a second risk owner. Durable intents, atomic cash AND inventory reservation, fencing/single execution authority, actual/unknown account state, duplicate/out-of-order event reconciliation, pending/ack/partial/fill/cancel-request/cancel-confirmed/unknown/settled semantics, restart recovery and outstanding native/manual orders. Restrict credentials/withdrawals and isolate model/research processes. No transport initially.

RFQ confirmation and ordinary resting orders have different binding points. Recheck data/state and risk before any future allowed acceptance/confirmation. Reserve plausible simultaneous obligations and prevent stale quote reuse; do not assume the ability to hedge, cancel or accept only part. Shared players/games across many combos create common exposure.

**Tests/acceptance:** two workers cannot spend/sell the same assets; lost responses do not cause blind retries; stale lease holder cannot trade; unknown states retain conservative reservations; partial/manual exits cannot open opposite exposure; counterparty/exchange outage and orphan-leg losses are modeled. Fixture canary is not a venue order or live fill validation.

### R6 — Approved in-play evidence and a narrow empirical policy study

**Serves:** #122 #145. **Dependencies:** R3 plus source/recorder approval, rights and a research-slot decision; actual live use later needs R5/R10.

Only after the owner approves `inplay-source-pilot-1` (vf decision packet §C) with the approval recorded in EXECUTION_PLAN, the rights question (§B) is resolved and a reviewed recorder is merged, run that selected-game source-quality pilot, not high-frequency all-sports ingestion; evaluation beyond source quality also needs a slot/budget decision and a registry id. Preserve game/book corrections and absence. Data inspected for engineering are development evidence. Freeze a modest exit comparison and primary risk/economic endpoint before its evaluation. Game/slate clustering, delayed controls, fill bounds, latency, capacity and tail loss determine usefulness; one exciting comeback does not.

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

**Oct 3 routine window:** follow current approved O1/F09 and retention policy when actually due; do not rerun completed actions just to claim progress. **After the pilot:** the existing single timing calibration, run once, logged, after the pilot's T-6h weeks (kickoffs through 2026-10-19 ET; about 2026-10-19) and before any pilot markout or E1 result is viewed; its output is a PROPOSED input to the owner's 2026-10-22 freeze review; no freeze is promised, with logged FEATURE_INSPECTION under its protocol. **Oct 22:** owner research/freeze and platform-readiness checkpoint, not an automatic pass, live launch or deadline for finishing every future domain. Preserve the existing EXP-003 review deadline/paused status unless an explicit later decision supersedes it.

**Dated checkpoints and owner-only gates (carried from the archive):**
- Fee re-checks: Kalshi by 2026-10-23T13:39:48Z (add SETTLEMENT_AND_TRANSFER_FEES), Polymarket US by 2026-10-24T01:39:45Z.
- `close_tick_alignment` DST check after 2026-11-01.
- EXP-003's current scope is rejected on 2026-11-15 if Q1 or Q4 is unresolved or unfavourable (EXECUTION_PLAN 2026-09-26 entry; relies on the PROPOSED emergency-power scoping).
- The Kalshi questions (`docs/research/KALSHI_QUESTIONS_2026-09-26.md`, revision 2) are drafted and NOT SENT; sending needs the owner to confirm the exact final text and channel.

By the October 22 checkpoint, target a fully reconciled current roadmap, current-family decision materials, trustworthy pricing/rights states, complete offline in-play extensions, a scoped RFQ feasibility result, useful operator states and an explicit next authorized evidence step. Unknowns are valid deliverables when their exact resolution/cost is identified.

Current owner decisions are carried forward, not reinvented: signed-in data rights, final Kalshi message/channel, NHL October policy/window options, #122 capture/slot/budget, and later account/live permissions. Existing approved EXP-002 $1,000/year continuation bar and six hours remain its own scope; no dollar price for hours or automatic extension. Default free quota and protected windows remain until changed.

**Completion ledger for every package:** status; issue(s); owner/paths; dependency; authority; acceptance/test; current evidence; review/PR/head/CI; deployed versus not applicable; blocker and resolver; next trigger; stop/defer reason. No percentage based on API counts. No item vanishes because it is not in the immediate batch.

## 8. Validation of this documentation update

Repository and current source-document reads were performed. No server/account/stream was accessed and no runtime/model/protocol/credential changed. A local checkout attempt failed because the execution environment could not resolve github.com; local pytest was therefore **not run**. Do not call this change tested locally. Require the exact-head CI and independent coordinator review before merging, particularly because this consolidates planning/ownership history.

The archive must match original blob `b0689cc48dfc8dd127636b67f7b0a3dc1d0e323d`; the final work-claims blob must return to its original value; only the index, the new strategy files and the review edits listed next should differ. In review, HANDOFF (roadmap pointer only), EXECUTION_PLAN and the 2026-09-30 directive record (the directive's §18 merge/deploy conditions and the owner's verbatim merge delegation only) were edited; no production evidence or financial/scheduling authority changed.

Coordinator review: `python -m pytest tests/invariants -q` passed (127) on `cc994c3` and again on the head carrying the second-round review fixes.

## 9. Completion ledger (R0–R11), 2026-09-30

Filled from facts by PR C (roadmap R1 + Terminal integration). The repository at the time was main `519580d` (#148),
after `04bf78c` (#149). "CI" means exact-head GitHub Actions pytest on 3.11 and 3.12. "Deployed" means production per the latest
HANDOFF record; it is not a fresh server probe. Implementation state and evidence state are separate columns, and
neither implies the other.

| Pkg | Requirement · issues | Implementation | Evidence | Owner · paths | Depends on | Authority | Acceptance tests | PR · exact CI head | Deployed | Blocker · resolver | Next trigger | Stop / defer reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R0 | Operate and protect evidence · #10 #11 #33 #47 #50 #74 | DONE/MAINTAIN (continuous) | Production `23b7b3b` verified 2026-09-29 21:52 ET: preflight PASS, backups verified, 0 failed units, 13 timers (HANDOFF) | deploy runbook, backup, freshness, collectors | — | existing grants (EXECUTION_PLAN) | runbook preflight / fail-closed; `tests/invariants` | #140–#143 (merged, CI green per HANDOFF); #144 docs-only | #140–#143 deployed (`23b7b3b`); #144 docs-only | weekly O1 pull and F09 by about 2026-10-03 · OWNER | the owner's routine | — |
| R1 | Fees, rules, rights, current EXP-002/NHL blockers · #5 #9 #29 #30 #96 #122 #134 | PARTIAL: KXNHLGAME and KXMVE* now FEE_UNSUPPORTED (explicit not-proven-standard map; every other series unchanged); blocker register `current_blockers.py` + generated `docs/research/CURRENT_BLOCKERS.md` | Fee facts from the captured PDF (2026-09-23) and help pages re-read 2026-09-30; PDF re-fetch HTTP 429 | `fee_schedules.py`, `current_blockers.py` | owner decisions, venue answers | directive 2026-09-30 (offline) | `tests/test_fee_not_proven_standard.py`, `tests/test_current_blockers.py`, `check-frozen` clean | PR C (this PR) · CI pending on its final head | not deployed | fees · VENUE; rights, message rev 2, NHL window · OWNER; A.C run · date | A.C window after about 2026-10-19; freeze review 2026-10-22; any Kalshi reply | code-complete, evidence-blocked by design |
| R2 | Source / state / latency contracts, fill-conditioned economics · #9 #50 #74 #82 #93 #122 #145 | DONE/MAINTAIN | Offline contracts, synthetic nulls and adverse-selection tests; no real fill exists | `inplay_evidence.py` (source-state-v1), `position_policy.py`, `inplay_replay.py`, `research_economics.py`, `execution_ticket.py`; ADR 0041 | R1 semantics | directive 2026-09-30 | `tests/test_source_state.py`, `tests/test_research_economics_fills.py`, `tests/test_execution_ticket_obligations.py` | #149 · head `5cd1996`, CI 3.11/3.12 success · merged `04bf78c` | not deployed (offline library; its displays ship with PR C) | none | consumers in R3/R5 (#148 reserves through `execution_ticket.reserve_simultaneous_obligations`) | — |
| R3 | Extend #122 foundation; one source-quality pilot proposal · #122 #145 #6 #32 | PARTIAL: state-version invalidation and pre-placed-vs-bot fills done in #149; pilot proposal `inplay-source-pilot-1` PROPOSED, NOT APPROVED | fixtures and synthetic cohorts only | `inplay_*`, `docs/research/INPLAY_SOURCE_FEASIBILITY.md` | R2 | offline only; any capture needs owner approval | `tests/test_inplay_*.py` | #149 (replay part) | not deployed | rights (DATA_RIGHTS) and a research slot · OWNER | the owner's rights decision; a slot decision | capture waits for rights + slot (#96) |
| R4 | RFQ / combination feasibility · #145 #30 #7 #93 | DONE/MAINTAIN (decision NARROW; D1–D6 are the owner's) | public primary docs; fixture lifecycle; the Terminal shows the capability states (PR C) | `rfq_research.py`, `docs/research/RFQ_*`, ADR 0042 (#148) | R1 facts | directive 2026-09-30 (read-only; no RFQ, quote or account) | `tests/test_rfq*` | #148 · exact CI head `28e6dfb`, CI 3.11/3.12 success · merged `519580d` | not applicable (research) | owner decisions D1–D6 · OWNER | an owner decision on D1–D3 | no participation until separately authorized |
| R5 | One-venue order / inventory / capital lifecycle · #6 #30 #32 #33 #93 #122 #145 | NOT STARTED (design only) | ADR 0035; `docs/research/EXECUTION_MODES_GAP.md`; `execution_ticket.reserve_simultaneous_obligations` (#149) | `execution_ticket.py`, `risk.py` | R1, R2; R4 for RFQ | needs an EXECUTION_PLAN entry scoping R5 offline | ADR 0035's fake-transport test list | — | not applicable | directive entry · OWNER | owner scopes R5 | no transport, credential or paper order without separate approval |
| R6 | Approved in-play evidence and narrow policy study · #122 #145 | BLOCKED | none (no capture) | `inplay_*` | R3 + rights + slot | owner approval of pilot and slot | honest sample / attrition / cost report | — | not applicable | R3 approvals · OWNER | R3 unblocked | no real in-play data before approval |
| R7 | Scoped RFQ pricing and maker research · #145 #6 #30 #82 #93 | DEFERRED | none | future, on `rfq_research` / `payoff_constraints` | viable R4, rights, slot, R5 semantics | none yet | claim-limited joint-model tests | — | not applicable | R4 verdict · coordinator; slot · OWNER | #148 verdict | no general SGP engine or quoting now |
| R8 | Evidence-driven learning, portfolio capital use · #82 #93 #6 #50 #145 | DEFERRED (lineage exists) | `research_evidence` registry lineage | `research_evidence.py`, `sizing*` | labelled evidence from matured families | none beyond research | no-promotion-on-weak-evidence tests | — | not applicable | evidence volume · time | first matured family | no hidden champion or decorative score |
| R9 | Remaining domains: weather expansion, public markets, crypto, macro/EIA, options/futures · #86 #88 #5 #7 #27 #30 | DEFERRED, slot-budgeted, kept visible | `docs/research/MULTI_CITY_WEATHER_V1.md`, `ACQUISITION_PORTFOLIO.md` | per domain | hypothesis, rights, budget, slot | per-domain approval | per-domain economic screen | — | not applicable | slot and budget · OWNER | a domain value case | two-family limit (#96); uneconomic domains recorded and dropped |
| R10 | First authorized live validation and scaling · #11 #6 #32 #93 #96 | NOT READY | no strategy has cleared its preregistered bar; EXP-001 evaluation looks at 180/365 days | execution, risk, venue | a qualifying strategy + R0/R1/R5 + approvals | Gate 9 owner approval (none granted) | Gates 8–10 | — | not applicable | a qualifying strategy · evidence | a strategy clears its bar | live never starts from code completion |
| R11 | Outside capital, optional commercial product · #83 | DEFERRED (explicitly later) | none | future | supported capacity, legal / entity decisions | owner decisions | — | — | not applicable | capacity evidence · OWNER | useful personal strategy evidence | not a prerequisite for tiny live or bootstrap |

**Owner Ideas after #145:** none. No `[Owner Idea]` issue newer than #145 exists as of 2026-09-30 (`gh issue list`).
PR C applies the OWNER_IDEAS row updates this ledger implies (#145, #122 and #134; the fee-model, state-validity,
in-play-evidence, research-evidence and research-economics primitives; and two new primitive rows).

**Next dependency-ready package (one):** R3. Refresh the one-route source-quality pilot proposal and its replay
acceptance onto the R2 contracts (state-version validity, latency stages, evidence status). It is offline and
documentation/fixture-level, and it prepares the exact owner decision (rights + slot) without taking one. R5 needs
an EXECUTION_PLAN entry first.

## 10. Architecture reconciliation, 2026-09-30 (#152)

This section changes no package, order or dependency. R0–R11 and §6 stand as written; §9 remains the completion
ledger. Detail: [`docs/engineering/ARCHITECTURE_RECONCILIATION_2026-09-30.md`](../engineering/ARCHITECTURE_RECONCILIATION_2026-09-30.md).

- **External architecture review and 25 X links:** the existing architecture is kept. The only mechanism adopted is
  the controlled defect loop (reproduce → repair the canonical owner → keep the regression → review), in
  `docs/AGENT_OPERATING_SYSTEM.md` §1. Everything else is ALREADY_COVERED, DEFERRED (behavioural evals, ADR 0006)
  or NOT_APPLICABLE. Nothing is added to the runtime.
- **R0 / R2 / R3 (in-play offline path):**
  - The path journal file → evidence → freshness/state validity → policy/replay → `inplay-view/1` is verified
    through its consumer.
  - Two provenance gaps in `inplay_evidence.py` are fixed:
    - an empty RECORDED journal was reported as SYNTHETIC and passed the consumer's RECORDED refusal;
    - a book carried an earlier message's venue stamp across a resync.
  - `inplay_view` now sits inside the offline and protected-label import boundary.
  - Implementation state: TESTED_LOCALLY on the PR branch. CI, merge and deploy are recorded in the PR.
- **R3, next dependency-ready package, sharpened.** R3a comes first:
  - the journal content digest and the last applied message hash carried through `BookState`/`build_view`;
  - transitions sliced to the as-of;
  - both shown in the existing in-play page under the UI contract.

  It is offline and needs a scope entry, per the coordinator's HANDOFF. Then the documentation-only
  `inplay-source-pilot-1` refresh. Capture, recorder, rights and research slot stay BLOCKED on the owner.
