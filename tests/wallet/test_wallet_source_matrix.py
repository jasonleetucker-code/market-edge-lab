"""W1: the source matrix document is complete and agrees with the typed matrix."""

from __future__ import annotations

import re
from pathlib import Path

from edge_lab.wallet_intel import polymarket_v2 as pm
from edge_lab.wallet_intel.observability import MATRIX, ExecutionEligibility, eligibility, first_source

DOC = Path(__file__).resolve().parents[2] / "docs" / "research" / "WALLET_SOURCE_MATRIX.md"
DIMENSIONS = ("Public vs private", "Identifiers and route", "Clocks and finality", "Proxy mappings",
              "Action taxonomy", "History and pagination", "Rules, fees, settlement",
              "Rights, eligibility, auth, cost", "Research vs execution")


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _rows(section: str) -> list[list[str]]:
    text = _text()
    start = text.index(section)
    end = text.find("\n## ", start + len(section))
    body = text[start: end if end != -1 else len(text)]
    return [[c.strip() for c in line.strip().strip("|").split("|")] for line in body.splitlines()
            if line.startswith("|") and not line.startswith("|---")][1:]


def test_every_source_covers_every_section_7_dimension_with_url_date_and_class():
    for source_id in MATRIX:
        rows = _rows(f"## Source: {source_id}")
        assert [r[0] for r in rows] == list(DIMENSIONS), source_id
        for dimension, finding, klass, url, retrieved in rows:
            assert klass in ("DOCUMENTED", "UNKNOWN"), (source_id, dimension)
            assert url.startswith("https://"), (source_id, dimension)
            assert retrieved == "2026-10-07" and finding, (source_id, dimension)


def test_polymarket_pins_have_url_date_and_class():
    rows = _rows("## Polymarket Data API v2 pins")
    assert len(rows) >= 18
    for number, fact, klass, url, retrieved in rows:
        assert re.fullmatch(r"P\d+", number) and klass in ("DOCUMENTED", "UNKNOWN")
        assert url.startswith("https://") and retrieved == "2026-10-07"
    assert "October 24, 2026" in _text() and pm.V1_RETIREMENT_DATE == "2026-10-24"


def test_doc_verdicts_match_the_typed_matrix_and_first_source():
    rows = {r[0]: r[1] for r in _rows("## Verdicts")}
    assert rows == {k: v.research_verdict for k, v in MATRIX.items()}
    assert first_source().source_id == "polymarket_data_api_v2"
    assert "**First source: Polymarket Data API v2**" in _text()


def test_no_source_permits_execution():
    for source_id, cap in MATRIX.items():
        assert cap.execution_permitted is False and cap.fixture_only is True
        assert eligibility(source_id).execution is ExecutionEligibility.BLOCKED_UNSUPPORTED
