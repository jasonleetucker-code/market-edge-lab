# Execution Plan

The only record of **what is authorized now**. Owner decisions override this file, and should
be written here when they are made.

## Current gate

| # | Gate | State |
|---|---|---|
| 1 | Data collection | **Complete.** Collectors, provenance, source health, freshness and immutable evidence (PR #2); NWS CLI and settlement-evidence collectors, pagination and pacing (PR #8). Scheduled read-only forward collection **authorized 2026-09-22** (see below; ADR 0012). |
| 2 | Settlement validation | **PASSED 2026-09-22 (PR #8, merged 22d217b).** 799 daily events audited (including a fresh 2024 validation with the procedure frozen first), 0 mis-predictions under the final procedure, 0 unexplained mismatches; see `experiments/EXP-001-kxhighny-nws-vs-market/gate2/REPORT.md` and `docs/SETTLEMENT.md`. |
| 3 | Historical dataset | **PASSED 2026-09-22 (PR #14, merged 2f5d640; Windows portability fixes PR #15, 7c93f78).** Point-in-time dataset EXP-001-pit-v2 (3,551 days, 3,551 usable, SHA-256 `1794b23c…`), train-only descriptive analysis, EXP-001 PREREGISTERED and frozen; see `experiments/EXP-001-kxhighny-nws-vs-market/gate3/`. |
| 4 | Baseline model | **EXIT CRITERIA MET 2026-09-22 (PR #18).** The frozen baseline was implemented; validation selected V1; the test split was opened once; **Stage A PASS** (model − R0 +1.253, 95% CI [+1.147, +1.362]; PIT coverage 0.806 ∈ [0.75, 0.85]). EXP-001 is `RUNNING` (Stage B pending). A Stage A pass is not evidence of an edge; see `experiments/EXP-001-kxhighny-nws-vs-market/gate4/REPORT.md`. Closed: the owner approved Gate 5 on 2026-09-22. |
| 5 | Market-vs-model | **PASSED 2026-09-23 (PR #22).** The domain-neutral opportunity engine (ADR 0013): contracts for event, market, executable quote, model estimate and opportunity; executable Kalshi prices (never mid or last); versioned fees (`kalshi-quadratic-taker-v1`, `UNVERIFIED_CURRENT_SCHEDULE`, so no result is claimable); fail-closed freshness; explicit liquidity; machine-readable rejection reasons. EXP-001 probabilities and forward books plug in (`edge-lab forward opportunities`). An independent review found one blocker (settlement equivalence), which was fixed and re-reviewed with no blocker. CI is green on the exact head. |
| 6 | Simulated / shadow trading | **PASSED 2026-09-23 (PR #23).** Append-only, hash-chained shadow ledger with all account state derived by replay (ADR 0014). The fill policy is deterministic (`latency-confirmed-v1`, the frozen EXP-001 execution model). The sizing foundation has hard caps and fractional Kelly. `edge-lab shadow run|settle|account`. No real-order path. The independent review found no blocker; 4 should-fix items were fixed and re-reviewed. CI is green on the exact head. The P0 risk/capital foundation (issue #6) and the Outcome Board backend (issue #3) were then built under the same directive (PR #24, ADR 0015): shadow only, with no withdrawal recommendation. Gate 7 engineering was authorized on 2026-09-23. |
| 7 | Adversarial validation | **Engineering authorized 2026-09-23** (daily-shadow directive): adversarial software tests on disposable stores, risk/ledger/timing/execution fault handling. **Engineering suite merged (PR #26):** `tests/gate7/`, `docs/engineering/GATE7_FINDINGS.md`. F01–F08 and F10–F13 are FIXED; F09 (no external anchor for the ledger head) is an open, documented limitation; checkpoint export/verify support landed in PR #37 (ADR 0021), and F09 stays OPEN until an independent checkpoint is stored and verified off-host. The dashboard review (PR #28) added reporting fixes. **Production evidence: none** (the daily pipeline is not yet deployed). **Research evidence: none.** Gate 7 research needs real Stage B days; the EXP-001 180/365-valid-day looks are unaffected. **Not passed.** |
| 8–10 | Paper/shadow → tiny real money → scaling | Not authorized. |

## Owner authorization record

- **2026-09-22, gate 2 → gate 3.** Directive recorded verbatim (acceptance criteria,
  merge authority, after-merge steps) in `docs/owner/2026-09-22-gate2-directive.md`. It
  stated: "You are also
  explicitly authorized to merge the resulting Gate 2 PR yourself when all acceptance
  criteria and CI requirements below are satisfied", and "If and only if Gate 2 passed:
  update `docs/EXECUTION_PLAN.md` to indicate Gate 3 is now the active gate." Gate 3
  becomes active when PR #8 merges. The directive also said not to begin model
  optimization in that PR.

- **2026-09-22, gate 3 → gate 4.** Directive recorded verbatim in
  `docs/owner/2026-09-22-gate3-directive.md`. It authorized merging the Gate 3 PR once all
  21 acceptance criteria hold, CI is green on the exact final head, the PR is mergeable and
  independent review has no unresolved correctness blocker. It also said: "If and only if
  Gate 3 passed: update `docs/EXECUTION_PLAN.md` so Gate 4 becomes active. Gate 4 should
  then begin with: «Implement the frozen baseline model and evaluate it on the predeclared
  train/validation/test protocol.» Do not perform that evaluation in the Gate 3 PR."
  PR #14 merged (2f5d640), so Gate 4 is active.

- **2026-09-22, Gate 4 lanes and scheduled read-only collection.** Recorded verbatim in
  `docs/owner/2026-09-22-gate4-collection-directive.md`. In summary:
  - **Scheduled collection** is authorized: read-only, unattended collection of public,
    unauthenticated Kalshi market/order-book data and the required public NWS data, on the
    existing Chase Upside VPS.
    - This includes fixed-time timers, the EXP-001 decision window plus its 10–15 min
      re-check, Market Edge's own storage, logs, health monitoring, failure alerts,
      backups, bounded retries and resource limits.
    - Precondition: a resource and isolation review shows that the Brisket application is
      not materially endangered. That review passed on 2026-09-22 (ADR 0012,
      `docs/deploy/VPS_REVIEW_2026-09-22.md`) and is re-run immediately before install.
    - It runs as a separate service and repository. No agent adds, replaces or rotates
      SSH keys. Owner-only steps (sudo, DNS, TLS, credentials) are prepared, then handed to
      the owner as exact commands.
  - **Merge authority:** agents may squash-merge PR #13 and this lane's docs, collector and
    Gate 4 PRs only when all of these hold:
    - the PR is reconciled with current `main`;
    - the Gate 3 / EXP-001 frozen artifacts are untouched;
    - an independent read-only review finds no unresolved correctness blocker;
    - CI is green on the exact final head;
    - the PR is mergeable.
  - **Attended laptop bridge:** allowed for a single window if the VPS is not yet live.
    No laptop scheduler may be left behind.
  - **Still excluded:** orders, trading credentials, authenticated trading APIs, deposits
    and withdrawals, funded accounts, paid APIs, subscriptions or hosting, and automatic
    financial decisions.

- **2026-09-22 (late ET), overnight build directive.** Recorded verbatim in
  `docs/owner/2026-09-22-overnight-build-directive.md`. In summary:
  - **Gates:**
    - Gate 5 (market-vs-model) is authorized now.
    - Gate 6 (simulated/shadow trading) is authorized only if Gate 5 passes.
    - The P0 risk/capital foundation (issue #6) is authorized only if Gate 6 passes.
    - The Outcome Board backend/domain layer (issue #3) is authorized only if the ledger
      and risk contracts are stable.
  - **Merge authority for this directive's PRs.** Agents may squash-merge only when all of
    these hold:
    - the PR is reconciled with current `main`;
    - the frozen EXP-001 artifacts are not improperly altered;
    - an independent read-only review finds no unresolved blocker;
    - CI is green on the exact final head;
    - the PR is mergeable;
    - the gate's acceptance criteria are actually met.
    Do not weaken a gate to meet the 30-day schedule.
  - **Laptop bridge:** it is a manual emergency fallback only, run when the VPS collector
    fails and the owner explicitly invokes it. No laptop scheduler is allowed.
    Runbook: `docs/deploy/EMERGENCY_LAPTOP_BRIDGE.md`.
  - **Still excluded:**
    - real orders, authenticated trading APIs, trading credentials;
    - funded accounts, deposits and withdrawals;
    - paid APIs, data or services;
    - real-money risk and automatic financial execution;
    - sports, sportsbook, crypto, equities, generic web/news scraping, dashboard styling,
      DNS/TLS/subdomains, and automatic withdrawals.

- **2026-09-23, daily shadow operation directive.** Recorded verbatim in
  `docs/owner/2026-09-23-daily-shadow-directive.md`. The owner authorizes:
  1. bounded daily official settlement-evidence collection on the existing VPS;
  2. scheduled opportunity evaluation, simulated bookkeeping and shadow settlement using
     stored evidence;
  3. Gate 7 adversarial engineering work and tests;
  4. a local, read-only, mobile-friendly dashboard over existing research and shadow data;
  5. review, testing and squash-merging of this mission's bounded PRs.

  Each PR must be reconciled with `main`, pass the targeted tests, the full suite and the
  frozen-artifact checks, and get an independent review for accounting, runtime, security
  or deployment changes. Blockers must be resolved and CI green on the final revision.

  Merge and deployment are separate states: deployment runs reviewed merged code only,
  under the existing edgelab isolation, and never during 17:40–18:35 America/New_York.

  **Not authorized:**
  - real orders or authenticated trading APIs;
  - deposits, withdrawals or funded accounts;
  - paid services or new credentials;
  - sports, crypto or equity expansion;
  - public dashboard exposure, DNS/TLS, tunnels or firewall changes;
  - unrelated Brisket changes;
  - SSH-key changes, OS upgrades or reboots;
  - Gate 8 or any real-money work.

  The laptop bridge stays a manual emergency fallback only.

- **2026-09-23, integration and production directive.** Recorded verbatim, with the
  owner's four clarifying answers, in
  `docs/owner/2026-09-23-integration-production-directive.md`. The owner authorizes:
  1. verifying the production collector on chaseupside through the owner's existing SSH
     access (no key requested, copied or added);
  2. deploying the reviewed, merged daily-shadow and settlement code with
     `docs/deploy/DAILY_SHADOW_ACTIVATION.md`, and enabling `edgelab-shadow.timer` and
     `edgelab-settlement.timer`;
  3. preserving the owner-supplied Kalshi fee-schedule PDF as evidence, and correcting the
     fee verification state where it supports that, without rewriting frozen EXP-001
     assumptions;
  4. the seven-day starter policy `STARTER_MAX_7D_V1` as an operational eligibility policy.
     It is enforced prospectively in the operational shadow account only; the research
     account is never touched;
  5. updating the canonical owner-idea process (re-planning at each new idea);
  6. a provider-neutral notification layer, with no paid SMS provider;
  7. GATE7-F09 design, tests and non-scheduled checkpoint support code. F09 stays OPEN;
  8. after the P0 work, bounded read-only foundations for:
     - Polymarket US public market data;
     - The Odds API free tier: the adapter foundation only (fixtures, a quota model,
       redaction and the owner's setup step). The free key is a **read-only data-feed
       credential**:
       - only the owner installs it, in server or local environment configuration;
       - agents never create, request, see or commit it;
       - no key exists yet.

       A live pull needs the key installed **and** an owner-approved activation and quota
       plan (issue #29);
     - Novig public daily data;
     - a venue capability registry with execution authorization false by default;
  9. squash-merging this directive's PRs when their acceptance conditions are met.

  **Not authorized:**
  - any order or order submission to any venue, trading credentials, one-click or
    automatic trading;
  - deposits, withdrawals or funding;
  - paid APIs or paid SMS, and Action PRO or Outlier purchases;
  - DNS or public dashboard exposure;
  - unrelated Brisket changes;
  - SSH-key changes, apt upgrades or reboots;
  - new scheduled jobs, including a scheduled ledger anchor or scheduled Odds API pulls;
  - configuring any SMS provider (Twilio, Telnyx, SNS or similar), paid or free tier;
  - Polymarket International, VPN or geolocation circumvention, or any authenticated
    Polymarket US endpoint. Polymarket US uses documented public US interfaces only, with
    one bounded smoke test where the terms and availability permit;
  - network calls in CI;
  - presenting Novig end-of-day files, or de-vigged sportsbook probabilities, as executable
    prices;
  - sports models or sports strategy. This directive supersedes the earlier sports and
    sportsbook exclusion only for the read-only data foundations listed above (§12);
  - any gate advance. The current gate stays at 7.

  **Status (end of 2026-09-23 session):**
  - Repository work merged in PRs #34, #35, #37, #38 and #39.
  - Production verification and deployment NOT DONE (no SSH route from the cloud session).
    They are owner-run, with the command sheet in `HANDOFF.md`.
  - F09 OPEN.
  - Gate unchanged at 7.

  Fee claims distinguish `claim_basis` NONE, CONSERVATIVE_BOUND and EXACT (ADR 0017).
  KXHIGHNY decisions from 2026-09-23T13:39:48Z carry CONSERVATIVE_BOUND for a direct
  member. A claim subtracts 0.0101 USD per contract before it counts. The
  no-scheduled-change check must be re-done by 2026-10-23.

## Standing merge rule: docs-only and test-only PRs

Owner rule of 2026-09-22 (verbatim source: `docs/owner/2026-09-22-overnight-build-directive.md`).
It is standing and not limited to one directive. A docs-only or test-only PR may merge
without another approval when **all** of these hold:

- it is reconciled with current `main`;
- CI is green on the exact head;
- it is mergeable;
- no review blocker is open;
- it changes no runtime code;
- it advances no gate;
- it weakens no acceptance criterion;
- it changes no credentials or deployment;
- it changes no financial authority.

A PR that fails any of these needs the usual authority: a directive grant or the owner.

## Authorized now (no further approval needed)

- Read-only collection from free, public, unauthenticated sources that the registry lists
  (`src/edge_lab/sources.py`), with each source's terms respected.
- Collector, provenance, freshness, health, storage and test infrastructure.
- Documentation, ADRs, experiment specifications in `DRAFT`, and research write-ups.
- Settlement-rule capture and re-audit for KXHIGHNY, read-only (`edge-lab settlement`).
- **Gate 4 work:** implement the frozen EXP-001 baseline exactly
  as preregistered (`experiments/EXP-001-kxhighny-nws-vs-market/experiment.toml`,
  `preregistration.json`, `gate3/DESIGN.md` §5–6); select V1/V2 on validation by the frozen
  rule; evaluate Stage A on the test split **once**; report the result whatever it is.
  Any change to the frozen spec is a dated `[[amendments]]` entry made *before* the test
  evaluation, or a new experiment.
- **Gate 5 work:** the market-vs-model opportunity engine as scoped in the 2026-09-22
  overnight directive.
  - Everything is computed from stored evidence; nothing places, simulates against live
    endpoints, or authenticates.
  - The fee schedule is versioned. A schedule that has not been verified against a
    primary source is labelled `UNVERIFIED_CURRENT_SCHEDULE`, and no claim of proven net
    profitability may rest on it.
  - Historical executable prices are never manufactured.
- **Gate 6 work, once Gate 5 has passed and merged:** the append-only shadow ledger,
  deterministic simulated fills, the shadow account, and the position-sizing foundation.
  Simulation only. Then, conditionally, the risk/capital foundation and the Outcome Board
  backend, as described in the directive.
- **Forward Stage-B collection (read-only, scheduled)** on the Chase Upside VPS, as scoped
  in the 2026-09-22 authorization above and ADR 0012. It covers:
  - the KXHIGHNY event, markets and order books in the EXP-001 decision window, plus the
    re-check capture;
  - the NWS PFMOKX forecast;
  - health status, alerts and verified backups.
  Collection is evidence gathering. Stage B *evaluation* for EXP-001 still needs a Stage A
  PASS, and it simulates only: it never sends orders.

- **Daily shadow operation (2026-09-23 directive):**
  - scheduled settlement-evidence refresh with bounded GETs;
  - the `shadow daily` orchestration: evaluation from stored evidence, simulated
    decisions, fills and settlement, summaries and receipt;
  - backups of the evidence DB and the shadow ledger.

  All of it runs on the VPS under edgelab isolation, after the re-check window.
- **Gate 7 engineering:** adversarial tests and fixes against disposable stores. Never run
  against production.
- **Integration directive work (2026-09-23):**
  - fee evidence and the multi-component fee verification;
  - `STARTER_MAX_7D_V1`, the venue capability registry and the execution-ticket
    contract (the ticket is a data contract only, and execution stays disabled);
  - the notification contract with local sinks only;
  - ledger checkpoint export and verify on demand;
  - the read-only Polymarket US and Novig public-data adapters. Live access is limited to
    one bounded Polymarket US smoke test and manual reads of Novig's published daily
    files, where the terms permit;
  - The Odds API adapter, on fixtures only. A live pull waits for the owner's key and an
    approved activation plan.

  None of these add a timer.
- **Local read-only dashboard** bound to 127.0.0.1, with no public exposure. Merged in PR #28
  (`edge-lab dashboard`, `docs/DASHBOARD.md`). It is local only: hosting, DNS/TLS, tunnels
  and firewall changes remain unauthorized.

## Explicitly not authorized

- Any order placement, order simulation against live endpoints, or authenticated trading client.
- Credential creation or storage, or funded accounts. One exception, directive §10 and
  issue #29: the owner may install The Odds API free read-only key in server or local
  environment configuration. Agents never create, request, see or commit it.
- Paid data or AI services, and any signup that creates an ongoing cost.
- Strategy optimization or parameter searches; any model variant, threshold or window not
  in the frozen EXP-001 spec; evaluating the test split more than once, or changing the
  experiment after seeing test performance.
- Any real-money step (gates 8–10), any live-order path, and any Stage B *evaluation*
  for a model that did not pass Stage A.
- Scheduled or unattended jobs **outside** the 2026-09-22 read-only VPS authorization and
  the 2026-09-23 daily-shadow authorization,
  including GitHub Actions cron, any paid host, and any authenticated source, without new
  owner approval.
- Browser automation against any source whose terms have not been reviewed and recorded.

## Cost policy for unattended infrastructure

Unattended infrastructure is not free just because no separate server was bought. This
repository is private. GitHub Actions minutes on a private repository come out of the
account's included allowance, and depending on plan and settings they can become billable
usage. (Allowances and prices change, so check current GitHub documentation rather than
trusting a number written here.) Any proposed scheduled collector must, before approval:

1. estimate its runtime per run and its minutes per month;
2. start at low frequency and increase only when evidence shows the extra data is needed;
3. bound each run (job `timeout-minutes`, request timeouts, bounded retries);
4. state how usage will be watched and how the job is switched off.

## Gate exit criteria

- **Gate 1 → 2:** repeated runs append immutable snapshots; per-source health is recorded;
  freshness is reported; a failure in one source does not lose the others.
  *(Met by PR #2: see `HANDOFF.md` for the evidence.)*
- **Gate 2 → 3 (met 2026-09-22):**
  1. Capture the official settlement source and rules as versioned evidence.
  2. Document the observation window, timezone, rounding, revisions, and missing/void provisions.
  3. Reproduce at least 30 historical resolved KXHIGHNY markets from the named settlement source,
     with zero unexplained mismatches.
  4. Measure how the settlement value relates to NWS CLI and NWS forecasts.
     *Amended 2026-09-22:* the CLI part was measured (739/739). The **forecast** part is
     moved to gate 3, because it needs the point-in-time forecast dataset. It is also not
     among the owner's 11 gate-2 acceptance criteria (recorded verbatim in
     `docs/owner/2026-09-22-gate2-directive.md`), which govern this gate. Recorded here
     rather than silently dropped.
- **Before any experiment leaves DRAFT:** the deterministic preregistration baseline now
  exists (`edge-lab experiments freeze`, validator check, CI `check-frozen`). Use it.
- **Gate 3 → 4 (met 2026-09-22; the owner's 21 criteria in
  `docs/owner/2026-09-22-gate3-directive.md` govern):** a point-in-time dataset for EXP-001, where each row records what was
  known at decision time (forecast issuance, receipt time, freshness); a settlement label
  from Kalshi `expiration_value` or the §4 CLI value; documented gaps; and a frozen EXP-001
  preregistration.
- **Gate 4 → 5 (the owner approved the transition on 2026-09-22):** the frozen baseline is implemented with tests, validation selection is
  recorded, Stage A on test is run once and reported (pass or fail) in EXP-001's log, and
  the owner decides whether and how Stage B collection proceeds. *(All met on 2026-09-22:
  PR #18 implemented and tested the baseline, recorded the V1 selection, ran Stage A once
  (PASS) and logged it; the owner authorized read-only scheduled collection on the Chase
  Upside VPS. The owner approved Gate 5 in the overnight directive.)*
- **Gate 5 → 6 (the owner's criteria, verbatim list in the overnight directive):** Gate 5
  passes only if all of these hold:
  - reusable contracts exist;
  - EXP-001 probabilities plug into them;
  - forward Kalshi books plug into them;
  - executable prices are correct;
  - fees are explicit;
  - freshness fails closed;
  - liquidity is explicit;
  - deterministic rejection reasons exist;
  - no historical quote is fabricated;
  - tests pass;
  - independent read-only review finds no blocker;
  - CI is green on the exact final head.
- **Gate 6 → risk foundation:** Gate 6 passes only if all of these hold:
  - the lifecycle works end to end;
  - the portfolio reconstructs from the ledger;
  - the fill policy is deterministic;
  - risk sizing is explicit;
  - no real-order path exists;
  - tests pass;
  - independent review finds no blocker;
  - CI is green on the exact head.
