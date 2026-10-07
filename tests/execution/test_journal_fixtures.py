"""Shared builders and out-of-process workers for the journal and reservation tests. It holds no tests.

The workers run in separate processes (a `subprocess` for kill points, a spawn-context `multiprocessing`
process for races). They receive file paths and plain strings, never a connection or an object.
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from edge_lab.execution import model as m
from edge_lab.execution.journal import ExecutionJournal, JournalError
from edge_lab.execution.reservations import CashBasis, ReservationError

UTC = timezone.utc
NOW = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
CENT = m.Grid(step=Decimal("0.01"), minimum=Decimal("0.01"), maximum=Decimal("0.99"))
WHOLE = m.Grid(step=Decimal("1"), minimum=Decimal("1"), maximum=Decimal("1000000"))
SCOPE = m.AccountScope(m.Environment.FIXTURE, "fixture-acct")
MARKET = "KXTEST-26OCT07-T50"
MAX_AGE = timedelta(minutes=5)
TTL = timedelta(minutes=10)
WORKER = "worker-a"


def entry(key: str = "EXP-TEST:ticket-0001", *, quantity: str = "10", price: str = "0.42", cost: str = "4.60",
          **kw) -> m.OrderIntent:
    base = dict(intent_key=key, strategy_id="synthetic-demo", strategy_version="v1", scope=SCOPE,
                market_ticker=MARKET, kind=m.IntentKind.ENTRY, side=m.Side.YES, action=m.Action.BUY,
                quantity=Decimal(quantity), limit_price=Decimal(price),
                time_in_force=m.TimeInForce.GOOD_TILL_CANCELED, max_total_cost=Decimal(cost),
                expires_at_utc=(NOW + timedelta(hours=1)).isoformat(), price_grid=CENT, quantity_grid=WHOLE,
                profile_version="kalshi-ordinary-v0", risk_policy_version="risk-v1",
                fee_schedule_version="kalshi-quadratic-taker-v1", reduce_only=False)
    base.update(kw)
    return m.OrderIntent(**base)


def reduction(key: str = "EXP-TEST:exit-0001", *, quantity: str = "5", price: str = "0.60", fee: str = "0.10",
              **kw) -> m.OrderIntent:
    return entry(key, quantity=quantity, price=price, cost=fee, kind=m.IntentKind.REDUCTION, action=m.Action.SELL,
                 reduce_only=True, **kw)


def grant(intent: m.OrderIntent, nonce: str | None = None, *, at: datetime = NOW,
          ttl: timedelta = timedelta(minutes=30)) -> m.ApprovalGrant:
    return m.ApprovalGrant(intent_digest=intent.digest(), scope_key=intent.scope.key(), method=m.ApprovalMethod.HUMAN,
                           approver_ref="owner", approved_at_utc=(at - timedelta(minutes=1)).isoformat(),
                           expires_at_utc=(at + ttl).isoformat(), nonce=nonce or f"nonce-{intent.intent_key}")


def request_digest(text: str = "request") -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def snapshot(journal: ExecutionJournal, revision: int, *, cash: str | None = "100", positions=None, externals=(),
             attributed=(), basis: CashBasis = CashBasis.AVAILABLE_AFTER_VENUE_HOLDS, at: datetime = NOW):
    return journal.reservations.record_account_snapshot(
        SCOPE, revision, at, None if cash is None else Decimal(cash), basis,
        {} if positions is None else positions, externals, attributed_open_orders=attributed, now=at)


def ready(path: Path, *, cash: str = "100", positions=None, externals=(), busy_timeout_ms: int = 250):
    """A new journal with one fresh snapshot and a live lease. Returns (journal, fence_token)."""
    journal = ExecutionJournal.open(path, busy_timeout_ms=busy_timeout_ms)
    snapshot(journal, 1, cash=cash, positions=positions, externals=externals)
    token = journal.reservations.acquire_lease(WORKER, TTL, NOW)
    return journal, token


def prepare(journal: ExecutionJournal, intent: m.OrderIntent, token: int, *, nonce: str | None = None,
            at: datetime = NOW):
    return journal.prepare_attempt(intent, grant(intent, nonce, at=at), fence_token=token,
                                   request_digest=request_digest(intent.intent_key), snapshot_max_age=MAX_AGE, now=at)


def counts(path: Path) -> dict[str, int]:
    import sqlite3

    conn = sqlite3.connect(str(path))
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("intents", "approvals", "attempts", "reservations", "receipts", "events")}
    finally:
        conn.close()


# ---------------------------------------------------------------- out-of-process workers


def race_worker(path: str, kind: str, key: str, quantity: str, token: int, barrier, results) -> None:
    """Run in a spawned process: wait for the other racer, then try one prepare. Reports the outcome."""
    try:
        journal = ExecutionJournal.open(path, busy_timeout_ms=20000)
        intent = (entry(key, quantity=quantity, price="0.50", cost=str(Decimal(quantity) * Decimal("0.5")))
                  if kind == "entry" else reduction(key, quantity=quantity, fee="0"))
        barrier.wait(timeout=60)
        try:
            prepare(journal, intent, token)
            results.put((key, "WON"))
        except (ReservationError, JournalError) as exc:
            results.put((key, f"REFUSED:{type(exc).__name__}:{exc}"))
        finally:
            journal.close()
    except BaseException as exc:  # report, never hang the parent
        results.put((key, f"CRASH:{type(exc).__name__}:{exc}"))


def lease_worker(path: str, worker_id: str, barrier, results) -> None:
    try:
        journal = ExecutionJournal.open(path, busy_timeout_ms=20000)
        barrier.wait(timeout=60)
        try:
            results.put((worker_id, f"TOKEN:{journal.reservations.acquire_lease(worker_id, TTL, NOW)}"))
        except (ReservationError, JournalError) as exc:
            results.put((worker_id, f"REFUSED:{type(exc).__name__}"))
        finally:
            journal.close()
    except BaseException as exc:
        results.put((worker_id, f"CRASH:{type(exc).__name__}:{exc}"))


def kill_worker_main(path: str, point: str, token: int) -> None:
    """`python test_journal_fixtures.py <path> <point> <token>`: prepare one attempt and die at `point`."""
    journal = ExecutionJournal.open(path)
    intent = entry()
    if point == "before_commit":
        journal._fault_hook = lambda where: os._exit(17) if where == "before_commit" else None
    attempt = prepare(journal, intent, token)
    if point == "after_prepare":
        os._exit(18)
    journal.mark_sent(attempt.attempt_id, now=NOW)
    if point == "after_sent":
        os._exit(19)
    os._exit(0)


if __name__ == "__main__":
    kill_worker_main(sys.argv[1], sys.argv[2], int(sys.argv[3]))
