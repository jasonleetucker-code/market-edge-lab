"""Event-centred research records (#192, ADR 0049): pure and deterministic.

A development in the news is not an outcome. This module turns evidence (news items and
transcript claims) into candidate *events* keyed by (topic, key entity). Each event carries
distinct, objectively resolvable *outcomes* from a versioned template. A story about an
impeachment investigation is evidence about the event, never proof that any outcome happened.

Independence: corroboration counts distinct origin families. Aggregator copies count under
the outlet that wrote the story, and podcasts and commentary never corroborate anything, so three
podcasts repeating one report are one origin at most and verify nothing.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .contracts import (
    ClaimType,
    EventStatus,
    EvidenceType,
    Topic,
    Verification,
)
from .extract import keywords

EVENTS_VERSION = "intel-events-v1"

# Topics with a template. Order matters only for display.
OUTCOME_TEMPLATES: dict[Topic, tuple[tuple[str, str, str], ...]] = {
    # (outcome slug, outcome text with {e}, resolution condition)
    Topic.IMPEACHMENT: (
        ("hearing", "A congressional committee holds an impeachment-related hearing on {e}",
         "An official committee hearing record (congress.gov or the committee's site) shows the hearing took place."),
        ("resolution_introduced", "An impeachment resolution naming {e} is formally introduced",
         "Congress.gov lists an introduced H.Res. with articles of impeachment naming the official."),
        ("house_vote", "The full House votes on an impeachment resolution naming {e}",
         "A House roll-call vote (clerk.house.gov) on the resolution or a motion to table it."),
        ("impeached", "The House impeaches {e}",
         "The House adopts at least one article of impeachment (House roll call / Congressional Record)."),
        ("leaves_office", "{e} resigns or otherwise leaves office",
         "An official announcement or record that the official left the office."),
    ),
    Topic.PERSONNEL: (
        ("leaves_office", "{e} leaves their current office",
         "An official announcement, resignation letter or record of departure."),
        ("successor_nominated", "A successor to {e} is formally nominated",
         "A nomination received by the Senate (congress.gov nominations) or an official announcement."),
        ("confirmed", "The Senate confirms the nomination involving {e}",
         "A Senate confirmation vote recorded on congress.gov / senate.gov."),
    ),
    Topic.LEGISLATION: (
        ("passes_house", "The House passes the measure involving {e}",
         "A recorded House passage (clerk.house.gov roll call or congress.gov actions)."),
        ("passes_senate", "The Senate passes the measure involving {e}",
         "A recorded Senate passage (senate.gov roll call or congress.gov actions)."),
        ("enacted", "The measure involving {e} is signed into law",
         "Congress.gov shows 'Became Public Law' / a Federal Register or GovInfo public-law record."),
    ),
    Topic.SHUTDOWN_BUDGET: (
        ("shutdown_begins", "A federal funding lapse (shutdown) begins",
         "OMB/agency shutdown notices or an official lapse in appropriations."),
        ("funding_enacted", "Funding legislation is enacted before the lapse deadline",
         "Congress.gov shows the appropriations/CR bill became law before the deadline."),
    ),
    Topic.FED: (
        ("rate_cut", "The FOMC lowers the federal funds target range at its next meeting",
         "The FOMC statement on federalreserve.gov."),
        ("rate_hold", "The FOMC leaves the target range unchanged at its next meeting",
         "The FOMC statement on federalreserve.gov."),
        ("rate_hike", "The FOMC raises the target range at its next meeting",
         "The FOMC statement on federalreserve.gov."),
    ),
    Topic.MACRO_DATA: (
        ("release_published", "The next official release of {e} is published on schedule",
         "The issuing agency's release (BLS/BEA) at its scheduled time."),
    ),
    Topic.TRADE: (
        ("tariff_in_effect", "New tariffs involving {e} take legal effect",
         "A Federal Register notice or official proclamation with an effective date."),
        ("deal_signed", "A trade agreement involving {e} is signed",
         "An official signing announcement by a party government."),
    ),
    Topic.COURTS: (
        ("charged", "Charges are formally filed involving {e}",
         "A court docket or official DOJ/prosecutor announcement."),
        ("ruling_issued", "A court issues the pending ruling involving {e}",
         "The court's published opinion or order."),
    ),
    Topic.ELECTIONS: (
        ("wins", "{e} wins the contest in question",
         "Certified results from the responsible election authority."),
        ("withdraws", "{e} withdraws from the race",
         "An official campaign statement or ballot-withdrawal filing."),
    ),
    Topic.EARNINGS: (
        ("reports", "{e} publishes its scheduled results",
         "The company's filing on SEC EDGAR (8-K/10-Q/10-K) or its official release."),
    ),
    Topic.GEOPOLITICS: (
        ("ceasefire", "A ceasefire or agreement involving {e} is formally announced",
         "Official statements by the parties or the mediating government."),
        ("talks_held", "Formal talks involving {e} take place",
         "Official statements by a participating government."),
    ),
}

GENERIC_ENTITIES = frozenset({
    "house", "senate", "congress", "white house", "president", "government", "administration", "u.s.", "us",
    "united states", "america", "american", "washington", "republicans", "democrats", "republican",
    "democrat", "gop", "court", "supreme court", "fed", "federal reserve", "news", "reuters", "ap",
    "associated press", "bbc", "cnn", "fox", "nbc", "cbs", "abc", "npr", "pbs", "politico", "the hill",
    "breaking", "live", "update", "updates", "watch", "video", "opinion", "analysis", "report",
})

# A topic whose events are about the institution itself (one event, no entity needed).
INSTITUTIONAL = {Topic.FED: "Federal Reserve", Topic.SHUTDOWN_BUDGET: "Federal funding"}


@dataclass(frozen=True)
class Evidence:
    """One piece of evidence reduced to what corroboration needs."""

    evidence_id: str  # stable id, e.g. "item:<item_key>" or "claim:<transcript>:<n>"
    kind: str  # "news" | "transcript_claim"
    source_id: str
    origin: str  # origin family (aggregator copies carry their outlet's family)
    evidence_type: EvidenceType
    title: str  # headline or claim text
    text: str  # snippet or claim text (may equal title)
    observed_utc: str | None  # publication time, else first-seen time
    topics: tuple[Topic, ...]
    entities: tuple[str, ...]
    claim_type: ClaimType | None = None  # for transcript claims
    link: str | None = None


@dataclass(frozen=True)
class Outcome:
    outcome_id: str  # "<event_id>:<slug>"
    slug: str
    text: str
    resolution_condition: str
    deadline_utc: str | None = None  # unknown until a confirmed market's rules set it


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    topic: Topic
    key_entity: str
    title: str
    outcomes: tuple[Outcome, ...]
    evidence_ids: tuple[str, ...]
    origins: tuple[str, ...]  # independent origin families among news/primary evidence
    primary_sources: tuple[str, ...]  # source ids of PRIMARY evidence
    first_evidence_utc: str | None
    last_evidence_utc: str | None
    verification: Verification
    contradictions: tuple[tuple[str, str], ...] = ()  # (evidence_id, evidence_id) pairs
    unconfirmed_claims: tuple[str, ...] = ()  # transcript claim evidence ids without corroboration
    version: str = EVENTS_VERSION


def _norm(entity: str) -> str:
    return re.sub(r"\s+", " ", entity.strip().casefold())


def event_id_for(topic: Topic, key_entity: str) -> str:
    digest = hashlib.sha256(f"{EVENTS_VERSION}\x00{topic.value}\x00{_norm(key_entity)}".encode()).hexdigest()
    return f"ev-{topic.value.lower()}-{digest[:12]}"


HONORIFICS = re.compile(
    r"^(?:(?:former|acting|then|vice)\s+)*(?:secretary|sen\.?|senator|rep\.?|representative|president|gov\.?|"
    r"governor|judge|justice|chairman|chairwoman|chair|speaker|minister|prime minister|mayor|attorney general|"
    r"ag|mr\.?|ms\.?|mrs\.?|dr\.?|director|commissioner|general|leader)\s+", re.I)
INSTITUTION_WORDS = frozenset({
    "house", "senate", "congress", "democrats", "republicans", "democratic", "republican", "committee",
    "department", "court", "administration", "party", "office", "agency", "commission", "bureau", "council",
    "caucus", "lawmakers", "officials", "white", "capitol", "states", "united", "federal", "national", "news",
    "times", "post", "journal", "press", "reuters", "res", "bill", "act",
})


def subject_name(entity: str) -> str:
    """An entity without leading titles ("Secretary Jane Doe" -> "Jane Doe")."""
    prev = None
    name = entity.strip()
    while prev != name:
        prev, name = name, HONORIFICS.sub("", name).strip()
    return name


def key_entity_of(ev: Evidence, topic: Topic) -> str | None:
    """The entity an event about `topic` is keyed on, or None when none is specific enough.

    Prefers a named subject (titles stripped) over institutions: "House Democrats file articles
    against Secretary Jane Doe" is keyed on "Jane Doe".
    """
    if topic in INSTITUTIONAL:
        return INSTITUTIONAL[topic]
    fallback = None
    for entity in ev.entities:
        name = subject_name(entity)
        n = _norm(name)
        if n in GENERIC_ENTITIES or len(n) < 4 or (name.isupper() and len(name) <= 4):
            continue
        words = set(n.replace(".", " ").split())
        if words & INSTITUTION_WORDS:
            if fallback is None and topic in (Topic.LEGISLATION, Topic.EARNINGS, Topic.GEOPOLITICS, Topic.TRADE,
                                              Topic.COURTS):
                fallback = name
            continue
        return name
    return fallback


def outcomes_for(event_id: str, topic: Topic, key_entity: str) -> tuple[Outcome, ...]:
    return tuple(
        Outcome(outcome_id=f"{event_id}:{slug}", slug=slug, text=text.format(e=key_entity), resolution_condition=rc)
        for slug, text, rc in OUTCOME_TEMPLATES.get(topic, ())
    )


_NEGATION = re.compile(r"\b(not|no|denies|denied|deny|rejects?|rejected|false|won't|will not|did not|didn't|"
                       r"never|refutes?|refuted|dismissed)\b", re.I)


def _contradicts(a: Evidence, b: Evidence) -> bool:
    """Crude, deterministic contradiction screen: same subject, opposite polarity.

    Two items about the same event whose keyword overlap is high but where exactly one carries
    a denial/negation marker are flagged for the owner. It is a flag, never a verdict.
    """
    if a.origin == b.origin:
        return False
    ka, kb = keywords(a.title + " " + a.text), keywords(b.title + " " + b.text)
    if not ka or not kb:
        return False
    overlap = len(ka & kb) / max(1, min(len(ka), len(kb)))
    if overlap < 0.5:
        return False
    return bool(_NEGATION.search(a.title + " " + a.text)) != bool(_NEGATION.search(b.title + " " + b.text))


def _verification(origins: set[str], primary: set[str], contradictions: list) -> Verification:
    if contradictions:
        return Verification.CONTRADICTED
    if primary:
        return Verification.CONFIRMED_PRIMARY
    if len(origins) >= 2:
        return Verification.CORROBORATED
    if len(origins) == 1:
        return Verification.SINGLE_SOURCE
    return Verification.UNVERIFIED


def build_events(evidence: list[Evidence] | tuple[Evidence, ...], *, max_events: int = 200) -> tuple[EventRecord, ...]:
    """Group evidence into events by (topic, key entity). Deterministic for the same input.

    Only news/primary evidence counts toward origins. Transcript claims attach to an event
    when they share its key entity, and they stay unconfirmed unless news corroborates them.
    """
    groups: dict[str, dict] = {}
    for ev in sorted(evidence, key=lambda e: (e.observed_utc or "", e.evidence_id)):
        for topic in ev.topics:
            if topic not in OUTCOME_TEMPLATES:
                continue
            entity = key_entity_of(ev, topic)
            if entity is None:
                continue
            eid = event_id_for(topic, entity)
            g = groups.setdefault(eid, {"topic": topic, "entity": entity, "items": []})
            g["items"].append(ev)

    records: list[EventRecord] = []
    for eid, g in groups.items():
        items: list[Evidence] = g["items"]
        news = [e for e in items if e.kind == "news"]
        if not news:
            continue  # a transcript alone never creates an event: it is an input, not a signal
        origins = {e.origin for e in news if e.evidence_type is not EvidenceType.COMMENTARY}
        primary = {e.source_id for e in news if e.evidence_type is EvidenceType.PRIMARY}
        contradictions: list[tuple[str, str]] = []
        for i, a in enumerate(news):
            for b in news[i + 1:]:
                if _contradicts(a, b):
                    contradictions.append((a.evidence_id, b.evidence_id))
        claims = [e for e in items if e.kind == "transcript_claim"]
        unconfirmed = tuple(c.evidence_id for c in claims if claim_verification(c, news) in
                            (Verification.UNVERIFIED, Verification.SINGLE_SOURCE))
        times = sorted(t for t in (e.observed_utc for e in items) if t)
        topic: Topic = g["topic"]
        entity: str = g["entity"]
        records.append(EventRecord(
            event_id=eid,
            topic=topic,
            key_entity=entity,
            title=f"{topic.value.replace('_', ' ').title()}: {entity}",
            outcomes=outcomes_for(eid, topic, entity),
            evidence_ids=tuple(e.evidence_id for e in items),
            origins=tuple(sorted(origins)),
            primary_sources=tuple(sorted(primary)),
            first_evidence_utc=times[0] if times else None,
            last_evidence_utc=times[-1] if times else None,
            verification=_verification(origins, primary, contradictions[:20]),
            contradictions=tuple(contradictions[:20]),
            unconfirmed_claims=unconfirmed,
        ))
    records.sort(key=lambda r: (-len(r.origins), -len(r.evidence_ids), r.last_evidence_utc or "", r.event_id))
    return tuple(records[:max_events])


def claim_verification(claim: Evidence, news: list[Evidence] | tuple[Evidence, ...], *, min_overlap: float = 0.4
                       ) -> Verification:
    """How independent news supports one transcript claim (a deterministic keyword match).

    A claim is CORROBORATED only by >= 2 independent non-commentary origins, CONFIRMED_PRIMARY
    by a primary source, SINGLE_SOURCE by one; podcasts never count. Opinion and speculation
    stay UNVERIFIED whatever matches, because they are not factual claims.
    """
    if claim.claim_type in (ClaimType.OPINION, ClaimType.SPECULATION):
        return Verification.UNVERIFIED
    kc = keywords(claim.text)
    if not kc:
        return Verification.UNVERIFIED
    origins: set[str] = set()
    primary = False
    for n in news:
        if n.evidence_type is EvidenceType.COMMENTARY:
            continue
        kn = keywords(n.title + " " + n.text)
        if not kn:
            continue
        if len(kc & kn) / max(1, min(len(kc), len(kn))) >= min_overlap and len(kc & kn) >= 2:
            origins.add(n.origin)
            primary = primary or n.evidence_type is EvidenceType.PRIMARY
    if primary:
        return Verification.CONFIRMED_PRIMARY
    if len(origins) >= 2:
        return Verification.CORROBORATED
    if len(origins) == 1:
        return Verification.SINGLE_SOURCE
    return Verification.UNVERIFIED


def is_new_information(claim: Evidence, news: list[Evidence] | tuple[Evidence, ...]) -> bool:
    """True when no collected news item shares the claim's substance (nothing to cross-check yet)."""
    return claim_verification(claim, news, min_overlap=0.3) is Verification.UNVERIFIED and \
        claim.claim_type not in (ClaimType.OPINION, ClaimType.SPECULATION)


@dataclass(frozen=True)
class StatusFacts:
    verification: Verification
    has_resolution: bool = False
    has_active_forecast: bool = False  # a non-superseded, non-abstaining forecast for an outcome
    has_packet: bool = False  # a research packet was generated
    has_confirmed_link: bool = False
    stale: bool = False  # no new evidence within the monitoring window
    evidence_count: int = 0  # evidence items attached so far
    reasons: tuple[str, ...] = field(default_factory=tuple)


def derive_status(facts: StatusFacts) -> tuple[EventStatus, str]:
    """The event status and its plain-English reason. Deterministic precedence:

    RESOLVED > FORECAST_READY > RESEARCHING > NEW (one item) > NEEDS_EVIDENCE > MONITOR > VERIFIED.
    FORECAST_READY needs verified evidence and an active forecast; nothing is made ready by
    a forecast on single-source or contradicted evidence.
    """
    verified = facts.verification in (Verification.CONFIRMED_PRIMARY, Verification.CORROBORATED)
    if facts.has_resolution:
        return EventStatus.RESOLVED, "An outcome has a recorded resolution."
    if verified and facts.has_active_forecast:
        return EventStatus.FORECAST_READY, "Verified evidence and an imported forecast exist."
    if facts.has_packet and not facts.has_active_forecast:
        return EventStatus.RESEARCHING, "A research packet was generated; no analysis imported yet."
    if facts.evidence_count <= 1 and not facts.has_active_forecast:
        return EventStatus.NEW, "First report seen; not yet cross-checked."
    if facts.verification in (Verification.SINGLE_SOURCE, Verification.UNVERIFIED, Verification.CONTRADICTED):
        why = {Verification.SINGLE_SOURCE: "Only one independent origin reports it.",
               Verification.UNVERIFIED: "No independent reporting matches it.",
               Verification.CONTRADICTED: "Independent sources disagree."}[facts.verification]
        if facts.has_active_forecast:
            why += " The forecast cannot be ready until the evidence is verified."
        return EventStatus.NEEDS_EVIDENCE, why
    if facts.stale:
        return EventStatus.MONITOR, "Verified, but no new evidence recently."
    return EventStatus.VERIFIED, "Corroborated by independent or primary sources; no forecast yet."
