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
| `--db` | evidence SQLite store | `SnapshotStore.open_readonly` (SQLite `mode=ro` + `query_only`); `forward.summary`, `latest_source_health`; The Odds API capture targets (`odds_targets`, `odds_transitions`, captured snapshots parsed by `odds_api.parse_odds`) |
| `--ledger` | shadow ledger SQLite file | `ShadowLedger.open_readonly`; `accounts`, `entries`, `state` (hash-chain replay) |
| `--status-dir` | `latest.json` (collector), `shadow_daily.json` (pipeline receipt), `freshness.json` (Freshness Fabric supervisor), `last_failure.json` (production unit failures), `last_verification.json` (deployment verification records), `execution_status.json` (the execution package's status export, schema `edge-lab-execution-status/1`) | JSON, fixed names only, 2 MB cap, every field optional |
| `--odds-ledger` | The Odds API quota ledger (default `odds_quota_ledger.json` beside `--db`) and its `<ledger>.pilot.json` runner state | `odds_pilot.dashboard_status`: read without locking or writing, no key, no network |
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
| `/opportunities` | Markets | Search, domain strip, filters (venue, state, cash release, sort), a paused line when the account's risk report allows no new risk (journey J3), and the board joining captured books (`data.observed_board`) with recorded decisions; every recorded decision payload in a technical disclosure. |
| `/market?venue=&id=&side=` | Market detail | Quote, price history (two or more captured observations), our assessment (journey J3: fee per contract, evaluated size, mechanism and evidence of the experiment linked by the decision's policy, every rejection reason), across venues (the `best_price` comparator's four claims at the recorded decision's evaluated size), research sizing (the read-only shadow sizing challenger, `sizing_counterfactual`), capital & timing, a read-only decision preview, rules & evidence. |
| `/positions` | Portfolio | Balances with basis labels; Open / Settling / Closed / All positions; accounting method; ledger record; settlement evidence from the receipt. |
| `/outcome-board` | Outcomes | What matters today: outcome groups ranked by account impact, bounds labelled as bounds; then journey J8, "Execution positions by outcome" from `execution_status.json` (actual positions "access not connected"; FIXTURE positions, settlements and venue P&L grouped by Kalshi event; bounds unknown because the export records none). |
| `/risk` | Risk | Capacity verdict, limit rows, capital release windows, starter rule, withdrawal not enabled, policy details. |
| `/experiments` | Research & Data | Tabs: Research (journey J7 "Research stages": candidate, development, shadow, qualified and rejected from the registry and the STRATEGY_QUALIFIED track, protected evidence named from protocol configuration only; then experiments, forward valid days, next preregistered look, then "Economic evidence": Family A paired sportsbook-vs-Kalshi evidence from `sports_evidence.terminal_view` with its protocol attrition, economic screen, size ladder and data gaps, and Family B from the newest verified EXP-003 payoff-scan result file, with its source store shown and laptop or fixture results labelled "not production evidence") and Data sources (source freshness from the Freshness Fabric, with journey J2's last attempt, completeness, latest failure, provenance and cost per source, venues, The Odds API card and its capture-target table with the research-benchmark consensus at each capture shown, related Polymarket US markets per event, source health, fees, venue registry, full receipt). |
| `/alerts` | Alerts | Attention items from blockers, failure records and the local notification outbox, grouped by origin (only production needs attention); nothing is sent. |
| `/more` | More | Links to Risk, Research & Data, Alerts, System & evidence. |
| `/setup` | none (under More) | Operator journey J1, setup and readiness: every missing environment, owner approval, permission and provider fact with its safe next step, from a static manifest pinned to EXECUTION_PLAN, the execution ledger and the activation packet (`views/ops_manifest.py`), plus the code's authorized environments and limit state from `execution_status.json`. |
| `/experiments/wallet` | none (under Research & Data) | Journey J4, wallet research: production shows "No wallet source is approved" and the copying status (research only, no execution); demo mode shows Demonstration A (`wallet_intel.demo.run_synthetic_demo`), SYNTHETIC on every section. |
| `/positions/execution` | none (under Portfolio) | Journey J5, execution portfolio from `execution_status.json`: actual holdings ("Access not connected"), the FIXTURE account's cash with its basis, reserves, positions, pending and unknown orders, fills and partial exits, settlement and venue-reported P&L. |
| `/risk/automation` | none (under Risk) | Journey J6, automation from `execution_status.json`: mode, reconciliation, armed grant and scope (TEST grants labelled), next action with the exporter's arm readiness per mode, stop reasons, limits and bounds, the rearm procedure and the control log. No control of any kind. |
| `/gallery` | none | Component gallery, demo mode only. |
| `/healthz` | none | Plain `ok`. No data. |

`?account=research` selects the frozen research account on account-scoped pages; operational
is the default. The two are never shown summed.

### The execution status export (journeys J1, J5, J6)

The dashboard never imports `src/edge_lab/execution/` (ADR 0043). The execution package writes a sanitized,
versioned projection of its journal (`execution/status_export.py`: `build_status`, `status_for_path`,
`write_status`) to `execution_status.json` in the status directory, and the dashboard reads that file
(`data.execution_status`) the way it reads `freshness.json`:

- labelled with its environment (today only FIXTURE can exist: a fake venue, never a real account);
- money, prices and quantities as exact decimal text, never floats; unknown as `null`, never 0;
- no approval nonce, request digest, receipt payload, venue order id, key, signature or credential; free text is
  redacted and the file is refused if it still looks like it holds a secret;
- states: no file ("No execution export": nothing is known, never an empty portfolio), unreadable, foreign schema
  or malformed shape (error, `data.execution_shape_problems`), an environment outside this Terminal's own allowlist
  (`views/ops_common.TERMINAL_ENVIRONMENTS`, FIXTURE only, pinned to `AUTHORIZED_ENVIRONMENTS`: refused, nothing
  shown, whatever the export's own list says) or an authorized list that differs from it (mismatch error), no
  journal, journal error, stale (older than 15 minutes: every figure reads "as of", never current), and the journal's own
  reconciliation, paused and empty states.

No timer or service writes the export today: the call site is the executor process (package O), which is not
activated. Browser fixture states `journeys`, `journeys_paused`, `journeys_idle`, `journeys_stale` and
`journeys_none` (`tests/browser/fixture_states.py`) write it from FIXTURE journals that the real orchestrator wrote
against the test fake venue (`tests/browser/journey_fixtures.py`).

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
