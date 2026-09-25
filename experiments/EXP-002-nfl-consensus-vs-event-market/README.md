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

- Paired Kalshi NFL books are not collected. The first output is PR C's data-gap report and
  bounded capture plan. Activating a new collector needs explicit EXECUTION_PLAN authority and
  the owner's approval.
- The payoff-equivalence mapping (ties, overtime, postponement, void and refund, units) is not
  established.

## Log

- 2026-09-25: DRAFT registered (EE v1 PR A). No data viewed for this experiment.
