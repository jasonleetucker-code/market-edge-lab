# Owner directive — 2026-10-07: finish the Kalshi ordinary-event automation core (#160)

Received in the laptop Claude Code session of 2026-10-07 (America/New_York). The owner pasted the research session's
summary of PR #163 and its "Next Claude Code prompt". The prompt is an edited successor of
`docs/strategy/CLAUDE_KALSHI_AUTOMATION_160.md` (PR #163), with the #162/#163 integration details added. The
owner then answered three questions in the same session.

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
