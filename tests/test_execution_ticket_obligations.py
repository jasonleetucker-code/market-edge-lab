"""Conservative reservation of simultaneous obligations (R2 / ADR 0041; design helper, no transport)."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from edge_lab.execution_ticket import (
    Obligation, ObligationState, reserve_simultaneous_obligations,
)

S = ObligationState


def ob(oid, loss, state=S.OUTSTANDING, keys=()):
    return Obligation(oid, state, None if loss is None else D(loss), tuple(keys))


def test_every_open_quote_reserves_its_full_worst_case_at_once_without_netting():
    quotes = (ob("q1", "40", keys=("game:1", "leg:QB")), ob("q2", "35", keys=("game:1", "leg:QB")),
              ob("q3", "20", keys=("game:2",)))
    r = reserve_simultaneous_obligations(quotes, available_cash=D("100"))
    assert r.required == D("95") and r.by_key["game:1"] == D("75") and r.by_key["leg:QB"] == D("75")
    fits = reserve_simultaneous_obligations(quotes, available_cash=D("100"), candidate=ob("q4", "5"))
    assert fits.new_risk_allowed and fits.required == D("100")  # exactly at the cash is allowed
    too_much = reserve_simultaneous_obligations(quotes, available_cash=D("100"), candidate=ob("q4", "6"))
    assert not too_much.new_risk_allowed and any(x.startswith("INSUFFICIENT_CASH") for x in too_much.reasons)


def test_a_cancel_request_and_an_unknown_state_stay_reserved_and_only_release_frees_cash():
    held = (ob("a", "50", S.CANCEL_REQUESTED), ob("b", "30", S.UNKNOWN), ob("c", "10", S.BOUND),
            ob("d", "99", S.RELEASED))
    r = reserve_simultaneous_obligations(held, available_cash=D("100"), candidate=ob("e", "11"))
    assert r.required == D("101") and not r.new_risk_allowed and "d" not in r.held
    assert any(x.startswith("CANCEL_NOT_CONFIRMED") for x in r.reasons)
    assert any(x.startswith("UNKNOWN_STATE_QUARANTINE") for x in r.reasons)


def test_unknown_worst_case_or_unknown_cash_blocks_new_risk():
    r = reserve_simultaneous_obligations((ob("a", None),), available_cash=D("1000"), candidate=ob("b", "1"))
    assert r.required is None and not r.new_risk_allowed and r.reasons[0].startswith("WORST_CASE_UNKNOWN")
    r2 = reserve_simultaneous_obligations((ob("a", "1"),), available_cash=None, candidate=ob("b", "1"))
    assert not r2.new_risk_allowed and any(x.startswith("CASH_UNKNOWN") for x in r2.reasons)
    assert not reserve_simultaneous_obligations((), available_cash=D("5")).new_risk_allowed  # no candidate
    with pytest.raises(ValueError):
        reserve_simultaneous_obligations((ob("a", "1"), ob("a", "2")), available_cash=D("5"))
