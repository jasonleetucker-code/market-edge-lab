# Proposed Claude Code handoff — Kalshi automation readiness

Prepared 2026-10-07 for owner intake #160. **Storing this prompt does not authorize it.** When the owner submits an implementation instruction, record the actual scope in EXECUTION_PLAN and apply the repository's review/merge rules. This research session performed no runtime or account operation.

---

@GitHub

Work exclusively in `jasonleetucker-code/market-edge-lab` — Market / Market Edge Lab.

Do not work in Calculator, Brisket, `riskittogetthebrisket`, another repository or its services. External repositories are read-only references, not edit targets.

## MISSION — finish the Kalshi ordinary-event automation core

Implement the complete dependency-ready campaign for **KALSHI_AUTOMATION_READY**, not merely one adapter or another roadmap. The campaign may span as many coherent, reviewed PRs as necessary. Finish independent work even when a provider/owner action blocks another stage.

The desired system can take a valid strategy proposal, verify current data/rules/fees, reconcile the approved account, enforce risk, reserve cash/inventory atomically, submit only through the authorized environment, track fills and cancellations, reconcile settlements, survive a crash and stop new risk safely.

The finish line is scoped technical readiness. It is **not** proof of profitable alpha and **not** live authorization. The owner's $50k–$100k annual after-cost objective is aspirational; starting capital is limited and not inferred from shadow examples. Do not create daily profit quotas or use leverage to meet the target.

Sports do not have to be the first demo instrument or first qualified strategy. One ordinary Kalshi event-contract executor should serve supported weather/sports/macro and other future strategies through typed inputs. RFQ negotiations, complex combo pricing, perpetual futures, cross-venue trades and investor accounting are separate capability profiles, not silently included.

## 1. Resume the actual current project

Read:

- AI_INSTRUCTIONS.md, HANDOFF.md, docs/EXECUTION_PLAN.md, docs/WORK_CLAIMS.md;
- docs/AGENT_OPERATING_SYSTEM.md, docs/SECURITY.md;
- docs/OWNER_IDEAS.md and docs/strategy/DELIVERY_ROADMAP.md;
- docs/DATA_PROVENANCE.md, docs/RESEARCH_PRINCIPLES.md, experiments/README.md;
- relevant source/fee/execution/in-play/RFQ/deploy/UI ADRs and current decision packets.

Then read #160 and these prepared deliverables:

`docs/research/KALSHI_AUTOMATION_AUDIT_2026-10-07.md`
`docs/strategy/KALSHI_AUTOMATION_DELIVERY_160.md`
`docs/strategy/CLAUDE_KALSHI_AUTOMATION_160.md`

Refresh default-branch SHA, current PRs, claims, reviews, CI, worktrees and dirty/unpushed work. Inspect the accessible production state separately; do not substitute a dated handoff.

Audit baseline was main `950c8372c475b9554a1cd0338c6f48517703dd24` (#156). At audit, open PRs included:

- #153, `arch/evidence-path-hardening`, head `9de0c35afca764e7ca2ff4acfe63c29a10c2845c`: reviewed provenance changes, explicitly awaiting owner merge decision;
- #158, `docs/nine-link-intake-157`, head `921c178356dd996231b9b226b8e669b1c5b1ed53`: documentation intake and R3a integration;
- #161, `fix/pm-sports-tick-before-settlement`, head `7b61ef622c9e9ace851709932d0ef3b1e470870c`: active capture-window fix.

#161 reports two NHL planner tests failing identically on base. Reproduce current failures, assign one bounded correction if needed and do not skip them to declare green. No old CI status certifies a changed head.

The latest main handoff's production proof was dated September30 at `14704e3`. It is not proof of today's deployment. The repo is public; the private Terminal and account records must not become public.

The research audit could not clone due DNS, run local suites, scan full history, test accounts or independently verify production. Complete those missing verifications where authorized. Do not inherit a false clean-security/full-audit claim.

## 2. Authority: move engineering forward without activating money

This is a request to implement the offline/disabled execution campaign, subject to an explicitly recorded owner scope and the normal repository process. Its presence in a document is not that scope. Before changing no-auth/no-order invariants, identify the owner's actual instruction and write the narrow approved boundary to EXECUTION_PLAN with the security ADR.

Keep approvals separate for:

1. isolated runtime code and fixture keys/transports;
2. official demo account setup and a bounded mock-order rehearsal;
3. production account-read credentials and reads;
4. any new production data acquisition;
5. tiny live orders with a named qualified strategy and exact limits;
6. later unattended automation.

Do not create/read back actual credentials, sign into accounts, place even demo-account orders, purchase services, send support messages, alter source budgets or deploy new services unless the relevant authorization is recorded. Prepare exact owner-only setup steps early. Never request a password, API key or MFA code pasted in chat.

No transfer/withdrawal permission, real funds, margin, borrowing, external investors or public visibility change. Existing approved collection continues without widened scope. A key installed for one purpose cannot silently authorize another.

If an external approval is missing, implement and test all independent authorized modules and leave a precise verification blocker. Do not stop the entire campaign after one open PR or one pending account action.

## 3. Protect finished work and experiments

Reuse R2 state/latency/economics, R4 RFQ feasibility, current in-play policy/replay, NHL and NFL collection, fee/risk primitives, shadow ledger, backups and Terminal.

#153 already addresses empty RECORDED journals, latest-message source stamps and header races. Integrate under its actual merge authority; do not duplicate it to bypass approval. Complete the already specified R3a admissible-prefix identity/as-of consumer work only where it remains missing and is in scope.

#156 E1 v2 is built but not proof of edge. Do not restart E1, revive rejected noise checks, run A.C early, consume hidden T-60m labels or shift evaluation windows. Preserve all evidence-access logging and current protocol order.

EXP-001 remains byte-compatible: frozen artifacts, models, fees/fills, ledger, decisions and 180/365-valid-day looks. No new empirical family beyond the current two-slot policy. A synthetic demo signal validates machinery, not alpha and not a new sports model. Paused EXP-003 does not donate its budget automatically.

Keep #32's 168-hour venue-tradable-cash rule. A hoped-for early sale does not guarantee cash release. Owner deposits, trading returns, incentives and software revenue remain separate.

## 4. Current gaps that determine the architecture

`execution_ticket.py` always refuses execution and rejects executable tickets. `tests/invariants/test_no_execution_paths.py` deliberately prohibits signing/venue auth/order paths. Do not simply delete this test or exempt all of src.

`reserve_simultaneous_obligations` is pure arithmetic. It reserves no database funds. Extend one canonical reservation authority with durable transactional state and fencing.

Current tickets and shadow positions use integer/binary-entry assumptions; `shadow_ledger.py` has account_opened/decision/fill/settlement and OPEN/SETTLED positions. `risk.py` uses shadow cost-basis/settlement economics. They are not real-account, partial-exit or live-mark risk implementations.

Keep proven owners; version new capabilities compatibly. A private execution journal can be a separate security/persistence domain, but there must be only one authoritative formula/reducer for each financial fact. Never migrate frozen research history into fabricated live records.

## 5. Current sources and reusable external lessons

Read audit source IDs K01–K25, O01–O12, P01–P06 and A01–A03. Reverify implementation-critical current docs; timestamps/versions matter.

Official starting points:

https://docs.kalshi.com/llms.txt
https://docs.kalshi.com/getting_started/api_keys
https://docs.kalshi.com/getting_started/api_environments
https://docs.kalshi.com/getting_started/historical_data
https://docs.kalshi.com/getting_started/fee_rounding
https://docs.kalshi.com/getting_started/rate_limits
https://docs.kalshi.com/getting_started/order_groups
https://docs.kalshi.com/api-reference/orders/create-order-v2
https://docs.kalshi.com/api-reference/orders/cancel-order-v2
https://docs.kalshi.com/api-reference/orders/amend-order-v2
https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account

The audit found Ed25519 recommended alongside RSA, live/historical account partitioning, account-dependent precision and shard/token constraints. Do not copy an older RSA-only client or assume recent results cover the whole account.

External examples are references, not a replacement platform:

- Spencer Fletcher's maker_state: adapt intent-before-send and unknown-is-not-flat. Results and important runtime pieces are withheld; current public Kalshi maker was removed. Do not import cancellation of unowned orders or production thresholds.
- charlieyang1557: learn from explicit failed strategy/own-fill reports, but its small self-reported sample and mixed denominators do not prove universal futility.
- tfrmma: selected code returns empty positions on failed reads and cancels all discovered orders. Treat these as negative conformance fixtures, not safe defaults.
- cryptuon: exact human approval/typed proposal concepts may help, but do not import an agent framework or LLM financial authority.
- Simulated profit screenshots, guaranteed-arbitrage claims, live-by-default configurations and geo-evasion are rejected.

No source copying without pinned commit, actual license/notice/dependency review and targeted tests. No unknown setup scripts or wallet/private-key tools are executed. Market's own evidence must establish profitability.

## 6. Build packages A–T in dependency order

The detailed owner paths, tests, production effects and acceptance live in KALSHI_AUTOMATION_DELIVERY_160.md. Complete them rather than treating this list as another brainstorm.

**A — Baseline/scope/reconciliation.** Review pending PRs and protect their files; reproduce baseline and frozen checks; identify authority and exact current execution ownership.

**B — API/account conformance.** Version hosts, schema, side/quantity/price/payout units, fee/account regime, capability/TIF, cancellation/amendment, history, scopes, tokens and settlement exceptions. Unknown/conflicting facts remain unsupported. Documentation examples are not observed venue receipts.

**C — Isolated security boundary.** Separate worker identity/store/keys from researchers and UI. Mutation-test no signing/auth/order calls outside exact permitted paths. Fixed host/method/path/account allowlists; fail closed on environment or scope ambiguity. No arbitrary URL/body signer.

**D — Durable intent/receipt journal.** Stable business key separate from send-attempt ID, immutable payload digest and approval binding. Persist intent/reservation/pending attempt before network. Same key/different payload is a conflict. Crash/diskfull/lock tests. Essential audit failure blocks sending.

**E — Atomic reservation/fencing.** One transaction reserves cash, inventory and risk capacity including manual/native/unknown obligations. Distinguish venue-held versus local unreflected cash. No double-spend, unsupported netting or stale-worker egress. Lease expiry is not proof a previous worker stopped.

**F — Signer and transports.** Maintained library, parsed key type, fixture keys only initially, correct official pre-sign format. Local approval binds the entire command even where the venue signature does not. Demo/prod allowlists, no credential-forwarding redirects or fallback. Token-aware bounded dispatcher preserves cancel/reconcile headroom.

**G — Complete account reads.** All authorized subaccounts/shards/pages; live plus historical records and moving cutoffs; dedup/watermark/retry semantics. Unknown or incomplete never flat. Missing old settlement detail is a documented gap. Do not cancel/flatten to make reconciliation easy.

**H — Order lifecycle.** Pending/unknown/ACK/resting/partial/filled/cancel-request/confirmed/rejected/expired states, with cumulative fills and canceled remainder independent. Persist/reconcile before retry; late fills apply once. Amend counts follow actual total-vs-remainder semantics. Stable local idempotency is not an unproved venue exactly-once guarantee.

**I — Risk and typed strategy tickets.** Entry/reduction/forbidden-flip semantics; explicit profile versions; quantities, limits, fees, expiry, native/account dimensions and evidence. Keep independent limits for orders, events, correlations, portfolio, daily new risk, losses, reserve, depth, freshness, latency and reconciliation. Do not assume every live position's remaining risk is its original cost. Unknowns reject.

**J — Streaming/recovery.** Reuse the current sequence/book/state path; prove snapshot/delta and reconnect state. Separate all clocks and updates. Gap or conflicting duplicate quarantines dependent state; account/REST reconciliation repairs it. A material game event invalidates an old recommendation.

**K — Demo orchestration.** Same deterministic core, synthetic labelled signal, one supported mock profile. No shortcut engine or production fallback. Record documented versus actually observed modes.

**L — Kill/restart.** Persisted global/venue/strategy/market/new-risk disables; owned-order cancel and separately approved closeout. Cancel unavailable is visible. Restart begins disarmed until complete reconciliation. Never auto-reset venue order-group protections or erase daily loss through restart.

**M — Account-aware shadow.** Actual authorized reads through the real risk chain to WOULD_SUBMIT/BLOCKED, but no financial write or real reservation mutation. Hypothetical inventory remains distinct.

**N — Private approval/UI.** Existing Terminal, exact intent-bound expiring approvals, authenticated commands/CSRF/replay defenses. Show cash/reserved/unknown/positions/fills/risk/reconciliation and the current mode. No keys in browser; no hidden change of order after approval.

**O — Operations.** Dedicated service and resources, private journal backups/restores, key rotation/compromise runbook, release hashes/schema compatibility, forward-only migration/rollback constraints, disarmed restart and verified incident delivery before unattended use. Preserve other services and protected collection.

**P — Fault/load suite.** Synthetic representative bursts, bounded memory/backlog, explicit hardware and performance measurements, kill/diskfull/network/clock/duplicates/races. Do not stress providers. Resolve current full-suite failures instead of redefining the suite.

**Q — Independent review.** Exact heads, actual adversarial checks, significant fixes re-reviewed, full required CI and frozen tests. Review each material boundary and integrated system; a documentation approval is not execution certification.

**R — Authorized demo proof.** Once approved: initial state → valid synthetic ticket → reserve → submit → real demo ACK/fill/resting/cancel/amend as supported → external reconcile → restart/reconcile → close or settle residual → cash/P&L/audit match. Do not force fills through wash/self-trading. Unobserved cases stay unobserved and have mock tests plus explicit residuals.

**S — Authorized production-read proof.** Once approved: complete current account/history, actual units/fee profile, external orders, current source quality and repeated stable reconciliation under bounded reads. No financial POST/PATCH/DELETE. No strategy outcome exposure to certify operations.

**T — Readiness certificate.** Code/config/schema/profile/source evidence and expiry, review/test receipts, actual demo/read verification, excluded capabilities and residuals. A required missing observation keeps the composite blocked. Live and unattended gates remain off; present exact activation packets rather than activate them.

Do not begin B/C writers editing the same shared files. Use one coordinator, two or three bounded specialists and an independent reviewer. UI fixtures and documentation can run in parallel; schema/persistence/security interfaces must settle before dependent code.

## 7. Financial invariants and acceptance tests

Authoritative arithmetic uses exact Decimal/fixed-point inputs; reject NaN/infinity/bool/off-grid/missing values. Current probability, executable price and expected payout are different. Native YES/NO and bid/ask mapping must pass adversarial tests for positive, zero and negative inventory, partial reductions and attempted flips.

Cash/inventory must reconcile without a balancing plug:

opening cash + admitted external flows + sale/settlement proceeds - purchases - actual fees = closing cash,

with pending/settled/held states separated. Deposits are not profit. Sold inventory never also settles. Partial sells retain correct basis and residual payout. Unknown balance or settlement is never zero. Fees/rebates are applied once at the actual native granularity/account regime.

Tests must include:

- timeout before egress versus ambiguous timeout after egress;
- durable commit failure, kill after send, lost ACK, duplicate ACK;
- canceled remainder plus late fills;
- two workers sharing the last available cash/inventory;
- stale worker after lease/fencing transition;
- manual or native Auto Sell discovered during reconciliation;
- archive movement/page failure/duplicate records;
- partial IOC/FOK contradiction/malformed receipt;
- amended total smaller than already filled quantity;
- state change while waiting for human confirmation;
- bad fee/rules version, max-price movement and future timestamps;
- exchange pause when cancellation is impossible;
- key unavailable, wrong environment, redirects, secret-bearing exception;
- order-group limit reached and reset denied without authority;
- changed risk limits cannot retroactively authorize queued orders;
- restart/backup restore retains event loss, pending exposure and arming state;
- full regression and protected-label/frozen-artifact invariants.

Mutation tests must prove unauthorized researcher/UI code cannot access signer/transport, not simply assert a flag is false. No production credentials or network requests in CI; generated test keys must be unmistakably nonproduction. Separate integration commands for explicitly authorized demo operations.

## 8. Human and autonomous approval are not the same

An owner approval is a bounded capability, not a UI checkbox. Bind it to exact account/environment, intent digest, strategy and model version, market, action, quantity, price/TIF, maximum all-in cost, fee/risk versions and expiry. Revalidate just before send. A changed order needs a new approval where terms change materially.

A future automated approval profile additionally needs allowed universe, max turnover/new risk/loss/concentration, per-game re-entry/order limits, quality requirements and stop conditions. Its default is disabled. Do not ship a generic FORCE flag or allow a plugin/LLM to set its own policy.

A kill switch blocks new risk; it is not a guarantee of instant cancellation or liquidation. Emergency cancellation/closeout has its own authorization and can be unavailable. Report remaining uncertainty and exposure.

## 9. Economic and statistical research continues independently

Do not make an unvalidated maker strategy the default simply because the executor supports resting orders. Quoted spreads are not filled spread, and fill-conditioned markout is not guaranteed exit P&L. Track own fills, remaining exposure, fee/reward attribution, opportunity episodes and realistic size/capital reuse.

Current study completion may depend on calendar evidence, not engineering. Finish the machine without forcing a strategy verdict. The first legitimate strategy need not be sports; no generic model may price every domain. Demo synthetic signals must never enter empirical strategy metrics.

Paid/professional data, institutional fee privileges and promotional rewards are not assumed. Use a value case, current terms and owner approval. RFQ/multi-leg strategies need their separate lifecycle/joint pricing/observability tests before another profile is certified.

## 10. Canonical integration and release

Use the exact dated integration section in KALSHI_AUTOMATION_DELIVERY_160.md after resolving #153/#158 overlap. Update the real OWNER_IDEAS and DELIVERY_ROADMAP rather than only posting another issue comment. Preserve #160/R5/R10 links, R3a work, all R0–R11 domains and prior owner decisions. HANDOFF must show actual build/review/merge/deploy/verification state. EXECUTION_PLAN records only real new authority.

Maintain a live package ledger A–T with owner, path, state, dependencies, acceptance, exact test/PR/CI evidence, external blocker and next independent task. Completed work is maintained, not restarted. Do not silently narrow the campaign to one PR, but avoid a giant unreviewable PR.

Run the actual local required suite and inspect full history/security when environment access permits. If execution is unavailable, report commands not run. Commit/push coherent branches, independently review, fix and re-review changed heads, require exact-head green CI and applicable owner merge delegation. Never bypass #153's owner gate or a failed preflight.

Deploy only reviewed merged scope under actual authority and the current protected-window runbook. Reverify code/schema, recovery, protected flows and no new collector/financial mode accidentally activated. Do not repeatedly deploy docs-only commits. Never alter the other application's units.

## 11. Final evidence-backed finish line

Report separate stages:

OFFLINE_EXECUTION_CORE_COMPLETE
DEMO_LIFECYCLE_VERIFIED
PRODUCTION_ACCOUNT_SHADOW_VERIFIED
KALSHI_AUTOMATION_READY_FOR_DECLARED_PROFILE
LIVE_AUTHORIZED
UNATTENDED_LIVE_AUTHORIZED

The last two remain false unless explicitly approved later.

Readiness must cite actual evidence for the thirty owner requirements mapped in the delivery plan. Missing demo stages, unavailable account history, unsupported product types or unverified fees remain BLOCKED/UNSUPPORTED, not swept into a green overall state. Production-write acceptance cannot be claimed from demo alone; disclose the residual verified only by a later approved canary.

In the final report state:

1. what is implemented and reused;
2. exact code/schema/profile and PR/CI heads;
3. independent reviews, fault/load/restore results and security coverage;
4. real demo receipts versus synthetic tests;
5. actual production-read scope and reconciliation;
6. what remains unsupported or blocked and why;
7. approvals already recorded versus newly required;
8. current strategy evidence, separately from engineering;
9. exact next owner setup/activation packet;
10. the single next dependency-ready task if a provider prerequisite prevents certification.

Do not wait idly for future games, install watchers or promise unattended follow-through. Do not rerun already completed initial backup/deletion/settlement tasks from stale notes. Restore ntfy only within an approved incident-readiness scope, not an unsolicited test during research.

Continue until all independently authorized dependency-ready engineering is complete or genuine external blockers remain. The objective is a defensible execution system ready for its declared use when a strategy and the owner authorize it—not a persuasive claim that a bot will make money.
