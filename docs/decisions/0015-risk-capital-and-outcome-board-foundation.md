# 0015 — Risk/capital and Outcome Board foundations are pure functions of the replayed ledger

Status: Accepted (2026-09-23). Issue #6 (P0 risk/capital foundation) and issue #3 (Outcome
Board backend). Authorized in `docs/owner/2026-09-22-overnight-build-directive.md`, on
condition that Gate 6 passes and the ledger and risk contracts are stable.

**Problem.** Before any real-money gate, the owner wants to know how much capital a shadow
account is using, what it could lose, when committed capital comes back, and how much could
ever be withdrawn safely. Each answer has to be deterministic and reproducible, and it must
never count hoped-for winnings as cash. The Outcome Board needs the same numbers grouped by
real-world outcome, not by contract.

**Alternatives.**
(a) Store risk figures next to the ledger and update them on each fill. That creates a
    second mutable truth, which drifts.
(b) Let a model or LLM summarize exposure. That breaks the rule that deterministic code owns
    balances, exposure and limits.
(c) Pure functions over `shadow_ledger.replay()` output, a versioned `RiskPolicy` and an
    `as_of` instant. **Chosen.**

**Decision.**
- **`edge_lab.risk.assess`.** The report covers:
  - equity, settled cash, committed capital, open worst-case risk and total exposure;
  - risk per position, per event and per cluster;
  - peak equity and drawdown (cost-basis equity moves only on settlement);
  - trailing daily and weekly realized loss;
  - the reserve floor and remaining risk capacity;
  - capital release by horizon (`available_now`, `within_1_hour`, `within_1_day`,
    `within_1_week`, `locked`);
  - limit breaches, and `new_risk_allowed`.
- **How release is reported.** Committed capital is released by horizon, but each bucket
  has `guaranteed_cash = 0`, because a losing binary returns nothing. The best-case payout
  is shown separately and never counted as cash. A position with no expected settlement
  time is `locked`.
- **Breaches.** Any breach (reserve floor, per-position/event/cluster/portfolio risk,
  daily/weekly loss, drawdown) sets capacity to zero. This is the simulation's kill switch.
- **Withdrawal contract.** `withdrawal_assessment` returns:
  - `technically_withdrawable`: settled cash;
  - `policy_safe_withdrawable`: settled cash above the reserve floor, and zero during a
    breach;
  - `recommended_owner_draw = None` with status `NOT_RECOMMENDED`, and the missing
    preconditions listed: shadow account, edge not verified, fee schedule unverified, no
    owner-approved policy, draw formula not defined.
  It will not recommend a draw even when every flag is set. That formula needs the owner's
  approval first.
- **Outcome Board** (`edge_lab.outcome_board.build_board`). It groups positions by
  `outcome_cluster` and reports:
  - linked positions and event ids;
  - current exposure, maximum loss and maximum gain;
  - account impact = max(loss, gain);
  - realized P&L;
  - the earliest settlement and its horizon;
  - status (OPEN, PARTIALLY_SETTLED, SETTLED).
  Groups are ranked by account impact, then settlement time, then cluster id. The maximum
  loss is the sum of the positions' worst cases, and the board states that method because
  it is an upper bound for mutually exclusive brackets.
- **EXP-001 wiring:**
  - The notional shadow account gets `EXP-001-shadow-risk-v1`, with limits the frozen
    1-contract rule never reaches. They are not tuned to any result.
  - `edge-lab shadow risk [--as-of]` emits the risk report, the withdrawal contract and
    the board.

**Tradeoffs.**
- The cluster worst case is an upper bound. The exact value needs scenario enumeration over
  the underlying outcome, and each position's settlement rule for it. Deferred until a
  cluster actually holds several positions.
- The limits are account-level constants in code. A real-money policy needs owner approval
  and its own versioned record.

**Reconsider when:**
- a funded gate is approached;
- positions can be exited before settlement;
- clusters routinely hold mutually exclusive positions, which would make the upper bound
  too loose.
