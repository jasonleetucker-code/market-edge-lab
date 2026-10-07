"""#160 package I: `project_account` builds the gate's projection from a real FIXTURE journal, and the gate agrees
with `reservations` (the transactional cash and inventory authority) on the same state."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import test_journal_fixtures as f
from edge_lab.execution import model as m
from edge_lab.execution import risk_gate as g
from edge_lab.execution.reservations import ExternalOrder, ExternalOrigin, ReceiptKind as K
from edge_lab.execution.risk_gate import CommitmentOrigin, MarketKeys, Reason as R
from edge_lab.execution_ticket import ObligationState as S, TicketLimits
from edge_lab.risk import RiskPolicy

NOW = f.NOW
YES, NO = m.Side.YES, m.Side.NO
KEYS = {f.MARKET: MarketKeys("KXTEST-26OCT07", "test-cluster")}
POLICY = RiskPolicy("risk-v1", reserve_floor=Decimal("0"), max_position_risk=Decimal("50"),
                    max_event_risk=Decimal("50"), max_cluster_risk=Decimal("50"), max_portfolio_risk=Decimal("90"),
                    daily_loss_limit=Decimal("90"), weekly_loss_limit=Decimal("90"), max_drawdown=Decimal("90"))
LIMITS = g.GateLimits("limits-v1", "risk-v1", "test-fixture-only", Decimal("100"), Decimal("0.05"),
                      timedelta(minutes=5), timedelta(minutes=5), Decimal("90"), Decimal("90"))
TICKET = TicketLimits(max_book_age=timedelta(seconds=30), max_order_state_age=timedelta(minutes=5),
                      max_orders_per_window=10, order_window=timedelta(hours=1), market_cooldown=timedelta(0))


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "exec.execution.sqlite3"


def _project(journal, intents=()):
    snap = journal.reservations.latest_snapshot(f.SCOPE)
    held = journal.reservations.held_reservations(f.SCOPE)
    return g.project_account(f.SCOPE.key(), snap, held, projection_id=f"{f.SCOPE.key()}#{snap.revision if snap else 0}",
                             intents={i.intent_key: i for i in intents}, market_keys=KEYS, pnl_history=(),
                             pnl_history_since_utc=(NOW - timedelta(days=30)).isoformat(), order_history=())


def _gate(intent, projection):
    return g.evaluate(intent, account=projection, market=None, policy=POLICY, limits=LIMITS, ticket_limits=TICKET,
                      evidence=None, now=NOW)


def test_the_gate_and_reservations_require_the_same_cash(path):
    external = ExternalOrder("manual-1", ExternalOrigin.MANUAL, f.MARKET, NO, m.Action.BUY, Decimal("1"),
                             Decimal("0.25"))
    journal, token = f.ready(path, externals=(external,))
    first = f.entry("EXP-TEST:a")
    view_a = journal.reservations.reservation(f.prepare(journal, first, token).reservation_id)
    candidate = f.entry("EXP-TEST:b", quantity="2", cost="1.00")

    projection = _project(journal, (first,))
    local, ext = projection.commitments
    assert (local.origin, local.state, local.kind, local.cash_worst_case, local.risk_worst_case, local.strategy_id,
            local.event_key) == (CommitmentOrigin.LOCAL, S.OUTSTANDING, m.IntentKind.ENTRY, Decimal("4.60"),
                                 Decimal("4.60"), "synthetic-demo", "KXTEST-26OCT07")
    assert (ext.origin, ext.cash_worst_case, ext.risk_worst_case, ext.strategy_id) == \
        (CommitmentOrigin.EXTERNAL, Decimal("0.25"), Decimal("1"), None)
    owner = journal.reservations.evaluate(candidate, NOW, snapshot_max_age=f.MAX_AGE)
    assert _gate(candidate, projection).cash_required == owner.cash_required == Decimal("5.85")

    # Once the venue lists the order as holding its cash, both count only the unreflected residual.
    f.snapshot(journal, 2, externals=(external,), attributed=(f.attributed(view_a, unreflected="0.10"),))
    projection = _project(journal, (first,))
    assert projection.commitments[0].cash_worst_case == Decimal("0.10")
    assert projection.commitments[0].risk_worst_case == Decimal("4.60")  # its risk is still the full cost
    owner = journal.reservations.evaluate(candidate, NOW, snapshot_max_age=f.MAX_AGE)
    assert _gate(candidate, projection).cash_required == owner.cash_required == Decimal("1.35")
    journal.close()


def test_inventory_is_the_reservation_authoritys_rule(path):
    journal, token = f.ready(path, positions={(f.MARKET, YES): Decimal("10")})
    f.prepare(journal, f.reduction("EXP-TEST:exit-a", quantity="6"), token)
    projection = _project(journal)
    assert [(i.market_ticker, i.side, i.available) for i in projection.inventory] == [(f.MARKET, YES, Decimal("4"))]
    too_many, fits = f.reduction("EXP-TEST:exit-b", quantity="5"), f.reduction("EXP-TEST:exit-c", quantity="4")
    assert R.INVENTORY_INSUFFICIENT in _gate(too_many, projection).codes()
    assert R.INVENTORY_INSUFFICIENT not in _gate(fits, projection).codes()
    owner = journal.reservations.evaluate(too_many, NOW, snapshot_max_age=f.MAX_AGE)
    assert not owner.allowed and any(r.startswith("INSUFFICIENT_INVENTORY") for r in owner.reasons)
    assert journal.reservations.evaluate(fits, NOW, snapshot_max_age=f.MAX_AGE).allowed
    journal.close()


def test_positions_carry_market_keys_and_a_held_opposite_side_forbids_a_flip(path):
    journal, _ = f.ready(path, positions={(f.MARKET, NO): Decimal("3"), ("KXUNMAPPED-1", YES): Decimal("2"),
                                          (f.MARKET, YES): Decimal("0")})
    projection = _project(journal)
    assert [(p.market_ticker, p.side, p.quantity, p.event_key) for p in projection.positions] == [
        ("KXTEST-26OCT07-T50", NO, Decimal("3"), "KXTEST-26OCT07"), ("KXUNMAPPED-1", YES, Decimal("2"), None)]
    assert R.FLIP_FORBIDDEN in _gate(f.entry("EXP-TEST:flip"), projection).codes()
    journal.close()


def test_a_quarantined_reservation_is_unknown_and_blocks_new_risk(path):
    journal, token = f.ready(path)
    rid = f.prepare(journal, f.entry("EXP-TEST:a"), token).reservation_id
    journal.mark_sent(rid, now=NOW)
    journal.reservations.record_fill(rid, Decimal("11"), NOW, receipt_id=f.receipt(journal, "r-1", K.FILL, rid))
    projection = _project(journal)
    (c,) = projection.commitments
    assert c.quarantined and c.cash_worst_case is None and c.risk_worst_case is None and c.state is S.UNKNOWN
    d = _gate(f.entry("EXP-TEST:b"), projection)
    assert {R.RECONCILIATION_UNHEALTHY, R.CASH_CAPACITY_INSUFFICIENT} <= set(d.codes()) and not d.allowed
    journal.close()


def test_no_snapshot_means_nothing_is_known(path):
    from edge_lab.execution.journal import ExecutionJournal

    journal = ExecutionJournal.open(path)
    projection = _project(journal)
    assert (projection.cash, projection.positions, projection.consistent, projection.external_orders_known,
            projection.observed_at_utc) == (None, None, False, False, None)
    d = _gate(f.entry(), projection)
    assert {R.ACCOUNT_SNAPSHOT_STALE, R.RECONCILIATION_UNHEALTHY, R.CASH_UNKNOWN, R.POSITIONS_UNKNOWN} <= set(d.codes())
    journal.close()


def test_unlisted_external_orders_are_unknown(path):
    journal, _ = f.ready(path)
    f.snapshot(journal, 2, externals=None)
    projection = _project(journal)
    assert not projection.external_orders_known
    d = _gate(f.entry(), projection)
    assert R.RECONCILIATION_UNHEALTHY in d.codes()
    d = _gate(f.reduction(), replace(projection, inventory=()))
    assert R.INVENTORY_UNKNOWN in d.codes()
    journal.close()


def test_the_builder_refuses_another_scopes_state(path):
    journal, _ = f.ready(path)
    snap = journal.reservations.latest_snapshot(f.SCOPE)
    with pytest.raises(ValueError):
        g.project_account("FIXTURE:other:primary", snap, (), projection_id="p", intents={}, market_keys={},
                          pnl_history=(), pnl_history_since_utc=None, order_history=())
    journal.close()
