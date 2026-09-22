# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-22, branch `claude/market-edge-agent-os-ghmeha` (foundation PR)._

```
STATUS: PARTIAL. The foundation is implemented and tested locally; it is not merged.
ACCEPTANCE:
  - A model-neutral instruction system: canonical AI_INSTRUCTIONS.md plus thin adapters,
    structure-tested
  - Existing collectors keep working and gain provenance, source health, freshness and
    immutable evidence
  - An experiment registry with a validated EXP-001 spec
  - Deterministic invariant tests (no execution paths, no secrets, fail-closed freshness,
    immutability, missing is not zero, instruction parity, valid experiments)
  - A news/web ingestion design and the Brisket reuse audit
EVIDENCE:
  - python -m pytest: all tests pass locally on Python 3.11
  - Live read-only collection on 2026-09-22 (sandbox, scratch DB): Kalshi 12 markets,
    2 events, 12 order books; NWS 4 payloads. A rerun appended rows (36 total). An UPDATE
    was blocked by the trigger. `edge-lab health` reported all kinds fresh.
  - CI: see the PR checks. It is not claimed here until the run is green.
UNRESOLVED:
  - KXHIGHNY settlement source. The captured live rules name The Weather Company
    (weather.com/kalshi, station CLINYC), not the NWS CLI report that web sources describe.
    Gate 2 is blocked on resolving this (EXP-001 README).
  - The collector only fetches the first page of /markets. A cursor is flagged as a
    `partial` anomaly but not followed.
  - No scheduled or recurring collection exists, so the dataset is only as large as
    manual runs make it.
BLOCKERS: NONE for engineering. Merging the PR needs owner review.
NEXT ACTION: Gate 2 PR:
  (1) capture Kalshi contract PDFs (GLOBALTEMPERATURE.pdf) and rules as versioned evidence;
  (2) add an NWS CLI collector (api.weather.gov/products/types/CLI/locations/NYC);
  (3) review weather.com terms before any automated access;
  (4) collect settled-market `result` and `settlement_value` fields to reproduce 30+
      settlements.
```

## Open questions for the owner

1. Should a free scheduled collector (e.g. a GitHub Actions cron writing to an artifact) be
   set up to build history? It costs nothing on public-repo minutes, but it is unattended
   infrastructure, so it needs a yes or no.
2. May agents merge PRs that only touch docs or tests once CI is green, or does every merge
   need you?
