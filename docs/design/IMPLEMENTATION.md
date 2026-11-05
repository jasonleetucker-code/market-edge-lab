# Terminal v1 — implementation ledger

Execution record for the Market Edge Terminal v1 directive
(`docs/owner/2026-09-23-terminal-v1-ui-directive.md`, issue #47). **Not a design authority**:
`UI_CONTRACT.md` is. Branch `ui/terminal-v1`.

## Baseline

- Baseline revision: `main` at `7aac49c` (2026-09-23), rebased onto `943d597` (PR #48, docs
  only) before the shared-doc edits.
- Test baseline on an unmodified `7aac49c` worktree (Windows, Python 3.12):
  `python -m pytest -q -o addopts="" -k "not sigterm"` → **1495 passed, 16 skipped, 3
  deselected**. The 3 deselected SIGTERM tests terminate pytest on Windows (known, see CI on
  Linux for them).
- Before state: the owner's six iPhone screenshots (dark theme, 2:40–2:41 PM ET on
  2026-09-23): a full-width red "SHADOW — NO REAL MONEY" banner; six navigation links wrapping
  into three rows; Overview led by "Collector status file (latest.json)" with raw ISO times,
  FRESH next to an INVALID capture and raw reason codes; Opportunities, Positions and Outcome
  Board repeating an operational and a research panel with "none recorded"; Risk opening with
  a raw policy-field table; Experiments opening with a registry table. The same fixture state
  re-rendered by `7aac49c` (`tests/browser/capture.py --src <main worktree>/src`) is the local
  before evidence (light theme in headless browsers, since the old CSS followed the OS).
- Claims: `docs/WORK_CLAIMS.md` row "Market Edge Terminal v1 UI". Shared docs
  (`EXECUTION_PLAN.md`, `OWNER_IDEAS.md`, `THIRD_PARTY_NOTICES.md`) were edited only after PR
  #48 released them, append-only. `HANDOFF.md` stays with the production-activation claim; its
  UI block is handed to that session.

## Routes

Before: `/`, `/opportunities`, `/positions`, `/outcome-board`, `/risk`, `/experiments`,
`/healthz`; GET/HEAD; query strings ignored; inline CSS; CSP `style-src 'unsafe-inline'`.

After: the same deep links (relabelled Terminal, Markets, Portfolio, Outcomes, Risk, Research
& Data) plus `/market` (detail), `/alerts`, `/more`, `/gallery` (demo only),
`/static/<version>/<allowlisted name>`, `/healthz`. Per-route query allowlists
(`presentation.ROUTE_PARAMS`). `/experiments/inplay` (In-play research, nav Research & Data, no query
parameters) and `/gallery/inplay` (its fixture states, demo only), registered by `views/inplay.py`
(`INPLAY_PAGES`, `INPLAY_DEMO_PAGES`) and merged in `app.make_app`.
`/experiments/intel` (News & political intelligence, #192, nav Research & Data; parameters `tab` ∈ {today,
opportunities, events, transcripts, history, sources}, `event`, `submitted`), `/experiments/intel/packet` (`event`,
`submitted`) and `/gallery/intel` (demo only), registered by `views/intel.py` (`INTEL_PAGES`, `INTEL_DEMO_PAGES`). The
one POST route, `/experiments/intel/inbox`, is handled by `dashboard/intel_post.py` and exists only when the dashboard
was started with `--intel-inbox` (UI_CONTRACT §14, 2026-11-05).

## Data-to-view map (every visible number has a canonical origin)

| Visible value | Origin |
|---|---|
| Shadow equity, tradable cash (settled cash), committed, open risk, realized P&L, fees, counts | `ShadowLedger.state()` replay (`AccountState`) |
| Remaining capacity, daily/weekly realized loss, drawdown, breaches, new_risk_allowed, capital release buckets, per-position/event/cluster risk | `risk.assess` with the account's registered `RiskPolicy` |
| Limit caps | `exp001_shadow.RISK_POLICY` (and research policy if registered) |
| Withdrawal figures and status | `risk.withdrawal_assessment` (always NOT_RECOMMENDED) |
| Outcome groups, exposure, bounds, account impact, horizons | `outcome_board.build_board` |
| Outcome group title (plain language) | `presentation.cluster_label` over the group's recorded `outcome_cluster` (raw id kept in "Why it matters") |
| Portfolio position row subtitle (venue · outcome) | `presentation.venue_label` + `presentation.cluster_label` over the position's recorded `outcome_cluster` (raw id kept in "Position details" as `cluster`) |
| Board and Markets coverage wording | `data.Context.observed` status. OK → `coverage_text`. ERROR → Terminal board meta "Captured books unavailable", Markets subtitle "Captured coverage unavailable (read error).", Markets coverage line "Captured books unavailable (read error)". NO_DATA → "No captured books", "No captured coverage yet.", "No books captured yet" |
| Quotes on tape, board and detail (ask, size, capture time) | `data.observed_board` → `kalshi_quotes.quotes_from_orderbook` over the latest target day's decision and re-check captures |
| Price change | difference of two captured asks of the same side (presentation; not an edge, not P&L) |
| Model and conservative probability, price at decision, fee, all-in cost, net edge, fee status, claim basis, size, binding constraint | recorded decision payloads (Gate 5 engine at decision time) |
| Fill status, simulated fill cost (max loss) | recorded fill payloads |
| Tradable-cash ETA, hours, starter eligibility | `starter_policy` verdict recorded on the fill or decision |
| Starter exceptions | `data.starter_view` → `starter_policy.policy_exceptions` |
| Capture status, reasons, valid days | `latest.json` (collector) or `forward.summary` (evidence DB) |
| Next capture windows | `forward.windows` (the collector schedule; not proof a timer runs) |
| Pipeline state, days, settlements, conflicts, missing days | `shadow_daily.json` receipt |
| Notifications | local outbox `notifications.jsonl`; origin by `notifications.origin_of` (missing = PRODUCTION, unknown = unrecognised); delivery wording by the origin push policy |
| Unit failure / verification | `last_failure.json` (always production) and `last_verification.json` (a confirmed check when `verification.verification_confirmed`, else "root confirmation not found or expired"; never an incident) |
| The Odds API card | `odds_pilot.dashboard_status(db, ledger, <ledger>.pilot.json, now=...)`; ledger `--odds-ledger`, default `odds_quota_ledger.json` beside `--db` |
| Odds capture targets: event, horizon, intended time, state, reason, slot, receipt time, credits, recorded capture detail, state history | `SnapshotStore.odds_targets()` / `odds_transitions()` (read-only) via `data.odds_capture_targets`; effective due, deadline and overdue by `odds_schedule.effective_due` / `deadline` / `is_expired` under `odds_pilot.RunnerSettings().config`; rows filtered to `odds_pilot.RunnerSettings().sport`; books and offers per event from the captured snapshot by `odds_api.parse_odds` for the rows shown (memoized by snapshot id and payload sha, bounded) and from the transition's recorded `detail` (bookmakers, offers, parse_problems) in the full list; a capture's freshness at receipt by `odds_api.offer_freshness` at the receipt time, combined worst-of by `freshness.combine`; "paused" from the card's `odds_pilot.dashboard_status` state |
| Consensus at a capture: consensus probability, range, MAD, contributing / quoting books, status, reason, freshness, update bounds, offered prices, implied with margin, per-book de-vig and margin, unsupported groups, version, hashes | `odds_consensus.consensus_for_event(store, event_id, as_of=captured_at_utc)` via `data.odds_consensus_at_capture`, for the captured rows shown only; memoized by (database, event, as_of, newest odds snapshot id received by as_of; other sources' writes never invalidate); every figure is the contract's value, only formatted (`percent`, `pp_size`, `pp`, `datetime_et`) |
| Source freshness: every source's freshness, schedule state, health, why, times, data and upstream age, usability, misses, disagreements, notes, details and policy; the summary and "due next"; the supervisor's state, deferral window and carried evaluation | `<status-dir>/freshness.json` (`freshness_fabric` supervisor, schema `freshness-fabric-status/1`) via `data.freshness_report`, read as written; the report's own age by `freshness.assess(generated_at_utc, max_age=freshness_fabric.SUPERVISOR_MAX_AGE)`; ages formatted from the artifact's seconds (`duration_text`), never recomputed from now |
| Polymarket US related markets: access gate, catalog state and coverage note, per Odds API event relationship, reasons, checks, flags, market fields, latest research book capture (YES bid / ask, sizes, receipt, freshness at capture), capture target states and attempts, attribution | `polymarket_sports.terminal_view(db, now=...)` via `data.pm_sports_view`; `polymarket_sports.market_history(store, slug)` via `data.pm_market_history` for the markets shown; prices formatted by `cents`, sizes by `quantity`; nothing is compared with a sportsbook price |
| In-play research (#122): mode, state, contract, book status and age at the replay clock, coverage, gaps, resyncs, failures, simulated inventory and reservations, policy proposal (action, quantity, limit, execution assumption, reasons), exit proceeds estimate at displayed depth, hold-versus-exit arms (replay P&L gross and net, change vs hold, worst and best entry), oracle diagnostics, after-cost claim, assumptions, authority, pilot status, blocker | `inplay_view.not_authorized_view()` in production (no in-play source is authorized) and `inplay_view.fixture_view(...)` in demo mode, via `data.inplay_view` / `data.inplay_fixture_views` (schema `inplay-view/1`; a LIVE mode or another schema is an error). Inside the contract: `inplay_evidence` (reconstruction, coverage), `position_policy.evaluate`, `inplay_replay.replay`. Formatted only (`money` unsigned-colour, `cents`, `count`, `percent`, `datetime_et`) |
| News & political intelligence (#192): collected items (source, time, evidence type, storage rights), last news run, feed status counts, events (status and reason, verification, origins, primary sources, evidence, contradictions, unconfirmed podcast claims, outcomes and resolution conditions), recorded packets (id, horizon and who set it), forecasts (point, range, basis, price awareness, horizon, superseded chain), candidates with captured rules, confirmed links, decisions (action, best side, ask, fee and fee status, all-in cost, break-even, probabilities, EV point and conservative, maximum acceptable price, top size, reasons, explanation, horizon check, market close, quote receipt), resolutions, performance (Brier by basis, hypothetical P&L per contract), inbox (queued files, processed results), processor availability | `intel.view.build_view` over `SnapshotStore.open_readonly` via `data.Context.intel_view` (schema `intel-view/1`): `service.feed_states`, `service.current_events`, `service.all_evidence`, `service.latest_packet_for_event` (packet page, via `data.Context.intel_packet`), `service.performance`, `store.intel_items`, `store.intel_records` (kinds run, transcript, packet, analysis, forecast, link, candidates, decision, resolution, inbox), `store.latest_snapshot` (captured rules and market title, `kalshi_link.rules_text`), `events.derive_status`; `inbox.pending` (never creates the inbox); heartbeat `intel.json` (intel-heartbeat/1) in the status directory. Decision sheets (`pricing.PricingSheet` as stored by `service.decide`) are passed through verbatim and only formatted (`cents`, `percent`, `edge_cents`, `hours_text`, `duration_text`, `datetime_et`, `date_label`); the economics label is VERIFIED only when the shown side records `fee_claimable` true |
