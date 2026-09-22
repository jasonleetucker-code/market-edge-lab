# Gate 2 report: KXHIGHNY settlement validation

**Verdict: Gate 2 criteria met** (§6). Merging PR #8 records the verdict. The owner's gate-2
directive of 2026-09-22 authorized that merge and the move to gate 3 once the criteria
held; see `docs/EXECUTION_PLAN.md`.

The tables are regenerated from committed fixtures with `python scripts/gate2_audit.py`,
and CI checks that they are current. Semantics and citations are in `docs/SETTLEMENT.md`;
the sample definition is in `SAMPLE.md` (windows A/B in 76c7c5a; window C in 04aeb95 with
the procedure frozen at 9f28602).

## 1. Method

The independence unit is the daily event; brackets are never counted as independent. For
each bracket:

- **Reproduction A** applies `edge_lab.settlement.resolve` to Kalshi's recorded
  `expiration_value`. This tests our rule semantics against Kalshi's.
- **Reproduction B** applies the same resolver to the NWS CLI value chosen by
  `edge_lab.nws_cli.settlement_value` (contract report-selection rules, scoped by date).
  This tests whether an independent official observation reproduces settlement.

Both are compared with Kalshi's `result`. UNKNOWN never counts as a match, and strike
fields must agree with `rules_primary`.

## 2. Results

| | A: 2026-07-16..09-21 | B: 2025 | C: 2024 |
|---|---|---|---|
| Role | inspected during exploration | **used to develop two rules** (see below) | **fresh validation**, procedure frozen first |
| Daily events (missing dates) | 68 (0) | 365 (0) | 366 (0) |
| Brackets | 408 | 2,190 | 2,196 |
| Rules source | NWS CLI 29, The Weather Company 39 | NWS CLI 365 | NWS CLI 366 |
| Rules wordings (templated `rules_hash`) | 6 | 2 | 2 |
| Exactly one YES per event | 68 | 365 | 366 |
| A: Kalshi value → result | 68/68 | 309/309 (56 lack `expiration_value`) | 366/366 |
| B: NWS CLI → result, final procedure | 68/68 | 361/365 | **366/366** |
| B: NWS CLI → result, original procedure (plain "first final") | 68/68 | 359/365, **1 mis-prediction** (25DEC03), 5 UNKNOWN | n/a |
| Mis-predicted brackets, final procedure | 0 | 0 | **0** |
| Unresolved, final procedure | 0 | 4 (archive gaps) | 0 |

**Window B is not an independent test.** Two report-selection rules were added because
window B events needed them: skipping a final report without a value (25FEB21) and NHIGH
delayed determination (25DEC03). Window C was defined afterwards, with the procedure frozen
before it was evaluated, and it reproduced all 366 days. Neither rule is exercised in
window C, so the delayed-determination rule rests on **one** observation (25DEC03).

## 3. Every non-trivial event (final procedure)

| Event | What happened | Explanation (evidence) |
|---|---|---|
| KXHIGHNY-25FEB21 | First final CLI (06:29Z) had no maximum; second final (10:33Z) said 36 | A report without the value cannot be the value. GLOBALTEMPERATURE words this as "first official non-preliminary report ... that includes the relevant data". Reproduced (36 = Kalshi). |
| KXHIGHNY-25DEC03 | Latest preliminary 41; first final 40 (06:33Z); re-issued final 41 (14:21Z = 9:21 AM EST) | NHIGH: determination delayed to 11 AM ET when "the Final report high is lower than earlier report(s)". Applied because the date precedes the GLOBALTEMPERATURE listing (after close, 2025-12-09). Reproduced (41 = Kalshi). Under GLOBALTEMPERATURE's wording the value would be 40, so which contract governed matters; we infer NHIGH from the date. |
| KXHIGHNY-25JUN02, -25JUN03 | No CLI product for these dates in the IEM archive | UNKNOWN: evidence unavailable. Reproduction A matches (Kalshi 66, 79). |
| KXHIGHNY-25JUN18, -25NOV13 | Only the preliminary CLI is archived | UNKNOWN, never guessed from a preliminary. Reproduction A matches (84, 51). |
| 56 events, mostly 2025-10-31..12-31 | Kalshi's historical record omits `expiration_value` | Reproduction A is not possible; reproduction B reproduced every one. |
| 25 events, 2025-01-16..02-09 | One bracket per event lacks strike fields | Strikes read from that market's own `rules_primary` (fields absent, not contradicting). Reproduced. |

**Unexplained mismatches (final procedure): 0.** Under the original procedure there was one
mismatch (25DEC03). It is explained by the NHIGH terms, but the rule was identified after
seeing the mismatch.

## 4. Kalshi value vs NWS CLI (no TWC value was observed)

No Weather Company value was ever obtained: its terms prohibit automated access
(`docs/SETTLEMENT.md` §6). What was measured is Kalshi's official `expiration_value`
against the NWS CLI settlement value:

- **Exact agreement: 739/739 events** where both exist (A 68/68, B 305/305, C 366/366).
- Difference distribution: `{0: 739}`. There were no disagreements, so no clustering can be
  observed.
- Only **39** of these events have TWC-named rules, all in window A (inspected during
  exploration). The evidence that NWS CLI tracks the value Kalshi uses *under TWC-named
  rules* is therefore 39 days.
- **Conclusion (bounded).** NWS CLI, selected per the contract rules, is a well-supported
  settlement **proxy label**. It is not shown to be identical to TWC. Kalshi's
  `expiration_value` remains the authoritative label, and every new settlement should be
  re-audited.

## 5. Limitations

- Contract PDFs are the 2026-09-22 versions only. Which document governed each historical
  event is inferred from dates (NHIGH through 2025-12-09, GLOBALTEMPERATURE after), plus
  each market's own rules text.
- NHIGH condition (1), METAR inconsistency, is not implemented. The delayed rule has one
  supporting observation.
- IEM is a re-serve of NWS products. It was verified against `api.weather.gov` for the 15
  products the API still holds.
- The comparison of settlement with **NWS forecasts** is gate 3 work (see
  `docs/EXECUTION_PLAN.md`).

## 6. Gate 2 acceptance criteria

The criteria are the owner's, recorded verbatim in `docs/owner/2026-09-22-gate2-directive.md`.

| # | Criterion | Evidence |
|---|---|---|
| 1 | Contract terms captured, versioned, immutable | `document_blobs`/`document_retrievals` (exact bytes, SHA-256, versions kept); `evidence/` |
| 2 | Settlement source hierarchy documented | `docs/SETTLEMENT.md` §1–2 |
| 3 | Window, station, timezone, precision, rounding, revisions, void/missing rules documented from primary evidence | `docs/SETTLEMENT.md` §3–5 (the METAR condition is noted as unimplemented) |
| 4 | ≥30 daily settlements evaluated | 799 (68 + 365 + 366) |
| 5 | Zero unexplained mismatches | final procedure: 0 mis-predictions; 4 UNKNOWN explained by archive gaps; the original procedure's one mismatch is explained (§3) |
| 6 | Kalshi-value vs NWS differences measured | 739/739 exact (§4) |
| 7 | Kalshi pagination complete | bounded cursor following, loop detection, every page stored (tests) |
| 8 | All relevant tests pass | `python -m pytest`: all tests pass locally (3.11.15, 3.12.3) and in CI |
| 9 | CI green on the exact final head | Before this file's last edit: head 45c02b0, run [35771310080](https://github.com/jasonleetucker-code/market-edge-lab/actions/runs/35771310080), both jobs green. The final head's run is in the PR #8 description; the merge is gated on it. This file cannot record its own commit's CI. |
| 10 | Independent review: no unresolved correctness blocker | §7 |
| 11 | No trading/auth capability | `tests/invariants/` |

## 7. Independent review log

A separate read-only reviewer agent tried to disprove completion, in two rounds. Its own
independent resolver and parser (not repo code) reproduced every bracket in all three
windows.

| Round | Finding | Severity | Resolution |
|---|---|---|---|
| 1 | Window B tuned the procedure (two rules added on B events); not a held-out test | major | Window C (2024) defined before evaluation with the procedure frozen at 9f28602 (commit order verified by the reviewer): 366/366. Window B's original-procedure result is reported (§2). |
| 1 | NHIGH delayed rule applied to all dates; conflicts with GLOBALTEMPERATURE's "first ... report" | major | Scoped by date (≤ 2025-12-09); conflict documented (`docs/SETTLEMENT.md` §4). |
| 1 | IndexError when a delay is needed but no final exists before the cutoff | minor | Returns UNKNOWN (test). |
| 1 | A superseded (uncorrected) preliminary drove the delay rule | minor | The latest preliminary (the correction) is used (test). |
| 1 | "TWC vs NWS" labelling overstated | minor | Relabelled "Kalshi value vs NWS"; 39 TWC-era days stated. |
| 1 | `rules_hash` unique per bracket, so it could not detect versions | minor | Date, comparison and strike templated out (6/2/2 versions). |
| 1 | Final reports with "VALID AS OF" silently unclassified | minor | Noted in the selection basis (test). |
| 1 | Nondeterministic dedupe of duplicate market records; fixture docstring | minor | Deterministic preference (test); docstring corrected. |
| 1 | Gate 3 marked active without a recorded owner approval; PASS ahead of CI/review evidence; criterion 4 forecast clause unmet | blocker | Owner directive recorded verbatim; gate 3 active on merge; forecast clause explicitly moved to gate 3 as an amendment. |
| 2 | The 11 criteria and CI requirements existed only in chat | major | This file's §6 and `docs/owner/2026-09-22-gate2-directive.md`. |
| 2 | Everything else re-checked: resolved; no blockers | — | — |
