# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-24 ~06:45 America/New_York. Written by the docs PR for the
2026-09-24 directive (`docs/owner/2026-09-24-brisket-health-and-next-phase-directive.md`).
The session ran on the owner's laptop with SSH to chaseupside._

```
STATUS: DONE for the directive's Market Edge build, merge and deploy scope. Two items wait on
  the owner: the Odds API key and subscribing on the phone.
ACCEPTANCE: the 2026-09-24 directive and the owner's four plan corrections (recorded verbatim),
  PHASES 2-9.
EVIDENCE:
  - Merged (squash). Each code PR had an independent review; blockers and should-fix items
    were fixed and re-reviewed; CI 3.11/3.12 was green on the exact head; each was reconciled
    with main.
    - #51 #50 index
    - #55 wall-clock test fix (another session's green test-only PR; merged to unblock CI)
    - #56 directive authority
    - #57 ntfy relay + owner secrets file (ADR 0028)
    - #58 best-price comparator + Polymarket US fee evidence + split-cancel refusal (ADR 0027)
    - #59 Odds API pilot (ADR 0029; evidence schema v5)
    - #60 sizing v2 research challenger (ADR 0026)
  - Production installs used DAILY_SHADOW_ACTIVATION.md: f646481 -> dd3ab4d -> bce5bc2 ->
    ced77b8. Every install had a VERIFIED backup of both stores first and a fail-closed
    decision check after (rejected_out_of_window). Other results:
    - shadow dry run PENDING_SETTLEMENT on each new SHA;
    - dashboard 200 (tailnet only);
    - 7 core timers enabled; edgelab-odds.timer installed and disabled;
    - no failed units; evidence schema v5 and VERIFIED after migration.
  - ntfy: the topic was generated as root straight into /etc/market-edge-lab/secrets.env
    (root:root 0600); nothing printed it. One TEST event SUBMITTED (attempts 1). Phone delivery
    is NOT verified. The relay has since SUBMITTED the "A run or data source failed" headlines
    caused by the install fail-closed checks. Those are real unit failures, run on purpose.
  - Odds API: code deployed. `odds run` reports SETUP_NEEDED. No live read and no credits
    spent.
  - Sizing v2: research only. `sizing.py`, `fees.py`, `exp001_shadow.py` and the EXP-001
    artifacts are byte-unchanged (hash-pinned test). Operational fills still use
    EXP-001-fixed-1-v1.
  - Brisket (separate repo, same host): /api/health fixed by riskittogetthebrisket#1405,
    deployed 15b43f4. It shows 200, contract_ok/served_generation_ok/source_health_ok true,
    and the post-deploy scrape had 1110 players.
UNRESOLVED:
  - The first settlement on real data is not yet observed. The settlement timer runs 11:15 and
    16:15 ET. After it, take a manual F09 checkpoint (owner cadence: roughly weekly plus notable
    ledger events; no timer).
  - F09 residual (ADR 0021): entries after 2026-09-23T22:47:20Z are unanchored until that
    checkpoint.
  - Starter policy: in force from 2026-09-24T00:00Z; first enforced decisions arrive in tonight's
    window.
  - Polymarket US: fees are an UNVERIFIED estimate that never supports a claim (settlement
    fees, debit rounding, account type and scheduled changes are unverified); rules are
    unresolved. So no cross-venue "cheaper" claim is possible yet. Re-check by
    2026-10-24T01:39Z.
  - Kalshi fee re-check due by 2026-10-23T13:39:48Z. Add SETTLEMENT_AND_TRANSFER_FEES to its
    record then.
  - Sizing v2 needs an evidence-based n_eff, the counterfactual runner and the read-only
    RESEARCH SIZING panel (NEXT). The comparator UI and the odds-target panel are NEXT.
  - Evidence schema v5 is forward-only. Rollback needs `edge_lab.storage mark-v4-for-rollback`
    (runbook Rollback).
  - Learning-history gaps are listed in docs/DATA_PROVENANCE.md §6c.
  - Root SSH hardening is a separate future security task. The same key opens root.
  - Other sessions' PRs #53 and #54 (Terminal follow-ups) are still open.
BLOCKERS: NONE for the running system. Owner actions:
  1. Install the free Odds API key: `sudoedit /etc/market-edge-lab/secrets.env`, add
     `EDGE_LAB_ODDS_API_KEY=<key>`. Then an agent runs `odds plan`, one `odds smoke`, and
     enables the timer (runbook §5b).
  2. Subscribe on the phone: privately run `sudo grep NTFY /etc/market-edge-lab/secrets.env`
     on the server, and subscribe in the ntfy app (server ntfy.sh, topic = the part after
     https://ntfy.sh/).
NEXT ACTION: after the 11:15 ET settlement run, confirm the first real settlement in
  shadow_daily.json and take the manual F09 checkpoint.
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
| every 15 min (once enabled) | edgelab-odds | game-relative NFL odds capture under the 450-credit budget; disabled until the key exists |

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

1. **ntfy:** approved and activated. The owner still needs to subscribe on the phone.
2. **F09 cadence:** manual, roughly weekly, plus after notable ledger events. No timer.
3. **Root SSH:** a separate future security task, outside Market Edge missions.
4. **Brisket:** repaired in the Brisket repository (#1405). The failing refresh units are
   handled there.

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
