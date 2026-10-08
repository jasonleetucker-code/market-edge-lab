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
Venue, State, Cash release, Sort; results/coverage line; a paused line when the selected account's canonical risk report allows
no new risk ("New positions halted · paused" or "Limit breached · paused", with a Risk link; "Risk capacity
unavailable (read error)" for an unreadable report; nothing for an account with no registered policy); board. Defaults: All observed, cash
release All, sort = qualified by net edge, then soonest known cash release, then title/ID;
unknowns last. Board columns (desktop ≥1060px container): Market/outcome | Venue | Quote |
Model | Net edge | Size | Tradable again | State | details. Narrower containers drop to five
columns; phones compose the same view model as a list item (metadata, title, two ≥44px quote
tiles, model/edge/ETA, state text + icon). Non-binary payoffs are research-only, never fake
YES/NO tiles. Empty result: "No matches in captured data" + Clear filters.

**Market detail `/market?venue=&id=&side=&account=`** — identity validated against stored
records. Order: breadcrumb; labels + full question; quote summary; price history (only with ≥2
same-side observations); our assessment (never 50% for unknown; journey J3 adds the recorded fee per contract,
the evaluated size, and a case block: mechanism, evidence and every rejection reason, see below); across venues (no
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

*Our assessment, case block* (Market v1 J3). Mechanism: the protocol's `mechanism`, or a legacy manifest's
`economic_rationale` (labelled as such), of the experiment linked to the decision's own `policy_id`
(`data.POLICY_EXPERIMENTS`: only rules in code; any other policy reads unknown with its reason and never borrows
another experiment's text), marked unproven. Evidence: the experiment's registry status and Stage A verdict as
neutral capsules with "a historical validation is not an edge". Rejection reasons: every recorded reason in plain
words with its code; "None: qualified at decision time" for a qualified decision; unknown when none is recorded.
A missing fee or size is the unknown marker, never 0.

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

**Execution journeys (read-only; Market v1 J1/J4/J5/J6)**: `/setup`, `/experiments/wallet`,
`/positions/execution` and `/risk/automation`. They are reached from More and joined by one journey tab strip,
with no new global navigation item.
- **Data source.** They render `execution_status.json` (written by `execution/status_export.py`; the dashboard
  never imports the execution package, ADR 0043) and `wallet_intel` research.
- **Labels.** Every execution figure is labelled with its environment (FIXTURE today). "Actual holdings" reads
  "Access not connected" until approved real account reads exist. The wallet page shows demonstration A only in
  demo mode, labelled SYNTHETIC; in production it shows the blocked state.
- **States.** Missing export, error, stale, no journal, known-empty versus unknown, paused and incomplete
  reconciliation. Unknown is "—", never 0.
- **No controls.** No arm, approve, cancel or send control exists. The private command surface (J9) is separate,
  later work.

**Outcomes `/outcome-board`** ("What matters today") — summary strip, rows ranked by
canonical account impact, exposure bars from canonical exposure, max loss/gain labelled as
bounds, "Why it matters" disclosure; an overdue group reads "Overdue · still open after its expected settlement".
Then (Market v1 J8) "Execution positions by outcome", from `execution_status.json` with the journeys' shared
export states (`views/ops_common`): first the blocked "Actual positions: access not connected"; then the export
status line, environment capsule, reconciliation and paused lines; one row per Kalshi event (the settlement's own
event ticker, else `kalshi.event_ticker_of`), held, settled and exited-before-settlement markets together, state
Open / Partly settled / Settled / Exited before settlement / Holdings unknown (none green); facts: positions held
(unknown when no snapshot lists positions, never 0), settled markets, max loss and settles-by unknown (the export
records no cost basis, worst case or settlement time per position); the markets table (side, held, result,
revenue, fees, venue-reported realized P&L signed and never coloured, unknown before a P&L baseline) in a
disclosure. States: missing export, error, refused environment, mismatch, no journal, journal error, stale,
paused, reconciliation incomplete, holdings unknown, known empty, populated. No ranking by impact: none is
computed.

**Risk `/risk`** ("Risk & capital") — metric band; capacity with the canonical
new_risk_allowed verdict and exact amount; limit rows (used/limit only with compatible
definitions); capital release windows (canonical buckets, labelled non-cumulative); starter
rule; withdrawal **Not enabled**; policy details disclosure.

**Research & Data `/experiments`** — tabs Research | Data sources. Research opens with "Research stages"
(Market v1 J7): Candidate (DRAFT without an active family slot), Development (DRAFT with an active slot, or
PREREGISTERED), Shadow (RUNNING), Qualified (only the STRATEGY_QUALIFIED readiness track, today NONE, as a known
empty state; no registry status qualifies a strategy), Rejected (CONCLUDED_FAIL, ABANDONED), plus "Concluded · not a
qualification" and "Status unrecognized" when non-empty; each experiment row shows its registry status, family slot
(QUEUED reads "Queued · waiting for a family slot"), protected evidence from protocol configuration only (Family A
outcome labels hidden, prohibited label scopes, holdout windows counted, never shown; an unreadable protocol is
treated as protected), EXP-001's forward valid days (with "as of … · stale, not current" when the collector status
is stale, also on its card and progress line) and "Incomplete" for manifest problems or a missing protocol. No
outcome, label or result count is read; nothing is green. Then: title, ID,
research stage, historical result, forward valid days, next preregistered look, progress
labelled "Observations toward the next scheduled evaluation", limitations, details; then one
"Economic evidence · A" and one "Economic evidence · B" section (the two research families at most; no
new navigation). Family A renders `sports_evidence.terminal_view` (schema sports-evidence-view/1; EXP-002
outcome labels hidden: no resolution state, result or count, "Hidden · holdout protection"): the contract's label "PAIRED RESEARCH EVIDENCE — NOT AN EDGE CLAIM", the family state,
protocol state (from the experiment registry), as-of and evidence window, due horizons with games, NFL
weeks, not-yet-due and superseded, paired horizons, largest exclusion, outcome labels (hidden),
probability / relation (CONDITIONAL_MAPPING, never equivalent), edge at a size ("Not defensible" with its
first reason), protocol-eligible opportunities (research_evidence attrition), the economic-screen verdict
(research_economics), next action and blocker; the EXP-002 gate line (`sports_evidence.exp002_gate_line`:
gate v3, a diagnostic with no pass state; freeze eligibility shown separately and always "Not eligible"; nothing
green); in disclosures the join diagnostics, missing evidence (the
report's gaps), protocol attrition (None reads unavailable, never 0), the screen's reasons, the size ladder
of the latest pre-label (T-24h / T-6h) paired book (depth status, all-in cost or its absence, fee state) with the fill modes, costs
and inputs with their evidence class, and provenance. Family B renders the newest EXP-003 payoff-scan result
file (`experiments/EXP-003-*/results/payoff_scan_*.json`, by evaluation as-of, found through the registry),
checked only with `payoff_constraints.verify_result_provenance` against EXP-003's own evidence-use log; nothing
is evaluated per request and a page view writes nothing (a registered known unlogged consumer). It shows the
label "PAYOFF RESEARCH — NOT A CAPTURED RESULT", the result's source store prominently (a laptop or fixture
result reads "not production evidence"), as-of and event window, proof completeness per set
(PROVEN / INCOMPLETE / UNSUPPORTED with reasons), claims per size with their reasons (NOT_EVALUATED included),
settlement costs from the evaluator's structured fields ("Settlement cost unknown", or "Refund unknown" for a
state it could not value; never parsed from reason text), orphan-leg exposure as an unsigned worst-state loss
(never a signed or positive figure), execution none,
and provenance and verification in a disclosure. A figure appears in the surplus column only for the
evaluator's CONDITIONAL_FULL_FILL_SURPLUS claim ("conditional on every leg filling · not captured
arbitrage"); every other claim shows its claim, never a number. Never profit for missing outcomes, never
"arbitrage" as a result, never a funded or approved-bankroll state, no edge score, nothing green. States:
populated, partial, stale, empty, unsupported, unknown (not configured or not readable), error, malformed;
Family B populated, stale (newest evaluation older than 8 days), empty (no result file), blocked (EXP-003 slot
not ACTIVE), error (unreadable, over the file or byte bound, not verified, or an evaluation as-of later than now or than
the file's generation time: never a silent fallback to an older file and never POPULATED forever; a link is
never followed), not available (evaluator or registry absent), malformed. Data
sources: first the Source freshness section (the Freshness Fabric supervisor's `freshness.json`,
schema `freshness-fabric-status/1`, read as written: what is fresh, what is due next and why; the sources needing attention
(missed, blocked, failing or degraded, disagreeing) as rows and every source by domain in a disclosure; every
source's acquisition mode with EXTERNAL_SCHEDULE shown as "supervised only · run by <schedule owner>";
freshness, schedule state, health, next due, last successful receipt, research/decision usability, why,
and (Market v1 J2) last attempt, completeness (the fabric's health in words: no partial or failed result, partial or
degraded, latest attempt failed, else unknown), latest failure (a recent miss, else a failing source's own reason;
"None recorded" only when healthy), provenance (the policy's description and version) and cost (the policy's budget
or quota words, else unknown: "cost not recorded", never $0), misses and disagreements; the report's own age judged by `generated_at_utc`; a protected-window deferral
names the window (the Kalshi close-tick guard included) and the carried evaluation
(`sources_evaluated_at_utc`, `carried_from_utc`); states: populated, stale report, partial, deferred with
or without a carried evaluation, not written / not configured, read error or foreign schema), then The
Odds API pilot card (`odds_pilot.dashboard_status`: "The Odds API — SETUP NEEDED" and
so on; active only with a stored live read that held offers, never "connected"; offered odds are
research only, never executable), then the Odds capture targets section (`data.odds_capture_targets`
over the stored `odds_capture_targets` / `odds_capture_transitions` rows): a summary (targets, captured,
missed, failed, open, last recorded change), the latest five targets whose intended time has passed and
the next five as rows (event, horizon, intended time ET, actual receipt, state, credits of the one paid
call with how many targets shared it, books returned parsed from the stored snapshot with a caveat
when the response had parse problems, a capture's freshness judged at receipt ("Fresh at receipt",
historical, never current); an open target past its canonical deadline is "Overdue"), and every target
in an "All targets" disclosure, whose books are the runner's record at capture (only the rows shown
parse a stored response; parsed captures are memoized, bounded). States: populated, no targets, no captures yet, overdue (stale record),
missed/failed/skipped/superseded rows, paid captures paused (the card's COST_BLOCKED, KEY_REJECTED,
QUOTA_EXHAUSTED, QUOTA_UNKNOWN, DISCOVERY_STALE), source unavailable, read error. Each captured
row shown carries a "Consensus at this capture · RESEARCH BENCHMARK — NOT EXECUTABLE" disclosure: Lane
C's `odds_consensus.consensus_for_event(store, event, as_of=the capture's receipt time)`, per exact
proposition (moneyline, each spread line, each total line): the consensus probability per outcome
(median of the books' de-vigged probabilities), range and MAD (method named), contributing books vs books
quoting the market at any line, freshness (`freshness_as_of`, worst of books) and earliest/latest contributing update;
offered prices as received and each book's de-vig in a separate nested disclosure and separate
tables, never in the consensus table; unsupported groups with their reason codes. States: populated,
insufficient books, unsupported, stale/unknown freshness, this capture unusable with an earlier one
shown and newer unusable captures listed (`newer_unusable`), failed closed, no consensus, not
installed, read error, and EXP-002 label proxy: an NFL event read at T-60m or after its T-6h decision cutoff
reads "Hidden · EXP-002 label proxy" in place of its probabilities, prices, lines and de-vigs
(`odds_consensus.withhold_label_proxies`), with its receipt, freshness and book and proposition counts kept and
no reveal path. After it, "Polymarket US related markets" (Lane B's
`polymarket_sports.terminal_view`, pm-sports-status/1): the access gate (an owner risk decision, never a
terms clearance; blocked when none is recorded), the catalog state (a filtered listing, never a full catalog;
partial, stale, failed or no scan), then per Odds API event of the target rows shown the relationship
("RELATED MARKET — NOT ECONOMICALLY EQUIVALENT", ambiguous, or none) with reasons and every rule check, the
latest research book capture (YES bid / ask, sizes, receipt, freshness at capture) with the
"Polymarket US (gateway.polymarket.us public API)" attribution on the figures, and the capture targets'
states; a capture at T-60m or received after EXP-002's T-6h decision cutoff (a proxy for its labels) reads
"Hidden · EXP-002 label proxy" in place of its prices, sizes and depth, there and in the capture attempts and
All events table, with its status, receipt and freshness kept and no reveal path; every event in a disclosure; each Odds capture target row names its event's relationship. Never
ranked, never "cheaper", nothing green; a partial, stale or missing scan never reads as "no market". Venues (Tested ≠ connected), collected sources with freshness,
fee verification, venue registry and full receipt in disclosures. Collected sources rows (J2) add records,
provenance (the source registry's access tier, status and credential kind), due (unknown: "not scheduled in this
record: see Source freshness") and cost (unknown: the registry has no cost field).

**In-play research `/experiments/inplay`** (#122; nav Research & Data; no global item) — the
`inplay_view` contract (inplay-view/1) as: label "IN-PLAY RESEARCH · NOT LIVE · NOT AN EDGE CLAIM",
a mode capsule (Fixture replay · not live, Synthetic replay · not live, No in-play source authorized;
never LIVE) and a state capsule whose populated word follows the mode (Fixture, Synthetic or Recorded evidence); a status line with the replay clock ("the fixture's time, not now");
Position · simulated (contract, game, book reconstruction state and age at the replay clock, coverage,
market state, simulated initial / remaining inventory, reserved by resting sales; reconstruction details
and every kept failure in a disclosure); Source and state validity (2026-09-30: evidence status and data kind,
source and source family, content age by publication clock, the game state the quote is declared to reflect —
"Unknown: not declared by the source" otherwise — and decision validity "Valid at replay clock", "Invalidated ·
recompute" or "Review required" with its reason code; clocks, context, all reasons and a latency-stage table where
unmeasured is not zero in a disclosure; the game clock is never shown as a time); Policy proposal (action "· proposal only", decision "Proposed ·
not sent" or "Blocked · no new risk", quantity, limit, execution assumption, primary reason (the decision's own reason, never the fee caveat; every reason in Policy details); exit proceeds
estimate at size with gross at displayed bids, fees, net "not profit" — unknown fees read "after-cost
figure unavailable", never a number); Hold versus exit (a note first: "A synthetic cohort of N games, not this contract (<ticker>)"; then one row per arm and execution semantics with
replay P&L gross and net, change vs hold, worst and best entry — signed, never coloured; oracle diagnostics
and provenance in a disclosure); Fill-conditioned economics (2026-09-30: one row per arm with its execution mode
— taker, book maker — evidence "Simulated · not actual", simulated fills, gross and net (fee unknown reads
"after-cost figure unavailable"), peak collateral, return on deployed, turnover of total capital as a multiple,
and the missing denominators named in the row subtitle; RFQ reads "not evaluated"; reasons in a disclosure);
Blocker and approval (authority, the pilot "PROPOSED, NOT APPROVED",
blocker; assumptions in a disclosure). Production reads "No in-play source is authorized". No balance,
edge score, input or trade control. States: populated, empty, stale, partial, unsupported, paused, error,
not authorized, invalidated, state unknown; `/gallery/inplay` (demo only) renders each from fixtures.

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

`tests/browser/fixture_states.py` (early, demo, broken, odds, odds_issues, freshness, freshness_deferred, polymarket,
polymarket_issues, polymarket_label_proxy, odds_label_proxy, economics, economics_issues),
`tests/browser/serve_fixture.py`,
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
  with its code. After the independent review of #80: only the captures behind the rows shown are
  parsed (memoized, bounded), history rows use the runner's recorded books, parse problems are a
  caveat, a capture's freshness is judged at receipt, and the pilot's sport filters the rows. Labels were shortened after the 180 px (360 px at 200% zoom) review so a row's
  state capsule never widens the page. Screenshots: fixture states `odds` and `odds_issues` at
  360x800, 390x844, 430x932, 768x1024, 1440x900 and 1920x1080 (Chromium), 390x844 and 1440x900
  (WebKit), and 180x400 / 720x450 as 200% zoom of 360 / 1440 (`tests/browser/capture.py`), reviewed
  locally by the author and described in the PR (not attached).
- **2026-09-24 — Sportsbook consensus at a capture.** Approved by the owner directive of 2026-09-24
  evening ("Terminal v1": sportsbook consensus labelled "RESEARCH BENCHMARK — NOT EXECUTABLE";
  contract C4) and the coordinator's phase-3 assignment after Lane C's #79 merged. §8 Research & Data:
  each captured row of the Odds capture targets section gains the "Consensus at this capture"
  disclosure (no new navigation). Composed in `views/research.py` (`consensus_body`, `_proposition`)
  from the existing facts, table, badge, state-text, empty/blocked/error/unavailable, disclosure and kv
  components; no new component, token or CSS. New presentation helpers only: `pp_size` (an unsigned
  probability spread in pp), `odds_market_label`, `freshness_code`. Offered prices and consensus
  probabilities never share a table; a book's margin is shown in signed pp. The contract is read only
  for the captured rows shown, at each capture's receipt time, memoized until an odds snapshot received by that time is added.
  Screenshots: fixture states `odds` and `odds_issues` (a capture with stale, unsupported and
  single-book lines; a later capture whose response lacked the game) and `/gallery` at 360x800 and
  1440x900, 720x450 and 180x400 as 200% zoom (`tests/browser/capture.py`), reviewed locally by the
  author and described in the PR (not attached).
- **2026-09-24 — Source freshness on Data sources.** Approved by the owner directive of 2026-09-24
  evening ("Terminal v1": a freshness/source view that makes clear where the fabric only supervises an
  external timer; contract C4) and the coordinator's phase-2 assignment after Lane A's #81 merged. §8
  Research & Data: Data sources opens with "Source freshness", read from the supervisor's artifact (no
  new navigation, no provider is run by the dashboard). Composed in `views/research.py`
  (`freshness_section`, `freshness_body`, `fabric_source_row`) from the existing section, facts, row,
  badge, state-text, empty/error/unavailable, disclosure, kv and list components; no new component,
  token or CSS. New namespaced state words (SCHEDULE_*, HEALTH_*, SUPERVISOR_*) and presentation helpers
  `prefixed_word`, `mode_label`, `window_label`, `duration_text` (formatting of the artifact's seconds).
  After the independent review of #91: a stale or undated report fails closed (no positive verdict is
  green, usability reads "Not decision-grade: report stale / time unknown"); verdicts are labelled "at
  evaluation, <time>"; one freshness-to-state mapping (`freshness_code`, shared with the consensus view);
  an unknown namespaced code is neutral; malformed JSON values render unknown or an error state, never a
  failed page; free text is scrubbed by the fabric's own rule; the artifact is read within the
  supervisor's 256 KiB bound.
  Screenshots: fixture states `freshness` and `freshness_deferred` and `/gallery` at 360x800, 1440x900,
  720x450 and 180x400 (200% zoom) (`tests/browser/capture.py`), reviewed locally by the author and
  described in the PR (not attached).
- **2026-09-24 — Polymarket US related markets.** Approved by the owner directive of 2026-09-24 evening
  ("Terminal v1": a related Polymarket US market labelled "RELATED MARKET — NOT ECONOMICALLY
  EQUIVALENT" and never ranked as cheaper; contract C4) and the coordinator's phase-4 assignment after
  Lane B's #84 merged. §8 Research & Data: Data sources gains "Polymarket US related markets" after the
  Odds capture targets, and each target row gains a "Polymarket US" fact (no new navigation). Composed in
  `views/research.py` (`pm_related_section`, `pm_related_body`, `pm_event_row`, `pm_market_block`) from
  the existing section, facts, row, badge, state-text, empty/blocked/error/unavailable, disclosure, kv
  and table components; no new component, token or CSS. New namespaced state words (PM_EVENT_*,
  PM_CATALOG_*, PM_ACCESS_*, PM_CHECK_*, PM_TARGET_*), none green. After the independent review of #94:
  only a filtered listing read in full may say "no related market in the listing read" (any other or
  unknown catalog state reads "not checked" or "partial or stale"); capture history is read for exactly
  the events rendered, and one that was not read says so (never "no capture target planned"); an open
  target past its deadline reads "Overdue · not captured" (the pilot's own rule); every Polymarket table
  carries the attribution, the research label and freshness at capture; a malformed view is an error
  state; an unusable latest scan attempt beside an older usable listing is said. Screenshots: fixture states
  `polymarket` and `polymarket_issues` (the recorded gateway bytes replayed through the pilot's own
  entry points) and `/gallery` at 360x800, 1440x900, 720x450 and 180x400 (200% zoom)
  (`tests/browser/capture.py`), reviewed locally by the author and described in the PR (not attached).
- **2026-09-25 — Economic evidence on the Research tab.** Approved by the owner's Economic Evidence v1
  directive of 2026-09-25 (section 15: a compact evidence/economics section in the existing Terminal for the
  two families, no new navigation, no asset-class dashboards), recorded in `docs/EXECUTION_PLAN.md` by PR A
  (#100); strategy handoff `docs/strategy/CLAUDE_ECONOMIC_EVIDENCE_V1.md` section 9. §8 Research & Data:
  the Research tab gains "Economic evidence · A" and "Economic evidence · B" after the experiment cards.
  Composed in `views/research.py` (`economics_section`, `economics_body`, `family_a_body`, `family_b_body`,
  `_ev_family_a`, `_ev_capacity`, `_ev_protocol_attrition`, `_ev_screen`) from the existing section, facts,
  badge, state-text, empty/blocked/error/unavailable, disclosure, kv, list and table components; no new
  component, token, CSS or navigation. New namespaced state words (EV_STATE_*, EV_PROTOCOL_*, EV_REL_*,
  EV_EDGE_*, EV_SCREEN_*, EV_GAP_*, EV_FILL_*, EV_FEE_*, EV_KIND_*, EV_BASIS_*), none green; a screen
  "Continue" reads "Continue research · not an edge". Each family is a section body, not a row: a row's
  aside capsule narrowed its body to one grid column at 360 px (reviewed and changed before merge). Short
  capsule labels ("Paired evidence", "Partial evidence") and plain numbers in facts keep the section inside
  180 px; the shell's pre-existing 180 px overflow is unchanged (measured the same on main with details
  open). `tests/browser/capture.py` gains `--open-details` (dev-only) to review the tables inside
  disclosures. Screenshots: fixture states `economics`, `economics_issues`, `odds` and `early` at 360x800,
  1440x900, 720x450 and 180x400 (zoom-equivalent), and 360x800 and 1440x900 with 200% root text, details
  closed and open; `/gallery` at the same sizes (Chromium emulation, not a physical phone), reviewed locally
  by the author and described in the PR (not attached).
- **2026-09-25 — Economic evidence · B from the EXP-003 result file.** Approved by the coordinator's Section B
  plan under the owner's Economic Evidence v1 directive (2026-09-25; `docs/EXECUTION_PLAN.md`), after PR B (#102)
  merged. §8 Research & Data: "Economic evidence · B" renders the newest verified EXP-003 payoff-scan result
  instead of "Not yet available". Composed in `views/research.py` (`family_b_body`, `_payoff_view`, `_payoff_set`)
  from the existing facts, badge, state-text, row, table, list, kv, disclosure and empty/blocked/error/unavailable
  components; no new component, token, CSS or navigation. New namespaced state words (EV_BSTATE_*, EV_SOURCE_*,
  EV_PROOF_*, EV_QUOTES_*, EV_CLAIM_*, EV_SETTLE_*, EV_STATE_BLOCKED), none green; the one positive claim reads
  "Conditional full-fill surplus · not captured". Page views write no evidence-use event: the producing CLI run
  logs its own, and the display is registered in `research_evidence.KNOWN_UNLOGGED_CONSUMERS`. A
  `<result>.source.json` sidecar is store-provenance metadata: it is skipped as a result and named in the
  provenance disclosure. A set with no size evaluated says why (its quote validity and reasons). The set-construction
  method and the input-hash definition are in the provenance, read only through `payoff_constraints.set_construction_of`
  and `input_hash_definition_of` (#105). A helper that is absent or raises leaves the value unavailable with its
  reason; it is never guessed. A legacy set construction carries a note that its INVALID set counts include mid-round
  anchor artifacts and are not comparable with per-round results. A legacy hash definition carries a note that its
  dataset hash is not comparable with a current-definition hash. After the #104 review: settlement costs are read
  from `states_skipped` and `worst_state_surplus` only (new word EV_SETTLE_REFUND_UNKNOWN); orphan exposure is
  unsigned; the surplus column shows only the claim-adjusted figure; a future as-of is an error; the verifier's
  reasons are path-scrubbed. Screenshots:
  fixture states `payoff_production` (the committed production result of #103), `payoff` (a SYNTHETIC production
  result with one conditional surplus) and `payoff_laptop` (the committed laptop result, not production evidence)
  at 360x800 and 1440x900, closed and with every disclosure open, and at 200% root text (Chromium emulation, not a
  physical phone), reviewed locally by the author and described in the PR (not attached).
- **2026-09-28 — In-play research page.** Approved by the owner directive of 2026-09-28 (#122 §21B: a compact
  in-play research view, never LIVE, no invented balances, no trade buttons, no edge score;
  `docs/owner/2026-09-28-exp002-validation-inplay-foundation-directive.md`) and the coordinator's PR C
  assignment. §8 gains "In-play research" at `/experiments/inplay` under Research & Data (no global navigation
  item; a crumb back to Research & Data) and the demo-only `/gallery/inplay`. Composed in `views/inplay.py` from
  the existing page-head, badge, state-text, status-line, section, facts, row, table, kv, list, disclosure and
  empty/blocked/error/unavailable components; no new component, token, CSS or `presentation.STATES` word (plain
  labels are passed to `badge` / `state_text`, codes stay in the title). Money is signed but uncoloured because
  every figure is a fixture or synthetic replay. The Research tab links it with one "In-play research"
  section after Economic evidence · B (a coordinator-granted exception to the claim row). Screenshots
  (`tests/browser/capture.py`), 24 shots, 0 with overflow, clipping, low contrast or foreign requests:
  - Chromium, `demo` state: `/experiments/inplay` and `/gallery/inplay` at 360x800, 390x844, 768x1024,
    1440x900 and 1920x1080, and at 360x800 and 1440x900 with 200% root text and every disclosure open;
  - Chromium, `early` state (production shape: not authorized): `/experiments/inplay` at 360x800 and 1440x900;
  - WebKit: `/experiments/inplay` in both states at 390x844 and 1440x900;
  - Chromium: `/experiments` (the Research tab link) in both states at 360x800 and 1440x900.

  This is Chromium and WebKit emulation, not a physical phone. The shots were reviewed locally by the
  author, described in the PR and not attached.
- **2026-09-29 — EXP-002 label hiding: the gate line and the Polymarket label proxy.** State rules only: no
  new component, token, CSS, layout, component style or navigation. Approved by the owner directive of
  2026-09-28 (§7D: a later price is an outcome too; §21A: the gate line;
  `docs/owner/2026-09-28-exp002-validation-inplay-foundation-directive.md`) and the coordinator's follow-up
  assignment (HANDOFF 2026-09-29, UNRESOLVED "Label proxy" and "UI_CONTRACT §8").
  - (a) Recorded after the fact for #124, which deferred it here. §8 Family A names the EXP-002 gate line:
    gate v3 is a diagnostic with no pass state; outcome access is read from the evidence-use log; freeze
    eligibility is separate and always "Not eligible"; nothing is green. The size ladder is that of the latest
    pre-label (T-24h / T-6h) paired book, because a T-60m Kalshi book is an EXP-002 label. #124's PR describes
    its screenshots.
  - (b) The in-play page of #127 is already recorded (2026-09-28 above) and is not repeated.
  - (c) §8 Data sources, "Polymarket US related markets": a capture at T-60m, or received after EXP-002's T-6h
    decision cutoff, is a correlated proxy for its labels (`docs/research/EXP002_FREEZE_PROPOSAL.md` §4).
    - The pilot's views withhold its prices, sizes and depth and the free text of its reason
      (`polymarket_sports.withhold_label_proxy`). This covers the Terminal and `pm-sports status`.
    - The page reads "Hidden · EXP-002 label proxy" (one new state word, `PM_CAPTURE_LABEL_PROXY`, neutral).
      It appears in the latest research book, the capture attempts ("Hidden") and the All events table.
    - The status, receipt, freshness at capture and target states stay.
    - The Terminal has no reveal path.
    - The gallery gains the SYNTHETIC `label_proxy` state.
    - §13 gains the browser fixture state `polymarket_label_proxy`: `polymarket` plus an ATL@GB T-60m capture
      with SYNTHETIC prices (`fixture_states.pm_t60m_capture`).

    Evidence (`tests/browser/capture.py`, 0 shots with overflow, clipping, low contrast or foreign requests):
    - fixture state `polymarket_label_proxy`, `/experiments?tab=sources`:
      - Chromium and WebKit at 360x800, 390x844 and 1440x900, closed (with screenshots) and with every
        disclosure open;
      - Chromium at 360x800 and 1440x900 with 200% root text;
    - `/gallery` in the `demo` state, Chromium and WebKit at 360x800, 390x844 and 1440x900.

    Element shots of the Polymarket section and the gallery state were reviewed at 390 and 1440 px. This is
    emulation, not a physical phone. The shots were reviewed locally by the author, described in the PR and not
    attached.
- **2026-09-29 (d) — EXP-002 label hiding: the sportsbook consensus proxy.** A state rule only: no new
  component, token, CSS, layout, component style or navigation. Approved by the coordinator's PR D assignment
  (a reviewer's finding after #130: sportsbook data at T-60m tracks the Kalshi T-60m book that is E1's exit label)
  under the owner directive of 2026-09-28 (§7D).
  - §8 Data sources, Odds capture targets, "Consensus at this capture": an NFL event read at T-60m or after its
    T-6h decision cutoff is withheld by the contract's display copy (`odds_consensus.withhold_label_proxies`).
    The cutoff is the Odds event's own kickoff with no tolerance.
    - The one rule is `odds_schedule.is_label_proxy` / `decision_cutoff`, beside the `deadline` it uses.
      Polymarket US (entry (c)) now calls the same rule with its 15-min kickoff tolerance.
    - Withheld: probabilities, offered prices, lines, de-vigs, unsupported groups, and the free text of the
      event's parse problems.
    - Kept: snapshot, receipt, freshness, books quoting and proposition counts.
    - The page reads "Hidden · EXP-002 label proxy" (one new neutral state word, `ODDS_CAPTURE_LABEL_PROXY`).
    - The Terminal and `edge-lab odds consensus` have no reveal path.
    - Other sports and pre-decision captures are unchanged.
  - The gallery gains the SYNTHETIC `label_proxy` consensus state. §13 gains the browser fixture state
    `odds_label_proxy`: `odds` plus the first game's T-60m capture with SYNTHETIC prices
    (`fixture_states.odds_t60m_capture`).

    Evidence (`tests/browser/capture.py`, 20 shots, 0 with overflow, clipping, low contrast or foreign requests):
    - fixture state `odds_label_proxy`, `/experiments?tab=sources`:
      - Chromium and WebKit at 360x800, 390x844 and 1440x900, closed (with screenshots) and with every
        disclosure open;
      - Chromium at 360x800 and 1440x900 with 200% root text;
    - `/gallery` in the `demo` state, Chromium and WebKit at 360x800, 390x844 and 1440x900.

    Element shots of the T-60m target row, with its consensus open, were reviewed in Chromium and WebKit at 390
    and 1440 px. This is emulation, not a physical phone. The shots were reviewed locally by the author, described
    in the PR and not attached.
- **2026-09-29 (e) — Kalshi NHL coverage block (NHL-B, ADR 0040).** One section, no new component, token, CSS,
  layout, component style or navigation. Approved by the coordinator's NHL-B assignment under the owner directive of
  2026-09-29 (`docs/owner/2026-09-29-nhl-prospective-evidence-directive.md`, issue #134).
  - §8 Data sources gains "Kalshi NHL coverage" after "Odds capture targets" (meta: KXNHLGAME · T-6h / T-60m before
    puck drop · development only). It reads `price_observations.nhl_coverage` through `data.Context.nhl_coverage`
    and is drawn with the existing `facts`, `empty_state`, `badge` and note patterns (`research.nhl_body`).
    - Shown: games discovered, Kalshi mapped and unmapped (never guessed), game-horizons planned, captured and missed,
      the next target, the last capture, the schedule state, team-market targets by state, missed reasons, reasons
      nothing is planned, settled reads (count only), fee and shootout-rule states, and the development-only note.
    - Never shown: a price, a size, a depth or a settled result. Outcomes read "Hidden · NHL outcome".
    - A horizon is shown with its nominal label and its actual lead when they differ, e.g. "T-60m nominal · read
      T-85m (protected window)" (`research.nhl_horizon_text`); never a bare "T-60m" for a book read at another lead.
    - States: source unavailable, read error, no schedule stored, schedule stale (warn), not collecting (off by
      default; the switch is not readable here), overdue targets (warn), populated.
  - New neutral or warning state words (`presentation.STATES`): `NHL_NOT_COLLECTING`, `NHL_SCHEDULE_OK`,
    `NHL_SCHEDULE_STALE`, `NHL_SCHEDULE_NO_DISCOVERY`, `NHL_SCHEDULE_UNREADABLE`, `NHL_OUTCOME_WITHHELD`. None is green.
  - The gallery gains the SYNTHETIC NHL coverage states (`fixtures.synthetic_nhl_coverage`). §13 gains the browser
    fixture state `nhl` (`fixture_states.nhl`): the recorded KXNHLGAME listing, a stored 2026-10-01 schedule, T-6h
    books captured through a fake fetch, a failed game-horizon, a rescheduled game and an unmapped team.

    Evidence (`tests/browser/capture.py`, 20 shots, 0 with overflow, clipping, low contrast or foreign requests):
    - fixture state `nhl`, `/experiments?tab=sources`:
      - Chromium and WebKit at 360x800, 390x844 and 1440x900, closed (with screenshots) and with every
        disclosure open;
      - Chromium at 360x800 and 1440x900 with 200% root text;
    - `/gallery` in the `demo` state, Chromium and WebKit at 360x800, 390x844 and 1440x900.

    Element shots of the NHL section were reviewed in Chromium at 390 and 1440 px. This is emulation, not a physical
    phone. The shots were reviewed locally by the author, described in the PR and not attached.

- **2026-09-30 — Source/state validity, fill-conditioned economics, current blockers and contract exceptions.**
  Approved by the owner directive of 2026-09-30 (`docs/owner/2026-09-30-roadmap-integration-sports-intelligence-rfq-directive.md`,
  "PR C": compact displays in the existing Terminal components) and the coordinator's PR C assignment; the spec is
  `docs/strategy/CLAUDE_SPORTS_INTELLIGENCE_RFQ_V1.md` §13. No token, theme, navigation item or new component.
  - §8 In-play research gains two sections, composed from the existing facts, rows, state text, tables and
    disclosures: "Source and state validity" after Position, and "Fill-conditioned economics" after Hold versus
    exit (wording above). The policy proposal is now checked against the game state it depends on: an invalidated
    or unreadable state reads "Blocked · no new risk" with a reason code (STATE_INVALIDATED: MATERIAL_STATE_CHANGE),
    never a sale. Two gallery states are added: invalidated and state unknown. Phases print in words ("in game"):
    the page never prints the word for a live feed. Production still reads "No in-play source is authorized" and
    shows neither section.
  - §8 Research & Data: Data sources gains "Current blockers" before "Fee schedule verification", from
    `current_blockers` (the one register; `docs/research/CURRENT_BLOCKERS.md` generates its table from it). One
    row per open item: title; scope, resolver, trigger (or "overdue since …") and "owner action needed" or "owner
    approval needed" in the subtitle; one status word, never green. The next item leads; verified, unknown,
    resolver and sources sit in a disclosure. States: populated, empty ("No research blocker recorded"), all closed
    ("No open blocker"), stale ("Register needs re-checking": reconciled over 14 days ago, or overdue), error and
    not installed (both "Blocker register unavailable", never "nothing open"), unrecognized status (neutral, code
    kept).
  - §8 Research & Data: Data sources gains "RFQ feasibility" after Current blockers, from
    `rfq_research.FEASIBILITY_MATRIX` (kept equal to `docs/research/RFQ_FEASIBILITY_2026-09.md` by a test). It
    shows:
    - a blocked state, "Decision: Narrow · no RFQ participation" ("Competitor quotes and fills are never shown");
    - counts per capability state (Documented, Private to the parties, Unavailable to us, Unknown) and the number of
      open owner decisions;
    - in disclosures, each capability with its state and note, and the owner decisions D1–D6 ("none taken here").

    No price, profit, competitor figure or control. States: populated, stale ("Documentation needs re-reading" after
    30 days), error and not installed ("RFQ feasibility unavailable"), unrecognized state (neutral).
  - §8 Terminal: the collapsed System & evidence opens with "Next research blocker or approval", one line with a
    link to Current blockers. Page order and the summary band are unchanged.
  - §8 Market detail: Rules & evidence gains "contract exceptions (recorded summary, not the rules)" for series
    with a recorded summary (KXNFLGAME, KXNHLGAME): tie, fair-price fallback, shootout, with each case's status.
    Other series show nothing new. No fixture state renders a sports market detail page; the row is covered by
    render tests (`tests/test_dashboard_blockers.py`), not screenshots.
  - §5 Formatting gains `presentation.ratio` (a multiple of a named denominator: "1.44×").
  - Label protection: no source-comparison widget is added. Nothing here reads NFL pilot quotes, T-60m label proxies
    or post-cutoff prices; any future comparison widget must use `odds_schedule.is_label_proxy`.
  - Screenshots, re-captured on the review-round head (Chromium; reproducible with `MSYS_NO_PATHCONV=1 python tests/browser/capture.py --states early demo
    --pages / "/experiments?tab=sources" /experiments/inplay /gallery/inplay --viewports 360x800 390x844 1440x900`
    at `--text-scale 1.0` and `2.0`, plus `--open-details` for `demo` at 390x844 and 1440x900): 52 shots, 0 with
    overflow, clipping, low contrast or foreign requests. Element shots of the new sections (including RFQ
    feasibility) at 390x844 and 1440x900 were reviewed locally by the author. The 200% text evidence is the
    capture.py audit. Two review fixes followed: blocker rows carry one
    status word, because a second badge squeezed the title at 390 px; and turnover prints as a multiple, not 12
    decimals. Emulation, not a physical phone; described in the PR, not attached.
- **2026-10-07 — execution journeys (J1/J4/J5/J6), read-only.** Approved by the 2026-10-07 evening owner
  directive (`docs/owner/2026-10-07-market-v1-autonomy-wallet-directive.md`; EXECUTION_PLAN: "operator Terminal
  journeys rendered from canonical or fixture data, honestly labelled").
  - §8 gains four pages, `/setup`, `/experiments/wallet`, `/positions/execution` and `/risk/automation`, reached
    from More, with one journey tab strip and no new global navigation item.
  - They are composed from the existing shell, section, facts, row, badge, table, state-text and disclosure
    components. Their state words (export and journal states, controller modes, readiness and setup states) are
    local tables in the `views/ops_*.py` modules, passed to `badge` / `state_text` as plain labels with the code in
    the title; no word is added to `presentation.STATES`, and none is green. No new token, CSS or layout.
  - Screenshots: five fixture states (`journeys`, `journeys_paused`, `journeys_idle`, `journeys_stale`,
    `journeys_none`) and `demo`, at 360x800 and 1440x900, at normal and 200% root text, plus every disclosure
    open (`tests/browser/capture.py`; 0 overflow, clipping, contrast or foreign-request findings).
  - Reviewed by the author and the coordinator (sampled), and described in the PR (not attached).
- **2026-10-08 — operator journeys J2, J3, J7 and J8, read-only.** Approved by the 2026-10-07 evening owner
  directive (`docs/owner/2026-10-07-market-v1-autonomy-wallet-directive.md`; EXECUTION_PLAN: "operator Terminal
  journeys rendered from canonical or fixture data, honestly labelled") and `docs/strategy/MARKET_V1_ACCEPTANCE.md`
  §2. No new route, navigation item, component, token, CSS or `presentation.STATES` word: every section is composed
  from the existing section, facts, row, badge, state-text, table, disclosure and empty/blocked/error/unavailable
  components; new state words are local tables (`research.COMPLETE_WORDS`, `STATUS_WORDS`, `SLOT_WORDS`,
  `outcomes.EXEC_GROUP_WORDS`) passed as plain labels with the code in the title; none is green.
  - J2 (§8 Data sources): five facts per Freshness Fabric row and four per Collected sources row. A cost or due time
    the canonical owner does not record reads unknown with its reason, never 0.
  - J3 (§8 Markets and Market detail): the paused line on Markets; fee per contract, evaluated size and the case
    block (mechanism, evidence, rejection reasons) in Our assessment. A decision is linked to an experiment only by
    its own `policy_id`.
  - J7 (§8 Research & Data): "Research stages" first on the Research tab; EXP-001's forward valid days carry the
    collector status's staleness (previously a stale `latest.json` showed its count as current).
  - J8 (§8 Outcomes): "Execution positions by outcome" after Linked outcomes, from the execution export (ADR 0043:
    no execution import); the "overdue" horizon gains its label (it printed the raw word).
  - Screenshots (`tests/browser/capture.py`, Chromium emulation, not a physical phone): 360x800 and 1440x900 at
    normal text for `journeys`, `journeys_paused`, `journeys_idle`, `journeys_stale`, `journeys_none` and `demo`
    (`/outcome-board`), `freshness`, `freshness_deferred` and `early` (`/experiments?tab=sources`), `demo`, `early`
    and `broken` (`/experiments`, `/opportunities`, two market details); at 200% root text for `journeys_paused`,
    `demo`, `freshness` and `early`; every disclosure open (audit only) for `journeys`, `freshness` and `demo`: 92
    shots, 0 with overflow, clipping, low contrast or foreign requests. Element shots of each new section at 360
    and 1440 px (normal and 200% text) were reviewed by the author; one review fix followed (an event whose holdings
    are unknown read "Positions held 0" and "Settled"; it now reads unknown). Described in the PR, not attached.
