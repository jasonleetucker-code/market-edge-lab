# 0016 — Daily shadow operation: research vs operational accounts, point-in-time cash, one orchestrator

Status: Accepted (2026-09-23, daily-shadow directive, `docs/owner/2026-09-23-daily-shadow-directive.md`)

**Problem.** Gates 5–6 left the engines unconnected to a daily schedule, and a review
found five gaps:
- Operational risk limits (daily and weekly loss, drawdown, remaining capacity) were not
  enforced before a simulated fill. Only sizing caps and cash were.
- Sizing caps could veto a frozen EXP-001 signal, so the research record could quietly
  deviate from the preregistered rule.
- Cash followed ledger append order, not modeled time. In catch-up, a settlement learned
  later could fund an earlier fill.
- Analysis opened the evidence store with the collector's constructor, which creates and
  migrates the schema.
- Settlement collection re-downloaded the full history every run, and a blocked contract
  PDF aborted it.

**Alternatives.**
- (a) Add risk vetoes to the single existing account. This changes the research record:
  a veto would drop a frozen-rule signal.
- (b) Keep one account and amend EXP-001. That rewrites a preregistered rule for an
  operational concern.
- (c) Two accounts in the same ledger, from the same decisions.

**Decision.** (c).
- **Accounts.**
  - `EXP-001-stage-b-research` records exactly the frozen rule: one contract per signalled
    bracket, `latency-confirmed-v1`, no caps and no vetoes, with a large notional bankroll.
    Only this account feeds the EXP-001 180/365-valid-day looks. If its cash ever binds,
    the fill is recorded as `RESEARCH_INVALID_CASH` and reported.
  - `EXP-001-stage-b-shadow` is the operational account. It applies sizing caps plus a
    pre-fill `risk.assess` on the point-in-time state.
    - Any breach, or a candidate whose worst case exceeds a position, event or cluster
      limit or the remaining capacity, is persisted as NO_FILL `RISK_VETO` with its
      binding constraint.
    - Exactly at a limit is allowed.
    - Zero capacity never authorizes risk.
- **Point-in-time cash and time order.**
  - A settlement records `evidence_available_utc`, the receipt time of its evidence.
  - `replay(as_of=…)` and `ShadowLedger.state_as_of` count only entries known by then.
  - A fill is refused unless the cash known at its time covers it. The fill time is the
    receipt of its confirmation book.
  - Cash-moving entries must be appended in knowledge-time order. A fill known earlier
    than an already-recorded fill or settlement is refused: out-of-order catch-up, or a
    retried older day, is a FAILED day that needs attention, never a quiet pass.
  - Within a day, all decisions are recorded first and then fills in confirmation-time
    order, so each fill's point-in-time state includes every earlier fill of that day.
  - The orchestrator stops at a failed day rather than running later days ahead of it.
  - A settlement's evidence must be received at or after both the settlement time and the
    fill.
  - A settlement's effective time is clamped to its evidence receipt, and the reported
    Kalshi field is kept.
- **Read-only analysis.** `SnapshotStore.open_readonly` and `ShadowLedger.open_readonly`
  use SQLite `mode=ro` and `query_only`, with no mkdir, no schema script and no journal
  PRAGMA, and they refuse a wrong schema. The database contents never change. SQLite
  itself maintains the WAL side files: a reader updates the `-shm` read-mark index and
  creates `-wal`/`-shm` if they are absent. Analysis must therefore run as the store's
  owner (`edgelab`), never as root, so those files keep the right owner. Only the final
  path component is checked for a symlink.
- **One orchestrator** (`edge_lab.daily`, `edge-lab shadow daily`).
  - It takes the collector lock and then the ledger lock.
  - It processes closed capture days in date order. Before each day it settles only on
    evidence received before that day's decision.
  - It optionally refreshes settlement evidence for due pending events only, with bounded
    GETs through the collector write path.
  - It settles, computes summaries, and writes a receipt with explicit states.
- **Collection fix.** A blocked contract PDF is recorded as an anomaly; the settled
  markets are still collected.
- **Backups.** The daily backup copies both the evidence DB and the ledger. The ledger
  copy is verified by its triggers and a full replay of every hash chain.

**Tradeoffs.**
- Two accounts double the ledger writes: tiny, about 12 decisions a day each.
- Operational vetoes make operational P&L differ from the research P&L. That is intended,
  and both are reported.
- Every append still replays the whole account (O(n²) over years). That is fine at about
  12 entries a day, but it should become an incremental replay before multi-market scale.
- The settlement-due rule (decision + 30 h) is a heuristic about Kalshi's usual
  publication time. Too early costs one wasted GET, never a wrong settlement.

**Rollback.** No schema change in either store (evidence v4, ledger v1). New fields live
in JSON payloads, which the older code ignores, so no migration is needed. Code and unit
files roll back **together**: the new backup unit uses flags older code rejects
(`docs/deploy/DAILY_SHADOW_ACTIVATION.md`, "Rollback"). The rolled-back code loses
point-in-time cash checking.

**Reconsider when** a second strategy or market family shares the ledger (move to
per-strategy accounts from a registry), or ledger replay time matters.
