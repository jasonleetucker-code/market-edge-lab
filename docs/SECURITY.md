# Security and Credentials

**Today:** the repository holds no credentials and has no order-capable code, no trading
client and no account client. `tests/invariants/` enforces this. There is one keyed
**read-only data-feed** client: `edge_lab.odds_api` can send The Odds API free-tier key as a
query parameter to read odds. That key is not installed (see below). It is not a trading
credential, and the registry cannot hold one.

## Rules

1. **No secrets in git.** This covers API keys, tokens, passwords, private keys, broker/exchange
   credentials, database URLs with passwords, and personal contact details used in User-Agents.
   Keep them in your local environment or `.env`, which is gitignored. Only `.env.example`,
   holding placeholders, is tracked.
2. **No credential is created, requested or used without owner approval** recorded in
   `docs/EXECUTION_PLAN.md`.
3. **Separate credentials by purpose** wherever the platform allows it:
   - research/read-only keys (for example, news or data APIs) are separate from trading keys;
   - trading keys are separate from withdrawal/transfer permission. Never enable withdrawal on
     an API key;
   - paper/demo environments get their own keys, never production keys.
4. **Research agents never receive execution credentials.** A future execution component
   runs with its own narrowly scoped credentials. Research code, notebooks and LLM contexts
   never load it or its keys.
5. **Least privilege and expiry.** Use the narrowest scopes, IP allowlists where offered,
   and rotation dates recorded with the credential (outside git).
6. **Secrets never enter prompts, logs, snapshots or error messages.** Redact before storing.
   Collectors must not persist request headers that carry credentials.

## Environment variable names (reserved for future use)

| Variable | Purpose | Status |
|---|---|---|
| `NWS_USER_AGENT` | NWS identification with contact info | in use (not secret, but personal) |
| `EDGE_LAB_ODDS_API_KEY` | The Odds API free-tier key (`CredentialKind.READ_ONLY_DATA_FEED`) | owner installs it in `/etc/market-edge-lab/secrets.env` (ADR 0028); not installed yet |
| `EDGE_LAB_NTFY_TOPIC_URL` | ntfy push topic URL (`https://ntfy.sh/<topic>`); the topic name is effectively a secret (ADR 0022) | owner-approved 2026-09-24; lives only in `/etc/market-edge-lab/secrets.env`, read only by `edgelab-notify` (ADR 0028) |
| `EDGE_LAB_NTFY_TOKEN` | optional ntfy access token, read only by `notify_ntfy.py` | not created |
| `EDGE_LAB_RESEARCH_<PROVIDER>_KEY` | read-only research data API keys | not created |
| `EDGE_LAB_TRADING_<VENUE>_KEY_ID` / `_PRIVATE_KEY_PATH` | execution credentials, execution component only | not created, not authorized |

Private keys are referenced by **file path** outside the repository. Their contents never
go in environment variables.

## The owner secrets file (ADR 0028)

`/etc/market-edge-lab/secrets.env` (root:edgelab 0640) is the only place on the server for
owner-installed values. It is **not** the regenerated `env` file.
- install.sh creates it empty once. After that it only enforces the owner and mode, and never
  reads, copies or prints the contents.
- Only the units that need a value load it, and each loads it optionally: `edgelab-notify`,
  and later `edgelab-odds`.
- Edit it as root with `sudoedit /etc/market-edge-lab/secrets.env`. Never paste its values into
  chat, git, tickets, logs or notifications.
- Read a value back only privately, as root, on the server.

## The Odds API key (read-only data feed)

Authority: directive 2026-09-23 section 10 and issue #29, recorded in
`docs/EXECUTION_PLAN.md`.

- **What it is.** A free-tier key that can only read odds. It is
  `CredentialKind.READ_ONLY_DATA_FEED` on the `the_odds_api` source. It is not a trading,
  account or withdrawal credential, and the registry has no kind for one
  (`tests/invariants/test_no_execution_paths.py`).
- **Who handles it.** Only the owner creates it and installs it, in the host environment as
  `EDGE_LAB_ODDS_API_KEY`, for example in a root-readable environment file for the service
  user. Agents never create, request, see or commit it. Never paste it into chat, git, a
  ticket or a notification.
- **How the code uses it.** `edge_lab.odds_api.load_key` is the only reader. A missing key is
  SETUP_NEEDED and nothing is sent. The key travels only as the documented `apiKey` query
  parameter; `edge_lab.http` refuses credential headers. Every returned or persisted URL is
  redacted (`redaction.redact_url`). Errors are re-raised with redacted text and no
  exception chain. The quota ledger holds counts only.
- **Before any live pull.** The key must be installed, **and** an owner-approved activation
  and quota plan must be recorded. Pulls stay under a protective ceiling of 450 of the 500
  monthly credits. No scheduled pulls are authorized.
- **If it leaks,** follow "If a secret is committed" below. Rotating the free key at the
  provider is the owner's step.

## If a secret is committed

Treat it as compromised. Revoke it at the provider first, then remove it from the tree, and
tell the owner. Rewriting history does not un-leak a secret that has already been pushed.
