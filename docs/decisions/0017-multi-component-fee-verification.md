# 0017 — Multi-component, point-in-time fee verification with a claim basis

Status: Accepted (2026-09-23, integration directive, `docs/owner/2026-09-23-integration-production-directive.md`)

**Problem.** The owner supplied Kalshi's official fee-schedule PDF, effective 2026-07-07. It
verifies some fee assumptions but not all of them:
- The coefficient is verified.
- KXHIGHNY's general-schedule multiplier is verified.
- The rounding mechanics are verified.
- The account type is only owner-attested.
- Multi-fill rebates are not modelled.

One `VERIFIED` boolean would either overstate this, making claims look exact, or understate
it, throwing away verified evidence. Three more constraints apply:
- The shadow accounts pin `fee_schedule_id` when they are opened.
- Ledger entries are hash-chained, and re-runs must be idempotent.
- The EXP-001 cost model (`fees.py`) is hash-frozen.

**Alternatives.**
- (a) Flip `kalshi-quadratic-taker-v1` to VERIFIED. That misreports the account-type and
  rebate uncertainty.
- (b) Add a new, verified schedule id and switch the shadow accounts to it. The math is
  identical, and it breaks `ensure_account` idempotency: an `account_opened` payload with a
  different schedule id raises `LedgerConflict`.
- (c) Keep the schedule and its math. Add dated `FeeVerificationRecord`s beside it,
  component by component, and evaluate them **point in time**.

**Decision.** (c).
- **Components.** COEFFICIENT, SERIES_MULTIPLIER, SCHEDULED_CHANGES,
  ROUNDING_FOR_ACCOUNT_TYPE, ACCOUNT_TYPE and MAKER_FEES. Each is VERIFIED, OWNER_ATTESTED,
  UNVERIFIED or NOT_APPLICABLE, and each cites its evidence.
- **Claim basis.** A schedule declares its `cost_model` relative to the real venue debit.
  - **NONE**: a core component (coefficient, multiplier, scheduled changes, rounding) is
    not verified. No net claim is possible.
  - **CONSERVATIVE_BOUND**: the core components are verified, for a **direct** member (owner-attested
    or verified). The frozen cost bounds a single fill. An order split into several fills (the minimum
    granularity is 0.01 contracts) is proven to cost less than the frozen cost plus **0.0101 USD per
    contract**. So a claim uses net minus that allowance (`claim_adjusted_net`), which is a lower
    bound. This follows the owner's decision of 2026-09-23. The first review of the PR found that
    the plain frozen cost is *not* an upper bound for split orders.
  - A **non-direct** account gets NONE: each fill can add up to 0.01 USD, and an FCM may add its
    own fees.
  - **EXACT**: every component is verified, including the account type, and the cost model
    is exact.
- **Point in time.** A record counts for a decision only when both its
  `knowledge_time_utc` and its `applies_from_utc` are at or before the decision's
  `as_of`. So:
  - earlier ledger entries rebuild byte-identically (a golden digest test guards this);
  - a fill's fee fields travel to its settlement unchanged.
- **Current view vs recorded basis.** The dashboard and receipt show the record known now and
  label it "current view". Each decision keeps the basis recorded with it. Withdrawal checks use
  the weakest recorded basis. `restated_verification` exists for labelled restatements later; it
  never writes to the ledger.
- **Unsupported fees** (another venue, or a non-standard Kalshi series) reject an opportunity with
  `FEE_UNSUPPORTED` under every policy. No cost means no edge.
- **Staleness.** A record carries `recheck_by_utc` (30 days). After it, the "no scheduled
  change" check is stale and the claim basis falls to NONE until a new record lands.
  Stale is not current.
- **Venue isolation.** `schedule_for(venue, scope)` returns Kalshi's general schedule only
  for Kalshi series that are not on the PDF's non-standard list. Every other venue is
  UNSUPPORTED until its own evidence is captured.
- **The exact debit** (`kalshi_exact_taker_buy`) is kept apart from the conservative
  simulation cost. It covers a single fill for direct or non-direct members and is used
  for reporting only.

**Tradeoffs.**
- A claim needs the component vocabulary and the allowance, not just a boolean.
- Someone must re-check scheduled changes monthly, or claims lapse. This is intended.
- The 0.0101 USD per-contract allowance is loose: the real excess is usually far smaller. It is
  what can be proven from the documented granularity.

**Reconsider when:**
- the account type is verified through a read-only account source;
- multi-fill rebates matter for a strategy;
- Kalshi publishes a machine-readable schedule with an effective date that could replace
  the manual record;
- another venue's fees are captured, which means adding its own records, never reusing
  these.
