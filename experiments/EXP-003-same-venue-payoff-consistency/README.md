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
- 2026-09-25 03:38Z (EE v1 PR B): first development scan
  (`results/payoff_scan_laptop_store_2026-09-22.json`). Two evidence-use events are logged:
  - `eu-92904c0f26bf2ab0ad278b774bbc4ac0`: the 03:38Z look, recorded by hand with `record-use`,
    because the scan did not log itself yet. The entry itself says so.
  - `eu-1252b03466882d648c95b9345eec0ce6`: the re-run that produced the committed report, logged
    by the scan CLI before output. Its event window is 2026-09-22..2026-09-23.

  The re-run followed the #102 review fixes, which added verified enumeration, refund and cost
  checks, and fail-closed logging. It gave the same result.
  - **Input.** The only evidence store in this session: the laptop's
    `data/edge_lab.sqlite3`, read-only. It holds 2 KXHIGHNY events (26SEP22, 26SEP23) with 6
    brackets each, books captured on 2026-09-22 about 22:38Z. The production VPS store, with daily
    decision and recheck books, was **not** read from this session. The same command runs
    read-only there.
  - **Windows.** Quote age 300 s and leg skew 60 s, stated for this run only. The protocol values
    are UNKNOWN.
  - **Result:** 2 sets, both relationship INCOMPLETE. VOID, REFUND and CANCELLATION are not
    excluded by captured evidence.
    - 26SEP23 at size 1: the top-of-book asks sum to 1.06 per basket, an observed inconsistency of
      -0.06 before fees. The worst state is the discretionary fair-price fallback, which pays 0.
      The claim is NO_SURPLUS_EVEN_BEFORE_FEES.
    - 26SEP23 at sizes 10 and 100: NOT_EVALUATED. The walk crosses fractional-size levels, and no
      fractional-fill fee rule is modelled.
    - 26SEP22: NOT_EVALUATED at every size. One bracket (B67.5) had no ask at all.
  - **Reading.** No surplus: a valid, expected result. It is not a verdict on the family (2 event
    days, one capture each).
