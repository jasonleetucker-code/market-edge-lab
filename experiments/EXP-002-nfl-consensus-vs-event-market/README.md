# EXP-002 — Family A: NFL consensus vs executable event-market prices (DRAFT)

**Status: DRAFT.** Not preregistered, not frozen, not running. Nothing here is evidence of an
edge, and no sports model or strategy is operational or authorized.

- **Authority:** owner directive 2026-09-25 (`docs/owner/2026-09-25-economic-evidence-v1-directive.md`,
  `docs/EXECUTION_PLAN.md`), issue #96. Family A is research on stored evidence, not the excluded
  "sports model or sports strategy".
- **Family slot:** A (ACTIVE). At most two new active families exist beside protected EXP-001;
  `edge-lab experiments validate` enforces the limit.
- **Spec:** `experiment.toml` (registry schema) and `protocol.toml` (research-protocol sidecar;
  experiments/README.md). Unknown values are written as `UNKNOWN: …` or `MISSING_OWNER_INPUT: …`
  on purpose. The validator accepts them in DRAFT and refuses them from PREREGISTERED on.
- **ID allocation:** from the registry on main `b19d28a`, where only `EXP-001` exists.
  `docs/owner/2026-09-22-gate4-collection-directive.md` and `scripts/run_exp001_gate4.py` mention
  "EXP-002" only as the name a follow-up model would take after an EXP-001 Stage A **fail**.
  Stage A passed, so that name was never registered. `experiments/sizing_v2/` states that it has
  no ID yet.
- **Evidence-use log:** `evidence_use.jsonl` (append-only; `edge_lab.research_evidence`). It starts
  empty. Any access before the log existed is UNKNOWN.

## What must be settled before PREREGISTERED

1. The single primary endpoint: calibration at a horizon, or markout at a named later horizon.
2. The maximum input age, the pair skew and the untouched future window (by outcome window as
   well as by dataset hash).
3. Episode start threshold, end/merge gap and minimum size, frozen before any outcome is viewed.
4. The size ladder rungs, the multiple-testing plan and the futility rule.
5. The minimum useful economic effect (**owner input**) and a power analysis.

## Current blockers

- Paired Kalshi NFL books are not collected yet. Collection was **APPROVED** by the owner on
  2026-09-25 (`docs/EXECUTION_PLAN.md`, #110; collection only, within
  `docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md` §6). The implementation (#112) is pending deploy.
  The protocol stays DRAFT.
- The payoff-equivalence mapping (ties, overtime, postponement, void and refund, units) is not
  established. The contract states are now verified (`rules_evidence/MANIFEST.md`). The proposed
  treatment is explicit payoff modelling with ex-ante bounds
  (`docs/research/RESEARCH_UNBLOCKING_DECISIONS.md` §A.D), which is not yet settled.

## Log

- 2026-09-25: DRAFT registered (EE v1 PR A). No data viewed for this experiment.
- 2026-09-25 (RU Writer R, research-unblocking directive): protocol recommendation, all
  PROPOSED, in `docs/research/RESEARCH_UNBLOCKING_DECISIONS.md` §A. Nothing is settled or frozen,
  and the experiment stays DRAFT.
  - **Changed in the DRAFT protocol.** `open_decisions` now carries the verified rules facts and
    points to the recommendations, with a new OPEN 6 for the primary endpoint. The `[costs_fills]
    fills` text, the `[stopping]` UNVIABLE wording and `experiment.toml` `[execution] fill_model`
    now use the fill-mode labels v2 (ADR 0037):
    - FIRST_DETECTION_ZERO_LATENCY, which is not delay-adjusted;
    - HINDSIGHT_UPPER_BOUND, an oracle bound that may only rule the family out.

    Neither is executable performance. `[endpoints] primary` and `[economics] power_analysis`
    carry pointers only. No result used the old labels.
  - **Rules evidence.** The Kalshi FOOTBALLGAMEWIN contract terms and CFTC certification were read
    from their public URLs and stored in `rules_evidence/` with hashes. The terms add fair-price
    states the market rules text does not list: suspension before 55 minutes, a forfeit before
    kickoff, a venue or home/away change, and a pre-game disqualification.
  - **Revised after review (same PR):** the primary-endpoint proposal is now a *cross-book*
    markout with a Kalshi-only placebo as a required bias check. The earlier same-book statistic
    was biased upward under a no-information null. The pilot dates follow the owner's collection
    approval (#110).
  - **Data looked at.** None in this experiment's scope. The laptop store was inventoried
    read-only to look for measured Odds/Kalshi timing. It holds no Odds API or KXNFLGAME rows, so
    no `sports:nfl:moneyline` data was viewed and nothing is appended to `evidence_use.jsonl`. The
    inventory itself is logged in EXP-003's log, because the store holds KXHIGHNY rows.

## Owner decisions

- 2026-09-26: owner decisions recorded (`docs/owner/2026-09-26-owner-decisions-economics-backup.md`): minimum useful effect $1,000/year (continuation bar beyond the pilot, not a pilot requirement); 6 owner hours through 2026-10-22; the +8 h extension returns to the owner. Status stays DRAFT.
