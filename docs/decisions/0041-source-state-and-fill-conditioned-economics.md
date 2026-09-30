# ADR 0041: Source, game-state and fill-conditioned economics contracts (R2, offline)

**Status:** Proposed 2026-09-29 (R2 PR A, Writer A). Scope: roadmap package R2, #145.

**Offline only.** Contracts, fixtures and tests. This ADR adds:
- no transport, credential, provider call, stream, timer or production access;
- no DB migration and no `storage.py` change;
- no research slot or experiment id.

EXP-001 and EXP-002 are untouched:
- no NHL, in-game or RFQ data enters EXP-002;
- its baseline and weights are not read or changed;
- `check-frozen` stays clean.

## Problem

Staleness in the repository was age-based only. It had no way to say:
- which game state a quote reflects;
- that a newer state version makes a recommendation obsolete;
- which source family a quote comes from, or how uncertain its clock is.

It also could not compare two sources' timing without inventing precision. The economics layer
screened captured books (episodes). It could not answer what our *fills* earned, by taking,
book-making or RFQ mode. Nor could it keep hypothetical quotes, unobservable outcomes and actual
fills apart.

## Decision

Extend the existing owners. No new module is added.

| Owner | Added | Why it belongs there |
|---|---|---|
| `inplay_evidence.py` (`source-state-v1` section) | `ClockReading` (precision, uncertainty, `clock_id`), `clock_order` (UNORDERED on overlap); `LatencyBreakdown` (six stages, unmeasured = None); `SourceObservation` (source family or UNKNOWN, context, declared incorporated state, `EvidenceStatus` + `DataKind`); `ObservationLog` (append-only); `content_freshness`; `state_relation`; `decision_validity`; `source_leadership` | It already owns the separate clocks (`Stamps`), the append-only `GameJournal` and `DataKind`. Source and state validity are the same evidence contract, one level up |
| `position_policy.py` | `evaluate(state_validity=...)`: a non-VALID state gives BLOCKED with `review_required` | It is the single position-policy owner (ADR 0038) |
| `inplay_replay.py` | optional `CohortEntry.state_journal`. The bot arm revalidates at submission; the pre-placed arm counts `fills_after_state_change` | It is the hold-vs-exit replay owner. Without a journal, results and cohort hashes are unchanged |
| `research_economics.py` (`fill-conditioned-economics-v1` section) | `ExecutionMode`, `Fill`, `fill_economics`, `markouts`, `liquidation_value`, `seasonal_scenario`, `FunnelRecord`/`funnel_report`; `_capital_returns` shared with `replay` | It is the canonical economics owner. The capital-return arithmetic is shared, not copied. The episode screen's outputs are unchanged |
| `execution_ticket.py` | pure `reserve_simultaneous_obligations` | It extends ADR 0035 item 3 (reservation) for obligations that bind at the counterparty's choice |

### Rules

- **A game clock is not UTC.** `ClockReading` refuses naive and non-UTC text.
- **Receipt order never proves incorporation.** Only a source's own documented declaration makes the
  incorporated state KNOWN. A publication provably before the event makes it CANNOT_INCORPORATE.
  Everything else is UNKNOWN.
- **Content freshness uses the publication clock.** A book received a second ago but published ten
  minutes ago is STALE. Without a stamp, freshness is UNKNOWN, unless the receipt alone already
  proves it is stale.
- **Corrections append.** `ObservationLog` refuses to overwrite and links each correction.
- **Invalidation is a policy state.** A material new event, a correction, an unreadable later update
  or an out-of-order update makes a dependent recommendation INVALIDATED or REVIEW_REQUIRED. It
  never becomes an order, a cancellation or a liquidation.
- **Two vocabularies, different meanings.** `EvidenceStatus` (ACTUAL / SIMULATED / HYPOTHETICAL /
  UNAVAILABLE) says whether the thing happened. `DataKind` says where the input came from. They are
  orthogonal: a SIMULATED fill can replay RECORDED books. `check_evidence` ties them together: ACTUAL
  needs RECORDED input, and UNAVAILABLE has none.
- **Source leadership is reported in both directions and names no winner.**
  - Moves must clear bid/ask noise.
  - Co-moves whose windows overlap, after capture spacing and clock uncertainty, are UNORDERED.
  - Shared or unknown families are reported as dependence.
  - The count of variants tried is a required input and part of the result.
  - Sparse captures give INSUFFICIENT_RESOLUTION.
- **The leadership report is fixture- and synthetic-fed in this batch.** `SourceSeries` refuses
  RECORDED input and any point at or after 2026-10-22 00:00 ET (`LEADERSHIP_REFUSED_FROM_UTC`).
  Stored NFL pilot pairs are not read before the single logged EXP-002 A.C timing run. No kickoff on
  or after 2026-10-22 is read. It has no outcome or label input.
- **Fill-conditioned economics.**
  - Modes are separate groups. P&L is attributed to a group only when an instrument's fills all sit
    in it.
  - ACTUAL and SIMULATED fills are never mixed.
  - P&L is a cash change, and residual inventory is never valued at 0.
  - Fees count once, and a fee inside the price refuses a second one.
  - A reused displayed depth, or collateral beyond capital, is refused.
  - Rebates, promotions and fixed cash costs are separate lines, and unsubsidized net is always shown.
  - Owner hours stay unpriced.
  - A markout needs a declared horizon and benchmark, is signed by direction, and is not liquidation
    profit.
  - Peak windows are never annualized.
  - In the funnel, UNKNOWN is not a nonfill, and no execution probability exists without observed
    outcomes.

## Alternatives considered

- **A new `source_state.py` module.** Rejected. The clocks, journal and data kinds it would need are
  already in `inplay_evidence`, and a second module would fork the evidence contract.
- **Mapping EvidenceStatus into DataKind.** Rejected, because they answer different questions (see
  Rules). Folding them together would let a replay over recorded books pass as ACTUAL.
- **Infer incorporated state from receipt order.** Rejected. It manufactures certainty the feeds do
  not give.
- **Rank sources ("A leads B").** Rejected. Counts in both directions, with dependence and
  resolution, are the honest output.
- **A new P&L engine for fills.** Rejected. The capital arithmetic is `research_economics`'s, and it
  is shared.
- **A `STATE_INVALIDATED` control in `pre_submit_checks` now.** Deferred to R5
  (`docs/research/EXECUTION_MODES_GAP.md`). The control chain's order and tests stay unchanged
  until an executor needs it.

## Tradeoffs

- UNORDERED and INSUFFICIENT_RESOLUTION will dominate on today's sparse data. That is the intended,
  honest result.
- Treating every non-clock field change as material, by default, over-invalidates. A policy can
  declare its own material fields.
- Refusing capital over-commitment and depth reuse raises rather than reports. A simulation that
  does either has a bug, not a finding.

## What would make us reconsider

- A source that documents a state sequence number: incorporated state becomes KNOWN for it.
- Measured clock error bounds per source: fewer UNORDERED results.
- An allocated experiment id with an evidence-use record and a post-A.C decision: RECORDED
  leadership series could be admitted, for pre-holdout dates only.
- Account-verified venue semantics for RFQ binding and partial acceptance: the reservation rule in
  the gap note changes for that venue only.
