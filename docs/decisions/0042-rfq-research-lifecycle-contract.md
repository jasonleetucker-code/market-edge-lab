# ADR 0042: RFQ research lifecycle contract (pure, fixture-fed; no participation)

**Status:** Proposed 2026-09-30 (PR B, roadmap R4, issue #145). Authority: the 2026-09-30 owner directive
(`docs/EXECUTION_PLAN.md`, PR #147), which allows "an optional pure fixture-fed lifecycle component" and does not
allow RFQ creation, quoting, acceptance, confirmation, credentials or subscriptions. The facts and conflicts behind it
are in `docs/research/RFQ_FEASIBILITY_2026-09.md`.

## Problem

Kalshi RFQs have a lifecycle that no existing owner models:
request → private quotes → acceptance → maker confirmation (the binding point) → execution timer → orders → fills.

Each stage has a different audience. Requests reach every authenticated subscriber. Quotes, acceptances and
executions reach only the two parties. Fills are per member. Research that reads this lifecycle naively would:
- treat requested size as volume;
- treat an accept or a `quote_executed` as a fill;
- read a missing competitor price as zero;
- release collateral on silence;
- let shared combo legs share collateral.

Existing owners do not cover it:
- `venues` holds capability stages, not lifecycle semantics.
- `execution_ticket` / ADR 0035 own our orders once they exist, and an RFQ produces ordinary orders only at the end.
- `payoff_constraints` proves logical payoff relations, not observability or obligations.

## Decision

Add `src/edge_lab/rfq_research.py`, a pure, stdlib-only, network-free module:
- **`observe(messages, observer, max_messages=…, keep=…)`** folds documented channel messages (plus fixture adapters
  for REST quote status and own fill records) into per-RFQ and per-quote views.
  - State is derived from the **set** of distinct events (a content key excludes transport sid/seq), so duplicates
    and reordering do not change it.
  - Contradictory terminal evidence gives UNKNOWN.
  - Party-only events addressed to other parties are counted and never used.
  - The bound counts every received message before local filtering; at most one message past it is read, and the
    whole batch is refused over it (reported as `">N"`).
  - The local filter applies only to public RFQ events; our own quote events and fills are always kept.
  - Malformed input (a bid outside [0, 1], a negative size) is counted and never used. One fill id seen with differing
    payloads is a conflicting fill: never double-counted, its quote UNKNOWN.
  - The channel's `quote_accepted` carries no acceptance time; the caller's receipt stamp is used, labelled as such.
- **Quantity layers stay separate:** requested (a demand upper bound), accepted-notified, orders placed, filled (fill
  records only).
- **Visibility:** competitor quote prices, other parties' fills and acceptance are UNAVAILABLE. A queue rank is
  UNSUPPORTED (undocumented).
- **`quote_is_current`:** replaced, cancelled, closed, lapsed-window and ambiguous quotes cannot be reused. Nothing
  is current without a caller-stated observation time within `max_age` and gap-free channel sequence numbers
  (OBSERVATION_STALE_OR_GAPPED).
- **`hypothetical_check`:** a changed or unknown state version invalidates a would-be price. Its last reason is always
  PARTICIPATION_NOT_AUTHORIZED, tied to `venues.KALSHI.execution_authorized`.
- **`derive_contracts`:** principal-only and fee-inclusive target-cost sizing. Fee-inclusive sizing needs a
  caller-supplied fee function; without one it is FEE_UNSUPPORTED.
- **`obligations`** (RFQ-specific derivation, kept here):
  - worst-case principal per own quote (maker: the worse side at full size);
  - per quote on an own RFQ that may bind: accepted, confirmed, executed or unknown (requester: the worse of `bid` and
    `1 − bid` for a known side, because the side mapping is a documentation conflict; the worst over both sides
    otherwise);
  - each mapped conservatively onto the canonical `execution_ticket.ObligationState`: OPEN and ACCEPTED are
    OUTSTANDING, CONFIRMED and ORDERS_PLACED are BOUND, REPLACED is CANCEL_REQUESTED, RFQ_CLOSED_REASON_UNKNOWN and
    UNKNOWN are UNKNOWN, and only the quote's own observed CANCELLED is RELEASED. An unattributed or conflicting own
    fill turns RELEASED into UNKNOWN, so nothing is freed.
- **Reservation is delegated.** `reserve_simultaneous` is a thin adapter onto the canonical owner,
  `execution_ticket.reserve_simultaneous_obligations` (PR #149, ADR 0041). It is applied per exchange index, because
  collateral is preallocated per shard. The canonical primitive decides what is held, never nets shared legs (its
  `by_key`), keeps unknown unknown and compares with cash. The adapter adds only the per-shard grouping, the fee
  allowance (none: FEE_UNSUPPORTED; negative: unknown) and EXPOSURE_UNKNOWN for an unknown shard.

`venues.py` is not changed. Adding RFQ capabilities would add a row per venue to the Terminal's coverage table, which
is PR C's integration. The research note records the recommended stages.

## Alternatives considered

- **Extend `execution_ticket.OrderState`.** Rejected: RFQ stages before execution are not orders, and one state enum
  for both would blur "accepted" with "resting" and the binding points.
- **Documentation only, no module.** Rejected: the traps above are easy to reintroduce in later replay code. Tests make
  them executable.
- **A WebSocket client with a replay recorder.** Rejected: no credential, subscription or storage right exists. Out of
  scope.

## Tradeoffs

- Worst-case reservations overstate the capital needed when the venue would net or partially accept. That is
  intended until C1 and the collateral timing are answered. Keeping replaced quotes and quotes on closed RFQs reserved
  until their own cancellation is seen overstates it further; a lost event must never free collateral.
- Fixture adapters for REST status and fills are our own normalisation, labelled as such. A real feed needs a reviewed
  parser against captured payloads.

## What would make us reconsider

- Venue answers to C1 (partial acceptance), C7 (block-trade reporting), C14 (the side mapping) or RFQ fees. Change the
  specific rule, not the layering.
- An authorized observation or participation package. It extends ADR 0035's journal and reservation for RFQ binding
  points and does not fork this module into a gateway.
