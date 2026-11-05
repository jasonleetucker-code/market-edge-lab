"""Shared vocabulary for the intel package (#192, ADR 0049).

Every value here is data: statuses, labels, caps and small frozen records. Nothing in this
module fetches, writes or decides money. Unknown stays None; it is never coerced to zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

INTEL_VERSION = "1"


class AccessStatus(str, Enum):
    """What we may do with a candidate source, after verification (never assumed)."""

    ACTIVE = "ACTIVE"  # verified feed/API, collected
    LIMITED = "LIMITED"  # verified, but only discovery or partial metadata (e.g. aggregator, headlines)
    UNAVAILABLE = "UNAVAILABLE"  # no usable free machine-readable channel found
    BLOCKED = "BLOCKED"  # access refused, needs a credential, or terms forbid automated use
    UNVERIFIED = "UNVERIFIED"  # not yet checked: never collected


COLLECTABLE = frozenset({AccessStatus.ACTIVE, AccessStatus.LIMITED})


class Rights(str, Enum):
    """What may be stored from a source (headline/snippet unless rights are clear)."""

    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"  # US-government works: raw bytes may be retained
    HEADLINE_SNIPPET = "HEADLINE_SNIPPET"  # headline, link, timestamps, <=300-char snippet only
    AGGREGATOR_DISCOVERY_ONLY = "AGGREGATOR_DISCOVERY_ONLY"  # headline, link and named outlet only


class EvidenceType(str, Enum):
    """Directive evidence-quality order (a category, not an accuracy guarantee)."""

    PRIMARY = "PRIMARY"  # official records and primary documents
    REPORTING = "REPORTING"  # credible independent reporting
    DATA = "DATA"  # reliable numerical data
    FORECAST = "FORECAST"  # methodologically transparent polling/forecasts
    ANALYSIS = "ANALYSIS"  # expert analysis
    COMMENTARY = "COMMENTARY"  # opinion, commentary, podcasts


EVIDENCE_RANK = {kind: i for i, kind in enumerate(EvidenceType)}


class Category(str, Enum):
    GENERAL = "GENERAL"
    POLITICS = "POLITICS"
    FINANCE = "FINANCE"
    PRIMARY = "PRIMARY"


class Topic(str, Enum):
    """Development topics recognized by the deterministic taxonomy (extract.py)."""

    IMPEACHMENT = "IMPEACHMENT"
    PERSONNEL = "PERSONNEL"  # resignations, departures, nominations, confirmations
    LEGISLATION = "LEGISLATION"  # bills and votes
    SHUTDOWN_BUDGET = "SHUTDOWN_BUDGET"
    FED = "FED"
    MACRO_DATA = "MACRO_DATA"  # inflation, jobs, GDP releases
    TRADE = "TRADE"  # tariffs, trade policy
    COURTS = "COURTS"  # investigations, indictments, rulings
    ELECTIONS = "ELECTIONS"  # elections, polls, candidates
    EARNINGS = "EARNINGS"  # corporate results, filings
    GEOPOLITICS = "GEOPOLITICS"  # conflicts, negotiations, sanctions


class ClaimType(str, Enum):
    REPORTED = "REPORTED"  # attributed report of something that happened
    PREDICTION = "PREDICTION"  # a statement about the future
    OPINION = "OPINION"  # judgment, commentary
    SPECULATION = "SPECULATION"  # rumour, hedged or unsourced


class Verification(str, Enum):
    CONFIRMED_PRIMARY = "CONFIRMED_PRIMARY"  # a primary/official source states it
    CORROBORATED = "CORROBORATED"  # >= 2 independent origin families report it
    SINGLE_SOURCE = "SINGLE_SOURCE"  # one origin family only
    UNVERIFIED = "UNVERIFIED"  # podcast/commentary only, or no match
    CONTRADICTED = "CONTRADICTED"  # independent sources disagree


class EventStatus(str, Enum):
    NEW = "NEW"
    RESEARCHING = "RESEARCHING"
    VERIFIED = "VERIFIED"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    FORECAST_READY = "FORECAST_READY"
    MONITOR = "MONITOR"
    RESOLVED = "RESOLVED"


class Action(str, Enum):
    """The only actions this lane can show. There is deliberately no BUY."""

    INVESTIGATE = "INVESTIGATE"
    WATCH = "WATCH"
    SKIP = "SKIP"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


INSUFFICIENT_EVIDENCE_TEXT = "INSUFFICIENT EVIDENCE — NO RELIABLE EDGE ESTIMATE"


class ForecastBasis(str, Enum):
    OWNER_JUDGMENT = "OWNER_JUDGMENT"  # the owner's own subjective range
    AI_ASSISTED_UNVALIDATED = "AI_ASSISTED_UNVALIDATED"  # imported from an assistant via the bridge
    BASE_RATE = "BASE_RATE"  # historical analogues with a stated count
    MODEL = "MODEL"  # a versioned quantitative model


class PriceAwareness(str, Enum):
    PRICE_BLIND = "PRICE_BLIND"  # recorded before any linked quote existed
    PRICE_AWARE = "PRICE_AWARE"  # a linked quote existed when it was recorded
    UNKNOWN = "UNKNOWN"


class LinkStatus(str, Enum):
    CANDIDATE = "CANDIDATE"  # title/keyword match only: never priced
    CONFIRMED = "CONFIRMED"  # the owner confirmed after reading the captured rules
    REJECTED = "REJECTED"


class InboxKind(str, Enum):
    TRANSCRIPT = "transcript"
    ANALYSIS = "analysis"  # assistant analysis or owner judgment (market-edge-intel-analysis/1)
    REFRESH = "refresh"  # refresh request: news, quotes or market discovery
    LINK = "link"  # the owner's decision on a candidate market (confirm/reject, with attestations)
    PACKET = "packet"  # prepare (record) the research packet for one event


class RefreshScope(str, Enum):
    NEWS = "news"
    QUOTES = "quotes"
    DISCOVER = "discover"


# Caps (bytes / characters). Changing one is a versioned change.
MAX_FEED_BYTES = 4 * 1024 * 1024
MAX_TRANSCRIPT_BYTES = 1_500_000
MAX_ANALYSIS_BYTES = 256 * 1024
MAX_INBOX_FILE_BYTES = 1_600_000
MAX_INBOX_PENDING = 20
SNIPPET_CHARS = 300
TITLE_CHARS = 300
MAX_FEED_GETS_PER_RUN = 60
MAX_KALSHI_GETS_PER_RUN = 120
VERIFICATION_VALID_DAYS = 14


@dataclass(frozen=True)
class FeedItem:
    """One parsed feed entry, already reduced to what the rights allow."""

    source_id: str
    item_key: str  # sha256(source_id, guid or canonical url)
    guid: str | None
    title: str
    link: str | None
    canonical_url: str | None
    snippet: str | None  # <= SNIPPET_CHARS, HTML stripped
    published_utc: str | None  # as stated by the feed, normalized; None when absent/unparseable
    updated_utc: str | None
    published_raw: str | None  # the feed's own text, kept for audit
    cluster_key: str  # syndication/duplicate grouping
    origin: str  # origin family: the outlet that originally reported (e.g. "reuters", "ap")
    via_aggregator: bool = False  # discovered through an aggregator (e.g. Google News)
    content_sha256: str = ""  # sha256 of (title, snippet, link): a change makes a new version


@dataclass(frozen=True)
class ParseResult:
    ok: bool
    items: tuple[FeedItem, ...] = ()
    error: str | None = None  # machine code, e.g. "DOCTYPE_REFUSED", "MALFORMED_XML", "TOO_LARGE"
    feed_title: str | None = None


@dataclass(frozen=True)
class Sentence:
    index: int
    text: str
    claim_type: ClaimType
    topics: tuple[Topic, ...]
    entities: tuple[str, ...]
    speaker: str | None = None
    timestamp: str | None = None  # cue start for srt/vtt


@dataclass(frozen=True)
class Transcript:
    """A parsed, normalized transcript (text only; metadata travels separately)."""

    text: str  # normalized UTF-8 text, cues and timestamps removed
    text_sha256: str
    format: str  # "txt" | "md" | "srt" | "vtt"
    segments: tuple[tuple[str | None, str | None, str], ...]  # (timestamp, speaker, text)


@dataclass(frozen=True)
class TranscriptMeta:
    podcast: str
    episode: str
    published_date: str | None  # YYYY-MM-DD or None
    episode_url: str | None
    transcript_source: str  # e.g. "owner paste", "ChatGPT cleanup", "publisher"
    notes: str | None = None


@dataclass(frozen=True)
class Extraction:
    extractor_version: str
    topics: tuple[Topic, ...]
    entities: tuple[str, ...]
    sentences: tuple[Sentence, ...] = field(default_factory=tuple)
