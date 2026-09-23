# Production activation record, 2026-09-23

Directive: `docs/owner/2026-09-23-production-activation-directive.md`.
Procedure: `docs/deploy/DAILY_SHADOW_ACTIVATION.md`, followed step by step with no other
procedure. Operator: the owner's local Claude Code session, over the owner's existing SSH
access to `chaseupside` (host `vmi3454985`). It ran as `dynasty` by default, and as root only
for the sheet's privileged steps and read-only journal reads. No keys, SSH configuration,
sudo rules, packages or Brisket units were changed, and there was no reboot.

Every state is reported separately, as observed. One state never implies another.

## 1. Before installing (13:25–13:28 EDT)

| State | Observed |
|---|---|
| NY time / running units | 13:25:25 EDT; no `edgelab-*` unit running |
| DEPLOYED_SHA (before) | `9326a7a077fac7f352e0e6a5b686e6de98e1e978` (collector only) |
| Timers | 5 enabled: pfm 17:45, decision 17:55:05, recheck 18:05, status 18:30 ET, backup 04:40 UTC |
| PFM / DECISION / RECHECK capture observed | NO. None of these units had ever run on schedule: the collector was installed at 02:09 UTC, after the 2026-09-23 window. The first window is 2026-09-23 17:45 ET (target 2026-09-24). |
| Only edgelab failure | `edgelab-decision` 02:09:55Z: the install-time fail-closed test (`rejected_out_of_window`, 0 records), as intended |
| latest.json | `last_closed_target_date` 2026-09-23 INVALID (no pfm, no decision capture: the collector was not yet installed for that window) |
| COLLECTOR_HEALTH | verifier: INVALID (last closed day). Judged not unhealthy for the stop condition: timers enabled, units loaded, fail-closed behaviour correct, backup VERIFIED at 04:40Z, and no window had yet occurred |
| Backup 04:40Z | evidence DB `VERIFIED_BACKUP_AND_RESTORE` |
| Brisket | nginx, dynasty, dynasty-frontend, docker active; `/api/health` HTTP 200 (0.12 s) |
| Resources | 6.5 of 7.9 GB available; PSI memory 0.00, cpu 0.18, io 1.67 (avg10); disk 34 %; OOM kills (30 d) 0; host booted 2026-09-23 02:06 UTC |
| Other failed units (not Market Edge; not touched) | 6 Brisket `dynasty-*` refresh services in `failed` state (depth-charts, dlf-fetch, injury-feed, playerctx, sharp-cohort-snapshot, trending-history). Reported for the owner. |
| Preflight (`preflight.sh`) | PASS: memory, worst-case fit, disk, inodes, load, systemd 255, NTP, tzdata, Python 3.12.3, git |

## 2. Install and dry runs (13:28–13:29 EDT)

| Step | Result |
|---|---|
| Staging | Bundle of `247fe80f7a745eb5489d2d4027c0348dc9ec93aa` plus `install.sh`, `preflight.sh`, `verify_production.sh`. sha256 is identical on laptop and VPS. The previous release files were kept in `~dynasty/edgelab-release/prev-9326a7a/` |
| Backup before install | `edge-backup-o2bpi1h8`: `VERIFIED_BACKUP_AND_RESTORE` |
| **INSTALLED** | `INSTALL OK: 247fe80…`. Previous code kept in `/opt/market-edge-lab/app.prev`. 15/15 permission checks ok: private data, DB, backups and ledger are unreadable to `dynasty`; the status file is readable |
| **FAIL_CLOSED_VERIFIED** | `edgelab-decision` at 17:28:27Z gave `rejected_out_of_window`, 0 records, target 2026-09-24, window [21:55:00Z, 21:59:30Z]; `reset-failed` done |
| Shadow dry run | `INVALID_CAPTURE`, exit 3, for 2026-09-23. See the note below |
| Settlement refresh | exit 0; `refresh.status = skipped` ("no open position is due for settlement"): no GET |
| **EVIDENCE_BACKUP** / **EVIDENCE_RESTORE** | `edge-backup-eqfiomf5`: `VERIFIED_BACKUP_AND_RESTORE`, schema v4. The temporary restore reproduced row counts (collection_runs 2, forward_captures 2) |
| **LEDGER_BACKUP** / **LEDGER_RESTORE** | `ledger/edge-backup-lqs5j63_`: `VERIFIED_BACKUP_AND_RESTORE`, schema v1, ledger_entries 2 (the two account openings), database sha256 `3bca10d3…7758` |
| Resource limits | `edgelab.slice` MemoryMax 384 MiB, MemoryHigh 320 MiB, CPUQuota 25 %, TasksMax 64. All 7 services run as `edgelab` in the slice, 256 MiB cap each |
| **SHADOW_TIMER** | enabled; 18:40 America/New_York |
| **SETTLEMENT_TIMER** | enabled; 11:15 and 16:15 America/New_York |

**Note on the shadow dry run.** The sheet expects `NO_CAPTURE` or `NOT_CLOSED` before the
first live day. The receipt said `INVALID_CAPTURE` (exit 3, alert) for 2026-09-23, because
the install-time fail-closed test at 02:09Z wrote a rejected capture record for that closed
day. The classification is true: 2026-09-23 has no valid evidence. It alerted once, and the
next run's identical condition was deduplicated (`repeat_of_previous_alert`). The sheet's
expectation should mention this case.

## 3. After install: verifier as root (13:29:36 EDT)

```
DEPLOYED_SHA: 247fe80f7a745eb5489d2d4027c0348dc9ec93aa
TIMERS: 7/7 enabled
UNIT_RESULTS: failed units: none
COLLECTOR_INSTALLED: YES; TIMERS_ENABLED: YES
COLLECTOR_HEALTH: INVALID (last closed day 2026-09-23; no pfm/decision capture: pre-first-window)
PFM/DECISION/RECHECK_CAPTURE_OBSERVED: NO (journal readable; none in 48 h)
VALID_DAY_OBSERVED: NO
BACKUP_EVIDENCE_DB: CREATED edge-backup-eqfiomf5; RESTORE_EVIDENCE_DB: VERIFIED
BACKUP_SHADOW_LEDGER: CREATED ledger/edge-backup-lqs5j63_; RESTORE_SHADOW_LEDGER: VERIFIED
JOURNAL_WARNINGS_24H: 8 (all the deliberate dry-run failures and their alerts)
OOM_30D: 0; MemAvailable 6508 MB; edgelab.slice MemoryPeak 31 MiB of 384 MiB
CHASE_UPSIDE_HEALTH: HEALTHY (4/4 units active; /api/health HTTP 200)
```

## 4. GATE7-F09: first independent ledger-head checkpoint

| Step (GATE7_FINDINGS "Closing GATE7-F09") | Evidence |
|---|---|
| 1. Code merged and deployed | `shadow anchor` ships in `247fe80`, deployed as above |
| 2. Export as `edgelab`, read-only | `sudo -u edgelab …/python -m edge_lab.cli shadow anchor export --ledger /var/lib/market-edge-lab/ledger/shadow_ledger.sqlite3` at 17:30:09Z. Ledger sha256 `0ba2b871…46d4` was identical before and after. `checkpoint_sha256` `487c744d19127c18bd318eac3036cd673326f7585104500ff174e9895022d08e`. Heads: research seq 1 `94acf0d5…fe1f`, shadow seq 2 `a8ad0fd6…3bec` |
| 3. Stored independently of the VPS | (c) the owner-held off-host copy on the owner's laptop, outside the repository and the production tree (`C:\Users\jason\market-edge-anchors\2026-09-23\`); the temporary VPS copy in `/tmp` was deleted. (d) committed to this private repository: `docs/engineering/ledger_checkpoints/2026-09-23T173009Z.json` |
| 4. Verify of the production ledger against the independent copy | The off-host copy was sent back to `/tmp` and `shadow anchor verify` run as `edgelab` on the live ledger: VERIFIED, "head unchanged", both accounts. Ledger sha256 unchanged by the verify; the temporary file was deleted |
| 5. Off-host verification | The backup bundle `ledger/edge-backup-lqs5j63_` (database sha256 `3bca10d3…7758`, equal to its manifest) was copied to the laptop. `shadow anchor verify` ran there from a clean checkout at the reviewed SHA `247fe80`: **VERIFIED**, both accounts "head unchanged" (output kept beside the off-host copy) |

What this proves: head truncation of the history up to checkpoint `487c744d…` is now
detectable under ADR 0021's attacker models:
- A1 and A3, by verifying on the VPS;
- A2, by verifying off-host;
- A4, by the laptop copy;
- A5, by the Git copy.

What it does not prove: anything about entries appended after 17:30:09Z. That residual gap is
accepted in ADR 0021 and shrinks only when a newer checkpoint is exported and stored the same
way. It is manual; no scheduled anchor is authorized. The history anchored today is only the
two account openings, so the next checkpoint, after the first real shadow day, is the one
that matters.

## 5. Redeploy of the newest reviewed main (13:55–13:57 EDT)

PR #42 (payoff guard, price grids, Polymarket US ladders) merged as `6e2031c`, which touches
the shadow path's engine. Production was redeployed with the same sheet so that the deployed
SHA equals merged `main` before the first window.

| Step | Result |
|---|---|
| BEFORE verifier (13:55 EDT) | DEPLOYED_SHA `247fe80`; 7/7 timers; no failed units; backups and restores VERIFIED; OOM 0; memory PSI 0.00; CHASE_UPSIDE_HEALTH HEALTHY; capture states NO (no window yet) |
| Staging / preflight | bundle `6e2031c`, sha256 identical on both ends; the previous release was kept in `prev-247fe80/`; PREFLIGHT: PASS |
| Backup before install | evidence `edge-backup-krsk9s17` and ledger `ledger/edge-backup-fil1f16s`: VERIFIED_BACKUP_AND_RESTORE |
| **INSTALLED** | `INSTALL OK: 6e2031c…`; `app.prev` = `247fe80`; 15/15 permission checks ok; all 7 timers kept enabled |
| **FAIL_CLOSED_VERIFIED** | 17:57:01Z `rejected_out_of_window`, 0 records, target 2026-09-24 |
| Shadow dry run | `INVALID_CAPTURE` for 2026-09-23, exit 0 (`repeat_of_previous_alert`), `code_version` 6e2031c |
| Settlement refresh | `skipped`, no GET |
| **EVIDENCE_BACKUP / EVIDENCE_RESTORE** | `edge-backup-mlj3ys07`: VERIFIED (collection_runs 3, forward_captures 3) |
| **LEDGER_BACKUP / LEDGER_RESTORE** | `ledger/edge-backup-al5aeq08`: VERIFIED (ledger_entries 2; database sha256 `3bca10d3…7758`, unchanged) |
| Slice | MemoryMax 384 MiB, MemoryHigh 320 MiB, CPU 25 %, TasksMax 64 |
| AFTER verifier (13:57 EDT) | DEPLOYED_SHA `6e2031c0c7ff1ba6dfd61fac99dab8ee3bb98a45`; 7/7 timers; SHADOW_TIMER next 18:40 ET; SETTLEMENT_TIMER next 16:15 ET; COLLECTOR_HEALTH INVALID (pre-first-window); PFM/DECISION/RECHECK_CAPTURE_OBSERVED NO; VALID_DAY_OBSERVED NO; OOM 0; MemAvailable 6496 MB; JOURNAL_WARNINGS_24H 11 (all deliberate dry-run failures); CHASE_UPSIDE_HEALTH HEALTHY |
| F09 re-check | The off-host checkpoint was verified again, off-host, against the newest backup `al5aeq08` (copied to the laptop, sha256 equal to its manifest): VERIFIED, both accounts "head unchanged" |

## 6. Concurrent deploy of `afa3ce9` by another session (14:28 EDT), and its verification

A second local session, under the owner's Tailscale private-dashboard directive
(`docs/owner/2026-09-23-tailscale-private-dashboard-directive.md`, PR #46, ADR 0024), took
the following host-side steps. They are recorded here because they changed production:

- installed Tailscale 1.102.4 (`--netfilter-mode=off --accept-dns=false`; no Funnel, no
  Tailscale SSH);
- deployed merged `main` `afa3ce9`, which includes PR #45 (the SnapshotStore
  connection-closing and Windows fixes) and PR #46;
- started the read-only `edgelab-dashboard.service` (127.0.0.1:8765 behind Tailscale Serve).

Both sessions agree. The PR #45 review found no blocker and showed that the WAL
checkpoint-on-close already happened on older code, whenever garbage collection ran; this
session had planned to hold #45 until after the first window.

That install ran no backup before it and no fail-closed test on the new code. This session
made those checks on `afa3ce9` at 14:35 EDT:

| Check | Result |
|---|---|
| DEPLOYED_SHA | `afa3ce90b9119343c07e5d99afc6647ddf4799e3`; `app.prev` = `6e2031c` |
| Running units | `edgelab-dashboard.service` only; it is read-only and exempt from the install check (see the activation sheet) |
| **FAIL_CLOSED_VERIFIED** | 18:35:02Z `rejected_out_of_window`, 0 records |
| **EVIDENCE_BACKUP / RESTORE** | `edge-backup-fx7f_vy4`: VERIFIED (forward_captures 4, all fail-closed test records, 0 real captures) |
| **LEDGER_BACKUP / RESTORE** | `ledger/edge-backup-w1vi57wj`: VERIFIED (ledger_entries 2) |
| Timers / failed units | 7/7 enabled; none failed |
| CHASE_UPSIDE_HEALTH | HEALTHY; MemAvailable 6445 MB; OOM 0 |

## 7. Deploy of `7aac49c`, the final merged main before the window (14:58–14:59 EDT)

PRs #43 (execution-ticket control checks, data only) and #44 (ntfy sink, disabled and not
wired) merged. Neither is on a production code path. Production was brought to merged
`main`, so the code running the first window is exactly what is reviewed on `main`.

| Step | Result |
|---|---|
| Staging / preflight | bundle `7aac49c`, sha256 identical on both ends; previous release in `prev-6e2031c/`; PREFLIGHT: PASS |
| Backup before install | `edge-backup-1q6ozcdh` and `ledger/edge-backup-yfp8r63p`: VERIFIED |
| **INSTALLED** | `INSTALL OK: 7aac49ce…`; timers keep their state |
| **FAIL_CLOSED_VERIFIED** | `rejected_out_of_window`, 0 records |
| Shadow / settlement dry runs | receipt `INVALID_CAPTURE`, exit 0 (dedup), `code_version` 7aac49c; refresh `skipped` |
| **EVIDENCE_BACKUP / RESTORE** | `edge-backup-60gum0bz`: VERIFIED |
| **LEDGER_BACKUP / RESTORE** | `ledger/edge-backup-_rpjz1bo`: VERIFIED (ledger_entries 2) |
| Dashboard | restarted after install (sheet exception); listening in about 5 s; HTTP 200 locally and for the tailnet Host |
| AFTER verifier (14:59:39 EDT) | DEPLOYED_SHA `7aac49ceffdcec2c9effe3bd896d63f19c9f17da`; 7/7 timers; no failed units; running: dashboard only; SHADOW_TIMER next 18:40 ET; SETTLEMENT_TIMER next 16:15 ET; COLLECTOR_HEALTH INVALID (pre-first-window); captures observed NO; VALID_DAY NO; OOM 0; MemAvailable 6368 MB; edgelab.slice peak 49 MiB of 384 MiB; CHASE_UPSIDE_HEALTH HEALTHY |

## 8. First real window (2026-09-23 17:45–18:30 ET, target 2026-09-24)

Code running the window: `7aac49c` (equal to `main` at the time). Read at 18:46–18:48 EDT,
as root, read-only; the evidence DB and ledger were opened `mode=ro` as `edgelab`.

**Captures (target 2026-09-24, event `KXHIGHNY-26SEP24`):**

| Unit | Result | Evidence |
|---|---|---|
| `edgelab-pfm` 17:45 ET | success | capture 6 `complete` at 21:45:05Z, window [21:30, 21:54]Z. 1 `pfm_list` plus 6 `pfm_product` snapshots; selected forecast max 68 °F (extract sha256 `05eb07dd…`) |
| `edgelab-decision` 17:55:05 ET | success | capture 7 `complete` at 21:55:11Z, window [21:55:00, 22:00:00]Z. 1 event, 1 market list, 6 order books (one per bracket) |
| `edgelab-recheck` 18:05 ET | success | capture 8 `complete` at 22:05:16Z, window [22:05:08, 22:10:11]Z. 6 order books |
| `edgelab-status` 18:30 ET | success | `latest.json`: `last_closed_target_date` 2026-09-24 **VALID**, `last_closed_reasons` [], `first_valid_day` 2026-09-24, `valid_days` 1; `invalid_days` [2026-09-23] (the pre-install day) |

**Shadow bookkeeping (`edgelab-shadow` 18:40 ET, receipt `shadow_daily.json`, code 7aac49c):**
receipt state `PENDING_SETTLEMENT`, exit 0; latest day 2026-09-24 VALID, `HEALTHY_TRADED`;
problems none.

| | research (frozen EXP-001 rule) | operational shadow |
|---|---|---|
| decisions | 12 (6 brackets × 2 sides) | 12 |
| qualified | 2 | 2 |
| fills | 2 | 2 |
| NO_FILL by reason | none | none |
| risk vetoes | 0 | 0 |
| starter-policy (policy) vetoes | n/a | 0: not yet in effect (the decision was 2026-09-23T21:55Z; `STARTER_MAX_7D_V1` applies from 2026-09-24T00:00Z) |
| pending settlement | 2 positions | 2 positions |
| committed / settled cash | 0.67 / 99,999.33 | 0.67 / 999.33; risk: no breaches, remaining capacity 9.33 |

Qualified and filled (1 contract each, at the decision ask, confirmed by the recheck):
- **B66.5 NO** at 0.56: model 0.747, net edge +0.167, fee 0.017248, cost 0.58.
- **B70.5 YES** at 0.08: model 0.187, net edge +0.097, fee 0.005152, cost 0.09.

Rejected:
- 9 decisions with NO_EDGE;
- T73 NO with INSUFFICIENT_SIZE (nothing offered).

Every decision is `claimable` under the fee record's CONSERVATIVE_BOUND basis (ADR 0017),
which subtracts 0.0101 USD per contract from any claim. Settlement: none yet. The
settlement timer refreshes 11:15 and 16:15 ET once positions are due.

This is one day of pipeline evidence, not evidence of an edge.

## 9. Second F09 checkpoint (after the first real shadow day, 18:47–18:48 EDT)

- **Backup first:** `edge-backup-h0wn8olk` (evidence: forward_captures 8, snapshots 21) and
  `ledger/edge-backup-sdi31qqw` (ledger_entries 30), both VERIFIED_BACKUP_AND_RESTORE.
- **Export** as `edgelab`, read-only (ledger sha256 unchanged):
  - checkpoint `89581b5af4d1498fb6632247d9b6186b93cb4edb2fbf3d287b4c13a34fb0e7d2`;
  - created 2026-09-23T22:47:20Z;
  - research 15 entries (head seq 16), shadow 15 entries (head seq 30).
- **Stored off-host:**
  - (c) the owner's laptop folder `market-edge-anchors/2026-09-23/` (outside the repository
    and the production tree);
  - (d) this repository, `docs/engineering/ledger_checkpoints/2026-09-23T224720Z.json`.

  The temporary VPS copy was deleted.
- **Verify, live production ledger vs the off-host copy (on the VPS):** VERIFIED, "head
  unchanged"; ledger sha256 unchanged.
- **Verify off-host:** backup `sdi31qqw` copied to the laptop (database sha256
  `1facc7a8…772f`, equal to its manifest). `anchor verify` from a clean checkout at the
  deployed SHA `7aac49c`:
  - against the new checkpoint: **VERIFIED**;
  - against the first checkpoint: **EXTENDED** ("history intact; 14 entries appended since
    the checkpoint").

## 10. Dashboard deploy by the Terminal v1 session (after 18:50 EDT)

Reported by the Terminal v1 session (PR #49); the Brisket state was independently re-read
by this session at 18:56 ET.

| Step | Result |
|---|---|
| DEPLOYED_SHA | before `7aac49c`, after `f646481ef3d095d877ee9de814bbd9edec021f10` (INSTALL OK 18:52 ET); `app.prev` = `7aac49c`; release files kept in `prev-7aac49c/` |
| Backup before install (18:51:49 ET) | `edge-backup-36jle2zs` and `ledger/edge-backup-b37xdtvk` (ledger_entries 30): VERIFIED_BACKUP_AND_RESTORE |
| **FAIL_CLOSED_VERIFIED** | 18:52:32 ET `rejected_out_of_window`; reset-failed. `last_failure.json` now names this test |
| Dashboard | restarted; all routes 200 on loopback, foreign Host 400, POST 405; tailnet URL serves the new release; Serve unchanged (tailnet only, no Funnel) |
| Verifier (18:55 ET) | DEPLOYED_SHA f646481; 7/7 timers; no failed units; **COLLECTOR_HEALTH VALID** (last closed 2026-09-24); **PFM/DECISION/RECHECK_CAPTURE_OBSERVED YES**; BACKUP/RESTORE both stores VERIFIED; OOM 0 |
| **CHASE_UPSIDE_HEALTH** | **UNHEALTHY**: `/api/health` HTTP 503 `"status":"degraded"` |

**Brisket degradation (not Market Edge; not touched).**
- **Cause:** the health body says `"contract_ok": false`, Brisket's own data-contract check.
  Everything else reads healthy:
  - `data_stale` false, last Brisket scrape 22:47:44Z;
  - circuit breakers closed, startup checks 8/8 ok;
  - nginx, dynasty, dynasty-frontend and docker all active.
- **When:** it was HEALTHY at this session's 14:59 ET verifier and already degraded at the
  Terminal session's 18:51 pre-install verifier, so it began before that install. The timing
  fits the Brisket scrape that finished at 22:47:44Z.
- **Host:** memory PSI 0.00, MemAvailable 6451 MB, no OOM, `edgelab.slice` 23.6 MiB.
  Nothing in the host resources points to Market Edge.
- **For the owner:** Brisket's data-contract failure needs its own look.
