"""Optional ntfy push sink behind the notification contract (ADR 0022). Disabled by default.

This is the only file in `src/` allowed to send an HTTP POST with a body
(`tests/invariants/test_no_execution_paths.py` names it exactly). It can only publish one
headline to one ntfy topic that the owner configured. It names no venue host or trading
path and does no request signing, and its target host comes only from configuration.

Activation needs a separate owner approval: a first real send publishes data to an
external service. Nothing in the daily run, a timer or a deploy file constructs this sink.
`sink_from_env` returns None unless `EDGE_LAB_NTFY_TOPIC_URL` is set.

Rules:
- **Minimal payload.** The contract has no sensitivity field, so only the event type,
  the severity and the one-line summary leave the host. Values, venue, market and event
  refs, deep links and the action mode are never sent. There is no click action.
- **Honest status.** A 2xx answer means the ntfy server accepted the message. It does not
  mean a phone showed it, so the sink returns SUBMITTED, never DELIVERED.
- **Expiry.** An event already expired at send time is not sent (EXPIRED). This is
  checked again before every retry.
- **Dedupe.** `dispatch` and the outbox history dedupe by `dedupe_key`. The ntfy server
  does not, so the key is also sent as `X-Sequence-ID`: a repeat replaces the earlier
  notification on the phone instead of adding one.
- **Bounded retry.** Transport errors and 5xx are retried a small fixed number of times,
  and only when a sequence id makes a duplicate harmless. 429 is never retried
  (RATE_LIMITED). Anything else is FAILED.
- **Never raises.** Every failure becomes a status, with a redacted `last_error`. A
  notification failure never changes risk, trading or ledger state.
- **Secrets.** The topic URL is effectively a password on a public server, and the
  optional access token is a credential. Neither is ever logged, stored or returned:
  errors are passed through `redaction.redact_text` with both removed, and
  `Target.label` shows only the scheme and host.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .freshness import parse_utc
from .notifications import LINK_HOSTS, DeliveryStatus, NotificationEvent, Severity, check_event
from .redaction import REDACTED, contains_secret, redact_text
from .sources import REGISTRY

ENV_TOPIC_URL = "EDGE_LAB_NTFY_TOPIC_URL"
ENV_TOKEN = "EDGE_LAB_NTFY_TOKEN"

TOPIC = re.compile(r"[-_A-Za-z0-9]{1,64}")
SEQUENCE_ID = TOPIC  # ntfy validates sequence ids with the topic pattern
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SEQUENCE_INVALID = re.compile(r"[^-_A-Za-z0-9]")
_LOCAL = ("127.0.0.1", "localhost")

PRIORITY = {Severity.INFO: "2", Severity.WARNING: "4", Severity.CRITICAL: "5"}
MAX_SUMMARY_CHARS = 240  # far below ntfy's 4,096-byte message limit
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 1.0
TIMEOUT_SECONDS = 10.0
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})

Opener = Callable[[Request, float], Any]


class NtfyConfigError(ValueError):
    """The configured topic URL or token is unusable. The message never contains either."""


def refused_host_brands() -> frozenset[str]:
    """Names a notification host may never contain: every registered data source and venue.

    Built from `sources.REGISTRY` and `notifications.LINK_HOSTS` at run time, so this file
    names no venue itself and a newly registered venue is refused automatically."""
    hosts = {(urlsplit(spec.base_url).hostname or "").lower() for spec in REGISTRY.values()}
    hosts |= {h for h in LINK_HOSTS if h not in _LOCAL}
    return frozenset(labels[-2] for labels in (h.split(".") for h in hosts if h) if len(labels) >= 2)


@dataclass(frozen=True)
class Target:
    url: str
    host: str

    @property
    def label(self) -> str:
        """Safe to log: scheme and host only. The topic is the secret part."""
        return f"{urlsplit(self.url).scheme}://{self.host}/{REDACTED}"


def parse_topic_url(url: str) -> Target:
    """Validate an https `<host>/<topic>` URL (plain http only for a loopback test server).

    No userinfo, query, fragment or extra path. The topic matches ntfy's own pattern. The
    host is never a registered data source or venue. Errors never echo the URL."""
    if not isinstance(url, str) or not url.isascii() or any(c in url for c in "\\ \t\r\n"):
        raise NtfyConfigError("ntfy topic URL must be plain ASCII with no whitespace")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise NtfyConfigError("ntfy topic URL does not parse") from None
    host = (parts.hostname or "").lower()
    if not host or "@" in parts.netloc or parts.query or parts.fragment:
        raise NtfyConfigError("ntfy topic URL must have a host and no userinfo, query or fragment")
    if not (parts.scheme == "https" or (parts.scheme == "http" and host in _LOCAL)):
        raise NtfyConfigError("ntfy topic URL must use https")
    topic = parts.path[1:] if parts.path.startswith("/") else ""
    if not TOPIC.fullmatch(topic):
        raise NtfyConfigError("ntfy topic URL path must be exactly one topic matching [-_A-Za-z0-9]{1,64}")
    if any(brand in host for brand in refused_host_brands()):
        raise NtfyConfigError(f"ntfy host {host} is a data-source or venue host; refused")
    netloc = host if port is None else f"{host}:{port}"
    return Target(url=f"{parts.scheme}://{netloc}/{topic}", host=host)


def sequence_id(dedupe_key: str) -> str | None:
    """`dedupe_key` as an ntfy sequence id: invalid characters become `_`, and a key longer
    than 64 characters keeps a prefix plus a hash of the whole key. None for an empty key."""
    if not dedupe_key:
        return None
    clean = _SEQUENCE_INVALID.sub("_", dedupe_key)
    if len(clean) <= 64:
        return clean
    return clean[:47] + "-" + hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:16]


def payload(event: NotificationEvent) -> tuple[dict[str, str], bytes]:
    """The headers and body sent for one event: type, severity and summary, nothing else."""
    summary = " ".join(event.summary.split())
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[: MAX_SUMMARY_CHARS - 12].rstrip() + " [truncated]"
    headers = {
        "X-Title": f"Market Edge {event.severity.value}: {event.type.value}",
        "X-Priority": PRIORITY[event.severity],
        "X-Tags": f"{event.severity.value.lower()},{event.type.value.lower()}",
        "Content-Type": "text/plain; charset=utf-8",
    }
    seq = sequence_id(event.dedupe_key)
    if seq is not None:
        headers["X-Sequence-ID"] = seq
    return headers, summary.encode("utf-8")


class _NoRedirect(HTTPRedirectHandler):
    """A redirect could carry the token to another host. Treat it as a failure."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ANN001
        return None


def _default_opener(request: Request, timeout: float) -> Any:
    return build_opener(_NoRedirect).open(request, timeout=timeout)


class NtfySink:
    """Publishes one headline per event to one configured ntfy topic. See the module rules."""

    sink_id = "ntfy"

    def __init__(self, topic_url: str, *, token: str | None = None, opener: Opener | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], datetime] | None = None,
                 max_attempts: int = MAX_ATTEMPTS, backoff: float = BACKOFF_SECONDS,
                 timeout: float = TIMEOUT_SECONDS) -> None:
        self._secrets = tuple(s for s in (topic_url, token) if s)
        self.target = parse_topic_url(topic_url)
        self._secrets += (self.target.url, urlsplit(self.target.url).path[1:])
        if token is not None and not _TOKEN.fullmatch(token):
            raise NtfyConfigError(f"{ENV_TOKEN} must match [A-Za-z0-9_-]{{1,128}}")
        self._token = token
        self._opener = opener or _default_opener
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_attempts = max(1, min(int(max_attempts), MAX_ATTEMPTS))
        self.backoff = backoff
        self.timeout = timeout
        self.last_error: str | None = None
        self.last_attempts = 0
        self.last_http_status: int | None = None

    def __repr__(self) -> str:
        return f"NtfySink({self.target.label}, token={'set' if self._token else 'none'})"

    def _redact(self, text: str) -> str:
        return redact_text(text, self._secrets)[:200]

    def _expired(self, event: NotificationEvent) -> bool:
        expires = parse_utc(event.expires_at_utc)
        return expires is not None and expires <= self._clock()

    def deliver(self, event: NotificationEvent) -> DeliveryStatus:
        self.last_error, self.last_attempts, self.last_http_status = None, 0, None
        try:
            return self._deliver(event)
        except Exception as exc:  # noqa: BLE001 - a notification failure is a status, never an exception
            self.last_error = self._redact(f"{type(exc).__name__}: {exc}")
            return DeliveryStatus.FAILED

    def _deliver(self, event: NotificationEvent) -> DeliveryStatus:
        refused = check_event(event)
        if refused is not None:
            return refused
        headers, body = payload(event)
        if any(contains_secret(v) for v in (*headers.values(), body.decode("utf-8"))):
            return DeliveryStatus.REFUSED_SECRET
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        retry_allowed = "X-Sequence-ID" in headers  # a duplicate then replaces, not adds
        attempts = self.max_attempts if retry_allowed else 1
        status = DeliveryStatus.FAILED
        for attempt in range(1, attempts + 1):
            if self._expired(event):
                return DeliveryStatus.EXPIRED
            self.last_attempts = attempt
            status, retryable = self._attempt(headers, body)
            if not retryable or attempt == attempts:
                return status
            self._sleep(self.backoff * (2 ** (attempt - 1)))
        return status

    def _attempt(self, headers: Mapping[str, str], body: bytes) -> tuple[DeliveryStatus, bool]:
        """One publish. Returns (status, whether a retry may help)."""
        request = Request(self.target.url, data=body, headers=dict(headers), method="POST")
        try:
            with self._opener(request, self.timeout) as response:
                code = int(getattr(response, "status", 200))
                response.read(4096)
        except HTTPError as exc:
            exc.close()
            self.last_http_status = exc.code
            self.last_error = f"HTTP {exc.code} from {self.target.label}"
            if exc.code == 429:
                return DeliveryStatus.RATE_LIMITED, False
            return DeliveryStatus.FAILED, exc.code in _RETRYABLE_STATUS
        except (OSError, http.client.HTTPException) as exc:  # URLError, timeouts, resets, TLS
            reason = getattr(exc, "reason", None) or exc
            self.last_error = self._redact(f"{type(exc).__name__} from {self.target.label}: {reason}")
            return DeliveryStatus.FAILED, True
        self.last_http_status = code
        if 200 <= code < 300:
            self.last_error = None
            return DeliveryStatus.SUBMITTED, False
        self.last_error = f"HTTP {code} from {self.target.label}"
        return DeliveryStatus.FAILED, code in _RETRYABLE_STATUS


def sink_from_env(environ: Mapping[str, str] | None = None, **kwargs: Any) -> NtfySink | None:
    """The configured sink, or None when `EDGE_LAB_NTFY_TOPIC_URL` is unset or blank.

    `EDGE_LAB_NTFY_TOKEN` is optional and is sent only as a Bearer header. Installing either
    value is an owner step; agents never create, see or commit them. A set but invalid value
    raises NtfyConfigError, whose message contains neither value."""
    env = os.environ if environ is None else environ
    topic_url = (env.get(ENV_TOPIC_URL) or "").strip()
    if not topic_url:
        return None
    token = (env.get(ENV_TOKEN) or "").strip() or None
    return NtfySink(topic_url, token=token, **kwargs)
