# 0018 — `STARTER_MAX_7D_V1`: a prospective, operational capital-release policy

Status: Accepted (2026-09-23, integration directive, `docs/owner/2026-09-23-integration-production-directive.md`; issue #32)

**Problem.** During the starter phase the owner wants money to be reusable for trading on
the same venue within one week of committing it. Several clocks look alike and can be
confused:
- the event ending;
- the market closing;
- the outcome being determined;
- cash becoming tradable;
- cash becoming withdrawable;
- cash reaching the bank.

The frozen EXP-001 research record must not change to comply retroactively. Kalshi's
KXHIGHNY contract also has a contractual latest expiry about 184 hours after our decision.
It applies only when the published data has a material error, and using it would make the
whole weather research domain ineligible.

**Alternatives.**
- (a) A dashboard filter only. It is easy to bypass, and it cannot reach tickets or risk.
- (b) A new rejection reason inside the Gate 5 engine. That would change the frozen Stage B
  qualification.
- (c) A separate, versioned eligibility policy. Research qualification is unchanged. The
  operational shadow account enforces the policy before a fill, and the risk report, the
  dashboard and the execution-ticket contract read it.

**Decision.** (c).
- **Governing clock.** Only `tradable_cash_release_eta` governs. Eligibility holds when it is
  no later than commitment + 168 elapsed hours. Time is converted to UTC first, so DST
  cannot shift it; a test shows the wall-clock trap.
- **Normal-path estimate.** The estimate is the venue's `expected_expiration_time`, plus
  `settlement_timer_seconds`, plus an evidence buffer, plus the venue's documented
  post-settlement trading hold.
  - The buffer is ceil(2 × the worst observed lag of `settlement_ts` after the normal-path
    time). For KXHIGHNY that is 49 h: 698 events, maximum +24.17 h, derived reproducibly
    from the Gate 3 market capture.
  - Kalshi's hold is 0 as `DOCUMENTED_INFERRED`. The docs say positions are resolved and
    "funds transferred" at settlement. That the funds can fund a new trade at once is an
    inference, and every verdict shows it.
- **Owner decision (2026-09-23).** The contractual latest expiry is reported as
  `abnormal_path_bound` and never governs.
- **Withdrawal and bank clocks** are reported only. If they are unknown they stay None.
- **Fail closed.** Each of these makes a position ineligible with a machine-readable reason:
  - unknown timing: TRADABLE_CASH_RELEASE_UNKNOWN;
  - missing series-lag or venue-cash evidence: SETTLEMENT_TIMING_UNVERIFIED;
  - a disputed, amended, non-open or rescheduled market, or one already past its venue-stated
    expected resolution: DELAYED_OR_DISPUTED. The Kalshi adapter cannot detect a reschedule
    directly; the past-expected check catches a market that has run late;
  - a post-settlement hold that pushes the release past 168 h: POST_SETTLEMENT_HOLD;
  - a hoped-for early sale: EXIT_DEPENDS_ON_LIQUIDITY. It never helps eligibility.
- **Enforcement (owner decision).** The operational shadow account enforces the policy from
  `EFFECTIVE_FROM_UTC` (2026-09-24T00:00Z) as NO_FILL `STARTER_POLICY_INELIGIBLE`, before
  the risk veto. Enforcement is prospective. The research account is never touched.
  Decisions and fills carry the verdict, with its evidence provenance.
  `expected_settlement_utc` keeps its existing meaning for both accounts.
- **Exceptions.** An open starter position past its expected release is a
  `SEVEN_DAY_POLICY_EXCEPTION`. Its capital stays reserved, nothing is sold, and it is
  surfaced in the risk view, the overview and the notifications.
- **Long-duration markets** stay visible for research. They become eligible only when the
  remaining conservative time fits.

**Tradeoffs.**
- The buffer is an empirical bound, not a guarantee. A rare delay beyond it becomes an
  exception, not a silent breach.
- Kalshi's cash timing comes from documentation, not from an account read, which is not
  authorized.
- Fills recorded by older code after the effective date carry no verdict. They are counted
  as `unchecked_filled_after_effective`, not re-evaluated.

**Reconsider when:**
- the owner changes the horizon or the clock;
- a venue documents a trading hold;
- a series' observed lag changes materially, which means re-deriving the evidence;
- real (not shadow) starter capital is authorized, when account-level holds must be read.
