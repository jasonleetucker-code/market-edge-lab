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
  - `/etc/market-edge-lab/secrets.env` (root:edgelab 0640) holds owner-installed values:
    `EDGE_LAB_NTFY_TOPIC_URL` (and optionally `EDGE_LAB_NTFY_TOKEN`) and
    `EDGE_LAB_ODDS_API_KEY`.
  - install.sh creates it empty once, then only enforces its owner and mode. It never reads,
    copies, rewrites or prints its contents (test: `test_install_creates_the_secrets_file_once_and_never_reads_it`).
  - The `dynasty` user cannot read it (install check).
- **Which units load it.** Only units that need a secret load it, and each loads it optionally
  (`EnvironmentFile=-…`). Today that is `edgelab-notify` and, later, `edgelab-odds` (pinned by
  test). The shadow, settlement and capture units do not load it.
- **Relay unit.** `edgelab-notify.service` has no timer. `edgelab-shadow` and
  `edgelab-settlement` start it through `OnSuccess=` and `OnFailure=`, so a failed run, which is
  often the thing worth pushing, is relayed too.
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
