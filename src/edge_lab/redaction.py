"""Secret redaction and refusal, shared by anything that persists or sends text.

Retrieved and generated text can carry credentials by accident: an API key in a URL query,
a bearer token or a cookie in an error message. Before any URL, error, provenance record or
notification is written or sent, it is redacted (`redact_url`, `redact_text`). Where a
secret must never appear at all, such as a notification, it is refused
(`contains_secret`).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SECRET_QUERY_KEYS = frozenset({"apikey", "api_key", "key", "token", "access_token", "secret", "password",
                               "signature", "sig", "session", "auth"})
REDACTED = "REDACTED"

_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|token|secret|password|passwd|"
               r"session[_-]?id|cookie)\b\s*[:=]\s*[^\s&]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)[?&](apikey|api_key|key|token|access_token|signature|sig)=[^&\s]+"),
    re.compile(r"-----BEGIN [A-Z ]*KEY-----"),
    # Venue request headers and HTTP authorization, as "Name: value" or "name=value" (the whole value to line end).
    re.compile(r"(?i)\b(kalshi-access-(?:key|signature|timestamp)|authorization|proxy-authorization|x-api-key)\b"
               r"\s*[:=]\s*[^\r\n]+"),
    re.compile(r"(?i)\bbasic\s+(?=[A-Za-z0-9+/]*[0-9+/=])[A-Za-z0-9+/]{8,}={0,2}"),  # credentials, not "basic words"
    # Key material and signatures assigned to a name.
    re.compile(r"(?i)\b(private[_-]?key|secret[_-]?key|signing[_-]?key|client[_-]?secret|signature)\b\s*[:=]\s*"
               r"[^\s&]+"),
    # A bare base64 run of 40+ characters that is not a plain hex digest (a key body, a signature): hashes such as
    # SHA-256 hex are identifiers and stay.
    re.compile(r"(?<![A-Za-z0-9+/=])(?=[A-Za-z0-9+/]*[G-Zg-z+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])"),
)


def redact_url(url: str) -> str:
    """The URL with the value of every secret-looking query parameter replaced."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return redact_text(url)
    query = [(k, REDACTED if k.lower() in SECRET_QUERY_KEYS else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    netloc = parts.netloc.rsplit("@", 1)[-1] if "@" in parts.netloc else parts.netloc  # drop user:pass@
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query, safe=REDACTED), parts.fragment))


def redact_text(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Remove known secret values, then anything matching a secret pattern."""
    out = text
    for value in secrets:
        if value:
            out = out.replace(value, REDACTED)
    for pattern in _PATTERNS:
        out = pattern.sub(_replacement, out)
    return out


def _replacement(match: re.Match[str]) -> str:
    text = match.group(0)
    if text[:1] in "?&":
        return f"{text[0]}{match.group(1)}={REDACTED}"
    if match.lastindex:
        return f"{match.group(1)}={REDACTED}"
    return REDACTED


def contains_secret(text: str) -> bool:
    return any(p.search(text) for p in _PATTERNS)


# A value `redact_text` already replaced, in the forms it writes ("name=REDACTED") or a header keeps ("Name: REDACTED").
_REDACTED_VALUE = re.compile(r"\s*[:=]\s*" + re.escape(REDACTED) + r"(?![A-Za-z0-9_])")


def contains_unredacted_secret(text: str) -> bool:
    """Whether text that has already been through `redact_text` still holds a secret: the same patterns, with every
    value redaction replaced set aside (otherwise "Authorization=REDACTED" would itself look like a credential)."""
    return contains_secret(_REDACTED_VALUE.sub("", text))
