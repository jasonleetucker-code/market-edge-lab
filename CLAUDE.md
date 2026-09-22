# CLAUDE.md — adapter

@AI_INSTRUCTIONS.md

The line above imports the canonical instructions into Claude Code. This file contains
no unique rules; any rule found here belongs in `AI_INSTRUCTIONS.md` or a doc it routes to.

Claude-specific mechanics only:

- Use `python -m pytest` (the `pytest` on PATH may belong to a different interpreter).
- When subagents are used, follow the role template in `docs/AGENT_OPERATING_SYSTEM.md`.
