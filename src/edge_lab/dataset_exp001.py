"""EXP-001 point-in-time dataset: one row per target date (the independence unit).

For each target date D the row records what the hypothetical strategy could have known at
the fixed decision time, and the settlement label, with provenance for both. No market
prices: historical executable order books do not exist before 2026-09-22.

Decision time (ADR 0010): 18:00 America/New_York on D-1.
Availability: the latest PFMOKX issuance whose issuance time is <= decision - 30 min,
contains a Central Park maximum for D, and was issued within 24 h of that cutoff.
Nothing issued later is ever considered. Suffixed (CCx/RRx/AAx) products are never used.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from .nws_cli import CliReport, contract_regime, settlement_value, _is_dst
from .nws_pfm import PARSER_VERSION as PFM_PARSER_VERSION, PfmForecast

BUILDER_VERSION = "2"
DECISION_LOCAL_HOUR = 18  # on D-1, America/New_York
AVAILABILITY_BUFFER = timedelta(minutes=30)
MAX_FORECAST_AGE = timedelta(hours=24)  # older than this at the cutoff = stale
PRIOR_GAP = timedelta(hours=12)  # "prior" issuance for the revision field

SPLITS = (
    ("train", date(2017, 1, 1), date(2022, 12, 31)),
    ("validation", date(2023, 1, 1), date(2024, 12, 31)),
    ("test", date(2025, 1, 1), date(2026, 9, 21)),
)
FIRST_DATE, LAST_DATE = SPLITS[0][1], SPLITS[-1][2]

COLUMNS = (
    "target_date", "split", "event_ticker", "rules_source", "rules_hash", "contract_regime",
    "decision_local", "decision_utc", "availability_cutoff_utc",
    "forecast_source", "forecast_wmo_header", "forecast_correction", "forecast_issued_utc",
    "forecast_available_utc", "forecast_lead_hours", "forecast_max_f",
    "prior_forecast_wmo_header", "prior_forecast_issued_utc", "prior_forecast_max_f",
    "forecast_product_sha256", "forecast_extract_sha256", "pfm_parser_version",
    "issuances_after_cutoff_ignored",
    "label_f", "label_source", "kalshi_expiration_value", "nws_cli_value_f", "nws_cli_basis",
    "nws_cli_wmo_header", "nws_cli_issued_utc",
    "market_price_available", "usable", "exclusion_reason",
)


def split_of(day: date) -> str | None:
    for name, start, end in SPLITS:
        if start <= day <= end:
            return name
    return None


def eastern_to_utc(local: datetime) -> datetime:
    """America/New_York wall time -> UTC using the US rule in force since 2007.
    18:00 is never inside a DST transition hour, so it is unambiguous."""
    if local.year < 2007:
        raise ValueError("DST rule implemented for 2007 onwards only")
    offset = timedelta(hours=-4) if _is_dst(local.date()) else timedelta(hours=-5)
    return local.replace(tzinfo=timezone(offset)).astimezone(timezone.utc)


def decision_time(target: date) -> tuple[datetime, datetime]:
    """(local naive, UTC) decision timestamps for target date D."""
    local = datetime.combine(target - timedelta(days=1), datetime.min.time()).replace(hour=DECISION_LOCAL_HOUR)
    return local, eastern_to_utc(local)


@dataclass(frozen=True)
class Issuance:
    forecast: PfmForecast
    product_sha256: str
    extract_sha256: str


@dataclass(frozen=True)
class KalshiEvent:
    event_ticker: str
    expiration_value: str | None
    rules_source: str
    rules_hash: str
    value_conflict: bool = False  # the event's markets report different expiration values


def select_forecast(issuances: list[Issuance], target: date, cutoff: datetime):
    """Latest issuance with a max for `target`, issued in (cutoff - 24h, cutoff].

    Returns (chosen | None, reason | None, n_ignored_after_cutoff)."""
    eligible, after = [], 0
    for iss in issuances:
        f = iss.forecast
        if f.issued_utc is None or target not in f.max_by_date:
            continue
        if f.issued_utc > cutoff:
            after += 1
            continue
        eligible.append(iss)
    if not eligible:
        return None, "NO_PFM_BEFORE_CUTOFF", after
    latest = max(i.forecast.issued_utc for i in eligible)
    tied = sorted((i for i in eligible if i.forecast.issued_utc == latest), key=lambda i: i.product_sha256)
    chosen = tied[0]
    if len({i.forecast.max_by_date[target] for i in tied}) > 1:
        # Two products with the same issuance minute disagree: which one a trader saw
        # last is unknowable, so refuse to pick.
        return None, "CONFLICTING_SIMULTANEOUS_ISSUANCES", after
    if cutoff - chosen.forecast.issued_utc > MAX_FORECAST_AGE:
        return None, "PFM_STALE_AT_CUTOFF", after
    return chosen, None, after


def build_rows(
    issuances: Iterable[Issuance],
    cli_reports: Iterable[CliReport],
    kalshi_events: dict[date, KalshiEvent],
    *,
    start: date = FIRST_DATE,
    end: date = LAST_DATE,
) -> list[dict[str, Any]]:
    issuances = list(issuances)
    reports = list(cli_reports)
    # Index issuances by the dates they forecast, to keep selection linear.
    by_target: dict[date, list[Issuance]] = {}
    for iss in issuances:
        for d in iss.forecast.max_by_date:
            by_target.setdefault(d, []).append(iss)
    rows = []
    day = start
    while day <= end:
        local, utc = decision_time(day)
        cutoff = utc - AVAILABILITY_BUFFER
        chosen, reason, after = select_forecast(by_target.get(day, []), day, cutoff)
        prior = None
        if chosen is not None:
            prior, _, _ = select_forecast(by_target.get(day, []), day, chosen.forecast.issued_utc - PRIOR_GAP)
        cli = settlement_value(reports, day)
        ev = kalshi_events.get(day)
        kalshi_value = ev.expiration_value if ev else None
        label, label_source = None, None
        if kalshi_value not in (None, ""):
            label, label_source = int(float(kalshi_value)), "kalshi_expiration_value"
        elif cli.value_f is not None:
            label, label_source = cli.value_f, "nws_cli_contract_rule"
        if reason is None and ev is not None and ev.value_conflict:
            reason = "KALSHI_VALUE_INCONSISTENT"
        if reason is None and label is None:
            reason = "NO_SETTLEMENT_LABEL"
        if (
            reason is None and kalshi_value not in (None, "") and cli.value_f is not None
            and int(float(kalshi_value)) != cli.value_f
        ):
            reason = "KALSHI_CLI_CONFLICT"
        f = chosen.forecast if chosen else None
        # 00:00 local on D has the UTC offset in force on D-1 (US transitions happen at
        # 02:00), so use D-1's DST state rather than D's.
        midnight = datetime.combine(day, datetime.min.time()).replace(
            tzinfo=timezone(timedelta(hours=-4) if _is_dst(day - timedelta(days=1)) else timedelta(hours=-5))
        ).astimezone(timezone.utc)
        rows.append({
            "target_date": day.isoformat(),
            "split": split_of(day),
            "event_ticker": ev.event_ticker if ev else "",
            "rules_source": ev.rules_source if ev else "",
            "rules_hash": ev.rules_hash if ev else "",
            "contract_regime": contract_regime(day),
            "decision_local": local.isoformat() + " America/New_York",
            "decision_utc": utc.isoformat(),
            "availability_cutoff_utc": cutoff.isoformat(),
            "forecast_source": "iem_afos_pfmokx" if f else "",
            "forecast_wmo_header": f.wmo_header if f else "",
            "forecast_correction": (f.correction or "") if f else "",
            "forecast_issued_utc": f.issued_utc.isoformat() if f else "",
            "forecast_available_utc": (f.issued_utc + AVAILABILITY_BUFFER).isoformat() if f else "",
            "forecast_lead_hours": f"{(midnight - f.issued_utc).total_seconds() / 3600:.2f}" if f else "",
            "forecast_max_f": f.max_by_date[day] if f else "",
            "prior_forecast_wmo_header": prior.forecast.wmo_header if prior else "",
            "prior_forecast_issued_utc": prior.forecast.issued_utc.isoformat() if prior else "",
            "prior_forecast_max_f": prior.forecast.max_by_date[day] if prior else "",
            "forecast_product_sha256": chosen.product_sha256 if chosen else "",
            "forecast_extract_sha256": chosen.extract_sha256 if chosen else "",
            "pfm_parser_version": PFM_PARSER_VERSION,
            "issuances_after_cutoff_ignored": after,
            "label_f": label if label is not None else "",
            "label_source": label_source or "",
            "kalshi_expiration_value": kalshi_value or "",
            "nws_cli_value_f": cli.value_f if cli.value_f is not None else "",
            "nws_cli_basis": cli.basis,
            "nws_cli_wmo_header": cli.report.wmo_header if cli.report else "",
            "nws_cli_issued_utc": cli.report.issued_at_utc.isoformat() if cli.report and cli.report.issued_at_utc else "",
            "market_price_available": "false",
            "usable": "true" if reason is None else "false",
            "exclusion_reason": reason or "",
        })
        day += timedelta(days=1)
    return rows


def to_csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def manifest(rows: list[dict[str, Any]], csv_text: str, inputs: dict[str, str]) -> dict[str, Any]:
    from collections import Counter

    by_reason = Counter(r["exclusion_reason"] or "USABLE" for r in rows)
    by_split = Counter((r["split"], r["usable"]) for r in rows)
    return {
        "dataset_id": "EXP-001-pit-v" + BUILDER_VERSION,
        "builder_version": BUILDER_VERSION,
        "pfm_parser_version": PFM_PARSER_VERSION,
        "decision_rule": "18:00 America/New_York on D-1",
        "availability_buffer_minutes": int(AVAILABILITY_BUFFER.total_seconds() // 60),
        "max_forecast_age_hours": int(MAX_FORECAST_AGE.total_seconds() // 3600),
        "date_range": [rows[0]["target_date"], rows[-1]["target_date"]] if rows else None,
        "splits": {name: [s.isoformat(), e.isoformat()] for name, s, e in SPLITS},
        "rows": len(rows),
        "rows_by_status": dict(sorted(by_reason.items())),
        "rows_by_split_usable": {f"{s}/{u}": n for (s, u), n in sorted(by_split.items())},
        "input_sha256": dict(sorted(inputs.items())),
        "dataset_sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
    }


def manifest_json(m: dict[str, Any]) -> str:
    return json.dumps(m, indent=2, sort_keys=True) + "\n"
