# Market v1 acceptance manifest

**Version 1.0, 2026-10-07 (evening), America/New_York.** Basis:
- owner directive `docs/owner/2026-10-07-market-v1-autonomy-wallet-directive.md`;
- scope in `docs/EXECUTION_PLAN.md`;
- intent in issues #160 and #168.

Package state lives in `KALSHI_EXECUTION_LEDGER.md`, which stays the one execution ledger. This file defines what
"v1 complete" means and where each requirement stands. It authorizes nothing.

**Classes:**
- `DONE_V1`: shipped and merged for v1.
- `REQUIRED_V1`: must ship before SOFTWARE_V1_COMPLETE.
- `BLOCKED_EXTERNAL`: needs an owner, provider or rights step.
- `LATER`: wanted, but not a v1 dependency.
- `REJECTED`: decided against, with the reason.

A deferred item is not implemented. A disabled path counts only if it is intentionally disabled and its
underlying software meets its acceptance.

## 1. Readiness tracks (each judged on its own evidence)

| Track | State | What changes it |
|---|---|---|
| SOFTWARE_V1_COMPLETE | NOT MET | Every REQUIRED_V1 row below is DONE_V1, with no essential runtime TODO and no manual DB repair |
| OFFLINE_AUTONOMOUS_LOOP_VERIFIED | NOT MET | Demonstration B passes on the real orchestrator (§5) |
| DEMO_LIFECYCLE_VERIFIED | NOT MET; BLOCKED_EXTERNAL | Activation packet decision 1, then package R |
| PRODUCTION_ACCOUNT_SHADOW_VERIFIED | NOT MET; BLOCKED_EXTERNAL | Activation packet decision 2, then package S |
| AUTOMATION_READY_FOR_DECLARED_PROFILE | NOT MET | Package T, computed from evidence; any unresolved critical safety gap blocks it |
| STRATEGY_QUALIFIED | NONE | A named strategy meets its own evidence requirements. No strategy qualifies today; wallet research has produced no result |
| LIVE_AUTHORIZED | FALSE | A separate owner grant |
| UNATTENDED_LIVE_AUTHORIZED | FALSE | A separate later owner grant, after reliable incident delivery |

## 2. Operator journeys (Terminal shell, existing tokens and components)

Every journey must render these states: real, empty, stale, missing, error, blocked, paused and incomplete. That
means no mock balance shown as real, no silent zeros and no fake readiness badges. Each journey needs 360 px,
1440 px and 200%-text screenshots inspected.

| # | Journey | Class | Acceptance |
|---|---|---|---|
| J1 | Setup / readiness | REQUIRED_V1 | Every missing permission, environment, provider fact or approval is named with its safe next step, derived from EXECUTION_PLAN, the ledger and the activation packet |
| J2 | Sources | REQUIRED_V1 | Due, attempted, succeeded, current, complete, provenance, cost and failure for each source. Extends the existing Data sources view |
| J3 | Opportunities | REQUIRED_V1 | Contract, mechanism, evidence, executable economics at our size, fees and rejection reasons. Extends the existing opportunities view |
| J4 | Wallet intelligence | REQUIRED_V1 (research) | Public-history coverage, selection date, leader vs follower results, category fit, uncertainty and copying status, on fixtures until a source is approved |
| J5 | Portfolio / orders | REQUIRED_V1 | Actual vs synthetic holdings, cash, reserves, pending and unknown orders, fills, partial exits, settlement and complete P&L, from the execution journal. FIXTURE-labelled until real reads exist |
| J6 | Automation | REQUIRED_V1 | Active grant and scope, current state (DISARMED … BOUNDED_AUTO), next action, limits, stop reasons, the rearm procedure and incidents |
| J7 | Research / learning | REQUIRED_V1 | Candidate, development, shadow, qualified and rejected states, with protected evidence still protected |
| J8 | Outcome board | DONE_V1 (backend), REQUIRED_V1 (integration) | Real-world outcomes for actual permitted positions, from canonical records (#3) |
| J9 | Private command surface | REQUIRED_V1 | Authentication and authorization, CSRF and same-origin checks, anti-replay, expiring exact-command approvals; no signer in the browser and no arbitrary execute endpoint (package N) |

## 3. Execution and automation (packages from the ledger)

| Pkg | Class | Note |
|---|---|---|
| A, C | DONE_V1 | #164 |
| D, E | DONE_V1 | #165 |
| H | REQUIRED_V1 (in merge) | #166, reviewed and approved |
| B, F | REQUIRED_V1 (in merge) | #167, reviewed and approved |
| I | REQUIRED_V1 (in progress) | The risk gate and account projection; removes the `risk → shadow_ledger` edge |
| G | REQUIRED_V1 | Complete account reads on fixtures: live and historical partition, pagination, subaccounts |
| J | REQUIRED_V1 | Stream and account recovery on fixtures |
| K + ORCH | REQUIRED_V1 | The supervised orchestrator (`execution/orchestrator.py`) and the fixture runner. One service, bounded queues, expired backlog rejected after restart, starts DISARMED |
| L | REQUIRED_V1 | Kill and restart; must handle crossing cancel and amend answers (ledger requirement) |
| M | REQUIRED_V1 (software); BLOCKED_EXTERNAL (verification) | Account-aware shadow; S verifies it |
| N | REQUIRED_V1 | Private approvals, automated-policy grant objects and validation. No grant is issued |
| O | REQUIRED_V1 (software); BLOCKED_EXTERNAL (keys, service activation) | Service units shipped disabled; backups and restore drills; secret runbooks; history secret scan before any credential |
| P | REQUIRED_V1 | Chaos and load suite on synthetic workloads |
| Q | REQUIRED_V1 | Independent review of every material PR, plus the integrated system |
| R, S | BLOCKED_EXTERNAL | Activation packet decisions 1 and 2 |
| T | REQUIRED_V1 (computation); its verdict depends on R and S | Certificate computed from evidence |

## 4. Wallet intelligence (issue #168; outside the execution package)

The owner (`wallet_intel.py`) is PLANNED. It extends `sources`/provenance, `research_evidence` lineage and
`research_economics`, with no second ledger or scheduler.

| # | Package | Class | Acceptance |
|---|---|---|---|
| W1 | Source and observability matrix | REQUIRED_V1 | Polymarket international and US, Kalshi, Bitcoin, Solana/EVM DEX and Hyperliquid, across every directive §7 dimension. Polymarket Data API v2 is pinned from the docs (v1 retirement announced for 2026-10-24) |
| W2 | Normalized wallet events and identity | REQUIRED_V1 | Every §8 field. Several fills per transaction stay distinct; proxy mappings are time-versioned; transfer, split, merge and reward are not directional; corrections are appended |
| W3 | Leader reconstruction | REQUIRED_V1 | Cash-flow-aware accounting with unknown cost basis kept as unknown, the §9 separations, and dimensions with uncertainty and shrinkage. No single score |
| W4 | Point-in-time selection manifest | REQUIRED_V1 | `discovered_at`, `selected_at` and label versions. Failed and disappeared wallets are retained; walk-forward selection with clustered dependence |
| W5 | Follower replay and copyability | REQUIRED_V1 | The follower timeline starts at our observation time, with depth, fees, slippage, partial fills and exits. Size and delay ladders; benchmarks per §10. Unknown fills are never wins |
| W6 | Follower policy and attribution | REQUIRED_V1 | Virtual attribution separate from inventory; no cash or inventory reuse; no shorts from missed entries; no catch-up by default |
| W7 | Defensive and threat tests | REQUIRED_V1 | Every §11 and §20 scenario, as tests |
| W8 | Typed bridge to execution | REQUIRED_V1 (software), disabled | The wallet → opportunity → risk-gate path, with no execution capability in the wallet code |
| W9 | AI-assisted filters | LATER | Deterministic baselines first. A model is added only after a measured gain, versioned, with no authority |
| W10 | Live public reads, paid feeds, empirical evaluation | BLOCKED_EXTERNAL | A recorded approval, rights, budget and a #96 slot |
| W11 | On-chain execution | LATER | A separate conformance profile; not a v1 dependency |

## 5. Demonstrations (each with reproducible commands, versions, hashes, logs and pass/fail)

- **A. Wallet research.** Synthetic events → classify and reconcile → point-in-time eligibility → follower
  replay → full position reconciliation → leader/follower difference shown. Synthetic data proves engineering
  only. REQUIRED_V1.
- **B. Autonomous core.** Repeated fixture cycles through the real orchestrator, with partial fills,
  conflicting signals, source loss, limits, process death and restart. Pass means no duplicated exposure,
  reservations preserved and a safe shutdown with no per-order intervention. It never bypasses fake-venue
  confinement. REQUIRED_V1.
- **C. Authorized external rehearsal.** Demo, then production read-only. BLOCKED_EXTERNAL.

## 6. Whole-roadmap placement for v1

| Domain | Class | Reason |
|---|---|---|
| EXP-001 weather (Gate 7 research) | DONE_V1 (operations) / continuing research | Collection and shadow are deployed; research needs calendar days |
| EXP-002 NFL pregame | Continuing research | Its protocol and timing are unchanged |
| NHL evidence (#134) | DONE_V1 (collection) | Development-only evidence |
| In-play (#122) | LATER for live; offline DONE_V1 | Needs a recorder approval |
| RFQ (#145) | LATER | NARROW decision; needs access and a slot |
| Public markets (#88) | LATER | Queued by slot and economics |
| Outside capital (#83) | LATER / BLOCKED | Legal, entity and custody prerequisites |
| SMS (#33) | BLOCKED_EXTERNAL | Provider approval |
| Multi-agent / generic agent platform | REJECTED (for now) | ADR 0006: no measured need |
