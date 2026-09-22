# AGENTS.md — adapter

Read **`AI_INSTRUCTIONS.md`** first. It is the canonical, model-neutral instruction file.
This adapter contains no unique rules; if you find one here, move it there.

Mechanics for AGENTS.md-aware tools (Codex, Copilot, Cursor, Gemini CLI, Jules, others):

- Setup: `python -m pip install -e ".[dev]"` (Python 3.11+).
- Test: `python -m pytest` (use the interpreter you installed into).
- Current state: `HANDOFF.md`. Current authorization: `docs/EXECUTION_PLAN.md`.
