# Owner directive: production activation and post-audit integration (2026-09-23)

Source: the owner's written instructions to the local Claude Code session on the owner's
laptop, 2026-09-23 (afternoon, America/New_York). This session has SSH access to the Chase
Upside VPS. Recorded **verbatim** below, in the order received:

1. the SSH preflight request;
2. the owner's SSH grant, which followed the preflight result;
3. the mission directive itself.

Summary and interpretation live in `docs/EXECUTION_PLAN.md`; this file is the source.

---

## 1. SSH preflight request (verbatim)

Before doing any project work, verify whether this session has working SSH access to the Chase Upside VPS.

Do not change anything on the server.

Run these read-only checks:

1. `ssh -V`
2. `ssh -o BatchMode=yes -o ConnectTimeout=10 chaseupside "whoami && hostname"`
3. If the `chaseupside` alias does not exist, try:
   `ssh -o BatchMode=yes -o ConnectTimeout=10 -i ~/.ssh/id_ed25519_riskit dynasty@chaseupside.com "whoami && hostname"`
4. Also test root without changing anything:
   `ssh -o BatchMode=yes -o ConnectTimeout=10 -i ~/.ssh/id_ed25519_riskit root@chaseupside.com "whoami && hostname"`

Report exactly:
- whether an SSH client exists;
- which host/alias resolved;
- which user authenticated;
- whether root authenticated;
- the exact error if any command fails.

Do not install, deploy, restart, or modify anything yet.

**Result (agent):**
- The client is `OpenSSH_10.2p1, OpenSSL 3.5.5 27 Jan 2026`.
- The alias `chaseupside` resolves to `dynasty@chaseupside.com`, key `id_ed25519_riskit`.
- `dynasty` authenticated on host `vmi3454985`.
- `root` authenticated with the same key.
- There were no errors, and nothing was changed.

## 2. SSH grant (verbatim)

SSH PREFLIGHT PASSED

This local Claude Code session has confirmed read-only SSH access to chaseupside:

- alias `chaseupside` -> dynasty@chaseupside.com
- host: vmi3454985
- dynasty authentication: PASS
- root authentication using the existing id_ed25519_riskit key: PASS

Use `dynasty` as the default SSH identity.

Use sudo/root only for the exact privileged steps required by the reviewed Market Edge deployment/runbook.

Do NOT:
- modify SSH configuration;
- add/remove/rotate keys;
- disable root SSH;
- alter dynasty sudo permissions;
- perform general host hardening;
- run apt upgrade;
- reboot;
- make unrelated Brisket changes.

Those are separate future security tasks.

You now have the access needed to execute the production portions of the next Market Edge directive rather than treating them as owner-only blockers.

## 3. Mission directive (verbatim)

MARKET EDGE LAB — PRODUCTION ACTIVATION + POST-AUDIT INTEGRATION MISSION

Repository:
jasonleetucker-code/market-edge-lab

Current verified GitHub main when this directive was written:
247fe80f7a745eb5489d2d4027c0348dc9ec93aa

CI on that exact main is GREEN.

PR #40 (GitHub reuse audit + depth ladder + F14 settlement fix) is merged.
PR #41 (final integration-state docs / roadmap) is merged.

There are no active WORK_CLAIMS rows at the time this directive was written.

Treat current main as truth and verify all of the above before editing.

DO NOT STOP AFTER WRITING A PLAN.

============================================================
MISSION ORDER
============================================================

The priority order is:

1. VERIFY THE EXISTING PRODUCTION COLLECTOR.
2. DEPLOY AND ACTIVATE THE ALREADY-BUILT DAILY SHADOW / SETTLEMENT PIPELINE.
3. VERIFY PRODUCTION END TO END.
4. STORE THE FIRST INDEPENDENT F09 LEDGER CHECKPOINT WHEN POSSIBLE.
5. FIX HIGH-VALUE LOW-RISK FOLLOW-UPS FROM THE GITHUB AUDIT.
6. UPDATE HANDOFF / ROADMAP TRUTHFULLY.

Do not start another broad research project before production is handled.

============================================================
0. GROUNDING
============================================================

Read:

- AI_INSTRUCTIONS.md
- HANDOFF.md
- docs/EXECUTION_PLAN.md
- docs/OWNER_IDEAS.md
- docs/WORK_CLAIMS.md
- docs/deploy/DAILY_SHADOW_ACTIVATION.md
- docs/engineering/GATE7_FINDINGS.md
- docs/GITHUB_REUSE_AUDIT.md
- THIRD_PARTY_NOTICES.md

Review:
- issue #4
- issue #11
- issue #29
- issue #30
- issue #32
- issue #33
- issue #36
- PR #40
- PR #41

Check:
- open PRs
- current worktrees
- dirty files
- branch state
- local main vs origin/main

Do not overwrite unpushed work.

============================================================
1. OWNER AUTHORIZATION
============================================================

The owner explicitly authorizes this session to:

- use the already-established local SSH/root access to chaseupside;
- verify Market Edge production state;
- deploy reviewed/merged current main using the existing activation sheet;
- enable the already-reviewed shadow and settlement timers;
- run the approved fail-closed dry runs;
- verify backups and restores;
- verify Chase Upside health/resources;
- export the first manual F09 ledger checkpoint if the ledger contains entries;
- implement bounded non-live-money follow-up fixes described below;
- open, review, and squash-merge PRs from this mission when all acceptance conditions pass.

NOT AUTHORIZED:

- real orders;
- trading credentials;
- deposits;
- withdrawals;
- funded trading;
- live one-click execution;
- automatic trading;
- paid APIs/services;
- paid SMS;
- DNS/public dashboard exposure;
- unrelated Brisket code changes;
- new SSH keys;
- apt upgrades;
- reboot unless separately approved.

============================================================
2. DO PRODUCTION FIRST
============================================================

Before touching production, run:

TZ=America/New_York date

NEVER install/restart Market Edge during:

17:40–18:35 America/New_York

or while any edgelab-* unit is running.

If current time is safely before 17:40 ET, proceed now.

Use only:

docs/deploy/DAILY_SHADOW_ACTIVATION.md

Do not invent another deployment procedure.

============================================================
3. VERIFY BEFORE DEPLOYING
============================================================

SSH into chaseupside using the owner's existing access.

Do not request or copy private keys.

Verify:

- deployed REVISION;
- existing edgelab timers;
- collector services;
- latest.json;
- recent PFM/decision/recheck journals;
- evidence DB;
- last closed target;
- Brisket services;
- /api/health;
- memory/headroom;
- OOM/resource pressure;
- backup status.

Run the merged production verifier as documented.

Report each state separately:

DEPLOYED_SHA
COLLECTOR_HEALTH
PFM_CAPTURE_OBSERVED
DECISION_CAPTURE_OBSERVED
RECHECK_CAPTURE_OBSERVED
VALID_DAY_OBSERVED
CHASE_UPSIDE_HEALTH

STOP CONDITION:

If the existing collector is unhealthy, do not install new work first.

Restore safe read-only collection and verify it.

Do not assume a timer means a capture succeeded.

============================================================
4. DEPLOY CURRENT MAIN
============================================================

Once the existing collector is healthy:

Deploy the latest reviewed main SHA.

Use:
docs/deploy/DAILY_SHADOW_ACTIVATION.md

Required sequence:

1. stage bundle/scripts;
2. preflight;
3. production backup BEFORE install;
4. install current main;
5. fail-closed collector dry run;
6. shadow dry run;
7. settlement refresh;
8. dual backup;
9. restore verification;
10. slice/resource check;
11. enable:
   - edgelab-shadow.timer
   - edgelab-settlement.timer
12. re-run production verifier.

Do not alter the existing forward capture schedule.

Do not touch the laptop bridge.
It remains:

MANUAL EMERGENCY FALLBACK ONLY

No laptop scheduler.

============================================================
5. PRODUCTION ACCEPTANCE
============================================================

Directly verify:

- deployed SHA equals current merged main;
- original collector timers remain enabled;
- shadow timer enabled;
- settlement timer enabled;
- evidence backup succeeds;
- ledger backup succeeds;
- evidence restore succeeds;
- ledger restore succeeds;
- Brisket services remain healthy;
- resource limits remain correct;
- no OOM;
- no abnormal PSI/resource pressure;
- status files readable where intended;
- private stores remain private.

Report:

INSTALLED
FAIL_CLOSED_VERIFIED
SHADOW_TIMER
SETTLEMENT_TIMER
EVIDENCE_BACKUP
LEDGER_BACKUP
EVIDENCE_RESTORE
LEDGER_RESTORE
COLLECTOR_HEALTH
CHASE_UPSIDE_HEALTH

Do not collapse these into one “production verified” statement.

============================================================
6. FIRST REAL WINDOW
============================================================

The collection window is around:

17:45 ET forecast
17:55:05 ET decision
18:05 ET recheck
18:30 ET status

Do not sit idle waiting for it if useful independent work remains.

If this session is still running after the window:

Inspect the real evidence.

Report:

target_date
PFM status
decision status
recheck status
VALID / INVALID
reasons
number of captured markets/books

Then run the daily/shadow path on the real evidence once the day is closed.

Report:

decisions
qualified
fills
NO_FILL by reason
risk vetoes
policy vetoes
pending settlement

A valid day with zero trades is a legitimate result.

Do not manufacture a trade.

============================================================
7. F09 — FIRST OFF-HOST CHECKPOINT
============================================================

GATE7-F09 remains OPEN until a ledger-head checkpoint exists independently of the ledger.

Once the shadow ledger contains entries:

Use the documented:

edge-lab shadow anchor export

Export the checkpoint on the VPS.

Then copy the checkpoint OFF THE VPS into a private owner-controlled location.

Good destinations:

- local laptop outside the production tree;
- private GitHub repository/file with appropriate access;
- another owner-controlled private store.

Do NOT:

- store the only copy beside the ledger;
- claim F09 closed merely because anchor-export code exists.

Then:

1. take/copy a verified ledger backup;
2. verify the off-host checkpoint against the copied backup from outside the VPS;
3. record evidence.

Only then decide whether F09 is satisfied for the documented attacker model.

No new scheduled anchoring job is authorized here.

============================================================
8. AUDIT FOLLOW-UP #1 — POLYMARKET US DEPTH LADDER
============================================================

PR #40 added a venue-neutral DepthLadder for captured books.

The highest-value reuse follow-up is to give Polymarket US the same capability.

Implement a Polymarket US ladder builder that feeds the existing:

DepthLadder
walk_ladder
price_depth_fill

Do NOT create a second depth abstraction.

Requirements:

- use the existing Polymarket US public adapter;
- preserve native price/quantity precision;
- explicit side semantics;
- fail closed on malformed levels;
- missing != zero;
- truncated/unknown depth != insufficient depth;
- no midpoint fill;
- no assumed liquidity;
- deterministic tests;
- fixture coverage;
- top-of-book output must agree with the existing Polymarket quote path.

Do not add authenticated trading.

============================================================
9. AUDIT FOLLOW-UP #2 — KALSHI TICK-GRID / PAYOFF GUARDS
============================================================

The HANDOFF currently records:

opportunity.evaluate does not yet reject non-binary Payoff.kind.

Fix that BEFORE a non-binary venue can flow into the opportunity engine.

Also review the GitHub-audit recommendation for per-market tick-grid handling.

Requirements:

- binary engine rejects unsupported payoff kinds explicitly;
- no silent interpretation;
- market-specific tick/price constraints live in the correct venue/market metadata layer;
- existing EXP-001 behavior remains identical;
- tests prove no frozen-result changes.

Do not generalize by weakening validation.

============================================================
10. AUDIT FOLLOW-UP #3 — NTFY SINK, BUT NO REAL SEND
============================================================

The audit identified ntfy as the best zero-cost immediate push option.

Build the provider adapter only if it fits cleanly into the existing notification abstraction.

Do NOT send a production message yet.

Requirements:

- reuse the existing NotificationEvent contract;
- stdlib HTTP is preferred;
- no new dependency if unnecessary;
- headline/minimal payload only;
- no secrets;
- expiry;
- dedupe;
- bounded retry;
- explicit provider failure status;
- notification failure never changes risk/trading state;
- config disabled by default;
- no external POST in tests;
- fixtures/mocks only.

Because the repo currently has a no-POST invariant, do NOT broadly weaken it.

If a narrow exception is needed:
- scope it only to the notification delivery module;
- retain a hard prohibition on trading/order POSTs;
- add tests that prove order-execution paths remain blocked.

No paid SMS provider.
No real ntfy send without separate owner approval.

============================================================
11. AUDIT FOLLOW-UP #4 — FLUMINE EXECUTION-TICKET CHECKLIST
============================================================

Do not copy Flumine wholesale.

Study the already-audited control ordering and integrate only missing CHECKS into our future execution-ticket contract.

Examples to review:

- market state;
- order state;
- strategy control;
- transaction control;
- exposure;
- max-order count;
- duplicate/open order interactions;
- pre-submit validation order.

This remains future execution architecture.

NO order submission.

If the existing execution_ticket.py already covers the concept, add nothing.

Prefer tests/docs over duplicate code.

============================================================
12. WINDOWS PORTABILITY
============================================================

The GitHub audit identified Windows-only failures that reproduced on main.

After production-critical work is complete, inventory them precisely.

Do NOT dismiss them merely because Linux CI is green.

Group them by root cause:

- CRLF/text hash;
- fixture-byte hashing;
- SIGTERM assumptions;
- fork availability;
- filesystem/WAL behavior;
- notification outbox path/encoding;
- fee-PDF evidence path;
- Novig/Polymarket fixture hashing.

Fix only legitimate portability defects without weakening deterministic evidence.

Platform-inapplicable behavior should be explicitly skipped with a precise reason, not allowed to randomly fail.

Target:
clean supported Windows Python 3.12 suite, except intentionally documented platform skips.

============================================================
13. DO NOT START ANOTHER GIANT SEARCH
============================================================

The 1,209-repo audit is complete.

docs/GITHUB_REUSE_AUDIT.md is now the source.

Do not spend this mission searching another thousand repositories.

Use the audit to reduce work.

Only research a specific upstream repo when a concrete implementation question requires it.

============================================================
14. ROADMAP UPDATE
============================================================

At the end, re-run the owner-idea planning rule.

Reorder:

NOW
NEXT
LATER
BLOCKED

The likely critical order is:

NOW
1. production activation/verification
2. real Stage B collection + shadow bookkeeping
3. F09 independent checkpoint

NEXT
4. Polymarket US depth
5. multi-venue best-price-for-size comparator
6. free Odds API live activation after owner supplies key
7. ntfy push activation after owner approval
8. cross-venue weather comparison

LATER
9. sports modeling lanes
10. Action PRO ingestion
11. execution ticket → eventual human-approved API execution
12. SMS provider
13. broader venues

But do not preserve this ordering if actual dependencies now say otherwise.

Record why priorities move.

============================================================
15. TEST / REVIEW / MERGE
============================================================

For any code PR:

- claim paths first;
- reconcile with latest main;
- targeted tests;
- full suite;
- Windows verification where available;
- experiment registry validation;
- frozen-artifact check;
- independent review;
- fix blockers;
- re-review high-risk fixes;
- exact-head CI green;
- mergeable;
- squash-merge.

Never let a deployment timer or research deadline weaken correctness.

============================================================
16. FINAL REPORT
============================================================

Return:

PRODUCTION
- deployed SHA
- collector health
- all timer states
- latest real capture state
- resource health
- Brisket health

SHADOW
- real decisions
- qualifications
- fills
- NO_FILL reasons
- vetoes
- settlements

BACKUPS
- evidence backup/restore
- ledger backup/restore

F09
- checkpoint exported?
- stored off-host?
- verification result?
- still open or satisfied for documented threat model?

AUDIT FOLLOW-UPS
- Polymarket depth status
- payoff-kind guard status
- tick-grid status
- ntfy adapter status
- execution-ticket checklist status

WINDOWS
- failures before
- failures after
- remaining intentional skips

REPOSITORY
- main SHA
- PRs
- tests
- CI
- open work claims

ROADMAP
- NOW
- NEXT
- LATER
- BLOCKED

Do not claim:
- live edge;
- real-money readiness;
- production verification;
- F09 closure;
- notification delivery;
unless directly evidenced.

Keep working on independent authorized tasks if waiting on CI or the 17:45 window.
