# 0022 — Optional ntfy push sink behind the notification contract; one-file POST exception

Status: Accepted as code only (2026-09-23; owner directive for a disabled-by-default ntfy
sink). **Not activated.** A first real send, installing a topic URL or token, and wiring the
sink into any run path, timer or deploy file each need a separate owner approval recorded
in the repo.

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
  payload must be minimal and the topic URL must be handled as a secret.

**Alternatives.**
- (a) **Apprise** as a dependency. It covers ntfy, SMS, email and chat. It adds six runtime
  dependencies, loads plugins dynamically, embeds credentials in service URLs, and its ntfy
  plugin (at the reviewed SHA) cannot set `X-Sequence-ID`, `X-Cache` or `X-Firebase`, so our
  dedupe mapping would be lost. Rejected now (audit §7.9: reconsider at three or more
  authorized channels).
- (b) **Shell sender** (`curl` from `deploy/vps/alert.sh` or a systemd unit). No Python
  exception is needed, but it duplicates the contract's minimisation, expiry, dedupe and
  redaction in shell, where they cannot be unit-tested the same way.
- (c) **Relax the invariant** for `src/` or for a notifications package. Rejected: it would
  let any future module POST.
- (d) **One stdlib sink in its own file, with a path-exact, rule-exact exception.** Chosen.

**Decision.** (d).
- **Module.** `src/edge_lab/notify_ntfy.py`, stdlib `urllib` only, no new dependency. It
  implements the existing `Sink` protocol (`deliver(event) -> DeliveryStatus`).
- **Disabled by default.** `sink_from_env` returns None unless `EDGE_LAB_NTFY_TOPIC_URL` is
  set. `EDGE_LAB_NTFY_TOKEN` is optional and travels only as `Authorization: Bearer`.
  Nothing in `src/`, `deploy/` or `scripts/` imports or constructs the sink, and a test
  enforces that.
- **Target.** Only `https://<host>/<topic>` (plain http only for a loopback test server).
  The topic matches ntfy's `[-_A-Za-z0-9]{1,64}`. No userinfo, query, fragment or extra path.
  The host is refused if it contains the name of any registered data source or venue, a list
  derived at run time from `sources.REGISTRY` and `notifications.LINK_HOSTS`, so the file
  itself names no venue. Redirects are not followed, because one could carry the token to
  another host.
- **Payload (the contract has no sensitivity field).** Only the event type, the severity and
  the one-line summary are sent, and the summary is truncated to 240 characters:
  - `X-Title`: `Market Edge <SEVERITY>: <TYPE>`;
  - `X-Priority`: INFO 2, WARNING 4, CRITICAL 5;
  - `X-Tags`: `<severity>,<type>`;
  - body: the summary.

  Values, venue, market and event refs, the deep link and the action mode are never sent.
  There is no `X-Click` or `X-Actions`. Secrets are refused by `check_event` and checked
  again on the final headers and body.
- **Dedupe.** `dispatch` and the outbox history still dedupe by `dedupe_key`. The key is also
  sent as `X-Sequence-ID`: invalid characters become `_`, and a key over 64 characters keeps
  a 47-character prefix plus 16 hex characters of its SHA-256. A repeat then replaces the
  notification on the phone, because the server itself does not dedupe.
- **Expiry.** An event already expired at send time is not sent (EXPIRED). The sink checks
  again with its own clock before each retry.
- **Retry.** At most 3 attempts (a constructor cannot raise the bound), with backoff
  1 s then 2 s through an injectable `sleep`. Only transport errors and 500/502/503/504 are
  retried, and only when a sequence id exists, so a duplicate collapses instead of adding a
  message. 429 is never retried and returns RATE_LIMITED. Any other status, a redirect or a
  bad token returns FAILED.
- **Status.** A 2xx means the server accepted the message, not that a phone showed it. A new
  `DeliveryStatus.SUBMITTED` records that. The sink never returns DELIVERED, which stays the
  local outbox's "written and flushed".
- **Never raises.** Every failure becomes a status with a redacted `last_error`. Additive
  change to `dispatch`: when a sink exposes `last_error` and `last_attempts`, the per-sink
  record uses them, so the redacted reason and the sink's own attempt count are recorded.
  The sink holds no reference to risk, ledger or trading state.
- **Secrets.** The topic URL, topic and token are removed from every error by
  `redaction.redact_text`. `Target.label` and `repr` show only the scheme and host. Config
  errors never echo the URL or token.
- **Invariant change** (`tests/invariants/test_no_execution_paths.py`):
  - `NOTIFICATION_DELIVERY_EXCEPTION` names exactly `edge_lab/notify_ntfy.py` and exempts it
    from exactly three rules: non-GET method, request body, auth header;
  - the order-endpoint, client-write-call and request-signing rules have no exception
    anywhere, that file included;
  - tests prove that:
    - the exception is bound to the exact path (a copy or rename fails);
    - every other `src/` file still fails on POST, body or auth header;
    - order patterns still fail inside the exempt file;
    - the file contains no venue name, trading path or URL literal, and imports nothing
      beyond stdlib and four `edge_lab` modules;
    - it refuses every registered source host and known venue hosts;
    - the token variable is read only there, through an injectable mapping;
    - the exception is in use, so it cannot outlive the sink.

**Tradeoffs.**
- Push is not SMS and has no receipt. SUBMITTED is the most we can claim.
- Content goes to ntfy.sh in plaintext, is cached there and passes through Google/Apple.
  That is why only type, severity and summary are sent. Summaries are free text written by
  callers. Today's receipt summaries can name a shadow account label (for example
  "... (research)") or a market id. They carry no position, PnL, balance or venue account
  id, but a future caller could. Callers own their summaries, and `check_event` refuses only
  secret-looking text.
- The sequence id keeps a readable (sanitised) dedupe key when it fits in 64 characters, so
  keys such as `veto_research_2026-09-25` are visible to the server. Hashing every key would
  hide that at the cost of readability.
- Two different keys that sanitise to the same id (for example `a:b` and `a/b`) collapse on
  the phone. The outbox dedupe still uses the raw key.
- The refused-host check is a substring test on registry-derived names. It fails closed, and
  may refuse an innocent host whose name contains one of them.
- The token is a credential. The code can read it, but no one may install it without the
  approval that `AI_INSTRUCTIONS.md` requires for handling credentials.

**Reconsider when:**
- the owner approves activation (then record the approval and wiring in the same PR);
- the contract gains a sensitivity field (then send PRIVATE events only as a generic
  "check the dashboard" headline, or not at all);
- three or more channels are authorized (then compare Apprise as an optional extra);
- a self-hosted ntfy server is approved (then consider `X-Cache: no` and `X-Firebase: no`);
- or ntfy's publish API changes.
