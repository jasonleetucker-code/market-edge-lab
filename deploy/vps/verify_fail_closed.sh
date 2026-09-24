#!/usr/bin/env bash
# Runbook section 4.1 (docs/deploy/DAILY_SHADOW_ACTIVATION.md): prove that the installed decision
# collector still fails closed, and have that intentional failure recorded as
# DEPLOYMENT_VERIFICATION instead of being pushed as a production incident (ADR 0028 amendment,
# 2026-09-24). Run as root, outside the capture window:
#
#   sudo bash /opt/market-edge-lab/app/deploy/vps/verify_fail_closed.sh
#
# Steps:
# 1. Refuse unless running as root and edgelab-decision.service is idle. The script can then
#    only start a new invocation, never join a scheduled one.
# 2. Arm: write armed-edgelab-decision.service in /run/market-edge-lab-verify (root-owned,
#    0755, on tmpfs, so a reboot clears it). While it exists, alert.sh waits (bounded) for a
#    confirmation of the invocation that failed. The armed file alone never changes an origin.
# 3. Start the real, installed unit. It must fail with rejected_out_of_window.
# 4. Read that invocation's InvocationID, Result and ExecMainStatus, and its own journal lines.
#    Confirm only if the invocation is new, Result=exit-code, ExecMainStatus=1, and the collector
#    printed "phase": "decision" and "status": "rejected_out_of_window".
# 5. Confirm: write confirmed-<InvocationID> (root-owned, 0644). alert.sh then records
#    origin=DEPLOYMENT_VERIFICATION for that invocation only, and the relay does not push it.
# 6. Wait until last_failure.json names the invocation, print it, disarm, and clear the failed
#    state of this one unit (reset-failed).
# Any other outcome is not confirmed: the unit succeeded, it failed another way, or the journal
# could not be read. Then the alert stays PRODUCTION and is pushed, and this script exits 1.
set -u
unit=edgelab-decision.service
# Overridable for tests only (sudo resets the environment).
verify_dir="${EDGE_LAB_VERIFY_DIR:-/run/market-edge-lab-verify}"
status_dir="${EDGE_LAB_STATUS_DIR:-/var/lib/market-edge-lab-status}"
owner_uid="${EDGE_LAB_VERIFY_OWNER_UID:-0}"
journal_wait="${EDGE_LAB_VERIFY_JOURNAL_WAIT_SECONDS:-10}"
record_wait="${EDGE_LAB_VERIFY_RECORD_WAIT_SECONDS:-90}"

say() { printf '%s\n' "$*"; }
stop() { say "FAIL_CLOSED_CHECK: $*"; exit 1; }
valid_id() { [ "${#1}" -eq 32 ] && case "$1" in *[!0-9a-f]*) return 1 ;; esac; }

[ "$(id -u)" = "$owner_uid" ] || stop "REFUSED: run as root (sudo bash $0)"
state=$(systemctl show -p ActiveState --value -- "$unit" 2>/dev/null) || stop "REFUSED: cannot read the state of $unit"
case "$state" in
  inactive|failed) ;;
  *) stop "REFUSED: $unit is '$state'; run this only while it is idle, outside the capture window" ;;
esac
previous=$(systemctl show -p InvocationID --value -- "$unit" 2>/dev/null || true)

umask 022
[ ! -L "$verify_dir" ] || stop "REFUSED: $verify_dir is a symlink"
mkdir -p -- "$verify_dir" && chmod 0755 -- "$verify_dir" || stop "REFUSED: cannot create $verify_dir"
[ "$(stat -c %u -- "$verify_dir")" = "$owner_uid" ] || stop "REFUSED: $verify_dir is not owned by uid $owner_uid"
armed="$verify_dir/armed-$unit"
trap 'rm -f -- "$armed"' EXIT
trap 'exit 1' HUP INT TERM
printf '{"unit": "%s"}\n' "$unit" > "$armed" || stop "REFUSED: cannot arm $armed"

say "== starting $unit (it must fail closed)"
if systemctl start -- "$unit"; then
  stop "NOT_CONFIRMED: $unit succeeded, so the collector did NOT fail closed. Investigate before anything else."
fi
invocation=$(systemctl show -p InvocationID --value -- "$unit" 2>/dev/null || true)
result=$(systemctl show -p Result --value -- "$unit" 2>/dev/null || true)
code=$(systemctl show -p ExecMainStatus --value -- "$unit" 2>/dev/null || true)
valid_id "$invocation" || stop "NOT_CONFIRMED: no readable InvocationID; the alert stays PRODUCTION"
[ "$invocation" != "$previous" ] || stop "NOT_CONFIRMED: no new invocation started; the alert stays PRODUCTION"
if [ "$result" != exit-code ] || [ "$code" != 1 ]; then
  stop "NOT_CONFIRMED: Result=$result ExecMainStatus=$code (expected exit-code and 1); the alert stays PRODUCTION"
fi

# The collector's stdout reaches the journal asynchronously: retry briefly.
output=""
i=0
while :; do
  output=$(journalctl --no-pager -q -o cat "_SYSTEMD_INVOCATION_ID=$invocation" 2>/dev/null || true)
  case "$output" in *'"status": "rejected_out_of_window"'*) break ;; esac
  [ "$i" -lt "$journal_wait" ] || break
  sleep 1
  i=$((i + 1))
done
say "== journal of invocation $invocation"
printf '%s\n' "$output" | tail -n 30
case "$output" in
  *'"status": "rejected_out_of_window"'*) ;;
  *) stop "NOT_CONFIRMED: the failure is not rejected_out_of_window; it stays a PRODUCTION alert" ;;
esac
case "$output" in
  *'"phase": "decision"'*) ;;
  *) stop "NOT_CONFIRMED: the output is not the decision phase; it stays a PRODUCTION alert" ;;
esac

tmp=$(mktemp "$verify_dir/.confirm.XXXXXX") || stop "NOT_CONFIRMED: cannot write the confirmation"
printf '{"unit": "%s", "invocation_id": "%s", "status": "rejected_out_of_window"}\n' "$unit" "$invocation" > "$tmp"
chmod 0644 -- "$tmp" && mv -f -- "$tmp" "$verify_dir/confirmed-$invocation" \
  || stop "NOT_CONFIRMED: cannot write the confirmation"
say "CONFIRMED: invocation $invocation failed closed (rejected_out_of_window)"

recorded=""
i=0
while [ "$i" -lt "$record_wait" ]; do
  line=$(head -c 1024 -- "$status_dir/last_failure.json" 2>/dev/null || true)
  case "$line" in *"\"invocation_id\": \"$invocation\""*) recorded=$line; break ;; esac
  sleep 1
  i=$((i + 1))
done
[ -n "$recorded" ] || stop "ALERT_NOT_RECORDED: last_failure.json does not name $invocation (journalctl -u 'edgelab-alert@*')"
say "RECORDED: $recorded"
case "$recorded" in
  *'"origin": "DEPLOYMENT_VERIFICATION"'*) ;;
  *) stop "ORIGIN_NOT_VERIFICATION: the failure was recorded as a production failure" ;;
esac
systemctl reset-failed -- "$unit" 2>/dev/null || true
say "FAIL_CLOSED_CHECK: PASS (recorded as DEPLOYMENT_VERIFICATION; not pushed as a production failure)"
exit 0
