#!/usr/bin/env bash
# Install or update Market Edge Lab's forward collector on the Chase Upside VPS (ADR 0012).
#
#   sudo bash install.sh --sha <40-hex commit> --bundle <path to git bundle> \
#        [--user-agent "market-edge-lab (contact: you@example.com)"] [--alert-url URL]
#
# Idempotent. Creates the `edgelab` system user and the directories below, installs the
# pinned code with its own venv and the systemd units, and verifies permissions. It does
# NOT enable or start any timer; that is a separate, explicit step (see README.md).
#
#   /opt/market-edge-lab/app            code at the pinned commit (root-owned, read-only)
#   /opt/market-edge-lab/venv           stdlib-only venv (no pip), .pth -> app/src
#   /var/lib/market-edge-lab            private data: db/, backups/   (edgelab, 0700)
#   /var/lib/market-edge-lab-status     non-sensitive status JSON     (edgelab, 0755)
#                                       incl. last_failure.json (production only) and
#                                       last_verification.json (the section 4.1 fail-closed check)
#   /var/lib/market-edge-lab-verify     fail-closed check confirmations (root:root 0755);
#                                       created by verify_fail_closed.sh, not by this script
#   /etc/market-edge-lab/env            NWS_USER_AGENT etc.           (root:edgelab 0640)
#   /etc/market-edge-lab/secrets.env    owner-installed secrets       (root:root 0600)
#                                       created empty once; NEVER read, rewritten or printed here
set -euo pipefail

SHA="" BUNDLE="" UA="" ALERT_URL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --sha) SHA="$2"; shift 2 ;;
    --bundle) BUNDLE="$2"; shift 2 ;;
    --user-agent) UA="$2"; shift 2 ;;
    --alert-url) ALERT_URL="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
die() { echo "INSTALL FAILED: $*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "run with sudo"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || die "--sha must be a full 40-hex commit"
[ -f "$BUNDLE" ] || die "--bundle $BUNDLE not found"
BUNDLE=$(realpath "$BUNDLE")
cd /  # the service account cannot enter the invoking user's home directory

APP_ROOT=/opt/market-edge-lab
DATA=/var/lib/market-edge-lab
STATUS=/var/lib/market-edge-lab-status
ETC=/etc/market-edge-lab
ENV_FILE=$ETC/env
SECRETS_FILE=$ETC/secrets.env
UNITS=(edgelab-pfm edgelab-decision edgelab-recheck edgelab-status edgelab-backup edgelab-shadow edgelab-settlement edgelab-odds)
# Installed and verified with the rest, but activated separately (ADR 0029): the Odds API timer
# is enabled only after the owner installs the key and `odds plan` / `odds smoke` pass.
SEPARATELY_ACTIVATED=edgelab-odds
CORE_TIMERS=()
for u in "${UNITS[@]}"; do [ "$u" = "$SEPARATELY_ACTIVATED" ] || CORE_TIMERS+=("$u"); done
# The unprivileged account that must NOT read private data (the Chase Upside app user).
OTHER_USER=${EDGELAB_OTHER_USER:-dynasty}

echo "== 1/7 service identity"
getent group edgelab >/dev/null || groupadd --system edgelab
id -u edgelab >/dev/null 2>&1 || useradd --system --gid edgelab --home-dir "$DATA" \
  --no-create-home --shell /usr/sbin/nologin --comment "Market Edge Lab collector" edgelab

echo "== 2/7 directories"
install -d -o root -g root -m 0755 "$APP_ROOT"
install -d -o edgelab -g edgelab -m 0700 "$DATA" "$DATA/db" "$DATA/ledger" "$DATA/backups" "$DATA/backups/ledger"
install -d -o edgelab -g edgelab -m 0755 "$STATUS"
install -d -o root -g edgelab -m 0750 "$ETC"

echo "== 3/7 code at $SHA"
rm -rf "$APP_ROOT/app.new"
git -c safe.directory='*' clone --quiet --no-checkout "$BUNDLE" "$APP_ROOT/app.new"
git -c safe.directory='*' -C "$APP_ROOT/app.new" -c advice.detachedHead=false checkout --quiet "$SHA"
[ "$(git -c safe.directory='*' -C "$APP_ROOT/app.new" rev-parse HEAD)" = "$SHA" ] || die "checkout is not $SHA"
rm -rf "$APP_ROOT/app.new/.git"
echo "$SHA" > "$APP_ROOT/app.new/REVISION"
chown -R root:root "$APP_ROOT/app.new"
chmod -R u+rwX,go+rX,go-w "$APP_ROOT/app.new"
chmod 0755 "$APP_ROOT/app.new/deploy/vps/alert.sh"
if [ -d "$APP_ROOT/app" ]; then rm -rf "$APP_ROOT/app.prev"; mv "$APP_ROOT/app" "$APP_ROOT/app.prev"; fi
mv "$APP_ROOT/app.new" "$APP_ROOT/app"

echo "== 4/7 venv (stdlib only)"
[ -x "$APP_ROOT/venv/bin/python" ] || python3 -m venv --without-pip "$APP_ROOT/venv"
SITE=$("$APP_ROOT/venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
echo "$APP_ROOT/app/src" > "$SITE/market_edge_lab.pth"
"$APP_ROOT/venv/bin/python" -c 'import edge_lab.forward, edge_lab.backup, edge_lab.odds_pilot' || die "edge_lab does not import"

echo "== 5/7 environment file"
existing() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 || true; }
UA=${UA:-$(existing NWS_USER_AGENT)}
ALERT_URL=${ALERT_URL:-$(existing EDGE_LAB_ALERT_URL)}
[ -n "$UA" ] || die "--user-agent is required on first install (NWS asks for contact information)"
case "$UA$ALERT_URL" in *$'\n'*|*\"*|*\'*) die "values must be single-line without quotes" ;; esac
tmp=$(mktemp "$ETC/env.XXXXXX")
{
  echo "# Market Edge Lab collector environment. Not a secret store: no credentials belong here."
  echo "NWS_USER_AGENT=$UA"
  echo "EDGE_LAB_CODE_VERSION=$SHA"
  [ -n "$ALERT_URL" ] && echo "EDGE_LAB_ALERT_URL=$ALERT_URL"
} > "$tmp"
chown root:edgelab "$tmp"; chmod 0640 "$tmp"; mv -f "$tmp" "$ENV_FILE"
# The owner's secrets (ADR 0028: the Odds API key, the ntfy topic URL) live in their own file,
# because the env file above is regenerated on every install. Create it once, empty; after that
# only its owner and mode are enforced. Its contents are never read, copied or printed here.
# root:root 0600: systemd reads EnvironmentFile= as root before dropping privileges, so no
# service account (the tailnet-reachable dashboard included) can read it.
if [ ! -e "$SECRETS_FILE" ]; then
  install -o root -g root -m 0600 /dev/null "$SECRETS_FILE"
fi
[ -f "$SECRETS_FILE" ] && [ ! -L "$SECRETS_FILE" ] || die "$SECRETS_FILE must be a regular file"
chown root:root "$SECRETS_FILE"; chmod 0600 "$SECRETS_FILE"

echo "== 6/7 systemd units (installed, NOT enabled)"
install -o root -g root -m 0644 "$APP_ROOT/app/deploy/vps/systemd/"edgelab-* "$APP_ROOT/app/deploy/vps/systemd/edgelab.slice" /etc/systemd/system/
systemctl daemon-reload
for u in "${UNITS[@]}"; do
  systemd-analyze verify "/etc/systemd/system/$u.service" "/etc/systemd/system/$u.timer" || die "unit $u does not verify"
done
systemd-analyze verify "/etc/systemd/system/edgelab-alert@.service" 2>/dev/null || true
# The notification relay has no timer: the daily units start it when they finish.
systemd-analyze verify "/etc/systemd/system/edgelab-notify.service" || die "edgelab-notify does not verify"
systemd-analyze verify "/etc/systemd/system/edgelab.slice" || die "edgelab.slice does not verify"
# The read-only dashboard (ADR 0024) is installed, never enabled here: enabling it and
# Tailscale Serve are the owner-approved steps in docs/DASHBOARD.md.
systemd-analyze verify "/etc/systemd/system/edgelab-dashboard.service" || die "edgelab-dashboard does not verify"

echo "== 7/7 permission and runtime checks"
# First run as the service account creates the database (schema migration) and the status file.
runuser -u edgelab -- "$APP_ROOT/venv/bin/python" -m edge_lab.cli forward status \
  --db "$DATA/db/edge_lab.sqlite3" --status-file "$STATUS/latest.json" >/dev/null || true
fails=0
expect() { # description, command...  (command must succeed)
  local what=$1; shift
  if "$@" >/dev/null 2>&1; then echo "  ok   $what"; else echo "  FAIL $what"; fails=1; fi
}
expect_not() { local what=$1; shift
  if "$@" >/dev/null 2>&1; then echo "  FAIL $what"; fails=1; else echo "  ok   $what"; fi
}
mode() { stat -c '%U:%G %a' "$1"; }
expect "env file is root:edgelab 640" test "$(mode "$ENV_FILE")" = "root:edgelab 640"
expect "secrets file is root:root 600" test "$(mode "$SECRETS_FILE")" = "root:root 600"
expect "data dir is edgelab:edgelab 700" test "$(mode "$DATA")" = "edgelab:edgelab 700"
expect "db dir is edgelab:edgelab 700" test "$(mode "$DATA/db")" = "edgelab:edgelab 700"
expect "ledger dir is edgelab:edgelab 700" test "$(mode "$DATA/ledger")" = "edgelab:edgelab 700"
expect "backups dir is edgelab:edgelab 700" test "$(mode "$DATA/backups")" = "edgelab:edgelab 700"
expect "status dir is edgelab:edgelab 755" test "$(mode "$STATUS")" = "edgelab:edgelab 755"
expect "database created" test -f "$DATA/db/edge_lab.sqlite3"
expect "edgelab can read the env file" runuser -u edgelab -- test -r "$ENV_FILE"
expect_not "edgelab cannot read the secrets file" runuser -u edgelab -- test -r "$SECRETS_FILE"
expect "edgelab can write its database dir" runuser -u edgelab -- test -w "$DATA/db"
if id -u "$OTHER_USER" >/dev/null 2>&1; then
  expect_not "$OTHER_USER cannot read the env file" runuser -u "$OTHER_USER" -- test -r "$ENV_FILE"
  expect_not "$OTHER_USER cannot read the secrets file" runuser -u "$OTHER_USER" -- test -r "$SECRETS_FILE"
  expect_not "$OTHER_USER cannot list private data" runuser -u "$OTHER_USER" -- ls "$DATA"
  expect_not "$OTHER_USER cannot read the database" runuser -u "$OTHER_USER" -- test -r "$DATA/db/edge_lab.sqlite3"
  expect_not "$OTHER_USER cannot list backups" runuser -u "$OTHER_USER" -- ls "$DATA/backups"
  expect_not "$OTHER_USER cannot list the shadow ledger" runuser -u "$OTHER_USER" -- ls "$DATA/ledger"
  expect "$OTHER_USER can read the status file" runuser -u "$OTHER_USER" -- cat "$STATUS/latest.json"
fi
[ "$fails" -eq 0 ] || die "permission/runtime checks failed (see above)"
for u in "${UNITS[@]}"; do
  echo "  info $u.timer: $(systemctl is-enabled "$u.timer" 2>/dev/null || true)"
done

cat <<EOF

INSTALL OK: $SHA
Next (owner):
  1. Fail-closed dry run (outside the window it must be rejected before any order-book request).
     Use the check script: its failure is recorded as DEPLOYMENT_VERIFICATION, not pushed
     (runbook section 4.1, ADR 0028):
       sudo bash /opt/market-edge-lab/app/deploy/vps/verify_fail_closed.sh
     Expect "FAIL_CLOSED_CHECK: PASS". Anything else stops here.
  2. Activate the schedule:
       sudo systemctl enable --now ${CORE_TIMERS[*]/%/.timer}
       systemctl list-timers 'edgelab-*'
     $SEPARATELY_ACTIVATED.timer is installed but stays disabled until the Odds API activation
     in docs/deploy/DAILY_SHADOW_ACTIVATION.md section 5b (key, odds plan, one odds smoke).
  Stop everything at any time: sudo systemctl disable --now 'edgelab-*.timer'
EOF
