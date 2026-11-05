"""Read-only view model of the news intelligence workspace (#192, ADR 0049).

`build_view` gathers everything the Terminal's intel workspace shows, from one evidence store
opened read-only (`SnapshotStore.open_readonly`), the private inbox directory and the collector's
heartbeat. It **computes nothing financial**: prices, fees, EVs, maximum prices and actions are
the stored decision sheets (`service.decide`) passed through verbatim. It also never writes:

- it calls only reading functions of `service` (`feed_states`, `current_events`,
  `latest_packet_for_event`, `performance`) and the store's read methods;
- it never calls `service.create_packet`, `refresh_events` or anything else that appends;
- it lists the inbox with `inbox.pending` and never creates its directories.

Each section carries a provenance label (`LABELS`) so collected news, deterministic
classification, imported AI analysis, owner judgment, provisional forecasts and economics are
never confused. Economics read VERIFIED only when a decision's side records `fee_claimable`
true; none does today (every intel series is UNVERIFIED or UNSUPPORTED).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from ..freshness import parse_utc
from . import inbox as inbox_mod
from . import registry, service
from .contracts import INSUFFICIENT_EVIDENCE_TEXT, LinkStatus
from .events import StatusFacts, derive_status
from .extract import EXTRACTOR_VERSION

VIEW_SCHEMA = "intel-view/1"
HEARTBEAT_SCHEMA = "intel-heartbeat/1"
HEARTBEAT_MAX_AGE = timedelta(minutes=15)
QUOTE_MAX_AGE = timedelta(minutes=15)  # pricing.PricingPolicy.max_book_age: a decision older than this is not current
MAX_ITEMS = 200
MAX_INBOX_RESULTS = 20
MAX_EVIDENCE_SHOWN = 40

COLLECTED = "COLLECTED (automatic)"
CLASSIFIED = f"CLASSIFIED (deterministic rules, {EXTRACTOR_VERSION})"
IMPORTED_AI = "IMPORTED AI ANALYSIS (unvalidated)"
OWNER = "OWNER JUDGMENT (unvalidated)"
PROVISIONAL = "PROVISIONAL FORECAST (no calibration history)"
ECON_ESTIMATE = "ECONOMICS: ESTIMATE — fees unverified"
ECON_UNSUPPORTED = "ECONOMICS: FEE UNSUPPORTED"
ECON_VERIFIED = "ECONOMICS: VERIFIED"
ECON_NONE = "ECONOMICS: NOT COMPUTED"
HYPOTHETICAL = "HYPOTHETICAL — no order, no fill"
LABELS = {"collected": COLLECTED, "classified": CLASSIFIED, "imported_ai": IMPORTED_AI, "owner": OWNER,
          "provisional": PROVISIONAL, "econ_estimate": ECON_ESTIMATE, "econ_unsupported": ECON_UNSUPPORTED,
          "econ_verified": ECON_VERIFIED, "econ_none": ECON_NONE, "hypothetical": HYPOTHETICAL}

NOT_RUNNING = ("The news collector is not running on this host (timers not activated, or last heartbeat {age}). "
               "Your submission would wait until it runs.")
_SUBMISSION_FILE = re.compile(r"(\d{8}T\d{6}Z)-([a-z]{1,20})-[0-9a-f]{10}\.json")


def safe_link(url: Any) -> str | None:
    """An http(s) URL with a host, else None: no javascript:, data: or relative links reach a page."""
    if not isinstance(url, str) or len(url) > 2000:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    return url.strip() if parts.scheme in ("http", "https") and parts.netloc else None


def basis_label(basis: Any) -> str:
    return OWNER if basis == "OWNER_JUDGMENT" else IMPORTED_AI


def economics_label(sheet: Mapping[str, Any] | None) -> str:
    """Which economics claim a stored sheet supports: VERIFIED only with a claimable fee on the side shown."""
    if not isinstance(sheet, Mapping):
        return ECON_NONE
    sides = [s for s in (sheet.get("yes"), sheet.get("no")) if isinstance(s, Mapping)]
    best = sheet.get("best_side")
    shown = [s for s in sides if s.get("side") == best] or sides
    if "FEE_UNSUPPORTED" in (sheet.get("action_reasons") or ()) or any(
            s.get("fee_status") == "UNSUPPORTED" for s in shown):
        return ECON_UNSUPPORTED
    if not any(s.get("ev_conservative") is not None or s.get("ev_point") is not None for s in shown):
        return ECON_NONE
    if best and any(s.get("side") == best and s.get("fee_claimable") is True for s in shown):
        return ECON_VERIFIED
    return ECON_ESTIMATE


# --------------------------------------------------------------------------- view model


@dataclass(frozen=True)
class Processor:
    """Whether the collector that processes the inbox is running (its heartbeat file)."""

    available: bool
    state: str  # AVAILABLE | STALE | MISSING | UNREADABLE
    at_utc: str | None
    reason: str


@dataclass(frozen=True)
class InboxState:
    configured: bool
    pending: tuple[dict[str, Any], ...] = ()  # {"file", "kind", "queued_utc"}: QUEUED, oldest first
    results: tuple[dict[str, Any], ...] = ()  # latest `inbox` records, newest first: DONE / REJECTED / REFUSED
    error: str | None = None


@dataclass(frozen=True)
class OutcomeView:
    outcome_id: str
    text: str
    resolution_condition: str
    forecast: dict[str, Any] | None  # the active (latest) forecast record, verbatim
    forecasts: int  # records in its superseded chain
    link: dict[str, Any] | None  # the latest link decision, verbatim
    decision: dict[str, Any] | None  # the latest decision for the linked ticker, verbatim
    resolution: dict[str, Any] | None


@dataclass(frozen=True)
class EventView:
    event_id: str
    title: str
    topic: str
    key_entity: str
    status: str
    status_reason: str
    verification: str
    origins: tuple[str, ...]
    primary_sources: tuple[str, ...]
    first_evidence_utc: str | None
    last_evidence_utc: str | None
    evidence: tuple[dict[str, Any], ...]
    contradictions: tuple[tuple[str, str], ...]
    unconfirmed_claims: tuple[str, ...]
    outcomes: tuple[OutcomeView, ...]
    packet: dict[str, Any] | None  # {"packet_id", "sha256", "created_utc", "horizon_date", "horizon_set_by"}
    candidates: tuple[dict[str, Any], ...]  # unconfirmed CANDIDATE markets with captured rules
    candidates_searched_utc: str | None
    changed: bool  # evidence newer than 24 h before the view's time


@dataclass(frozen=True)
class Opportunity:
    event_id: str
    event_title: str
    outcome_id: str
    outcome_text: str
    ticker: str
    market_title: str | None
    link: dict[str, Any]
    decision: dict[str, Any] | None  # verbatim stored payload; None: not priced yet
    forecast: dict[str, Any] | None
    economics: str
    current: bool  # the decision is younger than QUOTE_MAX_AGE at the view's time


@dataclass(frozen=True)
class TranscriptView:
    transcript_id: str
    meta: dict[str, Any]
    imported_utc: str | None
    format: str | None
    chars: int | None
    claims: int
    unverified: int
    new_information: int
    topics: tuple[str, ...]
    label: str
    sample_claims: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class History:
    forecasts: tuple[dict[str, Any], ...]  # every record, newest first, with "superseded" and "record_id"
    analyses: tuple[dict[str, Any], ...]
    decisions: tuple[dict[str, Any], ...]
    resolutions: tuple[dict[str, Any], ...]
    rejected_links: tuple[dict[str, Any], ...]
    performance: dict[str, Any] | None
    performance_error: str | None = None


@dataclass(frozen=True)
class IntelView:
    schema: str
    as_of_utc: str
    last_run: dict[str, Any] | None
    feed_counts: dict[str, int]
    items: tuple[dict[str, Any], ...]
    item_total: int
    events: tuple[EventView, ...]
    opportunities: tuple[Opportunity, ...]
    transcripts: tuple[TranscriptView, ...]
    history: History
    sources: tuple[dict[str, Any], ...]
    inbox: InboxState
    processor: Processor
    labels: dict[str, str] = field(default_factory=lambda: dict(LABELS))
    insufficient_text: str = INSUFFICIENT_EVIDENCE_TEXT


def _p(row) -> dict[str, Any]:
    return json.loads(row["payload_json"])


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _age_words(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 120:
        return f"{minutes} min ago"
    hours = minutes // 60
    return f"{hours} h ago" if hours < 72 else f"{hours // 24} d ago"


def processor_state(heartbeat: Mapping[str, Any] | None, now: datetime, *, unreadable: str | None = None) -> Processor:
    """AVAILABLE iff a heartbeat (schema intel-heartbeat/1) is present and younger than 15 minutes."""
    if unreadable:
        return Processor(False, "UNREADABLE", None, NOT_RUNNING.format(age=f"unreadable: {unreadable}"))
    if not isinstance(heartbeat, Mapping):
        return Processor(False, "MISSING", None, NOT_RUNNING.format(age="never recorded"))
    at = heartbeat.get("at_utc")
    parsed = parse_utc(at) if isinstance(at, str) else None
    if heartbeat.get("schema") != HEARTBEAT_SCHEMA or parsed is None:
        return Processor(False, "UNREADABLE", None, NOT_RUNNING.format(age="not in the intel-heartbeat/1 format"))
    age = now - parsed
    if age < timedelta(0):
        return Processor(False, "UNREADABLE", str(at), NOT_RUNNING.format(age="dated in the future"))
    if age > HEARTBEAT_MAX_AGE:
        return Processor(False, "STALE", str(at), NOT_RUNNING.format(age=_age_words(age)))
    return Processor(True, "AVAILABLE", str(at), f"The collector last checked the inbox {_age_words(age)}.")


def inbox_state(root: Path | None, store) -> InboxState:
    if root is None:
        return InboxState(configured=False)
    results: list[dict[str, Any]] = []
    for row in reversed(store.intel_records(kind="inbox")):
        p = _p(row)
        results.append({**p, "recorded_at_utc": row["recorded_at_utc"]})
        if len(results) >= MAX_INBOX_RESULTS:
            break
    try:
        pend = []
        for path in inbox_mod.pending(Path(root)):
            m = _SUBMISSION_FILE.fullmatch(path.name)
            queued = None
            if m:
                queued = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            pend.append({"file": path.name, "id": path.name[:-5], "kind": m.group(2) if m else None,
                         "queued_utc": _iso(queued) if queued else None})
    except OSError as exc:
        return InboxState(configured=True, results=tuple(results), error=type(exc).__name__)
    return InboxState(configured=True, pending=tuple(pend), results=tuple(results))


def _candidate_rules(store, ticker: str, series: list[str]) -> dict[str, Any] | None:
    """The captured rules of one candidate, from the market listing the discovery stored (never fetched)."""
    from .kalshi_link import SPEC, rules_text

    for kind, entity in [("market", ticker)] + [("markets", s) for s in series]:
        row = store.latest_snapshot(source=SPEC.legacy_name, kind=kind, entity_id=entity)
        if row is None:
            continue
        payload = json.loads(row["payload_json"])
        markets = payload.get("markets") if kind == "markets" else [payload.get("market", payload)]
        for m in markets if isinstance(markets, list) else []:
            if isinstance(m, dict) and m.get("ticker") == ticker:
                return {**rules_text(m), "captured_utc": row["fetched_at_utc"], "snapshot_id": row["id"]}
    return None


def _market_title(store, ticker: str) -> str | None:
    from .kalshi_link import SPEC

    row = store.latest_snapshot(source=SPEC.legacy_name, kind="market", entity_id=ticker)
    if row is None:
        return None
    m = json.loads(row["payload_json"])
    m = m.get("market", m) if isinstance(m, dict) else {}
    title = m.get("title") if isinstance(m, dict) else None
    return str(title) if title else None


def _latest(store, kind: str) -> dict[str, tuple[int, dict[str, Any], str]]:
    out: dict[str, tuple[int, dict[str, Any], str]] = {}
    for row in store.intel_records(kind=kind):
        out[row["subject_id"]] = (int(row["id"]), _p(row), row["recorded_at_utc"])
    return out


def build_view(store, *, now: datetime, inbox_root: Path | None, heartbeat: Mapping[str, Any] | None,
               heartbeat_error: str | None = None) -> IntelView:
    """The whole workspace from a read-only store. Raises only when the store itself cannot be read."""
    names = {c.source_id: c for c in registry.CANDIDATES}

    # Collected news (latest version of each item).
    raw_items = store.intel_items(limit=MAX_ITEMS)
    items = []
    for r in raw_items:
        cand = names.get(r["source_id"])
        items.append({"source_id": r["source_id"], "source": cand.name if cand else r["source_id"],
                      "category": cand.category.value if cand else None,
                      "evidence_type": cand.evidence_type.value if cand else None,
                      "rights": r["rights"], "origin": r["origin"], "via_aggregator": bool(r["via_aggregator"]),
                      "title": r["title"], "snippet": r["snippet"], "link": safe_link(r["link"]),
                      "published_utc": r["published_utc"], "first_seen_utc": r["first_seen_utc"]})
    run = store.latest_intel_record("run", "news")
    feeds = service.feed_states(store, now=now)
    counts: dict[str, int] = {}
    for f in feeds:
        counts[f["status"]] = counts.get(f["status"], 0) + 1

    # Journal state, latest per subject.
    forecasts_latest = _latest(store, "forecast")
    links_latest = _latest(store, "link")
    resolutions = _latest(store, "resolution")
    decisions_all = [(int(r["id"]), _p(r), r["recorded_at_utc"]) for r in store.intel_records(kind="decision")]
    candidates_latest = _latest(store, "candidates")
    packets_by_event: dict[str, dict[str, Any]] = {}
    for row in store.intel_records(kind="packet"):
        p = _p(row)
        packets_by_event[p.get("event_id")] = {"packet_id": row["subject_id"], "sha256": p.get("packet_sha256"),
                                               "created_utc": p.get("created_utc"),
                                               "horizon_date": p.get("horizon_date"),
                                               "horizon_set_by": p.get("horizon_set_by")}
    forecast_chain: dict[str, int] = {}
    for row in store.intel_records(kind="forecast"):
        forecast_chain[row["subject_id"]] = forecast_chain.get(row["subject_id"], 0) + 1

    def latest_decision(outcome_id: str, ticker: str | None) -> dict[str, Any] | None:
        best = None
        for _, p, _at in decisions_all:
            if p.get("outcome_id") == outcome_id and (ticker is None or p.get("ticker") == ticker):
                best = p
        return best

    # Events with their evidence.
    evidence = {e.evidence_id: e for e in service.all_evidence(store, now=now)}
    events = []
    recent = _iso(now - timedelta(hours=24))
    for ev in service.current_events(store, now=now):
        outcomes = []
        linked_tickers = set()
        for o in ev.outcomes:
            link = links_latest.get(o.outcome_id, (None, None, None))[1]
            if link:
                linked_tickers.add(link.get("ticker"))
            fc = forecasts_latest.get(o.outcome_id, (None, None, None))[1]
            outcomes.append(OutcomeView(
                outcome_id=o.outcome_id, text=o.text, resolution_condition=o.resolution_condition, forecast=fc,
                forecasts=forecast_chain.get(o.outcome_id, 0), link=link,
                decision=latest_decision(o.outcome_id, link.get("ticker") if link else None) if link else None,
                resolution=resolutions.get(o.outcome_id, (None, None, None))[1]))
        facts = StatusFacts(
            verification=ev.verification,
            has_resolution=any(o.resolution for o in outcomes),
            has_active_forecast=any(o.forecast and not o.forecast.get("abstained") for o in outcomes),
            has_packet=ev.event_id in packets_by_event,
            has_confirmed_link=any(o.link and o.link.get("status") == LinkStatus.CONFIRMED.value for o in outcomes),
            stale=bool(ev.last_evidence_utc and ev.last_evidence_utc < _iso(now - timedelta(days=7))),
            evidence_count=len(ev.evidence_ids))
        status, reason = derive_status(facts)
        shown = []
        for eid in ev.evidence_ids[:MAX_EVIDENCE_SHOWN]:
            e = evidence.get(eid)
            if e is None:
                continue
            cand = names.get(e.source_id)
            shown.append({"evidence_id": eid, "kind": e.kind, "title": e.title,
                          "source": cand.name if cand else ("Podcast transcript" if e.kind == "transcript_claim"
                                                            else e.source_id),
                          "origin": e.origin, "evidence_type": e.evidence_type.value, "link": safe_link(e.link),
                          "observed_utc": e.observed_utc,
                          "claim_type": e.claim_type.value if e.claim_type else None})
        contra = tuple((evidence[a].title if a in evidence else a, evidence[b].title if b in evidence else b)
                       for a, b in ev.contradictions)
        unconfirmed = tuple(evidence[c].title if c in evidence else c for c in ev.unconfirmed_claims)
        cands, searched = [], None
        if ev.event_id in candidates_latest:
            payload = candidates_latest[ev.event_id][1]
            searched = payload.get("searched_utc")
            seen = set(linked_tickers)
            for cnd in payload.get("candidates") or []:
                if not isinstance(cnd, dict) or cnd.get("ticker") in seen:
                    continue
                seen.add(cnd.get("ticker"))
                cands.append({**cnd, "rules": _candidate_rules(store, str(cnd.get("ticker")),
                                                               [str(s) for s in payload.get("series") or []])})
        events.append(EventView(
            event_id=ev.event_id, title=ev.title, topic=ev.topic.value, key_entity=ev.key_entity, status=status.value,
            status_reason=reason, verification=ev.verification.value, origins=tuple(ev.origins),
            primary_sources=tuple(ev.primary_sources), first_evidence_utc=ev.first_evidence_utc,
            last_evidence_utc=ev.last_evidence_utc, evidence=tuple(shown), contradictions=contra,
            unconfirmed_claims=unconfirmed, outcomes=tuple(outcomes), packet=packets_by_event.get(ev.event_id),
            candidates=tuple(cands), candidates_searched_utc=searched,
            changed=bool(ev.last_evidence_utc and ev.last_evidence_utc >= recent)))

    # Opportunities: one card per confirmed link (latest link decision per outcome).
    outcome_index = {o.outcome_id: (e, o) for e in events for o in e.outcomes}
    opportunities = []
    for outcome_id, (_, link, _at) in links_latest.items():
        if link.get("status") != LinkStatus.CONFIRMED.value:
            continue
        ev_o = outcome_index.get(outcome_id)
        decision = latest_decision(outcome_id, link.get("ticker"))
        decided = parse_utc(decision.get("decided_utc")) if decision else None
        opportunities.append(Opportunity(
            event_id=ev_o[0].event_id if ev_o else outcome_id.split(":")[0],
            event_title=ev_o[0].title if ev_o else "Event no longer in the 14-day window",
            outcome_id=outcome_id, outcome_text=ev_o[1].text if ev_o else outcome_id, ticker=str(link.get("ticker")),
            market_title=_market_title(store, str(link.get("ticker"))), link=link, decision=decision,
            forecast=forecasts_latest.get(outcome_id, (None, None, None))[1],
            economics=economics_label(decision.get("sheet") if decision else None),
            current=decided is not None and timedelta(0) <= now - decided <= QUOTE_MAX_AGE))
    order = {"INVESTIGATE": 0, "WATCH": 1, "INSUFFICIENT_EVIDENCE": 2, "SKIP": 3}
    opportunities.sort(key=lambda o: (o.decision is None, order.get(((o.decision or {}).get("sheet") or {})
                                                                     .get("action"), 9), o.ticker))

    # Transcripts.
    transcripts = []
    for row in reversed(store.intel_records(kind="transcript")):
        p = _p(row)
        claims = p.get("claims") or []
        transcripts.append(TranscriptView(
            transcript_id=row["subject_id"], meta=p.get("meta") or {}, imported_utc=p.get("imported_at_utc"),
            format=p.get("format"), chars=p.get("chars"), claims=len(claims),
            unverified=sum(1 for c in claims if c.get("verification") == "UNVERIFIED"),
            new_information=sum(1 for c in claims if c.get("new_information")),
            topics=tuple(p.get("topics") or ()), label=p.get("label") or "OWNER-SUPPLIED TRANSCRIPT",
            sample_claims=tuple(claims[:12])))

    # History.
    fc_rows = store.intel_records(kind="forecast")
    superseded = {r["supersedes_id"] for r in fc_rows if r["supersedes_id"] is not None}
    forecasts = tuple({**_p(r), "record_id": int(r["id"]), "superseded": int(r["id"]) in superseded,
                       "supersedes_id": r["supersedes_id"]} for r in reversed(fc_rows))
    analyses = tuple({k: v for k, v in _p(r).items() if k != "analysis_json"} | {"record_id": int(r["id"]),
                     "packet_id": r["subject_id"], "recorded_at_utc": r["recorded_at_utc"]}
                     for r in reversed(store.intel_records(kind="analysis")))
    decisions = tuple({**p, "record_id": rid} for rid, p, _ in reversed(decisions_all))
    res = tuple(p for _, p, _ in resolutions.values())
    rejected = tuple(p for _, p, _ in links_latest.values() if p.get("status") == LinkStatus.REJECTED.value)
    try:
        perf, perf_error = service.performance(store), None
    except Exception as exc:  # noqa: BLE001 - one section's failure is shown, never the whole page's
        perf, perf_error = None, type(exc).__name__
    history = History(forecasts=forecasts, analyses=analyses, decisions=decisions, resolutions=res,
                      rejected_links=rejected, performance=perf, performance_error=perf_error)

    return IntelView(
        schema=VIEW_SCHEMA, as_of_utc=_iso(now), last_run=_p(run) if run else None, feed_counts=counts,
        items=tuple(items), item_total=len(items), events=tuple(events), opportunities=tuple(opportunities),
        transcripts=tuple(transcripts), history=history, sources=tuple(feeds),
        inbox=inbox_state(inbox_root, store),
        processor=processor_state(heartbeat, now, unreadable=heartbeat_error))
