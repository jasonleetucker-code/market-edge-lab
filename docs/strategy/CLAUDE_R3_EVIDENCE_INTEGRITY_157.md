# Claude Code handoff — R3 evidence integrity and pilot readiness (#157)

This is a proposed implementation handoff, not self-executing authority. Reading this file alone grants nothing. Record the actual owner's next scoped implementation direction before runtime edits; do not infer approval of #153, credentials, acquisition or trading from an intake document.

```text
@GitHub

Work exclusively in jasonleetucker-code/market-edge-lab.
This project is Market / Market Edge Lab.
Do not work in Calculator, Brisket, riskittogetthebrisket or another repo.

MISSION: R3a EVIDENCE INTEGRITY -> EXISTING IN-PLAY PILOT READINESS

1. PURPOSE AND WHY THIS BATCH

Market is a private operator/research system intended eventually to prove
repeatable after-cost trading edges at real executable size. Initial
capital is limited; $50k-$100k annual profit is an aspiration, not a return
assumption or permission to increase risk.

The nine-link intake is #157. All S01-S09 were attempted but unavailable.
No post text, media, underlying repository, benchmark or trading claim
was recovered. Do not invent them or attribute this work to those posts.
Do not stall independent work while waiting for their content.

The repository-grounded finding is narrower and useful: finish the
existing in-play book evidence path's content identity and as-of
correctness, then refresh the existing source-quality pilot proposal.
This is not a new model, RFQ engine, scheduler or universal platform.

2. CURRENT RECORDS TO READ FIRST

AI_INSTRUCTIONS.md
HANDOFF.md
docs/EXECUTION_PLAN.md
docs/WORK_CLAIMS.md
docs/AGENT_OPERATING_SYSTEM.md
docs/OWNER_IDEAS.md
docs/strategy/DELIVERY_ROADMAP.md
docs/RESEARCH_PRINCIPLES.md
docs/DATA_PROVENANCE.md
docs/SECURITY.md
experiments/README.md

Then:
#157 and its linked documentation PR;
docs/research/NINE_LINK_AUDIT_2026-10-05.md;
docs/strategy/NINE_LINK_157_INTEGRATION.md;
#152 and PR #153, including reviews;
docs/engineering/ARCHITECTURE_RECONCILIATION_2026-09-30.md
  (on #153's branch if not merged);
docs/research/INPLAY_SOURCE_FEASIBILITY.md;
docs/owner/2026-09-29-vf-decision-packet.md;
current UI contract, COMPONENTS and FEATURE_INTEGRATION;
relevant ADRs 0038, 0041 and 0042.

Audit baseline:
950c8372c475b9554a1cd0338c6f48517703dd24

This main already includes #156 E1 v2. Do not rebuild or rerun it.

At intake, only PR #153 was open:
arch/evidence-path-hardening
9de0c35afca764e7ca2ff4acfe63c29a10c2845c
Reviewed, mergeable, exact-head tests successful (run 36711607471), but
explicitly awaiting the OWNER'S MERGE DECISION. Not merged or deployed.

Refresh main, PRs, claims, local worktrees, uncommitted/unpushed work and
new owner decisions. A released claim is not permission to overwrite an
open PR. Never use old green CI to certify a changed head.

Main's HANDOFF reported production 14704e3 on September 30. That is dated
coordinator evidence, not today's deployment state. The repository is
public; the operator site remains a separate private boundary. Do not
change visibility or expose new sensitive information.

3. AUTHORITY AND ENTRY ORDER

The intake authorized research and documentation, not runtime work.

First reconcile the #157 documentation and #153 dependency. Respect
#153's explicit owner merge boundary. Do not cherry-pick/reimplement its
fixes merely to bypass that boundary.

If a current owner direction expressly covers this offline R3a build,
record that exact limited scope in EXECUTION_PLAN through the normal
claim workflow, then implement it. If not, prepare the scope and offline
regression/design packet and mark runtime implementation awaiting that
approval. A stored handoff does not approve itself.

Allowed preparation: documentation, source verification, fixture design,
current-code inspection and tests that existing authority permits.

Never enable a recorder, stream, account read, new credential, paid API,
RFQ, quote, order, deposit/withdrawal, margin, destructive cleanup or gate
advance. Keep EXECUTION_NOT_AUTHORIZED and RECORDED-data refusal.

Do not widen the joint 450-credit Odds budget, the NFL/NHL scopes, timers
or protected windows. No initial real-money bankroll is specified here.

4. PRESERVE AND REUSE

R2 source-state/latency/economics and R4 RFQ feasibility are already built
in #148-#150. Keep them. RFQ remains NARROW; private competitor quote/fill
history is not observable by default.

#153 already fixes empty journal kinds, stale inherited source stamps,
header-read races and direct-import test coverage. Integrate, don't redo.

#154-#156 already implement proposed E1 v2 review/protocol/code changes.
No EXP-002 markout, outcome report, evaluation window or protocol freeze
is part of this batch. Preserve the once-only A.C ordering after the
pilot through October 19 and before pilot outcomes are viewed; refresh
actual dates/protocol rather than running it early.

EXP-001's model, data, ledger, fills, fees and 180/365-day looks stay
unchanged. No new experiment family or silent reassignment of paused
EXP-003's slot/budget. General ML, broader sports and investor features
are not dependencies for this batch.

5. ONE OR TWO COHERENT PRS

PR A: R3a book lineage and as-of consumer completion, once scoped.
PR B: existing pilot/Terminal contract refresh and canonical integration
only where needed after the backend contract is stable.

At most two writers and an independent reviewer. One writer owns
inplay_evidence.py and inplay_view.py. The second can prepare source and
pilot documents; it must not create a competing evidence contract.

No new database or runtime dependency without a demonstrated need.

6. INSPECT AND REPRODUCE THE REMAINING GAPS

Canonical path:
inplay_evidence.read_journal / parse_book_message
-> SubscriptionReconstructor / replay_book_journal
-> BookState / Transition / coverage_report
-> freshness and position_policy.evaluate
-> inplay_view.build_view
-> dashboard/data.py and dashboard/views/inplay.py.

At baseline, build_view uses transitions[-1] even if received after
as_of. Policy refuses the future book, but reporting can carry future
metadata. Inspect source, exit estimate, coverage, failure and diagnostic
paths too. A blocked trade decision does not certify the whole view PIT.

Parsed messages have raw_sha256, but book consumer identity is a ticker
and sequence tag. Do not call that a content-addressed provenance chain.
Replay already has cohort/config lineage; do not rebuild its registry.

Write focused failing regressions against the reconciled baseline before
changing behavior. If newer main already satisfies a requirement, record
its proof and omit the duplicate work.

7. CONTENT IDENTITY CONTRACT

Preserve three different concepts:
- exact full-journal artifact identity;
- ordered, admissible consumed-prefix identity;
- last-applied raw-message identity and its source timestamp, if any.

Include necessary header/data-kind, parser/version, market/subscription
and as-of metadata. A sequence number or timestamp alone is insufficient.
Hash the exact bytes for raw identity; label any canonicalized/parsed
hash separately. Do not manufacture raw-byte identity from reconstructed
JSON or old hashes.

A later append changes the full-file digest. It must not change the
past consumed-prefix digest or semantic as-of result. Separate these in
both tests and output; do not demand whole-output equality when full-file
provenance legitimately changes.

Use a pinned read/manifest or bounded immutable buffer as appropriate.
Preserve #153's replacement/header-race defenses; don't introduce a race
by separately reading header, content and digest without consistency.
No unbounded file loading for hypothetical future large journals.

8. AS-OF CORRECTNESS THROUGH THE CONSUMER

Define admissibility using recorded receipt/order, not whatever source
clock produces a convenient result. Handle equal timestamps, malformed
receipts and nonmonotonic arrival order explicitly. Do not silently sort
away an anomaly or drop a parse failure.

Select/reconstruct only the permitted history for the requested market
and as-of. Preserve the pre-window state needed for reconstruction while
separating the reporting interval from the consumed history.

Every dependent source field, bid/depth estimate, policy result, coverage
measure and failure count must use the same declared temporal contract.
A future update, correction, failure or resync must not alter a past
semantic view. Unknown-time records need an explicit fail-closed rule.

A journal with no admissible book is not a zero-priced market. Show
EMPTY/UNKNOWN/unsupported as the contract warrants. No future book should
be mislabeled simply 'older than the maximum age'.

Keep game-event time, provider send time, message source time, first-seen,
receipt and processing time distinct. No clock substitution to make a
latency look measurable. Preserve uncertainty.

RECORDED data remains refused by the existing offline view/replay.
Synthetic labels cannot be used to smuggle real captured inputs through.
Do not create a journal-to-live-strategy path under this task.

9. BOUNDARY AND REGRESSION TESTS

Use existing tests/test_inplay_evidence.py, test_inplay_view.py,
test_inplay_evidence_path.py from #153, source-state tests and applicable
invariant/browser tests; verify paths in current main.

Required cases:
- same ticker/sequence, different payload bytes -> different identity;
- mutate a consumed message -> changed identity/result where applicable;
- append after-as-of messages -> unchanged past semantic view/prefix;
- full-file digest changes honestly after append;
- future-only journal -> no displayed current quote/proceeds;
- gap, duplicate/conflict, reconnect and resync;
- missing source stamp after a stamped message -> UNKNOWN, not inherited;
- malformed or ambiguous receipt times with explicit refusal;
- empty RECORDED header and replacement races retain #153 protection;
- failures and coverage retain coherent denominators;
- hidden evaluation labels never read as a side effect;
- current fixture/synthetic accounting and no-execution invariants hold.

Extend direct-import tests carefully. Existing transitive type/constant
imports do not prove protected data access. Use a justified allowlist and
no-socket/no-store-read effect tests instead of a broad architectural
rewrite or meaningless blanket import ban.

The existing fixture has ts_ms two days before receipts. Do not silently
rewrite it to pass latency tests; create a named derived fixture and
record why.

10. CURRENT SOURCE CHECKS AND PILOT REFRESH

Public documents independently checked by intake:
https://docs.kalshi.com/getting_started/quick_start_websockets
https://docs.kalshi.com/websockets/orderbook-updates
https://docs.kalshi.com/api-reference/live-data/get-game-stats
https://docs.kalshi.com/websockets/communications

These are not originals recovered from the nine posts. Reverify exact
fields at implementation time; examples are not production traces, rights
grants, account entitlements or latency SLAs.

Refresh INPLAY_SOURCE_FEASIBILITY and existing inplay-source-pilot-1,
not another proposal. Include current message-envelope/source clocks,
sequence semantics, null/missing game stats, whole input traffic, bounded
retry/resync behavior, source isolation, storage/recovery, exact stop and
review conditions and ex-ante game selection.

Propose one minimum useful route and at most one fallback. Keep price-only
exit research from requiring an expensive rich feed without need. A
source-quality pilot proves data quality, not alpha.

RFQ sharding and self-filter options don't reveal others' private quotes,
deliver a league-only feed, or establish complete market flow. The existing
R4 observability limits remain. No RFQ subscriptions or quoting tests.

Do not invent request counts, message rates or cost from no captured
traffic. Separate measured, proposed-bound and unknown quantities.
The recorder remains off until the actual owner approvals exist.

11. UI AND DURABLE DOCUMENTATION

Reuse inplay-view/1 or explicitly version an additive contract change.
Use the current UI contract, components and fixture gallery. Show as-of,
consumed evidence identity and missing provenance without a fake LIVE
label, account balance or edge score.

Preserve production NOT_AUTHORIZED and gallery access policy. No new
trading buttons, public endpoint or dashboard theme.

Review changed populated/empty/stale/partial/unsupported/error states at
360px, 1440px and 200% text with existing browser tooling. Emulated browser
checks are not a physical-phone or VPS verification.

After reconciling #153, apply the exact claim-safe integration in
NINE_LINK_157_INTEGRATION.md to OWNER_IDEAS, DELIVERY_ROADMAP, HANDOFF and
only the actually granted EXECUTION_PLAN scope. No full-file replacement
from an old handoff. Keep R0-R11 and all long-term ideas visible.

12. OPERATIONS, REVIEW AND COMPLETION

Verify dated O1/F09 work only from authorized current records. Do not repeat
retention/deletion or install anything because an old due date passed.
No new watcher, scheduler or ntfy test. No idle wait for future games.

Run targeted tests, the current required full suite, frozen-artifact and
label-boundary checks. CI uses no network, provider credits or real keys.
No production write probes. Independent reviewer must assess temporal
correctness, content attribution, compatibility and authority.

Commit/push bounded work, open/update PRs, fix findings, re-review changed
heads and require current-main reconciliation and exact-head green CI.
A past CI run or local unit tests cannot substitute for required checks.

Merge only under actual delegation. #153's owner gate is not bypassed by
this handoff. Deploy only reviewed merged code with separately applicable
authority and the protected-window runbook; offline code merging does not
enable acquisition.

Final report must state:
- exact source access: still 0/9 unless actual content was recovered;
- what code/docs were reused, changed and independently tested;
- #153 and #157 integration/merge status;
- as-of/prefix/identity regression evidence;
- unchanged frozen experiments and authority;
- pilot proposal readiness and exact owner actions;
- PRs/commits/exact-head CI and deployed/not-deployed status;
- the next single useful evidence-producing action.

Completion means a reproducible, attributable, temporally honest offline
path and an actionable existing-pilot proposal. It does not mean an edge,
a live trader or permission to collect.
```
