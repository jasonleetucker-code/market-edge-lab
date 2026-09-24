# Polymarket US: fee and rules evidence (2026-09-24)

Scope: the owner directive of 2026-09-24, Phase 5
(`docs/owner/2026-09-24-brisket-health-and-next-phase-directive.md`). Only official
**Polymarket US** sources were used: `docs.polymarket.us` and the exchange's regulatory site
`polymarketexchange.com`. Polymarket International documentation (`docs.polymarket.com`) was
not used. Code: `fee_schedules.POLYMARKET_US_TAKER_V1`,
`fee_schedules.POLYMARKET_US_VERIFICATION_2026_09_24`, `polymarket_us.payoff_kind` and
`polymarket_us.fee_scope`. Decision: ADR 0027.

## How the pages were read

- Plain `curl` GETs from the laptop. The User-Agent was
  `market-edge-lab/0.1 (read-only research; fee evidence)`. No credentials or cookies were sent.
  All pages are public documentation.
- Documentation pages were fetched as the site's Markdown export: `<page URL>.md`, the form that
  `https://docs.polymarket.us/llms.txt` lists.
- The SHA-256 is of the exact bytes received. Page copies are **not** committed, because they
  are the venue's copyrighted text. A later fetch with a different hash means the page changed.
- Excerpts are quoted minimally (fewer than 15 words each). Retrieved text is data. Nothing in
  it was treated as an instruction.

| # | URL (as fetched) | Accessed (UTC) | Bytes | SHA-256 |
|---|---|---|---|---|
| 1 | https://docs.polymarket.us/llms.txt | 2026-09-24T01:33:44Z | 49954 | `4c541f6258fc3149a3837af35ca474d464692ab86523fa50fa4ed0aefe457ad0` |
| 2 | https://docs.polymarket.us/fees.md | 2026-09-24T01:33:51Z | 13537 | `24fcb758e11d6c1d8bd412dd12e5afd1725d390ffb52233786963c7d64cb564e` |
| 3 | https://docs.polymarket.us/learn/advanced/rule-structure.md | 2026-09-24T01:33:52Z | 2189 | `6f993d4b893de1dd351ca4eac3413123364ca5a3b47c2013a9eea37227f727f4` |
| 4 | https://docs.polymarket.us/learn/markets/contract-settlement.md | 2026-09-24T01:33:53Z | 1147 | `731230ebe68ce71051c4256e772a79099f5f6005d640723aab95b116eab79af0` |
| 5 | https://docs.polymarket.us/learn/markets/market-resolution.md | 2026-09-24T01:33:54Z | 2950 | `5fd91d4e678c808ff6207e638980a370cc9b9e2f1dbde0ac964fde0fccea978b` |
| 6 | https://docs.polymarket.us/learn/markets/clarifications.md | 2026-09-24T01:33:56Z | 2986 | `8528d0cadfb4221bf163e8c86244a3a364ec0e4fc111c07254c28612ded0cd15` |
| 7 | https://docs.polymarket.us/learn/trading/basics/buying-yes-vs-selling-no.md | 2026-09-24T01:33:57Z | 1987 | `f5e925c7ff6bbfae4109f80c4b3fe05e63334a8256c5eb412a0f4d9eec8b82fd` |
| 8 | https://docs.polymarket.us/market-structure/collateral-and-margin.md | 2026-09-24T01:35:06Z | 10324 | `d633b417bec47e6feab717302aa460a270d99c4982fdb38ca7ee1ec572d9326a` |
| 9 | https://docs.polymarket.us/faqs/sports-faqs.md | 2026-09-24T01:35:07Z | 18606 | `b3e1ccb06ead7fd3d9ee663ecf6086d9134378a94b60f595d4d7090b04718f3c` |
| 10 | https://docs.polymarket.us/faqs/weather-faqs.md | 2026-09-24T01:35:09Z | 2705 | `e7a85e6ebb771d85b19d551a9caebb011f1e693282b5673d170336b79f04642c` |
| 11 | https://docs.polymarket.us/faqs/general-faqs.md | 2026-09-24T01:35:10Z | 3079 | `ea8a918280614780eeca9f9da1ac0eedd7f7f6a78d1323cf0f35a13a170339a8` |
| 12 | https://docs.polymarket.us/learn/trading/basics/fractional-shares.md | 2026-09-24T01:35:12Z | 1275 | `2bd4d4c9e6649767ea0caf3e60db18f96cda52057e6810ab024b89cfec3ee017` |
| 13 | https://docs.polymarket.us/changelog.md | 2026-09-24T01:35:13Z | 116626 | `070eb6b857bb1af8fc1602b9d9d97e5e45fe45144d7868f4c856b6f6429d9ec6` |
| 14 | https://docs.polymarket.us/api-reference/markets/get-market-by-slug.md | 2026-09-24T01:35:15Z | 25307 | `c1c83c0b276b956c821b4551ba78000d12f9865f55104f3d99f79f090b4f1648` |
| 15 | https://polymarketexchange.com/regulatory.html | 2026-09-24T01:36:09Z | 6618 | `957a87b8a72debc6dfbfee26277c5870090cfcfcabd8a495ac3add95c69c0257` |
| 16 | https://polymarketexchange.com/files/legal/latest/rulebook (redirected to `.../files/legal/Polymarket%20US%20Rulebook%20(2026.09.14).pdf`; `application/pdf`, 84 pages) | 2026-09-24T01:36:16Z | 789996 | `e7b7793e75dd61a8adaf807c588e1212cf0600100e5727d7d546ba0a0b7f35e5` |
| 17 | https://docs.polymarket.us/partners/funding/vendor-fees.md | 2026-09-24T01:39:45Z | 8591 | `5ee5063318cf5c5ad4991fa1c0a52430a03d91df2981021e5bcc96f83c18eae8` |

Every component was in hand at the last capture, 2026-09-24T01:39:45Z. That time is the
record's `knowledge_time_utc`.

## Trading fees (source 2, unless stated)

| Component | Excerpt | What it establishes | State |
|---|---|---|---|
| Effective date, scope | "Effective exchange-wide from 12 AM ET, Thursday September 17, 2026." | One exchange-wide schedule, in effect from 2026-09-17T04:00Z. This is `applies_from_utc`. | VERIFIED |
| Formula | "Fee = Θ × C × p × (1 - p)" | Quadratic in price. C is contracts; p is "the trade price ($0.01 to $0.99)". | VERIFIED |
| Taker coefficient | table: Taker Fee, Theta `0.0695` | Θ = 0.0695 for takers. | VERIFIED (COEFFICIENT) |
| Maker | table: Maker Rebate, Theta `-0.0125`; "Maker rebate is applied at the point of trade." | Makers receive a rebate. The simulation is taker-only. | VERIFIED (MAKER_FEES) |
| Fee rounding | "rounded to the nearest $0.01 using banker's rounding (round half to even)" | The **fee**: per fill, to the cent, half to even. | documented |
| Debit (notional) rounding | nothing found; Rulebook 10.1(c): minimum increment "$0.001 per Contract" | How price × contracts is rounded when the cash moves is not documented. | **UNVERIFIED** (ROUNDING_FOR_ACCOUNT_TYPE) |
| Multi-fill cap | "never exceeds the banker's rounding of the cumulative exact fee" | An order's total fee is at most banker's(Σ exact fees). | VERIFIED |
| Cap direction | "The adjustment can only reduce a fill's charge, never increase it." | Fills never cost more than their own rounded fee. | VERIFIED |
| Cancel / expire | "Fees are only charged when a trade executes." | No fee on cancelled, expired or rejected orders. | VERIFIED |
| Volume rebates | Taker rebates of 10/25/50% on the prior month's taker volume from $250,000 | They can only lower cost. Not modelled. | not modelled |
| Worked examples | Examples 1 to 5 (1,000 lots) and the 99-row 100-lot table | Reproduced exactly by `fee_schedules.bankers_fee` (tests). | VERIFIED |
| Per-market coefficient | source 14: `feeCoefficient` is described only as "Fee coefficient" (nullable) | The field exists per market, but its relation to the schedule is undocumented. Every captured market shows 0.0695. | gated: the schedule prices a market only when its field equals 0.0695 (`polymarket_us.fee_scope`) |
| Scheduled changes | source 16, Rule 3.8(a): "The Company may post an updated fee schedule on its website" | Fees can change by posting, with deemed notice. No forward schedule and no fee-change feed exist, and the changelog (source 13) has no fee entries. | **UNVERIFIED** |
| Account type | source 17: vendor fees are declared per order by partner intermediaries | A route through an intermediary can add fees. No Polymarket US account exists here. | **UNVERIFIED** |
| Settlement, deposit and withdrawal fees | Sources 4 and 5 describe settlement and name no settlement fee; Rule 3.8(a) gives the exchange "sole authority to impose other fees" | Absence of mention is not evidence of zero. | **UNSUPPORTED (not established)**: the SETTLEMENT_AND_TRANSFER_FEES component, UNVERIFIED |

**Result.** The taker fee formula, coefficient and fee rounding are established, so
`POLYMARKET_US_TAKER_V1` exists. It prices research routes as a **conservative estimate**:
- each take's fee is rounded **up** to the cent;
- each take's debit (price × contracts + fee) is also rounded up to the cent, because
  notional rounding is undocumented.

What the bound covers:
- **The fee.** Ceiling ≥ banker's rounding, and a sum of ceilings ≥ the ceiling of the sum.
  So the fee bound holds for any split of an order into fills.
- **The cash debit.** The fee bound does **not** cover it. The notional's rounding is
  undocumented, ticks are $0.001, and an order can run as several fills or orders. The
  per-take ceiling bounds a single fill only. So the record carries a rounding allowance
  of **$0.01 per contract**: up to one cent per fill, with whole-contract fills. Fractional
  fills are not covered and are never priced.

Several components are unverified: SCHEDULED_CHANGES, ROUNDING_FOR_ACCOUNT_TYPE (the debit),
ACCOUNT_TYPE and SETTLEMENT_AND_TRANSFER_FEES. So the ADR 0017 claim basis is **NONE**, and
each of these blocks any upgrade:
- `verification_at` reports PARTIALLY_VERIFIED, and the fee is never claimable;
- the comparator reports the fee as UNVERIFIED (a published-schedule estimate).

The record lapses at `recheck_by_utc` 2026-10-24T01:39:45Z.

## Payout, cancellation and void semantics

| Topic | Source and excerpt | What it establishes |
|---|---|---|
| Standard payout | 4: "Winning contracts settle at $1.00" (losing at $0.00) | Binary, $1 per contract. |
| Alternative settlement | 4: "Polymarket Clearing follows the instructions in the market's Settlement Description." | A market's own terms can override $1/$0. |
| 50-50 language | 3: "canceled entirely with no make-up game, this market will settle 50-50" | Split settlement is a documented rule pattern. All five captured NFL markets (`tests/fixtures/polymarket_us/markets_limit5_…json`) carry it. |
| Sports cancellation | 9: "the Contract settles at last fair market prices" (cancelled, no-contest, postponed past expiry) | The settlement value is **not a fixed number**: it is a price at announcement time. |
| Sports ties | 9: "the Contract settles at $0.50" (winner markets without a tie outcome) | A split payout. |
| Co-winners | 9: "$1.00 divided by the number of winners, rounded down to the nearest tick" | A fractional payout. |
| Weather | 10: settlement from the NWS CLI (KNYC for New York) at "8:00 AM ET on the day following"; no data within a week settles at last fair market prices | A last-fair-market-price fallback exists here too. This is a rule-equivalence dimension for any Kalshi KXHIGHNY comparison. |
| Emergency void | 16, Rule 2.8(d)(iii): "cancellation of a Contract and return of any funds paid to enter Trades" | The exchange can void a contract and refund entry funds. |
| Contract modification | 16, Rule 10.3: may modify "Settlement Date and Payout Condition"; may adjust expiration on event cancellation | Terms can change after entry. |
| Clarifications | 6: "Polymarket US may cancel resting orders when a clarification is posted" | Resting orders can disappear. |
| NO side | 7 and 8: one instrument per market; NO is a short sale of YES with "$1.00 margin per contract" | A NO buy at q is a YES sale at 1 − q, and buying power falls by q. The fee is the same by symmetry. |
| Fractional contracts | 12: "Polymarket US does not support fractional contracts." Rulebook 10.1(a): "Contracts may be traded in fractional units." Changelog v0.0.43: partial-contract markets from 2026-06-11 | The sources conflict. A fractional take is never priced (`price_depth_fill`). |
| Tick | Rulebook 10.1(c): minimum increment "$0.001 per Contract unless otherwise specified" | This is consistent with `orderPriceMinTickSize`, which the adapter reads per market. |

**Result (Phase 5A, option B: "represent then refuse").**
- A market (sports or not) whose rules text names a last-fair-market-price settlement gets
  `binary_alternative_settlement`.
- A market whose rules text states a 50-50, $0.50 or $0.5 settlement gets the payoff kind
  `binary_split_on_cancel`.
- A sports market with neither gets `binary_alternative_settlement`, per the
  last-fair-market-price, tie and co-winner rules above.
- Both keep `amount=1`, and neither is shoehorned into `binary`.
- `opportunity.evaluate` rejects both (PAYOFF_UNSUPPORTED), and so does
  `best_price.compare`: the route is never walked or priced.
- Kalshi markets are unchanged (`kalshi_quotes` still builds `binary`).
- The weather last-fair-market-price fallback is refused as above when it appears in the
  market's own rules text. When it appears only in the FAQ, it is part of the rules
  comparison, which is not established (`rules_resolved=False`).

## Not established (stays UNSUPPORTED or unknown)

- Settlement fees, deposit and withdrawal fees, and any fee for an intermediary route.
- The rounding of the cash debit (notional), and fee or debit rounding for fractional fills.
- Any Polymarket US fee schedule before 2026-09-17: `schedule_for(..., as_of=)` is
  UNSUPPORTED before that date.
- Whether a scheduled fee change is pending.
- What the per-market `feeCoefficient` means when it differs from 0.0695.
- Fee rounding for fractional-contract fills.
- Payout timing and any post-settlement cash hold. The starter policy therefore fails closed
  for Polymarket US: the release time is UNKNOWN.
- The Participant Agreement, which was not read.
