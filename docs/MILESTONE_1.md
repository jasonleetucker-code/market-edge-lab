# Milestone 1 — Read-only evidence collection

## Objective

Build the evidence layer before building a strategy.

The collector must preserve enough point-in-time information to answer:

> What market data and external forecast data were actually available to us at a specific time?

## Scope

### Kalshi

Collect from the public production API:

- series metadata
- active market list for the configured series
- event metadata
- market order books

Default research series: `KXHIGHNY`.

### Weather

Collect from the National Weather Service API:

- point metadata for the configured reference coordinates
- 12-hour forecast
- hourly forecast
- raw grid forecast data

The default coordinates are a Central Park reference point. They are **not** asserted to be the settlement source.

## Evidence rules

1. Keep every raw response.
2. Timestamp receipt in UTC.
3. Hash canonical JSON.
4. Keep repeated unchanged responses; they prove what information remained available.
5. Never overwrite an older snapshot.
6. Never place trades from Milestone 1 code.
7. Never commit account credentials, API keys, or private research databases.

## Settlement-source gate

Before strategy work begins, separately verify the current contract rules, including:

- official settlement source
- observation location
- observation window and timezone
- rounding
- corrections/revisions
- missing-data procedure
- cancellation/voiding provisions

Then test whether our settlement parser can reproduce historical resolved contracts.

**No model gets promoted simply because its target resembles the market title.**

## Acceptance criteria

Milestone 1 is complete when the items below are checked. A box is checked only when there
is evidence. Evidence from 2026-09-22 comes from live read-only runs in a sandbox, not from
a scheduled deployment.

- [ ] `pytest` passes in CI. *(Tracked on the foundation PR's CI run. See `HANDOFF.md`.)*
- [x] A Kalshi-only collection run succeeds without credentials. *(2026-09-22: `--source kalshi`, exit 0)*
- [x] An NWS-only collection run succeeds with a compliant User-Agent. *(2026-09-22: NWS succeeded within a `--source all` run; points, forecast, hourly and grid were all stored)*
- [x] A combined collection run writes immutable records to SQLite. *(2026-09-22: 20 snapshots; UPDATE aborted by trigger)*
- [x] Re-running collection adds new snapshots instead of replacing old ones. *(2026-09-22: 2 runs → 36 rows)*
- [x] Raw payload hashes are retained. *(`payload_sha256` and `raw_sha256` on every new row)*
- [x] Recent snapshot metadata can be inspected from the CLI. *(`edge-lab recent`)*
- [x] Failure of a network call marks the collection run failed without deleting earlier snapshots. *(Unit tests: `tests/test_cli.py`; deletes are blocked by `tests/invariants/test_evidence_immutability.py`)*
- [x] No code path can submit an order. *(`tests/invariants/test_no_execution_paths.py`)*

## Next milestone

Milestone 2 will add:

- exact contract/settlement rule capture
- normalized executable-price views
- historical outcome labels
- a simple forecast-calibration baseline

Probability modeling does not begin until the settlement-source gate is satisfied.
