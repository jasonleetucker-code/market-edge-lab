# 0020 — One provider-neutral notification contract; SMS preferred, not configured

Status: Accepted (2026-09-23, integration directive; issue #33)

**Problem.** The owner prefers text messages for urgent alerts. Many subsystems will alert:
- collector failures;
- invalid captures;
- qualified opportunities;
- risk vetoes;
- settlements;
- starter-policy exceptions;
- future approval tickets.

Building SMS into each one would duplicate logic. Carrier SMS also needs a paid provider,
and none is authorized. Most importantly, a failed notification must never change trading
or risk truth.

**Alternatives.**
- (a) Extend `deploy/vps/alert.sh` for every alert. It is shell-only and has no structure.
- (b) Pick a provider now. That is not authorized, and it would lock the design to a vendor.
- (c) One `NotificationEvent` contract, a pure `dispatch` with dedupe, expiry, rate limits
  and bounded retries, and pluggable sinks.

**Decision.** (c).
- **Event fields:** id, type (the 13 directive types), severity, created and expiry times,
  venue/market/event refs, a one-line summary, structured values, action mode, a deep link
  (https to allowlisted hosts, or the local dashboard) and a dedupe key.
- **Rules.**
  - Secrets are refused, not sent. The shared `redaction.py` also redacts URLs and errors
    for the adapters.
  - Expired events are never delivered.
  - INFO and WARNING are rate-limited per window. CRITICAL is never rate-limited.
  - Each sink gets at most three attempts, and a status is recorded per attempt.
- **Sinks today:**
  - a JSONL outbox in the status directory, size-capped with a single rotation;
  - `DisabledSmsSink`, which records DISABLED_NO_PROVIDER.

  The existing shell webhook stays. There is no Python network sink, and the no-execution
  invariant forbids POST in `src/`.
- **Daily receipt.** `daily._finish` turns the receipt into events. It runs inside a
  try/except and records only `receipt["notifications"]`. State, exit code and ledger are
  already decided, and a test proves a broken sink changes none of them.

**Tradeoffs.** A local outbox is not a push to a phone. Until the owner approves an SMS
provider, urgent delivery still relies on the journal, the status file and the optional
webhook in `alert.sh`.

**Reconsider when:** the owner approves a provider (Twilio, Telnyx, SNS or similar, with cost,
registration and delivery receipts compared). Add it as a sink behind the same contract.
Network delivery then needs a reviewed exception to the POST invariant, or a shell/systemd
sender.

## Amendment 2026-09-24: event origin

Authority: owner directive of 2026-09-24, Deliverable 5
(`docs/owner/2026-09-24-next-build-chunk-directive.md`).

**Problem.** An event did not say why it existed. Runbook §4.1 deliberately makes the decision
unit fail, to prove the collector fails closed. That failure then reached the owner's phone as
"A run or data source failed", the same push a real incident gets.

**Decision.**
- **Field.** `NotificationEvent.origin` is an `Origin` enum with six values: PRODUCTION, TEST,
  DEPLOYMENT_VERIFICATION, MANUAL_DIAGNOSTIC, REPLAY and DEMO.
  - It is serialized in the outbox as `"origin": "<VALUE>"`, and the schema stays
    `edge-lab-notification/1` because the field is additive.
  - A line without the field reads as PRODUCTION. An unknown value makes `event_from_dict`
    return None, never a guess.
  - **Garbled origins.** A garbled outbox line is dropped, neither guessed nor relayed. A
    garbled unit-failure record is PRODUCTION and pushed. So is a failure record that claims
    DEPLOYMENT_VERIFICATION without root's confirmation. A bad field can make an extra alert,
    never a missing one.
  - The event id leaves the origin out, so the ids of events already relayed do not change.
- **Who sets it.** Whoever creates the event. `daily._notify` passes PRODUCTION explicitly,
  `send_test` passes TEST. A unit failure takes the origin that `alert.sh` recorded, and the
  relay accepts DEPLOYMENT_VERIFICATION only with root's confirmation (ADR 0028 amendment). It is never inferred from the clock, from a deployment being in progress, or
  from free text.
- **Delivery policy, enforced in `dispatch`.** A sink declares `external = False` only if it
  keeps events on this host (the outbox). A sink that declares nothing counts as external.
  An external sink gets:
  - PRODUCTION by default;
  - TEST and MANUAL_DIAGNOSTIC only when the caller names them in `push_origins`, which only
    `send_test` does, and only for TEST;
  - DEPLOYMENT_VERIFICATION, REPLAY and DEMO never. Naming them is a ValueError.

  A held event is recorded as HELD_BY_ORIGIN for that sink and still written to the local
  sinks. As a second layer, the ntfy sink itself refuses the never-pushed origins.
- **No interference.** Dedupe and rate limits count only the history of the same origin. An
  event held on every sink uses no budget. A burst of test, demo or verification events can
  therefore never dedupe or rate-limit a production alert.
- **Pushed non-PRODUCTION events are labelled.** An explicitly requested TEST or
  MANUAL_DIAGNOSTIC push names its origin in the ntfy title, and the body opens with a fixed
  line such as "Manual diagnostic, not a production incident."

**Tradeoffs.**
- A caller that builds an event without passing `origin` gets PRODUCTION, which keeps old
  callers working. New replay, demo or diagnostic producers must set their origin. The
  dashboard demo (`dashboard/demo.py`) writes to a demo status directory that the relay never
  reads, so it cannot push. It should still pass `origin=Origin.DEMO` when its owner next
  touches it.
- **Rollback.** Code from before this amendment ignores `origin`, so it would push any
  non-PRODUCTION outbox line (the fail-loud direction). It never reads
  `last_verification.json`.

**Reconsider when:** a new producer needs a pushed origin other than PRODUCTION or TEST. Add it
to `REQUESTABLE_PUSH_ORIGINS` in a reviewed change, never as configuration.
