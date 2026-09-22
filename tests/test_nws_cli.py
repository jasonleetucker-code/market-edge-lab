"""CLI parsing and report selection against real archived NWS products (fixtures)."""

import gzip
from datetime import date
from pathlib import Path

import pytest

from edge_lab.nws_cli import parse_cli, settlement_value, split_afos_archive

FIX = Path(__file__).parent / "fixtures" / "gate2"


def _reports(name):
    text = gzip.decompress((FIX / name).read_bytes()).decode()
    return [parse_cli(p) for p in split_afos_archive(text)]


@pytest.fixture(scope="module")
def reports_2026():
    return _reports("iem_clinyc_2026-07-15_2026-09-23.txt.gz")


@pytest.fixture(scope="module")
def reports_2025():
    return _reports("iem_clinyc_2025-01-01_2026-01-03.txt.gz")


def test_final_report_fields(reports_2026):
    (r,) = [r for r in reports_2026 if r.wmo_header == "CDUS41 KOKX 220620"]
    assert r.station == "CENTRAL PARK NY"
    assert r.climate_date == date(2026, 9, 21)
    assert r.kind == "final" and r.max_temp_f == 72
    assert r.issued_at_utc.isoformat() == "2026-09-22T06:20:00+00:00"
    assert r.correction is None


def test_preliminary_report_is_labelled(reports_2026):
    (r,) = [r for r in reports_2026 if r.wmo_header == "CDUS41 KOKX 212040"]
    assert r.kind == "preliminary" and r.climate_date == date(2026, 9, 21)


def test_corrected_report_is_detected(reports_2026):
    (r,) = [r for r in reports_2026 if r.wmo_header == "CDUS41 KOKX 272148"]
    assert r.correction == "CCA"


def test_missing_maximum_is_none_not_zero(reports_2025):
    (r,) = [r for r in reports_2025 if r.wmo_header == "CDUS41 KOKX 220629"]
    assert r.kind == "final" and r.max_temp_f is None


def test_unparseable_text_yields_nones():
    r = parse_cli("garbage")
    assert (r.climate_date, r.kind, r.max_temp_f, r.issued_at_utc) == (None, None, None, None)


def test_first_final_with_data_skips_final_without_value(reports_2025):
    selection = settlement_value(reports_2025, date(2025, 2, 21))
    assert selection.value_f == 36
    assert "skipped" in selection.basis


def test_delayed_determination_when_final_is_lower_than_earlier_report(reports_2025):
    # Dec 3 2025: preliminary 41, first final 40 (06:33Z), re-issued final 41 (14:21Z).
    selection = settlement_value(reports_2025, date(2025, 12, 3))
    assert selection.value_f == 41
    assert selection.report.wmo_header == "CDUS41 KOKX 041421"
    assert "delayed determination" in selection.basis


def test_revision_after_cutoff_is_not_used():
    from datetime import datetime, timezone

    from edge_lab.nws_cli import CliReport

    def rep(kind, value, iso):
        return CliReport("CENTRAL PARK NY", date(2025, 12, 3), kind, value,
                         datetime.fromisoformat(iso).astimezone(timezone.utc), "H", None)

    reports = [
        rep("preliminary", 41, "2025-12-03T21:35:00+00:00"),
        rep("final", 40, "2025-12-04T06:33:00+00:00"),
        rep("final", 42, "2025-12-04T16:30:00+00:00"),  # after 11:00 AM EST (16:00Z)
    ]
    assert settlement_value(reports, date(2025, 12, 3)).value_f == 40


def test_no_final_report_is_unknown(reports_2025):
    selection = settlement_value(reports_2025, date(2025, 6, 2))
    assert selection.value_f is None and selection.report is None


def _rep(kind, value, iso, day=date(2025, 12, 3), header="H"):
    from datetime import datetime, timezone

    from edge_lab.nws_cli import CliReport

    return CliReport("CENTRAL PARK NY", day, kind, value,
                     datetime.fromisoformat(iso).astimezone(timezone.utc), header, None)


def test_contract_regime_follows_globaltemperature_listing_date():
    from edge_lab.nws_cli import contract_regime

    assert contract_regime(date(2025, 12, 9)) == "nhigh"
    assert contract_regime(date(2025, 12, 10)) == "globaltemperature"


def test_globaltemperature_regime_uses_first_final_even_if_lower():
    day = date(2026, 8, 27)
    reports = [
        _rep("preliminary", 81, "2026-08-27T20:30:00+00:00", day),
        _rep("final", 77, "2026-08-28T06:30:00+00:00", day),
        _rep("final", 78, "2026-08-28T12:00:00+00:00", day),
    ]
    selection = settlement_value(reports, day)
    assert selection.value_f == 77 and selection.basis.startswith("globaltemperature")


def test_correction_supersedes_the_preliminary_it_corrects():
    # Uncorrected preliminary 81, corrected preliminary 77, final 77: no delay triggered.
    reports = [
        _rep("preliminary", 81, "2025-12-03T20:40:00+00:00"),
        _rep("preliminary", 77, "2025-12-03T21:48:00+00:00"),
        _rep("final", 77, "2025-12-04T06:30:00+00:00"),
        _rep("final", 79, "2025-12-04T14:00:00+00:00"),
    ]
    selection = settlement_value(reports, date(2025, 12, 3))
    assert selection.value_f == 77 and "delayed" not in selection.basis


def test_delay_needed_but_no_final_before_cutoff_is_unknown():
    reports = [
        _rep("preliminary", 45, "2025-12-03T21:00:00+00:00"),
        _rep("final", 40, "2025-12-04T17:00:00+00:00"),  # after 11:00 AM EST (16:00Z)
    ]
    selection = settlement_value(reports, date(2025, 12, 3))
    assert selection.value_f is None and "cutoff" in selection.basis


def test_unclassified_reports_are_noted_not_silently_dropped():
    from edge_lab.nws_cli import CliReport

    reports = [
        _rep("final", 50, "2025-12-04T06:30:00+00:00"),
        CliReport("CENTRAL PARK NY", date(2025, 12, 3), None, 51, None, "X", None),
    ]
    assert "1 unclassified report" in settlement_value(reports, date(2025, 12, 3)).basis
