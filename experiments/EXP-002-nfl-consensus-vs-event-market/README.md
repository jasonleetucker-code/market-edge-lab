# EXP-002 — Family A: NFL consensus vs executable event-market prices (DRAFT)

**Status: DRAFT.** Not preregistered, not frozen, not running. Nothing here is evidence of an
edge, and no sports model or strategy is operational or authorized.

- **Authority:** owner directive 2026-09-25 (`docs/owner/2026-09-25-economic-evidence-v1-directive.md`,
  `docs/EXECUTION_PLAN.md`), issue #96. Family A is research on stored evidence, not the excluded
  "sports model or sports strategy".
- **Family slot:** A (ACTIVE). At most two new active families exist beside protected EXP-001;
  `edge-lab experiments validate` enforces the limit.
- **Spec:** `experiment.toml` (registry schema) and `protocol.toml` (research-protocol sidecar;
  experiments/README.md). Unknown values are written as `UNKNOWN: …` or `MISSING_OWNER_INPUT: …`
  on purpose. The validator accepts them in DRAFT and refuses them from PREREGISTERED on.
- **ID allocation:** from the registry on main `b19d28a`, where only `EXP-001` exists.
  `docs/owner/2026-09-22-gate4-collection-directive.md` and `scripts/run_exp001_gate4.py` mention
  "EXP-002" only as the name a follow-up model would take after an EXP-001 Stage A **fail**.
  Stage A passed, so that name was never registered. `experiments/sizing_v2/` states that it has
  no ID yet.
- **Evidence-use log:** `evidence_use.jsonl` (append-only; `edge_lab.research_evidence`). It starts
  empty. Any access before the log existed is UNKNOWN.

## What must be settled before PREREGISTERED

1. The single primary endpoint: calibration at a horizon, or markout at a named later horizon.
2. The maximum input age, the pair skew and the untouched future window (by outcome window as
   well as by dataset hash).
3. Episode start threshold, end/merge gap and minimum size, frozen before any outcome is viewed.
4. The size ladder rungs, the multiple-testing plan and the futility rule.
5. The minimum useful economic effect (**owner input**) and a power analysis.

## Current blockers

- Paired Kalshi NFL books are not collected yet. Collection was **APPROVED** by the owner on
  2026-09-25 (`docs/EXECUTION_PLAN.md`, #110; collection only, within
  `docs/research/SPORTS_PAIRED_EVIDENCE_GAPS.md` §6). The implementation (#112) is pending deploy.
  The protocol stays DRAFT.
- The payoff-equivalence mapping (ties, overtime, postponement, void and refund, units) is not
  established. The contract states are now verified (`rules_evidence/MANIFEST.md`). The proposed
  treatment is explicit payoff modelling with ex-ante bounds
  (`docs/research/RESEARCH_UNBLOCKING_DECISIONS.md` §A.D), which is not yet settled.

## Log

- 2026-09-25: DRAFT registered (EE v1 PR A). No data viewed for this experiment.
- 2026-09-25 (RU Writer R, research-unblocking directive): protocol recommendation, all
  PROPOSED, in `docs/research/RESEARCH_UNBLOCKING_DECISIONS.md` §A. Nothing is settled or frozen,
  and the experiment stays DRAFT.
  - **Changed in the DRAFT protocol.** `open_decisions` now carries the verified rules facts and
    points to the recommendations, with a new OPEN 6 for the primary endpoint. The `[costs_fills]
    fills` text, the `[stopping]` UNVIABLE wording and `experiment.toml` `[execution] fill_model`
    now use the fill-mode labels v2 (ADR 0037):
    - FIRST_DETECTION_ZERO_LATENCY, which is not delay-adjusted;
    - HINDSIGHT_UPPER_BOUND, an oracle bound that may only rule the family out.

    Neither is executable performance. `[endpoints] primary` and `[economics] power_analysis`
    carry pointers only. No result used the old labels.
  - **Rules evidence.** The Kalshi FOOTBALLGAMEWIN contract terms and CFTC certification were read
    from their public URLs and stored in `rules_evidence/` with hashes. The terms add fair-price
    states the market rules text does not list: suspension before 55 minutes, a forfeit before
    kickoff, a venue or home/away change, and a pre-game disqualification.
  - **Revised after review (same PR):** the primary-endpoint proposal is now a *cross-book*
    markout with a Kalshi-only placebo as a required bias check. The earlier same-book statistic
    was biased upward under a no-information null. The pilot dates follow the owner's collection
    approval (#110).
  - **Data looked at.** None in this experiment's scope. The laptop store was inventoried
    read-only to look for measured Odds/Kalshi timing. It holds no Odds API or KXNFLGAME rows, so
    no `sports:nfl:moneyline` data was viewed and nothing is appended to `evidence_use.jsonl`. The
    inventory itself is logged in EXP-003's log, because the store holds KXHIGHNY rows.

- 2026-09-28 (VF Writer A, owner directive 2026-09-28 §7–§9, §21A). The status stays DRAFT; nothing is
  frozen.
  - **Gate v3** (`exp002-noise-gate-v3`, `docs/research/EXP002_GATE_V3.md`). The spread-based noise candidate
    failed its adversarial validation, with false-PASS up to 98% while the bias exceeded the tolerable level.
    v3 therefore has no PASS state (FAIL / INSUFFICIENT_DATA / INSUFFICIENT_EVIDENCE), and a freeze of the
    mid-based markout stays blocked. v2, the cross-book endpoint, the placebo, join v2 and logged label access
    are unchanged.
  - **Freeze settings proposed** (`docs/research/EXP002_FREEZE_PROPOSAL.md`, v1). They include an executable
    round-trip primary endpoint that needs no noise gate. PROPOSED; review required; chosen with no EXP-002
    data viewed.
  - **Fees** (`docs/research/EXP002_FEE_VERIFICATION.md`, captures in `fee_evidence/`). NOT RESOLVED:
    KXNFLGAME stays FEE_UNSUPPORTED, and no fee record was added. The Kalshi message remains NOT SENT.
  - **Terminal.** The Family A section shows the gate v3 line, with freeze eligibility separate and never
    eligible. The "latest paired book" no longer shows a T-60m book (a markout label). Such a display was
    possible and unlogged before, so pilot T-60m label exposure is UNKNOWN (freeze proposal §4).
  - **Data looked at:** none real. Only SYNTHETIC fixtures and simulations were used.
  - **Evidence-use log.** One hand-recorded POSSIBLE exposure was appended, at the coordinator's instruction:
    `eu-7f8e61282393c0bf2258b4bc90dd92c7`.
    - What it covers: the pilot T-60m KXNFLGAME books from 2026-09-26, which the pre-#124 Terminal could
      display. Whether anyone viewed them is unknown.
    - Fields: role DEVELOPMENT, `viewed_labels` null, `influenced_tuning` false.
    - Consequence: pilot T-60m data are DEVELOPMENT only and never relabelled untouched. Evaluation starts after
      #124 deploys (freeze proposal §4).

- 2026-09-29 (VF Writer A, coordinator instruction). The possible pre-#124 T-60m label exposure window is
  closed.
  - #124 was merged as `29a37d7` and deployed on production at 2026-09-29T02:09:50Z, per the coordinator.
  - The follow-up hand-recorded event `eu-f4954194ccbea8817aef73d4343122bb` extends
    `eu-7f8e61282393c0bf2258b4bc90dd92c7` to that time. It keeps the same fields: DEVELOPMENT, `viewed_labels`
    null, NOT A CONFIRMED VIEW.
  - The untouched evaluation window can start only after 2026-09-29T02:09:50Z and after the freeze is recorded
    (freeze proposal §4).
  - Production gate v3 at deploy: INSUFFICIENT_DATA (15 admissible T-6h games < 20; 1 NFL week < 4). Gate v2 is
    also INSUFFICIENT_DATA. Both are coordinator readings; the status stays DRAFT.

## Owner decisions

- 2026-09-26: owner decisions recorded (`docs/owner/2026-09-26-owner-decisions-economics-backup.md`): minimum useful effect $1,000/year (continuation bar beyond the pilot, not a pilot requirement); 6 owner hours through 2026-10-22; the +8 h extension returns to the owner. Status stays DRAFT.
