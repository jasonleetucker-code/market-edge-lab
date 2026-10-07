# HANDOFF — current state

This is the live state of the repository. Each session overwrites it; it is not a history
(git log is the history). Format: `AI_INSTRUCTIONS.md` → Handoff format.

_Last updated: 2026-09-30 ~07:30 America/New_York (VPS clock) by the laptop Claude coordinator session. It covers
the owner directive of 2026-09-30 (`docs/owner/2026-09-30-roadmap-integration-sports-intelligence-rfq-directive.md`,
issue #145): complete roadmap integration plus sports intelligence and RFQ feasibility v1. The NHL state of
2026-09-29 is in git history (#144)._

```
STATUS: DONE for this batch. The roadmap is consolidated (#146), and PR A/B/C (#149, #148, #150) are merged.
  Production 14704e3 is DEPLOYED and PRODUCTION_VERIFIED. All new code is offline: no new acquisition,
  credential, stream or financial transport.
ACCEPTANCE: the 2026-09-30 directive:
  - review and integrate #146;
  - PR A: source, game-state and latency contracts, plus fill-conditioned economics, extending existing owners;
  - PR B: RFQ feasibility (capability matrix, economics, PROCEED/NARROW/DEFER) with offline lifecycle fixtures;
  - PR C: current-blocker reconciliation, compact Terminal, R0–R11 ledger;
  - EXP-001 and EXP-002 unchanged; no authority expansion.
EVIDENCE (each item: independent review, fixes re-reviewed, exact-head CI green on 3.11/3.12, reconciled):
  - #147 (cd1d265): directive record and EXECUTION_PLAN entry (offline scope). #146 later added the §18 merge and
    deploy conditions, and the owner's verbatim delegation "keep going until everything is merged and deployed".
  - #146 (61e7965; exact head 18fb691): the roadmap consolidation.
    - Two review rounds. The original head failed CI: OWNER_IDEAS broke the intake and one-owner-per-primitive
      invariants.
    - Fixed: OWNER_IDEAS restored to the contract; wording that read as authority removed; the A.C ordering
      (before any pilot markout; no promised freeze) and dated checkpoints restored.
    - The archive equals the original blob b0689cc.
  - #149 (04bf78c; head 5cd1996), PR A (R2): extends inplay_evidence, position_policy, inplay_replay,
    research_economics and execution_ticket. ADR 0041.
    - Two review rounds. Blockers fixed:
      - source-leadership matching that depended on argument order;
      - mixed clock bases;
      - journal order;
      - a publication time used as the event time;
      - capital re-spent after a loss.
    - Refactor and no-journal replay are byte-identical (checked by hash).
  - #148 (519580d; head 28e6dfb), PR B (R4): docs/research/RFQ_FEASIBILITY_2026-09.md, with decision NARROW.
    - rfq_research.py is pure and fixture-fed, and reserves through execution_ticket (one primitive owner). ADR 0042.
    - Two review rounds. Blockers fixed: exposure released too early; the requester obligation lost.
  - #150 (14704e3; head 1cd6dfa), PR C:
    - Fee routing: `fee_schedules.not_proven_standard` makes KXNHLGAME and KXMVE* FEE_UNSUPPORTED (explicit map;
      every other series is unchanged).
    - A single blocker register (current_blockers.py → docs/research/CURRENT_BLOCKERS.md).
    - Terminal: in-play state-validity and simulated fill-economics sections (gallery only); "Current blockers"
      and RFQ feasibility on Data sources; next blocker on the Terminal; contract exceptions on market detail.
    - DELIVERY_ROADMAP §9: the R0–R11 ledger.
  - DEPLOYED 14704e3 at 07:18 ET via /root/deploy.sh: preflight PASS, backups verified before and after,
    fail-closed PASS, 0 failed units, 13 timers, both NHL switches kept.
    Production checks:
    - /experiments/inplay still reads "No in-play source is authorized", with no fixture sections;
    - /gallery/inplay returns 404;
    - Data sources shows the RFQ block ("Decision: Narrow") and "Current blockers" (11 open; next: O1/F09 by
      about 2026-10-03).
  - Reviewers ran full suites of about 3,515 tests. One gate7 subprocess timeout under concurrent load was not
    reproducible (30/30 on rerun). check-frozen is clean on every PR.
UNRESOLVED:
  - EXP-002 freeze blockers:
    - E1 design review;
    - the A.C run (once, after the pilot's T-6h weeks to 2026-10-19 ET and before any pilot markout or E1 result
      is viewed);
    - KXNFLGAME fees;
    - freeze proposal v2 wording (the Venue Change clause);
    - the owner's 2026-10-22 review.
  - NHL:
    - shootout and tie semantics RULES_UNRESOLVED;
    - KXNHLGAME fees FEE_UNSUPPORTED (routing now explicit, #150);
    - the October Odds budget (packet decision 1) and the read-time alignment (decision 2).
  - RFQ (NARROW): its own fees, entitlements, volume, quote lifetimes and pause behaviour are UNKNOWN. There are 15
    documented contradictions across Kalshi pages. Competitor quotes and fills are unavailable by design.
  - Rights: which terms govern API data is UNRESOLVED. The Kalshi message revision 2 is NOT SENT.
  - Fee-schedule PDF re-read got HTTP 429; the 2026-09-23 capture remains the evidence.
  - Routine:
    - O1 weekly pull and F09 by about 2026-10-03;
    - fee re-checks: Kalshi by 2026-10-23T13:39:48Z, Polymarket US by 2026-10-24T01:39:45Z;
    - DST check after 2026-11-01;
    - EXP-003 scope rejected on 2026-11-15 if Q1 or Q4 is unresolved or unfavourable.
BLOCKERS (owner-only):
  1. docs/owner/2026-09-29-vf-decision-packet.md: the data-rights review; Kalshi message revision 2 and channel;
     `inplay-source-pilot-1` approval.
  2. docs/owner/2026-09-29-nhl-decision-packet.md: October NHL Odds coverage (default (a)); the shared
     protected-window contract.
  3. docs/research/RFQ_FEASIBILITY_2026-09.md D1–D6. Only needed if RFQ research is to go beyond documentation:
     rights, an observe-only credential (not authorized), questions in revision 3, a public block-trade read scope,
     a #96 slot, and a budget.
NEXT ACTION: R3. Refresh the existing `inplay-source-pilot-1` proposal onto the merged R2 contracts: state
  versions, clock uncertainty, and a latency-stage budget for whole input messages. It stays docs and fixtures only
  until the owner decides the vf packet §B/§C. It needs a new EXECUTION_PLAN scope entry first. Separately, run O1
  and F09 around 2026-10-03.
```

## Architecture reconciliation (#152, PR #153), 2026-09-30

_Added by the laptop Claude session for the owner directive `docs/owner/2026-09-30-architecture-reconciliation-directive.md`.
The operations state above is unchanged by it._

```
STATUS: DONE for the directive's scope, pending the owner's merge. PR #153 is IMPLEMENTED, TESTED_LOCALLY and CI_GREEN
  (exact head 085edb9), and independently reviewed with verdict APPROVE. It is NOT MERGED and NOT DEPLOYED. No merge
  delegation clearly covers runtime code, so it stops at a reviewed PR (EXECUTION_PLAN, 2026-09-30 architecture entry).
ACCEPTANCE: the directive's completion list:
  - architecture and owner map;
  - source-access and adoption decisions;
  - roadmap integration;
  - one bounded confirmed-gap fix;
  - test and review evidence;
  - compatibility, safety and unresolved items.
  All are in docs/engineering/ARCHITECTURE_RECONCILIATION_2026-09-30.md.
EVIDENCE:
  - Gaps fixed in inplay_evidence.py, each reproduced by a regression that fails first:
    - an empty RECORDED journal was reported SYNTHETIC and passed the consumer's RECORDED refusal;
    - a book carried an earlier message's venue stamp across a resync (false published time; 599.05 s false
      TRANSPORT latency).
  - tests/test_inplay_evidence_path.py (journal file -> build_view): 5 fail on main 14704e3; with the fix, all 12
    tests in the file pass. The reviewer confirmed the before/after independently.
  - Full local suite (Windows, 3.12) at 085edb9, `-k "not sigterm"`: 3538 passed, 58 skipped, 3 deselected, 0 failed.
  - tests/invariants: 127 passed. `experiments check-frozen --base origin/main`: clean (exit 0).
  - CI: pytest 3.11 and 3.12 green on 085edb9 (actions run 36710106274).
  - Review: one read-only reviewer. Round 1: CHANGES_REQUIRED, no blocker, 9 findings (docs overclaims, direct-import
    scope, R3 ordering, HANDOFF). Round 2: APPROVE with 2 nits, both fixed in 085edb9.
  - Fixture gallery output is byte-identical to main (all 11 variants). check-frozen is clean.
  - The 25 X links: 3 were attempted this session, all HTTP 402. No disposition relies on unseen content.
UNRESOLVED:
  - The book path is not content-addressed through the consumer (journal digest; last message raw_sha256).
  - build_view does not slice transitions to the as-of. It fails closed: BOOK_STALE, and the view shows STALE.
    Both items are proposed as R3a for the R3 scope entry.
  - The import boundary is direct-import only. Transitive research_economics -> experiments and
    position_policy -> ... -> shadow_ledger predate this work; no protected data is read.
  - The hand-written fixture journal's ts_ms values are 2 days before their receipts. Left unedited; any latency
    test that uses it needs a labelled derivative.
BLOCKERS: the owner's merge decision on PR #153.
NEXT ACTION: the owner reviews and merges PR #153 (a normal deploy afterwards carries it; nothing reaches
  production, which shows NOT_AUTHORIZED for in-play). Then R3 as above: a scope entry, with R3a proposed in it.
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
| every 15 min | edgelab-odds | game-relative NFL odds capture (T-24h/T-6h/T-60m) under the 450-credit budget; enabled 2026-09-24 13:40Z; a paid call only for an admitted slot; since 2026-09-29 15:12 ET also NHL `icehockey_nhl` h2h T-60m, admitted only after NFL's worst case (`EDGE_LAB_ODDS_NHL`, ADR 0039) |
| :05, :20, :35, :50 | edgelab-observe | ADR 0030 Option A: plan later/closing-price targets, then bounded capture only when due; deferred in protected windows; enabled 2026-09-24 20:32Z; since 2026-09-25 also Kalshi KXNFLGAME books after each Odds NFL capture (owner-approved #110, `EDGE_LAB_KALSHI_NFL_CAPTURE=off` pauses it); since 2026-09-29 15:38 ET also schedule-driven KXNHLGAME T-6h/T-60m books (ADR 0040, `EDGE_LAB_KALSHI_NHL_CAPTURE`) |
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
  deployment. The ordered roadmap is `docs/strategy/DELIVERY_ROADMAP.md`; the Domain Readiness matrix
  (last scored 2026-09-24) is in `docs/strategy/archive/OWNER_IDEAS_pre_podcast_2026-09-29.md`.
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
