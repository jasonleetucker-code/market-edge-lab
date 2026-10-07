"""The private execution journal (#160 package D): store, intents, approvals, attempts, receipts, audit chain,
failure mapping and restart replay. FIXTURE only; nothing here touches a network."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

import test_journal_fixtures as f
from edge_lab.execution import model as m
from edge_lab.execution.journal import (AttemptRefused, AttemptState, ApprovalRefused, ExecutionJournal,
                                        IntentConflict, JournalBusy, JournalCorrupt, JournalUnavailable,
                                        ReceiptOutcome, UnknownSchema)
from edge_lab.execution.reservations import InvalidTransition, StaleFence
from edge_lab.execution_ticket import ObligationState

NOW = f.NOW


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "exec.execution.sqlite3"


@pytest.fixture
def ready(path: Path):
    journal, token = f.ready(path)
    yield journal, token
    journal.close()


def _receipt(journal: ExecutionJournal, receipt_id: str, payload: str = '{"ok":true}', **kw):
    return journal.record_receipt(receipt_id=receipt_id, kind=kw.pop("kind", "ORDER_RESPONSE"),
                                  source=kw.pop("source", "fixture-transport"), payload_json=payload,
                                  received_at=kw.pop("at", NOW), **kw)


# ---------------------------------------------------------------- the store


def test_open_sets_wal_full_sync_foreign_keys_busy_timeout_and_schema_version(path):
    with ExecutionJournal.open(path, busy_timeout_ms=300) as journal:
        conn = journal._conn
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 300
        assert dict(conn.execute("SELECT key, value FROM schema_meta")) == {
            "store_kind": "edge-lab-execution-journal", "schema_version": "1"}
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        assert len(tables) == 9
        for table in tables:  # no REAL (float) column anywhere: money and quantities are exact text
            for column in conn.execute(f"SELECT name, type FROM pragma_table_info('{table}')"):
                assert column[1] in ("TEXT", "INTEGER"), (table, column)
    with ExecutionJournal.open(path) as again:  # reopening an existing store is fine
        assert again.verify_chain().ok


@pytest.mark.parametrize("name", ["research.sqlite3", "edge_lab.db", "exec.sqlite3", ".execution.sqlite3",
                                  "exec.execution.sqlite3.bak", ":memory:"])
def test_only_an_execution_store_file_name_is_accepted(tmp_path, name):
    with pytest.raises(UnknownSchema):
        ExecutionJournal.open(tmp_path / name)
    assert not (tmp_path / name).exists()


def test_a_research_store_renamed_to_the_execution_suffix_is_refused(tmp_path):
    p = tmp_path / "research.execution.sqlite3"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE snapshots (id INTEGER PRIMARY KEY, payload TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(UnknownSchema, match="no schema_meta"):
        ExecutionJournal.open(p)


@pytest.mark.parametrize("key,value,match", [("schema_version", "2", "newer"), ("schema_version", "0", "unknown"),
                                             ("schema_version", "one", "unreadable"),
                                             ("store_kind", "edge-lab-research", "not")])
def test_an_unknown_or_newer_schema_is_refused(path, key, value, match):
    ExecutionJournal.open(path).close()
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER schema_meta_no_update")
    conn.execute("UPDATE schema_meta SET value = ? WHERE key = ?", (value, key))
    conn.commit()
    conn.close()
    with pytest.raises(UnknownSchema, match=match):
        ExecutionJournal.open(path)


def test_a_damaged_file_is_refused_as_corrupt(path):
    path.write_bytes(b"this is not a sqlite database at all" * 200)
    with pytest.raises(JournalCorrupt):
        ExecutionJournal.open(path)


def test_a_store_missing_an_append_only_trigger_is_refused(path):
    ExecutionJournal.open(path).close()
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER receipts_no_update")
    conn.commit()
    conn.close()
    with pytest.raises(UnknownSchema, match="receipts_no_update"):
        ExecutionJournal.open(path)


def test_a_rewritten_projection_is_detected(ready, path):
    journal, token = ready
    attempt = f.prepare(journal, f.entry(), token)
    assert journal.verify_chain().ok
    conn = sqlite3.connect(path)
    conn.execute("UPDATE reservations SET state = 'RELEASED', release_reason = 'CANCEL_CONFIRMED'")
    conn.execute("UPDATE attempts SET state = 'REJECTED'")
    conn.commit()
    conn.close()
    problems = journal.verify_chain().problems
    assert any(p.startswith(f"PROJECTION_DIVERGED: attempt {attempt.attempt_id}") for p in problems), problems
    assert any(p.startswith("PROJECTION_DIVERGED: reservation") for p in problems), problems


def test_a_store_missing_a_table_is_refused(path):
    ExecutionJournal.open(path).close()
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE egress_lease")
    conn.commit()
    conn.close()
    with pytest.raises(UnknownSchema, match="missing"):
        ExecutionJournal.open(path)


# ---------------------------------------------------------------- business intent


def test_same_key_same_digest_is_idempotent_and_creation_time_is_not_identity(path):
    with ExecutionJournal.open(path) as journal:
        first = journal.record_intent(f.entry(), NOW)
        again = journal.record_intent(f.entry(), NOW + timedelta(hours=3))
        assert first.created and not again.created and first.digest == again.digest
        assert f.counts(path)["intents"] == 1 and f.counts(path)["events"] == 1
        row = journal._conn.execute("SELECT digest, scope_key, canonical_json, recorded_at_utc FROM intents").fetchone()
        assert row[0] == f.entry().digest() and row[1] == f.SCOPE.key() and row[2] == f.entry().canonical()
        assert row[3] == m.utc_text(NOW)  # the first record's time is kept


def test_same_key_different_payload_conflicts_and_changes_nothing(path):
    with ExecutionJournal.open(path) as journal:
        journal.record_intent(f.entry(), NOW)
        before = f.counts(path)
        with pytest.raises(IntentConflict):
            journal.record_intent(f.entry(quantity="11", cost="5.00"), NOW)
        assert f.counts(path) == before
        stored = journal._conn.execute("SELECT digest FROM intents").fetchone()[0]
        assert stored == f.entry().digest()


def test_a_conflicting_intent_in_prepare_commits_nothing_and_leaves_the_approval_unused(ready, path):
    journal, token = ready
    journal.record_intent(f.entry(), NOW)
    changed = f.entry(price="0.43", cost="4.70")
    before = f.counts(path)
    with pytest.raises(IntentConflict):
        f.prepare(journal, changed, token, nonce="n-1")
    assert f.counts(path) == before
    assert f.prepare(journal, f.entry(), token, nonce="n-1").state is AttemptState.PENDING_EGRESS  # nonce unused


# ---------------------------------------------------------------- approvals


def test_approval_nonce_reuse_is_refused(ready, path):
    journal, token = ready
    intent = f.entry()
    journal.consume_approval(f.grant(intent, "n-1"), intent, NOW)
    before = f.counts(path)
    with pytest.raises(ApprovalRefused, match="APPROVAL_NONCE_REUSED"):
        journal.consume_approval(f.grant(intent, "n-1"), intent, NOW)
    with pytest.raises(ApprovalRefused, match="APPROVAL_NONCE_REUSED"):
        f.prepare(journal, intent, token, nonce="n-1")
    assert f.counts(path) == before


@pytest.mark.parametrize("make,problem", [
    (lambda i: f.grant(i, at=NOW - timedelta(hours=2), ttl=timedelta(minutes=30)), "APPROVAL_EXPIRED"),
    (lambda i: f.grant(f.entry(quantity="9", cost="4.00")), "APPROVAL_DIGEST_MISMATCH"),
    (lambda i: m.ApprovalGrant(intent_digest=i.digest(), scope_key="FIXTURE:other-acct:primary",
                               method=m.ApprovalMethod.HUMAN, approver_ref="owner",
                               approved_at_utc=(NOW - timedelta(minutes=1)).isoformat(),
                               expires_at_utc=(NOW + timedelta(minutes=5)).isoformat(), nonce="n-x"),
     "APPROVAL_SCOPE_MISMATCH"),
    (lambda i: f.grant(i, at=NOW + timedelta(hours=1)), "APPROVAL_FROM_FUTURE"),
])
def test_an_expired_or_mismatched_approval_commits_nothing(ready, path, make, problem):
    journal, token = ready
    intent = f.entry()
    before = f.counts(path)
    with pytest.raises(ApprovalRefused, match=problem):
        journal.prepare_attempt(intent, make(intent), fence_token=token, request_digest=f.request_digest(),
                                snapshot_max_age=f.MAX_AGE, now=NOW)
    assert f.counts(path) == before


# ---------------------------------------------------------------- prepare before egress and attempt states


def test_prepare_commits_intent_approval_reservation_and_pending_attempt_together(ready, path):
    journal, token = ready
    intent = f.entry()
    attempt = f.prepare(journal, intent, token, nonce="n-1")
    assert attempt.state is AttemptState.PENDING_EGRESS and attempt.attempt_no == 1
    assert attempt.client_order_id == intent.client_order_id() and attempt.fence_token == token
    assert attempt.request_digest == f.request_digest(intent.intent_key) and attempt.worker_id == f.WORKER
    assert attempt.approval_nonce == "n-1" and attempt.created_at_utc == m.utc_text(NOW)
    c = f.counts(path)
    assert (c["intents"], c["approvals"], c["attempts"], c["reservations"]) == (1, 1, 1, 1)
    r = journal.reservations.reservation(attempt.reservation_id)
    assert r.state is ObligationState.OUTSTANDING and r.cash_worst_case == intent.max_total_cost
    assert journal._conn.execute("SELECT attempt_id FROM approvals").fetchone()[0] == attempt.attempt_id
    assert journal.verify_chain().ok


def test_a_reservation_refusal_commits_nothing(path):
    journal, token = f.ready(path, cash="1.00")
    before = f.counts(path)
    with pytest.raises(Exception, match="INSUFFICIENT_CASH"):
        f.prepare(journal, f.entry(), token)
    assert f.counts(path) == before
    journal.close()


def test_an_unauthorized_environment_is_refused_before_anything_commits(ready, path):
    journal, token = ready
    demo = f.entry(scope=m.AccountScope(m.Environment.DEMO, "fixture-acct"))
    before = f.counts(path)
    with pytest.raises(AttemptRefused, match="ENVIRONMENT_NOT_AUTHORIZED"):
        f.prepare(journal, demo, token)
    assert f.counts(path) == before


def test_happy_path_and_evidence_backed_transitions(ready):
    journal, token = ready
    attempt = f.prepare(journal, f.entry(), token)
    with pytest.raises(InvalidTransition):
        journal.mark_acknowledged(attempt.attempt_id, provider_order_id="p-1", receipt_id="r-1", now=NOW)  # not SENT
    journal.mark_sent(attempt.attempt_id, now=NOW)
    with pytest.raises(InvalidTransition, match="RECEIPT_NOT_RECORDED"):
        journal.mark_acknowledged(attempt.attempt_id, provider_order_id="p-1", receipt_id="r-1", now=NOW)
    _receipt(journal, "r-1", '{"order":{"id":"p-1"}}', provider_id="p-1", attempt_id=attempt.attempt_id)
    done = journal.mark_acknowledged(attempt.attempt_id, provider_order_id="p-1", receipt_id="r-1", now=NOW)
    assert done.state is AttemptState.ACKNOWLEDGED and done.provider_order_id == "p-1"
    assert journal.reservations.reservation(attempt.reservation_id).state is ObligationState.OUTSTANDING
    assert journal.non_terminal_attempts() == []
    with pytest.raises(InvalidTransition):
        journal.mark_rejected(attempt.attempt_id, receipt_id="r-1", now=NOW)  # terminal


def test_no_new_attempt_while_an_earlier_one_could_exist(ready):
    journal, token = ready
    intent = f.entry()
    first = f.prepare(journal, intent, token, nonce="n-1")
    with pytest.raises(AttemptRefused, match="PENDING_EGRESS"):
        f.prepare(journal, intent, token, nonce="n-2")
    journal.mark_sent(first.attempt_id, now=NOW)
    with pytest.raises(AttemptRefused, match="SENT"):
        f.prepare(journal, intent, token, nonce="n-2")
    _receipt(journal, "r-ack", provider_id="p-1")
    journal.mark_acknowledged(first.attempt_id, provider_order_id="p-1", receipt_id="r-ack", now=NOW)
    with pytest.raises(AttemptRefused, match="ACKNOWLEDGED"):  # the order exists: never a second one
        f.prepare(journal, intent, token, nonce="n-2")


def test_a_rejected_attempt_releases_and_allows_a_new_approved_attempt(ready):
    journal, token = ready
    intent = f.entry()
    first = f.prepare(journal, intent, token, nonce="n-1")
    journal.mark_sent(first.attempt_id, now=NOW)
    _receipt(journal, "r-rej", '{"error":"insufficient_balance"}')
    journal.mark_rejected(first.attempt_id, receipt_id="r-rej", now=NOW)
    assert journal.reservations.reservation(first.reservation_id).state is ObligationState.RELEASED
    with pytest.raises(ApprovalRefused, match="NONCE_REUSED"):
        f.prepare(journal, intent, token, nonce="n-1")
    second = f.prepare(journal, intent, token, nonce="n-2")
    assert second.attempt_no == 2 and second.client_order_id == first.client_order_id
    assert second.attempt_id != first.attempt_id


def test_an_ambiguous_timeout_keeps_the_reservation_and_blocks_until_reconciled(ready):
    journal, token = ready
    intent = f.entry()
    first = f.prepare(journal, intent, token, nonce="n-1")
    journal.mark_sent(first.attempt_id, now=NOW)
    unknown = journal.mark_outcome_unknown(first.attempt_id, reason="read timeout after egress", now=NOW)
    assert unknown.state is AttemptState.OUTCOME_UNKNOWN
    assert journal.reservations.reservation(first.reservation_id).state is ObligationState.UNKNOWN
    with pytest.raises(AttemptRefused, match="OUTCOME_UNKNOWN"):
        f.prepare(journal, intent, token, nonce="n-2")
    with pytest.raises(InvalidTransition, match="only reconcile_attempt"):
        journal.mark_rejected(first.attempt_id, receipt_id="x", now=NOW)
    _receipt(journal, "lookup-1", '{"orders":[]}', kind="ORDER_LOOKUP")
    absent = journal.reconcile_attempt(first.attempt_id, AttemptState.ABSENT, receipt_id="lookup-1", now=NOW)
    assert absent.state is AttemptState.ABSENT and absent.state_reason == "RECONCILED"
    assert journal.reservations.reservation(first.reservation_id).state is ObligationState.RELEASED
    assert f.prepare(journal, intent, token, nonce="n-2").attempt_no == 2


def test_reconciling_an_unknown_attempt_as_found_keeps_it_reserved_and_blocks_retries(ready):
    journal, token = ready
    intent = f.entry()
    first = f.prepare(journal, intent, token, nonce="n-1")
    journal.mark_outcome_unknown(first.attempt_id, reason="connection reset during send", now=NOW)  # from PENDING
    _receipt(journal, "lookup-1", '{"orders":[{"id":"p-9"}]}')
    with pytest.raises(ValueError):
        journal.reconcile_attempt(first.attempt_id, AttemptState.ACKNOWLEDGED, receipt_id="lookup-1", now=NOW)
    found = journal.reconcile_attempt(first.attempt_id, AttemptState.ACKNOWLEDGED, receipt_id="lookup-1", now=NOW,
                                      provider_order_id="p-9")
    assert found.state is AttemptState.ACKNOWLEDGED and found.provider_order_id == "p-9"
    assert journal.reservations.reservation(first.reservation_id).state is ObligationState.OUTSTANDING
    with pytest.raises(AttemptRefused):
        f.prepare(journal, intent, token, nonce="n-2")


# ---------------------------------------------------------------- receipts


def test_duplicate_receipt_is_idempotent_and_a_different_payload_is_a_conflict_that_never_overwrites(ready, path):
    journal, _ = ready
    original = _receipt(journal, "fill-77", '{"count":"3"}', provider_id="p-1", kind="FILL")
    assert original.outcome is ReceiptOutcome.RECORDED
    assert _receipt(journal, "fill-77", '{"count":"3"}', provider_id="p-1", kind="FILL").outcome is ReceiptOutcome.DUPLICATE
    assert f.counts(path)["receipts"] == 1
    altered = _receipt(journal, "fill-77", '{"count":"30"}', provider_id="p-1", kind="FILL")
    assert altered.outcome is ReceiptOutcome.CONFLICTING_DUPLICATE and altered.payload_sha256 != original.payload_sha256
    assert _receipt(journal, "fill-77", '{"count":"30"}', kind="FILL").outcome is ReceiptOutcome.DUPLICATE
    rows = journal.receipts("fill-77")
    assert [(r["status"], r["payload_json"]) for r in rows] == [("ORIGINAL", '{"count":"3"}'),
                                                                ("CONFLICTING_DUPLICATE", '{"count":"30"}')]
    assert rows[0]["payload_sha256"] == m.sha256_text('{"count":"3"}') and rows[0]["provider_id"] == "p-1"
    with pytest.raises(InvalidTransition, match="RECEIPT_CONFLICTED"):
        journal._require_receipt(journal._conn, "fill-77")
    with pytest.raises(ValueError):
        _receipt(journal, "bad", "{not json")
    assert journal.verify_chain().ok


def test_receipts_and_events_are_append_only(ready, path):
    journal, token = ready
    f.prepare(journal, f.entry(), token)  # every append-only table has a row (a trigger fires per row)
    _receipt(journal, "r-1")
    conn = sqlite3.connect(path)
    for sql in ("UPDATE receipts SET payload_json = '{}'", "DELETE FROM receipts", "UPDATE events SET kind = 'X'",
                "DELETE FROM events", "UPDATE intents SET digest = digest", "DELETE FROM approvals",
                "UPDATE account_snapshots SET cash = '1000000'"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(sql)
    conn.close()


def test_an_altered_receipt_payload_in_the_file_is_detected(ready, path):
    journal, _ = ready
    _receipt(journal, "r-1", '{"count":"3"}')
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER receipts_no_update")
    conn.execute("UPDATE receipts SET payload_json = '{\"count\":\"300\"}'")
    conn.commit()
    conn.close()
    report = journal.verify_chain()
    assert not report.ok and any(p.startswith("RECEIPT_ALTERED") for p in report.problems)


# ---------------------------------------------------------------- audit chain and corrupt records


def test_every_change_is_chained_and_verifies(ready):
    journal, token = ready
    attempt = f.prepare(journal, f.entry(), token)
    journal.mark_sent(attempt.attempt_id, now=NOW)
    report = journal.verify_chain()
    assert report.ok and report.events >= 7, report
    kinds = [r[0] for r in journal._conn.execute("SELECT kind FROM events ORDER BY seq")]
    assert kinds[:2] == ["SNAPSHOT_RECORDED", "LEASE_ACQUIRED"]
    assert {"INTENT_RECORDED", "APPROVAL_CONSUMED", "RESERVATION_CREATED", "ATTEMPT_PREPARED", "ATTEMPT_STATE"} <= set(kinds)


@pytest.mark.parametrize("tamper,problem", [
    ("UPDATE events SET body_json = '{\"forged\":true}' WHERE seq = 2", "EVENT_ALTERED"),
    ("UPDATE events SET prev_hash = '" + "1" * 64 + "' WHERE seq = 3", "EVENT_LINK_BROKEN"),
    ("DELETE FROM events WHERE seq = 2", "EVENT_GAP"),
])
def test_a_tampered_event_breaks_the_chain(ready, path, tamper, problem):
    journal, token = ready
    f.prepare(journal, f.entry(), token)
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER events_no_update")
    conn.execute("DROP TRIGGER events_no_remove")
    conn.execute(tamper)
    conn.commit()
    conn.close()
    report = journal.verify_chain()
    assert not report.ok and any(p.startswith(problem) for p in report.problems), report


def test_a_rewritten_intent_is_detected_even_when_its_digest_is_rewritten_too(ready, path):
    journal, _ = ready
    journal.record_intent(f.entry(), NOW)
    forged = f.entry(quantity="100", cost="50")
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER intents_no_update")
    conn.execute("UPDATE intents SET canonical_json = ?", (forged.canonical(),))
    conn.commit()
    report = journal.verify_chain()
    assert any(p.startswith("INTENT_ALTERED") for p in report.problems)
    conn.execute("UPDATE intents SET digest = ?", (forged.digest(),))
    conn.commit()
    conn.close()
    report = journal.verify_chain()
    assert any(p.startswith("INTENT_UNAUDITED") for p in report.problems), report


def test_a_corrupt_reservation_record_fails_closed_and_commits_nothing(ready, path):
    journal, token = ready
    first = f.prepare(journal, f.entry(), token)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE reservations SET cash_worst_case = 'four dollars'")
    conn.commit()
    conn.close()
    with pytest.raises(JournalCorrupt):
        journal.reservations.reservation(first.reservation_id)
    before = f.counts(path)
    with pytest.raises(JournalCorrupt):
        f.prepare(journal, f.entry("EXP-TEST:ticket-0002"), token)
    assert f.counts(path) == before


# ---------------------------------------------------------------- essential write failures


def test_disk_full_raises_and_commits_nothing(ready, path):
    journal, token = ready
    conn = journal._conn
    pages = conn.execute("PRAGMA page_count").fetchone()[0]
    conn.execute(f"PRAGMA max_page_count = {pages + 1}")
    before = f.counts(path)
    with pytest.raises(JournalUnavailable, match="full"):
        _receipt(journal, "big", '{"blob":"' + "x" * 200_000 + '"}')
    with pytest.raises(JournalUnavailable):
        journal.record_intent(f.entry(evidence=tuple(f"e-{i:05d}" + "y" * 200 for i in range(2000))), NOW)
    assert f.counts(path) == before
    conn.execute("PRAGMA max_page_count = 1073741823")
    assert f.prepare(journal, f.entry(), token).state is AttemptState.PENDING_EGRESS  # usable again
    assert journal.verify_chain().ok


def test_a_lock_timeout_raises_busy_and_commits_nothing(ready, path):
    journal, token = ready
    holder = sqlite3.connect(path, isolation_level=None, timeout=0.1)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(JournalBusy):
            journal.record_intent(f.entry(), NOW)
        with pytest.raises(JournalBusy):
            f.prepare(journal, f.entry(), token)
        with pytest.raises(JournalBusy):
            _receipt(journal, "r-1")
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert f.counts(path)["intents"] == 0
    assert f.prepare(journal, f.entry(), token).state is AttemptState.PENDING_EGRESS


def test_busy_is_a_kind_of_unavailable():
    assert issubclass(JournalBusy, JournalUnavailable) and issubclass(JournalCorrupt, JournalUnavailable)


# ---------------------------------------------------------------- kill points and restart replay


def _kill(path: Path, point: str, token: int) -> int:
    helper = Path(__file__).with_name("test_journal_fixtures.py")
    src = Path(__file__).resolve().parents[2] / "src"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(src), str(helper.parent)])}
    result = subprocess.run([sys.executable, str(helper), str(path), point, str(token)], env=env, capture_output=True,
                            text=True, timeout=120)
    return result.returncode


def test_kill_before_commit_leaves_nothing(path):
    journal, token = f.ready(path)
    journal.close()
    before = f.counts(path)
    assert _kill(path, "before_commit", token) == 17
    assert f.counts(path) == before
    with ExecutionJournal.open(path) as reopened:
        assert reopened.recover(NOW) == [] and reopened.verify_chain().ok
        assert f.prepare(reopened, f.entry(), token).state is AttemptState.PENDING_EGRESS  # the nonce was never used


def test_kill_after_commit_before_send_recovers_as_outcome_unknown(path):
    journal, token = f.ready(path)
    journal.close()
    assert _kill(path, "after_prepare", token) == 18
    with ExecutionJournal.open(path) as reopened:
        listed = reopened.recover(NOW)  # the lease is still live: it cannot know the worker died yet
        assert [a.state for a in listed] == [AttemptState.PENDING_EGRESS]
        later = NOW + f.TTL + timedelta(seconds=1)
        listed = reopened.recover(later)
        assert [a.state for a in listed] == [AttemptState.OUTCOME_UNKNOWN]
        assert listed[0].state_reason.startswith("FENCE_SUPERSEDED")
        r = reopened.reservations.reservation(listed[0].reservation_id)
        assert r.state is ObligationState.UNKNOWN  # still reserved
        token2 = reopened.reservations.acquire_lease(f.WORKER, f.TTL, later)
        with pytest.raises(AttemptRefused, match="OUTCOME_UNKNOWN"):
            f.prepare(reopened, f.entry(), token2, nonce="n-new", at=later)
        assert reopened.verify_chain().ok


def test_a_restarted_worker_taking_a_new_lease_quarantines_its_dead_attempts(path):
    journal, token = f.ready(path)
    journal.close()
    assert _kill(path, "after_sent", token) == 19
    with ExecutionJournal.open(path) as reopened:
        assert [a.state for a in reopened.non_terminal_attempts()] == [AttemptState.SENT]
        new_token = reopened.reservations.acquire_lease(f.WORKER, f.TTL, NOW)  # same worker id, new process
        assert new_token == token + 1
        assert [a.state for a in reopened.non_terminal_attempts()] == [AttemptState.OUTCOME_UNKNOWN]
        with pytest.raises(StaleFence):
            f.prepare(reopened, f.entry("EXP-TEST:ticket-0002"), token)
