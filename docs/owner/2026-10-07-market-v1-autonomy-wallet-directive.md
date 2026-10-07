# Owner directive — 2026-10-07 (evening): finish Market v1 + controlled autonomous trading + wallet intelligence

Received in the laptop Claude Code session of 2026-10-07 (America/New_York). The owner pasted a 25-section
implementation prompt, with a summary from the research session that wrote it. The text came as pasted content
with no message of the owner's own, so the session asked before treating it as a directive. The owner answered:

1. "Should I adopt the pasted 'Finish Market v1 + controlled autonomous trading + wallet intelligence' text as
   your owner directive? I'd record it in EXECUTION_PLAN and open a wallet-intelligence issue. It's offline only:
   no keys, wallets, paid feeds, new scheduled collection or live trading." Answer: **"Yes, adopt it as written
   (Recommended)"**. The option text read: "Record it and continue the Kalshi lanes first (#166, #167, deploy,
   package I). Then build the v1 acceptance manifest, the orchestrator and the wallet lane in parallel, all
   fixture/offline, with the external activation packet."
2. "If wallet research goes ahead, which first data source should the lane use?" Answer: **"Synthetic fixtures +
   Polymarket v2 docs (Recommended)"**. The option text read: "Build the event model, point-in-time selection and
   follower replay on synthetic and documentation-example data. No network calls; live public reads need a
   separate approval later."

Earlier the same evening the owner wrote in their own words: "keep going until everything is merged", then "then
deploy it" (the merged main of the Kalshi lanes), then "then start package I".

**Authority.** The scope is recorded in `docs/EXECUTION_PLAN.md` (2026-10-07 evening entry). The durable intent is
issue #168, the wallet-intelligence Owner Idea, plus #160. The directive itself says it "requests a completion
campaign, not an actual trade". It grants no credential, wallet connection, spending approval, payment, support
message, scheduled collection, live risk change, borrowing, leverage, bridging, withdrawal, outside capital, token
approval or crypto trading.

## Directive (verbatim excerpts)

The full 25-section prompt, including its source register R01–R12, is in the session transcript. The R01–R12 list
is reproduced in issue #168. These sections bound the authority and are quoted exactly.

```text
MISSION:
FINISH MARKET V1
+
COMPLETE CONTROLLED AUTONOMOUS TRADING
+
ADD WALLET INTELLIGENCE AND COPYABILITY RESEARCH
```

```text
4. AUTHORITY AND EARLY UNBLOCK PACKET

This prompt requests a completion campaign, not an actual trade.

Record the precise approved implementation scope through the normal
owner-directive process. Preserve existing approvals.

Identify early the genuinely external steps:

- demo setup/credentials;
- bounded demo actions;
- production account reads;
- data rights;
- new recorder budgets/schedules;
- permitted execution venue;
- risk profile;
- real-money activation.

Give one concise packet with recommendations, exact scope and
prerequisites.

Do not create or handle real keys, connect wallets, approve contract
spending, make payments, send support messages, add scheduled collection
or change live risk merely to make the checklist green.

Use generated test keys, disposable stores and fixture transport where
approved.

Implement production-shaped components disabled until their
corresponding activation grant exists.

Provider-enforced key permissions and application restrictions differ.
Do not call a broadly privileged key read-only because our client uses
GET. Preserve current Kalshi key-scope unknowns and residual risk.

No borrowing, leverage, automatic bridging, withdrawals, outside capital,
token approvals or unrestricted crypto trading are granted here.

Missing approvals do not block independent code, tests, UI and docs.
```

```text
Full automation means routine decisions can run without individual
manual confirmations inside a previously approved policy.

It does not mean automatic funding, unrestricted new strategies,
self-authorized model promotion or guaranteed profits.
```

```text
Support the repository-equivalent states for:
DISARMED
OBSERVE_ONLY
SHADOW
DEMO
HUMAN_CONFIRMATION
BOUNDED_AUTO

Startup is disarmed pending reconciliation.
No silent rearm after incidents.
```

```text
Respect the active empirical-family limit.
Wallet research requires its own slot/budget.
Do not divert the execution team into every interesting strategy.
```

```text
Wallet analysis stays outside the financial executor.
Use the reviewed typed bridge; amend its boundary explicitly if needed.
```

```text
Require current-main reconciliation, exact-head green CI and merge
authority.
```

```text
Merged offline code does not activate collection or financial access.
```
