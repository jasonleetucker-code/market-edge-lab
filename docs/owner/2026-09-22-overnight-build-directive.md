# Owner directive — overnight build (Gates 5–6, risk, Outcome Board backend)

- **Received:** 2026-09-22 about 22:15 ET (2026-09-23 about 02:15 UTC), in the Claude Code
  session that deployed the forward collector.
- **Status:** the authorization record for Gate 5, conditional Gate 6, the conditional P0
  risk/capital foundation, the conditional Outcome Board backend, merge authority for this
  directive's PRs, and a standing merge rule for docs-only and test-only PRs.
- **Where it is summarised:** `docs/EXECUTION_PLAN.md`. The verbatim text below governs.

---

MARKET EDGE LAB — OVERNIGHT BUILD DIRECTIVE
Work continuously from the current local repository while the owner is asleep.
Do not stop after writing a plan. Continue through the authorized sequence below as long as each preceding gate actually passes.
Current `main`, `HANDOFF.md`, `docs/EXECUTION_PLAN.md`, open PRs, and work claims are newer than this prompt. Read them first.
OWNER AUTHORIZATIONS
The owner explicitly authorizes:

1. advancement to Gate 5 — Market-vs-model;
2. advancement to Gate 6 — simulated/shadow trading if Gate 5 passes;
3. implementation of the P0 risk/capital foundation if Gate 6 passes;
4. backend/domain foundations for the Outcome Board if the ledger/risk contracts are stable;
5. squash-merging PRs created by this overnight directive when the merge conditions below are met.

This does not authorize:

* real orders;
* authenticated trading APIs;
* trading credentials;
* funded accounts;
* deposits or withdrawals;
* paid APIs/data/services;
* real-money risk;
* automatic financial execution.

FIRST — CLEAN UP THE LAPTOP BRIDGE
The production forward collector is now installed and scheduled on `chaseupside`.
Therefore the attended laptop capture is no longer the primary or planned capture path.
Do this before beginning new work:

1. Check whether any laptop bridge process, background command, wait loop, PowerShell job, Claude background task, scheduled task, or other process is currently waiting to perform tomorrow's PFM/decision/recheck capture.
2. Stop/cancel it safely.
3. Verify there is no unattended Windows schedule for Market Edge collection.
4. Do not run a duplicate laptop capture tomorrow unless the VPS collector fails and the owner explicitly invokes the emergency bridge.
5. Update `HANDOFF.md` so it no longer says the laptop bridge is expected to capture tomorrow's window.

Do not delete the bridge code/runbook if it is useful disaster-recovery infrastructure.
The correct state is:

```text
VPS collector = PRIMARY
Laptop bridge = MANUAL EMERGENCY FALLBACK ONLY
Laptop scheduler = NONE
```

If `data/bridge.sqlite3` or other smoke/bridge evidence already exists, do not silently delete evidence. Mark it appropriately as smoke/non-production evidence if applicable.
PRODUCTION COLLECTOR — MONITOR, DON'T REDESIGN
The collector is deployed on `chaseupside` as the separate `edgelab` service.
Current production facts should be verified from the repo/host rather than assumed from this prompt.
Tonight:

* verify timers remain enabled;
* verify deployed SHA/revision;
* verify Market Edge services remain isolated from Brisket;
* verify Chase Upside remains healthy;
* verify backup timer/configuration;
* do not modify unrelated Brisket services;
* do not reboot;
* do not rotate keys;
* do not run apt upgrades.

The first real forward window has not happened yet.
Do not claim live-window success until actual evidence exists.
GATE 5 — MARKET-vs-MODEL ENGINE
Gate 5 is now authorized.
Mission
Build the reusable layer that answers:
Given our model probability and an actually executable market quote, is there a measurable opportunity after uncertainty, fees, freshness, liquidity and execution constraints?
The core must be domain-neutral.
It should eventually support:

* weather;
* sports;
* prediction markets;
* crypto;
* equities/macro.

Do not build those other domains tonight.
Core contracts
Implement durable representations for:
Event

* domain
* normalized event ID
* target date/time
* underlying outcome cluster
* settlement identity

Market

* venue
* normalized market ID
* native contract ID
* outcome
* payoff definition
* rules/hash
* status

Executable Quote

* venue
* side
* best bid
* best ask
* displayed size
* receipt timestamp
* source timestamp where available
* freshness
* evidence reference

Model Estimate

* experiment/model ID
* version
* probability
* uncertainty
* conservative probability
* generated timestamp
* input/data version

Opportunity
At minimum:

```text
event
market
outcome
model_probability
conservative_probability
executable_price
displayed_size
fee
all_in_cost
gross_edge
net_edge
freshness
qualification
rejection_reason
model_version
quote_evidence_id
```

EXECUTABLE PRICE RULES
For Kalshi:

* buying YES uses an actually executable YES-side price;
* buying NO uses the economically correct executable NO-side price;
* never use midpoint as a fill;
* never use last trade as a substitute for an executable quote;
* displayed quantity limits size;
* missing book fails closed;
* stale book fails closed;
* wrong event fails closed;
* unresolved settlement equivalence fails closed.

Do not manufacture historical executable prices.
Historical model validation and prospective opportunity testing remain separate.
FEES
Re-check the current Kalshi fee schedule using legitimate public/primary documentation.
Do not bypass access controls.
If the exact authoritative schedule cannot be verified:

* retain the existing documented assumption;
* version it;
* mark it clearly `UNVERIFIED_CURRENT_SCHEDULE` or equivalent;
* do not permit a claim of proven net Stage-B profitability using an unverified fee schedule.

The opportunity engine must allow fee schedules to be replaced/versioned cleanly.
CONSERVATIVE PROBABILITY
Build a deterministic conservative-probability interface.
An LLM must never simply say:
"I'm very confident; bet more."
Use actual model/calibration uncertainty.
Do not tune uncertainty haircuts to maximize profit.
REJECTION REASONS
Create explicit machine-readable states such as:

```text
QUALIFY
NO_EDGE
MODEL_UNAVAILABLE
MODEL_STALE
BOOK_MISSING
BOOK_STALE
INSUFFICIENT_SIZE
FEE_UNVERIFIED
RULES_UNRESOLVED
EVENT_MISMATCH
MARKET_CLOSED
INVALID_PRICE
```

Rejected opportunities are useful research evidence.
Do not silently discard them.
GATE 5 TESTS
At minimum:

* YES executable price;
* NO executable price;
* fee math;
* displayed-size limit;
* stale quote;
* stale model;
* missing book;
* event mismatch;
* unresolved rules;
* zero edge;
* negative edge;
* conservative probability;
* deterministic ranking;
* repeatability;
* missing is not zero;
* stale is not current;
* midpoint never used as fill;
* no order/authentication paths.

Gate 5 passes only if

* reusable contracts exist;
* EXP-001 probabilities plug into them;
* forward Kalshi books plug into them;
* executable prices are correct;
* fees are explicit;
* freshness fails closed;
* liquidity is explicit;
* deterministic rejection reasons exist;
* no historical quote fabrication occurs;
* tests pass;
* independent read-only review has no blocker;
* CI is green on exact final head.

If all are true, squash-merge Gate 5 and update the execution plan.
If not, leave Gate 5 incomplete.
GATE 6 — SHADOW / PAPER TRADING
Begin only if Gate 5 passes.
Gate 6 is explicitly authorized under that condition.
No real orders.
Append-only shadow ledger
Build:
Decision

* opportunity ID
* timestamp
* QUALIFY/REJECT
* reason
* model version
* quote/evidence IDs

Simulated Fill

* venue
* market
* side
* quantity
* executable price
* fees
* latency assumptions
* FILLED / NO_FILL
* reason

Position

* opened timestamp
* contract/outcome
* quantity
* cost basis
* max downside
* potential payout
* outcome cluster
* experiment/strategy

Settlement

* outcome
* settlement evidence
* gross P&L
* fees
* net P&L

Shadow Account

* starting bankroll
* settled cash
* committed capital
* open worst-case risk
* realized P&L
* equity

Portfolio state must be reconstructible from ledger history.
No unexplained mutable balance.
FILL POLICY
Never assume:

* midpoint fills;
* unlimited liquidity;
* future touched prices;
* stale fills;
* missing quote = fill.

Insufficient evidence produces:

```text
NO_FILL
```

with an explicit reason.
POSITION-SIZING FOUNDATION
Build the deterministic interface needed by Issue #6:

```text
suggest_position_size(
    bankroll,
    conservative_probability,
    executable_price,
    fees,
    available_size,
    event_exposure,
    cluster_exposure,
    total_open_risk,
    policy
)
```

Support at least:

* maximum position;
* maximum event exposure;
* maximum portfolio risk;
* liquidity cap;
* explicit reserve;
* optional fractional-Kelly calculation.

Hard caps always override Kelly.
Persist:

```text
raw_size
risk_adjusted_size
liquidity_capped_size
final_size
binding_constraint
```

Do not optimize Kelly fraction against historical profitability tonight.
GATE 6 TESTING
At minimum:

* winning position;
* losing position;
* NO_FILL;
* fees;
* duplicate decision;
* duplicate fill;
* duplicate settlement;
* restart/replay;
* complete account rebuild from zero;
* committed capital;
* open risk;
* realized P&L;
* no phantom profit;
* no negative cash;
* stale input;
* risk caps;
* event exposure;
* cluster exposure hook;
* deterministic replay.

Gate 6 passes only if:

* lifecycle works end to end;
* portfolio reconstructs from ledger;
* fill policy is deterministic;
* risk sizing is explicit;
* no real-order path exists;
* tests pass;
* independent review has no blocker;
* exact-head CI is green.

If those conditions hold, merge.
Otherwise leave an honest incomplete PR.
RISK / CAPITAL FOUNDATION
If Gate 6 passes and time remains, implement the P0 risk foundation from Issue #6.
Build:

* bankroll;
* settled cash;
* committed capital;
* open worst-case risk;
* risk per position;
* risk per event;
* cluster exposure;
* total portfolio exposure;
* drawdown;
* daily loss;
* weekly loss;
* reserve floor;
* remaining risk capacity;
* capital expected to release by horizon.

Horizon concepts:

```text
available_now
within_1_hour
within_1_day
within_1_week
locked
```

Expected winnings are never guaranteed available cash.
WITHDRAWAL FOUNDATION
Do not implement actual transfers.
Create data/contracts for eventually calculating:

```text
technically_withdrawable
policy_safe_withdrawable
recommended_owner_draw
```

Do not make a real recommendation before the policy/evidence is adequate.
OUTCOME BOARD BACKEND FOUNDATION
If the shadow ledger and risk models stabilize, create only the backend/domain layer needed by Issue #3.
Support:

* normalized underlying outcome;
* linked positions;
* maximum account impact;
* current exposure;
* settlement horizon;
* status;
* ranking by account impact.

No decorative UI tonight.
PRODUCTION BACKUP / RECOVERY HARDENING
If independent of the Gate work, verify:

* production Market Edge backup succeeds;
* restore into a disposable location succeeds;
* schema/integrity/triggers remain intact;
* stopping/restarting Market Edge collector services does not touch Brisket;
* disabling Market Edge timers preserves data.

Do not deliberately interrupt Brisket.
DO NOT BUILD TONIGHT
Do not spend tonight on:

* sports models;
* sportsbook ingestion;
* crypto strategies;
* equities;
* generic web/news scraping;
* paid data;
* dashboard styling;
* subdomain/DNS/TLS;
* live trading;
* automatic withdrawals.

Those are later lanes.
PARALLELISM
Use at most 2–3 bounded specialists.
Suggested:
Agent A
Gate 5 opportunity engine.
Agent B
Gate 6/ledger design and implementation after Gate 5 contracts stabilize.
Agent C
Production/reliability verification + risk foundation where independent.
Coordinator owns:

* gate transitions;
* integration;
* HANDOFF;
* EXECUTION_PLAN;
* owner authorization records;
* final review.

One writer per area.
Use compact context packages rather than making every agent reread the repo.
MERGE AUTHORITY
For PRs created by this overnight directive, agents may squash-merge only when:

* reconciled with current `main`;
* frozen EXP-001 artifacts are not improperly altered;
* independent read-only review finds no unresolved blocker;
* CI is green on exact final head;
* mergeable;
* gate acceptance criteria are actually met.

Do not weaken a gate to satisfy the 30-day schedule.
STANDING DOCS/TEST-ONLY MERGE RULE
The owner authorizes:
Docs-only or test-only PRs may merge without another approval if:

* current-main reconciled;
* exact-head CI green;
* mergeable;
* no review blocker;
* no runtime change;
* no gate advancement;
* no acceptance-criteria weakening;
* no credentials/deployment change;
* no financial-authority change.

Record this durably.
IF BLOCKED, KEEP WORKING
If waiting for CI/review:

* work an independent authorized lane;
* improve tests;
* harden error handling;
* prepare the next P0 interface;
* update durable docs.

Do not use waiting time for speculative low-priority features.
MORNING REPORT
Return:
Laptop bridge cleanup

* any bridge/background process found?
* stopped?
* any Windows scheduler found?
* confirmed VPS-only primary capture?

Production collector

* deployed SHA
* timers
* resource state
* backup/restore result
* Chase Upside health
* next real capture window
* live Stage-B days captured

Gate 5

* PR
* merged?
* verdict
* opportunity schema
* fee status
* tests/CI/review

Gate 6

* PR
* merged?
* verdict
* ledger
* shadow account
* sizing foundation
* tests/CI/review

Risk foundation

* implemented
* remaining

Outcome Board foundation

* implemented
* remaining

Repository

* current main
* tests
* open PRs
* work claims
* HANDOFF
* EXECUTION_PLAN

30-day plan

* completed P0
* remaining P0
* blockers
* critical path
* next actions

Continue until there is no further safe, independent, authorized P0 work to perform.
