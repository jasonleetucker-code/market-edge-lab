"""Versioned deterministic taxonomy: topics, entities, claim types, keywords (#192, ADR 0049).

This is a heuristic, not understanding. Topics come from keyword rules, entities from
capitalized n-grams and acronyms, claim types from marker phrases. Every rule is module-level
data so ``EXTRACTOR_VERSION`` names one auditable rule set; changing any rule is a new version.
No model is called and nothing here decides money.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from edge_lab.intel.contracts import ClaimType, Extraction, Sentence, Topic

__all__ = [
    "CLAIM_MARKERS",
    "EXTRACTOR_VERSION",
    "MAX_ENTITIES",
    "MAX_SENTENCES",
    "SENTENCE_CHARS",
    "TOPIC_RULES",
    "classify_sentence",
    "entities_of",
    "extract",
    "keywords",
    "split_sentences",
    "topics_of",
]

EXTRACTOR_VERSION = "intel-extract-v1"
MAX_SENTENCES = 2000
MAX_ENTITIES = 50
SENTENCE_CHARS = 600

# --------------------------------------------------------------------------------------------
# Rule data (the auditable part of the version). Patterns are case-insensitive and wrapped in
# word boundaries; ``(?-i:...)`` marks the parts that must match case exactly.
# --------------------------------------------------------------------------------------------

_NOT_A_NAME = r"(?!\s+(?-i:[A-Z]))"  # "bill" but not "Bill Gates"

TOPIC_RULES: tuple[tuple[Topic, tuple[str, ...]], ...] = (
    (Topic.IMPEACHMENT, (r"impeach\w*", r"articles of impeachment")),
    (Topic.PERSONNEL, (
        r"resign\w*", r"step(?:s|ped|ping)? down", r"nominat\w*", r"confirm(?:ed|ation) hearings?",
        r"fired", r"ouster", r"ousted", r"appointed", r"cabinet secretary",
    )),
    (Topic.LEGISLATION, (
        rf"bills?{_NOT_A_NAME}", r"House vot(?:e|es|ed|ing)", r"Senate vot(?:e|es|ed|ing)",
        r"passed the (?:House|Senate)", r"cloture", r"filibuster\w*", r"legislation", r"resolution",
    )),
    (Topic.SHUTDOWN_BUDGET, (
        r"shutdown", r"continuing resolution", r"appropriations?", r"debt ceiling", r"debt limit",
        r"budget deal",
    )),
    (Topic.FED, (
        r"Federal Reserve", r"the (?-i:Fed)", r"(?-i:FOMC)", r"rate (?:cut|hike)s?", r"interest rates?",
        r"Powell", r"(?-i:Fed) chair\w*",
    )),
    (Topic.MACRO_DATA, (
        r"(?-i:CPI)", r"consumer price index", r"inflation", r"jobs report", r"(?:nonfarm )?payrolls",
        r"unemployment rate", r"(?-i:GDP)", r"(?-i:PCE)", r"jobless claims",
    )),
    (Topic.TRADE, (r"tariffs?", r"trade deal", r"trade war", r"trade agreement", r"export controls")),
    (Topic.COURTS, (
        r"indict\w*", r"Supreme Court", r"ruling", r"judges?", r"lawsuits?", r"appeals court",
        r"investigations?", r"subpoena\w*", r"special counsel", r"grand jury",
    )),
    (Topic.ELECTIONS, (
        r"elections?", r"poll(?:s|ing|ed|ster|sters)?", r"primary", r"primaries", r"candidates?",
        r"ballots?", r"campaign\w*", r"midterms?", r"runoffs?",
        r"withdr(?:aw|aws|ew|awn|awing) from the race",
    )),
    (Topic.EARNINGS, (
        r"earnings", r"quarterly results", r"revenue", r"guidance", r"10-K", r"10-Q", r"8-K",
    )),
    (Topic.GEOPOLITICS, (
        r"cease-?fire", r"invasion", r"missiles?", r"sanctions", r"(?-i:NATO)", r"talks between",
        r"peace (?:deal|talks)", r"(?<!trade )(?<!price )wars?",
    )),
)

# Claim markers, checked in this precedence: SPECULATION, PREDICTION, OPINION, REPORTED.
CLAIM_MARKERS: tuple[tuple[ClaimType, tuple[str, ...]], ...] = (
    (ClaimType.SPECULATION, (
        r"reportedly", r"could", r"rumou?r\w*", r"unconfirmed", r"unverified", r"sources? (?:say|said|says)",
        r"might", r"may be", r"I['’]ve heard", r"apparently", r"allegedly", r"speculat\w*", r"perhaps",
        r"possibly",
    )),
    (ClaimType.PREDICTION, (
        r"will", r"won['’]t", r"(?:is|are) expected to", r"expect(?:s|ed to)?", r"likely", r"unlikely",
        r"forecasts?", r"predict\w*", r"going to", r"by (?:the end of|next)", r"(?:is|are) set to",
        r"plans? to",
    )),
    (ClaimType.OPINION, (
        r"I think", r"I believe", r"I feel", r"in my (?:view|opinion)", r"should", r"ought to",
        r"frankly", r"clearly", r"honestly", r"obviously", r"terrible", r"great", r"disaster\w*",
        r"ridiculous", r"absurd",
    )),
    (ClaimType.REPORTED, (
        r"said", r"says", r"announced", r"according to", r"reported", r"confirmed", r"filed", r"voted",
        r"released", r"published", r"stated", r"told", r"testified", r"signed", r"ruled", r"issued",
        r"approved",
        # plain past-tense event verbs: a statement that something happened
        r"resigned", r"passed", r"rejected", r"indicted", r"nominated", r"fired", r"arrested", r"charged",
        r"elected", r"sued", r"won", r"lost", r"raised", r"lowered", r"launched",
    )),
)

ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sen", "rep", "reps", "gov", "gen", "lt", "col", "sgt", "capt", "adm",
    "st", "jr", "sr", "vs", "etc", "inc", "corp", "ltd", "fig", "approx", "dept", "est",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "u.s", "u.k", "u.n", "e.u", "d.c", "u.s.a",
})

MONTHS = frozenset({
    "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
    "November", "December", "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec",
})
WEEKDAYS = frozenset({"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"})
ENTITY_STOPWORDS = frozenset({
    "The", "A", "An", "This", "That", "These", "Those", "He", "She", "It", "They", "We", "I", "You",
    "But", "And", "Or", "Nor", "So", "Yet", "In", "On", "At", "For", "If", "When", "After", "Before", "As",
    "To", "Of", "By", "From", "With", "Without", "While", "Then", "There", "Here", "What", "Who", "Why",
    "How", "Where", "Which", "Yes", "No", "Not", "Our", "Their", "His", "Her", "Its", "My", "Your",
    "Mr", "Mrs", "Ms", "Dr", "Sen", "Rep", "Gov", "Today", "Yesterday", "Tomorrow", "Also", "Now",
    "Well", "Oh", "Okay", "OK", "Just", "Some", "Many", "Most", "All", "Any", "Every", "Each",
    "Still", "Even", "However", "Meanwhile", "According", "Is", "Are", "Was", "Were", "Do", "Does", "Did",
    "Let", "Let's", "Here's", "There's", "It's", "That's", "I'm", "We're", "They're", "Don't",
}) | MONTHS | WEEKDAYS
_ACRONYM_STOP = frozenset({"AM", "PM", "OK", "TV", "AND", "THE", "FOR", "BUT", "NOT"})
_CONNECTORS = frozenset({"of", "the", "for"})

KEYWORD_STOPWORDS = frozenset("""
a about above after again against all also am an and any are aren't as at be because been before being
below between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down
during each few for from further had hadn't has hasn't have haven't having he he'd he'll he's her here
here's hers herself him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself
just let's me more most mustn't my myself no nor not now of off on once only or other ought our ours
ourselves out over own said same say says she she'd she'll she's should shouldn't so some such than
that that's the their theirs them themselves then there there's these they they'd they'll they're
they've this those through to too under until up very was wasn't we we'd we'll we're we've were weren't
what what's when when's where where's which while who who's whom why why's will with won't would
wouldn't you you'd you'll you're you've your yours yourself yourselves new one two get got like know
yeah really think going thing things lot way well even still back much many may might also just
""".split())


def _compile(patterns: Iterable[str]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(patterns) + r")\b", re.I)


_TOPIC_PATTERNS = tuple((topic, _compile(patterns)) for topic, patterns in TOPIC_RULES)
_CLAIM_PATTERNS = tuple((claim, _compile(patterns)) for claim, patterns in CLAIM_MARKERS)

# --------------------------------------------------------------------------------------------
# Sentences
# --------------------------------------------------------------------------------------------

_BOUNDARY = re.compile(r"([.!?…]+)([\"'”’)\]]*)(\s+)")
_PARAGRAPH = re.compile(r"\n[ \t]*\n")
_OPENERS = "\"'“‘([¿¡"
_WORD_BEFORE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z.]*)$")


def _is_abbreviation(before: str) -> bool:
    match = _WORD_BEFORE.search(before)
    if not match:
        return False
    word = match.group(1)
    if len(word) == 1 and word.isupper():  # an initial: "J. Smith"
        return True
    return word.lower().rstrip(".") in ABBREVIATIONS


def _split_paragraph(text: str, out: list[str], cap: int | None) -> None:
    start = 0
    for match in _BOUNDARY.finditer(text):
        if cap is not None and len(out) >= cap:
            return
        following = text[match.end():match.end() + 1]
        newline = "\n" in match.group(3)
        if not newline and not (following.isupper() or following.isdigit() or following in _OPENERS):
            continue
        if not newline and set(match.group(1)) == {"."} and _is_abbreviation(text[start:match.start()]):
            continue
        sentence = " ".join(text[start:match.end(2)].split())
        if sentence:
            out.append(sentence)
        start = match.end()
    tail = " ".join(text[start:].split())
    if tail and (cap is None or len(out) < cap):
        out.append(tail)


def _split(text: str, cap: int | None) -> list[str]:
    out: list[str] = []
    for paragraph in _PARAGRAPH.split(text):
        if cap is not None and len(out) >= cap:
            break
        _split_paragraph(paragraph, out, cap)
    return out


def split_sentences(text: str) -> list[str]:
    """Sentences of `text`, whitespace-collapsed, at most ``MAX_SENTENCES``.

    A boundary is ``.``, ``!``, ``?`` or ``…`` (plus closing quotes/brackets) followed by a
    newline, or by whitespace and a capital, digit or opening quote. A blank line always ends a
    sentence. A period after a known abbreviation ("Sen.", "U.S.", "Jan.") or a single capital
    initial does not end one.
    """
    return _split(text, MAX_SENTENCES)


# --------------------------------------------------------------------------------------------
# Topics, claims, keywords
# --------------------------------------------------------------------------------------------


def topics_of(text: str) -> tuple[Topic, ...]:
    """Topics whose rules match `text`, in `Topic` enum order, without duplicates."""
    found = {topic for topic, pattern in _TOPIC_PATTERNS if pattern.search(text)}
    return tuple(topic for topic in Topic if topic in found)


def classify_sentence(text: str) -> ClaimType:
    """The claim type of one sentence. Precedence (first match wins):

    1. SPECULATION: rumour or hedge markers ("reportedly", "could", "sources say", "allegedly"...).
       A hedged statement about the future is speculation, not a prediction.
    2. PREDICTION: future markers ("will", "is expected to", "likely", "forecast", "by next"...).
    3. OPINION: first-person or evaluative markers ("I think", "should", "disaster"...).
    4. REPORTED: attribution markers ("said", "announced", "according to", "voted"...).
    5. Otherwise OPINION: an unattributed statement is not treated as reported fact.
    """
    for claim, pattern in _CLAIM_PATTERNS:
        if pattern.search(text):
            return claim
    return ClaimType.OPINION


_KEYWORD_TOKEN = re.compile(r"[a-z0-9][a-z0-9'’-]*[a-z0-9]|[a-z0-9]")


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def keywords(text: str) -> frozenset[str]:
    """Casefolded content words (>= 3 chars, not stopwords, trailing plural 's' removed)."""
    out: set[str] = set()
    for token in _KEYWORD_TOKEN.findall(text.casefold()):
        token = token.replace("’", "'")
        if token.endswith("'s"):
            token = token[:-2]
        if len(token) < 3 or token in KEYWORD_STOPWORDS:
            continue
        token = _singular(token)
        if len(token) >= 3 and token not in KEYWORD_STOPWORDS:
            out.add(token)
    return frozenset(out)


# --------------------------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------------------------

_TOKEN = re.compile(r"(?:[A-Z]\.){2,}|[A-Za-z][A-Za-z'’&-]*[A-Za-z]|[A-Za-z]")
_ACRONYM = re.compile(r"^[A-Z]{2,6}$")
_POSSESSIVE = re.compile(r"['’]s$")


def _tokens(sentence: str) -> list[tuple[int, int, str]]:
    """(start, end, word) with possessives removed."""
    out = []
    for match in _TOKEN.finditer(sentence):
        word = _POSSESSIVE.sub("", match.group(0))
        out.append((match.start(), match.end(), word))
    return out


def _is_cap(word: str) -> bool:
    return word[:1].isupper() and word not in ENTITY_STOPWORDS


def _sentence_entities(sentence: str, known_non_initial: set[str] | None) -> list[str]:
    """Capitalized runs (1-4 tokens, "of"/"the"/"for" allowed inside) and acronyms, in text order."""
    tokens = _tokens(sentence)
    found: list[tuple[int, str]] = []
    i = 0
    while i < len(tokens):
        if not _is_cap(tokens[i][2]):
            i += 1
            continue
        run = [i]
        j = i + 1
        while j < len(tokens) and len(run) < 4:
            gap = sentence[tokens[j - 1][1]:tokens[j][0]]
            if gap.strip():  # punctuation between tokens ends a run
                break
            word = tokens[j][2]
            if _is_cap(word):
                run.append(j)
                j += 1
                continue
            # connectors join two capitalized words: "Secretary of State", "Bank of the West"
            k = j
            while k < len(tokens) and tokens[k][2] in _CONNECTORS and not sentence[tokens[k - 1][1]:tokens[k][0]].strip():
                k += 1
            if (k > j and k < len(tokens) and _is_cap(tokens[k][2])
                    and not sentence[tokens[k - 1][1]:tokens[k][0]].strip() and len(run) + (k - j) + 1 <= 4):
                run.extend(range(j, k + 1))
                j = k + 1
                continue
            break
        words = [tokens[n][2] for n in run]
        initial = run[0] == 0
        if len(words) == 1 and initial and not _ACRONYM.match(words[0]):
            # a lone sentence-initial capital is usually just grammar; keep it only if the text
            # also capitalizes it mid-sentence
            if known_non_initial is None or words[0] not in known_non_initial:
                i = j
                continue
        found.append((tokens[run[0]][0], " ".join(words)))
        i = j
    for start, _, word in tokens:
        if _ACRONYM.match(word) and word not in _ACRONYM_STOP:
            found.append((start, word))
    found.sort(key=lambda pair: pair[0])  # stable: a run starting at an acronym precedes it
    return [entity for _, entity in found]


def _non_initial_caps(sentences: list[str]) -> set[str]:
    caps: set[str] = set()
    for sentence in sentences:
        for _, _, word in _tokens(sentence)[1:]:
            if _is_cap(word):
                caps.add(word)
    return caps


def entities_of(text: str) -> tuple[str, ...]:
    """Capitalized n-grams and 2-6 letter acronyms, first-seen order, deduplicated, at most 50.

    Months, weekdays and stopwords ("The", "He", "But"...) never start or join an entity, so a
    sentence-initial "The White House" yields "White House".
    """
    sentences = _split(text, None)
    known = _non_initial_caps(sentences)
    seen: set[str] = set()
    out: list[str] = []
    for sentence in sentences:
        for entity in _sentence_entities(sentence, known):
            if entity not in seen:
                seen.add(entity)
                out.append(entity)
                if len(out) >= MAX_ENTITIES:
                    return tuple(out)
    return tuple(out)


# --------------------------------------------------------------------------------------------
# Whole extraction
# --------------------------------------------------------------------------------------------


def _cut(text: str) -> str:
    return text if len(text) <= SENTENCE_CHARS else text[: SENTENCE_CHARS - 1].rstrip() + "…"


def extract(text: str, *, segments: Iterable[tuple[str | None, str | None, str]] | None = None) -> Extraction:
    """Topics and entities over `text`, plus classified sentences (at most ``MAX_SENTENCES``).

    With `segments` (a transcript's ``(timestamp, speaker, text)``), sentences are split per
    segment and carry its speaker and timestamp; otherwise `text` itself is split.
    """
    parts: Iterable[tuple[str | None, str | None, str]] = segments if segments is not None else ((None, None, text),)
    sentences: list[Sentence] = []
    for timestamp, speaker, body in parts:
        for raw in split_sentences(body):
            if len(sentences) >= MAX_SENTENCES:
                break
            sentences.append(Sentence(
                index=len(sentences),
                text=_cut(raw),
                claim_type=classify_sentence(raw),
                topics=topics_of(raw),
                entities=entities_of(raw),
                speaker=speaker,
                timestamp=timestamp,
            ))
        if len(sentences) >= MAX_SENTENCES:
            break
    return Extraction(
        extractor_version=EXTRACTOR_VERSION,
        topics=topics_of(text),
        entities=entities_of(text),
        sentences=tuple(sentences),
    )
