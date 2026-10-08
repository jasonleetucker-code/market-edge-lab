# Start, restart and stop the executor: always DISARMED

**Approval gate:** owner approval of **executor service activation**, recorded in `docs/EXECUTION_PLAN.md`. This is
separate from the install approval ([INSTALL.md](INSTALL.md)). Starting at boot is part of the same activation
approval and must be named in it. Arming is never part of this runbook. Every arm is an operator's recorded request,
judged by `control.decide_arm`. A sending mode also needs that environment's own approval (DEMO: decision 1 of
`docs/strategy/KALSHI_OWNER_ACTIVATION_PACKET.md`).

## What a start is

- **Every start is DISARMED.** The executor boots only through `control.boot` (ADR 0046):
  - it takes the egress lease first;
  - it persists a `Started` event before anything acts;
  - it rebuilds latches, incidents and closeout authorizations from the journal;
  - it never re-arms.

  A systemd restart, a host reboot and a restore are all starts.
- **The old fence is dead.** A new lease bumps the fence token. Any attempt of the old fence that was still
  PENDING_EGRESS or SENT becomes OUTCOME_UNKNOWN: nobody can know whether it went out. It is resolved from the
  venue's order listing and is never re-sent.
- **The start check comes first.** `ops run` runs the release check (manifest, installed `REVISION`, journal
  schema) before anything else. Any mismatch fails the unit, and the failure alert fires.
- **Today the start refuses.** No networked runner exists in the execution package yet, so `ops run` exits 78
  (`NO_RUNNER`) after the check, and 78 is never restarted. The runner arrives with the DEMO approval (ADR 0043
  decision 7).

## Start (owner)

```bash
sudo runuser -u edgelab-exec -- /opt/market-edge-lab-exec/venv/bin/python -m edge_lab.execution.ops release-check --manifest /etc/market-edge-lab-exec/release.json --revision-file /opt/market-edge-lab-exec/app/REVISION --journal /var/lib/market-edge-lab-exec/journal/kalshi.execution.sqlite3
sudo systemctl start edgelab-exec.service
sudo journalctl -u edgelab-exec.service -n 20 --no-pager
```

What to expect:
- **Today:** one JSON line with `"started":false` and a `NO_RUNNER` problem. The unit is failed, with exit status
  78 and no restart.
- **Once a runner exists:** read `/var/lib/market-edge-lab-exec-status/execution_status.json` and check:
  - `control.mode` is `DISARMED`;
  - `control.last_started_at_utc` is the start you just made;
  - `service.state` is `STARTED_NO_SHUTDOWN_RECORDED`.

  Then run the health check ([INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)). Expect liveness LIVE. Expect
  reconciliation HEALTHY only after a COMPLETE account read.

## Start at boot (owner, only if the activation approval names it)

The units have no `[Install]` section, so `systemctl enable` does nothing. Starting at boot is an explicit wants link:

```bash
sudo systemctl add-wants multi-user.target edgelab-exec.service
```

A boot start is DISARMED like every other start.

## Restart

```bash
sudo systemctl restart edgelab-exec.service
```

The executor comes back DISARMED with a new fence (see above). Reconcile, and review any OUTCOME_UNKNOWN attempt,
before anyone asks to arm.

## Stop (no approval needed once installed: stopping only removes risk)

```bash
sudo systemctl stop edgelab-exec.service
sudo rm -f /etc/systemd/system/multi-user.target.wants/edgelab-exec.service && sudo systemctl daemon-reload   # if it was linked at boot
```

Stopping sends nothing. Resting orders stay at the venue: an outage never flattens a position. Cancelling owned
orders is a CANCEL_OWNED action of a running executor. With no executor running, cancel through the venue's own
interface. Either way, it is the owner's step ([INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)).
