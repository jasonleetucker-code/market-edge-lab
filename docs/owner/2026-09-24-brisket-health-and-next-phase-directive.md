# Owner directive, 2026-09-23/24: restore Brisket health, then begin the Market Edge next-phase build

Source: the owner's message to the local Claude Code session on the laptop (2026-09-24 ~01:00
UTC), followed by the owner's four corrections to the approved plan (same session, ~01:15 UTC).
The corrections supersede any conflicting wording in the directive.

- **The corrections are verbatim.**
- **The directive** keeps the owner's wording for every rule, bound and authorization in the
  Market Edge phases. Where the original put one item per line, those items are joined into
  sentences. Bracketed lines condense coordination boilerplate and one superseded schedule.

Where this record and a later owner decision disagree, the later decision wins and is recorded
in `docs/EXECUTION_PLAN.md`.

---

## Owner corrections to the approved plan (supersede conflicting wording below)

> 1. BRISKET HEALTH SEMANTICS
>
> When a critical source scrape fails or times out but the previous served generation remains
> structurally valid:
>
> - DO preserve and continue serving the last-known-good generation.
> - DO keep `contract_ok=true` for that served generation.
> - DO record that the attempted generation was refused and identify the failed/timed-out source.
> - DO NOT overwrite exports/latest or runtime generation state with the partial generation.
>
> However:
>
> DO NOT make overall `/api/health` green merely because the LKG contract remains valid.
>
> While the latest required critical-source run is failed/timed-out, overall health should remain
> truthfully DEGRADED / HTTP 503, with separate dimensions similar to:
>
> contract_ok=true
> served_generation_ok=true
> source_health_ok=false
> status=degraded
>
> Once the critical source successfully recovers and normal freshness requirements hold, overall
> health may return 200.
>
> Contract integrity and current ingestion health are separate truths.
>
> Update the regression tests accordingly.
>
> 2. ROBUST KELLY UNCERTAINTY
>
> Do not hardcode `p_lo` as the pessimistic probability.
>
> For each candidate stake, evaluate expected log wealth over the entire justified probability
> uncertainty set/posterior support and use the worst admissible value.
>
> For a YES position the adverse endpoint may be low p.
> For a NO position the adverse endpoint may be high p.
> For future payoff structures the adverse point may differ.
>
> The generic optimizer must derive this from the payoff, not assume a side.
>
> 3. ODDS API SNAPSHOT SCHEDULE
>
> Do not automatically spend three paid odds calls every calendar day.
>
> Use quota-free event/schedule discovery where the current provider rules permit it.
>
> Build a game-relative collection policy under the same hard 450-credit monthly ceiling.
>
> Initial preferred observations:
>
> - approximately T-24 hours
> - approximately T-6 hours
> - approximately T-60 minutes
>
> for relevant NFL events.
>
> You may adjust the offsets if measured provider/event behavior supports a better design.
>
> Before enabling:
> - enumerate the upcoming schedule;
> - calculate worst-case and expected monthly credits;
> - prove it remains <=450 and below provider remaining quota;
> - persist the intended target time for each snapshot so missed captures remain visible.
>
> The objective is useful prospective line-history and closing-line information, not merely
> regular clock polling.
>
> 4. BRISKET WORK-CLAIM COLLISION
>
> The read-only production investigation may proceed immediately.
>
> Before modifying server.py, data_contract.py, or another currently claimed Brisket path:
>
> - inspect the current WORK_CLAIMS;
> - inspect the owning branch/PR and recent commits;
> - coordinate or prove the claim stale under repository rules;
> - never create an overlapping writer merely to move faster.
>
> Continue independent evidence gathering while waiting.
>
> Everything else in the plan remains approved.
>
> Proceed through implementation rather than returning another plan.

---

## The directive

```text
# OWNER DIRECTIVE — RESTORE BRISKET HEALTH, THEN BEGIN MARKET EDGE NEXT-PHASE BUILD

This is a TWO-REPOSITORY mission:

1. `jasonleetucker-code/riskittogetthebrisket`
2. `jasonleetucker-code/market-edge-lab`

Treat the CURRENT repository state as authoritative. The SHAs mentioned below are historical anchors only.

OWNER INTENT

I trust you to make routine engineering/research decisions within the boundaries below.

Do not stop and ask me to choose between reasonable implementation alternatives when the evidence clearly supports one.

Make the decision, record why, test it, and continue.

Only stop for something genuinely owner-only, such as:
- a credential I personally must obtain/install;
- creating/funding a financial account;
- spending money;
- an irreversible/destructive operation outside an existing reviewed runbook;
- real-money order authority;
- materially weakening an existing safety/security boundary.

This directive DOES authorize the bounded work explicitly described below.

It DOES NOT authorize:
- real-money trades;
- deposits;
- withdrawals;
- brokerage/exchange trading credentials;
- Gate 8+ advancement;
- automatic live execution;
- paid APIs/subscriptions/services;
- public Market Edge exposure;
- disabling Tailscale/private access;
- SSH key changes;
- root-login hardening;
- OS upgrades/reboots;
- unrelated broad Brisket refactoring.

MISSION ORDER

PHASE 1 — Restore Brisket `/api/health` and `contract_ok`
PHASE 2 — Re-verify Market Edge after the Brisket repair
PHASE 3 — Design and build the next-generation mathematical stake-sizing research engine
PHASE 4 — Build the multi-venue best-price-for-size comparator
PHASE 5 — Close the Polymarket rules/fee gaps needed for honest comparison
PHASE 6 — Prepare and, when the owner supplies the free key, activate The Odds API sports-data pilot
PHASE 7 — Activate free ntfy push notifications safely
PHASE 8 — Reconcile the longitudinal learning-history requirement
PHASE 9 — Re-plan the roadmap and leave both repositories clean

Do not start broad macro/crypto implementation during this mission.
You MAY preserve them as NEXT/LATER research directions after the above work is complete.

[Global coordination rules: fetch current main, read canonical instructions, run bootstrap, read
HANDOFF / EXECUTION_PLAN / WORK_CLAIMS / open PRs / issues / runbooks, claim files before editing,
one writer per path, never overwrite another session's work, separate branches/PRs per repo.]

PHASE 2 — MARKET EDGE STARTUP AND PROTECTION

Read: AI_INSTRUCTIONS.md, HANDOFF.md, docs/EXECUTION_PLAN.md, docs/OWNER_IDEAS.md,
docs/WORK_CLAIMS.md, docs/DATA_PROVENANCE.md, docs/RESEARCH_PRINCIPLES.md,
docs/design/UI_CONTRACT.md, relevant ADRs, issues #6, #29, #30, #33, #47, #50.

If PR #51 remains open: reconcile it with current main; inspect its diff; run/confirm CI; merge it
if still correct and clean. Do not duplicate #50.

PRODUCTION NO-TOUCH WINDOWS
Market Edge collection is now valuable prospective evidence. Do not interrupt it.
NO Market Edge install/restart from 17:40 through 18:50 America/New_York.
Also avoid an install/restart while the settlement job is active around 11:15 ET and 16:15 ET.
Immediately before any install: check running `edgelab-*` jobs.
Coding/tests/PRs can continue during these windows.
Do not stop collection for development convenience.

PHASE 3 — NEXT-GENERATION MATHEMATICAL STAKE SIZING

OWNER GOAL: Market Edge should eventually recommend exactly how much capital to place on a
qualifying opportunity using mathematics, data, statistics and validated machine learning rather
than: a constant unit forever; intuition; raw model confidence; an LLM deciding a dollar number;
arbitrary confidence labels.

This work is SHADOW/RESEARCH ONLY. It does not authorize real-money use.
Do NOT alter the frozen EXP-001 research account or its preregistered sizing rule.
Do NOT silently switch the production operational shadow account to a new sizing policy during
this mission. Build a challenger/research sizing system first.

3A. Research the sizing problem deeply (Kelly; fractional Kelly; portfolio Kelly; estimation
error; Bayesian/robust Kelly; risk-constrained Kelly; drawdown/ruin constraints; CVaR/expected
shortfall; correlated wagers; liquidity and price impact; calibration uncertainty;
non-stationarity; growth vs survival) using primary/academic or technically authoritative
sources. Record citation, method, assumptions, where it applies, where it fails for prediction
markets/sportsbooks. Durable research document (e.g. docs/research/STAKE_SIZING_V2.md) and an
ADR for the selected architecture.

3B. Do NOT build `features -> opaque ML model -> dollar amount` as the primary safety-critical
sizing path. Separate: probability model; uncertainty/calibration model; execution-cost model;
portfolio/risk state; deterministic allocation optimizer; hard risk caps; explanation. ML may
estimate probability, calibration error, uncertainty, regime, source reliability, fill
probability, slippage/liquidity. The final amount must come from reproducible mathematical
optimization plus deterministic limits.

3C. Required inputs, where available: capital (equity, settled/tradable cash, committed capital,
open worst-case risk, reserve floor, capital-release timing); opportunity (payoff structure,
executable price, quantity/depth, spread, fees, price grid, estimated slippage, time to
settlement, time until capital is tradable again); model (raw probability, conservative
probability, uncertainty interval/posterior, calibration history, out-of-sample sample size,
model/version identity, domain/market type, measured recent degradation only where statistically
justified); portfolio (position, event, correlated-cluster, domain, venue, open-order exposure);
risk state (drawdown, daily/weekly realized losses, hard caps, stale/missing data state, risk
veto state, starter seven-day policy); market quality (freshness, rules certainty, fee certainty,
depth completeness, equivalence certainty, source reliability). Missing remains missing. Unknown
inputs must reduce size or block the recommendation according to an explicit rule.

3D. Work from the actual payoff contract. Derive wealth outcomes after entry cost, fees, payout,
slippage, quantity. Use expected log wealth / Kelly as the unconstrained growth benchmark, then
make it robust. Candidate: robust fractional Kelly + hard portfolio constraints, subject to
probability uncertainty, capital availability, max loss, position/event/cluster/portfolio limits,
daily/weekly/drawdown stops, executable depth, seven-day capital rule. Compare uncertainty methods
empirically.

3E. Compare at minimum: A flat unit; B fixed percentage; C full Kelly; D 1/2 Kelly; E 1/4 Kelly;
F robust/pessimistic fractional Kelly; G risk-constrained Kelly; H Kelly with
portfolio/correlation constraints. Measure compound growth, median terminal wealth, lower-tail
wealth, maximum drawdown, probability of specified drawdown, CVaR, ruin/minimum-bankroll
probability, volatility, turnover, capital lock, sensitivity to calibration error, to
slippage/fees and to correlation misspecification.

3F. ML only with enough evidence: chronological splits, point-in-time features, no leakage,
failed experiments recorded, no repeated optimization against the same test period, count
variants, compare against simple baselines. For sparse data prefer a simpler statistically
justified model.

3G. Do not treat simultaneous wagers as independent if they depend on the same underlying
event/story. Respect Outcome Board clusters, same-event exposure, mutually exclusive brackets,
venue duplicates, known correlated sports positions, future multi-domain hooks. Do not invent
correlation coefficients; where unknown use conservative cluster caps.

3H. Canonical versioned SizingRecommendation: policy_id, policy_version, bankroll,
tradable_cash, available_risk_budget, market_id, outcome_id, venue_id, model_probability,
conservative_probability, probability_uncertainty, entry_price, estimated_fee,
estimated_slippage, expected_net_edge, unconstrained_kelly_amount, fractional_kelly_amount,
liquidity_cap, position_cap, event_cap, cluster_cap, portfolio_cap, cash_horizon_cap,
drawdown_cap, recommended_amount, recommended_contracts, maximum_allowed_amount,
binding_constraint, secondary_constraints, verdict (SIZE, ZERO_EDGE, UNCERTAINTY_TOO_HIGH,
LIQUIDITY_LIMIT, RISK_LIMIT, STALE_DATA, CAPITAL_HORIZON, UNSUPPORTED), explanation,
input_timestamp, model_version, policy_version. Every dollar figure must be reproducible. No LLM
is allowed to mutate the number.

3I. EXP-001's frozen research account remains untouched. The existing operational shadow policy
remains untouched until a separately recorded sizing experiment passes its own acceptance
criteria. Build the new policy as a challenger, counterfactual replay, research report, optional
read-only recommendation on the dashboard. Do not change actual shadow fills yet.

3J. Integrate read-only sizing explanations into Terminal v1 only after the backend contract
exists, reusing the design system, clearly labelled RESEARCH SIZING or SHADOW RECOMMENDATION.
Never imply it is a funded order.

PHASE 4 — BEST-PRICE-FOR-SIZE COMPARATOR
Build ONE comparator over the existing shared objects. No venue-specific best-price engines.
Support: side/outcome; requested quantity; depth walk; per-market tick/price grid; gross cost;
average fill price; marginal/worst fill price; fee status; known fees; unknown fees; liquidity
completeness; freshness; rule-equivalence status; account-route availability; capital release
timing.
4A. Honest labels: BEST OBSERVED QUOTE; BEST GROSS COST FOR SIZE; BEST VERIFIED TOTAL COST;
BEST ACCOUNT-FEASIBLE ROUTE. If Polymarket fees remain unsupported you may say
`Kalshi $X total; Polymarket $Y gross, fees unknown`; you may NOT say `Polymarket is cheaper`
unless total-cost evidence proves it.
4B. Cross-venue comparison requires proven economic equivalence (settlement source, threshold,
inclusivity, timezone, observation period, void/cancel rule, payout, revision policy, resolution
timing). Non-equivalent markets may be shown as related discovery results but must not compete
for a "best price."

PHASE 5 — POLYMARKET US RULES + FEE EVIDENCE
Research current official Polymarket US documentation (not Polymarket International). Resolve,
if primary evidence permits: trading fee schedule; maker/taker; rounding; settlement fees;
market-specific differences; cancellation/void semantics; payout structure. Record exact access
date and source. If official evidence cannot establish a component: keep it UNSUPPORTED.
5A. 50-50 cancellation: choose the smallest correct option: A. extend the generic Payoff
abstraction so a split/cancellation outcome is correctly represented; OR B. explicitly refuse
those markets until the generic payoff engine supports them. Do not shoehorn them into a binary
contract. Do not alter EXP-001's existing binary behavior.

PHASE 6 — THE ODDS API SPORTS DATA
Goal: begin building OUR OWN prospective sportsbook-odds history. The free account/key remains
owner-installed. Agents must not ask the owner to paste the key into chat or commit it.
6A. This directive explicitly authorizes: use of the FREE The Odds API tier;
installation/use of the owner's read-only data-feed key after the owner obtains it; a bounded
read-only production schedule; no paid upgrade; no betting account; no sportsbook execution.
Budget: hard local safety ceiling 450 credits/month. Provider-reported remaining quota also wins
if lower. Never cross the free allowance automatically.
6B. Start with NFL: moneyline; spread; total. One region/bookmaker-cost group only unless current
provider accounting proves another choice is equally cheap. Do not start player props yet.
6C. [Superseded by owner correction 3 above: game-relative schedule instead of ~3 fixed daily
pulls at approximately 09:30 / 14:30 / 19:30 ET; design goal <= ~279 credits/month; provider
headers and actual cost are authoritative; documented free discovery/catalog calls may be used.]
6D. For every sports snapshot preserve: provider event id; sport/league; teams/participants;
commence time; bookmaker; market; side/outcome; threshold; offered odds; provider last-update
time; Market Edge receipt time; request identity with key redacted; parser version; payload
hash; source coverage; quota headers; failures; missing books/markets. Store all prospective
observations needed to reconstruct what was known at the time.
6E. If `EDGE_LAB_ODDS_API_KEY` is not installed: do every other task first, then give the owner
ONE concise exact setup step. Do not block the mission waiting for the key. Do not ask for it in
chat. After it is installed: one bounded live smoke read; verify exactly which books/markets
return; record quota consumption; then enable the approved bounded schedule. No live sports
strategy or betting is authorized by this.

PHASE 7 — ENABLE NTFY FREE PUSH
The owner now approves the first real ntfy push send. Use the already-built provider-neutral
notification contract and ntfy sink. Do not build another alert system.
7A. Keep fixed/minimal headlines. Do not send balances, stake sizes, market IDs, account IDs,
detailed model probabilities, secrets, API keys.
7B. Use the free hosted `ntfy.sh` path already allowed by the implementation. Generate a
cryptographically high-entropy private topic locally. Do not commit it. Do not place it in logs.
Store it in the approved server secret/environment configuration. No paid provider. No SMS. No
Funnel/public Market Edge exposure.
7C. Wire the existing sink through the existing notification dispatch layer. Notification
failure must NEVER change a trading/shadow result, fail the collector, change a risk decision,
retry forever. Preserve bounded retry, expiration, dedupe, rate limiting, CRITICAL behavior. Add
tests.
7D. Send ONE non-sensitive test event. Record only that the provider accepted/submitted it. Do
not claim phone delivery unless there is direct evidence. Then give the owner the exact
topic/subscription instructions needed in the mobile ntfy app.

PHASE 8 — LONGITUDINAL LEARNING HISTORY
Reconcile issue #50 (merge PR #51 when correct and green). Every future research-ready domain
should preserve enough prospective point-in-time evidence to later evaluate predictions,
uncertainty, prices, depth, fees, decisions, rejected decisions, risk vetoes, stale/missing
inputs, fills/no-fills, settlement, later price movement, source reliability, model version,
policy version. Rejected opportunities are first-class data. Do not create a second AI-memory
database; reuse provenance/snapshots, experiments, opportunity evaluations, shadow ledger,
settlement identity.

F09 CADENCE DECISION
Use MANUAL F09 checkpoints: approximately weekly; additionally after a materially important
ledger event (first settlement; settlement conflict; significant ledger migration; major
risk-policy/schema migration; before/after a recovery operation affecting ledger durability).
Do NOT create a scheduled F09 timer in this mission. Document this cadence.

ROOT SSH DECISION
Do not harden root SSH during this mission. Record it as a separate future security task. Do not
alter keys, sshd config, sudo, root login.

DOMAIN EXPANSION AFTER THIS CHUNK
After the above is clean, update the roadmap so the likely future sequence is:
1. Weather continues accumulating Stage B. 2. Sports prospective data collection. 3. Sports
baseline/preregistered models. 4. Economics/macro. 5. Crypto. 6. Energy/commodities.
7. Business/technology. 8. Culture/entertainment. 9. Politics/government. 10. Long-tail
discovery.
Add/reuse a Domain Readiness concept evaluating settlement clarity; point-in-time public data;
quantifiability; event frequency; liquidity; fees; 7-day capital horizon; model independence;
data latency; venue coverage; historical evidence; rule ambiguity. Do not implement a decorative
numerical "score" without validated weights. A readiness matrix/state is enough initially.

PARALLELISM
Brisket repair is P0 and finishes first. Then bounded lanes: A stake sizing; B comparator +
Polymarket rules/fees; C Odds API activation preparation; D ntfy activation. One writer per shared
primitive. No competing sizing engines, fee models, venue comparators or notification systems.

TESTING / REVIEW
For every code PR: reconcile with latest main; targeted tests; full relevant suite;
frozen-artifact checks; security/invariant tests; independent review; fix blockers; re-review
consequential fixes; exact-head CI green; mergeable; squash merge under existing owner authority
where permitted. No network calls in CI. No test result claims without execution. No production
claim without direct verification.

DEPLOYMENT RULES
MARKET EDGE: use `docs/deploy/DAILY_SHADOW_ACTIVATION.md`. Never deploy unmerged code. No-touch
17:40–18:50 America/New_York; avoid active settlement jobs. Before every deployment: verify
collector health; verified backup; confirm no edgelab capture job running. After: exact SHA;
fail-closed test; timers; dashboard; source health; Brisket health; resource health.

DO NOT DISTURB EXP-001
Frozen research account unchanged; no model retuning from the first shadow days; no sizing-rule
change to frozen research; no historical rewrite; no changing test criteria; no "we saw two
winners so increase size." One valid day is pipeline evidence only.
```

The Brisket-only sections of the directive (PHASE 1 A–H) are recorded in the Brisket repository's
owner intake (`docs/OWNER_REQUESTED_TODO.md`, "Added 2026-09-24"). This repository keeps only
the parts above.
