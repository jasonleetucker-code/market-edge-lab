"""PFM parser on real archived NWS products (fixtures) and edge cases."""

import gzip
from datetime import date, datetime, timezone
from pathlib import Path

from edge_lab.nws_pfm import extract, parse_pfm

FIX = Path(__file__).parent / "fixtures" / "gate3"


def _full():
    return gzip.decompress((FIX / "pfm_full_product_2024-03-10T2150Z.txt.gz").read_bytes()).decode()


def test_full_product_parses_central_park_block():
    f = parse_pfm(_full())
    assert f.wmo_header == "FOUS51 KOKX 102150"
    assert f.issued_utc == datetime(2024, 3, 10, 21, 50, tzinfo=timezone.utc)  # 550 PM EDT
    assert f.issued_local_zone == "EDT"
    assert f.max_by_date[date(2024, 3, 11)] == 50
    assert f.max_by_date[date(2024, 3, 12)] == 61
    assert f.min_by_date[date(2024, 3, 11)] == 36
    assert f.unaligned_values == 0


def test_extract_is_exact_substring_and_parses_identically():
    full = _full()
    ex = extract(full)
    for line in ex.splitlines():
        assert line == "" or line == "$$" or line in full.splitlines()
    a, b = parse_pfm(full), parse_pfm(ex)
    assert (a.issued_utc, a.max_by_date, a.min_by_date) == (b.issued_utc, b.max_by_date, b.min_by_date)


SYNTH = """FOUS51 KOKX 052050{suffix}
PFMOKX

NYZ072-061000-
Central Park-New York NY
40.78N  73.97W Elev. 16 ft
{local}

Date           01/05/25      Mon 01/06/25            Tue 01/07/25            Wed
EST 3hrly     16 19 22 01 04 07 10 13 16 19 22 01 04 07 10 13 16 19 22 01 04 07
UTC 3hrly     21 00 03 06 09 12 15 18 21 00 03 06 09 12 15 18 21 00 03 06 09 12
{row}
$$
"""


def _synth(row, local="350 PM EST Sun Jan 5 2025", suffix=""):
    return SYNTH.format(row=row, local=local, suffix=suffix)


def test_est_columns_max_at_19_min_at_07():
    row = "Min/Max                      25          38          27          41          30"
    f = parse_pfm(_synth(row))
    assert f.issued_utc == datetime(2025, 1, 5, 20, 50, tzinfo=timezone.utc)
    assert f.max_by_date == {date(2025, 1, 6): 38, date(2025, 1, 7): 41}
    assert f.min_by_date == {date(2025, 1, 6): 25, date(2025, 1, 7): 27, date(2025, 1, 8): 30}


def test_missing_value_stays_missing():
    row = "Min/Max                      25                      27          41          30"
    f = parse_pfm(_synth(row))
    assert date(2025, 1, 6) not in f.max_by_date and f.max_by_date[date(2025, 1, 7)] == 41


def test_misaligned_value_is_not_read():
    row = "Min/Max                      25         38           27          41          30"
    f = parse_pfm(_synth(row))
    assert date(2025, 1, 6) not in f.max_by_date and f.unaligned_values >= 1


def test_header_and_local_time_disagreement_is_ambiguous():
    f = parse_pfm(_synth("Min/Max                      25          38", local="351 PM EST Sun Jan 5 2025"))
    assert f.issued_utc is None


def test_correction_suffix_is_recorded():
    f = parse_pfm(_synth("Min/Max                      25          38", suffix=" CCA"))
    assert f.correction == "CCA"


def test_no_central_park_block_returns_none():
    assert parse_pfm("FOUS51 KOKX 052050\nPFMOKX\n\nNYZ176-061000-\nLaGuardia\n$$\n") is None


def test_wmo_header_trailing_local_line_uses_header_time():
    # 350 PM EST = 20:50Z; header 2051 is one minute later (common in the archive).
    f = parse_pfm(_synth("Min/Max                      25          38").replace("052050", "052051"))
    assert f.issued_utc == datetime(2025, 1, 5, 20, 51, tzinfo=timezone.utc)
    assert f.max_by_date == {date(2025, 1, 6): 38}


def test_wmo_header_beyond_tolerance_is_ambiguous():
    f = parse_pfm(_synth("Min/Max                      25          38").replace("052050", "052106"))
    assert f.issued_utc is None and f.max_by_date == {}


def test_wmo_header_before_local_line_is_ambiguous():
    f = parse_pfm(_synth("Min/Max                      25          38").replace("052050", "052049"))
    assert f.issued_utc is None


def test_wmo_header_across_month_end():
    text = _synth("Min/Max                      25          38", local="758 PM EST Fri Jan 31 2025")
    text = text.replace("052050", "010059").replace("01/05/25", "01/31/25")
    f = parse_pfm(text)
    assert f.issued_utc == datetime(2025, 2, 1, 0, 59, tzinfo=timezone.utc)


# Real pre-March-2017 layout (upper case labels; IEM copy repeats the zone header).
OLD = """FOUS51 KOKX 152333
PFMOKX

POINT FORECAST MATRICES
NATIONAL WEATHER SERVICE NEW YORK NY
633 PM EST SUN JAN 15 2017

NYZ072-160900-
CENTRAL PARK-NEW YORK NY
40.78N  73.97W ELEV. 16 FT
633 PM EST
NYZ072-160900-
CENTRAL PARK-NEW YORK NY
40.78N  73.97W ELEV. 16 FT
633 PM EST SUN JAN 15 2017

DATE           01/15/17      MON 01/16/17            TUE 01/17/17            WED
EST 3HRLY     16 19 22 01 04 07 10 13 16 19 22 01 04 07 10 13 16 19 22 01 04 07
UTC 3HRLY     21 00 03 06 09 12 15 18 21 00 03 06 09 12 15 18 21 00 03 06 09 12

MIN/MAX                      27          42          36          40          40
TEMP             34 32 29 28 27 32 40 42 40 39 38 37 36 34 38 40 40 40 43 44 44
$$
"""


def test_old_upper_case_layout_parses_and_extract_keeps_it():
    f = parse_pfm(OLD)
    assert f.issued_utc == datetime(2017, 1, 15, 23, 33, tzinfo=timezone.utc)
    assert f.max_by_date == {date(2017, 1, 16): 42, date(2017, 1, 17): 40}
    assert f.min_by_date == {date(2017, 1, 16): 27, date(2017, 1, 17): 36, date(2017, 1, 18): 40}
    ex = extract(OLD)
    assert "MIN/MAX" in ex and "DATE" in ex and "TEMP" not in ex
    g = parse_pfm(ex)
    assert (g.issued_utc, g.max_by_date, g.min_by_date) == (f.issued_utc, f.max_by_date, f.min_by_date)
