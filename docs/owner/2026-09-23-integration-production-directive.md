# Owner directive: next integration and production mission (2026-09-23)

Source: the owner's written instruction to the working agent session on 2026-09-23
(received about 08:50 America/New_York), titled "MARKET EDGE LAB — NEXT INTEGRATION +
PRODUCTION MISSION". It came with an attached official Kalshi fee-schedule PDF, preserved in
`experiments/EXP-001-kxhighny-nws-vs-market/fee_verification/`. Recorded **verbatim** below.
Summary and interpretation live in `docs/EXECUTION_PLAN.md`; this file is the source.

In the same session the owner also answered four clarifying questions, recorded after the
directive text.

---

MARKET EDGE LAB — NEXT INTEGRATION + PRODUCTION MISSION

Repository:
jasonleetucker-code/market-edge-lab

Target deadline remains:
2026-10-22

This directive supersedes older chat assumptions where they conflict with current main or the latest owner decisions.

DO NOT STOP AFTER WRITING A PLAN.
Perform the authorized work, test it, independently review it, fix review findings, merge when conditions are met, deploy the authorized production pieces, and return a truthful final report.

============================================================
0. START FROM CURRENT TRUTH
============================================================

Before editing:

1. Fetch current main.
2. Read:
   - AI_INSTRUCTIONS.md
   - HANDOFF.md
   - docs/EXECUTION_PLAN.md
   - docs/OWNER_IDEAS.md
   - docs/WORK_CLAIMS.md
   - docs/AGENT_OPERATING_SYSTEM.md
   - docs/deploy/DAILY_SHADOW_ACTIVATION.md
   - docs/engineering/GATE7_FINDINGS.md

3. Read relevant owner issues, especially:
   - #4 owner-idea process
   - #11 30-day plan
   - #29 The Odds API free-tier integration
   - #30 multi-venue prediction-market coverage
   - #32 seven-day starter policy / broad discovery / execution preference
   - #33 SMS-first alerting

4. Check:
   - open PRs
   - active work claims
   - local dirty files
   - worktrees/branches
   - current remote main SHA

Known state when this directive was written:

- GitHub main was:
  f7b5cf8628fb96983331bc095a6838c23baa6ffc

- Post-merge CI on that SHA was green.
- Daily pipeline, Gate 7 engineering suite, and local dashboard are merged.
- Last recorded production revision was older:
  9326a7a
- New daily shadow and settlement services were not yet production-verified.
- The existing forward collector must be preserved.

Do not assume those facts remain true. Verify them.

If local unpushed work exists, preserve it. Do not overwrite it merely to sync.

============================================================
OWNER AUTHORIZATION IN THIS DIRECTIVE
============================================================

By sending this directive, the owner authorizes:

1. Verification of the existing Market Edge production collector on chaseupside using the already-established SSH/root access.

2. Deployment of the reviewed/merged daily-shadow and settlement infrastructure from current main, following the repository activation procedure.

3. Enabling the already-reviewed:
   - edgelab-shadow.timer
   - edgelab-settlement.timer

4. Preservation and integration of the attached official Kalshi fee-schedule PDF as research evidence.

5. Correcting fee-verification status where supported by that evidence, WITHOUT rewriting frozen experiment assumptions retrospectively.

6. Implementing the owner's seven-day starter capital rule as a reusable operational-eligibility policy.

7. Updating the canonical AI/owner-idea process so every new material owner idea triggers backlog reprioritization, dependency/reuse analysis and safe parallelization analysis.

8. Building a provider-neutral notification event layer that can later drive SMS/push/in-app/email, but NOT purchasing or activating a paid SMS provider.

9. Bounded read-only multi-venue/data foundation work after the P0 work is stable:
   - Polymarket US public market data
   - The Odds API FREE-tier adapter foundation
   - Novig public/read-only data where legitimately accessible

10. Squash-merging PRs created under this directive when their acceptance conditions are actually met.

NOT AUTHORIZED:

- real-money orders;
- submitting an order to Kalshi, Polymarket, Novig, sportsbooks or any other venue;
- authenticated trading credentials;
- deposits;
- withdrawals;
- funding an account;
- automatic trading;
- human-approved live one-click trading;
- paid APIs;
- paid SMS;
- Action PRO purchase;
- Outlier purchase;
- DNS/public-dashboard exposure;
- unrelated Brisket changes;
- SSH-key rotation/addition;
- apt upgrade;
- server reboot unless required for an emergency and separately approved.

Read/write trading APIs may be researched and represented as capabilities, but EXECUTION REMAINS DISABLED.

============================================================
1. FIRST PRIORITY — VERIFY PRODUCTION COLLECTOR
============================================================

Before doing a production install, SSH into chaseupside using the owner's existing access.

Do NOT request private keys in chat.
Do NOT copy keys to cloud agents.
Do NOT add a new key.

Check New York time first.

Do not install/restart Market Edge during:

17:40–18:35 America/New_York

or while any edgelab unit is actively running.

Verify:

- current deployed revision;
- existing edgelab timers;
- latest status JSON;
- recent journals;
- DB existence/size;
- most recent forward captures;
- Brisket health;
- memory/headroom;
- no OOM/resource-pressure problem.

Check Chase Upside:

- nginx
- dynasty
- dynasty-frontend
- docker
- public /api/health

If the forward collector is NOT healthy:

STOP the new expansion work long enough to restore safe read-only collection first.

Do not claim “capture is still running” merely because timers exist.

Record separately:

COLLECTOR_INSTALLED
TIMERS_ENABLED
PFM_CAPTURE_OBSERVED
DECISION_CAPTURE_OBSERVED
RECHECK_CAPTURE_OBSERVED
VALID_DAY_OBSERVED

One does not imply the next.

============================================================
2. KALSHI FEE EVIDENCE — USE THE ATTACHED PDF
============================================================

An official Kalshi fee-schedule PDF is attached to this session.

Preserve its EXACT ORIGINAL BYTES in:

experiments/EXP-001-kxhighny-nws-vs-market/fee_verification/

Use a descriptive immutable name containing the effective date if appropriate.

Record:

- SHA-256;
- original filename;
- receipt date;
- effective date;
- source supplied by owner;
- page references;
- any current API corroboration.

The PDF states the general taker formula:

M × 0.07 × C × P × (1-P)

and separately gives maker-fee rules.

It is effective July 7, 2026.

It also states that products with specific schedules can differ.

DO NOT simply switch the whole fee system from
UNVERIFIED_CURRENT_SCHEDULE
to
VERIFIED
without reconciling all relevant details.

Specifically verify:

1. Does KXHIGHNY use the general schedule at the relevant dates?

2. What does the current Kalshi series/API say about:
   - fee type;
   - fee multiplier;
   - scheduled fee changes?

3. Reconcile:
   - model/trade fee precision;
   - “centicent” language;
   - displayed fee table;
   - balance precision;
   - direct-member vs non-direct-member accounting;
   - rebates/rounding refunds where applicable.

4. Preserve distinctions between:
   - exact venue trade fee;
   - cash-account debit caused by balance precision;
   - conservative simulation assumptions.

5. Never apply Kalshi's fee logic automatically to another venue.

6. Preserve the frozen EXP-001 research assumptions.

If the coefficient and multiplier are now verified but some cash-rounding/account-type assumption remains uncertain, represent those as separate states instead of one misleading VERIFIED boolean.

Possible model:

COEFFICIENT_VERIFIED
SERIES_MULTIPLIER_VERIFIED
ROUNDING_MODEL_VERIFIED_FOR_ACCOUNT_TYPE
FULL_SCHEDULE_VERIFIED

or an equivalent clean design.

Add regression tests using examples from the PDF.

No profitability claim may become claimable unless the exact assumptions required for that claim are verified.

============================================================
3. IMPLEMENT THE OWNER'S SEVEN-DAY STARTER POLICY
============================================================

The owner has clarified exactly what “settle within a week” means.

Canonical rule:

A new starter-phase position is eligible only if the committed capital / resulting settled balance is conservatively expected to be AVAILABLE TO TRADE AGAIN ON THAT SAME VENUE within:

168 elapsed hours

of the new capital commitment.

This does NOT mean:

- event occurs within a week;
- market closes within a week;
- we hope to resell it within a week;
- funds reach the bank within a week.

Track separate concepts:

event_end
resolution_time
tradable_cash_release_eta
withdrawable_cash_eta
bank_receipt_eta

The governing policy uses:

tradable_cash_release_eta

Implement a reusable policy such as:

STARTER_MAX_7D_V1

Requirements:

- 168 elapsed hours, timezone-safe.
- Unknown timing fails closed.
- Expected resell liquidity is not equivalent to settlement.
- Post-settlement trading holds count against 168 h.
- Bank withdrawal delay does NOT count if money is already reusable for trading.
- A delayed/rescheduled position becomes an explicit policy exception.
- Existing locked capital remains reserved.
- Do not force-sell on day seven.
- Long-duration catalogs remain visible for research but are ineligible for starter capital.
- A long-duration market genuinely nearing final settlement may become eligible based on REMAINING conservative release time.

Machine-readable reasons should include concepts such as:

HORIZON_OVER_7D
TRADABLE_CASH_RELEASE_UNKNOWN
SETTLEMENT_TIMING_UNVERIFIED
POST_SETTLEMENT_HOLD
DELAYED_OR_DISPUTED
EXIT_DEPENDS_ON_LIQUIDITY

CRITICAL RESEARCH-INTEGRITY RULE:

Do NOT change EXP-001's frozen research account/results to make them comply retroactively.

The operational eligibility layer is separate from the frozen research signal.

Add boundary tests:

167h59m
168h exactly
168h + epsilon
DST transition
unknown timing
event within one week but settlement outside it
withdrawal delayed but tradable immediately
tradable balance held after settlement
rescheduled event
long-term future close to actual settlement

Expose the result in:

- qualification;
- risk report;
- dashboard;
- future order-ticket contract.

============================================================
4. MAKE IDEA INTAKE A REAL PLANNING SYSTEM
============================================================

The owner has now made this a permanent project rule.

Issue #4 already records the direction.

Update the CANONICAL model-neutral instructions so every material new owner idea triggers, in the same planning session:

1. priority evaluation;
2. dependency analysis;
3. overlap/supersession analysis;
4. shared-infrastructure analysis;
5. parallel-build analysis;
6. roadmap impact;
7. NOW / NEXT / LATER / BLOCKED classification or equivalent.

Required planning question:

"Can this idea be implemented through an already-needed shared primitive so several owner ideas are unlocked at once without later rework?"

Examples of primitives that should have one canonical owner:

- event/market identity;
- venue registry;
- quotes/order-book normalization;
- fee models;
- model estimates;
- source ingestion/provenance;
- shadow/live ledger boundary;
- risk engine;
- notification system;
- execution-ticket contract;
- account/venue capability registry.

Do not build duplicate feature-specific implementations simply because two agents worked in parallel.

Parallelism should mean:

one shared contract + independent bounded implementations

not:

three competing versions of the same abstraction.

Creating/reprioritizing an idea STILL DOES NOT authorize implementation by itself.

docs/EXECUTION_PLAN.md remains execution authority.

Update:
- AI_INSTRUCTIONS.md
- docs/OWNER_IDEAS.md
- any light invariant/process tests necessary

Avoid creating a heavyweight project-management framework.

============================================================
5. SHARED NOTIFICATION FOUNDATION — SMS FIRST, PROVIDER NEUTRAL
============================================================

The owner prefers urgent text alerts over email.

Do NOT purchase or configure Twilio/Telnyx/SNS/etc.

Build the reusable notification CONTRACT if it cleanly fits the current architecture.

One notification event model should eventually drive:

- SMS;
- push;
- in-app;
- optional email;
- existing webhook/ntfy-style output.

Candidate event types:

SOURCE_FAILURE
CAPTURE_INVALID
OPPORTUNITY_QUALIFIED
PRICE_TARGET_REACHED
APPROVAL_REQUIRED
QUOTE_EXPIRING
RISK_VETO
KILL_SWITCH
POSITION_FILLED
POSITION_PARTIAL
POSITION_EXPIRED
SETTLED
SEVEN_DAY_POLICY_EXCEPTION

Include:

event_id
severity
created_at
expires_at
market/event/venue references
human summary
structured values
action_mode
deep-link target when safe
dedupe key

Never include:

API keys
passwords
session cookies
withdrawal credentials
sensitive full account payloads

Requirements:

- dedupe;
- expiry;
- rate limiting;
- bounded retries;
- delivery status where a provider supports it;
- failed notifications must never alter trading/risk truth.

Use an existing free/local sink for tests.
Do not activate paid carrier SMS.

============================================================
6. DEPLOY CURRENT REVIEWED DAILY PIPELINE
============================================================

After P0 fixes above are merged—or immediately if they are wholly independent and deployment should not wait—deploy the final reviewed current main using:

docs/deploy/DAILY_SHADOW_ACTIVATION.md

Do NOT invent a second deployment procedure.

Before install:
- production backup;
- Brisket health;
- resource check.

Install:
- current reviewed merged SHA only.

Run:
- collector fail-closed dry run;
- shadow bookkeeping dry run;
- settlement refresh;
- dual backup;
- restore verification;
- slice/resource verification.

Then enable:

edgelab-shadow.timer
edgelab-settlement.timer

Verify all expected Market Edge timers.

Keep the laptop bridge:

MANUAL EMERGENCY FALLBACK ONLY

No laptop scheduler.

After deployment verify separately:

DEPLOYED_SHA
COLLECTOR_HEALTH
SHADOW_TIMER
SETTLEMENT_TIMER
BACKUP_EVIDENCE_DB
BACKUP_SHADOW_LEDGER
RESTORE_EVIDENCE_DB
RESTORE_SHADOW_LEDGER
CHASE_UPSIDE_HEALTH

Do not call any item PRODUCTION_VERIFIED without direct evidence.

============================================================
7. GATE7-F09 — DO NOT HIDE THE LIMITATION
============================================================

Current known limitation:

A valid shorter ledger hash chain can remain after newest entries are truncated unless the head hash is anchored somewhere independent of the ledger.

Do not “fix” this by storing the anchor beside the ledger under the same write authority and then claim independent tamper detection.

This mission authorizes:

- architecture/design;
- tests;
- non-scheduled support code for an external checkpoint;
- threat-model documentation.

It does NOT authorize a new root scheduled anchoring service unless the owner separately approves it.

Compare sensible options such as:

- root-owned append-only checkpoint outside edgelab write paths;
- remote/off-host checkpoint;
- Git-backed signed/immutable checkpoint;
- other genuinely independent anchor.

State precisely which attacker model each option covers.

Keep F09 OPEN until independent deployed evidence exists.

============================================================
8. MULTI-VENUE FOUNDATION — BUILD SHARED PRIMITIVES, NOT A SOURCE ZOO
============================================================

Only after the P0 production/policy work is stable.

The owner's required prediction-market targets begin with:

- Kalshi
- Polymarket US
- Novig

The system must eventually:

1. union their market catalogs;
2. retain unique markets;
3. determine real rule equivalence;
4. compare equivalent executable prices;
5. account for venue-specific fees, quantity units and settlement;
6. identify best observed and best eligible price;
7. never claim universal best price when coverage is incomplete.

Extend the existing generic contracts.

Do NOT make separate market engines for each venue.

Build/review a capability registry that distinguishes:

venue_id
route_id
liquidity_pool_id
catalog_read
quote_read
depth_read
history_read
settlement_read
account_read
order_write
auth_required
execution_authorized

Execution-authorized defaults FALSE.

============================================================
9. FIRST PUBLIC MULTI-VENUE ADAPTER — POLYMARKET US
============================================================

If time remains after P0:

Build a bounded READ-ONLY Polymarket US public-data adapter.

Use documented public US interfaces only.

Do NOT confuse Polymarket US with Polymarket International.

No VPN/geolocation circumvention.
No authenticated trading.

At minimum research/implement:

- event/catalog discovery;
- market identifiers;
- outcomes;
- books/BBO where public;
- source timestamps;
- settlement/rule metadata;
- fee metadata where applicable;
- provenance;
- freshness;
- pagination/completeness;
- explicit unsupported fields.

Map into the SAME generic Event / Market / Quote contracts already used by the opportunity system.

A title match is not settlement-rule equivalence.

Add fixture tests and one bounded public smoke test if terms/availability permit.

============================================================
10. THE ODDS API FREE CONNECTOR FOUNDATION
============================================================

Issue #29 selects the FREE tier for integration.

Do not purchase anything.

If no API key exists:

build everything possible with fixtures and produce the exact safe setup step for the owner.

Never request that the key be pasted into chat/Git.

Implement:

- source adapter;
- quota model;
- credential redaction;
- immutable odds snapshots;
- event/book/market identity;
- freshness;
- coverage status;
- unsupported/paid-only venue status.

Free-tier safety budget:

do not consume the full 500-credit allowance automatically.

Use a configurable protective ceiling below the provider quota.

No CI network calls.

This is sportsbook-consensus infrastructure and can later support:

- sports probability benchmarks;
- prediction-market comparisons;
- best-price discovery.

Do not treat de-vigged fair probability as an executable sportsbook price.

============================================================
11. NOVIG — DO ONLY THE ACCESS-INDEPENDENT PART NOW
============================================================

Novig remains a required target.

Without owner-provided developer credentials:

- support/research the documented public daily data;
- build parsers/fixtures if useful;
- document live API capability requirements;
- preserve different price/quantity units correctly.

Do NOT invent credentials.
Do NOT submit orders.
Do NOT pretend end-of-day files are real-time executable books.

The eventual authenticated API integration should plug into the SAME venue capability and quote interfaces.

============================================================
12. DO NOT BUILD A MODEL FOR EVERY SPORT YET
============================================================

The owner wants broad discovery across:

weather
NFL
college football
NBA
WNBA
college basketball
NHL
MLB
UFC/MMA
boxing
soccer
tennis
golf
motorsports
cricket
rugby
esports
politics
economic releases
other well-defined near-term event markets

Preserve all of those as discovery/research targets.

But do NOT create dozens of weak models merely to claim coverage.

Correct architecture:

BROAD CATALOG DISCOVERY
        ↓
DATA QUALITY / SETTLEMENT / HORIZON SCREEN
        ↓
MODEL SUPPORTED?
        ↓
VALIDATED RESEARCH
        ↓
SHADOW
        ↓
EVENTUAL LIVE ELIGIBILITY

A newly discovered market with no validated model should say:

MODEL_UNSUPPORTED

not fabricate a probability.

Weather remains an active research domain.

Sports is a high-priority hypothesis, not a guaranteed superior edge.

============================================================
13. GATE / LIVE-MONEY BOUNDARY
============================================================

Do not advance into live-money trading.

One-click execution and automation remain FUTURE architecture.

You may define interfaces/tickets/capabilities, but:

NO LIVE ORDER
NO TRADING KEY
NO FUNDED CONNECTION
NO DEPOSIT
NO WITHDRAWAL
NO AUTO-EXECUTION

Do not alter that because an API technically supports orders.

============================================================
14. PARALLELISM
============================================================

Use up to three bounded lanes if safe.

Recommended:

LANE A — production + fee evidence
- fee PDF
- deployment
- production verification

LANE B — starter policy + agent/process + notification primitive
- seven-day policy
- owner backlog workflow
- notification contract

LANE C — read-only expansion foundation
only after shared interfaces are stable:
- Polymarket US
- Odds API fixtures/quota layer
- Novig public-data support

Coordinator owns:

- shared contracts;
- roadmap ordering;
- HANDOFF;
- EXECUTION_PLAN;
- owner-idea readiness;
- final integration.

One writer per file/area.

Do not allow parallel agents to invent competing:
- venue schemas;
- notification schemas;
- risk policies;
- source registries.

============================================================
15. REVIEW / TEST / MERGE
============================================================

For material PRs:

1. reconcile with latest main;
2. run targeted tests;
3. run full suite;
4. validate experiment registry;
5. check frozen artifacts;
6. independent read-only review;
7. fix blockers and worthwhile should-fixes;
8. re-review affected high-risk code;
9. exact-head CI green;
10. mergeable;
11. squash-merge.

For deployment code:
MERGED != DEPLOYED != PRODUCTION_VERIFIED.

Record each separately.

Do not weaken acceptance criteria to meet October 22.

============================================================
16. FINAL RE-PRIORITIZATION
============================================================

At the end of this mission, perform the newly required owner-idea portfolio review.

Produce an ordered roadmap:

NOW
NEXT
LATER
BLOCKED

For every important idea, identify:

- dependency;
- common shared layer;
- whether it can parallelize;
- what existing work it reuses;
- whether it moves up/down;
- October 22 effect.

Do not simply list issues numerically.

The roadmap should read like one coherent system being built intentionally.

============================================================
FINAL REPORT
============================================================

Return a concise but complete report:

1. CURRENT MAIN
- SHA
- tests
- CI
- PRs merged/open

2. PRODUCTION
- deployed SHA
- collector state
- seven timers or actual expected timer inventory
- latest capture status
- first/most recent valid Stage B day
- Chase Upside health
- resources

3. FEES
- PDF path + SHA256
- effective date
- coefficient verdict
- KXHIGHNY multiplier verdict
- exact rounding/account-type verdict
- claimable status
- any remaining uncertainty

4. SHADOW PIPELINE
- real decisions
- fills
- NO_FILL reasons
- pending settlements
- completed settlements
- risk vetoes
- backup/restore

5. SEVEN-DAY POLICY
- implementation status
- tests
- governing clock
- dashboard/report integration

6. OWNER-IDEA SYSTEM
- canonical rule updated?
- backlog reordered?
- shared primitives identified?
- parallel build recommendations?

7. NOTIFICATIONS
- shared abstraction status
- SMS provider status
- no-paid-service confirmation

8. MULTI-VENUE
For:
- Kalshi
- Polymarket US
- Novig
- The Odds API

report:
PLANNED / IMPLEMENTED / TESTED / LIVE_DATA_VERIFIED / NEEDS_ACCESS / PARTIAL

Do not use CONNECTED merely because code exists.

9. GATE 7
- engineering state
- production evidence
- research evidence
- F09 state

10. OCTOBER 22 ROADMAP
- NOW
- NEXT
- LATER
- BLOCKED
- what changed because of the newest owner ideas

Continue useful authorized work rather than waiting idly for future captures or CI.

If a task is blocked by access, move to another independent authorized lane and return to it when possible.

---

## Owner answers to clarifying questions (same session, 2026-09-23)

The owner's selected option is quoted first in each answer. The text after it is the agent's
recorded interpretation, not the owner's words.

1. **Kalshi account holding:** selected "Directly at kalshi.com/app". Interpretation: a
   direct member, attested by the owner and not verified through an account read.
2. **Claim basis:** selected "Yes, as CONSERVATIVE_BOUND (Recommended)".
   Interpretation: a net result computed with the verified coefficient and multiplier and
   the conservative frozen cost model may be claimable as a conservative lower bound.
   EXACT stays separate until the account-type rounding is verified.
3. **Seven-day clock for KXHIGHNY:** selected "Normal path + evidence buffer
   (Recommended)". Interpretation: the ETA is the expected expiration, plus the settlement
   timer, plus a buffer derived from observed historical settlement lags, and venue cash
   must be documented as reusable. `latest_expiration_time` is shown as the abnormal-path
   bound, and a real delay past 168 h becomes a policy exception.
4. **Enforcement:** selected "Enforce prospectively (Recommended)". Interpretation: from
   the policy's effective date the operational shadow account records NO_FILL /
   STARTER_POLICY_INELIGIBLE. Earlier days and the frozen research account are unchanged.
