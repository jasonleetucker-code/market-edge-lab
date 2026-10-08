"""Secret redaction and refusal, shared by anything that persists or sends text.

Retrieved and generated text can carry credentials by accident: an API key in a URL query,
a bearer token or a cookie in an error message. Before any URL, error, provenance record or
notification is written or sent, it is redacted (`redact_url`, `redact_text`). Where a
secret must never appear at all, such as a notification, it is refused
(`contains_secret`).

`redact_text` works on raw text: a named value runs greedily to whitespace or `&` (quotes included), and a
header value to the end of its line. It is not JSON-aware and can break JSON text, so structured data is redacted
structurally instead (`redact_json`: every string redacted on its own, then encoded), never as dumped JSON text.

Known limits, by design (each is an identifier or prose, not key material):
- Plain hex digests (SHA-256, git SHAs) and `0x` + 40 hex (an EVM address) are never a bare key body.
- `0x` + 64 hex is ambiguous: a Polymarket condition id and a transaction hash have exactly the shape of an EVM
  private key. It is redacted only right after a key-ish name (private, secret, key, seed, mnemonic); a bare one,
  or one introduced by other words ("seed phrase 0x..."), passes. Callers must never hold key material as text.
- A 40+ run of only letters and slashes, with no digit, `+` or `=` padding, reads as a path, not a key body.
  A random base64 body of 64+ characters has no digit and no `+` with probability under 1e-5.
- `authorization`, `proxy-authorization` and `signature` are also words in prose, so a value that is exactly one
  stop word (`_PROSE`: none, required, missing, ...; any case; trailing punctuation ignored) is kept. Any other
  value is redacted, as for every other name.
- A key that is itself quoted (`{"password": "x"}`, a JSON-dumped header map) is not matched by the name rules;
  only the value-shape rules (bearer, basic, bare base64, PEM) cover it. `redact_json` sees the value alone.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SECRET_QUERY_KEYS = frozenset({"apikey", "api_key", "key", "token", "access_token", "secret", "password",
                               "signature", "sig", "session", "auth"})
REDACTED = "REDACTED"

_SEP = r"\s*[:=]\s*"  # "name: value" or "name=value"; \s spans a newline
_VALUE = r"[^\s&]+"  # a named value: greedy to whitespace or '&', quotes included
_LINE = r"[^\r\n]+"  # a header value: the rest of the line
# A name starts at a word boundary, or right after an escape such as \n or \t written out in logged JSON text.
_START = r"(?:(?<=\\[bfnrt])|\b)"
# Prose values of authorization and signature: the whole value, any case, trailing punctuation ignored.
_PROSE = (r"(?:none|null|n/a|na|missing|required|not[ -]required|optional|pending|unchecked|checked|unverified|"
          r"verified|valid|invalid|expired|revoked|granted|not[ -]granted|not-yet-granted|denied|failed|absent|"
          r"present|unknown|empty|ok|yes|no|true|false)")
_PUNCT = r"[.,;:!?\u2026)\]\"']*"
_KEYISH = r"[A-Za-z_-]*(?:private|secret|key|seed|mnemonic)[A-Za-z_-]*"

_PATTERNS = (
    re.compile(r"(?i)" + _START + r"(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|token|secret|password|"
               r"passwd|session[_-]?id|cookie)\b" + _SEP + _VALUE),
    re.compile(r"(?i)" + _START + r"bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)[?&](apikey|api_key|key|token|access_token|signature|sig)=[^&\s]+"),
    re.compile(r"-----BEGIN [A-Z ]*KEY-----"),
    # Venue request headers, as "Name: value" or "name=value" (the value to line end), or "Name value" when the
    # value is credential-like (8+ characters with a digit): "the KALSHI-ACCESS-KEY header" is prose.
    re.compile(r"(?i)" + _START + r"(kalshi-access-(?:key|signature|timestamp)|x-api-key)\b"
               r"(?:" + _SEP + _LINE + r"|[ \t]+(?=\S*[0-9])\S{8,})"),
    # HTTP authorization: the rest of the line, unless the whole value is one prose word.
    re.compile(r"(?i)" + _START + r"(proxy-authorization|authorization)\b" + _SEP +
               r"(?=\S)(?!" + _PROSE + _PUNCT + r"[ \t]*(?:[\r\n]|\Z))" + _LINE),
    re.compile(r"(?i)" + _START + r"basic\s+(?=[A-Za-z0-9+/]*[0-9+/=])[A-Za-z0-9+/]{8,}={0,2}"),  # not "basic words"
    # Key material assigned to a name, and a signature (unless the value is one prose word).
    re.compile(r"(?i)" + _START + r"(private[_-]?key|secret[_-]?key|signing[_-]?key|client[_-]?secret)\b" + _SEP +
               _VALUE),
    re.compile(r"(?i)" + _START + r"(signature)\b" + _SEP + r"(?!" + _PROSE + _PUNCT + r"(?:[\s&]|\Z))" + _VALUE),
    # 0x + 64 hex right after a key-ish name: an EVM private key ("key 0x...", "eth_private_key: 0x...").
    re.compile(r"(?i)\b(" + _KEYISH + r")[\s:=\"'\\]{1,6}0x[0-9a-f]{64}(?![A-Za-z0-9+/=])"),
    # A bare base64 run of 40+ characters (a key body, a signature) that is not an identifier: not plain hex (SHA-256,
    # a git SHA), not 0x + 40 or 64 hex (an address, a condition id or transaction hash: see the docstring), and not
    # letters and slashes only (a path or prose: a key body has a digit, a '+' or '=' padding, or no slash).
    re.compile(r"(?<![A-Za-z0-9+/=])"
               r"(?!0[xX](?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})(?![A-Za-z0-9+/=]))"
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
    """Remove known secret values, then anything matching a secret pattern. For raw text, not JSON text."""
    out = text
    for value in secrets:
        if value:
            out = out.replace(value, REDACTED)
    for pattern in _PATTERNS:
        out = pattern.sub(_replacement, out)
    return out


def redact_json(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    """A JSON-ready copy of `value` with every string redacted on its own (`redact_text`), keys included.

    Mappings become dicts (keys as strings, as JSON encodes them), lists and tuples become lists, None, bools,
    ints and floats are kept, and anything else is redacted as its `str()` (like `json.dumps(default=str)`).
    Two keys that redact to the same text raise ValueError rather than silently merging."""
    if isinstance(value, str):
        return redact_text(value, secrets)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = redact_text(k if isinstance(k, str) else str(k), secrets)
            if key in out:
                raise ValueError("two keys redact to the same text")
            out[key] = redact_json(v, secrets)
        return out
    if isinstance(value, (list, tuple)):
        return [redact_json(v, secrets) for v in value]
    return redact_text(str(value), secrets)


def _replacement(match: re.Match[str]) -> str:
    text = match.group(0)
    if text[:1] in "?&":
        return f"{text[0]}{match.group(1)}={REDACTED}"
    if match.lastindex:
        return f"{match.group(1)}={REDACTED}"
    return REDACTED


def contains_secret(text: str) -> bool:
    return any(p.search(text) for p in _PATTERNS)
