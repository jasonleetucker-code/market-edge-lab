"""NWS Daily Climate Report (CLI) for Central Park, NY: collection and parsing.

The CLI product is issued several times per climate day:

- a *preliminary* report during the day ("VALID TODAY AS OF 0400 PM LOCAL TIME",
  section label TODAY), and
- a *final* report early the next morning (section label YESTERDAY),
- plus occasional corrections (WMO header suffix CCA/CCB/..., "...CORRECTED").

Kalshi's GLOBALTEMPERATURE terms use "the first official non-preliminary report", so
every issuance is kept and the parser records which kind each one is. Missing or
unparseable values stay None; they are never coerced to 0.

Sources (docs/SETTLEMENT.md):
- live: api.weather.gov/products/types/CLI/locations/NYC (recent issuances only)
- history: Iowa Environmental Mesonet AFOS archive (pil=CLINYC), a public re-serve of
  the same NWS text products, used for backfill.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from .http import Pacer, fetch, fetch_json_result
from .sources import get_source
from .storage import SnapshotStore

PARSER_VERSION = "1"
SOURCE = get_source("nws_cli_central_park")
API_LIST_URL = SOURCE.base_url
API_PRODUCT_URL = "https://api.weather.gov/products/{product_id}"
IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py"
IEM_PACER = Pacer(1.0)  # IEM asks for about one request per second
NWS_PACER = Pacer(0.5)

_TZ = {"EDT": timezone(timedelta(hours=-4)), "EST": timezone(timedelta(hours=-5))}
_WMO = re.compile(r"^(CDUS\d\d) (K\w{3}) (\d{6})(?: (CC[A-Z]|RR[A-Z]|AA[A-Z]))?\s*$", re.M)
_ISSUED = re.compile(
    r"^(\d{3,4}) (AM|PM) (EDT|EST) \w{3} (\w{3}) (\d{1,2}) (\d{4})\s*$", re.M
)
_SUMMARY = re.compile(r"\.\.\.THE (.+?) CLIMATE SUMMARY FOR (\w+) (\d{1,2}) (\d{4})\.\.\.")
_TEMP_BLOCK = re.compile(
    r"TEMPERATURE \(F\)\s*\n\s*(YESTERDAY|TODAY)\s*\n\s*MAXIMUM\s+(\S+)", re.M
)
_VALUE = re.compile(r"^(-?\d{1,3})R?$")  # "R" marks a new record; "MM" means missing


@dataclass(frozen=True)
class CliReport:
    station: str | None  # e.g. "CENTRAL PARK NY"
    climate_date: date | None  # the day the report summarizes
    kind: str | None  # "final" (YESTERDAY section) | "preliminary" (TODAY) | None
    max_temp_f: int | None
    issued_at_utc: datetime | None
    wmo_header: str | None  # e.g. "CDUS41 KOKX 220620"
    correction: str | None  # e.g. "CCA" when this issuance corrects an earlier one
    parser_version: str = PARSER_VERSION


def _issued(text: str) -> datetime | None:
    match = _ISSUED.search(text)
    if not match:
        return None
    hhmm, ampm, zone, mon, day, year = match.groups()
    hhmm = hhmm.zfill(4)
    hour, minute = int(hhmm[:2]), int(hhmm[2:])
    if not (1 <= hour <= 12 and 0 <= minute < 60):
        return None
    hour = hour % 12 + (12 if ampm == "PM" else 0)
    try:
        local = datetime.strptime(f"{year} {mon} {day} {hour} {minute}", "%Y %b %d %H %M")
    except ValueError:
        return None
    return local.replace(tzinfo=_TZ[zone]).astimezone(timezone.utc)


def parse_cli(text: str) -> CliReport:
    """Parse one CLI product. Every field that cannot be read is None."""
    wmo = _WMO.search(text)
    summary = _SUMMARY.search(text)
    block = _TEMP_BLOCK.search(text)

    climate_date = None
    station = None
    if summary:
        station = summary.group(1).strip()
        try:
            climate_date = datetime.strptime(
                f"{summary.group(2)} {summary.group(3)} {summary.group(4)}", "%B %d %Y"
            ).date()
        except ValueError:
            climate_date = None

    kind = None
    max_temp = None
    if block:
        label, raw = block.groups()
        preliminary_marker = "VALID TODAY AS OF" in text or "VALID AS OF" in text
        if label == "YESTERDAY" and not preliminary_marker:
            kind = "final"
        elif label == "TODAY":
            kind = "preliminary"
        value = _VALUE.match(raw)
        max_temp = int(value.group(1)) if value else None

    correction = None
    if wmo and wmo.group(4) and wmo.group(4).startswith("CC"):
        correction = wmo.group(4)
    elif "CLIMATE REPORT...CORRECTED" in text:
        correction = "CORRECTED"

    return CliReport(
        station=station,
        climate_date=climate_date,
        kind=kind,
        max_temp_f=max_temp,
        issued_at_utc=_issued(text),
        wmo_header=" ".join(wmo.groups()[:3]) if wmo else None,
        correction=correction,
    )


def split_afos_archive(text: str) -> list[str]:
    """Split an IEM AFOS text archive (products separated by \\x01) into products."""
    return [part.strip("\x03\n ") for part in text.split("\x01") if "CLIMATE REPORT" in part]


@dataclass(frozen=True)
class CliSettlement:
    value_f: int | None
    report: CliReport | None
    basis: str  # which contract rule selected the report, or why none was selected


def _eleven_am_et_next_day(climate_date: date) -> datetime:
    """11:00 AM US Eastern (EDT or EST as in effect) on the day after `climate_date`, in UTC."""
    next_day = climate_date + timedelta(days=1)
    offset = _TZ["EDT"] if _is_dst(next_day) else _TZ["EST"]
    return datetime(next_day.year, next_day.month, next_day.day, 11, 0, tzinfo=offset).astimezone(
        timezone.utc
    )


def _is_dst(day: date) -> bool:
    """US Eastern DST: second Sunday in March to first Sunday in November."""
    def nth_sunday(year: int, month: int, n: int) -> date:
        first = date(year, month, 1)
        return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))

    return nth_sunday(day.year, 3, 2) <= day < nth_sunday(day.year, 11, 1)


# The GLOBALTEMPERATURE contract was "initially ... listed after close-of-business on
# December 9, 2025" (certification filing). Target dates up to and including that day are
# evaluated under the NHIGH terms; later dates under GLOBALTEMPERATURE. Which document
# governed each KXHIGHNY event is an inference from these dates, not a captured fact.
GLOBALTEMPERATURE_FIRST_DATE = date(2025, 12, 10)


def contract_regime(climate_date: date) -> str:
    return "globaltemperature" if climate_date >= GLOBALTEMPERATURE_FIRST_DATE else "nhigh"


def settlement_value(
    reports: list[CliReport], climate_date: date, regime: str | None = None
) -> CliSettlement:
    """Select the CLI maximum that the applicable contract terms say decides settlement.

    Both regimes: a final report without a parseable maximum cannot be the value, so the
    first final report *with* data is used (GLOBALTEMPERATURE: "the first official
    non-preliminary report ... that includes the relevant data").

    NHIGH regime only (target dates through 2025-12-09): "Determination will be delayed
    until 11AM ET in the case of ... (2) the Final report high is lower than earlier
    report(s)." "Earlier report" means the latest preliminary issued before the first
    final (a correction supersedes the report it corrects). When that preliminary is
    higher, the latest final issued by 11:00 AM ET the next day is used. Condition (1),
    METAR inconsistency, needs METAR data we do not collect and is not applied.

    Returns value None, with the reason, whenever the evidence does not determine a value.
    """
    regime = regime or contract_regime(climate_date)
    day_reports = [r for r in reports if r.climate_date == climate_date and r.issued_at_utc]
    unclassified = [r for r in reports if r.climate_date == climate_date and r.kind is None]
    note = f"; {len(unclassified)} unclassified report(s) for this date ignored" if unclassified else ""
    finals = sorted(
        (r for r in day_reports if r.kind == "final" and r.max_temp_f is not None),
        key=lambda r: r.issued_at_utc,
    )
    if not finals:
        return CliSettlement(None, None, "no final CLI report with a maximum for this date" + note)
    first = finals[0]
    skipped = len([r for r in day_reports if r.kind == "final" and r.max_temp_f is None])
    basis = f"{regime}: first final report with data"
    if skipped:
        basis += f" ({skipped} earlier final report(s) without a maximum skipped)"

    if regime == "nhigh":
        earlier = sorted(
            (
                r for r in day_reports
                if r.kind == "preliminary" and r.max_temp_f is not None
                and r.issued_at_utc < first.issued_at_utc
            ),
            key=lambda r: r.issued_at_utc,
        )
        latest_preliminary = earlier[-1] if earlier else None
        if latest_preliminary and latest_preliminary.max_temp_f > first.max_temp_f:
            cutoff = _eleven_am_et_next_day(climate_date)
            eligible = [r for r in finals if r.issued_at_utc <= cutoff]
            if not eligible:
                return CliSettlement(
                    None, None,
                    "nhigh: delayed determination required but no final report by the "
                    f"{cutoff.isoformat()} cutoff" + note,
                )
            chosen = eligible[-1]
            return CliSettlement(
                chosen.max_temp_f,
                chosen,
                f"nhigh: delayed determination: first final ({first.max_temp_f}) lower than "
                f"latest earlier report ({latest_preliminary.max_temp_f}); latest final by "
                f"{cutoff.isoformat()} used" + note,
            )
    return CliSettlement(first.max_temp_f, first, basis + note)


def first_final(reports: list[CliReport], climate_date: date) -> CliReport | None:
    """The report selected by `settlement_value` (kept for callers wanting the report)."""
    return settlement_value(reports, climate_date).report


def _provenance() -> dict[str, str]:
    return {
        "source_id": SOURCE.source_id,
        "parser_version": PARSER_VERSION,
        "schema_version": SOURCE.schema_version,
    }


def collect_recent_cli(
    store: SnapshotStore,
    *,
    run_id: str,
    user_agent: str,
    anomalies: list[str] | None = None,
) -> dict[str, int]:
    """Store the CLI product list and every listed product not already stored.

    The NWS API keeps only recent issuances, so this must run regularly to keep all
    of them; history comes from `collect_cli_archive`.
    """
    anomalies = anomalies if anomalies is not None else []
    headers = {"User-Agent": user_agent, "Accept": "application/ld+json"}
    listing, listing_fetch = fetch_json_result(API_LIST_URL, headers=headers, pacer=NWS_PACER)
    store.save_snapshot(
        run_id=run_id, source=SOURCE.legacy_name, kind="cli_list", entity_id="NYC",
        url=API_LIST_URL, payload=listing, fetch=listing_fetch, **_provenance(),
    )
    graph = listing.get("@graph")
    if not isinstance(graph, list):
        raise ValueError("NWS CLI product list has no @graph array")
    counts = {"lists": 1, "products": 0, "already_stored": 0}
    for item in graph:
        product_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(product_id, str) or not product_id:
            anomalies.append("CLI list entry without id skipped")
            continue
        if store.has_snapshot(source=SOURCE.legacy_name, kind="cli_product", entity_id=product_id):
            counts["already_stored"] += 1
            continue
        url = API_PRODUCT_URL.format(product_id=product_id)
        product, product_fetch = fetch_json_result(url, headers=headers, pacer=NWS_PACER)
        report = parse_cli(product.get("productText") or "")
        if report.max_temp_f is None or report.climate_date is None:
            anomalies.append(f"CLI product {product_id} did not parse a max temperature/date")
        store.save_snapshot(
            run_id=run_id, source=SOURCE.legacy_name, kind="cli_product", entity_id=product_id,
            url=url, payload=product, fetch=product_fetch,
            source_timestamp_utc=product.get("issuanceTime"), **_provenance(),
        )
        counts["products"] += 1
    return counts


def iem_archive_url(start: date, end_exclusive: date) -> str:
    query = {
        "pil": "CLINYC",
        "sdate": start.isoformat(),
        "edate": end_exclusive.isoformat(),
        "fmt": "text",
        "limit": 9999,
    }
    return f"{IEM_URL}?{urlencode(query)}"


def collect_cli_archive(
    store: SnapshotStore,
    *,
    run_id: str,
    start: date,
    end_exclusive: date,
    user_agent: str,
    anomalies: list[str] | None = None,
) -> dict[str, int]:
    """Store the IEM CLINYC archive for a date range as an exact-bytes document."""
    anomalies = anomalies if anomalies is not None else []
    url = iem_archive_url(start, end_exclusive)
    result = fetch(url, headers={"User-Agent": user_agent, "Accept": "text/plain"}, pacer=IEM_PACER)
    store.save_document(
        run_id=run_id, source_id="iem_afos_clinyc", doc_type="nws_cli_archive_text", fetch=result
    )
    products = split_afos_archive(result.body.decode("utf-8", errors="replace"))
    if not products:
        anomalies.append(f"IEM archive {start}..{end_exclusive} contained no CLI products")
    return {"documents": 1, "products": len(products)}


def reports_from_payloads(payloads: list[dict[str, Any]]) -> list[CliReport]:
    """Parse stored NWS API product payloads."""
    return [parse_cli(p.get("productText") or "") for p in payloads]
