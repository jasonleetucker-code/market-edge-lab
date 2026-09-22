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

**Tradeoffs.** Locking is checked structurally, not cryptographically. An agent could still
edit a preregistered hypothesis. Review and git history are the backstop.

**Reconsider if** we need cross-experiment queries (then add an index or DB), or if edits to
preregistered text actually happen (then record a spec hash at preregistration).
