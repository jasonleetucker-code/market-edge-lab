"""The news intelligence workflow over the evidence store (#192, ADR 0049).

One owner for every step the owner can trigger, from the CLI, the inbox or a timer:

    collect news → (transcripts) → events → research packet → analysis import (forecast)
    → market candidates → owner-confirmed link → quote refresh → pricing decision → resolution

Every step appends records to the v8 journal (`intel_records`). Nothing is updated in place:
a newer forecast supersedes an older one, and decisions keep the quote, fee and forecast they
used. Network access happens only in `collect_news`, `verify_sources` and the Kalshi steps.
All of them are bounded, and Kalshi refuses protected scopes and windows.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

from ..http import HttpFetchError, fetch
from ..storage import SnapshotStore
from . import registry
from .analysis_import import Analysis, import_pasted
from .contracts import (
    COLLECTABLE,
    INSUFFICIENT_EVIDENCE_TEXT,
    MAX_FEED_BYTES,
    MAX_FEED_GETS_PER_RUN,
    AccessStatus,
    Action,
    ClaimType,
    EvidenceType,
    ForecastBasis,
    LinkStatus,
    PriceAwareness,
    Rights,
    TranscriptMeta,
)
from .events import Evidence, EventRecord, StatusFacts, build_events, claim_verification, derive_status, \
    is_new_information
from .extract import EXTRACTOR_VERSION, entities_of, extract, topics_of
from .feeds import parse_feed
from .packet import Packet, build_packet
from .pricing import Forecast, PricingPolicy, PricingSheet, price_link, protected_reason
from .transcripts import TranscriptError, episode_key, parse_transcript, validate_meta

SCHEMA = "market-edge-intel-record/1"
USER_AGENT = "market-edge-lab/0.1 (read-only research feed reader)"
FEED_ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml, application/json;q=0.9, */*;q=0.1"
FEEDS_PARSER_VERSION = "intel-feeds-v1"
NEWS_REFRESH_MIN_INTERVAL = timedelta(minutes=15)
RUN_DEADLINE_S = 240.0  # a collection stops starting new feed GETs after ~4 minutes (unit cap is 6)
FEED_TIMEOUT_S = 15.0


def _intel_lock(store: SnapshotStore):
    """One news collection at a time per evidence DB (the 2-hour run vs an owner refresh)."""
    from ..forward import exclusive_lock

    return exclusive_lock(store.path.with_name(store.path.name + ".intel.lock"), timeout_s=2.0)


def _kalshi_lock(store: SnapshotStore):
    """The host's single Kalshi pacer lock, shared with forward and observation captures."""
    from ..forward import exclusive_lock
    from ..price_observations import LOCK_TIMEOUT_S, _lock_path

    return exclusive_lock(_lock_path(store.path), timeout_s=LOCK_TIMEOUT_S)
EVENT_WINDOW = timedelta(days=14)

Fetcher = Callable[..., Any]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _payload(row) -> dict[str, Any]:
    return json.loads(row["payload_json"])


def _latest_by_subject(store: SnapshotStore, kind: str) -> dict[str, tuple[int, dict[str, Any]]]:
    out: dict[str, tuple[int, dict[str, Any]]] = {}
    for row in store.intel_records(kind=kind):
        out[row["subject_id"]] = (int(row["id"]), _payload(row))
    return out


# ============================================================================ sources and collection


def _robots_allows(url: str, fetcher: Fetcher) -> tuple[bool, str]:
    """(allowed, signal). A robots.txt that refuses our UA (401/403) counts as a refusal."""
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        res = fetcher(robots_url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain, */*;q=0.1"},
                      retries=0, timeout=15.0, max_bytes=512 * 1024)
    except HttpFetchError as exc:
        if exc.status in (401, 403):
            return False, "ROBOTS_REFUSED"
        if exc.status in (404, 410):
            return True, "NO_ROBOTS"
        return False, f"ROBOTS_UNREADABLE_{exc.status or 'NETWORK'}"
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(res.body.decode("utf-8", "replace").splitlines())
    return (True, "ROBOTS_ALLOW") if parser.can_fetch(USER_AGENT, url) else (False, "ROBOTS_DISALLOW")


def verify_sources(store: SnapshotStore, *, now: datetime | None = None, fetcher: Fetcher = fetch,
                   only: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Re-verify every collectable feed: robots.txt plus one feed GET and a parse.

    A pass is recorded as a `verification` record, and lets collection proceed for 14 days. A
    failure records why. No other User-Agent is tried.
    """
    now = now or utcnow()
    wanted = set(only or ())
    results = []
    for cand, feed in registry.collectable_feeds():
        if wanted and cand.source_id not in wanted and feed.feed_id not in wanted:
            continue
        allowed, robots = _robots_allows(feed.url, fetcher)
        rec: dict[str, Any] = {"source_id": cand.source_id, "feed_id": feed.feed_id, "url": feed.url,
                               "checked_at_utc": iso(now), "robots": robots, "ok": False}
        if allowed:
            try:
                res = fetcher(feed.url, headers={"User-Agent": USER_AGENT, "Accept": FEED_ACCEPT}, retries=1,
                              timeout=20.0, max_bytes=MAX_FEED_BYTES)
                parsed = parse_feed(res.body, source_id=cand.source_id, rights=cand.rights, origin=cand.origin,
                                    aggregator=cand.aggregator, content_type=res.content_type)
                newest = max((i.published_utc for i in parsed.items if i.published_utc), default=None)
                rec.update(http_status=res.http_status, parse_ok=parsed.ok, items=len(parsed.items),
                           newest_item_utc=newest, error=parsed.error,
                           cross_host_redirect=urlsplit(res.final_url).netloc != urlsplit(feed.url).netloc)
                rec["ok"] = bool(parsed.ok and parsed.items and not rec["cross_host_redirect"])
            except HttpFetchError as exc:
                rec.update(http_status=exc.status, error=str(exc)[:200])
        store.append_intel_record(kind="verification", subject_id=feed.feed_id, schema=SCHEMA, payload=rec,
                                  recorded_at_utc=iso(now))
        results.append(rec)
        time.sleep(0) if fetcher is not fetch else time.sleep(0.3)
    return results


def feed_states(store: SnapshotStore, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Per-feed effective status, verification and last collection for display and gating."""
    now = now or utcnow()
    verifications = _latest_by_subject(store, "verification")
    ok_verifications: dict[str, str] = {}
    for row in store.intel_records(kind="verification"):
        p = _payload(row)
        if p.get("ok"):
            ok_verifications[row["subject_id"]] = p["checked_at_utc"]
    fetch_rows = {r["feed_id"]: r for r in store.intel_fetch_summary()}
    out = []
    for cand in registry.CANDIDATES:
        for feed in cand.feeds or (None,):
            fid = feed.feed_id if feed else None
            last = fetch_rows.get(fid) if fid else None
            signal = last["access_signal"] if last is not None else None
            v = verifications.get(fid, (None, None))[1] if fid else None
            if v and not v.get("ok") and v.get("robots") in ("ROBOTS_DISALLOW", "ROBOTS_REFUSED"):
                signal = signal or "ROBOTS_DISALLOW"
            status = registry.effective_status(cand, last_verified_ok_utc=ok_verifications.get(fid) if fid else None,
                                               now=now, last_access_signal=signal)
            out.append({
                "number": cand.number, "source_id": cand.source_id, "name": cand.name, "category": cand.category.value,
                "evidence_type": cand.evidence_type.value, "rights": cand.rights.value,
                "declared_status": cand.status.value, "status": status.value, "note": cand.note,
                "mechanism": cand.mechanism, "terms": cand.terms, "feed_id": fid, "url": feed.url if feed else None,
                "verified_ok_utc": ok_verifications.get(fid) if fid else None,
                "last_attempt_utc": last["attempted_at_utc"] if last is not None else None,
                "last_outcome": last["outcome"] if last is not None else None,
                "last_success_utc": last["last_success_utc"] if last is not None else None,
                "last_error": last["error"] if last is not None else None,
                "access_signal": signal,
            })
    return out


def collect_news(store: SnapshotStore, *, now: datetime | None = None, fetcher: Fetcher = fetch,
                 max_gets: int = MAX_FEED_GETS_PER_RUN, force: bool = False,
                 deadline_s: float = RUN_DEADLINE_S) -> dict[str, Any]:
    """One bounded collection run over every verified, collectable feed.

    Each feed is isolated: a failure is recorded and the run continues. Conditional GETs reuse
    the latest ETag/Last-Modified. Only public-domain sources keep raw bytes. Runs never
    overlap (a lock), and a run stops starting new GETs after `deadline_s`.
    """
    from ..forward import LockBusy

    try:
        with _intel_lock(store):
            return _collect_news(store, now=now, fetcher=fetcher, max_gets=max_gets, force=force,
                                 deadline_s=deadline_s)
    except LockBusy:
        return {"status": "DEFERRED", "detail": "another news collection is running"}


def _collect_news(store: SnapshotStore, *, now: datetime | None, fetcher: Fetcher, max_gets: int, force: bool,
                  deadline_s: float) -> dict[str, Any]:
    now = now or utcnow()
    started_clock = time.monotonic()
    last_run = store.latest_intel_record("run", "news")
    if last_run is not None and not force:
        last_at = datetime.fromisoformat(_payload(last_run)["started_at_utc"].replace("Z", "+00:00"))
        if now - last_at < NEWS_REFRESH_MIN_INTERVAL:
            return {"status": "DEFERRED", "detail": "a news collection ran less than 15 minutes ago",
                    "last_run_utc": _payload(last_run)["started_at_utc"]}
    run_id = f"intel-news-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    store.start_run(run_id)
    states = {s["feed_id"]: s for s in feed_states(store, now=now) if s["feed_id"]}
    gets = 0
    summary = {"run_id": run_id, "started_at_utc": iso(now), "feeds": 0, "ok": 0, "not_modified": 0, "failed": 0,
               "skipped": 0, "new_items": 0}
    for cand, feed in registry.collectable_feeds():
        summary["feeds"] += 1
        st = states.get(feed.feed_id, {})
        base = {"run_id": run_id, "source_id": cand.source_id, "feed_id": feed.feed_id, "requested_url": feed.url,
                "attempted_at_utc": iso(utcnow() if fetcher is fetch else now), "parser_version": FEEDS_PARSER_VERSION,
                "retained": "NONE"}
        if AccessStatus(st.get("status", "UNVERIFIED")) not in COLLECTABLE:
            store.record_intel_fetch({**base, "outcome": "SKIPPED", "error": f"status {st.get('status')}: verify first"})
            summary["skipped"] += 1
            continue
        if gets >= max_gets or time.monotonic() - started_clock > deadline_s:
            why = "per-run GET cap reached" if gets >= max_gets else "run deadline reached"
            store.record_intel_fetch({**base, "outcome": "SKIPPED", "error": why})
            summary["skipped"] += 1
            continue
        etag, last_mod = store.latest_validators(feed.feed_id)
        headers = {"User-Agent": USER_AGENT, "Accept": FEED_ACCEPT}
        if etag:
            headers["If-None-Match"] = etag
        if last_mod:
            headers["If-Modified-Since"] = last_mod
        gets += 1
        started = time.monotonic()
        try:
            res = fetcher(feed.url, headers=headers, retries=1, timeout=FEED_TIMEOUT_S, max_bytes=MAX_FEED_BYTES,
                          accept_not_modified=True, extra_response_headers=("etag", "last-modified"))
        except HttpFetchError as exc:
            signal = f"HTTP_{exc.status}" if exc.status in (401, 403) else None
            store.record_intel_fetch({**base, "outcome": "REFUSED" if signal else "FAILED", "http_status": exc.status,
                                      "access_signal": signal, "error": str(exc)[:300],
                                      "duration_ms": int((time.monotonic() - started) * 1000)})
            summary["failed"] += 1
            continue
        hdrs = dict(res.response_headers or ())
        if res.http_status == 304:
            store.record_intel_fetch({**base, "outcome": "NOT_MODIFIED", "http_status": 304, "etag": etag,
                                      "last_modified": last_mod, "duration_ms": res.duration_ms})
            summary["not_modified"] += 1
            continue
        if urlsplit(res.final_url).netloc != urlsplit(feed.url).netloc:
            store.record_intel_fetch({**base, "outcome": "REFUSED", "http_status": res.http_status,
                                      "access_signal": "CROSS_HOST_REDIRECT", "final_url": res.final_url,
                                      "error": "redirected to another host; not followed as content"})
            summary["failed"] += 1
            continue
        parsed = parse_feed(res.body, source_id=cand.source_id, rights=cand.rights, origin=cand.origin,
                            aggregator=cand.aggregator, content_type=res.content_type)
        retained, retrieval_id = "NONE", None
        if cand.rights is Rights.PUBLIC_DOMAIN:
            retrieval_id, _, _ = store.save_document(run_id=run_id, source_id="news_feeds_public",
                                                     doc_type=f"intel_feed:{feed.feed_id}", fetch=res)
            retained = "RAW"
        fetch_id = store.record_intel_fetch({
            **base, "final_url": res.final_url, "outcome": "OK" if parsed.ok else "FAILED",
            "http_status": res.http_status, "etag": hdrs.get("etag"), "last_modified": hdrs.get("last-modified"),
            "raw_sha256": hashlib.sha256(res.body).hexdigest(), "raw_bytes": len(res.body), "retained": retained,
            "document_retrieval_id": retrieval_id, "item_count": len(parsed.items), "error": parsed.error,
            "duration_ms": res.duration_ms})
        if not parsed.ok:
            summary["failed"] += 1
            continue
        rows = [{
            "fetch_id": fetch_id, "source_id": cand.source_id, "feed_id": feed.feed_id, "item_key": i.item_key,
            "content_sha256": i.content_sha256, "first_seen_utc": iso(now), "published_utc": i.published_utc,
            "updated_utc": i.updated_utc, "published_raw": i.published_raw, "title": i.title, "link": i.link,
            "canonical_url": i.canonical_url, "snippet": i.snippet, "cluster_key": i.cluster_key, "origin": i.origin,
            "via_aggregator": int(i.via_aggregator), "rights": cand.rights.value, "parser_version": FEEDS_PARSER_VERSION,
        } for i in parsed.items]
        added = store.insert_intel_items(rows)
        summary["new_items"] += added
        summary["ok"] += 1
    summary["gets"] = gets
    store.finish_run(run_id, status="succeeded" if summary["failed"] == 0 else "partial")
    store.append_intel_record(kind="run", subject_id="news", schema=SCHEMA, payload=summary, recorded_at_utc=iso(now))
    summary["events"] = refresh_events(store, now=now)
    summary["packets"] = prepare_packets(store, now=now)
    return summary


# ============================================================================ transcripts


def import_transcript(store: SnapshotStore, *, data: bytes, meta: dict[str, Any], filename: str | None = None,
                      now: datetime | None = None) -> dict[str, Any]:
    """Validate, store privately and extract one owner-supplied transcript. Duplicates are reported."""
    now = now or utcnow()
    tmeta: TranscriptMeta = validate_meta(meta, today=now.date())
    transcript = parse_transcript(data, filename=filename)
    key = episode_key(tmeta)
    for row in store.intel_records(kind="transcript"):
        p = _payload(row)
        if p["text_sha256"] == transcript.text_sha256 or row["subject_id"] == key:
            return {"status": "DUPLICATE", "transcript_id": row["subject_id"], "record_id": int(row["id"]),
                    "detail": "this episode or identical text was already imported"}
    blob = store.save_blob(transcript.text.encode("utf-8"))
    ex = extract(transcript.text, segments=transcript.segments)
    news = _news_evidence(store, now=now)
    claims = []
    for s in ex.sentences:
        if s.claim_type is ClaimType.OPINION and not s.topics:
            continue  # chatter without a topic is not research material
        ev = _claim_evidence(key, tmeta, s.index, s.text, s.claim_type, s.topics, s.entities)
        claims.append({"n": s.index, "text": s.text, "claim_type": s.claim_type.value,
                       "topics": [t.value for t in s.topics], "entities": list(s.entities),
                       "speaker": s.speaker, "timestamp": s.timestamp,
                       "verification": claim_verification(ev, news).value,
                       "new_information": is_new_information(ev, news)})
    payload = {"meta": asdict(tmeta), "format": transcript.format, "text_sha256": transcript.text_sha256,
               "blob_sha256": blob, "chars": len(transcript.text), "extractor_version": EXTRACTOR_VERSION,
               "topics": [t.value for t in ex.topics], "entities": list(ex.entities)[:30], "claims": claims[:400],
               "imported_at_utc": iso(now), "label": "OWNER-SUPPLIED TRANSCRIPT (private; commentary, not evidence)"}
    rid, _ = store.append_intel_record(kind="transcript", subject_id=key, schema=SCHEMA, payload=payload,
                                       recorded_at_utc=iso(now))
    refresh_events(store, now=now)
    prepare_packets(store, now=now)
    return {"status": "IMPORTED", "transcript_id": key, "record_id": rid, "claims": len(claims),
            "unverified": sum(1 for c in claims if c["verification"] == "UNVERIFIED"),
            "new_information": sum(1 for c in claims if c["new_information"])}


def _claim_evidence(key: str, meta: TranscriptMeta | dict, n: int, text: str, ctype: ClaimType, topics, entities
                    ) -> Evidence:
    podcast = meta.podcast if isinstance(meta, TranscriptMeta) else meta["podcast"]
    date = meta.published_date if isinstance(meta, TranscriptMeta) else meta.get("published_date")
    return Evidence(evidence_id=f"claim:{key[:16]}:{n}", kind="transcript_claim", source_id="podcast",
                    origin=f"podcast:{podcast.casefold()}", evidence_type=EvidenceType.COMMENTARY, title=text,
                    text=text, observed_utc=f"{date}T00:00:00Z" if date else None, topics=tuple(topics),
                    entities=tuple(entities), claim_type=ctype)


# ============================================================================ evidence and events


def _news_evidence(store: SnapshotStore, *, now: datetime) -> list[Evidence]:
    since = iso(now - EVENT_WINDOW)
    out = []
    for r in store.intel_items(since_utc=since):
        cand = registry.BY_ID.get(r["source_id"])
        etype = cand.evidence_type if cand else EvidenceType.REPORTING
        text = f"{r['title']}. {r['snippet'] or ''}"
        out.append(Evidence(evidence_id=f"item:{r['item_key'][:16]}", kind="news", source_id=r["source_id"],
                            origin=r["origin"], evidence_type=etype, title=r["title"], text=r["snippet"] or r["title"],
                            observed_utc=r["published_utc"] or r["first_seen_utc"], topics=topics_of(text),
                            entities=entities_of(text), link=r["link"]))
    return out


def _transcript_evidence(store: SnapshotStore) -> list[Evidence]:
    out = []
    for row in store.intel_records(kind="transcript"):
        p = _payload(row)
        from .contracts import Topic
        for c in p["claims"]:
            out.append(_claim_evidence(row["subject_id"], p["meta"], c["n"], c["text"], ClaimType(c["claim_type"]),
                                       tuple(Topic(t) for t in c["topics"]), tuple(c["entities"])))
    return out


def all_evidence(store: SnapshotStore, *, now: datetime | None = None) -> list[Evidence]:
    now = now or utcnow()
    return _news_evidence(store, now=now) + _transcript_evidence(store)


def current_events(store: SnapshotStore, *, now: datetime | None = None) -> tuple[EventRecord, ...]:
    return build_events(all_evidence(store, now=now))


def _event_payload(ev: EventRecord) -> dict[str, Any]:
    d = asdict(ev)
    d["topic"] = ev.topic.value
    d["verification"] = ev.verification.value
    return d


def refresh_events(store: SnapshotStore, *, now: datetime | None = None) -> int:
    """Append an event snapshot whenever an event's evidence changed. Returns records added."""
    now = now or utcnow()
    latest = _latest_by_subject(store, "event")
    added = 0
    for ev in current_events(store, now=now):
        payload = _event_payload(ev)
        prev = latest.get(ev.event_id)
        if prev and {k: v for k, v in prev[1].items() if k != "snapshot_utc"} == payload:
            continue
        payload["snapshot_utc"] = iso(now)
        store.append_intel_record(kind="event", subject_id=ev.event_id, schema=SCHEMA, payload=payload,
                                  recorded_at_utc=iso(now))
        added += 1
    return added


def event_by_id(store: SnapshotStore, event_id: str, *, now: datetime | None = None) -> EventRecord | None:
    for ev in current_events(store, now=now):
        if ev.event_id == event_id:
            return ev
    return None


# ============================================================================ packets and analyses


def create_packet(store: SnapshotStore, event_id: str, *, now: datetime | None = None,
                  horizon_date: str | None = None) -> Packet:
    """Build and record the research packet for one event (never any Kalshi data).

    `horizon_date` is the owner's forecast horizon (YYYY-MM-DD); default end of the current year."""
    now = now or utcnow()
    ev = event_by_id(store, event_id, now=now)
    if ev is None:
        raise KeyError(f"no current event {event_id!r}")
    if horizon_date is not None and horizon_date < iso(now)[:10]:
        raise ValueError("the forecast horizon must not be in the past")
    names = {c.source_id: c.name for c in registry.CANDIDATES}
    horizon = horizon_date or f"{now.year}-12-31"
    packet = build_packet(ev, all_evidence(store, now=now), created_utc=iso(now), source_names=names,
                          horizon_date=horizon)
    if store.latest_intel_record("packet", packet.packet_id) is None:
        store.append_intel_record(kind="packet", subject_id=packet.packet_id, schema=SCHEMA, recorded_at_utc=iso(now),
                                  payload={"event_id": ev.event_id, "packet_sha256": packet.packet_sha256,
                                           "text": packet.text, "evidence_map": packet.evidence_map,
                                           "claim_map": packet.claim_map, "outcome_ids": packet.outcome_ids,
                                           "created_utc": iso(now), "horizon_date": horizon,
                                           "horizon_set_by": "owner" if horizon_date else "default",
                                           "outcomes": [asdict(o) for o in ev.outcomes]})
    return packet


PACKETS_PER_RUN = 30


def prepare_packets(store: SnapshotStore, *, now: datetime | None = None, top: int = PACKETS_PER_RUN) -> int:
    """Record packets for the best-supported current events, so the read-only dashboard can show
    them and imports can be validated. Local only. Returns packets newly recorded."""
    now = now or utcnow()
    before = len(store.intel_records(kind="packet"))
    for ev in current_events(store, now=now)[:top]:
        create_packet(store, ev.event_id, now=now)
    return len(store.intel_records(kind="packet")) - before


def latest_packet_for_event(store: SnapshotStore, event_id: str) -> Packet | None:
    best = None
    for row in store.intel_records(kind="packet"):
        if _payload(row)["event_id"] == event_id:
            best = row
    return stored_packet(store, best["subject_id"]) if best is not None else None


def stored_packet(store: SnapshotStore, packet_id: str | None) -> Packet | None:
    if not packet_id:
        return None
    row = store.latest_intel_record("packet", str(packet_id))
    if row is None:
        return None
    p = _payload(row)
    ev_map = tuple(tuple(x) for x in p["evidence_map"])
    cl_map = tuple(tuple(x) for x in p["claim_map"])
    return Packet(packet_id=row["subject_id"], packet_sha256=p["packet_sha256"], event_id=p["event_id"],
                  text=p["text"], evidence_ids=tuple(a for a, _ in ev_map), evidence_map=ev_map,
                  outcome_ids=tuple(p["outcome_ids"]), claim_ids=tuple(a for a, _ in cl_map), claim_map=cl_map)


def _first_quote_at(store: SnapshotStore, outcome_id: str) -> str | None:
    tickers = {p["ticker"] for _, p in [(None, _payload(r)) for r in store.intel_records(kind="link", subject_id=outcome_id)]}
    times = [_payload(r)["received_at_utc"] for t in tickers for r in store.intel_records(kind="quote", subject_id=t)]
    return min(times) if times else None


def import_analysis(store: SnapshotStore, pasted: str, *, now: datetime | None = None,
                    owner_judgment: bool = False) -> dict[str, Any]:
    """Validate a pasted assistant reply and record forecasts per outcome. `owner_judgment` is set
    only by the owner's explicit choice (CLI flag or dashboard checkbox), never by the pasted text."""
    now = now or utcnow()
    analysis: Analysis = import_pasted(pasted, lambda pid: stored_packet(store, pid), owner_judgment=owner_judgment)
    arid, asha = store.append_intel_record(
        kind="analysis", subject_id=analysis.packet_id, schema=SCHEMA, recorded_at_utc=iso(now),
        payload={"label": "MANUALLY IMPORTED AI ANALYSIS (unvalidated)" if analysis.basis is
                 ForecastBasis.AI_ASSISTED_UNVALIDATED else "OWNER JUDGMENT (unvalidated)",
                 "basis": analysis.basis.value, "assistant": analysis.assistant, "event_id": analysis.event_id,
                 "summary": analysis.summary, "market_price_seen": analysis.market_price_seen,
                 "analysis_json": analysis.canonical_json, "claims": [asdict(c) for c in analysis.claims]})
    forecasts = []
    for o in analysis.outcomes:
        prev = store.latest_intel_record("forecast", o.outcome_id)
        first_quote = _first_quote_at(store, o.outcome_id)
        if analysis.market_price_seen:
            awareness = PriceAwareness.PRICE_AWARE
        elif first_quote is None or first_quote > iso(now):
            awareness = PriceAwareness.PRICE_BLIND
        else:
            awareness = PriceAwareness.PRICE_AWARE
        fid = f"fc-{hashlib.sha256(f'{o.outcome_id}|{asha}'.encode()).hexdigest()[:12]}"
        payload = {"forecast_id": fid, "event_id": analysis.event_id, "outcome_id": o.outcome_id,
                   "point": o.probability, "low": o.low, "high": o.high, "abstained": o.abstain,
                   "basis": analysis.basis.value, "assistant": analysis.assistant, "packet_id": analysis.packet_id,
                   "packet_sha256": analysis.packet_sha256, "analysis_record_id": arid,
                   "reasoning": o.reasoning, "main_risk": o.main_risk, "key_evidence_ids": list(o.key_evidence_ids),
                   "price_awareness": awareness.value, "calibrated": False, "recorded_at_utc": iso(now),
                   "horizon_date": (_payload(store.latest_intel_record("packet", analysis.packet_id)) or {}).get(
                       "horizon_date"),
                   "label": "PROVISIONAL — no calibration history"}
        rid, _ = store.append_intel_record(kind="forecast", subject_id=o.outcome_id, schema=SCHEMA, payload=payload,
                                           recorded_at_utc=iso(now), supersedes_id=int(prev["id"]) if prev else None)
        forecasts.append({"forecast_id": fid, "outcome_id": o.outcome_id, "abstained": o.abstain, "record_id": rid})
    return {"status": "IMPORTED", "analysis_record_id": arid, "basis": analysis.basis.value,
            "forecasts": forecasts}


def active_forecast(store: SnapshotStore, outcome_id: str) -> dict[str, Any] | None:
    row = store.latest_intel_record("forecast", outcome_id)
    return _payload(row) if row else None


def _forecast_obj(p: dict[str, Any] | None) -> Forecast | None:
    if not p:
        return None
    return Forecast(forecast_id=p["forecast_id"], event_id=p["event_id"], outcome_id=p["outcome_id"],
                    point=p["point"], low=p["low"], high=p["high"], basis=ForecastBasis(p["basis"]),
                    calibrated=bool(p.get("calibrated")), recorded_at_utc=p["recorded_at_utc"],
                    abstained=bool(p.get("abstained")))


# ============================================================================ Kalshi: candidates, links, quotes


def discover_markets(store: SnapshotStore, event_id: str, *, now: datetime | None = None, reader=None,
                     categories: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Bounded catalog search for one event. Results are CANDIDATES, never priced."""
    from .kalshi_link import CATEGORIES, Reader, market_candidates, rules_text, series_candidates

    now = now or utcnow()
    ev = event_by_id(store, event_id, now=now)
    if ev is None:
        raise KeyError(f"no current event {event_id!r}")
    from ..forward import LockBusy

    run_id = f"intel-kalshi-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    try:
        lock = _kalshi_lock(store)
        lock.__enter__()
    except LockBusy:
        raise KalshiRefusedBusy() from None
    store.start_run(run_id)
    try:
        rd = reader or Reader(store, run_id=run_id, now=now)
        if reader is not None:
            rd.run_id = run_id
        catalog: list[dict[str, Any]] = []
        for cat in categories or CATEGORIES:
            catalog.extend(rd.series_catalog(cat))
        series = series_candidates(ev, catalog)
        cands = []
        rules: dict[str, dict[str, Any]] = {}
        for s in series:
            listed = rd.open_markets(str(s["ticker"]))
            rules.update({str(m.get("ticker")): rules_text(m) for m in listed})
            cands.extend(market_candidates(ev, listed))
        cands.sort(key=lambda c: (-c.score, c.ticker))
        store.finish_run(run_id, status="succeeded")
    except Exception:
        store.finish_run(run_id, status="failed")
        raise
    finally:
        lock.__exit__(None, None, None)
    payload = {"event_id": event_id, "searched_utc": iso(now), "series": [str(s["ticker"]) for s in series],
               "candidates": [{**asdict(c), "rules": rules.get(c.ticker)} for c in cands[:15]], "gets": rd.budget.used}
    store.append_intel_record(kind="candidates", subject_id=event_id, schema=SCHEMA, payload=payload,
                              recorded_at_utc=iso(now))
    return payload


def record_link(store: SnapshotStore, *, outcome_id: str, ticker: str, status: str, rules_read: bool,
                yes_matches_outcome: bool, now: datetime | None = None, note: str | None = None) -> dict[str, Any]:
    """The owner's decision on a candidate. CONFIRMED needs both attestations; protected scopes are refused."""
    now = now or utcnow()
    st = LinkStatus(status)
    reason = protected_reason(ticker)
    if reason:
        raise ValueError(f"{ticker} is a protected scope for this lane ({reason})")
    if st is LinkStatus.CONFIRMED and not (rules_read and yes_matches_outcome):
        raise ValueError("a link is CONFIRMED only after you read the market's rules and its YES means this outcome")
    payload = {"outcome_id": outcome_id, "ticker": ticker, "status": st.value, "rules_read": rules_read,
               "yes_matches_outcome": yes_matches_outcome, "decided_utc": iso(now), "by": "owner", "note": note}
    rid, _ = store.append_intel_record(kind="link", subject_id=outcome_id, schema=SCHEMA, payload=payload,
                                       recorded_at_utc=iso(now))
    return {**payload, "record_id": rid}


def confirmed_links(store: SnapshotStore) -> list[dict[str, Any]]:
    out = []
    for _, p in _latest_by_subject(store, "link").values():
        if p["status"] == LinkStatus.CONFIRMED.value:
            out.append(p)
    return out


def refresh_quotes(store: SnapshotStore, *, now: datetime | None = None, reader=None,
                   only_outcome: str | None = None, policy: PricingPolicy | None = None) -> dict[str, Any]:
    """Read market + order book for every confirmed link, then price and record a decision for each."""
    from .kalshi_link import KalshiRefused, Reader

    now = now or utcnow()
    links = [l for l in confirmed_links(store) if not only_outcome or l["outcome_id"] == only_outcome]
    if not links:
        return {"status": "NOTHING_TO_DO", "detail": "no confirmed market links", "decisions": []}
    from ..forward import LockBusy

    run_id = f"intel-quotes-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    try:
        lock = _kalshi_lock(store)
        lock.__enter__()
    except LockBusy:
        return {"status": "REFUSED", "code": "LOCK_BUSY", "detail": "another Kalshi capture holds the host lock",
                "decisions": []}
    store.start_run(run_id)
    decisions, errors = [], []
    try:
        rd = reader or Reader(store, run_id=run_id, now=now)
        if reader is not None:
            rd.run_id = run_id
        for link in links:
            ticker = link["ticker"]
            try:
                m = rd.market(ticker)
                ob = rd.orderbook(ticker)
            except KalshiRefused as exc:
                errors.append({"ticker": ticker, "error": exc.code})
                if exc.code == "BUDGET_EXHAUSTED":
                    break
                continue
            except (HttpFetchError, ValueError) as exc:
                errors.append({"ticker": ticker, "error": str(exc)[:200]})
                continue
            store.append_intel_record(kind="quote", subject_id=ticker, schema=SCHEMA, recorded_at_utc=iso(now),
                                      payload={"ticker": ticker, "market_snapshot_id": m.snapshot_id,
                                               "orderbook_snapshot_id": ob.snapshot_id,
                                               "received_at_utc": ob.received_at_utc})
            _maybe_resolve(store, link, m.payload, now=now)
            # The decision is made after its quote arrived: never date it before the receipt (a live
            # book received moments after the run started would otherwise read as future-stamped).
            received = _parse_time(ob.received_at_utc)
            decided_at = max(now, received) if received is not None else now
            decisions.append(decide(store, link=link, market=m.payload, orderbook=ob.payload,
                                    received_at_utc=ob.received_at_utc,
                                    evidence_id=f"snapshot:{ob.snapshot_id}", now=decided_at, policy=policy))
        store.finish_run(run_id, status="succeeded" if not errors else "partial")
    except KalshiRefused as exc:
        store.finish_run(run_id, status="failed", error=exc.code)
        return {"status": "REFUSED", "code": exc.code, "detail": exc.detail, "decisions": []}
    except Exception:
        store.finish_run(run_id, status="failed")
        raise
    finally:
        lock.__exit__(None, None, None)
    return {"status": "OK" if not errors else "PARTIAL", "decisions": decisions, "errors": errors}


def KalshiRefusedBusy():
    from .kalshi_link import KalshiRefused

    return KalshiRefused("LOCK_BUSY", "another Kalshi capture holds the host lock; try again shortly")


def _parse_time(text: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else None


def _maybe_resolve(store: SnapshotStore, link: dict[str, Any], market_payload: dict[str, Any], *, now: datetime) -> None:
    m = market_payload.get("market", market_payload)
    result = str(m.get("result") or "").lower()
    if result in ("yes", "no") and str(m.get("status") or "").lower() in ("settled", "finalized", "determined"):
        if store.latest_intel_record("resolution", link["outcome_id"]) is None:
            record_resolution(store, outcome_id=link["outcome_id"], result=result.upper(),
                              source=f"kalshi market {link['ticker']} result (status {m.get('status')})", now=now)


def _sheet_payload(sheet: PricingSheet) -> dict[str, Any]:
    def conv(v):
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [conv(x) for x in v]
        if hasattr(v, "value"):
            return v.value
        return v
    return conv(asdict(sheet))


def decide(store: SnapshotStore, *, link: dict[str, Any], market: dict[str, Any], orderbook: dict[str, Any] | None,
           received_at_utc: str | None, evidence_id: str | None, now: datetime | None = None,
           policy: PricingPolicy | None = None) -> dict[str, Any]:
    """Price one confirmed link against its active forecast and append the decision (SKIP included)."""
    now = now or utcnow()
    fc = active_forecast(store, link["outcome_id"])
    sheet = price_link(market_raw=market, orderbook_raw=orderbook, quote_received_at_utc=received_at_utc,
                       quote_evidence_id=evidence_id, forecast=_forecast_obj(fc), as_of_utc=iso(now),
                       policy=policy or PricingPolicy())
    m = market.get("market", market) if isinstance(market, dict) else {}
    payload = {"outcome_id": link["outcome_id"], "ticker": link["ticker"], "forecast_id": fc and fc["forecast_id"],
               "forecast_horizon_date": fc and fc.get("horizon_date"), "market_close_utc": m.get("close_time"),
               "horizon_check": _horizon_check(fc, m),
               "forecast_basis": fc and fc["basis"], "price_awareness": fc and fc.get("price_awareness"),
               "decided_utc": iso(now), "sheet": _sheet_payload(sheet),
               "label": "HYPOTHETICAL RESEARCH DECISION — no order, no fill, not a recommendation to trade"}
    rid, _ = store.append_intel_record(kind="decision", subject_id=link["outcome_id"], schema=SCHEMA, payload=payload,
                                       recorded_at_utc=iso(now))
    return {"record_id": rid, "ticker": link["ticker"], "action": sheet.action.value,
            "explanation": sheet.explanation, "reasons": list(sheet.action_reasons)}


def _horizon_check(fc: dict[str, Any] | None, market: dict[str, Any]) -> str:
    """Whether the forecast's horizon and the market's close are within two days (a flag, never a fix)."""
    h, close = (fc or {}).get("horizon_date"), market.get("close_time")
    try:
        gap = abs((datetime.fromisoformat(str(h)) - datetime.fromisoformat(str(close)[:10])).days)
    except (TypeError, ValueError):
        return "UNKNOWN"
    return "ALIGNED" if gap <= 2 else "MISMATCH"


def record_resolution(store: SnapshotStore, *, outcome_id: str, result: str, source: str,
                      now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    if result not in ("YES", "NO"):
        raise ValueError("result must be YES or NO")
    payload = {"outcome_id": outcome_id, "result": result, "source": source, "recorded_utc": iso(now)}
    rid, _ = store.append_intel_record(kind="resolution", subject_id=outcome_id, schema=SCHEMA, payload=payload,
                                       recorded_at_utc=iso(now))
    return {**payload, "record_id": rid}


# ============================================================================ performance


def performance(store: SnapshotStore) -> dict[str, Any]:
    """Brier score of forecasts made before resolution, and hypothetical P&L of INVESTIGATE decisions.

    Only forecasts recorded before the resolution count, and every forecast in a superseded chain
    counts at its own time: nothing is rewritten after the outcome is known.
    """
    from ..scoring import brier_score

    resolutions = {s: p for s, (_, p) in _latest_by_subject(store, "resolution").items()}
    pairs_by_basis: dict[str, list[tuple[float, int]]] = {}
    pnl = []
    for row in store.intel_records(kind="forecast"):
        p = _payload(row)
        res = resolutions.get(p["outcome_id"])
        if not res or p.get("abstained") or p.get("point") is None or p["recorded_at_utc"] >= res["recorded_utc"]:
            continue
        pairs_by_basis.setdefault(p["basis"], []).append((float(p["point"]), 1 if res["result"] == "YES" else 0))
    for row in store.intel_records(kind="decision"):
        p = _payload(row)
        res = resolutions.get(p["outcome_id"])
        sheet = p["sheet"]
        if not res or sheet.get("action") != Action.INVESTIGATE.value or not sheet.get("best_side"):
            continue
        side = sheet["yes"] if sheet["best_side"] == "YES" else sheet["no"]
        if not side or side.get("all_in_cost") is None:
            continue
        payoff = Decimal(1) if res["result"] == sheet["best_side"] else Decimal(0)
        pnl.append(str(payoff - Decimal(side["all_in_cost"])))
    total = sum((Decimal(x) for x in pnl), Decimal(0)) if pnl else None
    return {"brier_by_basis": {b: {"n": len(v), "brier": brier_score(v)} for b, v in pairs_by_basis.items()},
            "resolved_outcomes": len(resolutions), "hypothetical_entries": len(pnl),
            "hypothetical_pnl_per_contract": str(total) if total is not None else None,
            "label": "PROVISIONAL / HYPOTHETICAL — far too few resolutions to say anything about an edge"}


def status(store: SnapshotStore, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    run = store.latest_intel_record("run", "news")
    feeds = feed_states(store, now=now)
    counts: dict[str, int] = {}
    for f in feeds:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    return {"as_of_utc": iso(now), "last_news_run": _payload(run) if run else None, "feed_status_counts": counts,
            "items": len(store.intel_items(limit=100000)), "events": len(current_events(store, now=now)),
            "transcripts": len(store.intel_records(kind="transcript")),
            "packets": len(store.intel_records(kind="packet")), "forecasts": len(store.intel_records(kind="forecast")),
            "confirmed_links": len(confirmed_links(store)), "decisions": len(store.intel_records(kind="decision")),
            "insufficient_evidence_text": INSUFFICIENT_EVIDENCE_TEXT}
