# Owner directive — 2026-10-07: finish the Kalshi ordinary-event automation core (#160)

Received in the laptop Claude Code session of 2026-10-07 (America/New_York). The owner pasted the research session's
summary of PR #163 and its "Next Claude Code prompt". The prompt is an edited successor of
`docs/strategy/CLAUDE_KALSHI_AUTOMATION_160.md` (PR #163), with the #162/#163 integration details added. The
owner then answered four questions in the same session.

**Authority.** This is the owner's instruction to implement the offline, hard-disabled execution campaign. The
scope is recorded in `docs/EXECUTION_PLAN.md` (owner authorization record, 2026-10-07 entry) and the boundary in
ADR 0043. The directive authorizes no credentials, demo or production account access, account calls, order,
deposit, paid service, new collector or gate advance. Its own text keeps those as separate approvals.

## Directive (verbatim excerpts)

The full prompt (14 numbered sections) is in the session transcript. These sections bound the authority and are
quoted exactly.

```text
MISSION:
FINISH THE KALSHI ORDINARY-EVENT AUTOMATION CORE

This is an implementation continuation—not another generic research
round, another list of ideas, or a request to stop after one adapter.
```

```text
3. AUTHORITY: ENGINEERING FIRST, ACCOUNTS SEPARATELY

This prompt requests the implementation campaign. Record the precise
offline/disabled runtime scope in EXECUTION_PLAN before modifying the
existing no-auth/no-order invariant.

A handoff stored in git does not authorize itself.

Separate:
A. isolated runtime implementation and fixture tests;
B. official demo account setup and bounded mock-order testing;
C. production account-read credentials and reads;
D. new market-data acquisition;
E. a tiny real-money strategy pilot;
F. unattended automation.

Do not obtain or use actual credentials, create accounts, place demo
account orders, read production accounts, send support messages,
purchase services or activate new collectors unless the relevant
approval is already recorded.

Prepare exact owner setup/approval requests early.

Do not ask for passwords, API keys, private keys or MFA codes in chat.

No deposits, withdrawals, margin, borrowing or outside capital.

Existing source budgets and protected windows remain unchanged.

If one external approval is missing, finish every independent authorized
engineering package. Do not stop the entire campaign at that boundary.
```

```text
Commit/push coherent branches.
Run the actual local required suite, frozen checks and security scans.
Obtain independent review and exact-head CI.
Merge only under applicable delegation.
Deploy only approved reviewed scope through the gated runbook.
```

```text
LIVE_AUTHORIZED and UNATTENDED_LIVE_AUTHORIZED remain separate.
```

Section 7, the package list that the authorized components in `docs/EXECUTION_PLAN.md` are drawn from, verbatim:

```text
7. IMPLEMENT THE A–T CAMPAIGN

Use the detailed dependencies, owners and acceptance criteria in
KALSHI_AUTOMATION_DELIVERY_160.md.

A — BASELINE AND SCOPE
Reconcile current PRs, baseline failures, claims and authority.
Do not bypass #153's owner decision.

B — CONFORMANCE PACK
Version native units, account dimensions, fees, APIs, order capabilities,
history, clocks and settlement exceptions. Unknown remains unsupported.

C — ISOLATED EXECUTION SECURITY
Research and UI cannot load signer/key objects or send arbitrary
commands. Exact import and egress boundaries; private process identity;
strict environment and host allowlists; mutation-tested invariants.

D — DURABLE INTENT JOURNAL
Stable business intent distinct from transport attempts.
Commit intent, approval digest, reservation and pending egress before
network transmission. Same ID/different payload is a conflict.
Audit and recovery survive SIGKILL, disk-full and lock failures.

E — ATOMIC RESERVATIONS AND FENCING
One transactional cash/inventory/risk authority, including manual,
native Auto Sell, pending and unknown obligations.
No double-spend, oversell or unsupported netting.
A stale worker cannot transmit after losing authority.

F — SIGNER AND TRANSPORT
Maintained cryptography; generated fixture keys initially.
No generic arbitrary-request signer.
Bind local approval to the complete command.
Demo/prod isolation, credential-safe redirects, bounded token-aware
requests and reserved cancellation/reconciliation capacity.

G — COMPLETE ACCOUNT READS
Every relevant authorized page, subaccount and shard.
Live plus historical records, cutoff movement, deduplication and
bounded resampling.
Missing data is not flat, empty or zero.
Do not cancel or flatten holdings to simplify reconciliation.

H — ORDER LIFECYCLE
Pending, unknown, acknowledged, resting, partial, filled, cancel
requested/confirmed, rejected and expired behavior.
Cumulative fills remain separate from canceled remainder.
No blind resubmission after an ambiguous timeout.
Handle amendment lineage and late fills exactly once locally.

I — RISK AND STRATEGY TICKETS
Version entry/reduction/flip semantics, limits, quantities, prices,
fees, expiry, account dimensions and evidence.
Independently validate per-order, market, event, cluster, strategy,
account and portfolio exposure; reserves; losses; new risk; depth;
slippage; latency; source quality and reconciliation.
Do not use original purchase cost as every possible remaining-risk
or marginal-action measure.

J — FEED AND ACCOUNT RECOVERY
Reuse existing sequence/state reconstruction.
Detect gaps, conflicting duplicates and reconnects.
Reconcile stream and REST evidence.
New material game information invalidates an obsolete recommendation.
A reconnect is not proof resting orders disappeared.

K — DEMO ORCHESTRATION
Same deterministic core with separate environment.
A synthetic signal and one supported mock contract.
No production fallback and no fake observed fill.

L — KILL AND RESTART
Durable global/venue/strategy/market/new-risk disable.
Owned-order cancellation and separately authorized closeout.
Cancellation may be unavailable.
Restart disarmed until reconciliation.
Do not automatically reset loss limits or order-group protections.

M — ACCOUNT-AWARE SHADOW
Authorized real account inputs through the exact risk chain.
Output WOULD_SUBMIT or BLOCKED.
No financial write and no mutation of real reservations.
Hypothetical state is explicitly separate.

N — PRIVATE APPROVAL AND TERMINAL
Authenticated, expiring, anti-replay approval bound to exact intent.
CSRF/same-origin controls for command routes.
Show account, orders, fills, reservations, uncertainty and reconciliation.
No signing keys in browser and no substituted order after approval.

O — OPERATIONS AND RECOVERY
Dedicated permissions and resource bounds, private journal backups,
restore drills, secret rotation/compromise runbook, disarmed startup,
schema-aware deployment and rollback.
No changes to the other application's services.

P — CHAOS AND PERFORMANCE
Synthetic representative load and failure bursts.
Explicit queue, latency, memory, storage and recovery limits.
No provider stress tests.
Resolve current full-suite failures rather than skip them.

Q — INDEPENDENT REVIEW
Review security, exact arithmetic, state transitions, temporal
correctness, complete account reads and authority.
Fix and re-review changed heads.
Require exact-head CI and frozen checks.

R — AUTHORIZED DEMO REHEARSAL
Once approved, observe the real mock lifecycle:
account → synthetic ticket → reserve → submit → ACK/fill/resting →
cancel/amend as supported → reconcile → restart → reconcile →
close/settle residual → cash/P&L/audit match.
Do not self-trade to force a test.
Unobserved capabilities remain explicit residuals.

S — AUTHORIZED PRODUCTION-READ REHEARSAL
Once approved, verify actual account scope, precision, fees,
manual/native orders, full history and stable reconciliation.
No financial mutations and no protected strategy outcomes.

T — READINESS CERTIFICATE
Compute readiness from actual evidence for the declared profile.
Pin code/config/schema, tests, reviews, account/environment,
capabilities, limitations and retest triggers.
Live write and unattended automation remain disabled.

Do not stop after A, after a signer, or after one PR.
Continue all independent authorized work through T's prerequisites.
```

## Owner answers in the same session (verbatim)

1. Question: "May I merge this campaign's offline execution PRs myself, once each has an independent review and green
   CI on its exact final head? Execution stays hard-disabled: no credentials, no account calls, fake transport only."
   Answer: **"Yes, merge reviewed offline PRs (Recommended)"**. The option text read: "Recorded in EXECUTION_PLAN
   as the campaign's merge delegation. It covers no credentials, demo or production access, deploying an executor,
   or any gate advance."
2. Question: whether to merge PR #153 (in-play provenance fixes, reviewed, CI green, awaiting the owner's merge
   decision). Answer: **"Merge #153 now (Recommended)"**. #153 was merged as `fcd46fe` on 2026-10-07 after its
   branch was updated to main and CI passed on the exact head `1592efb`.
3. Question: "After #161 (the Polymarket capture-window fix) is reviewed, green and merged, may I deploy it to the
   VPS through the runbook before Saturday Oct 10, 4:10 PM ET?" Answer: **"Yes, deploy it via the runbook
   (Recommended)"**. The option text read: "Code-only deploy outside the protected windows, with the deployed SHA
   verified afterwards. No timer, budget or schema changes."
4. Question: "Deploys install a whole main SHA. Once #161 merges, the next deploy will also carry #153's in-play
   provenance fix (41 lines in inplay_evidence.py, which the read-only dashboard's in-play view uses), plus test- and
   docs-only changes. It won't carry the execution package. May the #161 deploy include #153?" Answer: **"Yes,
   deploy main with #153 (Recommended)"**. The option text read: "One code-only deploy of the merged main SHA via the
   runbook, outside protected windows, with the deployed SHA, the dashboard and the timers verified. #153 is reviewed,
   approved and CI-green."
