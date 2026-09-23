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
| Server-rendered HTML; self-hosted CSS, fonts and one small script (Market Edge Terminal v1, ADR 0025) | No build step and no client framework. The design contract is `docs/design/UI_CONTRACT.md`. Assets are package data served from an exact allowlist under a content-hash path. The CSP (`default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'`) forbids inline styles and scripts, third-party origins, frames and objects. Everything works without JavaScript; `terminal.js` only adds the tape's arrow buttons. |
| Bound to `127.0.0.1` | It is local-only. Public exposure, public tunnels, DNS/TLS and firewall changes are not authorized. The one exception is tailnet-only access through Tailscale Serve on the VPS, which proxies to this loopback bind (ADR 0024). A non-loopback `--host` is refused unless `--allow-non-loopback` is passed, and that prints a warning. |
| Host header must be local | A request whose `Host` is not `localhost`, a 127.0.0.0/8 address or `::1` (or the explicitly approved `--host`, matched literally: with `--host 0.0.0.0` only `Host: 0.0.0.0` is accepted, not a LAN address; or the one exact `<machine>.<tailnet>.ts.net` name given with `--tailscale-serve-host`, loopback bind only) gets 400. Malformed values (a non-numeric port, text after `]`) are refused. This stops a web page from reading the dashboard by pointing its own domain at 127.0.0.1 (DNS rebinding). |
| No authentication | Nothing is exposed publicly. On the VPS, tailnet membership (the owner's devices) is the access boundary (ADR 0024). We do not build a custom auth system. If exposure is ever authorized, authentication belongs in the front server (see "Limitations"). |

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
carries a persistent **SYNTHETIC UI DEMO** strip. The demo also writes synthetic decision and re-check book captures through the real `SnapshotStore` API and serves the component gallery at `/gallery` (demo mode only). Synthetic market ids start with `DEMO-`.
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
public tunnel service (Tailscale Funnel included), or publish a database. The one approved
remote path is the next section. The private stores stay private
(`docs/SECURITY.md`).

## Private phone access (Tailscale Serve, VPS)

Authority: owner directive 2026-09-23
(`docs/owner/2026-09-23-tailscale-private-dashboard-directive.md`). Design: ADR 0024.

`edgelab-dashboard.service` runs the dashboard on the VPS:
- as `edgelab`, read-only, bound to `127.0.0.1:8765`;
- over the live stores, opened with SQLite `mode=ro`.

Tailscale Serve publishes it at `https://<machine>.<tailnet>.ts.net/` to the owner's tailnet
only. **Serve, never Funnel.** Setup, as root, outside 17:40–18:35 America/New_York:

```bash
# once: official client from pkgs.tailscale.com; no firewall or resolver changes
tailscale up --netfilter-mode=off --accept-dns=false   # owner approves the login URL
NAME=$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
install -o root -g edgelab -m 0640 /dev/null /etc/market-edge-lab/dashboard.env
echo "EDGE_LAB_TAILSCALE_SERVE_HOST=$NAME" > /etc/market-edge-lab/dashboard.env
systemctl enable --now edgelab-dashboard.service
curl -s http://127.0.0.1:8765/healthz                   # ok
tailscale serve --bg 8765                              # tailnet only; owner enables HTTPS once
tailscale serve status; tailscale funnel status        # funnel must show no config
```

The phone opens `https://<machine>.<tailnet>.ts.net/` with the Tailscale app connected.

Stop options:
- **Remote access only:** `tailscale serve --https=443 off`.
- **Everything:** also `systemctl disable --now edgelab-dashboard.service`.

## Views (Market Edge Terminal v1)

The page order, hierarchy and states are fixed by `docs/design/UI_CONTRACT.md` §8. Every page
keeps the full technical record (codes, IDs, caveats, receipts, fee components) in
disclosures.

| Route | Label | What it shows |
|---|---|---|
| `/` | Terminal | Market overview: capture status (never "healthy" over an invalid capture), the selected shadow account's summary, the market board (All / Qualified / Watching / Blocked), What matters today, Activity, and a collapsed System & evidence record with every collector, receipt, blocker and account field. |
| `/opportunities` | Markets | Search, domain strip, filters (venue, state, cash release, sort), and the board joining captured books (`data.observed_board`) with recorded decisions; every recorded decision payload in a technical disclosure. |
| `/market?venue=&id=&side=` | Market detail | Quote, price history (two or more captured observations), our assessment, across venues, capital & timing, a read-only decision preview, rules & evidence. |
| `/positions` | Portfolio | Balances with basis labels; Open / Settling / Closed / All positions; accounting method; ledger record; settlement evidence from the receipt. |
| `/outcome-board` | Outcomes | What matters today: outcome groups ranked by account impact, bounds labelled as bounds. |
| `/risk` | Risk | Capacity verdict, limit rows, capital release windows, starter rule, withdrawal not enabled, policy details. |
| `/experiments` | Research & Data | Tabs: Research (experiments, forward valid days, next preregistered look) and Data sources (venues, source health, fees, venue registry, full receipt). |
| `/alerts` | Alerts | Attention items from blockers, failure records and the local notification outbox; nothing is sent. |
| `/more` | More | Links to Risk, Research & Data, Alerts, System & evidence. |
| `/gallery` | none | Component gallery, demo mode only. |
| `/healthz` | none | Plain `ok`. No data. |

`?account=research` selects the frozen research account on account-scoped pages; operational
is the default. The two are never shown summed.

## Security properties (tested)

- GET and HEAD only; any other method answers 405. Unknown paths answer 404.
- No endpoint takes SQL, a file path, a command or a URL. Each route reads only its allowlisted query parameters (`presentation.ROUTE_PARAMS`); every value is checked against a fixed set, the venue registry or a bounded pattern. An unsupported value answers 400 with a safe message; unknown parameter names are ignored.
- Static files: exact allowlist (`html.STATIC_FILES`), versioned path, immutable cache; traversal and unknown names answer 404.
- Every dynamic value is escaped with `html.escape`, and ledger or receipt content is treated
  as untrusted.
- Headers: `Content-Type: text/html; charset=utf-8`, `X-Content-Type-Options: nosniff`,
  `Cache-Control: no-store` (pages; only versioned static assets are cacheable), the CSP above,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cross-Origin-Resource-Policy: same-origin`.
- Rendering every page leaves the evidence DB and ledger files byte-identical.
- A crash while rendering a page answers 500 with a generic message. A one-line, path-stripped
  error goes to the server console.

## Limitations

- Local development server (`wsgiref`, single-threaded). It is fine for one person on
  loopback. It is not a production server.
- `--host ::1` binds an IPv6 socket. If the port is taken or the address is unavailable, the
  command prints one line and exits 2 instead of a traceback. SIGTERM stops the server like
  Ctrl+C, so the demo's temporary directory is removed either way.
- No authentication or TLS in the app, by design. On the VPS, TLS is Tailscale Serve's and access is tailnet membership. If hosting is ever authorized, put the WSGI
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
