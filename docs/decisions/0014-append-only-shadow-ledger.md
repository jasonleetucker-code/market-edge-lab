# 0014 — Append-only, hash-chained shadow ledger with replayed account state

Status: Accepted (2026-09-23). Gate 6, authorized in
`docs/owner/2026-09-22-overnight-build-directive.md` once Gate 5 had passed.

**Problem.** Gate 6 simulates trading the Gate 5 opportunities with no real orders. A shadow
account is only worth anything if every number in it can be explained. That covers cash,
committed capital, open risk, realized P&L and equity. The explanation has to come from
recorded decisions, simulated fills and official settlements. A mutable balance that
drifts, a fill at a price nobody offered, or a settlement that credits profit the position
never earned would each make any later Stage B result worthless.

**Alternatives.**
(a) Keep a balances table and update it as trades happen. Simple, but unauditable: one bad
    write is permanent and invisible.
(b) Add ledger tables to the collector's evidence database. That puts derived simulation
    state next to irreplaceable raw evidence, and it forces a schema migration on the
    production collector.
(c) A separate append-only journal in its own SQLite file, with account state computed only
    by replay. **Chosen.**

**Decision.**
- **Journal** (`edge_lab.shadow_ledger`). It records four entry kinds per account:
  `account_opened`, `decision`, `fill` and `settlement`.
  - Triggers reject UPDATE and DELETE.
  - `(account, kind, key)` is unique. Re-appending identical content is a no-op; different
    content raises `LedgerConflict`.
  - Entries are hash-chained per account over the account id, kind, key, effective time
    and payload hash. The wall-clock append time is kept outside the hash, so the same
    inputs always give the same chain.
  - The chain is tamper-*evident*, not a MAC: it exposes any edit or reordering, but
    anyone with write access to the file could forge a new, consistent chain. It is a
    research ledger, not a custody system.
  - Before each commit, the append replays the whole journal *with* the candidate entry.
    An entry that would leave the account unreadable (for example a reused `fill_id`) is
    refused.
  - Replay enforces every append-time invariant, so the two checks cannot drift apart.
  - A decision may carry a `slot`, and the ledger keeps slots unique. EXP-001 uses
    `D|market|side`, so a day is never decided or filled twice, even if a later engine or
    model version produces new opportunity ids.
- **Invariants are checked before anything is written:**
  - a fill needs a decision, and FILLED needs a QUALIFY decision;
  - a FILLED entry may not make settled cash negative;
  - a settlement needs an open FILLED position, and its payout and P&L are computed from
    the fill, never from the caller;
  - replay re-checks every hash and reconciles `equity == starting bankroll + realized
    P&L` exactly (Decimal).
- **Money model** (long binary contracts):
  - The worst-case loss equals the cash paid, fees and cent alignment included.
  - Equity is settled cash plus the cost of open positions. No unrealized gain is ever
    counted.
- **Fill policy** (`edge_lab.fill_policy`, `latency-confirmed-v1`). This is the frozen
  EXP-001 execution model, generalized:
  - entry at the decision ask, with quantity no more than the displayed size and a book no
    older than 5 min;
  - the fill counts only if a book captured 10–15 min later still offers no more than that
    price, with enough size;
  - the price paid is always the entry price.
  - Any gap gives `NO_FILL` with a machine-readable reason.
- **Sizing** (`edge_lab.sizing`). `suggest_position_size` applies a fixed count or
  fractional Kelly on the conservative probability.
  - The hard caps are position contracts, position risk, event risk, cluster risk,
    portfolio risk, reserve and liquidity. Each is applied, then the dollar caps are
    rechecked against the exact cost.
  - It records the raw, risk-adjusted, liquidity-capped and final sizes, and the binding
    constraint.
  - Caps always override Kelly. The Kelly fraction is a policy input and is never fitted to
    history.
- **EXP-001 adapter** (`edge_lab.exp001_shadow`):
  - The account `EXP-001-stage-b-shadow` has a notional $1,000 bankroll, and the frozen
    1-contract rule applies.
  - Every opportunity becomes a decision, including rejected ones.
  - `run_day` refuses a day until its re-check windows have closed, so an early run never
    leaves stale decisions.
  - Only VALID Stage B days can fill. The Gate 5 engine already makes every opportunity
    on an INVALID day EVIDENCE_INCOMPLETE; the `STAGE_B_DAY_INVALID` no-fill is a second
    guard.
  - NO_FILL reasons map to the frozen execution text as follows:
    - `NO_ENTRY_QUOTE` / `STALE_ENTRY_QUOTE` / `NO_ENTRY_PRICE` correspond to *NO_BOOK*;
    - `NO_CONFIRMATION`, `CONFIRMATION_*` and `PRICE_MOVED_AWAY` correspond to
      *NO_FILL_UNVERIFIED*.
    Either way, the daily value counts the trade as 0.
  - Settlement is written only when Kalshi's recorded result and the frozen resolver agree
    on `expiration_value`. Otherwise the position stays open.
- **CLI:** `edge-lab shadow run --date D`, `edge-lab shadow settle`, and
  `edge-lab shadow account`.

**Tradeoffs.**
- Replay is O(entries) per state read. That is fine at one event a day for years; add
  snapshots if it ever matters.
- Settlement needs captured settled-market evidence. The VPS collector does not capture
  that yet (the owner-authorized scope covers it, but no timer exists). Until it does,
  positions stay open, which is safe.
- The ledger is derived data. Losing it loses nothing: rebuild it from the evidence
  database and versioned code.

**Reconsider when:**
- a real-money gate (8+) needs an externally reconciled ledger;
- positions need partial fills or exits before settlement;
- a venue settles in other than whole-dollar binary payouts.
