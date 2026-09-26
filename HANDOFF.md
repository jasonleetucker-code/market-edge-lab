# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-25 ~21:45 America/New_York (VPS clock) by the laptop Claude coordinator
session. It covered the owner's Research Unblocking directive
(`docs/owner/2026-09-25-research-unblocking-directive.md`) and the owner's approval of Kalshi NFL
capture. The earlier state (Economic Evidence v1, first real settlement, F09 2026-09-25) is in git
history (#106, #108)._

```
STATUS: DONE for the directive's build scope. Every PR is merged. Production is 86e528b, DEPLOYED
  and PRODUCTION_VERIFIED 2026-09-26 01:31Z. Pending, time-based: the first Kalshi NFL captures,
  #107's first same-run settlement (KXHIGHNY-26SEP25) and the first Polymarket US capture. Two
  owner decisions remain (docs/owner/2026-09-25-research-unblocking-decision-packet.md).
ACCEPTANCE: the Research Unblocking directive §5–§16:
  - reclassified blockers;
  - a reviewed EXP-002 protocol recommendation;
  - the shadow-fill language review;
  - the Kalshi NFL capture plan (then the owner's approval, implementation and deployment);
  - the EXP-003 proof-obligation table;
  - economics and effort scenarios;
  - a backup retention proposal with a dry-run planner;
  - the owner decision packet.
  Not authorized and not done: backup deletion, off-host storage, sending messages to Kalshi, paid
  data, new timers, orders, gate advances, EXP-001 changes.
EVIDENCE:
  - Owner decision recorded: "Approve Kalshi NFL capture." (chat, 2026-09-25 ~17:30 ET) →
    docs/EXECUTION_PLAN.md (#110, 886fbff). It is bounded by SPORTS_PAIRED_EVIDENCE_GAPS §6:
    - KXNFLGAME only, at the Odds T-24h/T-6h/T-60m horizons;
    - ≤ 288 + 7 GETs a week, zero Odds credits;
    - the existing edgelab-observe timer, no new timer, unit or schema;
    - review 2026-10-22.
  - MERGED, each with an independent review, re-reviews until READY, exact-head CI green on
    3.11/3.12, and reconciled with main:
    - #109 (706a340) claims and the directive record.
    - #110 (886fbff) the approval record.
    - #111 (ce48e29) docs/research/RESEARCH_UNBLOCKING_DECISIONS.md: EXP-002 protocol
      recommendation, EXP-003 proof obligations, economics scenarios, and ADR 0037 fill-mode
      labels v2. Three review rounds; the first found the primary endpoint biased under the null.
    - #112 (c05bd8a) Kalshi NFL pairing in price_observations:
      - on by default; EDGE_LAB_KALSHI_NFL_CAPTURE=off is the kill switch, preserved by
        install.sh;
      - hard bounds;
      - EXP-001 priority;
      - no paging for NFL;
      - Fabric isolation.
      Two review rounds.
    - #113 (c800e02) docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md plus the dry-run
      `backup retention-plan`: no delete path; only restore-verified bundles count as good. Two
      review rounds.
    - #114 (e41404b) claims; #115 (86e528b) join v2 (prospective book choice, book_timing,
      BEFORE_ODDS pairs comparability-only and counted), v2 labels in the Terminal, and the ADR
      0037 index line. Three review rounds.
  - DEPLOYED via DAILY_SHADOW_ACTIVATION.md (/root/deploy.sh: preflight PASS required; verified
    backups before and after; fail-closed PASS; no failed units; 13 timers):
    - c05bd8a at 23:23Z. The first attempt at 23:21Z stopped on preflight FAIL (host load 4.79
      on 4 CPUs from another tenant), and nothing was installed. The retry waited for load < 3.
    - 86e528b at 01:31Z. verify_production:
      - DEPLOYED_SHA 86e528b; COLLECTOR_HEALTH VALID;
      - FRESHNESS CURRENT; restores VERIFIED (ledger 92 entries);
      - Chase Upside HEALTHY.
  - Production read-only checks (2026-09-26 ~01:33Z):
    - `nfl-dry-run`: switch ON, version kalshi-nfl-pairing-v1, 0 planned (no NFL Odds capture yet
      this week), 0 Odds calls, weekly cap 295.
    - `backup retention-plan --verify-reports <edgelab-backup journal> --checkpoints …`:
      - DRY_RUN_ONLY, deletes_performed 0;
      - 95 bundles; 40 restore-verified by recorded reports;
      - evidence: KEEP 47, DELETE-CANDIDATE 2 (147,456 B); ledger: KEEP 46.
  - Measured backup inventory (2026-09-25 ~21:15Z): evidence DB 3,383,296 B; ledger 258,048 B;
    backups 48,305,019 B (45 evidence + 42 ledger bundles); 67.1 GB free; **no off-host database
    backup exists**.
UNRESOLVED:
  - First Kalshi NFL captures: expected after the Saturday 2026-09-26 T-24h Odds captures for
    Sunday games. Verify from stored rows:
    - price_observations KXNFLGAME rows and receipt skew;
    - `sports_evidence report --summary` G1/G2 → PARTIAL;
    - join v2 timing split;
    - Fabric: NFL not counted in EXP-001's observe source.
    The first settled-markets read will be the first real use of the min/max_settled_ts filters.
  - #107 same-run settlement: not yet observed. Verify at the run that first fetches the
    KXHIGHNY-26SEP25 result (from 2026-09-26 11:15 ET):
    - the evidence receipt falls inside the same run, and the cutoff equals the refresh receipt;
    - payout, fees, equity, duplicates and the hash chain.
  - First Polymarket US research capture (T-24h, 2026-09-26 16:53Z): verify per runbook §5e.
  - Unverified external facts:
    - Kalshi settlement/transfer fees;
    - fractional-fill fee rule;
    - NO-side fallback payout;
    - KXNFLGAME fee semantics;
    - TWC settlement precision;
    - the Feb-vs-Sep conflict for a game suspended after 55 min.
    Drafted questions await owner approval to send.
  - Not built: the EXP-002 markout endpoint that uses the first T-60m book (#111 A.B), and the
    label-free correlation gate calculation. Both are needed before the 2026-10-21 freeze.
  - Section B shows stale after 2026-10-03 unless a newer EXP-003 result is recorded. EXP-003 is
    recommended paused.
  - Backup: decide retention by about 2026-10-08 (10 GB around 2026-10-14 at build-out pace).
    The restore-over-live runbook section is PROPOSED, not written.
  - ntfy deferred by the owner; DST re-check after 2026-11-01; fee re-checks (Kalshi by
    2026-10-23, Polymarket US by 2026-10-24); Brisket PRs #1406/#1407 are outside this repo.
BLOCKERS (owner-only; see the decision packet):
  1. Research economics and effort: the EXP-002 minimum useful contribution (recommended $1,000/yr,
     option B) and owner hours (6 h to 2026-10-22); EXP-003: approve or decline sending the
     drafted Kalshi questions (recommended pause; reject 2026-11-15 if unresolved).
  2. Backup retention proposed-v1 and a manual weekly off-host pull to the laptop (O1, $0).
NEXT ACTION: on 2026-09-26, verify the first Kalshi NFL captures, #107's same-run settlement and
  the first Polymarket US capture from stored rows; then build the EXP-002 markout endpoint and
  correlation gate for the pilot.
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
| :05, :20, :35, :50 | edgelab-observe | ADR 0030 Option A: plan later/closing-price targets, then bounded capture only when due; deferred in protected windows; enabled 2026-09-24 20:32Z; since 2026-09-25 also Kalshi KXNFLGAME books after each Odds NFL capture (owner-approved #110, `EDGE_LAB_KALSHI_NFL_CAPTURE=off` pauses it) |
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
  shadow bookkeeping are recorded; the first real settlement is recorded and verified
  (2026-09-25, KXHIGHNY-26SEP24), with an F09 checkpoint.
- **Research evidence:** 3 valid Stage B days (`latest.json` valid_days = 3, `verify_production.sh`
  VALID_DAY_OBSERVED at 86e528b, 2026-09-26 01:40Z). The EXP-001 180/365-valid-day looks are far off,
  and nothing here is evidence of an edge.
- **Gate 7 is NOT PASSED.** No Gate 8 or real-money work was done.

## 30-day plan (issue #11, target 2026-10-22)

- **Remaining calendar days:** 27 (as of 2026-09-25).
- The binding constraint is now the calendar (at most one valid day per day), not
  deployment. The ordered roadmap and the Domain Readiness matrix are in
  `docs/OWNER_IDEAS.md` → Roadmap (re-run 2026-09-24).
- By 2026-10-22 the system can show:
  - a deployed, verified pipeline;
  - up to about 28 days of point-in-time shadow bookkeeping, claimable only as a lower
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
  - RESOLVED (2026-09-25): CHASE_UPSIDE_HEALTH was UNHEALTHY (Brisket /api/health 503
    "degraded"); it has been HEALTHY at every EV1 verification.
BLOCKERS: NONE.
NEXT ACTION: the owner opens the tailnet URL on the iPhone and reviews Terminal, Markets, the
  market detail and Portfolio against UI_CONTRACT.md.
```

- Every user-visible change now follows docs/design/UI_CONTRACT.md (AI_INSTRUCTIONS.md, section User interface). New features use docs/design/FEATURE_INTEGRATION.md, and the PR template asks for the UI evidence.
- Rollback: /opt/market-edge-lab/app.prev holds the previous release (c05bd8a as of the 86e528b deploy, 2026-09-26 01:31Z; install.sh keeps exactly one), per DAILY_SHADOW_ACTIVATION.md → Rollback. The previous bundles are also kept under ~dynasty/edgelab-release/prev-<sha>/. No store or schema changed in this session.
