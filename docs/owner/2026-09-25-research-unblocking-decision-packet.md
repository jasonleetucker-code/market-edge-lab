# Research unblocking: blockers and the owner decision packet (2026-09-25)

Coordinator output for the owner's Research Unblocking directive
(`docs/owner/2026-09-25-research-unblocking-directive.md`). Status words:
- **CURRENT:** what exists.
- **PROPOSED:** a recommendation, not approved.
- **APPROVED:** only with a cited owner decision.
- **BLOCKED:** cannot proceed yet.
- **VERIFIED:** checked against evidence.

Supporting documents, each independently reviewed before merge:
- `docs/research/RESEARCH_UNBLOCKING_DECISIONS.md` (#111): the EXP-002 protocol, EXP-003 proof
  obligations, and the economics and effort scenarios.
- `docs/deploy/CAPTURE_AND_BACKUP_APPROVAL_PLAN.md` (#113): the Kalshi NFL capture and the backup
  retention proposal.

## 1. The blockers, reclassified

| Item | Current state | Category | Who resolves it | Recommended next action | Evidence required | What proceeds meanwhile |
|---|---|---|---|---|---|---|
| Kalshi NFL collection | **APPROVED** 2026-09-25 (#110); implemented (#112); DEPLOYED (production `86e528b` since 2026-09-26 01:31Z); switch ON | Owner authorization (given) | — | Verify the first captures from stored rows after the Saturday 2026-09-26 T-24h Odds captures | `price_observations` KXNFLGAME rows, `sports_evidence report --summary` with G1/G2 PARTIAL, pair skew | EXP-002 development pilot data accumulates |
| EXP-002 paired evidence | MISSING until the first captures | Missing data (time-based) | Production collection | As above | Paired horizons in the report | Protocol freeze prep |
| EXP-002 endpoint, horizon, cutoff, skew, episode, ladder, power, windows | **PROPOSED**, reviewed (#111) | Technical recommendation / statistical design | Agents; frozen by review before 2026-10-21 | Run the 3-week pilot (kickoffs 2026-09-27 to 10-19). Calibrate skew and run the label-free correlation gate before viewing labels. Freeze with `holdout_windows` | Pilot timing and noise measurements, evidence-use log | Nothing is waiting on the owner |
| EXP-002 tie / cancellation / fair-price states | Contract terms **VERIFIED** (captured PDFs, hashes); explicit payoff modelling **PROPOSED** | External fact → modelling recommendation | Agents | Use the bounded payoff interval (#111 A.D). One conflict between Kalshi documents (a game suspended after 55 min) stays UNVERIFIED | — | — |
| EXP-002 minimum useful contribution | UNKNOWN in the protocol | **Owner preference** | Owner (Decision 1) | Choose a threshold option (below) | — | The pilot runs regardless; the threshold matters only at the freeze |
| EXP-002 / EXP-003 owner-hour budget | UNKNOWN | **Owner preference** | Owner (Decision 1) | Choose the allowance (below) | — | — |
| Minimum independent clusters, episode minimums | UNKNOWN | Statistical design, not an owner input | Agents, from the pilot | Frozen from the pilot's measured ICC and variance (#111 A.G) | Pilot data | — |
| EXP-003 proof (KXHIGHNY partition) | **Cannot be proven** under the current text (#111 §B) | External fact verification | Kalshi, if asked; the owner authorizes asking | Pause the scope. Send the 8 drafted questions only if the owner approves (Decision 1). Reject by 2026-11-15 if unresolved | A written official answer | Nothing; no solver work continues |
| Kalshi emergency powers (Rule 2.8(d)) | Scoping **PROPOSED**: excluded from admissible states, reported as residual risk | Technical recommendation | Agents / review | Keep as proposed. If they are admissible, no Kalshi relation is ever provable, and EXP-003 is rejected now | — | — |
| TWC settlement precision, fractional-fill fees, settlement/transfer fees, NO-side fallback payout, KXNFLGAME fee semantics | UNVERIFIED | External fact verification | Kalshi (questions drafted) or later documents | Part of the Decision 1 question set; KXNFLGAME fee verification is a `fee_schedules` follow-up | Official documents or answers | EXP-002 economics stay "fees UNSUPPORTED" until verified |
| Shadow-fill labels | Fixed (**VERIFIED** by review): FIRST_DETECTION_ZERO_LATENCY, HINDSIGHT_UPPER_BOUND (ADR 0037) | Stale documentation / label correctness | Done (#111) | — | — | — |
| Stale "evaluator planned" references | **Fixed** (#111, #115, and OWNER_IDEAS in this PR) | Stale documentation | Done | — | — | — |
| Backup retention | **PROPOSED** `proposed-v1`; dry-run planner merged; deletes nothing | **Owner authorization** | Owner (Decision 2) | Decide by about **2026-10-08** (disk arithmetic in #113 B3) | #113 B2–B3 | Backups keep accumulating; 67 GB free |
| Off-host copy | **None exists** | Owner authorization | Owner (Decision 2) | Option O1: a manual weekly pull to the laptop, $0 | — | — |
| "Backup retention before any new collector" (OWNER_IDEAS item 4) | Premises partly stale (#113 §C) | Stale documentation | Coordinator records; the owner may overrule | Amended to byte-based triggers (PROPOSED, recorded in OWNER_IDEAS) | #113 §C | — |
| #107 same-run settlement | Deployed; **not yet observed** in production | Time-based observation | Coordinator | Verify at the run that first fetches the KXHIGHNY-26SEP25 result (from 2026-09-26 11:15 ET) | Settlement entries whose evidence receipt falls inside the same run, with a cutoff equal to the refresh receipt | — |
| KXHIGHNY-26SEP25 positions (2 per account) | Pending | Time-based observation | Coordinator | Same check as #107 | Event, outcome, payout, fees, equity, duplicates, hash chain | — |
| First Polymarket US research capture | Due 2026-09-26 16:53Z | Time-based observation | Coordinator | Verify from stored rows per runbook §5e | Target time, receipt, book count, misses, freshness, RELATED_NOT_EQUIVALENT | — |
| ntfy phone subscription | Deferred by the owner | Owner preference (deferred) | Owner, later | None now; not a research blocker | — | — |

## 2. What the owner actually needs to decide

Kalshi NFL collection is already decided (APPROVED, #110) and deployed. Two grouped decisions
remain. Everything technical is already recommended and reviewed.

### Decision 1: research economics and effort (both families)

**Family A (EXP-002, NFL).**
- **Threshold, recommended option B:** a minimum useful contribution of **$1,000 a year**, at no more
  than $2,500 of illustrative peak deployed capital. It is tested on the first-detection lower band,
  never on the hindsight bound.
- **Alternatives:**
  - A, $250 a year: learning-level; it continues families that may never matter.
  - C, $5,000 a year: a step toward the aspiration; it may stop a small but real family.
- **Honest caveat:** no Family A scenario inside the research size ladder reaches $1,000. The
  scenarios run from $1.70 to $382.50 a season, so reaching it needs verified capacity beyond
  250 contracts. Option B is a bar for continuing *beyond research*, not for doing the research.
- **Owner hours:** **6 h to 2026-10-22** (pilot report 2 h, freeze review 2 h, buffer 2 h).
  - **Extension:** +8 h to 2027-01-13, only if pairing yield ≥ 50% and the pilot shows the test fits
    weeks 7–18.
  - **Stop:** yield < 50% after fixes, or the pessimistic detectable effect is out of reach.
- **Capital:** none approved and none requested. Every amount is ILLUSTRATIVE.

**Family B (EXP-003, same-venue payoffs).**
- **Recommended: pause.** Allow 2 owner hours, and approve or decline **sending the 8 drafted
  questions to Kalshi**. Sending is a message on the owner's behalf, so it needs an explicit yes.
- **Review 2026-11-15.** With no answer, or an unfavourable one, the scope is rejected.
- Even a favourable answer gives a scenario of only $0.37–$18 a year. Declining the questions and
  rejecting now is a reasonable alternative.

Suggested wording:

> I approve for EXP-002 a minimum useful contribution of $1,000/year (option B) and 6 owner hours
> to 2026-10-22 with the stated extension/stop rules. For EXP-003 I [approve / decline] sending the
> drafted Kalshi questions; pause the scope and reject it on 2026-11-15 if unresolved.

### Decision 2: backup retention and off-host copy

**Retention: `proposed-v1`, for evidence-store local backups only.**
- **Keep:**
  - every valid bundle younger than 48 h;
  - the 3 newest valid bundles;
  - the newest bundle per UTC day for 7 days, per ISO week for 8 weeks, and per month for 12 months.
- **Keep forever:** the first bundle, both bundles around every schema change, the bundles linked to
  F09 checkpoints, pinned baselines, and **every ledger bundle**.
- **Never delete** a quarantined, active or not-covered bundle. Delete nothing while the newest
  valid bundle is older than 36 h.
- **How deletion would happen:** manual only, from a reviewed dry-run report, by a reviewed apply
  step that restore-verifies what it relies on first. No timer deletes.
- **Effect:**
  - At a year, about 29 copies (about 24 GB) against about 600 GB with no deletion (a scenario
    simulation).
  - **Today, on production** (read-only dry run, 2026-09-26 01:33Z, with the backup journal's
    restore-verification records): 2 evidence bundles are delete candidates (147,456 B), and 47
    evidence and 46 ledger bundles are kept. Only 40 bundles have a recorded restore check still in
    the journal, and every other bundle is kept by design.
- **Why now:** backup growth is driven by deploys, which write two full copies each. Without
  retention the backups reach 10 GB around 2026-10-14 at the current build pace. Decide by about
  **2026-10-08**.
- **The live database is the only original evidence.** A backup is a copy. A ledger checkpoint is a
  hash, not a restorable backup.

**Off-host: none exists today.** A VPS loss would lose everything, and the recovery point would be
unbounded. **Recommended O1 ($0):** a manual weekly pull of the newest verified bundles to the
laptop, verified there, keeping the last 4. The paid option O2 (object storage) is not recommended
yet.

Suggested wording (#113 B8):

> I approve backup retention policy proposed-v1 for the evidence store's local backups (manual,
> reviewed apply only; no timer deletes; review after 30 days), and I [approve / decline] a manual
> weekly off-host pull to the laptop (O1).

**Smaller alternative:** approve no deletion yet, only O1. That buys about 3–6 weeks before this
returns.

### Not a decision now

- **ntfy:** deferred by the owner. Not needed for research.
- **Brisket PRs #1406/#1407:** outside this repository.

## 3. What happens after each approval

- **Decision 1:**
  - The thresholds and hours are written into EXP-002's and EXP-003's `protocol.toml`
    (`[economics]`, `[budget]`). Both protocols stay DRAFT.
  - EXP-002 freezes only after the pilot, gate and review, by 2026-10-21.
  - If the questions are approved, the coordinator shows the exact message for a final yes before
    sending anything.
- **Decision 2:**
  - The policy is recorded in EXECUTION_PLAN.
  - A reviewed apply step is built that deletes only a reviewed report's candidates, after
    restore-verifying. It is run manually, once, with the report attached to the PR.
  - O1 gets a runbook section and a first pull.
