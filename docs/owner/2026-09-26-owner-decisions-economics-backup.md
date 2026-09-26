# Owner decisions, 2026-09-26 America/New_York: research economics, EXP-003, backup retention, off-host

Source: the owner's chat message to the laptop Claude Code coordinator session, received
2026-09-26 at about 03:15 America/New_York (07:15 UTC). It answers Decision 1 and Decision 2 of
`docs/owner/2026-09-25-research-unblocking-decision-packet.md`. It is recorded **verbatim** below.
An agent records a grant; it never creates one.

> I approve the following:
>
> 1. EXP-002 / NFL economics and research budget
>    * Use $1,000/year after-cost contribution as the minimum useful threshold for deciding whether this family deserves continued development beyond the research/pilot stage.
>    * Approve 6 owner hours through 2026-10-22 under the proposed allocation and stop rules.
>    * The $1,000 threshold is not a requirement for running the current pilot and is not a claim that the current size ladder can produce $1,000/year.
>    * If the pilot meets the proposed continuation criteria, the proposed additional 8-hour extension may come back to me for confirmation unless the existing directive already explicitly covers it.
> 2. EXP-003 / same-venue payoff relationships
>    * Keep EXP-003 paused.
>    * I approve sending the 8 drafted questions to Kalshi, but show me the exact final message before it is sent.
>    * Treat the questions as shared venue-fact verification where applicable, especially if the answers can also improve EXP-002 fee/fallback correctness.
>    * Do not resume major EXP-003 development merely because the questions were sent.
>    * If the relevant facts are still unresolved by 2026-11-15, reject the current EXP-003 scope as proposed.
>    * If Kalshi answers before then, re-evaluate the economics first. Do not resume the family unless the answers materially change its usefulness.
> 3. Backup retention
>    * I approve backup retention policy proposed-v1 for evidence-store local backups under the exact reviewed safeguards in `CAPTURE_AND_BACKUP_APPROVAL_PLAN.md`.
>    * Deletion must remain manual and reviewed; no timer-based deletion.
>    * Only eligible restore-verified copies may be deleted.
>    * Ledger backups, F09-linked backups, schema-change backups, protected baselines, unverified/quarantined/active copies, and all other specifically protected copies remain preserved exactly as the policy states.
>    * Run the reviewed dry-run immediately before any manual apply and attach the actual candidate list to the record.
>    * Do not delete original research evidence or treat a checkpoint hash as a replacement for a restorable backup.
> 4. Off-host backup
>    * I approve O1: a free weekly manual pull of the newest verified database bundles to my laptop, keeping the proposed last four copies and verifying them locally.
>    * Document the exact runbook and verification procedure.
>    * This approval does not authorize paid cloud/object storage.
>
> Continue with the already-authorized Kalshi NFL collection.
> Also proceed with the remaining safe technical work:
>
> * verify the first real NFL paired captures from stored evidence;
> * verify #107's first same-run settlement when it occurs;
> * verify the first Polymarket US research capture when it occurs;
> * build the EXP-002 measurement endpoint and pre-freeze noise/correlation gate;
> * preserve the forward-looking price-pairing rules and timing exclusions already reviewed;
> * keep EXP-002 and EXP-003 DRAFT until their actual freeze/preregistration requirements are satisfied.
>
> Do not retune EXP-001.
> Do not interpret these approvals as authority for live orders, paid data, new accounts, margin, deposits/withdrawals, or a gate advance.
> After recording these decisions, update the canonical handoff/roadmap truth and give me the next reasonable implementation batch based on current dependencies and the first real NFL paired evidence.

## How the coordinator applies it

- **EXP-002:**
  - `[economics] minimum_useful_effect` and `[budget] owner_hours` are set from items 1.1–1.2.
  - The protocol stays DRAFT.
  - The +8 h extension is **not** pre-approved: it returns to the owner.
- **EXP-003:**
  - Stays paused and DRAFT. Its slot state is unchanged, because the registry has no PAUSED
    state; "paused" is recorded in the protocol and README.
  - Budget: 2 owner hours.
  - Rejection on 2026-11-15 if unresolved.
  - The questions are sent only after the owner confirms the exact final message
    (`docs/research/KALSHI_QUESTIONS_2026-09-26.md`).
- **Backups:**
  - Deletion needs a reviewed, manual apply step that restore-verifies what it relies on and
    deletes only the candidates of a dry-run taken immediately before. The candidate list is
    attached to the record.
  - Until that step is merged and deployed, nothing is deleted.
- **O1:** a documented manual weekly pull with local verification. It keeps 4 copies. No paid
  storage.
