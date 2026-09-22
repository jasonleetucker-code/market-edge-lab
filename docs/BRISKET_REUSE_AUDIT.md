# Brisket infrastructure reuse audit

**Audit date:** 2026-09-22. **Tracking:** #12. **Delivery plan:** #11 (October 22).

## Conclusion and scope

Brisket is a useful engineering reference, not a trading framework to transplant.
Market Edge already contains most of the valuable ingestion patterns. The immediate
missing pieces worth porting are a small environment/context receipt, strict local
validation tiers, and WAL-aware backup/restore verification. These are implemented
in this change, without new runtime dependencies or any live service activation.

This is a cross-repository **infrastructure portability audit**, not a claim that every
line of Brisket has been security-audited, its production host was inspected, or its
entire test suite was executed. Code findings below come from the named functions;
production statements remain documentation unless separately measured. The first
reuse audit remains recoverable in Git history at Market Edge commit `22d217b`.

Pinned baselines:
- Brisket: `6932b97a297265313dbe962fb7ef1d2896cc6b63`.
- Market Edge: `22d217b8ac37742a5adef6ea0a0f6557bdfa2952`.
- Market Edge Gate 3 merged (PR #14, `2f5d640`); Gate 4 (baseline model) is now the
  active gate. Dataset construction, research splits, preregistration and owner-intake
  integration from Gate 3 remain recoverable in Git history; the root handoff and
  `docs/EXECUTION_PLAN.md` track the current Gate 4 workstream.

## Evidence inspected

Paths below are in the pinned Brisket revision unless prefixed `Market Edge`.
They are reproducible references, not instructions to load all of them every session.

| Evidence | What was examined |
|---|---|
| `AI_INSTRUCTIONS.md` | Universal entrypoint, owner intake, routing, receipts, formatter contract |
| `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md` | Twelve priorities; distinguish a proposed improvement from implemented code |
| `docs/engineering/AGENT_HARNESS_EXTERNAL_GUIDANCE_RECONCILIATION_2026-09-12.md` | Original 15-post reconciliation, provenance limitations and official Astra source |
| `scripts/agent_os_receipt.py` | Complete receipt implementation, subprocess errors, hashing and publication |
| `scripts/agent_session_start.sh` | Startup router, test-collection check and checkout-vs-source-freshness explanation |
| `scripts/tiered_validate.sh` | Complete quick/subsystem/full runner and failure propagation |
| `scripts/ci_change_scope.py` | Diff classification and working/staged/untracked path handling |
| `deploy/backup_user_kv.sh` | Complete online-backup, retention and restore-test implementation |
| `src/diagnostics/scrape_telemetry.py` | Complete event persistence, rotation, phase publication and error handling |
| `src/ros/scrape.py` | Failure isolation, cached-source behavior, CSV/run metadata publication |
| `src/sources/ktc_value_sources.py` | Native source provenance, numeric normalization, projected browser extraction and all-source capture |
| `agent-evals/README.md` | Actual evaluation contract and explicit self-reported-evidence limitation |
| `deploy/systemd/README.md` | Documented timers, liveness behavior, root-owned scripts and deployment separation |
| Market Edge `AI_INSTRUCTIONS.md`, `docs/BRISKET_REUSE_AUDIT.md` | Existing canonical policy and previous classifications |
| Market Edge `storage.py`, `pyproject.toml`, `tests/conftest.py`, CI workflow | Schema v3, runtime dependency policy, network guard and validation integration |
| Market Edge main/branches/open PRs/work claims | Initial baseline and collision check; unpushed Claude work is not observable |

No Brisket files, deployments, configuration or credentials are changed by this port.

## Reuse matrix: implementation versus ideas

| Mechanism | Disposition | Market Edge owner / action |
|---|---|---|
| One model-neutral front door | ALREADY COVERED | Keep `AI_INSTRUCTIONS.md`; do not create another Agent OS |
| Thin provider adapters | ALREADY COVERED | Keep existing `AGENTS.md` / `CLAUDE.md`; no unique product rules |
| Durable handoff/evidence ladder | ALREADY COVERED | Current handoff and gate documents; do not replace Claude's active state |
| Owner-intake capture and readiness review | APPLY IN EXISTING LANE | #4 belongs to Gate 3; index #3/#5/#6/#7/#9/#10/#11 instead of another backlog |
| Local session context / receipt | **ADAPTED NOW** | `scripts/agent_context.py` |
| Tiered local checks | **ADAPTED NOW** | `scripts/validate.py`; explicit target selection, no auto-skipped CI |
| Same-interpreter test invocation | **ADAPTED NOW** | `sys.executable -m ...`, with full-mode package-origin check |
| Exact-head CI | PRESERVE | Existing full 3.11/3.12 matrix; no path-skip changes |
| Selective CI classifier | DEFER | Explicit local targets suffice; full suite remains small enough to retain |
| Online SQLite backups | **ADAPTED NOW** | `edge_lab.backup`; manual, isolated bundles, no production paths |
| Restore testing | **ADAPTED NOW** | Hash + schema + row counts + integrity + foreign keys + disposable restore |
| Scheduled backup/retention/cloud mirror | DEFER | Requires hosting, storage/retention decision and explicit authorization |
| Source adapters and provenance | ALREADY COVERED | Existing collectors, `sources`, `provenance`, SQLite schema v3 |
| HTTP retries/pacing/pagination | ALREADY COVERED | Preserve Gate 2 implementation; no second fetcher |
| Captured replay fixtures | ALREADY COVERED / EXPAND WITH SOURCES | Existing collector and settlement fixtures; retain originals and parser version |
| Source-level failure isolation | ALREADY COVERED | Existing CLI/source-health path |
| Row/coverage checks | ADAPT, NOT COPY | Source-specific completeness evidence, not fantasy player-count floors |
| Freshness/last-good cache | PRESERVE STRICTER TARGET | Historical cache may be read; cannot masquerade as fresh tradable data |
| Versioned SQLite schema | ALREADY COVERED | Keep `SnapshotStore`; backup does not migrate or own schemas |
| Durable telemetry | PARTLY COVERED | Existing fetch/health records; later add crash-visible in-progress heartbeat in the same owner |
| Liveness versus readiness | APPLY AT HOSTING | An upstream outage must not produce an automatic service-restart loop |
| Bulk projected browser extraction | DEFER, KEEP LESSON | Extract required fields once if a permitted browser source becomes necessary |
| Playwright scraper | DO NOT COPY NOW | No authorized present source needs it; avoid browser memory overhead |
| Fantasy rankings/confidence/value blending | DO NOT COPY | Ranks and league valuations are not calibrated market probabilities |
| Source sentinel zero/missing convention | DO NOT COPY | A genuine zero temperature/price/profit is valid; unknown is separate |
| Agent behavioral grader | DEFER | Self-reported artifact flags are not independent proof of behavior |
| Steward/autonomous dispatch | DEFER | Adds state and cost; current bounded tasks suffice |
| Frontend/API framework | DEFER TO WEB LANE | Reuse architecture lessons, not an entire Next.js site before interfaces stabilize |
| Sleeper authentication | DO NOT COPY | Owner-only financial dashboard needs its own reviewed access boundary |
| nginx/systemd/host paths | ADAPT AT #10 | Separate service identity, secrets, DB, limits and rollback; measure actual host first |
| Immutable builds/locks/dependency audits | NEXT ENGINEERING CHECKPOINT | Source backlog is guidance, not evidence it is already solved |
| New external efficiency suggestions | EVALUATE PROMPTLY | Record source, check fit, test against actual task evidence, then promote |

The deadline is unchanged. This small reliability tranche supports #11; it does not
activate sports, a dashboard, paid feeds, scheduled collectors, Gate 4, or live orders.

## Concrete portability findings

### F1. Source validation can claim more than it proves

In `scripts/tiered_validate.sh`, `run_l2` runs `python -m pip check || true`,
which discards the dependency checker failure. If frontend dependencies are absent,
it prints instructions rather than failing, then reaches `L2: GREEN`. The file's
additive-tier description also differs from dispatch: selecting `l1` alone invokes
`run_l1`, not `run_l0` first. These are code-path findings; no production incident
is being inferred from them.

**Port:** each requested tier explicitly includes syntax validation. Full mode never
narrows tests and stops on a failed dependency, missing comparison base, wrong
checkout package, absent test target, pytest exit 5, command failure or timeout.
Successful output says only `REQUESTED_CHECKS_PASSED`, never CI_GREEN/DEPLOYED.

### F2. Source diff failure handling is not uniformly fail-closed

`ci_change_scope.py` widens on an unavailable main comparison, but local working,
staged and untracked collection each use `... or ""`. A failure there is therefore
indistinguishable from no local changes. Its line-based filename parsing is also
not a complete solution for unusual Git filenames.

**Port:** no automatic scope inference or CI skipping. Agents explicitly name local
test paths; full checks still run before integration. Revisit an automatic selector
only when measured test runtime justifies a tested, fail-closed implementation.

### F3. Existing backup script has application-specific weak-success paths

Brisket correctly uses SQLite's online-backup primitive. However, missing source
files are skipped with success, its restore check selects only the user_kv backup,
and the row-count query falls back to `0` after a SQL error before printing success.
Those choices must not become evidence-preservation guarantees in Market Edge.

**Port:** an incorrect source path cannot create an empty database. Every created
bundle is unique. Verification checks byte length/hash, required evidence tables,
all user-table counts, schema identity, SQLite integrity/foreign keys, and a real
restore into a disposable DB. No existing live DB or prior backup is overwritten.

### F4. A hash receipt is not proof the model read instructions

The source receipt is valuable for version attribution. But the label "loaded"
does not establish actual model ingestion or compliance. Its write failure is
intentionally swallowed, so a caller cannot assume the convenience file exists.

**Port:** JSON to stdout only, labeled filesystem evidence. Missing facts stay null.
It reports local HEAD/base, dirty state, interpreter/package origin and document
fingerprints, with `remote_state=NOT_CHECKED`. There are no hidden pulls/resets or
new shared receipt files. Actual live PR/claim inspection still uses GitHub.

### F5. Source defaults are not financial data semantics

KTC `_num` discards values at or below zero because that is its player-value
convention. ROS can retain earlier CSVs and reduce an availability multiplier.
Neither is a portable market-risk policy. Zero is a valid numerical observation;
a reduced source score does not make a stale quote safe to trade.

**Port:** preserve Market Edge's existing missing/freshness distinctions. The backup
integration regression specifically preserves a zero-valued snapshot without
changing it to missing. No fantasy weights, probabilities or cutoffs are imported.

### F6. Browser and telemetry lessons are useful without their runtime

`selected_players_array` projects required fields in-page; `capture_all_value_sources`
reuses one payload. That is the transferable performance idea, not copying the
fantasy parser, its global state, or its browser dependencies.

The telemetry module deliberately prioritizes non-interference and process-crash
survival over power-loss durability. That may fit diagnostic logs; it is not suitable
as the only ledger of future financial decisions. Existing evidence storage remains
the owner. A future crash heartbeat should reference that run ID, not form a second
source-health database. Log rotation and backups must have different retention rules.

### F7. Source agent evals grade declarations, not observed actions

The source README explicitly acknowledges that its flags/summary/path checks grade
what the submitted artifact declares. A useful optional aid, but not evidence that
an agent actually ran a test or obeyed a rule. We keep executable regressions and
actual CI evidence rather than porting a large self-report framework now.

### F8. Previous audit claims need attribution, not repetition

The earlier Market Edge report contains size/load claims about Brisket and categorical
statements about its monolithic scraper. This audit does not present those as newly
measured runtime facts. File length is not actual billed tokens; a source comment
is not an execution trace. Dated historical reports are not inherently technical debt.

## Your Twitter/Astra/Claude guidance

The Brisket reconciliation records all 15 original post identifiers. Its retrieval
summary says four had exact/corroborating content, two surfaced different posts by
the same author, and nine could not be retrieved. This is **the earlier auditor's
retrieval record**, not a claim this session retrieved all original posts.

Retain that distinction. An inaccessible post belongs in UNVERIFIED / NEEDS SOURCE,
not automatically REJECTED and not silently ALREADY_IMPLEMENTED based on a guessed
meaning. Adjacent posts and reposts are not independent corroboration.

Current first-party documentation was checked in this audit:
- [OpenAI Astra guidance](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra): task-relevant context, narrow routing and explicit finish lines; not maximal scaffolding.
- [Claude subagents](https://code.claude.com/docs/en/sub-agents): isolated context helps bounded side tasks; model selection and repeated context still matter. Do not assume Explore always uses a cheap model; verify the installed version and actual routing.
- [Claude memory](https://code.claude.com/docs/en/memory): imported files consume context; machine-local memory is not cross-machine project memory. Repository documents remain the shared record.

Apply the mechanisms, not a model name as a permanent role. No new model/API calls,
paid subscriptions, global profile overrides or automatic self-modifying agent loop
are introduced. No token-savings percentage is claimed without comparable measurements.

For each new efficiency idea record: exact source/content availability, mechanism,
existing canonical owner, disposition, test/evidence, and rollback. Compare correctness,
rework and total actual usage on representative tasks. One successful run does not
prove a universal saving. Urgent correctness/security work still outranks experiments
with an unverified tweet.

## Implementation and verification boundaries

Code ports are **adaptations**, not byte-identical imports. Brisket's domain/host
coupling and weak-success paths required changes. The source online-backup primitive
is also documented by [SQLite](https://www.sqlite.org/backup.html) and
[Python 3.12](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup).

See [RELIABILITY_TOOLKIT.md](engineering/RELIABILITY_TOOLKIT.md) for exact commands,
limits and the cross-model work loop.

Tests cover failure propagation, interpreter choice, missing/changed documents,
no hidden network commands, WAL contents, source protection, repeated backups,
corrupt bundles, invalid manifests, foreign-key violations and real SnapshotStore
integration. Local testing here used Python 3.13 / pytest 9; supported 3.11/3.12 and
the complete existing suite must be verified by the PR's actual GitHub Actions run.
The local runtime cannot clone GitHub (DNS unavailable), so it is not represented
as a full local checkout test. CI evidence belongs to the exact checked head.

No independent reviewer agent or live host inspection is claimed. This author
performed adversarial self-review and regressions. Independent PR review remains
part of the repository's material-change process. Source code is unchanged.

## Next integration points, without duplicate owners

1. Gate 4 owner finishes #4's idea-index/front-door rule and keeps the Gate 3
   dataset/holdout access controls in force. In particular, split before descriptive
   error analysis and do not inspect holdout feature-label relationships while
   choosing a model.
2. Before recurring collection: use verified backup bundles plus explicitly approved
   off-host storage/retention; add crash-visible run state, host resource limits and
   availability tests to the existing ingestion/hosting lane.
3. Before web deployment: typed API contracts, private auth and restricted cookies,
   separate Unix/service identity, no shared broker secrets, restore rehearsal and
   build identity. Shared VPS isolation is not equivalent to a separate host.
4. Before scaling engineering: pin/lock the selected dependency and formatting
   toolchain once; do not copy Brisket's old version pins or mass-format unrelated
   code. Measure the full suite before adding path-aware CI skips.
5. Before source subscriptions: compare costs and incremental benefits over the same
   period and current capital scale; information quality alone is not an ROI proof.

None of these follow-ups is an automatic research-gate or spending approval.
