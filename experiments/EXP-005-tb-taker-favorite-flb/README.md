# EXP-005 — Track B TB-05: taker favourite-side FLB, short-dated Kalshi non-sports (DRAFT, QUEUED)

**Status: DRAFT, slot QUEUED.** Not preregistered, not frozen, not running. No data has been read. It is a
**weakened hypothesis** (adversarial review R6, 2026-10-08), not an edge. No edge is established.

- **Authority:** owner directive of 2026-10-08, the Track B entry of `docs/EXECUTION_PLAN.md` (PR #185),
  issue #184; family slots per #96.
- **Family:** `TB_FLB`, shared with EXP-006 (one mechanism, one slot). `slot_status = "QUEUED"`.
- **Spec:** `experiment.toml` and `protocol.toml`. **Shortlist:** `docs/research/ALPHA_DISCOVERY_2026-10.md`,
  candidate TB-05.

## Design in one paragraph

Published support is at trade prices and contract or trade weight:
- Bürgi/Deng/Whelan: small positive post-fee returns above 70c through April 2025, with the slope halving in
  2025;
- Becker: the effect is YES-specific (affirmative bias).

On Polymarket the bias reverses at event-equal weight (Cardozo & Rivero-Wildemauwe). This experiment therefore:
- scores at the **one-minute candle ask**;
- makes **one decision per event** and weights events equally;
- uses only **post-2025-07** data;
- stops the band at **0.95**, because at 0.99 the gross edge (about 0.41%) is below one 1c tick;
- never buys a basket of an exclusive event (EXP-003 Family B, PAUSED).

## Kill rules (to be frozen unchanged)

- **KILL:** the validation block's event-clustered 95% upper bound is ≤ 0, or the point estimate is ≤ 0.
- **ARTEFACT:** the effect is positive only at trade weight.
- **DECAYED:** the latest block's point estimate is ≤ 0.

## Data and blockers

- **Nothing is held.** It needs approval A2, extended to the frozen non-sports universe.
- Per-series fee types are not yet read.
- The evidence-use log is **not created yet**. It is created with frozen `covered_scopes` when the universe is
  frozen, before the first look. Declaring a broad scope such as `kalshi` now would over-claim coverage of other
  experiments' scopes.
- The same `prohibited_fields` label tension applies as in EXP-004.

## Log

- **2026-10-08.** Registered as DRAFT/QUEUED by the Track B R4/R5 writer, and revised the same day to R6
  (quotes, event-equal weight, regime rule, 0.95 cap). No data was read.
