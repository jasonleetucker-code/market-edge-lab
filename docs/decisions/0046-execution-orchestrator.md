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
2. **Start only through `control.boot`.** `Started` is persisted first. Every start is DISARMED. Only an
   operator's `request_arm` changes the mode, judged once by `control.decide_arm` and persisted. The egress
   lease is taken at start, so an older fence's in-flight attempts become OUTCOME_UNKNOWN.
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

   The orchestrator never issues an `AutomationGrant`.
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
    only while this process holds the lease. Nothing amends, and a cancel goes only to an order with no unknown
    outcome, so one operation is in flight per order (the package L requirement).
11. **FIXTURE cash basis.** Package G reports the cash basis as UNKNOWN (ACC-02), so nothing could ever pass. A
    FIXTURE caller may declare `fixture_cash_basis`, the basis its fixture venue implements. It is refused for
    every other environment and recorded in BOOT and every CYCLE record. The placeholder risk limits stay the
    default: tests pass explicit TEST limits as typed inputs.

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
- **In-memory dedupe sets** (signal ids, recorded verdicts) grow with the process lifetime, not per cycle.

## Reconsider when

- Package J adds stream and feed recovery: signals and market state then come from it.
- Package L defines kill latches beyond control's, or amend support: crossing cancel and amend answers then need
  their recovery rule here.
- Package O moves execution to its own process and service user: `send` becomes the real transport there, and
  the scheduler (a reviewed, owner-approved unit) calls `run`.
- ACC-02 is settled by a venue observation: `account.CASH_BASIS` changes, and `fixture_cash_basis` is no longer
  needed even in tests.
