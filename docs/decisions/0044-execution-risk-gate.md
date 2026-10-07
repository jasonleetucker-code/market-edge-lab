# ADR 0044: Execution risk gate (pure, owner-limited, one owner per formula)

**Status:** Proposed 2026-10-07 (#160, campaign package I). Authority: the 2026-10-07 entry of
`docs/EXECUTION_PLAN.md` (offline, FIXTURE only; "risk and ticket checks" are listed). Boundary: ADR 0043.

## Problem

The execution package can build an intent, journal it, reserve cash and inventory, and format it for the venue. Nothing
yet decides whether a strategy's proposal is acceptable for the account as a whole:
- exposure by market, event, cluster and strategy;
- loss limits and new-risk budgets;
- fees, book depth and slippage;
- staleness, reconciliation health and the approval binding.

Three existing owners each hold part of the answer:
- `risk.py`: loss limits, drawdown and capacity, but over a replayed shadow account (and it imported `shadow_ledger`,
  the pinned edge in ADR 0043);
- `execution_ticket.py`: simultaneous obligations, plus the TicketLimits rate rules;
- `fee_schedules.py`: the versioned fee bounds and their verification.

A second copy of any of their formulas would be a second financial authority.

## Decision

1. **`risk.py` reads a protocol, not a ledger type.** `RiskAccount`/`RiskPosition` describe exactly what its functions
   read. `shadow_ledger` is no longer imported in any form. The import is removed outright: `TYPE_CHECKING` is not
   enough, because the boundary invariant's AST walk counts it. Output is byte-identical, tested against expectations
   recorded from the legacy module. `TRANSITIVE_EXEMPT` is empty.
2. **`execution/risk_gate.py` is pure.** `evaluate(intent, account, market, policy, limits, ticket_limits, evidence,
   now)` returns a `GateDecision`:
   - every failing check as a `Reason` code with a detail, in declaration order, the first primary;
   - the version id of every input it used;
   - its computed figures.

   There is no force or bypass argument. `revalidate` adds `ApprovalGrant.problems`, so a changed quantity or price
   after approval is a digest mismatch.
3. **Typed, versioned, immutable inputs.**
   - `AccountProjection` (built by `project_account` from a `reservations` snapshot and held reservations).
   - `MarketState` with `BookState`.
   - `DecisionEvidence`.
   - `GateLimits`: only what neither existing policy has (quantity per order, slippage, decision and source age,
     daily new risk, strategy cap).

   Money limits stay in `risk.RiskPolicy`, and order rate, cooldown and book or state ages in `TicketLimits`.
   Construction refuses float, bool, NaN, infinity, negatives and unknown schemas. A reused policy holding such a
   value fails POLICY_INVALID.
4. **One owner per formula.**

   | Formula | Owner |
   |---|---|
   | Cash and reserve floor | `reserve_simultaneous_obligations`, with cash minus `reserve_floor` available |
   | Exposure sums per key | its no-netting `by_key` |
   | Loss limits, drawdown, capacity | `risk.assess` on a projection-backed `RiskAccount` |
   | Inventory | `ReservationAuthority.inventory_for` |
   | Fees | `schedule_for`, `verification_at`, `taker_buy` |
   | Grid and direction | `MarketTradingProfile.check_yes_price`, `kalshi_wire.yes_terms` |
5. **Worst cases, never hope.**
   - An entry can lose its `max_total_cost`.
   - A held contract can still lose $1, its maximum value, whatever it cost. Purchase cost is never the remaining-risk
     measure.
   - An external order can add $1 per remaining contract.
   - An unknown market, event, cluster or strategy counts toward the candidate's own key. A held item on the
     candidate's own market whose event or cluster contradicts the market state fails EXPOSURE_KEY_CONFLICT.
   - A reduction adds no exposure and is not held to exposure or loss limits.
6. **Fail closed.**
   - Each of these is an explicit rejection:
     - an unknown or stale input;
     - a quarantined or UNKNOWN obligation;
     - an inconsistent snapshot;
     - unlisted external orders;
     - unknown P&L or order history, or one not complete since the projection's `account_genesis_utc`;
     - a snapshot revision without a time (or the reverse), or a "consistent" snapshot with problems (refused at
       construction);
     - an unverified or unsupported fee schedule;
     - a maker fee that is unverified for an order that can rest.
   - Loss limits use realized P&L only: deposits and withdrawals are listed and never counted.
   - Counts come only from the persisted order history. The decision's `inputs` record the genesis and a digest
     of each history.
   - The projection comes from one transaction (`ReservationAuthority.account_view`). Two separate reads could
     straddle a snapshot that releases a BOUND reservation, so that its fills are in neither.
7. **Owner-set limits.** `PLACEHOLDER_LIMITS`, `PLACEHOLDER_POLICY` and `PLACEHOLDER_TICKET_LIMITS` have zero caps
   and no `owner_approval_ref`, so every order fails LIMITS_NOT_SET_BY_OWNER. Real values come from the activation
   packet.

## Alternatives rejected

- **Extend `pre_submit_checks`.** It is bound to the research `ExecutionTicket`, and its final control always fails
  by design.
- **Compute everything locally in the gate.** That would copy the fee, loss and obligation formulas.
- **Use mark-to-market or purchase cost for held positions.** Neither bounds the remaining loss. $1 per contract does.
- **Let reductions bypass reconciliation health.** Inventory and fee cash cannot be trusted while state is unknown.
  De-risking under a quarantine is a kill-switch decision (package L).

## Tradeoffs

- $1 per held contract, plus double counting of a partly filled entry until its reservation is released, overstates
  exposure. Capacity is lower than strictly necessary.
- Unknown dimensions counted toward the candidate can block orders that are in fact unrelated.
- `project_account` mirrors `reservations._evaluate`'s cash obligation construction (quarantine is unknown;
  provider-held uses the residual; a negative residual is unknown). Tests pin agreement on `cash_required`, including
  the negative residual. A provider-held view the snapshot does not list keeps its full worst case.
- The genesis is caller-supplied until a later package ties it to the journal's genesis. A history shorter than the
  stated genesis is refused, and a moved genesis is visible in the decision's `inputs`.
- Key conflicts are detected only on the candidate's own market. A mistagged market elsewhere in the same event is
  not detectable here.
- One account scope is the whole portfolio. Cross-scope aggregation does not exist yet.
- The sale fee bound uses the buy formula's fee at the worst price at or above the limit. That assumes Kalshi charges
  sales with the same quadratic formula.

## Reconsider when

- `reservations` exposes a public cash-obligation builder: switch to it (inventory already is public).
- A venue observation (DEMO or production read) shows different sell fees, holds or fee rounding.
- Several scopes or subaccounts trade at once: add a portfolio projection.
- The owner sets real limits, or asks for de-risking during a quarantine.
