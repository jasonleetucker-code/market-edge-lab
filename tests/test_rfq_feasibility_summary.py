"""The Terminal's RFQ feasibility summary equals the feasibility document (PR C; R4 display)."""

from __future__ import annotations

from pathlib import Path

from edge_lab import rfq_research as rr

DOC = Path(__file__).resolve().parents[1] / rr.FEASIBILITY_DOCUMENT


def _matrix_rows() -> list[list[str]]:
    text = DOC.read_text(encoding="utf-8")
    block = text[text.index("## 2. (a) Capability and observability matrix"):text.index("### 2.1")]
    rows = [line for line in block.splitlines() if line.startswith("| ") and not line.startswith("| Item |")]
    return [[c.strip() for c in r.strip("|").split("|")] for r in rows]


def test_every_matrix_row_is_summarized_in_order_with_a_consistent_state():
    rows = _matrix_rows()
    assert [r[0] for r in rows] == [x.item for x in rr.FEASIBILITY_MATRIX]
    for cells, row in zip(rows, rr.FEASIBILITY_MATRIX):
        who, status = cells[2].lower(), cells[-1]
        if row.state is rr.CapabilityState.DOCUMENTED:
            assert status.startswith("VERIFIED"), row.item
        elif row.state is rr.CapabilityState.UNKNOWN:
            assert any(w in status for w in ("UNKNOWN", "UNRESOLVED", "UNVERIFIED")), row.item
        elif row.state is rr.CapabilityState.PRIVATE:
            assert any(w in who for w in ("parties", "private", "requester", "quoter")), row.item
        else:
            assert "authenticated" in who, row.item


def test_the_decision_and_the_owner_decisions_match_the_document():
    text = DOC.read_text(encoding="utf-8")
    assert f"## 6. (e) Decision: **{rr.FEASIBILITY_DECISION}**" in text
    assert [d for d, _ in rr.OWNER_DECISIONS] == ["D1", "D2", "D3", "D4", "D5", "D6"]
    for d, _ in rr.OWNER_DECISIONS:
        assert f"| {d}:" in text or f"{d}: " in text, d
