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


def test_owner_idea_intake_is_routed_and_indexed():
    text = CANONICAL.read_text()
    assert "`docs/OWNER_IDEAS.md`" in text and "Owner ideas" in text
    index = (ROOT / "docs/OWNER_IDEAS.md").read_text()
    assert "issue #4" in index and "Review log" in index
    assert "An issue is not authorization" in index or "never authorizes" in index


def _owner_ideas_section() -> str:
    text = CANONICAL.read_text()
    start = text.index("## Owner ideas")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else None]


def test_owner_idea_intake_triggers_replanning():
    section = _owner_ideas_section()
    for word in ("NOW", "NEXT", "LATER", "BLOCKED"):
        assert word in section, f"owner-idea rule lacks the {word} classification"
    for dimension in ("priority", "dependencies", "overlap", "shared infrastructure", "parallel", "roadmap"):
        assert dimension in section, f"owner-idea re-planning lacks the {dimension!r} analysis"
    assert "already-needed shared primitive" in section, "owner-idea rule lacks the shared-primitive question"
    assert "Re-prioritizing never authorizes" in section, "re-planning must not read as authorization"


def test_shared_primitives_have_exactly_one_canonical_owner():
    text = (ROOT / "docs/OWNER_IDEAS.md").read_text()
    start = text.index("## Shared primitives")
    table = text[start:text.index("\n## ", start + 1)]
    rows = [line for line in table.splitlines() if line.startswith("|") and not line.startswith("|---")][1:]
    assert len(rows) >= 10, "the shared primitives table is incomplete"
    required = ("identity", "venue", "quote", "fee", "model", "source", "ledger", "risk", "notification",
                "execution-ticket", "eligibility", "equivalence")
    first_cells = " ".join(row.strip("|").split("|")[0].lower() for row in rows)
    missing = [name for name in required if name not in first_cells]
    assert not missing, f"shared primitives missing from the table: {missing}"
    names = []
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) == 4 and all(cells), f"primitive row needs 4 non-empty cells: {row}"
        names.append(cells[0].lower())
        owners = re.findall(r"`([^`]+)`", cells[1])
        assert len(owners) == 1, f"a primitive needs exactly one canonical owner: {row}"
        if cells[2].startswith("PLANNED"):
            assert not (ROOT / owners[0]).exists(), f"{owners[0]} exists: update its row from PLANNED"
        else:
            assert (ROOT / owners[0]).exists(), f"built primitive owner is missing: {owners[0]}"
    assert len(names) == len(set(names)), "a primitive is listed twice"


def test_owner_idea_index_covers_open_directive_issues():
    index = (ROOT / "docs/OWNER_IDEAS.md").read_text()
    for issue in ("#3", "#5", "#6", "#7", "#9", "#10", "#27", "#29", "#30", "#32", "#33"):
        assert f"| {issue} |" in index, f"owner idea {issue} is not indexed"
