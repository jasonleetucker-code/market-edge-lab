"""Bounded Kalshi reads for the news lane (#192, owner answer "On-demand + 2-hour job").

What this may do: public, unauthenticated GETs of the series catalog by category, open markets
of a series, one market and its order book. Each read is stored as an immutable snapshot under
the lane's own source identity (`kalshi_public_intel`). It never vouches for routine Kalshi
health and never enters EXP-001, NFL or NHL queries.

What this refuses, before any request:
- the protected scopes KXHIGHNY, KXNFLGAME, KXNHLGAME and KXMVE*;
- any read inside a protected window, or within 10 minutes of the KXHIGHNY close tick;
- more than `MAX_KALSHI_GETS_PER_RUN` GETs in one run.

Matching a market to an event is a CANDIDATE only: a title or keyword match is never
settlement equivalence. Nothing here is ever sent to an AI model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote, urlencode

from ..http import Pacer, fetch_json_result
from ..sources import get_source
from ..storage import SnapshotStore
from .contracts import MAX_KALSHI_GETS_PER_RUN
from .events import EventRecord
from .extract import keywords
from .pricing import protected_reason

SPEC = get_source("kalshi_public_intel")
BASE_URL = SPEC.base_url
CATEGORIES = ("Politics", "Economics", "Elections", "World", "Financials")
CLOSE_TICK_UTC = (4, 57, 45)  # edgelab-observe-close (KXHIGHNY close-window capture)
CLOSE_TICK_GUARD = timedelta(minutes=10)
RUN_WINDOW = timedelta(minutes=5)
MATCHER_VERSION = "intel-kalshi-match-v1"

Getter = Callable[[str], tuple[dict[str, Any], Any]]


class KalshiRefused(RuntimeError):
    """A read was refused before any request (scope, window or budget)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class Budget:
    """At most `limit` GETs in one run; refuses the next one."""

    def __init__(self, limit: int = MAX_KALSHI_GETS_PER_RUN) -> None:
        self.limit = limit
        self.used = 0

    def take(self) -> None:
        if self.used >= self.limit:
            raise KalshiRefused("BUDGET_EXHAUSTED", f"{self.limit} Kalshi GETs already used in this run")
        self.used += 1


def _default_getter() -> Getter:
    from ..kalshi import PACER  # one pacer per process, shared with every Kalshi reader

    def get(url: str) -> tuple[dict[str, Any], Any]:
        return fetch_json_result(url, pacer=PACER)

    return get


def window_refusal(now: datetime) -> KalshiRefused | None:
    """Why a Kalshi read may not start now, or None."""
    from ..price_observations import protected_window_at

    now = now.astimezone(timezone.utc)
    hit = protected_window_at(now, now + RUN_WINDOW)
    if hit:
        return KalshiRefused("PROTECTED_WINDOW", f"inside the protected window {hit[0]}")
    for day in (-1, 0, 1):
        d = (now + timedelta(days=day)).date()
        tick = datetime(d.year, d.month, d.day, *CLOSE_TICK_UTC, tzinfo=timezone.utc)
        if abs(now - tick) <= CLOSE_TICK_GUARD:
            return KalshiRefused("CLOSE_TICK_GUARD", "within 10 minutes of the KXHIGHNY close-window capture")
    return None


def _url(path: str, **query: object) -> str:
    clean = {k: v for k, v in query.items() if v is not None}
    return f"{BASE_URL}{path}" + (f"?{urlencode(clean)}" if clean else "")


@dataclass(frozen=True)
class Read:
    payload: dict[str, Any]
    snapshot_id: int
    received_at_utc: str
    url: str


class Reader:
    """One run's bounded reader. Create one per run; it holds the GET budget."""

    def __init__(self, store: SnapshotStore, *, run_id: str, now: datetime, getter: Getter | None = None,
                 budget: Budget | None = None, check_window: bool = True) -> None:
        if check_window:
            refusal = window_refusal(now)
            if refusal:
                raise refusal
        self.store = store
        self.run_id = run_id
        self.getter = getter or _default_getter()
        self.budget = budget or Budget()

    def _read(self, path: str, *, kind: str, entity_id: str, **query: object) -> Read:
        self.budget.take()
        url = _url(path, **query)
        payload, fetch = self.getter(url)
        if not isinstance(payload, dict):
            raise ValueError(f"Kalshi {path} did not return a JSON object")
        sid = self.store.save_snapshot(
            run_id=self.run_id, source=SPEC.legacy_name, kind=kind, entity_id=entity_id, url=url, payload=payload,
            fetch=fetch, source_id=SPEC.source_id, parser_version=SPEC.parser_version,
            schema_version=SPEC.schema_version)
        received = getattr(fetch, "received_at_utc", None) or datetime.now(timezone.utc).isoformat()
        return Read(payload=payload, snapshot_id=sid, received_at_utc=received, url=url)

    def series_catalog(self, category: str) -> list[dict[str, Any]]:
        if category not in CATEGORIES:
            raise KalshiRefused("CATEGORY_NOT_ALLOWED", f"{category!r} is not one of {CATEGORIES}")
        read = self._read("/series", kind="series_catalog", entity_id=category, category=category)
        series = read.payload.get("series")
        if not isinstance(series, list):
            raise ValueError("Kalshi /series did not return a series list")
        return [s for s in series if isinstance(s, dict) and s.get("ticker") and not protected_reason(str(s["ticker"]))]

    def open_markets(self, series_ticker: str) -> list[dict[str, Any]]:
        _refuse_protected(series_ticker)
        read = self._read("/markets", kind="markets", entity_id=series_ticker, series_ticker=series_ticker,
                          status="open", limit=200)
        markets = read.payload.get("markets")
        if not isinstance(markets, list):
            raise ValueError("Kalshi /markets did not return a markets list")
        return [m for m in markets if isinstance(m, dict) and m.get("ticker") and not protected_reason(str(m["ticker"]))]

    def market(self, ticker: str) -> Read:
        _refuse_protected(ticker)
        return self._read(f"/markets/{quote(ticker, safe='')}", kind="market", entity_id=ticker)

    def orderbook(self, ticker: str) -> Read:
        _refuse_protected(ticker)
        return self._read(f"/markets/{quote(ticker, safe='')}/orderbook", kind="orderbook", entity_id=ticker,
                          depth=20)


def _refuse_protected(ticker: str) -> None:
    reason = protected_reason(ticker)
    if reason:
        raise KalshiRefused(reason, f"{ticker} is a protected scope for this lane")


# --------------------------------------------------------------------------- candidate matching


TOPIC_WORDS = {
    "IMPEACHMENT": {"impeach", "impeachment", "impeached"},
    "PERSONNEL": {"resign", "leave", "out", "fired", "confirm", "confirmed", "nominee", "secretary", "cabinet"},
    "LEGISLATION": {"bill", "pass", "act", "law", "vote", "house", "senate"},
    "SHUTDOWN_BUDGET": {"shutdown", "government", "funding", "budget", "debt"},
    "FED": {"fed", "rate", "rates", "fomc", "cut", "hike"},
    "MACRO_DATA": {"cpi", "inflation", "jobs", "payroll", "unemployment", "gdp"},
    "TRADE": {"tariff", "tariffs", "trade"},
    "COURTS": {"court", "ruling", "indicted", "indictment", "supreme", "charged"},
    "ELECTIONS": {"election", "win", "winner", "nominee", "primary", "race", "mayor", "governor"},
    "EARNINGS": {"earnings", "revenue", "eps"},
    "GEOPOLITICS": {"ceasefire", "war", "peace", "deal", "talks"},
}


@dataclass(frozen=True)
class Candidate:
    """A possible market for an event: never priced until the owner confirms it."""

    ticker: str
    event_ticker: str | None
    title: str
    score: float
    matched: tuple[str, ...]
    matcher_version: str = MATCHER_VERSION
    note: str = "CANDIDATE — a title/keyword match is not settlement equivalence; read the market's rules."


def _entity_words(event: EventRecord) -> set[str]:
    return set(keywords(event.key_entity))


def series_candidates(event: EventRecord, catalog: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    """Series whose title shares the event's key-entity words (required) and topic words."""
    ent = _entity_words(event)
    topic = TOPIC_WORDS.get(event.topic.value, set())
    scored = []
    for s in catalog:
        title = f"{s.get('title') or ''} {' '.join(map(str, s.get('tags') or []))}"
        words = set(keywords(title))
        hit_e, hit_t = ent & words, topic & words
        if not hit_e and event.topic.value not in ("FED", "SHUTDOWN_BUDGET", "MACRO_DATA"):
            continue
        score = 2.0 * len(hit_e) + len(hit_t)
        if score > 0:
            scored.append((score, str(s["ticker"]), s))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [s for _, _, s in scored[:limit]]


def market_candidates(event: EventRecord, markets: list[dict[str, Any]], *, limit: int = 10) -> list[Candidate]:
    """Open markets whose text shares the event's key-entity words. Deterministic order."""
    ent = _entity_words(event)
    topic = TOPIC_WORDS.get(event.topic.value, set())
    out = []
    for m in markets:
        ticker = str(m.get("ticker") or "")
        if not ticker or protected_reason(ticker):
            continue
        text = " ".join(str(m.get(k) or "") for k in ("title", "subtitle", "yes_sub_title", "rules_primary"))
        words = set(keywords(text))
        hit_e, hit_t = ent & words, topic & words
        if not hit_e and event.topic.value not in ("FED", "SHUTDOWN_BUDGET", "MACRO_DATA"):
            continue
        score = 2.0 * len(hit_e) + len(hit_t)
        if score <= 0:
            continue
        out.append(Candidate(ticker=ticker, event_ticker=m.get("event_ticker"), title=str(m.get("title") or ticker),
                             score=score, matched=tuple(sorted(hit_e | hit_t))))
    out.sort(key=lambda c: (-c.score, c.ticker))
    return out[:limit]


def rules_text(market_payload: dict[str, Any]) -> dict[str, str | None]:
    """The captured rules fields the owner must read before confirming a link."""
    m = market_payload.get("market", market_payload) if isinstance(market_payload, dict) else {}
    return {k: (str(m.get(k)) if m.get(k) is not None else None)
            for k in ("title", "subtitle", "yes_sub_title", "no_sub_title", "rules_primary", "rules_secondary",
                      "close_time", "expiration_time", "status", "settlement_sources")}
