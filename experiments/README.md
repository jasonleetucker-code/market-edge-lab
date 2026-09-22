# Experiment Registry

Every experiment we run, including the failures, lives here as
`EXP-NNN-slug/experiment.toml` (machine-readable) plus `README.md` (human log). Validate
with:

```bash
edge-lab experiments validate          # also runs in CI via tests/invariants/
```

## Lifecycle

```
DRAFT → PREREGISTERED → RUNNING → CONCLUDED_PASS | CONCLUDED_FAIL | CONCLUDED_INCONCLUSIVE
   └──────────────┴────────────┴──→ ABANDONED (with the reason, kept forever)
```

- **DRAFT:** anything may change. Periods can be `"TBD"`.
- **PREREGISTERED:** the hypothesis, decision rule, periods, cost/execution assumptions and
  success/failure criteria are **locked** before any test-period data is examined. From
  this point on, the validator rejects any `TBD` value in the decision time, model, periods,
  costs or execution.
- **Changing a locked field:** do not edit the original text. Append an `[[amendments]]`
  entry (`date`, `change`, `reason`). An amendment made after seeing results must say so,
  and it weakens the result.
- **CONCLUDED_*:** needs a `[result]` table with `code_commit`, `dataset_version`, `report`
  (a path that exists) and `summary`. A failed experiment is a valid, valuable outcome.
- **ABANDONED:** give the reason in the README. Never delete the directory.

## What the validator does *not* guarantee

The validator checks that a locked manifest is **fully specified**. It does **not** prove that
the preregistered hypothesis or criteria were never edited afterwards. Today, protection
against a silent edit comes only from git history and review, which give traceability but
not enforcement. **Before any experiment (starting with EXP-001) moves from DRAFT to
PREREGISTERED**, we must implement a deterministic preregistration baseline: for example, a
SHA-256 of the locked fields recorded at preregistration and re-checked by the validator,
with amendments as the only permitted change path. This is tracked in
`docs/EXECUTION_PLAN.md`.

## Required fields

`id, title, status, owner, created, hypothesis, economic_rationale, market, decision_time,
model, data_sources[], features[], success_criteria[], failure_criteria[],
risk_constraints[], limitations[], gates_required[]`, the tables
`[periods] (train/validation/test)`, `[costs]`, `[execution]` and `[artifacts]`, and an
optional `[[amendments]]`. `edge_lab/experiments.py` is the source of truth.

Research rules that every experiment follows: `docs/RESEARCH_PRINCIPLES.md`.
