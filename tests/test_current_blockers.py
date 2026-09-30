"""The current-blocker register is the one register; its document's table is generated from it (PR C, R1)."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from edge_lab import current_blockers as cb

DOC = Path(__file__).resolve().parents[1] / "docs" / "research" / "CURRENT_BLOCKERS.md"
NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def test_the_documents_register_block_is_generated_from_the_module():
    text = DOC.read_text(encoding="utf-8").replace("\r\n", "\n")
    start, end = text.index(cb.MARKDOWN_START), text.index(cb.MARKDOWN_END) + len(cb.MARKDOWN_END)
    assert text[start:end] == cb.render_markdown(), (
        "regenerate: PYTHONPATH=src python -c \"from edge_lab import current_blockers as c; print(c.render_markdown())\"")
    assert f"Last reconciled: {cb.LAST_RECONCILED}" in text
    for b in cb.BLOCKERS:
        assert f"| {b.blocker_id} | {b.status.value} |" in text


def test_render_is_deterministic_and_names_the_next_item():
    assert cb.render_markdown() == cb.render_markdown()
    assert "**Next** (as of 2026-09-30): ROUTINE_OFFHOST_BACKUP" in cb.render_markdown()
    assert "no open item" in cb.render_markdown(tuple(b for b in cb.BLOCKERS if b.status is cb.Status.RECORDED))


def test_the_register_is_consistent_and_every_item_has_a_source_and_resolver():
    assert cb.validate() == []
    for b in cb.BLOCKERS:
        assert b.sources and b.resolver_detail and b.trigger and b.verified and b.unknown
    bad = replace(cb.BLOCKERS[0], sources=())
    assert cb.validate((bad, bad))  # duplicate ids and no source


def test_owner_actions_and_owner_approvals_are_kept_apart():
    approvals = {b.blocker_id for b in cb.BLOCKERS if b.owner is cb.OwnerRole.APPROVAL}
    actions = {b.blocker_id for b in cb.BLOCKERS if b.owner is cb.OwnerRole.ACTION}
    assert {"KALSHI_MESSAGE_REV2", "DATA_RIGHTS", "NHL_READ_TIME_GAP", "EXP002_FREEZE_REVIEW"} <= approvals
    assert actions == {"ROUTINE_OFFHOST_BACKUP"}  # a routine is an action, not an approval
    assert cb.BLOCKERS[[b.blocker_id for b in cb.BLOCKERS].index("KALSHI_MESSAGE_REV2")].status is cb.Status.NOT_SENT


def test_next_blocker_is_the_soonest_dated_open_item_and_recorded_items_are_not_open():
    assert cb.next_blocker(NOW).blocker_id == "ROUTINE_OFFHOST_BACKUP"
    undated = tuple(replace(b, due_utc=None) for b in cb.BLOCKERS)
    assert cb.next_blocker(NOW, undated).owner is not cb.OwnerRole.NONE
    recorded = tuple(b for b in cb.BLOCKERS if b.status is cb.Status.RECORDED)
    assert recorded and cb.next_blocker(NOW, recorded) is None
    assert all(b.status is not cb.Status.RECORDED for b in cb.open_blockers())


def test_staleness_after_fourteen_days_and_when_overdue():
    b = next(x for x in cb.BLOCKERS if x.blocker_id == "NHL_SHOOTOUT_TIE")  # no due date
    assert not cb.is_stale(b, NOW) and not cb.is_overdue(b, NOW)
    assert cb.is_stale(b, datetime(2026, 10, 20, tzinfo=timezone.utc))
    routine = next(x for x in cb.BLOCKERS if x.blocker_id == "ROUTINE_OFFHOST_BACKUP")  # due 2026-10-03
    later = datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert cb.is_overdue(routine, later) and cb.is_stale(routine, later) and not cb.is_overdue(routine, NOW)
    recorded = next(x for x in cb.BLOCKERS if x.status is cb.Status.RECORDED)
    assert not cb.is_overdue(replace(recorded, due_utc="2026-10-01T00:00:00+00:00"), later)  # closed items never


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
