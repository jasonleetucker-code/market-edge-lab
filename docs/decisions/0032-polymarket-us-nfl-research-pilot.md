# ADR 0032: Polymarket US NFL research pilot (bounded public discovery and research book captures)

**Status:** Implemented, **disabled.** The access gate is closed; the timers are committed as
`*.timer.proposed`. Authority: the owner directive of 2026-09-24 (evening),
`docs/owner/2026-09-24-freshness-fabric-sports-directive.md`, section 17 items 2 and 3, and
coordinator contract C2.
- **Why disabled.** The terms/access review
  (`experiments/multi_venue/polymarket_us_sports_terms_2026-09-24.md`) did **not** clear
  unattended collection. The directive's pre-enable checklist therefore cannot be completed until
  the owner decides.
- **What this does not authorize:** no account, credential, order path, Polymarket International,
  VPN or geoblock circumvention, paid service or Odds API credit.

## Problem

The directive asks a question: "for an upcoming NFL event, what did major books offer at our
scheduled horizons, and did Polymarket US have a related market at that same point in time?"
- The Odds API side exists (ADR 0029, T-24h / T-6h / T-60m).
- The Polymarket US side needs three things:
  - a bounded way to find NFL markets;
  - a deterministic relationship to the Odds API event, which must never be mistaken for
    equivalence;
  - book captures at the same horizons, with misses kept visible.

Two traps:
- **Treating a filtered catalog as complete.** A market missing from a filtered listing is not
  absent.
- **Treating the same teams as the same contract.** Polymarket US settles a tie at $0.50 and a
  postponement at the last fair market price. A sportsbook voids.

## Alternatives

1. **Unfiltered full catalog (`/v1/markets`) every 6 h.** This is the only listing whose scan can
   be COMPLETE. Rejected: it pages every historical market, resolved ones included, from id 1. It
   is far beyond a 50-request run and is the "bulk download" the Terms prohibit.
2. **The NFL league endpoint (`/v2/leagues/nfl/events`).** Rejected: 40 MB per 50-event page,
   because it embeds about 300 markets per game (fixture read 1).
3. **`/v1/markets` with `tagIds`/`categories` filters.** Rejected: markets carry no tags, so an
   NFL tag filter returned nothing, and the sports category returned one boxing market (fixture
   reads 2 and 4).
4. **`/v1/events` filtered to `tagSlug=nfl`, `closed=false`,
   `sportsMarketTypes=football_team_full_game_winner`, paged to an empty page.** Chosen. It
   returned 33 games with only their moneyline embedded, in 0.34 MB (read 5), then an empty page
   (read 6).
5. **Reuse the ADR 0030 observation tables** (`custom` phase) **and the enabled observe timer.**
   Rejected. It would:
   - share EXP-001's observation budget (24 targets, 40 GETs) and the Kalshi collector lock;
   - start NFL captures the moment targets exist, bypassing the separate activation this pilot
     needs.
6. **Capture spreads and totals too.** Deferred. Each game lists 30 to 40 alternate lines, and
   the listing marks no main line (`eventState` is null). Picking one would be a guess. The right
   extension captures only the lines that exactly match an Odds API offer (Lane C groups offers by
   exact line), after moneylines prove out.

## Decision

- **Module.** `src/edge_lab/polymarket_sports.py`, on `polymarket_us.py`. The only addition to
  the adapter is `events_url` / `read_events_listing`, the `/v1/events` twin of `read_catalog`
  under the same completeness contract. There is no second adapter.
- **Discovery** (`pm-sports discover`, at most every 6 h):
  - reads the filtered listing through a bounded requester;
  - stores every page as an immutable snapshot (`polymarket_us_public`, kind `nfl_events`);
  - records a `pm_sports_scans` row with the coverage state (PARTIAL, a filtered listing),
    `filter_complete` (every page read to an empty page), the page snapshot ids and the derived
    NFL moneyline catalog;
  - drops and reports any returned event without the `nfl` tag and any market that is not the
    full-game winner. The server's filter is checked, never trusted.
- **Relationship** (`relate`): deterministic and versioned (`pm-odds-relationship-v1`). It
  compares against the latest stored Odds API NFL discovery (quota-free; no credit is spent).
  - **RELATED_NOT_EQUIVALENT** needs exactly one Odds API event with the same two teams (exact
    full names) within 36 h, and a kickoff within 15 minutes.
  - **AMBIGUOUS:** several candidates, one team only, a kickoff that differs by more than the
    tolerance, different New York dates, or a missing start time or team names.
  - **UNMATCHED:** no event with both teams, or only a rematch further than 36 h away.
  - Recorded checks: teams, date, start time, league, home/away (UNVERIFIED: Polymarket US has
    no documented field), and every rule dimension (overtime, ties, postponement / cancellation /
    no-contest, participant start, settlement source). The rule dimensions are UNVERIFIED because
    Odds API offers carry no rules text. Alternative settlement and payout structure DIFFER.
  - PAYOFF_UNSUPPORTED and RULES_UNRESOLVED are kept as flags.
  - No equivalent state exists: not in the code, and not in the schema (a CHECK constraint).
- **Targets:**
  - Offsets: T-24h / T-6h / T-60m before the market's `gameStartTime`
    (`odds_schedule.DEFAULT_OFFSETS`).
  - Due window: from 7 min before to 30 min after, and never within 5 min of kickoff.
  - A target falling in a protected window (11:13-11:30, 16:13-16:30, 17:40-18:50 ET, from
    `price_observations`) moves to the window's end, or before it if the end is too late.
  - Only RELATED_NOT_EQUIVALENT markets get targets.
  - Each target is written once, with its intended and effective times. A moved kickoff makes
    the open targets SUPERSEDED, and new targets carry new ids.
  - More than 20 markets in one slot (the same offset and time) are SKIPPED_CAP, visibly.
- **Captures** (`pm-sports capture`, every 15 min at :10/:25/:40/:55 ET):
  - planning is network-free, then expired targets are marked MISSED with the reason, then one
    book GET is sent per due target;
  - a CAPTURED row keeps the YES bid, ask and sizes, the listed levels (marked truncated), the
    book state, `transactTime`, the receipt time, the deviation from the intended time, and the
    snapshot;
  - a malformed, crossed, foreign or non-open book is NOT_EXECUTABLE, keeping the snapshot;
  - a 404 is NOT_EXECUTABLE BOOK_NOT_FOUND (final);
  - a transient failure is FAILED and retried at the next tick until the deadline;
  - nothing is fetched after its deadline;
  - captures pause when the catalog is older than 24 h, and the MISSED reason says so.
- **Caps**, lower than the directive's where the architecture allows:

  | Cap | Directive | Pilot | Why |
  |---|---|---|---|
  | markets per slot | 20 | 20 | the directive's value; the heaviest Sunday slot is about 10 games |
  | GETs per run | 50 | 50 HTTP attempts, **retries included**; books 20; discovery 12 | stricter than counting logical GETs |
  | pacer | 0.5 s or slower | **1.0 s** | 5% of the documented 20/s; the Terms forbid disproportionate load |
  | runtime | 5 min hard | **3 min** run deadline; unit `TimeoutStartSec=5min` | lets the 11:10 and 16:10 ET ticks finish before the settlement windows |
  | retries | bounded | **1** per request (transient only) | 429 and 5xx only; a 404 is final |
- **Lock.** `<db>.pm-sports.lock`, shared by discovery and capture, and **not** the Kalshi
  collector lock.
  - Justification: the pilot uses no Kalshi pacer. Sharing that lock would make NFL reads contend
    with EXP-001 captures and observations.
  - Polymarket US reads from `observe` (ADR 0030) use a separate process pacer. The combined worst
    case, 1/s plus 2/s, is 15% of the per-IP limit.
- **Exit codes.** Non-zero only for a genuine, non-retryable failure:
  - a FAILED target that no later unprotected tick can retry before its deadline;
  - a discovery failure that has just left captures without a catalog less than 24 h old (once,
    on that transition);
  - an unexpected error.

  Refusals exit 0: the terms gate, a protected window, lock busy, not due, budget, deadline.
- **Access gate.** `OWNER_ACCESS_DECISION = None` refuses every networked run before the network
  (BLOCKED_TERMS_REVIEW, exit 0, nothing written). Lifting it is a reviewed code change that
  references the owner's recorded decision.
- **Storage:** evidence schema **v7**, additive (`pm_sports_scans`, `pm_sports_targets`,
  `pm_sports_observations`, with triggers on those tables only).
  - Rollback: `python -m edge_lab.storage mark-v6-for-rollback --db PATH`. The real v6 code
    (`e6dfb69`) opens and backs up a stamped store VERIFIED (a test).
  - Registry: `polymarket_us_nfl_discovery` and `polymarket_us_nfl_book` (health ids, PLANNED).
- **Freshness Fabric (C1).** `freshness_records` gives discovery (POLL) and capture
  (EVENT_RELATIVE) records; `fabric_provider(context, now)` is the provider (see "Coordinator
  integration").
- **Terminal (Lane D).**
  - `polymarket_sports.terminal_view(db_path, now=...)` (schema `pm-sports-status/1`, read-only,
    never raises).
  - Or `related_markets(store, now=...)`: per Odds API event id, the related markets with state
    RELATED_NOT_EQUIVALENT / AMBIGUOUS / NO_RELATED_MARKET, flags, checks and the latest research
    capture; also `catalog_state`.
  - Every payload carries the label "RELATED MARKET — NOT ECONOMICALLY EQUIVALENT", with
    `executable: false`, `ranked: false` and `absence_is_evidence: false`.

## Worst case: requests, runtime, storage (measured sizes from the 2026-09-24 fixtures)

- **Requests:**
  - discovery: at most 12 HTTP attempts per run (6 pages with one retry each); typically 2 GETs;
    4 runs a day, so at most 48 a day;
  - captures: at most 50 attempts per run (20 books with one retry each is 40); 96 ticks a day,
    but GETs are sent only for due targets;
  - targets are at most 3 per related market, and markets at most 300 per listing (the page cap);
  - a real NFL week (about 16 games) is about 48 book GETs a week; the heaviest day (Sunday) is
    at most about 30.
- **Runtime:**
  - captures: 20 books at a 1 s pacer take about 25 s;
  - worst case: the 3-minute run deadline (no request starts with less than 3 s left; a request
    times out after at most 10 s), inside the unit's hard 5-minute stop;
  - discovery: about 3 s typical.
- **Storage:**
  - one 50-event page is about 0.5 MB stored (the 33-game page was 332 KB as canonical JSON), and
    the scan's derived catalog is about 35 KB;
  - typical: about 0.37 MB per scan, 4 a day, so about 1.5 MB a day, about 45 MB a month;
  - worst case (300 events, 6 full pages): about 3.6 MB per scan, about 14.5 MB a day, about
    435 MB a month;
  - a book is about 3.5 to 5 KB, plus about 3 KB of levels in its row: about 0.4 MB a week in a
    real week, and at most about 7 MB for a full 300-market listing horizon.
  - If disk becomes a concern, lower the discovery cadence before anything else.

## Shutoff

- **Stop now:**
  `sudo systemctl disable --now edgelab-pm-sports.timer edgelab-pm-sports-discover.timer`, once
  the timers are installed.
- **Close the gate in code:** set `polymarket_sports.OWNER_ACCESS_DECISION = None` and deploy.
  Every run then refuses before the network.
- **Roll the schema back:** stop the timers, then
  `python -m edge_lab.storage mark-v6-for-rollback --db /var/lib/market-edge-lab/db/edge_lab.sqlite3`,
  then deploy the v6 code. Nothing is deleted. Re-installing v7 code stamps v7 again.

## Tradeoffs

- **The filtered listing is never COMPLETE.** An NFL game Polymarket US lists under another tag,
  closes early, or hides is invisible. NO_RELATED_MARKET is therefore only "none within the
  filtered listing", and `absence_is_evidence` is always false.
- **Team names must match exactly.** A renamed franchise or a different spelling becomes UNMATCHED
  or AMBIGUOUS, never a forced match. That is correct, but it can lose captures until a
  deterministic alias table exists.
- **Moneyline only.** No spread or total comparison yet.
- **Research only.** A captured book is not an executable price claim: the depth is marked
  truncated and the payoff unsupported. The pilot is never compared with or ranked against a
  sportsbook offer.
- **Schema v7.** Every read-only consumer must run v7 code (the usual deploy order). The v6 → v5
  → v4 rollback tests now hold "the current code" at v6.

## Reconsider when

- the owner records an access decision, or Polymarket US grants or denies written permission;
- Polymarket US publishes an API or data licence, a main-line marker, or a total or cursor on its
  listings;
- the Terms change (re-read and re-hash source 21 of the review);
- a measured week shows the caps are too tight or too loose, or discovery storage matters.

## Coordinator integration (not done by this lane)

- **install.sh (Lane A / coordinator).**
  - Extend the separately activated set to a list, for example
    `SEPARATELY_ACTIVATED=(edgelab-odds edgelab-pm-sports edgelab-pm-sports-discover)`, and build
    CORE_TIMERS by membership.
  - Add both pilot units to `UNITS`.
  - Rename the two `*.timer.proposed` files to `*.timer` in the same change.
  - Update `tests/test_deploy_units.py`: its `SEPARATELY_ACTIVATED=edgelab-odds` assertion, and
    `tests/test_polymarket_sports_units.py::test_the_installer_does_not_know_or_enable_the_pilot_timers`.
- **Freshness Fabric registry.** Add one line: `polymarket_sports.fabric_provider`, with context
  `{"db_path": ...}`, once `freshness.SourceFreshness` exists.
- **Runbook, HANDOFF and verify_production (coordinator):**
  - a v7 → v6 rollback step, `mark-v6-for-rollback`, before the existing v6 → v5 one;
  - an activation section: owner access decision, the gate code change, enabling both timers,
    and verifying one discover and one capture from stored rows;
  - a verify_production state for the two timers (installed/disabled) and the latest scan's
    coverage;
  - an index line for this ADR in `docs/decisions/README.md`;
  - source rows in `docs/DATA_PROVENANCE.md`.
