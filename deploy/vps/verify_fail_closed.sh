#!/usr/bin/env bash
# Runbook section 4.1 (docs/deploy/DAILY_SHADOW_ACTIVATION.md): prove that the installed decision
# collector still fails closed, and have that intentional failure recorded as
# DEPLOYMENT_VERIFICATION instead of being pushed as a production incident (ADR 0028 amendment,
# 2026-09-24). Run as root, outside the capture window:
#
#   sudo bash /opt/market-edge-lab/app/deploy/vps/verify_fail_closed.sh
#
# Steps:
# 1. Refuse unless all of these hold:
#    - it runs as root, and no other copy of this check is running (flock);
#    - edgelab-decision.service is idle, so the script can only start a new invocation and
#      never join a scheduled one;
#    - edgelab-decision.timer is not due within 5 minutes.
# 2. Arm: write armed-edgelab-decision.service in /var/lib/market-edge-lab-verify (root-owned,
#    0755). While it exists, alert.sh waits (bounded) for a confirmation of the invocation that
#    failed. The armed file alone never changes an origin. A trap removes it on exit. A file
#    left by a killed check is removed at the next start, and alert.sh ignores one older than
#    15 minutes.
# 3. Start the real, installed unit. It must fail with rejected_out_of_window.
# 4. Read that invocation's InvocationID, Result and ExecMainStatus, and its own journal lines.
#    Confirm only if all of these hold:
#    - the invocation is new, and the timer did not trigger meanwhile (LastTriggerUSec unchanged);
#    - Result=exit-code and ExecMainStatus=1;
#    - the collector printed "phase": "decision" and "status": "rejected_out_of_window".
# 5. Confirm: write confirmed-<InvocationID> (root-owned, 0644). alert.sh then records
#    origin=DEPLOYMENT_VERIFICATION for that invocation only, in last_verification.json, and the
#    relay does not push it. The relay checks the confirmation again, so it is kept. Only
#    confirmations older than 7 days (far past the relay's 36-hour window) are tidied away.
# 6. Wait until last_verification.json names the invocation, print it, disarm, and clear the
#    failed state of this one unit (reset-failed).
# Any other outcome is not confirmed: the unit succeeded, it failed another way, or the journal
# could not be read. Then the alert stays PRODUCTION and is pushed, and this script exits 1.
set -u
unit=edgelab-decision.service
timer=edgelab-decision.timer
# Overridable for tests only (sudo resets the environment).
verify_dir="${EDGE_LAB_VERIFY_DIR:-/var/lib/market-edge-lab-verify}"
status_dir="${EDGE_LAB_STATUS_DIR:-/var/lib/market-edge-lab-status}"
owner_uid="${EDGE_LAB_VERIFY_OWNER_UID:-0}"
journal_wait="${EDGE_LAB_VERIFY_JOURNAL_WAIT_SECONDS:-10}"
record_wait="${EDGE_LAB_VERIFY_RECORD_WAIT_SECONDS:-90}"
timer_margin=300

say() { printf '%s\n' "$*"; }
stop() { say "FAIL_CLOSED_CHECK: $*"; exit 1; }
valid_id() { [ "${#1}" -eq 32 ] && case "$1" in *[!0-9a-f]*) return 1 ;; esac; }
prop() { systemctl show -p "$1" --value -- "$2" 2>/dev/null || true; }
journal_of() { journalctl --no-pager -q -o cat "_SYSTEMD_INVOCATION_ID=$1" 2>/dev/null || true; }

[ "$(id -u)" = "$owner_uid" ] || stop "REFUSED: run as root (sudo bash $0)"
umask 022
[ ! -L "$verify_dir" ] || stop "REFUSED: $verify_dir is a symlink"
mkdir -p -- "$verify_dir" && chmod 0755 -- "$verify_dir" || stop "REFUSED: cannot create $verify_dir"
[ "$(stat -c %u -- "$verify_dir")" = "$owner_uid" ] || stop "REFUSED: $verify_dir is not owned by uid $owner_uid"
exec 9>"$verify_dir/.lock" && flock -n 9 || stop "REFUSED: another fail-closed check is running"
# Holding the lock, any armed file is a leftover of a killed check: remove it.
rm -f -- "$verify_dir"/armed-*
find "$verify_dir" -maxdepth 1 -type f -name 'confirmed-*' -mtime +7 -delete 2>/dev/null || true

state=$(systemctl show -p ActiveState --value -- "$unit" 2>/dev/null) || stop "REFUSED: cannot read the state of $unit"
case "$state" in
  inactive|failed) ;;
  *) stop "REFUSED: $unit is '$state'; run this only while it is idle, outside the capture window" ;;
esac
# Not when the timer is about to fire: a scheduled run must never be mistaken for the check.
next=$(prop NextElapseUSecRealtime "$timer")
case "$next" in
  ""|n/a|0) ;;
  *)
    next_s=$(date -d "$next" +%s 2>/dev/null) || stop "REFUSED: cannot read when $timer fires next ($next)"
    [ $((next_s - $(date +%s))) -ge "$timer_margin" ] \
      || stop "REFUSED: $timer fires within 5 minutes ($next); run this later, outside the capture window"
    ;;
esac
previous=$(prop InvocationID "$unit")
trigger_before=$(prop LastTriggerUSec "$timer")

armed="$verify_dir/armed-$unit"
trap 'rm -f -- "$armed"' EXIT
trap 'exit 1' HUP INT TERM
printf '{"unit": "%s"}\n' "$unit" > "$armed" || stop "REFUSED: cannot arm $armed"

say "== starting $unit (it must fail closed)"
if systemctl start -- "$unit"; then
  started=$(prop InvocationID "$unit")
  output=""
  valid_id "$started" && output=$(journal_of "$started")
  case "$output" in
    *'"status": "skipped_duplicate"'*)
      stop "NOT_CONFIRMED: $unit exited 0 with skipped_duplicate. It ran inside its capture window, where a capture already existed, so the fail-closed path was not exercised. Run this check outside the window." ;;
    *'"status": "complete"'*)
      stop "NOT_CONFIRMED: $unit captured an order book (complete): it ran inside its capture window. Run this check outside the window." ;;
    *)
      stop "NOT_CONFIRMED: $unit succeeded, so the collector did NOT fail closed. Investigate before anything else." ;;
  esac
fi
invocation=$(prop InvocationID "$unit")
result=$(prop Result "$unit")
code=$(prop ExecMainStatus "$unit")
trigger_after=$(prop LastTriggerUSec "$timer")
valid_id "$invocation" || stop "NOT_CONFIRMED: no readable InvocationID; the alert stays PRODUCTION"
[ "$invocation" != "$previous" ] || stop "NOT_CONFIRMED: no new invocation started; the alert stays PRODUCTION"
[ "$trigger_after" = "$trigger_before" ] \
  || stop "NOT_CONFIRMED: $timer triggered during the check, so this run may be a scheduled one; the alert stays PRODUCTION"
if [ "$result" != exit-code ] || [ "$code" != 1 ]; then
  stop "NOT_CONFIRMED: Result=$result ExecMainStatus=$code (expected exit-code and 1); the alert stays PRODUCTION"
fi

# The collector's stdout reaches the journal asynchronously: retry briefly.
output=""
i=0
while :; do
  output=$(journal_of "$invocation")
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

named() { case "$(head -c 1024 -- "$1" 2>/dev/null || true)" in *"\"invocation_id\": \"$invocation\""*) return 0 ;; esac; return 1; }
i=0
while [ "$i" -lt "$record_wait" ]; do
  if named "$status_dir/last_verification.json"; then
    say "RECORDED: $(head -c 1024 -- "$status_dir/last_verification.json")"
    systemctl reset-failed -- "$unit" 2>/dev/null || true
    say "FAIL_CLOSED_CHECK: PASS (recorded as DEPLOYMENT_VERIFICATION in last_verification.json; not pushed)"
    exit 0
  fi
  named "$status_dir/last_failure.json" \
    && stop "ORIGIN_NOT_VERIFICATION: the failure was recorded as a production failure (last_failure.json)"
  sleep 1
  i=$((i + 1))
done
stop "ALERT_NOT_RECORDED: no record names $invocation (journalctl -u 'edgelab-alert@*')"
