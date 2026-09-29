# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-29 ~16:40 America/New_York (VPS clock) by the laptop Claude coordinator
session. It covered the owner directive of 2026-09-29 (`docs/owner/2026-09-29-nhl-prospective-evidence-directive.md`,
issue #134): EXP-002 correctness continuation plus bounded NHL prospective evidence. The earlier 2026-09-29 state
(E1 and label proxies) is in git history (#133)._

```
STATUS: DONE for the buildable scope. NHL prospective collection is BUILT, DEPLOYED and ACTIVE (production
  fb2f5fd). EXP-002 freeze blocker 2 has sourced counts (PROPOSED values). The owner decisions are open in
  docs/owner/2026-09-29-nhl-decision-packet.md and docs/owner/2026-09-29-vf-decision-packet.md.
ACCEPTANCE: the 2026-09-29 directive:
  A. EXP-002: continue the pre-freeze blockers in dependency order; no weakening; no NHL mixing.
  B. NHL: DATA_COLLECTION / DEVELOPMENT_ONLY.
     - Odds API icehockey_nhl h2h (T-60m first) under one shared ledger and the 450 ceiling, NFL first.
     - Kalshi KXNHLGAME only, under its own request bound.
     - Protected windows, truthful opening night, outcomes separated, private Terminal coverage.
     - No paid plan, timer, credentials or in-play.
EVIDENCE:
  - MERGED (independent review; review fixes; exact-head CI green on 3.11/3.12; reconciled with main):
    - #135 (2f2d9c4): directive record, EXECUTION_PLAN entry, OWNER_IDEAS #134 re-plan.
    - #138 (5f2095d): EXP-002 sourced tie / not-played counts (docs/research/EXP002_TIE_NOTPLAYED_BOUNDS.md),
      summarized under EXP-002 below.
    - #137 (7e0b81d): NHL-A. A sport-aware shared Odds planner.
      - One joint NFL-first monthly proof. NHL gets only what remains after NFL's full worst case.
      - NHL_WORST_CASE is derived from the published 2026-27 schedule (1,344 games).
      - Per-sport runner state; odds status with lead bands; smoke limited to the rank-1 sport.
      - The NFL golden pin is byte-identical. ADR 0039; docs/research/NHL_ODDS_BUDGET_2026-10.md.
    - #136 (c9a2406): NHL-B. Schedule-driven Kalshi KXNHLGAME T-6h and T-60m targets.
      - Protected-window shifts are labelled with the real lead. Its own bound: 727 GETs/week at worst.
      - Reschedule and absence supersession; settlement results withheld; its own freshness identity.
      - Terminal "Kalshi NHL coverage" block; NFL pin. ADR 0040.
    - #139 (fb2f5fd): a game that drops out of discovery and returns is re-planned (`:r<n>` ids).
      NOT_CAPTURED_SCHEDULE_STALE; both-switch install test.
  - DEPLOYED with /root/deploy.sh (preflight PASS, backups verified before and after, fail-closed PASS,
    0 failed units, 13 timers): 7e0b81d 15:10 ET, c9a2406 15:36 ET, fb2f5fd 16:31 ET.
  - ACTIVATED (docs/deploy/NHL_ACTIVATION_2026-09-29.md):
    - EDGE_LAB_ODDS_NHL=on at 15:12 ET. Preview was PROVEN (6 September slots admitted, October none).
    - EDGE_LAB_KALSHI_NHL_CAPTURE=on at 15:38 ET. The dry run planned 50 targets, 0 unmapped, 0 requests.
  - OBSERVATIONS CAPTURED (production, verified 16:18 ET):
    - 12 of 20 manual opening-night Kalshi rows.
    - Scheduled Kalshi: FLA@CAR T-60m and VAN@EDM T-6h (both team markets each).
    - Odds API: FLA@CAR T-60m h2h (1 credit).
    - 6 opening-night T-6h Kalshi horizons are MISSED NOT_COLLECTED_BEFORE_ACTIVATION. Nothing was captured late
      or relabelled.
  - Odds credits: September spent 45 (NFL) + NHL so far 1. The September NHL admission is 6 slots, at most 6
    credits.
  - October NHL Odds coverage is back-loaded by NFL's worst-case reservation: 0 on Oct 1–4, then released
    weekly, about 103 of 118 T-60m slots on the planner's model. Kalshi NHL is unaffected.
  - EXP-002 (freeze blocker 2, PROPOSED; the freeze review decides):
    - ties: 8 in 2,383 games since 2017 (official NFL.com standings);
    - fallback-F events: 14 in 2,384 (conservative).
    - Proposed t_max 0.01 and u_max 0.01. The earlier u_max of 0.005 holds only if pandemic seasons are excluded.
    - Evidence event eu-622b393f records the aggregate read of public 2026 settlements and standings covering
      DEVELOPMENT pilot games. The Terminal gate line now shows LABEL_VIEWS_LOGGED.
UNRESOLVED:
  - NHL:
    - Kalshi shootout and tie semantics are RULES_UNRESOLVED.
    - KXNHLGAME fees are FEE_UNSUPPORTED; fee_schedules routes it to the general quadratic schedule. That is for
      the fee owner.
    - Odds API NHL team names were verified only by tonight's 0-unmapped dry run.
    - The 19:00-game Odds (T-25m) and Kalshi (T-85m) read times are about 60 min apart; packet decision 2.
    - The evening opening-night captures after 16:18 ET are not yet verified in this record.
  - EXP-002 freeze blockers remaining:
    - review of the E1 design;
    - the A.C timing calibration (label-free, logged);
    - KXNFLGAME fees;
    - the owner freeze review 2026-10-22.
    - Blocker 2 now has sourced PROPOSED values.
    - Freeze proposal v2 should correct §2's "venue or home/away change" wording (the terms' Venue Change clause is
      narrower).
  - From the earlier packets: Kalshi message revision 2 NOT SENT; data rights UNRESOLVED.
  - Routine: O1 weekly pull and F09 by about 2026-10-03; DST check after 2026-11-01; fee re-checks Kalshi 10-23,
    Polymarket US 10-24.
BLOCKERS (owner-only):
  1. docs/owner/2026-09-29-nhl-decision-packet.md:
     - October NHL Odds coverage, options (a)-(d); the default is (a);
     - the shared protected-window contract (decision 2).
  2. docs/owner/2026-09-29-vf-decision-packet.md: Kalshi message revision 2 and channel; the data-rights review;
     the optional in-play pilot.
NEXT ACTION: verify tonight's remaining NHL captures (the 18:35–21:40 ET slots). Then do the EXP-002 A.C timing
  calibration (label-free, logged FEATURE_INSPECTION), and propose a shared protected-window contract for NHL
  Odds and Kalshi reads.
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
- **Research evidence:** 6 valid Stage B days (`latest.json` valid_days = 6, `verify_production.sh`
  at 2026-09-29 00:01Z). The EXP-001 180/365-valid-day looks are far off,
  and nothing here is evidence of an edge.
- **Gate 7 is NOT PASSED.** No Gate 8 or real-money work was done.

## 30-day plan (issue #11, target 2026-10-22)

- **Remaining calendar days:** 23 (as of 2026-09-29).
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
- Rollback: /opt/market-edge-lab/app.prev holds the previous release (29a37d7 as of the e00a335 deploy, 2026-09-29 03:17Z; install.sh keeps exactly one), per DAILY_SHADOW_ACTIVATION.md → Rollback. Previous bundles are kept under ~dynasty/edgelab-release/prev-<sha>/. No store or schema changed.
