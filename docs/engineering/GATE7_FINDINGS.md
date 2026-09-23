# Gate 7 adversarial engineering findings (EXP-001 shadow stack)

Scope: owner directive `docs/owner/2026-09-23-daily-shadow-directive.md`, PRIORITY 4 (A–D).
Suite: `tests/gate7/` (a test package; fixtures and helpers in `tests/gate7/conftest.py` and
`tests/gate7/gate7_support.py`). Reviewed at commit `8850e0b`. All destructive and fault tests run
on disposable `tmp_path` stores and ledgers. No test touches production, the network, or
the wall clock for correctness: every `now` is passed explicitly. The concurrency and lock tests
use real threads and processes, with hard timeouts.

This document does not claim profitability or any research result. See the evidence sections
below.

## How to read the tests

- **Defects** are tests that assert the correct behaviour and carry
  `@pytest.mark.xfail(strict=True, reason="GATE7-Fnn: ...")`. Once a fix lands, the test XPASSes,
  and strict mode turns that into a failure. Remove the marker in the same change that fixes
  the defect.
- **Plain tests** cover behaviour that is already correct. They guard against regressions.
- Tests for planned APIs call the API directly (for example `ShadowLedger.state_as_of`), with no
  import guard. Today they fail with `AttributeError`, which counts as the expected failure.

## Status after PR #26

All strict xfails were removed once their fixes landed: every former xfail test now passes
as a regression test. The independent PR-B review found one more blocker, which is fixed
and tested in `tests/test_shadow_accounts.py`: out-of-order fills, where a fill known
earlier than an already-recorded cash movement is refused. It also found should-fix items
covering same-day exposure ordering, stranded days, exceptions without a receipt, missed
capture days, per-event refresh errors, backup gating and the rollback runbook. They are
all fixed in the same PR (`tests/test_daily.py`, `tests/test_collectors.py`,
`tests/test_backup_ledger.py`, `tests/test_deploy_units.py`).

## Findings

| ID | Area | Severity | Defect | Failure scenario | Test(s) | Status |
|---|---|---|---|---|---|---|
| GATE7-F01 | A risk | BLOCKER | `exp001_shadow.run_day` never calls `risk.assess`. It enforces loss, drawdown and remaining-capacity limits only for display, after the fact. Sizing enforces the position, event, cluster, portfolio and reserve caps, but it does not know about daily or weekly loss, drawdown, or the rule that open worst-case exposure counts against loss headroom. | The day has already lost $10.00, exactly the daily limit, so capacity is 0 with no breach. All 3 signals still fill. Capacity is $0.30 and three signals costing $0.15 + $0.15 + $0.88 all fill. A DAILY_LOSS_LIMIT breach is reported and fills continue. $10 of open exposure leaves loss headroom at 0, and fills continue. | `test_gate7_risk.py::test_zero_capacity_without_breach_vetoes_every_fill`, `::test_concurrent_candidates_stop_at_exact_capacity`, `::test_one_cent_over_capacity_is_vetoed`, `::test_daily_loss_breach_vetoes_and_names_the_breach`, `::test_open_exposure_exhausting_headroom_vetoes` | FIXED (PR #26): pre-fill `risk_veto` on point-in-time state; NO_FILL RISK_VETO with binding persisted |
| GATE7-F02 | A risk | SHOULD-FIX | `risk.assess` sets `new_risk_allowed = not breaches`. A report can therefore show `remaining_risk_capacity == 0` next to `new_risk_allowed == True`. | Open risk exactly equals the portfolio limit. The report says new risk is allowed, and any consumer that reads only the flag authorizes risk at zero capacity. | `test_gate7_risk.py::test_zero_capacity_never_reports_new_risk_allowed` | FIXED (PR #26): `new_risk_allowed` requires capacity > 0 |
| GATE7-F03 | A risk / research integrity | BLOCKER (coupled to F01) | There is no separate research account. Once F01's vetoes land, the operational account stops carrying the frozen EXP-001 rule (1 contract per signal, latency-confirmed-v1), and the registered experiment would change without an amendment. | Operational vetoes remove fills. Nothing records the frozen-rule fills for the Stage B looks. | `test_gate7_risk.py::test_research_account_keeps_the_frozen_rule_when_operations_veto` | FIXED (PR #26): `EXP-001-stage-b-research` account records the frozen rule (ADR 0016) |
| GATE7-F04 | B timing / cash | BLOCKER | There is no point-in-time state. `run_day` sizes and checks cash against the full replayed ledger, so in catch-up processing, settlement cash learned *after* day D's decision finances D's fills. `ShadowLedger.state_as_of(t)` does not exist. | A position consumes $999.98 of $1,000 before D's decision. It wins, but the evidence arrives after D's decision, and it is settled before D is processed. D then fills 3 contracts with money it did not have at decision time. | `test_gate7_ledger.py::test_catch_up_settlement_cannot_finance_an_earlier_day`, `::test_state_as_of_excludes_settlements_not_yet_known` | FIXED (PR #26): `state_as_of`; sizing and pre-fill checks use it; the orchestrator settles per day on evidence known by that decision |
| GATE7-F05 | B timing | SHOULD-FIX | Settlement evidence does not record when it became available (`evidence_available_utc`). Without it, F04 cannot be fixed from the journal alone. | A settled-market capture fetched at 2026-09-24T14:00Z leaves no availability time in the settlement payload. | `test_gate7_ledger.py::test_settlement_evidence_records_when_it_became_available` | FIXED (PR #26): `evidence_available_utc` = snapshot receipt time |
| GATE7-F06 | B locking | SHOULD-FIX | When another connection holds a write lock, `ShadowLedger(...)` or an append blocks for the 30 s busy timeout and then raises raw `sqlite3.OperationalError`, not a ledger error. | A second writer, such as a CLI run during a daily job, stalls for 30 s and then fails with an unexplained sqlite error. The test expects `LedgerError` within 8 s. | `test_gate7_ledger.py::test_append_against_held_lock_fails_fast_with_ledger_error` | FIXED (PR #26): 5 s busy timeout, lock/busy raised as `LedgerError` |
| GATE7-F07 | C prices | NIT | `fee_schedules.valid_price(Decimal("NaN"))` raises `InvalidOperation`. As a result `opportunity.evaluate` and `fill_policy.simulate_fill` crash on a NaN ask instead of returning INVALID_PRICE / NO_ENTRY_PRICE. The Kalshi adapter already rejects non-finite levels, so only a future adapter is exposed. | Another venue adapter passes `Decimal("NaN")`, and the evaluation of the whole event aborts. | `test_gate7_market.py::test_nan_ask_from_any_adapter_is_invalid_price_not_a_crash` | FIXED (PR #26): `valid_price` rejects non-finite values |
| GATE7-F08 | B triggers | NIT | Nothing reports missing immutability triggers. Reopening the ledger for writing silently re-creates them (good). Read-only verification never notices they were gone. | Someone drops the triggers, edits rows, and reopens the file read-only for a report. The only detection left is the hash chain. | `test_gate7_ledger.py::test_readonly_verification_reports_missing_triggers` (formerly xfail); `::test_reopening_for_write_restores_dropped_triggers` (plain) | FIXED (PR #26): `verify_chain` also checks the append-only triggers (`verify_schema`) |
| GATE7-F09 | B tampering | NIT (documented limitation, ADR 0014) | Without an external anchor of the head hash, deleting or consistently rewriting the newest entries leaves a valid, shorter chain. `appended_at_utc` sits outside the hash by design. Edits to middle rows, deletions, backdating and reordering are all detected. | Someone with write access truncates the last settlement. `verify_chain` still passes. | `test_gate7_ledger.py::test_known_limit_head_truncation_and_appended_at_are_not_detected` (characterization, plain); `test_ledger_anchor.py::test_head_truncation_passes_the_chain_but_not_the_checkpoint` | OPEN: support code exists (`edge_lab.ledger_anchor`, `edge-lab shadow anchor export\|verify`, ADR 0021); no independent anchor has been stored, so head truncation is still undetected in production. See "Closing GATE7-F09" below |
| GATE7-F10 | B settlement | SHOULD-FIX | A later settled-market capture that contradicts an already recorded settlement is silently ignored, because `settle_open_positions` looks only at open positions. A ledger rebuilt from the same store would settle on the latest capture and book different P&L. | Kalshi's value moves from 67 to 70 after the first capture. B67.5 YES stays booked as a win with no alert. | `test_gate7_ledger.py::test_contradicting_later_settlement_capture_is_reported` | FIXED (PR #26): `report["conflicts"]` for contradicting captures; open positions with conflicting captures stay pending |
| GATE7-F11 | B timing / cash | SHOULD-FIX | `ShadowLedger.record_fill` enforces "settled cash never negative" in append order, not by effective or evidence time. So a direct ledger user can finance an earlier-dated fill with a later settlement. This is the ledger-level counterpart of F04. | The bankroll is $1.00, $0.99 is committed at T0, and the settlement is known at T0+2d. A fill dated T0+1h costing $0.42 is accepted. | `test_gate7_ledger.py::test_ledger_refuses_fill_financed_by_a_later_settlement` | FIXED (PR #26): cash checked as of the fill time, and fills must follow cash movements in knowledge-time order |
| GATE7-F12 | B/D settlement time | SHOULD-FIX (becomes BLOCKER once F01 lands, unless `settlement_ts` is always captured) | When `settlement_ts` is missing, the settlement is stamped at `expiration_time`, which is the *latest possible* expiry (2026-09-30 for the 26SEP23 fixture). That time is later than the evidence capture (2026-09-24). `risk.require_point_in_time` then refuses every `as_of` before it, so the risk report fails for up to a week. A pre-fill `risk.assess` for the following days would do the same. | A settle run on 09-24 stamps 09-30. `edge-lab shadow risk --as-of 2026-09-24T15:00Z` and next-day pre-fill checks raise `ValueError`. | `test_gate7_ledger.py::test_settlement_is_never_stamped_after_its_evidence_was_captured` | FIXED (PR #26): settlement time clamped to the evidence receipt; reported time kept |
| GATE7-F13 | D reporting / fees | SHOULD-FIX | Fill and settlement payloads carry `fee_schedule_id` (fills only) but not `fee_status` or `claimable`. Only decisions record that the P&L is not claimable while the schedule is UNVERIFIED_CURRENT_SCHEDULE. | A report built from fills or settlements alone cannot tell that the net P&L is unclaimable. | `test_gate7_reporting.py::test_fill_and_settlement_payloads_carry_fee_status` | FIXED (PR #26): fills and settlements carry `fee_schedule_id`, `fee_status`, `claimable` |
| GATE7-F14 | B settlement | SHOULD-FIX | `settle_open_positions` checked each market on its own: Kalshi's recorded result had to agree with the frozen resolver on *that market's* `expiration_value`. Nothing checked the event as a whole, although Gate 2 needs exactly one YES bracket and one expiration value per event (`settlement_audit`). Found by the 2026-09-23 GitHub reuse audit (PredictionMarketBench comparison, `docs/GITHUB_REUSE_AUDIT.md`). | Captured brackets that are each internally consistent but state different values (67 on one, 69 on another) booked several winners for one event, or booked every bracket as a loss. | `test_gate7_replay_semantics.py::test_an_event_with_several_yes_brackets_does_not_settle`, `::test_brackets_that_each_lose_on_their_own_value_do_not_settle`, `::test_brackets_stating_different_values_do_not_settle`, `::test_a_later_contradiction_is_reported_for_already_settled_positions`; incomplete evidence is not a conflict: `::test_unsettled_brackets_are_pending_not_a_conflict`, `::test_losing_brackets_settle_while_the_winning_bracket_is_not_yet_settled` | FIXED (audit PR #40): `event_settlement_problems` flags an event only when more than one bracket resolves YES or brackets state different values. Its open positions stay pending and every affected position, settled or open, is reported as a SETTLEMENT_CONFLICT with the reason. Unsettled brackets and a not-yet-settled winner are incomplete evidence: they stay pending without an alert, and coherent evidence settles exactly as before |

### Closing GATE7-F09 (ledger head anchor)

What exists: `edge_lab.ledger_anchor` and `edge-lab shadow anchor export|verify` (ADR 0021),
tested on disposable ledgers in `tests/test_ledger_anchor.py`. A checkpoint records each
account's entry count and head hash. Verifying against it reports TRUNCATED or REWRITTEN in
the cases where `verify_chain` alone still passes. Nothing is scheduled, and nothing has been
stored anywhere.

The characterization test above stays: the hash chain alone still cannot see head
truncation. F09 closes only when **all** of the following are recorded here, with dates and
evidence:

1. The code carrying `shadow anchor` is merged and deployed, and the deployed SHA is
   recorded.
2. A checkpoint of the production ledger was exported as `edgelab`, read-only:
   ```bash
   sudo -u edgelab /opt/market-edge-lab/venv/bin/python -m edge_lab.cli shadow anchor export --ledger /var/lib/market-edge-lab/ledger/shadow_ledger.sqlite3
   ```
3. It is stored somewhere independent of the VPS, per ADR 0021 option (c) (owner-held
   off-host copy) and/or (d) (private Git repository), or an owner-approved (b)/(e). A copy
   beside the ledger (option (a)) does not count.
4. A later `shadow anchor verify` of the production ledger, against that independent copy,
   returned VERIFIED or EXTENDED, and the output is recorded.
5. At least one such verification ran **off-host**: from the owner's own checkout at a
   known, reviewed SHA, against a copy of the production ledger or of a backup bundle's
   database fetched from the VPS. Root on the VPS (ADR 0021, A2) controls whatever runs
   there, so an on-host VERIFIED does not cover A2.

Items 1 to 5 show that a truncation would now be *detectable* for the anchored history. They
do not detect tampering with entries appended after the newest stored checkpoint. That residual
gap is accepted in ADR 0021. Keeping it small means exporting a checkpoint regularly, which is
manual unless the owner separately approves a scheduled anchor.

Reporting findings from the independent review of the local dashboard (PR #28, area D). All
are fixed and tested in `tests/test_dashboard.py`:

- **Host header (DNS rebinding).** Any Host was accepted. Now a non-local Host gets 400.
- **Incomplete receipt.** Settlement conflicts, the evidence cutoff, the latest day, missing
  capture days, valid-day counts and risk vetoes were not rendered. Now all are shown, and a
  test renders a receipt produced by `edge_lab.daily`.
- **Colours.** SETTLEMENT_CONFLICT, MISSING_CAPTURE and RESEARCH_INVALID_CASH were neutral.
  They are now errors.
- **Zero capacity.** It was shown as "BREACH — no breaches". It is now HALTED and listed as
  a blocker.
- **RESEARCH_INVALID_CASH** (a deviation from the frozen rule) is now a blocker.
- **Malformed receipt lists** now render as MALFORMED, not "none".

Observations that are not defects, recorded so nobody rediscovers them:

- **Portfolio cap versus loss headroom.** Under `EXP-001-shadow-risk-v1`, remaining capacity
  subtracts open worst-case risk from the $10 daily-loss headroom. Once F01 is fixed, the
  effective open-risk ceiling is therefore about $10, not the $50 portfolio cap. This is
  conservative and consistent with ADR 0015. It is not tuned.
- **Capacity is portfolio-level only.** `remaining_risk_capacity` has no event or cluster
  headroom. Those caps are enforced by sizing alone. The two policies must not drift apart;
  `test_operational_sizing_and_risk_limits_agree` guards this.
- **Frozen tail-bin property (DESIGN §5).** Mass for errors beyond +20 sits at k = +20.
  So P("greater than f+20") = 0, and P("greater than f+19") equals the end bin. The tests pin
  this frozen behaviour (`test_tail_bins_follow_the_frozen_clamp`). Changing it would need a
  preregistration amendment.
- **Malformed bid levels.** A finite but nonsensical bid level (negative, or ≥ 1) is not
  flagged as an anomaly by the adapter. It still cannot produce a valid ask: the engine
  rejects the result as INVALID_PRICE or INSUFFICIENT_SIZE
  (`test_nonsense_bid_levels_never_become_valid_asks`).

## Engineering robustness evidence (what the suite proves today)

Scope: fixture and synthetic inputs, run locally with
`python -m pytest -q -o addopts=""` at the commit that adds this file. Result: 636 passed,
17 xfailed. The suite covers the following:

- **A. Risk.** The breach and capacity tests take every limit at, just below and just above
  its boundary: portfolio, position, event, cluster, reserve, daily loss (including the
  trailing-24 h edge), and drawdown.
  - Open exposure in a cluster counts against loss headroom.
  - Sizing reduces a candidate to 0 contracts when it would cross a cap, and records the
    binding constraint in the persisted decision.
  - Consecutive candidates on one day share cluster headroom: the account fills to exactly
    the $6.00 cluster cap and never beyond.
- **B. Ledger and timing.**
  - A crash after the 1st fill, the 2nd fill or the 5th decision, followed by a restart,
    gives a ledger identical to a clean run: the same head hash and the same state.
  - A process killed inside an append transaction leaves no row.
  - A failed invariant rolls back its append.
  - Duplicate and conflicting decisions, fills and settlements behave as specified.
  - Four processes appending concurrently lose nothing and duplicate nothing, and exactly
    one of them wins a contested key.
  - Edits, consistent re-hashing of a middle row, deletions, backdating and reordering are
    all detected.
  - A short lock is waited out, and readers are not blocked while a writer holds its lock.
  - A rebuild from the same evidence after settlement is deterministic.
  - A delayed settlement stays open, `locked` and uncredited until its evidence exists.
- **C. Market, model and execution.**
  - YES/NO complements hold, and implied asks come from the opposite side's bids.
  - Crossed, locked, malformed and non-finite books are rejected, and so are prices off the
    price grid or outside (0, 1).
  - Zero and missing liquidity never becomes 0.
  - Freshness boundaries hold: exactly 5 min is fresh, and any future stamp is not.
  - The confirmation window is inclusive at 10 and 15 min.
  - A wrong event or market, unresolved rules, an unofficial or disagreeing outcome, an
    incomplete forecast, or a missing re-check all fail closed.
  - A price that moves away gives NO_FILL, and a fill is always at the entry price.
  - Worse fees and higher latency never add signals or fills. These are diagnostics only:
    the frozen `kalshi-quadratic-taker-v1` and `latency-confirmed-v1` are asserted unchanged.
  - Clamping at ±20, the strict greater and less comparisons, inclusive between-brackets,
    and bracket partitions summing to 1 for any forecast all hold.
- **D. Reporting.**
  - Equity is cost-basis, with no mark.
  - Best-case payouts never appear in available or withdrawable cash.
  - Unknown and overdue horizons stay `locked`.
  - Outcome-board loss and gain are labelled upper bounds. For the fixture day, the summed
    best case is strictly unattainable, as shown by enumerating every integer outcome.
  - Settlement P&L is computed from the fill.

The xfail tests above establish that F01–F13 exist. They do **not** show that any fix works.
That is shown only when each test XPASSes and its marker is removed.

## Production integration evidence

None yet. No real capture day has been observed through this suite. The forward collector,
the settled-market capture (no timer exists yet, ADR 0014) and the daily orchestrator have not
been exercised against production data here. In particular, whether real settled-market
payloads carry `settlement_ts` (F12) is unverified.

## Research-performance evidence

None. Fixture and synthetic tests cannot establish a profitable strategy. They also cannot
satisfy EXP-001's preregistered Stage B looks at the 180th and 365th *valid* decision days.
Nothing here moves any research state past HYPOTHESIS or PREREGISTERED. The fee schedule
remains UNVERIFIED_CURRENT_SCHEDULE, so no net result would be claimable even if one existed.
Gate 8 and any real-money work stay out of scope.
