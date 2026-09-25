# ADR 0035: Next execution package: durable intent journal, reservation, fencing, reconciliation (DESIGN ONLY)

**Status:** Proposed design, 2026-09-25 (EE v1 PR B). Authority: `docs/owner/2026-09-25-economic-evidence-v1-directive.md`
(item 7, "execution-package ADR, design only") and `docs/EXECUTION_PLAN.md`.

**This ADR authorizes and builds nothing:**
- no transport, credentials, account read or order;
- no paper order and no timer.

`EXECUTION_NOT_AUTHORIZED` stays the last control of `execution_ticket.pre_submit_checks`, and it
always fails. Implementation needs a separate owner directive, and so does any live behaviour. An
operational canary needs its own explicit live authority, and it is **not** evidence of alpha.

## Problem

`execution_ticket.py` (ADR 0019, PR #43) is a data contract. It holds a ticket, an ordered
pre-submit control chain, and an `OrderState` vocabulary (PENDING, OUTCOME_UNKNOWN, RESTING,
FILLED, CANCELLED, REJECTED) with checked transitions. It is not a lifecycle. It cannot survive a
crash, prevent two workers from spending the same balance, tell a lost response from a rejection,
or reconcile against the venue.

The dated venue facts show that a naive client is unsafe
(`tests/fixtures/conformance/venue_facts_2026-09-25.json`):
- Novig placement is not idempotent;
- Novig's `clientId` is never checked for uniqueness, so a replay places a second order;
- Novig's HTTP 201 means queued, not resting;
- Kalshi fills may be fractional to 0.01 contracts.

## Decision (the design a future package must implement)

One venue first (Kalshi, per #96). Everything below extends `execution_ticket.py` and
`risk.py`, and keeps the ledger boundary of ADR 0014. There is no second engine.

1. **Durable intent journal.** An append-only SQLite table, hash-chained like the shadow ledger,
   with its own file.
   - Every step is an event with a monotonically increasing sequence number and the writer's
     fencing token: INTENT, RESERVED, SUBMIT_ATTEMPT, ACK, PARTIAL_FILL, FILL, CANCEL_REQUESTED,
     CANCEL_CONFIRMED, REJECTED, OUTCOME_UNKNOWN, RECONCILED, SETTLED and RELEASED.
   - State is derived by replay, never stored mutably.
   - The INTENT is written and fsynced **before** any network call.
2. **Intent ids and venue idempotency.**
   - `intent_id` is content-derived from the ticket (it extends `ticket_id`).
   - Each venue adapter declares its idempotency capability in `venues.py`:
     - `IDEMPOTENT_KEY`: the venue deduplicates a client key;
     - `LABEL_ONLY`: Novig `clientId`;
     - `NONE`.
   - Under `LABEL_ONLY` or `NONE` a retry is **never** automatic. A lost response goes to
     OUTCOME_UNKNOWN and to reconciliation, not to resubmission.
3. **Atomic capital reservation.** One `BEGIN IMMEDIATE` transaction does three things:
   - checks the available cash (venue-tradable cash net of reservations, committed exposure and
     the reserve, from `risk.py`);
   - checks the `STARTER_MAX_7D_V1` verdict;
   - writes RESERVED.

   Two workers cannot both pass, because the second sees the first reservation. A reservation is
   released **exactly once**: at CANCEL_CONFIRMED with zero fills, at REJECTED, or at SETTLED.
4. **Single execution authority with fencing.**
   - One lease row holds (holder, token, expiry). A worker must hold an unexpired lease, and every
     write carries its token.
   - The journal refuses an event whose token is older than the current one, so a paused worker
     that wakes up cannot write.
   - The lease is advisory for liveness, but the token check is enforced in the write
     transaction.
5. **Attempts versus outcomes.** SUBMIT_ATTEMPT records that a request left. Only an ACK or a
   reconciliation establishes that an order exists. HTTP 201 from a queued-order venue is ACK_QUEUED,
   not RESTING. RESTING needs the venue's resting confirmation.
6. **Partial fills.** Fill events carry native fractional quantities (the 0.01 Kalshi step, never
   truncated), prices and fee quotes per fill. Exposure and reservation are adjusted per fill.
   The fee claim basis follows ADR 0017.
7. **Cancel request versus confirmation.** CANCEL_REQUESTED changes nothing financial. A
   cancelled order may still have filled first; only CANCEL_CONFIRMED plus a fill reconciliation
   releases the unfilled remainder.
8. **Unknown state and quarantine.**
   - A timeout, a lost response or an unparseable answer gives OUTCOME_UNKNOWN.
   - A timeout **never** releases capital and **never** triggers a blind resubmission.
   - While any intent on a market is OUTCOME_UNKNOWN, that market (and, by policy, the account)
     accepts no new risk. This is the existing `ORDER_STATE_UNHEALTHY` control.
9. **External reconciliation.** A reconciler reads the venue's orders, fills, positions and
   balance, and maps each venue order to an intent by client key or by (market, side, price, size,
   time window).
   - A late fill is applied **exactly once**, keyed by the venue fill id.
   - An unmatched venue order or fill is an incident: it raises an alert and blocks new risk. It
     is never ignored.
   - Balance drift beyond the fee rounding allowance is an incident.
10. **Restart recovery.** On start, replay the journal. Every intent that is not terminal goes to
    reconciliation before the worker takes a lease for new work. Nothing is resubmitted from
    memory.
11. **Orphan-leg policy (multi-leg sets, Family B).** Legs are submitted as independent intents;
    they are never assumed atomic.
    - Each leg reserves its own worst-case cash.
    - The basket has a declared orphan tolerance. If one leg fills and another does not, the
      filled leg's orphan exposure (as `payoff_constraints` reports it) stays reserved.
    - The policy is either unwind (a sale needs its own proven sell model, out of scope) or hold
      to settlement. A new basket is never opened to "complete" an orphan.

## Tests the package must ship (fake credentials, simulated transport only)

The simulated transport is structurally incapable of reaching a network: it is an in-process fake.
Its tests must cover:
- two workers spending the same balance;
- a crash before or after submission;
- a reused client id;
- a lost response;
- a cancel/fill race;
- delayed partial fills after a restart;
- a stale lease holder;
- duplicate or out-of-order events;
- a missing account snapshot;
- a reserve released exactly once;
- a late fill reconciled exactly once;
- a timeout that neither releases nor resubmits;
- a compromised-key drill on fake credentials.

## Alternatives considered

- **An external broker SDK or order-management service.** Rejected: a dependency and a surface
  that are not needed for one venue.
- **In-memory locks.** Rejected: they do not survive a restart or a second process.
- **Retrying until success.** Rejected: unsafe under non-idempotent placement (Novig).

## Tradeoffs

- SQLite single-host serialization limits throughput. That is acceptable for small bootstrap
  sizes; reconsider with measured contention.
- Conservative quarantine can block trading on a venue hiccup. That is the intended failure mode.

## What would make us reconsider

- A venue that offers true idempotent keys and atomic multi-leg orders, documented and verified
  (then the orphan policy changes for that venue only).
- A measured need for more than one execution host.
