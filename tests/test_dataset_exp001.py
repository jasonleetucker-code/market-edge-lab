"""Point-in-time selection: nothing issued after the cutoff can reach a row."""

from datetime import date, datetime, timedelta, timezone

import pytest

from edge_lab.dataset_exp001 import (
    COLUMNS, Issuance, KalshiEvent, build_rows, decision_time, eastern_to_utc, manifest,
    select_forecast, split_of, to_csv,
)
from edge_lab.nws_cli import CliReport
from edge_lab.nws_pfm import PfmForecast

D = date(2025, 1, 6)
UTC = timezone.utc


def iss(issued, value=40, day=D, correction=None, sha="a"):
    f = PfmForecast("FOUS51 KOKX X", correction, issued, "EST", {day: value}, {}, 0)
    return Issuance(f, sha + issued.isoformat(), "x" + sha)


def cli(day=D, value=41):
    return CliReport("CENTRAL PARK NY", day, "final", value,
                     datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC).replace(hour=6), "CDUS41", None)


def test_decision_time_handles_dst():
    assert decision_time(date(2025, 1, 6))[1] == datetime(2025, 1, 5, 23, 0, tzinfo=UTC)  # EST
    assert decision_time(date(2024, 7, 5))[1] == datetime(2024, 7, 4, 22, 0, tzinfo=UTC)  # EDT
    # D-1 = 2024-03-10 is the spring-forward day; 18:00 that evening is EDT.
    assert decision_time(date(2024, 3, 11))[1] == datetime(2024, 3, 10, 22, 0, tzinfo=UTC)
    # D-1 = 2024-11-03 is the fall-back day; 18:00 is EST.
    assert decision_time(date(2024, 11, 4))[1] == datetime(2024, 11, 3, 23, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        eastern_to_utc(datetime(2006, 7, 1, 18))


def test_latest_issuance_before_cutoff_is_chosen_and_later_ones_ignored():
    cutoff = decision_time(D)[1] - timedelta(minutes=30)  # 22:30Z
    early = iss(datetime(2025, 1, 5, 8, 30, tzinfo=UTC), 38, sha="e")
    main = iss(datetime(2025, 1, 5, 20, 50, tzinfo=UTC), 40, sha="m")
    at_cutoff = iss(cutoff, 41, sha="c")
    late = iss(cutoff + timedelta(minutes=1), 45, sha="l")  # 1 minute too late
    chosen, reason, after = select_forecast([late, early, main, at_cutoff], D, cutoff)
    assert chosen is at_cutoff and reason is None and after == 1


def test_correction_issued_after_cutoff_never_replaces_original():
    cutoff = decision_time(D)[1] - timedelta(minutes=30)
    original = iss(datetime(2025, 1, 5, 20, 50, tzinfo=UTC), 40, sha="o")
    correction = iss(cutoff + timedelta(hours=1), 44, correction="CCA", sha="k")
    chosen, _, after = select_forecast([original, correction], D, cutoff)
    assert chosen is original and after == 1


def test_stale_and_missing_forecasts_are_excluded_with_reasons():
    cutoff = decision_time(D)[1] - timedelta(minutes=30)
    old = iss(cutoff - timedelta(hours=25), 40)
    assert select_forecast([old], D, cutoff)[1] == "PFM_STALE_AT_CUTOFF"
    assert select_forecast([], D, cutoff)[1] == "NO_PFM_BEFORE_CUTOFF"


def _rows(issuances, reports, events=None):
    return build_rows(issuances, reports, events or {}, start=D, end=D)


def test_row_links_provenance_and_has_no_market_prices():
    (row,) = _rows([iss(datetime(2025, 1, 5, 20, 50, tzinfo=UTC), 40)], [cli()])
    assert row["usable"] == "true" and row["forecast_max_f"] == 40 and row["label_f"] == 41
    assert row["forecast_product_sha256"] and row["forecast_extract_sha256"] and row["nws_cli_wmo_header"]
    assert row["label_source"] == "nws_cli_contract_rule"
    assert row["market_price_available"] == "false"
    assert not [c for c in COLUMNS if any(k in c for k in ("price", "bid", "ask")) and c != "market_price_available"]


def test_kalshi_value_is_label_and_conflict_is_excluded():
    ev = {D: KalshiEvent("KXHIGHNY-25JAN06", "41.00", "nws_climatological_report_daily", "h")}
    (row,) = _rows([iss(datetime(2025, 1, 5, 20, 50, tzinfo=UTC))], [cli(value=41)], ev)
    assert row["label_source"] == "kalshi_expiration_value" and row["usable"] == "true"
    (row,) = _rows([iss(datetime(2025, 1, 5, 20, 50, tzinfo=UTC))], [cli(value=39)], ev)
    assert row["exclusion_reason"] == "KALSHI_CLI_CONFLICT" and row["usable"] == "false"


def test_missing_label_is_excluded_not_zero():
    (row,) = _rows([iss(datetime(2025, 1, 5, 20, 50, tzinfo=UTC))], [])
    assert row["exclusion_reason"] == "NO_SETTLEMENT_LABEL" and row["label_f"] == ""


def test_every_day_gets_a_row_and_output_is_deterministic():
    start, end = date(2025, 1, 1), date(2025, 1, 10)
    issuances = [iss(datetime(2025, 1, 5, 20, 50, tzinfo=UTC))]
    a = build_rows(issuances, [cli()], {}, start=start, end=end)
    b = build_rows(list(reversed(issuances)), [cli()], {}, start=start, end=end)
    assert len(a) == 10 and to_csv(a) == to_csv(b)
    assert all(r["exclusion_reason"] for r in a if r["usable"] == "false")
    m1 = manifest(a, to_csv(a), {"in": "1"})
    m2 = manifest(a, to_csv(a), {"in": "2"})
    assert m1["dataset_sha256"] == m2["dataset_sha256"] and m1["input_sha256"] != m2["input_sha256"]


def test_splits_are_chronological_and_contiguous():
    assert split_of(date(2022, 12, 31)) == "train" and split_of(date(2023, 1, 1)) == "validation"
    assert split_of(date(2024, 12, 31)) == "validation" and split_of(date(2025, 1, 1)) == "test"
    assert split_of(date(2016, 12, 31)) is None
