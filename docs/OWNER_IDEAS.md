# Owner Ideas

Durable owner ideas live in GitHub issues titled `[Owner Idea] …`. This file is an
**index**, not a copy: the issue body is the record. The process authority is issue #4
([Owner Process] Durable idea intake and readiness backlog). The canonical rule is in
`AI_INSTRUCTIONS.md` → Owner ideas.

- **Capture:** create or update an issue in seconds. Link related ideas. Do not invent
  details the owner did not give.
- **An issue is not authorization.** `docs/EXECUTION_PLAN.md` alone says what may be built.
- **Review:** at every gate transition, or when an idea's prerequisites appear, the
  coordinating agent reclassifies each open idea below and dates the review.

- **Re-plan on every material idea.** In the same session, record its priority,
  dependencies, overlap, shared primitive, parallel lanes and roadmap effect, and put it in
  **NOW / NEXT / LATER / BLOCKED** (`AI_INSTRUCTIONS.md` → Owner ideas).

Roadmap vocabulary: **NOW** (on the current critical path and authorized) · **NEXT**
(ready once a named prerequisite lands) · **LATER** (wanted; not on the 2026-10-22 path) ·
**BLOCKED** (waiting on an owner decision, access or evidence, which is named).

Newly classified ideas use the roadmap vocabulary in the Readiness column. Older rows
keep the readiness vocabulary until their next review: **NOT READY** (prerequisites absent) · **READY FOR RESEARCH** ·
**APPLY SELECTIVELY** (use the principle where current work already needs it) ·
**READY FOR IMPLEMENTATION** (prerequisites exist and there is an authorization path) ·
**SUPERSEDED / NOT PLANNED**.

## Shared primitives (one canonical owner each)

Every idea is built on these primitives. Extend the owner named here, and never fork it into
a feature-specific copy. `PLANNED` means the owner is chosen but not yet built. The ideas
column lists which issues each primitive serves.

| Primitive | Canonical owner | State | Serves |
|---|---|---|---|
| Event / market identity | `src/edge_lab/opportunity.py` | BUILT (Event, Market, settlement_identity) | #5 #9 #30 #32 |
| Venue and account capability registry | `src/edge_lab/venues.py` | BUILT (stages per capability, cash timing; execution never authorized; ADR 0019) | #30 #32 #29 #9 |
| Quote / order-book normalization | `src/edge_lab/opportunity.py` | BUILT (ExecutableQuote and DepthLadder / `walk_ladder` / `price_depth_fill` for Kalshi and Polymarket US, PRs #40 and #42; per-market `PriceGrid`, ADR 0023; sportsbook odds and Novig daily files are never executable) | #30 #9 #29 |
| Fee models and fee verification | `src/edge_lab/fee_schedules.py` | BUILT (Kalshi, with dated component-level verification records, ADR 0017; other venues unsupported). It reuses the hash-frozen EXP-001 cost model in `fees.py`, never forks it | #6 #30 #9 |
| Model estimates | `src/edge_lab/opportunity.py` | BUILT (ModelEstimate; EXP-001 only) | #5 #9 #32 |
| Source ingestion and provenance | `src/edge_lab/sources.py` | BUILT: the registry (with a read-only data-feed credential kind), fronting `storage.py`, `provenance.py` and the shared `redaction.py` | #7 #29 #30 #27 |
| Rules / settlement equivalence | `src/edge_lab/opportunity.py` | BUILT (`Event.settlement_identity`, `Market.rules_resolved`); cross-venue classification in `discovery.py` (title match is never equivalence); no equivalence proven across venues yet | #30 #9 |
| Shadow / live ledger boundary | `src/edge_lab/shadow_ledger.py` | BUILT (shadow only; no live ledger). Head checkpoints: `ledger_anchor.py`; the first independent checkpoint is stored off-host and in Git and verified (F09 closed for the anchored history, 2026-09-23) | #6 #3 #32 |
| Risk engine | `src/edge_lab/risk.py` | BUILT (limits, capital release, withdrawal contract) | #6 #3 |
| Capital-eligibility policies | `src/edge_lab/starter_policy.py` | BUILT (`STARTER_MAX_7D_V1`, ADR 0018); enforced prospectively in the operational shadow account | #32 #6 |
| Notification system | `src/edge_lab/notifications.py` | BUILT (contract, local outbox, SMS sink disabled; ADR 0020). ntfy push sink `notify_ntfy.py` built, disabled and unwired (ADR 0022) | #33 #3 #32 |
| Execution-ticket contract | `src/edge_lab/execution_ticket.py` | BUILT (data contract plus an ordered pre-submit control chain, PR #43; `EXECUTION_NOT_AUTHORIZED` always fails) | #32 #33 #30 |
| Operator views | `src/edge_lab/dashboard/` | BUILT (read-only; on chaseupside reachable only on the owner's tailnet via Tailscale Serve, ADR 0024) | #3 #6 #10 |
| Design system (Market Edge Terminal v1) | `docs/design/UI_CONTRACT.md` | BUILT (implemented in dashboard presentation.py, components.py, html.py and static/tokens.css; shell, tokens, fonts, components, honest states, gallery; ADR 0025, issue #47). Every user-visible feature reuses it per docs/design/FEATURE_INTEGRATION.md | #47 #3 #6 #9 #10 #29 #30 #32 #33 |

## Index

| Issue | Idea | Readiness | Why / prerequisites |
|---|---|---|---|
| #4 | Durable idea intake and readiness backlog (process) | **Implemented** 2026-09-22 (Gate 3 PR) | `AI_INSTRUCTIONS.md` rule + this index |
| #3 | Outcome Board / What Matters Today dashboard | **BACKEND + LOCAL VIEW IMPLEMENTED** 2026-09-23 (PR #28); hosting NOT READY | `edge_lab.outcome_board` (ADR 0015) plus the `/outcome-board` view of the local read-only dashboard (127.0.0.1 only). Hosting, auth and live marks are unauthorized and not built. |
| #5 | Sports prediction-market and sports-modeling expansion | **LATER** (discovery and data foundations NEXT via #29/#30; any sports model BLOCKED on a preregistered experiment) | Core framework is proving out on weather. Needs the shared identity, venue and equivalence layers; the 2026-09-23 directive authorizes data foundations only, not sports models. |
| #9 | Sportsbook odds aggregation, consensus pricing, best-venue comparison | **NEXT** (The Odds API data foundation via #29); comparison LATER | Sub-idea of #5. Needs market equivalence and verified access terms. Offered odds are never executable prices. |
| #6 | Dynamic bankroll, position sizing, withdrawal guidance | **P0 FOUNDATION IMPLEMENTED** 2026-09-23 (shadow only) | Shadow ledger (ADR 0014), `suggest_position_size`, and the risk/capital report with a withdrawal contract (ADR 0015). The withdrawal contract never recommends a draw. Since PR #26 the operational shadow account enforces the risk limits **before** each fill (NO_FILL RISK_VETO); the frozen research account is separate. A real-money policy, a verified edge and verified fees are all still missing. |
| #10 | Host privately on existing Chase Upside infrastructure (separate service/subdomain, real access control) | **IMPLEMENTED, private** 2026-09-23: collector, daily shadow and settlement deployed and verified (`docs/deploy/PRODUCTION_ACTIVATION_2026-09-23.md`); the dashboard is tailnet-only via Tailscale Serve (PR #46, ADR 0024) | A separate service with its own user, slice and stores on the VPS. Access control is tailnet membership. A public subdomain, DNS/TLS and public exposure remain unauthorized and are not planned. |
| #7 | Free-first multi-domain ingestion with paid-source ROI gate | APPLY SELECTIVELY NOW | Gate 3 applied it: the free IEM archive of NWS forecasts was chosen and paid weather data was not considered. The general ingestion platform is not built. |
| #32 | Starter policy: 7-day capital-release limit, broad discovery, API-first execution preference | **Policy IMPLEMENTED** 2026-09-23 (PR #38, ADR 0018; enforced prospectively in the operational shadow account; no deployment known or verified from this session); discovery foundation IMPLEMENTED (PR #39); execution BLOCKED (no live authority) | Governing clock: venue-tradable cash within 168 h. The ticket contract carries the verdict with execution disabled. |
| #33 | SMS-first alerting through one shared notification layer | **Contract IMPLEMENTED** 2026-09-23 (PR #38, ADR 0020; local outbox); **ntfy push sink BUILT, disabled** (PR #44, ADR 0022; the first real send needs owner approval); SMS delivery BLOCKED (provider needs owner approval) | Serves daily-run failures, settlement conflicts, invalid captures, risk vetoes, settlements and policy exceptions now; approval tickets later. |
| #30 | Multi-venue coverage, best-price comparison, unique-market discovery | **Foundation IMPLEMENTED** (registry PR #38; Polymarket US adapter TESTED + one smoke read, Novig daily files TESTED, discovery, PR #39; depth ladders for both book venues and per-market price grids, PR #42); best-price-for-size comparator NEXT; Novig live API BLOCKED (credentials) | Best-price claims still need proven rules equivalence and per-venue fee evidence (Polymarket US fees are UNSUPPORTED today). |
| #29 | The Odds API free tier (quota-capped sports odds pilot) | **Adapter IMPLEMENTED on fixtures** (PR #39: quota ledger, 450-credit ceiling, redaction, SETUP_NEEDED); live pulls BLOCKED (owner key + activation plan) | Sportsbook-consensus input for #5/#9. Offered odds and de-vigged values are never executable prices. |
| #27 | Action PRO permission and comparative sports-data subscription value | **LATER / BLOCKED** (no purchase authorized) | Paid source; needs the #7 ROI gate and a sports experiment that would use it. |

## Roadmap (re-run 2026-09-23 evening, production activation directive)

This ordering authorizes nothing; `docs/EXECUTION_PLAN.md` does. Re-prioritizing never
authorizes implementation.

One system, built in this order: evidence, then policy, then the shared venue layer, then
venue-specific data, then models, then (later, separately authorized) execution.

**NOW** (critical path; authorized)
1. **Keep production collecting and verified** (#10, #11). DONE for activation: `7aac49c`
   deployed, 7/7 timers, backups and restores verified, fail-closed verified (see `HANDOFF.md`
   for the first real window). Ongoing: read each night's status and receipt. Oct 22: every
   day lost here is a Stage B day lost.
2. **Accumulate valid Stage B days and real shadow bookkeeping** (EXP-001). Runs by itself
   (captures 17:45–18:05 ET, status 18:30, shadow 18:40, settlement 11:15/16:15). Oct 22:
   about 29 possible days, so pipeline evidence and early descriptive results, never a
   verdict (180 valid days is out of reach).
3. **F09: refresh the independent checkpoint after real shadow entries exist.** The first
   checkpoint anchors only the two account openings. Manual export, store (laptop + Git) and
   off-host verify, weekly or after notable days. No scheduled anchor unless the owner
   approves one.
4. **Re-check Kalshi scheduled fee changes by 2026-10-23** (calendar-bound; otherwise
   claimability silently lapses).

**NEXT** (ready once the named prerequisite lands)
5. **#30 best-price-for-size comparator.** Engineering is unblocked: both book venues now
   emit `DepthLadder`s on one primitive and carry `Market.price_grid`. A result becomes
   meaningful (not just gross cost) only with rules-equivalence evidence and Polymarket US fee
   evidence (fees are UNSUPPORTED today). Parallel lane: yes. Oct 22: gross-cost comparison
   is feasible, and a claimable comparison depends on fee evidence.
6. **#30 cross-venue weather comparison** (Kalshi KXHIGHNY vs any Polymarket US weather
   market). Weather is the only domain with a model. Depends on 5 plus a Polymarket US weather
   catalog read and rules equivalence. Also depends on modelling or refusing the "resolves
   50-50" payoff seen in Polymarket US rules (PR #42 finding).
7. **#29 live Odds API pilot.** Built on fixtures. Depends on the owner's free key and an
   approved activation and quota plan.
8. **#33 ntfy push activation.** Built and disabled. Depends on owner approval for the first
   external send and on choosing a private topic. It would carry only fixed headlines.
9. **#3 / #6 dashboard and board on real data.** Now reachable privately on the phone. It
   fills as real shadow days arrive; no new build is needed first.

**LATER** (wanted; not on the 2026-10-22 path)
10. **#5 / #9 sports models and consensus comparison.** Each needs a preregistered
    experiment. They reuse #29 data, discovery and the opportunity engine.
11. **#27 Action PRO ingestion.** Schema ideas are in the audit (§7.10). It needs the
    owner's recorded permission evidence, a credential decision (login) and a sports
    experiment that would use it.
12. **#32 execution modes** (human-approved API, then bounded automation). The ticket control
    chain is built; execution needs a gate 8+ decision, a credentials policy and an execution
    boundary (Hummingbot lessons, audit §7.8).
13. **#33 SMS provider**, after ntfy proves the event model on a phone.
14. **Broader venues** (ProphetX, IBKR/ForecastEx), after the comparator shows incremental
    catalog value.

**BLOCKED** (named blocker)
- The Odds API live data: the owner's free key plus an activation plan.
- ntfy real send: owner approval.
- SMS: provider choice and approval (cost and registration).
- Novig live API: owner-requested developer credentials.
- EXACT fee claims: a verified account type and modelling of multi-fill rebates.
- Action PRO: owner permission evidence, a credential decision, and no purchase is authorized.
- Any execution: gates 8–10.

**Why priorities moved (2026-09-23 evening).**
- **Production deployment is no longer the binding constraint.** It was done from the owner's
  laptop session. The binding constraint is now the calendar: valid Stage B days accrue at
  most one per day.
- **#10 moved from LATER to IMPLEMENTED (private).** The owner chose tailnet-only access (ADR
  0024), which needs no DNS/TLS or public auth.
- **Polymarket US depth and the payoff/grid guards moved from NEXT to done** (PR #42). That
  moves the best-price comparator to the top of NEXT: it now waits on evidence (rules, fees),
  not engineering.
- **ntfy moved from NEXT (build) to NEXT (activation).** The build is done (PR #44); only the
  owner decision remains.
- The 2026-10-22 date is unchanged.

**UI foundation (2026-09-23, owner directive, issue #47).** The Market Edge Terminal v1 design
system is NOW / P0: one shell, token set, component layer and state vocabulary that every later
page reuses. Order: shared shell and components first (done), integration of the existing pages
second (done), future domains third (sports, politics, economics and new venues feed the same
`MarketRow`, detail, source list, comparison and Alerts contracts; no new global navigation for
a new sport or source). Deferred behind it: discretionary new feature screens. Not deferred:
collection, correctness repairs and the fee re-check. Oct 22 is unchanged. Shared-primitive
row: "Design system" above.

Related owner records that are not ideas:
- **#11 [Owner Directive] 30-day delivery plan (target 2026-10-22).** This is the active
  roadmap: deadline fixed, scope adapts, P0/P1/P2 change control. Gates still govern:
  "a gate does not pass because the calendar says it should".
- **#12 [Infrastructure] Brisket portability audit.** An owner-authorized parallel lane with
  its own branch and file claim. It does not touch Gate 3 files.

## Review log

- **2026-09-23 (evening): production activation directive and GitHub audit follow-ups
  (PRs #42, #43, #44, #45; #46 from the parallel Tailscale session).**
  - The roadmap above was re-run with the reasons it moved. #10 is IMPLEMENTED (private);
    #33 ntfy is built but disabled; #30 depth and the grid are built.
  - Shared primitives: one depth abstraction serves both book venues; the ticket control
    chain reads `risk.RiskPolicy` (one owner), not its own limits.
  - No idea was dropped. #27, #29 live, SMS and Novig live stay BLOCKED on named owner
    decisions.

- **2026-09-23: final portfolio review of the integration directive (PRs #34, #35, #37, #38, #39).**
  - The roadmap above replaces the chronological ordering.
  - #32 policy, #33 contract, #30 foundation and #29 adapter moved to IMPLEMENTED at their
    stated scope; the remaining parts are NEXT or BLOCKED with named blockers.
  - The shared primitives table now lists every built owner. None is duplicated.
  - Parallel lanes this session: fees, F09 and production tooling, then the policy and
    notifications, then the adapters. Each had one writer and built on shared contracts.

- **2026-09-23: integration and production directive (intake of #27, #29, #30, #32, #33).**
  - The re-planning rule was added to `AI_INSTRUCTIONS.md`, and the Shared primitives table
    was added here.
  - Shared-primitive analysis: #32's policy, #33's alerts, #30's venues and #29's odds source
    all sit on primitives that already exist or are planned once. None needs its own engine.
    - The starter policy extends the risk engine.
    - Notifications are one contract for #33, #3 and #32 exceptions.
    - Venues are one registry for #30, #29 and #32 execution capability.
    - The odds source uses the existing source registry and snapshots.
  - Parallel build: one shared contract per primitive, written by the coordinator. The
    venue-specific adapters (Polymarket US, Odds API, Novig) are then independent bounded
    lanes.
  - Roadmap: #32's policy and #33's contract are NOW. #30 and #29 are NEXT. #27 is
    LATER/BLOCKED. The final portfolio review of this directive updates this entry.

- **2026-09-23: daily-shadow directive (PRs #25, #26, #28).**
  - #3: the local read-only view now exists; hosting is still not authorized.
  - #6: risk limits are now enforced before each fill; still no real-money policy.
  - #10: units are staged but not installed. Dashboard hosting is NOT READY (no DNS/TLS or
    exposure authorization).
  - #5, #7 and #9 unchanged. There was no sports work and no paid source.

- **2026-09-23: Gate 4 → 5 → 6 and the risk foundation (overnight directive, PRs #21–#24).**
  - #6 and #3 moved to foundation-implemented (shadow and backend only).
  - #5 and #9 stay outside scope. The directive says no sports tonight.
  - #7 unchanged: no paid sources.
  - #10 unchanged: headless collector only; no subdomain or dashboard.

- **2026-09-22, Gate 2 → Gate 3 / Gate 3 PR.**
  - Classifications as above. None change Gate 3 scope.
  - #7's free-first principle drove the forecast-source choice (IEM PFMOKX).
  - The Kalshi fee-schedule PDF sits behind a bot checkpoint and is not bypassed, which
    is consistent with #7's "no circumvention".
- **2026-09-22, Gate 4 exit criteria met (PR #18); Gate 5 awaits the owner.**
  - #10 is partly authorized: the headless read-only collector only (ADR 0012).
  - No other classification changes.
  - #3 and #6 stay NOT READY until a shadow ledger with real forward data exists.
  - #5 and #9 stay outside scope: no sports work.
- **2026-09-22, Gate 3 → Gate 4 (Gate 3 PR, effective on merge).**
  - No classification changes: #3, #6, #9 and #10 stay NOT READY, #5 READY FOR RESEARCH,
    #7 APPLY SELECTIVELY.
  - #10 captured and indexed.
  - Per #11, the next P0 steps are Gate 4 (the frozen baseline) and forward market
    collection. That collection is the owner's scheduled-collection decision (ADR 0008),
    and #10 is a candidate host for it.
  - #6's risk foundation and #3's Outcome Board are #11 P0 items for later in the month.
    They stay NOT READY until a shadow ledger exists.
