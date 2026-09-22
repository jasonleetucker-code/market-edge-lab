# EXP-001 Gate 3 design: decision time, data, model, split, costs, execution, criteria

Written and frozen **before any model was fitted and before any validation or test forecast
error was computed**. The binding version is `../experiment.toml`, frozen in
`../preregistration.json`. If this file and the manifest disagree, the manifest wins.

## 1. Decision time and availability (ADR 0010)

- **Target date D** is the local calendar date whose maximum temperature settles KXHIGHNY.
- **Decision time**: 18:00 America/New_York on D−1. Converted to UTC with the US DST rule
  (`dataset_exp001.decision_time`): 22:00Z during EDT, 23:00Z during EST.
- **Availability cutoff**: decision − 30 min.
- **Forecast used**: the latest PFMOKX issuance with issuance time ≤ cutoff that contains a
  Central Park daytime maximum for D, and was issued no more than 24 h before the cutoff.
  - Issuance time is the WMO header time. It must lie within 0–15 min after the product's
    typed local issuance line, otherwise the product is ambiguous and never used.
  - Later issuances and later corrections are never considered. The row records how many
    were ignored (`issuances_after_cutoff_ignored`).
  - Suffixed products (CCx correction, RRx delayed, AAx amendment) are never used. They keep
    the original timestamp but are sent later, so their availability time is unknown. The
    2016-12 → 2026-09 archive contains none.
  - If two products share the latest eligible issuance minute and disagree on D's max, the
    row is excluded (`CONFLICTING_SIMULTANEOUS_ISSUANCES`). Picking one would be arbitrary.
  - `forecast_available_utc` = issuance + 30 min. It is recorded separately from issuance.
- **Never used**: a forecast issued after the cutoff; a corrected value published after
  the cutoff; a later archive copy substituted for the original (products are identified
  by SHA-256 and deduplicated); settlement information; market information. The dataset
  has no market price columns at all.

## 2. Historical forecast source

| Candidate | Verdict |
|---|---|
| **NWS PFMOKX via IEM AFOS archive** (`iem_afos_pfmokx`) | **Chosen.** Official NWS forecast *as issued*, with its issuance timestamp; free; public-domain product re-served by a university archive; continuous 2016-12 → present. |
| IEM MOS archive (GFS/NAM MOS, NBM) | Model guidance, not the NWS forecast a trader sees. Future feature candidate, not needed for the baseline. |
| NDFD grids (NCEI) | Gridded and heavy (GRIB2), same forecaster intent as PFM. PFM is the text rendering at the point we need. |
| Our own `api.weather.gov` snapshots | Exist only from 2026-09-22. Usable for Stage B, not for history. |
| Paid vendors | Not considered (free-first rule, owner idea #7). |

Parsing (`edge_lab.nws_pfm`, parser v3) is positional. The Min/Max row's values are
right-aligned to the hour columns. The daytime max sits at 19 EST / 20 EDT, the overnight
min at 07 EST / 08 EDT. A value in any other column, or not aligned, is not read.

## 3. Dataset (see `QUALITY.md`, `dataset_manifest.json`)

- One row per target date, 2017-01-01 → 2026-09-21. Every row carries:
  - the event ticker (if the date has a Kalshi event), rules hash, rules source and
    contract regime;
  - decision and cutoff times;
  - the forecast's WMO header, issuance/availability time, lead, max, full-product
    SHA-256, extract SHA-256 and parser version;
  - the prior (≥ 12 h earlier) issuance for revision;
  - the label and its source, the NWS CLI value, basis, WMO header and issuance time;
  - `market_price_available=false`;
  - `usable` and `exclusion_reason`.
- **Label**: Kalshi `expiration_value` when the date's Kalshi event records one; 68 settled
  events record none. Otherwise
  the NWS CLI value selected under the contract rules validated in Gate 2
  (`nws_cli.settlement_value`), where Kalshi and NWS agreed on 739/739 events. If both
  exist and differ, the row is excluded (`KALSHI_CLI_CONFLICT`). If an event's markets
  disagree on `expiration_value`, the row is excluded (`KALSHI_VALUE_INCONSISTENT`) and
  never silently relabelled from the CLI.
- Exclusion codes: `NO_PFM_BEFORE_CUTOFF`, `PFM_STALE_AT_CUTOFF`,
  `CONFLICTING_SIMULTANEOUS_ISSUANCES`, `NO_SETTLEMENT_LABEL`, `KALSHI_CLI_CONFLICT`,
  `KALSHI_VALUE_INCONSISTENT`. Excluded rows stay in the file with their reason.
- **Issuance regime shift (disclosed before any error was computed):** the NWS issued fewer
  PFMOKX updates from mid-2025, and the afternoon package moved to about 18Z. In the test
  period the chosen forecast is typically 3–5 h old at the decision time, against about
  2.5 h in 2017–2024 (`QUALITY.md`, "regime by year"). The fit years therefore have fresher
  forecasts than the test years. This is not corrected; it is part of what Stage A tests.
- Identity: `dataset_sha256` is computed over the canonical CSV. Every input file's SHA-256
  is in the manifest, and CI rebuilds and byte-compares the outputs
  (`tests/test_gate3_reproducible.py`).

## 4. Train / validation / test (fixed by date)

| Split | Target dates | Use |
|---|---|---|
| train | 2017-01-01 → 2022-12-31 | Fit; descriptive analysis (`DESCRIPTIVE_TRAIN.md`). |
| validation | 2023-01-01 → 2024-12-31 | Choose between V1 and V2 only (rule in §5). |
| test | 2025-01-01 → 2026-09-21 | Evaluated **once**, in Gate 4, with everything frozen. |

**Labels versus performance.** Gate 2 inspected *settlement labels* for 2024–2026 to
validate the settlement procedure. That is not model information. No forecast error, model
score or strategy result has been computed for 2023–2026. `describe_exp001.describe`
refuses non-train rows, and `QUALITY.md` contains counts only.

## 5. Baseline model (specification; fitted in Gate 4)

Notation: f = `forecast_max_f` (integer °F), y = label (integer °F), k = y − f.

- **Empirical integer error distribution.**
  P(y = f + k) = (n_k + 0.5) / (N + 0.5 × 41) for k ∈ {−20, …, 20}, where n_k counts fit
  days with error k and N is the number of fit days. Errors outside ±20 are counted at the
  nearest end (±20). An outcome with |k| > 20 is scored at that end.
- **Variants (exactly two):**
  - V1: one pooled pmf.
  - V2: one pmf per meteorological season of D (DJF, MAM, JJA, SON).
- **Fit windows (no expanding updates):**
  - For validation scoring: fit on usable train days.
  - For test scoring: refit the selected variant once on usable train + validation days.
  - For Stage B: refit once on all usable days through 2026-09-21.
- **Bracket probability** = the sum of the pmf over the integers that `settlement.resolve`
  maps to YES for that market (greater: > floor; less: < cap; between: floor..cap
  inclusive).
- **Score**: per-day log score = ln P(y). Mean over usable days; higher is better.
- **Selection on validation**: compute the per-day difference d = ln P_V2(y) − ln P_V1(y).
  Choose V2 only if mean(d) > 0 **and** the lower end of its 95% bootstrap interval is > 0.
  Otherwise choose V1.
- **Bootstrap (all uses)**: `edge_lab.stats.block_bootstrap_mean_ci` exactly as implemented
  and frozen. Circular moving blocks of 7 days, starts drawn by
  `random.Random(20260922).randrange(n)`, ceil(n/7) blocks truncated to n, 10,000
  resamples, and percentile bounds m[floor(α/2·B)] and m[ceil((1−α/2)·B)−1] with α = 0.05
  unless stated. The input is per-day values of usable days in date order.
- **References**:
  - R0, monthly climatology: for each calendar month m, P(y) = (c_y + 0.5) / (N_m + 0.5 × S)
    over integer support y ∈ [min_y − 10, max_y + 10], where c_y counts fit days in month m
    with label y and S is the support size. min_y and max_y come from all fit-window labels
    (every month), so the support is the same for every month. An outcome outside the
    support is scored at the nearest end. Same fit windows as the model.
  - R1, Gaussian: y ~ N(f + μ, σ²) discretized to integers (mass on [y − 0.5, y + 0.5]),
    with μ and σ the fit-window mean and population sd of k. Probability is floored at
    1e-9. R1 is reported only; it is not a pass/fail criterion.
- No ML, no other features, no tuning beyond the V1/V2 rule.

## 6. Two separate validations

### Stage A: historical probability validation (Gate 4; data exist)

Uses the selected variant, fitted on train + validation, scored once on the usable test
days.

- **PASS** when both hold:
  1. mean(ln P_model(y) − ln P_R0(y)) > 0, with the 95% block-bootstrap interval's lower
     end > 0;
  2. calibration: randomized PIT u = F(y−1) + v·P(y), with v ~ U(0,1) drawn by
     `random.Random(20260922)` in date order (`edge_lab.stats.randomized_pit`). The
     fraction of test days with 0.10 ≤ u ≤ 0.90 (`stats.central_coverage`) lies in
     [0.75, 0.85].
- **FAIL** otherwise.
- **A Stage A pass is not evidence of a trading edge.** It shows only that the
  forecast-derived probabilities are informative and calibrated. Historical market prices
  and order books do not exist for us, so no historical comparison with the market is made
  or required.

### Stage B: prospective shadow trading (after Gate 3; needs collection)

- Data: KXHIGHNY order books collected at each decision time from the first decision day
  after this freeze. This needs a scheduled collector, which needs owner approval (ADR 0008).
  **Stage B is BLOCKED-ON-OWNER. That does not block Gate 3 or Stage A.**
- Execution and fees as §7 and §8. Signal: for each open bracket of event D, with model
  probability p (§5):
  - buy 1 YES if p − cost_yes ≥ 0.05;
  - buy 1 NO if (1 − p) − cost_no ≥ 0.05;
  - cost = `fees.cost_per_contract(1, ask)` (price + fee, cent-rounded).

  There is one fixed threshold and it is not searched. At most one contract per bracket
  per day.
- **Valid decision day**: the collector stored the event's order books in the decision
  window (§8) and a latency re-check snapshot 10–15 min later. Days without both are
  excluded from Stage B and counted in its report.
- **Daily value**: the sum of that day's net P&L over filled trades. It is 0 on a valid day
  with no signal, or where every signal was `NO_BOOK` or `NO_FILL_UNVERIFIED`. Such days
  stay in the mean.
- **Exactly two looks**, at the 180th and the 365th valid decision day. Each uses the block
  bootstrap with α = 0.025 (97.5% interval; Bonferroni for two looks). There is no
  checking in between.
  - **PASS** at a look: mean daily net P&L > 0 and lower bound > 0.
  - **FAIL** at a look: upper bound < 0, or Stage A failed (in which case Stage B is not
    run for this model).
  - Otherwise at 180: continue to 365. Otherwise at 365: **INCONCLUSIVE**.
- A Stage B pass would be SHADOW_POSITIVE, not EDGE_PROVEN.

## 7. Fee model (`edge_lab.fees`, version 1)

- Series snapshot: `fee_type: quadratic`, `fee_multiplier: 1`
  (`evidence/kalshi_series_KXHIGHNY.json`).
- Model fee = multiplier × 0.07 × C × P × (1 − P), with C contracts at price P in dollars.
  The coefficient 0.07 comes from the documented worked example: $0.00363825 for 1
  contract at $0.055 = 0.07 × 0.055 × 0.945.
- Trade fee = the model fee rounded up to $0.000001.
- Cash change for a non-direct member = floor to the cent of (−P × C − trade fee). The
  example gives $0.06 for 1 contract at $0.055
  (`evidence/kalshi_docs_fee_rounding.html`, SHA-256 `1fe9de3a…`).
- Conservative: taker only; no maker fills, no rounding rebates. No settlement fee is
  assumed, because none is documented in captured evidence.
- **Limitation**: the fee-schedule PDF (kalshi.com/docs/kalshi-fee-schedule.pdf) sits
  behind a bot checkpoint (HTTP 429, "Vercel Security Checkpoint") and was not retrieved,
  and it was not bypassed. The fee in force must be re-verified from a primary source
  before any Stage B shadow result is reported. A different schedule becomes a new fee
  model version applied from its effective date.

## 8. Execution model (Stage B only; nothing executes)

- **Book**: the KXHIGHNY order book for the bracket, captured in [decision − 5 min,
  decision]. A missing or older book means no trade (`NO_BOOK`), never a
  mid or last price.
- **Price**:
  - YES buys at the implied ask, 1 − best NO bid;
  - NO buys at 1 − best YES bid.

  Never mid, last or a model price.
- **Size**: 1 contract. It must be ≤ the displayed size at that level.
- **Latency L = 10 min**: the fill counts only if a later captured book, 10–15 min after
  the decision snapshot, still offers the same side at a price ≤ the entry price with size
  ≥ 1. Otherwise `NO_FILL_UNVERIFIED`, with P&L not counted.
- **No retroactive fills**: decisions use only data captured at or before the decision
  snapshot, and fills are never inferred from later trades.
- **P&L**: settles by `settlement.resolve` on the official label. Payout is $1 on a win,
  minus the cost per §7.

## 9. Power

See `POWER.md`.
