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
(`presentation.ROUTE_PARAMS`).

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
| Unit failure / verification | `last_failure.json` (production) and `last_verification.json`; a verification only when `verification.verification_confirmed` (root confirmation) |
| The Odds API card | `odds_pilot.dashboard_status(db, ledger, <ledger>.pilot.json, now=...)`; ledger `--odds-ledger`, default `odds_quota_ledger.json` beside `--db` |
| Experiments, Stage A result, report names, Stage B plan looks, limitations | experiment registry + `gate4/stage_a_result.json` |
| Venues and capabilities | `venues.VENUES` / `coverage_rows` |
| Source health | `SnapshotStore.latest_source_health` + `sources` registry descriptions |
| Fee verification | `fee_schedules` via `data.fee_rows` |
| Across venues: the four claims, per-route quote, gross cost, fee, fee status, verified (claim) total, depth, tradable-cash ETA, exclusions, related markets, summary | `best_price.compare` via `data.venue_comparison`, inputs built as `exp001_stageb.evaluate_day` builds them: the decision capture's listing (`kalshi_quotes.market_from_kalshi` plus the `settlement_equivalence` downgrade) and book (`kalshi_quotes.ladders_from_orderbook`; depth limit from the stored request URL, unknown = truncated), `fee_schedules.schedule_for` on the market's own series, the Stage B book-age limit; size, time and quote evidence ids from the recorded decision (`sizing.final_size`, `as_of_utc`, `quote_evidence_ids`: a different book is refused) |
| Research sizing: challenger (H) size, verdict, binding constraint, probabilities, expected net edge, entry price, fee, Kelly / pre-cap amounts, caps, bankroll basis, capital horizon, A–H comparison, unavailable reasons | `sizing_counterfactual.build_panel_bundle(store, ledger)` once per request (memoized by the contract on ledger heads, evidence snapshot id, config and code) and `panel_for_market_from_bundle(bundle, market_id)` (Lane A, #64) via `data.research_sizing`; every number is the contract's string |

**Dependencies recorded (shown as unavailable, never derived in the UI):**
1. *Realized today* (calendar day): the engine reports trailing-24 h realized **loss**, not a
   calendar-day result. Shown as "not computed"; Risk shows the trailing figure.
2. *Binding risk constraint*: `risk.assess` returns the capacity, not which headroom binds.
   Shown as the exact capacity plus the verdict.
3. *Cross-venue comparison*: the comparator runs on every captured route, but only Kalshi books
   are captured into the evidence store, so a real comparison has one route and says "Only
   Kalshi is captured for this market". Other venues appear once a collector stores their
   books and discovery proves rules equivalence. Rejected (unsized) decisions have no
   evaluated size, so they show "Not evaluated yet"; a counterfactual size needs Lane A's
   sizing contract.
3a. *Research sizing*: the contract (#64) is on main. A replay made without a readable or configured
   evidence database is flagged on the panel (captured settlements and confirmation quotes are
   missing from it). Free-text details from the contract are scrubbed of filesystem paths.
4. *Sport/league identity*: no sports market is captured; the Sports tab says so.
5. *Delivery status beyond the outbox*: phone delivery is not recorded; Alerts says so.
6. *Price history*: only the decision and re-check captures of the latest target day are read
   (two points at most per side).

## Owned paths

`src/edge_lab/dashboard/**` (presentation.py, components.py, html.py, app.py, data.py
additions, demo.py additions, fixtures.py, views/, static/), `tests/test_dashboard.py`
(updated), `tests/test_dashboard_terminal.py` (new), `tests/browser/**` (dev-only evidence),
`docs/design/**`, `docs/DASHBOARD.md`, ADR 0025, the directive record, `AI_INSTRUCTIONS.md`
(UI rule + routing row), `.github/pull_request_template.md`, `pyproject.toml` (package data);
appended sections in `docs/EXECUTION_PLAN.md`, `docs/OWNER_IDEAS.md`, `THIRD_PARTY_NOTICES.md`.

## Ordered checklist

1. [x] Baseline, claims, data/route inventory.
2. [x] Canonical design contract, tokens, fonts, asset serving.
3. [x] App shell and fixed navigation, then market tape.
4. [x] Component gallery and presentation contracts.
5. [x] Terminal, Markets and Market detail (first vertical slice, real early state).
6. [x] Portfolio, Outcomes and Risk.
7. [x] Research & Data, Alerts and More.
8. [x] Semantic parity, security, accessibility and browser-layout testing (see PR evidence).
9. [x] Independent design/data/security review; findings corrected. Round 1: 1 blocker (decisions for
   earlier target days shown as currently qualified), 6 should-fix, nits. Round 2 (da4dba2): all fixed, 2
   new should-fix from the fixes. Round 3 (e90669f): those fixed and verified, no blocker; one
   should-fix remained (a missed capture could leave the older captured day current), fixed with a
   regression test in the final commit.
10. [ ] Reviewed merge, private dashboard deployment, final browser verification.

## Conflicts identified (safer behaviour kept)

- **Query parameters.** The directive lists q, domain, sport, venue, state, horizon, sort,
  account and page; it also specifies `/market?venue=&id=&account=` and a Research/Data-sources
  tab. Implemented as per-route allowlists that add `id`, `side` (detail) and `tab` (Research &
  Data) only.
- **Mode notice at 360px.** The 12px notice, the 20px wordmark and a 44px bell need ~400px
  with a capsule border. Below 400px the notice keeps its text, size and weight but drops the
  capsule border/padding, so it never wraps or turns into a dot.
- **Tape "open-position markets first".** Only markets in the latest captured target day have
  quotes; an open position from an earlier day has no current quote and is not invented.
