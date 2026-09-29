# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-26 ~13:55 America/New_York (VPS clock) by the laptop Claude coordinator
session. It covered the owner's decisions of 2026-09-26
(`docs/owner/2026-09-26-owner-decisions-economics-backup.md`) and the day's first production
observations. The Research Unblocking state of 2026-09-25 is in git history (#116)._

```
STATUS: DONE for everything buildable, with two exceptions:
  - #120 (reviewed READY) and this record PR are BLOCKED on GitHub Actions: the account's billing
    stopped CI ("recent account payments have failed or your spending limit needs to be
    increased"). That is an owner-only fix.
  - The Kalshi questions await the owner's confirmation of the final text and the sending channel.
  Production is c32152f, DEPLOYED and PRODUCTION_VERIFIED.
ACCEPTANCE: the owner decisions of 2026-09-26: record them; retention proposed-v1 via a reviewed
  manual apply with a dry-run candidate list attached; O1 runbook and first pull; verify the first
  NFL pairs, #107's same-run settlement and the first Polymarket capture; build the EXP-002
  measurement endpoint and pre-freeze gate; keep EXP-002/EXP-003 DRAFT; no EXP-001 retuning; no
  orders, paid data, accounts or gate advance.
EVIDENCE:
  - MERGED, each with an independent review, re-reviews until READY, exact-head CI green and
    reconciled with main:
    - #117 (76e3bbc): the decision record; EXP-002 economics and hours; EXP-003 paused (hours not
      owner-set); the final Kalshi message, NOT SENT.
    - #118 (9911c3c): `backup retention-apply` (the only deleting command), O1 tooling and runbook
      §7–§9. Two review rounds; the first blocker was that F09-linked and pinned protection
      depended on flags.
    - #119 (c32152f): the EXP-002 label-free pre-freeze gate and cross-book markout endpoint. Three
      review rounds. A gate v2 pass is PASS_REPEAT_ONLY_NOT_FREEZE_ELIGIBLE; nothing in v2
      authorizes a freeze.
  - DEPLOYED (/root/deploy.sh: preflight PASS; backups verified before and after; fail-closed
    PASS; no failed units; 13 timers):
    - 9911c3c at 08:52Z;
    - c32152f at 09:13Z; verify_production: VALID, valid_days 3, both restores VERIFIED, Chase
      Upside HEALTHY.
  - FIRST RETENTION CYCLE (owner-approved proposed-v1), recorded in
    docs/deploy/retention-records/2026-09-26/:
    - Dry run 20260926T085314Z, report sha256 48eb171c…1fbaec. Candidates, each SUPERSEDED and
      covered by edge-backup-tlpycog1 (restore-verified at apply):
      - edge-backup-mlj3ys07 (73,728 B);
      - edge-backup-1q6ozcdh (73,728 B);
      - edge-backup-_m9y33hi (360,448 B).
    - Apply at 08:53:39Z: DELETED exactly those 3 (507,904 B). Kept 49 evidence and 49 ledger
      bundles. Ledger, F09-linked, pinned and unverified copies were untouched. The live DB was
      untouched.
  - FIRST O1 PULL: the newest verified bundles, edge-backup-tlpycog1 (evidence) and
    ledger/edge-backup-ui_qahf5, went to C:\Users\jason\market-edge-offhost\2026-09-26.
    `offhost-verify`: VERIFIED (manifest sha and a restore check, both stores). Runbook bug found:
    `--verify-reports /dev/stdin` fails under runuser; the fix is in #120.
  - #107 same-run settlement: PRODUCTION_VERIFIED at the 2026-09-26 11:15 ET run.
    - The run started at 15:15:04Z. Its refresh run settlement-refresh-608526a4… stored snapshot
      149 at 15:15:09.078Z.
    - The evidence cutoff equalled that receipt, and it settled 4 positions in the same run.
    - KXHIGHNY-26SEP25 = 69.00; Kalshi and the resolver agree. B67.5 YES −0.16 and T67 YES −0.07
      per account.
    - Equity 999.10 (operational) and 99999.10 (research); realized −0.90 each; committed 0.58;
      2 open positions each.
    - 96 ledger entries; no duplicates; both replays pass.
  - F09 checkpoint 2026-09-26T151756Z, after this notable ledger event:
    - Heads: research seq 94 a4fd85d5…; operational seq 96 311599aa….
    - Ledger backup edge-backup-ut3yody3, sha = manifest: VERIFIED against the new checkpoint and
      EXTENDED against 2026-09-25T201836Z.
    - Committed here, with a copy on the laptop in market-edge-anchors/2026-09-26/.
  - First Polymarket US research capture: 9 T-24h targets (Sunday 13:00 ET games, target 17:00Z),
    all CAPTURED at 16:55:06–14Z. Books fresh and open, snapshots 151–159, source hashes recorded.
    9 of 9 due targets observed, 0 missed. All RELATED_NOT_EQUIVALENT.
  - First Kalshi NFL pairs:
    - 18 KXNFLGAME targets (9 games × 2 team markets), planned at the 17:00:11Z Odds receipt.
    - 36 price rows, all CAPTURED at 17:05:10–13Z (receipt skew about 5 min), fresh, 1¢ spreads.
    - Budget: 9 game-horizons; 27 GETs expected, 54 worst, of the 295 weekly cap; 0 Odds calls.
    - `sports_evidence report --summary`: 18 sides paired, all AT_OR_AFTER_ODDS; G2 → PARTIAL.
      Every waterfall except SNAPSHOT (not enumerated) reconciles. The 9 events are
      RULES_UNRESOLVED (tie/not-played bounds not declared). The edge is NOT_DEFENSIBLE:
      FEE_UNSUPPORTED, RELATION_CONDITIONAL, NO_EPISODE_DEFINITION, BENCHMARK_NOT_TRUTH.
    - `exp002` gate: INSUFFICIENT_DATA, not freeze-eligible (9 dispersion pairs, 0 repeats,
      1 week), as expected before T-6h.
UNRESOLVED:
  - GitHub Actions billing: no CI, so no merge. #120 (runbook fix and three safeguards, READY) and
    this PR wait.
  - Kalshi questions: final text shown to the owner; NOT SENT. They need the owner's confirmation
    and channel.
  - EXP-003 owner hours: not stated by the owner (the packet recommended 2 h).
  - EXP-002 cannot freeze until:
    - gate v3 (spread-based noise, re-simulated, reviewed) exists;
    - the tie/not-played bounds, episode definition and δ_min are frozen;
    - KXNFLGAME fees are verified (G4; Kalshi Q7).
    Target freeze 2026-10-21.
  - Next routine operations:
    - O1 weekly pull about 2026-10-03;
    - F09 about weekly. An apply refuses once F09 is over 8 days old (after #120);
    - the next retention dry run and apply at the owner's cadence;
    - DST check after 2026-11-01;
    - fee re-checks: Kalshi by 2026-10-23, Polymarket US by 2026-10-24.
  - ntfy deferred by the owner. Brisket PRs #1406/#1407 are outside this repo.
BLOCKERS (owner-only):
  1. Fix GitHub billing (Settings → Billing & plans) so CI runs again.
  2. Confirm the Kalshi message text and channel (own email, or the help-center form via the
     browser).
  3. Optional: confirm EXP-003's owner hours.
NEXT ACTION: once CI runs, merge #120 and this record PR. Then build EXP-002 gate v3 and the
  protocol freeze inputs (the next batch in docs/OWNER_IDEAS.md, 2026-09-26 entry).
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
- Rollback: /opt/market-edge-lab/app.prev holds the previous release (9911c3c as of the c32152f deploy, 2026-09-26 09:13Z; install.sh keeps exactly one), per DAILY_SHADOW_ACTIVATION.md → Rollback. Previous bundles are kept under ~dynasty/edgelab-release/prev-<sha>/. No store or schema changed.
