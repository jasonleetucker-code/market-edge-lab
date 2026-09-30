# Owner Ideas

Durable owner requirements live in GitHub `[Owner Idea]` / `[Owner Directive]` issues. This is the current index and canonical shared-owner map, not a replacement for the issue bodies.

## Current delivery order

**Read [the integrated delivery roadmap](strategy/DELIVERY_ROADMAP.md) for the full dependency order, completion criteria, evidence gates and next batch.** It incorporates #145's podcast lessons and all ideas indexed below. The companion [Claude handoff](strategy/CLAUDE_SPORTS_INTELLIGENCE_RFQ_V1.md) specifies the next bounded implementation mission.

This consolidation is dated **2026-09-29 America/New_York**, audited against main `73b54cab8a3e383961550ef3086df6235b1e03b4` (#144). Runtime facts remain in `HANDOFF.md`; **only `docs/EXECUTION_PLAN.md` records implementation/operational authority**. A roadmap item, issue, proposal or podcast claim grants no account, trading, data-license, spending, schedule or gate permission.

The previous complete index, shared-owner table, roadmap reruns, domain-readiness matrix and review log are preserved **byte-for-byte** in [the historical archive](strategy/archive/OWNER_IDEAS_pre_podcast_2026-09-29.md), using original Git blob `b0689cc48dfc8dd127636b67f7b0a3dc1d0e323d`. This is an explicit consolidation of stale duplicated current-state prose, not deletion of owner intent. The archived schedules/statuses are historical; current ordering below and in DELIVERY_ROADMAP wins where dated plans conflict.

## Intake and readiness rules

- Capture material owner ideas in a canonical issue; search for overlap first. Record enough context for a fresh model and link related requirements.
- Re-plan material additions in the same session: priority, dependencies, overlap/supersession, shared owners, safe lanes, October 22 effect and authority.
- NOW means within the current critical path **and** existing authority. NEXT means a named prerequisite remains. LATER retains wanted scope off the immediate path. BLOCKED names evidence, access or owner authority still needed. DONE/MAINTAIN is an implementation status, not proof of edge.
- Preserve protected EXP-001 and the #96 limit of two new ACTIVE hypothesis families. An offline fixture or passive, authorized source is not a new hypothesis. Do not hide an empirical strategy behind those labels. EXP-003's pause does not silently assign a slot to #122 or RFQ.
- Never infer TESTED, CI_GREEN, MERGED, DEPLOYED, PRODUCTION_VERIFIED or research success from an earlier state.
- Use one canonical owner per concept. New modules below are planned only where no implementation is established; inspect current code before creating one.

## Complete current idea index

| Issue | Requirement | Current placement / next dependency |
|---|---|---|
| #4 | Durable idea intake / readiness process | DONE/MAINTAIN; keep this index, issue truth and roadmap aligned |
| #11 | October 22 delivery / live-readiness goal | Cross-cutting checkpoint; software/evidence readiness, not a promised positive verdict or trade date |
| #3 | Outcome Board / what matters today | Existing backend/view; integrate readable event identity, inventory/risk, outcomes and actual unavailable states; no separate app |
| #47 | Market Edge Terminal design system | Existing shell/tokens/components; mobile, desktop, accessibility, empty/stale/unsupported/error states accompany every user-visible package |
| #10 | Private hosting on existing infrastructure | DONE/MAINTAIN; current deployment/runbooks and isolation, no public site exposure implied |
| #5 | Sports expansion and modeling | NFL EXP-002 active DRAFT; NHL collection separate; later sport/model experiments need budget, protocol and slot |
| #9 | Sportsbook consensus / cross-market comparison | Baseline implemented; finish current fee/timing/rules questions. #145 adds future conditional source leadership, not a retroactive baseline rewrite |
| #29 | The Odds API pilot | NFL and NHL use one joint 450-credit monthly proof/ledger, NFL reservation first; no extra paid plan or ceiling assumed |
| #134 | NHL prospective evidence | BUILT/ACTIVE per latest handoff; opening observations recorded. NEXT: coverage, protected-window mismatch, schedule-time, fee/shootout-rule review; not NFL validation or a new hypothesis |
| #122 | In-play positions: HOLD/REDUCE/EXIT, then REENTER/ADD | Offline evidence/policy/replay/Terminal foundation BUILT. NEXT: scoped recorder approval and source-quality evidence; state-aware models/re-entry later; live actions BLOCKED |
| #145 | Conditional price discovery, RFQ/combos, adverse selection and full roadmap integration | NOW planning and source-backed feasibility; NEXT shared state/latency/attribution additions within granted scope. RFQ observation/quoting/empirical joint pricing require separate access/slot/authority |
| #30 | Multi-venue identity, best price and unique markets | Existing Kalshi/Polymarket foundations and best-size comparator; fees/rights/equivalence gaps remain. Novig and further routes follow a specific need; one execution route deeply before many |
| #6 | Bankroll, risk, sizing and withdrawal guidance | Shadow foundation and sizing-v2 challenger exist; evidence/review before operational promotion. Extend one risk owner, never a live shortcut |
| #32 | Starter capital horizon / execution preference | Keep STARTER_MAX_7D_V1 and 168-hour venue-tradable-cash meaning; hoped-for early sale does not satisfy it. One-venue order/reservation rehearsal before live |
| #93 | Bootstrap Capital Mode | NOW inside economics/capacity; separate total/deployed return, turnover, lockup, drawdown and fixed cash cost; actual bankroll not inferred from examples |
| #50 | Longitudinal evidence, including rejected opportunities | Existing immutable provenance and lineage; extend denominators, no-fill/unknown records, revisions and evidence-consumption logs |
| #74 | Always-on Freshness Fabric | Existing supervisor and sport-specific identities; conditional game-state validity extends it. New cadence/control requires evidence and scope; no duplicate schedulers |
| #7 | Free-first / paid-source value | Permanent constraint: marginal research/execution value case before a purchase; free is not automatically sufficient and paid is not automatically better |
| #27 | Action PRO / subscription comparisons | LATER/BLOCKED on a named hypothesis, rights, incremental value and owner spending approval |
| #36 | Selective external implementation reuse | Reuse only after current audit/license/compatibility review; no other-repository edits in a Market mission |
| #86 | Cross-domain prospective evidence | Acquisition and multi-city design exist. Purpose-budgeted streams only; preserve all intended domains in R9 without automatic firehose rollout |
| #88 | Equities/ETFs, options, futures and intraday research | Retained first-class domain, queued by slot/economics. Slower SEC/earnings first; later volatility/replication, exact contract futures/macro; data/broker prerequisites explicit |
| #82 | Adaptive Learning Engine | Existing lineage/evaluation first; source value, calibration, execution/economic/capacity drift, champion/challenger review. AutoML/online/RL later; auto-train never auto-live |
| #83 | Outside capital, unit/NAV accounting and fee governance | LATER/BLOCKED; simulated design then legal/entity/custody/tax/venue and owner approval. Separate investor gains from manager compensation; no friend-money pooling now |
| #33 | Notifications / SMS / ntfy | Existing outbox/relay; phone delivery unresolved and owner-deferred for current research. Reliable alert/incident path required before unattended live; no new test/send from this plan |
| #96 | Evidence-to-economics reset | Governing strategy: evidence, after-cost dollars, executable size, capacity and survival before breadth. Full roadmap does not mean every experiment active together |

## Shared primitives (one canonical owner each)

Implementation existence and production state are different. This table names ownership; it does not certify a complete audit of every module.

| Concept | Canonical owner / subordinate components | State and integration rule |
|---|---|---|
| Event/market identity, rules and probability/payoff semantics | `src/edge_lab/opportunity.py`; `discovery.py` for cross-venue mapping | Existing. Title similarity never proves equivalence; native quantities and probability types stay explicit |
| Venue/account capabilities | `src/edge_lab/venues.py` | Existing. Data, account read, order book making, RFQ observation/quoting and order writes separately verified |
| Quote/depth and requested-size economics | `opportunity.py`; `best_price.py` | Existing. Price/fee/depth/availability separation; no guaranteed fills or duplicated liquidity |
| Fees and effective-date verification | `fee_schedules.py`, reusing frozen `fees.py` where appropriate | Existing. No silent fallback to a wrong series/routing scope; frozen EXP-001 assumptions preserved |
| Source registration, raw evidence, rights | `sources.py`, `storage.py`, `provenance.py`, `redaction.py` | Existing. Permission inheritance and immutable received-at evidence; no second evidence database |
| Freshness supervision and source/game-state eligibility | `freshness.py`, `freshness_fabric.py`; existing `inplay_*` evidence contract for state versions | Existing base; #145 conditional state validity planned as an additive extension, not a new scheduler |
| Sportsbook math and capture | `odds_api.py` math, `odds_consensus.py`, `odds_schedule.py`, `odds_pilot.py` | Existing. Preserve EXP-002 baseline; one shared budget and decision-cutoff semantics |
| Later/closing and paired market observations | `price_observations.py`, `sports_evidence.py` | Existing. Preserve actual lead/skew, missing targets, join immutability and label withholding |
| Event/release calendar | `event_calendar.py` is a PLANNED owner; verify before creation | Shared calendar, not one per domain |
| Model estimates | `opportunity.py` | Existing contract; available models are not inferred from a domain enum |
| Research registry, slots, frozen protocols | `experiments.py` and per-experiment artifacts | Existing. EXP-001 unchanged; explicit additional family lifecycle |
| Evidence use / attrition | `research_evidence.py` | Existing. Logs declared access, does not prove unseen access never happened |
| Economic screens, episodes, capacity and attribution | `research_economics.py` | Existing. Extend maker/taker/RFQ/regime dimensions; unknown execution stays unknown; owner hours remain unpriced |
| Source leadership / latency analysis | Subordinate report under research/evidence contracts; implementation path selected only after code review | Planned #145 extension, no permanent sharp-source weights or second learning engine |
| Deterministic payoff constraints | `payoff_constraints.py` | Existing. Not a joint-probability model; current EXP-003 scope paused |
| In-play policy and replay | `position_policy.py`, existing `inplay_*` modules | BUILT offline. Extend rather than recreate; same entries and terminal-wealth baseline; no account transport |
| RFQ evidence/lifecycle adapter | One planned subordinate `rfq_research.py` owner, subject to overlap audit | Feasibility first; use common venue/evidence/economic/execution contracts; no competing broker stack |
| Joint payoff/probability pricing | Planned subordinate research component; no new generic engine yet | Logical constraints vs conditional probability separated; only after a viable scoped RFQ study |
| Ledger and checkpoints | `shadow_ledger.py`, `ledger_anchor.py` | Existing shadow only. Future live adapter must not rewrite frozen simulation history |
| Risk and sizing | `risk.py`; `sizing.py` frozen path; `sizing_v2.py`, evaluation/counterfactual components | Existing. No policy promotion or new money from roadmap changes |
| Capital eligibility | `starter_policy.py` | Existing 168-hour policy; risk/cash semantics unchanged |
| Execution ticket / future durable lifecycle | `execution_ticket.py`, current execution ADR | Contract exists, financial transport disabled. Reservations, fencing, unknown/cancel races and external reconciliation require a bounded later implementation |
| General instrument selection | `instrument_selection.py` planned, deferred | Build only after two concrete expressions justify it; not a pre-live universal optimizer |
| Notifications | `notifications.py` and current relay | Existing; preserve origin/secret controls and deferred phone status |
| Backup / restore | `backup.py` and current runbooks | Existing retention/manual apply/off-host verification. Do not repeat destructive actions or infer current restore from old success |
| UI / operator views | `src/edge_lab/dashboard/`, `outcome_board`; `docs/design/UI_CONTRACT.md` | Existing one shell. No feature is UI-complete until evidence/empty/error/mobile states are reviewed |

## Current review entry — #145 integration

**2026-09-29:** replaced the accumulating duplicated live-roadmap prose with a current index plus one dependency plan, archiving the previous file unchanged. Podcast-derived ideas remain attributed hypotheses, not verified profitability. Conditional source leadership and state-aware policy validity extend #9/#74/#122/#82. RFQ feasibility is a new bounded candidate with private-visibility and joint-pricing constraints. #96 focus, #93 bootstrap economics, EXP-001 freezes and all authority boundaries remain.

Immediate next batch: **Sports Intelligence & RFQ Feasibility v1**. Read DELIVERY_ROADMAP and its Claude handoff. Do not rebuild #122 or NHL capture; do not revive rejected noise-gate ideas or run the deployed A.C tool before its permitted post-pilot window. Historical review entries and their supersessions are in the archive.
