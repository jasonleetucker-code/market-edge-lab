# Executor key storage and rotation

**Approval gate:** an owner decision for each environment, recorded in `docs/EXECUTION_PLAN.md`:
- DEMO keys: decision 1 of `docs/strategy/KALSHI_OWNER_ACTIVATION_PACKET.md`;
- production read keys: decision 2.

**No key exists today**, and no agent creates, requests, handles, sees or installs one (`docs/SECURITY.md`). Every
step below that touches a key is the owner's, on the machine that holds it.

Before any key is installed, [SECRET_SCAN.md](SECRET_SCAN.md) must be clean on the exact release commit, with the
result recorded. As of 2026-10-08 it is not clean: one finding is pending a decision (see SECRET_SCAN.md).

A clean scan is not proof that no secret is in git. it finds credential shapes and credential-named assignments only. It does not find a bare key id (a UUID) or bare hex key on a line of its own, short values, an all-letter key or topic value, or a secret split across lines or encoded. So the controls that keep a key out of
the repository are the ones below: the key lives only on the host, root-only, in `/etc`, and never in a file
anyone commits. The scan is the check after the fact.

## Where a key lives

| | |
|---|---|
| File | `/etc/market-edge-lab-exec/credentials/kalshi-<env>-<YYYYMMDD>.pem`, `root:root 0600`, in a `root:root 0700` directory |
| Key id | `/etc/market-edge-lab-exec/credentials/kalshi-<env>-<YYYYMMDD>.id`, same owner and mode. It is account-identifying, so it stays off the command line, where `ps` would show it |
| How the executor gets it | systemd `LoadCredential=` in a root-owned drop-in (below). systemd reads the file as root and exposes a copy only to that service, under its credentials directory (`%d`), on a non-swappable in-memory filesystem. The copy is removed when the service stops |
| Who can read the file at rest | root only. No service account can, including `edgelab-exec`, the research user `edgelab` and the dashboard. This supersedes the activation packet's earlier draft ("owned by the executor's own service user, mode 0600"): a file the service user owns can be copied by anything running as that user |
| Never | in git, `.env`, `/etc/market-edge-lab/secrets.env` (the research secrets file), an environment variable, a command line, a chat, an issue, a log, a notification, a screenshot, or any backup |

**Keys are outside every backup.**
- Executor journal backups cover `/var/lib/market-edge-lab-exec*` only, and the backup unit cannot see
  `/etc/market-edge-lab-exec/credentials/` (`InaccessiblePaths`).
- Research backups and the research off-host pull cover research stores only.
- If a key is lost, rotate it: create a new one at the venue. Restoring a key is not a procedure.

The drop-in, when the DEMO approval exists. Its exact flag names arrive with the reviewed key loader in that same
approval's PR. The execution package reads no key path, environment variable or file today (ADR 0043 decision 7):

```ini
# /etc/systemd/system/edgelab-exec.service.d/key.conf   (root:root 0644)
[Service]
LoadCredential=kalshi-key:/etc/market-edge-lab-exec/credentials/kalshi-demo-20261101.pem
LoadCredential=kalshi-key-id:/etc/market-edge-lab-exec/credentials/kalshi-demo-20261101.id
```

That PR must also show, on the host, that the credential loads with the unit's `InaccessiblePaths`. systemd reads
`LoadCredential=` sources itself, outside the service's namespace, but this is checked on the real host, not
assumed. Use `systemd-analyze verify`, then one DISARMED start whose journal shows the credential directory
populated, without printing the key.

The same approval changes the unit's egress from `RestrictAddressFamilies=AF_UNIX` and `IPAddressDeny=any` to the
reviewed DEMO egress. The code's host allowlist (`conformance`) stays the exact-host control. systemd cannot
allowlist by host name.

## Install a key (owner)

1. Create the key in the venue's web interface for the approved environment only. A demo key is never a production
   key. Never enable withdrawal or transfer on any key.
2. Move the private key file to the host privately (for example `scp` to your own home directory). Then:
   ```bash
   sudo install -o root -g root -m 0600 ~/kalshi-demo.pem /etc/market-edge-lab-exec/credentials/kalshi-demo-YYYYMMDD.pem
   printf '%s\n' '<key id>' | sudo tee /etc/market-edge-lab-exec/credentials/kalshi-demo-YYYYMMDD.id >/dev/null
   sudo chmod 0600 /etc/market-edge-lab-exec/credentials/kalshi-demo-YYYYMMDD.id
   shred -u ~/kalshi-demo.pem
   ```
3. Record the key id's last four characters, the creation date and the rotation due date outside git, for example
   in your password manager (`docs/SECURITY.md` rule 5).
4. Write the drop-in, run `sudo systemctl daemon-reload`, then restart through [START_DISARMED.md](START_DISARMED.md).
   The executor starts DISARMED: a key alone never arms anything.

## Rotate (owner; every 90 days, after any suspicion, and when anyone with access leaves)

1. Create the new key at the venue, and install it under a new dated name (as above).
2. Point the drop-in at the new files, then `daemon-reload` and restart. The executor comes back DISARMED.
3. Confirm one approved read works with the new key.
4. Revoke the old key at the venue.
5. `sudo shred -u` the old `.pem` and `.id` files. Record the rotation outside git.

## Compromise

Revoke the key at the venue first. That is the only control that stops a stolen key. Then stop the executor and
follow [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) and `docs/SECURITY.md`, "If a secret is committed". Rewriting
history or deleting a file does not un-leak a key.
