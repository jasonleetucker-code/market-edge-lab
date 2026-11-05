"""The curated 50-candidate news and primary-source registry (#192, ADR 0049).

Every candidate from the owner directive stays listed with its real, verified status. The
declared status here comes from the 2026-11-05 verification sweep
(`docs/research/NEWS_SOURCE_VERIFICATION_2026-11-05.md`): HTTP status, a parse check and a
robots.txt check, all made with our honest User-Agent. Collection additionally needs a recorded
verification younger than `VERIFICATION_VALID_DAYS` (see `effective_status`), so a status can
only fall, never rise, without fresh evidence.

Rules:
- An inaccessible source is never ACTIVE.
- A robots.txt that disallows the feed path, or refuses our honest User-Agent (401/403), makes
  the source BLOCKED. No other User-Agent is ever tried.
- A source that needs a key or a declared contact User-Agent is BLOCKED until the owner acts.
- Paywalled publishers are at most LIMITED: headline, link, timestamps and summary only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .contracts import (
    COLLECTABLE,
    VERIFICATION_VALID_DAYS,
    AccessStatus,
    Category,
    EvidenceType,
    Rights,
)

VERIFIED_ON = "2026-11-05"
SWEEP_REF = "docs/research/NEWS_SOURCE_VERIFICATION_2026-11-05.md"


@dataclass(frozen=True)
class Feed:
    """One machine-readable channel of a candidate."""

    feed_id: str
    url: str
    format: str  # "rss" | "atom" | "federal_register_json"


@dataclass(frozen=True)
class Candidate:
    number: int  # the directive's numbering (1-50)
    source_id: str
    name: str
    homepage: str
    category: Category
    evidence_type: EvidenceType
    rights: Rights
    origin: str  # origin family for independence counting
    status: AccessStatus  # declared from the latest sweep; see effective_status
    mechanism: str  # how it is (or would be) accessed
    note: str  # why this status: the evidence in one line
    feeds: tuple[Feed, ...] = ()
    terms: str = "Publisher RSS offered for reading; we store headline, link, timestamps and a short snippet, privately."
    min_interval_minutes: int = 120  # never poll faster than this
    verified_on: str | None = VERIFIED_ON
    aggregator: bool = False


def _f(feed_id: str, url: str, fmt: str = "rss") -> tuple[Feed, ...]:
    return (Feed(feed_id, url, fmt),)


G, P, F, PR = Category.GENERAL, Category.POLITICS, Category.FINANCE, Category.PRIMARY
REP, PRIM, DATA, FCST, ANA, COM = (EvidenceType.REPORTING, EvidenceType.PRIMARY, EvidenceType.DATA,
                                   EvidenceType.FORECAST, EvidenceType.ANALYSIS, EvidenceType.COMMENTARY)
HS, PD = Rights.HEADLINE_SNIPPET, Rights.PUBLIC_DOMAIN
A, L, U, B = AccessStatus.ACTIVE, AccessStatus.LIMITED, AccessStatus.UNAVAILABLE, AccessStatus.BLOCKED
GN_BLOCKED = ("No first-party public feed assumed; Google News RSS discovery is disallowed by news.google.com "
              "robots.txt (Disallow: / for /rss/search), so it is not used.")
PAYWALL = "Paywalled publisher: headline, link, timestamps and the feed's own summary only; never article text."

CANDIDATES: tuple[Candidate, ...] = (
    # A. General news and breaking developments
    Candidate(1, "ap", "Associated Press", "https://apnews.com", G, REP, HS, "ap", B,
              "Google News RSS (discovery)", GN_BLOCKED),
    Candidate(2, "reuters", "Reuters", "https://www.reuters.com", G, REP, HS, "reuters", B,
              "Google News RSS (discovery)", GN_BLOCKED),
    Candidate(3, "bbc", "BBC News", "https://www.bbc.com/news", G, REP, HS, "bbc", A,
              "publisher RSS", "200, 34 items, newest same day; robots allows.",
              _f("bbc_top", "https://feeds.bbci.co.uk/news/rss.xml")),
    Candidate(4, "npr", "NPR", "https://www.npr.org", G, REP, HS, "npr", B,
              "publisher RSS (feeds.npr.org)",
              "Feed answers 200, but feeds.npr.org/robots.txt refuses our User-Agent (403 Access Denied)."),
    Candidate(5, "pbs", "PBS NewsHour", "https://www.pbs.org/newshour", G, REP, HS, "pbs", A,
              "publisher RSS", "200, 20 items, ETag; robots allows.",
              _f("pbs_headlines", "https://www.pbs.org/newshour/feeds/rss/headlines")),
    Candidate(6, "abc", "ABC News", "https://abcnews.go.com", G, REP, HS, "abc", A,
              "publisher RSS", "200 for top stories and politics; robots allows.",
              (Feed("abc_top", "https://abcnews.com/abcnews/topstories", "rss"),
               Feed("abc_politics", "https://abcnews.com/abcnews/politicsheadlines", "rss"))),
    Candidate(7, "cbs", "CBS News", "https://www.cbsnews.com", G, REP, HS, "cbs", A,
              "publisher RSS", "200, 30 items; robots allows.",
              _f("cbs_latest", "https://www.cbsnews.com/latest/rss/main")),
    Candidate(8, "nbc", "NBC News", "https://www.nbcnews.com", G, REP, HS, "nbc", A,
              "publisher RSS", "200, 25 items; robots allows.",
              _f("nbc_news", "https://feeds.nbcnews.com/nbcnews/public/news")),
    Candidate(9, "guardian", "The Guardian", "https://www.theguardian.com", G, REP, HS, "guardian", A,
              "publisher RSS", "200 for world and US news, ETag; robots allows.",
              (Feed("guardian_world", "https://www.theguardian.com/world/rss", "rss"),
               Feed("guardian_us", "https://www.theguardian.com/us-news/rss", "rss"))),
    Candidate(10, "aljazeera", "Al Jazeera English", "https://www.aljazeera.com", G, REP, HS, "aljazeera", A,
              "publisher RSS", "200, 25 items, ETag; robots allows.",
              _f("aljazeera_all", "https://www.aljazeera.com/xml/rss/all.xml")),
    Candidate(11, "axios", "Axios", "https://www.axios.com", G, REP, HS, "axios", B,
              "publisher RSS (api.axios.com)", "api.axios.com/robots.txt refuses our User-Agent (403)."),
    Candidate(12, "propublica", "ProPublica", "https://www.propublica.org", G, REP, HS, "propublica", A,
              "publisher RSS", "200, ETag; robots allows. The feed carries full text, which we drop.",
              _f("propublica_main", "https://www.propublica.org/feeds/propublica/main")),
    Candidate(13, "time", "TIME", "https://time.com", G, REP, HS, "time", A,
              "publisher RSS", "200, 25 items; robots allows. Full text in feed is dropped.",
              _f("time_feed", "https://time.com/feed/")),
    Candidate(14, "cnn", "CNN", "https://www.cnn.com", G, REP, HS, "cnn", U,
              "publisher RSS (rss.cnn.com)",
              "rss.cnn.com answers 200, but its newest item is 2023-05-01: stale, not a live feed. " + GN_BLOCKED),
    Candidate(15, "fox", "Fox News", "https://www.foxnews.com", G, REP, HS, "fox", A,
              "publisher RSS", "200 for latest and politics, ETag; robots allows. Full text in feed is dropped.",
              (Feed("fox_latest", "https://moxie.foxnews.com/google-publisher/latest.xml", "rss"),
               Feed("fox_politics", "https://moxie.foxnews.com/google-publisher/politics.xml", "rss"))),
    Candidate(16, "usatoday", "USA Today", "https://www.usatoday.com", G, REP, HS, "usatoday", B,
              "publisher RSS (rssfeeds.usatoday.com)", "403 to our User-Agent. " + GN_BLOCKED),
    Candidate(17, "latimes", "Los Angeles Times", "https://www.latimes.com", G, REP, HS, "latimes", A,
              "publisher RSS", "200 (politics); robots allows. Full text in feed is dropped.",
              _f("latimes_politics", "https://www.latimes.com/politics/rss2.0.xml")),
    Candidate(18, "france24", "France 24", "https://www.france24.com", G, REP, HS, "france24", A,
              "publisher RSS", "200, 24 items; robots allows.",
              _f("france24_en", "https://www.france24.com/en/rss")),
    # B. Politics, government, elections and policy analysis
    Candidate(19, "politico", "Politico", "https://www.politico.com", P, REP, HS, "politico", A,
              "publisher RSS", "200, 30 items; no robots.txt (404). Full text in feed is dropped.",
              _f("politico_politics", "https://rss.politico.com/politics-news.xml")),
    Candidate(20, "thehill", "The Hill", "https://thehill.com", P, REP, HS, "thehill", A,
              "publisher RSS", "200, ETag; robots allows.",
              _f("thehill_news", "https://thehill.com/news/feed/")),
    Candidate(21, "rollcall", "Roll Call", "https://rollcall.com", P, REP, HS, "rollcall", U,
              "publisher RSS", "200, but the feed is malformed XML (duplicate attribute): not parseable."),
    Candidate(22, "notus", "NOTUS", "https://www.notus.org", P, REP, HS, "notus", U,
              "publisher RSS", "No feed found (notus.org/feed answers 404)."),
    Candidate(23, "semafor", "Semafor", "https://www.semafor.com", P, REP, HS, "semafor", A,
              "publisher RSS", "200, ETag; robots allows. Full text in feed is dropped.",
              _f("semafor_all", "https://www.semafor.com/rss.xml")),
    Candidate(24, "cspan", "C-SPAN", "https://www.c-span.org", P, PRIM, HS, "cspan", B,
              "publisher RSS", "c-span.org/rss answers 403 to our User-Agent. " + GN_BLOCKED),
    Candidate(25, "ballotpedia", "Ballotpedia", "https://ballotpedia.org", P, ANA, HS, "ballotpedia", A,
              "publisher RSS (news.ballotpedia.org)", "200, ETag; robots allows. Full text in feed is dropped.",
              _f("ballotpedia_news", "https://news.ballotpedia.org/feed/")),
    Candidate(26, "cook", "Cook Political Report", "https://www.cookpolitical.com", P, FCST, HS, "cook", U,
              "publisher RSS", "200, but the newest item is 2024-06-14: stale, not a live feed."),
    Candidate(27, "sabato", "Sabato's Crystal Ball", "https://centerforpolitics.org/crystalball", P, FCST, HS,
              "sabato", B, "publisher RSS", "Feed and robots.txt answer 403 to our User-Agent."),
    Candidate(28, "ddhq", "Decision Desk HQ", "https://decisiondeskhq.com", P, DATA, HS, "ddhq", U,
              "publisher RSS", "No feed found (decisiondeskhq.com/feed answers 404)."),
    Candidate(29, "opensecrets", "OpenSecrets", "https://www.opensecrets.org", P, DATA, HS, "opensecrets", B,
              "publisher RSS", "opensecrets.org/news/feed answers 403 to our User-Agent."),
    Candidate(30, "factcheck", "FactCheck.org", "https://www.factcheck.org", P, ANA, HS, "factcheck", A,
              "publisher RSS", "200, ETag; robots allows. Full text in feed is dropped.",
              _f("factcheck_feed", "https://www.factcheck.org/feed/")),
    # C. Finance, economics and financial-market news
    Candidate(31, "cnbc", "CNBC", "https://www.cnbc.com", F, REP, HS, "cnbc", B,
              "publisher RSS (search.cnbc.com)", "search.cnbc.com robots.txt: User-agent * Disallow: /."),
    Candidate(32, "yahoo_finance", "Yahoo Finance", "https://finance.yahoo.com", F, REP, HS, "yahoo", U,
              "publisher RSS", "finance.yahoo.com/news/rssindex answers 404."),
    Candidate(33, "marketplace", "Marketplace", "https://www.marketplace.org", F, REP, HS, "marketplace", B,
              "publisher RSS", "Feed and robots.txt answer 403 to our User-Agent."),
    Candidate(34, "marketwatch", "MarketWatch", "https://www.marketwatch.com", F, REP, HS, "marketwatch", B,
              "Dow Jones public RSS", "Feed answers 200, but feeds.content.dowjones.io/robots.txt refuses (403)."),
    Candidate(35, "bloomberg", "Bloomberg", "https://www.bloomberg.com", F, REP, HS, "bloomberg", L,
              "publisher RSS (feeds.bloomberg.com)", "200, 20 items, ETag; no robots.txt (404). " + PAYWALL,
              _f("bloomberg_markets", "https://feeds.bloomberg.com/markets/news.rss"),
              terms=PAYWALL),
    Candidate(36, "ft", "Financial Times", "https://www.ft.com", F, REP, HS, "ft", L,
              "publisher RSS", "200, 12 items, ETag; robots allows. " + PAYWALL,
              _f("ft_home", "https://www.ft.com/rss/home"), terms=PAYWALL),
    Candidate(37, "wsj", "The Wall Street Journal", "https://www.wsj.com", F, REP, HS, "wsj", B,
              "Dow Jones public RSS", "Feed answers 200, but feeds.content.dowjones.io/robots.txt refuses (403)."),
    Candidate(38, "investopedia", "Investopedia", "https://www.investopedia.com", F, ANA, HS, "investopedia", B,
              "publisher RSS", "Feed answers 403 to our User-Agent."),
    Candidate(39, "thestreet", "TheStreet", "https://www.thestreet.com", F, REP, HS, "thestreet", A,
              "publisher RSS", "200, 50 items, ETag; robots allows. Full text in feed is dropped.",
              _f("thestreet_full", "https://www.thestreet.com/.rss/full/")),
    Candidate(40, "quartz", "Quartz", "https://qz.com", F, REP, HS, "quartz", A,
              "publisher RSS", "200, 19 items; robots allows.",
              _f("quartz_rss", "https://qz.com/rss")),
    # D. Primary government and economic sources
    Candidate(41, "congress", "Congress.gov", "https://www.congress.gov", PR, PRIM, PD, "congress", L,
              "congress.gov RSS (most-viewed bills)",
              "RSS answers 200 but lists only the most-viewed bills, undated. The bill/vote API needs an "
              "api.data.gov key (owner approval).",
              _f("congress_most_viewed", "https://www.congress.gov/rss/most-viewed-bills.xml"),
              terms="US-government work (public domain).", min_interval_minutes=720),
    Candidate(42, "clerk_house", "Office of the Clerk, U.S. House", "https://clerk.house.gov", PR, PRIM, PD,
              "house", U, "roll-call XML pages",
              "No verified feed: the probed vote index answers 404, and roll-call lists need page parsing.",
              terms="US-government work (public domain)."),
    Candidate(43, "senate", "U.S. Senate roll-call votes", "https://www.senate.gov", PR, PRIM, PD, "senate", B,
              "roll-call XML", "senate.gov vote_menu XML answers 403 to our User-Agent.",
              terms="US-government work (public domain)."),
    Candidate(44, "federal_register", "Federal Register", "https://www.federalregister.gov", PR, PRIM, PD,
              "federal_register", A, "official JSON API (no key)", "200, 20 documents, newest same day; robots allows.",
              _f("federal_register_newest",
                 "https://www.federalregister.gov/api/v1/documents.json?order=newest&per_page=40",
                 "federal_register_json"),
              terms="US-government work (public domain); API needs no key."),
    Candidate(45, "govinfo", "GovInfo", "https://www.govinfo.gov", PR, PRIM, PD, "govinfo", A,
              "official RSS (bills)", "200, 100 items; robots allows. The GovInfo API needs a key (not used).",
              _f("govinfo_bills", "https://www.govinfo.gov/rss/bills.xml"),
              terms="US-government work (public domain)."),
    Candidate(46, "sec_edgar", "SEC EDGAR", "https://www.sec.gov/edgar", PR, PRIM, PD, "sec", B,
              "EDGAR latest-filings Atom",
              "SEC requires a declared contact User-Agent and www.sec.gov/robots.txt refuses ours (403). Waits for "
              "an owner-supplied contact; the owner's email is never used.",
              terms="US-government work; SEC fair-access policy (<=10 req/s, declared UA)."),
    Candidate(47, "fed", "Federal Reserve press releases", "https://www.federalreserve.gov", PR, PRIM, PD, "fed", A,
              "official RSS", "200, 20 items, ETag; no robots.txt (404).",
              _f("fed_press_all", "https://www.federalreserve.gov/feeds/press_all.xml"),
              terms="US-government work (public domain)."),
    Candidate(48, "bls", "Bureau of Labor Statistics", "https://www.bls.gov", PR, DATA, PD, "bls", B,
              "official RSS", "www.bls.gov/robots.txt refuses our User-Agent (403); the feed answered 403 earlier.",
              terms="US-government work (public domain)."),
    Candidate(49, "bea", "Bureau of Economic Analysis", "https://www.bea.gov", PR, DATA, PD, "bea", B,
              "official RSS (apps.bea.gov)", "apps.bea.gov robots.txt: User-agent * Disallow: / (feed path not allowed).",
              terms="US-government work (public domain)."),
    Candidate(50, "fred", "FRED / ALFRED", "https://fred.stlouisfed.org", PR, DATA, HS, "fred", B,
              "official API", "The FRED/ALFRED API needs a free key: credential creation needs owner approval.",
              terms="FRED API terms; attribution required."),
)

BY_ID = {c.source_id: c for c in CANDIDATES}


def _check() -> None:
    numbers = sorted(c.number for c in CANDIDATES)
    if numbers != list(range(1, 51)):
        raise AssertionError("the registry must hold exactly the directive's 50 candidates")
    if len(BY_ID) != len(CANDIDATES):
        raise AssertionError("duplicate source_id")
    for c in CANDIDATES:
        if c.status in COLLECTABLE and not c.feeds:
            raise AssertionError(f"{c.source_id}: a collectable source needs a feed")
        if c.status not in COLLECTABLE and c.feeds:
            raise AssertionError(f"{c.source_id}: a non-collectable source must not carry a feed")


_check()


def effective_status(candidate: Candidate, *, last_verified_ok_utc: str | None, now: datetime,
                     last_access_signal: str | None = None) -> AccessStatus:
    """The status collection may use now: the declared status, capped by fresh evidence.

    A collectable source falls to UNVERIFIED when its last successful verification is missing
    or older than VERIFICATION_VALID_DAYS, and to BLOCKED when the latest attempt was refused
    (an access signal such as HTTP 401/403 or a robots disallow). It never rises above the
    declared status.
    """
    if candidate.status not in COLLECTABLE:
        return candidate.status
    if last_access_signal in ("HTTP_401", "HTTP_403", "ROBOTS_DISALLOW", "LOGIN_REDIRECT"):
        return AccessStatus.BLOCKED
    if not last_verified_ok_utc:
        return AccessStatus.UNVERIFIED
    try:
        verified = datetime.fromisoformat(last_verified_ok_utc.replace("Z", "+00:00"))
    except ValueError:
        return AccessStatus.UNVERIFIED
    if verified.tzinfo is None:
        return AccessStatus.UNVERIFIED
    age = now.astimezone(timezone.utc) - verified.astimezone(timezone.utc)
    if age < timedelta(0) or age > timedelta(days=VERIFICATION_VALID_DAYS):
        return AccessStatus.UNVERIFIED
    return candidate.status


def collectable_feeds() -> tuple[tuple[Candidate, Feed], ...]:
    """Every (candidate, feed) pair whose declared status allows collection."""
    return tuple((c, f) for c in CANDIDATES if c.status in COLLECTABLE for f in c.feeds)


def counts() -> dict[str, int]:
    out = {s.value: 0 for s in AccessStatus}
    for c in CANDIDATES:
        out[c.status.value] += 1
    return out
