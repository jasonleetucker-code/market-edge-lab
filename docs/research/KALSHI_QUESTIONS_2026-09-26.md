# Questions to Kalshi (venue-fact verification), 2026-09-26

**Status: FINAL DRAFT, NOT SENT.** On 2026-09-26 the owner approved sending the 8 questions drafted
in `docs/research/RESEARCH_UNBLOCKING_DECISIONS.md` §B, on condition that the owner sees and
confirms the exact final message first
(`docs/owner/2026-09-26-owner-decisions-economics-backup.md`, item 2).

The questions are shared venue-fact verification:
- Q1 and Q3–Q6 serve EXP-003 (paused).
- Q2, Q5, Q6 and Q7 also serve EXP-002's fee and fallback correctness.

The owner's account identity is not included here. Kalshi support may need it, and the owner adds
it when sending.

---

**Subject:** Questions on settlement fallbacks, cancellations, settlement precision and fees (KXHIGHNY, KXNFLGAME)

Hello Kalshi team,

I am doing research on Kalshi's contract rules and fee schedule. I would appreciate written answers
to the questions below, or pointers to the governing documents. Where a question is answered by a
document, citing it (with version and date) is ideal.

**1. Fallback consistency across mutually exclusive markets.** For a series whose event markets
are mutually exclusive (for example KXHIGHNY-26SEP25, whose brackets have
`mutually_exclusive: true`), the rules say that with missing data all strikes resolve to "the last
fair price" determined at the Exchange's sole discretion. Are the fair prices assigned across all
markets of one such event constrained to sum to $1.00? If not, what constraint, if any, applies?

**2. NO-side payout at a non-binary value.** When a binary market resolves to a value v other than
$0 or $1 (a fair price, a last traded price or an Outcome Review Committee allocation), is a NO
(short) position always paid $1.00 − v per contract? Is v restricted to the market's price grid, or
can it be sub-cent?

**3. Cancellation refunds.** Rulebook v1.29 Rule 2.8 allows an emergency action that cancels a
contract and returns the funds paid to enter trades. In that case, are trading fees and rounding
fees returned together with contract prices? Are there other paths (for example Rule 6.3(c) or
Rule 7.1) by which a contract is voided with funds returned rather than settled at a value?

**4. Settlement precision (KXHIGHNY).** For KXHIGHNY under The Weather Company source, is the
expiration value guaranteed to be a whole degree Fahrenheit? If a fractional value is reported (for
example 81.5), how do the inclusive "between" brackets (for example 80–81 and 82–83) resolve?

**5. Fees on fractional fills.** For a taker order that fills fractional quantities (0.01
contracts) against several resting orders, is each fill's fee exactly the Fee Rounding
documentation's per-fill trade fee plus rounding fee minus accumulator rebate? Is there any
per-fill minimum?

**6. Settlement cost.** Is any settlement fee charged beyond balance-precision rounding
(MiscFeeAmt) when a binary market settles at $0/$1, at $0.50 (a two-team tie) or at a fair price?

**7. KXNFLGAME fees.** The fee schedule of July 7, 2026 lists KXNFLGAME under "Non-Standard Fees"
with maker multiplier 1 and taker multiplier 1, and the API reports `fee_type`
`quadratic_with_maker_fees`. For this series, is the taker fee exactly
`round up(0.07 × C × P × (1 − P))` and the maker fee `round up(0.0175 × C × P × (1 − P))`, subject
only to event-level overrides returned by the event fee-changes endpoint?

**8. MECNET.** What does `collateral_return_type: MECNET` on a mutually exclusive event mean for a
member holding YES positions in several of its markets?

Thank you,
[owner's name / account email]

---

## Handling of the answer

- The answer is recorded here verbatim with its date and channel, and evaluated as venue evidence
  (explicit / documented / inference).
- **EXP-003** is re-evaluated on economics first. It resumes only if the answers materially change
  its usefulness. It is rejected if Q1 and Q4 are unresolved on 2026-11-15.
- **EXP-002** uses the Q2, Q5, Q6 and Q7 answers for its fee and fallback modelling (the
  `fee_schedules` KXNFLGAME verification record).
