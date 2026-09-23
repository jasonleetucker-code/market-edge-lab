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
