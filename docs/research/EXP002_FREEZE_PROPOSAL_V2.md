# EXP-002 proposed freeze settings, version 2 (`exp002-freeze-proposal-v2`, 2026-09-30)

Roadmap R1 (EXP-002 freeze blockers). Writer B, from `main` at `e8703d7`. **These are technical settings for
review, not a questionnaire and not a freeze.** EXP-002 stays DRAFT. `protocol.toml` is not changed by this
document.

This version supersedes `exp002-freeze-proposal-v1` (`EXP002_FREEZE_PROPOSAL.md`, 2026-09-28) **for the review
only**. v1 is never edited in place. It stays the record the review compares against. A later version gets a new
version id.

Status words are those of v1 and `RESEARCH_UNBLOCKING_DECISIONS.md`:
- **APPROVED**: a recorded owner decision;
- **VERIFIED**: checked against cited primary evidence;
- **PROPOSED**: a recommendation only;
- **BLOCKED**.

**Data rule for this document.** No EXP-002 data was viewed to write it:
- no production database, pilot book, odds capture, pair or settlement;
- no `exp002 --with-results` run, and no E1 or markout result;
- no NFL 2026 result or standings.

Its inputs are repository documents and code. It also reads EXP-002's `evidence_use.jsonl`, which records
access events and holds no market data. Every EXP-002 fact below comes from a cited repository record.

## 0. What changed since v1

| v1 item | v2 | Source |
|---|---|---|
| §3 row 1: `t_max = 0.01`, `u_max = 0.005`, "a sourced count is still required" | Sourced counts exist. PROPOSED `t_max = 0.01` (99% level; sensitivity 0.02) and `u_max = 0.01` (95% level; sensitivity 0.005) | `EXP002_TIE_NOTPLAYED_BOUNDS.md` (#138) |
| §2 fallback row: "a venue or home/away change" | Corrected to the terms' Venue Change clause: only a game **moved outside the same scheduling week, or with the home/away designation reversed** | contract terms PDF; #138 §1; `CURRENT_BLOCKERS.md` (NFL_FALLBACK_WORDING) |
| E1 (§3 rows 3–5, 11) | Implemented as research code, `exp002-e1-roundtrip-v1` (#129), with conservative readings (§4). Still PROPOSED | `EXP002_E1_ENDPOINT.md` |
| A.C timing calibration | The tool is built and deployed (#142, #143). It runs once, logged, at a fixed point in the sequence (§5) | `EXP002_AC_CALIBRATION_TOOL.md` |
| §3 row 14, variant budget | The A.C run's three windows count against it (§5.2) | A.C tool doc; A.H |
| §4 evidence exposure | Seven hand-recorded evidence-use events, all closed (§6.2) | `experiments/EXP-002-*/evidence_use.jsonl` |
| §5 blockers | Updated list and timeline (§8) | this document |
| — | A placeholder for the independent E1 design review (§E1 review) | pending |

## 1. APPROVED owner economics (recorded; not re-decided here; identical to v1)

Source: `docs/owner/2026-09-26-owner-decisions-economics-backup.md`, item 1.

| Item | Approved value | What it is not |
|---|---|---|
| Minimum useful threshold | **$1,000/year after-cost contribution**, for deciding whether the family deserves continued development beyond the research/pilot stage. Packet option B attributes a test band: ≤ $2,500 illustrative peak deployed capital, on the FIRST_DETECTION_ZERO_LATENCY lower band. | Not a promise. Not a capacity estimate. Not a pilot requirement. Not a claim that the research ladder can produce it (A.E ladder scenarios: $1.70–$382.50 a season). **Not a substitute for a minimum detectable markout effect** (§3). |
| Owner hours | **6 owner hours through 2026-10-22**: pilot report 2 h, freeze review 2 h, buffer 2 h. Stop rules of C.4. | Hours are hours, never dollars; no hourly value is assumed. **The +8 h extension is NOT granted.** It returns to the owner. |

The illustrative arithmetic of v1 §1 is unchanged and still UNVERIFIED for KXNFLGAME fees:
- 1.6¢ per contract after all costs at 250 contracts a game on about 255 games, or 39¢ at 10 contracts;
- a T-6h→T-60m round trip of about 4.5¢ under the general formula.

## 2. Contract facts (corrected)

| Fact | State | Source |
|---|---|---|
| KXNFLGAME YES pays $1 on a win (overtime included) and $0 on a loss | VERIFIED | contract terms 2026-09-11; market rules (A.D) |
| A tie after overtime pays $1/(tied teams), rounded down = $0.50 | VERIFIED. Also observed in production: `KXNFLGAME-25SEP28GBDAL` settled 0.5000 on both team markets | terms; `rules_secondary`; #138 §2.2 (Kalshi public API) |
| **Discretionary last fair price F ∈ [0, 1]** when a game is: (a) postponed and not started within 48 hours; (b) suspended or abandoned after kickoff, before 55 minutes of play, and not resumed within 48 hours (unless declared final); (c) forfeited before kickoff; (d) under the Venue Change clause, **moved outside the same scheduling week, or with the home/away designation reversed**; (e) affected by a disqualification or ineligibility before the game starts | VERIFIED (discretionary F) | terms (`rules_evidence/FOOTBALLGAMEWIN_contract_terms_read-2026-09-25.pdf`, sha256 `19578b71…cfca4b`); `rules_evidence/MANIFEST.md`; #138 §1 |
| **Not F:** a venue change that keeps the designated home and away teams, with the game played within 48 hours of the original date, resolves on the official final result. So does a postponement that starts within 48 hours | VERIFIED | terms, Venue Change and postponement clauses; #138 §1; `CURRENT_BLOCKERS.md` |
| Suspended after 55 min, not resumed and not declared final | **CONFLICT**: "result as it stands" (terms, Sept) vs "last fair market price" (certification, Feb). Which governs is UNVERIFIED. Absorbed in `u` (§3 row 2) | A.D; question S1 / Kalshi message Q9 (NOT SENT) |
| Settlement fee | "There is no settlement fee" (fee schedule 2026-07-07). Settlement rounding is not addressed | `EXP002_FEE_VERIFICATION.md` |
| KXNFLGAME trading fee | **FEE_UNSUPPORTED** (§7) | `CURRENT_BLOCKERS.md` FEE_KXNFLGAME |
| Fill granularity 0.01 contracts; fills can be fractional for whole-contract orders | VERIFIED (documented behaviour) | Fixed-Point docs (EXP-001 `fee_verification/`) |
| A YES ask is 1 − the best NO bid (orderbook representation) | VERIFIED (documented) | `kalshi_quotes`; A.A |
| Reading `settlement_value_dollars` as the YES payoff of a KXNFLGAME tie | Partly supported (the 2025 GB–DAL tie settled at 0.50); no KXNFLGAME fallback-F settlement has been observed. E1 refuses to guess when the value is absent (§4) | #138; `EXP002_E1_ENDPOINT.md` §2 item 9 |

**The wording correction.** v1 §2 listed "a venue or home/away change" as an F trigger. That is broader than the
terms, whose Venue Change clause sends a game to F only if it is "reversed or if the game is moved outside the
same scheduling week" (terms PDF, Venue Change). A venue-only move with the designation kept and play within 48
hours resolves normally. #138 §3 classified the historical venue-only moves (for example 2018 KC @ LAR, 2021 GB @
NO) as not F. The bounds in §3 row 1 already use this narrower reading, so the correction changes a sentence, not a
number.

## 3. PROPOSED technical settings

Rows marked "unchanged" restate v1 in substance; v1 §3 holds the full text and rationale.

| # | Setting | PROPOSED value (v2) | Change from v1 | Depends on |
|---|---|---|---|---|
| 1 | Tie and not-played payoff bounds | In `V = (1 − t − u)·p + 0.50·t + u·F`, F ∈ [0, 1], every state stays in the sample. **`t_max = 0.01`**, set at the **99%** level: it clears the exact one-sided 99% Poisson bound of the 10-minute-overtime era, 8 ties in 2,383 games = 0.73%. Registered sensitivity `t_max = 0.02` (the 2025+ both-possess rule has 1 tie in 320 games; 95% bound 1.48%). **`u_max = 0.01`**, set at the **95%** level, **not 99%**: 14 conservative F events in 2,384 scheduled games (2017–2025, pandemic seasons included) give a 95% bound of 0.92% and a 99% bound of 1.07%. Registered sensitivity `u_max = 0.005`, which holds only if 2020 (and, at 99%, 2021) are excluded, a regime assumption that cannot be verified ex ante. | `u_max` 0.005 → 0.01; both now sourced | owner review |
| 2 | Suspended-game rule conflict | Absorbed in `u`: both texts pay a value in [0, 1]. Recorded as UNRESOLVED; Kalshi message Q9 (NOT SENT) | unchanged | — |
| 3 | Primary endpoint | **E1**, the executable gross round-trip markout under FIRST_DETECTION_ZERO_LATENCY: T-6h entry from AT_OR_AFTER_ODDS pairs when `c_low(side) − ask ≥ θ` with displayed ask depth ≥ 1, at most one side per game; exit at the bid of the first T-60m book; missing exits scored at the settlement payoff, with exit-at-0 as a sensitivity. Now implemented (§4). | unchanged design; implemented | E1 design review (§E1 review) |
| 4 | Direction rule and test | One-sided, H₀: E[gross P&L] ≤ 0; game units; wild cluster bootstrap with Rademacher weights and NFL-week clusters; one-sided 90% bound for futility; θ = 1¢ frozen before any label | unchanged | E1 design review |
| 5 | Secondary endpoints | (a) the mid-based cross-book markout and placebo, "not bias-bounded", descriptive; (b) hold-to-settlement gross of the E1 trades; (c) the attrition waterfall | unchanged | — |
| 6 | Maximum input ages | Odds ≤ 10 min; Kalshi book ≤ 5 min; sportsbook `last_update` ≤ 10 min (CURRENT) | unchanged | — |
| 7 | Pair-skew semantics | Join v2 window [−5, +10] min, provisional; E1 admits AT_OR_AFTER_ODDS only | unchanged; the A.C run proposes the window (§5) | A.C run |
| 8 | Episode start / end / merge | A.F: 2¢ per contract after fees at 10 contracts | unchanged | **BLOCKED** by FEE_UNSUPPORTED |
| 9 | Minimum meaningful quantity | 10 contracts | unchanged | — |
| 10 | Size ladder | 1, 10, 50, 100, 250 contracts, descriptive; visible depth is a ceiling | unchanged | — |
| 11 | Minimum useful measured effect | δ_min(E1) = 1¢ gross per contract, statistical; possibly under-powered at a ~30% trade rate. The pilot trade rate and E1 SD decide it before the freeze. The economic hurdle is separate and needs fees | unchanged | pilot look (§6.1); fees |
| 12 | Independent clusters and episodes | `min_independent_clusters` = max(8, ⌈weeks needed at ICC 0.10⌉) from the pilot E1 SD; `min_episodes_for_scenario` = 20 over ≥ 4 weeks | unchanged | pilot look |
| 13 | Development and evaluation windows | §6 | restated with the exposure record | — |
| 14 | Variant budget | V0 (E1) plus at most 2 registered challengers, Holm-corrected. The E0→E1 change is a design revision made with no data viewed and does not consume the budget. **New:** the A.C run's windows count against the budget (§5.2). | clarified | owner review |
| 15 | Futility | Operational (at the review), statistical (one interim, 2026-11-30), economic, as in v1 | unchanged | — |
| 16 | Continuation | Only with a named missing observation, its cash cost and owner hours approved at the review. **The +8 h is not granted.** | unchanged | owner |

### 3.1 Effect of the bounds on E1 entries (analytic; nothing run)

Raising `u_max` from 0.005 to 0.01 lowers `c_low` by `0.005·p`: at most 0.5¢, about 0.25¢ at p = 0.5. A T-6h side
is lost only if its margin `c_low − ask` lies in the band **[θ, θ + 0.005·p)**. With θ = 1¢ that band is under
half a tick wide, because asks sit on a 1¢ grid and `c_low` is continuous. The tie term at `t_max = 0.01` lowers
`c_low` by `t·max(p − 0.5, 0)`, which is zero for p ≤ 0.5 and 0.3¢ at p = 0.8 (#138 §5).

The number of pilot entries in that band has **not** been counted. The count is label-free, because E1 entry uses
T-6h information only. The coordinator can get it on production by running `exp002` **without**
`--with-results`, once with `--e1-tie-bound 0.01 --e1-postponement-bound 0.005` and once with `0.01` and `0.01`,
and reporting the two entry counts. It is optional and not a blocker.

The base-rate reads behind these bounds included public 2026 settlements and standings covering DEVELOPMENT-pilot
games. They were aggregate reads: non-binary settlements and tie counts only. They are recorded as evidence-use
event `eu-622b393fce9cb7a4da0e105a1d9b13bc` (§6.2). The pilot games contributed 0 events to either count.

## 4. E1 status (implemented, PROPOSED, not frozen)

`exp002-e1-roundtrip-v1` is implemented in `src/edge_lab/sports_evidence.py` (#129), with tests in
`tests/test_exp002_e1.py` and the measurement version `exp002-measurement-v3`. It reports gross figures only;
every output is labelled "PILOT DESCRIPTIVE — PROPOSED ENDPOINT, NOT FROZEN, NOT A TEST" and "a displayed quote is
not a proven fill". Its conservative readings (`EXP002_E1_ENDPOINT.md` §2) include:
- **Undeclared bounds compute no entries.** Today `JoinPolicy()` and the protocol leave `t_max` / `u_max`
  UNKNOWN, so a default run counts every side as `BOUNDS_UNDECLARED`. There is no fallback to the unadjusted
  consensus.
- **Run-time bounds until the freeze.** Until a freeze records the bounds in `protocol.toml`, they are passed at
  run time with `--e1-tie-bound` / `--e1-postponement-bound`. They are recorded as `CALLER_DECLARED_CANDIDATE`,
  validated before the store opens, and never reach the gates.
- Pairing is judged per side. Freshness fails closed. Each side gets exactly one reason, in a fixed order.
- A missing exit is scored at the settlement payoff; one whose settlement is not final is PENDING, never 0.
- A tie or fair-price settlement uses the stated `settlement_value_dollars` only when it is within [0, 1];
  otherwise PENDING.
- The wild cluster bootstrap is exact up to 12 weeks and flagged `COARSE_FEW_CLUSTERS` below 10. Its bounds are
  descriptive and are not compared with δ_min.
- The label-free path cannot read a T-60m book or a settlement. Results need a logged `--with-results` run.

Implementing E1 clears no blocker by itself; it makes the design reviewable.

## §E1 review: pending; recommendations will be incorporated

**PENDING.** An independent E1 design review is being written in a separate PR
(`docs/research/EXP002_E1_DESIGN_REVIEW.md`). Its PROPOSED changes (for example bootstrap calibration and bias
points) will be folded into this section and into §3 rows 3, 4, 11 and 15 before this proposal goes to review. No
recommendation is assumed here.

## 5. A.C timing calibration

### 5.1 When and how it runs

- **Built and deployed:** `sports_evidence exp002-timing` (#142, #143; deployed with production `23b7b3b`).
- **Runs once, logged**, on production:
  - **after** the pilot's T-6h weeks, which cover kickoffs through **2026-10-19 ET** (`PILOT_FIRST_ET` 2026-09-27
    to `PILOT_LAST_ET` 2026-10-19);
  - **before** any pilot markout or E1 result is viewed.
  - It is never run early, and never re-run to "improve" a window.
- It reads T-24h and T-6h timing and feature fields of pilot games only. It never reads a T-60m target, book or
  their existence, a later book or a settlement.
- It records a FEATURE_INSPECTION event (DEVELOPMENT; `influenced_tuning` true) in EXP-002's log before showing
  anything, and refuses if it cannot. Its output and event carry the caveat "T-60m book prices possibly seen
  (UNKNOWN, unlogged Terminal display)".
- **Its output is a PROPOSED input**, not a freeze. The recommended window goes to the owner's review as a
  PROPOSED join variant. Changing `JoinPolicy` is separate, reviewed work.

### 5.2 Its windows count in the variant budget

The tool reports all three windows it tries: [−5, +5], [−5, +10] and [−10, +15] min. Under A.H ("every tried
timing limit, filter or horizon counts") and the tool's own rule (A.C step 4), **each window counts against
EXP-002's variant budget** of V0 plus at most 2.

The provisional [−5, +10] is V0's window. The other two therefore take **both challenger slots**. v1 row 14 named
two candidate challengers (a T-24h decision, θ = 2¢). Under the current rule, neither can be registered without a
larger budget.

PROPOSED: keep the budget as it is. Treat the two tried windows as the two registered challengers. Record the
T-24h and θ = 2¢ candidates as not registered. Whether a label-free timing choice should count separately is an
owner question for the review; this proposal does not assume it.

## 6. Windows and evidence exposure (no silent shift)

### 6.1 Windows

| Window | v1 | v2 (PROPOSED) |
|---|---|---|
| Development pilot | kickoffs 2026-09-27 → 2026-10-19 ET | **Unchanged.** DEVELOPMENT role; every look logged. |
| A.C run | after the pilot, before any label look | **Unchanged order**, now with a tool (§5): once, after the pilot's T-6h weeks, before any pilot markout or E1 result. |
| Pilot label look (E1 SD, trade rate, markout SD, placebo) | after the A.C timing freeze | After the A.C run is recorded. Logged as LABEL_RESULT_INSPECTION, DEVELOPMENT. Those games are permanently excluded from evaluation. It feeds rows 11 and 12. |
| Freeze | not promised; earliest decision at the 2026-10-22 review | **Not promised.** The owner's review on 2026-10-22 decides, within the approved 6 hours. A freeze cannot be recorded before that review, so the v1 case "recorded by 2026-10-21" no longer applies. |
| Evaluation (untouched) | first kickoff after both the freeze record and 2026-09-29T02:09:50Z | **Unchanged rule.** It starts at the first kickoff after the freeze is recorded (so not before 2026-10-22) **and** after 2026-09-29T02:09:50Z, whichever is later. A game kicking off on 2026-10-22 before the freeze record time is excluded. Games between 2026-10-22 and a later freeze are not added, even if unviewed. The start time goes into the freeze record. It ends at week 18, about 2027-01-10. |

### 6.2 Evidence-use events recorded since v1

Read from `experiments/EXP-002-nfl-consensus-vs-event-market/evidence_use.jsonl` on 2026-09-30. The log holds a
header and exactly the seven events below: all LABEL_RESULT_INSPECTION, DEVELOPMENT, scope
`sports:nfl:moneyline`, `influenced_tuning` false. The first six are **hand-recorded possible exposures, not
confirmed views** (`viewed_labels` null). The seventh is a deliberate aggregate read (`viewed_labels` true,
`viewed_results` false). All windows are closed.

| Event | Surface | Window (UTC) | Closed by |
|---|---|---|---|
| `eu-7f8e61282393c0bf2258b4bc90dd92c7` | Terminal "Latest paired book" could show a T-60m KXNFLGAME book (ask, depth) | 2026-09-26T00:00 → 2026-09-29T01:16:30 | extended by the next event |
| `eu-f4954194ccbea8817aef73d4343122bb` | same, extended to the #124 deploy (REVISION 29a37d7) | 2026-09-26T00:00 → 2026-09-29T02:09:50 | #124 deploy |
| `eu-4defeb1ad1016f2d05711056ff557e4e` | Polymarket US related-market T-60m / post-cutoff captures (Terminal Data sources, `pm-sports status`); a correlated label proxy | 2026-09-26T00:00 → 2026-09-29T13:16:16 | #130 deploy (e0d3330); CLI paths closed by `eu-1b51…` |
| `eu-1b511255ce03cd852668a4f124151625` | CLI paths: plain `sports_evidence report` related entries and `observe status --market kalshi:KXNFL…` | 2026-09-26T00:00 → 2026-09-29T14:24:17 | #131 deploy (0d1e210) |
| `eu-9a3aeaf3f2c6e0c9def3b1a46c8a2edf` | Odds API T-60m / post-cutoff consensus (Terminal, `odds consensus`, plain report rows); a correlated label proxy | 2026-09-24T00:00 → 2026-09-29T14:36:08 | extended by the next event |
| `eu-d9f8610f10ba4ff51727de34679a2f29` | same, closed at the PR D deploy | 2026-09-24T00:00 → 2026-09-29T15:45:00 | #132 deploy (d508773) |
| `eu-622b393fce9cb7a4da0e105a1d9b13bc` | Aggregate public read of 2026 KXNFLGAME settlements and NFL.com 2026 standings (T column), for the #138 bounds | 2026-09-27T00:00 → 2026-09-29T00:15:00 | a single read |

**Consequences (restated):**
- Pilot-window data are DEVELOPMENT only and can never be relabelled untouched.
- The evaluation window starts after the freeze (so not before the 2026-10-22 review) **and** after
  2026-09-29T02:09:50Z. Every recorded window ends before either, so none moves the start.
- The A.C record states the exposure caveat instead of certifying that no label was in view.
- An evidence-use log records declared access only (its header says so). It cannot prove the absence of an
  unlogged view.

## 7. Fees

- **KXNFLGAME is still FEE_UNSUPPORTED** (`CURRENT_BLOCKERS.md`, FEE_KXNFLGAME):
  - it is on the captured non-standard fee list (PDF pp.6–11), and no verification record exists;
  - the public Fees help page, read 2026-09-30, defers per-series fees to the PDF;
  - the PDF re-read returned HTTP 429, so the 2026-09-23 capture remains the evidence.
- The **Kalshi fee re-check is due 2026-10-23T13:39:48Z**, the day after the review. A new record, if any, arrives
  too late to inform the review, so plan without it.
- Consequences:
  - the gross E1 test can be frozen without fees, but no net or after-cost claim can be made;
  - the episode threshold (row 8) stays BLOCKED;
  - the economic hurdle of row 11 cannot be evaluated.
- Resolvers: a Kalshi answer (message revision 2, Q7, NOT SENT; sending is the owner's), or a new primary document.

## 8. Freeze blockers and timeline

**No freeze is promised.** The owner's 2026-10-22 review decides, within the approved 6 hours. None of the items
below is cleared by this document.

| # | Blocker | State (2026-09-30) |
|---|---|---|
| 1 | Review of the E1 primary endpoint (§3 rows 3–5, 11) | Implemented (#129). The independent design review is **pending** (§E1 review). E0 cannot be frozen: gate v3 has no pass |
| 2 | Sourced tie and not-played bounds behind `t_max` / `u_max` | **Sourced** (#138). The values are PROPOSED (§3 row 1) for the owner's review. They are not in `protocol.toml` until a freeze records them |
| 3 | A.C timing calibration, logged, with the exposure caveat | Tool built and deployed. **Waiting for its window** (§5) |
| 4 | KXNFLGAME fees for any after-fee figure | **FEE_UNSUPPORTED** (§7). It does not block a gross freeze; it blocks every net claim and row 8 |
| 5 | Label paths closed before evaluation-window captures | **DONE**: #124 (Terminal T-60m book), #130 / #131 (Polymarket proxy and CLI paths), #132 (Odds consensus proxy), with the closing events of §6.2 |
| 6 | Contract wording in the proposal | **DONE in v2** (§2, the Venue Change clause) |
| 7 | The owner's freeze review | 2026-10-22, within 6 approved hours |

Not blockers, recorded: the suspended-after-55-minutes conflict (absorbed in `u`; message Q9 NOT SENT); the optional
label-free E1 entry count in the `[θ, θ + 0.005·p)` band (§3.1); the tie `settlement_value_dollars` reading (§2).

**Timeline (dates govern; nothing here is a deadline that lowers a standard):**

| When | What | Who |
|---|---|---|
| now → 2026-10-19 ET | Pilot capture continues; no label look | collectors (APPROVED) |
| after the pilot's T-6h weeks (about 2026-10-19/20) | A.C run, once, logged (§5) | coordinator |
| after the A.C run is recorded | Pilot label look for E1 SD and trade rate, logged | coordinator |
| before the review | E1 design review folded into this proposal (§E1 review) | reviewer, then this author |
| 2026-10-22 | Owner freeze review: freeze, change or stop, within the 6 approved hours | owner |
| first kickoff after the freeze record (if any) | Evaluation window starts | — |
| 2026-10-23T13:39:48Z | Kalshi fee re-check due | fee owner |
| 2026-11-30 | The one statistical interim look, if frozen | — |

## 9. Sources

- `docs/research/EXP002_FREEZE_PROPOSAL.md` (v1, unchanged)
- `docs/research/EXP002_TIE_NOTPLAYED_BOUNDS.md` (#138)
- `docs/research/CURRENT_BLOCKERS.md` (#150)
- `docs/research/EXP002_E1_ENDPOINT.md` (#129)
- `docs/research/EXP002_AC_CALIBRATION_TOOL.md` (#142, #143)
- `docs/research/RESEARCH_UNBLOCKING_DECISIONS.md` (A.C, A.D, A.H)
- `docs/research/EXP002_FEE_VERIFICATION.md`
- `experiments/EXP-002-nfl-consensus-vs-event-market/rules_evidence/` (terms PDF, MANIFEST)
- `experiments/EXP-002-nfl-consensus-vs-event-market/evidence_use.jsonl` (access log, read 2026-09-30)
- `docs/owner/2026-09-26-owner-decisions-economics-backup.md` (APPROVED economics)
