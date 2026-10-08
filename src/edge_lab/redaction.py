"""Secret redaction and refusal, shared by anything that persists or sends text.

Retrieved and generated text can carry credentials by accident: an API key in a URL query,
a bearer token or a cookie in an error message. Before any URL, error, provenance record or
notification is written or sent, it is redacted (`redact_url`, `redact_text`). Where a
secret must never appear at all, such as a notification, it is refused
(`contains_secret`).

Redaction keeps JSON valid: a value never runs past an unescaped double quote and never splits a
backslash escape, so `json.loads(redact_text(json.dumps(x)))` still parses (`odds_api.save_snapshot`).
A value that is itself quoted with an escaped quote (`\\"...`) is matched from inside the quote.

Known limits, by design (each is an identifier or prose, not key material):
- `0x`-prefixed hex (EVM addresses, Polymarket condition ids) and plain hex digests are never a bare key body.
- A 40+ run of only letters and slashes, with no digit, `+` or `=` padding, reads as a path, not a key body.
  A random base64 body of 64+ characters has no digit and no `+` with probability under 1e-5.
- `authorization` and `signature` are words in prose ("participation authorization: none"), so their value is
  redacted only when it is credential-shaped (`_CRED`). The distinctive names (the Kalshi headers, x-api-key,
  key-material names, password, ...) redact any value.
- A key that is itself quoted (`{"password": "x"}`, a JSON-dumped header map) is not matched by the name rules;
  only the value-shape rules (bearer, basic, bare base64, PEM) cover it.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SECRET_QUERY_KEYS = frozenset({"apikey", "api_key", "key", "token", "access_token", "secret", "password",
                               "signature", "sig", "session", "auth"})
REDACTED = "REDACTED"

_SEP = r"\s*[:=]\s*(?:\\?[\"'])?"  # "name: value", "name=value", an optionally quoted value; \s spans a newline
_VALUE = r"(?:[^\s&\"\\]|\\\S)+"  # one token; stops at an unescaped quote and never splits a backslash escape
_LINE = r"(?:[^\r\n\"\\]|\\[^\s nr])+"  # the rest of the line; also stops at an encoded \n or \r and at a quote
# A credential-shaped token: 8+ characters with a digit or one of + / = _ . ~ -, or 16+ characters of anything.
_CRED = r"(?:(?=[^\s\"'\\]*[0-9+/=_.~-])[^\s\"'\\]{8,}|[^\s\"'\\]{16,})"
# A name starts at a word boundary or right after an encoded \n, \t, ... (JSON text: "x\nKALSHI-ACCESS-KEY: ...").
_START = r"(?:(?<=\\[bfnrt])|\b)"

_PATTERNS = (
    re.compile(r"(?i)" + _START + r"(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|token|secret|password|"
               r"passwd|session[_-]?id|cookie)\b" + _SEP + _VALUE),
    re.compile(r"(?i)" + _START + r"bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)[?&](apikey|api_key|key|token|access_token|signature|sig)=[^&\s]+"),
    re.compile(r"-----BEGIN [A-Z ]*KEY-----"),
    # Venue request headers, as "Name: value" or "name=value" (the value to line end), or "Name value" when the
    # value is credential-like (8+ characters with a digit); "the KALSHI-ACCESS-KEY header" is prose.
    re.compile(r"(?i)" + _START + r"(kalshi-access-(?:key|signature|timestamp)|x-api-key)\b"
               r"(?:" + _SEP + _LINE + r"|[ \t]+(?=[^\s\"'\\]*[0-9])[^\s\"'\\]{8,})"),
    # HTTP authorization: an optional scheme, then a credential-shaped token, then the rest of the line.
    re.compile(r"(?i)" + _START + r"(proxy-authorization|authorization)\b" + _SEP +
               r"(?:[A-Za-z][A-Za-z0-9-]*[ \t]+)?" + _CRED + r"(?:" + _LINE + r")?"),
    re.compile(r"(?i)" + _START + r"basic\s+(?=[A-Za-z0-9+/]*[0-9+/=])[A-Za-z0-9+/]{8,}={0,2}"),  # not "basic words"
    # Key material assigned to a name (any value), and a signature (a credential-shaped value).
    re.compile(r"(?i)" + _START + r"(private[_-]?key|secret[_-]?key|signing[_-]?key|client[_-]?secret)\b" + _SEP +
               _VALUE),
    re.compile(r"(?i)" + _START + r"(signature)\b" + _SEP + _CRED),
    # A bare base64 run of 40+ characters (a key body, a signature) that is not an identifier: not plain hex (SHA-256,
    # a git SHA), not 0x-prefixed hex (an EVM address, a Polymarket condition id), and not letters and slashes only
    # (a path or prose: a key body has a digit, a '+' or '=' padding, or no slash).
    # It starts after a non-run character or an encoded \n, \t, ..., never on the letter of a JSON escape.
    re.compile(r"(?:(?<=\\[bfnrt])|(?<![A-Za-z0-9+/=])(?:(?<!\\)|(?![bfnrtu])))"
               r"(?!0[xX][0-9a-fA-F]+(?![A-Za-z0-9+/=]))"
               r"(?=[A-Za-z0-9+/]*[G-Zg-z+/])"
               r"(?=[A-Za-z0-9+/]*[0-9+]|[A-Za-z/]*=|[A-Za-z]+(?![A-Za-z0-9+/=]))"
               r"[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])"),
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
