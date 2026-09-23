# Owner directive: daily shadow operation, adversarial validation, first read-only dashboard (2026-09-23)

Source: the owner's written instruction to the working agent session on 2026-09-23,
titled "MARKET EDGE LAB — NEXT MISSION". Recorded **verbatim** below. Summary and
interpretation live in `docs/EXECUTION_PLAN.md`; this file is the source.

---

MARKET EDGE LAB — NEXT MISSION
Daily shadow operation, adversarial validation, and the first read-only dashboard

Repository: jasonleetucker-code/market-edge-lab
Release target: October 22, 2026. Do not restart the 30-day clock.

MISSION

Continue from the completed overnight work. Do not rebuild Gates 5/6, the risk engine, or the Outcome Board backend.

At preparation of this directive, GitHub main was c62218fe3171505211c1170b58e80cd22442e742:

- PR #21: overnight authorization and standing merge rule.
- PR #22: Gate 5 opportunity engine.
- PR #23: Gate 6 shadow ledger, fill policy, and sizing.
- PR #24: risk/capital report and Outcome Board backend.
- Recorded VPS collector revision: 9326a7a.
- Laptop backup capture: canceled; manual emergency fallback only.
- The last committed handoff reported zero valid live Stage B days. Recheck actual current status; do not treat that old count as current.

Read current AI_INSTRUCTIONS.md, HANDOFF.md, docs/EXECUTION_PLAN.md, relevant ADRs, Issue #11, open PRs, and work claims. Check local changes and active worktrees before syncing. Preserve unpushed work.

Load task-relevant context, not the whole repository again.


OWNER AUTHORIZATION

By sending this directive, the owner authorizes:

1. Bounded daily official settlement-evidence collection on the existing VPS.
2. Scheduled opportunity evaluation, simulated bookkeeping, and shadow settlement using stored evidence.
3. Gate 7 adversarial engineering work and tests.
4. A local, read-only, mobile-friendly dashboard over existing research/shadow data.
5. Review, testing, and squash-merging of bounded PRs in this mission under the conditions below.

Record this authorization once in the canonical owner/execution documents.

NOT authorized:
- real orders or authenticated trading APIs;
- deposits, withdrawals, or funded accounts;
- paid services or new external credentials;
- sports/crypto/equity expansion;
- public dashboard exposure, DNS/TLS, tunnels, or firewall changes;
- unrelated Brisket changes;
- SSH-key changes, OS upgrades, or rebooting.

Use existing approved access only. If this session cannot reach the VPS or laptop, complete independent repository work and report the precise access limitation. Never request private keys in chat or copy them into a cloud workspace.


PRIORITY 1 — VERIFY PRODUCTION WITHOUT DISRUPTING CAPTURE

Read actual deployed revision, timers, limits, status, backups, and relevant logs. Confirm Chase Upside remains healthy.

Use current America/New_York time.

If the first capture window has elapsed, inspect its evidence and valid-day status. Otherwise record the next window and keep building. Do not wait idle until evening.

Preserve the existing forecast/decision/recheck schedule. No disruptive changes during 17:40–18:35 America/New_York or while a capture is running.

Report separately:
- installed/timers enabled;
- fail-closed dry run verified;
- real decision/recheck captured;
- complete forecast evidence;
- valid-day classification;
- eventual settlement lifecycle verified.

One state does not prove the next. A valid no-signal day is acceptable. Retrospective fetching cannot manufacture a missed decision window.

VPS is the sole planned capture source.

Keep the laptop bridge MANUAL EMERGENCY FALLBACK ONLY. Verify the recorded cancellation. Cancel only a positively identified leftover bridge process/task if one exists. Do not kill all Python or Claude processes, create a laptop scheduler, or delete evidence.


PRIORITY 2 — MAKE DAILY SHADOW OPERATION COMPLETE

The engines already exist. Integrate them.

Build one bounded orchestration entrypoint that reuses the existing functions to:

1. Identify eligible closed capture days deterministically.
2. Evaluate opportunities from their stored point-in-time inputs.
3. Record qualifying/rejected decisions and simulated fills idempotently.
4. Refresh official settlement evidence on a bounded cadence.
5. Settle positions only when compatible, conclusive evidence exists.
6. Refresh account, risk, and Outcome Board summaries.
7. Emit an operational receipt and explicit exit status.

Decision logic must not see settlement labels or later quotes. Settlement is a separate stage.

Catch-up processing must respect what cash and information were available at the modeled time. Future settlements cannot finance earlier hypothetical positions.

Keep the evidence database and shadow ledger separate and private.

Evaluation must use read-only evidence access: opening the store for analysis must not create, migrate, or change it. Collection keeps its existing authorized write path.

Back up BOTH stores. An evidence-only backup does not protect the shadow ledger.

Requirements:
- bounded official GETs, pacing, deadlines, and retries;
- no unnecessary daily full-history download;
- concurrency protection across workers, settlements, and backups;
- restart recovery between decision, fill, and settlement;
- missing/conflicting settlement evidence leaves positions pending;
- clear HEALTHY_NO_SIGNAL, PENDING_SETTLEMENT, INVALID_CAPTURE, and FAILED states;
- processing timestamps separate from event time and evidence-availability time;
- provisional fee status preserved on every relevant entry;
- timezone-aware bookkeeping schedules after the recheck window.

Check whether settlement collection unnecessarily couples usable market results to a blocked PDF download. Preserve successful evidence while reporting partial coverage accurately.

Stage, review, and test new units before activation. Deploy reviewed merged code only, under the existing edgelab isolation.

Check the combined resource budget—not just the cap on each individual service.

Preserve backups and a tested rollback path. Code rollback must not corrupt a migrated database.


PRIORITY 3 — FEE EVIDENCE WITHOUT AN ENDLESS RETRY LOOP

Try legitimate primary sources for the applicable current Kalshi fee schedule.

Record:
- source and retrieval time;
- effective dates;
- relevant series/product;
- coefficient/formula;
- rounding;
- exact document bytes/hash where available.

An old or generic schedule does not automatically verify current KXHIGHNY fees.

If access remains blocked:
- stop retrying indefinitely;
- retain UNVERIFIED_CURRENT_SCHEDULE;
- retain claimable=false;
- state the exact owner browser-download action;
- continue independent engineering with clearly provisional simulations.

Do not edit pinned fees.py or rewrite preregistration to accommodate new evidence. Use versioned adapters and auditable changes.

Historical entries retain their original assumptions. A corrected restatement must be separate and traceable.


PRIORITY 4 — GATE 7 ADVERSARIAL ENGINEERING

Start software stress testing now. Do not wait months for observations to test failure handling.

However, fixture tests cannot establish a profitable strategy or satisfy EXP-001's preregistered 180/365-valid-day research looks.

Separate:
- engineering robustness;
- production integration evidence;
- research-performance evidence.

Do not advance to Gate 8 or real-money work under this directive.

A. RISK ENFORCEMENT

Review risk.assess and exp001_shadow.run_day together.

Confirm whether daily/weekly loss, drawdown, remaining capacity, and candidate exposure are enforced before a simulated fill—not merely displayed afterward.

Test:
- zero remaining capacity without an existing breach;
- exact-boundary limits;
- a proposed position crossing a limit;
- consecutive/concurrent candidates;
- correlated existing exposure;
- reserve and cash limits.

Zero capacity cannot authorize new risk. Persist every veto and its binding constraint.

Do not silently change EXP-001's frozen one-contract signal/selection/fill rules. Keep experimental signals distinct from operational eligibility.

A change affecting the registered experiment requires a documented amendment or separate diagnostic policy/account, never a retrospective rewrite.

B. LEDGER AND TIMING

Test:
- crashes between writes;
- duplicate/conflicting decisions, fills, and settlements;
- concurrent appends;
- hash-chain tampering;
- missing triggers;
- locked databases;
- restart/replay;
- delayed settlement evidence;
- out-of-order processing.

Do not book spendable cash before it was known available.

C. MARKET/MODEL/EXECUTION

Test:
- YES/NO complements;
- zero or missing liquidity;
- malformed/non-finite prices;
- stale or future quotes;
- wrong events;
- unresolved rules;
- incomplete forecasts;
- missing rechecks;
- worse fees and execution latency;
- price movement.

Verify tail-bin handling and probability-to-bracket conversion against the frozen design. Do not introduce model variants or tune on outcomes.

D. REPORTING

Existing equity is cost-basis shadow equity unless actual executable liquidation marks exist.

Keep hypothetical winnings out of available cash.

Delayed/unknown settlement horizons stay locked.

Cluster best/worst-case bounds must not be presented as necessarily attainable scenarios.

Run destructive/fault tests only in isolated disposable stores—not production.

Deterministic replay of published results is allowed. A new model-selection pass over the Stage A holdout is not.


PRIORITY 5 — FIRST READ-ONLY DASHBOARD

Once canonical summary interfaces are stable, build a useful local UI.

This may proceed in a non-overlapping lane while integration/adversarial tests run. Do not label failed controls as verified.

Choose the smallest maintainable stack. A single Python service with server-rendered pages is acceptable. Justify dependencies; do not build your own production web server or authentication system merely to avoid a small dependency.

Required views:

1. Overview
   Collector freshness, pipeline state, shadow equity, open risk, blockers.

2. Opportunities
   Model probability, executable price, fees, edge, size, and rejection reasons.

3. Positions/performance
   Simulated fills, pending settlements, P&L, and accounting basis.

4. Outcome Board
   Linked positions, account-impact ranking, horizons, and explicit bound labels.

5. Risk/capital
   Caps, reserves, remaining capacity, breaches, sizing constraints.

6. Experiments/sources
   Recorded results, provenance, stage status, source health, fee verification.

UI rules:
- Prominent SHADOW / NO REAL MONEY label.
- Starting bankroll clearly marked notional.
- No invented positions, signals, or profits.
- Empty state means NOT STARTED or NO DATA—not an unexplained zero balance.
- Optional synthetic demo data must be isolated and unmistakably labeled.
- Withdrawal recommendations remain unavailable.
- Cost-basis equity is not liquidation value.
- Bounds are not exact scenario predictions.
- Escape untrusted content.
- No arbitrary SQL/file/subprocess endpoints, debug dumps, or secret exposure.
- Read existing canonical calculations; do not create a second ledger/risk engine.
- Bind to 127.0.0.1 by default.
- No public hosting, tunnels, subdomain, DNS, or firewall changes.

Add endpoint, empty/stale/error-state, and mobile-layout tests, plus a fresh-install runbook.


WORKFLOW AND MERGE AUTHORITY

Use at most three independent specialist lanes:
- operating pipeline/deployment;
- adversarial risk/ledger review;
- local read-only UI.

One writer per area. Coordinator owns shared integration and state documents.

For every PR:
- reconcile with current main without overwriting active work;
- targeted tests, then full supported suite;
- experiment/frozen-artifact checks;
- Windows 3.12 verification when that environment is available;
- independent review for accounting, runtime, security, and deployment changes;
- resolve blockers;
- green CI on the final integrated revision;
- squash-merge only bounded correct work authorized here.

Merge and deployment are separate states. Record both revisions.

A blocked download, unavailable SSH, or upcoming timer must not halt independent repository work. Stop safely at access boundaries rather than working around them.

Keep the existing standing docs/tests merge rule; do not broaden it silently.


CROSS-SESSION CONTINUITY

Update HANDOFF and the execution plan after material integrations.

Preserve the October 22 deadline and update owner-idea readiness.

During long missions, publish compact progress checkpoints to GitHub using existing authorized access. Another assistant must be able to recover the state without the local Claude session.

Never publish private databases, keys, account details, or unlicensed feed content.

Do not reactivate the laptop capture merely because the owner is not remotely connected.


FINAL REPORT

Report:
- PRs and merges;
- tested main and deployed revisions;
- collector/timer status;
- laptop bridge remains disabled;
- valid real capture days;
- shadow decisions, fills, pending and completed settlements;
- fee verification;
- backup/restore results for evidence AND ledger;
- adversarial findings and unresolved risks;
- Gate 7 engineering versus research status;
- dashboard startup command and completed views;
- owner-only blockers;
- next action and October 22 roadmap impact.

Do not claim full live-market verification until a real capture day and eventual settlement have been observed. A no-trade day is a legitimate result.

Continue useful authorized work. Do not stop after a plan or wait idle for a future collection window.
