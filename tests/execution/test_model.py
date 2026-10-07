"""Execution contracts (ADR 0043): exact values, closed vocabularies, layered identity and approval binding."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from edge_lab.execution import model as m

UTC = timezone.utc
NOW = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
CENT = m.Grid(step=Decimal("0.01"), minimum=Decimal("0.01"), maximum=Decimal("0.99"))
WHOLE = m.Grid(step=Decimal("1"), minimum=Decimal("1"), maximum=Decimal("1000000"))
SCOPE = m.AccountScope(m.Environment.FIXTURE, "fixture-acct")


def intent(**kw) -> m.OrderIntent:
    base = dict(intent_key="EXP-TEST:ticket-0001", strategy_id="synthetic-demo", strategy_version="v1", scope=SCOPE,
                market_ticker="KXTEST-26OCT07-T50", kind=m.IntentKind.ENTRY, side=m.Side.YES, action=m.Action.BUY,
                quantity=Decimal("10"), limit_price=Decimal("0.42"), time_in_force=m.TimeInForce.GOOD_TILL_CANCELED,
                max_total_cost=Decimal("4.60"), expires_at_utc=(NOW + timedelta(minutes=5)).isoformat(),
                price_grid=CENT, quantity_grid=WHOLE, profile_version="kalshi-ordinary-v0",
                risk_policy_version="risk-v1", fee_schedule_version="kalshi-quadratic-taker-v1", reduce_only=False)
    base.update(kw)
    return m.OrderIntent(**base)


@pytest.mark.parametrize("value", [True, False, 0.1, 1.0, float("nan"), float("inf"), "NaN", "inf", "1e3", "",
                                   "1,000", " ", None, [1], Decimal("NaN"), Decimal("Infinity"), "0x10"])
def test_inexact_values_are_refused(value):
    with pytest.raises(m.ExactValueError):
        m.exact_decimal(value, name="x")


@pytest.mark.parametrize("value,expected", [("0.42", Decimal("0.42")), (3, Decimal(3)), (Decimal("1.50"), Decimal("1.5")),
                                            ("-2", Decimal(-2)), (".5", Decimal("0.5"))])
def test_exact_values_are_accepted(value, expected):
    assert m.exact_decimal(value, name="x") == expected


def test_decimal_text_is_canonical():
    assert m.decimal_text(Decimal("1.50")) == m.decimal_text(Decimal("1.5")) == "1.5"
    assert m.decimal_text(Decimal("100")) == "100" and m.decimal_text(Decimal("1E+2")) == "100"
    assert m.decimal_text(Decimal("0.000")) == "0" and m.decimal_text(Decimal("-0")) == "0"


def test_grid_refuses_off_grid_and_out_of_range():
    assert CENT.check("0.42", name="p") == Decimal("0.42")
    for bad in ("0.425", "0", "1", "0.995", "1.00"):
        with pytest.raises(m.ExactValueError):
            CENT.check(bad, name="p")
    with pytest.raises(m.ExactValueError):
        m.Grid(step=Decimal("0.03"), minimum=Decimal("0.01"), maximum=Decimal("0.99"))  # bounds off-grid
    with pytest.raises(m.ExactValueError):
        m.Grid(step=0.01, minimum=Decimal("0.01"), maximum=Decimal("0.99"))  # float step


def test_fractional_quantity_grid_is_explicit():
    tenth = m.Grid(step=Decimal("0.1"), minimum=Decimal("0.1"), maximum=Decimal("100"))
    assert intent(quantity=Decimal("2.5"), quantity_grid=tenth, max_total_cost=Decimal("1.10")).quantity == Decimal("2.5")
    with pytest.raises(m.ExactValueError):
        intent(quantity=Decimal("2.5"))  # whole-contract grid


def test_entry_and_reduction_semantics():
    assert intent().kind is m.IntentKind.ENTRY
    red = intent(kind=m.IntentKind.REDUCTION, action=m.Action.SELL, reduce_only=True, max_total_cost=Decimal("0.20"))
    assert red.reduce_only
    with pytest.raises(ValueError):
        intent(action=m.Action.SELL)  # an entry is a buy
    with pytest.raises(ValueError):
        intent(reduce_only=True)
    with pytest.raises(ValueError):
        intent(kind=m.IntentKind.REDUCTION, action=m.Action.SELL, reduce_only=False)  # would be a flip
    with pytest.raises(ValueError):
        intent(kind=m.IntentKind.REDUCTION, action=m.Action.BUY, reduce_only=True)


def test_max_cost_cannot_understate_the_principal():
    with pytest.raises(m.ExactValueError):
        intent(max_total_cost=Decimal("4.19"))  # 10 x 0.42 = 4.20
    assert intent(max_total_cost=Decimal("4.20")).max_total_cost == Decimal("4.2")


@pytest.mark.parametrize("field,value", [("quantity", Decimal("0")), ("quantity", Decimal("-1")), ("quantity", 10.0),
                                         ("limit_price", 0.42), ("limit_price", Decimal("1")), ("max_total_cost", "-1"),
                                         ("market_ticker", "kx lower"), ("intent_key", ""), ("expires_at_utc", "2026-10-07T15:05:00"),
                                         ("evidence", ["x"]), ("reduce_only", 0), ("side", "yes")])
def test_invalid_fields_are_refused(field, value):
    with pytest.raises((ValueError, m.ExactValueError)):
        intent(**{field: value})


def test_post_only_requires_a_resting_order():
    with pytest.raises(ValueError):
        intent(post_only=True, time_in_force=m.TimeInForce.IMMEDIATE_OR_CANCEL)
    assert intent(post_only=True).post_only


def test_digest_covers_every_field_and_client_id_is_stable():
    a = intent()
    assert a.digest() == intent().digest() and a.client_order_id() == intent().client_order_id()
    assert a.digest() == intent(limit_price=Decimal("0.420")).digest()  # equal values, equal identity
    variants = [intent(limit_price=Decimal("0.43")), intent(quantity=Decimal("11"), max_total_cost=Decimal("5")),
                intent(scope=m.AccountScope(m.Environment.FIXTURE, "fixture-acct", 1)),
                intent(scope=m.AccountScope(m.Environment.DEMO, "fixture-acct")), intent(strategy_version="v2"),
                intent(side=m.Side.NO), intent(time_in_force=m.TimeInForce.IMMEDIATE_OR_CANCEL),
                intent(evidence=("snap:1",)), intent(fee_schedule_version="other"), intent(max_total_cost=Decimal("4.61")),
                intent(expires_at_utc=(NOW + timedelta(minutes=6)).isoformat()),
                intent(price_grid=m.Grid(step=Decimal("0.001"), minimum=Decimal("0.001"), maximum=Decimal("0.999")))]
    digests = {v.digest() for v in variants} | {a.digest()}
    assert len(digests) == len(variants) + 1
    assert len({v.client_order_id() for v in variants}) == len(variants)


def test_scope_keys_are_distinct_and_opaque():
    assert SCOPE.key() == "FIXTURE:fixture-acct:primary"
    assert m.AccountScope(m.Environment.DEMO, "a", 0).key() != m.AccountScope(m.Environment.DEMO, "a").key()
    for bad in ("", "has space", "x" * 300):
        with pytest.raises(ValueError):
            m.AccountScope(m.Environment.FIXTURE, bad)
    with pytest.raises(ValueError):
        m.AccountScope(m.Environment.FIXTURE, "a", True)


def grant(i: m.OrderIntent, **kw) -> m.ApprovalGrant:
    base = dict(intent_digest=i.digest(), scope_key=i.scope.key(), method=m.ApprovalMethod.HUMAN,
                approver_ref="owner", approved_at_utc=NOW.isoformat(),
                expires_at_utc=(NOW + timedelta(minutes=2)).isoformat(), nonce="n-1")
    base.update(kw)
    return m.ApprovalGrant(**base)


def test_an_approval_binds_one_digest_one_scope_and_expires():
    i = intent()
    g = grant(i)
    assert g.problems(i, now=NOW + timedelta(seconds=30)) == []
    changed = intent(limit_price=Decimal("0.43"))
    assert any(p.startswith("APPROVAL_DIGEST_MISMATCH") for p in g.problems(changed, now=NOW))
    other = replace(i, scope=m.AccountScope(m.Environment.FIXTURE, "other-acct"))
    assert any(p.startswith("APPROVAL_SCOPE_MISMATCH") for p in g.problems(other, now=NOW))
    assert "APPROVAL_EXPIRED" in g.problems(i, now=NOW + timedelta(minutes=2))
    assert any(p.startswith("APPROVAL_FROM_FUTURE") for p in g.problems(i, now=NOW - timedelta(seconds=1)))
    assert "INTENT_EXPIRED" in grant(i, expires_at_utc=(NOW + timedelta(hours=1)).isoformat()).problems(
        i, now=NOW + timedelta(minutes=5))


def test_approval_construction_is_strict():
    i = intent()
    with pytest.raises(ValueError):
        grant(i, intent_digest="abc")
    with pytest.raises(ValueError):
        grant(i, expires_at_utc=NOW.isoformat())  # must expire after it is granted
    with pytest.raises(ValueError):
        grant(i, method=m.ApprovalMethod.POLICY)  # a policy approval names its policy
    with pytest.raises(ValueError):
        grant(i, policy_ref="p-1")  # a human approval does not
    assert grant(i, method=m.ApprovalMethod.POLICY, policy_ref="p-1").policy_ref == "p-1"


def test_times_must_carry_a_zone():
    with pytest.raises(ValueError):
        m.utc_text(datetime(2026, 10, 7, 15, 0))
    with pytest.raises(ValueError):
        m.parse_utc_text("2026-10-07T15:00:00")
    assert m.parse_utc_text("2026-10-07T11:00:00-04:00") == NOW


def test_canonical_json_refuses_floats_and_nan():
    assert m.canonical_json({"b": Decimal("1.50"), "a": m.Side.YES}) == '{"a":"yes","b":"1.5"}'
    with pytest.raises(ValueError):
        m.canonical_json({"x": float("nan")})


# ---------------------------------------------------------------- review fixes (foundation review, 3766d87)


def test_digest_is_independent_of_the_callers_decimal_context():
    import decimal

    a = intent(max_total_cost=Decimal("4.6000000000000000000001"))
    b = intent(max_total_cost=Decimal("4.6000000000000000000002"))
    assert a.digest() != b.digest()  # normalize() at 28 digits used to merge them
    baseline = intent(max_total_cost=Decimal("4.2345678")).digest()
    with decimal.localcontext() as ctx:
        ctx.prec = 3
        assert intent(max_total_cost=Decimal("4.2345678")).digest() == baseline
        assert m.decimal_text(Decimal("1.2345678")) == "1.2345678"


@pytest.mark.parametrize("value", ["9E+100000", "1" * 31, "0." + "0" * 40 + "1", "١٢", "１２"])
def test_huge_tiny_and_non_ascii_numbers_are_refused(value):
    with pytest.raises(m.ExactValueError):
        m.exact_decimal(value if "E" not in value else Decimal(value), name="x")


def test_grid_errors_are_exact_value_errors():
    with pytest.raises(m.ExactValueError):
        m.Grid(step=Decimal("0.01"), minimum=Decimal("0"), maximum=Decimal("1E40"))


def test_max_total_cost_has_a_typo_guard_for_both_kinds():
    with pytest.raises(m.ExactValueError):
        intent(max_total_cost=Decimal("11.01"))  # 10 contracts x 1.10
    with pytest.raises(m.ExactValueError):
        intent(kind=m.IntentKind.REDUCTION, action=m.Action.SELL, reduce_only=True, max_total_cost=Decimal("1000000"))


def test_evidence_order_does_not_change_identity_and_duplicates_are_refused():
    assert intent(evidence=("b", "a")).digest() == intent(evidence=("a", "b")).digest()
    assert intent(evidence=("b", "a")).evidence == ("a", "b")
    with pytest.raises(ValueError):
        intent(evidence=("a", "a"))


def test_problems_refuses_a_naive_now_and_grants_validate_types():
    i = intent()
    g = grant(i)
    with pytest.raises(ValueError):
        g.problems(i, now=datetime(2026, 10, 7, 15, 0))
    with pytest.raises(ValueError):
        grant(i, intent_digest=123)
    with pytest.raises(ValueError):
        grant(i, scope_key="free text")


def test_a_lookalike_string_is_never_an_authorized_environment():
    assert not m.environment_authorized("FIXTURE")
    assert m.environment_authorized(m.Environment.FIXTURE)
