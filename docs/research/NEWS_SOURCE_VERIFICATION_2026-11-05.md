# News source verification sweep — 2026-11-05

This is the evidence behind the declared statuses in `src/edge_lab/intel/registry.py` (#192, ADR 0049).

**Method.** It was run once on 2026-11-05, between about 18:55 and 19:05 UTC, from a cloud container.
- One GET per URL, with the honest User-Agent `market-edge-lab/0.1 (read-only research feed reader)` and a feed
  Accept header, paced at 0.5 s.
- The body was parsed with `xml.etree` (or `json`): we record the item count and the newest dated item.
- The host's `robots.txt` was checked with `urllib.robotparser` for our User-Agent.
- No other User-Agent was tried, and no login, paywall or CAPTCHA was approached.

**Status rules.**
- **ACTIVE:** a live parseable feed that robots allows.
- **LIMITED:** live, but paywalled headlines only, or of narrow value.
- **UNAVAILABLE:** no live feed found (404, stale or malformed).
- **BLOCKED:** refused (401/403), robots disallow, robots.txt refused to our User-Agent, or a key or declared
  contact is required.
- A robots.txt that answers 403 to our User-Agent is treated as a refusal, per `urllib.robotparser` convention.

Collection additionally requires a recorded verification younger than 14 days (`registry.effective_status`).

| # | Source | Status | Probed URL | HTTP | Parse | Newest item | robots | Note |
|---|---|---|---|---|---|---|---|---|
| 1 | Associated Press | BLOCKED | `https://news.google.com/rss/search?q=site:apnews.com&hl=en-US&gl=US&ceid=US:en` | 200 | FEED 100 | 2026-11-05T18:54Z | False | No first-party public feed assumed; Google News RSS discovery is disallowed by news.google.com robots.txt (Disallow: / for /rss/search), so it is not used. |
| 2 | Reuters | BLOCKED | `https://news.google.com/rss/search?q=site:reuters.com&hl=en-US&gl=US&ceid=US:en` | 200 | FEED 100 | 2026-11-05T18:57Z | False | No first-party public feed assumed; Google News RSS discovery is disallowed by news.google.com robots.txt (Disallow: / for /rss/search), so it is not used. |
| 3 | BBC News | ACTIVE | `https://feeds.bbci.co.uk/news/rss.xml` | 200 | FEED 34 | 2026-11-05T18:53Z | True | 200, 34 items, newest same day; robots allows. |
| 4 | NPR | BLOCKED | `https://feeds.npr.org/1001/rss.xml` | 200 | FEED 10 | 2026-11-05T18:30Z | no-robots(403) | Feed answers 200, but feeds.npr.org/robots.txt refuses our User-Agent (403 Access Denied). |
| 5 | PBS NewsHour | ACTIVE | `https://www.pbs.org/newshour/feeds/rss/headlines` | 200 | FEED 20 | 2026-11-05T18:47Z | True | 200, 20 items, ETag; robots allows. |
| 6 | ABC News | ACTIVE | `https://abcnews.com/abcnews/topstories` | 200 | FEED 25 | 2026-11-05T18:47Z | True | 200 for top stories and politics; robots allows. |
| 7 | CBS News | ACTIVE | `https://www.cbsnews.com/latest/rss/main` | 200 | FEED 30 | 2026-11-05T18:59Z | True | 200, 30 items; robots allows. |
| 8 | NBC News | ACTIVE | `https://feeds.nbcnews.com/nbcnews/public/news` | 200 | FEED 25 | 2026-11-05T18:47Z | True | 200, 25 items; robots allows. |
| 9 | The Guardian | ACTIVE | `https://www.theguardian.com/world/rss` | 200 | FEED 45 | 2026-11-05T18:51Z | True | 200 for world and US news, ETag; robots allows. |
| 10 | Al Jazeera English | ACTIVE | `https://www.aljazeera.com/xml/rss/all.xml` | 200 | FEED 25 | 2026-11-05T18:30Z | True | 200, 25 items, ETag; robots allows. |
| 11 | Axios | BLOCKED | `https://api.axios.com/feed/` | 200 | FEED 100 | 2026-11-05T18:20Z | False | api.axios.com/robots.txt refuses our User-Agent (403). |
| 12 | ProPublica | ACTIVE | `https://www.propublica.org/feeds/propublica/main` | 200 | FEED 20 | 2026-11-05T11:00Z | True | 200, ETag; robots allows. The feed carries full text, which we drop. |
| 13 | TIME | ACTIVE | `https://time.com/feed/` | 200 | FEED 25 | 2026-11-05T17:14Z | True | 200, 25 items; robots allows. Full text in feed is dropped. |
| 14 | CNN | UNAVAILABLE | `http://rss.cnn.com/rss/cnn_topstories.rss` | 200 | FEED 69 | 2023-05-01T23:02Z | no-robots(404) | rss.cnn.com answers 200, but its newest item is 2023-05-01: stale, not a live feed. No first-party public feed assumed; Google News RSS discovery is disallowed by news.google.com robots.txt (Disallow: / for /rss/search), so it is not used. |
| 15 | Fox News | ACTIVE | `https://moxie.foxnews.com/google-publisher/latest.xml` | 200 | FEED 25 | 2026-11-05T17:49Z | True | 200 for latest and politics, ETag; robots allows. Full text in feed is dropped. |
| 16 | USA Today | BLOCKED | `http://rssfeeds.usatoday.com/usatoday-NewsTopStories` | 403 | HTTP_ERROR | — | no-robots(403) | 403 to our User-Agent. No first-party public feed assumed; Google News RSS discovery is disallowed by news.google.com robots.txt (Disallow: / for /rss/search), so it is not used. |
| 17 | Los Angeles Times | ACTIVE | `https://www.latimes.com/politics/rss2.0.xml` | 200 | FEED 95 | 2026-11-05T11:00Z | True | 200 (politics); robots allows. Full text in feed is dropped. |
| 18 | France 24 | ACTIVE | `https://www.france24.com/en/rss` | 200 | FEED 24 | 2026-11-05T18:16Z | True | 200, 24 items; robots allows. |
| 19 | Politico | ACTIVE | `https://rss.politico.com/politics-news.xml` | 200 | FEED 30 | 2026-11-05T11:05Z | no-robots(404) | 200, 30 items; no robots.txt (404). Full text in feed is dropped. |
| 20 | The Hill | ACTIVE | `https://thehill.com/news/feed/` | 200 | FEED 15 | 2026-11-05T18:36Z | True | 200, ETag; robots allows. |
| 21 | Roll Call | UNAVAILABLE | `https://rollcall.com/feed/` | 200 | UNPARSEABLE:duplicate attrib | — | True | 200, but the feed is malformed XML (duplicate attribute): not parseable. |
| 22 | NOTUS | UNAVAILABLE | `https://www.notus.org/feed` | 404 | HTTP_ERROR | — | True | No feed found (notus.org/feed answers 404). |
| 23 | Semafor | ACTIVE | `https://www.semafor.com/rss.xml` | 200 | FEED 271 | 2026-11-05T18:27Z | True | 200, ETag; robots allows. Full text in feed is dropped. |
| 24 | C-SPAN | BLOCKED | `https://www.c-span.org/rss/` | 403 | HTTP_ERROR | — | no-robots(403) | c-span.org/rss answers 403 to our User-Agent. No first-party public feed assumed; Google News RSS discovery is disallowed by news.google.com robots.txt (Disallow: / for /rss/search), so it is not used. |
| 25 | Ballotpedia | ACTIVE | `https://news.ballotpedia.org/feed/` | 200 | FEED 20 | 2026-11-05T10:30Z | True | 200, ETag; robots allows. Full text in feed is dropped. |
| 26 | Cook Political Report | UNAVAILABLE | `https://www.cookpolitical.com/rss.xml` | 200 | FEED 10 | 2024-06-14T06:29Z | True | 200, but the newest item is 2024-06-14: stale, not a live feed. |
| 27 | Sabato's Crystal Ball | BLOCKED | `https://centerforpolitics.org/crystalball/feed/` | 403 | HTTP_ERROR | — | no-robots(403) | Feed and robots.txt answer 403 to our User-Agent. |
| 28 | Decision Desk HQ | UNAVAILABLE | `https://decisiondeskhq.com/feed/` | 404 | HTTP_ERROR | — | True | No feed found (decisiondeskhq.com/feed answers 404). |
| 29 | OpenSecrets | BLOCKED | `https://www.opensecrets.org/news/feed/` | 403 | HTTP_ERROR | — | True | opensecrets.org/news/feed answers 403 to our User-Agent. |
| 30 | FactCheck.org | ACTIVE | `https://www.factcheck.org/feed/` | 200 | FEED 10 | 2026-11-03T16:58Z | True | 200, ETag; robots allows. Full text in feed is dropped. |
| 31 | CNBC | BLOCKED | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114` | 200 | FEED 30 | 2026-11-05T18:57Z | False | search.cnbc.com robots.txt: User-agent * Disallow: /. |
| 32 | Yahoo Finance | UNAVAILABLE | `https://finance.yahoo.com/news/rssindex` | 404 | HTTP_ERROR | — | True | finance.yahoo.com/news/rssindex answers 404. |
| 33 | Marketplace | BLOCKED | `https://www.marketplace.org/feed/` | 403 | HTTP_ERROR | — | no-robots(403) | Feed and robots.txt answer 403 to our User-Agent. |
| 34 | MarketWatch | BLOCKED | `https://feeds.content.dowjones.io/public/rss/mw_topstories` | 200 | FEED 10 | 2026-11-05T18:18Z | no-robots(403) | Feed answers 200, but feeds.content.dowjones.io/robots.txt refuses (403). |
| 35 | Bloomberg | LIMITED | `https://feeds.bloomberg.com/markets/news.rss` | 200 | FEED 20 | 2026-11-05T18:52Z | no-robots(404) | 200, 20 items, ETag; no robots.txt (404). Paywalled publisher: headline, link, timestamps and the feed's own summary only; never article text. |
| 36 | Financial Times | LIMITED | `https://www.ft.com/rss/home` | 200 | FEED 12 | 2026-11-05T17:41Z | True | 200, 12 items, ETag; robots allows. Paywalled publisher: headline, link, timestamps and the feed's own summary only; never article text. |
| 37 | The Wall Street Journal | BLOCKED | `https://feeds.content.dowjones.io/public/rss/RSSWorldNews` | 200 | FEED 74 | 2026-11-05T17:54Z | no-robots(403) | Feed answers 200, but feeds.content.dowjones.io/robots.txt refuses (403). |
| 38 | Investopedia | BLOCKED | `https://www.investopedia.com/feedbuilder/feed/getfeed?feedName=rss_headline` | 403 | HTTP_ERROR | — | True | Feed answers 403 to our User-Agent. |
| 39 | TheStreet | ACTIVE | `https://www.thestreet.com/.rss/full/` | 200 | FEED 50 | 2026-11-05T18:45Z | True | 200, 50 items, ETag; robots allows. Full text in feed is dropped. |
| 40 | Quartz | ACTIVE | `https://qz.com/rss` | 200 | FEED 19 | 2026-11-05T18:45Z | True | 200, 19 items; robots allows. |
| 41 | Congress.gov | LIMITED | `https://www.congress.gov/rss/most-viewed-bills.xml` | 200 | FEED 1 | — | True | RSS answers 200 but lists only the most-viewed bills, undated. The bill/vote API needs an api.data.gov key (owner approval). |
| 42 | Office of the Clerk, U.S. House | UNAVAILABLE | `https://clerk.house.gov/evs/2026/index.asp` | 404 | HTTP_ERROR | — | no-robots(404) | No verified feed: the probed vote index answers 404, and roll-call lists need page parsing. |
| 43 | U.S. Senate roll-call votes | BLOCKED | `https://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_119_2.xml` | 403 | HTTP_ERROR | — | True | senate.gov vote_menu XML answers 403 to our User-Agent. |
| 44 | Federal Register | ACTIVE | `https://www.federalregister.gov/api/v1/documents.json?order=newest&per_page=20` | 200 | JSON 20 | 2026-11-05 | True | 200, 20 documents, newest same day; robots allows. |
| 45 | GovInfo | ACTIVE | `https://www.govinfo.gov/rss/bills.xml` | 200 | FEED 100 | 2026-11-05T04:55Z | True | 200, 100 items; robots allows. The GovInfo API needs a key (not used). |
| 46 | SEC EDGAR | BLOCKED | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom` | 200 | FEED 40 | 2026-11-05T19:00Z | no-robots(403) | SEC requires a declared contact User-Agent and www.sec.gov/robots.txt refuses ours (403). Waits for an owner-supplied contact; the owner's email is never used. |
| 47 | Federal Reserve press releases | ACTIVE | `https://www.federalreserve.gov/feeds/press_all.xml` | 200 | FEED 20 | 2026-11-05T16:00Z | no-robots(404) | 200, 20 items, ETag; no robots.txt (404). |
| 48 | Bureau of Labor Statistics | BLOCKED | `https://www.bls.gov/feed/bls_latest.rss` | 200 | FEED 1 | 2026-11-05T13:30Z | no-robots(403) | www.bls.gov/robots.txt refuses our User-Agent (403); the feed answered 403 earlier. |
| 49 | Bureau of Economic Analysis | BLOCKED | `https://apps.bea.gov/rss/rss.xml` | 200 | FEED 49 | 2026-11-04T13:30Z | False | apps.bea.gov robots.txt: User-agent * Disallow: / (feed path not allowed). |
| 50 | FRED / ALFRED | BLOCKED | `https://fred.stlouisfed.org/` | 200 | HTML | — | robots-err:TimeoutError | The FRED/ALFRED API needs a free key: credential creation needs owner approval. |

Counts: {'ACTIVE': 22, 'LIMITED': 3, 'UNAVAILABLE': 7, 'BLOCKED': 18, 'UNVERIFIED': 0}.

**Additional robots checks (curl, same User-Agent).**
- `news.google.com/robots.txt` has `User-agent: *` with `Disallow: /`, plus Allow lines only for home and section
  pages. `/rss/search` is therefore disallowed, so AP, Reuters, CNN, USA Today and C-SPAN discovery through it
  is BLOCKED.
- These robots.txt files answered 403 to our User-Agent: feeds.npr.org, feeds.content.dowjones.io (MarketWatch,
  WSJ), www.sec.gov, www.bls.gov and api.axios.com.
- `search.cnbc.com` has `User-agent: *` with `Disallow: /`.
- `apps.bea.gov` has `Disallow: /`, with Allow lines only for unrelated paths.

Re-run with `edge-lab intel verify-sources` (records each result as a verification record in the evidence store).
