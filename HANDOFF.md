# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-25 ~04:15 America/New_York (VPS clock) by the laptop Claude coordinator
session. It covered the owner's Economic Evidence v1 directive (docs/owner/2026-09-25-economic-
evidence-v1-directive.md; strategy reset #96)._

```
STATUS: DONE for the build scope. Every Economic Evidence v1 PR is merged, DEPLOYED and
  PRODUCTION_VERIFIED (production efe86e3). Pending, time-based:
  - the first real settlement (2026-09-25 11:15 ET, or 16:15) and the manual F09 checkpoint;
  - the first Polymarket US research capture (2026-09-26 16:53Z).
  No edge is claimed. Both new research families are DRAFT and cannot be preregistered without
  owner inputs (BLOCKERS 1).
ACCEPTANCE: the Economic Evidence v1 directive, sections 6-20: W0 operating verification; PR A
  (protocols, evidence consumption, attrition, economic screen, #96 canonical integration); PR B
  (semantic conformance, pure same-venue payoff evaluator, execution-package design); PR C (NFL
  paired evidence, gaps, capacity, Terminal); review, tests and exact-head CI before merge;
  deploy only reviewed merged code. Not authorized and not done: orders of any kind, credentials,
  paid data, new timers, backup deletion, public exposure, any gate advance.
EVIDENCE:
  - W0 (PRODUCTION_VERIFIED 2026-09-25 02:13Z, before any EV1 change):
    - f5bfa6e deployed; evidence DB schema v7, WAL, quick_check ok; ledger v1 ok; 13 timers;
      no failed units.
    - #95 WAL fix proven on a DISPOSABLE clone forced into WAL: the pre-#95 sandbox fails "unable
      to open database file"; the #95 sandbox opens and creates -wal/-shm; a write to the pinned
      DB file is refused; clone sha unchanged. Production was never write-probed.
    - Quota visibility after atomic replacement: the dashboard showed the ledger's 9 used /
      491 remaining without a restart.
    - Backups 23 MB total (36 evidence, 33 ledger bundles). Restore verified: evidence schema 7
      in 0.63 s; ledger 60 entries in 0.25 s. Anchor verify vs 2026-09-23T224720Z EXTENDED
      (history intact, 15 entries appended per account).
  - MERGED, each with an independent review and re-reviews until READY, exact-head CI green on
    3.11/3.12 and reconciled with main (merge helper with --match-head-commit):
    - #97 (db44858) reconciliation; #98 (b19d28a) #96 strategy docs with the corrected Family B
      surplus formula and post-audit corrections; #99 (d4498fc) EV1 claims.
    - #100 (b654b13) PR A: directive record; OWNER_IDEAS/EXECUTION_PLAN/RESEARCH_PRINCIPLES/
      experiments README/DATA_PROVENANCE §6d/ADR 0034; HANDOFF Gate 7 = 2 valid days; DRAFT
      EXP-002 (Family A) and EXP-003 (Family B); research_evidence (append-only evidence-use log,
      holdout by window + hash, reconciling attrition waterfalls); research_economics (episodes,
      replay, size ladder, cluster-bootstrap economic screen; minimums only from the protocol,
      unknown -> INSUFFICIENT_EVIDENCE). 4 review rounds.
    - #101 (f8adf4f) PR C: sports_evidence (read-only, network-free, bounded); gaps G1-G8;
      Terminal "Economic evidence · A"; outcome labels hidden unless a logged --with-results run.
    - #102 (5e8b07f) PR B: ContractSemantics/RelationTier incl. CONDITIONAL_EQUIVALENT (additive,
      legacy = UNKNOWN); dated venue facts DOCUMENTED_UNVERIFIED_BYTES (no endpoint called);
      KXNFLGAME fees UNSUPPORTED (sources conflict); payoff_constraints with the corrected formula;
      research payoff-scan CLI; ADR 0035 (execution package, design only, no transport) and
      ADR 0036. 4 review rounds; the last blocker made integer settlement an OBSERVED premise
      (39/39 TWC-era values), so no KXHIGHNY set can be PROVEN.
    - #103 (f5dec06) first production payoff scan; test_agent_context ignores .git lock files.
    - #105 (9f9bce8) one set per capture round; every anchor and event accounted for; the dataset
      hash covers every snapshot read in the window; legacy files are labelled.
    - #104 (efe86e3) Terminal Section B from the verified EXP-003 result file (verify_result_file +
      verify_result_provenance against the repository log); sports_evidence on the store's public
      metadata API.
  - DEPLOYED via DAILY_SHADOW_ACTIVATION.md with /root/deploy.sh (preflight PASS required),
    verified backups before and after, fail-closed PASS (held, not pushed), no failed units,
    13 timers:
    - f8adf4f at 05:04Z (01:04 ET): #100, #101;
    - 5e8b07f at 06:19Z (02:19 ET): #102;
    - efe86e3 at 08:02Z (04:02 ET): #103, #105, #104.
    - Each: verify_production.sh -> DEPLOYED_SHA matches; COLLECTOR_HEALTH VALID (valid_days 2);
      FRESHNESS CURRENT, 0 disagreements; both restores VERIFIED (ledger 60 entries); Chase
      Upside HEALTHY; 63 GB free.
  - Close capture 2026-09-25: 24 rows CAPTURED (12 pre_close, 12 close), 8 requests, no
    failures; freshness 0 unreadable.
  - Family A coverage on production (read-only report, as of 2026-09-25 05:05Z): 32 events,
    95 horizons, 190 opportunities; 93 horizons not yet due, 2 due; 0 paired: no KXNFLGAME
    listing or book is stored (G1). Waterfalls reconcile (EVENT, HORIZON, OPPORTUNITY);
    MARKET/SNAPSHOT are not enumerated (None, never 0). Screen: INSUFFICIENT_EVIDENCE.
  - Family B on production (backup edge-backup-5q41yg5u, sha 5ad68c03…552a = manifest, read
    locally): 2 events, 8 valid capture rounds, 24 size rows: 13 NO_SURPLUS_EVEN_BEFORE_FEES
    (asks sum 1.06-1.09 per $1 basket; worst state the fair-price fallback, pays 0), 11
    NOT_EVALUATED (fractional depth with no fee rule; a bracket with no ask). Every set is
    INCOMPLETE (VOID/REFUND/CANCELLATION not excluded; integer settlement only observed).
    No positive claim. Evidence-use: every look is in EXP-003's log, including two reviewer
    re-runs recorded by hand with upper-bound times.
  - Terminal on production (efe86e3): Section A "No paired evidence yet"; Section B shows the
    production result, "Production store", both legacy notes, Settlement costs Unknown, Positive
    claims 0; no absolute path on the page.
UNRESOLVED:
  - The first real settlement (11:15 ET, or 16:15): verify event, outcome, source, payout, fees,
    P&L, cash release, equity for both accounts, duplicates and the hash chain; then the manual
    F09 checkpoint.
  - The first Polymarket US research capture (T-24h, 2026-09-26 16:53Z): verify per runbook §5e.
  - Family A has no paired evidence until Kalshi KXNFLGAME listings and books are captured (G1);
    that needs an owner approval (BLOCKERS 2). About 15 regular-season weeks remain.
  - Unverified venue facts: Kalshi settlement/transfer fees; a fee rule for fractional fills;
    what a NO position receives under the fair-price fallback; KXNFLGAME fee semantics; TWC
    settlement precision; Novig production public book.
  - Section B shows stale after 2026-10-03 unless a newer EXP-003 result is recorded.
  - Backup growth is quadratic (full daily copies, never deleted); ntfy subscription mismatch;
    close_tick_alignment after the 2026-11-01 DST change; fee re-checks (Kalshi by
    2026-10-23T13:39:48Z, Polymarket US by 2026-10-24T01:39Z).
  - Brisket PRs #1406/#1407 have merge conflicts; outside this repository and mission.
BLOCKERS (owner-only):
  1. EXP-002 and EXP-003 inputs: minimum useful annual effect and owner-hour budget per family;
     cluster and episode minimums; EXP-002 tie/not-played treatment, pair skew, size ladder and
     episode definition.
  2. Kalshi NFL capture re-scope of edgelab-observe (about 144 GETs a week, worst 288; no new
     timer): approve or decline in docs/EXECUTION_PLAN.md with a review date.
  3. The backup retention/deletion policy.
  4. The ntfy phone subscription.
NEXT ACTION: after the 2026-09-25 11:15 ET settlement run, verify the first real settlement and
  take the manual F09 checkpoint. Then the owner sets BLOCKERS 1-2 so the families can be
  preregistered and Family A can collect paired evidence.
```

## Daily operation (what runs by itself)

| ET time | Unit | Does |
|---|---|---|
| 17:45 | edgelab-pfm | captures the NWS PFM forecast |
| 17:55:05 | edgelab-decision | captures the event, markets and order books in the decision window |
| 18:05 | edgelab-recheck | captures the confirmation books |
| 18:30 | edgelab-status | writes `latest.json` (VALID/INVALID with reasons) |
| 18:40 | edgelab-shadow | bookkeeping from stored evidence; writes `shadow_daily.json` |
| 11:15, 16:15 | edgelab-settlement | a bounded settlement refresh once positions are due, then bookkeeping |
| 04:40 UTC | edgelab-backup | verified backups of the evidence DB and the shadow ledger |
| always | edgelab-dashboard | read-only dashboard, tailnet-only (Tailscale Serve) |
| after shadow/settlement/any failure alert | edgelab-notify | relays new outbox events and unit failures to ntfy (fixed headlines) |
| every 15 min | edgelab-odds | game-relative NFL odds capture (T-24h/T-6h/T-60m) under the 450-credit budget; enabled 2026-09-24 13:40Z; a paid call only for an admitted slot |
| :05, :20, :35, :50 | edgelab-observe | ADR 0030 Option A: plan later/closing-price targets, then bounded capture only when due; deferred in protected windows; enabled 2026-09-24 20:32Z |
| 04:57:45 UTC | edgelab-observe-close | the KXHIGHNY close-window capture (close 05:00:00Z; `observe status` → `close_tick_alignment`); enabled 2026-09-24 20:32Z |
| every 5 min (:01, :06, ...) | edgelab-freshness | Freshness Fabric v1 supervisor (ADR 0031): network-free; writes `freshness.json`; supervises every schedule, controls none |
| :10, :25, :40, :55 | edgelab-pm-sports | Polymarket US NFL research book captures at T-24h/T-6h/T-60m (ADR 0032; owner risk decision); related, never equivalent |
| 02:47, 08:47, 14:47, 20:47 | edgelab-pm-sports-discover | Polymarket US NFL filtered listing discovery (at most 12 requests a scan) |

Production has 13 enabled timers: 7 original core, 2 observation, 1 Freshness supervisor, 1 Odds and 2 Polymarket US pilot.

Read the state without sudo: `cat /var/lib/market-edge-lab-status/latest.json` and
`shadow_daily.json`, or `bash /opt/market-edge-lab/app/deploy/vps/verify_production.sh`
(root sees journals and backups too). Deploy only with
`docs/deploy/DAILY_SHADOW_ACTIVATION.md`, never during 17:40–18:50 ET (2026-09-24 owner rule) or a settlement run. The laptop bridge
remains MANUAL EMERGENCY FALLBACK ONLY.

## F09 checkpoint procedure (manual; no timer)

1. After the shadow run, `sudo systemctl start edgelab-backup.service` (a verified backup).
2. `sudo -u edgelab /opt/market-edge-lab/venv/bin/python -m edge_lab.cli shadow anchor export --ledger /var/lib/market-edge-lab/ledger/shadow_ledger.sqlite3 > /tmp/ckpt.json`
3. Copy it off the VPS (the owner's laptop, `market-edge-anchors/<date>/`) and commit a copy
   to `docs/engineering/ledger_checkpoints/`. Delete the VPS copy.
4. Copy the newest ledger backup's `database.sqlite3` and `manifest.json` to the laptop, and
   check its sha256 against the manifest. Run `shadow anchor verify` from a clean checkout
   at the deployed SHA against the new checkpoint (VERIFIED) and the previous one
   (EXTENDED).

## Gate 7 status (engineering vs research)

- **Engineering:** the suite is merged. F01–F08 and F10–F14 are FIXED. F09 is CLOSED for the
  anchored history, with the residual accepted in ADR 0021.
- **Production evidence:** deployed and verified; the first valid day and the first real
  shadow bookkeeping are recorded; settlement not yet observed.
- **Research evidence:** 2 valid Stage B days (2026-09-24, 2026-09-25; `verify_production.sh`
  COLLECTOR_HEALTH, 2026-09-25 01:57Z, as recorded above). The EXP-001 180/365-valid-day looks
  are far off, and nothing here is evidence of an edge.
- **Gate 7 is NOT PASSED.** No Gate 8 or real-money work was done.

## 30-day plan (issue #11, target 2026-10-22)

- **Remaining calendar days:** 28.
- The binding constraint is now the calendar (at most one valid day per day), not
  deployment. The ordered roadmap and the Domain Readiness matrix are in
  `docs/OWNER_IDEAS.md` → Roadmap (re-run 2026-09-24).
- By 2026-10-22 the system can show:
  - a deployed, verified pipeline;
  - up to about 29 days of point-in-time shadow bookkeeping, claimable only as a lower
    bound;
  - settled results;
  - multi-venue read-only foundations.

  It cannot show an edge verdict.

## Owner decisions recorded 2026-09-24

1. **ntfy:** approved and activated at the relay/provider level. The owner rotated the topic after
   exposure and subscribed; one TEST was SUBMITTED/accepted by ntfy, but at 11:24 ET the owner
   confirmed **nothing arrived on the phone**. End-to-end delivery is unresolved.
2. **F09 cadence:** manual, roughly weekly, plus after notable ledger events. No timer.
3. **Root SSH:** a separate future security task, outside Market Edge missions.
4. **Brisket:** the `/api/health` fix is done (riskittogetthebrisket#1405, deployed `15b43f4`,
   verified). The owner scoped this session to that fix only. The six failing `dynasty-*` refresh
   units are diagnosed and handed off in riskittogetthebrisket#1409:
   - #1407 is a ready fix for the import-path and EvidenceStatus failures;
   - #1406 records the DLF root cause and needs an owner decision;
   - playerctx is on a WIP branch.
5. **The Odds API:** the owner installed the free key privately. Activated 2026-09-24 (runbook
   §5b activation record). No paid plan, no credit purchases, no props, no other sports.
6. **Later/closing observations:** the owner approved ADR 0030 Option A at 11:24 ET: staggered
   hourly due-target checks plus the dedicated close-window tick. This is read-only evidence
   collection. The generalized #74 Freshness Orchestrator remains NEXT.

## UI (Terminal v1)

```
STATUS: DONE for the directive's code, review, merge and private deployment; owner visual acceptance on the phone pending.
ACCEPTANCE: owner directive docs/owner/2026-09-23-terminal-v1-ui-directive.md (issue #47);
  contract docs/design/UI_CONTRACT.md §12; ADR 0025.
EVIDENCE:
  - PR #49 squash-merged as f646481 (CI green 3.11/3.12 on the final head 6ca2be5; three rounds of
    independent review, no open blocker).
  - Local python -m pytest -o addopts="" -k "not sigterm": 1588 passed, 16 skipped, 3 deselected
    (baseline 7aac49c: 1495).
  - Browser audit (tests/browser/capture.py): 336 renders, Chromium + WebKit at
    360/390/430/768/1440/1920 over 3 fixture states. No overflow, clipping, low contrast or
    third-party requests. Emulated WebKit only; no physical-iPhone check yet.
  - Deployed 2026-09-23 18:52 ET via DAILY_SHADOW_ACTIVATION.md:
    - DEPLOYED_SHA 7aac49c -> f646481;
    - backups edge-backup-36jle2zs / ledger/edge-backup-b37xdtvk, both VERIFIED;
    - fail-closed check rejected_out_of_window (so last_failure.json shows edgelab-decision at 22:52:33Z by design);
    - dashboard restarted; verifier: 7/7 timers, no failed units, COLLECTOR_HEALTH VALID.
  - The tailnet URL serves the new UI on real data. Serve is unchanged; there is no Funnel.
UNRESOLVED:
  - Shown as unavailable rather than derived (docs/design/IMPLEMENTATION.md): calendar-day
    "Realized today"; which risk headroom binds; cross-venue equivalence; sport/league identity;
    phone delivery status.
  - Outcome rows show the raw outcome-cluster id; a plain-language label is a follow-up.
  - Once after the restart, the tape read "No quotes captured yet" while captures existed. Five
    later renders were correct and it was not reproduced. When the loader errors, the tape
    should say "unavailable" rather than "none yet" (follow-up).
  - CHASE_UPSIDE_HEALTH is UNHEALTHY: Brisket /api/health returns 503 "degraded". This predates
    this install and is not Market Edge.
BLOCKERS: NONE.
NEXT ACTION: the owner opens the tailnet URL on the iPhone and reviews Terminal, Markets, the
  market detail and Portfolio against UI_CONTRACT.md.
```

- Every user-visible change now follows docs/design/UI_CONTRACT.md (AI_INSTRUCTIONS.md, section User interface). New features use docs/design/FEATURE_INTEGRATION.md, and the PR template asks for the UI evidence.
- Rollback: /opt/market-edge-lab/app.prev (7aac49c), per DAILY_SHADOW_ACTIVATION.md → Rollback. No store or schema changed.
