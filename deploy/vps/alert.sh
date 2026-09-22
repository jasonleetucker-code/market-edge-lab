#!/usr/bin/env bash
# Failure alert for an edgelab-* unit (systemd OnFailure=). Read-only with respect to the
# lab's data: it records the failure in the status directory and the journal, and, only if
# the owner configured EDGE_LAB_ALERT_URL (e.g. a private ntfy topic) in
# /etc/market-edge-lab/env, sends a one-line notification there.
set -u
unit="${1:-unknown}"
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
status_dir=/var/lib/market-edge-lab-status
msg="market-edge-lab: ${unit} failed at ${now} on $(hostname). Check: journalctl -u ${unit}"
logger -t edgelab-alert -p user.err -- "$msg"
tmp="${status_dir}/last_failure.json.tmp"
printf '{"unit": "%s", "failed_at_utc": "%s"}\n' "$unit" "$now" > "$tmp" && mv -f "$tmp" "${status_dir}/last_failure.json"
if [ -n "${EDGE_LAB_ALERT_URL:-}" ]; then
  curl -fsS -m 10 --retry 2 -H "Title: Market Edge Lab collector failure" -d "$msg" "$EDGE_LAB_ALERT_URL" >/dev/null \
    || logger -t edgelab-alert -p user.warning -- "alert delivery to EDGE_LAB_ALERT_URL failed"
fi
exit 0
