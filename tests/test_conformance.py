"""Semantic conformance (EE v1 PR B): native units, legacy compatibility, rights inheritance, venue facts."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from edge_lab.fee_schedules import get_fee_schedule, schedule_for
from edge_lab.kalshi_quotes import ladders_from_orderbook
from edge_lab.opportunity import (
    KALSHI_BINARY_UNITS, NOVIG_V3_UNITS, ClockKind, ClockStamp, ContractSemantics, DataRights, DepthStatus, Event,
    ExecutableQuote, FeeRoundingScope, FeeSemantics, Market, MarketStatus, OutcomeFinality, Payoff, Policy,
    ProbabilityMeaning, RelationTier, RulesIdentity, evaluate, payout_value, price_depth_fill, semantics_for,
    walk_ladder,
)

FIXTURES = Path(__file__).parent / "fixtures"
FACTS = json.loads((FIXTURES / "conformance" / "venue_facts_2026-09-25.json").read_text(encoding="utf-8"))


def _market(**over):
    base = dict(venue="kalshi", market_id="kalshi:KXHIGHNY-26SEP23-B69.5", native_id="KXHIGHNY-26SEP23-B69.5",
                event_id="e", outcome="69-70", payoff=Payoff("binary", D(1), "69-70"), rules_sha256="r",
                status=MarketStatus.OPEN, rules_resolved=True, rules_detail="ok")
    base.update(over)
    return Market(**base)


def test_a_legacy_market_reads_every_semantic_field_as_unknown():
    s = semantics_for(_market())
    assert s.legacy and not s.units.known and s.units.payout_per_unit is None  # Payoff.amount is not copied
    assert s.probability_meaning is ProbabilityMeaning.UNKNOWN and s.relation_tier is RelationTier.UNKNOWN
    assert s.source_family is None and s.finality is OutcomeFinality.UNKNOWN and s.rights is None
    assert s.rules.rules_sha256 == "r"


def test_semantics_never_change_a_frozen_opportunity_id():
    event = Event("weather", "e", "2026-09-23", None, "c", "s")
    quote = ExecutableQuote("kalshi", "kalshi:KXHIGHNY-26SEP23-B69.5", "YES", D("0.30"), D("0.35"), D(10),
                            "2026-09-23T21:58:00+00:00", None, "snap:1")
    policy = Policy("p", "point", D("0.01"), 1, timedelta(minutes=5), timedelta(hours=6), "flag")
    as_of = datetime(2026, 9, 23, 22, 0, tzinfo=timezone.utc)
    plain = evaluate(event=event, market=_market(), side="YES", quote=quote, estimate=None,
                     fee_schedule=get_fee_schedule("kalshi-quadratic-taker-v1"), policy=policy, as_of=as_of)
    semantics = ContractSemantics(
        KALSHI_BINARY_UNITS, RulesIdentity("r", "twc", "h", None),
        FeeSemantics("kalshi-quadratic-taker-v1", "2026-07-07", FeeRoundingScope.PER_FILL, "CONSERVATIVE_BOUND"),
        ProbabilityMeaning.MARKET_IMPLIED_PRICE, RelationTier.PARTITION_MEMBER, None,
        (ClockStamp(ClockKind.RECEIPT, "2026-09-23T21:58:00Z", D(1), None, "fetched_at_utc"),),
        OutcomeFinality.PENDING, DataRights(frozenset({"RESEARCH_ONLY"}), ("kalshi_public",)))
    rich = evaluate(event=event, market=_market(semantics=semantics), side="YES", quote=quote, estimate=None,
                    fee_schedule=get_fee_schedule("kalshi-quadratic-taker-v1"), policy=policy, as_of=as_of)
    assert rich.opportunity_id == plain.opportunity_id and rich.to_dict() == plain.to_dict()


def test_one_cent_contracts_convert_explicitly_and_never_as_dollar_contracts():
    assert payout_value(D(100), NOVIG_V3_UNITS) == D("1.00")
    assert payout_value(D(100), KALSHI_BINARY_UNITS) == D(100)
    assert "payout_per_unit" in (NOVIG_V3_UNITS.incompatibility(KALSHI_BINARY_UNITS) or "") or \
        "price_convention" in (NOVIG_V3_UNITS.incompatibility(KALSHI_BINARY_UNITS) or "")
    with pytest.raises(ValueError, match="off the native step"):
        payout_value(D("1.5"), NOVIG_V3_UNITS)
    assert payout_value(D("1.55"), KALSHI_BINARY_UNITS) == D("1.55")  # fractional Kalshi counts are kept
    with pytest.raises(ValueError, match="off the native step"):
        payout_value(D("1.555"), KALSHI_BINARY_UNITS)
    with pytest.raises(ValueError, match="UNKNOWN"):
        payout_value(D(1), semantics_for(_market()).units)


def test_stored_kalshi_books_hold_fractional_sizes_that_are_never_truncated():
    payload = json.loads((FIXTURES / "forward" / "orderbook_KXHIGHNY-26SEP23-B69.5.json").read_text(encoding="utf-8"))
    ladders = ladders_from_orderbook("KXHIGHNY-26SEP23-B69.5", payload, received_at_utc="2026-09-23T21:58:00Z",
                                     evidence_id="snap", depth_limit=None)
    sizes = [level.size for level in ladders["YES"].asks]
    assert D("771.60") in sizes and any(s != s.to_integral_value() for s in sizes)
    fill = walk_ladder(ladders["YES"], D(800))
    assert fill.status is DepthStatus.FILLABLE and any(t.size != t.size.to_integral_value() for t in fill.takes)
    cost, why = price_depth_fill(fill, get_fee_schedule("kalshi-quadratic-taker-v1"))
    assert cost is None and "fractional" in why  # no fee rule for a fractional fill is invented


def test_derived_rights_are_the_most_restrictive_union():
    odds = DataRights(frozenset({"RESEARCH_ONLY", "NO_REDISTRIBUTION"}), ("the_odds_api",))
    kalshi = DataRights(frozenset({"RESEARCH_ONLY"}), ("kalshi_public",))
    both = DataRights.inherit(odds, kalshi)
    assert both.restrictions == {"RESEARCH_ONLY", "NO_REDISTRIBUTION"} and both.sources == ("the_odds_api",
                                                                                           "kalshi_public")
    assert "UNKNOWN_RIGHTS" in DataRights.inherit(kalshi, None).restrictions


def test_probability_meaning_and_relation_tier_are_separate_vocabularies():
    assert {m.value for m in ProbabilityMeaning} >= {"PHYSICAL_ESTIMATE", "SPORTSBOOK_CONSENSUS",
                                                     "MARKET_IMPLIED_PRICE", "RISK_NEUTRAL_OPTION_QUANTITY",
                                                     "DETERMINISTIC_PAYOFF_BOUND", "UNKNOWN"}
    assert {t.value for t in RelationTier} >= {"EQUIVALENT", "CONDITIONAL_EQUIVALENT", "RELATED_NOT_EQUIVALENT",
                                               "COMPLEMENT", "PARTITION_MEMBER", "NESTED_THRESHOLD", "UNKNOWN"}
    assert not ({m.value for m in ProbabilityMeaning} & {t.value for t in RelationTier} - {"UNKNOWN"})


def test_the_dated_venue_facts_match_the_code_constants():
    facts = {f["id"]: f for f in FACTS["facts"]}
    assert "No venue endpoint" in FACTS["method"]
    assert facts["kalshi_fixed_point_quantities"]["status"] == "VERIFIED_FROM_DOCS"
    assert KALSHI_BINARY_UNITS.quantity_step == D("0.01") and KALSHI_BINARY_UNITS.verification == "VERIFIED_FROM_DOCS"
    assert NOVIG_V3_UNITS.payout_per_unit == D("0.01")
    assert "never checks it for uniqueness" in " ".join(facts["novig_placement_not_idempotent"]["quotes"])
    assert "UNVERIFIED" in facts["novig_public_book_qa_examples"]["status"]
    assert "UNVERIFIED" in facts["novig_environments"]["status"]


def test_kxnflgame_fees_stay_unsupported_until_verified():
    assert "KXNFLGAME" in {f["series"] for f in FACTS["fee_findings"]}
    assert type(schedule_for("kalshi", "KXNFLGAME")).__name__ == "UnsupportedFeeSchedule"
