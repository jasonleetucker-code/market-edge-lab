# EXP-006 — Track B TB-03: maker favourite-side premium, Kalshi non-sports, two-sided bound (DRAFT, QUEUED)

**Status: DRAFT, slot QUEUED.** Not preregistered, not frozen, not running. No data has been read. It is a
**weakened hypothesis** (adversarial review R6: WEAKEN; near-KILL in sports, which is excluded), not an edge.
**By design this experiment cannot establish an edge.** It can only kill the hypothesis, or justify a forward
virtual-maker study.

- **Authority:** owner directive of 2026-10-08, the Track B entry of `docs/EXECUTION_PLAN.md` (PR #185),
  issue #184; family slots per #96.
- **Family:** `TB_FLB`, shared with EXP-005. `slot_status = "QUEUED"`.
- **Spec:** `experiment.toml` and `protocol.toml`. **Shortlist:** `docs/research/ALPHA_DISCOVERY_2026-10.md`,
  candidate TB-03.

## Design in one paragraph

A public trade tape has no depth, queue or order history, so it cannot estimate what *our* resting bids would
have filled. It can bound them:
- **Optimistic bound:** what incumbent makers earned buying the favourite at 0.70–0.95, net of the per-series
  maker fee.
- **Pessimistic bound:** trade-through fills of a hypothetical bid at the touch.

Data is post-2025-07 only, non-sports only, with one market per event, weighted per event and event-clustered.

## Kill and bound rules (to be frozen unchanged)

| Result | Verdict |
|---|---|
| Optimistic bound's 95% upper bound ≤ 0, or its point estimate ≤ 0 | **KILL** (FALSIFIED) |
| Positive at trade weight only | **KILL** |
| Optimistic > 0 and pessimistic ≤ 0 | **INSUFFICIENT_EVIDENCE** (uninformative about us). Request the forward virtual-maker study; do not continue retrospectively. |
| Pessimistic > 0 | Genuinely interesting, still not an edge. The forward study is needed. |

## Corrections carried from R6

- Sports maker fees date from 2025: a flat 0.25c before 2025-07-01, quadratic after (inGame 2025-07-07, a
  secondary source).
- The 2026-08-20 changelog entry is an **exemption** for independent NFL combos, not a start date.
- Becker's category "+7%" is the maker–taker gap. Maker returns themselves are about +3.6%.

## Data and blockers

- **Nothing is held.** It needs approval A2 for the non-sports universe.
- Maker-fee modelling is planned in the `research/tb-harness` lane and is not merged.
- The evidence-use log is not created until the universe is frozen.
- The forward virtual-maker study needs its own collection grant (decision packet).

## Log

- **2026-10-08.** Registered as DRAFT/QUEUED by the Track B R4/R5 writer, as R6's two-sided bound design. No
  data was read.
