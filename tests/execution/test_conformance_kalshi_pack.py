"""Conformance pack `kalshi-ordinary-v0` (#160 package B): the doc and the machine-readable profile agree, every fact
cites an official page and a retrieval date, and the profile's helpers refuse anything outside it."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from edge_lab.execution import conformance as c
from edge_lab.execution import kalshi_wire, signer, transport
from edge_lab.execution.model import Environment, ExactValueError, Grid, TimeInForce

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "execution" / "KALSHI_CONFORMANCE.md"
FIXTURES = ROOT / "tests" / "fixtures" / "kalshi_exec"
ALL_FACTS = c.PROFILE_FACTS + kalshi_wire.ENDPOINT_FACTS + signer.SIGNING_FACTS + transport.AUTH_HEADER_FACTS


def _doc_rows() -> dict[str, list[str]]:
    rows = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(cells) == 7 and re.fullmatch(r"[A-Z]{2,4}-\d{2}", cells[0]):
            assert cells[0] not in rows, f"{cells[0]} appears twice in the doc"
            rows[cells[0]] = cells
    return rows


def test_fact_ids_are_unique_across_modules():
    ids = [f.id for f in ALL_FACTS]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)
    assert len(ids) > 100


@pytest.mark.parametrize("fact", ALL_FACTS, ids=lambda f: f.id)
def test_every_code_fact_appears_in_the_doc_with_the_same_value_source_and_date(fact):
    rows = _doc_rows()
    assert fact.id in rows, f"{fact.id} is missing from {DOC.name}"
    _, _, value, support, evidence, source, retrieved = rows[fact.id]
    assert value.replace("\\|", "|") == fact.display(), fact.id
    assert support == fact.support.value, fact.id
    assert evidence.split(" ")[0] == fact.evidence.value, fact.id
    if fact.fixture:
        assert f"`{fact.fixture}`" in evidence, fact.id
    assert source == fact.source and retrieved == fact.retrieved == "2026-10-07", fact.id


def test_every_doc_fact_row_is_in_the_code():
    assert set(_doc_rows()) == {f.id for f in ALL_FACTS}


def test_every_fact_cites_an_official_page_that_the_doc_lists_as_read():
    doc = DOC.read_text(encoding="utf-8")
    read_section = doc.split("## Pages read on 2026-10-07", 1)[1]
    for fact in ALL_FACTS:
        assert fact.source.startswith("https://docs.kalshi.com/"), fact.id
        relative = fact.source.removeprefix("https://docs.kalshi.com/")
        page = relative.rsplit("/", 1)[1]
        assert f"`{page}`" in read_section or f"`{relative}`" in read_section, \
            f"{fact.id}: {relative} is not in the pages-read list"


def test_only_evidence_classes_possible_today_are_used():
    assert {f.evidence for f in ALL_FACTS} <= c.EVIDENCE_POSSIBLE_NOW
    assert not {c.Evidence.DEMO_OBSERVED, c.Evidence.PRODUCTION_READ_VERIFIED} & c.EVIDENCE_POSSIBLE_NOW


def test_fixture_tested_facts_name_existing_documentation_examples():
    readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
    tested = [f for f in ALL_FACTS if f.evidence is c.Evidence.FIXTURE_TESTED]
    assert tested
    for fact in tested:
        assert (FIXTURES / fact.fixture).is_file(), fact.id
        assert f"| `{fact.fixture}` | documentation-example | {fact.source} |" in readme, fact.id
        # the fixture really carries every field the fact says is required
        assert set(fact.value) <= set(json.loads((FIXTURES / fact.fixture).read_text(encoding="utf-8"))), fact.id


@pytest.mark.parametrize("kwargs", [dict(id="bad"), dict(source="https://example.com/x"), dict(retrieved="today"),
                                    dict(evidence=c.Evidence.FIXTURE_TESTED), dict(fixture="x.json")])
def test_a_malformed_fact_is_refused(kwargs):
    base = dict(id="ZZ-01", value="v", evidence=c.Evidence.DOCUMENTED, source="https://docs.kalshi.com/x")
    base.update(kwargs)
    with pytest.raises(ValueError):
        c.Fact(**base)


def test_unknown_and_unsupported_facts_are_listed_in_the_conflicts_or_excluded():
    doc = DOC.read_text(encoding="utf-8")
    conflicts = doc.split("## Conflicts and unknowns", 1)[1].split("## Pages read", 1)[0]
    for fact in ALL_FACTS:
        if fact.support is c.Support.UNKNOWN:
            assert f"`{fact.id}`" in conflicts, f"{fact.id} is UNKNOWN but not discussed under Conflicts and unknowns"


def test_hosts_per_environment_mirror_the_facts():
    facts = {f.id: f for f in c.PROFILE_FACTS}
    assert c.hosts_for(Environment.PRODUCTION) == facts["ENV-01"].value
    assert c.hosts_for(Environment.DEMO) == facts["ENV-02"].value
    assert c.API_PATH_PREFIX == facts["ENV-03"].value
    assert c.hosts_for(Environment.FIXTURE) == ("fixture.invalid",)  # RFC 2606: can never resolve
    assert not set(c.hosts_for(Environment.FIXTURE)) & (set(facts["ENV-01"].value) | set(facts["ENV-02"].value))
    with pytest.raises(ValueError):
        c.hosts_for("PRODUCTION")


def test_helper_constants_mirror_the_facts():
    wire = {f.id: f for f in kalshi_wire.ENDPOINT_FACTS}
    facts = {f.id: f for f in c.PROFILE_FACTS}
    assert {t.value for t in c.SUPPORTED_TIME_IN_FORCE} == set(wire["ORD-08"].value)
    assert c.REDUCE_ONLY_TIME_IN_FORCE == {TimeInForce.IMMEDIATE_OR_CANCEL}
    assert c.ORDER_STATUSES == wire["ORD-26"].value
    assert c.POSITION_SETTLEMENT_STATUSES == facts["ACC-06"].value
    assert (c.SUBACCOUNT_MIN, c.SUBACCOUNT_MAX) == facts["SUB-01"].value
    assert c.QUANTITY_STEP == facts["QTY-01"].value
    assert c.DEFAULT_TOKEN_COST == facts["RL-01"].value
    assert c.PAGE_LIMIT_MAX <= min(facts["PAG-01"].value[1], 100)
    tiers = {row.split(" ")[0]: tuple(int(x) for x in row.split(" ")[1].split("/")) for row in facts["RL-03"].value}
    assert {k: v[:2] for k, v in c.RATE_TIERS.items()} == tiers
    assert c.SELF_TRADE_PREVENTION in wire["ORD-10"].value
    assert c.DEFAULT_TIER == "basic"


def test_quantity_grid_has_no_default_maximum():
    grid = c.quantity_grid("250")
    assert grid == Grid(step=Decimal("0.01"), minimum=Decimal("0.01"), maximum=Decimal("250"))
    assert grid.check("2.55", name="q") == Decimal("2.55")
    with pytest.raises(ExactValueError):
        grid.check("2.555", name="q")
    with pytest.raises(TypeError):
        c.quantity_grid()  # type: ignore[call-arg]
    with pytest.raises(ExactValueError):
        c.quantity_grid(1.5)


def _market(**kw):
    record = json.loads((FIXTURES / "market_binary_active.json").read_text(encoding="utf-8"))
    record.update(kw)
    return record


def test_market_profile_reads_the_grid_from_the_record():
    m = c.MarketTradingProfile.from_market_record(_market())
    assert m.ticker == "HIGHNY-24JAN01-T60" and m.exchange_index == 0 and len(m.price_bands) == 3
    assert m.check_yes_price(Decimal("0.055")) == Decimal("0.055")  # edge band, 0.001 tick
    assert m.check_yes_price(Decimal("0.56")) == Decimal("0.56")
    assert m.check_yes_price(Decimal("0.10")) == Decimal("0.10")  # band boundary
    for bad in ("0.555", "0.0005", "0", "1", "1.01", "-0.5"):
        with pytest.raises((c.UnsupportedByProfile, ExactValueError)):
            m.check_yes_price(Decimal(bad))
    assert c.PRICE_GRID_FROM_MARKET_RECORD == "market.price_ranges"


@pytest.mark.parametrize("change", [
    {"market_type": "scalar"}, {"market_type": None}, {"status": "closed"}, {"status": "inactive"},
    {"settlement_bounds_type": "floor"}, {"settlement_bounds_type": None}, {"exchange_index": None},
    {"exchange_index": -1}, {"exchange_index": True}, {"exchange_index": "0"}, {"price_ranges": []},
    {"price_ranges": None}, {"price_ranges": [{"start": "0", "end": "1"}]},
    {"price_ranges": [{"start": 0.0, "end": "1.0000", "step": "0.0100"}]},
    {"price_ranges": [{"start": "0.0000", "end": "1.0000", "step": "0.0300"}]},
    {"price_ranges": [{"start": "0.5000", "end": "0.4000", "step": "0.0100"}]},
    {"price_ranges": [{"start": "0.0000", "end": "2.0000", "step": "0.0100"}]},
    {"ticker": ""},
])
def test_market_profile_refuses_anything_outside_the_ordinary_binary_profile(change):
    with pytest.raises(c.UnsupportedByProfile):
        c.MarketTradingProfile.from_market_record(_market(**change))


@pytest.mark.parametrize("kw", [dict(ticker=""), dict(exchange_index=-1), dict(exchange_index=None),
                                dict(price_bands=()), dict(price_bands=("0.01",))])
def test_a_market_profile_built_directly_is_still_checked(kw):
    args = dict(ticker="T", exchange_index=0, price_bands=(Grid(step=Decimal("0.01"), minimum=Decimal("0"),
                                                                  maximum=Decimal("1")),))
    args.update(kw)
    with pytest.raises(c.UnsupportedByProfile):
        c.MarketTradingProfile(**args)


def test_market_profile_refuses_a_missing_field_rather_than_defaulting():
    for key in ("market_type", "status", "settlement_bounds_type", "exchange_index", "price_ranges", "ticker"):
        record = _market()
        del record[key]
        with pytest.raises(c.UnsupportedByProfile):
            c.MarketTradingProfile.from_market_record(record)
