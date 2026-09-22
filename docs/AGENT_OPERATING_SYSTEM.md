# Agent Operating System

How agents work in this repository. The rules themselves live in `AI_INSTRUCTIONS.md`; this
file covers the workflow. It is model-neutral and grants no product or financial authority.

## 1. The work loop

A delegated mission runs until it reaches its finish line or hits a real external blocker.
It is not over after one response.

```
inspect main/PRs/claims → claim → implement → test → review own diff adversarially
→ fix → retest → evidence → handoff
```

- **Inspect** the live code path before changing it. Do not work from memory or from chat.
- **Test** with the cheapest relevant check first, then run the full `python -m pytest` before pushing.
- **Self-review**: read the diff as a hostile reviewer would. Ask what would make CI reject it,
  and what it claims that isn't proven.
- **Evidence**: record the exact commands and results. `UNRESOLVED: NONE` must be true.

Ask the owner only when a decision is consequential (financial, destructive, credentials or
spending), crosses a gate, or is genuinely ambiguous after reading the repo. Routine
implementation choices are resolved from evidence and existing conventions. If one lane is
blocked, keep working on independent lanes.

## 2. Parallel agents: split real work, not role names

Parallelize only when there are genuinely independent tasks. The default shape:

```
coordinator (root) → 1–3 bounded specialists on independent tasks → root integrates
→ independent read-only reviewer when the change is material
```

Every delegated agent gets this contract, in writing, in its prompt:

| Field | Example |
|---|---|
| Mission | "Survey current news-API terms and costs" |
| Owned files / area | `src/edge_lab/foo.py`, `tests/test_foo.py` — or **read-only** |
| Role | writer or read-only (researchers and reviewers are read-only) |
| Expected output | a report, a diff, a test result |
| Acceptance test | `python -m pytest tests/test_foo.py` passes; the report cites sources |
| Stopping condition | done, blocked (say why), or N attempts without progress |

**One writer per file or area.** Two agents never edit the same file set at the same time.
The root agent owns the canonical docs (`AI_INSTRUCTIONS.md`, this file, `HANDOFF.md`,
`docs/EXECUTION_PLAN.md`) unless it explicitly hands one over.

## 3. Model strength

Match the model to the stakes:

- Cheaper/faster models handle mechanical, bounded work: formatting, renames, simple fixtures,
  and summarizing a known file.
- The strongest available reasoning model handles architecture, statistics and experiment
  design, debugging, adversarial validation, anything touching money or risk, and final review
  of consequential changes.

Escalate when evidence shows a task is harder than expected. Never trade correctness for tokens.

## 4. Branches, PRs, CI

- `main` is shared truth. Use one bounded branch per coherent change. Prefer one meaningful PR
  over many tiny ones.
- Never rewrite history on a shared branch or someone else's branch.
- A PR description ends with the handoff block from `AI_INSTRUCTIONS.md`.
- CI (`.github/workflows/test.yml`) must be green on the PR head before anyone calls it CI_GREEN.
  A red CI is work to do now, not something waiting on review.
- Merging needs owner approval unless `docs/EXECUTION_PLAN.md` delegates it for that class of change.

## 5. Work claims

`docs/WORK_CLAIMS.md` holds one line per piece of work in flight. The rules:

1. Before editing, check open PRs, branches and the claims table for overlapping paths.
2. Add your row in your first commit, with an **expiry date** of 7 days or less.
3. A claim blocks concurrent edits to **the paths it lists**, not a whole area. On a
   collision, move to other work. Do not fork the file or build a parallel version.
4. **Delete** your row in your last commit. Git history is the log, so the table stays short.
5. An expired row is not a live claim. Anyone may remove it, and should say so in their commit.

## 6. Handoffs

`HANDOFF.md` is the **current state**, overwritten each session, not a diary. It uses the
handoff block from `AI_INSTRUCTIONS.md`, plus a short list of known open questions. Another
model must be able to continue from `main` + `HANDOFF.md` alone, without "the previous chat."

## 7. Skills and agent evals (deferred)

This repository is small enough that the routing table in `AI_INSTRUCTIONS.md` is the whole
progressive-disclosure layer. Add `.agents/skills/<name>/SKILL.md` (with YAML frontmatter
`name` and `description`) only when a repeated procedure has outgrown a doc section.
Behavioral agent evals are deferred; see `docs/decisions/0006-defer-agent-behavior-evals.md`.
Deterministic repository invariants live in `tests/invariants/` and run in CI.
