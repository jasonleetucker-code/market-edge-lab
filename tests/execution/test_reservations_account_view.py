"""#160 package I review: the public read accessors of the reservation authority. FIXTURE only; no network."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

import test_journal_fixtures as f
from edge_lab.execution import model as m
from edge_lab.execution.journal import ExecutionJournal
from edge_lab.execution.reservations import AccountView, ReservationAuthority

YES = m.Side.YES


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "exec.execution.sqlite3"


def test_account_view_pairs_the_latest_snapshot_with_the_reservations_held_then(path):
    journal, token = f.ready(path, positions={(f.MARKET, YES): Decimal("10")})
    f.prepare(journal, f.entry("EXP-TEST:a"), token)
    f.prepare(journal, f.reduction("EXP-TEST:exit-a", quantity="3"), token)
    view = journal.reservations.account_view(f.SCOPE)
    assert isinstance(view, AccountView) and view.scope_key == f.SCOPE.key()
    assert view.snapshot == journal.reservations.latest_snapshot(f.SCOPE) and view.snapshot_revision == 1
    assert list(view.held) == journal.reservations.held_reservations(f.SCOPE) and len(view.held) == 2
    journal.close()


def test_account_view_without_a_snapshot(path):
    journal = ExecutionJournal.open(path)
    view = journal.reservations.account_view(f.SCOPE)
    assert (view.snapshot, view.snapshot_revision, view.held) == (None, None, ())
    journal.close()


def test_inventory_for_is_the_rule_reserve_uses(path):
    journal, token = f.ready(path, positions={(f.MARKET, YES): Decimal("10")})
    f.prepare(journal, f.reduction("EXP-TEST:exit-a", quantity="6"), token)
    view = journal.reservations.account_view(f.SCOPE)
    from decimal import localcontext

    from edge_lab.execution.reservations import _exact_context

    with localcontext(_exact_context()):
        assert ReservationAuthority.inventory_for(view.snapshot, list(view.held), f.MARKET, YES) == (Decimal("4"), None)
    assert not journal.reservations.evaluate(f.reduction("EXP-TEST:exit-b", quantity="5"), f.NOW,
                                             snapshot_max_age=f.MAX_AGE).allowed
    assert journal.reservations.evaluate(f.reduction("EXP-TEST:exit-c", quantity="4"), f.NOW,
                                         snapshot_max_age=f.MAX_AGE).allowed
    journal.close()
