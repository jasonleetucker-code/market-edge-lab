# 0006 — Defer behavioral agent evals; enforce repository invariants instead

Status: Accepted (2026-09-22)

**Problem.** We want regressions against agents making dangerous claims: stale data called
live, missing data treated as zero, trading during research, invented fees, revised data in
backtests, "backtest = edge", exposed secrets, and so on.

**Alternatives.** (a) Copy Brisket's `agent-evals/`: JSON cases plus a deterministic grader of
*self-reported* run artifacts, run manually and not in CI. (b) Model-graded evals.
(c) Deterministic tests of the *repository's* invariants, so that code which would enable
the bad behaviour cannot merge.

**Decision.** (c) now, in `tests/invariants/`:
- no order or authenticated code paths; HTTP is GET-only;
- no secrets in tracked files;
- freshness fails closed;
- snapshots are immutable;
- missing values are not zero;
- the instruction adapters are structurally sound;
- experiment manifests are valid.

(a) is deferred. Brisket's own README concedes it grades *declared* state, not ground truth,
and at our size the cost of maintaining it outweighs the signal.

**Reconsider when** several agent providers are active at once and we see a repeated
behavioural failure, or before gate 8 (paper/shadow). At that point, start with around five
cases drawn from real incidents, using Brisket's case schema.
