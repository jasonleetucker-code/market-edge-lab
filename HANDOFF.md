# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-22, by PR #2 (foundation). This file reaches `main` only through
that PR's squash merge._

```
STATUS: DONE for PR #2's scope (gate 1 foundation). Gate 2 has not started.
ACCEPTANCE:
  - A model-neutral instruction system: canonical AI_INSTRUCTIONS.md plus thin adapters,
    structure-tested
  - Existing collectors keep working and gain provenance, source health, freshness and
    immutable evidence
  - An experiment registry with a validated EXP-001 DRAFT spec
  - Deterministic invariant tests (no execution/auth paths, no secrets, fail-closed
    freshness, immutability, missing is not zero, instruction parity, valid experiments)
  - A news/web ingestion design and the Brisket reuse audit
EVIDENCE:
  - python -m pytest: 100 passed locally on Python 3.11.15 (system) and on Python 3.12.3
    (a scratch venv; the system python3.12 has no pytest installed)
  - GitHub Actions `tests` workflow: pytest (3.11) and pytest (3.12) both succeeded on earlier
    PR heads 9169182 (run 35765195459) and fb684af. This file cannot record the CI result of
    its own commit. The merge policy for PR #2 required both jobs green on the final head;
    that SHA and run are recorded in the PR #2 description.
  - Two independent read-only reviews:
    - The first found 2 major issues (INSERT OR REPLACE bypassed immutability; the validator
      accepted TBD fields once locked) and 4 minor ones.
    - The second (pre-merge) found 2 major issues (`edge-lab health` exited 0 after a failed
      run; the locked-experiment check missed placeholder variants such as TODO, empty and
      nested values) and several minor ones (source_health and collection_runs history was
      mutable; skipped market entries were silent; credential headers were not refused;
      news-API prices were unmarked).
    - Every finding is fixed with a regression test.
  - Live read-only collection on 2026-09-22 (sandbox, scratch DB): Kalshi 12 markets,
    2 events, 12 order books; NWS 4 payloads. Two runs on a fresh schema-v2 DB gave 40 rows,
    every source_health row was ok, and `edge-lab health` reported every kind fresh (exit 0).
    UPDATE and INSERT OR REPLACE on snapshots were blocked.
UNRESOLVED:
  - KXHIGHNY settlement source. The contract-specific evidence captured 2026-09-22
    (series.settlement_sources, markets[].rules_primary) names The Weather Company
    (weather.com/kalshi, station CLINYC). Generic Kalshi and web descriptions mention the
    NWS Daily Climate Report. These are not necessarily equivalent. The primary evidence
    wins, and the discrepancy blocks modeling until gate 2 resolves it (EXP-001 README).
  - Preregistration immutability. The validator rejects recognizable placeholders in locked
    experiments (a heuristic), but it does not prove preregistered text was never edited; git history
    gives traceability only. A deterministic preregistration baseline (e.g. a hash of the
    locked fields) must exist before any experiment leaves DRAFT (docs/EXECUTION_PLAN.md).
  - The collector only fetches the first page of /markets. A cursor is flagged as a
    `partial` anomaly but not followed.
  - Kalshi throttling: live runs needed 1 to 3 retries across 16 requests (recorded in
    source_health.retries). Pace requests before any scheduled collection.
  - No scheduled collection exists, so the dataset is only as large as manual runs make it.
BLOCKERS: NONE. The owner granted merge authority for PR #2 on 2026-09-22.
NEXT ACTION: Gate 2 settlement validation (not modeling):
  (1) capture the Kalshi contract PDFs (GLOBALTEMPERATURE.pdf) and the rules as versioned
      evidence;
  (2) collect settled-market `result` and `settlement_value` fields;
  (3) review weather.com terms before any automated access;
  (4) add an NWS CLI collector as a comparison source;
  (5) reproduce 30+ settlements with zero unexplained mismatches.
```

## Open questions for the owner

1. **Scheduled collection.** Should a low-frequency collector be set up to build history
   (e.g. a GitHub Actions cron)? This repository is private, so Actions minutes come out of
   the account's included allowance and may become billable depending on plan and settings.
   Unattended infrastructure is not free. Approval needs a runtime/minutes estimate and cost
   controls (`docs/EXECUTION_PLAN.md` → Cost policy).
2. **Standing merge rule.** May agents merge docs- or test-only PRs once CI is green, or does
   every merge need an explicit owner grant like the one given for PR #2?
