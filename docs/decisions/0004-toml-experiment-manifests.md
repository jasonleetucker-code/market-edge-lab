# 0004 — Experiments are TOML manifests validated in CI

Status: Accepted (2026-09-22)

**Problem.** Without a durable, structured record, results become notebook folklore and
failed experiments disappear (survivorship bias).

**Alternatives.** (a) Markdown only. (b) YAML + JSON Schema (adds PyYAML/jsonschema).
(c) TOML, read with stdlib `tomllib`, plus a small Python validator.

**Decision.** (c). Each experiment lives in `experiments/EXP-NNN-slug/experiment.toml`, plus
a human-readable `README.md`. The validator (`edge_lab.experiments`) enforces required
fields, the lifecycle, locked periods once preregistered, amendment structure, and that
concluded results carry the code commit, dataset version and report. It runs in CI through
`tests/invariants/test_experiments_valid.py`.

**Tradeoffs.** The validator checks that locked manifests contain no recognizable
placeholders (`TBD`, `TODO`, `pending`, `?`, empty values, including nested ones). That is a
heuristic, not a proof that the specification is adequate. It does **not** freeze them. An agent could still edit a preregistered
hypothesis or criterion, and only review and git history would show it. That is
traceability, not enforcement.

**Required follow-up.** Before any experiment moves DRAFT → PREREGISTERED, add a
deterministic preregistration baseline. For example: store a SHA-256 over the locked fields
at preregistration, have the validator recompute and compare it, and route every later
change through `[[amendments]]`.

**Reconsider if** we need cross-experiment queries (then add an index or DB).
