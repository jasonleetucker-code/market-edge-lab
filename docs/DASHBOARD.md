# Local read-only dashboard

Authority: owner directive 2026-09-23, PRIORITY 5 (`docs/owner/2026-09-23-daily-shadow-directive.md`).
Code: `src/edge_lab/dashboard/`. Tests: `tests/test_dashboard.py`.

## Purpose

One place to see, on a laptop or phone browser, what the shadow operation is doing: collector
freshness, the daily pipeline receipt, shadow decisions and simulated fills, pending
settlements, risk and capital, the Outcome Board, experiment status, source health and fee
verification.

It is **SHADOW, NO REAL MONEY**. Every page says so in a banner. It never places orders,
never writes to any store, and never recommends a withdrawal.

## Stack, and why

| Choice | Reason |
|---|---|
| Python stdlib only (`wsgiref`, `html`, `sqlite3`) | The runtime rule is stdlib-only (`AI_INSTRUCTIONS.md`). The page count is small and needs no template engine or framework, so a dependency buys nothing. |
| A WSGI application (`edge_lab.dashboard.app.make_app(config)`) | WSGI is the standard interface. If hosting is ever authorized, a real server (gunicorn, uWSGI, a reverse proxy) can run the same callable. We do not build our own production server. `wsgiref` is only the local development server. |
| Server-rendered HTML, inline CSS, no JavaScript | No build step, no client code to audit. A strict CSP (`default-src 'none'; style-src 'unsafe-inline'`) forbids scripts, images, frames and forms. |
| Bound to `127.0.0.1` | It is local-only. Public exposure, tunnels, DNS/TLS and firewall changes are not authorized. A non-loopback `--host` is refused unless `--allow-non-loopback` is passed, and that prints a warning. |
| Host header must be local | A request whose `Host` is not `localhost`, a 127.0.0.0/8 address or `::1` (or the explicitly approved `--host`, matched literally: with `--host 0.0.0.0` only `Host: 0.0.0.0` is accepted, not a LAN address) gets 400. Malformed values (a non-numeric port, text after `]`) are refused. This stops a web page from reading the dashboard by pointing its own domain at 127.0.0.1 (DNS rebinding). |
| No authentication | Nothing is exposed, so there is no one to authenticate. We do not build a custom auth system. If exposure is ever authorized, authentication belongs in the front server (see "Limitations"). |

## Data sources (all read-only, all optional)

| Flag | Source | How it is read |
|---|---|---|
| `--db` | evidence SQLite store | `SnapshotStore.open_readonly` (SQLite `mode=ro` + `query_only`); `forward.summary`, `latest_source_health` |
| `--ledger` | shadow ledger SQLite file | `ShadowLedger.open_readonly`; `accounts`, `entries`, `state` (hash-chain replay) |
| `--status-dir` | `latest.json` (collector), `shadow_daily.json` (pipeline receipt), `last_failure.json` | JSON, fixed names only, 2 MB cap, every field optional |
| `--experiments-root` | `experiments/` (defaults to this checkout's) | `experiments.validate_all` / `load`; Stage A result JSON; report **file names** only |

Figures come from the canonical modules only: `shadow_ledger.replay` (balances, P&L),
`risk.assess` with `exp001_shadow.RISK_POLICY`, `risk.withdrawal_assessment` (always
NOT_RECOMMENDED), `outcome_board.build_board`, and `fee_schedules`. The dashboard has no ledger,
risk engine or fee model of its own.

A source that is not configured or does not exist shows **NO DATA / NOT STARTED** with the
reason. It never shows zeros. A source that cannot be read shows **ERROR** with a one-line
message: no traceback, no directory paths (only file names), no environment values. A status
file older than 26 hours, or with a missing or future timestamp, is flagged **STALE** or
**UNKNOWN** (`edge_lab.freshness.assess`).

## Fresh-install runbook

```bash
git clone https://github.com/jasonleetucker-code/market-edge-lab.git
cd market-edge-lab
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .
python -m edge_lab.dashboard \
    --db data/edge_lab.sqlite3 \
    --ledger data/shadow_ledger.sqlite3 \
    --status-dir data/status
```

Open <http://127.0.0.1:8765>. Stop with Ctrl+C. Every flag is optional: with none, every page
renders NO DATA panels. `--port` changes the port.

To look at the pages without real data:

```bash
python -m edge_lab.dashboard --demo
```

`--demo` builds a synthetic ledger, evidence store and status files in a **new temporary
directory** through the real `ShadowLedger`/`SnapshotStore` APIs. It ignores `--db`, `--ledger`
and `--status-dir`, never opens them, and deletes its temporary directory on exit. Every page
carries a large **SYNTHETIC DEMO DATA** watermark. Synthetic market ids start with `DEMO-`.
The experiment registry in demo mode is the real, read-only repository manifest, and the page
says so.

## Viewing VPS data safely

The VPS collector is the production capture source. Do not run the dashboard there with an
open port, and do not expose it.

1. Copy **non-sensitive status JSON** to the laptop, for example
   `scp vps:/var/lib/market-edge-lab-status/latest.json ./data/status/`, and the same for
   `shadow_daily.json` once the pipeline writes it.
2. For ledger or evidence views, copy a **backup** (not the live file) produced by the
   existing backup path, into a local directory. A backup is a **bundle directory**
   (`edge-backup-*/`) holding `database.sqlite3` and a manifest, and there is one per
   kind (evidence, ledger). Point `--db` and `--ledger` at each bundle's
   `database.sqlite3` file, not at the directory.
3. Run the dashboard locally on `127.0.0.1`.

Never: bind `0.0.0.0` on the VPS, open a firewall port, use an SSH `-R`/`-L` tunnel or any
tunnel service, or publish a database. The private stores stay private
(`docs/SECURITY.md`).

## Views

| Route | What it shows |
|---|---|
| `/` Overview | Collector status file (freshness and age) and the status re-derived from the evidence DB; the pipeline receipt state, latest day, valid/closed capture days, missing capture days, settlement conflicts and evidence cutoff; per account the **notional starting bankroll**, **cost-basis shadow equity (not liquidation value)**, settled cash, committed capital, open worst-case risk, realized P&L, new-risk-allowed; blockers such as the UNVERIFIED fee schedule, stale inputs, pending or overdue settlements, settlement conflicts, missed or invalid capture days, risk breaches or zero-capacity halts, and RESEARCH_INVALID_CASH (a frozen-rule deviation). |
| `/opportunities` | Every recorded decision from the ledger payloads: model and conservative probability, executable price, fee, all-in cost, net edge, size and binding constraint, qualification with primary and all rejection reasons, fill outcome, freshness, fee status, claimable. |
| `/positions` | The accounting basis note, NO_FILL reason counts, every simulated fill (FILLED and NO_FILL with reason), open positions with settlement state (awaiting, overdue, or no time = locked), settled positions with payout and net P&L, and pending settlements and settlement evidence conflicts from the receipt. |
| `/outcome-board` | Outcome groups ranked by account impact, with exposure, max loss and max gain labelled **upper bound, not a predicted scenario**, horizon, status, the bound method, and linked positions. |
| `/risk` | Policy caps, the risk report (reserve floor, remaining capacity, drawdown, trailing loss windows, breaches, new_risk_allowed), capital release by horizon (best-case payout never counted as cash), exposure by event and cluster, sizing-policy parameters, binding sizing constraints, and the withdrawal contract: **NOT RECOMMENDED**. |
| `/experiments` | Registry status and manifest validation, the EXP-001 Stage A recorded result, gate report file names, source health, fee schedules with verification status and claimable, and the full receipt (days, settlement refresh). |
| `/healthz` | Plain `ok`. No data. |

Both shadow accounts always appear. `EXP-001-stage-b-shadow` is the **operational** account
(sizing policy and risk limits). `EXP-001-stage-b-research` is the **frozen EXP-001 research
account**. If it has not been opened, it shows NOT STARTED.

## Security properties (tested)

- GET and HEAD only; any other method answers 405. Unknown paths answer 404.
- No endpoint takes SQL, a file path, a command or any parameter. Query strings are ignored.
- Every dynamic value is escaped with `html.escape`, and ledger or receipt content is treated
  as untrusted.
- Headers: `Content-Type: text/html; charset=utf-8`, `X-Content-Type-Options: nosniff`,
  `Cache-Control: no-store`, a CSP without scripts, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`.
- Rendering every page leaves the evidence DB and ledger files byte-identical.
- A crash while rendering a page answers 500 with a generic message. A one-line, path-stripped
  error goes to the server console.

## Limitations

- Local development server (`wsgiref`, single-threaded). It is fine for one person on
  loopback. It is not a production server.
- `--host ::1` binds an IPv6 socket. If the port is taken or the address is unavailable, the
  command prints one line and exits 2 instead of a traceback. SIGTERM stops the server like
  Ctrl+C, so the demo's temporary directory is removed either way.
- No authentication or TLS, by design (not exposed). If hosting is ever authorized, put the WSGI
  app behind an authenticated reverse proxy with TLS, as a separately reviewed change.
- The research account's risk figures appear only if code registers a risk policy for it
  (`exp001_shadow.RESEARCH_RISK_POLICY`). Otherwise the dashboard says the figures are not
  computed. Its sizing is the frozen EXP-001 rule, which is shown as text.
- New-risk status is `OK`, `BREACH` (a limit is breached) or `HALTED` (no limit breached, but
  zero remaining risk capacity). BREACH and HALTED are both listed as blockers.
- Equity is cost basis. There is no liquidation mark, because no executable liquidation quotes
  are stored.
- The receipt schema (`edge-lab-shadow-daily-receipt/1`) is read defensively. Unknown fields are
  ignored, and missing ones render as unknown.
- The page re-reads the sources on every request. `forward.summary` re-derives day status from
  the evidence DB, which can take a moment on a large store.
