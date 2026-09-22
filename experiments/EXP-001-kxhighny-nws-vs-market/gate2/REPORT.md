# Gate 2 report: KXHIGHNY settlement validation

**Verdict: PASS.** Every Gate 2 criterion in `docs/EXECUTION_PLAN.md` is met (§6).
Produced 2026-09-22 from the evidence in this folder. To regenerate the tables from the
committed fixtures, run `python scripts/gate2_audit.py`; to check them, run
`python scripts/gate2_audit.py --check` (CI does this).

Semantics and citations: `docs/SETTLEMENT.md`. Sample definition, fixed before the held-out
window was evaluated: `SAMPLE.md` (commit 76c7c5a).

## 1. Method

The independence unit is the daily event. For each event, and each of its brackets:

- **Reproduction A:** apply `edge_lab.settlement.resolve` to Kalshi's own recorded
  `expiration_value`. This tests whether our rule semantics match Kalshi's.
- **Reproduction B:** apply the same resolver to the NWS CLI value chosen by
  `edge_lab.nws_cli.settlement_value`, which implements the contract's report-selection
  rules. This tests whether an independent official observation reproduces settlement.

Both are compared with Kalshi's recorded `result`. UNKNOWN never counts as a match. Strike
fields must agree with the `rules_primary` text, or the bracket is UNKNOWN.

## 2. Results

| | Window A: 2026-07-16..09-21 (inspected during exploration) | Window B: 2025 calendar year (held out) |
|---|---|---|
| Daily events | 68 (no missing dates) | 365 (no missing dates) |
| Brackets | 408 | 2,190 |
| Rules source | NWS CLI 29, The Weather Company 39 | NWS CLI 365 |
| Events with exactly one YES | 68 | 365 |
| Reproduction A (Kalshi value → result) | **68/68** | **309/309** (56 events have no `expiration_value` in Kalshi's historical record) |
| Reproduction B (NWS CLI → result) | **68/68** | **361/365** |
| Mis-predicted brackets (wrong YES/NO) | **0** | **0** |
| Unresolved (UNKNOWN) events | 0 | 4, all explained (§3) |

## 3. Every non-trivial event

| Event | What happened | Explanation (evidence) |
|---|---|---|
| KXHIGHNY-25FEB21 | First final CLI (06:29Z) had no maximum; second final (10:33Z) said 36 | GLOBALTEMPERATURE: first final report "that includes the relevant data". Reproduced (36 = Kalshi). |
| KXHIGHNY-25DEC03 | Preliminary 41, first final 40 (06:33Z), re-issued final 41 (14:21Z = 9:21 AM EST) | NHIGH: determination delayed to 11 AM ET when "the Final report high is lower than earlier report(s)". Reproduced (41 = Kalshi). Before this rule was implemented, the audit mis-predicted this event; that failure is what surfaced the rule. |
| KXHIGHNY-26AUG27 | A corrected preliminary (CCA) was higher than the first final | Delayed-determination rule applied; the latest final by 11 AM ET was still 77. Reproduced. |
| KXHIGHNY-25JUN02, -25JUN03 | No CLI product for these dates in the IEM archive | UNKNOWN: independent evidence unavailable. Kalshi recorded 66 and 79, and reproduction A matches. |
| KXHIGHNY-25JUN18, -25NOV13 | Only the preliminary CLI is archived; the final is absent | UNKNOWN, never guessed from the preliminary. Kalshi recorded 84 and 51, and reproduction A matches. |
| 56 events, 2025-10-31..12-31 (most) | Kalshi's historical record omits `expiration_value` | Reproduction A not possible; reproduction B reproduced every one. |
| 25 events, 2025-01-16..02-09 | One bracket per event lacks strike fields in Kalshi's record | Strikes read from that market's own `rules_primary` (fields absent, not contradicting); reproduced. |

**Unexplained mismatches: 0.**

## 4. The Weather Company vs NWS

TWC values could not be obtained legitimately (see `docs/SETTLEMENT.md` §6), so Kalshi's
official `expiration_value` was compared with the NWS CLI settlement value:

- **Exact agreement: 373/373 events** where both exist. That is 68/68 in window A, including
  all 39 TWC-era days, and 305/305 in window B.
- Difference distribution: `{0: 373}`. No boundary, rounding or correction clustering is
  possible to observe, because there were no disagreements.
- The two cases where the CLI value changed between issuances (2025-02-21 and 2025-12-03)
  are handled by the contract rules above. They are not TWC/NWS differences.
- **Conclusion (bounded):** NWS CLI, selected per the contract rules, reproduced every
  observed Kalshi settlement value, including under TWC-named rules. It is a well-supported
  *proxy label*. It is not proven identical to TWC. Keep Kalshi's `expiration_value` as the
  authoritative label, and keep auditing every new settlement.

## 5. Limitations

- Contract PDFs are the 2026-09-22 versions. Historical versions are unavailable, so
  per-event contract text relies on each market's own `rules_primary`/`rules_secondary`.
- NHIGH condition (1), inconsistency with METAR, is not implemented, because no METAR is
  collected.
- Window A was examined before `SAMPLE.md` was written. Window B is the independent test.
- IEM is a re-serve of NWS products. It was verified against `api.weather.gov` only for the
  15 products the API still holds.

## 6. Gate 2 criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Contract terms captured and versioned as immutable evidence | ✅ `document_blobs`/`document_retrievals` (exact bytes, SHA-256, versions kept) + `evidence/` |
| 2 | Settlement source hierarchy documented | ✅ `docs/SETTLEMENT.md` §1–2 |
| 3 | Window, station, timezone, precision, rounding, revisions, void/missing rules documented from primary evidence | ✅ `docs/SETTLEMENT.md` §3–5 (METAR condition noted as unimplemented) |
| 4 | ≥30 historical daily settlements evaluated | ✅ 433 (68 + 365) |
| 5 | Zero unexplained mismatches | ✅ 0 mis-predictions; 4 UNKNOWNs explained by missing archive products |
| 6 | TWC/Kalshi-value vs NWS differences measured | ✅ 373/373 exact (§4) |
| 7 | Kalshi pagination complete | ✅ bounded cursor following, loop detection, every page stored (tests) |
| 8 | Tests pass | see the PR (local runs on 3.11 and 3.12) |
| 9 | CI green on the final head | see the PR checks |
| 10 | Independent review: no unresolved correctness blocker | see the PR |
| 11 | No trading/authentication capability | ✅ `tests/invariants/` |
