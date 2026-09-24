"""One provider-neutral notification contract for every alert (issue #33, ADR 0020).

Collector failures, invalid captures, qualified opportunities, risk vetoes, settlements,
starter-policy exceptions and future approval tickets all produce the same
`NotificationEvent`. Sinks deliver the events. Today the sinks are:
- a local JSONL outbox, readable by the operator and the dashboard;
- a disabled SMS sink that records that no provider exists;
- an optional ntfy push sink (`edge_lab.notify_ntfy`, ADR 0022). It exists only when a topic
  URL is configured. Only the `edge-lab notify relay|test` commands construct it; the relay
  forwards this outbox from its own networked unit, so the daily run never sends anything.

The optional shell webhook in `deploy/vps/alert.sh` fires only for PRODUCTION unit failures.
A paid carrier (Twilio, Telnyx, SNS or similar) needs a separate owner approval, and no
provider code exists here.

Rules:
- An event never carries a secret: `check_secrets` refuses one, and the event is not
  delivered.
- Expired events are never delivered as actionable.
- Duplicates (the same `dedupe_key` already in the outbox history) are not re-sent.
- INFO and WARNING events are rate-limited per window. CRITICAL events are never
  rate-limited, so a noisy source cannot hide a risk or kill-switch alert.
- A sink gets a bounded number of attempts. Each attempt's status is returned.
- **A notification failure never changes trading, risk or ledger truth.** Callers record
  the outcome and move on (`dispatch` never raises for a sink failure).
- **Every event carries its origin** (`Origin`; ADR 0020 amendment of 2026-09-24). By default
  only PRODUCTION events reach an external (push) sink. TEST and MANUAL_DIAGNOSTIC events reach
  one only when the caller names them in `push_origins`. DEPLOYMENT_VERIFICATION, REPLAY and
  DEMO events never do. The origin is set by whoever creates the event. It is never inferred
  from the clock, from a deployment being in progress, or from free text. A line written
  before the field existed reads as PRODUCTION. Origins never interfere with each other:
  dedupe and rate limits count only the history of the same origin.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field, replace
from urllib.parse import urlsplit
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from .freshness import parse_utc
from .redaction import contains_secret

SCHEMA = "edge-lab-notification/1"


class EventType(str, Enum):
    SOURCE_FAILURE = "SOURCE_FAILURE"
    CAPTURE_INVALID = "CAPTURE_INVALID"
    OPPORTUNITY_QUALIFIED = "OPPORTUNITY_QUALIFIED"
    PRICE_TARGET_REACHED = "PRICE_TARGET_REACHED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    QUOTE_EXPIRING = "QUOTE_EXPIRING"
    RISK_VETO = "RISK_VETO"
    KILL_SWITCH = "KILL_SWITCH"
    POSITION_FILLED = "POSITION_FILLED"
    POSITION_PARTIAL = "POSITION_PARTIAL"
    POSITION_EXPIRED = "POSITION_EXPIRED"
    SETTLED = "SETTLED"
    SEVEN_DAY_POLICY_EXCEPTION = "SEVEN_DAY_POLICY_EXCEPTION"
    # An operator-initiated delivery check (`edge-lab notify test`). Never derived from a run.
    TEST = "TEST"


class Origin(str, Enum):
    """Why an event exists. The event carries it, and the outbox stores it as `origin`."""

    PRODUCTION = "PRODUCTION"  # a real run or unit of the live system
    TEST = "TEST"  # an explicit delivery check (`edge-lab notify test`)
    DEPLOYMENT_VERIFICATION = "DEPLOYMENT_VERIFICATION"  # an intentional install-time check (runbook §4.1)
    MANUAL_DIAGNOSTIC = "MANUAL_DIAGNOSTIC"  # an operator's by-hand investigation
    REPLAY = "REPLAY"  # re-derived from history (counterfactuals, backfills)
    DEMO = "DEMO"  # fixtures and demo data


# External (push) delivery by origin. PRODUCTION is pushed by default. The requestable origins
# are pushed only when the caller names them (`push_origins`). All others never leave the host.
DEFAULT_PUSH_ORIGINS = frozenset({Origin.PRODUCTION})
REQUESTABLE_PUSH_ORIGINS = frozenset({Origin.TEST, Origin.MANUAL_DIAGNOSTIC})
NEVER_PUSHED_ORIGINS = frozenset(Origin) - DEFAULT_PUSH_ORIGINS - REQUESTABLE_PUSH_ORIGINS


def push_allowed(origin: Origin, push_origins: Iterable[Origin] = ()) -> bool:
    """Whether an event of `origin` may reach an external sink, given the caller's explicit request."""
    return origin in DEFAULT_PUSH_ORIGINS or (origin in REQUESTABLE_PUSH_ORIGINS and origin in set(push_origins))


def origin_of(data: Mapping[str, Any]) -> Origin | None:
    """The origin of a serialized event. A missing field (a line written before it existed) means
    PRODUCTION. An unknown value gives None, never a guess."""
    raw = data.get("origin")
    if raw is None:
        return Origin.PRODUCTION
    try:
        return Origin(raw)
    except (ValueError, TypeError):
        return None


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ActionMode(str, Enum):
    INFO_ONLY = "INFO_ONLY"
    OPEN_MARKET_EDGE = "OPEN_MARKET_EDGE"
    OPEN_VENUE = "OPEN_VENUE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"  # future; no approval path exists yet


class DeliveryStatus(str, Enum):
    DELIVERED = "DELIVERED"  # accepted by the sink (for the outbox: written and flushed)
    # A remote push server (ntfy) accepted the message. That is not proof a phone showed it:
    # push has no delivery receipt, so a remote sink never reports DELIVERED (ADR 0022).
    SUBMITTED = "SUBMITTED"
    DEDUPED = "DEDUPED"
    RATE_LIMITED = "RATE_LIMITED"
    EXPIRED = "EXPIRED"
    REFUSED_SECRET = "REFUSED_SECRET"
    REFUSED_LINK = "REFUSED_LINK"
    FAILED = "FAILED"
    DISABLED_NO_PROVIDER = "DISABLED_NO_PROVIDER"
    # The event's origin keeps it off this external sink. It stays in the local outbox.
    HELD_BY_ORIGIN = "HELD_BY_ORIGIN"


# A deep link is allowed only to these hosts, over https: Market Edge's own local dashboard
# and official venue pages. Anything else is refused rather than sent.
LINK_HOSTS = ("127.0.0.1", "localhost", "kalshi.com", "polymarket.us", "novig.com")


@dataclass(frozen=True)
class NotificationEvent:
    event_id: str
    type: EventType
    severity: Severity
    created_at_utc: str
    expires_at_utc: str | None
    summary: str  # one human line, safe for a text message
    values: Mapping[str, str] = field(default_factory=dict)
    venue_id: str | None = None
    market_id: str | None = None
    event_ref: str | None = None
    action_mode: ActionMode = ActionMode.INFO_ONLY
    deep_link: str | None = None
    dedupe_key: str = ""
    origin: Origin = Origin.PRODUCTION

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "event_id": self.event_id, "type": self.type.value,
                "severity": self.severity.value, "created_at_utc": self.created_at_utc,
                "expires_at_utc": self.expires_at_utc, "summary": self.summary, "values": dict(self.values),
                "venue_id": self.venue_id, "market_id": self.market_id, "event_ref": self.event_ref,
                "action_mode": self.action_mode.value, "deep_link": self.deep_link, "dedupe_key": self.dedupe_key,
                "origin": self.origin.value}


def make_event(type: EventType, severity: Severity, *, created_at: datetime | str, summary: str,
               dedupe_key: str, ttl: timedelta | None = None, **kw: Any) -> NotificationEvent:
    """Build an event with a deterministic id (so the same condition gets the same id).

    Pass `origin=` for anything that is not a production event. The id leaves the origin out, so
    the ids of events relayed before the field existed stay the same."""
    created = parse_utc(created_at)
    if created is None:
        raise ValueError("created_at must be timezone-aware")
    values = {str(k): str(v) for k, v in (kw.pop("values", None) or {}).items()}
    event_id = "ntf-" + hashlib.sha256(f"{type.value}|{dedupe_key}|{created.isoformat()}".encode()).hexdigest()[:24]
    return NotificationEvent(event_id=event_id, type=type, severity=severity, created_at_utc=created.isoformat(),
                             expires_at_utc=None if ttl is None else (created + ttl).isoformat(), summary=summary,
                             values=values, dedupe_key=dedupe_key, **kw)


def event_from_dict(data: Mapping[str, Any]) -> NotificationEvent | None:
    """Rebuild an event from its `to_dict()` form (an outbox line), or None if it is not one.

    Unknown types, severities, action modes or origins give None rather than a guess. A line
    without `origin` (written before the field existed) reads as PRODUCTION."""
    try:
        if data.get("schema") != SCHEMA:
            return None
        origin = origin_of(data)
        if origin is None:
            return None
        values = data.get("values") or {}
        if not isinstance(values, Mapping):
            return None
        return NotificationEvent(
            event_id=str(data["event_id"]), type=EventType(data["type"]), severity=Severity(data["severity"]),
            created_at_utc=str(data["created_at_utc"]),
            expires_at_utc=None if data.get("expires_at_utc") is None else str(data["expires_at_utc"]),
            summary=str(data.get("summary") or ""), values={str(k): str(v) for k, v in values.items()},
            venue_id=data.get("venue_id"), market_id=data.get("market_id"), event_ref=data.get("event_ref"),
            action_mode=ActionMode(data.get("action_mode") or ActionMode.INFO_ONLY.value),
            deep_link=data.get("deep_link"), dedupe_key=str(data.get("dedupe_key") or ""), origin=origin)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def check_event(event: NotificationEvent) -> DeliveryStatus | None:
    """A reason to refuse the event, or None. Secrets and unsafe links are never sent."""
    strings = [v for v in event.to_dict().values() if isinstance(v, str)]
    strings += [f"{k}={v}" for k, v in event.values.items()]
    if any(contains_secret(s) for s in strings):
        return DeliveryStatus.REFUSED_SECRET
    if event.deep_link is not None and not _safe_link(event.deep_link):
        return DeliveryStatus.REFUSED_LINK
    return None


def _safe_link(link: str) -> bool:
    """https to an allowlisted host (or http to the local dashboard); no userinfo or tricks."""
    if any(c in link for c in "\\ \t\n") or not link.isascii():
        return False
    try:
        parts = urlsplit(link)
    except ValueError:
        return False
    if any(c in parts.netloc for c in "@?#") or not parts.hostname:
        return False
    host = parts.hostname.lower()
    local = host in ("127.0.0.1", "localhost")
    if parts.scheme == "https":
        return local or any(host == h or host.endswith("." + h) for h in LINK_HOSTS)
    return parts.scheme == "http" and local


class Sink(Protocol):
    """`external = False` marks a sink that keeps events on this host (the outbox). A sink that
    does not declare it counts as external, so an unknown sink never gets a non-PRODUCTION event
    by accident."""

    sink_id: str

    def deliver(self, event: NotificationEvent) -> DeliveryStatus: ...


class JsonlOutbox:
    """Append-only local outbox: one JSON line per delivered event. Bounded in size.

    When the file passes `max_bytes` it is rotated once to `<name>.1`, replacing any
    older rotation, so the outbox never grows without bound."""

    sink_id = "local-outbox"
    external = False

    def __init__(self, path: Path, *, max_bytes: int = 1_000_000) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes

    def history(self) -> list[dict[str, Any]]:
        out = []
        for p in (self.path.with_name(self.path.name + ".1"), self.path):
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out

    def deliver(self, event: NotificationEvent) -> DeliveryStatus:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.to_dict(), sort_keys=True, ensure_ascii=False) + "\n"
        if self.path.exists() and self.path.stat().st_size + len(line.encode("utf-8")) > self.max_bytes:
            os.replace(self.path, self.path.with_name(self.path.name + ".1"))
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        with closing(os.fdopen(fd, "a", encoding="utf-8", newline="\n")) as fh:
            # Readable like the receipt, whatever the service umask. os.fchmod does not exist on
            # Windows before Python 3.13; there the mode bits are not meaningful anyway.
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o644)
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        return DeliveryStatus.DELIVERED


class DisabledSmsSink:
    """SMS is the owner's preferred urgent channel, but no provider is approved or configured.
    This sink records that fact for every urgent event and sends nothing."""

    sink_id = "sms-disabled"
    external = True  # stands in for a future carrier, so it never gets a non-PRODUCTION event

    def deliver(self, event: NotificationEvent) -> DeliveryStatus:
        return DeliveryStatus.DISABLED_NO_PROVIDER


@dataclass(frozen=True)
class Limits:
    window: timedelta = timedelta(hours=1)
    per_window: Mapping[Severity, int] = field(default_factory=lambda: {Severity.INFO: 20, Severity.WARNING: 10})
    dedupe_window: timedelta = timedelta(days=8)  # longer than the pipeline's 7-day re-run horizon
    max_attempts: int = 3


def dispatch(events: Iterable[NotificationEvent], sinks: Iterable[Sink], *, now: datetime,
             history: Iterable[Mapping[str, Any]] = (), limits: Limits = Limits(),
             push_origins: Iterable[Origin] = ()) -> list[dict[str, Any]]:
    """Deliver events to every sink. Returns one status record per (event, sink). Never raises
    for a sink failure: a failed notification must not change what the caller does next.

    An external sink gets only PRODUCTION events, plus TEST or MANUAL_DIAGNOSTIC events when the
    caller names them in `push_origins`. Any other event is recorded as HELD_BY_ORIGIN on that
    sink and still goes to the local sinks. An event held on every sink uses no dedupe or
    rate-limit budget. Naming an origin that is never pushed is a programming error (ValueError)."""
    at = parse_utc(now)
    if at is None:
        raise ValueError("now must be timezone-aware")
    requested = frozenset(Origin(o) for o in push_origins)
    if requested & NEVER_PUSHED_ORIGINS:
        raise ValueError(f"never pushed: {sorted(o.value for o in requested & NEVER_PUSHED_ORIGINS)}")
    sinks = list(sinks)
    recent = [(origin_of(h), h) for h in history
              if (parse_utc(h.get("created_at_utc")) or at) >= at - limits.dedupe_window]
    seen = {(o, h.get("dedupe_key")) for o, h in recent}
    in_window = Counter((o, h.get("severity")) for o, h in recent
                        if (parse_utc(h.get("created_at_utc")) or at) >= at - limits.window)
    results: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda e: (e.severity is not Severity.CRITICAL, e.created_at_utc, e.event_id)):
        def record(status: DeliveryStatus, sink: str = "*", attempts: int = 0, error: str | None = None) -> None:
            results.append({"event_id": event.event_id, "type": event.type.value, "severity": event.severity.value,
                            "origin": event.origin.value, "sink": sink, "status": status.value,
                            "attempts": attempts, "error": error})
        refused = check_event(event)
        if refused is not None:
            record(refused)
            continue
        expires = parse_utc(event.expires_at_utc)
        if expires is not None and expires <= at:
            record(DeliveryStatus.EXPIRED)
            continue
        allowed = [getattr(s, "external", True) is False or push_allowed(event.origin, requested) for s in sinks]
        if not any(allowed):
            for sink in sinks:
                record(DeliveryStatus.HELD_BY_ORIGIN, sink.sink_id)
            continue
        if event.dedupe_key and (event.origin, event.dedupe_key) in seen:
            record(DeliveryStatus.DEDUPED)
            continue
        cap = limits.per_window.get(event.severity)
        if (event.severity is not Severity.CRITICAL and cap is not None
                and in_window[(event.origin, event.severity.value)] >= cap):
            record(DeliveryStatus.RATE_LIMITED)
            continue
        seen.add((event.origin, event.dedupe_key))
        in_window[(event.origin, event.severity.value)] += 1
        for sink, ok in zip(sinks, allowed):
            if not ok:
                record(DeliveryStatus.HELD_BY_ORIGIN, sink.sink_id)
                continue
            status, error, attempts = DeliveryStatus.FAILED, None, 0
            for attempts in range(1, limits.max_attempts + 1):
                try:
                    status = sink.deliver(event)
                    # A sink that retries and handles its own failures (ntfy) reports its
                    # redacted reason and its own attempt count (0 if it refused before sending).
                    error = getattr(sink, "last_error", None)
                    own_attempts = getattr(sink, "last_attempts", None)
                    attempts = own_attempts if isinstance(own_attempts, int) else attempts
                    break
                except Exception as exc:  # noqa: BLE001 - a sink failure is recorded, never raised
                    error = f"{type(exc).__name__}: {exc}"[:200]
            record(status, sink.sink_id, attempts, error)
    return results


# --------------------------------------------------------------------------- daily receipt events

def events_from_receipt(receipt: Mapping[str, Any], *, now: datetime,
                        exceptions: Iterable[Mapping[str, Any]] = (),
                        origin: Origin = Origin.PRODUCTION) -> list[NotificationEvent]:
    """Events the daily shadow receipt implies. Only facts already in the receipt are used.
    Every event carries the caller's `origin`; the daily run passes PRODUCTION explicitly."""
    events: list[NotificationEvent] = []
    state = receipt.get("state")
    link = "http://127.0.0.1:8765/"
    if state in ("FAILED", "LOCK_BUSY"):
        events.append(make_event(EventType.SOURCE_FAILURE, Severity.CRITICAL, created_at=now,
                                 summary=f"Market Edge daily shadow run {state}",
                                 dedupe_key=f"daily:{state}:{now.date().isoformat()}",
                                 values={"problems": str(len(receipt.get("problems") or []))},
                                 action_mode=ActionMode.OPEN_MARKET_EDGE, deep_link=link))
    for day in receipt.get("days") or []:
        if day.get("capture_status") not in (None, "VALID") or day.get("result") == "INVALID_CAPTURE":
            events.append(make_event(EventType.CAPTURE_INVALID, Severity.WARNING, created_at=now,
                                     summary=f"Stage B day {day.get('target_date')} capture {day.get('capture_status')}",
                                     dedupe_key=f"capture:{day.get('target_date')}",
                                     values={"target_date": str(day.get("target_date"))}, deep_link=link,
                                     action_mode=ActionMode.OPEN_MARKET_EDGE))
        for account, counts in (day.get("accounts") or {}).items():
            vetoes = counts.get("risk_vetoes") or 0
            if vetoes:
                events.append(make_event(EventType.RISK_VETO, Severity.WARNING, created_at=now,
                                         summary=f"{vetoes} risk veto(es) on {day.get('target_date')} ({account})",
                                         dedupe_key=f"veto:{account}:{day.get('target_date')}",
                                         values={"account": account, "vetoes": str(vetoes)}, deep_link=link,
                                         action_mode=ActionMode.OPEN_MARKET_EDGE))
    settled = (receipt.get("settlement") or {}).get("settled") or 0
    if settled:
        events.append(make_event(EventType.SETTLED, Severity.INFO, created_at=now,
                                 summary=f"{settled} shadow position(s) settled",
                                 dedupe_key=f"settled:{receipt.get('generated_at_utc')}",
                                 values={"settled": str(settled)}, deep_link=link,
                                 action_mode=ActionMode.OPEN_MARKET_EDGE))
    if (receipt.get("settlement") or {}).get("conflicts"):
        events.append(make_event(EventType.SOURCE_FAILURE, Severity.CRITICAL, created_at=now,
                                 summary="Settlement evidence conflict: positions held pending",
                                 dedupe_key="settlement-conflict:" + json.dumps(
                                     receipt["settlement"]["conflicts"], sort_keys=True)[:200],
                                 deep_link=link, action_mode=ActionMode.OPEN_MARKET_EDGE))
    for exc in exceptions:
        events.append(make_event(EventType.SEVEN_DAY_POLICY_EXCEPTION, Severity.CRITICAL, created_at=now,
                                 summary=f"Capital past its expected release: {exc.get('market_id')}",
                                 dedupe_key=f"starter-exception:{exc.get('fill_id')}",
                                 values={"fill_id": str(exc.get("fill_id")),
                                         "expected_release": str(exc.get("tradable_cash_release_eta_utc"))},
                                 market_id=exc.get("market_id"), deep_link=link,
                                 action_mode=ActionMode.OPEN_MARKET_EDGE))
    origin = Origin(origin)
    return [replace(e, origin=origin) for e in events]  # the id leaves the origin out, so it is unchanged
