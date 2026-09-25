# EXP-003 — Family B: same-venue payoff consistency (DRAFT)

**Status: DRAFT.** Not preregistered, not frozen, not running. A conditional full-fill surplus is
not captured arbitrage. No fills exist in this experiment.

- **Authority:** owner directive 2026-09-25 (`docs/owner/2026-09-25-economic-evidence-v1-directive.md`,
  `docs/EXECUTION_PLAN.md`), issue #96.
- **Family slot:** B (ACTIVE).
- **Spec:** `experiment.toml` and `protocol.toml` (research-protocol sidecar). Unknown values are
  explicit on purpose.
- **ID allocation:** the next free ID after EXP-002 in the registry on main `b19d28a`.
- **Isolation from EXP-001:** this family reads market-side books, rules and fee records only.
  EXP-001 forecasts, outcomes, labels and the shadow ledger are `prohibited_inputs`.
  `edge_lab.research_evidence.record_use` refuses to log access to them for this experiment.
  EXP-001 is not changed in any way.
- **Evidence-use log:** `evidence_use.jsonl` (append-only). Any access before the log existed is
  UNKNOWN.

## What must be settled before PREREGISTERED

1. The primary endpoint and the allowlist of relationship sets.
2. The maximum leg book age, the leg-to-leg skew and the untouched future window (by event-day
   window as well as by dataset hash).
3. Episode start threshold, end/merge gap and minimum size.
4. The size ladder, the multiple-testing plan and the futility rule.
5. The minimum useful economic effect (**owner input**).

## Log

- 2026-09-25: DRAFT registered (EE v1 PR A). No data viewed for this experiment. The evaluator
  and the run over stored KXHIGHNY books follow in PR B.
- 2026-09-25 03:38Z (EE v1 PR B): first development scan
  (`results/payoff_scan_laptop_store_2026-09-22.json`). Every look at this data is logged, and
  there are five:
  - `eu-92904c0f26bf2ab0ad278b774bbc4ac0`: the 03:38Z look, recorded by hand with `record-use`,
    because the scan did not log itself yet. The entry itself says so.
  - `eu-1252b03466882d648c95b9345eec0ce6` (04:55Z) and `eu-c903acfb44e9b10a3950237db62cc074`
    (05:16Z): CLI-logged re-runs during the #102 review fixes. The code version they record is the
    branch HEAD *before* those fixes were committed, so the code that actually ran had uncommitted
    changes. The CLI now marks that case as `+uncommitted-code-changes`.
  - `eu-2cec29434e848288ac12fb8ba6a11981` (05:17Z): a re-run at the committed code `a4a9635`. Its
    note names the report hash in the older free-text form.
  - `eu-374acc98ca83fac9d86ed28643e2bc54`: the run that produced the committed result file, at the
    committed code `79edfda`. Its note carries the exact `report_sha256=<sha>` token, which
    `verify_result_provenance` requires.

  All five use the same books and event window (2026-09-22..2026-09-23) and give the same result.
  Integer settlement is only an observed premise, so every KXHIGHNY proof stays INCOMPLETE on that
  ground alone. No positive surplus could be claimed here in any case.
  The result file carries its provenance: laptop store, store identity (schema v3, max snapshot
  id 36), code version, event window and evidence-use event id. It is checked by
  `payoff_constraints.verify_result_file` and `verify_result_provenance`.
  - **Input.** The only evidence store in this session: the laptop's
    `data/edge_lab.sqlite3`, read-only. It holds 2 KXHIGHNY events (26SEP22, 26SEP23) with 6
    brackets each, books captured on 2026-09-22 about 22:38Z. The production VPS store, with daily
    decision and recheck books, was **not** read from this session. The same command runs
    read-only there.
  - **Windows.** Quote age 300 s and leg skew 60 s, stated for this run only. The protocol values
    are UNKNOWN.
  - **Result:** 2 sets, both relationship INCOMPLETE. VOID, REFUND and CANCELLATION are not
    excluded by captured evidence.
    - 26SEP23 at size 1: the top-of-book asks sum to 1.06 per basket, an observed inconsistency of
      -0.06 before fees. The worst state is the discretionary fair-price fallback, which pays 0.
      The claim is NO_SURPLUS_EVEN_BEFORE_FEES.
    - 26SEP23 at sizes 10 and 100: NOT_EVALUATED. The walk crosses fractional-size levels, and no
      fractional-fill fee rule is modelled.
    - 26SEP22: NOT_EVALUATED at every size. One bracket (B67.5) had no ask at all.
  - **Reading.** No surplus: a valid, expected result. It is not a verdict on the family (2 event
    days, one capture each).
- 2026-09-25 06:21Z: **first production payoff scan**
  (`results/payoff_scan_production_edge-backup-5q41yg5u.json`, evidence-use event
  `eu-20c877aea7e2500aa5037daee75a8cd8`, code `5e8b07f`).
  - **Input.** A verified copy of the production evidence DB from the post-install backup
    `edge-backup-5q41yg5u` (taken 2026-09-25 06:19Z). Schema v7, sha256 `5ad68c03…c997552a`,
    equal to the backup manifest's `database_sha256` and recomputed locally. The manifest and
    backup id are in `results/payoff_scan_production_edge-backup-5q41yg5u.source.json`. The copy
    was scanned locally with SQLite `mode=ro`; there was no production host access.
  - **Scope.** Every stored KXHIGHNY event day: 2026-09-24 and 2026-09-25, 2 events of 6 brackets
    each. The store holds 48 order books, max snapshot id 78, latest receipt 05:00:05Z. No holdout
    is declared, so the window overlaps none.
  - **Parameters.** Quote age 300 s, leg skew 60 s and sizes 1, 10 and 100, the same as the laptop
    run and stated for this run only.
  - **Point-in-time sets.** The scan evaluated 38; all 38 are INCOMPLETE. VOID, REFUND and
    CANCELLATION are not excluded, and integer settlement is only an observed premise.
    - **30 are INVALID.** Each is anchored partway through a capture round, so it mixes books from
      two rounds. Its legs are stale (older than 300 s) and do not overlap within 60 s, so it is
      not evaluated.
    - **8 are VALID:** one per complete capture round, each with a skew of about 3 s. Across their
      24 size rows the result is 13 NO_SURPLUS_EVEN_BEFORE_FEES and 11 NOT_EVALUATED. In every
      evaluated row the worst state is the discretionary fair-price fallback, which pays 0.

    | Event | Round (UTC) | Asks sum - 1 (pre-fee, top of book) | Size 1 | Size 10 | Size 100 |
    |---|---|---|---|---|---|
    | 26SEP24 | 09-23 21:55 (decision) | +0.06 | no surplus (cost 1.14) | no surplus (11.14) | not evaluated: fractional level |
    | 26SEP24 | 09-23 22:05 (recheck) | +0.06 | no surplus (1.14) | no surplus (11.14) | no surplus (112.50) |
    | 26SEP24 | 09-25 04:50 (pre-close) | n/a | not evaluated | not evaluated | not evaluated |
    | 26SEP24 | 09-25 04:59 (close) | n/a | not evaluated | not evaluated | not evaluated |
    | 26SEP25 | 09-24 21:55 (decision) | +0.09 | no surplus (1.17) | no surplus (11.45) | not evaluated: fractional level |
    | 26SEP25 | 09-24 22:05 (recheck) | +0.07 | no surplus (1.15) | no surplus (11.24) | not evaluated: fractional level |
    | 26SEP25 | 09-24 23:05 (+1 h) | +0.06 | no surplus (1.14) | no surplus (11.24) | not evaluated: fractional level |
    | 26SEP25 | 09-25 04:05 (+6 h) | +0.07 | no surplus (1.15) | no surplus (11.21) | not evaluated: fractional level |

    - In the two 26SEP24 near-close rounds (04:50 and 04:59Z), bracket B66.5 had no ask at all
      (INSUFFICIENT_DEPTH, 0 offered), so no size could be evaluated.
    - "Not evaluated: fractional level" means the depth walk crossed a fractional-size Kalshi
      level, and no fee rule for fractional fills is modelled.
  - **Reading.** In every complete round the top-of-book asks cost 1.06 to 1.09 per $1 basket
    before fees, so there is no surplus even before fees or the fallback state. This is a valid
    no-surplus result over 2 event days and 8 rounds. It is not a verdict on the family.
