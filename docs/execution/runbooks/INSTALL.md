# Install the executor host pieces (installed, not started)

**Approval gate:** owner approval of an **executor host install**, recorded in `docs/EXECUTION_PLAN.md`. No such
approval exists today. The 2026-10-07 entries authorize FIXTURE-only code and say that any service activation
needs its own approval. This runbook creates a user, directories, code, a release manifest and unit files. It starts
nothing, enables nothing, schedules nothing and installs no key.

It changes no research path. `deploy/vps/install.sh` is not used and does not know these units. Run it outside the
research protected windows: 17:40–18:50 America/New_York, the 11:15 and 16:15 ET settlement runs, and any running
`edgelab-*` unit (`deploy/vps/README.md`). Read the VPS clock first (`date -u` on the host). The laptop clock has
been wrong before.

## Preconditions (agent, unprivileged)

1. The approval names the exact commit `<SHA>` (merged `main`).
2. `python scripts/secret_scan.py --history --rev <SHA>` is clean. Record its output summary ([SECRET_SCAN.md](SECRET_SCAN.md)).
3. `python -m pytest` is green on `<SHA>`, and so is CI on that exact commit.
4. Copy the git bundle of `<SHA>` to `~dynasty/edgelab-exec-release/market-edge-lab.bundle`.

## Install (owner, sudo)

```bash
# 1. identity: a dedicated system user with no login and no home
sudo groupadd --system edgelab-exec
sudo useradd --system --gid edgelab-exec --home-dir /var/lib/market-edge-lab-exec --no-create-home --shell /usr/sbin/nologin --comment "Market Edge Lab executor" edgelab-exec

# 2. directories (paths and modes: README.md)
sudo install -d -o root -g root -m 0755 /opt/market-edge-lab-exec /etc/market-edge-lab-exec
sudo install -d -o root -g root -m 0700 /etc/market-edge-lab-exec/credentials
sudo install -d -o edgelab-exec -g edgelab-exec -m 0700 /var/lib/market-edge-lab-exec /var/lib/market-edge-lab-exec/journal /var/lib/market-edge-lab-exec-backup /var/lib/market-edge-lab-exec-backup/journal
sudo install -d -o edgelab-exec -g edgelab -m 0750 /var/lib/market-edge-lab-exec-status

# 3. code at <SHA>, root-owned and read-only; the previous tree is kept as app.prev
cd /
sudo rm -rf /opt/market-edge-lab-exec/app.new
sudo git -c safe.directory='*' clone --quiet --no-checkout ~dynasty/edgelab-exec-release/market-edge-lab.bundle /opt/market-edge-lab-exec/app.new
sudo git -c safe.directory='*' -C /opt/market-edge-lab-exec/app.new -c advice.detachedHead=false checkout --quiet <SHA>
sudo git -c safe.directory='*' -C /opt/market-edge-lab-exec/app.new rev-parse HEAD   # must print <SHA>
sudo rm -rf /opt/market-edge-lab-exec/app.new/.git
echo <SHA> | sudo tee /opt/market-edge-lab-exec/app.new/REVISION
sudo chown -R root:root /opt/market-edge-lab-exec/app.new && sudo chmod -R u+rwX,go+rX,go-w /opt/market-edge-lab-exec/app.new
[ -d /opt/market-edge-lab-exec/app ] && sudo rm -rf /opt/market-edge-lab-exec/app.prev && sudo mv /opt/market-edge-lab-exec/app /opt/market-edge-lab-exec/app.prev
sudo mv /opt/market-edge-lab-exec/app.new /opt/market-edge-lab-exec/app

# 4. the executor's own venv (stdlib only; cryptography arrives only with the DEMO approval)
[ -x /opt/market-edge-lab-exec/venv/bin/python ] || sudo python3 -m venv --without-pip /opt/market-edge-lab-exec/venv
SITE=$(/opt/market-edge-lab-exec/venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
echo /opt/market-edge-lab-exec/app/src | sudo tee "$SITE/market_edge_lab_exec.pth"

# 5. the release manifest (never written over an existing one; the previous one is kept)
sudo /opt/market-edge-lab-exec/venv/bin/python -m edge_lab.execution.ops release-manifest --revision <SHA> --out /etc/market-edge-lab-exec/release.json.new
#    For an update whose previous release runs the same journal schema, name it as the compatible rollback:
#    add --rollback-revision <PREVIOUS_SHA> --rollback-journal-schema <N> (MIGRATION_AND_ROLLBACK.md).
[ -f /etc/market-edge-lab-exec/release.json ] && sudo mv /etc/market-edge-lab-exec/release.json /etc/market-edge-lab-exec/release.json.prev
sudo mv /etc/market-edge-lab-exec/release.json.new /etc/market-edge-lab-exec/release.json && sudo chmod 0644 /etc/market-edge-lab-exec/release.json

# 6. unit files: installed, NOT started. They have no [Install] section, so nothing can enable them.
sudo install -o root -g root -m 0644 /opt/market-edge-lab-exec/app/deploy/executor/systemd/edgelab-exec.slice /opt/market-edge-lab-exec/app/deploy/executor/systemd/edgelab-exec.service /opt/market-edge-lab-exec/app/deploy/executor/systemd/edgelab-exec-backup.service /opt/market-edge-lab-exec/app/deploy/executor/systemd/edgelab-exec-health.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/edgelab-exec.slice /etc/systemd/system/edgelab-exec.service /etc/systemd/system/edgelab-exec-backup.service /etc/systemd/system/edgelab-exec-health.service
```

## Verify (owner)

| Check | Command | Expect |
|---|---|---|
| nothing runs | `systemctl is-active edgelab-exec.service` | `inactive` |
| nothing is enabled | `systemctl is-enabled edgelab-exec.service edgelab-exec-backup.service edgelab-exec-health.service` | `static` for each (no [Install] section) |
| the start check passes | `sudo runuser -u edgelab-exec -- /opt/market-edge-lab-exec/venv/bin/python -m edge_lab.execution.ops release-check --manifest /etc/market-edge-lab-exec/release.json --revision-file /opt/market-edge-lab-exec/app/REVISION` | `"ok":true`, no problems (no journal exists yet) |
| research cannot see executor data | `sudo runuser -u edgelab -- ls /var/lib/market-edge-lab-exec` | permission denied |
| the executor cannot read research secrets | `sudo runuser -u edgelab-exec -- test -r /etc/market-edge-lab/secrets.env` | non-zero exit |
| nobody but root reads credentials | `sudo runuser -u edgelab-exec -- ls /etc/market-edge-lab-exec/credentials` | permission denied |
| `dynasty` sees nothing private | `ls /var/lib/market-edge-lab-exec-status /var/lib/market-edge-lab-exec-backup` (as `dynasty`) | permission denied for both |
| no network module or signer loaded | `sudo runuser -u edgelab-exec -- /opt/market-edge-lab-exec/venv/bin/python -c "import sys, edge_lab.execution.ops; print([m for m in ('cryptography','socket','ssl') if m in sys.modules])"` | `[]` |

## Undo (owner)

The data is kept: never delete the journal, the status or the backups.
```bash
sudo systemctl stop edgelab-exec.service edgelab-exec-backup.service edgelab-exec-health.service
sudo rm -f /etc/systemd/system/edgelab-exec.slice /etc/systemd/system/edgelab-exec.service /etc/systemd/system/edgelab-exec-backup.service /etc/systemd/system/edgelab-exec-health.service
sudo systemctl daemon-reload
```
