# Owner directive — 2026-10-08: implement the JEV/GROKBOT, crawler and wallet-intelligence improvements

Received in the laptop Claude Code session of 2026-10-08 (America/New_York) as the owner's own message. The
message points to issue #181 (new Owner Idea), issue #168 (wallet intelligence), draft PR #182, and the
implementation specification `docs/strategy/CLAUDE_JEV_CRAWLER_WALLET_V1.md`, which is on PR #182's branch
`docs/jev-crawler-ideas-20261008` (head `c650946` when received; `a919d8f` after review fixes).

**Authority.** The scope is recorded in `docs/EXECUTION_PLAN.md`, in the 2026-10-08 entry. The directive authorizes
the offline engineering implementation covered by the specification, "subject to recording its exact scope through
the repository's established process". It excludes the operations listed under STEP 6 below. Merges use the
existing delegated authority and review requirements.

## Directive (verbatim excerpts)

```text
MISSION:
BEGIN IMPLEMENTING OUR NEW JEV/GROKBOT,
ADVANCED CRAWLER, AND WALLET INTELLIGENCE
IMPROVEMENTS.
```

```text
STEP 1 — READ THE NEW REQUIREMENTS

Review:

GitHub Issue #181
GitHub Issue #168
Draft Pull Request #182

Then read the complete implementation specification:

docs/strategy/CLAUDE_JEV_CRAWLER_WALLET_V1.md

That file currently exists on branch:

docs/jev-crawler-ideas-20261008

Review the draft PR and integrate the documentation
through the normal review and merge process when
its requirements are satisfied.

Do not assume the PR has already merged.
```

```text
STEP 3 — IMPLEMENT THE IMPROVEMENTS

Execute the full bounded implementation specification.

The immediate priorities are:

A. Complete versioned causal wallet-selection
manifests and deterministic replay verification.

B. Improve suspicious-trading diagnostics by
separating liquidity role, price consistency,
contamination evidence, and follower copyability.

C. Build price-relative trader-skill diagnostics
that distinguish profitable traders from those
with misleading win rates.

D. Extend wallet-following simulations across
realistic latency, liquidity, size, fees,
slippage, partial fills, and capital constraints.

E. Implement reusable, fixture-driven market-change
and crawler intelligence through our existing
source and freshness infrastructure.

F. Build a strictly bounded JEV/Kev-style semantic
decision interface with deterministic validation,
abstention, provenance, and adversarial tests.

G. Integrate the useful research and diagnostics
into our existing Market Edge Terminal without
creating another dashboard.
```

```text
STEP 4 — USE PARALLEL AGENTS WHERE APPROPRIATE
[...]
Continue the existing Kalshi execution campaign
independently.
[...]
Do not create duplicate:

- Trading engines
- Risk engines
- Wallet accounting systems
- Freshness schedulers
- Data repositories
- Machine-learning registries
- Agent orchestration frameworks

Reuse our existing infrastructure.
```

```text
STEP 5 — IMPLEMENT, TEST, REVIEW, AND INTEGRATE
[...]
5. Obtain independent review.
6. Create a pull request.
7. Verify exact-head CI.
8. Merge only under the repository's existing
   delegated authority and review requirements.
9. Continue to the next dependency-ready package.
```

```text
STEP 6 — PRESERVE OUR SAFETY AND EVIDENCE RULES

This authorizes the offline engineering implementation
covered by the specification, subject to recording
its exact scope through the repository's established
process.

It does NOT authorize:

- New live market-data collection
- Paid APIs or AI model calls
- Credentials or account access
- New scheduled jobs
- Demo or real-money orders
- Unattended live trading
- Production deployment
- Changes to financial risk limits

Implement production-shaped components safely
behind disabled capability boundaries.

Preserve existing experiment restrictions, evidence
requirements, and source budgets.

Synthetic profitability is not evidence of a real
trading advantage.
```

```text
STEP 7 — KEEP MOVING

If one component is blocked by external permissions,
complete the independent engineering work.

Document the exact missing permission and continue.
[...]
Bring me one consolidated decision packet for
anything that actually requires my authorization.
```

The rest of the message (STEP 2 reconciliation, the final-report list and "START IMPLEMENTING NOW.") is in the session
transcript. It adds no authority beyond the excerpts above.
