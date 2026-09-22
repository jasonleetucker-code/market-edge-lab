# EXP-001: KXHIGHNY NWS forecast vs market

**Status: RUNNING. Stage A PASSED (Gate 4, 2026-09-22); Stage B is pending.** The
preregistration was frozen on 2026-09-22 (`preregistration.json`).
- Gate 2 validated settlement. Gate 3 built the point-in-time dataset and the full
  specification (`gate3/`).
- Gate 4 fitted the frozen baseline. The validation rule selected V1, and the test split
  was opened once for Stage A (`gate4/REPORT.md`).
- Stage A checks probabilities only. Nothing here claims a trading edge.
- Stage B (prospective shadow trading) needs the forward order-book evidence now being
  collected (ADR 0012).

## Log

- **2026-09-22.** Spec drafted. First live read-only collection succeeded: 12 open markets,
  2 events, 12 order books, and 4 NWS payloads. The captured series metadata and market rules
  name **The Weather Company** (`https://weather.com/kalshi`) as the settlement source, for
  station CLINYC:

  > "If the maximum temperature recorded at New York City (CLINYC) for Sep 23, 2026, is
  > greater than 72° fahrenheit according to The Weather Company, then the market resolves
  > to Yes." (`markets[].rules_primary`)

  The series `contract_url` and `contract_terms_url` point to `GLOBALTEMPERATURE.pdf`.
  Web search results and third-party pages instead describe settlement on the NWS Daily
  Climate Report. **Primary evidence wins, and the discrepancy is itself a gate-2 finding.**
  Next: capture the contract PDFs, review the weather.com terms, collect the NWS CLI, and
  measure how the two agree.

- **2026-09-22 (gate 2).** Captured contract terms (GLOBALTEMPERATURE, the certification
  filing, legacy NHIGH) as exact bytes, plus every settled market (live and historical API).
  The rules source changed from NWS CLI to The Weather Company on 2026-08-14. Reproduced
  Kalshi results for 68/68 days (2026), 361/365 days (2025; this window was used to develop
  two rules; 4 UNKNOWN from archive gaps) and 366/366 days (2024, fresh validation with the
  procedure frozen first). 0 mis-predicted brackets under the final procedure. Kalshi
  `expiration_value` equals the NWS CLI settlement value on 739/739 events. Two contract
  report-selection rules were needed and implemented: "first final report that includes
  the data", and NHIGH's delayed determination when the final is lower than earlier reports.

- **2026-09-22 (gate 3).** Built `gate3/dataset.csv` (EXP-001-pit-v2): one row per
  target date 2017-01-01 → 2026-09-21, 3,551 days, all usable.
  - Forecast: the NWS PFMOKX Central Park max from the latest issuance at or before 17:30
    ET on D−1 (decision 18:00 ET).
  - Label: Kalshi `expiration_value` (1,801 days) or the NWS CLI contract-rule value (1,750
    days). They agree on all 1,797 days where both exist.
  - Train-only descriptive analysis: error sd 3.2 °F, MAE 2.3 °F, bias +0.44 °F, with a
    long right tail.
  - Specified the baseline (empirical error pmf, V1 pooled or V2 seasonal), the fee and
    execution models, Stage A (historical probability validation) and Stage B
    (prospective shadow trading), and the power check. Froze the preregistration (re-frozen once before merge after a second
    independent review corrected a DESIGN sentence and a Stage B definition; no
    validation or test error was computed at any point).
  - Found and fixed during the build: pre-March-2017 products use upper-case labels, and
    the WMO header often trails the local issuance line by 1 minute. Parser v2/v3
    handles both (v3 also refuses suffixed products); this was found before any error
    statistic was computed.

- **2026-09-22 (gate 4).** Implemented the frozen baseline (`src/edge_lab/exp001_baseline.py`,
  `scripts/run_exp001_gate4.py`) and ran it once. The work is four commits on
  `gate4/exp001-baseline`: code and amendments, validation, the single test run, and
  reproducibility tests.
  - Six dated pre-validation `[[amendments]]` (commit `e3405cf`) resolved ambiguities before
    any validation or test score existed. None changes a model, window or threshold.
  - Validation selection (`gate4/validation_selection.json`, commit `e1705d2`, train and
    validation rows only): d = lnP_V2 - lnP_V1 has mean -0.0020, 95% block-bootstrap CI
    [-0.0256, +0.0207], so the frozen rule selects **V1 (pooled)**.
  - Stage A: V1, R0 and R1 were refitted on 2,922 train + validation days and scored once on
    629 test days (split opened once, run at `e1705d2`, `gate4/test_split_opened.json`).
    - Condition 1: model - R0 per-day log score +1.253, CI [+1.147, +1.362]. Met.
    - Condition 2: randomized-PIT central coverage 0.806 (507/629), inside [0.75, 0.85]. Met.
    - Tails: 75 days with u < 0.10 and 47 with u > 0.90.
  - Reported only (not criteria):
    - model - R1: +0.020, CI [-0.001, +0.039]. The interval includes 0: V1 is not
      distinguishable from the Gaussian reference R1 at 95%;
    - mean Brier: model 0.892, R0 0.968, R1 0.897;
    - mean log loss: model 2.451, R0 3.705, R1 2.471.
  - Caveats, recorded and not investigated (investigating them would mean analysing the
    test split beyond the preregistration):
    - Climatology (R0) is a low bar.
    - The PIT tails are asymmetric: 75 days (11.9%) fell below 0.10 and 47 (7.5%) above
      0.90. Coverage is still inside the preregistered range.
    - The R1 Brier score uses floored probabilities over f±60, which need not sum to 1.
  - **Stage A PASS.** Per amendment 5 the status is now `RUNNING`: Stage B is pending.
    The owner authorized scheduled read-only forward collection on 2026-09-22 (ADR 0012).
    Stage B evaluation needs the valid days that collection produces. This is probability
    validation only. It is not evidence of a trading edge. Full report: `gate4/REPORT.md`.

## Open questions

1. ~~What does GLOBALTEMPERATURE.pdf specify?~~ Answered in `docs/SETTLEMENT.md`.
2. ~~Is automated retrieval from weather.com/kalshi permitted?~~ No (terms of use), so it
   is not collected. Kalshi's `expiration_value`/`result` serve as the official evidence.
3. How often do TWC final values differ from NWS CLI? Not directly measurable. Kalshi's
   value agreed with NWS on 39/39 TWC-era days; keep auditing new settlements.
4. ~~Framework prerequisite: deterministic preregistration baseline.~~ Implemented
   (`edge-lab experiments freeze`, CI `check-frozen`); use it when preregistering.
5. ~~Gate 3 design question: decision time vs. forecast availability.~~ Answered in ADR 0010
   and `gate3/DESIGN.md` §1.
6. ~~Stage B needs order books collected at 18:00 ET daily.~~ Authorized by the owner on
   2026-09-22: read-only scheduled collection on the Chase Upside VPS (ADR 0012,
   `edge-lab forward`).
7. Re-verify the fee coefficient against Kalshi's fee-schedule PDF before any Stage B
   result.
