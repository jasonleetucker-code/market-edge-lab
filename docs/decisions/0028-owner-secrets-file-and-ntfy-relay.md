# ADR 0028: Owner secrets file and the ntfy relay unit

**Status:** Accepted 2026-09-24. Owner authority: `docs/EXECUTION_PLAN.md` (2026-09-24 entry) and
`docs/owner/2026-09-24-brisket-health-and-next-phase-directive.md` (Phase 7, and Phase 6 for the
key).

## Problem

The owner approved two things:
- the first real ntfy push, with a private high-entropy topic kept only in server secret
  configuration;
- the owner installing The Odds API free read-only key.

There was no place to put either value.
- `/etc/market-edge-lab/env` is rewritten on every install and says it is "not a secret store".
  A value placed there would be wiped by the next deploy.
- The only units that produce notifications are `edgelab-shadow` and `edgelab-settlement`
  (through `daily._notify`, which writes the local outbox). `edgelab-shadow` has no network by
  design (`IPAddressDeny=any`, `RestrictAddressFamilies=AF_UNIX`), and a test pins that.

## Alternatives

1. **Put the values in `env` and teach install.sh to carry them over.** Rejected. install.sh
   would then read secrets, and every install would copy them again.
2. **Send from inside `daily._notify`.** The shadow unit would need network, which weakens a
   deliberate boundary. It would also put an external call inside the run whose receipt is
   the evidence of record.
3. **A separate root-owned secrets file, plus a relay unit that forwards the outbox.**
   Chosen.

## Decision

- **Secrets file.**
  - `/etc/market-edge-lab/secrets.env` (root:root 0600) holds owner-installed values:
    `EDGE_LAB_NTFY_TOPIC_URL` (and optionally `EDGE_LAB_NTFY_TOKEN`) and
    `EDGE_LAB_ODDS_API_KEY`.
  - install.sh creates it empty once, then only enforces its owner and mode. It never reads,
    copies, rewrites or prints its contents (test: `test_install_creates_the_secrets_file_once_and_never_reads_it`).
  - Neither `edgelab` nor `dynasty` can read it (install checks). systemd reads
    `EnvironmentFile=` as root before dropping privileges, so the units still receive the values,
    and the dashboard and every other `edgelab` process cannot open the file. A same-user process
    could still read a running relay's `/proc/<pid>/environ`, but only for the seconds the relay
    runs.
  - The ntfy topic is written by the tested `deploy/vps/set_ntfy_topic.py`, run as root. It
    keeps an existing topic unless `--force` is given, writes atomically and prints nothing
    secret.
- **Which units load it.** Only units that need a secret load it, and each loads it optionally
  (`EnvironmentFile=-…`). Today that is `edgelab-notify` and, later, `edgelab-odds` (pinned by
  test). The shadow, settlement and capture units do not load it.
- **Relay unit.** `edgelab-notify.service` has no timer. It starts in two ways:
  - `edgelab-shadow` and `edgelab-settlement` start it on success (`OnSuccess=`).
  - `edgelab-alert@` starts it after recording a failure. A failure of any unit, including runs
    killed before they wrote the outbox, is relayed from `last_failure.json` as the fixed
    headline "A run or data source failed"; the unit name goes only into the dedupe key.
  - Its write access is only the status directory. The database and ledger are inaccessible
    to it.
  - It runs `edge-lab notify relay`, which reads the local outbox and forwards events from the
    last 36 h once each through the normal `dispatch` rules. Those rules cover refusal of
    secrets, expiry, dedupe (the relay keeps its own history of SUBMITTED events), rate limits
    and CRITICAL-first.
  - Delivery goes through the unchanged ADR 0022 sink: fixed headline only, 3 attempts within
    15 s, a circuit breaker, and SUBMITTED, never DELIVERED.
  - The relay exits 0 whatever the provider answers, and it has no `OnFailure`. A notification
    failure can therefore never change a receipt, a ledger or a risk decision, and it cannot
    start an alert loop.
- **Test send.** `edge-lab notify test` sends one fixed TEST event (new `EventType.TEST`,
  headline "Test notification, no action needed").
- **Sink construction.** Only `cli.py` constructs the sink, and only through `sink_from_env`.
  The invariant test now allows exactly that file and still forbids `daily.py`, units and
  scripts.

## Tradeoffs

- **History and rate limits.** Each SUBMITTED event is written to the relay history immediately,
  so a killed relay does not re-send. Dedupe is by `dedupe_key` and by `event_id`. The hourly
  rate limit counts events by creation time, so a backlog retried later is capped per relay run
  (20 INFO + 10 WARNING) rather than per clock hour. CRITICAL events are never capped.
- **Alert URL.** `EDGE_LAB_ALERT_URL` must not point at the ntfy topic: `alert.sh` sends free
  text.
- **Delay.** Pushes arrive after the daily run finishes, not during it. At most the relay's own
  runtime is added.
- **Retries.** A FAILED or RATE_LIMITED event is retried on the next relay, meaning the next
  daily run, not immediately. Events older than 36 h are never pushed, so a relay outage
  never floods the phone later. The outbox and dashboard still hold everything.
- **History file.** The relay history (`ntfy_relay.jsonl`) sits beside the outbox in the
  non-sensitive status directory. It holds the same event records the outbox already
  exposes.
- **Topic handling.** The topic is a password on a public server. It exists only in the
  secrets file and the owner's phone.

## Reconsider when

- a paid or SMS provider is approved (a second sink behind the same relay);
- notifications must arrive during a run (then consider a networked sidecar, never network
  for the shadow unit);
- a self-hosted ntfy server is approved (ADR 0022's list);
- secrets move to a real secret manager.

## Amendment 2026-09-24: the fail-closed check is DEPLOYMENT_VERIFICATION, bound to its invocation

Authority: owner directive of 2026-09-24, Deliverable 5
(`docs/owner/2026-09-24-next-build-chunk-directive.md`). See also the ADR 0020 amendment
(event origin).

### Problem

Every install runs runbook §4.1: start `edgelab-decision.service` outside its window and expect
`rejected_out_of_window`. The unit then fails on purpose, and the chain below pushed that
failure to the owner's phone as "A run or data source failed", exactly like a real incident:

`OnFailure=edgelab-alert@` → `alert.sh` writes `last_failure.json` → `OnSuccess=edgelab-notify`
→ push.

The fix must not weaken real alerts. A genuine failure of any unit must still push, including
the decision unit and including a failure during a deployment. The origin must also never be
guessed from the clock or from "a deployment is happening".

### Alternatives

1. **Suppress alerts during a deployment window, or by time of day.** Rejected. That is the
   clock inference the directive forbids, and it would hide a real failure in that window.
2. **An environment variable or runtime drop-in on the unit.** Rejected. `systemctl start` cannot
   scope an environment to one invocation. A drop-in marks every invocation until it is removed,
   so an aborted check would leave production failures mislabelled.
3. **A separate "verify" copy of the unit, or a transient `systemd-run` unit.** Rejected. It
   would not exercise the installed unit file, and the copy could drift from it.
4. **Classify by the failure text alone (`rejected_out_of_window`).** Rejected. A production
   timer that fires late is rejected with the same status, and that is a real incident.
5. **Trust an `origin` field in the status directory.** Rejected alone. Every `edgelab` process
   can write that directory.
6. **A root-issued confirmation bound to the exact systemd InvocationID, checked by `alert.sh`
   and again by the relay.** Chosen.

### Decision

- **`deploy/vps/verify_fail_closed.sh` runs the check, as root.**
  - **Refusals.** It refuses unless all of these hold:
    - it runs as root;
    - no other check holds its `flock`;
    - `edgelab-decision.service` is idle (`inactive` or `failed`), so the check can only start a
      new invocation and never join a scheduled one;
    - `edgelab-decision.timer` is not due within 5 minutes (`NextElapseUSecRealtime`).

    This clock read only refuses to *start* a check. It never classifies a failure.
  - **Arming.** It writes `armed-edgelab-decision.service` in `/var/lib/market-edge-lab-verify`
    (root-owned, 0755). A trap removes the file on exit.
  - **Running the real unit.** It starts the real, installed unit and reads the invocation's
    `InvocationID`, `Result` and `ExecMainStatus`, and that invocation's own journal lines
    (`_SYSTEMD_INVOCATION_ID=`, which only root can read).
  - **Confirmation.** It writes `confirmed-<InvocationID>` only if all of these hold:
    - the ID is new;
    - the timer's `LastTriggerUSec` did not change during the check;
    - `Result=exit-code` and `ExecMainStatus=1`;
    - the collector printed `"phase": "decision"` and `"status": "rejected_out_of_window"`.

    The file is root-owned, 0644, and its content is exactly
    `{"unit": "edgelab-decision.service", "invocation_id": "<id>", "status": "rejected_out_of_window"}`.
  - **Finish.** It waits until `last_verification.json` names the invocation, then runs
    `reset-failed` on that one unit (never `edgelab-*`). It exits 1 with a reason for anything
    else, including a clear message when the unit succeeded with `skipped_duplicate` or
    `complete` (the check ran inside the capture window).
  - **Tidying.** Confirmations are kept, because the relay re-checks them on every run within
    its 36-hour window. Only confirmations older than 7 days are deleted, when the next check
    starts. The directory is persistent (not `/run`), so a reboot cannot turn a held
    verification into a push.
- **`alert.sh` (as `edgelab`) decides per invocation.**
  - It takes the failed invocation from `MONITOR_INVOCATION_ID`, which systemd 251+ passes to
    `OnFailure=` units (the VPS runs 255), falling back to `systemctl show`.
    **Requirement: systemd ≥ 251.** On an older systemd the `MONITOR_SERVICE_RESULT` and
    `MONITOR_EXIT_STATUS` values are absent. Every failure then fails closed to PRODUCTION: the
    check cannot be recorded as verification, and it pushes as before.
  - It records `origin: DEPLOYMENT_VERIFICATION` only if all of these hold:
    - that ID's confirmation exists and matches byte for byte;
    - the confirmation and its directory are owned by root, not symlinks, and not group- or
      world-writable;
    - `MONITOR_SERVICE_RESULT=exit-code` and `MONITOR_EXIT_STATUS=1`. A missing value fails
      closed to PRODUCTION.

    Everything else is `PRODUCTION`.
  - **Two record files.**
    - A PRODUCTION failure goes to `last_failure.json`, which stays production-only.
    - A verification goes to `last_verification.json`.

    A check therefore never overwrites a production failure that has not been relayed. Both use
    `{"unit", "failed_at_utc", "invocation_id" (null if unknown), "origin"}`, written through
    `mktemp` and an atomic rename.
  - **Waiting.** Only while this unit is armed, `alert.sh` waits up to 40 s (inside the alert
    unit's 60 s limit) for the confirmation. The armed file alone never changes an origin.
    - `alert.sh` treats an armed file older than 15 minutes (by mtime) as not armed, and the
      check removes leftover armed files at startup, under its lock.
    - A stale file (a killed check, a power loss) therefore can never add 40 s to later alerts.
      With the webhook's ~33 s, those 40 s could otherwise push `edgelab-alert@` past
      `TimeoutStartSec=60` and skip the relay.
    - This age test decides only whether to wait, never the origin.
  - **Webhook.** The optional `EDGE_LAB_ALERT_URL` webhook fires for PRODUCTION only.
- **The relay** reads both files (`last_verification.json` sits beside `last_failure.json`).
  - A record is DEPLOYMENT_VERIFICATION only if it says so **and** root's confirmation of its
    exact unit and invocation exists and passes the same ownership, mode, symlink and content
    checks (`edge_lab.verification.verification_confirmed`, a stdlib-only module with no sink,
    which the read-only dashboard also uses). Such a record is held (`HELD_BY_ORIGIN`).
  - Anything else is PRODUCTION and pushed: a missing, garbled or forged origin, and a claim
    without a confirmation.
  - Neither file is ever modified.
- **Why a real failure still alerts.**
  - A production failure of the same unit has a different InvocationID, so it has no
    confirmation, even while a check is armed. After at most 40 s it is recorded as PRODUCTION
    in `last_failure.json` and pushed.
  - A check whose unit fails another way, or that races a timer trigger, is never confirmed.
  - No `edgelab` process can write the root-owned directory, so no service can mark its own
    failure as verification in either `alert.sh` or the relay.
  - Tests: `tests/test_deploy_units.py` runs both scripts against stubbed `systemctl` and
    `journalctl`. `tests/test_notify_ntfy.py` covers the relay's re-check.

### Tradeoffs

- **Delay.** While a check is armed, a failure of the decision unit is recorded up to 40 s later.
  No other unit ever waits.
- **Script death.** If the check script dies before confirming (for example SIGKILL), the
  failure is pushed as PRODUCTION: a false alarm, never a missed one. An armed file left behind
  is ignored once it is 15 minutes old, and removed by the next check.
- **Single records.** `last_failure.json` and `last_verification.json` each hold only the
  latest record. The journal keeps every failure.
- **Old records.** Records written before this amendment have no origin and read as PRODUCTION.
- **Dashboard.** Its failure card reads `last_failure.json`. That file is now production-only,
  so the card no longer shows a verification as a failure. Showing `last_verification.json` is
  the dashboard owner's change.

### Reconsider when

- the fail-closed check must cover more units than the decision collector (extend the script's
  unit list and each unit's expected status in one reviewed place);
- systemd gains a supported way to pass per-invocation metadata to `OnFailure=` units;
- the failure records become a history rather than single latest records.
