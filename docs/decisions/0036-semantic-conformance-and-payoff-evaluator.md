# ADR 0036: Semantic conformance metadata and the same-venue payoff evaluator

**Status:** Accepted 2026-09-25 (EE v1 PR B). Authority: `docs/owner/2026-09-25-economic-evidence-v1-directive.md`
(items 4 and 5) and `docs/EXECUTION_PLAN.md`. Research only; no network call, order or credential.

## Problem

Two contracts can look comparable and still differ in units, rules, fees, clocks, finality or
rights. Examples:
- a one-cent Novig contract counted as a $1 contract;
- a fractional Kalshi fill truncated to an integer;
- a de-vigged book probability treated as a market price.

Family B (EXP-003) also needs to know whether a set of same-venue contracts has a *proven* payoff
relationship, and what it would cost at a given size after fees and states.

## Decision

1. **Additive semantics on `opportunity.Market`** (`semantics: ContractSemantics | None`, never part
   of an opportunity id). The fields:
   - `UnitSemantics`: native step, price convention, payout per unit, currency, multiplier and
     normalization version;
   - `RulesIdentity`;
   - `FeeSemantics`: schedule, effective time, rounding scope, claim basis;
   - `ProbabilityMeaning`, kept separate from `RelationTier` (which includes
     CONDITIONAL_EQUIVALENT for mappings that hold only on stated states);
   - source family, where None means UNKNOWN;
   - `ClockStamp` (kind, precision, uncertainty);
   - `OutcomeFinality`;
   - `DataRights` (inheritance takes the most restrictive union).

   `semantics_for` is the explicit compatibility reader: a legacy market reads as UNKNOWN,
   and its `Payoff.amount` is not taken as documented units. `payout_value` is the only unit
   conversion, and it refuses unknown units and off-step quantities.
2. **Dated venue facts are fixtures** (`tests/fixtures/conformance/venue_facts_2026-09-25.json`):
   - Kalshi quantities have a 0.01 step;
   - a Novig contract pays one cent;
   - Novig placement is not idempotent, and 201 means queued;
   - the Novig public book is documented only with QA examples;
   - the KXNFLGAME fee conflict is recorded.

   They were read from documentation with no endpoint called. Whatever is unconfirmed is
   UNVERIFIED.
3. **`payoff_constraints.py`**, a pure evaluator.
   - **Scope:** allowlisted complements, partitions and nested thresholds; long legs only.
   - **States:** enumerated states, including discretionary `Variable`s (for example Kalshi's
     "last fair price" fallback), or excluded with evidence. A missing kind makes the proof
     INCOMPLETE.
   - **Formula:** the strategy's corrected formula. State-dependent settlement costs and refunds
     sit inside the minimum. Fees enter once, per fill, through the canonical depth walk and
     schedule.
   - **Outputs, kept separate:** the relationship, the observed inconsistency, the conditional
     full-fill surplus, simulated execution (not modelled) and the actual result (none).
   - **Orphan legs:** orphan-leg exposure is always reported.
   - **Soundness rule:** a minimum over a subset of states bounds the true minimum from above. So
     "no surplus" is a valid conclusion from an incomplete proof, while a positive surplus needs a
     proven, fully costed set and a claimable fee basis.
4. **Stored-evidence scan** (`edge-lab research payoff-scan`).
   - It opens the store read-only and reads market-side books and rules only.
   - It drops the EXP-003 `prohibited_fields` (settled fields) and skips post-close snapshots.
   - The windows are required arguments: the protocol values are UNKNOWN, and nothing defaults them.
5. **`storage.SnapshotStore.snapshot_metadata` and `max_row_id`:** public, bounded, payload-free
   reads, so research readers never use the private connection.

## Alternatives considered

- **A general optimizer (LP) over arbitrary contract graphs.** Rejected (#96: no universal
  solver). It would also need a proven state space, which is the hard part.
- **Generalizing `Payoff` or `ExecutableQuote` quantities in place.** Rejected: that risks
  changing frozen EXP-001 behaviour. The semantics are additive.

## Tradeoffs

- The fee model prices integer takes only. A walk that crosses a fractional Kalshi level is
  NOT_EVALUATED rather than guessed, and stored KXHIGHNY books do hold fractional sizes.
- v1 refuses anything but $1 USD contracts. Novig or other units need an explicit, versioned
  conversion design.

## What would make us reconsider

- A verified fractional-fill fee rule from Kalshi.
- A venue with atomic multi-leg orders.
- Settlement or transfer fees verified for KXHIGHNY; the evaluator treats them as UNKNOWN today.
