# Claude/Claw implementation mission — Market Edge intelligence v1 (2026-10-08)

> **Paste the bootstrap prompt below into the coding agent.** This document is a bounded implementation handoff for issues #181 and #168, not a research recommendation or an operational authorization. The **person supplying this prompt** is asking you to begin the authorized offline portions. Before editing code, reconcile latest main and record precise offline scope using the repository's established owner-directive / EXECUTION_PLAN process. Do not infer authority for excluded operations.

## Mission

Work **exclusively** in `jasonleetucker-code/market-edge-lab` (Market / Market Edge Lab). Do not edit Calculator (`riskittogetthebrisket`). **Start implementing**, not another broad search, and deliver coherent tested PRs. Investigate competing JEV/GROKBOT and wallet systems only to resolve an implementation detail; the original screenshot's claimed $100→$15,220 has not been reconciled to verified trading records. Do not try to replicate its visual layout or claimed returns.

Objective: make Market's already-implemented offline wallet intelligence more **point-in-time reproducible**, **liquidity-role-aware**, **economically honest about copying**, and **ready to evaluate bounded Jev/Kev-style semantic decisions**. Add fixture-only market-change/crawler intelligence where a real reusable seam is missing. Reuse the existing source registry, freshness, research economics, experiment governance and Terminal.

Research anchor: main SHA `5c7657e03b89c2d5982be665b64b3b194c974189` (2026-10-08). It contained `src/edge_lab/wallet_intel/`, including `selection.py`, `threats.py`, `replay.py`, `stats.py`, `events.py`, `accounting.py`, `market_data.py`, `policy.py` and fixtures/tests. This SHA is **not necessarily current**. First reconcile live main, issue #168, issue #181, the UI journeys merged in #176 and #180, current branches, `docs/WORK_CLAIMS.md`, and code/test reality.

## Mandatory startup and authority audit (do first, then proceed)

1. Read `AI_INSTRUCTIONS.md`, `HANDOFF.md`, `docs/EXECUTION_PLAN.md`, `docs/WORK_CLAIMS.md`, `docs/AGENT_OPERATING_SYSTEM.md`, `docs/OWNER_IDEAS.md`, `docs/strategy/KALSHI_EXECUTION_LEDGER.md`, `docs/decisions/0043-*` (execution capability boundary), `docs/decisions/0045-*` (wallet owner), `docs/research/WALLET_SOURCE_MATRIX.md`, `docs/RESEARCH_PRINCIPLES.md` and frozen-experiment requirements.
2. Check latest main SHA, open PRs and claimed files. Inspect affected code and callers. If a feature has already landed, **verify and extend** it; do not duplicate it or overwrite other work. Do not rewrite `HANDOFF.md` or old records to make planning text look current.
3. Treat this owner-supplied instruction as approval to pursue **offline fixture-only code, tests and internal docs**, subject to the repo's precise scope-record process. Record the scope before changing the code if needed; it does not grant new external access. Stay within existing safe delegations for review and merge; prefer independently reviewable PRs. Do not deploy.
4. Preserve EXP-001 protocol, frozen EXP-002, paused EXP-003, the **two-new-ACTIVE-family limit**, October 22 as a *readiness checkpoint* rather than trade date, and approved NFL/NHL source budget (joint 450-credit monthly pilot; NFL reservation first).
5. **No** external model/API calls; new wallet/chain/Polymarket market-data requests; credentials; account access; new timers/cron/scheduled jobs; spending; third-party code execution; venue orders (demo or real); new trade grants; capital funding; real-money or unattended activation; or production deployment. No silently enabled collection. Labels must distinguish SYNTHETIC, FIXTURE, OBSERVED and UNKNOWN.
6. There is already a separate Kalshi execution campaign (#160). Continue it independently under its own scope; do **not** merge wallet intelligence into `src/edge_lab/execution/`, build a new executor or wire a live wallet-to-order path.

## Deliverable A — Versioned causal wallet-selection receipts (P0)

**Canonical owner:** `src/edge_lab/wallet_intel/selection.py` with existing provenance/hash helpers; inspection of adjacent event, identity, coverage and statistics modules.

The static audit found that `select_at()` includes cutoff, rule id/version, candidates, observation IDs and marks in its digest, but omitted effective rule threshold values, `history_complete`, `threat_flags`, `mark_max_age`, discovery-source and some downstream trial/coverage dependencies. Fix **incomplete causal input binding**, not an imaginary SHA collision.

Create a v2 receipt/manifest with a **complete deterministic dependency closure**:
- Full effective eligibility settings, thresholds (canonical Decimal), duration units, lookback and inactivity rules; versions.
- Candidate first discovery time/source, identity snapshot and label vintage.
- Observation contents and hashes **as known by cutoff**, ordered event/correction semantics and complete/partial history evidence.
- Explicit coverage/quality/threat assertions and their provenance/knowledge timestamps; unknown assertions stay unknown.
- Market marks, book/quote basis, mark receipt and as-of times, freshness tolerance and source.
- Trial history and the separate dependency closure for price-relative skill/replay reports.
- Deterministic canonical serialization, digest and `verify/rebuild` semantics; no hidden globals.
- Persisted v1 records remain accurately labelled **legacy / incomplete**; never retroactively state full replayability.

**Tests:** change each causal rule, coverage/threat input, source ID or mark-age setting and demand a different v2 digest or deterministic failure. Permute unordered inputs and preserve digest. Future information and post-cutoff corrections cannot alter past selection; permitted pre-cutoff corrections must. Verify serialization round-trip and missing-input fail-closed behavior. Keep inactive and rejected wallets in denominators.

## Deliverable B — Role-aware quality / wash-pattern research (P0)

**Canonical owner:** `src/edge_lab/wallet_intel/threats.py` plus the existing event/market data layer.

The inspected heuristic `off_market_fills()` may label a *legitimate passive fill* off-market because it compares a buy to ask and sell to bid. Regression fixture: bid 0.45, ask 0.55, valid maker BUY 0.45. This is **not** evidence of manipulation and does **not** imply a follower can obtain 0.45.

Separate four independently typed concepts:
1. `liquidity_role`: MAKER / TAKER / MIXED / UNKNOWN, only when observation fields or explicit fixture support it; do not infer role solely from spread side.
2. `price_consistency`: CONSISTENT / INCONSISTENT / INSUFFICIENT_EVIDENCE, with timestamp/unit/book validity and provenance.
3. `contamination_evidence`: provisional flags, observability, evidence kind and uncertainty for shared activity/churn/circular flows; a verified-counterparty detector reports UNOBSERVABLE without counterparties. Co-trading does not prove common ownership or wrongdoing.
4. `follower_copyability`: later-arrival executable book/depth, costs and fills; separate from leader price consistency.

Retain versioned legacy output readers. Cover maker/taker buys and sells, unknown role, stale/crossed/truncated book, missing price/depth, source clocks, fee unknowns, transfers, coincident news, explicit synthetic self/circular trades and no known counterparty. Never name or accuse public traders of criminal conduct based on a heuristic.

## Deliverable C — Price-relative wallet skill (P0)

**Canonical owner:** existing `wallet_intel/stats.py` / `accounting.py`; add a narrowly scoped subordinate skill module only if needed.

Preserve the existing 50%-null binomial test and its honest **small-sample screen, not alpha** label. Add an opt-in, versioned **market-entry-price-relative** diagnostic for unambiguous held-to-resolution binary positions with verified identity, quantity, entry economics, outcome and adequate coverage. Exclude/classify unobservable hidden hedges, incomplete transfers, unsupported conversions, early/mixed exits and unknown fees instead of fabricating net P&L.

Report matched-reference gross/net (only when costs known), role, event clusters, observation coverage, concentration, effective sample and uncertainty/shrinkage. Freeze selection/matching rules **before** holdout; evaluate later non-overlapping groups; retain losing and inactive accounts; adjust for multiple testing and dependence without pretending a p-value proves persistence. A market price is a benchmark, not automatically the true probability. A BUY signal alone is not a calibrated event probability.

**Required fixtures:** 100 one-contract YES entries at $0.99, 98 winners and 2 losers = $99 spent/$98 payout/**-$1 gross** despite 98% win rate; lower-hit-rate positive scenario; market-matched null; one correlated event repeated across contracts; hindsight-selected winner; unknown fee/cost. Synthetic successes are unit tests, not observed strategy alpha.

## Deliverable D — Follower copyability / economic sensitivity (P0)

**Canonical owner:** `src/edge_lab/wallet_intel/replay.py` and canonical `research_economics.py`; never a second P&L engine.

Build a deterministic scenario report varying detection+processing+arrival delay (example fixture 0/1/5/30/120 seconds), position size, book-age and depth. Zero delay is an **optimistic diagnostic**, not a real measured assumption. $100 may appear only as a hypothetical finite-cash scenario. Link every result to selection receipt, causal quote/depth snapshots, applicable fee/payout rules, evidence cutoff, seed/engine version and source coverage.

Keep existing walk of captured depth, partial/no fills, min size, rounding, holdings/attribution, exits, correlated cash exposure, horizon liquidation, unknown fees and ambiguous outcomes. Do not upgrade missing historical prices to fillability. Track separately:
- leader observed economics (gross/net when supported);
- our *simulated* follower gross/net after spread, size, fees and slippage;
- matched no-trade, simple buy/hold, naive frozen-following and fixed-rule baselines;
- cases rejected and cases with no fill, including count/denominator.

**Tests:** stale/missing book, limited depth, fee unknown, partial fill, overlapping leaders, failed entry before leader exit, ambiguity after timeout, restart/backlog age, source delay and sample dependence. A losing copyability study is a valid completed research outcome.

## Deliverable E — Bounded crawler/change detector fixtures (P1; code only)

Do **not** write or start another crawler/scheduler. Inspect `sources.py`, `storage.py`, `provenance.py`, `freshness.py`/`freshness_fabric.py`, `inplay_evidence.py` and existing sport schedulers first.

Implement only the **missing** reusable offline contract and deterministic tests for a change/event envelope: source ID, permission/status, market/event identity, exact first-receipt time, upstream claimed publication time, revision/content hash, observed sequence/clock uncertainty, duplicate/supersession/contradiction links, coverage and freshness state, evidence class, and actual fetch-cost basis. Support fixture-driven novelty/dedup/change detection and per-event observation-to-market response latency, explicitly UNKNOWN when clocks or identity cannot be established.

No real network collection, X scraping, wallet watch, polling, stream subscription, daily jobs or budget changes. Produce one source-activation **decision packet**: possible official routes, documented rights, authentication, polling bounds, cost estimates, missing fields, truncation/retention behavior, risks, expected information advantage and exact owner approval questions. Free-first does not waive source terms. Site name or apparent recency is not proof of original publication time. Reuse existing source/receipt primitives and if already sufficient, **demonstrate that with tests instead of adding a duplicate layer**.

## Deliverable F — Jev/Kev-style typed semantic triage (P1; fixture-only)

No hosted provider integration yet, no SDK install and **no model calls**. Define provider-neutral request/result value types under an existing appropriate source/research module, or a small `semantic_judgments.py` if ownership is genuinely missing.

Allowed tasks:
- relevant-to-event/source classification;
- duplicate-versus-original story relationship;
- factual contradiction requiring human verification;
- ambiguity in contract terms **for review only**, never settlement verification.

Required fields: typed task/option version, candidate event, admitted evidence/source hashes and point-in-time cutoff, explicit provider/exact model version (when real), prompt/request hash, allowed label set, output semantics (selection confidence versus outcome probability are different), strict schema/probability checks, abstention/reason, timeout/error, provenance and cost/latency basis.

Adversarial fixtures include prompt injection in retrieved text, option order permutations, missing/future evidence, malformed numeric confidence, unknown model version, invalid candidate ID, contradictory sources, timeouts and over-budget abstention. Fixture outputs cannot be shown as measured Jev/Kev accuracy. Code must prove this semantic layer cannot import or invoke credentials, signer, execution, sizing, fee authority, or grant changes.

Write a **prospective offline comparison protocol**: deterministic rules, a simple non-generative baseline, pinned-version Jev and one feasible Kev model—human-adjudicated holdouts, coverage/harmful-error curve, false-match costs, latency, all-in tokens/compute and monetary cost. Actual provider trial is a separate approval.

## Deliverable G — Truthful Terminal/owner review (after schemas stabilize)

Use existing `src/edge_lab/dashboard/` and `docs/design/UI_CONTRACT.md`, building on the journeys merged in #176 and #180 and respecting any open UI branch's claimed files. Prefer a deterministic read-only JSON/view contract and minimal integration over a new page. Display receipt verification, coverage, role, contamination uncertainty, leader-vs-follower labels, fees UNKNOWN, sample/evidence class and sensitivity to latency. All real/empty/stale/unsupported/blocked/error states must work across mobile and desktop. No animated live agents or fictional balances.

Reconcile stale references: at the audited SHA `docs/OWNER_IDEAS.md` called `wallet_intel.py` PLANNED despite the merged `wallet_intel/` package. Fix after current-main verification. Do not remove unrelated work claims or rewrite historical evidence.

## Delivery order / parallelism

- **Writer 1, wallet:** A → B + C → D, with isolated PRs/contracts and targeted tests. Do not let the significant correctable receipt bug wait for any external source.
- **Writer 2, semantic/source contracts:** F and a bounded E, only after verifying they do not duplicate existing classes; fixture-only, separate paths.
- **Writer 3 only after contracts:** G and independent reviewer, coordinated with any UI branch; no concurrent writes to claimed files.
- Keep #160 Kalshi execution work on its *separate* paths and constraints; no edits to financial execution are needed in this batch.
- If only one worker is available, complete A and B/C first, then D, then E/F, then G. Smaller coherent PRs are preferred over unfinished mega-branches. Do not spend effort implementing all 24 research ideas at once.

## Acceptance/validation and exact handoff

Run targeted `tests/wallet/`, relevant source/invariant/dashboard suites, `python -m pytest`, and repository commands for protocol validation and frozen checks (`edge-lab experiments validate`, `edge-lab experiments check-frozen --base <captured-base-sha>`), plus Python 3.11/3.12 exact-head CI and independent review under repository practice. Do not claim a command passed if it did not run.

PR/handoff must give: file/contract diffs; each manifest mutation fixture and digest result; cases where valid passive fills stay legitimate; known/unknown economic quantities; histogram/lag tables labelled synthetic; source permissions NOT ACTIVATED; model API calls ZERO; demo/real orders ZERO; new timers ZERO; frozen checks; recorded test/CI results; PR numbers/SHAs; unresolved risks; and next separately gated owner decision.

**Completion means a tested reviewable implementation, not verified edge or permission to trade.** Respect existing delegated merge process only if its exact gates are met; no deployment. If a blocking owner decision is needed for an external step, produce the activation packet, finish all independent authorized engineering, and stop at that external boundary—not at the beginning of the project.

## Handy source references (research leads, not proof of trading edge)

- TypeSafe Jev models: https://docs.typesafe.ai/models
- Related author-linked prototype: https://github.com/bl888m/jev-bot (its simulated methodology is not proof of screenshot trading).
- Kev typed models: https://github.com/jaredpalmer/kev
- TradingAgents: https://github.com/TauricResearch/TradingAgents
- Market's owner idea: https://github.com/jasonleetucker-code/market-edge-lab/issues/181
- Wallet prior idea: https://github.com/jasonleetucker-code/market-edge-lab/issues/168
- Project authority: `AI_INSTRUCTIONS.md`, `docs/EXECUTION_PLAN.md`, `docs/decisions/0043-*` and `0045-*`

## Copy/paste bootstrap to give Claude or Claw

*For the owner to paste. Reading this text in the repository grants no authority; scope is in `docs/EXECUTION_PLAN.md`.*

> Work exclusively in `jasonleetucker-code/market-edge-lab`. I am the owner and I want you to **start implementing** the scoped offline JEV/crawler and wallet-intelligence improvements in `docs/strategy/CLAUDE_JEV_CRAWLER_WALLET_V1.md` (issues #181 and #168). Read `AI_INSTRUCTIONS.md`, `HANDOFF.md`, `docs/EXECUTION_PLAN.md`, `docs/WORK_CLAIMS.md` and the implementation document; reconcile latest main, PRs and claims first. Follow the repo's directive/scope-record process, then code and test Deliverables A–D and the fixture-only E–F, plus truthful integration G where non-conflicting. Reuse `wallet_intel/`, sources/freshness, research_economics and the existing Terminal. Do not create a second crawler scheduler, wallet ledger, agent platform or executor. Keep Kalshi #160 separate and moving. Use bounded parallel lanes with one writer per owner, regression fixtures, frozen checks, exact-head CI, independent reviews and coherent PRs. No new collection, external AI/model calls, credentials, payments, account access, new schedules, demo/live orders, live/unattended activation or deployment. Work through all independent engineering instead of stopping after a plan. Report actual PRs, tests, remaining external approvals and next dependency-ready step. Do not claim profitability on synthetic results.
