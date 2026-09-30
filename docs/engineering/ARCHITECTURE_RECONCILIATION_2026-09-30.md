# Architecture reconciliation — 2026-09-30

Directive: [`docs/owner/2026-09-30-architecture-reconciliation-directive.md`](../owner/2026-09-30-architecture-reconciliation-directive.md)
(intake issue #152).
External review baseline: main `519580d` (#148). This note was written against main `14704e3` (#150, merged
2026-09-30 11:17Z during this session). It is one linked engineering note, not a roadmap: package order stays in
[`DELIVERY_ROADMAP.md`](../strategy/DELIVERY_ROADMAP.md) and authority stays in `docs/EXECUTION_PLAN.md`.

**Result:**
- The existing architecture is kept.
- One offline evidence path was verified end to end, and two confirmed provenance gaps in its canonical owner were
  fixed, each with a regression that failed first.
- One agent-workflow rule was made explicit (AGENT_OPERATING_SYSTEM §1, "Defects").
- Nothing else is adopted. Nothing here is evidence of an edge.

## 1. Existing architecture (verified or pointed to; nothing recreated)

| Review finding | Canonical owner | Verified here |
|---|---|---|
| Python/SQLite evidence store, immutable snapshots and raw documents | `storage.py`, `sources.py`, `provenance.py` (`docs/DATA_PROVENANCE.md`) | Owner table only (`docs/OWNER_IDEAS.md` → Shared primitives). Not re-audited |
| Source health and freshness | `freshness.py` (`assess`, `require_fresh`, `parse_utc`), `freshness_fabric.py` | `assess`/`parse_utc` as used by the in-play path (§2) |
| argparse CLI; replay-derived shadow ledger; private Terminal; bounded systemd operations | `cli.py`; `shadow_ledger.py`; `dashboard/`; `deploy/` | Owner table only. No operating service was touched |
| In-play reconstruction, sequence gaps, distinct clocks, corrected game-state history, failure coverage; R2 source-state intelligence | `inplay_evidence.py` (contracts `inplay-evidence-v1`, `source-state-v1`, ADR 0038/0041) | Yes, end to end (§2–§3) |
| Scoped delegation, one writer per area, review/fix loops, model selection, completion states | `docs/AGENT_OPERATING_SYSTEM.md`, `AI_INSTRUCTIONS.md` | Yes (§4) |

## 2. The in-play offline evidence path: owner and dependency map

No production caller exists: no in-play recorder is approved, and production shows `NOT_AUTHORIZED`
(`dashboard/data.py::inplay_view`). The path runs on fixtures, synthetic cohorts and test-written journals only.

| # | Stage | Owner · symbols | Contract / schema | Side effects | Proving tests |
|---|---|---|---|---|---|
| 1 | Journal file (the only transport) | `inplay_evidence.read_journal`, `journal_data_kind` (new), `JournalLine` | JSONL. Header `{"journal": "inplay-journal-v1", "data_kind": SYNTHETIC\|FIXTURE\|RECORDED}`. Each line `{receipt_utc, kind: book\|failure\|game_state, body, first_observed_utc?, processing_utc?}`. A bad line is a PARSE_ERROR failure, never skipped | Reads one local file. No socket, no write | `test_journal_requires_a_header`; `test_a_journal_with_no_lines_keeps_its_header_data_kind` (new) |
| 2 | Normalization | `parse_book_message` → `BookMessage` or `ParseFailure`; `game_state_from_payload` → `GameState` | `Stamps`: receipt, first-observed, processing and venue `source_ts_utc` (from `ts_ms` only). `raw_sha256` per message; `GameState.observation_id` | Pure | `test_four_clocks_stay_separate_and_source_time_is_never_invented`, `test_null_game_stats_is_unsupported_and_unmapped_fields_stay_unknown` |
| 3 | Sequencing and books | `SubscriptionReconstructor`, `reconstruct_many`, `apply_message`, `replay_book_journal` | `BookState` (VALID or unusable with reason), `Transition`, `SeqScope` | Pure, in memory | gap/duplicate/seq-scope tests in `test_inplay_evidence.py`; `test_fixture_journal_reconstruction_with_gap_reconnect_and_failures` |
| 4 | Coverage | `coverage_report` → `CoverageReport` | usable seconds; unusable seconds by reason including SILENT_UNKNOWN; gaps, resyncs, failures | Pure | `test_coverage_counts_unusable_and_silent_time_and_keeps_failures` |
| 5 | Freshness and state validity | `freshness.assess`; `content_freshness`; `GameJournal`, `game_state_as_of`; `decision_validity` → `StateValidity` | `StateValidity.authorizes_execution` is always False; INVALIDATED / REVIEW_REQUIRED reasons | Pure | `test_source_state.py`: `test_material_new_event_invalidates_the_dependent_recommendation`, `test_duplicate_state_changes_nothing_and_a_correction_invalidates`, `test_unknown_incorporated_state_is_never_inferred_from_receipt_order`, `test_stale_data_that_was_just_received_is_stale`, `test_future_state_reference_and_future_as_of_are_refused` |
| 6 | Policy proposal | `position_policy.evaluate` → `PolicyDecision` (`position-policy-v1`) | BOOK_STALE if received after as-of or older than max age. State validity blocks. `authorizes_execution` False | Pure | `test_position_policy.py` |
| 7 | Replay | `inplay_replay.replay(Cohort, ReplayConfig)` → `ReplayReport` (`inplay-replay-v1`) | `cohort_sha256`, `config_variant`, fee model id. A RECORDED cohort is refused. Its only producer is `synthetic_martingale_cohort`; no journal-to-cohort builder exists (by design until a recorder is approved) | In memory; `ReplayLedger` never touches a stored ledger | `test_every_arm_sees_the_identical_cohort_and_diagnostics_stay_apart`, `test_recorded_cohorts_are_refused_and_labels_must_say_synthetic`, `test_no_fill_is_interpolated_through_a_gap`, `test_a_recommendation_invalidated_before_submission_sends_nothing`, `test_a_state_change_after_the_order_left_cannot_recall_it` |
| 8 | Fill economics | `inplay_view.fill_economics_section` → `research_economics` (`Fill`, `ExecutionMode`) | SIMULATED fills only; missing denominators named | Pure | `test_research_economics_fills.py`; `test_fill_economics_keeps_modes_apart_and_names_missing_denominators` |
| 9 | Consumer | `inplay_view.build_view` / `fixture_view` / `not_authorized_view` → dict `inplay-view/1`; `dashboard/data.py::inplay_view`, `inplay_fixture_views`; `dashboard/views/inplay.py` formats only | View states POPULATED / EMPTY / STALE / PARTIAL / UNSUPPORTED / PAUSED / ERROR / NOT_AUTHORIZED. `build_view` refuses RECORDED data and ACTUAL inventory | Pure; renders make no network call | `test_inplay_view.py`, `test_dashboard_inplay.py`, `test_inplay_evidence_path.py` (new, file → consumer) |

**Provenance owner.** The in-play journal is not registered in `sources.py`/`storage.py`, because no recorder
exists. When one is approved (R3 → R6), its raw journal goes through `sources.py`/`provenance.py`, not a second
evidence store. Per-message `raw_sha256` is the content address today.

## 3. Criteria: what the tests proved before this change, and after

| Criterion | Before | After this PR |
|---|---|---|
| Attributable to input hashes, versions and as-of | **Replay: covered.** Cohort hash, config variant, replay, evaluator and policy versions, fee model and as-of (`test_the_cohort_hash_covers_the_parsed_state_and_is_unchanged_without_a_journal`, `test_synthetic_generator_is_deterministic_and_labelled`). **Book path: PARTIAL.** Per-message `raw_sha256` is dropped by `BookState`/`Transition`, and the view's book evidence id `journal:<ticker>:seq<n>` is not content-addressed | Unchanged. **Proposed for the R3 scope entry (R3a, §5):** it changes the `inplay-view/1` contract, so it needs its own UI-contract review |
| Missing source time never replaced by receipt time | **Messages: covered** (`test_four_clocks_…`). **Books: GAP B.** `BookState.last_source_ts_utc` was carried forward from an earlier message, including across a gap and a resync onto a new subscription | **FIXED.** The field is now the venue stamp of the last applied message, or None. Through the consumer, before the fix a snapshot received 5 s earlier showed a pre-gap `published_utc` and a measured 599.05 s TRANSPORT "latency". Content age was UNKNOWN before and after, because the view's venue clock has no error bound. No gating changed: BOOK_STALE uses receipt time. The published time was falsely attributed, and the false latency figure would have fed the R2 latency research |
| Synthetic, fixture and recorded stay distinguishable | Covered (`check_evidence`; Cohort and `build_view` refuse RECORDED) except **GAP A:** `replay_book_journal` defaulted to SYNTHETIC when a journal had no lines, so an empty RECORDED journal passed `build_view`'s RECORDED refusal and was shown as synthetic | **FIXED.** The kind comes from the header (`journal_data_kind`); the consumer refuses. Tests are parametrized over all three kinds |
| Gaps, corrections, stale input and unknown state refuse through the consumer | Covered: `test_stale_paused_and_resync_views_never_propose_a_sale`, `test_partial_view_keeps_gaps_and_failures`, `test_an_invalidated_decision_is_blocked_with_its_reason`, `test_an_unreadable_state_update_needs_review`, plus the replay-state tests in §2 row 7 | Also through a journal *file* into the consumer (`test_the_fixture_journal_reaches_the_view_with_its_label_coverage_and_refusals`) |
| Failures and unusable intervals stay in coverage | Covered (§2 row 4) | Also asserted after the file → consumer hop |
| Pinned inputs, code, config and as-of reproduce the result | Covered for `fixture_view` (`test_fixture_view_is_deterministic`) and the synthetic replay | Also a file → view test on a byte copy of the journal, with the as-of shown to be the replay clock (`test_the_same_pinned_journal_config_and_as_of_reproduce_the_same_view`) |
| No live writes, network, execution or protected labels | Network, storage and execution direct-import checks covered `inplay_evidence`, `inplay_replay`, `position_policy`. **Not** the consumer `inplay_view`. The checker missed `from . import x`. **No** protected-label check existed for any module | **Extended (test-only, direct imports):** `inplay_view` joins the boundary and the subprocess no-socket import test, `from . import x` is resolved, and a new direct-import assertion covers protected-label owners (`sports_evidence`, `exp002_timing`, `odds_schedule`, `price_observations`, `odds_consensus`, `experiments`, `settlement`, `forward`). Mutation-checked: adding `from . import sports_evidence` to `inplay_view` fails it. **Transitive imports are not covered.** `research_economics` imports `experiments` (the `RESERVED_TEST_EXPERIMENT_IDS` constant), and `position_policy` → `execution_ticket` → `risk` imports `shadow_ledger` (the `AccountState` type). This predates the branch. No protected data or store is read on the in-play path. A transitive `sys.modules` check with a justified allowlist is left for R3a |

**Observed, not changed:** `build_view` takes the last transition even when it was received after `as_of`.
- This fails closed. The policy refuses with `BOOK_STALE: received <time>` (the receipt is after the as-of), and the view shows STALE, so no
  sale is proposed.
- But the view's source block then shows the later receipt time, and its detail says "older than".
- Point-in-time slicing of transitions is the caller's job today. It belongs with R3a.

**Also observed:** the hand-written fixture `tests/fixtures/inplay/ws_orderbook_journal_fixture.jsonl` gives
`ts_ms` values exactly two days before their receipt times (2026-10-02 against 2026-10-04). No existing assertion
reads them, and the fixture is left unedited. Any future latency test that uses it must correct this in a separate,
labelled derivative fixture, not by overwriting this one.

## 4. External ideas: source access and adoption

**Two questions, kept apart:** could the source be read (access), and is its mechanism useful here (disposition)?

### 4.1 Official references (read 2026-09-30 by a read-only researcher)

WebFetch returns a model summary of each page, so this is not a raw-text audit. The Anthropic article is dated
2024-12-19.

| Mechanism | Official guidance (paraphrased) | Market owner | Disposition |
|---|---|---|---|
| M1 task-specific context | OpenAI: a minimal root document routing to supporting docs. Claude memory: keep CLAUDE.md short; imports load at launch; procedures belong in skills | `AI_INSTRUCTIONS.md` routing table; `CLAUDE.md` / `AGENTS.md` adapters; AOS §7 | ALREADY_COVERED |
| M2 explicit finish lines | OpenAI: put run / inspect / fix in the request. Anthropic: stopping conditions such as iteration caps. Sub-agents: `maxTurns` | AOS §1 work loop; §2 contract (acceptance test, stopping condition); handoff block | ALREADY_COVERED |
| M3 durable, attributed handoffs | Claude auto-memory is machine-local and not a shared record. CLAUDE.md/AGENTS.md are shared through git | `HANDOFF.md` (dated, "by"), `WORK_CLAIMS.md`, owner issues, git; "No private instruction forks" | ALREADY_COVERED. No memory database |
| M4 bounded independent workers | Anthropic: parallelization and orchestrator-workers. Sub-agents: tool limits, worktree isolation | AOS §2 (1–3 specialists, one writer per area, read-only reviewers) | ALREADY_COVERED. Used here: one read-only researcher and one read-only reviewer |
| M5 failure → regression → reviewed fix | Anthropic: evaluator-optimizer; tests verify code; human review stays crucial | AOS §1 (test, self-review, evidence); Gate 7 findings; `tests/invariants` | **PARTIAL → IMPLEMENT_NOW:** AOS §1 "Defects" bullet, applied first in this PR. Behavioural agent evals stay **DEFERRED** (ADR 0006: no repeated behavioural failure observed, gate 8 not reached) |

All four sources favour simple, composable patterns, with complexity added only when it measurably helps. That is
the same as roadmap rule 5 and ADR 0006. AOS §3 already routes by capability, risk and cost; no model roster is
added.

**Rejected without a measured need:**
- Calculator's Steward;
- a vector database;
- a second scheduler;
- a graph framework;
- a generic agent platform;
- a behavioural-eval harness;
- unattended self-modification.

### 4.2 The 25 owner-supplied links

**Access in this session.** Three were attempted (#3, #6, #8). All returned HTTP 402 with no body: UNVERIFIED here.
The other 22 were not attempted.

**The "Review access" column is the external reviewer's state and was not re-verified here.** Its "indexed" means
INDEXED_EXCERPT_ONLY. "Topic" is the reviewer's recovered title, not read content. No disposition relies on unseen
detail; a failed retrieval says nothing about an idea's merit.

| # | Source (x.com status id) | Review access | Topic (per review) | Disposition |
|---|---|---|---|---|
| 1 | av1dlive 2097362674078331148 | indexed | cross-agent memory stack | ALREADY_COVERED (M3); no memory DB |
| 2 | lucaspatiri_ 2097357340215279710 | indexed | UGC prompting | NOT_APPLICABLE |
| 3 | kocer_eth 2098333699641086183 | UNVERIFIED | not recovered | none (unseen) |
| 4 | rubenhassid 2098365950940569639 | indexed | skill / prompt packs | DEFERRED: a skill only when a repeated procedure outgrows a doc (AOS §7); no pack install |
| 5 | virgilxbt 2098412843775172931 | UNVERIFIED | not recovered | none (unseen) |
| 6 | openaidevs 2098480213244117065 | indexed | skills, context, completion | ALREADY_COVERED (M1, M2), via the official article |
| 7 | txbrraa 2098521751898529815 | indexed | website tutorial | NOT_APPLICABLE (the UI contract governs) |
| 8 | akshay_pachaar 2064051835636498924 | indexed | self-repairing harness | M5 loop only, IMPLEMENT_NOW; unattended self-repair or promotion NOT_APPLICABLE |
| 9 | 0xricker 2097328121556979988 | indexed | long-horizon agents | ALREADY_COVERED (M2); run-length claims not adopted |
| 10 | gippp69 2097696163424014406 | indexed | agent-run back office | NOT_APPLICABLE |
| 11 | mikenevermiss 2098270564016091458 | indexed | general model guide | NOT_APPLICABLE (no concrete mechanism) |
| 12 | pvncher 2095991462416490862 | indexed | rethinking skills/prompts | Same source family as #6; ALREADY_COVERED |
| 13 | maestrooth 2096882831138165160 | indexed | prompt collection | NOT_APPLICABLE |
| 14 | sairahul1 2096902575035683147 | indexed | prompting masterclass | ALREADY_COVERED (M1, M2) |
| 15 | n01ennn 2096962591125905888 | indexed | graph and loop engineering | ALREADY_COVERED (M4); no graph framework |
| 16 | bober_smart 2078784709253841039 | indexed | second-brain folders | ALREADY_COVERED (git-backed decisions); no second source of truth |
| 17 | beamnxw 2098087790663672123 | indexed | model use-case catalog | NOT_APPLICABLE |
| 18 | chddaniel 2105003444067328214 | indexed | Dots guide | NOT_APPLICABLE (no reliability, permission or cost evidence) |
| 19 | 0xcodila 2105037810591772840 | UNVERIFIED | not recovered | none (unseen; not conflated with #20) |
| 20 | 0xcodila 2105087209342685352 | indexed | always-on chief of staff | NOT_APPLICABLE; unattended access to financial systems is prohibited (AI_INSTRUCTIONS → Authority) |
| 21 | higgsfield 2104989726604484946 | indexed | always-on creative agents | NOT_APPLICABLE |
| 22 | teamily_ai 2105025063762489426 | indexed | human-agent business OS | NOT_APPLICABLE (no paid platform, no replacement Agent OS) |
| 23 | charliejhills 2104204601553777129 | indexed | AI motion design | NOT_APPLICABLE (the UI contract governs) |
| 24 | minchoi 2101873007673086304 | indexed | different models for different jobs | ALREADY_COVERED (AOS §3); no hard-coded roster |
| 25 | slash1sol 2104975408319926389 | indexed (photo URL) | terminology teaser | NOT_APPLICABLE (insufficient context) |

## 5. Roadmap placement

- **No new package.** This work sits in R0 (evidence integrity) and on the R2/R3 in-play path. Everything R0–R11
  and its dependencies stay as listed in `DELIVERY_ROADMAP.md` §5–§9.
- **Next dependency-ready package: R3.**
  - **R3a** (proposed; offline code, testable once scoped): make the in-play consumer attributable and point-in-time:
    - carry a journal content digest and the last applied message's `raw_sha256` through `BookState`/`build_view`;
    - slice transitions to the as-of;
    - show both in the existing in-play page under the UI contract, with its states.
  - The documentation-only `inplay-source-pilot-1` refresh onto the R2 contracts, as already recorded in HANDOFF and §9.
- **Authority for R3a.**
  - R3a is *proposed* for the R3 scope entry that `HANDOFF.md` (#151) and roadmap §9 require before R3 starts.
  - It needs that new entry. Whether it comes before or after the pilot-proposal refresh is the owner's or
    coordinator's call when that entry is written.
  - Any capture, recorder activation, rights change or research slot stays BLOCKED on the owner.

## 6. Compatibility and safety

- **Schemas unchanged:** `inplay-view/1`, `inplay-evidence-v1`, `source-state-v1`, `inplay-replay-v1`.
- **Values change only in two cases:**
  - When the last applied book message carried no venue stamp, `last_source_ts_utc`, `published_utc` and the
    TRANSPORT stage are now None. They render with the existing wording ("not sent", "Unknown age…", unmeasured).
  - A journal with no lines now reports its header's data kind.
- **Fixture gallery unchanged:** every fixture's last applied message carries a stamp.
- **Backend-only:** no page, component or style changed.
- **Not touched:** EXP-001 artifacts, EXP-002 exposure controls, NFL/NHL separation, quotas, protected windows,
  collection, fees, methodology, models, timers, credentials, production stores, the A.C calibration.
