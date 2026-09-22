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

Milestone 1 is complete when:

- [ ] `pytest` passes in CI.
- [ ] A Kalshi-only collection run succeeds without credentials.
- [ ] An NWS-only collection run succeeds with a compliant User-Agent.
- [ ] A combined collection run writes immutable records to SQLite.
- [ ] Re-running collection adds new snapshots instead of replacing old ones.
- [ ] Raw payload hashes are retained.
- [ ] Recent snapshot metadata can be inspected from the CLI.
- [ ] Failure of a network call marks the collection run failed without deleting earlier snapshots.
- [ ] No code path can submit an order.

## Next milestone

Milestone 2 will add:

- exact contract/settlement rule capture
- normalized executable-price views
- historical outcome labels
- a simple forecast-calibration baseline

Probability modeling does not begin until the settlement-source gate is satisfied.
