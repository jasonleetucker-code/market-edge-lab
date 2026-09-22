# EXP-001: KXHIGHNY NWS forecast vs market

**Status: PREREGISTERED (frozen 2026-09-22, `preregistration.json`).** Gate 2 (settlement)
passed; Gate 3 built the point-in-time dataset and the full specification (`gate3/`). No
model has been fitted, no validation or test error has been computed, and nothing here
claims an edge. Next: Gate 4 implements the frozen baseline and evaluates it once.

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

- **2026-09-22 (gate 3).** Built `gate3/dataset.csv` (EXP-001-pit-v1): one row per
  target date 2017-01-01 → 2026-09-21, 3,551 days, all usable.
  - Forecast: the NWS PFMOKX Central Park max from the latest issuance at or before 17:30
    ET on D−1 (decision 18:00 ET).
  - Label: Kalshi `expiration_value` (1,801 days) or the NWS CLI contract-rule value (1,750
    days). They agree on all 1,797 days where both exist.
  - Train-only descriptive analysis: error sd 3.2 °F, MAE 2.3 °F, bias +0.44 °F, with a
    long right tail.
  - Specified the baseline (empirical error pmf, V1 pooled or V2 seasonal), the fee and
    execution models, Stage A (historical probability validation) and Stage B
    (prospective shadow trading), and the power check. Froze the preregistration.
  - Found and fixed during the build: pre-March-2017 products use upper-case labels, and
    the WMO header often trails the local issuance line by 1 minute. Parser v2 handles
    both; this was found before any error statistic was computed.

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
6. Stage B needs order books collected at 18:00 ET daily. That is scheduled collection,
   which is an owner decision (ADR 0008).
7. Re-verify the fee coefficient against Kalshi's fee-schedule PDF before any Stage B
   result.
