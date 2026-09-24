# 0027 — One best-price-for-size comparator, an honest claim ladder, Polymarket US fees, split-cancel refusal

Status: Accepted (2026-09-24, owner directive Phases 4, 5 and 5A,
`docs/owner/2026-09-24-brisket-health-and-next-phase-directive.md`; issue #30)

**Problem.**
- Issue #30 asks for the best attainable price for a position across venues. A naive
  "cheapest price" would:
  - compare a top-of-book quote with a fill for a size;
  - compare a Kalshi total that includes fees with a Polymarket US price that has none;
  - compare markets that only look alike (same title, different settlement rules);
  - pass off a stale book as current.
- Polymarket US fees were UNSUPPORTED, so no total could be stated for that venue at all.
- Polymarket US markets can settle 50-50 or at a last fair market price. The engine only
  prices binary contracts paying $1 or $0.

**Alternatives.**
1. A best-price function per venue pair. Rejected: the directive and ADR 0019 allow one
   comparator over shared objects.
2. One ranking by "best effective price", with fees assumed zero or taken from another
   venue when unknown. Rejected: it turns missing into zero and mixes claim grades.
3. One comparator that produces four separate claims, each gated on its own evidence, with
   machine-readable reasons when a claim cannot be made. Chosen.

For split settlement (5A):
- A. Extend `Payoff` so a split or cancellation outcome is priced.
- B. Represent it as a distinct payoff kind and refuse it everywhere until a generic payoff
  engine exists. Chosen, because it is the smallest correct option: pricing a
  last-fair-market-price settlement needs a model of that price, which does not exist.

**Decision.**

- **`src/edge_lab/best_price.py`: one comparator.**
  - Input: a `PositionRequest` (reference event and market, side, quantity) and `Route`s
    (event, market, captured `DepthLadder`, fee schedule from `schedule_for`).
  - For each route it reports:
    - the depth walk: `walk_ladder(..., price_grid=market.price_grid)`. This is the grid
      check's first production caller, which ADR 0023 said was missing. An off-grid level
      makes the ladder INVALID_BOOK;
    - gross cost, average price and worst (limit) price;
    - fees from `price_depth_fill`;
    - fee status (below);
    - liquidity: FILLABLE, INSUFFICIENT_DEPTH, DEPTH_UNKNOWN (a truncated capture),
      INVALID_BOOK or BOOK_MISSING;
    - freshness, using the same rule as `evaluate`: a book after `as_of` is UNKNOWN;
    - equivalence;
    - account-route availability;
    - the capital-release ETA from `STARTER_MAX_7D_V1`, or UNKNOWN.
  - It never executes: `execution_authorized` is False on every output.
- **Fee status.**
  - VERIFIED: claim basis EXACT.
  - CONSERVATIVE_BOUND: the total plus the ADR 0017 allowance bounds the real debit.
  - UNVERIFIED: a documented schedule prices it, but no claim may rest on it; shown as an
    estimate.
  - UNSUPPORTED: no fee model, so the fee is unknown and never zero.
- **Four claims, gated in order.** Each claim is None with a reason when unsupported.
  - Every claim needs: a supported payoff, an open market, a valid book with an offer, and
    a **fresh** book. A route that fails only on freshness is named in the claim's
    `stale_candidates` and never ranked. A supported claim carries the winning route's
    `freshness`.
  - **BEST OBSERVED QUOTE** needs only that.
  - **BEST GROSS COST FOR SIZE** also needs a ladder that covers the quantity.
  - **BEST VERIFIED TOTAL COST** also needs a claim-grade fee (EXACT or CONSERVATIVE_BOUND,
    via `claim_adjusted_net`). Under CONSERVATIVE_BOUND a total is an upper bound, so the
    lowest total is the lowest *bound*, not a proven order (below).
  - **BEST ACCOUNT-FEASIBLE ROUTE** also needs:
    - a recorded account read (`venues`: account_read LIVE_DATA_VERIFIED; none today);
    - starter-policy eligibility.
  - When no route qualifies, the reason is the gate reached by the route that got furthest,
    for example NO_ACCOUNT_CONNECTED.
- **Equivalence.**
  - A route is REFERENCE (the requested contract), or MATCHED_EQUIVALENT via
    `discovery.is_equivalent`: the same settlement identity, resolved and hashed rules on
    both sides, and the same payoff and outcome.
  - Anything else is listed in `related` and never priced against the request. A title
    never counts.
  - REFERENCE needs every contract field of the request to match (venue, id, event, outcome,
    payoff, rules hash, settlement identity). A capture of the same market whose rules or
    payoff changed is RELATED. Two routes for one market id are refused (`ValueError`), so a
    market is never compared with another capture of itself.
  - Today every Polymarket US market has `rules_resolved=False`. So in real data it is
    always RELATED to a Kalshi request, and the tests build equivalent pairs explicitly.
- **Summary text.**
  - The summary is deterministic.
  - It says "A is cheaper than B" only when `proven_cheaper(A, B)` holds. Both need a
    verified total, and A's claim total (an upper bound on A's real cost) must be below
    either:
    - B's exact total (`total_cost`), when B's fee is VERIFIED (EXACT). Never B's claim
      total, which an EXACT record's nonzero allowance would inflate; or
    - B's gross cost, the lower bound on a taker's real cost. This floor assumes the real
      debit is at least price × quantity. That is proven for the Kalshi direct-member
      schedule only, and must be re-proven for any other venue before its records can
      reach CONSERVATIVE_BOUND.

    Two overlapping bounds prove nothing. They are printed as ranges with "No proven order"
    (for example "Kalshi between $4.00 and $4.2710"). Equal totals are "equal" only when
    both are exact. `Claim.proven_below` lists, machine-readably, the routes the winner is
    proven cheaper than.
  - Without verified totals on both sides it gives separate figures, for example
    "Kalshi … at most $X total (…)" and "Polymarket US … $Y gross, fees unverified
    (published-schedule estimate $F, not claim-grade)", or "fees unknown".
- **Polymarket US fees.** Evidence: `experiments/multi_venue/polymarket_us_fees_2026-09-24.md`.
  - `PolymarketUsTakerSchedule` / `POLYMARKET_US_TAKER_V1` is the published exchange-wide
    taker fee 0.0695·C·p·(1−p), effective 2026-09-17.
  - The venue rounds each fill's **fee** half to even and caps an order's total fee. The
    schedule instead rounds each take's fee **up** to the cent. That bounds the fee for any
    split into fills.
  - The **cash debit** is a different matter:
    - notional rounding is undocumented;
    - ticks are $0.001;
    - a quantity can execute as several fills or as separate orders, and each order's
      banker's-rounded fee can sit up to $0.005 above exact.

    The schedule rounds each take's debit up to the cent, which bounds a single fill of a
    single order only. So the record carries a rounding allowance of **$0.015 per contract**
    ($0.005 of fee rounding per order + $0.01 of notional rounding per fill). That covers
    several fills or orders of whole contracts, and is tested over random splits.

    Worked example: 100 contracts at 0.321 bought as 100 one-contract orders can cost
    $35.00. The single-take cost is $33.62, so the bound is $33.62 + $1.50 = $35.12. The
    earlier $0.01 allowance gave $34.62, which fell short. Fractional fills are never priced.
    ROUNDING_FOR_ACCOUNT_TYPE stays UNVERIFIED.
  - Below $0.01 and above $0.99 (outside the documented range), the fee is bounded by its
    value at the range edge.
  - `schedule_for("polymarket_us", scope)` returns it only for `POLYMARKET_US_EXCHANGE_SCOPE`.
    `polymarket_us.fee_scope` assigns that scope only when the market's own `feeCoefficient`
    equals 0.0695. Anything else is UNSUPPORTED. With `as_of` before 2026-09-17 00:00 ET it
    is UNSUPPORTED too, because no earlier Polymarket US schedule was captured.
  - A new component, `SETTLEMENT_AND_TRANSFER_FEES`, covers settlement, deposit and
    withdrawal fees. A record that states it without verifying it supports no claim.
    Records that predate it (Kalshi, 2026-09-23) do not state it and are unaffected: their
    ledger fields and claim basis are unchanged. The Kalshi record should add it at its
    next re-check, due 2026-10-23.
  - The dated record `POLYMARKET_US_VERIFICATION_2026_09_24`:
    - VERIFIED: coefficient, multiplier (scope-gated), maker fees;
    - UNVERIFIED:
      - scheduled changes (Rulebook Rule 3.8(a): changes by posting, with no forward
        schedule);
      - rounding (the debit's rounding is undocumented);
      - account type (no account; intermediaries can add vendor fees);
      - settlement and transfer fees (not documented; Rule 3.8 lets the exchange impose
        other fees);
    - so the claim basis is **NONE**. The schedule prices research routes, but no
      Polymarket US total is claim-grade. Every one of those components blocks an upgrade.
  - The schedule is not added to `FEE_SCHEDULES`. That registry is the set a shadow
    account may pin, it is Kalshi only, and the dashboard reads it.
- **Split settlement: represent, then refuse.** `polymarket_us.payoff_kind` assigns, in
  this order:
  - `binary_alternative_settlement` when the rules text of any market (sports or not) names
    a last-fair-market-price settlement ("last fair market price", "LFMP");
  - `binary_split_on_cancel` when the rules text states a split: "50-50", "50/50", "50 50",
    "fifty-fifty", "$0.50", "$0.5", "0.5(0) per", "50 cents", "fifty cents", or "half of
    the payout / value / settlement / $1" and "half a dollar";
  - `binary_alternative_settlement` for a sports market with neither (Sports FAQs:
    cancellation or no-contest settles at the last fair market price, a tie at $0.50,
    co-winners at $1/n);
  - `binary` otherwise.

  The amount stays 1. `evaluate` already rejects any kind other than `binary`
  (PAYOFF_UNSUPPORTED, ADR 0023), and the comparator refuses such a route before walking
  it: no price for it is ever quoted. Sizing needs no change: `suggest_position_size` is
  reached only through a qualifying opportunity, which `evaluate` refuses here. A request
  for such a payoff yields four absent claims (PAYOFF_UNSUPPORTED). Kalshi's adapter is
  untouched and EXP-001 is byte-for-byte unchanged:
  - `fees.py` and `evaluate` are not modified;
  - the Kalshi verification state is unchanged;
  - the existing tests pass.

**Tradeoffs.**
- The Polymarket US estimate can overstate the fee by up to 1 cent per take, plus 1 cent on
  the debit, and a claim would add $0.015 per contract on top. That is acceptable for an
  estimate that is never claim-grade today.
- Matching split or last-fair-market-price language is textual, so a false positive refuses
  a market that might be binary. That fails closed, by design.
- A weather market whose own rules text carries the Weather FAQ's last-fair-market-price
  fallback is refused as `binary_alternative_settlement`. Where the fallback appears only
  in the FAQ, the market stays `binary`, and the fallback is a rule-equivalence dimension
  (not established).
- The lowest verified total can be named "best" while its order against another verified
  route stays unproven. The claim's `proven_below` and the summary say which orders are
  proven.
- No route is account-feasible until an owner-approved account read exists (ADR 0019).
- `best_price` imports two private helpers (`opportunity._freshness`,
  `discovery._series_scope`) so that it does not fork the freshness and scope rules.

**Reconsider when:**
- Polymarket US publishes a forward fee schedule or fee-change feed, documents its debit
  rounding and its settlement and transfer fees. Only with all of these, plus a
  direct-account attestation, could its totals become CONSERVATIVE_BOUND;
- a market's `feeCoefficient` differs from the exchange theta;
- a generic payoff engine can price split or last-fair-market-price settlement (option A);
- rules equivalence is established for a real cross-venue pair;
- an account read is authorized.
