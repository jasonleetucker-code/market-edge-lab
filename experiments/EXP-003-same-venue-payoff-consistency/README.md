# EXP-003 — Family B: same-venue payoff consistency (DRAFT)

**Status: DRAFT.** Not preregistered, not frozen, not running. A conditional full-fill surplus is
not captured arbitrage. No fills exist in this experiment.

- **Authority:** owner directive 2026-09-25 (`docs/owner/2026-09-25-economic-evidence-v1-directive.md`,
  `docs/EXECUTION_PLAN.md`), issue #96.
- **Family slot:** B (ACTIVE).
- **Spec:** `experiment.toml` and `protocol.toml` (research-protocol sidecar). Unknown values are
  explicit on purpose.
- **ID allocation:** the next free ID after EXP-002 in the registry on main `b19d28a`.
- **Isolation from EXP-001:** this family reads market-side books, rules and fee records only.
  EXP-001 forecasts, outcomes, labels and the shadow ledger are `prohibited_inputs`.
  `edge_lab.research_evidence.record_use` refuses to log access to them for this experiment.
  EXP-001 is not changed in any way.
- **Evidence-use log:** `evidence_use.jsonl` (append-only). Any access before the log existed is
  UNKNOWN.

## What must be settled before PREREGISTERED

1. The primary endpoint and the allowlist of relationship sets.
2. The maximum leg book age, the leg-to-leg skew and the untouched future window (by event-day
   window as well as by dataset hash).
3. Episode start threshold, end/merge gap and minimum size.
4. The size ladder, the multiple-testing plan and the futility rule.
5. The minimum useful economic effect (**owner input**).

## Log

- 2026-09-25: DRAFT registered (EE v1 PR A). No data viewed for this experiment. The evaluator
  and the run over stored KXHIGHNY books follow in PR B.
