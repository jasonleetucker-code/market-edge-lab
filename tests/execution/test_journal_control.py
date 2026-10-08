"""Control events and orchestrator records in the execution journal (#160 package K). FIXTURE only.

They are ordinary hash-chained rows of `events`: no schema change, so a store written before this package opens
and verifies unchanged, and `verify_chain` covers every control row.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import test_journal_fixtures as f
from edge_lab.execution import control as c
from edge_lab.execution import model as m
from edge_lab.execution.journal import (CONTROL_EVENT_KIND, SCHEMA_VERSION, ExecutionJournal, JournalCorrupt)

NOW = f.NOW
OTHER = m.AccountScope(m.Environment.FIXTURE, "other-acct")


def at(minutes: int = 0) -> str:
    return (NOW + timedelta(minutes=minutes)).isoformat()


EVENTS = (
    c.Started(at(0)),
    c.ReconciliationObserved(c.Reconciliation.COMPLETE, at(1), "fixture"),
    c.IncidentRaised("lifecycle:abc.1", "quarantined", at(2)),
    c.IncidentAcknowledged("lifecycle:abc.1", "owner", at(3)),
    c.ArmAccepted(c.Mode.BOUNDED_AUTO, "owner", ("x",), "a" * 64, at(4), "b" * 64),
    c.ArmRefused(c.Mode.SHADOW, "owner", ("RECONCILIATION_NOT_COMPLETE: PARTIAL",), at(5)),
    c.Disarm("owner", "shutdown", at(6)),
    c.SetLatch(c.LatchScope.MARKET, "kxtest-1", "manual", at(7)),
    c.ClearLatch(c.LatchScope.MARKET, "KXTEST-1", "owner", at(8)),
    c.CloseoutAuthorized(c.LatchScope.GLOBAL, "*", "owner", at(9), at(30)),
)


@pytest.fixture
def journal(tmp_path: Path):
    with ExecutionJournal.open(tmp_path / "k.execution.sqlite3") as j:
        yield j


def test_every_control_event_type_round_trips_in_order_per_scope(journal):
    seqs = [journal.append_control_event(f.SCOPE, e, now=NOW) for e in EVENTS]
    journal.append_control_event(OTHER, c.Started(at(0)), now=NOW)
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert journal.control_events(f.SCOPE) == EVENTS
    assert journal.control_events(OTHER) == (c.Started(at(0)),)
    assert journal.verify_chain().ok
    # The replayed state is the live state: boot over the stored events keeps latches and incidents.
    _, state = c.boot(f.SCOPE, journal.control_events(f.SCOPE), at_utc=at(40))
    assert state.mode is c.Mode.DISARMED


def test_records_round_trip_with_decimals_as_text_and_filter_by_type(journal):
    journal.append_control_record(f.SCOPE, "CYCLE", {"cycle": 1, "cash": Decimal("1.50")}, now=NOW)
    journal.append_control_record(f.SCOPE, "SIGNAL_ACCEPTED", {"signal_id": "s1"}, now=NOW)
    journal.append_control_record(OTHER, "CYCLE", {"cycle": 9}, now=NOW)
    records = journal.control_records(f.SCOPE)
    assert [(r.record_type, r.body) for r in records] == [("CYCLE", {"cycle": 1, "cash": "1.5"}),
                                                          ("SIGNAL_ACCEPTED", {"signal_id": "s1"})]
    assert [r.body for r in journal.control_records(f.SCOPE, "CYCLE")] == [{"cycle": 1, "cash": "1.5"}]
    assert records[0].at_utc == NOW.isoformat()
    assert journal.verify_chain().ok


@pytest.mark.parametrize("bad", ["cycle", "", "1CYCLE", "CYCLE-1", "X" * 65])
def test_record_types_are_upper_case_labels(journal, bad):
    with pytest.raises(ValueError):
        journal.append_control_record(f.SCOPE, bad, {}, now=NOW)


def test_refusals_write_nothing(journal):
    before = journal.verify_chain().events
    with pytest.raises(ValueError):
        journal.append_control_event(f.SCOPE, object(), now=NOW)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        journal.append_control_record(f.SCOPE, "CYCLE", {"x": 1.5}, now=NOW)  # a float is not canonical
    with pytest.raises(ValueError):
        journal.append_control_record(f.SCOPE, "CYCLE", {}, now=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        journal.append_control_record("FIXTURE:x:primary", "CYCLE", {}, now=NOW)  # type: ignore[arg-type]
    assert journal.verify_chain().events == before


def test_an_altered_control_row_breaks_the_chain_and_a_malformed_one_does_not_decode(journal):
    journal.append_control_event(f.SCOPE, EVENTS[0], now=NOW)
    seq = journal.append_control_event(f.SCOPE, EVENTS[1], now=NOW)
    conn = journal._conn  # test-only tampering, outside the journal's API
    conn.execute("DROP TRIGGER events_no_update")
    body = json.loads(conn.execute("SELECT body_json FROM events WHERE seq = ?", (seq,)).fetchone()[0])
    body["fields"]["status"] = "NOT_A_STATUS"
    conn.execute("UPDATE events SET body_json = ? WHERE seq = ?", (json.dumps(body), seq))
    assert not journal.verify_chain().ok
    with pytest.raises(JournalCorrupt):
        journal.control_events(f.SCOPE)


def test_no_schema_change(journal):
    assert SCHEMA_VERSION == 1 and CONTROL_EVENT_KIND == "CONTROL_EVENT"
    tables = {r[0] for r in journal._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert len(tables) == 9
