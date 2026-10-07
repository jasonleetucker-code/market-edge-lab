# Kalshi automation delivery campaign — #160

**Date:** 2026-10-07. **Basis:** `docs/research/KALSHI_AUTOMATION_AUDIT_2026-10-07.md`, owner-uploaded automation-readiness assignment, and inspected main `950c8372c475b9554a1cd0338c6f48517703dd24`.

This is an implementation **proposal** elaborating existing DELIVERY_ROADMAP R5/R10. It does not replace the master roadmap, authorize its own runtime implementation, approve credentials or demo/production requests, change the frozen experiments, or grant live authority. Execution scope belongs in EXECUTION_PLAN after an actual owner decision.

## 1. Finish line and scope

Complete one deterministic, recoverable Kalshi **ordinary event-order** integration. It must support valid entry/reduction, fixed-point quantities, bounded limit prices, supported time-in-force modes, cancellation/amendment, partial fills, account history, reservations, risk, private approval and reconciliation. It must remain usable by different qualified strategies without copying the executor for each sport.

This does not promise execution for every Kalshi product. RFQ negotiations, multivariate pricing, futures/perpetuals, cross-venue legs, automated transfers and investor accounts are not implicitly supported. The capability profile must explicitly reject excluded products/actions. Ordinary-event readiness is not universal-venue readiness.

Choose a simple **demo instrument** for the first complete lifecycle based on actual mock-market availability, supported units, observable fills and settlement/close. A synthetic demo signal is software evidence, not an alpha strategy or permission to alter EXP-001/EXP-002. Do not block the executor build on finding a profitable model; do not use executor completion to lower strategy standards.

### Milestones

| Milestone | Required evidence | Does not imply |
|---|---|---|
| OFFLINE_EXECUTION_CORE_COMPLETE | Deterministic end-to-end and fault/concurrency tests on disposable stores; reviewed isolated boundary | Account connectivity or real fills |
| DEMO_LIFECYCLE_VERIFIED | Authorized official demo receipts, account/order reconciliation, crash/restart exercises; residual capabilities explicitly listed | Production parity, alpha or real-money approval |
| PRODUCTION_ACCOUNT_SHADOW_VERIFIED | Authorized production reads, complete account reconciliation and current data/fee profile; no write requests | Real order acceptance/fills |
| KALSHI_AUTOMATION_READY | Declared ordinary-event profile satisfies its acceptance matrix, security/operations and access prerequisites; no unresolved critical safety blocker; production write remains off | Strategy profitability, LIVE_AUTHORIZED, universal RFQ support |
| TINY_LIVE_READY / LIVE_AUTHORIZED | Separately qualified strategy, exact owner-approved capital/pilot, necessary credentials and operational checks | Unattended or larger-scale approval |
| UNATTENDED_LIVE_AUTHORIZED | A later explicit policy after live/shadow reconciliation and reliable incident response | Unlimited models, accounts, risk or spending |

A missing credential/provider stage prevents the corresponding verified status. It does not prevent independent offline engineering. Do not replace missing demo evidence with a synthetic receipt labelled DEMO_VERIFIED or force a YES verdict because it is the requested finish line.

## 2. Authority partition

| Work | Current assignment | Next necessary boundary |
|---|---|---|
| Research, source verification, documentation PR and owner decision packet | Authorized by uploaded assignment | Normal claims/review |
| New isolated execution code and revised no-execution invariant | Proposed, not self-authorized by this document | Explicit scope/ADR reviewed and recorded before implementation |
| Fixture signing using generated test keys, fake transport and disposable stores | Part of proposed offline scope | Never production material or real account calls |
| Demo signup/key/mock account tests | Not performed or implicitly approved here | Owner setup and bounded demo action approval |
| Production account reads | Not performed/approved here | Owner scope/key/rights decision, private deployment and endpoint limits |
| Existing collectors | Continue only existing authority | No new budgets, intervals, datasets or credentials |
| New in-play/RFQ acquisition | Separate | Existing rights/pilot/slot/budget requirements |
| Production order transport code | Build only in approved isolated scope; hard-disabled | No actual write before separately approved live pilot |
| Merge/deploy | Follow actual class-specific delegation | #153 owner merge boundary must not be bypassed |
| Live, funds, margin, outside capital, paid services | Not authorized | Separate owner decisions and applicable qualification |

Avoid two opposite failures: asking the owner to invent routine technical settings, and pretending that an agent-generated plan grants consequential permissions. Present exact grouped approvals early; keep completing independent work.

## 3. Dependency graph and safe work organization

The campaign is not capped at three PRs. Each package below is a coherent acceptance boundary; split/merge packages based on actual code ownership rather than arbitrary PR counts.

```
A baseline/reconcile → B conformance → C security boundary
                            ↓                  ↓
                      D private journal → E atomic reservation/fencing
                            ↓                  ↓
                      F signer/transport → G complete account reads
                            ↓                  ↓
                      H canonical lifecycle ← I risk/strategy ticket
                            ↓                  ↓
                      J feed/reconnect → K demo orchestration
                            ↓                  ↓
                      L recovery/kill → M account-aware shadow
                            ↓                  ↓
                      N approval UI → O private operations/release
                            ↓                  ↓
                      P chaos/load + Q independent conformance review
                                      ↓
                      R authorized demo → S production-read rehearsal
                                      ↓
                          T evidence-backed readiness certification
```

Dependencies are semantic. Persistence contracts must precede dependent writers, while source/fee documentation, UI fixture design and security review can run independently. Two or three non-overlapping implementation writers plus an independent reviewer are sufficient; do not create a role-name army. One coordinator owns shared contracts and canonical docs. Claim exact paths; expired claims do not erase an active PR's work.

Reconcile #153/#158 and preserve #161's capture fix. Do not mechanically merge all three: verify authority, review and current CI for each. The two NHL planner test failures reported on main require independent reproduction and a separately owned fix if still present; no skipping unrelated failures to claim a green release.

## 4. Proposed ownership and persistence design

Keep `execution_ticket.py` the conceptual lifecycle/reservation/approval contract owner and extend with clearly subordinate modules. Suggested paths (finalize only after checking current tree): `edge_lab/execution/` for private store, pure reducers, Kalshi wire adapter, signer and worker. Register the actual owners; do not create another strategy/risk/fee authority.

- `opportunity.py`: instrument identity, units, grid and typed opportunity semantics.
- `fee_schedules.py`: versioned fee/account-regime verification and allowed scopes.
- `risk.py`: pure risk rules over a versioned account projection; legacy shadow behavior unchanged.
- `execution_ticket.py`: normalized bounded intent and approval contract, reservation semantics and lifecycle.
- subordinate private execution store: transactional intent/attempt/obligation/receipt projections, not a second financial formula implementation.
- `shadow_ledger.py`: protected research history remains unchanged; its data must not be relabelled live.
- `inplay_evidence.py`: source/sequence/as-of lineage reused; do not create another recorder/reconstructor.
- `dashboard/`: sanitized read projections and separately authenticated commands; no signing keys in UI.
- `backup.py`: extend safe backup/recovery support for new private persistence only after its ownership/retention policy is approved.

Use integer fixed-point units or Decimal-backed serialized strings for authoritative quantities/money; reject bool, NaN, infinity, negative quantities and off-grid values. No Decimal constructed from an already rounded binary float. Do not guess missing fee or balance units from a number's magnitude.

Keep raw provider receipts immutable where permitted, derived projections rebuildable, and credentials separate. A transactional materialized balance is acceptable as a projection if a journal replay reconstructs it and updates are atomic; no second source of P&L truth.

## 5. Work packages A–T

### A — Reconcile baseline and register scope

**Objective:** a reproducible base, reviewed pending PR integration and exact ownership/authority. **Paths:** AI instructions, EXECUTION_PLAN, claims, HANDOFF, current tests and #153/#158/#161. **Depends:** current read.

**Acceptance:** record exact base/deployed verification date, PR heads and review/CI; preserve local/unpushed work; identify failed baseline tests; locate all existing interfaces; record scoped runtime approval before adding signing/order code. No protected outcomes viewed. **Tests:** baseline suite and frozen artifacts; when unavailable, clearly blocked, not a fabricated pass. **Production:** none by this package alone. **Parallel:** coordinator-owned.

### B — Current API, payoff and account conformance pack

**Objective:** machine-testable documented wire contracts, not copied README assumptions. **Owners:** venues/opportunity/fee contracts and sanitized fixtures. **Depends:** A.

Cover production/demo environment separation; Ed25519/RSA; bid/ask and YES/NO conversions; fractional quantities; native ticks; account/subaccount/shard identifiers; fee rounding regimes; time-in-force, reduce-only, cancel-on-pause and self-trade semantics; cancel/amend response meanings; live/history pagination and watermarks; rate token costs; order groups; settlement exceptions.

**Acceptance:** each fact has version/date/source/evidence class; unknown/conflicting semantics remain unsupported. Document which API capabilities are unavailable in demo/account. **Tests:** official-example fixtures labelled documentation, malformed numbers, mixed units, optional fields, deprecated fields and incompatible products. **Production:** no calls. **External verification:** primary docs and later authorized account observations.

### C — Isolated execution security boundary

**Objective:** permit only the reviewed executor to authenticate or send approved commands while research remains non-financial. **Owners:** security ADR, invariants, import boundaries, config/worker allowlists. **Depends:** A/B and explicit runtime scope.

Use a distinct execution identity, private storage and sanitized IPC/interface. Research/LLMs cannot load signer/config/key objects, arbitrary URLs or command bodies. Exact environment and host allowlists; redirects cannot forward credentials. No provider default-full-access key accepted without scope evidence.

**Acceptance:** mutation tests demonstrate that signing/order/credential code added to any unauthorized module fails; unknown mode defaults off; credential presence alone cannot arm execution. Full-history/current-tree/artifact/dependency scan performed locally before credentials; record limitations rather than security-clean claim from filenames. **Production:** no credential installation or host changes without additional approval. **Parallel:** security reviewer independent; boundary contract centralized.

### D — Private durable execution journal

**Objective:** survive a kill at every point without losing intent or duplicating local state. **Depends:** C.

Persist immutable business intent, decision/approval digest, source evidence, attempt identity, environment/account/subaccount/shard, request body digest, risk-policy version, reservation, send status, provider receipt, fill, cancellation, settlement and correction. Distinguish business intent from transport attempt; creation time alone cannot supply business deduplication.

**Acceptance:** intent/reserve and pending egress committed before send; same key/same payload is idempotent, same key/different payload conflicts; durable writes and restart replay; local telemetry failure policy separated from essential journal failure. **Tests:** pre/post-commit kills, disk full, lock timeout, corrupt record, duplicate receipt and altered payload. **Production:** new private schema designed only, no migration of frozen research.

### E — Atomic cash, inventory and risk reservations with fencing

**Objective:** extend pure obligation calculation into one transactional authority. **Depends:** D and B.

Include existing external/manual/native orders, pending and unknown submissions, fees and full simultaneous obligations. Track venue-held cash separately from local not-yet-reflected reservations to avoid both double counting and overspending. Account synchronization revisions must be explicit. Unknown state retains conservative reservation; a network partition/lease expiry does not prove the old worker cannot still send.

**Acceptance:** only one fenced egress authority; stale workers rejected before external send; two candidate transactions cannot spend/sell the same capacity; no unsupported cross-market netting. **Tests:** concurrent workers, paused process, lease takeover, all RFQ-like obligations binding (fixtures only), lost cancel, partial fill, manual sale, inconsistent balance and database restart. **Production:** none until approved private worker deploy.

### F — Signer and environment-specific transport

**Objective:** maintained cryptography plus safe transport shared by demo/production through isolated configuration. **Depends:** B/C/D.

Fixture keys only in unit tests. Verify parsed key type and official pre-sign bytes; no secret echo, body leakage, environment fallback or arbitrary request signing. Bind local authorization to the whole command, because the provider signature's format is not our approval envelope. Rate budgets account for actual documented tokens and shards, bounded retries, read freshness and reserved cancel/reconcile capacity.

**Acceptance:** deterministic request serialization; keys never exported to caller; production write disabled even if keys exist; only allowed method/path/account pairs; TLS verification; timeout uncertainty explicit. **Tests:** wrong algorithm, clock skew, query stripping, invalid key, redirects, wrong account/host, malformed scopes, retry after ambiguous response and log redaction. **External:** documentation only until separately approved test access.

### G — Complete account-read reconciliation

**Objective:** trustworthy balances, orders, positions, fills and settlement history across all approved dimensions. **Depends:** D/F.

Read all relevant pages/subaccounts/shards, live and historical tiers, approximate update timestamps, overlapping cutoffs and corrections. Requests are not one atomic snapshot; define bounded resampling/watermark reconciliation. Distinguish pending transfers, settled tradable cash, holds, reserved amounts, realized/unrealized value and bank-withdrawable funds where actually returned.

**Acceptance:** missing field/page/access never equals zero/flat; complete scope manifest; unidentified manual holdings block or conservatively consume capacity under policy, never disappear; no blanket cancel/flatten to simplify recovery. **Tests:** default-unsettled omission, archive moves mid-read, duplicate fills, cursor loops, incomplete pagination, stale updates, unknown subaccount, account unit changes and missing old settlement fields. **Production:** adapter offline first; authenticated reads require explicit scope.

### H — Ordinary event-order state machine and reducer

**Objective:** correct pending/unknown/resting/partial/filled/cancel/amend/terminal handling. **Depends:** D/E/F/G contract.

Use cumulative executed quantity plus remaining/canceled quantity and terminal status; canceled does not mean never filled. Match actual venue identities, not price coincidence. Persist before transmission, receive/reconcile idempotently and never retry an ambiguous submission blindly. An amendment's total-count semantics differ from desired remainder. Cancellation does not immediately free inventory/cash.

**Acceptance:** exact order/fill/position relationships; terminal state cannot lose late receipt information; unknown orders quarantined until established by adequate external evidence; local exactly-once application is distinguished from unproven provider exactly-once execution. **Tests:** every legal transition plus timeout at each stage, late fill after cancel, partialIOC, malformed ACK, duplicate/out-of-order receipts, order replaced and old fills delayed. **Production:** fake transport only until authorization.

### I — Risk and strategy-ticket versioning

**Objective:** a domain-neutral proposal cannot bypass account/risk controls. **Depends:** B/E/G/H interfaces.

Version action-specific ticket semantics for entry, reduction and forbidden flips; actual account/fee/regime dimensions; source/model/strategy version; instrument and native quantity; expiry/maximum price and fees; evidence identity; risk state; supported TIF. Keep EXP-001 output stable. Check per-order/market/event/cluster/strategy/account/shard/global exposure, realized/unrealized drawdown definition, rolling loss, daily new risk, reserve, slippage/fees/depth, source/book/decision age, exchange state, correlation, order count and reconciliation.

**Acceptance:** every missing or stale required input yields an explicit rejection; a held position's historical cost is not blindly substituted for current opportunity cost or marginal flip risk; deposits are not P&L and cannot reset a loss limit. **Tests:** Decimal boundaries, unknown market type, stale policy, change of quantity after approval, correlated simultaneous commitments, negative/NaN/bool values, count reset on restart and unsupported account semantics. **Owner:** exact real limits remain owner choices; propose reasoned options.

### J — Streaming order/book/account recovery

**Objective:** reconcile stream observations and REST without fictitious continuity. **Depends:** B/G/H; reuse R3 evidence.

Preserve sequence scope, subscription identity, event/source/send/receipt clocks, duplicate conflicts, gap quarantine, snapshot baseline and REST catch-up. No unverified source-time substitution or backwards correction. Relevant state change invalidates pending decision until re-evaluated.

**Acceptance:** post-gap state usable only after proof; missing private messages trigger reconciliation; subscription reconnect not order cancellation; message-rate bounds cover incoming traffic, not merely retained rows. **Tests:** reconnect storm, dropped delta, new SID, concurrent markets, corrected touchdown, receipt-order anomalies and endpoint disagreement. **Production:** no new stream without explicit credential/source/budget approval.

### K — Demo orchestration and synthetic strategy bridge

**Objective:** same core execution path, mock environment, one explicit simple capability profile. **Depends:** F–J.

Use a synthetic signal generator with a conspicuous demo identity, not a fake research promotion. Market selection should demonstrate real mock order mechanics, not profitability. Unknown demo capability stays unsupported; never fallback to production. Allowed operation sequence and maximum mock activity are approved separately.

**Acceptance:** same reducers/reservation/risk as future production; fixture runner can execute the complete sequence before credentials; actual demo reports only actions/receipts actually observed. **Tests:** testnet/prod host mismatch, accidental live key, market unavailable, no liquidity, unsupported order modes, unknown fees and restart. **External:** owner must create/install demo access; no account creation by this campaign document.

### L — Kill, recovery and emergency semantics

**Objective:** stop new risk durably and reconcile what remains, including when cancel/exit cannot happen. **Depends:** D–J.

Global/venue/strategy/market switches, NEW_RISK_DISABLED, owned-order cancel request and separately authorized closeout. Ordinary outages must not lead to blanket flattening. Auto Sell/manual orders are attributed and reserved. Persist latches across restart; order-group reset is a privileged reviewed action, not automatic recovery.

**Acceptance:** command prevents subsequent new-risk egress even with queued tickets; true endpoint cancellation unavailability visible; restarts do not rearm automatically; recovery reads venue state before new orders. **Tests:** kill between sign/send, diskfull/workerfreeze, stale fencing, pending cancels, exchange halt, late fills, unavailable alerts and lost API access. **Production:** activation policy separate.

### M — Account-aware shadow

**Objective:** run the exact deterministic chain against authorized account state with no writes. **Depends:** G–L.

Produce WOULD_SUBMIT or BLOCKED with full intent and hypothetical reservation. Hypothetical state must not reduce real available cash or interfere with current manual trading; keep its journal mode distinct. No outcomes or future fills may be used to choose proposed entries.

**Acceptance:** no network mutation possible under read-only process identity; all relevant constraints and external orders included; exact repeatability from input versions. **Tests:** strategy proposes forbidden side/size, changed fees, native order overlap, outdated snapshot, absent history and proxy attempt to reach signer. **External:** only production account-read approval unlocks genuine account-aware verification.

### N — Human approval and private operator interface

**Objective:** owner understands and approves exact immutable terms without sharing secrets. **Depends:** I/M; UI fixture work earlier.

Use existing Terminal components with actual/fixture/demo/read-shadow/live state labels. New commands need authentication/authorization, same-origin/CSRF defenses, anti-replay and a short-lived intent binding. Approval covers environment/account, strategy/version, instrument, side/action, total quantity, limit/TIF, fee/max-cost, expiry and risk digest. Recheck state before send; do not silently substitute a changed order.

**Acceptance:** display actual held/reserved/pending/unknown cash and inventory, fills/order-state discrepancies, last successful reconcile, current armed state, why blocked, kill availability; mobile/desktop/200% text; no keys in browser. **Tests:** duplicate click, stale approval, CSRF, unauthenticated mutation, changed account, reopened browser tab, revised rules and network failure. **Production:** a private page alone is not approval to activate write routes.

### O — Deployment, rollback, backups and secrets

**Objective:** execution recovery is operationally repeatable without damaging research or the other application. **Depends:** C/D/L/N.

Dedicated service user, minimum filesystem/egress privileges, resource headroom, health and alert path, private journal backups, key storage/rotation runbooks outside ordinary research backups. Full-history scan before credentials and sanitized CI artifacts. Do not assume rollback can run old code against an incompatible new schema; document forward-only migrations, compatible rollback release and offline restore procedures. Never restore over live evidence for a test.

**Acceptance:** release manifest pins code/schema/contract/fee/profile; restart comes up disarmed; restore drill preserves order-intent/receipt identity; liveness and actual reconciliation health distinct. **Tests:** disk pressure, interrupted migration, backup failure, obsolete state, logs leaking headers, service permissions and resource exhaustion. **Authority:** separate installation/keys/schedule approval; no OS-wide hardening or other repo changes.

### P — Chaos, performance and regression suite

**Objective:** prove bounded behavior under expected bursts and faults, not marketing latency. **Depends:** components incrementally; full campaign before T.

Use synthetic load, not provider stress. Measure queue depth, p95/p99 decision/storage/risk latency under declared workload; max backlog, journal size and memory; reserve cancellation/reconcile headroom. Test shutdown/restart, rate limiting, wrong clocks, HTTP errors, bad schema, lost data, durable identity and manual concurrency.

**Acceptance:** explicit load profile and hardware; no statistical result from fixtures; shared VPS work isolation; baseline full suite including #161's reported unrelated failures resolved or honestly blocking. **Production:** none; no wholesale database migration without measured need.

### Q — Independent review and conformance verification

**Objective:** review meaningful money/security/state changes, not only documentation. **Depends:** each material package and integrated result.

Independent reviewer receives exact heads and adversarial scenarios, not author-only assertions. Review environment separation, account history completeness, ambiguous outcomes, cancellation/partial-fill math, game-state leakage, fee precision, secret boundary and approval semantics. Re-review consequential fixes on changed heads.

**Acceptance:** no unresolved critical safety finding; full exact-head CI; frozen artifacts and research labels unchanged; THIRD_PARTY_NOTICES and dependency pins correct if any reuse occurred. Code-only approval does not certify venue observations.

### R — Authorized demo rehearsal

**Objective:** observed mock-environment loop. **Depends:** K/L/N/O/P/Q plus owner demo access/operation approval.

Record start/account/environment verification → current market/rules → synthetic proposal → validation/reservation → send → ACK/resting/fill → cancel/amend as supported → external reconciliation → process restart → reconcile again → closed or settled residual → final cash/P&L reconciliation and audit manifest. No self-trading/wash-volume to force a desired test case. Missing market/liquidity leaves a test unobserved; cover logic in mocks and identify the residual.

**Acceptance:** immutable sanitized demo receipt references and exact code/config; no secrets, real personal info or real funds; documented differences from production. Credentials unavailable means BLOCKED_OWNER, not a reason to stop independent code.

### S — Authorized production-read rehearsal

**Objective:** verify the actual eligible account and source profile without financial writes. **Depends:** G/M/O/Q plus exact owner production-read scope/rights.

Use explicitly bounded reads and approved data. Compare complete local projection with provider evidence; all manual/native open obligations visible; identify precision, fee tier, subaccount/shard and data gaps. Feed/account time consistency has a documented maximum age/retry budget.

**Acceptance:** actual PRODUCTION_READ_VERIFIED per capability, repeated stable reconciliation as policy requires, no POST/PATCH/DELETE to financial routes; unknown fees or history prevent appropriate economics/risk claims. No strategy outcomes read as part of operational proof.

### T — Scoped readiness certificate and activation packet

**Objective:** a truthfully computed status, not an edited checklist. **Depends:** A–S as required by declared scope.

Certificate records code/config/schema/profile hashes, tests/reviews, evidence timestamps, member/environment, documented versus observed semantics, readiness per capability, unobserved demo limitations, constraints, incidents, expiry/retest triggers and owner approvals. A provider/API/rules/fee/key change can invalidate relevant evidence.

**Acceptance:** all mandatory profile rows supported; no unsupported feature portrayed ready; live write and unattended activation off. Provide exact tiny-live and later automation checklists with strategy evidence, capital/risk terms and operator stop policy, without selecting those values unilaterally. State the next specific blocker if composite readiness is not met.

## 6. Owner's thirty finish criteria mapped to evidence

| Requirement | Current state from audit | Package / evidence |
|---|---|---|
| 1 public Kalshi data | Existing selected collection, current production not reverified | A/B/J/O; source-specific receipts |
| 2 account-read adapter | Missing | F/G/S |
| 3 demo integration | Missing | F/K/R |
| 4 demo account reconciliation | Unobserved | G/H/R |
| 5 deterministic risk chain | Shadow foundation only | E/I/P |
| 6 atomic cash/inventory reserves | Pure calculation only | D/E/concurrency tests |
| 7 auth signer/transport | Deliberately absent | C/F with test keys, then approved access |
| 8 create/cancel/amend | Contract only | H/R |
| 9 partial fills | Design/fixtures, no actual adapter | H/P/R |
| 10 unknown submit | Enum/refusal exists, no durable external reconcile | D/G/H/L |
| 11 idempotency | Content-derived ticket/local research constraints | D/H; do not promise venue exactly-once |
| 12 startup reconcile | Missing actual venue implementation | G/L/R/S |
| 13 manual/native orders | Simulated concepts | E/G/N/S |
| 14 rate/backoff | Public collection primitives, no execution token dispatcher | F/J/P |
| 15 stream gaps/reconnect | Offline foundation | J/R/S with new access |
| 16 kill switches | No active trade worker | L/P/R |
| 17 account-aware shadow | Missing | M/S |
| 18 human confirmation | Planned contract, no command service | N/P |
| 19 unattended mode off | Execution universally disabled | C/L/N/T; preserve safe default |
| 20 no research credentials | Existing guard, new boundary not implemented | C/F/O/mutation tests |
| 21 no withdrawal permission | Requirement, no key verification | B/C/S scope evidence |
| 22 complete audit trail | Shadow/evidence exists; order trail missing | D/H/R |
| 23 private Terminal state | Research views exist | N/O |
| 24 deployment/rollback | Existing research procedures | O tested execution extension |
| 25 full/adversarial tests | No new implementation/test run here | P/Q exact heads |
| 26 independent review | Future implementation prerequisite | Q |
| 27 tiny-live checklist | Proposal | T + future strategy/owner decisions |
| 28 automation checklist | Proposal | T + later live evidence |
| 29 valid demo/shadow signal | Synthetic fixture bridge planned | K/R/M; no alpha claim |
| 30 no major missing build for approved scope | Not currently satisfied | T composite, not universal YES |

All rows keep distinct NOT_IMPLEMENTED, OFFLINE_TESTED, DEMO_VERIFIED, PRODUCTION_READ_VERIFIED, BLOCKED_OWNER, BLOCKED_PROVIDER and UNSUPPORTED states. A required observation cannot be replaced with an assertion in a document.

## 7. Research portfolio and economics remain separate

Continue protected EXP-001 and current EXP-002 under their actual timings, budget and outcome-use controls. Do not resurrect abandoned noise gates or run A.C before its allowed window. NHL remains separate development evidence. New in-play/RFQ studies need a slot/protocol and do not inherit EXP-003's paused budget. Broader weather/SEC/options/futures/macro/crypto/energy remain queued under R9.

Choose an execution rehearsal by software controllability; choose first real strategy by mechanism, independent evidence, fees, attainable size and capacity. There is no proved winning strategy in this audit. Native Auto Sell, maker incentives, orderbook imbalance, low latency and AI-agent architecture do not create profit by themselves.

Every economic report separates actual/simulated fills, variable costs, incentive estimates/paid amounts, fixed costs, owner hours, total versus deployed capital and peak simultaneous exposure. No assumed professional market-maker privileges. Additional capital helps only if marginal executable opportunity remains.

## 8. Canonical integration instructions (pending reconciliation)

#153 and #158 already propose changes to OWNER_IDEAS, DELIVERY_ROADMAP, EXECUTION_PLAN and HANDOFF. This document does **not** overwrite those pending edits. After their legitimate review/integration, apply the following additions to current files, adjusting current status without inventing approvals.

**OWNER_IDEAS:** add #160 row: `Kalshi automation readiness — research recorded; next explicitly scoped R5 ordinary-event execution campaign, offline → authorized demo → authorized production-read shadow → scoped readiness. Not live authority. Complete campaign in strategy/KALSHI_AUTOMATION_DELIVERY_160.md. Reuses #11/#32/#36/#96 and existing shared owners; R3a pending work retained.` Add actual new subordinate owners only when the runtime ADR is approved, not as BUILT now.

**DELIVERY_ROADMAP:** dated R5/R10 refinement: `#160 prioritizes finishing a single deterministic Kalshi ordinary-event lifecycle while current strategy evidence accrues. A–T packages and factual readiness matrix are in KALSHI_AUTOMATION_DELIVERY_160.md. R2/R4 and E1 v2 are built; don't restart them. R3a/source pilot remain scoped dependencies where needed. Full RFQ pricing, every market, general ML and investor features are not prerequisites for first qualified live strategy. No new empirical family or financial scope is granted.` Preserve R0–R11 and historical decisions.

**HANDOFF:** add exact documentation PR/head/readback/CI state, main950c audit, open153/158/161 as currently verified, no new production verification and independent review pending. Do not overwrite the operational coordinator's current status. The next action is explicit runtime scope + reconciliation + A–T execution campaign, not another speculative research platform.

**EXECUTION_PLAN:** record only this session's research/documentation scope and explicit prohibited actions. Separate future approval entries for runtime boundary, demo, production reads, tiny live and unattended activation. Never convert `KALSHI_AUTOMATION_READY` aspiration into new key/trading permission.

**Issue #160:** link resulting PR and exact source/readiness limits. Cross-reference #145/#157 and shared-owner issues without creating redundant tickets. Canonical integration remains PENDING until actual files/merged state demonstrate it.

## 9. Completion and external blockers

The implementation agent should continue all dependency-ready authorized packages; opening one PR or waiting for one account decision is not the campaign finish line. Conversely, unavailable keys/demo/provider facts can make final verification impossible in that session. Return the maximum independently completed state, a precise remaining observation/owner action, and its affected certificate rows.

Do not provide an invented time-to-profit or total calendar duration. The October22 checkpoint remains a review target, not evidence. Inspect actual dates and operations; prior backup due dates do not authorize repeat deletion. Reliable alerts are required before unattended live, but repeated unsolicited ntfy tests are not part of this research.

This proposal is deliberately a large completion campaign with measurable intermediate states. It is not a way to claim that architecture, access, demo behavior, real strategy evidence and financial authorization are the same thing.
