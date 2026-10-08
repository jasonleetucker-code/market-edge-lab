# ADR 0046: The supervised execution orchestrator (one service, bounded cycles, FIXTURE only)

**Status:** Proposed 2026-10-07 (#160, campaign package K). Authority: the 2026-10-07 (evening) entry of
`docs/EXECUTION_PLAN.md`, which authorizes "one supervised orchestration service in the execution package" that
starts DISARMED with only FIXTURE egress possible. Boundary: ADR 0043. Risk gate: ADR 0044.

## Problem

Packages A–I built the parts: exact intents, the journal and reservations, the lifecycle reducer, the wire format,
account reads, the risk gate and the control contract. Nothing composes them. Demonstration B
(`docs/strategy/MARKET_V1_ACCEPTANCE.md` §5) needs repeated cycles through the real components, with faults and
process death, and proof that no exposure is duplicated, reservations survive and a shutdown is safe.

Composition is where the dangerous paths live:
- a send without a committed reservation;
- a retry of an ambiguous write;
- a backlog replayed as fresh after a restart;
- a service that arms itself.

## Decision

1. **One module, `execution/orchestrator.py`, and no capability.** It imports no transport and no signer. The
   caller supplies `send(WireRequest) -> reply` (the `TransportResult` shape). `CAPABILITY_USERS` is unchanged:
   the orchestrator is not a capability user, because it never needs the transport's internals, only one call.
2. **Start only through `control.boot`.** The egress lease is taken first, so an older fence's in-flight
   attempts become OUTCOME_UNKNOWN, and a start refused because another worker holds a live lease writes nothing.
   Then `Started` is persisted, before anything acts. Every start is DISARMED. Only an operator's `request_arm`
   changes the mode, judged once by `control.decide_arm` and persisted.
3. **Persistence through the journal, with no schema change.** Control events (`append_control_event`) and
   orchestrator records (`append_control_record`: signals, decisions, planned intents, P&L observations,
   settlements, attributions, cycles) are ordinary hash-chained rows of `events`, subject = scope key. The
   schema version stays 1. In-memory state is a cache rebuilt from these records at start.
4. **Cycle order: safety before new risk.** The steps run in this order:
   1. lease renewal;
   2. this process's leftover in-flight attempts become unknown;
   3. the full account read (package G) inside the request budget and deadline;
   4. the snapshot;
   5. `ReconciliationObserved`;
   6. venue evidence applied to our own orders through the lifecycle reducer;
   7. only then signals, strategies, arbitration, the risk gate, control and sends;
   8. settlement and attribution records;
   9. a health review that raises incidents.

   Every anomaly a step finds is raised as a control incident (a disarm) before the next step: the read and
   evidence anomalies (an acknowledged order missing from a COMPLETE listing, a duplicate client id at the venue, a
   lifecycle quarantine, an unknown attempt that cannot be resolved, a journal refusal, a quarantined reservation,
   a degraded reconciliation) are raised before any decision, and a decision-phase anomaly before the next
   decision (review finding F1).
5. **One attempt per intent key, ever.** An `INTENT_PLANNED` record is written before `prepare_attempt`. A
   planned key is never prepared again. An ambiguous send stays OUTCOME_UNKNOWN until the order listing resolves
   it: found means ACKNOWLEDGED; not found in a COMPLETE listing, `NOT_FOUND_MIN_DELAY` after the send, means
   ABSENT. It is never re-sent.
6. **Arbitration.** Reductions come first, then strategy order, then intent key. At most one intent per market
   per cycle, and at most `max_intents_per_cycle`. Each intent is gated on a fresh `account_view`, and the
   journal's transactional reservation is the hard capacity check.
7. **Grant usage from persisted records.** In BOUNDED_AUTO each order gets a POLICY `ApprovalGrant` bound to its
   digest and the armed grant's digest (nonce = intent digest, single use). Usage comes from the journal and
   records:
   - exposure: $1 per held contract plus an ENTRY's full cost while held;
   - turnover: today's attempts;
   - losses: the venue's realized P&L ledger.

   The orchestrator never issues an `AutomationGrant`. The usage's `as_of` is the time of its evidence (the older
   of the snapshot's observation and the P&L ledger's last COMPLETE read), not the decision time, so stale evidence
   blocks as stale usage (F3). Turnover per day, P&L per day, equity and peak are running aggregates rebuilt from
   the persisted records at start; no decision rescans history (F6).
8. **Signals.** The queue is bounded and typed. Signals are refused at admission when they are:
   - out of identity (another scope, an unknown strategy, an unregistered source);
   - duplicates, from the future, expired, or valid for too long.

   Accepted signals are persisted. At start, a backlog signal whose validity has ended is QUARANTINED_RESTART.
   Valid backlog is flagged to its strategy, and its age is judged by the risk gate's source and decision ages.
9. **Bounds.** Per cycle: signals drained, proposals, intents, network requests (reads and sends share one
   budget), and a deadline. Every record a cycle writes is bounded by these, and demonstration B measures the
   journal rows added per cycle.
10. **Shutdown.** It persists a Disarm. Resting orders stay unless `cancel_owned=True`. Then each of our own
    acknowledged orders is cancelled: `request_cancel` is journaled before the send, and the cancel is sent
    only while this process holds the lease. A cancel reply naming another order confirms nothing: it is kept as
    evidence and the reservation becomes UNKNOWN (F4). Nothing amends, and a cancel goes only to an order with no
    unknown outcome, so one operation is in flight per order (the package L requirement).
11. **Fencing (F2; amended 2026-10-07 by package J's review follow-ups).** Only the egress lease holder writes. A
    worker that lost the lease is fenced out: it writes nothing (no snapshot, control event, record, receipt,
    attempt or reservation change) and sends nothing, because the live worker's control log and journal are no
    longer its own. It does not even raise a lease-lost incident, which would land in the live worker's log and
    make that worker's replay diverge from its live state. Only attempts of this instance's own fence are turned
    unknown at a cycle start.

    *What the check is.* Each journal write re-reads the lease from the store immediately before it
    (`_check_writer` calls `_lease_held`); a cached "fenced out" flag is never trusted on its own. The check is per
    write, not per group of writes: control events and records go through `_apply`/`_record`, and every direct
    journal write goes through `_write` (the in-flight sweep, the snapshot, lookup receipts, attempt resolution,
    fills, cancels, releases, each write recording a send's reply, and each write of a shutdown cancel, from
    `request_cancel` to the receipt and the reservation move); at boot, `Started` and `GENESIS` go through
    `_write` too. Three writes are not behind it, each because it is its own fence check in one transaction:
    `acquire_lease` (the first thing a boot does: refused with LeaseHeld, writing nothing, while another worker's
    lease is live; `recover` then runs as the new holder), `renew_lease`, and `prepare_attempt`.

    The original text said "re-read before every writing phase"; the package K review showed that was not enough.
    A supervisor restart under the **same worker id** takes a new fence while the old instance is mid-cycle; the
    old instance's cached flag stayed false, and its `_raise_pending` appended `IncidentRaised:journal-refused` to
    the control log after the new instance's `Started` (`test_orchestrator_fencing.py` reproduces it and now
    proves the old instance appends nothing). The package J re-review found the mirror case at boot: `Started`
    used to be appended before the lease was taken, so a second worker refused with LeaseHeld still left a
    `Started` in the live worker's log, and a replay of that log (the status export's) showed DISARMED while the
    live worker could send. A boot now writes nothing until it holds the lease
    (`test_a_boot_refused_by_a_live_lease_writes_nothing`). Package P's chaos lane reproduced both (P-1, the
    refused boot; P-2, a worker stalled inside a send past its lease that still recorded its DECISION and an
    incident) against the pre-review code; both reproductions pass on this design. No control event or record is
    appended anywhere except through `_apply`, `_record` or (for `Started` and `GENESIS` at boot) `_write`, so
    decisions, incidents, disarms, latches and every other control write are behind the per-write lease re-read;
    the three exceptions above are the only ones.

    *What happens on loss.* A write that finds the lease lost raises `OrchestratorFencedOut`; `run_cycle` turns
    that into a `fenced_out` report and nothing further is written. Every later `run_cycle` raises
    `OrchestratorFencedOut`, and `run(n)` stops after the cycle that found out, so a fenced instance does not keep
    reading the whole account every interval. Operator calls refuse the same way; `submit_signal` answers
    FENCED_OUT; a shutdown cut short reports what it did (a cancel whose reply could not be recorded reports
    CANCEL_OUTCOME_UNKNOWN). A reply that comes back after a takeover is not recorded by the old instance: the
    attempt is already OUTCOME_UNKNOWN (the takeover did that) and the live worker resolves it from the venue's
    order listing, never by a resend.

    *The remaining window, stated honestly.* The lease read and the write are separate SQLite transactions; nothing
    spans both, and the journal's control-event and record appends take no fence token. So a takeover that commits
    between a lease read and the write that follows it still lets **that one write** land (for example the ack
    receipt that comes before `mark_sent`). The next write re-reads and stops; `test_orchestrator_fencing.py`
    takes the lease over between two writes of a reply and of a cancel reply and proves the second is never
    attempted. A request already handed to `send` before a takeover can still reach the venue; the journal's
    transactional fence check in `prepare_attempt` remains the hard stop for starting a send, and the new holder
    reconciles anything in flight. The lease's expiry is not checked by `_lease_held` (only identity and fence
    token): an expired but untaken lease still lets this instance write evidence, and `prepare_attempt` refuses
    any send on it. Closing the window entirely needs fenced appends in the journal (a journal change, outside
    packages J and K).
12. **FIXTURE cash basis.** Package G reports the cash basis as UNKNOWN (ACC-02), so nothing could ever pass. A
    FIXTURE caller may declare `fixture_cash_basis`, the basis its fixture venue implements. It only fills a basis
    package G reports as UNKNOWN, never replaces a known one (F5); it is refused for every other environment and
    recorded in BOOT and every CYCLE record. The placeholder risk limits stay the
    default: tests pass explicit TEST limits as typed inputs.

13. **Stream recovery (package J, `execution/recovery.py`; added 2026-10-07).** There is no stream transport: it
    is future work that needs the owner's credential, source and budget approval. The recovery model is pure and
    immutable; the orchestrator holds its state in memory and is fed by an optional `StreamSource.drain(n)`,
    configured together with `OrchestratorConfig.recovery` (both or neither; without them nothing changes, and
    demonstration B's pinned hash is unchanged).
    - **Where it drains** (bounded by `max_items_per_drain`): before the account read, so that what arrived so far
      can be proven by it; before the strategies propose, when the cycle takes its marks (`recovery.marks`); at the
      start of each decision; and once more just before the decision acts (WOULD_SUBMIT or prepare and send).
    - **Proof.** After a COMPLETE reconciliation, `recovery.prove` clears every stream quarantine whose
      `not_before` is at or before the read's **proof time**: min(read start, `manifest.as_of_start`), the venue's
      own user-data time at the start of the read. A COMPLETE read may let that data time trail the start by up to
      `max_data_lag`, and data from before an anomaly cannot prove anything after it (package J review H1; the
      same rule `account` uses for a snapshot's `observed_at`). A read without a data time proves nothing, and a
      read must cover every subaccount the stream reports on (`RecoveryConfig.subaccounts`, default `{0}`, which
      is what the orchestrator reads). A REST/stream disagreement (the stream delivered a fill or a count at or
      before the proof time that the COMPLETE listing does not show) keeps that market quarantined and is raised
      as an incident before any decision, like every other evidence anomaly (rule 4). Stream observations after
      the proof time are not judged by that read. In practice a stream anomaly received at T is proven by the
      first cycle whose venue data post-dates T: usually the next cycle, not the current one.
    - **Invalidation drops decisions.** A decision is BLOCKED with `STREAM_INVALIDATED`, `STREAM_QUARANTINE` or
      `STREAM_DOWN` reasons when its market (or the account) changed since the marks, a quarantine covers it, or a
      required subscription is not live. Nothing is prepared or sent. A dropped decision is not retried: its
      signal was consumed, and the strategy re-evaluates on its next signal from fresh evidence. An account-wide
      quarantine blocks reductions too (fail-closed: a reduction sized on unproven positions could oversell).
      Market epochs come from a never-reused counter and are pruned at each proof; a pruning proof bumps the
      account epoch, so marks taken before it read every market as changed (a market unmarked then is not
      presumed unchanged). A book seen for the first time, or again after the bounded book table evicted it,
      counts as a change. A book side known to be empty and a side that is unknown are kept apart.
    - **A reconnect is not a cancellation.** A lost connection or a new subscription id changes no reservation,
      attempt or order; it only requires a REST proof before stream-dependent decisions proceed.
    - **Restart.** The recovery state is not persisted: a restart starts disconnected (STREAM_DOWN) and needs new
      subscriptions plus a COMPLETE read, which is the conservative reading of a lost process. A DISAGREEMENT
      quarantine clears only when a later read agrees; a restart drops it with the rest of the in-memory state,
      but the incident it raised is persisted and keeps the service DISARMED until an operator acknowledges it.
    - Every private-stream venue fact is UNKNOWN (`recovery.STREAM_FACTS`; the conformance pack excludes
      WebSockets). Tradeoff: REST may lag the stream, so a fill the stream delivered just before the venue data
      time of a read can show up as a disagreement and disarm. That is fail-closed; revisit once DEMO_OBSERVED
      latency evidence exists.
    - **Bounded memory.** Dedupe windows, tracked orders, fill ids per order and quarantined markets are bounded
      by `dedupe_window` and `max_tracked`; past `max_tracked` the state quarantines (account-wide) rather than
      forgetting silently, except books, which forget the least recently observed one (re-seeing it is a change).

14. **When a listed fill count is true (package P finding P-3; amended 2026-10-08).** Step 6 rebuilds each order's
    lifecycle view from one read: the order listing's cumulative fill count plus the same read's fills. That count
    was read at some moment inside the read, which no single time names. It therefore carries two times:
    - the **lower bound** `as_of_utc`: the snapshot's `observed_at`, min(read start, `manifest.as_of_start`), as
      before. The dispute check (a count below fills clearly before it) and the not-found delay
      (`NOT_FOUND_MIN_DELAY`) use it;
    - the **upper bound** `as_of_upper_utc`: `ReadManifest.data_true_by`, the latest of the read's end plus
      `account.CLOCK_SKEW`, the closing `as_of_end`, and the latest order or fill stamp the read returned
      (`latest_record_at`: a record existed when it was read).

    A fill is on top of the count only if stamped after the upper bound (and never inside the lifecycle's own
    `TIMESTAMP_SKEW` window, which the upper bound only widens). A fill between the bounds may already be inside
    the count: it is never added on top, and the view stays `fill_timing_uncertain` (fees are not reported
    complete). Uncertain is never coerced to "not covered" or to "covered and settled"; the fills received remain
    a lower bound, so a fill listing read after the order listing still raises `filled`. The same holds for a final
    count: an order canceled or executed inside the band keeps the venue's count (before, the band's fills on top
    of it exceeded it, FILL_EXCEEDS_OPEN_QUANTITY, and the order quarantined).

    *What is guaranteed, and what is checked.* Because the upper bound covers every order and fill of the read, no
    fill of one read is ever added on top of that read's own count, whatever the clocks do. Separately, a venue
    clock leading ours by more than `CLOCK_SKEW` breaks the read's timing assumption. The opening as_of check
    (USER_DATA_AS_OF_IN_FUTURE) misses such a lead when the as_of itself lags (a lead L with as_of lag A is caught
    there only if L - A > 5 s), so the read also checks its records: an order or fill stamped after the read's end
    plus `CLOCK_SKEW` is RECORD_STAMPED_IN_FUTURE. Either problem makes the read not COMPLETE and leaves live orders
    and fills unknown (None), so step 6 folds nothing from it and the incident disarms. A lead that neither the as_of
    nor any record shows goes undetected, but then no record of the read is stamped beyond the clock bound either.
    The package P review reproduced the gap this closes: a venue 7 s ahead with its as_of 3 s behind gave a COMPLETE
    read and 6 fills recorded against the venue's 3.

    Before this rule the count was labelled with the lower bound alone. Any fill stamped more than 2 s after it
    was added on top of a count that already held it, whenever the venue's user-data as_of lagged the read start by
    more than 2 s (accepted up to `max_data_lag`) or our clock trailed the venue's by 2-5 s (accepted up to
    `CLOCK_SKEW`). The journal then recorded 6 fills where the venue had 3, and the reservation went BOUND while
    the order rested (`tests/execution/test_fill_label.py`). This rule involves two tolerances, and the
    orchestrator defines neither: `account.CLOCK_SKEW` (how far the venue's clock may lead ours in an account read)
    and `lifecycle.TIMESTAMP_SKEW` (how far a fill stamp and a snapshot time may disagree). They are not the only
    clock tolerances in the package: `reservations.SNAPSHOT_CLOCK_SKEW` (a snapshot's observation time ahead of
    `now`), `recovery`'s `max_clock_skew` (stream stamps ahead of receipt) and the orchestrator's
    `SIGNAL_CLOCK_SKEW` (a signal's issue time) are separate, each owned by its module; consolidating them is out
    of scope here.

    A one-sided alternative (label the count with the upper bound only) also fixes P-3, but it would judge disputes
    at the read's end. A fill listing and an order listing that race inside one read would then quarantine falsely.

    *The lookup receipt.* Its payload now records everything `filled_quantity` is derived from: the order and fill
    records, `as_of_utc` (lower), `as_of_upper_utc` (upper), `authoritative_complete`, and the view's conclusion
    (`fill_timing_uncertain`, `fees_complete`). Re-folding the payload with the versioned lifecycle code reproduces
    the recorded count (`test_a_fill_just_before_a_read_is_recorded_once`); before, the payload held only the lower
    bound and re-derived 6 where the receipt said 3. This changes the payload, and so the receipt ids, of every
    lookup receipt. Demonstration B's pinned hash (`d331d6eb…`) is nevertheless unchanged, and was not re-pinned:
    its summary hashes cycle outcomes, counts, states, the venue's end state, attempts, the chain's event count and
    record-type counts, none of which includes a receipt id or payload. The demonstration summary was dumped before
    and after the payload change and is byte-identical. Its fixture venue also stamps fills 10 minutes behind every
    read, so no fill falls between the bounds there.

## Alternatives rejected

- **Make the orchestrator a capability user (import transport).** That is not needed, and it would widen
  `CAPABILITY_USERS` before package O's executor process exists.
- **New journal tables for orchestrator state.** That would change the schema and require a version bump. The
  events table already gives append-only, hash-chained and verified storage.
- **Retry an ambiguous send under the same client order id.** The venue's 409 meaning is UNKNOWN (ORD-16), and
  the journal forbids a blind resubmission.
- **Keep the signal queue in memory only.** A restart would silently drop it, and it would not prove that an
  expired backlog is quarantined.

## Tradeoffs and limitations

- **Venue facts the cycle rests on are provisional.**
  - A create reply carries counts, not a status. The status folded into the lifecycle is inferred: resting while
    anything remains, otherwise executed or canceled (ORD-14).
  - `NOT_FOUND_MIN_DELAY` (30 s) decides when "not found" proves absence.
- **Lookup and fill receipts are derived.** They are canonical JSON of package G's parsed records, not raw page
  bytes. Raw create, reject and cancel replies are kept verbatim.
- **The P&L baseline** (the first COMPLETE read) is dated at the account genesis. A loss realized between genesis
  and the first COMPLETE read would then fall outside the daily window. No order of ours can be placed before
  the baseline exists (PNL_HISTORY_UNKNOWN).
- **One account scope and one subaccount (0).** A BOUNDED_AUTO grant binds one strategy, so other strategies are
  blocked under it.
- **Reservation release lags a cycle.** A BOUND reservation is released only against a snapshot observed strictly
  after its end, so exposure is double counted for about one cycle (conservative).
- **A cycle that raises** (for example JournalBusy) writes no CYCLE record. The next cycle starts by turning any
  leftover in-flight attempt into OUTCOME_UNKNOWN.
- **In-memory dedupe sets are bounded** (F6): signal ids are kept only while still valid; recorded verdicts and
  raised incident ids keep the most recent `RECENT_MEMORY`. Forgetting one can only repeat a record or re-raise a
  recurring anomaly, never send. The planned-intent index and the order history stay complete in memory, because
  the risk gate requires the order history complete since genesis (ADR 0044); their size grows with attempts, not
  per decision.

## Reconsider when

- A stream transport is approved (package J's model is in place, rule 13): its venue facts (`STREAM_FACTS`) then
  need DEMO_OBSERVED evidence, signals and market state may come from it, and REST lag decides whether a
  disagreement should still disarm immediately.
- The journal gains fenced appends: the remaining window in rule 11 then closes.
- Package L defines kill latches beyond control's, or amend support: crossing cancel and amend answers then need
  their recovery rule here.
- Package O moves execution to its own process and service user: `send` becomes the real transport there, and
  the scheduler (a reviewed, owner-approved unit) calls `run`.
- ACC-02 is settled by a venue observation: `account.CASH_BASIS` changes, and `fixture_cash_basis` is no longer
  needed even in tests.
