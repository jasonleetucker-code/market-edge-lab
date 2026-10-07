# Kalshi execution campaign — package ledger (#160)

The live state of packages A–T from `docs/strategy/KALSHI_AUTOMATION_DELIVERY_160.md`. Scope: `docs/EXECUTION_PLAN.md`
2026-10-07 entry. Boundary: ADR 0043. Update this file in the same PR as the work it describes.

**States:**
- `NOT_STARTED` / `IN_PROGRESS`
- `IMPLEMENTED` → `TESTED_LOCALLY` → `CI_GREEN` → `REVIEWED` → `MERGED`
- `BLOCKED_OWNER` / `BLOCKED_PROVIDER` / `UNSUPPORTED`

A package that needs a venue observation (demo or production) cannot pass `OFFLINE_TESTED` without that
observation.

## Readiness stages

| Stage | State | What would change it |
|---|---|---|
| OFFLINE_EXECUTION_CORE_COMPLETE | NOT MET | D–L, P and Q merged with fixture end-to-end and fault tests |
| DEMO_LIFECYCLE_VERIFIED | NOT MET; BLOCKED_OWNER | Owner demo setup plus a recorded approval to add DEMO to `AUTHORIZED_ENVIRONMENTS`; package R |
| PRODUCTION_ACCOUNT_SHADOW_VERIFIED | NOT MET; BLOCKED_OWNER | Owner production-read key scope and approval; package S |
| KALSHI_AUTOMATION_READY_FOR_DECLARED_PROFILE | NOT MET | Package T, computed from evidence |
| LIVE_AUTHORIZED | FALSE | A separate owner decision with a qualified strategy |
| UNATTENDED_LIVE_AUTHORIZED | FALSE | A separate later owner decision |

## Packages

| Pkg | Scope | Owner (lane) | Paths | State | Evidence | Next / blocker |
|---|---|---|---|---|---|---|
| A | Baseline, scope, reconciliation | coordinator | EXECUTION_PLAN, owner record, this ledger | IN_PROGRESS | #162 merged `5d750b1` (baseline NHL failures fixed); #153 merged `fcd46fe` (owner); #161 reviewed (APPROVE), fixes re-review pending; #158/#163 docs-only, CI re-running on main | Merge #158/#163 under the standing docs rule; full-suite baseline on the foundation head |
| B | API, payoff and account conformance pack | wire lane | `docs/execution/`, `execution/conformance.py`, fixtures | IN_PROGRESS | — | Public documentation only; every fact carries an evidence class |
| C | Isolated security boundary | coordinator | ADR 0043, `tests/invariants/test_execution_boundary.py`, `test_no_execution_paths.py` | IMPLEMENTED | Foundation PR | Independent review; history and secret scan before any credential |
| D | Durable intent journal | journal lane | `execution/journal.py` | IN_PROGRESS | — | — |
| E | Atomic reservations and fencing | journal lane | `execution/reservations.py` | IN_PROGRESS | — | Reuses `execution_ticket.reserve_simultaneous_obligations` |
| F | Signer and transport | wire lane | `execution/signer.py`, `transport.py`, `kalshi_wire.py` | IN_PROGRESS | — | FIXTURE only; test-generated keys |
| G | Complete account reads | coordinator, after F | `execution/account.py` | NOT_STARTED | — | Needs B's history and pagination facts |
| H | Order lifecycle reducer | lifecycle lane | `execution/lifecycle.py`, `fake_venue.py` | IN_PROGRESS | — | — |
| I | Risk and strategy tickets | coordinator, after D/E/H | `execution/risk_gate.py`, `risk.py` (account-projection refactor) | NOT_STARTED | — | Uses `risk.py` and `execution_ticket.py`, with no second formula; checks the opposite-side holding before every ENTRY; removes the pinned `risk → shadow_ledger` edge |
| J | Feed and account recovery | after G/H | — | NOT_STARTED | — | Reuses `inplay_evidence` sequence logic |
| K | Demo orchestration (fixture runner) | after F–J | — | NOT_STARTED | — | Real demo is package R (BLOCKED_OWNER) |
| L | Kill and restart | after D–J | — | NOT_STARTED | — | — |
| M | Account-aware shadow | after G–L | — | NOT_STARTED | — | Real reads are package S (BLOCKED_OWNER) |
| N | Private approval and Terminal | after I/M | — | NOT_STARTED | — | UI contract applies |
| O | Operations and recovery | after C/D/L/N | — | NOT_STARTED | — | Service user and keys need approval |
| P | Chaos and performance | incremental | — | NOT_STARTED | — | — |
| Q | Independent review | per PR | — | IN_PROGRESS | #161 reviewed | Every material PR |
| R | Authorized demo rehearsal | — | — | BLOCKED_OWNER | — | Demo account, key and approval |
| S | Authorized production-read rehearsal | — | — | BLOCKED_OWNER | — | Read-scope key and approval |
| T | Readiness certificate | — | — | NOT_STARTED | — | Needs A–S as the profile requires |
