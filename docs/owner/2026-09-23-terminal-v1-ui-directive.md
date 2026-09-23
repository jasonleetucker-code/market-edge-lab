# Owner directive, 2026-09-23: Market Edge Terminal v1 design and implementation contract

Recorded verbatim below (the owner's message in the "Market Edge Terminal v1 design" session,
2026-09-23 ~19:00 UTC), together with six owner-supplied iPhone screenshots of the previous
dashboard (the before state; not committed: they show only the private dashboard, and the
text of each is summarized in `docs/design/IMPLEMENTATION.md`). Owner requirement: issue #47.

Nothing below is paraphrased. Where this record and a later owner decision disagree, the later
decision wins and is recorded in `docs/EXECUTION_PLAN.md`.

---

# MARKET EDGE LAB — TERMINAL V1 DESIGN AND IMPLEMENTATION CONTRACT

Repository: jasonleetucker-code/market-edge-lab
Owner requirement: GitHub issue #47
Delivery deadline: October 22, 2026; unchanged
Mission: implement the permanent product interface now, not a disposable dashboard reskin.

## 0. What you are being asked to build

Build an original Market Edge interface that combines the information density and numerical discipline of a modern financial-market terminal with the clear event browsing and compact price selections of a premium sports-market application.

The owner's Yahoo Finance reference describes an information experience: market tape, quote boards, price movement, financial hierarchy, and fast comparison. It is not permission to copy Yahoo's brand or page. The sports-app reference describes market organization and price presentation, not a sports-only product. Weather, politics, economics, sports, and other prediction markets must feel native to the same interface.

Implement the exact visual direction below. Do not return several design options, choose another theme, substitute a template, or decide that changing the current font and padding is enough. Do not reinterpret this as a marketing landing page.

The design name is Market Edge Terminal v1. The product remains Market Edge Lab; the header wordmark reads MARKET EDGE.

### Fixed aesthetic

- Charcoal and graphite surfaces, warm-white typography, precise dividers, restrained signal-orange accents.
- Compact market boards and aligned numerical columns, not a grid of oversized rounded cards.
- A distinct IBM Plex typographic system, not default system-ui or an Inter/Poppins template.
- Market information is visually central. Diagnostics are accessible but subordinate.
- Professional and calm. No casino theatrics, generic AI branding, or decorative trading imagery.
- The same quality on a phone and a desktop, with different layouts rather than a shrunken desktop table.

### Prohibited visual choices

No violet/cyan gradients, glowing borders, glassmorphism, frosted panels, giant pill containers, floating translucent navigation, excessive drop shadows, bento-card landing pages, emoji navigation, stock trader photographs, robot/sparkle icons, random market logos, animated confetti, fake profit curves, motivational slogans, or oversized welcome messages.

Do not copy another company's logo, distinctive artwork, proprietary CSS, or exact screen composition. This is an original interface with a fixed specification.

### Your decision boundary

No discretionary changes to the specified theme, typography, navigation, component geometry, page order, data meanings, or visual hierarchy. You retain ordinary engineering judgment only to implement this contract correctly within the existing code.

If a requirement conflicts with security, accessibility, or established financial semantics, preserve the safer behavior, identify the precise conflict, and propose the smallest compliant correction. Do not silently invent an alternative product design. Missing data uses the defined unavailable state; it is not permission to invent data or abandon the design.

## 1. Scope and authorization

By giving you this directive, the owner authorizes the existing dashboard's presentation-layer redesign, its required read-only presentation routes, local static assets, small same-origin JavaScript enhancements, fixture-based browser testing, canonical design documentation, and reviewed merges for this mission.

Updating the already-private dashboard through the existing approved deployment path is authorized after tests and review pass. This is not permission to establish a new public access path or alter trading authority.

Do not change:

- Models, qualification thresholds, fee calculations, sizing, balances, settlement logic, risk limits, or frozen experiments.
- Collector schedules, source permissions, account connections, or the meaning of stored evidence.
- Live-order permissions, deposits, withdrawals, or paid subscriptions.
- Tailscale membership/access policy, Funnel, public ports, DNS, SSH keys, or unrelated Brisket services.

The application remains read-only and SHADOW / NO REAL MONEY. Polished visuals do not imply validated profitability or trading readiness.

This direction supersedes earlier presentation-only advice to defer serious interface work. It does not supersede production safety or research gates. Treat the shared UI foundation as NOW / P0, ahead of discretionary new feature screens. Keep collection running and do not delay an urgent correctness repair for design work.

## 2. Establish a baseline before editing

1. Read AI_INSTRUCTIONS.md, HANDOFF.md, docs/EXECUTION_PLAN.md, docs/WORK_CLAIMS.md, docs/OWNER_IDEAS.md, docs/DASHBOARD.md, and the current private-access/deployment runbook.
2. Review issue #47 and its links to #3, #4, #6, #10, #11, #30, #32, and #33.
3. Inspect current main, open PRs, local changes, and claims. The repo may be newer than this prompt. Do not overwrite work or assume a historic SHA remains current.
4. Inspect the actual dashboard modules. At preparation of this specification they included html.py, app.py, data.py, views.py, server.py, and demo.py under src/edge_lab/dashboard/.
5. Inventory existing routes, security headers, allowed hosts, asset handling, canonical data access, and the semantics asserted by current tests.
6. Read the six owner-supplied iPhone screenshots as the before state. Capture your own local before screenshots from the baseline revision as well. Do not require access to the private phone session to begin development.
7. Record the unmodified test baseline. Distinguish existing failures from new failures; do not waive either silently.
8. Claim the dashboard paths. Coordinate edits to canonical docs with the current claim holder. Assign one writer per file; do not let several agents restyle views.py independently.

Create docs/design/IMPLEMENTATION.md with the baseline SHA, current routes, a compact data-to-view map, owned paths, and the ordered checklist below. This is an execution ledger, not a second design authority. Start implementation after recording it; do not stop at a plan.

## 3. Make this a permanent cross-agent contract first

Create these canonical documents before composing individual pages:

- docs/design/UI_CONTRACT.md: the fixed visual tokens, layouts, semantics, and acceptance criteria from this directive.
- docs/design/COMPONENTS.md: component APIs, states, composition examples, and ownership.
- docs/design/FEATURE_INTEGRATION.md: the required checklist for adding any future user-visible feature.

Update AI_INSTRUCTIONS.md with this rule and a UI routing-table entry:

“All user-visible Market Edge work must follow docs/design/UI_CONTRACT.md and reuse the canonical shell, tokens, components, formatting, and state vocabulary. No agent may introduce a separate theme, page template, or duplicate presentation logic. A feature is not UI-complete until its real, empty, stale, error, unsupported, and blocked states are implemented and mobile/desktop evidence has been reviewed. Design changes require an explicit documented amendment, not an agent's stylistic preference. Backend-only changes document their existing UI contract or why no UI change is required.”

Keep AGENTS.md and CLAUDE.md as thin pointers; do not duplicate this specification into model-specific files.

Add the design system to the Shared primitives table in docs/OWNER_IDEAS.md. Reorder the relevant roadmap around shared shell/components first, page integration second, and future domains third. Record what lower-priority work is deferred; do not move October 22.

Update the PR checklist and execution plan so user-visible changes require design-contract compliance, semantic parity, and browser evidence. Tests can detect violations but cannot certify that a design looks good; visual inspection remains required.

## 4. Use the existing application, not a replacement frontend stack

Keep the existing Python server-rendered dashboard and canonical data readers. Do not introduce React, Next.js, Tailwind, a UI kit, a separate Node production service, or a second API merely to achieve this appearance.

Refactor presentation into these owners, reconciling equivalent files if they now exist:

- dashboard/presentation.py: typed page/row view models and formatting/mapping only.
- dashboard/components.py: reusable escaped HTML components.
- dashboard/html.py: document shell and common navigation.
- dashboard/views.py: page composition; split into a views package only if necessary to give each page a clear owner.
- dashboard/static/tokens.css: the single token definition.
- dashboard/static/terminal.css: shell and component styling.
- dashboard/static/terminal.js: small progressive enhancements only.
- dashboard/static/fonts/: licensed, pinned, self-hosted fonts.
- dashboard/static/icons.svg: a small static icon sprite with provenance.

Do not place a second inline stylesheet in every page. No ad hoc hex colors or font families in page modules. Use explicit variants of shared components rather than one-off panel classes.

Add static serving through an exact resource allowlist. Reject traversal and unknown assets; never expose an arbitrary filesystem path. Ensure assets are packaged in an installed wheel and work outside the repository working directory.

## 5. Exact visual tokens

The default and only shipped theme for this mission is DARK. Do not let OS color-scheme settings unexpectedly change the product. A future light theme must extend the same token contract and be separately specified.

Use these CSS values:

```css
:root {
  color-scheme: dark;
  --me-canvas: #101214;
  --me-surface: #171A1D;
  --me-surface-raised: #20252A;
  --me-surface-hover: #272D33;
  --me-line: #343B43;
  --me-control-line: #65717E;
  --me-text: #F4F2EC;
  --me-text-secondary: #BEC3CA;
  --me-text-muted: #949EA9;
  --me-accent: #FF7A45;
  --me-accent-ink: #101214;
  --me-positive: #49D3A2;
  --me-negative: #FF8088;
  --me-warning: #E8BA65;
  --me-info: #89B8FA;
  --me-focus: #B8D6FF;
  --me-radius-control: 4px;
  --me-radius-panel: 6px;
  --me-space-1: 4px;
  --me-space-2: 8px;
  --me-space-3: 12px;
  --me-space-4: 16px;
  --me-space-5: 24px;
  --me-space-6: 32px;
}
```

Rules:

- Orange identifies brand/selection/primary navigation, not profit.
- Green/red communicate signed changes, results, and qualified semantic states with text/icons too.
- YES is not inherently a good trade, and NO is not inherently a bad trade. Do not color every YES green and every NO red.
- Muted information remains readable. Do not lower opacity on whole sections to create hierarchy.
- Panels use a 1px divider/border and 6px radius. Controls use 4px. Small status badges may be 999px-radius capsules; large containers may not.
- No shadows on ordinary sections. Use one restrained shadow only for a real overlay/menu.
- Use opaque surfaces, not transparency or blur.
- Focus is a 2px visible outline with a 2px offset, never removed.
- Essential control outlines and selected states must be distinguishable; subdued separator lines are not a substitute for accessible controls.

Verify rendered text contrast against the actual backgrounds. Minimum 4.5:1 for normal text and 3:1 for large text; do not merely inspect the token table.

## 6. Exact typography and number treatment

Acquire fonts from the official IBM Plex source, pin the source/version and hashes, retain the applicable license in third-party notices, and self-host WOFF2. No browser request to Google Fonts, a font CDN, or an analytics service.

Use:

- IBM Plex Sans: body, controls, descriptions, market titles. Weights 400, 500, 600.
- IBM Plex Sans Condensed: wordmark, page/section headings. Weight 600.
- IBM Plex Mono: quoted prices, money, probability/edge columns, numerical chart axes. Weights 400 and 500.

Do not replace these with Inter, Poppins, a system-font-first design, or an unrelated display font. System fonts are failure fallbacks only. Use font-display: swap; verify the intended fonts actually loaded before approving screenshots. Do not use synthetic bold.

Typography scale:

| Element | Mobile | Desktop |
|---|---:|---:|
| Wordmark | 20px / 24px | 22px / 26px |
| Page heading | 26px / 30px | 30px / 34px |
| Section heading | 18px / 24px | 20px / 26px |
| Primary balance | 28px / 34px | 32px / 38px |
| Quote tile price | 18px / 22px | 18px / 22px |
| Market title | 15px / 20px | 14px / 20px |
| Body | 15px / 22px | 14px / 21px |
| Metadata / badges | 12px / 16px | 12px / 16px |
| Input text | 16px / 22px | 14px / 20px |

Use uppercase sparingly: wordmark, short section eyebrows, and compact state codes. Do not uppercase long headings. Section eyebrows may use 0.07em letter spacing; body copy may not.

Right-align comparable numeric columns. Use tabular figures and reserve stable width so updates do not move surrounding content. Never truncate a financial number with an ellipsis; wrap the containing layout instead.

Formatting is a shared function, not repeated template arithmetic:

- Currency: $1,000.00; preserve extra precision where economically meaningful.
- Binary $1 contract price: 48¢; subcent values remain visible, such as 48.25¢.
- Probability: 64.0% when supported precision warrants it.
- Probability-point difference: +5.2 pp, not +5.2%.
- Net expected value: an explicitly labeled amount per contract or per order from the canonical engine. Never relabel a probability difference as return on investment.
- Missing: — with accessible text explaining unavailable/not recorded.
- Known zero: $0.00 or 0, only when the underlying result is actually known.
- Main times: 5:45 PM EDT, with date where ambiguity exists. Use America/New_York by default; expose the exact UTC timestamp in Details.
- Relative age is supplementary, never the only audit timestamp.
- Rounding for display must not convert a marginally negative edge into a positive-looking one or a limit into a more permissive value. Provide exact values in Details.

## 7. Fixed application shell and navigation

### Breakpoints

- Mobile: below 768px.
- Tablet: 768px through 1199px.
- Desktop: 1200px and above.
- Page content maximum width: 1600px; center content beyond that width.

### Header

Desktop/tablet: 64px high. Mobile: 56px high plus any required top safe area.

Left: the text wordmark MARKET EDGE, preceded by a simple 4px-wide by 20px-high orange vertical rule. No generated logo artwork.

Right: compact persistent SHADOW · NO REAL MONEY text/badge and a 44px notification-bell target. On desktop, put the selected account name before those items. The bell opens Alerts; badge counts only real locally available attention items.

Mobile header must fit at 360px without wrapping. Use 12px mode text and a compact 20px wordmark; remove the desktop descriptor/account text rather than reducing the mode notice to an ambiguous dot.

The header is sticky. Do not place a second giant red banner beneath it. Red is reserved for actual blocked/error states. In demo mode additionally show SYNTHETIC UI DEMO in a compact, persistent, unmistakable strip.

### Navigation and routes

Keep existing deep links working. Use these labels and destinations:

| Visible label | Route |
|---|---|
| Terminal | / |
| Markets | /opportunities |
| Portfolio | /positions |
| Outcomes | /outcome-board |
| Risk | /risk |
| Research & Data | /experiments |
| Alerts | /alerts — read-only route over existing notification/status evidence |
| More | /more — mobile/tablet navigation index |

Desktop: 192px left navigation rail below the header/tape. Group Terminal/Markets/Portfolio/Outcomes first; Risk/Research & Data/Alerts second. Active item: 2px orange left marker, raised background, medium-weight text. Do not add disconnected pages or invent a Settings backend.

Tablet: 72px rail with icons and concise visible labels. Tooltips supplement labels, never replace all accessible naming.

Mobile: a solid fixed bottom bar, five equal targets in this order:

Terminal | Markets | Portfolio | Outcomes | More

Use 20px line icons with 12px labels. Bar height is 64px plus bottom safe area. Active icon/label use the accent; others use secondary text. More contains working links to Risk, Research & Data, and Alerts. The bell remains a direct Alerts shortcut.

Use an audited subset of Lucide-style line icons, a single consistent 1.75–2px stroke, and license notices. No icon font, emojis, remote sprite, or mixture of filled/outlined icon families.

All main content needs bottom padding of at least 88px + env(safe-area-inset-bottom). Use viewport-fit=cover, keep zoom enabled, and test real browser chrome. Safe-area padding alone does not prove Safari toolbar compatibility.

## 8. The market tape: market-terminal character without fake liveness

Immediately below the header, provide one horizontal quote tape: 52px mobile, 48px desktop. It scrolls horizontally within its own container; the page itself must not overflow.

A tape item contains a short market label, venue, selected outcome, latest captured quoted price, and price change only when a comparable earlier observation exists. Include an accessible full label and timestamp.

- Item width: approximately 184px mobile, 216px desktop; do not squeeze several illegible tickers into 390px.
- At most 12 items, drawn from actual loaded evidence: open-position markets first, then remaining loaded markets in a stable alphabetical order. Deduplicate by venue plus native market/outcome identity.
- Separate items with 1px vertical rules. No mini-card floating shadows.
- Tape is manually swipeable; desktop provides left/right controls. Do not autoplay a marquee.
- On desktop it may remain sticky below the header. On mobile it scrolls away with the page, leaving only the header fixed.
- Clicking a tape item opens its real market detail, not a trade.
- Price movement is the change in the same price field/side over a stated interval, not our model edge and not account P&L.
- Color movement only when computed from actual comparable observations. Otherwise display Change unavailable in detail, with no arrow on the tape.
- Label captured or delayed prices as such. Do not say LIVE solely because the webpage refreshed.
- With zero quote observations: render one tidy strip saying No quotes captured yet and a working Markets link. Do not insert fake equity tickers, fake sports, or decorative numbers.

## 9. Build the presentation contract before the pages

Use canonical backend results and the existing read-only Context. The presentation layer may group, sort, filter, format and compute pixel coordinates. It must not independently calculate money, fees, eligibility, position sizes, settlement outcomes, or risk capacity.

A market row must preserve these distinctions, with unavailable values explicit:

- Venue/exchange and, where known, broker/route/liquidity identity.
- Event, outcome, threshold/line, domain and sport/league.
- Exact rule identity/equivalence status.
- Quote timestamp, source freshness, side, price, quantity and depth coverage.
- Price per contract versus total cost for the requested size.
- Raw model probability, conservative estimate and source/version.
- Fee status and canonical expected value/edge.
- Historical decision versus current observation.
- Estimated return of tradable cash and the 168-hour policy verdict.
- Action mode: research, shadow candidate, blocked, or unsupported. Live execution stays disabled.

Require an explicit origin for every visible number in the data-to-view map. Existing computed summaries are authoritative. A missing field yields an unavailable state; record a separate dependency instead of silently recomputing it in JavaScript.

Operational and research shadow accounts are separate scopes. Default to Operational shadow. Use a compact account switch; do not repeat both accounts' entire pages vertically. Research mode carries a visible FROZEN RESEARCH RULE badge. Never sum their balances, count them as independent real accounts, or show their notional bankroll as the owner's actual money.

## 10. Shared component inventory

Implement these reusable components before final page composition:

1. AppShell: header, tape, rail/bottom nav, content, account context.
2. SectionHeader: title, scope metadata, optional one action.
3. MetricStrip: compact financial cells, known/missing state, scope label.
4. StatusLine: semantic icon/text, event time, report freshness separately.
5. DomainTabs and FilterBar: keyboard/touch accessible, no wrapped primary nav.
6. MarketRow: desktop/tablet board row and mobile composition of the same view model.
7. QuoteTile: outcome/side, price, venue/freshness, selected/disabled variants.
8. EdgeValue: net-value/probability-point labels without conflating them.
9. VenueComparison: comparable quote costs plus explicit exclusions.
10. MarketDetail: full information and read-only ticket preview.
11. PositionRow and OutcomeExposureRow.
12. HistoryChart: real observations, accessible alternative, no fake curve.
13. ActivityRow and PipelineTimeline.
14. EvidenceDisclosure: compact summary, exact provenance inside.
15. EmptyState / UnavailableState / ErrorState / BlockedState.

Every component needs a documented input contract and fixture examples for its relevant states. Do not create vague untyped dictionaries with hidden optional meanings at every call site.

Build a local component gallery available only in explicit demo/test mode. It must not load production stores or become a publicly exposed route. Include both empty and realistic synthetic populated states. This gallery is the reusable fixture surface for future agents, not another application.

## 11. Terminal page — exact hierarchy

The Terminal is the default home, not a collector report.

### Mobile order

1. Global header and market tape.
2. Page heading Market overview; secondary date/time, not a greeting.
3. Compact data/operation status line, at most two lines before a Details link.
4. A single Operational shadow summary region. Primary amount: Shadow equity · cost basis; below it a 2×2 grid for Tradable cash, Committed, Open risk, and Realized today. Draw from canonical values. Missing daily performance is unavailable, not zero.
5. Section Market board, with tabs All, Qualified, Watching, Blocked. Watching means observed/not qualified, not a fictional saved watchlist.
6. Up to five available market rows and a View all markets link. If no rows are available, the defined informative empty state appears here.
7. Section What matters today: up to three outcome-exposure rows from the selected account; no data means no open exposure, only when known.
8. Section Activity: up to five real event/status items with timestamps.
9. Collapsed System & evidence disclosure linking to detailed source/experiment information.

At 390×844, standard text size, the first market row or informative empty state must begin within the first approximately 650 CSS pixels of the page. Do not achieve that by shrinking text or hiding a critical warning. At enlarged text size, prioritize accessibility over the fold target.

The summary region is not a giant hero card. Target 160px maximum height at standard mobile text size; allow growth for accessibility and long numbers.

### Desktop composition

Below the shared shell: a 12-column workspace with a main board occupying 8 columns and a 4-column context rail. Gaps are 16px. Summary metrics form one aligned band over the main workspace.

Main: market board, then any supported price/portfolio history.
Context rail: current status and next scheduled activity, What matters today, recent activity.

Do not manufacture a chart merely to fill a rectangle. A genuinely useful compact schedule/activity list is the correct early-state alternative.

### Exact early-state messaging

The screenshot's FRESH latest.json and INVALID capture must not collapse into a green “System healthy.” Present, for example:

Last target unavailable · Sep 23
Missing forecast and decision evidence. Status report refreshed 11 minutes ago.

Those words are illustrative of the supplied screenshot, not values to hardcode. Distinguish a not-yet-due capture from a missed or failed capture using canonical timing/status evidence. If that distinction is unavailable, say Capture timing not verified; do not assume an expected launch gap.

## 12. Markets page — the product's central board

Heading: Markets.
Subtitle: Observed prices and model assessments plus the actual coverage timestamp.

### Control order

1. Search input: Search captured markets.
2. Domain strip: All, Weather, Sports, Politics, Economics, Financial, Other.
3. When Sports is selected, show the available sport/league filter; distinguish unsupported/no data from a verified zero-market result. Do not turn the top-level product into an NFL app.
4. Filter controls: Venue, State, Cash release, Sort.
5. Results/coverage line.
6. Board/list.

Domain tabs are one horizontal strip with swipe overflow, never a second multi-row primary navigation. Every tab functions, including an honest not-connected or no-captured-markets state.

Default state is All observed, not “Qualified only” hiding all current data. Default cash-release filter is All, with the starter policy visible. Users can select Within 7 days, Over 7 days, or Unknown for research browsing. Viewing an ineligible market never enables allocation to it.

Default sort: known qualifying assessments by canonical net edge, then remaining rows by soonest known cash release, then stable title/ID. Unknown values sort last. Make the selected sort explicit and deterministic.

### Desktop columns

Market / outcome | Venue | Quote | Model | Net edge | Size | Tradable again | State

- Title column flexes and is widest; numeric columns align right.
- Fixed headings, subtle row separators, no zebra-striping rainbow.
- Standard row height minimum 64px; expand if the title requires it.
- Last row action: accessible View details, not a fake Buy button.
- Best-price information cannot appear unless equivalence, fee/size treatment and coverage permit the claim. Otherwise say Observed quote.

### Mobile market row

Use a connected list with separators, not an independent giant card per market:

- Top metadata: domain/league at left, venue/time at right, 12px.
- Market question/title: 15px medium, normally two lines; preserve distinguishing threshold/date/outcome.
- Two compact quote tiles for genuine supported sides, each at least 44px tall. Explicit side/outcome label above price. Missing side shows Unavailable.
- Bottom: model probability, canonical net edge, and tradable-cash ETA in a compact two-column arrangement; allow a second line, never clip.
- State/eligibility is text plus a small icon. Make the row title and quote tiles open details with the correct side, not submit an order.

Do not assume every sport, draw market, spread, DFS entry, or political contract has a simple YES/NO payoff. Use the existing payoff type. Unsupported types get a research-only presentation, not fabricated binary price tiles.

### Interactions

Implement bounded, allowlisted GET parameters and server-rendered results. Main filters work without JavaScript. Query values cannot name a file, SQL expression, callable, shell command, or remote URL.

Allow only explicit parameters for q, domain, sport, venue, state, horizon, sort, account, and page. Search maximum 120 characters. Account is operational/research; venue/sport values come from known registries or safely loaded identities. Page size is 25, with bounded page values.

Use parameterized existing read APIs or filter already-loaded canonical values. Never concatenate query values into SQL or HTML. Unknown values receive a safe validation message, not an exception dump.

Show No matches in captured data when filters exclude everything, with a working Clear filters action. Do not say no such markets exist across the whole industry.

## 13. Market detail — financial quote page plus a read-only ticket

Add a stable read-only detail destination, such as /market?venue=...&id=...&account=.... Validate identity against stored/known market records. IDs are not filesystem paths. Preserve venue, outcome and rules identity; title alone is not a key.

Desktop: main detail column plus 320px right inspector. Mobile: full-width document; no nested-scroll full-screen modal required.

Render in this exact order:

1. Breadcrumb back to the preserved market filter state.
2. Domain/venue labels and the complete question/outcome with date/threshold.
3. Quote summary: price, source time, price type, available size, and freshness.
4. Price history chart only when actual same-side comparable observations exist.
5. Our assessment: raw model, conservative model, net expected value/edge, fee status, model version; unavailable means no assessment, not 50%.
6. Across venues: eligible equivalent comparisons first, excluded/unproven comparisons separately.
7. Capital & timing: maximum loss/quantity from canonical outputs, estimated cash-release time, 168-hour verdict and uncertainty.
8. Decision preview: existing ticket data, explicitly Read-only · Trading disabled.
9. Rules & evidence: full question, settlement definition, source, timestamps and technical IDs in a disclosure.

The preview may show the selected outcome's existing numbers. Do not add a working submit, deposit, withdraw, approve-trade or auto-trade control. A quantity input that would change financial calculations is outside this UI mission; show the requested size already produced by the canonical engine, or Size not evaluated.

If an approved official venue link is already available, label it Open on [venue] and make clear it leaves Market Edge. Never generate affiliate/order links or allow arbitrary URLs from untrusted data without a safe scheme/host policy.

For comparisons distinguish:

- Lowest observed quote.
- Best verified total cost at the evaluated size.
- Best account-feasible route, only when authorized account data actually exists.

Unknown fees, unrelated rules, missing depth or no account access cannot silently become an executable “best buy.”

## 14. Portfolio page

Keep /positions, label it Portfolio.

Top: selected account and compact metrics for cost-basis shadow equity, tradable cash, committed capital, open worst-case risk, and realized P&L. Show the accounting basis beside the main amount.

Then a position-state control: Open, Settling, Closed, All. Implement filtering; do not add dead tabs.

Desktop positions use aligned rows. Mobile positions show:

- Market/outcome and venue.
- Position side, quantity and entry price.
- Cost and maximum loss.
- Settlement state and tradable-cash ETA.
- Realized result only after canonical settlement evidence.

Methodology moves into How these balances are calculated. Keep the complete required caveats there and concise basis labels next to affected numbers.

Never add unrealized profit to the headline if the ledger carries positions at cost. Never display a positive equity curve assembled from expected winnings. Do not aggregate research and operational shadow accounts.

No positions: No open shadow positions only if the account loaded and has none. Follow with Positions will appear after a qualifying decision and simulated fill. If evaluation has not occurred, say that. If the ledger failed to load, show an error, not an empty portfolio.

## 15. Outcomes page

Keep /outcome-board, label it Outcomes; page heading What matters today.

This is a ranked exposure board, not a feed of every event on the internet.

Top: count of linked outcome groups, open risk, and largest exposure if known. Then compact rows sorted by the existing canonical account-impact measure.

Each row:

- Short real-world outcome phrased plainly.
- Domain/venue count and linked-position count.
- Maximum-loss upper bound and maximum-gain upper bound, explicitly labeled as bounds.
- Horizontal exposure bar using canonical exposure for length.
- Expected cash-release timing/state.
- Why it matters disclosure showing linked positions and their contributions.

Do not call summed bounds an attainable combined scenario. Do not change the exposure engine to make a more attractive chart.

No linked positions: one intentional empty state, not repeated “none recorded” in separate operational and research panels.

## 16. Risk page

Keep /risk, heading Risk & capital.

Top band: tradable cash, committed capital, remaining risk capacity, realized daily loss, realized weekly loss, drawdown. Unknowns remain explicit.

Below: Capacity for new positions, using the canonical capacity and new_risk_allowed verdict. If a percentage lacks a defined denominator, show the exact amount and binding constraint instead of inventing “80% safe.”

Use horizontal limit rows for Position, Event, Related outcomes, Portfolio, Daily loss, Weekly loss, and Drawdown. Show used/limit only when both use compatible definitions. Zero denominators and not-applicable fields get a descriptive state, not division or a full green bar.

Next: Capital release with Available now, Within 1 day, Within 7 days, and Unknown / delayed, only using the existing canonical classification. Label overlapping/cumulative horizons if that is what the backend returns; do not display them as additive buckets.

Prominent but compact: Starter rule: estimated tradable cash within 168 hours plus current exceptions. This concerns reusing proceeds on the same venue, not arrival in a bank.

Move raw field names and policy IDs into Policy details. Policies are visible, not editable. Withdrawal guidance reads Not enabled; there is no withdrawal action.

## 17. Research & Data page

Keep /experiments; use a two-tab read-only view: Research and Data sources.

Research cards have a compact editorial structure:

- Friendly experiment name, then small stable ID.
- Current research stage and separately operational pipeline status.
- Historical result where available.
- Forward valid days and next preregistered checkpoint.
- Concise limitations plus a Details link/disclosure.

A progress bar to 180 valid days is labeled Observations toward the next scheduled evaluation. It is not “edge proven,” software completion, or a countdown to guaranteed success. Historical test days do not count as prospective forward days.

Data sources render as a compact list with columns/cells for Source, Supported scope, Access stage, Last successful observation, Freshness and Outstanding requirement.

A source marked TESTED is not Connected. A single smoke read is not a reliable scheduled feed. Daily files are not real-time books. Public market reads do not imply account or order access. Preserve those distinctions in visible language and details.

Technical hashes, identifiers, complete report fields, exact reason codes, and source evidence remain available under disclosures. Do not silently drop fields during redesign.

## 18. Alerts and More

/alerts reads the existing notification outbox, failure records and pipeline evidence. It does not send anything.

Group by urgency and date, with a consistent row: semantic icon, short title, affected market/source, time, concise reason, action link when valid.

Distinguish Recorded locally, Delivery attempted, Delivered according to provider, and unknown delivery status. A row in a file is not proof that a phone received a push.

Expired opportunities remain historical but are visibly Expired; no actionable-looking prompt. Critical system/risk failures remain visible even when a market filter is applied elsewhere.

Do not add server-side “mark read” writes. Browser-only dismissed/collapsed preferences may be used only for presentation, never to erase safety state; default critical items remain visible.

/more is a clean list linking to Risk, Research & Data, Alerts, and existing system details. No advertisement, profile gamification, social feed, or account-connection buttons that do nothing.

## 19. Honest state vocabulary and empty-state design

Map technical values to plain language without modifying stored codes. Details always reveal the original code.

| Situation | Primary visible treatment |
|---|---|
| Data never collected | Waiting for first capture |
| Data read failed | Data unavailable + specific safe reason |
| Report refreshed but capture invalid | Capture incomplete + separate report time |
| Capture scheduled but not due, verified | Next capture [time] |
| Capture missed or failed | Capture needs attention + actual missing evidence |
| Evaluation not run | Not evaluated yet |
| Evaluation ran, no qualifying rows | No qualifying opportunities |
| Model unsupported | No model for this market |
| No comparable venue | No equivalent venue price verified |
| Stale quote | Stale quote — not actionable |
| Positive historical model result | Historical validation passed, not Profitable |
| Risk capacity zero | New positions halted with the binding reason |
| Seven-day rule fails | Outside starter horizon |
| No account permission | Account access not connected |

Unknown codes render neutrally and remain inspectable; they must not default to green. A routine no-fill is not necessarily a system failure: show its actual reason and severity.

Empty states are small structured sections, not giant illustrations. Use one short title, one or two explanatory sentences, relevant known last/next times, and a real navigation action. Do not show a “Refresh market” button that secretly runs collection.

## 20. Chart, motion, and interaction rules

- Charts consume existing persisted observations. Do not generate random sparkline data, interpolate through missing periods as if observed, or turn a single point into a trend.
- Price charts use a cents/probability-quote axis appropriate to that instrument; account charts state cost-basis or liquidation basis explicitly.
- Include units, time range, accessible description/table and discontinuities. A quote series and model-probability series must be separately labeled.
- A minimal shared SVG renderer is sufficient for the first version. Pixel-coordinate conversion may use floating point; financial computations remain canonical Decimal results.
- Range choices appear only for available data; an empty range explains why it is empty.
- Transition duration: 120ms for hover/focus, 160ms for a deliberate disclosure. No spring physics or page-entry animations.
- Price-change highlighting lasts at most 600ms and only follows an actual new observation. Do not flash arbitrary values.
- Respect prefers-reduced-motion by removing nonessential motion.
- No sound, vibration, or gamified urgency.
- Refresh is manual in this mission. Refresh reloads stored dashboard information; it does not initiate a new upstream scan. Label its time accordingly.
- Do not add continuous polling, market streaming, a service worker, or background financial-data caching merely to create a live impression.
- Core navigation, account selection, filters, and disclosures work without JavaScript. JS improves ergonomics, not financial truth.

## 21. Security and static-asset implementation

Preserve read-only stores, existing authentication/private-access boundaries, allowed-host checks, XSS escaping, error redaction, and GET/HEAD restrictions.

Changes needed for local assets/forms must be narrow and tested. Target policy after moving CSS/JS to self-hosted assets:

```text
default-src 'none';
script-src 'self';
style-src 'self';
font-src 'self';
img-src 'self';
connect-src 'self';
base-uri 'none';
object-src 'none';
frame-ancestors 'none';
form-action 'self';
```

Reconcile this with current protections rather than dropping an existing stronger restriction unnecessarily. No unsafe-eval, wildcard hosts, third-party scripts, remote analytics, inline event handlers, or unsanitized dynamic SVG/HTML.

GET filter forms only. No mutating dashboard endpoint is added. Client-side script must not contain keys, account secrets, private server paths or authority to trade.

Use textContent for untrusted dynamic text, not innerHTML. URL generation must validate schemes/hosts and encode values. Reject traversal, malicious query strings, unknown routes, and unsupported methods without a sensitive response body.

Keep response caching off for private financial/status HTML. Immutable caching is permitted only for fingerprinted non-sensitive static assets. Do not cache private pages in a service worker.

Preserve the user's existing working Tailscale URL. Do not assume its exact hostname from chat or change Serve/Funnel/firewall configuration during a visual refactor.

## 22. Required implementation order and parallel work

Execute in this order:

1. Baseline, claims, data/route inventory.
2. Canonical design contract, tokens, fonts, asset serving.
3. App shell and fixed navigation, then market tape.
4. Reusable component gallery and semantic presentation contracts.
5. Terminal plus Markets plus Market detail as the first integrated vertical slice.
6. Portfolio, Outcomes and Risk using the same components.
7. Research & Data, Alerts and More.
8. Semantic parity, security, accessibility and browser-layout testing.
9. Independent design/data/security review; correct findings.
10. Reviewed merge, private dashboard deployment, final browser verification.

After step 4, at most three bounded lanes may run: shared shell/component owner, page-composition owner, independent test/review owner. Split pages into owned files before parallel editing. No agent chooses its own colors/fonts/layout.

Do not build all the functionality as isolated mockups first and defer integration. The real current empty/invalid state must be usable in the first vertical slice. Synthetic states expand testing; they are never the production default.

## 23. Browser, visual, and financial-truth test matrix

Use a browser tool or a development-only browser-test dependency such as Playwright if needed. Do not add a browser process to the production collector. Use audited tooling, isolated fixtures, disabled external network and fixed clocks. Do not execute third-party UI templates/installers.

Test at:

- 360×800 mobile;
- 390×844 mobile;
- 430×932 mobile;
- 768×1024 tablet;
- 1440×900 desktop;
- 1920×1080 wide desktop.

Exercise Chromium and WebKit. Emulated WebKit is not proof of behavior on the owner's physical iPhone; distinguish those checks in the report. Verify the actual private iPhone page when available without claiming device access you do not have.

### Fixture states

A. Current production-shaped early state: recently refreshed report, invalid/missing capture, zero decisions, known or unavailable account state as appropriate.

B. Clearly labeled synthetic populated state with weather, a team sport, a fight, a political event and an economic event. Use the same components, not sport-specific page forks.

C. Stale/malformed sources, unknown fees, unproven equivalence and unsupported models/payoffs.

D. Open/settling/closed shadow positions, negative results, zero risk capacity, delayed capital release and settlement conflicts.

E. Long names, Unicode, subcent quotes, very large monetary values and missing timestamps.

F. Research account selection, verifying it never changes operational figures.

Synthetic account values must come through fixture/canonical ledger paths, not invented production template constants. The gallery and screenshots must label synthetic data visibly.

### Required assertions

- No body-level horizontal overflow at supported widths under normal and enlarged text settings.
- No clipped quote/amount/outcome; no primary navigation wrapping into three rows.
- Bottom navigation/browser-safe spacing leaves the final actionable link reachable.
- Touch actions are at least 44×44 CSS px; controls have keyboard operation and visible focus.
- 200% text scaling/zoom does not hide essential information; allow natural document growth.
- Correct heading hierarchy, landmark labels, form labels and selected-tab semantics.
- No color-only state meaning; measured text/control contrast passes.
- All links, tabs, filter resets and account switches work; no dead mock buttons.
- Every dynamic field remains escaped, including title, reason, receipt, venue, unit and URL cases.
- Foreign Host rejection and private route boundaries still hold for new static/detail routes.
- Unsupported methods still fail; no new order/deposit/withdrawal endpoint exists.
- Rendering and filtering never modify durable evidence, financial ledger entries, or source state.
- Monetary values, risk decisions, account scope and frozen outputs match the baseline canonical results.
- Known zero, unknown, not-evaluated, stale, blocked, unavailable and error are distinct.
- Font files and CSS/JS load from this application; no unexpected browser network requests.
- Application assets work from a fresh package installation, not only the developer checkout.

Keep new CSS plus JavaScript small: initial targets are at most 70 KiB CSS and 35 KiB JS before compression, and at most 300 KiB first-view font transfer using only required licensed subsets/weights. Measure and report; missing a budget requires a specific explanation, not replacing the design with a library. Avoid external network/LLM calls in rendering and bound evidence reads/results.

Do not fix overflow by applying blanket overflow-x:hidden to the whole page. Fix the grid/width issue; only designated strips and technical code panes may scroll horizontally.

## 24. Screenshot review is mandatory

Capture before/after screenshots for every existing page and after screenshots for new detail/alerts views. Include mobile and desktop, with early empty and populated synthetic states.

Open and inspect the screenshots yourself. Do not infer success from tests named mobile or from HTML containing a class.

Have an independent reviewer check this exact contract, not invent a new aesthetic. The review must identify specific discrepancies: spacing, font actually loaded, column alignment, density, overflowing titles, missing caveat, wrong state, unreachable control, confusing shadow scope, or generic template residue.

Fail the design review if:

- It is still the original giant-panel layout with different colors.
- Market data does not receive the primary visual hierarchy.
- A page looks like an unrelated dashboard template.
- Technical explanations or internal IDs dominate the opening screen.
- Empty production screens are less considered than populated demo screens.
- A beautiful example relies on fake live quotes, unsupported prices, or invented financial values.
- The compact shadow indicator is no longer immediately visible.

The owner must be able to judge the delivered interface from actual rendered pages, not your description of them.

## 25. Permanent future-feature integration rules

Write this checklist into FEATURE_INTEGRATION.md and the PR template. Every future user-visible feature answers:

1. Which existing route and layout slot owns it?
2. Which canonical backend result supplies each value?
3. Which existing components render it?
4. Does it need a genuinely new reusable component? If so, add it to the gallery and documentation before using it.
5. What are its empty, missing, stale, unsupported, error, blocked and populated states?
6. Which account/venue/domain scope applies?
7. Is it read-only, simulated, or separately authorized for an action? Is that visible?
8. How does it behave at 360px and 1440px and enlarged text size?
9. Which financial/provenance caveats must remain adjacent to its figures?
10. Which tests and reviewed screenshots demonstrate conformity?

A later sports model supplies data to the same MarketRow and detail contracts. A politics source uses the same source list. A new venue uses the same comparison component. SMS/push events use the same Alerts view. A future live-execution ticket needs its own safety authorization but must fit the existing inspector, not create another app.

No new global navigation item merely because a new sport or source was added. Use the established domain/filter hierarchy. No agent may fork the theme for a feature or dump raw JSON/configuration into a user-facing page and call it complete.

## 26. Review, merge, deployment, and rollback

Use small coherent PRs, but do not publish a half-migrated visual system across production pages. Keep the legacy release available until the integrated replacement passes. Internal development flags must not expose an unreviewed design publicly.

Before merge: reconcile current main and concurrent claims; run targeted and full tests; validate experiments/frozen artifacts; run security and browser tests; resolve blockers; obtain independent review and exact-final-head green CI. Preserve all required third-party notices. Clearly report pre-existing platform failures rather than using them to excuse new regressions.

The owner authorizes squash-merging this bounded UI mission after those conditions pass. Do not merge a substitute theme or a partial redesign as full completion.

Deploy only through the already-approved private dashboard release path. Confirm actual service identity, SHA, access route and ownership; the screenshot proves page access, not the server's complete configuration. Update only what the dashboard requires.

No production deployment/restart from 5:40 PM to 6:35 PM America/New_York, nor while a relevant capture is active. Local coding and tests may continue. Do not stop collectors, restart Brisket, migrate financial stores or alter shared networking to ship CSS.

Verify the private URL after deployment, static assets, all routes, shadow labeling, allowed-host security, and existing collector/Brisket health. Record the rollback revision and procedure. If access prevents deployment, finish reviewed code/screenshots and report DEPLOYMENT_BLOCKED; do not claim it is already on the phone.

## 27. Required completion report

Return:

- Exact main/deployed SHA and PRs.
- Canonical design docs and the AI-instruction/PR-checklist changes.
- Before/after images for Terminal, Markets, Portfolio, Outcomes, Risk, Research & Data; plus Market detail and Alerts.
- Which screenshots use production-shaped fixtures versus synthetic populated data.
- Browser/viewport/physical-device checks actually performed.
- Confirmation of semantic parity and untouched models/ledger/risk/fees/experiments.
- Asset size, font loading, accessibility and security results.
- Every nonworking element or unavailable field, with the honest UI state used.
- Private deployment status, actual bookmark URL when verified, and rollback revision.
- The roadmap changes that make this the foundation for every later feature.

Use separate verdicts: IMPLEMENTED, TESTED, VISUALLY_REVIEWED, MERGED, DEPLOYED, PRIVATE_ACCESS_VERIFIED. Do not combine them into one unsupported “done.”

Do not return only a plan, new CSS tokens, component screenshots, or an attractive empty shell. Deliver the integrated interface across the existing application.

The final product should feel like one deliberately designed market terminal, whether the next row is a temperature bracket, an NFL game, a boxing bout, a political vote, or an economic release. Future features inherit this system; they do not reinvent it.

## Reference sources for implementation, not additional design choices

- Existing repository modules and owner iPhone screenshots are the before-state basis.
- Official IBM Plex family/license: https://github.com/IBM/plex
- WCAG contrast explanation: https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
- WCAG target-size explanation: https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
- Official Lucide assets/license: verify the canonical lucide-icons/lucide repository before using its small static icon subset.

The 44px touch-target requirement is this product's design standard; do not misstate it as the WCAG 2.2 AA minimum. The aesthetic specification is original design direction, not a claim that Yahoo Finance uses these exact fonts, colors, or layouts.
