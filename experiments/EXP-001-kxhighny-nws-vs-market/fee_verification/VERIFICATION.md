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
| Fill granularity | **VERIFIED**: 0.01 contracts | Fixed-Point Representation docs (`docs_kalshi_fixed_point_…md`). Fills can be fractional even when the order is for whole contracts. |
| **Full schedule verified** | **NO** | The account type is only owner-attested, and multi-fill rebates are not modelled exactly. |
| **Claim basis** | **CONSERVATIVE_BOUND**, for a direct member, with a **0.0101 USD per-contract allowance** | See below. EXACT is not claimable. |

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
  - Rebates pay back the accumulated rounding overpayment of one order, in whole precision units.
  - They are **capped** so that a fill's net fee is never negative. So overpayment on small fills can stay unreturned.
- **Split orders.** An order can match several resting orders and fill in pieces. Each piece is rounded separately.
  - For a single fill, the frozen cost is at least the real debit for either account type.
  - For a split order it can be **slightly lower** than the real debit. The review of this PR found a direct-member case that is 0.0002 USD higher, and non-direct cases up to 0.02–0.03 USD higher. `tests/test_fee_verification.py` keeps one such case.
  - **Bound (direct member).** An order for C contracts fills in at most 100·C pieces, because the minimum granularity is 0.01 contracts. Each piece adds under 0.000001 USD of fee rounding and under 0.0001 USD of balance rounding, and rebates only lower the total. So the real debit is below `frozen + 0.0101·C`, for any price grid and even when the rebate cap binds.
  - **Non-direct members** have no useful bound: each piece can add up to 0.01 USD, and an FCM may add its own fees (PDF p.3). So the claim basis is NONE for a non-direct account.

## What the verdict means

These three quantities stay separate:

1. **Exact venue trade fee:** `trade_fee` (rounded up to $0.000001).
2. **Cash-account debit from balance precision:** `kalshi_exact_taker_buy(..., account_type="direct")`. It is used for reporting only and never writes to the ledger.
3. **Conservative simulation assumption:** the frozen EXP-001 cost, `fees.taker_buy_cost`, which floors to the cent with no rebate. For single fills, `tests/test_fee_verification.py` checks `C·P ≤ exact direct debit ≤ exact non-direct debit ≤ frozen cost < exact direct debit + 0.01 USD` over 5,000 random cases. Split orders need the allowance described above; tests cover random and worst-case splits.

**Claim basis CONSERVATIVE_BOUND** (direct member). All of these hold:
- the coefficient, the series multiplier, the scheduled-change check, the rounding mechanics and the fill granularity are verified;
- the account type is owner-attested as direct.

A claim uses the recorded net **minus 0.0101 USD per contract** (`claim_adjusted_net`). That figure is a lower bound on the real result. It is never an exact figure.

EXACT needs all of these:
- the account type verified;
- multi-fill rebates modelled;
- an exact cost model priced into the ledger.

## Point in time

- Decisions made before 2026-09-23T13:39:48Z keep `UNVERIFIED_CURRENT_SCHEDULE` and `claimable = false`, because that is what was known then. (13:39:48Z is when the last piece of evidence, the fill granularity, was captured.)
- Later decisions carry:
  - `PARTIALLY_VERIFIED`;
  - `claim_basis = CONSERVATIVE_BOUND`;
  - `claim_allowance_per_contract = 0.0101`.
- The dashboard and receipt show the **current view** (the record known now) next to the basis recorded with each decision.
- Withdrawal preconditions use the **weakest** basis recorded on the account's fills.
- A labelled restatement function (`restated_verification`) exists for later reports. Nothing in the ledger is restated or rewritten.
- After 2026-10-23T13:39:48Z the record no longer supports claims until a new dated record replaces it.

## Frozen EXP-001

None of these changed:
- `fees.py` (hash-pinned);
- the preregistration;
- the `[costs] fee_model` text;
- the schedule id `kalshi-quadratic-taker-v1`;
- the cost math.

This record adds evidence beside them. It does not alter a frozen research assumption.
