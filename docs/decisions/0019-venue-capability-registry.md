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
