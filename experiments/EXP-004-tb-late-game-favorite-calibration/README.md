# EXP-004 — Track B TB-01: late-game favourite underpricing, NBA/MLB (DRAFT, QUEUED)

**Status: DRAFT, slot QUEUED.** Not preregistered, not frozen, not running. No data has been read. It is a
**weakened hypothesis** (adversarial review R6, 2026-10-08), not an edge. No edge is established.

- **Authority:** owner directive of 2026-10-08 (`docs/owner/2026-10-08-rapid-alpha-discovery-directive.md`),
  the Track B entry of `docs/EXECUTION_PLAN.md` (PR #185), issue #184. Family slots: #96.
- **Family:** `TB_TTE` (new label, never A or B). `slot_status = "QUEUED"`: it holds no slot. ACTIVE needs an
  owner slot decision (`docs/owner/2026-10-08-alpha-discovery-decision-packet.md`).
- **Spec:** `experiment.toml` and `protocol.toml`. Unknowns are explicit on purpose.
- **ID allocation:** the next free ID after EXP-003 on `main` `67743ed` (no branch held EXP-004 or later).
- **Shortlist and ranking:** `docs/research/ALPHA_DISCOVERY_2026-10.md`, candidate TB-01.

## Design in one paragraph

The published effect (Moshrefi, arXiv 2607.14430) bucketed trades by time to the market close, which for these
markets is the realized end of the game. That conditions on the future: overtime and extra innings move tied
late games out of the last bucket. R6 notes that this selection predicts the paper's league ordering
(NHL 4.56 > MLB 2.05 > NBA 1.62). This experiment replaces that clock with **minutes since the scheduled start**,
known before the game, and scores at the **one-minute candle ask** (next minute's ask high), never at trade
prints. It makes **one decision per game**, so the two team markets are never double-counted, and clusters by game.
NHL and NFL are excluded by the Track B scope.

Kagan & Baiocchi (Kalshi-hosted, August 2026) also find better calibration once the clock is corrected; this
comes via the owner-supplied external research of 2026-10-08. So the evidence against now dominates. The
experiment stays queued because the shared A2 read settles it in days.

## Preregistered-in-draft kill rules (from R6; to be frozen unchanged)

- **KILL:** the validation block's game-clustered 95% upper bound of mean net return per dollar is ≤ 0, or the
  point estimate is ≤ 0.
- **ARTEFACT:** the effect appears under realized-close bucketing and vanishes under the scheduled-start clock.
- **UNINFORMATIVE:** the positive control fails (realized-close bucketing does not reproduce the S-shape on our
  sample).

## Data and blockers

- **Nothing is held.** It needs approval A2, a one-time Kalshi read of settled NBA/MLB markets, trades and
  one-minute candles. The Becker tape covers prints only and cannot score the primary endpoint.
- NBA/MLB fee multipliers are unverified. Results stay gross with a fee band until they are verified.
- **Label/field tension (open decision):** the scope-mandated `prohibited_fields` (settled fields) must be
  scoped to feature records before a label reader consumes this protocol.

## Evidence-use log

`evidence_use.jsonl` was created on 2026-10-08T10:37:29Z with `covered_scopes`:
- `kalshi:kxnbagame`
- `kalshi:kxmlbgame`
- `sports:nba:moneyline`
- `sports:mlb:moneyline`

So NBA games after the freeze can later be certified untouched if nobody views them unlogged. Retrospective
2025–26 outcomes predate the log and are UNKNOWN_LEGACY: they are exploratory only. **No use has been recorded.**

## Log

- **2026-10-08.** Registered as DRAFT/QUEUED by the Track B R4/R5 writer. The design was revised the same day to
  R6's bias-proof test: scheduled-start clock, quotes, one decision per game, positive, discriminating, sweep and
  negative controls. No data was read.
