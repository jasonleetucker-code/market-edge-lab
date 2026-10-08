# ADR 0047: The account-aware shadow (one chain, a read-only identity, FIXTURE only)

**Status:** Proposed 2026-10-08 (#160, campaign package M). Authority: the 2026-10-07 campaign grant in
`docs/EXECUTION_PLAN.md` (offline, FIXTURE only). Boundary: ADR 0043. Risk gate: ADR 0044. Orchestrator: ADR 0046.
Real account-aware verification is package S and stays BLOCKED_EXTERNAL (activation packet decision 2): everything
here is verified on FIXTURE account reads only.

## Problem

Package M must run the exact deterministic chain against the account and produce, for each proposal, WOULD_SUBMIT or
BLOCKED with the full intent and a hypothetical reservation, with no writes to the venue. Acceptance:
- no network mutation is possible under a read-only process identity, structurally;
- every relevant constraint and every external or manual order is included;
- the results repeat exactly from the input versions.

The hypothetical state must not reduce real available cash or interfere with manual trading, and its records must
never be mistaken for real intents, attempts or reservations. Nothing may use outcomes or future fills to choose
entries.

The orchestrator already had a SHADOW mode (package K). It ran the gate and recorded WOULD_SUBMIT, but:
- it stopped before the pre-egress steps and before the checks `prepare_attempt` makes, so a WOULD_SUBMIT could be
  refused by the real reservation;
- it recorded no intent and no reservation;
- its process held a write-capable `send`, and it took the egress lease of whatever store it was given.

## Decision

1. **One chain: M is the orchestrator's SHADOW mode, not a second module that re-derives decisions.** `_decide` is
   shared by every mode up to egress. After the gate, SHADOW runs:
   - `_egress_request`: the egress lease, the cycle's request budget and the exact create request. A real send runs
     the same function; it was extracted from `_prepare_and_send` unchanged.
   - What `prepare_attempt` checks, read-only:
     - no earlier attempt of the intent may still be live (`NO_ORDER_STATES`);
     - the reservation must fit. This uses `ReservationAuthority.decide`, the capacity rule extracted from
       `_evaluate`, so `_reserve` and the shadow call the same function.
   - The approval is not consumed, because there is none: SHADOW judges with `gate.evaluate`, as before.

   What SHADOW does not share is what follows an allowed decision in a sending mode: the approval (human or
   policy) and the grant checks, the `INTENT_PLANNED` record, `prepare_attempt`, `send` and the reply handling.
2. **The hypothetical reservation is built by the reservation authority's own code.**
   `ReservationAuthority.new_reservation` builds it, and `_reserve` now inserts from the same function. It has:
   - id `shadow:<client_order_id>#<attempt_no>`;
   - fence token 0, which the store's `CHECK (fence_token >= 1)` can never hold.

   It lives only in the cycle that made it. That cycle's later decisions see it the way they would see a real
   reservation:
   - in the account view the gate projects;
   - in the capacity rule;
   - in the order history, for rate and daily-new-risk limits;
   - in the intents map, for strategy attribution.

   A would-be send also counts against the cycle's request budget (`shadow_sends`). Nothing writes the reservation
   to the reservation tables. So it never reduces real available cash, never counts against real capacity, and
   never survives into the next cycle.
3. **A verdict record of its own.** Every SHADOW-mode decision writes a `SHADOW_VERDICT` control record next to the
   `DECISION` row (`shadow.ShadowVerdict`). It holds:
   - the full intent and its digest;
   - the outcome and every reason;
   - the hypothetical reservation (exactly for WOULD_SUBMIT);
   - the capacity rule's figures, or `null` when the rule was not asked (never "no obligations");
   - the digest of the exact create request;
   - the version of every input: the gate's own list, the snapshot revision and time, the control state basis, the
     ticket limits, the strategy hashes and the verdict schema.

   No loader reads `SHADOW_VERDICT` as a planned intent: `_load_records` reads only `INTENT_PLANNED`. Verdicts are
   deduplicated with the `DECISION` row they accompany. The cycle report carries them all (`shadow_verdicts`).
4. **The read-only process identity** (`OrchestratorConfig.identity = ProcessIdentity.READ_ONLY`):
   - The caller's `send` is wrapped in `shadow.ReadOnlySender`. It re-validates each request against the
     allowlist. A write, a non-GET or a non-`WireRequest` raises `ShadowWriteRefused` before the caller's callable
     is reached.
   - `request_arm` to anything but OBSERVE_ONLY or SHADOW is persisted as `ArmRefused`
     (`READ_ONLY_IDENTITY`). `decide_arm` is not consulted.
   - The process holds no automation grant (config refusal), and `shutdown(cancel_owned=True)` is refused.
   - `_prepare_and_send` and `_cancel_owned` refuse too. Both are unreachable in this identity; they are kept as a
     second stop.
   - **A shadow store is its own store.** A READ_ONLY worker id starts with `shadow-`, and an executor's never does.
     Before taking the lease, the orchestrator reads the store's lease holder and this scope's `BOOT` records (which
     now carry `identity`). A read-only process refuses an executor's store, and an executor refuses a shadow
     store. So a shadow never takes, or even contends for, a live executor's egress lease, and never turns a live
     executor's in-flight attempts into OUTCOME_UNKNOWN.

   The live executor's and the person's orders appear to the shadow as external orders. They are counted at their
   worst case under the configured `ExternalCashPolicy`, and the default `UNKNOWN_BLOCKS` refuses all new risk
   while any are open.
5. **Structural guarantee** (amends ADR 0043 §3; enforced by `tests/invariants/test_execution_boundary.py`):
   - The shadow path (`shadow.py`, `orchestrator.py`) and every package module it imports, transitively, reach no
     capability module and no capability user. A proxy module in between is caught, and so is a capability user
     added later (package O's executor), because the reach is computed from `CAPABILITY_USERS`.
   - The shadow path binds no package object and names no capability.
   - `shadow.py` names no write builder, order endpoint or journal write.
   - The read-only sender's inner callable (`_inner_send`) is private safety state named only by `shadow.py`.
6. **Point in time.** The strategy's context holds the snapshot, the market states at `now` and its signals. Its
   field set is pinned by a test, and it holds no settlement, outcome or P&L. Evidence or sources stamped after `now`
   fail the gate (DECISION_STALE, SOURCE_STALE: "stale or future"). A recorded verdict is append-only: a later fill
   or settlement never changes it.

## Alternatives rejected

- **A separate pure `shadow` module that re-implements the decision.** This means two chains that can drift. The
  gate and the capacity rule would be called from two places, with two sets of inputs.
- **Shadow reservations in the reservation tables, with a flag.** Every capacity query would have to remember the
  flag; one that forgot would spend real cash on hypothetical orders. Fence token 0 already cannot be stored.
- **Keeping hypothetical reservations across cycles.** A would-be order's later life (rests, fills, expires) is
  exactly the future the shadow must not see. Carrying it forward would either invent fills or hold capacity
  forever.
- **The shadow on the executor's own store.** Its lease takeover would turn the live executor's in-flight attempts
  into OUTCOME_UNKNOWN and fence the live worker out: real interference with trading.
- **Making the read-only guarantee a convention** (SHADOW "just doesn't call send"). This was the package K state.
  A read-only process now holds no write-capable reference at all.

## Tradeoffs and limitations

- **The shadow judges without approval.** HUMAN_CONFIRMATION's approval and BOUNDED_AUTO's grant limits and usage
  are mode authorizations, not account constraints, and are not part of a shadow verdict. Every gate check,
  control latch, incident, reconciliation, stream and capacity check is.
- **Re-proposals repeat.** A key that got WOULD_SUBMIT is not planned, so the same intent proposed again next cycle
  is judged again. The real chain would refuse a second attempt. The verdict is recorded once per (key, outcome,
  reasons).
- **The store identity check is reads before the lease, not one transaction with it.** A takeover in between is
  possible in principle. The hard separation (a distinct service user, file and credentials) is package O, and the
  real read-only credential is package S.
- **The worker-id prefix is a convention the config enforces**, not a property of the SQLite file. It is cheap and
  visible in every `BOOT` record and in the lease row.
- **`BOOT` records gain an `identity` field.** Demonstration B's pinned hash (`d331d6eb…`) does not include record
  bodies and is unchanged.

## Reconsider when

- Package S gets production-read approval. Real account reads run under a read-only credential, and the `shadow-`
  store becomes a distinct file and service user (package O).
- Package N shows shadow verdicts to the owner. The `SHADOW_VERDICT` record is the source, and the status export
  should show it as hypothetical, never as an order.
- The journal gains fenced appends or a store-kind marker: the identity check can then become transactional.
