# Owner directive, 2026-09-24 (morning): next build chunk

Source: the owner's message to the laptop Claude Code session, 2026-09-24 ~10:50 UTC. Title: "MARKET
EDGE LAB — NEXT BUILD CHUNK: Sizing Counterfactuals + Terminal Integration + Multi-Venue UI +
Closing-Price History + Alert Hygiene + Odds API Readiness + Learning-History Audit".

Recorded in substance, section by section. Every authorization, prohibition, bound and acceptance
criterion keeps the owner's wording. Where this record and a later owner decision disagree, the
later decision wins and is recorded in `docs/EXECUTION_PLAN.md`.

## Deliverables (all research/shadow)

1. **Sizing v2 counterfactual runner.** Extend the canonical sizing-v2 owner; never build a second
   engine.
   - Policies: A flat 1-unit, B fixed %, C full Kelly, D 1/2 Kelly, E 1/4 Kelly, F
     robust/pessimistic fractional Kelly, G drawdown-constrained Kelly, H the current candidate.
     Existing versioned semantics are preserved.
   - Replay uses only information available at the original decision time. Settlement is
     attached only after it became known.
   - Include every opportunity:
     - qualified;
     - rejected for edge, risk, capital horizon, stale or missing data, liquidity, or
       unsupported payoff or rules;
     - qualified but not filled;
     - filled;
     - settled.

     A zero size is recorded with its exact reason.
   - **Per-policy state.** Each policy has its own isolated state: bankroll, cash, committed
     capital, open risk, exposures, settlement timing, P&L, drawdown, high-water mark and capital
     release. It never overwrites the canonical shadow ledger.
   - **Metrics** are as listed by the owner. No statistical significance is implied from a few
     settlements.
   - **Output:** a versioned `CounterfactualSizingRun` with per-event rows.
   - **Deterministic tests** are required for:
     - leakage and isolation;
     - rejected opportunities and fees;
     - drawdown and capital release;
     - cluster exposure and fractional contracts;
     - fail-closed behaviour on missing data;
     - edge cases: edge size and sign, probabilities and prices near 0 or 1, bankroll near the
       reserve.
2. **Read-only Terminal v1 sizing panel.** Labelled RESEARCH SIZING or SHADOW SIZING CHALLENGER,
   never "Recommended bet".
   - Fields come only from the canonical sizing result.
   - A compact comparison across policies is allowed.
   - No stake input, no submit, no order action.
   - Unavailable states name the actual reason.
3. **Multi-venue comparator UI.**
   - Four distinct claims: best observed quote, best gross cost for the requested size, best
     verified total cost, best account-feasible route. No arithmetic in the UI.
   - Non-equivalent markets show "RELATED MARKET — NOT ECONOMICALLY EQUIVALENT", unranked.
   - The requested size is the evaluated or counterfactual size, with no arbitrary user entry.
4. **Later / closing price capture.** General, not sports-only.
   - **Phases:** decision, recheck, post_decision_1h, post_decision_6h, pre_close, close,
     settlement_preceding, custom.
   - **Stored per observation (the owner's list):** event id; market id; outcome/side; venue;
     native market id; source timestamp; receipt timestamp; bid; ask; available depth; price
     grid; freshness; rules identity/version; observation phase; target phase time; actual phase
     time; source hash; collection status; reason if missed. Repeated observations are kept and
     never overwritten.
   - **Close semantics (the owner's list):** for each venue/market type determine trading close
     time, event start, market suspension, settlement cutoff and the last valid executable quote
     before close; if exact close cannot be established, label it "latest pre-close
     observation", not "closing price".
   - **Derived later:** quote movement, implied probability movement, CLV-like metrics, our price
     vs later market, rejected-opportunity later movement, venue convergence, model-vs-market
     convergence.
   - **"Closing price" is defined carefully.** Otherwise the label is "latest pre-close
     observation".
   - Metrics come later; CLV is not proof of profit.
   - **Scheduling:** build the schemas, CLI, capture logic, tests, runbook, estimates and manual
     capture. A new unattended timer is **not** authorized. Present the exact proposed schedule as
     the owner-decision blocker.
5. **Notification hygiene.**
   - An explicit event origin: PRODUCTION / TEST / DEPLOYMENT_VERIFICATION / MANUAL_DIAGNOSTIC /
     REPLAY / DEMO.
   - Delivery policy by origin: DEPLOYMENT_VERIFICATION is stored and shown, never pushed as a
     production failure. A real production failure during deployment still alerts.
   - Suppression is never based on the clock.
   - Alerts UI distinguishes the origins.
   - Tests as listed.
6. **Odds API work that needs no key.**
   - Review and do not rebuild. Adversarial quota tests.
   - Event identity that never collapses distinct events.
   - Offered odds / implied / de-vigged / consensus kept separate, and never executable.
   - Prospective time-series storage per issue #50.
   - Preserve the game-relative schedule. Prove the month under 450 credits with provider cost
     semantics.
   - The dashboard shows SETUP NEEDED until a live read succeeds.
7. **Issue #50 learning-history audit.**
   - A durable coverage matrix across raw, market, model, decision, sizing, execution, outcome,
     later-market and operations data.
   - Gaps classified P0 (lost unless collected now) / P1 (reconstructable) / P2.
   - Fix the safe P0 gaps. Where a P0 gap needs a new scheduler authorization, build everything
     except the timer and record the exact blocker.

## Settlement checkpoint (~11:15 ET)

- Do not wait idle for it.
- No deploy or restart while `edgelab-settlement` is active.
- Afterwards, verify any first real settlement in full:
  - event and outcome, source, payout, fees and P&L;
  - state transition and cash release;
  - equity reconciliation for both accounts;
  - no duplicates, and the hash chain intact.
- Never repair the ledger by hand; diagnose.
- If the ledger changed materially, take the manual F09 checkpoint: a verified backup, export,
  copy off-host, store the repo copy, verify (new VERIFIED, previous EXTENDED), then delete the
  VPS temporaries. The cadence stays roughly weekly plus significant ledger events. **No F09
  timer.**

## Operating authority and safety

- **Authorized:** the bounded implementation, testing, documentation, PR, merge and deployment
  work described above. Ordinary engineering choices are made, documented and tested without
  asking.
- **Not authorized:**
  - real-money orders, exchange or broker submission;
  - deposits, withdrawals, funded-account actions, trading credentials;
  - Gate 8+, automatic live execution;
  - paid APIs or subscriptions;
  - public exposure, Funnel;
  - SSH configuration or root-login changes, OS upgrades or reboots;
  - changes to Brisket;
  - changes to the frozen EXP-001 research rule;
  - automatic replacement of the operational shadow sizing policy.
- **EXP-001 is frozen** (no retuning, resizing, reinterpretation, rewriting or criteria change).
  Operational shadow fills stay on their current policy. Sizing v2 is challenger and
  counterfactual only.
- **Production protection:**
  - no Market Edge install or restart 17:40–18:50 America/New_York, or while settlement runs
    (around 11:15 and 16:15 ET);
  - pre-install checks and backup, one runbook (`docs/deploy/DAILY_SHADOW_ACTIVATION.md`);
  - coding, tests, GitHub work and CI may continue in protected windows.
- **Quality:**
  - every code PR has targeted and full tests, frozen-artifact and invariant checks, independent
    review and re-review;
  - exact-head CI green;
  - no network in CI;
  - no production mutation from tests.
- **Parallelism:** bounded lanes with clean file ownership, one writer per file, and the
  coordinator owning the shared contracts.
- **Roadmap and handoff:** re-plan after the deliverables. Owner actions only when truly
  owner-only: the Odds API key (`EDGE_LAB_ODDS_API_KEY` in `/etc/market-edge-lab/secrets.env`,
  installed privately, never pasted in chat) and the ntfy phone subscription.

## Coordinator note (2026-09-24)

The field lists under Deliverable 4 were added after the original record, from the owner's
message, because the first record referred to them without listing them (review of PR #68).
