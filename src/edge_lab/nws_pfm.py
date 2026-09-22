"""NWS Point Forecast Matrices (PFM) for Central Park, NY: parse forecasts as issued.

The NWS New York office (OKX) issues `PFMOKX` several times a day. Its `NYZ072 Central
Park-New York NY` block tabulates the official forecast by local time. The `Min/Max` (or
`Max/Min`) row gives 12-hour extremes: the daytime maximum (7 AM–7 PM local standard time)
is printed in the column of the period's last hour (19 EST / 20 EDT); the overnight
minimum in the 07 EST / 08 EDT column. Values are right-aligned to their hour column.
We verified that every value in the sample archive aligns exactly to an hour token.

Parsing is positional and deterministic. A value that does not align to an hour column,
or sits in an unexpected column, is not read (it stays None). Nothing is inferred.

Archive: Iowa Environmental Mesonet AFOS (pil=PFMOKX), a public re-serve of NWS text
products (docs/decisions/0011-...).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

PARSER_VERSION = "1"
ZONE = "NYZ072"
POINT_NAME = "Central Park-New York NY"

_TZ = {"EDT": timezone(timedelta(hours=-4)), "EST": timezone(timedelta(hours=-5))}
_WMO = re.compile(r"^(FOUS\d\d) (K\w{3}) (\d{6})(?: ([A-Z]{3}))?\s*$", re.M)
_ISSUED = re.compile(
    r"^(\d{3,4}) (AM|PM) (EDT|EST) \w{3} (\w{3}) +(\d{1,2}) (\d{4})\s*$", re.M
)
_HOURS = re.compile(r"^(EDT|EST) (3|6)hrly")
_EXTREMES = re.compile(r"^(Min/Max|Max/Min)")
# Column of the period's last hour for daytime max / overnight min, per local zone.
_MAX_HOUR = {"EST": 19, "EDT": 20}
_MIN_HOUR = {"EST": 7, "EDT": 8}


@dataclass(frozen=True)
class PfmForecast:
    wmo_header: str | None  # e.g. "FOUS51 KOKX 102150"
    correction: str | None  # e.g. "CCA" when the header carries a correction suffix
    issued_utc: datetime | None  # from the local issuance line (DST-explicit)
    issued_local_zone: str | None  # "EDT" | "EST"
    max_by_date: dict[date, int] = field(default_factory=dict)
    min_by_date: dict[date, int] = field(default_factory=dict)
    unaligned_values: int = 0
    parser_version: str = PARSER_VERSION


def _parse_issued(text: str) -> tuple[datetime | None, str | None]:
    match = _ISSUED.search(text)
    if not match:
        return None, None
    hhmm, ampm, zone, mon, day, year = match.groups()
    hhmm = hhmm.zfill(4)
    hour, minute = int(hhmm[:2]), int(hhmm[2:])
    if not (1 <= hour <= 12 and 0 <= minute < 60):
        return None, zone
    hour = hour % 12 + (12 if ampm == "PM" else 0)
    try:
        local = datetime.strptime(f"{year} {mon} {day} {hour} {minute}", "%Y %b %d %H %M")
    except ValueError:
        return None, zone
    return local.replace(tzinfo=_TZ[zone]).astimezone(timezone.utc), zone


def _wmo_consistent(wmo_ddhhmm: str, issued_utc: datetime) -> bool:
    """WMO header day/hour/minute (UTC) must match the local issuance line (±1 day wrap)."""
    try:
        dd, hh, mm = int(wmo_ddhhmm[:2]), int(wmo_ddhhmm[2:4]), int(wmo_ddhhmm[4:])
    except ValueError:
        return False
    return (issued_utc.day, issued_utc.hour, issued_utc.minute) == (dd, hh, mm)


def zone_block(text: str, zone: str = ZONE) -> str | None:
    """The zone's block, from its UGC line up to the `$$` terminator."""
    match = re.search(rf"^{zone}-[^\n]*\n.*?(?=^\$\$)", text, re.S | re.M)
    return match.group(0) if match else None


def _first_date(date_line: str, issued: date) -> date | None:
    """Date of the first column: the first `MM/DD/YY` or `MM/DD` token on the Date line."""
    match = re.search(r"(\d\d)/(\d\d)(?:/(\d\d))?", date_line[5:])
    if not match:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    year = 2000 + int(match.group(3)) if match.group(3) else issued.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    if not match.group(3) and candidate < issued - timedelta(days=180):
        candidate = date(year + 1, month, day)  # section starting in the next year
    return candidate


def _sections(block: str):
    """Yield (date_line, hours_line, extremes_line) for each tabular section."""
    lines = block.splitlines()
    for i, line in enumerate(lines):
        if not _HOURS.match(line):
            continue
        date_line = next((lines[j] for j in range(i - 1, -1, -1) if lines[j].startswith("Date")), None)
        extremes = next(
            (lines[j] for j in range(i + 1, min(i + 6, len(lines))) if _EXTREMES.match(lines[j])),
            None,
        )
        if date_line and extremes:
            yield date_line, line, extremes


def parse_pfm(text: str, zone: str = ZONE) -> PfmForecast | None:
    """Parse one PFM product (or an extract containing its header and zone lines)."""
    wmo = _WMO.search(text)
    block = zone_block(text, zone)
    if block is None:
        return None
    issued_utc, local_zone = _parse_issued(block)
    if issued_utc is not None and wmo and not _wmo_consistent(wmo.group(3), issued_utc):
        issued_utc = None  # ambiguous: header and local line disagree; refuse to guess
    correction = wmo.group(4) if wmo and wmo.group(4) and wmo.group(4).startswith("CC") else None

    forecast = PfmForecast(
        wmo_header=" ".join(wmo.groups()[:3]) if wmo else None,
        correction=correction,
        issued_utc=issued_utc,
        issued_local_zone=local_zone,
    )
    if issued_utc is None or local_zone is None:
        return forecast

    issued_local_date = issued_utc.astimezone(_TZ[local_zone]).date()
    unaligned = 0
    for date_line, hours_line, extremes in _sections(block):
        zone_name = hours_line[:3]
        hour_cols = [(m.end() + 10, int(m.group())) for m in re.finditer(r"\d\d", hours_line[10:])]
        start = _first_date(date_line, issued_local_date)
        if start is None or not hour_cols:
            continue
        col_date: dict[int, tuple[date, int]] = {}
        current, previous = start, None
        for end, hour in hour_cols:
            if previous is not None and hour <= previous:
                current += timedelta(days=1)
            col_date[end] = (current, hour)
            previous = hour
        for m in re.finditer(r"-?\d+", extremes[8:]):
            end = m.end() + 8
            if end not in col_date:
                unaligned += 1
                continue
            day, hour = col_date[end]
            value = int(m.group())
            if hour == _MAX_HOUR[zone_name]:
                forecast.max_by_date.setdefault(day, value)
            elif hour == _MIN_HOUR[zone_name]:
                forecast.min_by_date.setdefault(day, value)
            else:
                unaligned += 1
    return PfmForecast(
        wmo_header=forecast.wmo_header,
        correction=forecast.correction,
        issued_utc=forecast.issued_utc,
        issued_local_zone=forecast.issued_local_zone,
        max_by_date=forecast.max_by_date,
        min_by_date=forecast.min_by_date,
        unaligned_values=unaligned,
    )


def split_products(archive_text: str) -> list[str]:
    """Split an IEM AFOS archive (\\x01-separated) into PFM products."""
    return [part.strip("\x03\n ") for part in archive_text.split("\x01") if "PFMOKX" in part]


_KEEP = re.compile(r"^(Date|EDT |EST |UTC |Min/Max|Max/Min)")


def extract(product: str, zone: str = ZONE) -> str | None:
    """Exact-substring evidence extract: product header lines + the zone lines the parser
    reads (UGC, name, issuance, Date/hours/UTC/extremes rows), each copied verbatim."""
    block = zone_block(product, zone)
    if block is None:
        return None
    head = product.split(f"{zone}-", 1)[0]
    header_lines = [l for l in head.splitlines() if _WMO.match(l) or l.startswith("PFM")]
    block_lines = block.splitlines()
    kept = block_lines[:4] + [l for l in block_lines[4:] if _KEEP.match(l)]
    return "\n".join(header_lines + [""] + kept + ["$$"])


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
