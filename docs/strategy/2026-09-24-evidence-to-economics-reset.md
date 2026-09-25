# Evidence-to-economics strategy reset

Owner directive: #96. Date: 2026-09-24 America/New_York.

**Status: durable strategic reconciliation; implementation and canonical-index reconciliation are separate.** This document records the owner's supplied independent review, an audit of current repository evidence, and the recommended implementation sequence. It does not report new strategy results or activate financial capabilities.

**Audit baseline:** `f5bfa6e11337861c5999c6ddf03a94c67d54716f` on `main`, the merge of #95. Its parent is `3990ee708ddf8a0b9ba514f0d107a9167f907796` (#94). Re-read current main before implementation. The companion handoff is [CLAUDE_ECONOMIC_EVIDENCE_V1.md](CLAUDE_ECONOMIC_EVIDENCE_V1.md).

## 1. Decision and authority

Market Edge remains a long-term cross-market research and trading project. Its immediate job is no longer to implement every potentially useful market, collector, model or dashboard. Its immediate job is to test a small number of explicit mechanisms, establish after-cost executable economics, measure capacity and reject weak ideas.

The owner's $50,000–$100,000 annual after-cost trading-profit objective remains aspirational, not a forecast. Starting personal capital is limited and not specified; examples elsewhere are not an approved bankroll. Software revenue, owner deposits, investor capital and trading profits are separate quantities.

The governing hierarchy is valid evidence, valid hypothesis, after-cost edge, executability, capacity, operational safety, repeatability, diversification and capital scalability. Complexity is not independent progress. Safety is a prerequisite throughout, not something postponed until the sixth item.

Preserve EXP-001 completely: frozen artifacts, forecasts, model, decision times, fee assumptions, fills, statistical looks, historical results and ledger. Its 180th/365th-valid-day looks remain binding. A parallel payoff study may reuse source snapshots but cannot add interim EXP-001 alpha verdicts or rewrite its decisions.

Alongside protected EXP-001, maintain at most **two new major active hypothesis families**. A family consumes a slot while outcome analysis, tuning or strategy development is active. Splitting a family into many hidden variants does not bypass the trial budget. Passive bounded collection is not itself an active hypothesis, but it needs a purpose, budget and review/stop date. Exceptions require a documented owner decision.

This intake authorizes strategy/document reconciliation and preparation of bounded work. Follow `docs/EXECUTION_PLAN.md` for runtime implementation, new schedules, credential access and deployment. Nothing here authorizes paid services, account creation, authenticated paper/live orders, deposits, withdrawals, margin, borrowing, outside capital, a gate advance or deletion of backups. Test-only code is not live authorization. The existing gates are 8 paper/shadow, 9 tiny real money, 10 scaling; do not rename all three as Gate 8.

## 2. Audit method and limits

The audit used GitHub repository metadata, current file contents, open issues, the branch listing, current main commits, the open-PR collection, selected implementation code and current primary-source documentation. The open-PR collection was empty at the audit; this changes once the documentation PR is opened.

The active claim file still lists A/B/C/D/E/F through 2026-10-01. A merged PR is not proof that the corresponding agent has no unpushed work. Server-local worktrees, dirty files, live processes, production databases, current venue accounts and physical/mobile UI were not directly inspected. No end-to-end test or VPS deploy was performed during this audit.

`HANDOFF.md` still describes a September 24 16:45 ET snapshot centered on #76. Newer roadmap records and commits describe subsequent work. Treat both as dated evidence, not as a fresh server probe. In particular, the audit cannot certify the currently deployed SHA, current number of timers, mounted schema, current account balances, fresh settlement counts or current off-host restore status.

### Evidence anchors

All repository paths below refer to the audited commit unless a later source is explicitly identified.

| ID | Evidence | Supports |
|---|---|---|
| R1 | `AI_INSTRUCTIONS.md`; `docs/AGENT_OPERATING_SYSTEM.md`; `docs/WORK_CLAIMS.md` | Canonical owners, stdlib-first runtime, gate authority, one writer per claimed path |
| R2 | `HANDOFF.md`; `docs/EXECUTION_PLAN.md`; `docs/OWNER_IDEAS.md` | Dated production/authority/roadmap claims and their inconsistencies |
| R3 | `experiments/README.md`; `docs/RESEARCH_PRINCIPLES.md`; `experiments/EXP-001-kxhighny-nws-vs-market/` | Existing registry, freeze mechanism, claims ladder and protected experiment |
| R4 | `docs/DATA_PROVENANCE.md`; `src/edge_lab/storage.py` | SQLite evidence schema 7; append-only data; timestamps; normalized JSON versus exact document bytes |
| R5 | `src/edge_lab/odds_consensus.py`; `src/edge_lab/odds_api.py`; #79 | Existing paired proportional de-vig and exact-line median research benchmark |
| R6 | `src/edge_lab/opportunity.py`; `src/edge_lab/best_price.py`; `src/edge_lab/fee_schedules.py` | Price/depth/rules/fees contracts and current binary-unit scope |
| R7 | `src/edge_lab/execution_ticket.py` | Disabled execution; order-state/transition metadata; unknown outcome and duplicate checks |
| R8 | `src/edge_lab/shadow_ledger.py`; `src/edge_lab/risk.py`; `src/edge_lab/starter_policy.py` | Simulated journal, cash/risk replay and starter-capital boundary |
| R9 | `src/edge_lab/backup.py`; #95; `deploy/vps/systemd/` | WAL-aware online backup/restore checks; recent reader-permission defect and fix |
| R10 | #80/#85/#91/#94; `src/edge_lab/dashboard/`; `docs/design/UI_CONTRACT.md` | Existing Terminal odds/consensus/freshness/related-market integrations |
| R11 | #89/#90; `docs/research/ACQUISITION_PORTFOLIO.md`; `SOURCE_READINESS.md`; `MULTI_CITY_WEATHER_V1.md` | Acquisition and multi-city design work, not proof of broad production collection |
| R12 | Issues #5/#9/#11/#30/#50/#74/#82/#83/#86/#88/#93 | Prior intent and reuse/defer decisions |

Code inspection supports the boundaries described below; it is not a complete security audit. Missing means no implementation was established in the inspected baseline, not proof that no unpushed agent has written one.

## 3. What exists today and what is not established

**Today:** a substantial private research/data/shadow platform, centered on a protected NYC-weather experiment and expanding sports evidence. There is no evidence here of a validated profitable live strategy.

Merged work includes #79 consensus/readiness, #80 odds history, #81 freshness, #84 Polymarket NFL research, #85 consensus UI, #89 acquisition planning, #90 twelve-city weather design, #91 freshness UI, #92 roadmap reconciliation, #94 related-market UI and #95 SQLite reader/WAL permissions. Do not recreate these.

Newer roadmap text records two valid weather target days, three Odds captures and initial later-price observations, and describes a Freshness deployment at `c6e0dd9`. Those are historical reports, not counts freshly measured by this audit. #94/#95 being merged does not prove their complete permanent production activation. #95's commit describes a real production failure and transient-unit verification; verify the final running units independently.

### Gap analysis

| Topic | Classification | Current evidence and required change |
|---|---|---|
| Experiment registry and freeze | ALREADY EXISTS AND SATISFIES core freeze; EXISTS BUT NEEDS MODIFICATION | Reuse `experiments.py`/TOML lifecycle. Add sidecar budgets, family slots, evidence roles and attrition; do not alter EXP-001 frozen validation |
| Data provenance | ALREADY EXISTS; PARTIALLY IMPLEMENTED for new requirements | Receipt/publication times, hashes, failures and documents exist. Add probability semantics, clock quality, evidence-use and inherited rights |
| Exact raw evidence | EXISTS BUT NEEDS MODIFICATION selectively | JSON snapshots retain canonical JSON and exact-byte hash, not exact original bytes. Documents retain bytes. New byte-sensitive feeds need bounded raw preservation; old bytes cannot be recovered from a hash |
| Freshness | ALREADY EXISTS; recent fixes MUST REMAIN | #81 supervisor and #95 WAL fix. Keep no-work/UNKNOWN fail-closed. Separate availability, age, novelty and historical as-of eligibility |
| Sports odds | ALREADY EXISTS AND SATISFIES benchmark foundation | Exact-line two-way proportional de-vig, median, dispersion, source times, hashes, read-only bounded APIs exist. Consensus is not calibrated truth |
| Sports experiment | MISSING complete protocol and paired evidence | Formal narrow experiment, venue mapping, tie/void treatment, outcome joins, latency limits and after-cost evaluation are not established |
| Event-market collection | PARTIALLY IMPLEMENTED | Weather books and PM sports adapter exist. Kalshi NFL paired collection is queued, not proven complete; full catalog coverage cannot be inferred |
| Contract rules | PARTIALLY IMPLEMENTED | Hashes/settlement identity and related-vs-equivalent refusals exist. Explicit complete payoff-state proof including cancellation/fallback is still needed |
| Fee versioning | ALREADY EXISTS; NEEDS CURRENT EXTERNAL VERIFICATION | Reuse dated component records and conservative claim basis. New scopes need effective-date/rounding proof; do not replace frozen EXP fees |
| Native units | PARTIALLY IMPLEMENTED | Decimal/grid/depth types exist, but opportunity/ticket/shadow position paths remain long binary $1/integer constrained. Do not generalize those fields by naming alone |
| Payoff relationships | MISSING coherent executable evaluator; intent ALREADY EXISTS | #5/#9 discuss relationships. Build a small pure same-venue proof/pricing layer over current contracts, not another venue engine |
| Capacity and dollar screen | PARTIALLY IMPLEMENTED / MISSING reports | Depth walking/sizing exists. No demonstrated episode-level annual-dollar screen, fee-inclusive size ladder and capital-constrained replay |
| Shadow fills | ALREADY EXISTS for frozen experiment | Add separate challenger sensitivity bounds. Never reinterpret observed/rejected quotes as actual fills or mutate EXP-001 |
| Order states | EXISTS BUT NEEDS MODIFICATION | `PENDING`, `OUTCOME_UNKNOWN`, `RESTING`, terminal states and duplicate controls exist. No durable authenticated lifecycle/reservation/reconciler is established |
| Capital reservation | MISSING for future orders | Shadow no-negative-cash replay is useful but not a multi-process live reservation/lease mechanism |
| Reconciliation | PARTIAL | Shadow journal replay/hash checking exists. External balances/orders/positions/fills/cancel races remain future work |
| Security | PARTIAL | Private service/secrets/hardening exist; #95 proves read-side permissions matter. Read/write scopes, compromise drill and live authority need review before accounts |
| Backups | EXISTS BUT NEEDS MODIFICATION | Existing WAL-aware copies, hashes, integrity/trigger and ledger checks plus restore rehearsal. Growth, compression, bounded retention/off-host recovery and measured RTO/RPO need work |
| UI | ALREADY EXISTS; ACTIVE CLAIM | Reuse Terminal components. Add economics/attrition/provenance panels after contracts settle; no new asset-class dashboard proliferation |
| Adaptive learning | DEFERRED broad engine; PARTIAL foundations | #82 is intent, not evidence of autonomous learning. Build evidence/model lineage and review reports first |
| Public markets | DEFERRED implementation breadth; design EXISTS | #88 remains first-class. SEC/earnings gets a research slot later, not a simultaneous universal stock/options/futures platform |
| PostgreSQL/object stack | SUPERSEDED as immediate default | Keep current SQLite runtime pending measured concurrency/durability limits. Evaluate cold/derived storage incrementally |
| Licensing/access | NEEDS CURRENT EXTERNAL VERIFICATION | Source terms, private permission, owner risk acceptance, usage purpose and production availability are distinct evidence categories |
| Work in flight | ACTIVE WORK ALREADY IN FLIGHT | No open PR at audit, but unexpired A/B/C/D/E/F claims remain. Reconcile with agents before editing their files |

## 4. Reconciliation with earlier direction

**Confirmed:** #50 PIT history, #74 truthful freshness, #6 risk, #32 168-hour starter horizon, #93 survival/capacity, existing immutable accounting and one-owner architecture. No changes to EXP-001, existing operational quotas or protected collection windows.

**Modified:** #86 is now a bounded acquisition portfolio serving named hypotheses, not automatic activation of every plausible domain. #82 is lineage/experiment discipline first. #88 stays important but narrower and queued. #11's October 22 checkpoint emphasizes economic evidence and one complete operational route, not asset/API counts.

**Added:** explicit two-family limit; economic screen; consumed-holdout history; attrition; source-family dependence; probability-type and clock-uncertainty metadata; payoff proof; marginal capacity; research/collector budgets; owner-hour cost; explicit continuation/futility/stop decisions.

**Superseded:** the assumption that many simultaneous domain/model races maximize progress; automatic twelve-city rollout ahead of sports/payoff economics; a general instrument optimizer before two concrete expressions exist; unconditional 'never collect equity quotes prospectively' (historical products may not reproduce observed bid/ask/latency). Preserve older dated instructions as history and explain the new ordering rather than silently deleting them.

**Deferred:** investor/fund features #83; broad auto-ML/RL; every sport/props; full-market options; multiple brokerage adapters; HFT-style macro response; social/news firehoses; commercialization; enterprise streaming infrastructure. Existing safe collectors are not silently disabled by this planning document; review them explicitly and avoid losing protected prospective evidence.

## 5. Research portfolio and the two initial charters

Use new DRAFT experiment IDs allocated from current registry, not guessed numbers. A DRAFT may honestly have unknown thresholds; a PREREGISTERED experiment may not. Freeze rules, analysis plan, stopping rule, variants and untouched future window before outcome evaluation.

### Family A: sportsbook information versus executable event-market prices

Initial feasibility scope: NFL, pregame moneyline, Kalshi first execution-candidate venue, one existing consensus method. NFL is chosen for reuse, not because it is statistically sufficient or the most beatable league. Do not add another league merely to inflate a sample.

Reuse the current proportional two-way de-vig and median methodology as baseline. Bookmaker source-family links are explicit and UNKNOWN where not established; do not invent independence or sharp-book weights. A new de-vig variant is a logged challenger consuming research budget.

Before probability comparison, map the full outcomes: team wins, tie, overtime, cancellation, postponement, void/refund, alternate settlement and payout units. Two-way moneyline de-vig can encode conditional-on-no-tie economics and must not automatically be treated as an unconditional binary team-win probability. Unsupported mappings remain related-only. Record every exclusion and its denominator.

Separate two hypotheses: (a) calibration/outcome information at defined pregame horizons, and (b) predictive markout/lag at a named later horizon. Pick one primary objective per protocol. A better Brier score is not net trading profit; a favorable markout is not a guaranteed exit. Historical price probabilities are benchmarks, not settlement truth.

Use paired source snapshots received before each cutoff. Define maximum book age, source-update age, pair skew and receipt/clock uncertainty. Existing T-24h/T-6h/T-60m data cannot establish a seconds-long opportunity. Later captures are outcome labels, never entry features.

Define outcome unit as game/event, with nested markets/horizons/books clustered rather than counted as independent trials. Use chronological evaluation, dependence-aware uncertainty, registered variants, delayed-signal/placebo controls and a minimum economically useful effect tied to costs. Avoid repeatedly checking the same holdout until a strategy passes.

Outputs: universe/coverage census, mapping evidence, attrition waterfall, paired dataset manifest, benchmark improvement, conservative after-cost replay, markouts, episode persistence bounds, size ladder, fixed-cost burden, and continue/block/stop decision. No sports model becomes operational from this work.

### Family B: same-venue payoff consistency

Start with a small allowlisted set of complements, exhaustive partitions and nested thresholds using stored Kalshi evidence where semantics are complete. Build a payout matrix: rows are contracts, columns are all admissible settlement states, cells are exact native-currency payouts. Include void/refund/corrected/disputed/fallback cases or declare the proof incomplete.

For nonnegative long positions q, compute conditional full-fill worst-state surplus as `min_s(sum_i(q_i * payout_i(s))) - sum_i(acquisition_cost_i(q_i)) - other_applicable_costs`. Fees enter once, with rounding at the correct scope. Use actual ask ladders and depth caps; sale legs require an explicit proven short/sell/collateral model and are out of v1 scope.

Validate exact settlement identity, units, rule versions, currency, clocks and overlap of quote-validity intervals. A label match is not a proof. Unknown fees or rules prevent a claim. A raw quote imbalance, a proof, an executable-looking full-fill bound and realized profit are separate outputs.

The first version is deterministic proof/pricing, not an optimizer over every possible graph. Exhaustive enumeration of a small verified settlement partition is acceptable. If outcome states are too complex, return unsupported rather than silently leaving states out.

Model partial/orphan legs and asynchronous capture explicitly. Same-venue batch orders are not assumed atomic. Do not double-count a synthetic complement that represents the same underlying liquidity. A risk-free terminal payoff conditional on all fills does not remove entry, counterparty, settlement or funding risks.

The mathematical identity itself does not need a learned outcome-probability model. Empirical opportunity frequency, fillability, costs, persistence and capacity still need prospective evidence and a budgeted research protocol.

### Waiting queue

After a family ends or is deliberately deprioritized: weather forecast-revision/information-accumulation; slower SEC/earnings; exact-fixing BTC/ETH; options replication/distribution bounds; slower macro/EIA; conditional liquidity provision. Re-evaluate the next slot based on economics and access, not sunk effort. Risk-neutral option quantities are not physical probabilities. Related assets without identical payoffs are forecasts, not arbitrage.

## 6. Economic screen and capacity specification

The primary screen uses deduplicated opportunity **episodes**, not snapshot count. One discrepancy repeatedly observed until repricing is not many executable opportunities. Episodes sharing scarce depth/capital must not all be filled independently in replay.

For a stationary scenario only, annual contribution can be expressed as `N_episodes * E[q_filled * net_edge_per_unit] - incremental_fixed_cash_costs`. When edge and fill size depend on each other, do not replace that joint expectation with a product of unrelated means. In implementation prefer chronological scenario replay with actual eligible episode timestamps, finite venue capital, overlapping positions and release delays.

Define `net_edge_per_unit` after variable fees/spread/slippage/execution-loss assumptions. Do not subtract those costs again later or subtract realized losses from an EV already averaging wins/losses. Fixed costs are distinct. Owner hours and a selected hourly opportunity cost are shown separately from cash P&L and are not silently embedded in the same measure. Taxes are excluded unless specifically modeled.

Report return on total available capital separately from return on deployed capital. Capital-days integrate the relevant reserved/committed exposure over elapsed time using disjoint accounting states; do not count the same dollars twice as reserved and committed. Return on initial margin is not the same as return on maximum loss.

Every input must say OBSERVED, ESTIMATED, OWNER_INPUT or UNKNOWN. Short samples do not justify a precise annual forecast. Show bounds/scenarios, seasonality, clustering, missingness and the time range. Annual opportunity estimates are not proven recurrence. The owner must define minimum useful annual dollars and research expenditure before expensive optimization; the long-term $50k goal is not a minimum for every bootstrap experiment.

For capacity, replay an explicit size ladder under initial capital scenarios, not an assumed actual bankroll. At each size show complete/truncated depth, all-in cost, conservative fill count, concentration, lockup, cash fragmentation, reserve and marginal profit of the next capital increment. Visible depth is only an optimistic instantaneous ceiling; market impact/fill probability remain unknown without appropriate evidence. Flag the point where more capital adds idle balance rather than productive deployment.

A useful cash-cost example, not a budget: $150/month is $1,800/year, or 36%, 18% and 7.2% of $5k/$10k/$25k respectively. Capital-times-return examples remain arithmetic scenarios only; no annual return is selected or promised.

## 7. Eight coherent work packages

Packages are backlog scope, not blanket implementation or financial authority. Claims below refer to the audit and must be refreshed. No more than two writers plus an independent read-only reviewer in the immediate batch.

### W0 — Operating baseline and evidence durability (P0)

**Objective/why:** ensure new evidence is not lost to stale operational truth, a permissions regression or runaway backups.

**Dependencies:** authorized server operator; reconcile A/E/F claims. **Likely paths:** `backup.py`, existing backup/deploy units, current verifier/runbooks; no new backup subsystem.

**Acceptance:** actual deployed SHA/schema/unit status recorded; #95 DB-reader/WAL/quota replacement behavior verified on permanent units; verified evidence and ledger backup restored to disposable locations; hash/trigger/chain checks; measured backup duration/bytes, bounded timeout design, storage-growth budget; retention/off-host owner decisions explicitly outstanding where necessary. No backup deletion, account credential read or infrastructure purchase without approval.

**Tests:** missing WAL/SHM, concurrent reader/writer, atomic quota file replacement, SQL-write refusal, interrupted copy, corrupted artifact, disk full, timeout and restore from older supported schema.

**Production impact:** operations-sensitive, isolated PR and reviewed runbook. It does not block offline W1/W2 work, but blocks new production collection where headroom/durability is not demonstrated. **Parallel:** separate bounded operator lane only. **External verification:** SQLite behavior/documentation and actual host metrics, not speculative migration.

### W1 — Research charters, economics, consumption and attrition (P0)

**Objective/why:** turn two candidate mechanisms into falsifiable, budgeted experiments with traceable denominators.

**Dependencies:** existing registry; coordinated experimental metadata ownership. **Paths:** `experiments.py` compatibly, new non-frozen experiment folders, a subordinate `research_evidence.py` if needed; do not create another registry.

**Acceptance:** two DRAFT charters; family-slot tracking; research cash/time budget, stop/review criteria and minimum useful effect; append-only evidence-use records; economic screen manifest; attrition by event, target, snapshot and stage. Legacy evidence access is UNKNOWN unless observed; raw inspection versus viewing labels/results is distinguished. Previously viewed evidence is not relabeled untouched.

**Tests:** no post-cutoff joins; split overlap; repeated-holdout use prevents clean untouched claims; idempotent use events; nonexclusive failure reasons do not double-count the waterfall; zero/missing denominators; legacy EXP-001 validation unchanged.

**Production:** initially none, derived files/fixtures only. **Parallel:** independent of W0, then shared contract precedes W3/W4. **External:** statistical review for future thresholds; no fixed arbitrary sample-size promise.

### W2 — Units, payoff semantics, fees, clocks and rights (P0)

**Objective/why:** prevent dimensionally plausible but economically wrong comparisons.

**Dependencies:** R6 contracts; A/B/C path handoff. **Paths:** additive contracts in `opportunity.py`/venue adapters and `venues.py`, existing `fee_schedules.py`/`sources.py`; freeze-sensitive regression tests.

**Acceptance:** preserved native price/quantity/payout/currency/tick with versioned conversions; exact settlement proof references; probability meaning (physical/consensus/market-implied/risk-neutral/bound) distinct from economic-relation tier; fee effective dates; clock interval/source precision; source-family metadata; use/license inheritance through outputs. Direct multiplication of a one-cent native count into $1 contracts must be impossible without explicit conversion.

**Tests:** one-cent vs one-dollar scales, fractional counts, decimal rounding, malformed/future clocks, overlapping uncertainty intervals, mismatched currencies/rules, fee changes, revoked/unknown downstream permissions. No integer truncation of fractional values. Do not change frozen EXP-001's intended one-contract behavior.

**Production:** additive contract risk; code-only first. **Parallel:** one writer for shared types, not concurrent edits by sports/payoff writers. **External:** current exact venue/product docs and examples; no QA example becomes production verification.

### W3 — Paired sports evidence and outcomes (P0 experiment unblocker)

**Objective/why:** move from a useful odds display to an evaluable dataset aligned with the sports charter.

**Dependencies:** W1/W2 and W0 for added scheduled collection. **Paths:** reuse `odds_schedule.py`, `odds_pilot.py`, `odds_consensus.py`, existing Kalshi adapter, `price_observations.py`, `research_readiness.py`, shared Freshness providers. No second scheduler or evidence database.

**Acceptance:** complete bounded NFL moneyline universe; explicit rules mapping; odds/exchange/fee/rule snapshots selected by admissible receipt times; related-only rows excluded from equivalent-payoff claims with reasons; source/research denominators; later executable markouts and final outcomes; sample/clock adequacy test. Missing exchange captures produce DATA_GAP, not nearest later prices.

**Tests:** ties, overtime, rescheduling, cancellation, unmatched team identifiers, incomplete pages, no-book/depth, conflicting result source, stale/upstream timestamps, no work, budget exhaustion and retries. Existing 450-credit pilot cap unchanged unless explicitly amended.

**Production:** stored-evidence joins first; a new bounded public capture plan is a separate reviewed activation, not an excuse to consume paid quota. **Parallel:** sports adapter writer after W2; claims A/B/C/E. **External:** current market rules/API/fees and source cadence/terms.

### W4 — Small same-venue payoff evaluator (P0/P1)

**Objective/why:** test the second family without inventing probability forecasts.

**Dependencies:** W1/W2. **Paths:** a pure `payoff_constraints.py` beneath canonical opportunity/settlement contracts, current depth/fee functions, independent fixtures. Register one semantic owner; no giant solver dependency.

**Acceptance:** verified payout matrix and finite state enumeration for allowlisted complete sets/complements/nesting; all-in worst-state full-fill surplus at size; partial-leg exposure scenarios; claim ladder separates theorem, observed quote discrepancy, hypothetical execution and realized result.

**Tests:** nonexhaustive states, ties/void/refunds, unequal units, duplicate liquidity, truncated depth, different station/window/threshold inclusivity, unmatched fee versions, asynchronous snapshots and orphan legs. Known counterexamples must fail closed.

**Production:** none in first slice; reads stored evidence or fixtures. **Parallel:** after shared contract, can run beside W3. **External:** contract settlement/fee proof, not current account execution.

### W5 — Fill sensitivity and capital-constrained economics (P1)

**Objective/why:** learn whether a positive-looking signal survives plausible execution and matters in dollars.

**Dependencies:** W3/W4 usable evidence; current risk/sizing ownership. **Paths:** derived `research_economics.py` under the research contract, reuse `best_price.py`, sizing/depth/fee helpers; no rewrite of frozen fill policy.

**Acceptance:** chronological episode replay; conservative and explicitly less-conservative assumptions; capital reservations in the simulator; size/cost/capacity tables; scenario uncertainty; no unwarranted annualization; baseline/no-trade/opportunity-cost comparison; live-vs-shadow separation.

**Tests:** one quote seen repeatedly, capital overlap, fee double counting, no signal days, all no-fill days, failed captures, adverse selection, drawdown/correlation, partial sizing, inaccessible cash and extreme fee/slippage scenarios.

**Production:** offline only initially. **Parallel:** after evidence contracts. **External:** fees/contract economics, not fabricated live fills.

### W6 — One-venue order and capital rehearsal (P1, gated)

**Objective/why:** finish software behavior before a qualified strategy needs capital, without connecting money now.

**Dependencies:** W2 and reviewed security/authority scope. **Paths:** extend `execution_ticket.py`; one durable order-journal/reservation adapter defined by ADR; existing risk/account interfaces. Do not force live order events into the frozen shadow schema.

**Acceptance:** intent/reserve/submit-attempt/acknowledged/partial/filled/cancel-requested/cancel-confirmed/rejected/unknown/reconcile/settled semantics; venue-specific idempotency capability; atomic reserve and fence/lease; crash recovery; late fill handling; orphan policy. Unknown exposure stays reserved conservatively, stops new risk and reconciles. No global exception handler converts timeouts to rejections.

**Tests:** two workers spending the same balance; crash before/after submission; reused client ID; lost response; cancel/fill race; delayed partial fills after restart; stale lease holder; duplicate/out-of-order events; missing account snapshot; reserve release exactly once; compromised-key drill on fake credentials.

**Production:** no credentials/no network transport in first implementation; simulated transport must be structurally incapable of orders. Human canary and strategy pilot are separate later authorizations. **Parallel:** after initial economic batch, one writer only. **External:** broker/venue account and live semantics verified when that boundary is approached.

### W7 — Operator evidence views and stop/continue review (P1)

**Objective/why:** surface actionable research/operating decisions, not decorative finance statistics.

**Dependencies:** backend report schemas; Lane D handoff. **Paths:** existing dashboard/presentation/components/tests; no extra navigation for each asset.

**Acceptance:** per-family evidence window/consumption/attrition; edge at selected size; fees/rules/probability type; supported/uncertain/unsupported/operationally-blocked; cash/reserved/committed/unsettled separate; unknown-order attention; capacity/fixed costs/owner hours; next decision and owner action. No 83/100 edge score, fake profit forecast or daily income quota.

**Tests:** populated/empty/stale/unknown/blocked/zero-data/partial outcomes; mobile 360px, desktop 1440px, 200% text; no arithmetic in UI; no fake funded state or investor PII. Actual UI review remains required.

**Production:** private read-only view, standard reviewed deployment if authorized. **Parallel:** fixture-led design only before backend settles. **External:** none beyond displayed source facts.

## 8. Coverage of the review's thirty proposed additions

These are mapped into packages rather than thirty subsystems.

| Review addition | Home / treatment |
|---|---|
| 1 Annual-dollar screen | W1/W5 |
| 2 First-public-information graph | Minimal timestamped source linkage now in W2; SEC expansion queued |
| 3 LLM look-ahead audit | W1 protocol/model provenance; historical extraction is not proof of historical ignorance |
| 4 Probability-type metadata | W2 |
| 5 Payoff solver | W4 bounded enumerator, no generalized platform |
| 6 Unit conformance | W2 |
| 7 Clock uncertainty | W2/W3 |
| 8 Source-family grouping | W2/W3, unknown relationships remain unknown |
| 9 Sentinel collection | W3 policy design, production schedule only with authority |
| 10 Market-universe history | Existing discovery/storage extended by W3 |
| 11 Attrition | W1/W3 |
| 12 Delayed/placebo controls | W1 protocol and W5 evaluation |
| 13 Fill bounds | W5, separate from EXP-001 |
| 14 Adverse selection | W5 markouts, W6 actual fill linkage later |
| 15 Unknown-order quarantine | W6, extend existing OUTCOME_UNKNOWN |
| 16 Execution authority/lease | W6 with fencing, not an advisory in-memory flag |
| 17 Atomic reservation | W6 |
| 18 Orphan legs | W4 scenarios/W6 lifecycle |
| 19 Outcome finality | W2/W3 versioned labels; no rewriting settled history |
| 20 License inheritance | W2 dataset manifests |
| 21 Station uncertainty | W2 weather proof, protected EXP-001 unchanged |
| 22 Capital opportunity cost | W5 distinct benchmark, not double-counted cash cost |
| 23 Capacity vs prediction decay | W5/W7 separate evidence |
| 24 Restore drill | Existing W0 mechanism, improve measured operations |
| 25 Compromised-key drill | W6 fixture-only first |
| 26 Owner-hour economics | W1 budgets/W5 reports |
| 27 Source value | W1/W7 bounded ablation or comparison, no invented causal attribution |
| 28 Experiment budget | W1 |
| 29 Collector review/stop date | W1/W3 lifecycle |
| 30 Evidence consumption | W1 append-only role events |

## 9. Storage, security and modeling qualifications

Keep SQLite and current online-backup mechanism unless measured writer contention, restore objectives or actual multi-host needs justify a migration. #95 is evidence of a concrete permission/atomic-file issue, not proof SQLite must be replaced. Measure lock waits, write transaction length, WAL growth and restore time. Do not put the live SQLite file on network storage.

Design compressed verified backups and approved off-host copies, preserving schema/hash/ledger anchors. Existing append-only evidence cannot be deleted casually to fit storage. Retention changes require policy and owner approval. Secrets never enter research datasets/backups by convenience. Object batching and Parquet/DuckDB exports are candidates for a bounded measured analytical need; stdlib/runtime/dependency rules remain.

For LLMs, store model/version, prompt hash, source hashes and receipt/evaluation time. Historical documents do not prove that the model lacks knowledge of their later outcomes. Mark retrospective predictive results with contamination uncertainty. Time-restricting prompts or removing names is not a proof that training-data knowledge disappeared. Prospective evaluation with a fixed configuration carries separate evidentiary status.

A re-fetched unchanged book can be a valid fresh observation of unchanged offers if the source contract supports that conclusion. Conversely, a new HTTP response carrying an old forecast is not a new forecast. Preserve observation time, source update time, novelty and completeness independently. Do not change the existing UNKNOWN fail-closed gate to make reports green.

## 10. Current external checks and unresolved facts

These checks concern documentation, not activated services. URLs are included so a later agent can repeat the verification; capture effective-date evidence before using them in claims.

- S1: SQLite's own guidance supports single-host applications with low writer concurrency and identifies concurrent writers/network storage as reasons to consider client-server architecture: https://sqlite.org/whentouse.html . This supports retaining current storage pending measurements, not a throughput guarantee.
- S2: The Odds API documents featured-market history from June 2020 at ten-minute intervals, five-minute intervals since September 2022, paid-plan history: https://the-odds-api.com/historical-odds-data/ . This cannot resolve second-level historical latency.
- S3: Published pricing checked during this audit lists free 500 credits and $30/20k, $59/100k, $119/5m, $249/15m monthly tiers: https://the-odds-api.com/ . These are vendor-listed prices, not a purchase recommendation or forecast of source latency. Current project cap remains 450/month. Reverify current plan/terms before any owner budget decision.
- S4: Kalshi's public-data quick start: https://docs.kalshi.com/getting_started/quick_start_market_data . Public API documentation is not blanket permission for every storage/distribution use.
- S5: Kalshi fixed-point counts: https://docs.kalshi.com/getting_started/fixed_point_migration . The documented 0.01 count granularity reinforces preserving exact native quantities, including fills, even when planned orders are whole contracts.
- S6: Novig v3 order documentation: https://docs.novig.com/api-reference/execution/place-an-order . It describes one-cent winning contracts, non-idempotent placement, clientId as a non-unique label, and HTTP 201 as queued rather than resting. These are direct conformance requirements, not authorization to call an order endpoint.
- S7: Novig public book documentation: https://docs.novig.com/api-reference/public/get-the-order-book . It describes a no-key route and sequence/ETag behavior, but examples use a QA host. Recheck production host, access, rights and units before replacing the repo's older NEEDS_ACCESS assumption.
- S8: The Odds API terms: https://the-odds-api.com/terms-and-conditions.html . Record use-specific restrictions and derived-data rights; do not infer other vendors' rights from these terms.

Not newly resolved here: private Polymarket permission scope; production Novig entitlement; current account-specific fees/margin/trading permissions; commercial redistribution; broker transition rules; all vendor prices in the supplied review. These do not need to become blockers for fixture-only economics research. They do block claims/activations that actually depend on them.

The repo currently distinguishes Polymarket owner risk acceptance from independently verified permission. Preserve that history and do not silently label the license cleared, expand commercial use or treat acceptance as a trading grant.

## 11. Stop rules and research governance

Every new family has a declared question, cash/time budget, evaluation window and next decision date. Use ACCESS_BLOCKED, ECONOMICALLY_UNVIABLE, STATISTICAL_FUTILITY, OPERATIONALLY_UNUSABLE, BUDGET_EXHAUSTED, INSUFFICIENT_EVIDENCE or CONTINUE, with evidence and reversible governance where appropriate.

Define statistical futility and error control before evaluating results. Insufficient evidence is not no edge. Conversely, indefinite extensions are not free: identify the specific missing observation and marginal cost/value of another window. A recurring structural failure across several independent well-designed families can justify domain deferral. Retain failed/abandoned records.

A collector without an active experiment may continue only as a bounded explicitly approved sentinel/archive with documented prospective value and review date. Do not halt EXP-001 or another authorized time-critical source casually.

## 12. Roadmap and exact canonical-document integration

**Immediate batch: Economic Evidence v1.** W0 verify/report in parallel with W1; then minimum W2; then stored-evidence W3/W4 plus a small truthful UI/reporting slice. No broad new ingestion, learned sports model, database migration or live account work. Missing data is a concrete acquisition requirement, not simulated success.

**By the existing October 22 checkpoint:** target two budgeted protocols and their decision-useful evidence reports; semantic/unit/fee proof; paired-data coverage and gaps; dollar/capacity scenarios; a restore result; one disabled order-lifecycle specification; operator visibility. This is a software/economics checkpoint, not a scheduled positive alpha verdict.

**Following 30–60-day evidence window:** improve paired capture only where necessary and authorized, measure persistence and source delay, implement conservative replay and capacity, test one durable order/reservation route without credentials, perform security review, consider read-only accounts only with separate scoped authorization. End or continue each experiment by its registered criteria.

**61–90-day direction:** act on the evidence, not the calendar. A separately authorized operational canary validates real account behavior only. A strategy pilot additionally needs strategy evidence and frozen risk limits. Neither is implied by this plan. No arbitrary minimum ninety-day wait is imposed, and no live date is promised.

### Files for the coordinator to reconcile

| File / issue | Exact change |
|---|---|
| `docs/OWNER_IDEAS.md` | Index #96; retain #82/#83/#93 durable records; two-family active research section; reorder sports/payoff before broad expansion; mark displaced work deferred, not deleted; preserve truthful completion states |
| `docs/EXECUTION_PLAN.md` | Append dated owner strategic direction and exact planning/test-only scope. Keep current gates/financial/scheduling prohibitions. Do not convert package descriptions into unbounded runtime authority |
| `HANDOFF.md` | Replace stale live-state assertions with operator-verified current SHA/schema/timers/CI/evidence, note unverified facts, two active research slots and next bounded batch |
| `docs/RESEARCH_PRINCIPLES.md` | Economic screen, evidence consumption, attrition, LLM training lookahead, probability semantics, sample dependence and registered futility |
| `experiments/README.md` | Compatibility-preserving new-experiment sidecar contracts; leave existing frozen manifests byte-for-byte unchanged |
| `docs/DATA_PROVENANCE.md` | Clock quality, native units, source families, licensing lineage, outcome finality, raw-byte limits and as-of research semantics |
| Acquisition/source readiness docs | Purpose/budget/review/stop fields; revise automatic broad waves; record Novig public QA documentation as verification task; paid odds trial only if justified |
| Existing architecture/ADR/runbooks | No mandatory Postgres; backup/WAL/restore plan; one-venue order/reservation design when that package starts |
| Existing UI integration plan | Economics, attrition, capacity and exceptions reuse current components; no asset tabs or generic edge score |
| #11/#5/#9/#30/#50/#74/#82/#83/#86/#88/#93 | Link #96 and document confirmed/modified/deferred boundaries without rewriting history |

At audit time several of these paths are claimed by Lane E or specialists. This documentation branch deliberately does not overwrite them. Its standalone strategy and handoff make the direction durable; canonical incorporation remains pending until the owner/coordinator reconciles and merges it. Do not describe an open documentation PR as a deployed strategy change.

## 13. Acceptance for this strategic update

The update succeeds when future agents can identify the audit baseline, preserve completed work, see exactly what changes and why, locate the two proposed protocols and ordered packages, distinguish source evidence from assumptions, and execute the next bounded batch without duplicating architecture or gaining financial authority accidentally.

The first implementation batch succeeds with honest, reproducible evidence and clear blockers even if both candidate families prove economically unattractive. It does not succeed merely by adding code or displaying a positive number.
