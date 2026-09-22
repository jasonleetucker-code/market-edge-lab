# 0009 — Preregistration freeze: hashed baseline + CI immutability check

Status: Accepted (2026-09-22)

**Problem.** The validator could reject placeholders in a locked experiment, but it could not
detect a silent edit to a preregistered hypothesis or criterion.

**Alternatives.**
(a) Rely on review and git history.
(b) Sign or timestamp the manifest with an external service.
(c) A one-time baseline file with a hash of the locked fields, a validator comparison,
    and a CI check that baseline files are never modified or deleted.

**Decision.** (c).
- `edge-lab experiments freeze EXP-NNN` writes `preregistration.json` (locked fields plus
  their SHA-256). It refuses to overwrite a baseline or to freeze a non-PREREGISTERED or
  under-specified manifest.
- The validator requires the baseline for every locked status, checks its self-hash, and
  compares it with the current manifest.
- CI runs `edge-lab experiments check-frozen` against the PR base, or against the previous
  commit on pushes to `main`, and fails on any modified or deleted baseline.
- Changes go through `[[amendments]]` only.

**Tradeoffs.** Someone who rewrites git history, force-pushes or disables CI can still get
around it. Those actions are owner-approval matters under `AI_INSTRUCTIONS.md`, and the
check makes the ordinary path safe rather than making the system tamper-proof.

**Reconsider if** experiments are ever run outside this repository's PR flow, or if an
external timestamp becomes necessary for third-party credibility.
