# ADR 0034: Research-protocol sidecar, evidence consumption, attrition and the economic screen

**Status:** Accepted 2026-09-25 (EE v1 PR A). Authority: `docs/owner/2026-09-25-economic-evidence-v1-directive.md`
and the matching `docs/EXECUTION_PLAN.md` entry; strategy #96 (`docs/strategy/`). Research contracts only:
no order, credential, paid call, timer or network request. EXP-001 is unchanged.

## Problem

#96 limits new research to two families. Before any model work, those families must answer four
questions:
1. What exactly is the protocol, including what is still unknown?
2. Which evidence has already been looked at?
3. What fell out of the sample, and why?
4. Is the idea worth money at a fillable size, with finite capital?

The registry (`experiments.py`, ADR 0004/0009) validated and froze manifests. It had no place for
family slots, clustering, budgets, futility, a minimum useful effect or an episode definition, and
EXP-001's frozen manifest must not change shape. Nothing recorded evidence consumption, attrition
denominators or episode-level, capital-constrained economics. Snapshot-count annualization and
bankroll × size products were the named failure modes (strategy §6).

## Decision

1. **A sidecar, not a schema change.** New experiments (created from 2026-09-25) carry
   `protocol.toml`; older ones are read as LEGACY by an explicit reader (`protocol_state`).
   - DRAFT requires every field present and allows explicit `UNKNOWN` / `MISSING_*` values.
   - PREREGISTERED rejects them outside `[knowledge]`.
   - The freeze adds `protocol` and `protocol_sha256` keys only when a sidecar exists, so
     EXP-001's baseline bytes and hash are untouched.
   - `validate_all` enforces at most two ACTIVE families; an extra family needs an owner-exception
     document.
2. **Evidence consumption lives in the registry directory**, as `evidence_use.jsonl`
   (`research_evidence.py`).
   - Append-only: `check-frozen` in CI compares the file with its base.
   - Event ids are content hashes, so only identical events deduplicate.
   - A holdout is matched by its outcome window (scope plus interval) or by its hash, across every
     experiment's log.
   - Access before the log started is `UNKNOWN_LEGACY`; unknown booleans count as viewed.
   - Protocol `prohibited_inputs` are refused at record time.
   - The out-of-band limitation is carried in every status.
3. **Attrition is a pure report over units the caller enumerates** from existing stores.
   - Each level (event, market, horizon, snapshot, opportunity) has its own waterfall.
   - Every raw reason is kept, and one primary reason per unit (a fixed order) makes the waterfall
     reconcile.
   - A premature miss is corrected to PENDING_TARGET.
   - A level that was not enumerated, and a NOT_APPLICABLE stage, report None, never 0.
4. **Economics is episode-based and capital-constrained** (`research_economics.py`).
   - Size-ladder rungs come from the canonical depth walk and fee schedule, with fees once, inside
     the net edge.
   - Episodes form under a frozen definition.
   - Chronological replay uses finite per-venue capital, a reserve and settlement release. One
     pool serves every strategy passed together, and an open position's liquidity pool is not
     taken twice.
   - The replay reports conservative (detection) and less-conservative (best single observation)
     fills.
   - The capacity ladder reports marginal contribution and marginal capital, and flags idle
     capital.
   - The screen keeps variable economics, fixed cash costs and owner hours separate. The annual
     figure is a scenario, produced only when the protocol's minimum episode count is met.
   - A cluster bootstrap gives the uncertainty band.
   - The verdict is INSUFFICIENT_EVIDENCE, ECONOMICALLY_UNVIABLE, BELOW_MINIMUM_USEFUL or CONTINUE.
   - Every input is labelled OBSERVED / ESTIMATED / OWNER_INPUT / UNKNOWN. Amounts are
     `ILLUSTRATIVE_SCENARIO_NOT_APPROVED_BANKROLL`.

## Alternatives considered

- **New fields in `experiment.toml`, added to `FROZEN_FIELDS`.** Rejected: it would change
  EXP-001's frozen view and hash, or need a per-experiment exception. The sidecar is additive.
- **A SQLite table for evidence use.** Rejected for now. The log belongs with the experiment it
  governs, must be reviewable in PRs, and is protected by the same CI base comparison as
  baselines. The evidence store stays about market data.
- **Annualizing from snapshot counts, or multiplying capital × size × turnover.** Rejected: these
  are the named failure modes.
- **A general optimizer or ML capacity model.** Rejected as premature (#96).

## Tradeoffs

- Placeholder detection is a heuristic, as it is for manifests. A concrete-looking but inadequate
  value is a review question.
- The evidence log proves declared access only. Anyone with git and CI control could rewrite it;
  that stays governance (history rewrites need owner approval).
- One entry per liquidity pool until release is conservative. It can understate a strategy that
  would legitimately re-enter fresh liquidity in the same contract.
- A capital-limited smaller fill keeps the deeper rung's per-unit edge, which understates rather
  than overstates.
- The annual scenario scales the window linearly under a stated stationarity assumption. It ignores
  seasonality unless the window covers it.

## What would make us reconsider

- A third family approved by the owner with an exception, or a need for per-family slot
  accounting finer than ACTIVE/QUEUED/ENDED.
- Evidence logs that grow too large for git review. Then move them to an append-only store with
  the same content-hash ids and export them for review.
- Real fills (Gate 9+). `EdgeKind.REALIZED` exists for that, but no realized result exists today.
