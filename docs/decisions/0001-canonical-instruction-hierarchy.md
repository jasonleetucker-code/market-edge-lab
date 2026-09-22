# 0001 — One canonical, model-neutral instruction file

Status: Accepted (2026-09-22)

**Problem.** Several AI systems (ChatGPT, Codex, Claude, Astra, others) will work in this
repo. Rules kept in one provider's file, or in a model's memory, drift out of sync. Brisket
shows the failure mode: a 2,507-line `CLAUDE.md` acting as the "universal" runbook, and the
same rules copied into three files.

**Alternatives.** (a) One file per vendor, kept in sync by hand. (b) `AGENTS.md` as the
canonical file. (c) A neutral `AI_INSTRUCTIONS.md`, with thin adapters.

**Decision.** (c). `AI_INSTRUCTIONS.md` holds every rule plus a routing table to the domain
docs. `AGENTS.md` (read natively by Codex, Copilot, Cursor, Gemini CLI, Jules and others)
and `CLAUDE.md` (which `@import`s the canonical file) hold loading mechanics only. Agents
with no repo discovery (ChatGPT, Astra) get a one-line bootstrap prompt. No `GEMINI.md`,
because Gemini CLI can read `AGENTS.md`.

**Tradeoffs.** One indirection for AGENTS-native tools. A test enforces the adapter
structure (pointer present, size cap, no rule sections), not the meaning of rules.

**Reconsider if** a major tool stops following a pointer from its adapter, or if AGENTS.md
becomes a universally imported standard. In that case, make AGENTS.md canonical and turn
`AI_INSTRUCTIONS.md` into the pointer.
