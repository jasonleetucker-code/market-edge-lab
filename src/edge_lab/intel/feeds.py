"""Hardened RSS 2.0 / Atom / Federal Register JSON parser (#192, ADR 0049).

Pure and network-free: bytes in, frozen `FeedItem`s out. Everything a feed contains is
untrusted data. It is reduced to what the source's `Rights` allow (headline, link, timestamps,
a short snippet), never evaluated, never followed and never read as an instruction.

Refusals return `ParseResult(ok=False, error=<code>)` and never raise:

- ``TOO_LARGE``       body longer than ``max_bytes``
- ``EMPTY``           nothing but whitespace (or a byte-order mark)
- ``DOCTYPE_REFUSED`` any ``<!DOCTYPE`` or ``<!ENTITY`` (entity-expansion bombs, external entities)
- ``MALFORMED_XML``   the XML parser rejected the body
- ``UNKNOWN_FORMAT``  well-formed, but not RSS, Atom or the Federal Register API shape
- ``MALFORMED_JSON``  the JSON parser rejected the body

Timestamps are normalized to ``YYYY-MM-DDTHH:MM:SSZ``. A timestamp without a zone is unknown
(``None``), not assumed UTC; the feed's own text is kept in ``published_raw`` for audit. The one
exception is the Federal Register's date-only ``publication_date``, which is a calendar date by
definition and is stored as that date at ``T00:00:00Z``.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from edge_lab.intel.contracts import (
    MAX_FEED_BYTES,
    SNIPPET_CHARS,
    TITLE_CHARS,
    FeedItem,
    ParseResult,
    Rights,
)

__all__ = [
    "UNKNOWN_ORIGIN",
    "canonical_url",
    "cluster_key",
    "group_clusters",
    "independent_origins",
    "normalize_title",
    "parse_feed",
]

# An aggregator item whose outlet cannot be identified has no origin family. It never counts as
# an independent origin (missing is not a source).
UNKNOWN_ORIGIN = "unknown"

MAX_URL_CHARS = 2048
_MAX_GUID_CHARS = 1024
_MAX_RAW_DATE_CHARS = 200
_MAX_CLEAN_INPUT_CHARS = 100_000  # bound the work done on any one untrusted text field
_ELLIPSIS = "…"

ATOM_NS = "http://www.w3.org/2005/Atom"
_ATOM03_NS = "http://purl.org/atom/ns#"
_DC_NS = "http://purl.org/dc/elements/1.1/"
_RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RSS10_NS = "http://purl.org/rss/1.0/"

_REFUSED_DECL = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)
_BOMS = (b"\xef\xbb\xbf",)

_TRACKING_PARAMS = frozenset({"fbclid", "gclid", "ocid", "cmpid"})
_DEFAULT_PORTS = {"http": 80, "https": 443}

_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<(?:[A-Za-z/!?][^<>]*)>")
_OUTLET_SUFFIX = re.compile(r"\s+[-–—|]\s+([^-–—|]{1,40})$")
_APOSTROPHES = re.compile(r"['’‘`]")
_PUNCT = re.compile(r"[^\w\s]|_")
_FR_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_OUTLET_ALIASES = {
    "ap": "ap",
    "ap news": "ap",
    "associated press": "ap",
    "the associated press": "ap",
    "reuters": "reuters",
    "thomson reuters": "reuters",
}
# Wire-service markers inside a non-aggregator item's own text: (pattern, origin).
_WIRE_MARKERS = (
    (re.compile(r"\(AP\)"), "ap"),
    (re.compile(r"\bAssociated Press\b", re.I), "ap"),
    (re.compile(r"\(Reuters\)", re.I), "reuters"),
    (re.compile(r"\bReuters reported\b", re.I), "reuters"),
)


# --------------------------------------------------------------------------------------------
# Text, URL and identity helpers
# --------------------------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _truncate(text: str, limit: int) -> str:
    """Cut `text` to at most `limit` characters, ending with an ellipsis when cut."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + _ELLIPSIS


def _clean(raw: str | None, limit: int) -> str | None:
    """Untrusted markup -> plain, single-line text of at most `limit` chars (None when empty).

    Drops script/style bodies and tags, unescapes entities (then drops any tags the unescape
    revealed), removes control and format characters, NFC-normalizes and collapses whitespace.
    """
    if raw is None:
        return None
    text = raw[:_MAX_CLEAN_INPUT_CHARS]
    text = _SCRIPT_STYLE.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _SCRIPT_STYLE.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = unicodedata.normalize("NFC", text)
    text = "".join(" " if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") else ch for ch in text)
    text = " ".join(text.split())
    return _truncate(text, limit) if text else None


def canonical_url(url: str | None) -> str | None:
    """A comparable form of an http(s) URL, or None for anything else.

    Lowercases scheme and host, drops user info, default ports, the fragment and tracking
    parameters (``utm_*``, fbclid, gclid, ocid, cmpid), sorts the remaining parameters and strips
    a trailing slash from a non-root path. Other schemes (javascript:, data:, mailto:, ...) and
    URLs with whitespace or control characters return None.
    """
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or len(url) > MAX_URL_CHARS or any(ch <= " " or ch == "\x7f" for ch in url):
        return None
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    host = host.lower()
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    params = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(sorted(params))
    return urlunsplit((scheme, netloc, path, query, ""))


def _strip_outlet_suffix(title: str) -> tuple[str, str | None]:
    """Split a trailing `` - Outlet`` / `` | Outlet`` (outlet <= 40 chars) off a title."""
    match = _OUTLET_SUFFIX.search(title)
    if not match or not title[: match.start()].strip():
        return title, None
    return title[: match.start()].rstrip(), match.group(1).strip()


def normalize_title(title: str) -> str:
    """Casefolded headline without outlet suffix or punctuation, single-spaced (for clustering)."""
    stripped, _ = _strip_outlet_suffix(" ".join(title.split()))
    text = _APOSTROPHES.sub("", stripped.casefold())
    return " ".join(_PUNCT.sub(" ", text).split())


def cluster_key(title: str, canonical_url: str | None) -> str:
    """sha256 of the normalized headline, so syndicated copies of one story cluster together.

    Falls back to the canonical URL (then the raw title) only when the headline normalizes to
    nothing, e.g. a title made only of punctuation.
    """
    basis = normalize_title(title)
    if not basis:
        basis = "url\x00" + canonical_url if canonical_url else "raw\x00" + title
    return _sha256(basis)


def _origin_slug(name: str | None) -> str | None:
    """Outlet name -> origin family slug ("Associated Press" -> "ap", "The Hill" -> "hill")."""
    if not name:
        return None
    key = " ".join(name.casefold().split())
    if key in _OUTLET_ALIASES:
        return _OUTLET_ALIASES[key]
    if key.startswith("the "):
        key = key[4:]
    slug = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
    return slug or None


def _wire_origin(*texts: str | None) -> str | None:
    """The wire service named earliest in the item's own text, if any."""
    best: tuple[int, str] | None = None
    for text in texts:
        if not text:
            continue
        for pattern, origin in _WIRE_MARKERS:
            match = pattern.search(text)
            if match and (best is None or match.start() < best[0]):
                best = (match.start(), origin)
        if best is not None:
            return best[1]
    return None


def _content_sha256(title: str, snippet: str | None, link: str | None) -> str:
    payload = {"link": link, "snippet": snippet, "title": title}
    return _sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


# --------------------------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------------------------


def _format_utc(moment: datetime) -> str | None:
    """Aware datetime -> ``YYYY-MM-DDTHH:MM:SSZ``; naive -> None (unknown zone)."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        return None
    try:
        utc = moment.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None
    return (f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}"
            f"T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}Z")


def _parse_rfc822(raw: str) -> str | None:
    try:
        return _format_utc(parsedate_to_datetime(raw))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _parse_iso(raw: str) -> str | None:
    text = raw.strip()
    if text[-1:] in ("z", "Z"):
        text = text[:-1] + "+00:00"
    try:
        return _format_utc(datetime.fromisoformat(text))
    except (ValueError, OverflowError):
        return None


def _parse_any_date(raw: str) -> str | None:
    """RSS dates are RFC 822 by spec but feeds also send ISO 8601; try both."""
    return _parse_rfc822(raw) or _parse_iso(raw)


def _parse_fr_date(raw: str) -> str | None:
    if not _FR_DATE.match(raw):
        return _parse_iso(raw) if raw else None
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return None
    return f"{day.isoformat()}T00:00:00Z"


def _raw_date(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = " ".join(raw.split())[:_MAX_RAW_DATE_CHARS]
    return text or None


# --------------------------------------------------------------------------------------------
# XML access (namespace-aware, iterative: no recursion on hostile nesting)
# --------------------------------------------------------------------------------------------


def _split_tag(tag: object) -> tuple[str | None, str]:
    if not isinstance(tag, str):  # comments and processing instructions
        return None, ""
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    return None, tag


def _text_of(element: ET.Element | None) -> str | None:
    """All text inside `element` in document order, gathered without recursion."""
    if element is None:
        return None
    chunks: list[str] = []
    size = 0
    stack: list[ET.Element | str] = [element]
    while stack and size < _MAX_CLEAN_INPUT_CHARS:
        node = stack.pop()
        if isinstance(node, str):  # a child's tail text
            chunks.append(node)
            size += len(node)
            continue
        if node.text and isinstance(node.tag, str):
            chunks.append(node.text)
            size += len(node.text)
        for child in reversed(node):  # LIFO: first child (then its tail) is popped first
            if child.tail:
                stack.append(child.tail)
            stack.append(child)
    text = "".join(chunks)
    return text if text.strip() else None


def _child(element: ET.Element, ns: str | None, local: str) -> ET.Element | None:
    for child in element:
        if _split_tag(child.tag) == (ns, local):
            return child
    return None


def _child_text(element: ET.Element, ns: str | None, local: str) -> str | None:
    return _text_of(_child(element, ns, local))


# --------------------------------------------------------------------------------------------
# Item assembly
# --------------------------------------------------------------------------------------------


class _Raw:
    """Fields of one entry as the feed stated them, before rights and normalization."""

    __slots__ = ("title", "link", "guid", "published_raw", "published_utc", "updated_utc",
                 "description", "outlet")

    def __init__(self, *, title, link, guid, published_raw, published_utc, updated_utc,
                 description, outlet=None):
        self.title = title
        self.link = link
        self.guid = guid
        self.published_raw = published_raw
        self.published_utc = published_utc
        self.updated_utc = updated_utc
        self.description = description
        self.outlet = outlet


def _build_item(raw: _Raw, *, source_id: str, rights: Rights, origin: str,
                aggregator: bool) -> FeedItem | None:
    title = _clean(raw.title, TITLE_CHARS * 4)  # strip the outlet suffix before the final cut
    if not title:
        return None
    item_origin = origin or UNKNOWN_ORIGIN
    if aggregator:
        outlet = _clean(raw.outlet, 200)
        candidate, suffix = _strip_outlet_suffix(title)
        if outlet is None or (suffix is not None and suffix.casefold() == outlet.casefold()):
            title = candidate  # strip only the named outlet, or any suffix when none is named
        else:
            suffix = None
        item_origin = _origin_slug(outlet) or _origin_slug(suffix) or UNKNOWN_ORIGIN
    title = _truncate(title, TITLE_CHARS)

    link_text = raw.link.strip() if isinstance(raw.link, str) else None
    canon = canonical_url(link_text)
    link = link_text if canon else None

    if rights is Rights.AGGREGATOR_DISCOVERY_ONLY:
        snippet = None
    else:
        snippet = _clean(raw.description, SNIPPET_CHARS)
    if not aggregator:
        item_origin = _wire_origin(title, snippet) or item_origin

    guid = raw.guid.strip()[:_MAX_GUID_CHARS] if isinstance(raw.guid, str) and raw.guid.strip() else None
    norm = normalize_title(title)
    identity = guid or canon or norm or title
    return FeedItem(
        source_id=source_id,
        item_key=_sha256(source_id + "\x00" + identity),
        guid=guid,
        title=title,
        link=link,
        canonical_url=canon,
        snippet=snippet,
        published_utc=raw.published_utc,
        updated_utc=raw.updated_utc,
        published_raw=raw.published_raw,
        cluster_key=cluster_key(title, canon),
        origin=item_origin,
        via_aggregator=aggregator,
        content_sha256=_content_sha256(title, snippet, link),
    )


def _rss_entry(item: ET.Element, ns: str | None) -> _Raw:
    """One RSS 2.0 <item> (ns None) or RSS 1.0 item (ns = RSS 1.0 namespace)."""
    guid_el = _child(item, ns, "guid")
    guid = _text_of(guid_el)
    link = _child_text(item, ns, "link")
    if not link:
        atom_link = _child(item, ATOM_NS, "link")
        if atom_link is not None:
            link = atom_link.get("href")
    if not link and guid and guid_el is not None and guid_el.get("isPermaLink", "true").lower() != "false":
        link = guid
    pub = _child_text(item, ns, "pubDate") or _child_text(item, _DC_NS, "date")
    raw_pub = _raw_date(pub)
    updated = _child_text(item, ATOM_NS, "updated")
    source_el = _child(item, ns, "source")
    return _Raw(
        title=_child_text(item, ns, "title"),
        link=link,
        guid=guid if guid else (item.get(f"{{{_RDF_NS}}}about") if ns else None),
        published_raw=raw_pub,
        published_utc=_parse_any_date(raw_pub) if raw_pub else None,
        updated_utc=_parse_iso(updated) if updated and updated.strip() else None,
        description=_child_text(item, ns, "description"),  # content:encoded is never read
        outlet=_text_of(source_el),
    )


def _atom_link(entry: ET.Element, ns: str) -> str | None:
    best: str | None = None
    for child in entry:
        if _split_tag(child.tag) != (ns, "link"):
            continue
        rel = (child.get("rel") or "alternate").lower()
        href = child.get("href") or (child.text or "").strip() or None
        if rel == "alternate" and href:
            return href
        if best is None and href and rel not in ("self", "edit", "enclosure", "replies"):
            best = href
    return best


def _atom_entry(entry: ET.Element, ns: str) -> _Raw:
    published = _child_text(entry, ns, "published") or _child_text(entry, ns, "issued")
    updated = _child_text(entry, ns, "updated") or _child_text(entry, ns, "modified")
    raw_pub = _raw_date(published) or _raw_date(updated)
    source = _child(entry, ns, "source")
    return _Raw(
        title=_child_text(entry, ns, "title"),
        link=_atom_link(entry, ns),
        guid=_child_text(entry, ns, "id"),
        published_raw=raw_pub,
        published_utc=_parse_iso(raw_pub) if raw_pub else None,
        updated_utc=_parse_iso(updated) if updated and updated.strip() else None,
        description=_child_text(entry, ns, "summary"),  # <content> (full text) is never read
        outlet=_child_text(source, ns, "title") if source is not None else None,
    )


def _items_from_xml(root: ET.Element) -> tuple[list[_Raw], str | None] | None:
    ns, local = _split_tag(root.tag)
    local = local.lower()
    if local == "rss" and ns is None:
        channel = _child(root, None, "channel")
        if channel is None:
            return None
        entries = [_rss_entry(el, None) for el in channel if _split_tag(el.tag) == (None, "item")]
        return entries, _child_text(channel, None, "title")
    if local == "rdf" and ns == _RDF_NS:
        channel = _child(root, _RSS10_NS, "channel")
        entries = [_rss_entry(el, _RSS10_NS) for el in root if _split_tag(el.tag) == (_RSS10_NS, "item")]
        return entries, _child_text(channel, _RSS10_NS, "title") if channel is not None else None
    if local == "feed" and ns in (ATOM_NS, _ATOM03_NS):
        entries = [_atom_entry(el, ns) for el in root if _split_tag(el.tag) == (ns, "entry")]
        return entries, _child_text(root, ns, "title")
    return None


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _items_from_federal_register(payload: object) -> list[_Raw] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return None
    entries: list[_Raw] = []
    for result in payload["results"]:
        if not isinstance(result, dict):
            continue
        raw_date = _raw_date(_str_or_none(result.get("publication_date")))
        description = _str_or_none(result.get("abstract"))
        if description is None:  # say what the document is rather than nothing
            agencies = result.get("agencies")
            names = [a.get("name") for a in agencies if isinstance(a, dict)] if isinstance(agencies, list) else []
            parts = [p for p in [_str_or_none(result.get("type"))] + [_str_or_none(n) for n in names] if p]
            description = " · ".join(parts) or None
        entries.append(_Raw(
            title=_str_or_none(result.get("title")),
            link=_str_or_none(result.get("html_url")),
            guid=_str_or_none(result.get("document_number")),
            published_raw=raw_date,
            published_utc=_parse_fr_date(raw_date) if raw_date else None,
            updated_utc=None,
            description=description,
        ))
    return entries


# --------------------------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------------------------


def _refuse(code: str) -> ParseResult:
    return ParseResult(ok=False, error=code)


def parse_feed(body: bytes, *, source_id: str, rights: Rights, origin: str, aggregator: bool = False,
               content_type: str | None = None, max_bytes: int = MAX_FEED_BYTES) -> ParseResult:
    """Parse one feed body into rights-reduced `FeedItem`s; refuse hostile input with a code.

    `origin` is the source's own origin family (e.g. "bbc"). For `aggregator=True` (e.g. Google
    News) each item's origin is the outlet it names instead, or `UNKNOWN_ORIGIN`.
    """
    if not isinstance(body, (bytes, bytearray, memoryview)):
        return _refuse("UNKNOWN_FORMAT")
    data = bytes(body)
    if len(data) > max_bytes:
        return _refuse("TOO_LARGE")
    for bom in _BOMS:
        if data.startswith(bom):
            data = data[len(bom):]
    if not data.strip():
        return _refuse("EMPTY")
    # Refuse declarations before any parser sees the bytes; NULs are removed for the scan so a
    # UTF-16/32 body cannot hide one.
    if _REFUSED_DECL.search(data) or _REFUSED_DECL.search(data.replace(b"\x00", b"")):
        return _refuse("DOCTYPE_REFUSED")

    stripped = data.lstrip()
    is_json = (content_type is not None and "json" in content_type.lower()) or stripped[:1] in (b"{", b"[")
    feed_title: str | None = None
    if is_json:
        try:
            payload = json.loads(data)
        except (ValueError, RecursionError):
            return _refuse("MALFORMED_JSON")
        entries = _items_from_federal_register(payload)
        if entries is None:
            return _refuse("UNKNOWN_FORMAT")
    else:
        try:
            root = ET.fromstring(data)
        except Exception:  # noqa: BLE001 - any parser failure on untrusted bytes is a refusal
            return _refuse("MALFORMED_XML")
        found = _items_from_xml(root)
        if found is None:
            return _refuse("UNKNOWN_FORMAT")
        entries, raw_title = found
        feed_title = _clean(raw_title, TITLE_CHARS)

    items: list[FeedItem] = []
    seen: set[tuple[str, str]] = set()
    for raw in entries:
        item = _build_item(raw, source_id=source_id, rights=rights, origin=origin, aggregator=aggregator)
        if item is None or (item.item_key, item.content_sha256) in seen:
            continue
        seen.add((item.item_key, item.content_sha256))
        items.append(item)
    return ParseResult(ok=True, items=tuple(items), feed_title=feed_title)


def group_clusters(items) -> dict[str, tuple[FeedItem, ...]]:
    """Items grouped by `cluster_key`, keys and members in first-seen order."""
    groups: dict[str, list[FeedItem]] = {}
    for item in items:
        groups.setdefault(item.cluster_key, []).append(item)
    return {key: tuple(members) for key, members in groups.items()}


def independent_origins(items) -> frozenset[str]:
    """Distinct origin families behind `items`.

    An aggregator item counts under the outlet it names, so a Google News copy of a Reuters
    story adds nothing beyond "reuters". Items with an unknown origin count for nothing.
    """
    return frozenset(item.origin for item in items if item.origin and item.origin != UNKNOWN_ORIGIN)
