"""Randomized checks of genuine invariants, with recorded seeds (directive §20).

They test bookkeeping truths that must hold for any input: attribution sums to inventory, cash and
inventory reconcile, nothing goes short, deduplication is idempotent, point-in-time selection ignores
the future and an unknown fee never becomes a number. None of them assumes copying is profitable.
"""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

import pytest
from wallet_support import D, Books, acct, at, book, config, enrolled, limits, obs, signal

from edge_lab.wallet_intel.events import Action, ObservationLog, assign_occurrences
from edge_lab.wallet_intel.policy import FollowerPolicy
from edge_lab.wallet_intel.replay import FillStatus, Resolution, replay

SEEDS = (20261007, 1, 7, 42, 99, 1234, 31337, 271828)
TOKENS = ("m1-yes", "m1-no", "m2-yes")


def _random_run(seed: int, fee_fn=None):  # type: ignore[no-untyped-def]
    rng = random.Random(seed)
    held: dict[tuple[str, str], int] = {}
    signals, books = [], []
    for i in range(40):
        leader = rng.choice(("L1", "L2", "L3"))
        token = rng.choice(TOKENS)
        when = at(i * 3)
        before = held.get((leader, token), 0)
        if before > 0 and rng.random() < 0.4:
            qty = rng.randint(1, before)
            action = Action.TRADE_SELL
            held[(leader, token)] = before - qty
        else:
            qty = rng.randint(1, 200)
            action = Action.TRADE_BUY
            held[(leader, token)] = before + qty
        price = Decimal(rng.randint(10, 90)) / 100
        market = token.split("-")[0]
        signals.append(signal(f"s{i}", action, leader=leader, token=token, qty=str(qty), price=str(price), when=when,
                              before=None if rng.random() < 0.1 else str(before), market=market,
                              event=f"evt-{market}", delay=timedelta(seconds=rng.randint(1, 300))))
        mid = Decimal(rng.randint(10, 90)) / 100
        books.append(book(token, bid=str(mid - D("0.01")), ask=str(mid + D("0.01")), size=str(rng.randint(1, 60)),
                          levels=rng.randint(1, 3), captured=when + timedelta(seconds=rng.randint(0, 200)),
                          truncated=rng.random() < 0.3))
    res = {"m1-yes": Resolution("m1-yes", D(1), at(200)), "m1-no": Resolution("m1-no", D(0), at(200))}
    lim = limits(risk_per_signal=D(rng.randint(1, 30)), per_leader=D(40), per_event=D(50), total=D(80))
    pol = FollowerPolicy(lim, enrollments=enrolled("L1", "L2", "L3"))
    cfg = config() if fee_fn is None else config(fee_fn=fee_fn)
    return replay(signals, pol, initial_cash=D(rng.randint(10, 150)), books=Books(*books), resolutions=res,
                  config=cfg, horizon=at(days=1))


@pytest.mark.parametrize("seed", SEEDS)
def test_attribution_cash_and_inventory_always_reconcile(seed):
    r = _random_run(seed)
    assert all(r.reconciliation.values()), (seed, r.reconciliation)
    fb = r.final_book
    assert fb.cash >= 0 and all(q >= 0 for q in fb.inventory.values())
    for token, qty in fb.inventory.items():
        assert sum(fb.attribution.get(token, {}).values(), Decimal(0)) == qty
    # No leader ever sold more than its own signals bought.
    bought: dict[tuple[str, str], Decimal] = {}
    for f in r.fills:
        if f.status in (FillStatus.FILLED, FillStatus.PARTIAL):
            key = (f.leader_key, f.instrument_id)
            bought[key] = bought.get(key, Decimal(0)) + (f.filled if f.side == "BUY" else -f.filled)
            assert bought[key] >= 0, (seed, key)


@pytest.mark.parametrize("seed", SEEDS)
def test_an_unknown_fee_anywhere_never_becomes_a_number(seed):
    rng = random.Random(seed + 1)
    r = _random_run(seed, fee_fn=lambda side, levels: None if rng.random() < 0.3 else Decimal(0))
    if r.final_book.fees_unknown:
        assert not r.follower.net_pnl.known and not r.follower.fees.known
    for fill in r.fills:
        assert fill.fee.known == (fill.fee.value is not None)


@pytest.mark.parametrize("seed", SEEDS)
def test_deduplication_is_idempotent_across_overlapping_retrievals(seed):
    rng = random.Random(seed)
    a = acct(1)
    base = [obs(a, Action.TRADE_BUY, qty=rng.choice((5, 10)), price="0.40", when=at(rng.randint(0, 5)), tx="0xt1")
            for _ in range(8)]
    numbered = assign_occurrences(base)
    expected = {o.observation_id for o in numbered}
    log = ObservationLog()
    for _ in range(5):
        log.ingest(numbered)  # whole retrievals again, in the same canonical order
    view = log.as_known_at(at(days=1), include_conflicted=True)
    assert {o.observation_id for o in view} == expected
    assert len(view) == len(numbered)


@pytest.mark.parametrize("seed", SEEDS)
def test_point_in_time_view_ignores_anything_received_later(seed):
    rng = random.Random(seed)
    a = acct(1)
    log = ObservationLog()
    early = [obs(a, Action.TRADE_BUY, when=at(i)) for i in range(5)]
    log.ingest(early)
    cutoff = at(days=1)
    before = log.as_known_at(cutoff)
    late = [obs(a, Action.TRADE_BUY, when=at(rng.randint(0, 600)), receipt_delay=timedelta(days=2)) for _ in range(10)]
    log.ingest(late)
    assert log.as_known_at(cutoff) == before
