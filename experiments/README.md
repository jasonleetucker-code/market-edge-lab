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
  this point on, the validator rejects placeholder or empty values (`TBD`, `TODO`, `pending`,
  `?`, empty strings/tables/lists, including nested ones) in the hypothesis, rationale,
  market, decision time, model, data sources, features, success/failure criteria, periods,
  costs (`fee_model`, `spread`) and execution (`fill_model`, `latency`).
- **Changing a locked field:** do not edit the original text. Append an `[[amendments]]`
  entry (`date`, `change`, `reason`). An amendment made after seeing results must say so,
  and it weakens the result.
- **CONCLUDED_*:** needs a `[result]` table with `code_commit`, `dataset_version`, `report`
  (a path that exists) and `summary`. A failed experiment is a valid, valuable outcome.
- **ABANDONED:** give the reason in the README. Never delete the directory.

## Preregistration freeze

To preregister:

1. Set `status = "PREREGISTERED"`.
2. Run `edge-lab experiments freeze EXP-NNN`. This writes `preregistration.json` with a
   SHA-256 over the locked fields (hypothesis, rationale, market, decision time, model,
   data sources, features, success/failure criteria, risk constraints, periods, costs,
   execution) and a copy of them.
3. Commit both files together.

From then on:

- the validator rejects a locked manifest whose locked fields differ from the baseline, and
  rejects a baseline that no longer matches its own hash;
- CI (`edge-lab experiments check-frozen`) fails if a committed `preregistration.json` is
  modified or deleted;
- changes are recorded only as `[[amendments]]` (`date`, `change`, `reason`, and optionally
  `field` + `value`). The original text stays recoverable in both files.

This detects silent mutation through the normal PR/CI path. It cannot stop someone who
rewrites git history or disables CI, which remains a governance matter
(`AI_INSTRUCTIONS.md`: history rewrites need owner approval).

The placeholder check (`TBD`, `TODO`, `pending`, `?`, empty values) is a heuristic. It
cannot judge whether concrete-looking text is an adequate specification; that is a
review question.

## Required fields

`id, title, status, owner, created, hypothesis, economic_rationale, market, decision_time,
model, data_sources[], features[], success_criteria[], failure_criteria[],
risk_constraints[], limitations[], gates_required[]`, the tables
`[periods] (train/validation/test)`, `[costs]`, `[execution]` and `[artifacts]`, and an
optional `[[amendments]]`. `edge_lab/experiments.py` is the source of truth.

Research rules that every experiment follows: `docs/RESEARCH_PRINCIPLES.md`.
