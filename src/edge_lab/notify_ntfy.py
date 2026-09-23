"""Optional ntfy push sink behind the notification contract (ADR 0022). Disabled by default.

This is the only file in `src/` allowed to send an HTTP POST with a body
(`tests/invariants/test_no_execution_paths.py` names it exactly). It can only publish a
fixed headline to one ntfy topic on an allowlisted host. It names no venue host or trading
path and does no request signing.

Activation needs a separate owner approval: a first real send publishes data to an
external service. Nothing in the daily run, a timer or a deploy file constructs this sink.
`sink_from_env` returns None unless `EDGE_LAB_NTFY_TOPIC_URL` is set.

Rules:
- **Allowlisted host.** The topic URL must be https, `<host>/<topic>`, where the host is
  exactly `ntfy.sh` or a self-hosted name listed in `SELF_HOSTED_HOSTS` (reviewed code, empty
  today; never taken from configuration). IP literals, ports, userinfo, queries, fragments
  and extra path segments are refused. The URL is re-validated before every request, and
  the opener refuses any URL other than the one validated when the sink was built.
- **Nothing identifying leaves the host.** Only the event type, the severity and a fixed
  headline chosen by event type are sent. The caller's summary, values, venue, market and
  event refs, deep link and action mode are never sent. The sequence id is a BLAKE2b hash
  of the dedupe key keyed with the topic, so it is stable per topic for dedupe. It resists
  guessing only for someone who sees the id WITHOUT the topic. The ntfy.sh operator and
  every subscriber hold the topic, so for them it is no stronger than a plain hash; dedupe
  keys stay low-entropy by design, so treat them as visible to anyone with the topic.
- **Honest status.** A 2xx answer means the ntfy server accepted the message. It does not
  mean a phone showed it, so the sink returns SUBMITTED, never DELIVERED.
- **Expiry.** An event already expired at send time, or whose expiry does not parse, is
  not sent (EXPIRED). This is checked again before every retry.
- **Dedupe.** `dispatch` and the outbox history dedupe by `dedupe_key`. The ntfy server
  does not, so the hashed key is also sent as `X-Sequence-ID`: a repeat replaces the
  earlier notification on the phone instead of adding one.
- **Bounded cost.** At most three attempts inside a 15-second budget per event, backoff
  through an injectable `sleep`, and retries only when a sequence id makes a duplicate
  harmless. 429 is never retried (RATE_LIMITED). Certificate errors, redirects and other
  4xx are not retried (FAILED). After three consecutive failed events the sink stops
  sending for a cooldown (a simple circuit breaker). The 15-second budget is best-effort:
  the urllib timeout applies to each socket operation, not the whole request, and DNS
  resolution has no timeout at all.
- **Never raises.** Every failure becomes a status, with a redacted `last_error`. A
  notification failure never changes risk, trading or ledger state.
- **Secrets.** The topic is effectively a password on a public server, and the optional
  access token is a credential. Neither appears in a repr or an error: errors pass through
  `redaction.redact_text` with both removed. The token and the redaction list live only in
  closures, not in attributes, and the sink and its target refuse to be pickled or copied.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import os
import re
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .freshness import parse_utc
from .notifications import DeliveryStatus, EventType, NotificationEvent, Severity, check_event
from .redaction import REDACTED, redact_text

ENV_TOPIC_URL = "EDGE_LAB_NTFY_TOPIC_URL"
ENV_TOKEN = "EDGE_LAB_NTFY_TOKEN"

# The only hosts the sink may publish to. Adding a self-hosted server is a reviewed code
# change (and an invariant test change), never a configuration value.
DEFAULT_HOSTS: tuple[str, ...] = ("ntfy.sh",)
SELF_HOSTED_HOSTS: tuple[str, ...] = ()

TOPIC = re.compile(r"[-_A-Za-z0-9]{16,64}")  # ntfy allows 1-64; short topics are guessable
SEQUENCE_ID = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,128}")

PRIORITY = {Severity.INFO: "2", Severity.WARNING: "4", Severity.CRITICAL: "5"}
# One fixed, non-identifying line per event type. The caller's free-text summary is never sent.
HEADLINES: Mapping[EventType, str] = {
    EventType.SOURCE_FAILURE: "A run or data source failed",
    EventType.CAPTURE_INVALID: "Invalid capture day",
    EventType.OPPORTUNITY_QUALIFIED: "An opportunity qualified",
    EventType.PRICE_TARGET_REACHED: "A price target was reached",
    EventType.APPROVAL_REQUIRED: "An approval is required",
    EventType.QUOTE_EXPIRING: "A quote is expiring",
    EventType.RISK_VETO: "Risk vetoes recorded",
    EventType.KILL_SWITCH: "Kill switch engaged",
    EventType.POSITION_FILLED: "A shadow position filled",
    EventType.POSITION_PARTIAL: "A shadow position partially filled",
    EventType.POSITION_EXPIRED: "A shadow position expired",
    EventType.SETTLED: "Shadow positions settled",
    EventType.SEVEN_DAY_POLICY_EXCEPTION: "Capital past its expected release",
}
FOOTER = "Open Market Edge for details."

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 1.0
TIMEOUT_SECONDS = 10.0
DEADLINE_SECONDS = 15.0  # total per event, attempts and backoff included
BREAKER_THRESHOLD = 3  # consecutive FAILED events before the breaker opens
BREAKER_COOLDOWN_SECONDS = 300.0
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})

Opener = Callable[[Request, float], Any]


class NtfyConfigError(ValueError):
    """The topic URL or token is unusable. The message never contains either."""


def _allowed_hosts() -> tuple[str, ...]:
    return DEFAULT_HOSTS + SELF_HOSTED_HOSTS


def _validate(url: object) -> tuple[str, str]:
    """(normalized URL, host) for an allowlisted https `<host>/<topic>`, else NtfyConfigError."""
    if not isinstance(url, str) or not url.isascii() or any(c in url for c in "\\ ?#") \
            or any(ord(c) < 0x20 or ord(c) == 0x7F for c in url):
        raise NtfyConfigError("ntfy topic URL must be plain ASCII with no whitespace, control characters, ? or #")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise NtfyConfigError("ntfy topic URL does not parse") from None
    if parts.scheme != "https":
        raise NtfyConfigError("ntfy topic URL must use https")
    if "@" in parts.netloc or port is not None or parts.query or parts.fragment:
        raise NtfyConfigError("ntfy topic URL must have no userinfo, port, query or fragment")
    host = (parts.hostname or "").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise NtfyConfigError("ntfy topic URL must name a host, not an IP address")
    if parts.netloc.lower() != host or host not in _allowed_hosts():
        raise NtfyConfigError(f"ntfy host is not allowlisted (allowed: {', '.join(_allowed_hosts())})")
    topic = parts.path[1:] if parts.path.startswith("/") else ""
    if not TOPIC.fullmatch(topic):
        raise NtfyConfigError("ntfy topic URL path must be exactly one topic matching [-_A-Za-z0-9]{16,64}")
    return urlunsplit(("https", host, "/" + topic, "", "")), host


@dataclass(frozen=True)
class Target:
    """A validated topic URL. Construction validates; the URL never appears in a repr."""

    url: str = field(repr=False)
    host: str = field(init=False)

    def __post_init__(self) -> None:
        normalized, host = _validate(self.url)
        object.__setattr__(self, "url", normalized)
        object.__setattr__(self, "host", host)

    @property
    def label(self) -> str:
        """Safe to log: scheme and host only. The topic is the secret part."""
        return urlunsplit(("https", self.host, "/" + REDACTED, "", ""))

    def __reduce_ex__(self, protocol: object) -> Any:  # pickle, copy and deepcopy all go through here
        raise TypeError("an ntfy Target holds a secret topic and cannot be pickled or copied")

    __reduce__ = __getstate__ = lambda self: self.__reduce_ex__(None)  # noqa: E731


def parse_topic_url(url: str) -> Target:
    """Validate a topic URL (see `_validate`). Errors never echo the URL."""
    return Target(url)


def sequence_key(topic_url: str) -> bytes:
    """The secret that keys sequence ids: the validated topic, at most 64 bytes (BLAKE2b's limit)."""
    return urlsplit(_validate(topic_url)[0]).path[1:].encode("ascii")[:64]


def sequence_id(dedupe_key: str, key: bytes) -> str | None:
    """BLAKE2b-256 hex of `dedupe_key`, keyed with the topic. Stable per topic, valid for ntfy.

    A plain hash of a guessable key (for example an account label plus a date) can be
    brute-forced by anyone who sees it. This one resists that only for someone who sees the
    id without the topic; the ntfy operator and subscribers hold the topic. None if empty."""
    if not dedupe_key:
        return None
    if not 16 <= len(key) <= 64:
        raise NtfyConfigError("sequence key must be the 16-64 byte topic")
    return hashlib.blake2b(dedupe_key.encode("utf-8"), key=key, digest_size=32).hexdigest()


def payload(event: NotificationEvent, key: bytes) -> tuple[dict[str, str], bytes]:
    """Headers and body for one event: type, severity and a fixed headline, nothing else."""
    headers = {
        "X-Title": f"Market Edge {event.severity.value}: {event.type.value}",
        "X-Priority": PRIORITY[event.severity],
        "X-Tags": f"{event.severity.value.lower()},{event.type.value.lower()}",
        "Content-Type": "text/plain; charset=utf-8",
    }
    seq = sequence_id(event.dedupe_key, key)
    if seq is not None:
        headers["X-Sequence-ID"] = seq
    return headers, f"{HEADLINES[event.type]}. {FOOTER}".encode("utf-8")


class _NoRedirect(HTTPRedirectHandler):
    """A redirect could carry the token to another host. Treat it as a failure."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _default_opener(request: Request, timeout: float) -> Any:
    """Direct connection (no environment proxy), no redirects."""
    return build_opener(ProxyHandler({}), _NoRedirect).open(request, timeout=timeout)


def _guarded(opener: Opener | None, expected_url: str, token: str | None) -> Opener:
    """An opener that refuses any request except a POST to the URL validated when the sink was
    built. It alone holds the token, and adds it only to that request."""

    def open_checked(request: Request, timeout: float) -> Any:
        if request.full_url != expected_url or request.get_method() != "POST":
            raise NtfyConfigError("refused: request is not for the validated ntfy topic")
        _validate(request.full_url)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        return (opener or _default_opener)(request, timeout)

    return open_checked


def _redactor(secrets: tuple[str, ...]) -> Callable[[str], str]:
    """Redacts the given secrets and secret patterns, holding the secrets only in a closure."""
    ordered = tuple(sorted({s for s in secrets if s}, key=len, reverse=True))

    def redact(text: str) -> str:
        return redact_text(text, ordered)[:200]

    return redact


def _cert_error(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", None)
    return isinstance(exc, ssl.SSLCertVerificationError) or isinstance(reason, ssl.SSLCertVerificationError)


class NtfySink:
    """Publishes one fixed headline per event to one allowlisted ntfy topic. See the module rules."""

    # The token and the redaction secrets are held only by the `_opener` and `_redact` closures.
    __slots__ = ("_target", "_has_token", "_redact", "_opener", "_sleep", "_clock", "_monotonic", "max_attempts",
                 "backoff", "timeout", "deadline", "last_error", "last_attempts", "last_http_status",
                 "_consecutive_failures", "_open_until")
    sink_id = "ntfy"

    def __init__(self, topic_url: str, *, token: str | None = None, opener: Opener | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], datetime] | None = None,
                 monotonic: Callable[[], float] = time.monotonic, max_attempts: int = MAX_ATTEMPTS,
                 backoff: float = BACKOFF_SECONDS, timeout: float = TIMEOUT_SECONDS,
                 deadline: float = DEADLINE_SECONDS) -> None:
        target = parse_topic_url(topic_url)
        if token is not None and not _TOKEN.fullmatch(token):
            raise NtfyConfigError(f"{ENV_TOKEN} must match [A-Za-z0-9_-]{{1,128}}")
        self._target = target
        self._has_token = bool(token)
        self._redact = _redactor((topic_url, token or "", target.url, urlsplit(target.url).path[1:]))
        self._opener = _guarded(opener, target.url, token)
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic
        self.max_attempts = max(1, min(int(max_attempts), MAX_ATTEMPTS))
        self.backoff = backoff
        self.deadline = min(deadline, DEADLINE_SECONDS)
        self.timeout = min(timeout, self.deadline)
        self.last_error: str | None = None
        self.last_attempts = 0
        self.last_http_status: int | None = None
        self._consecutive_failures = 0
        self._open_until: float | None = None

    @property
    def target(self) -> Target:
        return self._target

    def __repr__(self) -> str:
        return f"NtfySink(host={self._target.host}, token={'set' if self._has_token else 'none'})"

    __str__ = __repr__

    def __reduce_ex__(self, protocol: object) -> Any:  # pickle, copy and deepcopy all go through here
        raise TypeError("an NtfySink holds a secret topic and token and cannot be pickled or copied")

    __reduce__ = __getstate__ = lambda self: self.__reduce_ex__(None)  # noqa: E731

    def _expired(self, event: NotificationEvent) -> bool:
        if event.expires_at_utc is None:
            return False
        expires = parse_utc(event.expires_at_utc)
        return expires is None or expires <= self._clock()  # an unparseable expiry fails closed

    def deliver(self, event: NotificationEvent) -> DeliveryStatus:
        self.last_error, self.last_attempts, self.last_http_status = None, 0, None
        try:
            status = self._deliver(event)
        except Exception as exc:  # noqa: BLE001 - a notification failure is a status, never an exception
            self.last_error = self._redact(f"{type(exc).__name__}: {exc}")
            status = DeliveryStatus.FAILED
        if self.last_attempts:
            if status is DeliveryStatus.FAILED:
                self._consecutive_failures += 1
                if self._consecutive_failures >= BREAKER_THRESHOLD:
                    self._open_until = self._monotonic() + BREAKER_COOLDOWN_SECONDS
            elif status is DeliveryStatus.SUBMITTED:
                self._consecutive_failures, self._open_until = 0, None
        return status

    def _deliver(self, event: NotificationEvent) -> DeliveryStatus:
        refused = check_event(event)
        if refused is not None:
            return refused
        if self._expired(event):
            return DeliveryStatus.EXPIRED
        if self._open_until is not None and self._monotonic() < self._open_until:
            self.last_error = "circuit open after repeated failures; not sent"
            return DeliveryStatus.FAILED
        headers, body = payload(event, sequence_key(self._target.url))
        attempts = self.max_attempts if "X-Sequence-ID" in headers else 1  # a duplicate then replaces
        started = self._monotonic()
        status = DeliveryStatus.FAILED
        for attempt in range(1, attempts + 1):
            if attempt > 1 and self._expired(event):
                return DeliveryStatus.EXPIRED
            remaining = self.deadline - (self._monotonic() - started)
            if remaining <= 0:
                self.last_error = f"per-event deadline of {self.deadline:g}s reached"
                return DeliveryStatus.FAILED
            url, _ = _validate(self._target.url)  # re-validated before every request
            self.last_attempts = attempt
            status, retryable = self._attempt(url, headers, body, min(self.timeout, remaining))
            if not retryable or attempt == attempts:
                return status
            pause = self.backoff * (2 ** (attempt - 1))
            if self._monotonic() - started + pause >= self.deadline:
                return status
            self._sleep(pause)
        return status

    def _attempt(self, url: str, headers: Mapping[str, str], body: bytes,
                 timeout: float) -> tuple[DeliveryStatus, bool]:
        """One publish. Returns (status, whether a retry may help)."""
        label = self._target.label
        request = Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with self._opener(request, timeout) as response:
                code = getattr(response, "status", None)
                response.read(4096)
        except HTTPError as exc:
            exc.close()
            self.last_http_status = exc.code
            self.last_error = f"HTTP {exc.code} from {label}"
            if exc.code == 429:
                return DeliveryStatus.RATE_LIMITED, False
            return DeliveryStatus.FAILED, exc.code in _RETRYABLE_STATUS
        except (OSError, http.client.HTTPException) as exc:  # URLError, timeouts, resets, TLS
            reason = exc.reason if isinstance(exc, URLError) else exc
            self.last_error = self._redact(f"{type(exc).__name__} from {label}: {reason}")
            return DeliveryStatus.FAILED, not _cert_error(exc)
        if not isinstance(code, int):
            self.last_error = f"no HTTP status from {label}"
            return DeliveryStatus.FAILED, False
        self.last_http_status = code
        if 200 <= code < 300:
            self.last_error = None  # an earlier attempt's failure no longer applies
            return DeliveryStatus.SUBMITTED, False
        self.last_error = f"HTTP {code} from {label}"
        return DeliveryStatus.FAILED, code in _RETRYABLE_STATUS


def sink_from_env(environ: Mapping[str, str] | None = None, **kwargs: Any) -> NtfySink | None:
    """The configured sink, or None when `EDGE_LAB_NTFY_TOPIC_URL` is unset or blank.

    `EDGE_LAB_NTFY_TOKEN` is optional and is sent only as a Bearer header. Installing either
    value is an owner step; agents never create, see or commit them. A set but invalid value
    raises NtfyConfigError, whose message contains neither value."""
    env = os.environ if environ is None else environ
    topic_url = (env.get(ENV_TOPIC_URL) or "").strip(" ")  # only spaces: a control character fails validation
    if not topic_url:
        return None
    token = (env.get(ENV_TOKEN) or "").strip(" ") or None
    return NtfySink(topic_url, token=token, **kwargs)
