# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-24 ~16:45 America/New_York (VPS clock) by the laptop Claude session that
reviewed, merged and deployed PR #76._

```
STATUS: PARTIAL.
  - PR #76 (ADR 0030 Option A observation timers): MERGED, DEPLOYED and PRODUCTION_VERIFIED for
    install, timers and the first scheduled plan run.
  - Not yet observed: a scheduled network capture (first due ~19:05 ET) or a close capture
    (00:57:45 ET).
  - ntfy phone delivery is unresolved: the server path is proven clean, and the phone/subscription
    side needs the owner.
  - No settlement was due today.
ACCEPTANCE:
  - owner follow-up 2026-09-24 (ntfy TEST not received; ADR 0030 Option A approved; #74);
  - owner instructions for PR #76 review, merge, deploy and timer verification (not-before-due
    evidence rules).
EVIDENCE:
  - PR #76 review. The PR arrived at 47459fc with CI red on both Pythons. Fixed on the PR branch,
    under a work claim:
    - two blockers: a primitive row with two owners, and a stale NOT_AUTHORIZED test;
    - should-fix items, over two independent re-reviews:
      - `observe status` reports the approved policy separately from systemd's real timer state,
        and adds `close_tick_alignment`;
      - a retryable failure no longer alerts; exit 1 only when no unprotected scheduled tick
        remains before the deadline (the protected windows are counted);
      - close groups cannot be starved (CLOSE_GUARD);
      - the close tick and retry interval are pinned to the timer files by test;
      - stop and rollback commands name all 10 timers (no glob) and check is-enabled;
      - a v5 rollback re-enables Odds;
      - the verifier reports the observation timers.
    - Final head e8b04c1: CI green on 3.11 and 3.12; full local suite 2239 passed. Re-review
      READY with no blockers.
    - Squash-merged as 9d66c907b0a63612aed2b8696f4a9c9a9be57c81 (GitHub state MERGED).
  - DEPLOYED 9d66c90 at 2026-09-24 16:31 ET (20:31Z) via DAILY_SHADOW_ACTIVATION.md:
    - after the 16:15 ET settlement run finished and the protected window closed;
    - preflight PASS; both stores VERIFIED before and after; install exit 0;
    - FAIL_CLOSED_CHECK PASS, recorded as DEPLOYMENT_VERIFICATION with HELD_BY_ORIGIN 1 (not
      pushed);
    - shadow dry run PENDING_SETTLEMENT; dashboard 200.
  - PRODUCTION_VERIFIED (verify_production.sh, 20:36Z):
    - DEPLOYED_SHA 9d66c90; TIMERS 9/9 core and observation enabled, plus edgelab-odds (10
      enabled); failed units: none;
    - COLLECTOR_HEALTH VALID; backups and restores of both stores VERIFIED;
    - Chase Upside HEALTHY: Brisket /api/health 200. Brisket was not touched.
  - Observation timers were enabled 20:32Z. Both show enabled/active, Persistent=no.
    - edgelab-observe.timer (AccuracySec 15s): first trigger 16:35 ET, Result success.
    - edgelab-observe-close.timer (AccuracySec 1s): next 2026-09-25 04:57:45Z; not yet triggered.
    - `systemd-analyze calendar` normalizes the expressions to :05/:20/:35/:50
      America/New_York and daily 04:57:45 UTC.
  - First scheduled tick (16:35 ET, exit 0):
    - `observe plan`: 6 decision markets, 42 targets planned;
    - 24 decision/recheck rows backfilled from the stored forward captures;
    - 12 post-decision targets MISSED with PLANNED_AFTER_DEADLINE. Those decisions were made on
      2026-09-23, before any schedule; nothing was fabricated late.
    - `observe capture`: NOTHING_DUE, 0 requests.
  - `observe status`: timers enabled/active (systemd); close_tick_alignment ALIGNED (6 of 6).
    The source-confirmed KXHIGHNY close is 2026-09-25T05:00:00Z (production evidence DB), and
    each close window is 04:57:30-04:59:50Z.
  - Odds API:
    - 14:15 ET T-6h target (ATL @ GB) CAPTURED at 18:15:07Z: snapshot 24, 1 event, 9 books,
      3 credits.
    - Quota: 6 used, 494 remaining, no reservations. The 19:15 ET T-60m target is PLANNED.
  - Settlement: the 11:15 and 16:15 ET runs exited 0 with nothing due. The ledger is unchanged at
    30 entries and VERIFIED against the 2026-09-23T224720Z checkpoint. No F09 checkpoint was
    triggered.
  - ntfy diagnosis. Read-only, run as edgelab with the relay's EnvironmentFile; it printed no
    topic.
    - The configured URL is well formed: https, ntfy.sh, one topic segment, valid charset, at
      least 32 characters, contains uppercase, no whitespace or quotes, no token.
    - The post-rotation TEST was sent 12:43:57Z, 14 min after the owner's rotation (secrets.env
      mtime 12:29:23Z).
    - ntfy.sh's cache for the configured topic holds exactly that message: "Market Edge INFO: TEST",
      id o7zaiYbOTCOe, 12:43:59Z, priority 2 (low), expires 2026-09-25 00:43:59Z.
    - The server path is therefore clean: Market Edge sent it, ntfy accepted and stored it on the
      configured topic.
UNRESOLVED:
  - The first scheduled network observations:
    - ~19:05 ET: post_decision_1h for tonight's decisions;
    - 00:50 ET: pre_close;
    - 00:57:45 ET: close.
    Verify each as CAPTURED / MISSED / FAILED / NOT_EXECUTABLE / PARTIAL_RETRYING from stored rows.
    Never infer them from timer state.
  - ntfy phone delivery: PROVIDER SUBMITTED / PHONE DELIVERY FAILED OR UNVERIFIED. The remaining
    problem is on the phone/subscription side. Likely causes:
    (a) the subscribed topic differs (topics are case-sensitive; this one has uppercase and 32+
        characters);
    (b) priority 2 displays as a quiet notification that is easy to miss;
    (c) app notifications are disabled.
  - The Odds 19:15 ET T-60m target is pending.
  - First real settlement: the 2026-09-25 11:15 ET run at the earliest (16:15 ET if Kalshi has
    not settled). Then verify fully and take the manual F09 checkpoint.
  - Close-time risk: re-check close_tick_alignment after the 2026-11-01 DST change (ADR 0030).
  - Fee re-checks: Kalshi by 2026-10-23T13:39:48Z; Polymarket US by 2026-10-24T01:39Z.
BLOCKERS: ntfy end-to-end delivery needs an owner check on the phone; no agent can see it.
NEXT ACTION: the owner opens the configured topic in the ntfy app before 2026-09-24 20:43 ET.
  - If the TEST is listed, the subscription is right; fix notification display (priority or app
    settings).
  - If it is not listed, re-subscribe to the exact topic.
  Proving a repair then needs one additional TEST send, which needs the owner's explicit OK.
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

Production has 10 enabled timers: 7 original core, 2 observation and 1 Odds.

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
- **Research evidence:** 1 valid Stage B day. The EXP-001 180/365-valid-day looks are far
  off, and nothing here is evidence of an edge.
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
