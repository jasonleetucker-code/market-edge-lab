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


S = rr.CapabilityState
# The one state each document row maps to, read from its "Who can see it" and "Status" columns. A mislabelled
# summary row fails here, whatever the looser rules below allow.
EXPECTED = {
    "Request metadata": S.UNAVAILABLE,  # authenticated channel; we hold no credential
    "Combo definitions and legs": S.DOCUMENTED,
    "Authentication and actual entitlements": S.UNKNOWN,
    "Storage, training and derived-data rights": S.UNKNOWN,
    "Our quotes vs other makers' quotes": S.PRIVATE,
    "Acceptance and fill visibility": S.PRIVATE,
    "Native quantity and payout": S.DOCUMENTED,
    "Fee-inclusive vs principal-only target size": S.DOCUMENTED,
    "Full-request obligations and partial acceptance": S.UNKNOWN,
    "Quote replacement and expiry": S.DOCUMENTED,
    "Acceptance → maker confirmation → execution": S.DOCUMENTED,
    "Timing classes and the binding point": S.DOCUMENTED,
    "Collateral": S.UNKNOWN,
    "Common-leg exposure": S.DOCUMENTED,
    "Account attribution": S.DOCUMENTED,
    "Outage, pause, cancel and unknown states": S.UNKNOWN,
}


def test_each_row_maps_to_exactly_one_expected_state():
    assert {x.item: x.state for x in rr.FEASIBILITY_MATRIX} == EXPECTED
    assert [r[0] for r in _matrix_rows()] == list(EXPECTED)


def test_every_matrix_row_is_summarized_in_order_with_a_consistent_state():
    rows = _matrix_rows()
    assert [r[0] for r in rows] == [x.item for x in rr.FEASIBILITY_MATRIX]
    for cells, row in zip(rows, rr.FEASIBILITY_MATRIX):
        who, status = cells[2].lower(), cells[-1]
        if row.state is rr.CapabilityState.DOCUMENTED:
            assert status.startswith("VERIFIED") and "access UNKNOWN" not in status, row.item
        elif row.state is rr.CapabilityState.UNKNOWN:
            assert any(w in status for w in ("UNKNOWN", "UNRESOLVED", "UNVERIFIED")), row.item
        elif row.state is rr.CapabilityState.PRIVATE:
            assert any(w in who for w in ("parties", "private", "requester", "quoter")), row.item
        else:  # UNAVAILABLE: documented, but only for an authenticated account we do not have
            assert "authenticated" in who and "access UNKNOWN" in status, row.item


def test_the_decision_and_the_owner_decisions_match_the_document():
    text = DOC.read_text(encoding="utf-8")
    assert f"## 6. (e) Decision: **{rr.FEASIBILITY_DECISION}**" in text
    assert [d for d, _ in rr.OWNER_DECISIONS] == ["D1", "D2", "D3", "D4", "D5", "D6"]
    for d, _ in rr.OWNER_DECISIONS:
        assert f"| {d}:" in text or f"{d}: " in text, d
