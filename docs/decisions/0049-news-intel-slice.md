# ADR 0049: News and transcript intelligence slice: inbox handoff, v8 journal, Kalshi exclusion from AI

**Status:** Accepted 2026-11-05 (#192). Authority: the 2026-11-05 entry of `docs/EXECUTION_PLAN.md` and the owner's
verbatim answers in `docs/owner/2026-11-05-news-political-intelligence-directive.md`.

## Problem

The owner wants a working chain inside the existing Terminal: free news and political/economic sources, collected
every two hours plus a manual refresh; podcast transcripts the owner pastes in; event-centred research; links to
Kalshi markets; deterministic pricing; and an auditable record of forecasts and decisions.

The repository constrains how this can be built:

- **The dashboard cannot write or fetch.** It is GET/HEAD-only. The kernel denies it any network
  (`IPAddressDeny=any`) and pins the evidence DB read-only.
- **No reusable news or AI plumbing.** No news collector, XML parser or model runtime exists. Any AI provider call is
  unauthorized.
- **Kalshi rights are unresolved.** `DATA_RIGHTS` is UNRESOLVED. The website Data Terms restrict AI use.
- **No fee claim is possible.** Politics series fall to the general fee schedule, which is UNVERIFIED and not
  claimable. Most econ series are FEE_UNSUPPORTED.
- **Protected research cannot be touched.** The shadow ledger holds only EXP-001 accounts. Two #96 family slots are
  in use. Protected windows and protected label scopes exist.

## Decision

1. **One package, existing owners.** Everything lives in `src/edge_lab/intel/` and extends the canonical owners:
   - `sources` (two SourceSpecs and a `news` health profile);
   - `http` (opt-in `max_bytes`, a 304 result, ETag/Last-Modified);
   - `storage` (schema v8);
   - `opportunity` (pure `break_even_probability` and `max_acceptable_price`);
   - `stats` (`brier_score`);
   - `kalshi`/`kalshi_quotes`, `fee_schedules`, `starter_policy` and `freshness_fabric`.

   There is no second store, scheduler, pricing engine or ledger.
2. **Inbox handoff (owner answer 2).** One dashboard POST route, `/experiments/intel/inbox`, validates and writes one
   size-capped file atomically into a private inbox (`tmp/` → `new/`). It accepts:
   - a transcript;
   - an analysis or owner-judgment import;
   - a refresh request.

   The dashboard keeps no network access, and its evidence DB stays read-only. The CSRF token is per-process and
   compared with `secrets.compare_digest`; it uses no `hmac`, which the execution-path invariant forbids.

   The collector processes the inbox as follows:
   - `edge-lab intel process-inbox` renames each file into `work/` before parsing, so a bad file cannot re-trigger.
   - It records the result.
   - It moves the file to `done/` or `rejected/`.
3. **Schema v8 in the evidence DB** (additive, every table append-only):
   - `intel_fetches` holds every attempt, including 304s and failures.
   - `intel_items` holds one row per (source, item, version).
   - `intel_records` is a typed journal with a per-subject hash chain. It covers transcript metadata, extractions,
     events, status transitions, judgments, forecasts, links, decisions, resolutions and inbox results.

   Transcript text goes into the existing content-addressed `document_blobs`. Raw feed bytes are kept only for
   US-government public-domain sources. Publisher feeds keep the hash and size, plus the headline, link, timestamps
   and a snippet of at most 300 characters. Rights take precedence over full byte-reproducibility here, and
   `DATA_PROVENANCE.md` records this exception.
4. **The research journal is not a shadow-ledger account.** Each decision is appended with its inputs at decision
   time: forecast id, quote snapshot id, ask, fee schedule and status, and the action policy version. SKIP and
   INSUFFICIENT_EVIDENCE are recorded too. Hypothetical entries use the ask and fee at decision time, never a mid.
   Forecasts are only ever superseded, never edited. A forecast recorded before the first linked quote snapshot
   existed is PRICE_BLIND. Brier scores and hypothetical P&L are labelled PROVISIONAL and HYPOTHETICAL.
5. **Kalshi stays out of AI.** `intel/packet.py` may not import Kalshi, opportunity or pricing modules, and an AST
   test enforces this. The analysis import rejects price, fee and ticker fields, except in the owner's link block.
   Kalshi intel snapshots use their own source identity, `kalshi_public_intel`, so they never vouch for routine
   Kalshi health or enter EXP or sports queries. The lane refuses KXHIGHNY, KXNFLGAME, KXNHLGAME and KXMVE*.
   It also refuses protected windows and shares the host's single Kalshi pacer lock.
6. **A candidate is not equivalence.** Matching a market to an event by title or keywords yields CANDIDATE. Only a
   link the owner confirms, after reading the captured rules, is priced. `opportunity.evaluate` is still called
   for its canonical reasons. Its weather-specific `rules_check` returns RULES_UNRESOLVED for these markets, and that
   reason is shown rather than hidden.
7. **The action policy (`intel-action-v1`) is deterministic.** The possible actions are INVESTIGATE, WATCH, SKIP and
   INSUFFICIENT_EVIDENCE. There is never a "buy". A provisional forecast can reach INVESTIGATE at most.
8. **Schedules ship disabled.** `edgelab-news.timer` runs every 2 hours. `edgelab-news-inbox.timer` runs every
   5 minutes and makes no network call unless a refresh was requested. Both are SEPARATELY_ACTIVATED and are watched
   by the Freshness Fabric.

## Alternatives considered

- **Direct writes from the dashboard.** This would remove the kernel network and file sandbox. Rejected; the owner
  chose the inbox.
- **CLI-only import.** It fails the directive's paste/upload requirement.
- **A separate `intel.sqlite3`.** It would make a deploy a no-op until activation. Rejected: it contradicts "no second
  evidence database" and needs a new backup kind.
- **A news shadow-ledger account.** It needs its own approval, and the fill policy is EXP-001-specific. The journal
  records the same decision-time facts without fills.
- **A systemd `.path` trigger for the inbox.** It has lower latency, but none of the existing install, verify or stop
  tooling knows about `.path` units. A misconfigured processor also fails silently at the trigger limit. A 5-minute
  timer is covered by all of that existing tooling.
- **LLM extraction.** Not authorized (no AI calls). A versioned deterministic taxonomy is auditable, and the manual
  bridge supplies the AI step.

## Tradeoffs

- **Deterministic extraction is crude.** Categories come from keyword rules and entities from capitalized n-grams.
  Both are versioned and labelled heuristic.
- **Books are usually stale.** A 2-hour refresh leaves most books STALE, so their age is shown and an on-demand
  refresh is offered.
- **Deploy migrates the DB.** Deploying migrates the evidence DB to v8 even while the timers stay disabled. Rollback
  uses `mark-v7-for-rollback`.
- **No claimable EV.** Until the fees for a linked series are verified, no EV figure is claimable.

## Reconsider if

- the owner authorizes an inference runtime or AI use of Kalshi data;
- #181 builds `semantic_judgments.py`, in which case the import schema moves there;
- a full-text license is obtained;
- the journal shows a candidate hypothesis worth a DRAFT/QUEUED protocol;
- the inbox needs lower latency than 5 minutes.
