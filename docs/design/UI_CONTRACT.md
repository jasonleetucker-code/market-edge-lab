# Market Edge Terminal v1 — UI contract

**Status: canonical and binding** for every user-visible Market Edge surface. Owner authority:
issue #47 and the directive recorded verbatim in
`docs/owner/2026-09-23-terminal-v1-ui-directive.md`. Decision record: ADR 0025.
Companion documents: `COMPONENTS.md` (component APIs), `FEATURE_INTEGRATION.md` (checklist
for any new feature), `IMPLEMENTATION.md` (execution ledger, not a design authority).

The product is **Market Edge Lab**; the header wordmark reads **MARKET EDGE**. The design is
an original market terminal: charcoal surfaces, warm-white type, precise dividers, restrained
signal orange, compact boards and aligned numerals. It is not a landing page, a template, or
a sports-only app. Weather, sports, politics, economics and future domains share one shell.

**Changes to this contract need a dated amendment** (section 14), never an agent's
stylistic preference. Tests detect violations; they do not certify that a page looks right.
Reviewed screenshots do that.

## 1. Non-negotiables

- Read-only. **SHADOW · NO REAL MONEY** is visible on every page. No order, deposit,
  withdrawal, approval, auto-trade or "mark read" control exists.
- Market information is visually central; diagnostics are reachable but subordinate
  (disclosures). Raw codes, IDs and caveats are never deleted, only moved into Details.
- Quotes, model probabilities, fees, price movement, net edge and balances stay semantically
  distinct. A probability difference is **pp**, never **%** or a return.
- Known zero, missing, not evaluated, stale, unsupported, error and blocked are distinct
  (section 9). Missing never renders as 0.
- Operational and research shadow accounts are separate scopes, never summed.
- A fresh status report is not proof of fresh market data or a valid capture.
- Synthetic data appears only in demo/test mode, under a persistent **SYNTHETIC UI DEMO**
  strip, and only through fixture or canonical ledger paths.

**Prohibited:** violet/cyan gradients, glow, glassmorphism, blur, translucency, giant pill
containers, floating navigation, drop shadows on sections, bento landing grids, emoji
navigation, stock photography, robot/sparkle icons, random logos, confetti, fake profit
curves, slogans, oversized welcome copy, a second theme, copied third-party branding or CSS.

## 2. Architecture (one owner per concern)

| Concern | Owner |
|---|---|
| Canonical figures (ledger, risk, board, fees, experiments, observed quotes) | `dashboard/data.py` → canonical modules |
| Formatting, state vocabulary, query allowlist, typed view models, sort/filter | `dashboard/presentation.py` |
| Escaped HTML components | `dashboard/components.py` (API: `COMPONENTS.md`) |
| Document shell, navigation, static-asset allowlist | `dashboard/html.py` |
| Page composition (one module per page) | `dashboard/views/*.py` |
| Routing, CSP, static serving, parameter validation | `dashboard/app.py` |
| Tokens (the only colour/font/spacing definitions) | `dashboard/static/tokens.css` |
| Shell and component styling | `dashboard/static/terminal.css` |
| Progressive enhancement (tape arrows only) | `dashboard/static/terminal.js` |
| Fonts, icons, licences, provenance | `dashboard/static/fonts/`, `static/icons.svg`, `static/ASSETS_PROVENANCE.md` |
| Synthetic view-model fixtures, gallery | `dashboard/fixtures.py`, `views/gallery.py` (demo only) |

Stdlib-only server-rendered Python. No React/Next/Tailwind/UI kit, no Node service, no second
API. Presentation may group, sort, filter, format and compute pixel coordinates; it never
computes money, fees, eligibility, sizes, settlement or risk capacity. A missing canonical
field renders as unavailable and is logged as a dependency in `IMPLEMENTATION.md`.

## 3. Tokens (exact; `tokens.css`)

```
--me-canvas #101214        --me-surface #171A1D        --me-surface-raised #20252A
--me-surface-hover #272D33 --me-line #343B43           --me-control-line #65717E
--me-text #F4F2EC          --me-text-secondary #BEC3CA --me-text-muted #949EA9
--me-accent #FF7A45        --me-accent-ink #101214     --me-positive #49D3A2
--me-negative #FF8088      --me-warning #E8BA65        --me-info #89B8FA
--me-focus #B8D6FF         radius: control 4px, panel 6px
space: 4 8 12 16 24 32 px (--me-space-1 … -6)
```

- Dark is the only theme (`color-scheme: dark`); OS preference never switches it.
- Orange = brand, selection, primary navigation. Never profit.
- Green/red = signed changes, results and semantic states, always with text or an icon.
  YES is not green and NO is not red by default.
- Panels: 1px border, 6px radius. Controls: 4px. Only small status badges are 999px capsules.
- No shadows on sections; opaque surfaces only; no whole-section opacity.
- Focus: 2px `--me-focus` outline, 2px offset, never removed.
- No hex colour or font family outside `tokens.css` (tested).

## 4. Typography

Self-hosted IBM Plex WOFF2 (Latin-1 split subsets, OFL-1.1, pinned in
`ASSETS_PROVENANCE.md`); no font CDN; `font-display: swap`; `font-synthesis: none`.

| Family | Weights | Used for |
|---|---|---|
| IBM Plex Sans | 400, 500, 600 | body, controls, market titles, times |
| IBM Plex Sans Condensed | 600 | wordmark, page and section headings, mode notice |
| IBM Plex Mono | 400, 500 | prices, money, probabilities, edges, chart axes |

| Element | Mobile | Desktop (≥768) |
|---|---|---|
| Wordmark | 20/24 | 22/26 |
| Page heading | 26/30 | 30/34 |
| Section heading | 18/24 | 20/26 |
| Primary balance | 28/34 | 32/38 |
| Quote tile price | 18/22 | 18/22 (15/20 inside dense board rows) |
| Market title | 15/20 | 14/20 |
| Body | 15/22 | 14/21 |
| Metadata / badges | 12/16 | 12/16 |
| Input text | 16/22 | 14/20 |

Uppercase only for the wordmark, short eyebrows (0.07em tracking) and state codes. Numbers
use tabular figures, right-align in comparable columns, never ellipsize; the layout wraps.

## 5. Formatting (`presentation.py`, never template arithmetic)

| Kind | Format | Function |
|---|---|---|
| Currency | `$1,000.00`; extra precision kept (`$0.0158`); negatives `−$3.20` | `money` |
| $1-contract price | `48¢`, `48.25¢` | `cents` |
| Probability | `64.0%` | `percent` |
| Probability difference | `+5.2 pp` | `pp` |
| Net EV | `+5.12¢` per contract, truncated toward zero; `<0.01¢` keeps its sign | `edge_cents` |
| Missing | `—` with accessible reason | `components.na` |
| Times | `5:45 PM EDT`, `Sep 23, 5:45 PM EDT` (America/New_York via `forward.eastern_offset`) | `time_et`, `datetime_et` |
| Relative age | supplementary only (`11 min ago`) | `age_text` |

Display rounding never turns a marginally negative edge positive or a limit more permissive.
Exact values and UTC timestamps are in Details.

## 6. Shell and navigation

Breakpoints: mobile < 768, tablet 768–1199, desktop ≥ 1200. Content max width 1600px, centred.

- **Header** (sticky; 56px mobile + safe area, 64px ≥768): 4×20px orange rule + wordmark;
  right side: account name (desktop), **SHADOW · NO REAL MONEY** (12px), 44px bell → Alerts
  with a count of real attention items only. Fits at 360px without wrapping. No red banner.
- **Demo strip**: `SYNTHETIC UI DEMO — …`, amber, persistent, demo mode only.
- **Tape** (below header; 52px mobile, 48px desktop, sticky on desktop only): section 7.
- **Navigation** — labels and routes are fixed:

| Label | Route |
|---|---|
| Terminal | `/` |
| Markets | `/opportunities` |
| Portfolio | `/positions` |
| Outcomes | `/outcome-board` |
| Risk | `/risk` |
| Research & Data | `/experiments` |
| Alerts | `/alerts` |
| More | `/more` (mobile/tablet index) |

  Desktop: 192px rail, groups {Terminal, Markets, Portfolio, Outcomes} and {Risk, Research &
  Data, Alerts}; active = 2px orange left marker, raised background, 500 weight. Tablet:
  72px rail, icon plus visible label. Mobile: fixed bottom bar, 5 equal targets (Terminal,
  Markets, Portfolio, Outcomes, More), 20px icons, 12px labels, 64px + safe area; active in
  accent. Main content bottom padding ≥ 88px + safe area. `viewport-fit=cover`, zoom enabled.
- Icons: the Lucide subset in `static/icons.svg` (inlined sprite; one stroke weight).

## 7. Market tape

Captured quotes only, from `data.observed_board` (latest target day's decision and re-check
books). Up to 12 items: open-position markets first, then alphabetical; one per venue +
native market + side. Each item: outcome label, venue, side, captured ask, and a change only
when two comparable observations of the same side exist. Labelled **captured**, never
LIVE. Manual swipe; desktop arrow buttons (JS); no marquee. Clicking opens market detail.
Zero quotes: one strip "No quotes captured yet." with a Markets link. Evidence read error
(`observed` is ERROR): one strip "Captured quotes unavailable (read error)." with the error icon
and a Markets link; a read failure never uses the zero-quotes wording.

## 8. Pages (order and hierarchy are fixed)

**Terminal `/`** — mobile order: header+tape; "Market overview" + date/time; status line (≤2
lines + Details); account switch; single summary (Shadow equity · cost basis; 2×2: Tradable
cash, Committed, Open risk, Realized today); Market board (tabs All/Qualified/Watching/Blocked,
≤5 rows, View all markets); What matters today (≤3); Activity (≤5); collapsed System &
evidence. At 390×844 the first row or the board's informative empty state starts within
~650px. Desktop: summary band, then 8-column board + 4-column rail (status + next scheduled
windows, What matters today, Activity). The status line never collapses an invalid capture
into "healthy": e.g. "Capture needs attention · Sep 23 — Missing forecast and decision
evidence. Report refreshed 11 min ago."

**Markets `/opportunities`** — controls in order: search, domain strip (All, Weather, Sports,
Politics, Economics, Financial, Other), sport/league filter when Sports is selected, then
Venue, State, Cash release, Sort; results/coverage line; board. Defaults: All observed, cash
release All, sort = qualified by net edge, then soonest known cash release, then title/ID;
unknowns last. Board columns (desktop ≥1060px container): Market/outcome | Venue | Quote |
Model | Net edge | Size | Tradable again | State | details. Narrower containers drop to five
columns; phones compose the same view model as a list item (metadata, title, two ≥44px quote
tiles, model/edge/ETA, state text + icon). Non-binary payoffs are research-only, never fake
YES/NO tiles. Empty result: "No matches in captured data" + Clear filters.

**Market detail `/market?venue=&id=&side=&account=`** — identity validated against stored
records. Order: breadcrumb; labels + full question; quote summary; price history (only with ≥2
same-side observations); our assessment (never 50% for unknown); across venues (no
equivalence claimed without evidence); research sizing (read-only challenger); capital & timing; decision preview marked **Read-only ·
Trading disabled**; rules & evidence disclosure. Desktop: main column + 320px inspector.

*Across venues* renders `best_price.compare` (ADR 0027) for the page's side at the recorded
decision's time and evaluated size; no size is ever entered. Its four claims (best observed
quote, best gross cost for size, best verified total cost, best account-feasible route) are
shown side by side, each with its own figure or its reason for absence; there is never one
"best" verdict. Routes ranked by at least one claim come first, routes ranked by none
separately; each shows quote, gross cost, fees (verified, partial, an unverified estimate or
unavailable), verified total or — (never for a stale book), depth, tradable-cash release,
rules status and claim status. Stale routes are named as not ranked. Related markets are
listed as **RELATED MARKET — NOT ECONOMICALLY EQUIVALENT**, unpriced and unranked. States: populated, single captured route, all stale, refused payoff,
not evaluated (no decision, no size, or an earlier target day), no captured book, read error.

*Research sizing* (after Across venues, main column) renders Lane A's read-only
`sizing_counterfactual` panel for the market's latest recorded decision, every side.
It is labelled with the contract's **RESEARCH SIZING - SHADOW SIZING CHALLENGER** label and never
"Recommended bet". It shows the challenger policy's (H) size, verdict, binding constraint,
probabilities, expected net edge, entry price, fee, Kelly and pre-cap amounts, bankroll basis and
capital horizon; caps and fill details in a disclosure; a compact A–H policy comparison; the
top-of-book caveat; limitations. Every figure is the contract's string, only formatted. A side or
panel the engine cannot compute shows its named reason (No model, Fees unsupported, Stale quote,
Rules unresolved, Insufficient uncertainty evidence, Risk state unavailable, Unsupported payoff,
…). No stake input, slider, submit or order action exists. States: sized, computed zero, a side
unavailable, the whole panel unavailable, contract not installed, read error.

**Portfolio `/positions`** — account, metric strip with basis labels; Open / Settling /
Closed / All; position rows; "How these balances are calculated"; settlement evidence. Never
counts unrealized gains; an unreadable ledger is an error, not an empty portfolio.

**Outcomes `/outcome-board`** ("What matters today") — summary strip, rows ranked by
canonical account impact, exposure bars from canonical exposure, max loss/gain labelled as
bounds, "Why it matters" disclosure.

**Risk `/risk`** ("Risk & capital") — metric band; capacity with the canonical
new_risk_allowed verdict and exact amount; limit rows (used/limit only with compatible
definitions); capital release windows (canonical buckets, labelled non-cumulative); starter
rule; withdrawal **Not enabled**; policy details disclosure.

**Research & Data `/experiments`** — tabs Research | Data sources. Research: title, ID,
research stage, historical result, forward valid days, next preregistered look, progress
labelled "Observations toward the next scheduled evaluation", limitations, details. Data
sources: The Odds API pilot card (`odds_pilot.dashboard_status`: "The Odds API — SETUP NEEDED" and
so on; active only with a stored live read that held offers, never "connected"; offered odds are
research only, never executable), then the Odds capture targets section (`data.odds_capture_targets`
over the stored `odds_capture_targets` / `odds_capture_transitions` rows): a summary (targets, captured,
missed, failed, open, last recorded change), the latest five targets whose intended time has passed and
the next five as rows (event, horizon, intended time ET, actual receipt, state, credits of the one paid
call with how many targets shared it, books returned parsed from the stored snapshot, freshness by the
source's odds max age; an open target past its canonical deadline is "Overdue"), and every target in an
"All targets" disclosure. States: populated, no targets, no captures yet, overdue (stale record),
missed/failed/skipped/superseded rows, paid captures paused (the card's COST_BLOCKED, KEY_REJECTED,
QUOTA_EXHAUSTED, QUOTA_UNKNOWN, DISCOVERY_STALE), source unavailable, read error. Venues (Tested ≠ connected), collected sources with freshness,
fee verification, venue registry and full receipt in disclosures.

**Alerts `/alerts`** — Needs attention, Standing conditions, Recent notifications, Tests,
verification checks and diagnostics, Expired; delivery state stated honestly (recorded locally;
phone delivery not recorded; stored and never pushed where the origin policy holds it). Origins
never mix: only production (or an unrecognised origin, failing closed) can need attention or
count on the bell; each notification and failure record carries its origin badge.
`last_failure.json` is always a production incident. A `last_verification.json` record is a
verification check when root confirmed it, and "Verification record (root confirmation not found
or expired)" otherwise, never an incident. Terminal Activity lists production events only. **More
`/more`** — links to Risk, Research & Data, Alerts, System & evidence.

**Gallery `/gallery`** — demo mode only; every component with synthetic fixtures.

## 9. State vocabulary (`presentation.STATES`)

| Situation | Visible treatment |
|---|---|
| Never collected | Waiting for first capture |
| Read failed | Data unavailable + safe reason |
| Report fresh, capture invalid | Capture needs attention / Capture incomplete + separate report time |
| Next capture scheduled | Next scheduled window … (collector schedule, not proof the timer runs) |
| Evaluation not run | Not evaluated yet |
| Ran, nothing qualified | No qualifying opportunities / Not qualified |
| No model | No model for this market |
| No comparable venue | No equivalent venue price verified |
| Stale quote | Stale quote — not actionable |
| Comparator route, judged at its decision time | Fresh at decision time (plus the book's age now) / Stale at decision time — not ranked |
| Stage A pass | Historical validation passed (never "Profitable") |
| Zero capacity | New positions halted + binding reason |
| Seven-day rule fails | Outside starter horizon |
| No account permission | Access not connected |

Unknown codes render neutral and keep the code in the badge title and in Details. Empty
states are small: title, one or two sentences, known times, one real action.

## 10. Charts and motion

Charts draw persisted observations only (no interpolation through gaps, no single-point
trend), with units, time range and an accessible table. Transitions 120ms (hover/focus) and
160ms (disclosure); none under `prefers-reduced-motion`. No polling, streaming, service
worker, sound or gamified urgency. Refresh reloads stored data only.

## 11. Security

CSP: `default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self';
connect-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none';
form-action 'self'`. No inline styles, scripts or handlers (tested). GET/HEAD only. Host
allowlist unchanged (loopback, approved bind host, exact Tailscale Serve name). Query values
validated per route (`presentation.ROUTE_PARAMS`); unknown values → safe 400; unknown names
ignored. Static files from an exact allowlist under a content-hash version path, immutable
cache; everything else `no-store`. Untrusted text is escaped; generated URLs are same-origin
and URL-encoded.

## 12. Acceptance (every user-visible change)

- Real, empty, stale, error, unsupported and blocked states implemented.
- No body-level horizontal overflow at 360, 390, 430, 768, 1440, 1920 (normal and 200% text);
  no clipped numbers; primary nav never wraps; last link reachable above the bottom bar.
- Touch targets ≥ 44×44 CSS px (a product standard, not the WCAG 2.2 AA minimum); keyboard
  operable; visible focus; landmarks, headings, labels, selected-tab semantics; no
  colour-only meaning; measured contrast ≥ 4.5:1 text, 3:1 large text and controls.
- Fonts load from this application; no third-party request.
- Budgets: CSS ≤ 70 KiB, JS ≤ 35 KiB, first-view fonts ≤ 300 KiB (uncompressed).
- `python -m pytest tests/test_dashboard.py tests/test_dashboard_terminal.py` passes;
  `tests/browser/capture.py` screenshots reviewed on mobile and desktop.

## 13. Evidence tooling

`tests/browser/fixture_states.py` (early, demo, broken, odds, odds_issues), `tests/browser/serve_fixture.py`,
`tests/browser/capture.py` (Playwright, dev-only; blocks non-loopback requests; audits
overflow, targets, fonts, first-row position). Emulated WebKit is not a physical iPhone.

## 14. Amendments

A design change is a dated entry here: what changed, why, who approved it (owner or a recorded
directive), and the screenshots that justify it.

- **2026-09-23 — tape read-error state; plain outcome labels.** Approved by the owner's
  session request (Terminal v1 follow-ups; merge reconciliation assigned by the 2026-09-24
  next-build-chunk directive, Lane B). (1) §7: the tape gains an unavailable variant,
  so an unreadable evidence database reads "Captured quotes unavailable (read error)."
  instead of the zero-quotes wording, which had presented a read failure as an empty day.
  (2) Outcome group titles on Outcomes and Terminal "What matters today" use
  `presentation.cluster_label`: known cluster patterns only, raw id otherwise, raw id always
  in "Why it matters". No token, layout or component-style change. Screenshots: the
  `early`, `demo` and `broken` states at 390x844 and 1440x900 (`tests/browser/capture.py`),
  reviewed locally by the author and described in PR #53 (not attached).
- **2026-09-23 — honest board coverage on read error; plain labels on position rows.**
  Approved by the owner's session request (Terminal v1 follow-ups, second batch; merge
  reconciliation assigned by the 2026-09-24 next-build-chunk directive, Lane B). (1) The
  Terminal "Market board" section meta read "No captured books" when the evidence database
  could not be read; it now reads "Captured books unavailable" on ERROR and keeps "No captured
  books" for NO_DATA. The Markets page subtitle likewise reads "Captured coverage unavailable
  (read error)." on ERROR (its coverage line already did). (2) Portfolio position row
  subtitles use `presentation.cluster_label`; the raw id stays in "Position details"
  (`cluster`). No token, layout or component change. Screenshots: `early`, `demo` and `broken`
  at 390x844 and 1440x900, reviewed locally by the author and described in PR #54 (not
  attached).
- **2026-09-24 — Across venues from the comparator.** Approved by the 2026-09-24 next-build-chunk
  directive, Deliverable 3 (`docs/owner/2026-09-24-next-build-chunk-directive.md`). §8 market
  detail: the "Across venues" slot now renders `best_price.compare` (four separate claims,
  per-route rows, related markets unranked, stale routes named) instead of a fixed "No
  equivalent venue price verified" state. New component `venue_comparison` built from the
  existing facts, row, badge, state-text and disclosure components; new state words for route
  exclusions and rules equivalence in `presentation.STATES`. §9 gains the comparator's
  decision-time freshness row: the comparator judges a book at the recorded decision time, so it
  says "at decision time" and never plain "fresh" beside the Quote section's current-time
  verdict; a single captured route reuses "No equivalent venue price verified". No token, CSS,
  layout or navigation change. Markets rows get no comparison indicator: §8 fixes the board
  columns. Screenshots: 360x800 and 1440x900 (`tests/browser/capture.py`), reviewed locally by
  the author and described in PR #65 (not attached).
- **2026-09-24 — Research sizing panel.** Approved by the 2026-09-24 next-build-chunk directive,
  Deliverable 2. §8 market detail gains a "Research sizing" section after "Across venues" that
  renders Lane A's `sizing_counterfactual` panel contract (read-only; one memoized replay per
  request). New component `research_sizing` built from the existing facts, badge,
  table, disclosure and state components; new state words for the sizing-v2 verdicts. No token,
  CSS, layout or navigation change. Risk & capital is unchanged. Screenshots: 360x800 and
  1440x900 (`tests/browser/capture.py`), reviewed locally by the author and described in PR #69
  (not attached).
- **2026-09-24 — Alerts by origin; The Odds API card.** Approved by the 2026-09-24 next-build-chunk
  directive, Deliverables 5 and 6 (UI parts). §8 Alerts gains the "Tests, verification checks and
  diagnostics" group and origin badges (notifications.Origin); `last_verification.json` joins
  `last_failure.json` (production only) and is a check, confirmed or not; Terminal Activity shows
  production events only. The demo's synthetic notifications carry origin DEMO, so they appear in
  that group (the gallery shows every origin, production included). §8 Research & Data sources gains the
  Odds API card. New state words for origins and the Odds pilot states; new component
  `odds_status_card`. No token, CSS, layout or navigation change. Screenshots: 360x800 and
  1440x900 (`tests/browser/capture.py`), reviewed locally by the author and described in the PR
  (not attached).
- **2026-09-24 — Odds capture targets on Data sources.** Approved by the owner directive of
  2026-09-24 evening (Freshness Fabric v1 + sports, "Terminal v1": the Odds capture target/history
  table; coordinator contract C4; `docs/owner/2026-09-24-freshness-fabric-sports-directive.md`).
  §8 Research & Data gains the "Odds capture targets" section right after The Odds API card (no new
  navigation). It is composed in `views/research.py` (`odds_targets_section` / `odds_targets_body` /
  `target_row` / `targets_table`) from the existing section, facts, row, badge, state-text,
  empty/blocked/error, disclosure, kv and table components; no new component, token, CSS or layout.
  New state words: the target states (CAPTURED, CAPTURING, MISSED, SKIPPED_BUDGET, DEFERRED,
  SUPERSEDED) and one target's freshness (TARGET_OVERDUE, TARGET_PENDING, TARGET_NO_CAPTURE); the
  existing PLANNED, FAILED, QUOTA_* and SETUP_NEEDED words are reused; an unknown state is neutral
  with its code. Labels were shortened after the 180 px (360 px at 200% zoom) review so a row's
  state capsule never widens the page. Screenshots: fixture states `odds` and `odds_issues` at
  360x800, 390x844, 430x932, 768x1024, 1440x900 and 1920x1080 (Chromium), 390x844 and 1440x900
  (WebKit), and 180x400 / 720x450 as 200% zoom of 360 / 1440 (`tests/browser/capture.py`), reviewed
  locally by the author and described in the PR (not attached).
