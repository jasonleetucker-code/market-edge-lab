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

## Research-protocol sidecar (every experiment except EXP-001)

Owner directive #96 and Economic Evidence v1 (`docs/owner/2026-09-25-economic-evidence-v1-directive.md`)
need research-governance fields that the manifest schema above never had. They live in a
**sidecar**, `EXP-NNN-slug/protocol.toml` (`protocol_version = "research-protocol-v1"`), beside
the unchanged manifest.

- **Who needs one.** Every experiment except those in the explicit allowlist
  `experiments.LEGACY_EXPERIMENTS`, which holds only EXP-001, the experiment that predates the
  sidecar. A backdated `created` date does not exempt a manifest. EXP-001 is read as **LEGACY**
  (`experiments.protocol_state`): every protocol field is UNKNOWN for it, and nothing is
  inferred. **EXP-001's manifest, baseline, hashes and validation are byte-for-byte unchanged.**
  `created` dates are UTC.
- **What it holds.** The top-level keys and tables in `experiments.PROTOCOL_TOP` and
  `PROTOCOL_TABLES`:
  - the family slot (`family`, `slot_status` ACTIVE/QUEUED/ENDED, optional `owner_exception`);
  - mechanism and named hypothesis;
  - `[universe]` and `[observation]` (unit, clusters, dependence);
  - `[endpoints]` (one primary);
  - `[information]` (cutoff, max input age, clock uncertainty);
  - `[data_roles]`, including `prohibited_inputs`;
  - `[variants]` (with the multiple-testing plan);
  - `[costs_fills]` and `[size_capital]`;
  - `[evaluation]` (chronological, untouched future window, exposure history, controls);
  - `[budget]` (research cash, owner hours, data costs, review date);
  - `[stopping]` (futility, stop, continue, verdicts);
  - `[economics]` (minimum useful effect, power analysis);
  - `[readiness]` (product vs strategy, permitted uses, blockers);
  - `[episode]` (the frozen episode definition);
  - `[knowledge]`.
- **DRAFT.** Every field must be present. An unknown is written explicitly, as `"UNKNOWN: <why>"`,
  `"MISSING_OWNER_INPUT: <what>"` or `"MISSING_POWER_ANALYSIS: <what>"`. Never invent a
  threshold, sample size, source independence or annual opportunity count to fill a field.
- **PREREGISTERED and later.** Every decision field must be settled. Outside `[knowledge]`, the
  validator rejects the tokens UNKNOWN, UNVERIFIED, TBD and MISSING_* anywhere in a value, a value
  that starts with "unknown" or "missing", and deferral phrases such as "to be frozen" or "will
  be decided". This is a heuristic, like the manifest check: a concrete-looking but inadequate
  value is still a review question. `[knowledge]` holds facts that may honestly stay unknown,
  such as source independence, annual episode count and fill probability.
- **Freeze.** `edge-lab experiments freeze` adds `protocol`, `protocol_sha256` and
  `protocol_file` to the new baseline. After that, the validator rejects any change to the
  sidecar. Record changes as `[[amendments]]` with `field = "protocol.<table>.<key>"`. Baselines
  frozen without a sidecar (EXP-001) are not affected.
- **Family slots.** At most `experiments.MAX_ACTIVE_FAMILIES` (2) distinct ACTIVE families among
  experiments that are not concluded or abandoned. Several experiments may share one family (one
  slot). Another family needs `owner_exception = "docs/owner/<decision>.md"`, an existing owner
  decision document under `docs/owner/`.
  Protected EXP-001 does not use a slot.
- **Evidence-use log.** Each new experiment keeps `evidence_use.jsonl`, created with a header by
  `research_evidence.init_log` and appended by `edge-lab experiments record-use`.
  - The header declares `covered_scopes`, the outcome scopes whose research access the log
    records. A scope that no log covers, or that has a known unlogged consumer, is never
    certified untouched. KXHIGHNY is such a scope: EXP-001's pipeline, ledger and Terminal read
    it daily.
  - `[data_roles] prohibited_label_scopes` makes `record-use` refuse any label- or outcome-viewing
    use in those scopes, whatever the dataset is called. That includes tuning or development that
    saw outcome-derived results.
  - `[data_roles] prohibited_fields` names record fields the family's readers must drop. It is
    enforced by the readers that consume the protocol, and is declarative for any reader that does
    not.
  - Scopes, roles and viewed flags are self-declared: a mislabelled scope or flag sidesteps the
    checks. See the limitation in `research_evidence.OUT_OF_BAND_LIMITATION`.
  - `[economics] min_episodes_for_scenario` and `min_independent_clusters` feed the economic
    screen. Callers read them with `research_economics.protocol_minimums(experiment_id)` and never
    pass their own numbers. `economic_screen` always uses the committed protocol's values, and
    says so when a caller's differ. The id is normalized, so case and spaces make no difference.
    An id with no settled values gets UNKNOWN. Only the explicit unit-test ids in
    `research_economics.SCREEN_TEST_EXPERIMENT_IDS` may supply their own. While either is unknown, the screen can only say INSUFFICIENT_EVIDENCE.
- **Open decisions.** An optional top-level `open_decisions` list names choices that are not
  settled yet. A DRAFT may list any; PREREGISTERED and later must have an empty list.
  - The log is append-only: `edge-lab experiments check-frozen` (run in CI) fails if an existing
    line changes or the file is deleted.
  - `edge-lab experiments holdout-status` says whether an outcome window can still support an
    untouched-evaluation claim. See `docs/RESEARCH_PRINCIPLES.md` → Consumed evidence.

Current families (2026-09-25):
- **A:** `EXP-002-nfl-consensus-vs-event-market`;
- **B:** `EXP-003-same-venue-payoff-consistency`.

Both are DRAFT. IDs were allocated from this registry, where only EXP-001 existed.

Research rules that every experiment follows: `docs/RESEARCH_PRINCIPLES.md`.
