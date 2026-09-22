"""Gate 2 regression: reproduce recorded KXHIGHNY settlements from archived evidence.

Fixtures: IEM archives are exact bytes; market fixtures are the captured 2026-09-22 API
market objects filtered to the sample windows and re-serialized (see
experiments/EXP-001-kxhighny-nws-vs-market/gate2/). Windows are defined in SAMPLE.md.
"""

import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from edge_lab.nws_cli import parse_cli, split_afos_archive
from edge_lab.settlement_audit import audit, summarize

FIX = Path(__file__).parent / "fixtures" / "gate2"


def _load(markets, cli):
    ms = json.loads(gzip.decompress((FIX / markets).read_bytes()))
    text = gzip.decompress((FIX / cli).read_bytes()).decode()
    return ms, [parse_cli(p) for p in split_afos_archive(text)]


@pytest.fixture(scope="module")
def window_a():
    ms, cli = _load("kalshi_markets_window_a.json.gz", "iem_clinyc_2026-07-15_2026-09-23.txt.gz")
    start, end = date(2026, 7, 16), date(2026, 9, 21)
    sums, rows = audit(ms, cli, start=start, end=end)
    return sums, rows, summarize(sums, start, end)


@pytest.fixture(scope="module")
def window_b():
    ms, cli = _load("kalshi_markets_window_b.json.gz", "iem_clinyc_2025-01-01_2026-01-03.txt.gz")
    start, end = date(2025, 1, 1), date(2025, 12, 31)
    sums, rows = audit(ms, cli, start=start, end=end)
    return sums, rows, summarize(sums, start, end)


@pytest.fixture(scope="module")
def window_c():
    ms, cli = _load("kalshi_markets_window_c.json.gz", "iem_clinyc_2024-01-01_2025-01-03.txt.gz")
    start, end = date(2024, 1, 1), date(2024, 12, 31)
    sums, rows = audit(ms, cli, start=start, end=end)
    return sums, rows, summarize(sums, start, end, rows)


def test_window_c_fresh_validation_with_frozen_procedure(window_c):
    # Procedure frozen at 9f28602 before window C was evaluated (SAMPLE.md amendment 1).
    sums, rows, s = window_c
    assert s["events"] == 366 and s["missing_dates"] == []
    assert s["reproduced_from_nws_cli"] == 366
    assert s["reproduced_from_kalshi_value"] == 366 == s["events_with_kalshi_value"]
    assert s["kalshi_value_minus_nws_cli"] == {"0": 366}
    assert s["unresolved_events"] == [] and _wrong(rows) == []


def _wrong(rows):
    return [r for r in rows if r.expected_from_nws_cli != "unknown" and not r.match_nws_cli]


def test_window_a_every_day_reproduced(window_a):
    sums, rows, s = window_a
    assert s["events"] == 68 and s["missing_dates"] == []
    assert s["events_by_rules_source"] == {"nws_climatological_report_daily": 29, "the_weather_company": 39}
    assert s["reproduced_from_nws_cli"] == 68
    assert s["reproduced_from_kalshi_value"] == 68
    assert s["kalshi_value_minus_nws_cli"] == {"0": 68}
    assert s["events_not_exactly_one_yes"] == []
    assert _wrong(rows) == []


def test_window_b_held_out_year(window_b):
    sums, rows, s = window_b
    assert s["events"] == 365 and s["missing_dates"] == []
    assert s["reproduced_from_nws_cli"] == 361
    assert s["events_with_kalshi_value"] == 309
    assert s["reproduced_from_kalshi_value"] == 309
    assert s["kalshi_value_minus_nws_cli"] == {"0": 305}
    assert _wrong(rows) == []  # zero mis-predictions: every non-match is UNKNOWN
    # The only unresolved events are those whose final CLI is absent from the archive.
    assert s["unresolved_events"] == [
        "KXHIGHNY-25JUN02", "KXHIGHNY-25JUN03", "KXHIGHNY-25JUN18", "KXHIGHNY-25NOV13",
    ]
    for ev in sums:
        if ev.unresolved:
            assert ev.explanations == ["NWS CLI: no final CLI report with a maximum for this date"]


def test_bracket_rows_carry_rule_evidence(window_a):
    _, rows, _ = window_a
    assert all(r.rules_hash and r.rules_source != "unrecognized" for r in rows)
    assert {r.rules_source for r in rows if r.target_date >= "2026-08-14"} == {"the_weather_company"}
    assert {r.rules_source for r in rows if r.target_date <= "2026-08-13"} == {"nws_climatological_report_daily"}


def test_committed_audit_tables_are_current():
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts" / "gate2_audit.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


QUOTES = {
    "GLOBALTEMPERATURE_contract_terms.pypdf.txt": [
        "The Source Agencies are, in hierarchical order, National Weather Service",
        "Only the first official non-preliminary report published by the Source Agencies that includes the relevant data will be used for resolution.",
        "Contract resolution is based on the full precision reported by the Source Agency.",
        "If no data is available for <time period> by the Expiration Date, all strikes shall resolve to the last fair price",
        '"between" means within an inclusive range',
    ],
    "NHIGH_contract_terms.pypdf.txt": [
        "Determination will be delayed until 11AM ET in the case of either (1) High temperature is not consistent with 6-hr or 24-hr highs reported by METAR or (2) the Final report high is lower than earlier report(s).",
        "only encompasses Expiration Values that are strictly greater than <degrees>",
    ],
    "GLOBALTEMPERATURE_product_certification.pypdf.txt": [
        # Extraction interleaves the page header ("KalshiEX LLC KalshiEX LLC") after
        # "A new" at a page break; the unbroken remainder is checked.
        "Source Agency can be added via a Part 40 amendment.",
        "All instructions on how to access the Underlying are non-binding",
    ],
}


def test_settlement_quotes_appear_verbatim_in_deterministic_extractions():
    import re

    evidence = Path(__file__).resolve().parents[1] / "experiments" / "EXP-001-kxhighny-nws-vs-market" / "gate2" / "evidence"

    def norm(text):
        return re.sub(r"\s+", " ", text).strip()

    for name, quotes in QUOTES.items():
        text = norm((evidence / name).read_text())
        for quote in quotes:
            assert norm(quote) in text, (name, quote)


def test_evidence_pdfs_match_manifest_hashes():
    import hashlib

    evidence = Path(__file__).resolve().parents[1] / "experiments" / "EXP-001-kxhighny-nws-vs-market" / "gate2" / "evidence"
    manifest = (evidence / "MANIFEST.md").read_text()
    for pdf in evidence.glob("*.pdf"):
        assert hashlib.sha256(pdf.read_bytes()).hexdigest() in manifest, pdf.name
