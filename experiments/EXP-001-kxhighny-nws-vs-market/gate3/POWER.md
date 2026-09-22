# EXP-001 sample-size and power reality check

Inputs come only from the **train** split (`DESCRIPTIVE_TRAIN.md`, "Power inputs"). No
validation or test result was used or computed. Approximations use two-sided α = 0.05 and
power 0.8, so the minimum detectable effect is MDE ≈ 2.8 × sd / √n_eff.

## Independent unit

The day. One decision per target date. Brackets of the same day share one outcome, so
they are not independent observations. Train lag-1 autocorrelation is 0.155 for the
forecast error and 0.108 for the log-score difference. That is why every interval uses a
7-day block bootstrap. With ρ ≈ 0.1–0.16, n_eff ≈ n × (1 − ρ)/(1 + ρ) ≈ 0.73–0.82 × n.

| Split | Usable days | n_eff (approx.) |
|---|---|---|
| train | 2,191 | ~1,650 |
| validation | 731 | ~550 |
| test | 629 | ~470 |

## Stage A (historical, test once)

- **Model vs R0 climatology.** In-sample on train, the per-day log-score difference has
  mean ≈ 1.03 nats and sd ≈ 1.00. On the test split, MDE ≈ 2.8 × 1.00 / √470 ≈ 0.13 nats.
  The expected gap is about 8× that. **Stage A is heavily powered against climatology.**
  Passing it is a low bar: it confirms that the pipeline, the point-in-time selection and
  the calibration are sound. It is not evidence of an edge.
- **Calibration.** The randomized PIT central-80% coverage has SE ≈ √(0.16/470) ≈ 0.018.
  The [0.75, 0.85] band is about ±2.7 SE, so a calibrated model fails it by chance only
  rarely. A coverage error of more than about 0.05 would be detected.
- **V1 vs V2 selection (validation).** The sd of the per-day V2−V1 difference is unknown
  until Gate 4. It is expected to be much smaller than the per-day log-score sd (0.90),
  because the two pmfs share most of their mass. When the difference is not resolvable,
  the rule defaults to V1 (simpler), so low power costs nothing but a possibly better
  variant.

## Stage B (prospective shadow trading): the binding constraint

- A single contract's P&L has sd ≈ √(p(1−p)) ≤ $0.50. Detecting a mean edge δ per contract
  needs about n ≈ 7.84 × 0.25 / δ² roughly independent trades:

  | Edge per contract δ | Trades needed (σ = 0.5) |
  |---|---|
  | $0.10 | ~200 |
  | $0.05 | ~780 |
  | $0.02 | ~4,900 |

- At 0–3 signals a day (correlated within the day), 180 decision days give on the order of
  100–400 trades and about 180 independent days. **180 days can only detect a large edge
  (roughly ≥ $0.07–0.10 per contract). An edge of a few cents would need years of one
  series.** That is why Stage B allows continuation to 365 days, and why an INCONCLUSIVE
  outcome is expected and acceptable.
- One city, one series, one decision time. Any edge found would be specific to NYC
  summer/winter regimes and to this market's liquidity. Generalization needs new
  preregistered experiments, not reuse of this one.

## Consequences written into the preregistration

- Stage A pass/fail is computable from existing data. Stage B needs data that do not yet
  exist and cannot be backfilled (historical order books), and it is BLOCKED-ON-OWNER for
  scheduled collection (ADR 0008).
- Neither stage alone can establish EDGE_PROVEN.
