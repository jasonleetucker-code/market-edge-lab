# 0019 — One venue and account capability registry; execution never authorized by data

Status: Accepted (2026-09-23, integration directive; issues #30, #32, #29)

**Problem.** The owner wants Kalshi, Polymarket US, Novig and sportsbook-consensus data. Without
one registry, each adapter would invent its own notion of "connected", and code existing would
be confused with a verified connection. That risks overstating coverage, or implying a trading
path because an API happens to offer one.

**Alternatives.**
- (a) A flag per adapter module.
- (b) Extend `sources.py`. That registry is about ingestion, not venue capabilities or
  execution.
- (c) A separate `venues.py` registry of venues and routes. Each capability carries an
  evidence-backed connectivity stage. `execution_authorized` is structurally False.

**Decision.** (c).
- **What a `VenueSpec` states.**
  - It separates `venue_id` (the exchange), `route_id` (the access path) and
    `liquidity_pool_id`. Two routes onto one pool are not independent liquidity.
  - It states every capability: catalog, quote, depth, history, settlement, account read,
    order write.
  - Each capability has a stage: PLANNED, NEEDS_ACCESS, IMPLEMENTED, TESTED,
    LIVE_DATA_VERIFIED, PARTIAL, STALE or UNSUPPORTED.
  - Only a recorded read is LIVE_DATA_VERIFIED.
- **Execution.** Constructing a spec with `execution_authorized=True` raises. Order write is
  never beyond NEEDS_ACCESS.
- **Distinct venues.** Polymarket US and Polymarket International are separate venues;
  International is UNSUPPORTED from the US. The Odds API is an AGGREGATOR, not a venue.
- **Cash timing** (`VenueCashTiming`) lives here. The starter policy consumes it.
- **Read-only data-feed credentials** (The Odds API free key) are a separate credential kind
  on the *source* registry, added with the adapters. They are never a trading credential.

**Tradeoffs.** Stages must be updated by hand when evidence changes. Tests pin the
invariants: no execution, and no live-verified stage without a recorded read.

**Reconsider when:** an owner decision authorizes an execution route. That needs its own ADR
and a change to the invariant tests. It is never a flag flip.

## Adapters addendum (2026-09-23, read-only multi-venue foundation)

- **Credential kind.** `sources.CredentialKind` has exactly two members: `NONE` and
  `READ_ONLY_DATA_FEED`. A credentialed source must also declare:
  - `credential_env_var`, the only place the owner installs the key;
  - `credential_transport="query_param"`, since `edge_lab.http` still refuses credential
    headers;
  - `owner_approval_ref`, a file that names the source.

  There is no trading kind, so a trading credential cannot be registered by adding data.
- **Why the invariant changed.** The old invariant was "no registered source requires
  credentials". The Odds API free key is owner-approved (directive section 10, issue #29), so
  that invariant could not hold. It was replaced, not deleted. Every credentialed source must
  be READ_ONLY_DATA_FEED, use query-param transport, name an env var, not be ACTIVE, and
  have an approval file that names it. Two more tests pin the rest:
  - the enum has only those two members;
  - `src/` reads no secret-looking environment variable other than a registered one.

  The credential-header refusal test is unchanged.
- **Adapters.** All three are PLANNED sources with no collector job and no timer.
  - `polymarket_us` (public gateway). Catalog, book, depth and settlement parsing are
    TESTED. One bounded live GET is recorded in `experiments/multi_venue/`. It stays at
    TESTED in the registry, because `test_only_recorded_reads_are_live_data_verified`
    currently pins LIVE_DATA_VERIFIED to Kalshi; that promotion is a coordinator decision.
    Price history is PLANNED. Fees are UNSUPPORTED.
  - `novig` public daily data. `history_read` is TESTED, with one manual read recorded. The
    live API stays NEEDS_ACCESS (OAuth).
  - `the_odds_api`. `catalog_read` and `quote_read` stay NEEDS_ACCESS; TESTED would read as
    access obtained. The evidence text says they are fixture-tested and that a live read
    needs the owner's key and an approved activation. Offered odds are never quotes, and
    redirects are refused for this source.
  - `discovery.classify` is the one shared discovery step, and `discovery.CatalogCoverage`
    is the shared coverage record. MATCHED_EQUIVALENT needs:
    - the same settlement identity;
    - resolved and hashed rules on both sides;
    - the same contract: payoff kind, amount, YES condition and outcome.

    Sibling brackets of one event are only related.
- **Follow-up (coordinator-owned, not changed here):** `opportunity.evaluate` does not check
  `Payoff.kind`. A non-binary market (for example `sportsbook_fixed_odds_per_unit_stake` from
  `odds_api`) could be priced as a $1 binary contract if anyone attached a quote to it.
  Today nothing builds such a quote, and fees are UNSUPPORTED for every venue except Kalshi.
  The engine should still reject any payoff kind other than `binary` explicitly.
- **Reconsider when** a second credentialed source is proposed, or when any source with a
  credential is to become ACTIVE. Either needs its own owner approval and a change to these
  tests in the same PR.
