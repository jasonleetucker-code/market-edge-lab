# Market Edge Terminal v1 — components

Every user-visible page is composed from these functions. Owner: `src/edge_lab/dashboard/
components.py` (HTML) and `presentation.py` (view models, formatting). Styles:
`static/terminal.css`. Live examples of every state: `/gallery` in demo mode
(`python -m edge_lab.dashboard --demo`, fixtures in `dashboard/fixtures.py`).

Rules for all components:
- Inputs are canonical values or `presentation` view models. A component never computes a
  balance, fee, size, eligibility or settlement.
- Every dynamic string is escaped (`html.esc`). Arguments named `*_html` or `body` are
  already-escaped HTML from other components.
- `None` renders as the unavailable marker (`na`), with an accessible reason. Never `0`.
- New variants are added here and to the gallery **before** a page uses them. No one-off
  panel classes, inline styles or colours in page modules.

## Shell (html.py)

| Component | Signature | Notes |
|---|---|---|
| AppShell | `page(Shell(title, nav, body, demo, rendered_utc, rendered_et, account_label, tape, alerts))` | Header, demo strip, tape slot, rail, main, footer, mobile tab bar. `nav` is a `NAV` key. |
| Navigation | `NAV`, `rail(nav)`, `tabbar(nav)` | Fixed labels/routes (UI_CONTRACT §6). Adding a global item needs an amendment. |
| Assets | `STATIC_FILES`, `asset_url(name)`, `asset_version()` | Exact allowlist; versioned immutable URLs. |

## Primitives (components.py)

| Component | Signature | States |
|---|---|---|
| Icon | `icon(name, cls="", label=None)` | Decorative unless `label`. Names: sprite ids without `i-`. |
| Unavailable marker | `na(reason)` | Always carries the reason for AT. |
| Number | `num(text, cls="", reason=...)` | Mono tabular; `None` → `na`. |
| Text | `txt(text, reason=...)` | Times and labels (not mono). |
| Money | `money_cell(value, signed=False, reason=...)` | Uses `presentation.money`; signed adds pos/neg class. |
| Badge | `badge(code, label=None, kind=None)` | Plain label from `STATES`, stored code in title; unknown → neutral. |
| State text | `state_text(code, label=None, kind=None)` | Dense rows: icon + text. |
| Badge + code | `badge_code(code)` | Details: semantic badge plus exact code. |
| Code | `code(value)` | IDs, hashes, raw codes. |

## Structure

| Component | Signature | Notes |
|---|---|---|
| SectionHeader + section | `section(title, body, meta=None, action=None, sid=None, cls="", flush=False)` | One optional action link. `flush` for edge-to-edge lists. |
| Page heading | `page_head(title, sub=None, extra="", crumb="")` | `extra` holds the account switch. |
| EvidenceDisclosure | `disclosure(summary, body, open_=False, boxed=False)` | Codes, exact values, provenance live here. |
| Key-values | `kv(pairs)` | Details only. |
| Technical table | `table(headers, rows, wrap=(), right=(), empty=..., caption=None)` | Scrolls in its own container; Details only. |

## States

| Component | Signature | Use |
|---|---|---|
| EmptyState | `empty_state(title, text, kind="nd", times=None, action=None)` | Known empty (loaded, nothing there). |
| UnavailableState | `unavailable(title, message, action=None)` | Not configured / not started. |
| ErrorState | `error_state(title, message)` | Read failure (role=alert). Never looks empty. |
| BlockedState | `blocked_state(title, message, action=None)` | Halted, not enabled, anomaly. |
| StatusLine | `status_line(kind, title, detail="", detail_html="")` | Event state + separate report time. |

## Financial and market components

| Component | Signature | Notes |
|---|---|---|
| MetricStrip | `metric_strip([metric(label, value_html, basis=None, lead=False)], label=...)` | Scope in the accessible name; basis next to each figure. |
| Bar | `bar(value, maximum, kind="", label="")` | SVG; nothing drawn when either side is unknown or max ≤ 0. |
| DomainTabs / tabs | `tabs([(href, text, current, count)], label=...)` | One swipeable strip; `aria-current`. |
| Account switch | `account_switch(params, path, extra=None)` | Operational / Research; never both at once. |
| QuoteTile | `quote_tile(QuoteSide or None, side, href, label=None, current=False)` | Side label above the captured ask; "Unavailable" with reason; "at decision" for decision-time prices. |
| EdgeValue | `edge_value(Assessment or None)` | Net EV per $1 contract; not a return. |
| MarketRow / board | `market_row(MarketRow, params)`, `market_board(rows, params, label=...)` | One view model; container queries switch 9-col / 5-col / mobile composition. |
| Market link | `market_href(row, params, side=None)` | Same-origin, URL-encoded, keeps filters. |
| Tape | `tape([(MarketRow, QuoteSide)], params, unavailable=False)` | Captured quotes only; "No quotes captured yet." when the evidence loaded with none; `unavailable=True` (evidence read error) → "Captured quotes unavailable (read error).", never the empty wording. |
| Facts | `facts(pairs, wide=False)` | Compact label/value grid inside rows and detail sections. |
| PositionRow / OutcomeExposureRow | `row(title_html, sub="", aside="", body="")` | Shared row shell; pages supply facts, bars, disclosures. |
| ActivityRow | `activity_row(kind, title, detail, when_utc, href=None, extra_html="")` | Semantic icon, time, reason, valid link. |
| PipelineTimeline | `timeline([(kind, title, detail, when_text)])` | Scheduled/observed steps. |
| HistoryChart | `history_chart([(utc, value)], label=...)` | ≥2 persisted points or an explanatory empty state; accessible table always. |
| VenueComparison | `venue_comparison(comparison)` | A `best_price.Comparison` (ADR 0027): `comparison_claims` (the four claims side by side, each its own figure or reason; never one "best"), then `comparison_route` rows grouped as ranked by at least one claim / ranked by none, related markets "RELATED MARKET — NOT ECONOMICALLY EQUIVALENT" unranked, stale routes named, a refused payoff as a blocked state; claim meanings and the comparator summary in disclosures. No input or order control. |
| Across venues slot | `views/markets.venues_section(ctx, row, side)`, `views/markets.comparison_body(result)` | Runs `data.venue_comparison` at the recorded decision's time and evaluated size; states: not evaluated (no decision / no size / earlier target day), no captured book, read error (UI_CONTRACT §8). |
| ResearchSizing | `research_sizing(panel)`, `sizing_side(side)`, `sizing_comparison(rows)` | Lane A's `sizing_counterfactual` panel dict (panel_version 1), strings only formatted: the contract's RESEARCH SIZING label (never "Recommended bet"), per side the challenger (H) result or its named unavailable reason, caps and fill in a disclosure, the A–H comparison table, the top-of-book caveat, limitations. No input or order control. |
| OddsSourceStatus | `odds_status_card(status)` | `odds_pilot.dashboard_status` as one row: title "The Odds API — <STATE>", the research-only label, live read verified, latest successful capture, quota, discovery, next capture, timer (not observable), executable never; details in a disclosure. ACTIVE only with `live_read_verified`, else UNVERIFIED; a state outside `odds_pilot.DASHBOARD_STATES` is UNKNOWN. Slot: `views/research.odds_section` / `odds_body` (not configured, read error). |
| Odds capture targets slot | `views/research.odds_targets_section(ctx)`, `odds_targets_body(result, status, now)`, `target_row(t, now, max_age)`, `targets_table(targets)` | `data.odds_capture_targets` (`OddsTargets` / `OddsTarget`) composed from facts, row, badge, state-text, empty/blocked/error, disclosure, kv and table. Rows: the latest 5 past and next 5 targets; every target in the "All targets" disclosure (capped at `data.ODDS_TARGETS_MAX`, the cap stated). Credits are one call's cost with how many targets shared it, never summed; books are parsed from the stored snapshot for the rows shown and taken from the runner's record at capture in the full list (`()` = known zero, `None` = unknown with a reason, parse problems = caveat); a capture's freshness is "at receipt", never current. States: populated, no targets, no captures yet, overdue, paused (from `odds_pilot.dashboard_status`), source unavailable, read error. Gallery: `fixtures.synthetic_odds_targets`. |
| Source freshness slot | `views/research.freshness_section(ctx)`, `freshness_body(result, now)`, `fabric_source_row(src, policy, now)` | `data.freshness_report` (`FreshnessReport`: the artifact as written plus its own age by `generated_at_utc`). A summary (generated, evaluated, fresh, due now, missed, blocked, unknown), the explicit external-schedule count, the supervisor's "due next" list, a "Needs attention" list (missed, blocked, failing or degraded, disagreeing), and every source grouped by domain in a disclosure, one row each (freshness with data age at evaluation and objective, schedule state, health, next due, last successful receipt, usability, why, misses, disagreements; policy and times in a disclosure). States: populated, stale report, partial, deferred (carried or nothing carried), not written / not configured, read error / foreign schema. Gallery: `fixtures.synthetic_freshness`. |
| Alert origin | `views/alerts._row(alert)`, `views/common.failure_alert(record)` | Origin badge (`presentation.origin_code`) on every notification and failure record; production vs "Tests, verification checks and diagnostics" groups; delivery wording from the origin policy. |
| Research sizing slot | `views/markets.sizing_section(ctx, row)`, `views/markets.sizing_body(result)` | `data.research_sizing` (one `build_panel_bundle` per request, memoized by the contract); states: contract not installed / broken, no ledger, read error, a replay without the evidence database (caveat), and the panel's own unavailable reasons. |
| MarketDetail | `views/markets.detail(ctx, params)` | Section order fixed; read-only ticket preview. |

## View models (presentation.py)

- `Params` — validated query state; `href()` builds filter-preserving links.
- `QuoteSide` — side, label, price (ask), size, received time, phase, evidence id, anomaly,
  change and its basis. Change is `None` unless two comparable observations exist.
- `Assessment` — one recorded decision payload plus its fill: probabilities, prices, fee,
  net edges, fee status, claim basis, size, binding constraint, fill status, starter verdict.
- `MarketRow` — identity, domain, title/outcome, quotes, assessments, `primary`, `state`
  (qualified / watching / blocked / unsupported), `state_code`, `cash_release`.
- `build_rows`, `filter_rows`, `sort_rows`, `tape_rows`, `page_slice` — grouping only.
- `cluster_label(cluster)` — plain-language outcome-cluster title for known patterns only
  (EXP-001 `weather:us-nyc-central-park:<date>` → "NYC Central Park high temperature · Sep 24");
  any other id is returned raw, never a guessed label. The raw id stays in Details.

## Ownership

One writer per file at a time (`docs/WORK_CLAIMS.md`). Component or token changes go through
`UI_CONTRACT.md` §14 amendments; page modules consume, never restyle.
