"""The dashboard's single write route: POST /experiments/intel/inbox (issue 192, ADR 0049, UI_CONTRACT §14 2026-11-05).

It turns one browser form into one size-capped JSON file in the private intel inbox, through
`intel.inbox.write_submission`, and nothing else. The evidence database stays read-only (it is
opened only with `SnapshotStore.open_readonly`, to validate an analysis against its recorded
packet), the dashboard keeps no network, and no order, money, approval or account action exists.

Checks, in order, each refusing with a readable reason and writing nothing:

1. the dashboard was started with an inbox (`--intel-inbox`), else 405 "not enabled";
2. the Host is allowed (checked by the app before this module runs);
3. the request's Origin (or, without one, its Referer) names exactly this Host (403);
4. a Content-Length is given (411) and is at most `MAX_BODY_BYTES` (413) — the body is never
   read past it, and the server's socket timeout bounds a slow sender (408);
5. the body is `application/x-www-form-urlencoded` or `multipart/form-data` (415), parsed with
   the stdlib only (`urllib.parse`, `email.parser.BytesParser(policy=email.policy.HTTP)`);
6. the per-process form token matches (`secrets.compare_digest`; 403);
7. the kind and every field are validated against fixed sets and bounded patterns (400), an
   uploaded transcript must be strict UTF-8 (415), and a full inbox answers 429.
"""

from __future__ import annotations

import email.parser
import email.policy
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit

from . import presentation as pr

MAX_BODY_BYTES = 1_600_000
MAX_FIELDS = 40
MAX_UPLOAD_BYTES = 1_500_000
FORM = "application/x-www-form-urlencoded"
MULTIPART = "multipart/form-data"
KINDS = ("transcript", "analysis", "refresh", "link", "packet")
UPLOAD_SUFFIXES = (".txt", ".md", ".srt", ".vtt")
_EVENT = re.compile(r"ev-[a-z_]{1,40}-[0-9a-f]{12}")
_OUTCOME = re.compile(r"ev-[a-z_]{1,40}-[0-9a-f]{12}:[a-z0-9_]{1,40}")
_TICKER = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,99}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DEFAULT_PORTS = {"http": "80", "https": "443"}


@dataclass(frozen=True)
class Outcome:
    """What the app answers: a 303 to `location`, or a refusal page with `code` and `reason`."""

    code: int
    reason: str = ""
    location: str | None = None
    back: str = pr.INTEL_PATH


class Refused(Exception):
    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def new_token() -> str:
    """The per-process form token (never stored, never logged)."""
    return secrets.token_urlsafe(32)


def _norm_host(netloc: str, scheme: str | None) -> str:
    text = netloc.strip().lower().rstrip(".")
    if scheme and text.endswith(":" + _DEFAULT_PORTS.get(scheme, "-")):
        text = text.rsplit(":", 1)[0]
    return text


def same_origin(environ: dict[str, Any]) -> bool:
    host = environ.get("HTTP_HOST")
    if not host:
        return False
    origin = environ.get("HTTP_ORIGIN")
    source = origin if origin is not None else environ.get("HTTP_REFERER")
    if not source or source == "null":
        return False
    parts = urlsplit(str(source))
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return _norm_host(parts.netloc, parts.scheme) in {_norm_host(str(host), parts.scheme), _norm_host(str(host), None)}


def _content_length(environ: dict[str, Any]) -> int:
    raw = str(environ.get("CONTENT_LENGTH") or "").strip()
    if not raw:
        raise Refused(411, "The request did not say how long it is (Content-Length is required).")
    if not raw.isdigit():
        raise Refused(400, "The request's Content-Length is not a number.")
    n = int(raw)
    if n > MAX_BODY_BYTES:
        raise Refused(413, f"The submission is larger than {MAX_BODY_BYTES // 1000} kB.")
    return n


def _read(environ: dict[str, Any], n: int) -> bytes:
    stream = environ.get("wsgi.input")
    if stream is None:
        raise Refused(400, "The request has no body.")
    chunks, left = [], n
    try:
        while left > 0:
            chunk = stream.read(min(left, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
    except (TimeoutError, OSError):
        raise Refused(408, "The upload was too slow and timed out. Try again.") from None
    body = b"".join(chunks)
    if len(body) != n:
        raise Refused(400, "The request ended before its stated length.")
    return body


def _text(value: bytes, what: str) -> str:
    try:
        return value.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise Refused(415, f"{what} is not valid UTF-8 text.") from None


def parse_body(content_type: str, body: bytes) -> tuple[dict[str, list[str]], dict[str, tuple[str, bytes]]]:
    """(fields, files). Every text value is strict UTF-8; at most MAX_FIELDS parts."""
    ctype = content_type.split(";", 1)[0].strip().lower()
    fields: dict[str, list[str]] = {}
    files: dict[str, tuple[str, bytes]] = {}
    if ctype == FORM:
        try:
            pairs = parse_qsl(body.decode("ascii"), keep_blank_values=True, encoding="utf-8", errors="strict",
                              max_num_fields=MAX_FIELDS)
        except (UnicodeDecodeError, ValueError):
            raise Refused(400, "The form could not be read (too many fields or invalid UTF-8).") from None
        for k, v in pairs:
            fields.setdefault(k, []).append(v)
        return fields, files
    if ctype != MULTIPART:
        raise Refused(415, "Only form submissions are accepted (urlencoded or multipart form data).")
    if "boundary=" not in content_type:
        raise Refused(400, "The multipart form has no boundary.")
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1", errors="strict")
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(header + body)
    if not msg.is_multipart():
        raise Refused(400, "The multipart form could not be read.")
    parts = list(msg.iter_parts())
    if len(parts) > MAX_FIELDS:
        raise Refused(400, "The form has too many fields.")
    for part in parts:
        if part.get_content_disposition() != "form-data":
            raise Refused(400, "The multipart form has a part that is not form data.")
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str) or not name:
            raise Refused(400, "The multipart form has an unnamed part.")
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename is not None:
            if len(payload) > MAX_UPLOAD_BYTES:
                raise Refused(413, f"The uploaded file is larger than {MAX_UPLOAD_BYTES // 1000} kB.")
            files[name] = (str(filename), payload)
        else:
            fields.setdefault(name, []).append(_text(payload, f"The field {name}"))
    return fields, files


def _one(fields: dict[str, list[str]], name: str, *, limit: int = 200, required: bool = False) -> str | None:
    values = fields.get(name) or []
    if len(values) > 1:
        raise Refused(400, f"The field {name} was given more than once.")
    value = values[0].strip() if values else ""
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in value):
        raise Refused(400, f"The field {name} contains control characters.")
    if len(value) > limit:
        raise Refused(400, f"The field {name} is longer than {limit} characters.")
    if required and not value:
        raise Refused(400, f"The field {name} is required.")
    return value or None


def _checked(fields: dict[str, list[str]], name: str) -> bool:
    return (_one(fields, name, limit=10) or "") in ("yes", "on", "true", "1")


def _match(value: str | None, pattern: re.Pattern, what: str) -> str:
    if value is None or not pattern.fullmatch(value):
        raise Refused(400, f"The {what} is missing or not recognised.")
    return value


def _upload_name(name: str) -> str:
    base = PureWindowsPath(PurePosixPath(name).name).name.strip()
    if not base or len(base) > 120 or not re.fullmatch(r"[A-Za-z0-9._ ()-]+", base):
        raise Refused(400, "The uploaded file name is not plain (letters, digits, dots, dashes, spaces).")
    if not base.lower().endswith(UPLOAD_SUFFIXES):
        raise Refused(415, "Only .txt, .md, .srt or .vtt transcript files are accepted.")
    return base


def build_payload(kind: str, fields: dict[str, list[str]], files: dict[str, tuple[str, bytes]], *, today: date,
                  packet_lookup: Callable[[str], Any] | None) -> dict[str, Any]:
    """The inbox payload for one submission, validated as far as the dashboard can without writing."""
    from ..intel.pricing import protected_reason

    if kind == "transcript":
        from ..intel.transcripts import TranscriptError, parse_transcript, validate_meta
        meta = {k: v for k, v in (
            ("podcast", _one(fields, "podcast", required=True)), ("episode", _one(fields, "episode", required=True)),
            ("published_date", _one(fields, "published_date", limit=10)),
            ("episode_url", _one(fields, "episode_url", limit=2000)),
            ("transcript_source", _one(fields, "transcript_source", limit=120, required=True)),
            ("notes", _one(fields, "notes", limit=4000))) if v is not None}
        upload = files.get("file")
        filename = None
        if upload is not None and upload[1]:
            filename = _upload_name(upload[0])
            data = upload[1]
            text = _text(data, "The uploaded file")
        else:
            text = _one(fields, "text", limit=MAX_UPLOAD_BYTES) or ""
            data = text.encode("utf-8")
            if not text:
                raise Refused(400, "Paste a transcript or choose a file.")
        try:
            validate_meta(meta, today=today)
            parse_transcript(data, filename=filename)
        except TranscriptError as exc:
            raise Refused(415 if exc.code in ("NOT_UTF8", "BINARY") else 400, exc.message) from None
        return {"text": text, "meta": meta, "filename": filename}
    if kind == "analysis":
        text = _one(fields, "text", limit=262_144, required=True)
        owner = _checked(fields, "owner_judgment")
        if packet_lookup is not None:
            from ..intel.analysis_import import AnalysisError, import_pasted
            try:
                import_pasted(text, packet_lookup, owner_judgment=owner)
            except AnalysisError as exc:
                raise Refused(400, "The analysis does not validate: " + "; ".join(exc.problems[:8])) from None
            except Exception:  # noqa: BLE001 - a store read problem: the collector validates it again
                pass
        return {"text": text, "owner_judgment": owner}
    if kind == "refresh":
        scope = _one(fields, "scope", limit=20)
        if scope not in ("news", "quotes", "discover"):
            raise Refused(400, "Unknown refresh scope.")
        payload: dict[str, Any] = {"scope": scope}
        if scope == "discover":
            payload["event_id"] = _match(_one(fields, "event_id"), _EVENT, "event")
        outcome = _one(fields, "outcome_id")
        if scope == "quotes" and outcome:
            payload["outcome_id"] = _match(outcome, _OUTCOME, "outcome")
        return payload
    if kind == "link":
        outcome = _match(_one(fields, "outcome_id"), _OUTCOME, "outcome")
        ticker = _match(_one(fields, "ticker", limit=100), _TICKER, "market ticker")
        status = _one(fields, "status", limit=20)
        if status not in ("CONFIRMED", "REJECTED"):
            raise Refused(400, "Choose Confirm link or Reject candidate.")
        if protected_reason(ticker):
            raise Refused(400, f"{ticker} is protected research scope; this lane never links it.")
        rules_read, yes_ok = _checked(fields, "rules_read"), _checked(fields, "yes_matches_outcome")
        if status == "CONFIRMED" and not (rules_read and yes_ok):
            raise Refused(400, "A link is confirmed only after you tick both boxes: you read the market's rules, "
                               "and its YES means this outcome.")
        return {"outcome_id": outcome, "ticker": ticker, "status": status, "rules_read": rules_read,
                "yes_matches_outcome": yes_ok}
    if kind == "packet":
        payload = {"event_id": _match(_one(fields, "event_id"), _EVENT, "event")}
        horizon = _one(fields, "horizon_date", limit=10)
        if horizon:
            try:
                if not _DATE.fullmatch(horizon):
                    raise ValueError(horizon)
                day = date.fromisoformat(horizon)
            except ValueError:
                raise Refused(400, "The forecast horizon must be a real date written YYYY-MM-DD.") from None
            if day < today:
                raise Refused(400, "The forecast horizon must not be in the past.")
            payload["horizon_date"] = horizon
        return payload
    raise Refused(400, "Unknown submission kind.")


def _return(fields: dict[str, list[str]]) -> tuple[str, str | None]:
    tab = (fields.get("return_tab") or [""])[0]
    event = (fields.get("return_event") or [""])[0]
    tab = tab if tab in dict(pr.INTEL_TABS) else "today"
    return tab, event if _EVENT.fullmatch(event or "") else None


def _back(tab: str, event: str | None, **extra: str) -> str:
    q = {"tab": tab, **({"event": event} if event else {}), **extra}
    return pr.INTEL_PATH + "?" + urlencode(q)


def handle(environ: dict[str, Any], *, inbox_root: Path | None, token: str, db: Path | None,
           now: datetime) -> Outcome:
    """Validate one submission and queue it. Never raises; never writes anything but the one inbox file."""
    if inbox_root is None:
        return Outcome(405, "Submissions are not enabled on this dashboard (it was started without --intel-inbox).")
    back = pr.INTEL_PATH
    try:
        if not same_origin(environ):
            raise Refused(403, "The form did not come from this dashboard (its Origin does not match the Host).")
        n = _content_length(environ)
        fields, files = parse_body(str(environ.get("CONTENT_TYPE") or ""), _read(environ, n))
        tab, event = _return(fields)
        back = _back(tab, event)
        sent = (fields.get("token") or [""])
        if len(sent) != 1 or not secrets.compare_digest(sent[0].encode(), token.encode()):
            raise Refused(403, "The form has expired or did not come from this page. Reload the page and try again.")
        kind = _one(fields, "kind", limit=20)
        if kind not in KINDS:
            raise Refused(400, "Unknown submission kind.")
        lookup = None
        if kind == "analysis" and db is not None:
            lookup = _packet_lookup(db)
        payload = build_payload(kind, fields, files, today=now.date(), packet_lookup=lookup)
        from ..intel.inbox import InboxError, write_submission
        try:
            sid = write_submission(inbox_root, kind, payload, now=now)
        except InboxError as exc:
            code = {"INBOX_FULL": 429, "TOO_LARGE": 413}.get(exc.code, 400)
            raise Refused(code, exc.message) from None
        except OSError:
            raise Refused(500, "The private inbox could not be written. Nothing was queued.") from None
        return Outcome(303, location=_back(tab, event, submitted=sid), back=back)
    except Refused as exc:
        return Outcome(exc.code, exc.reason, back=back)


def _packet_lookup(db: Path) -> Callable[[str], Any] | None:
    """A packet lookup over the read-only store, or None when it cannot be opened (the collector validates then)."""
    from ..intel import service
    from ..storage import SnapshotStore

    try:
        store = SnapshotStore.open_readonly(db)
    except Exception:  # noqa: BLE001 - validation is a convenience; the collector validates again
        return None
    return lambda pid: service.stored_packet(store, pid)
