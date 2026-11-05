"""SYNTHETIC news-intelligence data for the demo and the /gallery/intel states (issue 192). Demo/test mode only.

Everything is written through the real APIs into a store the caller owns (a fresh temporary one):
`store.insert_intel_items` / `record_intel_fetch` for collected items (no network), `service.import_transcript`,
`service.create_packet`, `service.import_analysis`, `service.discover_markets` and `service.refresh_quotes` with an
in-memory Kalshi reader (no request is made), and `service.record_link`. Headlines, tickers, rules and prices are
invented, links point at example.com, and every page that shows them carries the SYNTHETIC UI DEMO strip.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..http import FetchResult
from ..storage import SnapshotStore
from . import data as d

DEMO_TICKER = "KXPOLDEMO-26DEC31-IMP"
DEMO_OTHER = "KXPOLDEMO-26DEC31-RES"
DEMO_CPI = "KXCPI-26DEC-DEMO"
TRANSCRIPT = """Host: Welcome back to the synthetic demo show.
Guest: The House clerk recorded articles of impeachment against Jane Doe on Thursday, according to the clerk's office.
Guest: I think Jane Doe will be impeached before the end of the year.
Host: Some people say the vote could slip into January.
"""
HEADLINES = (  # (source_id, feed_id, origin, hours ago, title, snippet)
    ("bbc", "bbc_top", "bbc", 2, "House Democrats file articles of impeachment against Secretary Jane Doe",
     "SYNTHETIC demo item. Articles of impeachment were filed against Jane Doe on Thursday."),
    ("guardian", "guardian_us", "guardian", 3, "Jane Doe impeachment articles filed as House leaders weigh vote",
     "SYNTHETIC demo item. House leaders have not scheduled an impeachment vote on Jane Doe."),
    ("federal_register", "federal_register_newest", "federal_register", 5,
     "Notice: House resolution on Jane Doe impeachment articles", "SYNTHETIC demo item. A primary-source notice."),
    ("politico", "politico_politics", "politico", 4, "Senate prepares for possible Jane Doe impeachment trial",
     "SYNTHETIC demo item. Senate staff are reviewing trial procedures."),
    ("fed", "fed_press_all", "fed", 6, "Federal Reserve issues FOMC statement on interest rates",
     "SYNTHETIC demo item. The Committee kept the target range unchanged."),
    ("thestreet", "thestreet_full", "thestreet", 7, "Markets steady after Fed holds rates",
     "SYNTHETIC demo item. Stocks were little changed."),
)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fetch(url: str, at: datetime) -> FetchResult:
    return FetchResult(requested_url=url, final_url=url, http_status=200, content_type="application/json", body=b"{}",
                       received_at_utc=at.isoformat(), duration_ms=1, attempts=1)


def add_items(store: SnapshotStore, now: datetime, headlines=HEADLINES, *, run: str = "intel-demo-news") -> None:
    """Collected items as the collector stores them (one fetch per feed), plus the run record."""
    from ..intel import service

    run_id = f"{run}-{now.strftime('%Y%m%dT%H%M%SZ')}"
    store.start_run(run_id)
    for n, (source, feed, origin, hours, title, snippet) in enumerate(headlines):
        at = now - timedelta(hours=hours)
        fid = store.record_intel_fetch({
            "run_id": run_id, "source_id": source, "feed_id": feed, "requested_url": f"https://example.com/{feed}",
            "attempted_at_utc": _iso(at), "outcome": "OK", "http_status": 200, "retained": "NONE",
            "item_count": 1, "parser_version": service.FEEDS_PARSER_VERSION})
        key = hashlib.sha256(f"{source}|{n}|{title}".encode()).hexdigest()
        store.insert_intel_items([{
            "fetch_id": fid, "source_id": source, "feed_id": feed, "item_key": key,
            "content_sha256": hashlib.sha256(f"{title}|{snippet}".encode()).hexdigest(), "first_seen_utc": _iso(at),
            "published_utc": _iso(at), "updated_utc": None, "published_raw": None, "title": title,
            "link": f"https://example.com/demo/{feed}/{n}", "canonical_url": f"https://example.com/demo/{feed}/{n}",
            "snippet": snippet, "cluster_key": key[:16], "origin": origin, "via_aggregator": 0,
            "rights": "HEADLINE_SNIPPET", "parser_version": service.FEEDS_PARSER_VERSION}])
    store.finish_run(run_id, status="succeeded")
    store.append_intel_record(kind="run", subject_id="news", schema=service.SCHEMA, recorded_at_utc=_iso(now),
                              payload={"run_id": run_id, "started_at_utc": _iso(now - timedelta(minutes=30)),
                                       "feeds": len(headlines), "ok": len(headlines), "not_modified": 0, "failed": 0,
                                       "skipped": 0, "new_items": len(headlines)})
    service.refresh_events(store, now=now)
    service.prepare_packets(store, now=now)


def market(ticker: str, *, close: datetime, title: str, rules: str) -> dict[str, Any]:
    return {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "status": "active", "title": title,
            "subtitle": "", "yes_sub_title": "Yes", "no_sub_title": "No", "close_time": _iso(close),
            "expected_expiration_time": _iso(close + timedelta(hours=12)),
            "latest_expiration_time": _iso(close + timedelta(days=7)), "market_type": "binary",
            "price_level_structure": "linear_cent",
            "price_ranges": [{"start": "0.0000", "end": "1.0000", "step": "0.0100"}],
            "rules_primary": rules, "rules_secondary": "SYNTHETIC demo rules: invented for the demo only.",
            "settlement_timer_seconds": 3600, "result": "", "can_close_early": True}


BOOK = {"orderbook_fp": {"no_dollars": [["0.5800", "40.00"], ["0.6200", "75.00"]],
                         "yes_dollars": [["0.3400", "50.00"], ["0.3600", "120.00"]]}}


class FakeKalshi:
    """An in-memory Kalshi: answers the reader's GETs from fixed SYNTHETIC payloads. No request is made."""

    def __init__(self, markets: list[dict[str, Any]], received: datetime) -> None:
        self.markets = {m["ticker"]: m for m in markets}
        self.received = received

    def __call__(self, url: str):
        path = url.split("?", 1)[0]
        if path.endswith("/series"):
            payload = {"series": [{"ticker": "KXPOLDEMO", "title": "Jane Doe impeachment", "tags": ["Politics"]}]}
        elif path.endswith("/markets"):
            payload = {"markets": list(self.markets.values())}
        elif path.endswith("/orderbook"):
            payload = BOOK
        else:
            payload = {"market": self.markets[path.rsplit("/", 1)[1]]}
        return json.loads(json.dumps(payload)), _fetch(url, self.received)


def _reader(store: SnapshotStore, fake: FakeKalshi, now: datetime):
    from ..intel.kalshi_link import Reader

    return Reader(store, run_id="unused", now=now, getter=fake, check_window=False)


def populate(store: SnapshotStore, now: datetime, *, state: str = "populated") -> None:
    """One SYNTHETIC workflow: news → transcript → packet → analysis → candidates → link → priced decision.

    `state`: populated (fresh decision), stale (priced 3 h ago), unsupported (a KXCPI-series link, no fee
    schedule), insufficient (the analysis abstains)."""
    from ..intel import service
    from ..intel.analysis_import import extract_object

    now = now.astimezone(timezone.utc).replace(microsecond=0)
    add_items(store, now)
    service.import_transcript(store, data=TRANSCRIPT.encode(), now=now - timedelta(minutes=50),
                              meta={"podcast": "Synthetic Politics Pod", "episode": "Demo episode 1 (SYNTHETIC)",
                                    "published_date": (now - timedelta(days=1)).date().isoformat(),
                                    "transcript_source": "synthetic demo text"})
    ev = next((e for e in service.current_events(store, now=now) if e.topic.value == "IMPEACHMENT"), None)
    if ev is None or not ev.outcomes:
        return
    packet = service.latest_packet_for_event(store, ev.event_id) or service.create_packet(store, ev.event_id, now=now)
    obj = extract_object(packet.text)
    obj["assistant"] = "Synthetic assistant (demo)"
    obj["summary"] = "SYNTHETIC: articles filed; no floor vote is scheduled."
    for o in obj["outcomes"]:
        if state == "insufficient":
            o.update(abstain=True, reasoning="SYNTHETIC: the evidence cannot support an estimate.",
                     main_risk="unknown")
        else:
            o.update(probability=0.55, low=0.45, high=0.65, reasoning="SYNTHETIC: E1 and E2 report filed articles; "
                     "no vote is scheduled.", key_evidence_ids=["E1"], main_risk="Leaders table the articles.")
    service.import_analysis(store, "```json\n" + json.dumps(obj) + "\n```", now=now - timedelta(minutes=40))
    # The forecast horizon defaults to Dec 31 of this year: the populated market closes then (ALIGNED); the stale
    # state's market closes 40 days out, so its card also shows the horizon MISMATCH flag.
    close = now + timedelta(days=40) if state == "stale" else datetime(now.year, 12, 31, 23, 0, tzinfo=timezone.utc)
    ticker = DEMO_CPI if state == "unsupported" else DEMO_TICKER
    markets = [market(ticker, close=close, title="SYNTHETIC: Will Jane Doe be impeached before 2027?",
                      rules="SYNTHETIC: If the House impeaches Jane Doe before Dec 31, 2026, the market resolves Yes."),
               market(DEMO_OTHER, close=close, title="SYNTHETIC: Will Jane Doe resign before 2027?",
                      rules="SYNTHETIC: If Jane Doe resigns before Dec 31, 2026, the market resolves Yes.")]
    priced_at = now - timedelta(hours=3) if state == "stale" else now - timedelta(minutes=2)
    fake = FakeKalshi(markets, priced_at)
    try:
        service.discover_markets(store, ev.event_id, now=priced_at - timedelta(minutes=5),
                                 reader=_reader(store, fake, priced_at), categories=("Politics",))
    except Exception:  # noqa: BLE001 - candidates are optional in a synthetic state
        pass
    outcome = next((o.outcome_id for o in ev.outcomes if o.slug == "impeached"), ev.outcomes[0].outcome_id)
    service.record_link(store, outcome_id=outcome, ticker=ticker, status="CONFIRMED", rules_read=True,
                        yes_matches_outcome=True, now=priced_at - timedelta(minutes=1))
    service.refresh_quotes(store, now=priced_at, reader=_reader(store, fake, priced_at))


def build_store(root: Path, now: datetime, state: str) -> SnapshotStore:
    store = SnapshotStore(root / f"intel_{state}.sqlite3")
    if state == "empty":
        return store
    if state in ("blocked", "today"):
        add_items(store, now)
        return store
    populate(store, now, state=state)
    return store


@lru_cache(maxsize=2)
def _views(hour_key: str) -> dict[str, tuple[d.Loaded, str]]:
    from ..intel.view import build_view

    now = datetime.fromisoformat(hour_key)
    root = Path(tempfile.mkdtemp(prefix="edge-lab-intel-gallery-"))
    beat = {"schema": "intel-heartbeat/1", "at_utc": _iso(now - timedelta(minutes=3))}
    old_beat = {"schema": "intel-heartbeat/1", "at_utc": _iso(now - timedelta(hours=7))}
    spec = {  # name: (store state, tab, inbox configured, heartbeat)
        "populated": ("populated", "opportunities", True, beat),
        "today": ("today", "today", True, beat),
        "stale": ("stale", "opportunities", True, old_beat),
        "unsupported": ("unsupported", "opportunities", True, beat),
        "insufficient": ("insufficient", "opportunities", True, beat),
        "blocked": ("blocked", "today", True, None),
        "not_enabled": ("blocked", "transcripts", False, None),
        "empty": ("empty", "today", True, beat),
    }
    out: dict[str, tuple[d.Loaded, str]] = {}
    try:
        stores: dict[str, SnapshotStore] = {}
        for name, (state, tab, inbox, hb) in spec.items():
            try:
                store = stores.get(state) or build_store(root, now, state)
                stores[state] = store
                ro = SnapshotStore.open_readonly(store.path)
                out[name] = (d.Loaded(d.OK, build_view(ro, now=now, inbox_root=(root / "inbox") if inbox else None,
                                                       heartbeat=hb)), tab)
            except Exception as exc:  # noqa: BLE001 - a broken fixture shows as an error state
                out[name] = (d.Loaded(d.ERROR, message=d.short_error(exc)), tab)
        out["error"] = (d.Loaded(d.ERROR, message="ReadOnlyStoreError: evidence store schema v7 != code v8; "
                                                  "refusing to analyse"), "today")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return out


def synthetic_intel_views(now: datetime) -> dict[str, tuple[d.Loaded, str]]:
    """Every gallery state (name → (loaded view, tab to show)), built once per hour."""
    now = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return _views(now.isoformat())


def demo_intel(store: SnapshotStore, root: Path, now: datetime) -> Path:
    """The demo's intel workspace: a populated SYNTHETIC workflow and an empty inbox.

    No heartbeat is written: no collector runs in the demo, so the page honestly says submissions would wait
    (the "processed by the collector" state is in /gallery/intel)."""
    populate(store, now)
    inbox = root / "intel_inbox"
    inbox.mkdir(mode=0o700)
    return inbox
