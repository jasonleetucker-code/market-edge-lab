# 0022 — Optional ntfy push sink behind the notification contract; one-file POST exception

Status: Accepted as code only (2026-09-23; owner directive for a disabled-by-default ntfy
sink; revised the same day after an independent security review). **Not activated.** A
first real send, installing a topic URL or token, and wiring the sink into any run path,
timer or deploy file each need a separate owner approval recorded in the repo.

**Problem.**
- ADR 0020 gives every alert one `NotificationEvent` contract, but the only sinks are a
  local outbox and a disabled SMS sink. Nothing reaches the owner's phone.
- The reuse audit (`docs/GITHUB_REUSE_AUDIT.md` §7.9, report E §6) found ntfy to be the best
  free push channel now. It is not carrier SMS: it needs the ntfy app installed and online,
  it goes through FCM/APNs or a websocket, and it gives no delivery receipt.
- Publishing to ntfy is an HTTP POST with a body. The no-execution invariant
  (`tests/invariants/test_no_execution_paths.py`) forbids POST, request bodies and auth
  headers anywhere in `src/`. Any sink therefore needs a deliberate, narrow exception.
- ntfy.sh topics are public: without an account the topic name is effectively a password.
  ntfy.sh stores message content (about 12 h) and forwards it to Google or Apple. So the
  payload must reveal nothing, and the topic URL must be handled as a secret.

**Alternatives.**
- (a) **Apprise** as a dependency. It covers ntfy, SMS, email and chat, but:
  - it adds six runtime dependencies;
  - it loads plugins dynamically;
  - it embeds credentials in service URLs;
  - its ntfy plugin (at the reviewed SHA) cannot set `X-Sequence-ID`, `X-Cache` or
    `X-Firebase`, so our dedupe mapping would be lost.

  Rejected now. Audit §7.9 says to reconsider at three or more authorized channels.
- (b) **Shell sender** (`curl` from `deploy/vps/alert.sh` or a systemd unit). No Python
  exception is needed, but minimisation, expiry, dedupe and redaction would be duplicated in
  shell, where they cannot be unit-tested the same way.
- (c) **Relax the invariant** for `src/` or for a notifications package. Rejected: it would
  let any future module POST.
- (d) **One stdlib sink in its own file, with a path-exact, rule-exact exception.** Chosen.

**Decision.** (d).
- **Module.** `src/edge_lab/notify_ntfy.py`, stdlib `urllib` only, no new dependency. It
  implements the existing `Sink` protocol (`deliver(event) -> DeliveryStatus`).
- **Disabled by default.** `sink_from_env` returns None unless `EDGE_LAB_NTFY_TOPIC_URL` is
  set. `EDGE_LAB_NTFY_TOKEN` is optional and travels only as `Authorization: Bearer`.
  Nothing in `src/`, `deploy/` or `scripts/` imports or constructs the sink; a test enforces
  that.
- **Host allowlist, not a denylist.**
  - The URL must be https to `<host>/<topic>`, where the host is exactly `ntfy.sh`
    (`DEFAULT_HOSTS`) or a name in `SELF_HOSTED_HOSTS`. That tuple is empty, lives in
    reviewed code and is pinned by an invariant test. Configuration can never add a host.
  - IP literals (v4 and v6), explicit ports, userinfo, queries, fragments, trailing dots,
    subdomains and extra path segments are refused.
  - The topic must match `[-_A-Za-z0-9]{16,64}`. ntfy allows 1 to 64 characters, but short
    topics are guessable.
- **The target cannot be redirected.**
  - Building a `Target` validates it.
  - The sink's `target` is a read-only property, and the class uses `__slots__`.
  - The URL is re-validated immediately before every request.
  - The opener is wrapped in a guard that refuses any request other than a POST to the
    exact URL validated at construction. That covers an injected opener too.
  - The real opener ignores environment proxies (`ProxyHandler({})`) and follows no
    redirects, because a redirect could carry the token to another host.
- **Payload: nothing identifying.** The contract has no sensitivity field, and
  `events_from_receipt` summaries contain market ids, account labels, fill ids and dates. So
  the summary is never sent. Only these go out:
  - `X-Title`: `Market Edge <SEVERITY>: <TYPE>`;
  - `X-Priority`: INFO 2, WARNING 4, CRITICAL 5;
  - `X-Tags`: `<severity>,<type>`;
  - body: a fixed headline per event type (`HEADLINES`) plus "Open Market Edge for details.";
  - `X-Sequence-ID`: the full SHA-256 hex (64 characters) of the dedupe key.

  Values, refs, the deep link and the action mode are never sent. There is no `X-Click` or
  `X-Actions`. A test runs realistic receipt events through the sink and checks that no
  market id, account label, fill id, date, summary or dedupe-key text appears in any header
  or body.
- **Dedupe.** `dispatch` and the outbox history still dedupe by the raw `dedupe_key`. The
  hashed sequence id makes a repeat replace the phone notification, since the server itself
  does not dedupe.
- **Expiry fails closed.** An event already expired at send time is not sent (EXPIRED), and
  neither is an event whose `expires_at_utc` does not parse. Expiry is checked again before
  each retry.
- **Bounded cost.**
  - At most 3 attempts inside a 15-second budget per event, with backoff and per-attempt
    timeouts included. Neither bound can be raised by a constructor argument.
  - Backoff is 1 s then 2 s, through an injectable `sleep` and monotonic clock.
  - Only transport errors and 500/502/503/504 are retried, and only when a sequence id
    exists.
  - 429 is never retried and returns RATE_LIMITED.
  - Certificate errors, redirects, other 4xx and a missing or non-integer status are FAILED
    without a retry.
  - After 3 consecutive FAILED events, a per-instance circuit breaker returns FAILED without
    sending for 300 s. A success resets it.
- **Status.** A 2xx means the server accepted the message, not that a phone showed it. A new
  `DeliveryStatus.SUBMITTED` records that. The sink never returns DELIVERED, which stays the
  local outbox's "written and flushed".
- **Never raises.** Every failure becomes a status with a redacted `last_error`.
  - Additive change to `dispatch`: when a sink exposes `last_error` and `last_attempts`, the
    per-sink record uses them. The record then shows the redacted reason, the sink's own
    attempt count, and 0 when the sink refused before sending.
  - The sink holds no reference to risk, ledger or trading state.
- **Secrets.** The topic URL, topic and token are removed from every error by
  `redaction.redact_text`. `Target`'s repr omits the URL. The sink's repr and str show only
  the host and whether a token is set. `__slots__` leaves no `__dict__` to dump. Config
  errors never echo the URL or token.
- **Invariant change** (`tests/invariants/test_no_execution_paths.py`):
  - `NOTIFICATION_DELIVERY_EXCEPTION` names exactly `edge_lab/notify_ntfy.py` and exempts it
    from exactly three rules: non-GET method, request body, auth header.
  - The order-endpoint, client-write-call and request-signing rules have no exception
    anywhere, that file included.
  - Tests prove that:
    - the exception is bound to the exact path, so a copy or rename fails;
    - every other `src/` file still fails on POST, body or auth header;
    - order patterns still fail inside the exempt file;
    - the file contains no venue name, trading path or URL literal, and imports only
      stdlib and three `edge_lab` modules;
    - the host allowlist is exactly `("ntfy.sh",)` plus an empty self-hosted tuple;
    - venue, data-source, IP-literal and userinfo/port-trick URLs are refused, including
      when a `Target` is built directly;
    - the token variable is read only in that file, through an injectable mapping;
    - the exception is in use, so it cannot outlive the sink.

**Tradeoffs.**
- Push is not SMS and has no receipt. SUBMITTED is the most we can claim.
- The fixed headlines say only what kind of thing happened. The owner must open Market Edge
  to learn which market or account is involved. That is deliberate, because content goes to
  ntfy.sh in plaintext, is cached there and passes through Google/Apple.
- The hashed sequence id cannot be read on the phone, so two alerts of the same type
  look alike until the dashboard is opened.
- Only ntfy.sh is reachable until a reviewed change adds a self-hosted host.
- The circuit breaker can hide a recovery for up to 300 s. The outbox still records every
  event.
- The token is a credential. The code can read it, but no one may install it without the
  approval that `AI_INSTRUCTIONS.md` requires for handling credentials.

**Reconsider when:**
- the owner approves activation (then record the approval and the wiring in the same PR);
- the contract gains a sensitivity field or a vetted public headline field (then decide
  whether anything beyond the fixed headline may be sent);
- three or more channels are authorized (then compare Apprise as an optional extra);
- a self-hosted ntfy server is approved (then add it to `SELF_HOSTED_HOSTS` and the invariant,
  and consider `X-Cache: no` and `X-Firebase: no`);
- or ntfy's publish API changes.
