# ADR 0043: Isolated Kalshi execution boundary (offline, hard-disabled)

**Status:** Accepted 2026-10-07 (#160, campaign package A/C). Authority: the owner's 2026-10-07 chat directive to
implement the Kalshi ordinary-event automation campaign, with the grant recorded in `docs/EXECUTION_PLAN.md`
(2026-10-07 entry) and verbatim in `docs/owner/2026-10-07-kalshi-execution-campaign-directive.md`. The campaign plan
is `docs/strategy/KALSHI_AUTOMATION_DELIVERY_160.md` (PR #163).

## Problem

The repository proves it cannot trade:
- `tests/invariants/test_no_execution_paths.py` forbids order paths, non-GET methods, venue auth headers, request
  bodies, client writes and signing anywhere in `src/`;
- `execution_ticket.pre_submit_checks` always ends in `EXECUTION_NOT_AUTHORIZED`.

That invariant names its own successor: a "separate component with its own review", changed "in the same PR as that
decision". The campaign needs that component:
- a durable intent journal;
- atomic reservations;
- a signer and transport;
- account reconciliation;
- an order lifecycle.

Two opposite failures are possible:
- **Lift the rule everywhere.** Any research module could then sign or send.
- **Hide execution code inside research modules.** The no-execution test would then stop meaning anything.

## Decision

1. **One package, `src/edge_lab/execution/`, is the only place execution code may live.** Research modules, the
   dashboard and the CLI never import it. `tests/invariants/test_execution_boundary.py` enforces this with an AST
   scan of every source file. Adding an `import edge_lab.execution` anywhere else fails CI.
2. **Inside the package, the no-execution rules still apply file by file.** Each rule is relaxed only for the
   exact file that needs it, in a path-exact table (`EXECUTION_EXCEPTIONS` in the invariant):
   - `execution/signer.py`: the request-signing rule only;
   - `execution/transport.py`: non-GET methods, request bodies and the two Kalshi auth headers;
   - `execution/kalshi_wire.py`: the order-endpoint rule only.

   Every other file in the package, including the journal, reservations, lifecycle and risk gate, is held to
   the full research rules. A copy, a rename or a new file inherits nothing.
3. **The package imports only reviewed owners.** It may import its own modules and an allowlist of canonical
   owners:
   - `execution_ticket`, `risk`, `fee_schedules`, `opportunity`, `freshness`, `redaction`, `venues`.

   It never imports a protected-label owner: `sports_evidence`, `exp002_timing`, `odds_schedule`,
   `price_observations`, `odds_consensus`, `experiments`, `settlement`, `forward`, `shadow_ledger`,
   `exp001_*`, `storage`. So it cannot read protected outcomes, and it cannot write the research store.
4. **Environments are closed and hard-disabled.** `Environment` is FIXTURE, DEMO or PRODUCTION.
   - FIXTURE is the only environment authorized. It means a fake transport and a disposable store.
   - DEMO and PRODUCTION network egress stay disabled by reviewed constants, pinned by tests to the plan's
     authorization phrases. Configuration, credentials or flags cannot enable them.
   - Enabling DEMO later is its own PR, made in the same change as a recorded owner approval.
   - No force flag exists.
5. **Exact values only.** Prices, quantities and money in the execution package are `Decimal` values built from
   `str` or `int`, never from `float` or `bool`. NaN, infinity and off-grid values are refused at construction.
6. **Identity is layered.** These are distinct, linked records:
   - business intent: a stable `intent_key` plus a content digest;
   - approval grant, bound to the intent digest;
   - send attempt;
   - provider order;
   - fill;
   - cancellation;
   - settlement;
   - correction.

   A client order id is derived from the intent. It is never proof of venue exactly-once execution.
7. **Credentials are not handled in this scope.**
   - Tests use keys generated at test time, never read from disk or the environment.
   - The signer receives a key object from its caller. No module reads a trading key path or environment
     variable.
   - Key handling arrives with the DEMO approval.
8. **Dependency.** Signing needs maintained cryptography, which the standard library does not provide. `cryptography`
   becomes an optional `execution` extra:
   - only `execution/signer.py` may import it;
   - CI installs it;
   - every other runtime module stays stdlib-only.

## Alternatives rejected

- **A separate repository or process right now.** The process boundary (distinct service user and store) is
  package O and is designed in. A second repository now would duplicate the risk, fee and ticket owners, and the
  campaign forbids a second financial authority.
- **Delete or exempt `test_no_execution_paths.py` for all of `src/`.** This loses the property that research cannot
  trade.
- **Write the signer with stdlib `hmac`.** Kalshi signs with Ed25519 or RSA-PSS, not HMAC. Hand-rolled
  cryptography is not acceptable.

## Tradeoffs

- Several files carry narrowly relaxed rules. Each relaxation is path-exact and is tested both ways: the
  exception is in use, and it does not spread to other files.
- The `cryptography` extra adds a compiled dependency to CI and to a future executor host. Research hosts that skip
  the extra can still import the rest of the package.

## Reconsider when

- DEMO access is approved: the DEMO constant, key handling and the real opener arrive in one reviewed PR.
- The executor moves to its own process or service user (package O).
- Another venue or an RFQ profile needs execution. That is a new profile, not an edit of this one.
