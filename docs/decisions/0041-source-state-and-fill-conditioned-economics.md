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
| `research_economics.py` (`fill-conditioned-economics-v1` section) | `ExecutionMode`, `Fill`, `Resolution`, `fill_economics`, `markouts`, `liquidation_value`, `seasonal_scenario`, `FunnelRecord`/`funnel_report`; `_capital_returns` shared with `replay` | It is the canonical economics owner. The capital-return arithmetic is shared, not copied. The episode screen's outputs are unchanged |
| `execution_ticket.py` | pure `Obligation` and `reserve_simultaneous_obligations`: the **one** reservation primitive (RFQ research, #148, calls it rather than keeping its own) | It extends ADR 0035 item 3 (reservation) for obligations that bind at the counterparty's choice |

### Rules

- **A game clock is not UTC.** `ClockReading` accepts only an ISO-8601 instant with a UTC offset (any
  offset is converted to UTC). It refuses a naive time and any other text, such as a game clock.
- **Receipt order never proves incorporation.** Only a source's own documented declaration makes the
  incorporated state KNOWN. CANNOT_INCORPORATE needs a publication provably before a *lower* bound on
  the event's time (`event_not_before`, for example the previous state's time). A scoreboard's
  publication time is an upper bound on the event, never that lower bound. Everything else is UNKNOWN.
- **Content freshness uses the publication clock.** A book received a second ago but published ten
  minutes ago is STALE. Without a stamp, freshness is UNKNOWN, unless the receipt alone already
  proves it is stale.
- **Corrections append.** `ObservationLog` refuses to overwrite and links each correction.
- **Invalidation is a policy state.** A material new event, a correction, an unreadable later update
  or an out-of-order update makes a dependent recommendation INVALIDATED or REVIEW_REQUIRED. It
  never becomes an order, a cancellation or a liquidation. "Later" means later first-observed time,
  whatever the journal's append order. `evaluate` refuses a validity computed for another state
  version or at another instant.
- **Two vocabularies, different meanings.** `EvidenceStatus` (ACTUAL / SIMULATED / HYPOTHETICAL /
  UNAVAILABLE) says whether the thing happened. `DataKind` says where the input came from. They are
  orthogonal: a SIMULATED fill can replay RECORDED books. `check_evidence` ties them together: ACTUAL
  needs RECORDED input, and UNAVAILABLE has none.
- **Source leadership is reported in both directions and names no winner.**
  - Both series must be on the same event and the same clock basis (PUBLISHED or RECEIVED), and every
    point's clock origin must match that basis.
  - Moves must clear bid/ask noise. One-sided quotes are bridged over and counted, never dropped silently.
  - Matching is symmetric: swapping the arguments swaps the two directional counts and nothing else.
    A move with more than one candidate partner is AMBIGUOUS and gets no direction.
  - Co-moves whose windows overlap, after capture spacing and clock uncertainty, are UNORDERED.
  - Shared or unknown families are reported as dependence.
  - The count of variants tried is a required input and part of the result.
  - Sparse captures give INSUFFICIENT_RESOLUTION.
- **The leadership report is fixture- and synthetic-fed in this batch.** `SourceSeries` carries its
  `event_id` and `kickoff_utc`, and refuses:
  - RECORDED input;
  - a kickoff at or after 2026-10-22 00:00 ET (`LEADERSHIP_REFUSED_FROM_UTC`);
  - a point whose latest possible true time (`interval()[1]`) is at or after it. With an unknown clock
    bound, that is the stamp plus precision plus 24 hours.

  Stored NFL pilot pairs are not read before the single logged EXP-002 A.C timing run. It has no
  outcome or label input.
- **Fill-conditioned economics.**
  - Modes are separate groups. P&L is attributed to a group only when an instrument's fills all sit
    in it.
  - ACTUAL and SIMULATED fills are never mixed.
  - P&L is a cash change, and residual inventory is never valued at 0.
  - Fees count once, and a fee inside the price refuses a second one.
  - Capital is a cash balance: capital plus realized results, minus fees paid and open collateral. It
    may never go negative. A realized loss is gone whether it came from settlement or a closing trade,
    and a flat or settled instrument deploys nothing, so both exit paths give the same capital-days
    and returns.
  - A reused displayed depth is refused, and so is a settlement value outside [0, 1].
  - Rebates, promotions and fixed cash costs are separate lines, and unsubsidized net is always shown.
  - Owner hours stay unpriced.
  - A markout needs a declared horizon and benchmark, is signed by direction, and is not liquidation
    profit.
  - Peak windows are never annualized.
  - In the funnel, UNKNOWN is not a nonfill. Each record carries its evidence status and data kind.
    An own fill rate comes only from ACTUAL own quotes with every outcome observed. A simulated rate
    is reported apart, labelled as a simulator's output.

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
- Known limitation: an unknown fee is not charged to `fill_economics`' cash balance, so the capital
  check can pass where the real fee would not; every net figure is already blocked (FEE_SCOPE_UNKNOWN).

## What would make us reconsider

- A source that documents a state sequence number: incorporated state becomes KNOWN for it.
- Measured clock error bounds per source: fewer UNORDERED results.
- An allocated experiment id with an evidence-use record and a post-A.C decision: RECORDED
  leadership series could be admitted, for pre-holdout dates only.
- Account-verified venue semantics for RFQ binding and partial acceptance: the reservation rule in
  the gap note changes for that venue only.

## Addendum 2026-10-08: source change/event envelope (#181 Deliverable E, offline)

**Scope.** The 2026-10-08 directive (`docs/owner/2026-10-08-jev-crawler-wallet-directive.md`, EXECUTION_PLAN
entry E). Fixture-only code, tests and docs. No transport, poll, stream, scraper, scheduler, timer, budget change,
credential, model call or `edge_lab.execution` import. Nothing above in this ADR changes.

**Problem.** Deliverable E asks for one reusable contract for "a source said something changed". It must carry
identity, permission, receipt and claimed publication times, revision, sequence, links, coverage, freshness, evidence
class and fetch cost. It must also support novelty, dedup and change detection, observation-to-market response
latency and conditional lead-lag. Most of the parts already had owners. The missing piece was the composition: a
keyed, append-only change history across sources, with honest ordering rules and cost.

**Already covered, reused unchanged (and demonstrated by tests):**
- permission: `sources.REGISTRY` status;
- content digests: `provenance.payload_sha256`;
- freshness: `freshness.combine`, `require_fresh`;
- clocks, ordering and latency bounds: `ClockReading`, `clock_order`, `measure_between`;
- evidence class: `DataKind`, `EvidenceStatus`, `check_evidence`;
- content freshness on the publication clock: `content_freshness`;
- price-series lead-lag: `source_leadership`, unchanged;
- read coverage: `discovery.CoverageState`.

**Decision.** One new module, `src/edge_lab/source_changes.py` (`source-change-v1`). It composes those owners and
copies none of them. It is a module rather than another `inplay_evidence` section because envelopes cover
documents, rules, schedules and listings as well as in-play feeds, and `inplay_evidence` is already the largest
evidence module. The first rejected alternative of this ADR (a separate `source_state.py`) is still respected: no
clock, journal, data-kind or leadership type is redefined here.

**Rules:**
- **Permission is never self-asserted.** An envelope's `source_permission` must equal the registry's. RECORDED
  content needs a registered ACTIVE source. FIXTURE and SYNTHETIC content may name any source, so fixture work
  needs no collection permission.
- **Receipt order alone never orders two copies of one source.** Supersession needs one of:
  - a source sequence with the same documented scope;
  - provably ordered publication stamps;
  - non-overlapping fetch windows (the older copy's receipt provably before the newer copy's request).

  Otherwise the copy is ORDER_UNKNOWN. The key then has several current copies, and its freshness is UNKNOWN
  until a provably newer copy resolves it. A provably older copy is a LATE_ARRIVAL and never becomes current. The
  same sequence number with different content is a SEQUENCE_CONFLICT.
- **Duplicates are availability, not news.** The same copy again is REPLAYED. The same content from the same
  source is a DUPLICATE. Content another source already reported is an ECHO. Only content never seen on the key is
  `novel`.
- **Contradictions are recorded, never resolved.** A source's current content that differs from another source's
  current content gets a CONTRADICTS link. Decision use of both sources fails closed: `key_freshness` gives UNKNOWN,
  so `require_current` raises through `require_fresh`.
- **Origin is not established here.** "First observed by us" is not first published. A site name, a stated
  attribution (`attributed_to`) or a recent stamp is a claim. `attribution` reports who we saw first and who
  claims the earliest stamp, and keeps `original_publication` UNKNOWN.
- **Response latency is a window.** It runs from the last unchanged market capture to the first changed capture
  provably after the observation, each widened by its clock error bound. It is UNKNOWN when:
  - identity is not linked (SAME_ID or a named, versioned DECLARED_MAPPING);
  - a capture is on another market (an identity mismatch, never a silent filter);
  - there is no baseline capture;
  - a cross-clock bound is unknown.

  A change that cannot be placed before or after the observation is UNORDERED. A market that never changed gives
  only a lower bound.
- **First-report leadership** compares report windows in both directions, conditioned on a stated
  `SourceContext`. A RECEIVED-basis window opens at the last earlier capture without the content. Without such a
  capture it is unbounded below, so polling cadence bounds every claim. Windows wider than the required resolution,
  or with unknown clock bounds, give INSUFFICIENT_RESOLUTION. Shared or unknown families are reported as dependence.
  The count of variants tried is a required input.
- **Reports are fixture- and synthetic-fed in this batch.** `response_latency` and `first_report_leadership`
  refuse RECORDED input. Real input needs an approved collector, an allocated experiment id and an evidence-use
  record first.
- **Cost: unknown is never zero.** `FetchCost` with an UNKNOWN basis carries no amounts. Zero money needs MEASURED
  or DOCUMENTED evidence and a reference. Totals take the worst basis, and one unknown amount makes that total
  unknown. `SourceYield.money_per_novel` is None unless the cost is known.

**Tradeoffs.**
- Validating permission against the current registry means that a later registry change makes older envelopes
  fail to load until they are migrated in a reviewed change. This is deliberate, and today no RECORDED envelope
  exists.
- Strict ordering will leave many real poll pairs ORDER_UNKNOWN unless collectors record request times. That is
  the intended pressure on any future collector.
- The ledger is in-memory and O(n) per append. That fits fixtures. A persistent store would be a separate,
  additive `storage.py` change with its own review.

**Reconsider when:**
- a source documents a sequence or revision field (its copies then order without fetch windows);
- the owner approves a collector for a source in `docs/research/SOURCE_ACTIVATION_PACKET.md` (its envelopes then
  need persistence and an evidence-use record);
- measured clock bounds per source exist (fewer UNKNOWN latencies).

Tests: `tests/test_source_changes.py`, `tests/test_source_changes_reports.py`. Each rule above was mutation-checked
(23 deliberate breaks, all caught).
