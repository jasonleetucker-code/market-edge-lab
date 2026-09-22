"""Gate 2 settlement audit: reproduce Kalshi results from contract rules and evidence.

For every daily event (the independence unit) and every bracket in it, compute:

- the expected outcome from Kalshi's own recorded `expiration_value`
  ("reproduction A": does our parser apply the rules exactly as Kalshi did?), and
- the expected outcome from the first final NWS CLI maximum
  ("reproduction B": does the independent official observation reproduce settlement?),

then compare both with Kalshi's recorded `result`. Nothing here trades or estimates
profitability; it only answers "can we determine how a contract settles?".
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from .nws_cli import CliReport, settlement_value
from .settlement import Outcome, RulesSource, kalshi_result, parse_value, read_rules, resolve

AUDIT_VERSION = "1"


def event_date(event_ticker: str) -> date | None:
    """KXHIGHNY-26SEP21 -> 2026-09-21 (None when the ticker does not follow the pattern)."""
    parts = event_ticker.split("-")
    if len(parts) != 2:
        return None
    try:
        return datetime.strptime(parts[1], "%y%b%d").date()
    except ValueError:
        return None


_DATE_TEXT = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?"
    r"|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?) \d{1,2}, \d{4}"
)
_STRIKE_TEXT = re.compile(r"(greater than|less than|between) -?[\d.]+(?:-[\d.]+)?°")


def rules_template(market: Mapping[str, Any]) -> str:
    """Rules text with date, comparison and strike templated out: identical across the
    brackets and days that share one wording, so versions can be grouped. (The
    comparison is checked separately against strike_type by the resolver.)"""
    parts = []
    for key in ("rules_primary", "rules_secondary", "early_close_condition"):
        text = str(market.get(key) or "")
        text = _DATE_TEXT.sub("<DATE>", text)
        text = _STRIKE_TEXT.sub("<COMPARISON> <STRIKE>°", text)
        parts.append(text)
    return "\n---\n".join(parts)


def rules_hash(market: Mapping[str, Any]) -> str:
    """Version id of the rules wording (date and strike templated out)."""
    return hashlib.sha256(rules_template(market).encode("utf-8")).hexdigest()[:16]


def _preferred(a: Mapping[str, Any], b: Mapping[str, Any]) -> Mapping[str, Any]:
    """Deterministic choice between duplicate records of one market (live vs historical,
    or repeated captures): prefer one with expiration_value, then the later
    updated_time, then the canonical-JSON larger record."""
    def key(m):
        return (
            bool(m.get("expiration_value")),
            str(m.get("updated_time") or ""),
            json.dumps(m, sort_keys=True),
        )

    return a if key(a) >= key(b) else b


@dataclass
class BracketRow:
    target_date: str
    event_ticker: str
    market_ticker: str
    strike_type: str | None
    floor_strike: Any
    cap_strike: Any
    rules_source: str
    rules_hash: str
    kalshi_result: str
    kalshi_expiration_value: str | None
    settlement_value_dollars: str | None
    nws_cli_max_f: int | None
    nws_cli_issued_utc: str | None
    nws_cli_wmo_header: str | None
    nws_cli_basis: str
    expected_from_kalshi_value: str
    expected_from_nws_cli: str
    match_kalshi_value: bool
    match_nws_cli: bool
    strikes_from_rules_text: bool
    explanation: str = ""


@dataclass
class EventSummary:
    target_date: str
    event_ticker: str
    brackets: int
    yes_brackets: int
    rules_source: str
    kalshi_expiration_value: str | None
    nws_cli_max_f: int | None
    value_difference: str | None  # kalshi - nws, when both exist
    reproduced_from_kalshi_value: bool
    reproduced_from_nws_cli: bool
    unresolved: bool
    explanations: list[str] = field(default_factory=list)


def _market_with_rules_strikes(market: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Fill absent strike fields from rules_primary (never overrides present fields)."""
    if market.get("strike_type") is not None:
        return dict(market), False
    reading = read_rules(market.get("rules_primary"))
    if reading.comparison is None:
        return dict(market), False
    filled = dict(market)
    filled["strike_type"] = reading.comparison
    filled["floor_strike"] = reading.low
    filled["cap_strike"] = reading.high
    return filled, True


def audit(
    markets: Iterable[Mapping[str, Any]],
    cli_reports: Iterable[CliReport],
    *,
    start: date,
    end: date,
) -> tuple[list[EventSummary], list[BracketRow]]:
    """Audit every event with start <= target date <= end. No event is excluded."""
    reports = list(cli_reports)
    by_event: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for market in markets:
        ticker = market.get("event_ticker") or ""
        d = event_date(ticker)
        if d is not None and start <= d <= end:
            by_event[ticker].append(market)
    # A market may appear in both the live and historical listings; keep one copy.
    for ticker, items in by_event.items():
        unique: dict[Any, Mapping[str, Any]] = {}
        for m in items:
            k = m.get("ticker")
            unique[k] = _preferred(unique[k], m) if k in unique else m
        by_event[ticker] = [unique[k] for k in sorted(unique, key=str)]

    summaries: list[EventSummary] = []
    rows: list[BracketRow] = []
    for ticker in sorted(by_event, key=lambda t: event_date(t)):
        d = event_date(ticker)
        selection = settlement_value(reports, d)
        final = selection.report
        cli_max = selection.value_f
        explanations: list[str] = []
        if final is None or not selection.basis.endswith("first final report with data"):
            explanations.append(f"NWS CLI: {selection.basis}")
        values = sorted({m.get("expiration_value") for m in by_event[ticker]} - {None, ""})
        kalshi_value = values[0] if len(values) == 1 else None
        if len(values) > 1:
            explanations.append(f"brackets disagree on expiration_value: {values}")
        sources = {read_rules(m.get("rules_primary")).source for m in by_event[ticker]}
        source = sources.pop().value if len(sources) == 1 else "mixed"

        ok_a = ok_b = True
        yes = 0
        for raw_market in by_event[ticker]:
            market, from_rules = _market_with_rules_strikes(raw_market)
            actual = kalshi_result(raw_market)
            yes += actual is Outcome.YES
            exp_a = resolve(market, kalshi_value).outcome if kalshi_value is not None else Outcome.UNKNOWN
            exp_b = resolve(market, cli_max).outcome
            match_a = exp_a is not Outcome.UNKNOWN and exp_a is actual
            match_b = exp_b is not Outcome.UNKNOWN and exp_b is actual
            ok_a &= match_a
            ok_b &= match_b
            note = []
            if from_rules:
                note.append("strike fields absent in Kalshi record; strikes read from rules_primary")
            rows.append(
                BracketRow(
                    target_date=d.isoformat(),
                    event_ticker=ticker,
                    market_ticker=str(raw_market.get("ticker")),
                    strike_type=market.get("strike_type"),
                    floor_strike=_plain(market.get("floor_strike")),
                    cap_strike=_plain(market.get("cap_strike")),
                    rules_source=read_rules(raw_market.get("rules_primary")).source.value,
                    rules_hash=rules_hash(raw_market),
                    kalshi_result=actual.value,
                    kalshi_expiration_value=raw_market.get("expiration_value") or None,
                    settlement_value_dollars=raw_market.get("settlement_value_dollars"),
                    nws_cli_max_f=cli_max,
                    nws_cli_issued_utc=final.issued_at_utc.isoformat() if final else None,
                    nws_cli_wmo_header=final.wmo_header if final else None,
                    nws_cli_basis=selection.basis,
                    expected_from_kalshi_value=exp_a.value,
                    expected_from_nws_cli=exp_b.value,
                    match_kalshi_value=match_a,
                    match_nws_cli=match_b,
                    strikes_from_rules_text=from_rules,
                    explanation="; ".join(note),
                )
            )
        if yes != 1:
            explanations.append(f"{yes} YES brackets (expected exactly 1)")
        if kalshi_value is None:
            explanations.append("no Kalshi expiration_value recorded for this event")
        k = parse_value(kalshi_value)
        diff = None
        if k is not None and cli_max is not None:
            diff = str((k - cli_max).normalize() + 0)
        summaries.append(
            EventSummary(
                target_date=d.isoformat(),
                event_ticker=ticker,
                brackets=len(by_event[ticker]),
                yes_brackets=yes,
                rules_source=source,
                kalshi_expiration_value=kalshi_value,
                nws_cli_max_f=cli_max,
                value_difference=diff,
                reproduced_from_kalshi_value=ok_a and kalshi_value is not None,
                reproduced_from_nws_cli=ok_b and cli_max is not None,
                unresolved=not (ok_b and cli_max is not None),
                explanations=explanations,
            )
        )
    return summaries, rows


def _plain(value: Any) -> Any:
    return str(value) if value is not None and not isinstance(value, (int, str)) else value


def missing_dates(summaries: list[EventSummary], start: date, end: date) -> list[str]:
    """Calendar dates in [start, end] with no event at all (reported, never hidden)."""
    have = {s.target_date for s in summaries}
    out = []
    day = start
    while day <= end:
        if day.isoformat() not in have:
            out.append(day.isoformat())
        day = date.fromordinal(day.toordinal() + 1)
    return out


def summarize(
    summaries: list[EventSummary], start: date, end: date, rows: list[BracketRow] | None = None
) -> dict[str, Any]:
    by_source = Counter(s.rules_source for s in summaries)
    with_both = [s for s in summaries if s.value_difference is not None]
    diffs = Counter(s.value_difference for s in with_both)
    return {
        "audit_version": AUDIT_VERSION,
        "window": [start.isoformat(), end.isoformat()],
        "events": len(summaries),
        "missing_dates": missing_dates(summaries, start, end),
        "events_by_rules_source": dict(by_source),
        "reproduced_from_nws_cli": sum(s.reproduced_from_nws_cli for s in summaries),
        "events_with_kalshi_value": sum(s.kalshi_expiration_value is not None for s in summaries),
        "reproduced_from_kalshi_value": sum(s.reproduced_from_kalshi_value for s in summaries),
        "unresolved_events": [s.event_ticker for s in summaries if s.unresolved],
        "kalshi_value_minus_nws_cli": {str(k): v for k, v in sorted(diffs.items())},
        "kalshi_value_vs_nws_cli_exact_agreement": (
            f"{sum(1 for s in with_both if s.value_difference == '0')}/{len(with_both)}"
        ),
        "events_not_exactly_one_yes": [s.event_ticker for s in summaries if s.yes_brackets != 1],
        "rules_versions": (
            {h: n for h, n in sorted(Counter(r.rules_hash for r in rows).items())} if rows else None
        ),
    }


def rows_csv(rows: list[BracketRow]) -> str:
    buffer = io.StringIO()
    names = list(asdict(rows[0]).keys()) if rows else []
    writer = csv.DictWriter(buffer, fieldnames=names, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(asdict(row))
    return buffer.getvalue()


__all__ = [
    "BracketRow",
    "EventSummary",
    "RulesSource",
    "audit",
    "event_date",
    "missing_dates",
    "rows_csv",
    "summarize",
]
