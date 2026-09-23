# Kalshi fee verification for KXHIGHNY (2026-09-23)

This file reconciles the owner-supplied Kalshi fee-schedule PDF with the public API and the
Fee Rounding documentation. The machine-readable record is
`KALSHI_KXHIGHNY_VERIFICATION_2026_09_23` in `src/edge_lab/fee_schedules.py`, explained in
ADR 0017. Byte hashes and page references are in `MANIFEST.json`.

## Verdicts

| Component | State | Evidence |
|---|---|---|
| Coefficient 0.07 (general taker schedule) | **VERIFIED** | PDF p.2: `fees = round up(M x 0.07 x C x P x (1-P))`. Effective July 7, 2026. |
| KXHIGHNY uses the general schedule, taker multiplier 1 | **VERIFIED** (from 2026-07-07) | PDF pp.6–11: KXHIGHNY is not in "Non-Standard Fees". The API `fee_type` is `quadratic` and `fee_multiplier` is `1`; the series was last updated 2026-09-17. |
| Scheduled fee changes | **VERIFIED as of 2026-09-23T13:17:48Z** | `/series/fee_changes?series_ticker=KXHIGHNY&show_historical=true` returns `[]`. The PDF points to kalshi.com/fee-schedule for upcoming changes. That page is behind a bot checkpoint, so the API is the machine-readable source. Re-check by 2026-10-23. |
| Rounding for the account type | **VERIFIED** (documented mechanics) | PDF p.2: "fee + positionCost is rounded to a centicent". Fee Rounding docs: trade fee rounded up to $0.000001; balances aligned to $0.0001 for direct members and $0.01 for non-direct; the rounding fee is rebated per order. |
| Account type | **OWNER_ATTESTED**: direct member | The owner's answer (directive record). It has not been checked through an account read, and none is authorized. |
| Maker fees | **VERIFIED**: 0 for KXHIGHNY | PDF p.2: the maker multiplier defaults to 0. KXHIGHNY is not listed with a maker multiplier. The simulation is taker-only in any case. |
| **Full schedule verified** | **NO** | The account type is only owner-attested, and multi-fill rebates are not modelled. |
| **Claim basis** | **CONSERVATIVE_BOUND** | See below. EXACT is not claimable. |

## Reconciliations

The directive asked for each of these to be reconciled.

- **Model fee vs trade fee precision.**
  - The model fee is `M·0.07·C·P·(1−P)`, unrounded.
  - The trade fee is that value rounded **up** to $0.000001 (docs).
  - The PDF's "round up" describes the resulting cash debit, which is the next point.
- **"Centicent" (PDF) vs balance precision (docs).**
  - A centicent is $0.0001, which is the direct-member balance precision.
  - The PDF's rule that fee + positionCost is rounded up to a centicent is the same thing as the docs' "aligned change = floor(revenue − trade fee) to $0.0001" for a direct member.
  - Non-direct members are aligned to $0.01 instead, and Kalshi rebates the difference over the order's fills.
- **The displayed fee table (pp.4–5).** The table shows the model fee rounded **up to the cent**:
  - 1 contract at $0.01 displays $0.01, while the model fee is $0.000693;
  - 100 contracts at $0.05 display $0.34, while the model fee is $0.3325;
  - 100 contracts at $0.50 display $1.75, which is exact.

  The table is a display convention. It is not the direct-member debit, which is kept to a centicent. Every row is regression-tested in `tests/test_fee_verification.py`.
- **Direct vs non-direct accounting.** For one fill that is the first fill of its order:
  - The direct-member debit is `ceil_$0.0001(P·C + trade fee)`. With C=1 and P=0.055 that is **$0.0587**.
  - The non-direct debit is `ceil_$0.01(...)`, which is **$0.06** for the same trade. That is the frozen EXP-001 model (`fees.py`).
  - The first fill of an order earns no rebate, because a single rounding fee is below one precision unit.
- **Rebates and rounding refunds.**
  - Rebates pay back the accumulated rounding overpayment of one order, in whole precision units. They can only lower the cost.
  - The frozen model ignores them, so it over-states cost.
  - Multi-fill orders are not modelled exactly.

## What the verdict means

These three quantities stay separate:

1. **Exact venue trade fee:** `trade_fee` (rounded up to $0.000001).
2. **Cash-account debit from balance precision:** `kalshi_exact_taker_buy(..., account_type="direct")`. It is used for reporting only and never writes to the ledger.
3. **Conservative simulation assumption:** the frozen EXP-001 cost, `fees.taker_buy_cost`, which floors to the cent with no rebate. `tests/test_fee_verification.py` proves `C·P ≤ exact direct debit ≤ exact non-direct debit ≤ frozen cost < exact direct debit + $0.01` on a grid of prices and quantities.

**Claim basis CONSERVATIVE_BOUND.** The coefficient, series multiplier, scheduled-change check and rounding mechanics are verified, and the frozen cost is an upper bound on the debit for either account type. So a positive net result computed with it is a **lower bound** on the real result. It is never an exact figure.

EXACT needs all of these:
- the account type verified;
- multi-fill rebates modelled;
- an exact cost model priced into the ledger.

## Point in time

- Decisions made before 2026-09-23T13:18:03Z keep `UNVERIFIED_CURRENT_SCHEDULE` and `claimable = false`, because that is what was known then.
- Later decisions carry `PARTIALLY_VERIFIED` and `claim_basis = CONSERVATIVE_BOUND`.
- Reports may *restate* earlier trades from on or after 2026-07-07 under this record (`restated_verification`), labelled as a restatement. The ledger is never rewritten.
- After 2026-10-23T13:18:03Z the record no longer supports claims until a new dated record replaces it.

## Frozen EXP-001

None of these changed:
- `fees.py` (hash-pinned);
- the preregistration;
- the `[costs] fee_model` text;
- the schedule id `kalshi-quadratic-taker-v1`;
- the cost math.

This record adds evidence beside them. It does not alter a frozen research assumption.
