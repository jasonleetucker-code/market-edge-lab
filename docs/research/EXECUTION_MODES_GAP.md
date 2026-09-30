# Execution modes gap: taking, resting making and RFQ against the current execution design

**Status:** design record, 2026-09-29 (R2 PR A, Writer A). Roadmap package R2, #145. This feeds R5,
the one-venue order, inventory and capital rehearsal.

**This authorizes nothing.** It adds no transport, credential, account read, quote, RFQ request,
acceptance, confirmation or order, and no timer. `EXECUTION_NOT_AUTHORIZED` stays the last control of
`execution_ticket.pre_submit_checks`, and it always fails. Implementing any row below needs its own
owner directive. Live use needs separate live authority.

## 1. What exists today (built on, not redesigned)

- **`execution_ticket.py` (ADR 0019).** A ticket is an order draft. It has:
  - a content-derived `ticket_id`, which is the future idempotency key;
  - the ordered `pre_submit_checks` control chain;
  - the `OrderState` vocabulary (PENDING, OUTCOME_UNKNOWN, RESTING, FILLED, CANCELLED, REJECTED) with
    checked transitions. `ORDER_STATE_UNHEALTHY` blocks new risk when our own order view is not current.
  - This PR adds the pure `reserve_simultaneous_obligations` helper (§4).
- **ADR 0035, the execution package design.** It covers:
  - a durable, hash-chained intent journal, with INTENT fsynced before any network call;
  - per-venue idempotency capability (`IDEMPOTENT_KEY`, `LABEL_ONLY`, `NONE`), with no blind retry;
  - atomic cash reservation (`BEGIN IMMEDIATE`), released exactly once;
  - a single lease with fencing tokens enforced in the write transaction;
  - attempts kept apart from outcomes, and per-fill partial fills;
  - CANCEL_REQUESTED kept apart from CANCEL_CONFIRMED;
  - OUTCOME_UNKNOWN quarantine, external reconciliation, restart recovery and the orphan-leg policy.
- **ADR 0038, the in-play foundation.**
  - Every open sale reserves inventory, whatever its origin: native Auto Sell, manual, bot or unknown.
  - A cancel *request* releases nothing, and over-reservation blocks.
  - Reconciliation imports native and manual orders before any bot order is drafted.
  - Stale inputs block new risk and never liquidate.
- **R2 (this PR).**
  - `inplay_evidence.decision_validity` turns a recommendation made on an old game state into a
    policy state: INVALIDATED or REVIEW_REQUIRED.
  - `position_policy.evaluate(state_validity=...)` BLOCKS such a proposal for review.
  - `research_economics.ExecutionMode` (TAKER, BOOK_MAKER, RFQ) keeps the modes' economics apart.

## 2. One chain, six distinct objects

Each object has its own identity. None is inferred from the next one.

```
raw observation -> policy recommendation -> order intent / quote intent
   -> venue acknowledgement / acceptance / confirmation -> actual fill -> ledger posting
```

- A recommendation is not an intent.
- An acceptance is not a confirmation, and a confirmation is not a fill.
- A fill is posted exactly once, keyed by the venue fill id (ADR 0035 item 9).
- A markout on a fill is not a ledger posting.

## 3. Commitment points by mode

| Mode | We commit when | It can bind until | Binding size | Revalidate before commitment |
|---|---|---|---|---|
| TAKING (IOC or marketable limit) | the order leaves | the IOC answer; after that nothing rests | up to the order; partial fills possible | `pre_submit_checks` + `decision_validity` at submission time |
| RESTING MAKING | the order is placed | a **confirmed** cancel, a fill, expiry or close; the counterparty picks the moment | any part, at any time, including after a state change | at placement only. A resting order cannot react, which is why ADR 0041 counts `fills_after_state_change` |
| RFQ QUOTING | the quote is sent | the venue's binding point (acceptance and/or maker confirmation). This design assumes binding from send until a confirmed withdrawal or expiry | **full request size**; no partial acceptance is assumed | before sending, and again before any maker confirmation step the venue documents |

The venue-specific RFQ stages, visibility and fee or size semantics are PR B's scope
(`docs/research/RFQ_*`). Where PR B documents a later binding point, this design still treats the quote
as a reserved obligation until that point is **confirmed** to have passed. It never assumes cancel
succeeded. It never assumes a hedge, a partial acceptance or instant cancellation.

## 4. Gap table

| Requirement | Exists | Gap by mode | Proposed extension (owner) | Fixture test the rehearsal must ship |
|---|---|---|---|---|
| **One execution authority** | ADR 0035 item 4: a lease with fencing tokens. Designed, not built | Quotes and resting orders are long-lived obligations. The lease holder must own *every* open obligation, not only the orders it placed in this session | `execution_ticket` / journal (R5): obligations are journal entities that belong to the fenced authority. A new holder inherits them through replay | a stale lease holder cannot quote, place, confirm or cancel |
| **Atomic cash reservation** | ADR 0035 item 3 (buys) | Resting sales, RFQ quotes on either side, and combos that share legs | the reservation covers the **worst case at full size** of every open obligation at once (`reserve_simultaneous_obligations`) | two workers cannot reserve the same cash; two quotes on one game both reserve fully |
| **Atomic inventory reservation** | ADR 0038 (sells, any origin) | RFQ sells of held contracts, and quotes that would sell inventory already reserved by Auto Sell | one reservation table for cash **and** inventory, keyed by obligation id | a manual sale plus a quote above holdings is OVER_RESERVED and blocks |
| **Fencing** | ADR 0035 item 4 | a quote confirmation is a write like any other | every quote, confirm and cancel event carries the token; an older token is refused | a paused worker that wakes cannot confirm an old quote |
| **Reconciliation: native, manual and bot** | ADR 0035 item 9; ADR 0038 imports native orders first | RFQ quotes, acceptances and confirmations must be reconciled too. Others' quotes are UNAVAILABLE, never reconstructed | the reconciler maps venue quote and order ids to intents. An unmatched own quote or fill is an incident and blocks new risk | an unmatched confirmation blocks new risk and raises an alert |
| **Idempotency and retry per provider** | ADR 0035 item 2 (`venues.py` capability) | per mode: quote replacement, quote ids and confirmation retries may differ from order placement | declare the capability per venue **per mode** (`order`, `quote`, `confirm`, `cancel`). Under `LABEL_ONLY` or `NONE`, a lost answer goes to OUTCOME_UNKNOWN | a lost quote response is never re-sent blindly |
| **Partial and late fills** | ADR 0035 item 6; `ReplayLedger` (late fill after a cancel request) | a resting maker can partially fill after a cancel request. RFQ is modelled at full size | per-fill events with native 0.01 quantities. RFQ: an unexpected partial is an incident, not a normal path | a late partial fill after CANCEL_REQUESTED is applied once and the remainder stays reserved |
| **Cancel request vs cancel confirmation** | ADR 0035 item 7; ADR 0038; `RestingOrder.cancel_requested`; `ObligationState.CANCEL_REQUESTED` | `OrderState` has no CANCEL_REQUESTED state. It lives in the journal events | keep it an event plus a flag. Only CANCEL_CONFIRMED plus fill reconciliation releases | a request releases nothing; a confirmation releases only the unfilled remainder |
| **Unknown-state quarantine** | `OrderState.OUTCOME_UNKNOWN`; `ORDER_STATE_UNHEALTHY`; ADR 0035 item 8 | a quote whose send or withdrawal answer is lost | `ObligationState.UNKNOWN` stays reserved and blocks new risk on that market (and, by policy, the account) | a timeout neither releases nor re-sends |
| **Restart recovery** | ADR 0035 item 10 | outstanding quotes and resting orders at restart may still bind | on restart, every non-terminal obligation goes to reconciliation and **stays reserved**. There is no assumed cancel-all | a restart with an open quote keeps its reservation until the venue confirms it is gone |
| **State revalidation** | R2: `decision_validity` and `evaluate(state_validity)`. `pre_submit_checks` has no game-state control | taking needs it at submission. Making needs it at placement, and it cannot protect a resting order afterwards. RFQ needs it before send and before confirmation | a future `STATE_INVALIDATED` control in `pre_submit_checks`, fed by `decision_validity`. Not added in this PR, so the control order and its tests stay unchanged | a material event between decision and submission blocks; an in-flight change is reported, not undone |
| **Conservative simultaneous reservation** | **added:** `execution_ticket.reserve_simultaneous_obligations` (pure) | every held obligation's worst case is summed, with no netting and no partial acceptance. A cancel request and an unknown state count. An unknown worst case or unknown cash blocks | the R5 reservation transaction calls it (or its SQL equivalent) inside `BEGIN IMMEDIATE` | `tests/test_execution_ticket_obligations.py` |
| **Kill switch** | `EXECUTION_NOT_AUTHORIZED` (always fails); risk report `new_risk_allowed`; ADR 0038: stale inputs never liquidate | a kill blocks **new** risk: no new order, quote or confirmation. It cannot guarantee liquidation. Resting orders and sent quotes may still bind until confirmed cancelled; a thin book may not absorb a sale | kill = refuse new obligations, then request cancels and keep every reservation until confirmations arrive. A reduce-only exit is a separately authorized procedure (ADR 0038) | under the kill, a new quote is refused and existing obligations remain reserved and reported |

## 5. What stays out of scope

- No transport, no simulated venue with a network path, and no credential handling.
- No automatic hedging, no atomic multi-leg assumption (ADR 0035 item 11), and no copied-price strategy.
- No RFQ participation, and no quote sent to learn private flow. A quote can be an executable
  obligation; it is not a data fetch.

## 6. What would change this design

- Venue documentation, verified on an account, of a guaranteed atomic multi-leg or a guaranteed
  cancel. This would change only the affected row, for that venue.
- PR B's RFQ matrix documenting a binding point or partial acceptance that differs from §3. The
  RFQ row would change; the conservative reservation stays until the fact is verified.
