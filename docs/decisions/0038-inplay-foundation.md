# ADR 0038: In-play foundation v1: evidence contract, pure position policy, hold-vs-exit replay

**Status:** Proposed 2026-09-28 (VF Writer B, PR B). Authority:
`docs/owner/2026-09-28-exp002-validation-inplay-foundation-directive.md` (#122 offline work).

**Offline only.** This ADR builds:
- no transport, credential, account read, order route, timer or production acquisition;
- no research slot and no experiment id.

`EXECUTION_NOT_AUTHORIZED` stays the last control of `execution_ticket.pre_submit_checks`, and
it always fails. The source-feasibility record and the proposed (not approved) pilot are in
`docs/research/INPLAY_SOURCE_FEASIBILITY.md`.

## Problem

Owner Idea #122 asks whether managing a sports position **during** the game (HOLD, REDUCE,
EXIT; later RE-ENTER, ADD) beats holding to settlement after costs, or meets a declared risk
objective. Everything in the repository assumes hold-to-settlement. Answering the question
honestly needs four things the repository lacked:

1. An evidence contract for in-play books and game state. Snapshot-plus-delta sequencing, gaps,
   corrections and several clocks must not quietly become "the price at time t".
2. A pure policy that proposes an action, and refuses one, without inventing a probability or
   liquidating through bad data.
3. A replay that compares arms over identical entries. It must keep bot-triggered and preplaced
   execution apart, never fill through gaps, and keep accounting that cannot oversell,
   double-count or value an unknown as zero.
4. A future-execution design in which the Kalshi app's native Auto Sell and a bot never both
   sell the same contracts.

## Decision

### Three new pure modules; nothing existing is forked

| Module | Owns | Reuses |
|---|---|---|
| `inplay_evidence.py` (`inplay-evidence-v1`) | book reconstruction (valid start, `seq`/`sid` counted per subscription across markets by default, the scope UNVERIFIED and a conflicting repeat failing closed, one market per subscription the supported safe mode; duplicates, gaps → UNUSABLE until resync, negative/crossed → UNUSABLE), separate clocks, append-only game-state journal with linked corrections, coverage report, JSONL **file** transport only | `opportunity.walk_ladder` for sale walks (selling YES into YES bids mirrors taking NO asks at 1 − b); `fee_schedules.valid_price`; `OutcomeFinality` |
| `position_policy.py` (`position-policy-v1`) | HOLD / REDUCE / EXIT proposals, bounded quantities, refusal states | `execution_ticket.OrderState` / `OPEN_ORDER_STATES` for order state; `fee_schedules.schedule_for` / `verification_at` / `taker_buy` for fees (no fee formula copied) |
| `inplay_replay.py` (`inplay-replay-v1`) | three arms × two execution semantics over one cohort; isolated in-memory ledger; oracle diagnostics; sensitivities; calibrated synthetic nulls | `position_policy.evaluate` for every decision; ADR 0037's labels |

There is no new risk engine, executor, account ledger, scheduler or model registry.
`risk.py`, `execution_ticket.py`, `research_economics.py` and the shadow ledger are unchanged.
`position_policy.py` is the single planned owner of the position-policy primitive.

### Policy rules

- **No probability input exists**, so none can be invented. A fair-value policy is UNSUPPORTED
  until its model is independently justified, and REENTER and ADD are UNSUPPORTED. Entry cost is
  carried for accounting, never as the valuation anchor.
- **Stale inputs block new risk and never trigger liquidation.** Each of these gives BLOCKED
  with `no_new_risk` and `review_required`, never EXIT:
  - a missing, stale, future-dated or unreconstructed book;
  - a paused or closed market;
  - unknown or stale inventory;
  - unpinned rules;
  - a PENDING or OUTCOME_UNKNOWN order.

  The response to a kill state is a separately authorized reduce-only or cancellation procedure.
  It is not a market sale through an empty book.
- **Displayed is not executable.** A bid below the target, or an empty bid side, gives HOLD.
  Depth at or above the target bounds the quantity. Truncated depth is stated, never
  extrapolated.
- **The policy cannot act.** `PolicyDecision.authorizes_execution` is always False (constructing
  True raises). The module has no transport, signing or submission surface, which
  `tests/test_inplay_regressions.py` checks.

### Native Auto Sell versus bot: one inventory, reserved

Verified on 2026-09-28:
- Kalshi Auto Sell is a **resting limit sell** that can fill with the app closed and can fill
  partially.
- The Create Order V2 docs accept `reduce_only` **only with immediate_or_cancel**. A resting
  (GTC) take profit therefore cannot be reduce-only.
- A sale beyond the held quantity may open NO exposure (INFERENCE from the signed position;
  unverified on an account).

So:
1. Every open sale reserves inventory, whatever its origin (native Auto Sell, manual, bot or
   unknown): PENDING, OUTCOME_UNKNOWN and RESTING, including cancel-*requested*. Only a
   confirmed cancel or a fill releases it. The policy sells only `held − reserved`.
2. Reservations above holdings (a manual sale under a resting Auto Sell) are OVER_RESERVED:
   BLOCKED, never "sell the difference".
3. A preplaced policy proposes its resting sale once. Later evaluations see it as reserved and
   HOLD, so repeated calls cannot duplicate sales.
4. The future executor (ADR 0035) extends `execution_ticket.py` with its single-authority lease,
   fencing tokens and atomic reservation. Two changes are needed:
   - The reservation covers **inventory** for sells, beside cash for buys.
   - Reconciliation must import native and manual orders before any bot order is drafted.

   A bot IOC exit should set `reduce_only=true`, which the docs allow for IOC. A resting exit
   cannot, so its reservation is the only guard.

### Replay rules

- **Identical cohort.** Every arm (HOLD, FULL_EXIT, PARTIAL_EXIT) sees the same entries, times,
  quantities, capital and evidence, pinned by one cohort hash.
- **BOT_TRIGGERED.** The policy decides on the book received at detection. The marketable limit
  arrives after decision plus arrival latency. It fills only against the first usable book
  received at or after arrival, and only within `max_arrival_gap`.
  - It never fills on the detecting book. A zero decision-plus-arrival latency is refused unless
    the configuration names `diagnostic_mode="FIRST_DETECTION_ZERO_LATENCY"`. Such a report is a
    labelled diagnostic: it is never a policy result and never supports an after-cost claim.
  - Unknown arrival latency is no fill.
- **PREPLACED_LIMIT.** A resting sale at the target is placed at entry. It needs an admissible
  book to be placed: one received at or before placement, and no older than `max_book_age`, which
  may be a book from just before entry. It reserves its inventory.
  - An entry whose sale was never placed is `placed=False`, and its arm reports a `not_placed`
    count, so a never-placed arm cannot pass for HOLD.
  - Fills are keyed by book identity (evidence id, or position, plus receipt). Books that share a
    receipt time are counted and reported.
  - Under STRICT_THROUGH (the default) it fills only when a usable book shows bids *strictly
    above* the limit, at the limit price, and only up to the largest crossing size yet seen.
    Visible size is never summed across snapshots.
  - A touch is counted, not filled. TOUCH_UPPER_BOUND is a labelled diagnostic.
  - The preplaced arm never uses information later than its placement.
- **No interpolation.** A book that is not usable, or that falls between samples, is no evidence
  of a fill.
- **Diagnostics apart.** FIRST_DETECTION_ZERO_LATENCY and HINDSIGHT_UPPER_BOUND (ADR 0037) are
  reported separately and never as arm results.
- **Accounting.** The ledger rules:
  - no overselling and no double reservation;
  - one fill per fill id, one fee per fill;
  - a cancel request releases nothing, and a late fill still lands;
  - the residual settles exactly once, and sold contracts get no payout;
  - resting orders expire at close;
  - the cash-flow and quantity reconciliation must come out empty.

  Proceeds are not profit: P&L is the cash change over the common horizon. Released cash stays
  idle; nothing is recycled.
- **INCOMPLETE, never 0.** A missing settlement value or finality leaves the entry's P&L at None,
  and the arm totals too. A COMPLETE-only subtotal is labelled as such.
- **Fees.** An unknown fee (today KXNFLGAME, a non-standard series, Kalshi Q7) blocks every
  after-cost figure, while gross stays as a labelled diagnostic. `after_cost_claim` is True only
  when all three hold:
  - a claimable fee basis;
  - every cost known;
  - non-synthetic evidence.

  Resting fills are charged the taker fee, an upper bound where the maker fee is lower.
- **Real data is refused in v1.** A RECORDED cohort is refused: real in-play evaluation needs an
  allocated experiment id and an evidence-use record. Synthetic and fixture labels must say so.
- **Nulls.** A calibrated-martingale synthetic null (P(YES) = price by construction) shows that
  take-profit does not manufacture alpha before costs and loses after spread and fees. The tests
  pin both.

## Alternatives considered

- **Extend `research_economics.replay`.** Rejected. It replays episode-level pregame
  opportunities with capital pools. The in-play question needs order-level timing, reservations
  and residual settlement. Writer A owns that file in this directive.
- **Put the policy in `execution_ticket.py`.** Rejected. A ticket is an order draft for the
  approval boundary; a policy proposal is research output. Mixing them would make a research
  result look one step from submission.
- **A reorder buffer for out-of-order deltas.** Deferred. Failing closed until a snapshot is
  simpler and safe. Reconsider if measured resync cost is high.
- **Fill resting orders on touch.** Rejected as the default, because queue position is unknown.
  It is kept as a labelled upper bound.
- **Route A (stream) first.** Deferred. It needs a credential whose documented scope includes
  account reads (see the feasibility record).

## Tradeoffs

- STRICT_THROUGH and the max-crossing rule understate what a resting order might have got. That
  bias is conservative and deliberate.
- Sampled REST books (route B) cannot see between polls. The replay records this as absence of
  evidence, so fill counts are lower bounds.
- Whole-contract quantity steps keep fees modelled (no fractional-fill fee rule exists) at the
  cost of floors on partial exits.

## What would make us reconsider

- An account-level verification of YES/NO netting and of whether Auto Sell orders are
  reduce-only.
- A documented market-data-only key scope. That would make route A viable without account-read
  authority.
- Measured queue and fill data (gate 8 or later), which would replace the fill-rule bounds.
- A defensible state or fair-value model, which would move FAIR_VALUE out of UNSUPPORTED through
  its own review.

## Frozen EXP-001, EXP-002

Untouched. No in-play data, label or window touches EXP-002. `check-frozen` stays clean.
