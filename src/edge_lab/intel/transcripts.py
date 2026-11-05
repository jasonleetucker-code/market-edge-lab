"""Owner-supplied podcast transcripts: parsing, normalization and metadata (#192, ADR 0049).

Pure and network-free. A transcript is untrusted text: it is decoded strictly, normalized and
split into ``(timestamp, speaker, text)`` segments; nothing in it is ever followed or obeyed.

Formats: ``txt``, ``md``, ``srt`` and ``vtt``. The format comes from ``declared_format``, else the
filename extension, else a sniff (a ``WEBVTT`` header, or an SRT number + ``-->`` cue), else txt.

Refusals raise `TranscriptError` with a machine ``code``: ``TOO_LARGE``, ``EMPTY``, ``NOT_UTF8``,
``BINARY``, ``UNSUPPORTED_FORMAT`` or ``BAD_META``.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import date, timedelta
from pathlib import PurePath

from edge_lab.intel.contracts import MAX_TRANSCRIPT_BYTES, Transcript, TranscriptMeta
from edge_lab.intel.feeds import canonical_url

__all__ = [
    "FORMATS",
    "TranscriptError",
    "episode_key",
    "parse_transcript",
    "validate_meta",
]

FORMATS = ("txt", "md", "srt", "vtt")
_FORMAT_ALIASES = {
    "txt": "txt", "text": "txt",
    "md": "md", "markdown": "md",
    "srt": "srt", "subrip": "srt",
    "vtt": "vtt", "webvtt": "vtt",
}

_BOM = b"\xef\xbb\xbf"
_SNIFF_CHARS = 4096

_TIME = r"(?:\d{1,3}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
_TIMING = re.compile(rf"^\s*({_TIME})\s*-->\s*({_TIME})")
_SRT_SNIFF = re.compile(rf"^\s*\d+\s*\n\s*{_TIME}\s*-->", re.M)
_VOICE = re.compile(r"<v(?:\.[\w.-]+)?\s+([^>]+)>", re.I)
_CUE_TAG = re.compile(r"</?[A-Za-z][^<>]*>|\{\\[^{}]*\}")  # <i>, </v>, <c.x>, {\an8}
_CUE_TIMESTAMP = re.compile(rf"<{_TIME}>")
# Optional leading "[00:12:34]" / "(12:34)" / "00:12:34", then "Speaker Name:" (1-4 capitalized words).
_LINE_TIME = re.compile(r"^\s*[\[(]?(\d{1,2}:\d{2}(?::\d{2})?)[\])]?\s+")
_SPEAKER = re.compile(r"^((?:[A-Z][\w.'’-]*)(?:[ \t]+[A-Z][\w.'’-]*){0,3}):[ \t]+(\S.*)$")
_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]]*$")

_MD_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_MD_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_MD_ITALIC = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])|(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")
_MD_LINK = re.compile(r"\[([^\[\]\n]+)\]\((?:[^()\s]+)\)")
_MD_QUOTE = re.compile(r"^[ \t]{0,3}>[ \t]?")

_META_KEYS = frozenset({"podcast", "episode", "published_date", "episode_url", "transcript_source", "notes"})
_META_LIMITS = {"podcast": 200, "episode": 200, "transcript_source": 120, "notes": 4000, "episode_url": 2048,
                "published_date": 32}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TranscriptError(ValueError):
    """A refused transcript or metadata block; ``code`` is the machine-readable reason."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


# --------------------------------------------------------------------------------------------
# Format selection and normalization
# --------------------------------------------------------------------------------------------


def _format_for(text: str, filename: str | None, declared_format: str | None) -> str:
    if declared_format is not None:
        fmt = _FORMAT_ALIASES.get(declared_format.strip().lstrip(".").lower())
        if fmt is None:
            raise TranscriptError("UNSUPPORTED_FORMAT", f"declared format {declared_format!r} is not one of {FORMATS}")
        return fmt
    if filename:
        suffix = PurePath(filename).suffix.lstrip(".").lower()
        if suffix:
            fmt = _FORMAT_ALIASES.get(suffix)
            if fmt is None:
                raise TranscriptError("UNSUPPORTED_FORMAT", f"file extension .{suffix} is not one of {FORMATS}")
            return fmt
    head = text[:_SNIFF_CHARS]
    if head.lstrip().startswith("WEBVTT"):
        return "vtt"
    if _SRT_SNIFF.search(head):
        return "srt"
    return "txt"


def _clean_line(line: str) -> str:
    """Drop control characters (keeping tabs) and trailing whitespace."""
    line = "".join(ch for ch in line if ch == "\t" or unicodedata.category(ch) != "Cc")
    return line.rstrip()


def _normalize(text: str) -> str:
    """NFC, LF line endings, no trailing spaces, at most one blank line in a row, trimmed."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for line in text.split("\n"):
        line = _clean_line(line)
        if not line.strip():
            if out and out[-1] != "":
                out.append("")
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _text_sha256(text: str) -> str:
    return hashlib.sha256(_collapse(text.casefold()).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------
# Format parsers -> segments
# --------------------------------------------------------------------------------------------

Segment = tuple[str | None, str | None, str]


def _cue_time(raw: str) -> str:
    """``00:01:02,500`` / ``01:02.5`` -> ``HH:MM:SS.mmm``."""
    raw = raw.replace(",", ".")
    clock, _, frac = raw.partition(".")
    parts = clock.split(":")
    while len(parts) < 3:
        parts.insert(0, "0")
    hours, minutes, seconds = (int(p) for p in parts[-3:])
    millis = int((frac + "000")[:3]) if frac else 0
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _merge_cues(cues: list[Segment]) -> list[Segment]:
    """Join a cue to the previous one when the speaker is the same and no sentence ended."""
    merged: list[Segment] = []
    for timestamp, speaker, text in cues:
        if merged:
            prev_ts, prev_speaker, prev_text = merged[-1]
            if prev_speaker == speaker and not _SENTENCE_END.search(prev_text):
                merged[-1] = (prev_ts, prev_speaker, f"{prev_text} {text}")
                continue
        merged.append((timestamp, speaker, text))
    return merged


def _cue_segments(text: str, fmt: str) -> list[Segment]:
    """SRT/VTT: drop numbers, timings, header/NOTE/STYLE/REGION blocks and markup."""
    cues: list[Segment] = []
    for index, block in enumerate(re.split(r"\n\s*\n", text)):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        first = lines[0].strip()
        if fmt == "vtt":
            is_header = index == 0 and first.startswith("WEBVTT")
            if is_header or first.split()[0] in ("NOTE", "STYLE", "REGION"):
                continue
        timestamp: str | None = None
        body: list[str] = []
        for line in lines:
            timing = _TIMING.match(line)
            if timing or "-->" in line:
                timestamp = _cue_time(timing.group(1)) if timing else None
                body = []  # anything before the timing line is a cue number or identifier
                continue
            body.append(line)
        if not body:
            continue
        speaker: str | None = None
        joined = " ".join(line.strip() for line in body)
        voice = _VOICE.search(joined)
        if voice:
            speaker = _collapse(html.unescape(voice.group(1))) or None
        joined = _CUE_TIMESTAMP.sub(" ", joined)
        joined = _collapse(html.unescape(_CUE_TAG.sub("", joined)))
        if speaker is None:
            match = _SPEAKER.match(joined)
            if match:
                speaker, joined = match.group(1), match.group(2)
        if joined:
            cues.append((timestamp, speaker, joined))
    return _merge_cues(cues)


def _strip_markdown_line(line: str) -> tuple[str, bool]:
    """One markdown line -> (plain text, is_heading)."""
    heading = _MD_HEADING.match(line)
    if heading:
        line = heading.group(1)
    line = _MD_QUOTE.sub("", line)
    line = _MD_LINK.sub(r"\1", line)
    line = _MD_BOLD.sub(r"\2", line)
    line = _MD_ITALIC.sub(lambda m: m.group(1) or m.group(2), line)
    return line, heading is not None


def _prose_segments(text: str, *, markdown: bool) -> tuple[str, list[Segment]]:
    """txt/md: a leading timestamp and ``Speaker Name:`` start a new segment.

    Returns the text (markdown markers and leading line timestamps removed) and the segments.
    A speaker carries over blank lines until the next speaker prefix or markdown heading; each
    paragraph is its own segment, and a heading is a segment without a speaker.
    """
    lines_out: list[str] = []
    segments: list[Segment] = []
    current: list[str] = []
    seg_ts: str | None = None
    speaker: str | None = None

    def flush() -> None:
        nonlocal current, seg_ts
        if current:
            segments.append((seg_ts, speaker, " ".join(current)))
        current, seg_ts = [], None

    for line in text.split("\n"):
        if not line.strip():
            flush()
            lines_out.append("")
            continue
        if markdown:
            line, is_heading = _strip_markdown_line(line)
            if is_heading:
                flush()
                speaker = None
                if line.strip():
                    segments.append((None, None, _collapse(line)))
                lines_out.append(line)
                continue
        line_ts: str | None = None
        time_match = _LINE_TIME.match(line)
        if time_match:
            line_ts = time_match.group(1)
            line = line[time_match.end():]
        match = _SPEAKER.match(line.strip())
        if match:
            flush()
            speaker = match.group(1)
            seg_ts = line_ts
            current.append(_collapse(match.group(2)))
        else:
            if not current:
                seg_ts = line_ts
            current.append(_collapse(line))
        lines_out.append(line)
    flush()
    return "\n".join(lines_out), segments


def parse_transcript(data: bytes, *, filename: str | None = None, declared_format: str | None = None,
                     max_bytes: int = MAX_TRANSCRIPT_BYTES) -> Transcript:
    """Decode, validate and normalize one transcript. Raises `TranscriptError` on refusal."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TranscriptError("BINARY", "transcript must be bytes")
    data = bytes(data)
    if len(data) > max_bytes:
        raise TranscriptError("TOO_LARGE", f"{len(data)} bytes exceeds the {max_bytes}-byte cap")
    if data.startswith(_BOM):
        data = data[len(_BOM):]
    if b"\x00" in data:
        raise TranscriptError("BINARY", "NUL bytes: this is not a text transcript")
    try:
        raw = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise TranscriptError("NOT_UTF8", f"invalid UTF-8 at byte {exc.start}") from None
    if not raw.strip():
        raise TranscriptError("EMPTY", "the transcript is empty")

    normalized = _normalize(raw)
    fmt = _format_for(normalized, filename, declared_format)
    if fmt in ("srt", "vtt"):
        segments = _cue_segments(normalized, fmt)
        text = "\n".join(f"{speaker}: {body}" if speaker else body for _, speaker, body in segments)
    else:
        text, segments = _prose_segments(normalized, markdown=fmt == "md")
        text = _normalize(text)
    if not text.strip():
        raise TranscriptError("EMPTY", f"no transcript text after parsing the {fmt} cues")
    return Transcript(text=text, text_sha256=_text_sha256(text), format=fmt, segments=tuple(segments))


# --------------------------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------------------------


def _meta_str(raw: dict, key: str, *, required: bool) -> str | None:
    value = raw.get(key)
    if value is None:
        if required:
            raise TranscriptError("BAD_META", f"{key} is required")
        return None
    if not isinstance(value, str):
        raise TranscriptError("BAD_META", f"{key} must be text")
    if any(unicodedata.category(ch) == "Cc" and ch not in "\n\t" for ch in value):
        raise TranscriptError("BAD_META", f"{key} contains control characters")
    value = unicodedata.normalize("NFC", value).strip()
    if not value:
        if required:
            raise TranscriptError("BAD_META", f"{key} is required")
        return None
    limit = _META_LIMITS[key]
    if len(value) > limit:
        raise TranscriptError("BAD_META", f"{key} is longer than {limit} characters")
    return value


def validate_meta(raw: dict, *, today: date | None = None) -> TranscriptMeta:
    """Validate the owner's transcript metadata block. Raises ``TranscriptError("BAD_META")``.

    Required: podcast, episode (<= 200 chars), transcript_source (<= 120). Optional:
    published_date (YYYY-MM-DD; when `today` is given, at most one day after it), episode_url
    (http/https only) and notes (<= 4000). Unknown keys are refused.
    """
    if not isinstance(raw, dict):
        raise TranscriptError("BAD_META", "metadata must be an object")
    unknown = sorted(str(key) for key in raw if key not in _META_KEYS)
    if unknown:
        raise TranscriptError("BAD_META", f"unknown field(s): {', '.join(unknown)}")
    podcast = _meta_str(raw, "podcast", required=True)
    episode = _meta_str(raw, "episode", required=True)
    source = _meta_str(raw, "transcript_source", required=True)
    notes = _meta_str(raw, "notes", required=False)
    published = _meta_str(raw, "published_date", required=False)
    if published is not None:
        try:
            if not _ISO_DATE.match(published):
                raise ValueError(published)
            day = date.fromisoformat(published)
        except ValueError:
            raise TranscriptError("BAD_META", "published_date must be a real date written YYYY-MM-DD") from None
        if today is not None and day > today + timedelta(days=1):
            raise TranscriptError("BAD_META", f"published_date {published} is in the future")
    url = _meta_str(raw, "episode_url", required=False)
    if url is not None and canonical_url(url) is None:
        raise TranscriptError("BAD_META", "episode_url must be an http(s) URL")
    return TranscriptMeta(podcast=podcast, episode=episode, published_date=published, episode_url=url,
                          transcript_source=source, notes=notes)


def episode_key(meta: TranscriptMeta) -> str:
    """sha256 of the casefolded, whitespace-collapsed podcast and episode (duplicate detection)."""
    def norm(value: str) -> str:
        return _collapse(unicodedata.normalize("NFC", value).casefold())

    return hashlib.sha256((norm(meta.podcast) + "\x00" + norm(meta.episode)).encode("utf-8")).hexdigest()
