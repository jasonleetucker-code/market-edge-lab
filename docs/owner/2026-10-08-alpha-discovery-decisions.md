# Owner decisions — 2026-10-08: Track B alpha-discovery decision packet

These decisions answer the consolidated Track B packet. The packet is
`docs/owner/2026-10-08-alpha-discovery-decision-packet.md`, on branch `research/alpha-shortlist-20261008` at `8c65add`
(under review). The owner gave the answers in the laptop Claude Code session on 2026-10-08, through the session's
question tool. The question text and the chosen option text are quoted verbatim below.

**Authority.** The scope is recorded in `docs/EXECUTION_PLAN.md`, in the 2026-10-08 Track B decisions entry. These
decisions extend the 2026-10-08 Track B entry. They do not replace it.

## 1. Packet item 1: Kalshi one-time public read (approval A2) — APPROVED

Question as asked:

> Packet item 1, the highest-value unlock: a one-time read of Kalshi's public, keyless endpoints for settled
> markets, trades and 1-minute bid/ask candles. The universe is NBA Oct 2025–Feb 2026, MLB 2025, and the frozen
> non-sports series closing from 2025-07-01. It excludes KXHIGHNY, NFL/KXNFLGAME, KXNHLGAME and combos. Stage 1 is
> ≤300 GETs, stage 2 ≤20,000 GETs, paced and outside protected windows. Research use only: no schedule, no account,
> no orders. Kalshi's data-rights terms are UNRESOLVED (the Developer Agreement page was unreadable to us), so
> please read it before approving. Approve?

Answer: **"Approve as written (Recommended)"**. The option text read:

> I've read the Kalshi Developer Agreement and it permits private research storage. Run stage 1, then the bounded
> stage 2, for all three draft experiments (EXP-004/005/006).

## 2. Packet item 7: standing merge delegation for Track B research code — APPROVED until 2026-11-15

Question as asked:

> Packet item 7: a standing merge delegation for Track B research code PRs (e.g. the Kalshi trades/candles adapter
> and harness glue), under the same conditions as other delegations. These are: offline and pure, fixture tests,
> exact-head CI green, independent review, no execution import, no collector/timer/credential/network beyond an
> approved one-time read, no change to EXP-001/002/003. Expires 2026-11-15. Approve?

Answer: **"Approve until 2026-11-15 (Recommended)"**. The option text read:

> Track B code PRs that meet every condition merge without a per-PR approval from you.

## 3. Low-risk items 6a, 10, 3 and 12 — all four APPROVED

Question as asked: "Low-risk items. Select every one you approve; anything left unselected stays pending." All four
options were selected:

- **"6a: EIA rules audit"**:

  > An outcome- and price-blind audit of about 20 EIA-linked Kalshi contracts' rules against official EIA release
  > notes (documentation only; no API, no prices). Tests the new reference-period/vintage mechanism.

- **"10: backup pull research use"**:

  > Use the next already-approved off-host backup pull (overdue about 6 days) as a laptop research input, for
  > feature-only, logged diagnostics. No extra pull.

- **"3: extend Kalshi fee Q7"**:

  > Add the NBA/MLB/NHL fee multipliers and per-series maker-fee history to the still-unsent Kalshi message. You'd
  > read the current fee PDF yourself and send it from your account. I never send it.

- **"12: decline family-B scans"**:

  > Accept the recommendation NOT to run complement/partition scans while EXP-003 is paused.

## 4. Packet item 8: sportsbook consensus vs Kalshi ask — leave to EXP-002

Question as asked:

> Packet item 8: your external research ranked 'fresh sportsbook consensus vs the Kalshi ask' first, but that is
> family A's mechanism, which is EXP-002 itself, so Track B is excluded from it. How should it run?

Answer: **"Leave to EXP-002 (Recommended)"**. The option text read:

> No new work. EXP-002's own A.C calibration run (around 2026-10-19) and E1 cover it.

## Not decided (packet recommendations stand as DEFER or no decision)

- Item 2: Becker tape.
- Item 4: IEM archives.
- Item 5: Novig daily files.
- Item 6b: vintage archive.
- Item 9: forward paper-maker study.
- Item 11: family-slot decision.
- Item 13: wallet datasets.
