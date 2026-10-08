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
| A | Baseline, scope, reconciliation | coordinator | EXECUTION_PLAN, owner records, this ledger | MERGED | #164 `3481369` (scope record + plan entry; #153/#158/#161/#162/#163 reconciled and merged; #161 deployed `9ed305e` on 2026-10-07; evidence in HANDOFF.md, "2026-10-07 production update") | Keep the ledger current |
| B | API, payoff and account conformance pack | wire lane | `docs/execution/`, `execution/conformance.py`, fixtures | MERGED | #167 `8dd572c`; 111 facts, DOCUMENTED/FIXTURE_TESTED only | Venue observation (R/S) |
| C | Isolated security boundary | coordinator | ADR 0043, `tests/invariants/test_execution_boundary.py`, `test_no_execution_paths.py` | MERGED | #164 `3481369`; 8 review rounds ending APPROVE at bb6e725 (structural capability, tamper and runtime-immutability rules) | History and secret scan before any credential (package O) |
| D | Durable intent journal | journal lane | `execution/journal.py` | MERGED | #165 `0bac2b9`; 3 review rounds: blocker (cancel released on local fills only) and 4 should-fixes fixed; 448 tests | **Bump the schema version before any persistent store exists** (the version-1 schema changed in place while unmerged) |
| E | Atomic reservations and fencing | journal lane | `execution/reservations.py` | MERGED | #165 `0bac2b9`; cross-process race tests; provider-id ownership is unique | — |
| F | Signer and transport | wire lane | `execution/signer.py`, `transport.py`, `kalshi_wire.py` | MERGED | #167 `8dd572c`; 409 on a write is AMBIGUOUS; exact refill; FIXTURE only | DEMO opener with the pinned `REAL_OPENER_REQUIREMENTS` (needs decision 1) |
| G | Complete account reads | G lane | `execution/account.py`, fixtures | MERGED | #172 `4c6e938`; 2 review rounds | Follow-ups: `record_account_snapshot` should accept caller problems; the journal should record amended client ids; re-id-on-amend residual (attribution could pick a sibling attempt; capacity stays held) |
| H | Order lifecycle reducer | lifecycle lane | `execution/lifecycle.py`, `fake_venue.py` | MERGED | #166 `dd93a8f`; 3 review rounds (two blockers fixed) | Provisional constants are listed below |
| I | Risk and strategy tickets | I lane | `execution/risk_gate.py`, `risk.py`, `reservations.account_view`/`inventory_for`, ADR 0044 | MERGED | #171 `a287c8c`; 2 review rounds; full suite 5515 passed / 0 failed | **Open before leaving FIXTURE:** bind `account_genesis` to the journal's genesis (it is caller-supplied today) |
| J | Feed and account recovery | J lane | `execution/recovery.py`, orchestrator stream wiring, ADR 0046 §11/§13 | MERGED | #177 `1065c25`; 3 review rounds (HIGH: quarantine cleared by venue data older than the anomaly; boot-order MEDIUM); 22/22 mutations caught; full suite 6037 passed / 0 failed | All nine private-stream venue facts are UNKNOWN (`STREAM_FACTS`; the conformance pack excludes WebSockets). Follow-up: a same-worker reboot takes the lease before validating the journal (fails closed; ADR 0046 §2) |
| K | Orchestrator and fixture runner | K lane | `execution/orchestrator.py`, journal control events and records, ADR 0046 | MERGED | #175 `1afe37f`; **demonstration B passes**: 60 seeded cycles (seed 20261007, summary hash `d331d6eb…`), with partial fills, conflicting signals, an outage, limits, faults, two process deaths and restarts; no duplicated exposure; reservations preserved. Fencing follow-ups (per-write lease re-read; a fenced instance stops) merged in #177; P-3 fill double-count fixed in #178 `8837311` | `fixture_cash_basis` is a FIXTURE-only declaration while cash basis is UNKNOWN (ACC-02). The account genesis is tied to a journal GENESIS record (partly closes I's open item). The orchestrator passes no priority to `send`: whatever wires it to the transport must mark reads and cancels protective |
| L | Kill and restart | coordinator | `execution/control.py` | CONTRACT MERGED | #170 `b67fcd2` (modes, latches, incidents, closeout authorizations, boot/replay); 4 review rounds | Wire into the orchestrator. **Requirement from H:** a cancel and an amend may both be in flight on one order: serialize them per order, or define recovery for answers that cross, and never block an emergency cancel |
| M | Account-aware shadow | after G–L | — | NOT_STARTED | — | Real reads are package S (BLOCKED_OWNER) |
| N | Private approval and Terminal | coordinator | `execution/control.py` (AutomationGrant, grant_problems) | GRANT CONTRACT MERGED (#170); UI NOT_STARTED | No grant is issued | Terminal journeys J5/J6/J9; the UI contract applies |
| O | Operations and recovery | after C/D/L/N | — | NOT_STARTED | — | Service user and keys need approval |
| P | Chaos and performance | P lane | `tests/execution/test_chaos*.py`, `test_load.py`, `chaos_support.py`, `docs/execution/PERFORMANCE.md` | IN REVIEW | Branch `exec/p-chaos`; found P-1 (refused boot wrote `Started`) and P-2 (stalled worker wrote after takeover), fixed in #177, and P-3 (fills double-counted near a read), fixed in #178 | Account history ceiling: past ~1,500–1,600 orders one read no longer fits the 80-request cycle budget, so the cycle is not COMPLETE and disarms |
| Q | Independent review | per PR | — | IN_PROGRESS | Execution PRs #164–#167, #170–#172 and #175–#178 each had an independent review ending APPROVE. The merged heads differ from the approved commit only by merges from main or declared docs-only additions (#165: package docstring, ledger and activation packet; #172: ledger text); #164's approval is at `bb6e725` (row C). Outside the execution package, wallet PR #174 (#168) had its R1 fix `6afb6c2` and docs `ebe9ad9` re-reviewed: APPROVE at `ebe9ad9` (probes: correction before observation re-times the signal, later correction ignored, no later knowledge leaks); its merged head `642775b` adds only a merge of main (#173, docs). That re-review was recorded only in the session, and is recorded here | Integrated review of the whole system before T |
| R | Authorized demo rehearsal | — | — | BLOCKED_OWNER | — | Demo account, key and approval |
| S | Authorized production-read rehearsal | — | — | BLOCKED_OWNER | — | Read-scope key and approval |
| T | Readiness certificate | — | — | NOT_STARTED | — | Needs A–S as the profile requires |

## Facts that must be confirmed before anything leaves FIXTURE

These are values or semantics the offline code depends on that the documentation leaves open. Each has
to be confirmed against the venue (DEMO_OBSERVED or PRODUCTION_READ_VERIFIED) before it is relied on.

- **`lifecycle.TIMESTAMP_SKEW` (provisionally 2 s).** If the venue's fill stamps and snapshot times drift
  further apart than this, normal flows quarantine falsely. With it, `account.CLOCK_SKEW` (provisionally 5 s) and
  the venue's user-data lag (`max_data_lag`, 1 min) bound when a count is true: an order
  listing's fill count is taken as true somewhere between the snapshot's `observed_at` and
  `ReadManifest.data_true_by` (the latest of read end + `CLOCK_SKEW`, the closing as_of and the read's latest order
  or fill stamp); fills stamped in between are never added on top of it and leave fees incomplete (ADR 0046 rule 14,
  P-3). No fill of a read is ever added on top of that read's own count. A venue clock leading ours by more than
  `CLOCK_SKEW` makes the read not COMPLETE (orders and fills unknown, so it disarms) when the opening as_of or any
  order or fill stamp shows it (USER_DATA_AS_OF_IN_FUTURE, RECORD_STAMPED_IN_FUTURE); a lead hidden by a lagging
  as_of with no recent record goes undetected. If the venue's real lead or lag is routinely near these values,
  reads disarm or fees stay incomplete more often.
- **`lifecycle.NOT_FOUND_MIN_DELAY` (provisionally 30 s).** It compares our clock with the venue's.
- **Whether the available balance already excludes cash held by resting orders.** This drives
  `reservations`' venue-held credit.
- **What a 409 on a repeated `client_order_id` means.** It is treated as AMBIGUOUS.
- **The meaning of `reduce_to`.** It is refused.
- **Whether `post_only` crosses or rejects, and whether an amend keeps time priority.**
- **How sales are charged fees.** The risk gate's fee bound for a sale uses the buy formula at the worst price at
  or above the limit, which assumes Kalshi charges sales the same way.
- **API-key scopes.** Kalshi's api_keys page documents no permission scopes, no read-only keys, no
  withdrawal permission settings and no IP allowlist (checked 2026-10-07). A production-read key would
  therefore be able to trade if stolen. See Decision 2 of `KALSHI_OWNER_ACTIVATION_PACKET.md`.
