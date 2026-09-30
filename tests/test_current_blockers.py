"""The current-blocker register and its document stay in step (PR C, R1; 2026-09-30)."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from edge_lab import current_blockers as cb

DOC = Path(__file__).resolve().parents[1] / "docs" / "research" / "CURRENT_BLOCKERS_2026-09-30.md"
NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def _doc_rows() -> dict[str, str]:
    rows = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| ([A-Z0-9_]+) \| ([A-Z_]+) \|", line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def test_every_register_item_is_in_the_document_with_the_same_status():
    assert _doc_rows() == {b.blocker_id: b.status.value for b in cb.BLOCKERS}


def test_the_register_is_consistent_and_every_item_has_a_source_and_resolver():
    assert cb.validate() == []
    for b in cb.BLOCKERS:
        assert b.sources and b.resolver_detail and b.trigger and b.verified and b.unknown
    bad = replace(cb.BLOCKERS[0], sources=())
    assert cb.validate((bad, bad))  # duplicate ids and no source


def test_the_owner_only_actions_are_marked_for_approval():
    owner = {b.blocker_id for b in cb.BLOCKERS if b.owner_approval_needed}
    assert {"KALSHI_MESSAGE_REV2", "DATA_RIGHTS", "NHL_READ_TIME_GAP", "EXP002_FREEZE_REVIEW"} <= owner
    assert cb.BLOCKERS[[b.blocker_id for b in cb.BLOCKERS].index("KALSHI_MESSAGE_REV2")].status is cb.Status.NOT_SENT


def test_next_blocker_is_the_soonest_dated_open_item_and_recorded_items_are_not_open():
    assert cb.next_blocker(NOW).blocker_id == "ROUTINE_OFFHOST_BACKUP"
    undated = tuple(replace(b, due_utc=None) for b in cb.BLOCKERS)
    assert cb.next_blocker(NOW, undated).owner_approval_needed
    recorded = tuple(b for b in cb.BLOCKERS if b.status is cb.Status.RECORDED)
    assert recorded and cb.next_blocker(NOW, recorded) is None
    assert all(b.status is not cb.Status.RECORDED for b in cb.open_blockers())


def test_staleness_after_fourteen_days():
    b = cb.BLOCKERS[0]
    assert not cb.is_stale(b, NOW)
    assert cb.is_stale(b, datetime(2026, 10, 20, tzinfo=timezone.utc))


def test_contract_exceptions_are_per_series_and_unresolved_stays_unresolved():
    nhl = cb.exceptions_for("KXNHLGAME-26OCT04BOSTOR-BOS")
    assert {x.case: x.status for x in nhl}["Shootout"] == "RULES_UNRESOLVED"
    nfl = cb.exceptions_for("KXNFLGAME-26OCT04BUFNE-BUF")
    assert any("$0.50" in x.summary for x in nfl)
    assert cb.exceptions_for("KXHIGHNY-26SEP30-T70") is None and cb.exceptions_for(None) is None


def test_the_register_fee_rows_match_the_routing():
    from edge_lab import fee_schedules as fs

    for series in ("KXNFLGAME", "KXNHLGAME", "KXMVECROSSCATEGORY"):
        assert isinstance(fs.schedule_for("kalshi", series), fs.UnsupportedFeeSchedule), series
    fee_items = {b.blocker_id: b.status for b in cb.BLOCKERS if b.blocker_id.startswith("FEE_")}
    assert set(fee_items.values()) == {cb.Status.FEE_UNSUPPORTED}
