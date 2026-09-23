# 0023 — Binary payoff guard in the engine; per-market price grids as metadata

Status: Accepted (2026-09-23, production activation and post-audit integration directive,
follow-up #2 of `docs/GITHUB_REUSE_AUDIT.md`).

**Problem.**
- `opportunity.evaluate` computes edge as probability minus price per contract. That is a
  dollar edge only for a binary contract paying exactly 1. Nothing refused another payoff,
  so a scalar or categorical contract, or one paying 100, would have been priced wrongly
  and silently.
- Venues publish per-market price grids: Kalshi `price_ranges` (with subpenny structures
  since the week of 2026-07-27), Polymarket US `orderPriceMinTickSize`. The engine only
  knew the universal 1/100-cent grid (`valid_price`).

**Alternatives.**
1. Enforce the market grid inside `evaluate`, as a new INVALID_PRICE cause.
2. Keep the grid as market metadata. Enforce it where a price is chosen or walked: depth
   walks (`walk_ladder(price_grid=...)`) and, later, execution tickets.
3. Infer a grid when the venue publishes none, for example the cent grid.

**Decision.**
- `Reason.PAYOFF_UNSUPPORTED`: `evaluate` rejects any `Payoff.kind` other than `binary`, and
  any amount other than 1. The contract is never reinterpreted. EXP-001's markets are
  binary and pay 1, so its results do not change.
- `PriceGrid` / `PriceRange` in `opportunity.py`, carried on `Market.price_grid`:
  - built by `kalshi_quotes.price_grid_from_kalshi` and
    `polymarket_us.price_grid_from_market`;
  - None when the venue publishes none or the field is malformed; it is never assumed
    (alternative 3 rejected).
- Alternative 2. The engine keeps `valid_price` only. Enforcing a new rule in `evaluate`
  would change the frozen EXP-001 decision path in production without a preregistration
  amendment. A test pins that a market's grid does not change `evaluate`'s output.

**Tradeoffs.**
- An off-grid captured ask can still qualify in `evaluate`. The captured Kalshi books are on
  their market grid (tested), an off-grid level would be a venue anomaly, and a ticket or
  depth walk rejects it.
- A new reason code is added to the engine vocabulary. Opportunity ids are unaffected,
  because they hash inputs, not reasons.

**Reconsider if** a preregistered experiment is amended or a new experiment starts. Grid
enforcement in `evaluate` could then be part of its frozen spec. Also reconsider if a venue
is added whose contracts are not binary; that needs its own payoff model, not a weaker
guard.

Provenance: the per-market `price_ranges` check is an idea from `arshka/pykalshi`
(THIRD_PARTY_NOTICES.md TPN-R003); no code was copied.
