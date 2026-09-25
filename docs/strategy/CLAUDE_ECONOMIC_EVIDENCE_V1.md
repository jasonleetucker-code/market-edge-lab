# Claude Code handoff — Economic Evidence v1

Work exclusively in `jasonleetucker-code/market-edge-lab` (Market / Market Edge Lab). Do not work in Calculator, Brisket or any other repository. This is an implementation handoff, not another brainstorming assignment.

## Mission and reason

Market Edge is a private, Python-based research/data/shadow platform for identifying and eventually trading genuine after-cost edges. It already contains an immutable SQLite evidence store, protected NYC weather research, sports odds/consensus, venue/rules/depth/fees primitives, a shadow ledger, risk controls, Freshness supervision and a mobile Terminal.

The owner expects to start with little capital and ultimately hopes for $50,000–$100,000/year of sustainable after-cost trading profit. This is an aspiration, not a forecast. The independent review identified the principal risk: building an impressive platform without demonstrating economically meaningful profit capacity.

Owner directive **#96** changes the near-term strategy to **two new active research families at most**, in addition to the untouched NYC experiment:
1. narrow sportsbook information versus executable event-market prices;
2. same-venue mathematical payoff relationships.

The purpose of this batch is to make those two questions testable with trustworthy data, cost, size, attrition and research lineage. Do not build an autonomous learning system, universal broker stack or huge new data lake.

Read `docs/strategy/2026-09-24-evidence-to-economics-reset.md` for the audited gap analysis, work packages W0–W7, source checks and exact canonical-document changes. This handoff is self-contained on the operative requirements, but current repo truth always supersedes its historical state snapshot.

## 1. Establish current truth before editing

The audit baseline was main `f5bfa6e11337861c5999c6ddf03a94c67d54716f` (#95), following #94 at `3990ee708ddf8a0b9ba514f0d107a9167f907796`. No PRs were open at the audit; the strategy documentation PR may now be open. Do not assume those facts remain current.

Read:
- `AI_INSTRUCTIONS.md`, `HANDOFF.md`, `docs/EXECUTION_PLAN.md`, `docs/OWNER_IDEAS.md`, `docs/WORK_CLAIMS.md`, `docs/AGENT_OPERATING_SYSTEM.md`;
- `docs/RESEARCH_PRINCIPLES.md`, `docs/DATA_PROVENANCE.md`, `experiments/README.md`;
- the relevant current `docs/research/` acquisition/source-readiness/multi-city plans;
- existing UI and deployment contracts only where the batch touches them;
- issues #96, #11, #5, #9, #6, #7, #30, #32, #50, #74, #82, #83, #86, #88 and #93, including newer decisions.

Inspect default branch, recent commits, PRs/reviews/exact-head CI, remote branches, local worktrees, uncommitted/unpushed changes, current experiment inventory and work claims. Record what is actually running and what exists only in code/docs.

At audit time A/B/C/D/E/F claims remained unexpired even after their PRs merged. Do not delete their rows because a PR is closed. Coordinate or obtain release of the exact paths before editing. The strategy author only owned the new `docs/strategy/` files; canonical root/roadmap files were intentionally left to the coordinator.

`HANDOFF.md` was stale relative to main. Obtain actual server SHA/schema/timers/health through the already authorized operator route, or state that production remains unverified from this session. Do not reuse a historical count as a fresh measurement. Current tests, source code, production and statistical results are separate evidence.

## 2. Preserve completed work and hard boundaries

Do not rebuild the following:
- `experiments.py` and its existing freeze/lifecycle;
- `odds_consensus.py` and `odds_api.py` proportional two-way de-vig, exact-line median, dispersion, hashes and bounded stored-data queries;
- `freshness.py` / `freshness_fabric.py` and current no-work/UNKNOWN rules;
- `opportunity.py` Event/Market/Payoff/quote/depth contracts and `best_price.py`;
- `fee_schedules.py`, `venues.py`, `sources.py`, provenance/redaction;
- `shadow_ledger.py`, `risk.py`, `starter_policy.py`, `ledger_anchor.py`;
- `execution_ticket.py`, which already contains `OUTCOME_UNKNOWN`, transition checks and duplicate controls;
- `backup.py` online-copy/integrity/hash/restore machinery;
- Terminal odds history, consensus, freshness and related-market components from #80/#85/#91/#94.

Keep SQLite and the stdlib runtime for this batch. No PostgreSQL, Kafka, Kubernetes, feature-store service, new broker SDK or generalized solver dependency without a separate measured need and approval.

Preserve EXP-001's original files, frozen code/artifacts, model, fee/statistical assumptions, decisions, fill method, ledger and 180/365-valid-day looks. No interim alpha verdicts, retuning, reclassification of old trades or rewriting its manifest to accommodate new fields. Add new-experiment sidecars compatibly.

Preserve `STARTER_MAX_7D_V1` and the distinction between venue-tradable cash and bank withdrawals. Do not assume an early resale satisfies the 168-hour policy.

This batch is read-only research, documentation and mock/test-only implementation within current authority. No real/paper venue orders, API-key installation/readback, account registration, funded-account changes, margin, paid plans, new timers, new production network runs, backup deletion, public dashboard exposure or gate advancement merely because this prompt contains a future design. Review current explicit authority for each operational step. Keep `EXECUTION_NOT_AUTHORIZED` unconditionally enforced.

## 3. Scope the batch before writing code

Use at most two writers plus one independent read-only reviewer. One writer owns shared types. Do not simultaneously give sports and payoff workers write ownership of `opportunity.py`, `storage.py`, `cli.py`, fees or canonical docs.

Produce one concise implementation plan with claimed paths, dependencies, acceptance, production impact and stop boundaries. Prefer three coherent PRs, not a giant feature branch:

**PR A — research contract and governance.** Two DRAFT protocols, economic screening schema, evidence-consumption and attrition records, canonical strategy reconciliation.

**PR B — semantic conformance and pure payoff evaluator.** Minimum shared contracts plus small deterministic same-venue evaluation with fixtures/stored evidence.

**PR C — paired sports evidence, economics and private UI.** Stored-data join/coverage report using the existing consensus, episode/size accounting and a narrow Terminal view. No extra data purchases or new schedules. If existing snapshots are insufficient, finish the truthful data-gap report and exact bounded capture plan; keep production activation as a separately authorized continuation.

W0 operating verification/backup work may proceed in a bounded separate operator lane. It is a prerequisite for increasing production ingestion, not a reason to stop offline research contracts.

Before creating another module, assign exactly one semantic owner and check whether existing code already owns the concept. Possible subordinate modules are `research_evidence.py`, `research_economics.py` and `payoff_constraints.py`; these are not mandatory names and must not become duplicate registries/ledgers/engines.

## 4. Operating verification: fix the real prerequisites, not imaginary ones

Review #95 and verify permanent dashboard/Freshness units can read after the last writer closes and WAL/SHM side files need recreation. Keep SQL/query-only and DB-file protections. Check the quota file is read after atomic replacement rather than pinned to a stale inode. Do not broaden write access to the ledger directory to make a check pass. Unknown quota must block spend.

Use existing backup/restore tooling to obtain a measured result: database/schema/hash/trigger verification, ledger-chain verification, copy/restore duration, bytes, headroom and failure behavior. If a fresh restore cannot be performed through available authority, report the exact blocker.

Design compression and size-aware timeout as a scoped improvement. No old backups are deleted and no off-host paid service is opened without a retention/destination decision. Backup job success alone is not restore proof. Preserve F09 as manual, roughly weekly and on notable ledger events; do not add an anchor timer.

A preflight FAIL blocks an install. Never override because the gap between timers is short. Respect 17:40–18:50 America/New_York and actual settlement/capture jobs; re-read the current runbook for any newer window. Verify each service is idle rather than assuming a calendar gap guarantees it.

## 5. PR A: research governance and two DRAFT protocols

Allocate new experiment IDs from the actual registry. Do not guess EXP-002/003 if another session used them. Create two DRAFT specifications, not a claim that two strategies are validated.

Each charter must contain:
- mechanism and named economic hypothesis;
- exact eligible universe and observation/cluster units;
- primary versus secondary endpoint;
- data availability/cutoffs, feature/label separation and permission lineage;
- existing baseline, allowed variants and multiple-testing plan;
- cost/fill/size/capital assumptions and evidence quality;
- chronological validation, independent future evaluation window and exposure history;
- budgeted owner hours, cash/data costs, review date and stop/continue/futility logic;
- minimum useful economic result or an explicit missing owner/power-analysis input;
- product readiness versus strategy readiness and permitted uses.

Unknown values are permitted honestly in DRAFT. Do not make up sample size, threshold, annual opportunity count, source independence or profitability merely to pass preregistration validation. Before PREREGISTERED, settle those choices with adequate power/cost rationale and freeze them before reading the test outcomes. Keep all failed and inconclusive candidates.

### Evidence-consumption contract

Extend current experiment provenance rather than create another AI-memory store. Record dataset/version/hash, experiment/family, role, effective as-of window, actor/tool, action time, code/model/prompt version, action type and influence on development.

Distinguish untouched evaluation, operational-only access, feature inspection, label/result viewing, validation/tuning and training/development. A clean holdout cannot be reclaimed by copying/renaming the same dataset. Legacy access history is UNKNOWN, not retrospectively certified untouched. An append-only access ledger is useful but is not proof that nobody viewed a file outside it; document procedural limits.

Avoid touching protected EXP-001 outcomes in the new development workflow. Its preregistered reporting remains separate.

### Attrition contract

Report potential events, markets, target horizons and snapshots separately. Show unavailable/missing/stale/partial/rules-unresolved/unsupported/insufficient-size/capital-veto/eligible/signal/no-signal/fill/no-fill/outcome-pending/final-evaluable counts with reasons and the correct denominators.

Keep all raw multi-reasons, but use a deterministic primary exclusion order or set accounting so the waterfall reconciles without double-counting. Zero is not missing, no signal is not failed collection, and no simulated fill is not no opportunity. Future targets must not be marked missed before their deadlines.

## 6. PR B: semantic conformance and same-venue payoff evidence

Add only the shared metadata needed now, compatibly:
- native quantity and granularity, price convention, currency, payout per native unit, multiplier and normalization version;
- exact rule/settlement identity and evidence hash;
- fee scope, effective timestamp, rounding and claim basis;
- probability meaning: physical estimate, sportsbook consensus, market-implied price, risk-neutral option quantity, deterministic replication/payoff bound;
- economic relation tier independent of probability meaning;
- source family/grouping with UNKNOWN permitted;
- event/source/first-observed/receipt/ingestion/processing clocks and precision/uncertainty when available;
- outcome finality and source-rights version/use restrictions inherited into derived datasets.

Do not require fields absent from legacy records to be fabricated. Define an explicit compatibility reader and keep legacy outputs/frozen IDs unchanged. New unsupported payoffs stay unsupported.

Official checks discovered during the audit, to reverify and capture as fixtures before a live adapter uses them:
- Kalshi fixed-point quantities can be fractional to 0.01; integer truncation is not safe for new fill/account handling.
- Novig v3 documents one-cent winning contracts; native count cannot be reused as $1 contracts.
- Novig placement is documented non-idempotent; `clientId` is a label not uniqueness enforcement; HTTP 201 means queued, not resting.
- Novig now documents an unauthenticated public-book path, but examples use QA. Do not claim production public access or widen collection before endpoint/terms verification.

Reference URLs are in the strategy document. Do not make any order request during a documentation/conformance test.

### Payoff evaluator

Use existing Event/Market/Payoff, depth/grid and fee code. Build a pure bounded evaluator for a verified allowlist of same-venue complements, exhaustive partitions and nested thresholds. Do not build a universal optimizer.

Inputs: contracts and rule proofs, finite settlement states, native payout matrix, signedness/long-only eligibility, observed ladders, timing validity, fee versions, size request and declared capital scenario.

Initially support nonnegative long legs only. Buying complement shares is different from assuming short selling is supported. Refuse unavailable selling/collateral economics.

For each supported size compute all-in acquisition cost, per-state payout, minimum full-fill payout, worst-state surplus, limiting depth/leg and capital lockup. Include refunds, ties, cancellation and fallback outcomes in the proof or return incomplete/unsupported. A missing state must never make the result look risk-free.

Keep distinct: semantic proof, observed quote inconsistency, conditional full-fill surplus, simulated achievable result and actual captured profit. There are no actual fills in this batch. Same-venue legs are not presumed atomic. Report orphan-leg exposure and do not suppress it because the complete basket would settle favorably.

Tests must include a genuinely valid complete set and deliberately invalid lookalikes: missing tail bracket, overlapping/exclusive thresholds, changed rules/station/window, partial depth, truncated depth, stale/nonoverlapping quotes, one-cent/$1 mismatch, fee rounding erasing surplus, duplicate synthetic liquidity, cancellation/refund breaking a naive proof, and only one leg filling.

## 7. PR C: one narrow sports dataset and honest economics

Start feasibility with **NFL pregame moneyline and the existing consensus method**, using Kalshi as the first intended execution-price route if the actual market/rules/access evidence supports it. Do not silently expand sports or create an ML winner predictor. Do not assume that two-way sportsbook prices and a binary team-win event are economically identical.

Map game identity, scheduled time, teams, market side, overtime, ties, postponements, cancellation/refund, result source, rules version and settlement horizon. Where mappings are related-not-equivalent, keep the observations but block equivalence/edge claims. Do not infer no market from partial catalog failure.

Build deterministic joins over existing snapshots using receipt times at/before the decision cutoff. Reject excessive pair skew; source update timestamps are distinct. Persist IDs/hashes of all inputs plus consensus/version and explicit missingness. Never fill absent historical exchange prices from a later book.

The current sparse T-24h/T-6h/T-60m schedule supports defined-horizon feasibility/calibration, not seconds-level lag claims. A five-minute historical feed cannot establish five-second execution. Paid quota does not prove lower latency. Freeze any markout horizons at the resolution the data supports, and disclose interval uncertainty in observed persistence/lead-lag.

A later source change, de-vig method, weighting, freshness filter or exclusion is a registered variant, not a quiet improvement. Do not count nine books, both team sides or multiple snapshots as independent games. Define appropriate clustering and chronological validation. Add delayed-signal and placebo controls in the protocol.

Attach eventual official outcomes and contract resolution states; distinguish pending/preliminary/corrected/final. A matching final winner does not prove the order would have filled.

### Data-gap continuation

If paired Kalshi sports books, rule versions or outcome labels are missing, produce an exact gap inventory and minimum capture plan: selected events/markets, existing adapters, target schedule, worst-case requests/retries/bytes, permissions, quota interaction and rollback. Preserve the approved 450-credit monthly Odds cap. Do not spend additional credits or add timers merely to populate the UI.

Once current authority explicitly covers that exact bounded public collector and W0 passes, it may be a separate reviewed continuation. If scope is not authorized, leave activation blocked with a concrete decision packet while completing fixture/stored-data work. Do not make the entire batch dependent on Polymarket permission or a new Novig account when a same-venue Kalshi research path is sufficient.

## 8. Economic and capacity report requirements

Treat observed discrepancies as episodes with a defined start/end and shared liquidity. Repeated observations of the same orders do not create repeated earning opportunities.

Build an interpretable scenario report from explicit inputs: eligible episodes, fill assumptions, size ladder, per-unit variable costs, lockup, finite per-venue capital, reserve, correlated exposures, fixed cash costs and owner hours. Mark inputs OBSERVED, ESTIMATED, OWNER_INPUT or UNKNOWN.

Prefer chronological replay. A simplified screen is `annual eligible episodes * E[fillable quantity * net edge per unit] - incremental fixed cash costs`, only under stated stationarity assumptions. Do not multiply capital by executable quantity and turnover again, assume unlimited fills, or subtract fees/losses twice when already included in net edge/P&L.

Show:
- gross versus net variable-cost result;
- fixed cash costs separately;
- owner-hour economic cost separately;
- return on total available capital versus deployed capital;
- capital-days, lockup, idle cash and reasons;
- conservative and less-conservative fill sensitivities;
- size ladder and marginal useful capital;
- opportunity frequency and dependence;
- uncertainty/insufficient evidence rather than an exact annual-profit forecast.

Unknown probability means no estimated stochastic EV. A payoff proof can yield a conditional bound without a learned probability. An economics screen may say INSUFFICIENT_EVIDENCE or ECONOMICALLY_UNVIABLE; neither is a code failure. Small-capacity opportunities can be worthwhile bootstrap experiments even if they cannot alone produce $50k/year.

## 9. UI is part of this batch, but not a separate redesign

Use the existing Terminal shell, tables/detail views and canonical presentation APIs. Add a compact evidence/economics section for the two families showing protocol status, as-of window, denominator/attrition, probability/relation type, source/rules/fee provenance, edge at a selected size where calculable, capacity limits, fixed-cost assumptions and the next blocker/decision.

Do not present zero profit where outcome data is missing. Do not label a conditional basket surplus arbitrage captured. Do not show a funded/ready-to-submit state without account evidence. No numerical edge score, daily profit target, new theme or separate stock/options/futures navigation.

Build populated/empty/stale/unsupported/partial/unknown cases against stable backend fixtures. Review 360px, 1440px and 200% text with the repo's browser-evidence workflow. Report what was actually rendered; do not claim a physical-phone check from browser emulation.

## 10. Durable canonical reconciliation

At the legitimate claim handoff, update the canonical strategy docs rather than leaving #96 detached indefinitely:
- `OWNER_IDEAS.md`: index #96, integrate #82/#83/#93 as appropriate, two active research slots and explicit displaced/deferred waves;
- `EXECUTION_PLAN.md`: dated authority entry for actual planning/test-only work, without financial or scheduling permission inflation;
- `RESEARCH_PRINCIPLES.md`: economics, consumed evidence, attrition, LLM model-level lookahead, typed probabilities, dependence and preregistered futility;
- `experiments/README.md`: compatible sidecar rules for new experiments, no frozen changes;
- `DATA_PROVENANCE.md`/source plans: purpose, rights inheritance, clock precision, units/finality, review/stop dates and raw-byte limitation;
- `HANDOFF.md`: fresh verified operational state, completed versus pending work, test/CI/deploy distinction and next concrete batch.

Preserve previous directives with dated supersession notes. #86 broad expansion is narrowed, not erased. #88 remains first-class but queued. #82 becomes simple lineage/review before autonomous learning. #83 investor/fund work is deferred. #93 bootstrap economics and #32 survival/horizon remain intact. Public markets can eventually qualify first, but that does not justify fifteen simultaneous experiments.

## 11. Later execution work: design the boundary now, do not implement everything

Document a next-package ADR that extends the existing order-state types into a durable one-venue lifecycle, with atomic reservation, intent IDs, venue-specific dedup semantics, single-authority fencing, restart recovery and external reconciliation. Include unknown status, cancel requests versus confirmation, late/partial fills and orphan legs.

A timeout must not release risk or cause blind resubmission. A canceled order may still have fills; settlement clears the appropriate exposure later. Two workers must not spend the same cash. Paper/sandbox validates software, not live fill quality. A real operational canary needs separate explicit owner authority and cannot be counted as alpha proof; a strategy pilot also requires its evidence gate.

Do not include live transport, keys or account reads in Economic Evidence v1 unless a later exact directive explicitly authorizes them. No general brokerage integration is needed to finish this batch.

## 12. Testing, review, merge and deployment

Run the relevant existing tests plus new deterministic fixtures. Then run the full required suite with `python -m pytest`, experiment validation/frozen checks and any current lint/static commands documented by the repo. Derive exact command names from current code; do not invent a test result.

Explicitly test future-data joins, altered evidence roles, attrition reconciliation, identical replay output/hash, money/unit math, rule mismatches, fees erasing surplus, partial data, no-work freshness, legacy compatibility and EXP-001 frozen artifacts. Network calls in CI remain prohibited. No tests may consume the production data budget.

Obtain independent review for statistics, payoff math, accounting, safety, storage and production changes. Resolve consequential findings and re-review the delta. Require full relevant CI green on the **exact final head**, current-main reconciliation and mergeability. Do not self-certify independence. Do not relax tests to get green.

Commit and push bounded branches; open/update PRs with purpose, source evidence, changed contracts, tests, actual results, production impact, authority and remaining blockers. Respect the actual merge delegation; an open PR is a successful handoff when approval/CI is still missing. Do not claim it merged.

Deploy only reviewed merged code where explicit authority permits and the current runbook preflight passes. Verify actual SHA, schema, protected flows, quota, reader health, backups/restores and private UI. Never infer deployment from merge. This batch may appropriately end with code/PRs and no production change.

## 13. Completion and stop conditions

Economic Evidence v1 is complete when:
1. current repo/production limitations and claims are recorded honestly;
2. two DRAFT or legitimately frozen protocols exist, with no hidden third family;
3. economic screening, evidence roles and attrition are reproducible;
4. native unit/rule/fee/time semantics have adversarial fixtures;
5. the small payoff evaluator proves valid cases and rejects counterexamples;
6. the sports join produces valid rows or explicit, actionable gaps without hindsight;
7. capacity/fill sensitivity output distinguishes data, estimates and unknowns;
8. the existing UI exposes those truths without invented values;
9. frozen EXP-001 behavior and financial authority are unchanged;
10. tests/review/PR/CI and actual deployment state are documented separately.

Stop at access, legal-scope, quota, paid-source, credential, new-schedule, shared-file conflict or financial-authority boundaries, but continue independent offline work. Do not wait idly for future sporting outcomes or scheduled settlement during this implementation session.

Final report must include: exact commits/PRs and CI heads; what reused existing work; protocols and budgets; coverage/attrition counts with as-of time; payoff proof/counterexamples; capacity/cost results or why unavailable; restore/production evidence versus unverified items; UI evidence; unchanged gates; canonical-doc reconciliation status; owner-only decisions; and the single best next implementation batch.

Remove only your own completed claim rows. Keep incomplete work and remaining owners explicit. Do not report a successful research conclusion merely because all implementation acceptance tests passed.

**Success is a shorter defensible path from point-in-time data to validated, executable, capacity-measured economics—not a larger platform.**
