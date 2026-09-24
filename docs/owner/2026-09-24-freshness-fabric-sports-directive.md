# Owner directive, 2026-09-24 (evening): Freshness Fabric v1 + sports prospective data

Source: the owner's message to the laptop Claude Code session, 2026-09-24 about 16:45 ET. Title: "OWNER
DIRECTIVE — NEXT MAJOR BUILD CHUNK: FRESHNESS FABRIC V1 + SPORTS PROSPECTIVE DATA FOUNDATION +
SPORTSBOOK CONSENSUS RESEARCH LAYER + TERMINAL FRESHNESS / ODDS VISIBILITY".

Recorded in substance, section by section. Every authorization, prohibition, bound and acceptance
criterion keeps the owner's wording. A later owner decision wins, and is recorded in
`docs/EXECUTION_PLAN.md`.

## Purpose

Move Market Edge from a weather-centred research pipeline with several specialized collectors to a
multi-domain, continuously supervised market-research system. At the same time, start building the
prospective sports evidence that future sports-model experiments will need. The directive authorizes
bounded read-only/research work only.

## Scope

- **ntfy is out of scope.** The server path is proven clean. The remaining issue is the phone's
  subscription topic. Do not rotate the topic, send another test, change priority, or block on ntfy.
- **Freshness Fabric v1 (issue #74).**
  - One shared canonical abstraction, owned by `src/edge_lab/freshness.py`. A subordinate module is
    allowed; a competing scheduler abstraction is not.
  - **Concepts, at least:**
    - identity: source id, domain, acquisition mode (STREAM / POLL / EVENT_RELATIVE /
      RELEASE_DRIVEN / MANUAL / EXTERNAL_SCHEDULE);
    - policy: freshness objective (max useful age), minimum safe cadence, maximum useful cadence;
    - timing: intended time, next due, last attempt, last successful receipt, upstream and receipt
      timestamps, data age, upstream age;
    - health: source health, freshness FRESH / STALE / UNKNOWN;
    - scheduling state: DUE, NOT_DUE, MISSED, PAUSED, BUDGET_BLOCKED, QUOTA_BLOCKED,
      PROTECTED_WINDOW, LOCK_BUSY;
    - controls: pacing, budget or quota, protected windows, retries/backoff, policy version, and
      why the next run is due.
  - Unknown stays unknown, and missing is never zero.
- **Existing schedules stay as they are in v1.** Forward weather, the Odds API, ADR 0030
  observations and settlement are observed as EXTERNAL_SCHEDULE, not migrated. Deterministic parity
  tests run against their canonical contracts (at least forward weather, the Odds API and ADR 0030).
  A disagreement is reported, and production behaviour does not change silently.
- **Sports becomes the second prospective domain.** No predictive sports model. A Polymarket US
  NFL research lane is added on the existing `src/edge_lab/polymarket_us.py`; no second adapter.
- **Relationships fail closed.** Same teams is not equivalence. Default RELATED_NOT_EQUIVALENT
  until deterministic rules prove more, checking at least:
  - teams, date, start time, league;
  - regulation vs overtime, ties;
  - postponement, cancellation, no-contest, participant-start conditions;
  - settlement provider, alternative settlement, last-fair-market-price terms;
  - payout structure.

  PAYOFF_UNSUPPORTED, RULES_UNRESOLVED and RELATED_NOT_EQUIVALENT are never weakened to create a
  comparison.
- **Sportsbook consensus research layer (#9).**
  - Deterministic and versioned, built from Odds API snapshots already stored. No extra credits.
  - It is a RESEARCH BENCHMARK, never an executable price. Offered price and de-vigged consensus
    probability are never conflated.
  - Calculations: raw implied probability; paired de-vigged probabilities; contributing book count;
    median consensus; dispersion or range; source freshness; earliest and latest contributing update.
  - Spreads and totals are grouped by exact normalized line. Non-complementary markets are
    unsupported until their math exists.
  - No sharp-book weighting, strategy optimization or threshold change.
- **Sports prospective history (#50).**
  - Every observation must later answer:
    - offers, books, consensus and Polymarket US state;
    - source update and receipt times, and which source moved first;
    - misses, dispersion, the next horizon and the outcome;
    - what was knowable at that moment.
  - No second history database.
  - A generalized per-domain research-readiness / learning-history completeness report. Missing
    prerequisites are never shown green.
- **Terminal v1.**
  - A freshness/source view that makes clear where the fabric only supervises an external timer.
  - The Odds capture target/history table.
  - Sportsbook consensus labelled "RESEARCH BENCHMARK — NOT EXECUTABLE".
  - A related Polymarket US market in the existing across-venues section, labelled "RELATED MARKET —
    NOT ECONOMICALLY EQUIVALENT" and never ranked as cheaper.
  - No new global navigation.
  - States: populated, empty, no captures yet, stale, missed, unsupported, quota blocked, error,
    partial catalog, no related market, related but non-equivalent, source unavailable.
  - Reviewed at 360 px, 1440 px and 200% text.
- **Not touched:**
  - the frozen EXP-001 (model, parameters, threshold, decision time, fee assumption, fixed sizing,
    history, Stage A result);
  - operational sizing (sizing v2 stays evidence-limited and counterfactual only).
- **Production observations continue.** Verify observations, the close, Odds targets and the first
  real settlement from stored data as they occur. The first real settlement triggers a manual F09;
  F09 stays manual.

## New unattended authority (section 17)

1. **One Freshness Fabric supervisor timer,** about every 5 minutes, primarily local/status-oriented.
   - It runs in `edgelab.slice` with the existing hardening and a small CPU/memory cap.
   - It calls no paid API and has no order path, no credentials and no browser.
   - It does not duplicate existing captures and makes no 5-minute polling of upstream sources.
   - It writes one bounded current-status artifact. Network-free is preferred.
2. **Bounded Polymarket US NFL public catalog discovery,** at most every 6 hours.
3. **Bounded target-based Polymarket US NFL research book captures** around T-24h / T-6h / T-60m,
   for identified relevant markets.
   - Recommended caps: NFL only; public gateway only; max 20 markets per slot; max 50 GETs per run;
     0.5 s or slower pacer; 5-minute hard runtime; bounded retries.
   - A lower or safer bound is used where the architecture suggests one, and the reason is
     documented.

**Before enabling either networked scheduled source:**
- verify current source documentation and terms;
- calculate worst-case requests and runtime, and state storage growth;
- confirm no credentials or paid access;
- add explicit shutoff instructions;
- test failure and retry behaviour;
- have the deployment independently reviewed;
- require exact-head CI green.

These are research collectors only. No authenticated source is authorized.

## Still not authorized (section 18)

- **Money and accounts:** real orders; sportsbook or Polymarket trading accounts; trading
  credentials; deposits or withdrawals; automated bets; Gate 8.
- **Paid data:** buying API credits; upgrading The Odds API; Action PRO; Outlier.
- **Scope:** player props; other sports added silently.
- **Access:** scraping behind authentication; bypassing CAPTCHA, paywalls or geoblocks; using a VPN
  or VPS to evade eligibility.
- **Models:** a sports prediction model in this mission; auto-retraining; any change to EXP-001.
- **Other:** public dashboard exposure; unrelated Brisket changes.

## Standards (sections 19–20)

- **Every material lane:** targeted tests; the full suite; frozen-artifact and invariant checks;
  deterministic fixtures; zero network in CI; adversarial cases; independent review.
- **Deployment changes:** exact-head CI green, independent review, and deploy only merged `main`
  through `docs/deploy/DAILY_SHADOW_ACTIVATION.md`.
  - Never deploy in a protected window.
  - Before install: preflight and verified backups of both stores.
  - After install: verify every state independently.

## Roadmap effect (section 21)

| Item | Before | After |
|---|---|---|
| #74 Freshness Fabric | NOW | v1 implementation / supervision; not closed by v1 |
| Sports prospective data | NEXT | NOW |
| Odds target UI | NEXT | NOW |
| #9 sportsbook consensus | NEXT | research benchmark implementation |
| Sports predictive model | LATER | unchanged; needs a preregistered experiment |
| Cross-venue executable comparison | constrained | still constrained by equivalence and fees |

## Success criteria (section 22)

Market Edge can answer two questions:
1. "What data sources are currently fresh, what is due next, and why?"
2. "For an upcoming NFL event, what did major books offer at our scheduled horizons, what did the
   research consensus imply, and did Polymarket US have a related market at that same point in time?"

It must preserve raw evidence, timestamps, quota state, misses and failures, source freshness,
rules uncertainty, exact lines and the related-vs-equivalent distinction, and show all of this
cleanly in Terminal on the owner's phone.

## Coordinator contracts (set before the lanes start, so no two lanes fork an abstraction)

- **C1 — Freshness Fabric (Lane A).**
  - `freshness.py` owns:
    - the enums: `AcquisitionMode`, `ScheduleState`, and the existing `Freshness`;
    - the frozen records `SourcePolicy` (static) and `SourceFreshness` (one source at one instant);
    - the provider protocol `provider(context, now) -> list[SourceFreshness]`.
  - A subordinate module (e.g. `freshness_fabric.py`) may hold the registry, the providers for
    existing schedules, and the supervisor.
  - Existing schedules are read-only EXTERNAL_SCHEDULE providers; parity tests run against their
    canonical functions.
  - Status artifact: `/var/lib/market-edge-lab-status/freshness.json`, schema
    `freshness-fabric-status/1`. It holds the current state only, bounded in size.
  - CLI: `edge-lab freshness status`.
  - Unit: `edgelab-freshness.{service,timer}`, every 5 minutes, network-free (`AF_UNIX` only).
- **C2 — Polymarket US NFL pilot (Lane B).**
  - It reuses `polymarket_us.py` (catalog pagination and completeness, books, payoff guards, pacer)
    and stores through `SnapshotStore`. Any new table is additive, with a rollback stamp helper.
  - The relationship function returns RELATED_NOT_EQUIVALENT / UNMATCHED / AMBIGUOUS with reasons.
  - Its schedule is exposed through a C1 provider (the first domain designed on the fabric).
  - Units are separate from the supervisor. It spends no Odds API credit.
- **C3 — Consensus and readiness (Lane C).**
  - It extends the existing consensus in `odds_api.py`: exact-line grouping, median, dispersion,
    book count, freshness, and update-time bounds, all versioned.
  - The derived artifact builder is network-free.
  - The per-domain research-readiness report takes one canonical owner module.
- **C4 — Terminal (Lane D).** `src/edge_lab/dashboard/**` only, consuming C1–C3 through their
  public functions. No arithmetic in the UI.
