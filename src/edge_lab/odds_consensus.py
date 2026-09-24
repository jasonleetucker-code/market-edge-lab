"""Sportsbook consensus RESEARCH BENCHMARK from stored Odds API snapshots (#9, ADR 0033).

RESEARCH BENCHMARK — NOT EXECUTABLE. Everything here is derived, read-only and network-free:

- **Input:** immutable `snapshots` rows (source `the_odds_api`, kind `odds`) that the pilot
  already stored. No request is made and no credit is spent. The evidence store is opened
  read-only by the CLI; the functions below only read the store they are given.
- **Two kinds of value, never mixed:**
  - an `OfferedPrice` is a bookmaker's quote exactly as received (raw price text, its odds
    format, the decimal conversion and 1/decimal, which still holds the margin). It is what a
    sportsbook advertises, not a fill;
  - an `OutcomeConsensus.consensus_probability` is a de-vigged research estimate: the median,
    across books, of each book's proportional two-way de-vig at one exact line. It is not a
    price anyone can trade at.
- **Math** (canonical owner `edge_lab.odds_api`: `pair_offers`, `group_propositions`,
  `median`, `median_absolute_deviation`): only clean two-sided complements are de-vigged (h2h
  two-way, spreads with exactly opposite points, totals Over/Under at the same point). Spreads
  and totals are grouped by exact normalized line and never combined across lines. A draw or
  three-way h2h, a missing side, a duplicate side and any unknown market are UNSUPPORTED with a
  reason. No sharp-book weighting, no strategy, no thresholds.
- **Dispersion:** per outcome, the range (max - min) and the MAD (median absolute deviation
  from the median, unscaled) of the contributing books' de-vigged probabilities.
- **Freshness:** per book, its market `last_update` (else the bookmaker's `last_update`)
  against the registry's odds max age, judged at the snapshot's receipt time; the proposition
  takes the worst of its books (`freshness.combine`). Unknown stays unknown.
  Snapshot and event roll-ups (`freshness_at_receipt`) are the worst of what they show, UNKNOWN
  when nothing is shown; a point-in-time read's `freshness_as_of` is the worst of that and the
  receipt age at as_of, so it is never FRESH while any contributing book is stale or unknown.
- **Point in time:** a consensus "as of T" uses only snapshots received at or before T. Newer
  captures of an event that were unusable are surfaced (`newer_unusable`), never skipped silently.
- **Bounded cost:** a metadata index, one payload in memory at a time; an event read parses only
  the newest snapshot holding the event (and newer unusable ones), and only that event.
- **Versioned and hashed:** `CONSENSUS_VERSION`; `input_sha256` identifies the exact inputs
  (stored payload hash, receipt time, odds format, version, parameters); `output_sha256` the
  derived content. The same inputs always give the same bytes.

Public API (what the Terminal calls; it formats, it never recomputes):
`consensus_for_snapshot`, `consensus_for_event`, `consensus_series_for_event`,
`consensus_since`, `build_snapshot_consensus`, `build_artifact`; each result has `to_dict()`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from contextlib import closing
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qs, urlsplit

from . import odds_api
from .freshness import Freshness, assess, combine, parse_utc
from .provenance import canonical_json, sha256_hex
from .sources import get_source

LABEL = "RESEARCH BENCHMARK — NOT EXECUTABLE"
OFFERED_LABEL = "OFFERED_PRICE_AS_RECEIVED"
SCHEMA = "odds-consensus/1"
ARTIFACT_SCHEMA = "odds-consensus-artifact/1"
CONSENSUS_VERSION = odds_api.CONSENSUS_VERSION
DISPERSION_METHOD = "range_and_unscaled_mad_v1"
MIN_BOOKS = 2  # definitional: one book's de-vig is not a cross-book consensus (not a strategy threshold)
SOURCE = get_source(odds_api.SOURCE_ID).legacy_name
KIND = "odds"
ODDS_MAX_AGE = get_source(odds_api.SOURCE_ID).max_age["odds"]
_DECIMAL_CONTEXT = odds_api.CONSENSUS_DECIMAL_CONTEXT
UTC = timezone.utc


class ConsensusStatus(str, Enum):
    SUPPORTED = "SUPPORTED"  # at least MIN_BOOKS books paired this exact proposition
    INSUFFICIENT_BOOKS = "INSUFFICIENT_BOOKS"  # one book only: its de-vig is shown, no consensus
    UNSUPPORTED = "UNSUPPORTED"  # not a clean two-sided complement (see `reasons`)


class PointInTimeError(ValueError):
    """A snapshot received after the requested as-of time was asked for."""


# --------------------------------------------------------------------------- result types


@dataclass(frozen=True)
class OfferedPrice:
    """A bookmaker's offered price exactly as received. Not a probability, not executable."""

    bookmaker: str
    market_key: str
    outcome_name: str
    point: str | None  # the line as received (text)
    line: str | None  # the normalized line ("44.50" -> "44.5"); None for h2h
    raw_price: str  # exactly as received
    odds_format: str
    decimal_odds: Decimal | None  # None when the raw price is not a valid quote
    implied_probability_with_margin: Decimal | None  # 1 / decimal odds; includes the book's margin
    label: str = OFFERED_LABEL
    executable: bool = False


@dataclass(frozen=True)
class BookDevig:
    """One book's proportional two-way de-vig at this exact line (a research estimate)."""

    bookmaker: str
    probabilities: tuple[Decimal, Decimal]  # in the proposition's outcome order; sums to 1
    implied_with_margin: tuple[Decimal, Decimal]
    overround: Decimal
    market_last_update_utc: str | None
    bookmaker_last_update_utc: str | None
    update_basis: str | None  # "market", "bookmaker" or None (no usable timestamp)
    age_at_receipt_seconds: int | None
    freshness_at_receipt: Freshness
    method: str = odds_api.PAIRED_DEVIG_METHOD
    label: str = odds_api.RESEARCH_ONLY
    executable: bool = False


@dataclass(frozen=True)
class OutcomeConsensus:
    """The de-vigged consensus for one outcome of one proposition. Not a price."""

    outcome_name: str
    line: str | None
    consensus_probability: Decimal | None  # median of the books' de-vigged probabilities
    min_probability: Decimal | None
    max_probability: Decimal | None
    range: Decimal | None  # max - min
    mad: Decimal | None  # median(|p - median|), unscaled
    book_count: int
    dispersion_method: str = DISPERSION_METHOD


@dataclass(frozen=True)
class UpdateBounds:
    """Earliest and latest provider `last_update` among the contributing books."""

    earliest_utc: str | None
    latest_utc: str | None
    known: int
    unknown: int  # missing or unparseable: never replaced by a guess


@dataclass(frozen=True)
class PropositionConsensus:
    event_id: str  # the provider's native event id
    market_key: str
    outcomes: tuple[tuple[str, str | None], tuple[str, str | None]]  # (name, normalized line), sorted
    status: ConsensusStatus
    reason: str | None
    offered: tuple[OfferedPrice, ...]  # both sides of every contributing book, as received
    books: tuple[BookDevig, ...]
    contributing_book_count: int
    market_bookmaker_count: int  # books that quoted this market for this event (any line)
    consensus: tuple[OutcomeConsensus, OutcomeConsensus]
    freshness_at_receipt: Freshness  # worst of the contributing books
    market_update: UpdateBounds
    bookmaker_update: UpdateBounds
    label: str = LABEL
    consensus_version: str = CONSENSUS_VERSION
    executable: bool = False


@dataclass(frozen=True)
class UnsupportedGroup:
    """Offers of one market (and line) that enter no consensus, grouped by reason code."""

    event_id: str
    market_key: str
    line: str | None
    status: str  # an odds_api.PairingStatus value
    reasons: tuple[str, ...]
    bookmakers: tuple[str, ...]
    offered: tuple[OfferedPrice, ...]
    consensus_status: ConsensusStatus = ConsensusStatus.UNSUPPORTED
    executable: bool = False


@dataclass(frozen=True)
class CaptureTarget:
    """A pilot target this snapshot was captured for (from the stored request context)."""

    target_id: str | None
    offset: str | None
    target_utc: str | None


@dataclass(frozen=True)
class EventConsensus:
    event_id: str  # the provider's native event id
    sport_key: str | None
    league: str | None
    home_team: str | None
    away_team: str | None
    commence_time_utc: str | None
    bookmaker_count: int
    propositions: tuple[PropositionConsensus, ...]
    unsupported: tuple[UnsupportedGroup, ...]
    capture_targets: tuple[CaptureTarget, ...]
    freshness_at_receipt: Freshness = Freshness.UNKNOWN  # worst of its propositions; UNKNOWN when none


@dataclass(frozen=True)
class UnusableCapture:
    """A newer stored observation that mentions the event but gives it no usable consensus:
    it failed closed (hash mismatch, unknown odds format, unknown receipt time) or the provider's
    response did not include the event. Shown so an older result is never passed off as latest."""

    snapshot_id: int
    received_at_utc: str | None
    problems: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotConsensus:
    """The benchmark for one stored odds snapshot (or one event of it)."""

    snapshot_id: int
    received_at_utc: str | None
    payload_sha256: str | None
    sport: str | None
    odds_format: str | None
    purpose: str | None
    slot_id: str | None
    events: tuple[EventConsensus, ...]
    problems: tuple[str, ...]
    input_sha256: str
    output_sha256: str = ""
    # True when the snapshot could not be used at all (payload hash mismatch, unknown or
    # conflicting odds format): `events` is empty and `problems` says why.
    failed_closed: bool = False
    # Worst of the events' freshness (each the worst of its books, judged at receipt); UNKNOWN
    # when there is no proposition at all. Unknown and stale propagate (freshness.combine).
    freshness_at_receipt: Freshness = Freshness.UNKNOWN
    as_of_utc: str | None = None  # set only by point-in-time reads
    receipt_freshness_as_of: Freshness | None = None  # the receipt time alone, judged at as_of_utc
    # What a display at as_of_utc must show: the worst of receipt_freshness_as_of and
    # freshness_at_receipt. Never FRESH while any contributing book is stale or unknown.
    freshness_as_of: Freshness | None = None
    # Point-in-time event reads only: newer observations of the event that were unusable.
    newer_unusable: tuple[UnusableCapture, ...] = ()
    schema: str = SCHEMA
    consensus_version: str = CONSENSUS_VERSION
    label: str = LABEL
    executable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


# --------------------------------------------------------------------------- helpers


def _dec(value: Decimal) -> str:
    return "0" if value == 0 else format(value, "f")


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return _dec(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _iso(value: Any) -> str | None:
    parsed = parse_utc(value)
    return None if parsed is None else parsed.isoformat().replace("+00:00", "Z")


def _native(event_id: str) -> str:
    prefix = f"{odds_api.VENUE}:"
    return event_id[len(prefix):] if event_id.startswith(prefix) else event_id


def _offered(offer: odds_api.OddsOffer) -> OfferedPrice:
    implied = odds_api.implied_probability(offer)
    return OfferedPrice(offer.bookmaker, offer.market_key, offer.outcome_name, offer.point,
                        odds_api.normalize_line(offer.point), offer.raw_price, offer.odds_format,
                        offer.decimal_odds, None if implied is None else implied.probability)


def _odds_format(payload: Mapping[str, Any], url: str | None) -> tuple[str | None, str | None]:
    """(odds format, problem). From the stored request context and the stored (redacted) URL;
    never guessed from the prices. Disagreement or absence fails closed."""
    request = payload.get("request") if isinstance(payload.get("request"), Mapping) else {}
    stated = request.get("odds_format") if isinstance(request.get("odds_format"), str) else None
    from_url = None
    if url:
        values = parse_qs(urlsplit(url).query).get("oddsFormat") or []
        from_url = values[0] if len(values) == 1 else None
    found = {v for v in (stated, from_url) if v is not None}
    if len(found) > 1:
        return None, f"ODDS_FORMAT_CONFLICT: request says {stated!r}, URL says {from_url!r}"
    if not found:
        return None, "ODDS_FORMAT_UNKNOWN: neither the stored request nor the URL states the odds format"
    fmt = found.pop()
    if fmt not in ("decimal", "american"):
        return None, f"ODDS_FORMAT_UNSUPPORTED: {fmt!r}"
    return fmt, None


def _raw_updates(events: Any) -> dict[tuple[str, str, str | None], str | None]:
    """Provider last_update per (event, bookmaker, None) and (event, bookmaker, market)."""
    out: dict[tuple[str, str, str | None], str | None] = {}
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, Mapping) or not event.get("id"):
            continue
        native = str(event["id"])
        for book in event.get("bookmakers") or []:
            if not isinstance(book, Mapping) or not book.get("key"):
                continue
            out[(native, str(book["key"]), None)] = book.get("last_update")
            for market in book.get("markets") or []:
                if isinstance(market, Mapping) and market.get("key"):
                    out[(native, str(book["key"]), str(market["key"]))] = market.get("last_update")
    return out


def _bounds(values: Sequence[str | None]) -> UpdateBounds:
    known = sorted(parse_utc(v) for v in values if parse_utc(v) is not None)  # type: ignore[type-var]
    return UpdateBounds(_iso(known[0]) if known else None, _iso(known[-1]) if known else None, len(known),
                        len(values) - len(known))


def _book_devig(pair: odds_api.PairedDevig, updates: Mapping[tuple[str, str, str | None], str | None],
                received: datetime | None) -> BookDevig:
    native = _native(pair.event_id)
    market_raw = updates.get((native, pair.bookmaker, pair.market_key))
    book_raw = updates.get((native, pair.bookmaker, None))
    market_ts, book_ts = _iso(market_raw), _iso(book_raw)
    basis, ts = ("market", market_ts) if market_ts else (("bookmaker", book_ts) if book_ts else (None, None))
    fresh = assess(ts, max_age=ODDS_MAX_AGE, now=received) if received is not None else Freshness.UNKNOWN
    age = int((received - parse_utc(ts)).total_seconds()) if received is not None and ts else None  # type: ignore[operator]
    return BookDevig(pair.bookmaker, pair.probabilities, pair.implied, pair.overround, market_ts, book_ts, basis, age,
                     fresh)


def _outcome_stats(name: str, line: str | None, values: Sequence[Decimal], supported: bool) -> OutcomeConsensus:
    if not supported:
        return OutcomeConsensus(name, line, None, None, None, None, None, len(values))
    lo, hi = min(values), max(values)
    return OutcomeConsensus(name, line, odds_api.median(values), lo, hi, hi - lo,
                            odds_api.median_absolute_deviation(values), len(values))


def _proposition(key: tuple[str, str, tuple], pairs: tuple[odds_api.PairedDevig, ...],
                 updates: Mapping[tuple[str, str, str | None], str | None], received: datetime | None,
                 market_books: int) -> PropositionConsensus:
    event, market, outcomes = key
    books = tuple(_book_devig(p, updates, received) for p in pairs)
    supported = len(pairs) >= MIN_BOOKS
    status = ConsensusStatus.SUPPORTED if supported else ConsensusStatus.INSUFFICIENT_BOOKS
    reason = None if supported else (f"{len(pairs)} book paired this exact line; a consensus needs {MIN_BOOKS} "
                                     "(the single book's de-vig is shown, not a consensus)")
    consensus = tuple(_outcome_stats(outcomes[i][0], outcomes[i][1], [p.probabilities[i] for p in pairs], supported)
                      for i in range(2))
    offered = tuple(_offered(o) for p in pairs for o in p.offers)
    return PropositionConsensus(
        _native(event), market, outcomes, status, reason, offered, books, len(pairs), market_books,
        consensus,  # type: ignore[arg-type]
        combine(*(b.freshness_at_receipt for b in books)),
        _bounds([b.market_last_update_utc for b in books]), _bounds([b.bookmaker_last_update_utc for b in books]))


def _unsupported(unpaired: Iterable[odds_api.UnpairedOffer]) -> dict[str, tuple[UnsupportedGroup, ...]]:
    groups: dict[tuple[str, str, str | None, str], list[odds_api.UnpairedOffer]] = {}
    for u in unpaired:
        line = odds_api.normalize_line(u.offer.point) if u.offer.market_key != "h2h" else None
        groups.setdefault((_native(u.offer.event_id), u.offer.market_key, line, u.status.value), []).append(u)
    out: dict[str, list[UnsupportedGroup]] = {}
    for (event, market, line, status), rows in sorted(groups.items(), key=lambda kv: tuple(x or "" for x in kv[0])):
        out.setdefault(event, []).append(UnsupportedGroup(
            event, market, line, status, tuple(sorted({u.reason for u in rows})),
            tuple(sorted({u.offer.bookmaker for u in rows})), tuple(_offered(u.offer) for u in rows)))
    return {k: tuple(v) for k, v in out.items()}


def _targets(request: Mapping[str, Any], native: str) -> tuple[CaptureTarget, ...]:
    rows = request.get("targets") if isinstance(request.get("targets"), list) else []
    out = [CaptureTarget(t.get("target_id"), t.get("offset"), t.get("target_utc")) for t in rows
           if isinstance(t, Mapping) and _native(str(t.get("event_id") or "")) == native]
    return tuple(sorted(out, key=lambda t: (t.target_utc or "", t.target_id or "")))


def _input_sha256(snapshot_id: int, payload_sha256: str | None, received: str | None, fmt: str | None) -> str:
    return sha256_hex(canonical_json({
        "consensus_version": CONSENSUS_VERSION, "pairing_method": odds_api.PAIRED_DEVIG_METHOD,
        "dispersion_method": DISPERSION_METHOD, "min_books": MIN_BOOKS,
        "odds_max_age_seconds": int(ODDS_MAX_AGE.total_seconds()), "snapshot_id": snapshot_id,
        "payload_sha256": payload_sha256, "received_at_utc": received, "odds_format": fmt}))


_VOLATILE = ("output_sha256", "as_of_utc", "receipt_freshness_as_of", "freshness_as_of", "newer_unusable")


def _sealed(result: SnapshotConsensus) -> SnapshotConsensus:
    """Roll freshness up (worst of the events shown; UNKNOWN when none) and hash the content."""
    result = replace(result, freshness_at_receipt=combine(*(e.freshness_at_receipt for e in result.events)))
    body = result.to_dict()
    for volatile in _VOLATILE:
        body.pop(volatile, None)
    return replace(result, output_sha256=sha256_hex(canonical_json(body)))


# --------------------------------------------------------------------------- builders


def build_snapshot_consensus(row: Mapping[str, Any], *, event_id: str | None = None) -> SnapshotConsensus:
    """The benchmark for one stored odds snapshot row (`id`, `fetched_at_utc`, `url`,
    `payload_sha256`, `payload_json`). Pure: no store, no clock, no network.

    Fails closed, with a problem and no events, when the stored payload does not match its
    stored hash or its odds format is not stated by the stored request or URL. With `event_id`,
    only that event is parsed (the integrity and format checks still cover the whole payload),
    so an event read costs one event, not the whole slate."""
    with localcontext(_DECIMAL_CONTEXT):
        return _build(row, None if event_id is None else _native(str(event_id)))


def _build(row: Mapping[str, Any], only: str | None) -> SnapshotConsensus:
    snapshot_id = int(row["id"])
    received_dt = parse_utc(row["fetched_at_utc"])
    received = _iso(received_dt)
    stored_sha = row["payload_sha256"]
    problems: list[str] = []
    if received is None:
        problems.append(f"RECEIPT_TIME_UNKNOWN: fetched_at_utc {row['fetched_at_utc']!r} is not a zoned timestamp")
    text = row["payload_json"]
    if sha256_hex(text) != stored_sha:
        problems.append("PAYLOAD_HASH_MISMATCH: the stored payload does not match its stored sha256; not used")
        return _sealed(SnapshotConsensus(snapshot_id, received, stored_sha, None, None, None, None, (), tuple(problems),
                                         _input_sha256(snapshot_id, stored_sha, received, None), failed_closed=True))
    payload = json.loads(text)
    payload = payload if isinstance(payload, Mapping) else {}
    request = payload.get("request") if isinstance(payload.get("request"), Mapping) else {}
    sport = payload.get("sport") if isinstance(payload.get("sport"), str) else None
    purpose = request.get("purpose") if isinstance(request.get("purpose"), str) else None
    slot = request.get("slot_id") if isinstance(request.get("slot_id"), str) else None
    fmt, fmt_problem = _odds_format(payload, row["url"] if "url" in row.keys() else None)  # type: ignore[union-attr]
    base = dict(snapshot_id=snapshot_id, received_at_utc=received, payload_sha256=stored_sha, sport=sport,
                odds_format=fmt, purpose=purpose, slot_id=slot,
                input_sha256=_input_sha256(snapshot_id, stored_sha, received, fmt))
    if fmt is None:
        problems.append(fmt_problem or "ODDS_FORMAT_UNKNOWN")
        return _sealed(SnapshotConsensus(events=(), problems=tuple(problems), failed_closed=True,  # type: ignore[arg-type]
                                         **base))
    raw_events = payload.get("events")
    if only is not None and isinstance(raw_events, list):
        raw_events = [e for e in raw_events if isinstance(e, Mapping) and str(e.get("id")) == only]
    parsed = odds_api.parse_odds(raw_events, odds_format=fmt, received_at_utc=received,
                                 evidence_id=f"snapshot:{snapshot_id}")
    problems += [f"PARSE: {p}" for p in parsed.problems]
    updates = _raw_updates(raw_events)
    paired, unpaired = odds_api.pair_offers(parsed)
    unsupported = _unsupported(unpaired)
    books_per_market: dict[tuple[str, str], set[str]] = {}
    for o in parsed.offers:
        books_per_market.setdefault((_native(o.event_id), o.market_key), set()).add(o.bookmaker)
    props: dict[str, list[PropositionConsensus]] = {}
    for key, pairs in odds_api.group_propositions(paired).items():
        native = _native(key[0])
        props.setdefault(native, []).append(_proposition(key, pairs, updates, received_dt,
                                                         len(books_per_market.get((native, key[1]), ()))))
    events: list[EventConsensus] = []
    seen: set[str] = set()
    for raw in raw_events if isinstance(raw_events, list) else []:
        if not isinstance(raw, Mapping) or not raw.get("id") or str(raw["id"]) in seen:
            continue
        native = str(raw["id"])
        seen.add(native)

        def text(key: str) -> str | None:
            value = raw.get(key)  # noqa: B023 - evaluated immediately
            return value if isinstance(value, str) and value else None
        events.append(EventConsensus(
            native, text("sport_key"), text("sport_title"), text("home_team"), text("away_team"),
            _iso(raw.get("commence_time")),
            len({b.get("key") for b in raw.get("bookmakers") or [] if isinstance(b, Mapping) and b.get("key")}),
            tuple(props.get(native, ())), unsupported.get(native, ()), _targets(request, native),
            combine(*(p.freshness_at_receipt for p in props.get(native, ())))))
    events.sort(key=lambda e: (e.commence_time_utc or "", e.event_id))
    return _sealed(SnapshotConsensus(events=tuple(events), problems=tuple(problems), **base))  # type: ignore[arg-type]


def _check_as_of(as_of: datetime | None) -> datetime | None:
    if as_of is None:
        return None
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise ValueError("as_of must be a timezone-aware datetime")
    return as_of.astimezone(UTC)


def _at(result: SnapshotConsensus, as_of: datetime | None) -> SnapshotConsensus:
    if as_of is None:
        return result
    receipt = assess(result.received_at_utc, max_age=ODDS_MAX_AGE, now=as_of)
    return replace(result, as_of_utc=_iso(as_of), receipt_freshness_as_of=receipt,
                   freshness_as_of=combine(receipt, result.freshness_at_receipt))


_FLOOR = datetime.min.replace(tzinfo=UTC)  # unknown receipt times sort first and are never "known by T"


def _index(store: Any, needle: str | None = None) -> list[tuple[datetime | None, int]]:
    """(receipt instant, id) of every stored odds snapshot, oldest first, WITHOUT loading any
    payload into Python. `needle` narrows to snapshots whose stored JSON contains that text
    (SQLite `instr`), a cheap pre-filter that is always confirmed by parsing.

    The evidence store has no public metadata-only read, and `storage.py` is outside this
    module's lane, so this uses the store's own connection. A read-only store (`open_readonly`)
    gives a `mode=ro`, `query_only` connection; nothing here writes."""
    sql = "SELECT id, fetched_at_utc FROM snapshots WHERE source = ? AND kind = ?"
    params: list[Any] = [SOURCE, KIND]
    if needle is not None:
        sql += " AND instr(payload_json, ?) > 0"
        params.append(needle)
    with closing(store._connect()) as conn:
        rows = conn.execute(sql, params).fetchall()
    return sorted(((parse_utc(r[1]), int(r[0])) for r in rows), key=lambda t: (t[0] or _FLOOR, t[1]))


def _load(store: Any, snapshot_id: int) -> Mapping[str, Any] | None:
    """One stored snapshot row, payload included: one payload in memory at a time."""
    return store.snapshots_by_id([snapshot_id]).get(snapshot_id)


def _known(received: datetime | None, as_of: datetime | None) -> bool:
    if as_of is None:
        return True
    return received is not None and received <= as_of  # an unknown receipt time is never "known by T"


def _known_at(row: Mapping[str, Any], as_of: datetime | None) -> bool:
    return _known(parse_utc(row["fetched_at_utc"]), as_of)


def _only_event(result: SnapshotConsensus, native: str) -> SnapshotConsensus | None:
    events = tuple(e for e in result.events if e.event_id == native)
    if not events:
        return None
    return _sealed(replace(result, events=events))


def _needle(native: str) -> str:
    return json.dumps(native, ensure_ascii=False)  # the id as a JSON string, as stored


def consensus_for_snapshot(store: Any, snapshot_id: int, *, as_of: datetime | None = None
                           ) -> SnapshotConsensus | None:
    """The benchmark for one stored odds snapshot, or None when no such snapshot exists.

    With `as_of`, a snapshot received after it (or with an unknown receipt time) raises
    PointInTimeError: it was not knowable at that time."""
    at = _check_as_of(as_of)
    row = store.snapshots_by_id([int(snapshot_id)]).get(int(snapshot_id))
    if row is None:
        return None
    if row["source"] != SOURCE or row["kind"] != KIND:
        raise ValueError(f"snapshot {snapshot_id} is {row['source']}/{row['kind']}, not {SOURCE}/{KIND}")
    if not _known_at(row, at):
        raise PointInTimeError(f"snapshot {snapshot_id} was received at {row['fetched_at_utc']!r}, "
                               f"not at or before {_iso(at)}")
    return _at(build_snapshot_consensus(row), at)


def consensus_series_for_event(store: Any, event_id: str, *, as_of: datetime | None = None
                               ) -> tuple[SnapshotConsensus, ...]:
    """Every stored observation of one event received at or before `as_of` (all when None),
    oldest first, each restricted to that event. A snapshot that mentions the event but failed
    closed is kept in the series (`failed_closed`, no events, its problems), so a gap is visible.
    Payloads are loaded one at a time. Accepts the native or `the_odds_api:` id."""
    at = _check_as_of(as_of)
    native = _native(str(event_id))
    out = []
    for received, sid in _index(store, _needle(native)):
        if not _known(received, at):
            continue
        row = _load(store, sid)
        if row is None:
            continue
        result = build_snapshot_consensus(row, event_id=native)
        one = result if result.failed_closed else _only_event(result, native)
        if one is not None:
            out.append(_at(one, at))
    return tuple(out)


def consensus_for_event(store: Any, event_id: str, as_of: datetime) -> SnapshotConsensus | None:
    """The latest usable observation of one event received at or before `as_of`, restricted to
    that event. `as_of` is required (point in time).

    Bounded: snapshots are walked newest first and the walk stops at the first one that holds
    the event, so only that snapshot and any newer unusable ones are parsed. Newer observations
    that mention the event but failed closed, or whose response lacked the event, are returned
    in `newer_unusable`, so an older result is never passed off as the latest capture. When no
    usable observation exists but unusable ones do, the newest unusable one is returned with no
    events and its problems. None only when nothing mentioning the event was knowable by then."""
    if as_of is None:
        raise ValueError("as_of is required: a consensus is always as of a time")
    at = _check_as_of(as_of)
    native = _native(str(event_id))
    unusable: list[tuple[UnusableCapture, SnapshotConsensus]] = []
    for received, sid in reversed(_index(store, _needle(native))):
        if not _known(received, at):
            continue
        row = _load(store, sid)
        if row is None:
            continue
        result = build_snapshot_consensus(row, event_id=native)
        if result.failed_closed:
            unusable.append((UnusableCapture(sid, result.received_at_utc, result.problems), result))
            continue
        one = _only_event(result, native)
        if one is None:
            absent = f"EVENT_ABSENT: snapshot {sid} mentions event {native} but its response does not include it"
            gap = _sealed(replace(result, events=(), problems=result.problems + (absent,)))
            unusable.append((UnusableCapture(sid, result.received_at_utc, gap.problems), gap))
            continue
        return _at(replace(one, newer_unusable=tuple(u for u, _ in unusable)), at)
    if not unusable:
        return None
    newest = unusable[0][1]
    return _at(replace(newest, newer_unusable=tuple(u for u, _ in unusable[1:])), at)


def consensus_since(store: Any, since: datetime | None = None, *, as_of: datetime | None = None
                    ) -> tuple[SnapshotConsensus, ...]:
    """Every stored odds snapshot received at or after `since` and at or before `as_of`,
    oldest first. Payloads are loaded one at a time."""
    start, at = _check_as_of(since), _check_as_of(as_of)
    out = []
    for received, sid in _index(store):
        if start is not None and (received is None or received < start):
            continue
        if not _known(received, at):
            continue
        row = _load(store, sid)
        if row is not None:
            out.append(_at(build_snapshot_consensus(row), at))
    return tuple(out)


def build_artifact(results: Sequence[SnapshotConsensus], *, selection: Mapping[str, Any]) -> dict[str, Any]:
    """The derived JSON artifact: deterministic for the same stored inputs and selection."""
    body = {"schema": ARTIFACT_SCHEMA, "label": LABEL, "consensus_version": CONSENSUS_VERSION,
            "executable": False, "selection": dict(selection),
            "snapshots": [r.to_dict() for r in results]}
    body["artifact_sha256"] = sha256_hex(canonical_json(body))
    return body


# --------------------------------------------------------------------------- CLI


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    """`edge-lab odds consensus`: read-only, network-free. Prints (or writes) one JSON artifact."""
    from .storage import ReadOnlyStoreError, SnapshotStore

    parser = argparse.ArgumentParser(
        prog="edge-lab odds consensus",
        description="RESEARCH BENCHMARK - NOT EXECUTABLE. Sportsbook consensus from stored Odds API snapshots (ADR 0033). "
                    "Opens the evidence store read-only; no network; no credits.")
    parser.add_argument("--db", default="data/edge_lab.sqlite3")
    pick = parser.add_mutually_exclusive_group()
    pick.add_argument("--snapshot", type=int, help="one stored odds snapshot id")
    pick.add_argument("--since", help="snapshots received at or after this ISO-8601 time (with zone)")
    pick.add_argument("--event", help="one event (native or the_odds_api: id): its whole stored series")
    parser.add_argument("--as-of", help="point in time (ISO-8601 with zone): only snapshots received by then")
    parser.add_argument("--out", help="write the JSON artifact here (atomically) instead of stdout")
    args = parser.parse_args(argv)

    def when(text: str | None, name: str) -> datetime | None:
        if text is None:
            return None
        parsed = parse_utc(text)
        if parsed is None:
            parser.error(f"{name} must be an ISO-8601 time with a zone")
        return parsed

    as_of, since = when(args.as_of, "--as-of"), when(args.since, "--since")
    try:
        store = SnapshotStore.open_readonly(args.db)
    except ReadOnlyStoreError as exc:
        print(json.dumps({"command": "odds consensus", "state": "NO_STORE", "detail": str(exc)}))
        return 1
    selection: dict[str, Any] = {"as_of_utc": _iso(as_of)}
    try:
        if args.snapshot is not None:
            selection["snapshot_id"] = args.snapshot
            one = consensus_for_snapshot(store, args.snapshot, as_of=as_of)
            if one is None:
                print(json.dumps({"command": "odds consensus", "state": "NOT_FOUND",
                                  "detail": f"no stored snapshot {args.snapshot}"}))
                return 1
            results: tuple[SnapshotConsensus, ...] = (one,)
        elif args.event is not None:
            selection["event_id"] = _native(args.event)
            results = consensus_series_for_event(store, args.event, as_of=as_of)
        else:
            selection["since_utc"] = _iso(since)
            results = consensus_since(store, since, as_of=as_of)
    except PointInTimeError as exc:
        print(json.dumps({"command": "odds consensus", "state": "NOT_KNOWABLE_AT_AS_OF", "detail": str(exc)}))
        return 1
    except ValueError as exc:
        print(json.dumps({"command": "odds consensus", "state": "INVALID", "detail": str(exc)}))
        return 2
    text = json.dumps(build_artifact(results, selection=selection), sort_keys=True, indent=2)
    if args.out:
        _write_atomic(Path(args.out), text + "\n")
        print(json.dumps({"command": "odds consensus", "state": "WRITTEN", "out": args.out,
                          "snapshots": len(results)}))
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
