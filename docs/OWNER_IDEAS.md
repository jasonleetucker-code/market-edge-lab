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
| Quote / order-book normalization | `src/edge_lab/opportunity.py` | BUILT (ExecutableQuote; Kalshi only) | #30 #9 #29 |
| Fee models and fee verification | `src/edge_lab/fee_schedules.py` | BUILT (Kalshi, with dated component-level verification records, ADR 0017; other venues unsupported). It reuses the hash-frozen EXP-001 cost model in `fees.py`, never forks it | #6 #30 #9 |
| Model estimates | `src/edge_lab/opportunity.py` | BUILT (ModelEstimate; EXP-001 only) | #5 #9 #32 |
| Source ingestion and provenance | `src/edge_lab/sources.py` | BUILT: the registry, fronting `storage.py` (snapshots) and `provenance.py` | #7 #29 #30 #27 |
| Rules / settlement equivalence | `src/edge_lab/opportunity.py` | BUILT (`Event.settlement_identity`, `Market.rules_resolved`); cross-venue matching not built | #30 #9 |
| Shadow / live ledger boundary | `src/edge_lab/shadow_ledger.py` | BUILT (shadow only; no live ledger; head checkpoint for F09 planned beside it) | #6 #3 #32 |
| Risk engine | `src/edge_lab/risk.py` | BUILT (limits, capital release, withdrawal contract) | #6 #3 |
| Capital-eligibility policies | `src/edge_lab/starter_policy.py` | BUILT (`STARTER_MAX_7D_V1`, ADR 0018); enforced prospectively in the operational shadow account | #32 #6 |
| Notification system | `src/edge_lab/notifications.py` | BUILT (contract, local outbox, SMS sink disabled; ADR 0020) | #33 #3 #32 |
| Execution-ticket contract | `src/edge_lab/execution_ticket.py` | BUILT (data contract only; execution disabled) | #32 #33 #30 |
| Operator views | `src/edge_lab/dashboard/` | BUILT (local, read-only) | #3 #6 #10 |

## Index

| Issue | Idea | Readiness | Why / prerequisites |
|---|---|---|---|
| #4 | Durable idea intake and readiness backlog (process) | **Implemented** 2026-09-22 (Gate 3 PR) | `AI_INSTRUCTIONS.md` rule + this index |
| #3 | Outcome Board / What Matters Today dashboard | **BACKEND + LOCAL VIEW IMPLEMENTED** 2026-09-23 (PR #28); hosting NOT READY | `edge_lab.outcome_board` (ADR 0015) plus the `/outcome-board` view of the local read-only dashboard (127.0.0.1 only). Hosting, auth and live marks are unauthorized and not built. |
| #5 | Sports prediction-market and sports-modeling expansion | **LATER** (discovery and data foundations NEXT via #29/#30; any sports model BLOCKED on a preregistered experiment) | Core framework is proving out on weather. Needs the shared identity, venue and equivalence layers; the 2026-09-23 directive authorizes data foundations only, not sports models. |
| #9 | Sportsbook odds aggregation, consensus pricing, best-venue comparison | **NEXT** (The Odds API data foundation via #29); comparison LATER | Sub-idea of #5. Needs market equivalence and verified access terms. Offered odds are never executable prices. |
| #6 | Dynamic bankroll, position sizing, withdrawal guidance | **P0 FOUNDATION IMPLEMENTED** 2026-09-23 (shadow only) | Shadow ledger (ADR 0014), `suggest_position_size`, and the risk/capital report with a withdrawal contract (ADR 0015). The withdrawal contract never recommends a draw. Since PR #26 the operational shadow account enforces the risk limits **before** each fill (NO_FILL RISK_VETO); the frozen research account is separate. A real-money policy, a verified edge and verified fees are all still missing. |
| #10 | Host privately on existing Chase Upside infrastructure (separate service/subdomain, real access control) | **PARTLY AUTHORIZED** 2026-09-22: headless read-only collector only | Forward collector authorized on the VPS as a separate service (ADR 0012; headroom review `docs/deploy/VPS_REVIEW_2026-09-22.md` PASS). Daily shadow and settlement units are staged in the repo (PR #26) under the 2026-09-23 authorization but not yet installed (owner SSH step). Dashboard hosting, subdomain, DNS/TLS and auth remain NOT READY and unauthorized; the dashboard is local only. |
| #7 | Free-first multi-domain ingestion with paid-source ROI gate | APPLY SELECTIVELY NOW | Gate 3 applied it: the free IEM archive of NWS forecasts was chosen and paid weather data was not considered. The general ingestion platform is not built. |
| #32 | Starter policy: 7-day capital-release limit, broad discovery, API-first execution preference | **NOW** (starter policy, P0); discovery NEXT; execution BLOCKED (no live authority) | `STARTER_MAX_7D_V1` is authorized by the 2026-09-23 integration directive. The governing clock is venue-tradable cash within 168 h. It uses the risk primitive plus venue timing evidence. |
| #33 | SMS-first alerting through one shared notification layer | **NOW** (provider-neutral contract); SMS delivery BLOCKED (paid provider needs owner approval) | Serves collector failures, qualification alerts, policy exceptions and future approval tickets. |
| #30 | Multi-venue coverage, best-price comparison, unique-market discovery | **NEXT** (Kalshi, Polymarket US and Novig public data after the P0 policy work) | Needs the venue capability registry, rules equivalence and per-venue fee evidence. Polymarket US public data needs no access; Novig live API needs owner-provided developer credentials (separate approval). |
| #29 | The Odds API free tier (quota-capped sports odds pilot) | **NEXT** (fixtures, quota and redaction); live pulls BLOCKED (owner free key) | Sportsbook-consensus input for #5/#9. Offered odds are never executable prices. A 450-credit protective ceiling. |
| #27 | Action PRO permission and comparative sports-data subscription value | **LATER / BLOCKED** (no purchase authorized) | Paid source; needs the #7 ROI gate and a sports experiment that would use it. |

Related owner records that are not ideas:
- **#11 [Owner Directive] 30-day delivery plan (target 2026-10-22).** This is the active
  roadmap: deadline fixed, scope adapts, P0/P1/P2 change control. Gates still govern:
  "a gate does not pass because the calendar says it should".
- **#12 [Infrastructure] Brisket portability audit.** An owner-authorized parallel lane with
  its own branch and file claim. It does not touch Gate 3 files.

## Review log

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
