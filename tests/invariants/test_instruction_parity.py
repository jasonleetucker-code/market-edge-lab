"""Structural checks that keep one canonical instruction system.

These check structure (pointers, size, existence), not wording, so that honest edits
to the canonical rules don't break tests while forks and bloat do.
"""

import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "AI_INSTRUCTIONS.md"
ADAPTERS = {"AGENTS.md": 30, "CLAUDE.md": 20}  # file -> max lines
HANDOFF_FIELDS = ("STATUS:", "ACCEPTANCE:", "EVIDENCE:", "UNRESOLVED:", "BLOCKERS:", "NEXT ACTION:")


def test_canonical_file_exists_and_is_compact():
    lines = CANONICAL.read_text().splitlines()
    assert 40 < len(lines) <= 200, "AI_INSTRUCTIONS.md should stay a compact front door"


def test_adapters_point_to_canonical_and_stay_thin():
    for name, max_lines in ADAPTERS.items():
        text = (ROOT / name).read_text()
        assert "AI_INSTRUCTIONS.md" in text, f"{name} must point to AI_INSTRUCTIONS.md"
        assert len(text.splitlines()) <= max_lines, f"{name} exceeds {max_lines} lines; move rules to canonical docs"
        # Adapters hold mechanics, not rule sections.
        assert len(re.findall(r"^#{1,6} ", text, re.M)) <= 1, f"{name} has rule sections"


def test_claude_adapter_imports_canonical():
    assert "@AI_INSTRUCTIONS.md" in (ROOT / "CLAUDE.md").read_text().splitlines()


def test_every_routed_document_exists():
    text = CANONICAL.read_text()
    routed = set(re.findall(r"`((?:docs|experiments)/[^`]*|HANDOFF\.md)`", text))
    assert routed, "routing table not found"
    missing = [p for p in routed if not (ROOT / p).exists()]
    assert not missing, f"AI_INSTRUCTIONS.md routes to missing paths: {missing}"


def test_handoff_has_all_fields():
    text = (ROOT / "HANDOFF.md").read_text()
    missing = [field for field in HANDOFF_FIELDS if field not in text]
    assert not missing, f"HANDOFF.md missing {missing}"


def test_work_claim_rows_are_well_formed():
    rows = [
        line for line in (ROOT / "docs/WORK_CLAIMS.md").read_text().splitlines()
        if line.startswith("|") and not line.startswith("|---") and "| Claim |" not in line
    ]
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) == 5 and all(cells), f"claim row needs 5 non-empty cells: {row}"
        date.fromisoformat(cells[4])  # expiry must be an ISO date
