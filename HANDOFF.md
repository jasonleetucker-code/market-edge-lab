# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-24 ~09:50 America/New_York by the laptop coordinator session. It ran
the next-build-chunk directive (`docs/owner/2026-09-24-next-build-chunk-directive.md`) and
the owner's ntfy / Odds API activation request._

```
STATUS: PARTIAL. All seven deliverables are built, merged and deployed (production 6497af3).
  The Odds API is live. ntfy phone delivery awaits the owner. The first real settlement
  (11:15 ET run) is not yet observed.
ACCEPTANCE: the next-build-chunk directive (seven deliverables, settlement checkpoint, safety
  sections) and the owner's activation request (Part A ntfy, Part B Odds API; secrets never
  printed, read back, logged or committed).
EVIDENCE:
  - Merged (squash). Each PR had an independent review and re-review, exact-head CI green on
    3.11/3.12, and was reconciled with main:
    - #64 sizing-v2 counterfactual runner (Deliverable 1);
    - #69 read-only RESEARCH SIZING panel (2);
    - #65 comparator "Across venues" UI (3);
    - #68 later/closing price observations, manual only (4; ADR 0030; evidence schema v6);
    - #66 notification origin (5);
    - #67 Odds API readiness and the #50 coverage audit (6, 7);
    - #71 Odds smoke string-path fix (a production crash before any request);
    - #70 alerts by notification origin and the Odds API status card (5, 6 UI), plus #53 and
      #63 (other sessions' Terminal follow-ups, reconciled by Lane B).
  - Production is 6497af3, installed 2026-09-24 ~14:00Z (after 2e3e172 at 13:37Z). Both installs
    used DAILY_SHADOW_ACTIVATION.md. The second waited for the host's load to drop below the
    preflight limit (a Brisket scrape). For each install:
    - preflight PASS, and backups of both stores VERIFIED before and after the install;
    - verify_fail_closed.sh: FAIL_CLOSED_CHECK: PASS; the relay reported HELD_BY_ORIGIN 1 (not
      pushed);
    - shadow dry run PENDING_SETTLEMENT; dashboard active;
    - 8 timers; no failed edgelab units.
  - The live dashboard (6497af3):
    - /alerts groups "Verification check: edgelab-decision.service refused as expected" under
      "Tests, verification checks and diagnostics", not as an incident;
    - Data sources shows "The Odds API — ACTIVE · LIVE READ VERIFIED" with the research-only,
      not-executable label.
  - The manual settlement dry run (runbook §4.3) was skipped on purpose: the scheduled
    11:15 ET run is the first real settlement path.
  - ntfy (Part A):
    - the owner rotated the topic after exposure; it is present only in secrets.env;
    - exactly one TEST was SUBMITTED to the new topic, and the relay's last run succeeded;
    - redaction: 0 literal occurrences of the topic in the journal, status files, evidence
      DB or dashboard pages (runbook §5b record);
    - PHONE DELIVERY: OWNER_CONFIRMATION_PENDING.
  - Odds API (Part B), all 2026-09-24:
    - odds plan PROVEN: 2026-09 worst case 45, expected 42; 2026-10 worst case 450 <= ceiling
      450, expected 270; provider remaining 500.
    - Scope: americanfootball_nfl; h2h/spreads/totals; region us; game_relative_v1
      (T-24h/T-6h/T-60m); no props, no other sports, no paid endpoints.
    - One smoke read at 13:38:53Z was CAPTURED (snapshot 22): 3 credits; 500 -> 497
      remaining; 16 events, 856 offers, 9 books, all three markets.
    - Redaction verified by literal counts (the stored URLs carry apiKey=REDACTED).
    - edgelab-odds.timer enabled at 13:40Z; the first paid slot is 14:15 ET.
  - Brisket: 200, contract_ok, served_generation_ok and source_health_ok all true. It was not
    touched.
  - Sizing counterfactual on production data: 12 decisions, 0 sized, all CAPITAL_HORIZON. They
    predate STARTER_MAX_7D_V1 (in force from 2026-09-24T00:00Z), so this is the designed
    fail-closed result.
UNRESOLVED:
  - The first real settlement, due in the 11:15 ET run. Verify event, outcome, source, payout,
    fees, P&L, cash release, equity for both accounts, no duplicates and the hash chain. If the
    ledger changed, take the manual F09 checkpoint (procedure below).
  - PR #73: the venue registry still says The Odds API is "not connected" (stage TESTED) above
    the ACTIVE card. #73 moves only catalog_read/quote_read to LIVE_DATA_VERIFIED. It is in
    review; deploy after the settlement window.
  - A later-price row in the Terminal (optional in Deliverable 4) is not built.
  - The first paid Odds slots (14:15 and 19:15 ET): confirm CAPTURED or MISSED with a reason,
    3 credits each.
  - Later/closing price capture has no timer. The proposed schedule is an owner decision
    (ADR 0030), and order-book depth after the re-check is lost until then.
  - Carried forward:
    - the Kalshi fee re-check (by 2026-10-23T13:39:48Z; add SETTLEMENT_AND_TRANSFER_FEES then);
    - the Polymarket US fee re-check (by 2026-10-24T01:39Z);
    - evidence schema v6 is forward-only (rollback: `mark-v5-for-rollback`);
    - root SSH hardening is a separate security task.
BLOCKERS: NONE for the running system. Owner-only:
  1. Confirm whether the TEST push reached the phone (only the owner can see it).
  2. Decide the later/closing price capture schedule (ADR 0030).
NEXT ACTION: after the 11:15 ET settlement run, verify the first real settlement and take the
  manual F09 checkpoint if the ledger changed.
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

1. **ntfy:** approved and activated. The owner rotated the topic after exposure and subscribed;
   one TEST was SUBMITTED to the new topic. Phone delivery: OWNER_CONFIRMATION_PENDING.
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
