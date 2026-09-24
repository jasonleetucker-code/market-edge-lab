#!/usr/bin/env bash
# Failure alert for an edgelab-* unit (systemd OnFailure=). Read-only with respect to the
# lab's data: it records the failure in the status directory and the journal, and, only if
# the owner configured EDGE_LAB_ALERT_URL (e.g. a private ntfy topic) in
# /etc/market-edge-lab/env, sends a one-line notification there.
#
# Origin (ADR 0028 amendment, 2026-09-24). last_failure.json names the failed invocation
# (its systemd InvocationID) and an origin:
# - DEPLOYMENT_VERIFICATION only when root has confirmed that this exact invocation was the
#   runbook's fail-closed check (deploy/vps/verify_fail_closed.sh) and that it failed with
#   rejected_out_of_window. The confirmation is a file named after the invocation ID that
#   holds the unit, the ID and that status. It must be owned by root, like its directory, and
#   neither may be group- or world-writable, so no service account can forge one.
# - PRODUCTION in every other case: no confirmation, a confirmation for another invocation,
#   an untrusted or malformed file, no invocation ID, or any other failure of the same unit,
#   including one during a deployment.
# The check can only confirm after the unit has failed. So while a check is armed for this
# unit, this script waits (bounded) for the confirmation, then decides. It never decides from
# the clock. A DEPLOYMENT_VERIFICATION failure is recorded and logged, and the relay does not
# push it (notify_ntfy.relay_outbox). The optional webhook below fires for PRODUCTION only.
set -u
unit=$(printf '%s' "${1:-unknown}" | tr -c 'A-Za-z0-9@._-' '_')
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Overridable for tests only; the unit's environment comes from the root-owned env file.
status_dir="${EDGE_LAB_STATUS_DIR:-/var/lib/market-edge-lab-status}"
verify_dir="${EDGE_LAB_VERIFY_DIR:-/run/market-edge-lab-verify}"
trusted_uid="${EDGE_LAB_VERIFY_OWNER_UID:-0}"
wait_s="${EDGE_LAB_VERIFY_WAIT_SECONDS:-40}"

valid_id() { [ "${#1}" -eq 32 ] && case "$1" in *[!0-9a-f]*) return 1 ;; esac; }

# Owned by the trusted uid, not a symlink, not writable by group or others.
trusted() {
  [ -e "$1" ] && [ ! -L "$1" ] || return 1
  [ "$(stat -c %u -- "$1" 2>/dev/null)" = "$trusted_uid" ] || return 1
  mode=$(stat -c %a -- "$1" 2>/dev/null) || return 1
  case "${mode: -2}" in *[2367]*) return 1 ;; esac
  return 0
}

# systemd >= 251 passes the failed unit's invocation to OnFailure= units.
invocation="${MONITOR_INVOCATION_ID:-}"
[ -n "$invocation" ] || invocation=$(systemctl show -p InvocationID --value -- "$unit" 2>/dev/null || true)
valid_id "$invocation" || invocation=""

origin=PRODUCTION
if [ -n "$invocation" ] && [ "${MONITOR_SERVICE_RESULT:-exit-code}" = "exit-code" ] \
    && [ "${MONITOR_EXIT_STATUS:-1}" = "1" ] && trusted "$verify_dir"; then
  confirm="$verify_dir/confirmed-$invocation"
  waited=0
  while [ ! -e "$confirm" ] && [ -e "$verify_dir/armed-$unit" ] && [ "$waited" -lt "$wait_s" ]; do
    sleep 1
    waited=$((waited + 1))
  done
  expected="{\"unit\": \"$unit\", \"invocation_id\": \"$invocation\", \"status\": \"rejected_out_of_window\"}"
  if [ -f "$confirm" ] && trusted "$confirm" && [ "$(head -c 512 -- "$confirm" 2>/dev/null)" = "$expected" ]; then
    origin=DEPLOYMENT_VERIFICATION
  fi
fi

inv_json=null
[ -n "$invocation" ] && inv_json="\"$invocation\""
if [ "$origin" = PRODUCTION ]; then
  msg="market-edge-lab: ${unit} failed at ${now} on $(hostname). Check: journalctl -u ${unit}"
  logger -t edgelab-alert -p user.err -- "$msg"
else
  msg="market-edge-lab: ${unit} failed closed as expected at ${now} (${origin}, invocation ${invocation}). Recorded locally; not pushed."
  logger -t edgelab-alert -p user.notice -- "$msg"
fi
tmp="${status_dir}/last_failure.json.tmp"
printf '{"unit": "%s", "failed_at_utc": "%s", "invocation_id": %s, "origin": "%s"}\n' "$unit" "$now" "$inv_json" "$origin" > "$tmp" \
  && mv -f "$tmp" "${status_dir}/last_failure.json"
if [ "$origin" = PRODUCTION ] && [ -n "${EDGE_LAB_ALERT_URL:-}" ]; then
  curl -fsS -m 10 --retry 2 -H "Title: Market Edge Lab collector failure" -d "$msg" "$EDGE_LAB_ALERT_URL" >/dev/null \
    || logger -t edgelab-alert -p user.warning -- "alert delivery to EDGE_LAB_ALERT_URL failed"
fi
exit 0
