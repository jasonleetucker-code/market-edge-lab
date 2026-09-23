# Emergency laptop bridge (manual fallback only)

```text
VPS collector  = PRIMARY (chaseupside, `edgelab` service, deploy/vps/)
Laptop bridge  = MANUAL EMERGENCY FALLBACK ONLY
Laptop scheduler = NONE
```

## When it may run

**Only when both of these are true:**

1. The VPS collector has failed, or will clearly miss a window. For example:
   - the host is down;
   - the timers are not active;
   - `latest.json` or `last_failure.json` shows a failure that cannot be fixed before
     the window.
2. The owner explicitly invokes the emergency bridge for that window, in chat or in
   writing.

Never run it as a routine duplicate of a healthy VPS window. Never leave a Windows
Scheduled Task, cron job, Claude scheduled task, or unattended wait loop behind.
The bridge is attended: a person or an attended agent session runs it for one window and
then stops.

History: the owner approved a one-window attended bridge for 2026-09-23 (target
2026-09-24). It was cancelled before any capture once the VPS collector was deployed and
verified (2026-09-23 about 02:18 UTC). No bridge evidence exists.

## How to run one window (target date D, decision 18:00 ET on D−1)

The collector's own timing gate protects the evidence. A phase started outside its window
is recorded as `rejected_out_of_window` and does no network work. A late start after the
laptop sleeps therefore cannot produce out-of-window evidence.

Use a separate database, never the laptop's research DB, so bridge evidence stays
identifiable:

```bash
export PYTHONPATH=src NWS_USER_AGENT="market-edge-lab research collector (emergency bridge)"
# at 17:45 ET
python -m edge_lab.cli forward capture --phase pfm --db data/bridge.sqlite3
# at 17:55:05 ET (window 17:55-17:59:30 ET)
python -m edge_lab.cli forward capture --phase decision --db data/bridge.sqlite3
# at 18:05 ET (per-bracket 10-15 min after each decision book)
python -m edge_lab.cli forward capture --phase recheck --db data/bridge.sqlite3
# after 18:20 ET
python -m edge_lab.cli forward status --db data/bridge.sqlite3 --date YYYY-MM-DD   # the target date D
```

On the Windows laptop (PowerShell), set the environment first with
`$env:PYTHONPATH = "src"; $env:NWS_USER_AGENT = "market-edge-lab research collector (emergency bridge)"`
and then run the same `python -m edge_lab.cli ...` lines.

- Keep the laptop plugged in and awake for the whole window.
- Record in `HANDOFF.md` that the window was bridged, with the reason and the `forward
  status` result.
- `data/` is git-ignored. The bridge DB is immutable evidence: do not delete it or edit it.

## Not built yet

A verified import of bridge evidence into the VPS database does not exist yet. It would be
an append-only copy that preserves raw hashes. Until it does, a bridged day is kept as a
separate immutable database, and it is not counted among the VPS's valid days.
