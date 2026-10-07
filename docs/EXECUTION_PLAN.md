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
| 7 | Adversarial validation | **Engineering authorized 2026-09-23** (daily-shadow directive): adversarial software tests on disposable stores, risk/ledger/timing/execution fault handling. **Engineering suite merged (PR #26):** `tests/gate7/`, `docs/engineering/GATE7_FINDINGS.md`. F01–F08 and F10–F14 are FIXED; F09 (no external anchor for the ledger head): support landed in PR #37 (ADR 0021); closed for the anchored history on 2026-09-23 (independent checkpoints stored and verified off-host), with the ADR 0021 residual. The dashboard review (PR #28) added reporting fixes. **Production evidence (2026-09-23):** the daily pipeline is deployed and verified; the first valid Stage B day (2026-09-24) was captured and booked (2 shadow fills per account), and settlement is not yet observed (`docs/deploy/PRODUCTION_ACTIVATION_2026-09-23.md`). F09 is closed for the anchored history (two independent checkpoints). **Research evidence:** 2 valid Stage B days (2026-09-24, 2026-09-25; production verification 2026-09-25 01:57Z, `HANDOFF.md`), which is not evidence of an edge. Gate 7 research needs many real Stage B days; the EXP-001 180/365-valid-day looks are unaffected. **Not passed.** |
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
  - Production verification and deployment were not done from that cloud session (no SSH
    route). They were done later the same day by the owner's local session under the
    production activation directive below.
  - Gate unchanged at 7.

  Fee claims distinguish `claim_basis` NONE, CONSERVATIVE_BOUND and EXACT (ADR 0017).
  KXHIGHNY decisions from 2026-09-23T13:39:48Z carry CONSERVATIVE_BOUND for a direct
  member. A claim subtracts 0.0101 USD per contract before it counts. The
  no-scheduled-change check must be re-done by 2026-10-23.

- **2026-09-23 (afternoon ET), SSH grant and production activation directive.** Recorded
  verbatim in `docs/owner/2026-09-23-production-activation-directive.md`.
  - **SSH grant.** The owner's local Claude Code session may use the existing access to
    chaseupside:
    - `dynasty` by default;
    - root only for the exact privileged steps of a reviewed runbook.
    - It must not change SSH configuration or keys, disable root SSH, alter sudo rules,
      harden the host, apt-upgrade, reboot or touch unrelated Brisket code. Those are
      separate future security tasks.
  - **Authorized:**
    - verify production;
    - deploy reviewed merged `main` with `docs/deploy/DAILY_SHADOW_ACTIVATION.md` only;
    - enable `edgelab-shadow.timer` and `edgelab-settlement.timer`;
    - run the fail-closed dry runs;
    - verify backups and restores and Chase Upside health;
    - export the first manual F09 checkpoint and store and verify it off-host;
    - bounded non-live-money follow-ups: Polymarket US depth, the payoff guard and tick
      grid, an ntfy sink with no real send, execution-ticket checks, Windows portability;
    - review and squash-merge this mission's PRs.
  - **Not authorized:**
    - real orders, trading credentials, deposits or withdrawals, funded or automatic
      trading;
    - paid APIs or paid SMS;
    - DNS or public dashboard exposure;
    - unrelated Brisket changes;
    - new SSH keys, apt upgrades, reboots;
    - any real ntfy send without separate owner approval;
    - any new scheduled anchoring job.
  - **Status:** production evidence is in `docs/deploy/PRODUCTION_ACTIVATION_2026-09-23.md`,
    the F09 evidence is in `docs/engineering/GATE7_FINDINGS.md`, and the current state is in
    `HANDOFF.md`. PRs #42 (ADR 0023), #43, #44 (ADR 0022) and #45 merged, each independently
    reviewed with CI green on the exact head.

- **2026-09-23 (~14:10 ET), private phone access to the dashboard over Tailscale.** Recorded
  verbatim in `docs/owner/2026-09-23-tailscale-private-dashboard-directive.md`; PR #46,
  ADR 0024.
  - **Authorized, narrowly:**
    - the official Tailscale client on chaseupside, with `--netfilter-mode=off` and
      `--accept-dns=false`;
    - joining the owner's tailnet;
    - the read-only dashboard on 127.0.0.1:8765 (`edgelab-dashboard.service`), published to
      the tailnet only with Tailscale Serve;
    - a Host-header allowance for the exact Serve name.
  - **Not authorized:** Tailscale Funnel or Tailscale SSH, firewall, nginx, DNS or SSH
    changes, public exposure, credentials, orders.
  - `edgelab-dashboard.service` runs continuously. It is exempt from the activation sheet's
    "no running `edgelab-*` unit" install check and is restarted after each install.

- **2026-09-23 (~15:00 ET), Market Edge Terminal v1 UI directive.** Recorded verbatim in
  `docs/owner/2026-09-23-terminal-v1-ui-directive.md`; owner requirement issue #47; ADR 0025.
  - **Authorized:** the dashboard's presentation-layer redesign; its read-only presentation
    routes (`/market`, `/alerts`, `/more`, a demo-only `/gallery`); local static assets
    (self-hosted IBM Plex fonts and a Lucide icon subset with their licences); small
    same-origin JavaScript enhancements; fixture-based browser testing with development-only
    tooling; canonical design documents (`docs/design/`); reviewed squash-merge of this bounded
    UI mission; and updating the already-private dashboard through the existing approved
    release path after tests and review pass, outside 17:40–18:35 America/New_York and never
    during an active capture.
  - **Not authorized:** any change to models, qualification thresholds, fees, sizing,
    balances, settlement, risk limits or frozen experiments; collector schedules, source
    permissions or account connections; live orders, deposits, withdrawals or paid services;
    Tailscale membership or policy, Funnel, public ports, DNS or SSH keys; unrelated Brisket
    services. The application stays read-only and SHADOW / NO REAL MONEY.
  - **Priority:** the shared UI foundation is NOW / P0, ahead of discretionary new feature
    screens, without delaying collection or an urgent correctness repair. 2026-10-22 is
    unchanged.
  - **Standing UI acceptance rule (from this directive).** Every user-visible change follows
    `docs/design/UI_CONTRACT.md`: canonical shell, tokens, components, formatting and state
    vocabulary; real, empty, stale, error, unsupported and blocked states; semantic parity with
    canonical results (amounts, risk verdicts, account scope, frozen outputs); reviewed
    mobile and desktop browser evidence. The PR template
    (`.github/pull_request_template.md`) asks for each item. Tests detect violations; reviewed
    screenshots are still required.

- **2026-09-24, Brisket health repair and next-phase build directive.** Recorded in
  `docs/owner/2026-09-24-brisket-health-and-next-phase-directive.md` (the owner's four
  corrections verbatim). Gate 7 is unchanged and **not passed**.
  - **Authorized (shadow/research only):**
    - **Stake sizing v2.** A challenger research engine, counterfactual replay, a simulation
      study and a research report. Later, a read-only dashboard recommendation labelled
      RESEARCH SIZING. The operational shadow account keeps `EXP-001-fixed-1-v1`, and the
      frozen research account and preregistration are untouched. v2 may influence shadow
      fills only after a separately recorded sizing experiment passes its own acceptance
      criteria.
    - **Multi-venue comparison.** One best-price-for-size comparator over the shared depth,
      grid, fee, equivalence and venue primitives, using only the honest claim labels in the
      directive.
    - **Polymarket US evidence.** Rules and fee evidence taken from official Polymarket US
      documentation only. A split (50-50) cancellation payoff is represented and refused,
      never treated as binary.
    - **The Odds API free tier.** An NFL pilot covering h2h, spreads and totals for one
      region.
      - The owner installs the read-only key in the server secrets file; agents never
        create, request, see or commit it.
      - One bounded smoke read after the key exists. Then one scheduled unit
        (`edgelab-odds.timer`) running a game-relative capture policy: about T-24 h, T-6 h
        and T-60 min per event, discovered through the quota-free events endpoint.
      - Hard ceiling of 450 credits per month, or the provider's remaining quota if lower.
      - Before enabling: the schedule is enumerated, worst-case and expected credits are
        computed, and every snapshot's target time is persisted.
      - Excluded: player props, paid tiers, betting accounts and execution.
    - **ntfy.** The first real ntfy push is approved.
      - The existing sink is wired into the existing dispatch layer.
      - A high-entropy private topic on the free hosted `ntfy.sh` is kept only in the server
        secrets file, never in Git or logs.
      - One non-sensitive test send. Only SUBMITTED is recorded; phone delivery is not
        claimed without direct evidence.
      - Headlines stay fixed and minimal.
    - **F09.** Manual checkpoints, roughly weekly and after a notable ledger event (the first
      settlement, a settlement conflict, a significant ledger or risk-schema migration, or
      before and after a recovery that affects ledger durability). **No F09 timer.**
    - **Roadmap.** A Domain Readiness matrix, with states only and no numerical score. The
      domain sequence: weather, then sports data, sports models, macro, crypto, energy,
      business/tech, culture, politics, long tail.
  - **Not authorized:** real-money trades, deposits, withdrawals, trading credentials, Gate 8+,
    live execution, paid APIs or services, SMS, public exposure or Funnel, disabling Tailscale,
    SSH key / sshd / sudo / root-login changes (root SSH hardening is a separate future
    security task), OS upgrades or reboots, broad macro/crypto implementation, retuning EXP-001
    or changing its sizing, criteria or history.
  - **Status (2026-09-24, verified on production):** merged and deployed as `ced77b8`: PRs #57
    (ntfy relay, ADR 0028), #58 (comparator, ADR 0027), #59 (Odds API pilot, ADR 0029; evidence
    schema v5, forward-only with a tested manual rollback) and #60 (sizing v2 research, ADR 0026).
    One ntfy test was SUBMITTED. `edgelab-odds.timer` is installed and disabled until the owner's
    key exists. Operational fills are unchanged (`EXP-001-fixed-1-v1`); EXP-001 is untouched.
  - **Operations:**
    - No Market Edge install or restart from 17:40 to 18:50 America/New_York, nor while a
      settlement job runs (around 11:15 and 16:15 ET).
    - Before any install, check that no `edgelab-*` capture job is running.
    - Deploy only merged code, through `docs/deploy/DAILY_SHADOW_ACTIVATION.md`.

- **2026-09-24 (morning), next build chunk directive.** Recorded in
  `docs/owner/2026-09-24-next-build-chunk-directive.md`.
  - **Authorized (research/shadow only):**
    - the sizing-v2 counterfactual runner (derived replay store; never the canonical ledger);
    - the read-only RESEARCH SIZING panel and the multi-venue comparator UI in Terminal v1;
    - later/closing-price capture: schemas, CLI, capture logic, tests, runbook and **manual**
      capture only;
    - notification origin/provenance and delivery policy;
    - Odds API work that needs no key;
    - the #50 coverage audit and safe P0 storage fixes;
    - settlement verification and a manual F09 checkpoint after the first real settlement;
    - review, merge and deploy of that work through `docs/deploy/DAILY_SHADOW_ACTIVATION.md`.
  - **Not authorized at the time of this directive:** a new unattended timer for later/closing-price
    capture. **Superseded only for that timer by the owner's 2026-09-24 11:24 ET follow-up below.**
    The other exclusions remain: any change to operational shadow fills or the frozen EXP-001 rule;
    orders, money, credentials, paid services, public exposure, SSH changes, Brisket changes.

- **2026-09-24 11:24 ET, owner follow-up: freshness and later/closing-price schedule.**
  - The owner confirmed the first ntfy TEST did **not** reach the phone. SUBMITTED remains only
    provider acceptance; end-to-end delivery is unresolved and must not be claimed.
  - The owner explicitly approved a scheduled later/closing-price capture.
  - **Authorized:** ADR 0030 Option A: `edgelab-observe.timer` (:05/:20/:35/:50 each hour) and
    `edgelab-observe-close.timer` (04:57:45 UTC), both `Persistent=false`, using the existing
    read-only `observe plan/capture` path, protected windows, collector lock, pacing, bounded GETs,
    append-only evidence and fail-closed semantics. Implementation, tests, reviewed merge and deployment
    through `docs/deploy/DAILY_SHADOW_ACTIVATION.md` are authorized.
  - **Still not authorized:** orders, real money, trading credentials, paid services, Gate 8+,
    weakening freshness/provenance rules, or broad new unattended collectors not covered by this
    approval.
  - Issue #74 records the longer-term requirement for one cross-domain Freshness Orchestrator.
    These ADR 0030 timers are an immediate evidence-preservation step and should later migrate under
    that shared primitive without changing their evidence contract.

- **2026-09-24 (evening), Freshness Fabric v1 + sports prospective data directive.** Recorded in
  `docs/owner/2026-09-24-freshness-fabric-sports-directive.md`.
  - **Authorized (research / read-only):**
    - Freshness Fabric v1 in `src/edge_lab/freshness.py` (a subordinate module allowed), observing
      existing schedules as EXTERNAL_SCHEDULE with parity tests; no migration of working timers;
    - one bounded Freshness supervisor timer (about every 5 minutes, local/status-oriented,
      network-free preferred);
    - a Polymarket US NFL research pilot on `polymarket_us.py`: public, unauthenticated catalog
      discovery at most every 6 hours, and target-based research book captures around
      T-24h / T-6h / T-60m;
      - caps: NFL only, max 20 markets per slot, max 50 GETs per run, pacer 0.5 s or slower,
        5-minute hard runtime, bounded retries;
      - enabled only after a terms/access review, worst-case request/runtime and storage
        estimates, failure tests, independent review and exact-head CI green;
    - a deterministic, versioned sportsbook consensus research benchmark from stored Odds API
      snapshots (no extra credits);
    - a per-domain research-readiness report;
    - Terminal v1 views for freshness, Odds targets, consensus and related markets;
    - review, merge and deployment through `docs/deploy/DAILY_SHADOW_ACTIVATION.md`.
  - **Not authorized:**
    - orders, accounts, trading credentials, money movement, Gate 8+;
    - buying credits or upgrading the Odds API; Action PRO; Outlier; player props; other sports;
    - authenticated scraping, CAPTCHA, paywall or geoblock bypass, VPN evasion;
    - a sports prediction model, auto-retraining, any EXP-001 change;
    - public dashboard exposure, Brisket changes;
    - ntfy work (out of scope for this mission).

- **2026-09-24 (evening, later), cross-domain prospective evidence directive (#86).** Recorded in
  `docs/owner/2026-09-24-cross-domain-prospective-evidence-directive.md`.
  - **Authorized now (planning, research, and non-production code/docs):**
    - the cross-domain acquisition portfolio;
    - source-readiness classification;
    - the combined resource budget;
    - the Multi-City Weather v1 design, including bounded read-only public verification GETs of
      market families, rules and stations (small counts, paced, documented).
  - **Authorized, gated, one source at a time:** bounded, read-only prospective collectors from
    free, legitimately accessible public sources, keyless first (§64, §65, §67, §82). Each must:
    - be in the portfolio with a market-relevance statement, an outcome/label plan, a completeness
      definition and a storage policy;
    - pass a terms/access review;
    - have a worst-case resource budget, with the combined VPS footprint recomputed;
    - register in `sources.py` and run as a #74 Freshness Fabric provider (no new generic
      scheduler);
    - follow the point-in-time contract (PROSPECTIVE_CAPTURE separate from HISTORICAL_BACKFILL;
      MISSED never backfilled);
    - roll out incrementally (fixture → sample → bounded smoke → low-frequency collection →
      several clean runs) with independent review and exact-head CI green before merge and deploy.

    The first such collector is Multi-City Weather v1, and it starts only after the Freshness Fabric
    + sports mission's lanes are merged and deployed.
  - **Owner action required (never done by agents):** free-key sources (READY_FOR_OWNER_KEY). Agents
    create no accounts and never handle keys.
  - **Not authorized:**
    - paid or licensed data;
    - trading, execution, Gate 8+, risk-limit changes;
    - EXP-001 changes or new operational models or strategies;
    - broad web, social or news scraping;
    - unnecessary donor PII;
    - storing unbounded crypto ticks;
    - per-domain schedulers or evidence databases;
    - extending 2026-10-22 automatically.

- **2026-09-24 (night), #88 Public Markets Edge.** Owner directive in chat, reconciled into
  `docs/OWNER_IDEAS.md` as a first-class domain.
  - **Authorized now (research only):**
    - source and licensing research for equities, ETFs, options and futures; for each source:
      real-time vs delayed, venue vs consolidated, history, auth, cost, limits, retention, storage
      and redistribution rights, research-grade vs execution-grade;
    - SEC EDGAR and official-source ingestion planning;
    - paper/sandbox broker evaluation, **with no signup**;
    - architecture work so the shared primitives can represent public-market instruments.
  - **Keyless collectors** (e.g. EDGAR filing events for a bounded universe) fall under the #86
    gated rule: one source at a time, with terms review, budget, fabric provider, review and CI.
  - **Owner-only:** creating any account or key (including a paper-only broker account), after the
    security ADR for broker keys.
  - **Not authorized:**
    - paid market data (SIP, OPRA, CME real-time or historical, Cboe DataShop);
    - brokerage signup, funding, margin, short selling, derivatives permissions;
    - order-write credentials, paper or live orders (Gate 8+);
    - automated quote-page scraping.

  Every intraday experiment needs a rationale, trigger, windows, point-in-time features, costs,
  spread, slippage, latency, session rules, effective sample size, out-of-sample validation and
  prospective shadow criteria.
- **2026-09-24 (night), Polymarket US NFL pilot: owner risk decision.**
  - **The decision.** The owner decided ("its my risk decision. just do it") to run the PR #84
    pilot despite Polymarket US Terms §4–§5. The Terms review verdict stays "not cleared by the
    Terms themselves".
  - **An unverified permission text** (no sender, date or headers) is recorded as
    OWNER_ATTESTED_EXPRESS_PERMISSION — UNVERIFIED. It is not the basis for activation. Its stated
    conditions are honoured anyway: at most 100 requests per minute, attribution to Polymarket US,
    no redistribution.
  - **Authorized once PR #84 passes review and CI:** the pilot's discovery and capture timers,
    within ADR 0032's caps. Scope: public keyless gateway, NFL moneylines, RELATED_NOT_EQUIVALENT
    only.
  - **Not authorized:** trading, account credentials, orders, money movement, paid services,
    Polymarket International.

- **2026-09-24 ~22:10 America/New_York (2026-09-25 UTC), MISSION: ECONOMIC EVIDENCE V1 (#96).** Recorded in substance in
  `docs/owner/2026-09-25-economic-evidence-v1-directive.md`. Strategy record and handoff:
  `docs/strategy/2026-09-24-evidence-to-economics-reset.md` and
  `docs/strategy/CLAUDE_ECONOMIC_EVIDENCE_V1.md`. Those two documents authorize nothing by
  themselves; this entry records the owner's scope for them.
  - **Authorized (this bounded batch only):**
    - two DRAFT research protocols, one per new family (not PREREGISTERED);
    - evidence consumption and attrition records;
    - an economic screen, including the size ladder and capacity sensitivity;
    - semantic conformance metadata (units, rules, fees, probability meaning, clocks, finality,
      rights);
    - a pure same-venue payoff evaluator;
    - stored-evidence sports pairing, a data-gap report, economics/capacity, and a compact view
      in the existing Terminal;
    - an execution-package ADR, **design only** (no transport);
    - canonical integration of #96;
    - review, merge and deployment of reviewed code under
      `docs/deploy/DAILY_SHADOW_ACTIVATION.md` (preflight PASS, protected windows).
  - **Research families.** Protected EXP-001 is unchanged. At most two new active hypothesis
    families:
    - **A:** narrow sportsbook information versus executable event-market pricing;
    - **B:** same-venue mathematical payoff relationships.

    Family A is stored-evidence research. It is **not** the excluded "sports model or sports
    strategy" of the 2026-09-23 directive: no winner model, no operational sports strategy.
  - **Not authorized:** live orders; authenticated paper orders; account signup; credential
    installation or readback; deposits or withdrawals; margin; paid data or services; outside
    investor capital; new timers or new production network scope; backup deletion; public
    dashboard exposure; any research or execution gate advance; changes to EXP-001 or
    `STARTER_MAX_7D_V1` semantics. `EXECUTION_NOT_AUTHORIZED` stays enforced.
  - **Unchanged.** Gate 7 is not passed. Collectors already authorized above (Odds API,
    Polymarket US pilot, ADR 0030 observations, the Freshness supervisor) continue under their
    existing authority until an explicit review. The 450-credit Odds cap is unchanged. The
    automatic twelve-city Multi-City Weather rollout is no longer the next build
    (`docs/OWNER_IDEAS.md`, roadmap re-run 2026-09-25); its design (#90) is kept.

- **2026-09-25 ~17:30 America/New_York, owner approval: Kalshi NFL capture.** During the Research
  Unblocking session (directive: `docs/owner/2026-09-25-research-unblocking-directive.md`) the owner
  wrote in chat, verbatim: "Approve Kalshi NFL capture." The coordinator records it bounded by the
  only proposal on record, `docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md` §6 ("The smallest
  justified capture extension"). Anything outside these bounds needs a new approval.
  - **Scope:** Kalshi `KXNFLGAME` only. Both team markets of each NFL game the Odds pilot already
    targets, at the pilot's existing T-24h / T-6h / T-60m target times. No NCAAF, no other market
    type, no new horizon.
  - **Requests:** Kalshi public, unauthenticated market data (`sources.kalshi_public`); no key,
    account, order endpoint or redistribution. Per game-horizon at most 1 listing + 2 book GETs,
    with at most one retry each (≤ 6). Settlement metadata: at most one settled-markets read per
    game day (≤ 7 a week). Bound: about 144 GETs in a normal week, **at most 288 + 7 a week**, and
    the existing per-run caps (24 markets, 40 GETs). **Zero Odds API credits**; the 450-credit cap
    is unchanged.
  - **Mechanism:** the existing `price_observations` collector and the existing `edgelab-observe`
    timer. **No new timer, unit or schema.** The shared Kalshi pacer, the collector lock and the
    protected windows (11:13–11:30, 16:13–16:30, 17:40–18:50 ET) apply. Pairing precision is a
    technical choice inside these bounds (proposal §6 options (a) or (b)); either needs the usual
    review.
  - **Research use:** stored evidence for DRAFT EXP-002 is development data until a genuinely
    future evaluation window is selected. Evidence use is logged; inspected outcomes are never
    relabelled as untouched.
  - **Review date:** 2026-10-22. **Pause/rollback:** stop planning NFL custom targets (proposal §6
    Rollback). Planned targets expire as MISSED with their reason; stored evidence is kept.
  - **Backup prerequisite:** `docs/OWNER_IDEAS.md` item 4 made backup retention a prerequisite
    before any new collector. That was an agent recommendation. The owner's later explicit approval
    governs this collector. The measured growth impact (proposal §6: about 0.7 MB a week) is
    reported in `docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md`. Backup deletion stays **not
    authorized**.
  - **Not changed:** every other prohibition above, and EXP-001.

- **2026-09-26 ~03:15 America/New_York, owner decisions: research economics, EXP-003, backup
  retention, off-host copy.** Recorded verbatim in
  `docs/owner/2026-09-26-owner-decisions-economics-backup.md`. These answer the 2026-09-25 decision
  packet.
  - **EXP-002:**
    - minimum useful effect $1,000/year after-cost, as the bar for continued development beyond the
      research/pilot stage; it is not a pilot requirement;
    - 6 owner hours through 2026-10-22 under the proposed stop rules;
    - the +8 h extension returns to the owner;
    - stays DRAFT.
  - **EXP-003:**
    - PAUSED; stays DRAFT. The owner stated no hours budget; the packet's 2 h awaits confirmation;
    - **sending the 8 drafted Kalshi questions is approved, but only after the owner confirms the
      exact final message** (`docs/research/KALSHI_QUESTIONS_2026-09-26.md`). The answers are
      shared venue-fact verification, including EXP-002 fees and fallbacks;
    - reject the current scope on 2026-11-15 if the relevant facts are unresolved (either Q1 or Q4
      unresolved or unfavourable, relying on the PROPOSED emergency-power scoping);
    - if answered earlier, economics first; no major development resumes merely because the
      questions were sent.
  - **Backup retention `proposed-v1`** for evidence-store local backups, **APPROVED** under the
    exact safeguards of `docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md` B4–B8:
    - deletion is manual and reviewed, with no timer-based deletion;
    - only eligible restore-verified copies may be deleted;
    - ledger, F09-linked, schema-change, baseline, unverified, quarantined and active copies are
      preserved as the policy states;
    - the reviewed dry-run is run immediately before any manual apply, and its actual candidate
      list is attached to the record;
    - original evidence is never deleted, and a checkpoint hash never replaces a restorable backup.
  - **Off-host O1 APPROVED:** a free weekly manual pull of the newest verified bundles to the
    owner's laptop, keeping the last 4, verified locally. The runbook and verification procedure
    are to be documented. **No paid cloud or object storage.**
  - **Not authorized by this:** live orders, paid data, new accounts, margin,
    deposits/withdrawals, a gate advance. EXP-001 is not retuned.

- **2026-09-28 ~20:00 America/New_York, owner directive: EXP-002 validation foundation + #122 in-play
  offline foundation + operational reconciliation.** Recorded in
  `docs/owner/2026-09-28-exp002-validation-inplay-foundation-directive.md`.
  - **Authorized (bounded):**
    - EXP-002 technical follow-through: a replacement pre-freeze gate, proposed freeze settings,
      fee and payoff verification from public documents, and a Terminal gate line;
    - #122 **offline** work: source and API feasibility research, an in-play evidence contract,
      a pure HOLD/REDUCE/EXIT policy evaluator, deterministic replay with isolated accounting,
      fixtures and synthetic nulls, and a read-only Terminal view;
    - one *proposed* in-play source-quality pilot packet (not approved);
    - canonical roadmap reconciliation.
  - **Not authorized:**
    - orders (real or authenticated paper), new account reads, credentials;
    - new production streams or scheduled acquisition, including any in-play polling or streaming
      (the 295/week pregame approval does not extend);
    - additional Odds spending or pregame cap increases;
    - paid data, margin/borrowing, deposits/withdrawals, outside capital;
    - a gate advance, or a third active research family (#96 limit; EXP-003's pause frees no slot
      automatically).
  - EXP-002's budget is not #122's budget. EXECUTION_NOT_AUTHORIZED stays enforced.

- **2026-09-29 ~13:15 America/New_York, owner directive: EXP-002 correctness continuation + bounded NHL
  prospective evidence.** Recorded in `docs/owner/2026-09-29-nhl-prospective-evidence-directive.md`; the
  durable owner record is issue #134. Owner statement: "Hockey starts tonight, so we need to start collecting
  data for that as well."
  - **Authorized (bounded):** implementing and **activating** a free/public NHL prospective evidence collector.
    NHL is DATA_COLLECTION / DEVELOPMENT_ONLY and not a research family.
    - The Odds API `icehockey_nhl`, `h2h` only: T-60m first; T-6h and T-24h only if the exact combined proof
      fits. It runs under the **one shared quota ledger and the 450-credit ceiling**. NFL keeps priority, and
      NHL never consumes an NFL reservation.
    - Kalshi `KXNHLGAME` only (public, keyless), under its own exact request bound, after EXP-001 and NFL in
      capture priority.
    - Private Terminal coverage.
  - **Gates:** exact quota proof, tests, independent review, exact-head CI, protected windows and deploy
    preflight. Opening night: missed horizons stay MISSED; manual observations are labelled as such and never
    relabelled.
  - **Supersedes, for NHL only:** the 2026-09-28 directive's "no new scheduled acquisition" and "no additional
    Odds spending", within the existing free ceiling. The NFL pregame approval (295/week), the NFL Odds caps
    and the ceiling are **unchanged**.
  - **Needs explicit owner approval before activation:** a paid tier, a higher ceiling or a materially larger
    budget, a new credential scope, a new timer or service, or high-frequency or in-play streaming.
  - **Not authorized:** orders, account reads, credentials, a gate advance, mixing NHL into EXP-002, or an NHL
    model. EXECUTION_NOT_AUTHORIZED stays enforced.

- **2026-09-30 ~02:20 UTC (2026-09-29 ~22:20 America/New_York), owner directive: complete roadmap integration +
  sports intelligence & RFQ feasibility v1.** Recorded in
  `docs/owner/2026-09-30-roadmap-integration-sports-intelligence-rfq-directive.md`; issue #145, PR #146.
  - **Authorized (offline, bounded):**
    - review and integration of the #145 roadmap consolidation;
    - PR A (R2): source, game-state and latency contracts, plus fill-conditioned economics, extending the existing
      `inplay_*` and `research_economics` owners; #122 gap extensions; an execution-modes gap note;
    - PR B (R4): an RFQ feasibility packet from public documentation, and an optional pure fixture-fed lifecycle
      component;
    - PR C: current-blocker reconciliation at document and test level, compact Terminal integration and R0–R11
      tracking.
  - **Constraints:** no network in tests, no credentials, no DB migration.
  - **Not authorized:**
    - account or credential access; authenticated streams or subscriptions;
    - new scheduled collection; any budget, ceiling, request-bound or protected-window change;
    - paid services; support-message sending;
    - RFQ creation, quoting, acceptance or confirmation;
    - orders, funding, margin, outside capital, a gate advance.
  - **Experiments:** EXP-001 frozen; EXP-002 scope unchanged; the #96 two-family limit stands, with no slot
    transfer from the paused EXP-003; the A.C tool is not run before about 2026-10-19.
    EXECUTION_NOT_AUTHORIZED stays enforced.
  - **Merge and deploy conditions (the directive's §18, owner's words in substance):** commit and push bounded
    branches; merge only with current-main reconciliation, the applicable delegation, independent review and
    required CI green on the exact final head (an old green result never substitutes); deploy only reviewed merged
    code under actual authority and the gated runbook; new acquisition and financial transport stay disabled unless
    separately approved. These are conditions, not a new grant. **The applicable delegation** for merging and
    deploying this batch's reviewed offline code is the owner's standing chat instruction, repeated across the coordinator sessions of 2026-09-22 to 2026-09-30: "keep going until everything is merged and deployed" (verbatim), bounded by these conditions and by every
    prohibition above. It delegates no financial, acquisition, credential or gate authority.

- **2026-09-30 (America/New_York), owner directive: architecture reconciliation and bounded hardening.**
  Recorded verbatim in `docs/owner/2026-09-30-architecture-reconciliation-directive.md`.
  - **Authorized (offline, bounded, for this task (#152) only):**
    - local inspection;
    - regression tests;
    - fixes to demonstrated gaps in existing canonical owners;
    - reconciliation of external architecture and agent-engineering ideas;
    - roadmap reconciliation;
    - a reviewable PR.
  - The result is in `docs/engineering/ARCHITECTURE_RECONCILIATION_2026-09-30.md`.
  - **Not authorized:**
    - deployment or any change to operating services;
    - orders, RFQs, credentials, spending, new timers or broader collection;
    - data-rights changes, public exposure or production-store mutation;
    - running the A.C calibration early, or any other protected outcome or markout inspection;
    - methodology changes or model promotion;
    - new infrastructure without a measured need and a separate decision. That covers a vector database, a
      second scheduler, a graph framework, a generic agent platform, a Calculator Steward transplant and a
      behavioural-eval harness (ADR 0006).
  - **Merge:** the directive allows merging only under documented authority that clearly covers the exact change.
    - This PR changes runtime code (`inplay_evidence.py`), so the standing docs/test-only rule does not apply.
    - The 2026-09-30 batch delegation covers that batch's code, not this change.
    - It therefore stops at a reviewed PR for the owner to merge. It grants nothing else.
  - **Merged 2026-10-07** by the owner's decision (answer 2 in
    `docs/owner/2026-10-07-kalshi-execution-campaign-directive.md`): squash `fcd46fe`, exact head `1592efb`,
    CI green. Deploy approved with #161's deploy (owner answer 4 in the same record).
- **2026-10-07 (America/New_York), owner directive: finish the Kalshi ordinary-event automation core (#160).**
  Recorded in `docs/owner/2026-10-07-kalshi-execution-campaign-directive.md` (authority sections verbatim, plus the
  owner's three answers). Campaign plan: `docs/strategy/KALSHI_AUTOMATION_DELIVERY_160.md` (PR #163), packages A–T.
  Boundary: ADR 0043.
  - **Authorized (offline, hard-disabled):**
    - the isolated execution package `src/edge_lab/execution/`, built under ADR 0043's file-exact rules. This
      covers the intent journal, reservations and fencing, the lifecycle, risk and ticket checks, the wire
      format, the signer, the transport, account reconciliation, kill and restart, account-aware shadow logic, and
      fixture-only Terminal work;
    - the isolated execution package may run in the FIXTURE environment only: a fake transport and disposable
      stores. Signing tests use keys generated at test time;
    - the matching revision of `tests/invariants/test_no_execution_paths.py` (path-exact exceptions only) and a new
      import-boundary invariant;
    - `cryptography` as an optional `execution` extra, imported only by `execution/signer.py`;
    - documentation, conformance research from public documentation, and owner setup and approval packets.
  - **Merge delegation:** agents may squash-merge this campaign's offline execution PRs when **all** of these hold:
    - an independent review, with re-review of changed heads;
    - required CI green on the exact final head;
    - current-main reconciliation;
    - mergeability;
    - no open review blocker.

    This is owner answer 1. It covers no credentials, no demo or production access, no deployment of an executor
    and no gate advance.
  - **Deploy:** PR #161 (the Polymarket capture-window fix) may be deployed through the runbook once reviewed and
    merged (owner answer 3):
    - code only;
    - outside the protected windows;
    - deployed SHA verified;
    - no timer, budget or schema change.

    The deploy is of the merged main SHA. It may also carry #153's reviewed in-play provenance fix and the merged
    test- and docs-only changes (owner answer 4). Nothing from the execution package is deployed.
  - **Not authorized (each needs its own recorded owner approval):**
    - DEMO or PRODUCTION egress, including any change to `execution.model.AUTHORIZED_ENVIRONMENTS`;
    - creating, installing, reading or requesting any credential, key or account;
    - demo mock orders and production account reads;
    - new market-data acquisition or streams;
    - any real-money order, and unattended automation (LIVE_AUTHORIZED and UNATTENDED_LIVE_AUTHORIZED stay false);
    - deposits, withdrawals, margin, borrowing or outside capital;
    - paid services and support messages;
    - changes to source budgets, protected windows or EXP-001/EXP-002 protocols;
    - a gate advance. Gates 8–10 stay not authorized.

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
- **Read-only dashboard** bound to 127.0.0.1 (PR #28, `docs/DASHBOARD.md`). On chaseupside it
  is reachable only from the owner's tailnet through Tailscale Serve (PR #46, ADR 0024).
  Public exposure, Tailscale Funnel, DNS/TLS for chaseupside.com, and firewall changes
  remain unauthorized.
- **Production-activation follow-ups (2026-09-23):**
  - Polymarket US depth ladders; the binary payoff guard and per-market price grids
    (ADR 0023).
  - The execution-ticket pre-submit control chain (data only; `EXECUTION_NOT_AUTHORIZED`
    always fails).
  - The ntfy sink (ADR 0022). It is disabled unless configured, is not wired into any run
    or timer, and **sends nothing without separate owner approval**. The owner gave that
    approval on 2026-09-24: wiring plus one test send (see the 2026-09-24 entry above).
  - Windows portability.

## Explicitly not authorized

- Any order placement, order simulation against live endpoints, or authenticated trading client. The ADR 0043
  execution package is offline code that runs in the FIXTURE environment only (2026-10-07 entry); it
  authenticates to nothing.
- Credential creation or storage, or funded accounts. One exception, directive §10 and
  issue #29: the owner may install The Odds API free read-only key in server or local
  environment configuration. Agents never create, request, see or commit it.
- Paid data or AI services, and any signup that creates an ongoing cost.
- Strategy optimization or parameter searches; any model variant, threshold or window not
  in the frozen EXP-001 spec; evaluating the test split more than once, or changing the
  experiment after seeing test performance.
- Any real-money step (gates 8–10), any live-order path, and any Stage B *evaluation*
  for a model that did not pass Stage A.
- Scheduled or unattended jobs **outside** the 2026-09-22 read-only VPS authorization, the
  2026-09-23 daily-shadow authorization, and the narrowly approved 2026-09-24 ADR 0030 observation
  timers, the 2026-09-24 evening Freshness supervisor and Polymarket US NFL pilot timers, including GitHub Actions cron, any paid host, and any authenticated source, without new
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
