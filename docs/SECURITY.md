# Security and Credentials

**Today:** the repository has no credentials, no authenticated clients, and no order-capable
code. `tests/invariants/` enforces this.

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
| `EDGE_LAB_RESEARCH_<PROVIDER>_KEY` | read-only research data API keys | not created |
| `EDGE_LAB_TRADING_<VENUE>_KEY_ID` / `_PRIVATE_KEY_PATH` | execution credentials, execution component only | not created, not authorized |

Private keys are referenced by **file path** outside the repository. Their contents never
go in environment variables.

## If a secret is committed

Treat it as compromised. Revoke it at the provider first, then remove it from the tree, and
tell the owner. Rewriting history does not un-leak a secret that has already been pushed.
