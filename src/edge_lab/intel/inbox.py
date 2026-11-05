"""The private inbox between the read-only dashboard and the collector (owner answer "Inbox handoff").

The dashboard has no network and cannot write the evidence DB. It may only hand the collector
a request, through `write_submission`, which drops one size-capped JSON file into `new/`. The
five kinds are a transcript, an analysis/judgment paste, a refresh request, a link decision,
and a packet request. The collector (`process_inbox`, run by `edge-lab intel process-inbox`) handles each file:

1. it renames the file `new/` → `work/` before reading it, so a bad file cannot re-trigger;
2. it validates and dispatches it;
3. it records an `inbox` result in the journal, then moves the file to `done/` or `rejected/`.

Layout under the inbox root: tmp/ new/ work/ done/ rejected/. The file name is generated here,
never taken from the request.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import MAX_INBOX_FILE_BYTES, MAX_INBOX_PENDING, InboxKind, RefreshScope

INBOX_SCHEMA = "market-edge-intel-inbox/1"
DIRS = ("tmp", "new", "work", "done", "rejected")


class InboxError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def ensure_layout(root: Path) -> None:
    for d in DIRS:
        (root / d).mkdir(parents=True, exist_ok=True, mode=0o700)


def pending(root: Path) -> list[Path]:
    new = root / "new"
    return sorted(p for p in new.glob("*.json")) if new.is_dir() else []


def _validate(kind: InboxKind, payload: dict[str, Any]) -> None:
    if kind is InboxKind.TRANSCRIPT:
        if not isinstance(payload.get("text"), str) or not payload["text"].strip():
            raise InboxError("EMPTY", "the transcript text is empty")
        if not isinstance(payload.get("meta"), dict):
            raise InboxError("BAD_META", "transcript details are missing")
    elif kind is InboxKind.ANALYSIS:
        if not isinstance(payload.get("text"), str) or not payload["text"].strip():
            raise InboxError("EMPTY", "nothing was pasted")
    elif kind is InboxKind.REFRESH:
        try:
            RefreshScope(payload.get("scope"))
        except ValueError:
            raise InboxError("BAD_SCOPE", "unknown refresh scope") from None
        if payload.get("scope") == RefreshScope.DISCOVER.value and not payload.get("event_id"):
            raise InboxError("BAD_EVENT", "market discovery needs an event")
    elif kind is InboxKind.PACKET:
        if not isinstance(payload.get("event_id"), str) or not payload["event_id"]:
            raise InboxError("BAD_EVENT", "a packet request needs an event")
    elif kind is InboxKind.LINK:
        for key in ("outcome_id", "ticker", "status"):
            if not isinstance(payload.get(key), str) or not payload[key]:
                raise InboxError("BAD_LINK", f"link decision is missing {key}")
    else:  # pragma: no cover - enum is closed
        raise InboxError("BAD_KIND", "unknown submission kind")


def write_submission(root: Path, kind: str, payload: dict[str, Any], *, now: datetime | None = None) -> str:
    """Atomically queue one submission; returns its generated id. Raises InboxError on refusal."""
    try:
        k = InboxKind(kind)
    except ValueError:
        raise InboxError("BAD_KIND", "unknown submission kind") from None
    _validate(k, payload)
    ensure_layout(root)
    if len(pending(root)) >= MAX_INBOX_PENDING:
        raise InboxError("INBOX_FULL", f"{MAX_INBOX_PENDING} submissions are already waiting; try again after the "
                                       "collector has processed them")
    now = now or datetime.now(timezone.utc)
    sid = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{k.value}-{uuid.uuid4().hex[:10]}"
    body = json.dumps({"schema": INBOX_SCHEMA, "id": sid, "kind": k.value,
                       "submitted_utc": now.replace(microsecond=0).isoformat(), "payload": payload},
                      ensure_ascii=False, sort_keys=True).encode("utf-8")
    if len(body) > MAX_INBOX_FILE_BYTES:
        raise InboxError("TOO_LARGE", f"the submission is larger than {MAX_INBOX_FILE_BYTES // 1000} kB")
    tmp = root / "tmp" / f"{sid}.json"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, root / "new" / f"{sid}.json")
    return sid


def process_inbox(store, root: Path, *, now: datetime | None = None, limit: int = MAX_INBOX_PENDING,
                  kalshi_reader_factory=None, fetcher=None) -> list[dict[str, Any]]:
    """Handle queued submissions oldest first. Each gets an `inbox` record, whatever happens."""
    from . import service

    ensure_layout(root)
    results = []
    for path in pending(root)[:limit]:
        work = root / "work" / path.name
        try:
            os.replace(path, work)
        except FileNotFoundError:
            continue  # another processor took it
        result: dict[str, Any] = {"file": path.name}
        ok = False
        try:
            if work.stat().st_size > MAX_INBOX_FILE_BYTES:
                raise InboxError("TOO_LARGE", "submission file too large")
            sub = json.loads(work.read_text(encoding="utf-8"))
            if not isinstance(sub, dict) or sub.get("schema") != INBOX_SCHEMA:
                raise InboxError("BAD_SCHEMA", "not an inbox submission")
            kind = InboxKind(sub.get("kind"))
            payload = sub.get("payload") or {}
            _validate(kind, payload)
            result.update(kind=kind.value, id=sub.get("id"), submitted_utc=sub.get("submitted_utc"))
            when = now or datetime.now(timezone.utc)
            if kind is InboxKind.TRANSCRIPT:
                out = service.import_transcript(store, data=payload["text"].encode("utf-8"), meta=payload["meta"],
                                                filename=payload.get("filename"), now=when)
            elif kind is InboxKind.ANALYSIS:
                out = service.import_analysis(store, payload["text"], now=when,
                                              owner_judgment=payload.get("owner_judgment") is True)
            elif kind is InboxKind.PACKET:
                pk = service.create_packet(store, payload["event_id"], now=when,
                                           horizon_date=payload.get("horizon_date") or None)
                out = {"status": "PREPARED", "packet_id": pk.packet_id, "event_id": pk.event_id}
            elif kind is InboxKind.LINK:
                out = service.record_link(store, outcome_id=payload["outcome_id"], ticker=payload["ticker"],
                                          status=payload["status"], rules_read=bool(payload.get("rules_read")),
                                          yes_matches_outcome=bool(payload.get("yes_matches_outcome")), now=when)
            else:
                scope = RefreshScope(payload["scope"])
                if scope is RefreshScope.NEWS:
                    kwargs = {"fetcher": fetcher} if fetcher else {}
                    out = service.collect_news(store, now=when, **kwargs)
                elif scope is RefreshScope.QUOTES:
                    reader = kalshi_reader_factory(store, when) if kalshi_reader_factory else None
                    out = service.refresh_quotes(store, now=when, reader=reader,
                                                 only_outcome=payload.get("outcome_id"))
                else:
                    reader = kalshi_reader_factory(store, when) if kalshi_reader_factory else None
                    out = service.discover_markets(store, payload["event_id"], now=when, reader=reader)
            result.update(status="DONE", outcome=_brief(out))
            ok = out.get("status") not in ("REFUSED",) if isinstance(out, dict) else True
            if not ok:
                result["status"] = "REFUSED"
        except InboxError as exc:
            result.update(status="REJECTED", code=exc.code, message=exc.message)
        except Exception as exc:  # every failure is recorded for the owner, never swallowed silently
            code = getattr(exc, "code", type(exc).__name__)
            msg = getattr(exc, "message", None) or "; ".join(getattr(exc, "problems", []) or [str(exc)])
            result.update(status="REJECTED", code=str(code), message=str(msg)[:2000])
        dest = root / ("done" if result.get("status") == "DONE" else "rejected") / path.name
        os.replace(work, dest)
        store.append_intel_record(kind="inbox", subject_id=path.name, schema=INBOX_SCHEMA, payload=result)
        results.append(result)
    return results


def _brief(out: Any) -> Any:
    if not isinstance(out, dict):
        return out
    keep = {k: v for k, v in out.items() if k not in ("candidates", "decisions") or not isinstance(v, list)}
    if isinstance(out.get("decisions"), list):
        keep["decisions"] = [{k: d.get(k) for k in ("ticker", "action", "explanation")} for d in out["decisions"]]
    if isinstance(out.get("candidates"), list):
        keep["candidates"] = len(out["candidates"])
    return keep
