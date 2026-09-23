"""Kalshi fee evidence (owner-supplied PDF, effective 2026-07-07) and the multi-component,
point-in-time fee verification (ADR 0017)."""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab import exp001_shadow as shadow, exp001_stageb as stageb, fees
from edge_lab.fee_schedules import (
    FEE_VERIFICATIONS, KALSHI_KXHIGHNY_VERIFICATION_2026_09_23 as RECORD, KALSHI_NONSTANDARD_SERIES,
    KALSHI_QUADRATIC_TAKER_V1 as KALSHI, ClaimBasis, ComponentState, CostModel, FeeScheduleStatus,
    UnsupportedFeeSchedule, VerificationComponent, displayed_fee, kalshi_exact_taker_buy, recheck_due,
    restated_verification, schedule_for, verification_at,
)
from edge_lab.freshness import parse_utc
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.storage import SnapshotStore

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "experiments/EXP-001-kxhighny-nws-vs-market/fee_verification"
KNOWN = parse_utc(RECORD.knowledge_time_utc)
NATIVE = "KXHIGHNY-26SEP24-B70.5"
UTC = timezone.utc


# ---------------------------------------------------------------- the evidence itself

def test_pdf_bytes_match_the_manifest():
    manifest = json.loads((EVIDENCE / "MANIFEST.json").read_text())
    for doc in manifest["documents"]:
        data = (EVIDENCE / doc["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == doc["sha256"], doc["path"]
    for doc in manifest["transcriptions"]:
        assert hashlib.sha256((EVIDENCE / doc["path"]).read_bytes()).hexdigest() == doc["sha256"], doc["path"]
    pdf = manifest["documents"][0]
    assert pdf["sha256"] == "c326a69f596a11e8f8be2620402d39a8d4823920c21cc97c93a114d862699601"
    assert pdf["bytes"] == 281129 and pdf["effective_date"] == "2026-07-07"


def test_api_captures_support_the_multiplier_and_no_scheduled_change():
    series = json.loads((EVIDENCE / "api_series_KXHIGHNY_2026-09-23T131747Z.json").read_text())["series"]
    assert series["ticker"] == "KXHIGHNY" and series["fee_type"] == "quadratic" and series["fee_multiplier"] == 1
    changes = json.loads((EVIDENCE / "api_series_fee_changes_KXHIGHNY_2026-09-23T131748Z.json").read_text())
    assert changes == {"series_fee_change_arr": []}


def test_nonstandard_series_list_matches_the_pdf_transcription_and_excludes_kxhighny():
    listed = json.loads((EVIDENCE / "pdf_nonstandard_series.json").read_text())
    assert {s["series"] for s in listed["series"]} == set(KALSHI_NONSTANDARD_SERIES)
    assert "KXHIGHNY" not in KALSHI_NONSTANDARD_SERIES and listed["kxhighny_listed"] is False


def test_every_pdf_table_row_is_the_model_fee_rounded_up_to_the_cent():
    rows = json.loads((EVIDENCE / "pdf_table_rows.json").read_text())["rows"]
    assert len(rows) == 21
    for row in rows:
        price = Decimal(row["price"])
        assert displayed_fee(1, price) == Decimal(row["fee_1_contract"]), row
        assert displayed_fee(100, price) == Decimal(row["fee_100_contracts"]), row
        assert Decimal(row["price_100_contracts"]) == price * 100


@pytest.mark.parametrize("contracts,price,displayed", [(1, "0.01", "0.01"), (100, "0.50", "1.75"),
                                                       (100, "0.05", "0.34"), (100, "0.15", "0.90")])
def test_pdf_examples_directly(contracts, price, displayed):
    assert displayed_fee(contracts, Decimal(price)) == Decimal(displayed)


# ---------------------------------------------------------------- exact debit vs frozen model

def test_docs_worked_example_for_both_account_types():
    direct = kalshi_exact_taker_buy(1, Decimal("0.055"), account_type="direct")
    non_direct = kalshi_exact_taker_buy(1, Decimal("0.055"), account_type="non_direct")
    assert direct.model_fee == Decimal("0.00363825") and direct.trade_fee == Decimal("0.003639")
    assert direct.total_cost == Decimal("0.0587")  # centicent: fee + position cost rounded up
    assert non_direct.total_cost == Decimal("0.06") == fees.taker_buy_cost(1, Decimal("0.055"))
    assert non_direct.rounding_fee == Decimal("0.001361")  # the docs' worked rounding fee


def test_frozen_model_is_an_upper_bound_on_the_exact_debit():
    rng = random.Random(20260923)
    for _ in range(5000):
        contracts = rng.randint(1, 500)
        price = Decimal(rng.randint(1, 9999)) / Decimal(10000)
        direct = kalshi_exact_taker_buy(contracts, price, account_type="direct").total_cost
        non_direct = kalshi_exact_taker_buy(contracts, price, account_type="non_direct").total_cost
        frozen = fees.taker_buy_cost(contracts, price)
        assert contracts * price <= direct <= non_direct <= frozen < direct + Decimal("0.01"), (contracts, price)
        assert frozen == non_direct == KALSHI.taker_buy(contracts, price).total_cost


def test_exact_debit_rejects_unknown_account_types_and_bad_input():
    with pytest.raises(ValueError):
        kalshi_exact_taker_buy(1, Decimal("0.5"), account_type="fcm")
    with pytest.raises(ValueError):
        kalshi_exact_taker_buy(0, Decimal("0.5"), account_type="direct")
    with pytest.raises(ValueError):
        kalshi_exact_taker_buy(1, Decimal("1"), account_type="direct")


# ---------------------------------------------------------------- the verification record

def test_record_components_and_derived_state():
    states = {c.component: c.state for c in RECORD.components}
    assert set(states) == set(VerificationComponent)
    assert states[VerificationComponent.COEFFICIENT] is ComponentState.VERIFIED
    assert states[VerificationComponent.SERIES_MULTIPLIER] is ComponentState.VERIFIED
    assert states[VerificationComponent.ROUNDING_FOR_ACCOUNT_TYPE] is ComponentState.VERIFIED
    assert states[VerificationComponent.ACCOUNT_TYPE] is ComponentState.OWNER_ATTESTED
    assert RECORD.full_schedule_verified is False
    assert RECORD.claim_basis(CostModel.CONSERVATIVE_UPPER_BOUND) is ClaimBasis.CONSERVATIVE_BOUND
    assert RECORD.claim_basis(CostModel.EXACT) is ClaimBasis.NONE  # EXACT needs every component verified


def test_an_unverified_core_component_means_no_claim():
    for core in (VerificationComponent.COEFFICIENT, VerificationComponent.SERIES_MULTIPLIER,
                 VerificationComponent.SCHEDULED_CHANGES, VerificationComponent.ROUNDING_FOR_ACCOUNT_TYPE):
        weakened = replace(RECORD, components=tuple(
            replace(c, state=ComponentState.UNVERIFIED) if c.component is core else c for c in RECORD.components))
        assert weakened.claim_basis(CostModel.CONSERVATIVE_UPPER_BOUND) is ClaimBasis.NONE, core


def test_full_verification_with_an_exact_cost_model_is_exact():
    full = replace(RECORD, components=tuple(replace(c, state=ComponentState.VERIFIED) for c in RECORD.components))
    assert full.full_schedule_verified and full.claim_basis(CostModel.EXACT) is ClaimBasis.EXACT
    # ...but the frozen conservative model can still only support a bound.
    assert full.claim_basis(CostModel.CONSERVATIVE_UPPER_BOUND) is ClaimBasis.CONSERVATIVE_BOUND


def test_verification_is_point_in_time_at_the_knowledge_time():
    before = verification_at(KALSHI, KNOWN - timedelta(microseconds=1), NATIVE)
    at = verification_at(KALSHI, KNOWN, NATIVE)
    assert before.status is FeeScheduleStatus.UNVERIFIED_CURRENT_SCHEDULE and not before.claimable
    assert before.verification_id is None and before.claim_basis is ClaimBasis.NONE
    assert at.status is FeeScheduleStatus.PARTIALLY_VERIFIED and at.claimable
    assert at.claim_basis is ClaimBasis.CONSERVATIVE_BOUND and at.verification_id == RECORD.verification_id


def test_record_goes_stale_after_its_recheck_date():
    recheck = parse_utc(RECORD.recheck_by_utc)
    assert verification_at(KALSHI, recheck, NATIVE).claimable
    late = verification_at(KALSHI, recheck + timedelta(seconds=1), NATIVE)
    assert not late.claimable and late.status is FeeScheduleStatus.UNVERIFIED_CURRENT_SCHEDULE
    assert recheck_due(recheck + timedelta(seconds=1)) == [RECORD.verification_id]
    assert recheck_due(recheck) == []


def test_record_covers_only_its_series():
    other = verification_at(KALSHI, KNOWN + timedelta(days=1), "KXHIGHCHI-26SEP24-B70.5")
    assert not other.claimable and other.verification_id is None
    unknown = verification_at(KALSHI, KNOWN + timedelta(days=1))
    assert not unknown.claimable


def test_restatement_covers_trades_from_the_effective_date_only():
    now = KNOWN + timedelta(days=1)
    earlier_trade = datetime(2026, 9, 22, 22, tzinfo=UTC)  # before the record was known
    assert not verification_at(KALSHI, earlier_trade, NATIVE).claimable  # what was known then
    assert restated_verification(KALSHI, earlier_trade, now, NATIVE).claim_basis is ClaimBasis.CONSERVATIVE_BOUND
    pre_effective = datetime(2026, 7, 6, 12, tzinfo=UTC)
    assert not restated_verification(KALSHI, pre_effective, now, NATIVE).claimable


def test_ledger_fields_are_legacy_before_the_record_and_extended_after():
    assert shadow.fee_fields("2026-09-22T22:00:00+00:00", "kalshi:" + NATIVE) == {
        "fee_schedule_id": "kalshi-quadratic-taker-v1", "fee_status": "UNVERIFIED_CURRENT_SCHEDULE",
        "claimable": False}
    assert shadow.fee_fields("2026-09-23T22:00:00+00:00", "kalshi:" + NATIVE) == {
        "fee_schedule_id": "kalshi-quadratic-taker-v1", "fee_status": "PARTIALLY_VERIFIED", "claimable": True,
        "claim_basis": "CONSERVATIVE_BOUND", "fee_verification_id": RECORD.verification_id,
        "claim_allowance_per_contract": "0.0101"}


def test_receipt_fee_block_has_fixed_keys_at_any_time():
    early = shadow.fee_receipt("2026-09-22T23:00:00+00:00")
    late = shadow.fee_receipt("2026-09-24T23:00:00+00:00")
    assert set(early) == set(late)
    assert early["claim_basis"] == "NONE" and late["claim_basis"] == "CONSERVATIVE_BOUND"


def test_schedule_base_status_is_unchanged_and_verification_is_a_separate_record():
    assert stageb.FEE_SCHEDULE is KALSHI and KALSHI.status is FeeScheduleStatus.UNVERIFIED_CURRENT_SCHEDULE
    assert len(FEE_VERIFICATIONS) == 1


# ---------------------------------------------------------------- never another venue's fees

@pytest.mark.parametrize("venue", ["polymarket_us", "polymarket_international", "novig", "the_odds_api"])
def test_kalshi_fees_never_price_another_venue(venue):
    schedule = schedule_for(venue, "KXHIGHNY")
    assert isinstance(schedule, UnsupportedFeeSchedule) and schedule.status is FeeScheduleStatus.UNSUPPORTED
    assert not verification_at(KALSHI, KNOWN + timedelta(days=1), scope=None).claimable


def test_nonstandard_kalshi_series_is_unsupported_and_general_series_uses_the_schedule():
    assert isinstance(schedule_for("kalshi", "KXNFLGAME"), UnsupportedFeeSchedule)
    assert isinstance(schedule_for("kalshi", None), UnsupportedFeeSchedule)
    assert schedule_for("kalshi", "KXHIGHNY") is KALSHI


# ---------------------------------------------------------------- frozen research record

# Ledger digest produced by main (f7b5cf8) code for the D=2026-09-23 fixture day plus its
# settlement: every (account, kind, key, payload_sha256) in order. The decision time is
# before the verification record, so the new code must rebuild it byte for byte.
GOLDEN_LEDGER_DIGEST = "487e941ccd26921102d9db7feefdea6183569c96af618f74555045ee85d1bc38"


def test_pre_verification_ledger_rebuilds_byte_identically(tmp_path, monkeypatch):
    from test_exp001_shadow import CLOSED, _result, _settled
    from test_forward import D, _full_day

    store = SnapshotStore(tmp_path / "fwd.sqlite3")
    ledger = ShadowLedger(tmp_path / "ledger.sqlite3")
    _full_day(store, monkeypatch)
    shadow.run_day(store, ledger, D, model=stageb.load_model(), now=CLOSED)
    _settled(store, 70, _result(70))
    report = shadow.settle_open_positions(store, ledger, now=datetime(2026, 9, 24, 15, tzinfo=UTC))
    assert report["settled"]  # settled after the record was known, fee fields copied from the fill
    with sqlite3.connect(tmp_path / "ledger.sqlite3") as con:
        rows = con.execute("SELECT account_id, kind, entry_key, payload_sha256 FROM ledger_entries ORDER BY seq").fetchall()
    assert len(rows) == 38
    assert hashlib.sha256(repr(rows).encode()).hexdigest() == GOLDEN_LEDGER_DIGEST


# ---------------------------------------------------------------- the engine uses the point-in-time state

def _evaluate(as_of: datetime, native: str = NATIVE, fee_verification: str = "require"):
    from test_opportunity import MARKET, POLICY, estimate, quote, run
    return run(q=quote(received=as_of - timedelta(minutes=2)),
               e=estimate(observed=as_of - timedelta(hours=3), generated=as_of),
               market=replace(MARKET, native_id=native), schedule=KALSHI,
               policy=replace(POLICY, fee_verification=fee_verification), as_of=as_of)


def test_engine_claimability_follows_the_record_known_at_as_of():
    before, after = _evaluate(KNOWN - timedelta(seconds=1)), _evaluate(KNOWN + timedelta(hours=8))
    assert before.rejection_reason == "FEE_UNVERIFIED" and not before.claimable
    assert before.fee_status == "UNVERIFIED_CURRENT_SCHEDULE"
    assert after.qualification == "QUALIFY" and after.claimable and after.fee_status == "PARTIALLY_VERIFIED"
    # The fee itself never changes: verification is evidence, not a new cost.
    assert before.fee == after.fee and before.all_in_cost == after.all_in_cost


def test_engine_never_claims_for_an_uncovered_series():
    other = _evaluate(KNOWN + timedelta(hours=8), native="KXHIGHCHI-26SEP24-B70.5")
    assert other.rejection_reason == "FEE_UNVERIFIED" and not other.claimable


# ---------------------------------------------------------------- split orders (review B1)

def _real_order_debit(fills: list[Decimal], price: Decimal, precision: Decimal) -> Decimal:
    """Kalshi's documented per-fill mechanics (Fee Rounding docs): trade fee ceil $0.000001,
    balance change floored to the account precision, the rounding fee accumulated per order,
    and rebates paid in whole precision units, capped so a fill's net fee is not negative."""
    from decimal import ROUND_CEILING, ROUND_FLOOR
    k = Decimal("0.07") * price * (1 - price)
    acc = total = Decimal(0)
    for c in fills:
        trade_fee = (k * c).quantize(Decimal("0.000001"), ROUND_CEILING)
        change = -(price * c) - trade_fee
        aligned = change.quantize(precision, ROUND_FLOOR)
        rounding = change - aligned
        acc += rounding
        rebate = min(acc.quantize(precision, ROUND_FLOOR), (trade_fee + rounding).quantize(precision, ROUND_FLOOR))
        acc -= rebate
        total += -aligned - rebate
    return total


def _split(rng: random.Random, contracts: int, max_pieces: int) -> list[Decimal]:
    units = contracts * 100  # Kalshi's minimum fill granularity is 0.01 contracts
    cuts = sorted(rng.sample(range(1, units), rng.randint(0, min(max_pieces, units - 1))))
    return [Decimal(b - a) / 100 for a, b in zip([0, *cuts], [*cuts, units])]


def test_split_orders_can_exceed_the_single_fill_cost_so_an_allowance_is_needed():
    fills = [Decimal(x) for x in ("0.36", "0.24", "0.04", "0.26", "0.17", "0.03", "0.09", "0.04", "0.53", "0.13",
                                  "0.1", "0.31", "0.1", "0.02", "0.08", "0.06", "0.16", "0.04", "0.02", "0.15", "0.07")]
    price = Decimal("0.9963")
    real = _real_order_debit(fills, price, Decimal("0.0001"))
    frozen = fees.taker_buy_cost(3, price)
    assert real > frozen  # the plain frozen cost is NOT an upper bound for a split order
    assert real < frozen + RECORD.rounding_allowance_per_contract * 3


def test_direct_member_debit_is_below_frozen_plus_allowance_for_any_split():
    rng = random.Random(20260923)
    allowance = RECORD.rounding_allowance_per_contract
    for _ in range(3000):
        contracts = rng.randint(1, 4)
        price = Decimal(rng.randint(1, 9999)) / Decimal(10000)
        fills = _split(rng, contracts, rng.choice((0, 3, 30, 400)))
        real = _real_order_debit(fills, price, Decimal("0.0001"))
        assert real < fees.taker_buy_cost(contracts, price) + allowance * contracts, (contracts, price, fills)


def test_worst_case_split_into_minimum_fills_stays_inside_the_allowance():
    # 100 fills of 0.01 per contract at prices where fees are tiny (the rebate cap binds).
    for price in (Decimal("0.0001"), Decimal("0.0137"), Decimal("0.5"), Decimal("0.9999")):
        for contracts in (1, 3):
            fills = [Decimal("0.01")] * (100 * contracts)
            real = _real_order_debit(fills, price, Decimal("0.0001"))
            assert real < fees.taker_buy_cost(contracts, price) + RECORD.rounding_allowance_per_contract * contracts


def test_claim_basis_requires_a_direct_account_and_an_allowance():
    assert replace(RECORD, account_type="non_direct").claim_basis(CostModel.CONSERVATIVE_UPPER_BOUND) is ClaimBasis.NONE
    assert replace(RECORD, rounding_allowance_per_contract=None).claim_basis(
        CostModel.CONSERVATIVE_UPPER_BOUND) is ClaimBasis.NONE
    unattested = replace(RECORD, components=tuple(
        replace(c, state=ComponentState.UNVERIFIED) if c.component is VerificationComponent.ACCOUNT_TYPE else c
        for c in RECORD.components))
    assert unattested.claim_basis(CostModel.CONSERVATIVE_UPPER_BOUND) is ClaimBasis.NONE


def test_claim_adjusted_net_subtracts_the_allowance_per_contract():
    from edge_lab.fee_schedules import claim_adjusted_net
    after = verification_at(KALSHI, KNOWN + timedelta(hours=1), NATIVE)
    assert claim_adjusted_net(Decimal("0.50"), 3, after) == Decimal("0.50") - Decimal("0.0303")
    before = verification_at(KALSHI, KNOWN - timedelta(hours=1), NATIVE)
    assert claim_adjusted_net(Decimal("0.50"), 3, before) is None


# ---------------------------------------------------------------- unsupported fees never qualify (review S1)

@pytest.mark.parametrize("policy", ["flag", "require"])
def test_unsupported_fee_schedule_rejects_instead_of_crashing_or_qualifying(policy):
    from test_opportunity import MARKET, POLICY, estimate, quote, run
    as_of = KNOWN + timedelta(hours=8)
    o = run(q=quote(received=as_of - timedelta(minutes=2)), e=estimate(observed=as_of - timedelta(hours=3), generated=as_of),
            market=replace(MARKET, native_id="KXNFLGAME-26SEP24-X"), schedule=schedule_for("kalshi", "KXNFLGAME"),
            policy=replace(POLICY, fee_verification=policy), as_of=as_of)
    assert o.qualification == "REJECT" and "FEE_UNSUPPORTED" in o.reasons
    assert o.fee is None and o.net_edge is None and not o.claimable


def test_a_declared_verified_conservative_schedule_is_not_exact():
    from edge_lab.fee_schedules import QuadraticTakerSchedule
    verified = replace(KALSHI, schedule_id="test-verified", status=FeeScheduleStatus.VERIFIED)
    assert verification_at(verified, KNOWN, NATIVE).claim_basis is ClaimBasis.NONE  # no proven allowance
    exact = replace(verified, cost_model=CostModel.EXACT)
    assert verification_at(exact, KNOWN, NATIVE).claim_basis is ClaimBasis.EXACT
    assert isinstance(exact, QuadraticTakerSchedule)


def test_recorded_claim_basis_is_the_weakest_filled_basis():
    from edge_lab.fee_schedules import recorded_claim_basis
    assert recorded_claim_basis([]) is ClaimBasis.NONE
    legacy = {"status": "FILLED", "claimable": False}
    bound = {"status": "FILLED", "claim_basis": "CONSERVATIVE_BOUND"}
    assert recorded_claim_basis([bound]) is ClaimBasis.CONSERVATIVE_BOUND
    assert recorded_claim_basis([bound, legacy]) is ClaimBasis.NONE
    assert recorded_claim_basis([bound, {"status": "NO_FILL"}]) is ClaimBasis.CONSERVATIVE_BOUND


# ---------------------------------------------------------------- a day decided after the record (review S4)

def test_day_decided_after_the_record_carries_the_bound_end_to_end(tmp_path, monkeypatch):
    from edge_lab import fee_schedules
    from test_exp001_shadow import CLOSED, _result, _settled
    from test_forward import D, _full_day

    early = replace(RECORD, knowledge_time_utc="2026-09-22T00:00:00Z")  # as if known before D's decision
    monkeypatch.setattr(fee_schedules, "FEE_VERIFICATIONS", (early,))
    store = SnapshotStore(tmp_path / "fwd.sqlite3")
    ledger = ShadowLedger(tmp_path / "ledger.sqlite3")
    _full_day(store, monkeypatch)
    model = stageb.load_model()
    shadow.run_day(store, ledger, D, model=model, now=CLOSED)
    shadow.run_day(store, ledger, D, model=model, now=CLOSED)  # re-run: idempotent, no conflict
    _settled(store, 70, _result(70))
    shadow.settle_open_positions(store, ledger, now=datetime(2026, 9, 24, 15, tzinfo=UTC))
    shadow.settle_open_positions(store, ledger, now=datetime(2026, 9, 24, 16, tzinfo=UTC))
    kinds = {"decision": 0, "fill": 0, "settlement": 0}
    for acct in ledger.accounts():
        for row in ledger.entries(acct):
            payload = json.loads(row["payload_json"])
            if row["kind"] in ("decision", "fill", "settlement"):
                kinds[row["kind"]] += 1
                assert payload["claim_basis"] == "CONSERVATIVE_BOUND"
                assert payload["fee_verification_id"] == RECORD.verification_id
                assert payload["claim_allowance_per_contract"] == "0.0101"
    assert all(kinds.values())
