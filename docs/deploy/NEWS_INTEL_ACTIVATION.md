# News intelligence timers: deploy, activation, pause and rollback (owner command sheet)

Lane: #192, ADR 0049 (`docs/decisions/0049-news-intel-slice.md`). Units: `edgelab-news.service` /
`.timer` and `edgelab-news-inbox.service` / `.timer` in `deploy/vps/systemd/`.

**Authority.** The 2026-11-05 entry of `docs/EXECUTION_PLAN.md` authorizes building these units and
shipping them **DISABLED and SEPARATELY_ACTIVATED**. It does **not** authorize deploying to the VPS or
enabling either timer: each is the owner's own decision, recorded in the repository before or with
the step. Nothing in this sheet is run by an agent.

## 1. What a deploy does (even with both timers disabled)

`install.sh` (`deploy/vps/README.md`, "Install or update") does the following for this lane:

- installs the four unit files and runs `systemd-analyze verify` on them. It **never enables** either
  timer: both are in `SEPARATELY_ACTIVATED`, so neither appears in the "Activate the schedule" line it
  prints;
- creates `/var/lib/market-edge-lab/intel-inbox` with `tmp/ new/ work/ done/ rejected/`, owned by
  `edgelab:edgelab`, mode 0700, and checks that the Chase Upside user cannot list it;
- installs the dashboard unit with **one** extra `ReadWritePaths=` entry, the inbox. The dashboard keeps
  `IPAddressDeny=any` and its read-only pin on the evidence DB, and every other hardening line is unchanged.
  A running dashboard picks the new path up only on restart: `sudo systemctl restart edgelab-dashboard.service`;
- **migrates the evidence DB to schema v8** (step 7's first run as the service account). The change is
  additive: three append-only tables, `intel_fetches`, `intel_items` and `intel_records`. Older code
  refuses a v8 store, so a rollback stamps it first (section 6).

Install outside 17:40-18:50 America/New_York, away from the 11:15 / 16:15 ET settlement runs and the
04:40 UTC backup, with no `edgelab-*` unit running, exactly as for every other install.

## 2. Pre-checks (no sudo unless shown)

```bash
systemctl is-enabled edgelab-news.timer edgelab-news-inbox.timer   # expect: disabled, disabled
bash ~/edgelab-release/verify_production.sh | grep -E 'NEWS_TIMER|NEWS_INBOX_TIMER|TIMERS|FRESHNESS'
sudo ls -ld /var/lib/market-edge-lab/intel-inbox /var/lib/market-edge-lab/intel-inbox/new   # edgelab edgelab drwx------
sudo runuser -u edgelab -- /opt/market-edge-lab/venv/bin/python -m edge_lab.cli intel --db /var/lib/market-edge-lab/db/edge_lab.sqlite3 status
```

`intel status` must print JSON with `feed_status_counts`. Before the first verification, every feed
reads UNVERIFIED.

## 3. Verify the sources first (owner, network; outside the protected windows)

A feed is collected only while it is ACTIVE or LIMITED **and** has been verified in the last 14 days.
`verify-sources` reads each feed's robots.txt and makes one GET per collectable feed, with the honest
User-Agent. A robots disallow or a 401/403 makes that source BLOCKED, and no other User-Agent is ever
tried.

```bash
sudo systemd-run --wait --pipe --quiet -p User=edgelab -p Group=edgelab -p Slice=edgelab.slice -p EnvironmentFile=/etc/market-edge-lab/env /opt/market-edge-lab/venv/bin/python -m edge_lab.cli intel --db /var/lib/market-edge-lab/db/edge_lab.sqlite3 verify-sources
```

Expect `{"verified": N, "failed": [...]}`. Read every `failed` entry. If `verified` is 0, stop here:
the timer would only record SKIPPED feeds, and the Freshness Fabric shows the source as PAUSED.

Optionally, run one bounded job by hand (the unit itself, with its caps and its alert):

```bash
sudo systemctl start edgelab-news.service
sudo journalctl -u edgelab-news -n 60 --no-pager
cat /var/lib/market-edge-lab-status/intel.json
```

## 4. Enable the two timers (owner only, after recording the decision)

```bash
sudo systemctl enable --now edgelab-news.timer edgelab-news-inbox.timer
systemctl is-enabled edgelab-news.timer edgelab-news-inbox.timer
systemctl list-timers edgelab-news.timer edgelab-news-inbox.timer
```

You may enable `edgelab-news-inbox.timer` alone (the dashboard handoff only, with no scheduled
collection) or `edgelab-news.timer` alone (in which case the 2-hour run drains the inbox).

**Schedules** (America/New_York):

| Timer | When | Bounds |
|---|---|---|
| `edgelab-news` | 01:32, 03:32, ..., 23:32 (every 2 h) | at most 1 GET per feed and 60 feed GETs; at most 120 Kalshi GETs (quotes of owner-CONFIRMED links only); `TimeoutStartSec=6min` |
| `edgelab-news-inbox` | every 5 min (:03, :08, ..., :58) | no network unless a refresh was queued; then one bounded collection (at most one per 15 min) or one bounded Kalshi read; `TimeoutStartSec=6min` |

The `:32` past odd hours keeps every 2-hour run (at most 6 minutes) clear of the protected windows
(11:13-11:30, 16:13-16:30 and 17:40-18:50 ET), the 04:40 UTC backup and the 10 minutes around the
04:57:45 UTC close tick, in EST and EDT alike. `tests/test_intel_units.py` checks this. The minute is
also clear of every other edgelab timer.

**Protected windows.** They bind Kalshi, not news feeds:

- Kalshi reads (`kalshi_public_intel`) are refused by the code inside the protected windows and within
  10 minutes of the KXHIGHNY close tick.
- The series KXHIGHNY, KXNFLGAME, KXNHLGAME and every KXMVE* series are always refused.
- Feed GETs are not Kalshi and are not refused inside a window. The calendar keeps the scheduled run
  out of them. A news refresh you queue from the dashboard during a window collects feeds then; a quote
  or market-discovery refresh queued then is refused.

## 5. Watch, and pause

What to watch:

- **Heartbeat.** `/var/lib/market-edge-lab-status/intel.json` (schema `intel-heartbeat/1`): `processor`
  (`run` or `inbox`) and `at_utc`. Both units write it after each drain, so it shows the latest of either.
- **Freshness Fabric.** The rows `news_feeds_public` and `intel_inbox` in `freshness.json`:
  - Before activation, both read PAUSED ("not activated").
  - After activation, expect NOT_DUE and, for the news row, FRESH within 3 h of the last successful feed fetch.
  - MISSED means a tick passed with no run.
  - A news row PAUSED after a run means every feed was skipped: verify the sources again (section 3).
  - Whether a timer is enabled is not observable to the fabric. Read it from systemd.
  ```bash
  sudo runuser -u edgelab -- /opt/market-edge-lab/venv/bin/python -m edge_lab.cli freshness status --db /var/lib/market-edge-lab/db/edge_lab.sqlite3 --ledger /var/lib/market-edge-lab/ledger/shadow_ledger.sqlite3 --odds-ledger /var/lib/market-edge-lab/db/odds_quota_ledger.json --status-dir /var/lib/market-edge-lab-status | grep -A12 -E '"source_id": "(news_feeds_public|intel_inbox)"'
  ```
- **Timer state.** `verify_production.sh` prints `NEWS_TIMER` and `NEWS_INBOX_TIMER` separately.
  They are not counted in `TIMERS`, which covers the core schedule.
- **Failures.** A failed run triggers `edgelab-alert@` like every collector unit.
  `sudo journalctl -u edgelab-news -u edgelab-news-inbox --since today --no-pager`.

**Pause** (the evidence, the journal and queued submissions all stay):

```bash
sudo systemctl disable --now edgelab-news.timer edgelab-news-inbox.timer
systemctl is-enabled edgelab-news.timer edgelab-news-inbox.timer   # expect: disabled, disabled
```

While paused, the dashboard still queues at most 20 submissions in `intel-inbox/new/`. They are
handled at the next drain after you resume. Stop at once if a source objects, rate-limits or blocks
the host; never work around a block. The full-stop and rollback lines in
`docs/deploy/DAILY_SHADOW_ACTIVATION.md` and `deploy/vps/README.md` name both timers.

## 6. Rollback to the code before ADR 0049 (v7)

The full procedure, with expected outputs, is "Rollback" in `docs/deploy/DAILY_SHADOW_ACTIVATION.md`.
For a one-step rollback, run the following as root, in order, outside the windows above:

1. Stop **every** timer (the named line in that runbook's step 1, which includes both news timers) and
   check that nothing is running.
2. Run a verified backup: `sudo systemctl start edgelab-backup.service`. Expect `VERIFIED_BACKUP_AND_RESTORE`
   for both stores.
3. Stamp the store v8 → v7, still on the new code, with the timers stopped:
   ```bash
   sudo runuser -u edgelab -- /opt/market-edge-lab/venv/bin/python -m edge_lab.storage mark-v7-for-rollback --db /var/lib/market-edge-lab/db/edge_lab.sqlite3
   ```
   Expect `{"from": 8, "to": 7, ...}`. It refuses (exit 1, nothing changed) anything that is not a
   complete, intact v8 store. The intel tables stay; v7 code ignores them.
4. Restore the previous code and its units, then remove the news units, which v7 does not know:
   ```bash
   sudo rm -f /etc/systemd/system/edgelab-news.service /etc/systemd/system/edgelab-news.timer /etc/systemd/system/edgelab-news-inbox.service /etc/systemd/system/edgelab-news-inbox.timer
   sudo systemctl daemon-reload
   ```
5. Re-enable the timers that were enabled before, then restart the dashboard. Its restored unit no
   longer has the inbox path. The inbox directory may stay; nothing older reads it.

Re-installing the newer code later stamps the store v8 again. The migration is idempotent and keeps
every row.

## 7. Cost and limits

- No key, account, paid API or AI call. The feeds and Kalshi endpoints are public and unauthenticated.
- Runtime: at most 12 runs a day of at most 6 minutes each, plus 288 inbox ticks a day. An empty inbox
  makes no network call and no database write.
- Storage: the store keeps the headline, link, timestamps and a snippet of at most 300 characters per
  item. Raw feed bytes are kept only for US-government public-domain feeds; for every other feed, only
  the hash and size.

## Note: redirects block a feed

Feeds are fetched without following redirects. Any 3xx, even a same-host http→https move, is recorded as
`REDIRECT`, and the feed stays BLOCKED until `edge-lab intel verify-sources` passes again. If a publisher moved a
feed permanently, the fix is a reviewed change to its URL in `src/edge_lab/intel/registry.py`, not a retry.
