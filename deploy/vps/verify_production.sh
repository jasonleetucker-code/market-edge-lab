#!/usr/bin/env bash
# Read-only production state report for Market Edge Lab on the Chase Upside VPS.
#
# Prints one `STATE <NAME>: <value>` line per observed state, then a SUMMARY. It changes
# nothing: no writes, no service control, no network except one GET of the public
# Chase Upside /api/health. It needs no sudo. A section it cannot read without privilege
# prints NOT_READABLE_WITHOUT_PRIVILEGE instead of guessing. Every section runs even when
# an earlier one fails (set -u, not set -e).
#
# Usage: bash verify_production.sh          (as dynasty; or via sudo to read private sections)
#
# One state does not imply the next: an enabled timer is not a capture, a capture is not a
# valid day, and a clean journal is not a verified backup. Procedure:
# docs/deploy/DAILY_SHADOW_ACTIVATION.md.
set -u

APP=/opt/market-edge-lab/app
DATA=/var/lib/market-edge-lab
STATUS=/var/lib/market-edge-lab-status
NAMES=(pfm decision recheck status backup shadow settlement)
NR=NOT_READABLE_WITHOUT_PRIVILEGE
SUMMARY=()

state() { # NAME VALUE
  printf 'STATE %s: %s\n' "$1" "$2"
  SUMMARY+=("$1: $2")
}
detail() { sed 's/^/    /'; }
have() { command -v "$1" >/dev/null 2>&1; }

# The system journal is readable only by root or the adm/systemd-journal groups. Without it,
# journalctl silently shows nothing for system units, which must never read as "no entries".
# So the journal counts as readable only when a PID 1 (systemd) message is actually visible.
if journalctl -q --no-pager -n 1 _PID=1 -o cat 2>/dev/null | grep -q .; then
  JOURNAL=yes; JNOTE=""
elif [ "$(id -u)" -eq 0 ]; then
  JOURNAL=no; JNOTE="UNKNOWN (no system journal visible, even as root)"
else
  JOURNAL=no; JNOTE="UNKNOWN ($NR: journal)"
fi
# Unit states come from systemd. If it cannot be reached, they are UNKNOWN, never "not found".
if systemctl show --property=Version --value --no-pager >/dev/null 2>&1; then
  SYSTEMD=yes
else
  SYSTEMD=no
fi
NOSD="UNKNOWN (systemd not reachable from this shell)"

echo "== Market Edge Lab production state, host $(hostname), $(date -u +%Y-%m-%dT%H:%M:%SZ), user $(id -un), journal readable: ${JOURNAL}, systemd: ${SYSTEMD}"

# --------------------------------------------------------------------------- time
ny_time=$(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z')
state NY_TIME "$ny_time"
hh=$(TZ=America/New_York date +%H); mm=$(TZ=America/New_York date +%M)
minute=$((10#$hh * 60 + 10#$mm))
if [ "$minute" -ge 1060 ] && [ "$minute" -le 1115 ]; then
  state IN_CAPTURE_WINDOW "yes (17:40-18:35 America/New_York: read-only is fine; do not install or restart now)"
else
  state IN_CAPTURE_WINDOW "no"
fi
if [ "$SYSTEMD" = yes ]; then
  running=$(systemctl list-units 'edgelab-*' --state=running --no-legend --plain --no-pager 2>/dev/null | awk '{print $1}' | tr '\n' ' ')
  state RUNNING_UNITS "${running:-none}"
else
  state RUNNING_UNITS "$NOSD"
fi

# --------------------------------------------------------------------------- code and units
if [ -r "$APP/REVISION" ]; then
  state DEPLOYED_SHA "$(head -c 64 "$APP/REVISION" | tr -d '\n')"
else
  state DEPLOYED_SHA "NOT_FOUND ($APP/REVISION missing or unreadable)"
fi

if [ "$SYSTEMD" = yes ]; then
  echo "== timers"
  systemctl list-timers 'edgelab-*' --all --no-pager 2>&1 | detail
  enabled=0; timer_states=""
  for n in "${NAMES[@]}"; do
    s=$(systemctl is-enabled "edgelab-$n.timer" 2>/dev/null); s=${s:-not-found}
    timer_states="$timer_states $n=$s"
    [ "$s" = enabled ] && enabled=$((enabled + 1))
  done
  state TIMERS "${enabled}/${#NAMES[@]} enabled:${timer_states}"

  echo "== last result of each service"
  for n in "${NAMES[@]}"; do
    line=$(systemctl show "edgelab-$n.service" -p LoadState -p ActiveState -p Result -p ExecMainStatus \
           -p ActiveEnterTimestamp --no-pager 2>/dev/null | tr '\n' ' ')
    printf '    edgelab-%-11s %s\n' "$n" "${line:-UNKNOWN}"
  done
  failed=$(systemctl list-units 'edgelab-*' --state=failed --no-legend --plain --no-pager 2>/dev/null | awk '{print $1}' | tr '\n' ' ')
  state UNIT_RESULTS "failed units: ${failed:-none} (per-service Result/ExecMainStatus above)"
else
  state TIMERS "$NOSD"
  state UNIT_RESULTS "$NOSD"
fi

# --------------------------------------------------------------------------- status files
if [ -r "$STATUS/latest.json" ]; then
  latest=$(python3 - "$STATUS/latest.json" <<'PY' 2>&1
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as exc:
    print(f"UNPARSEABLE ({type(exc).__name__})")
    raise SystemExit(0)
keys = ("generated_at_utc", "last_closed_target_date", "last_closed_status", "last_closed_reasons",
        "valid_days", "first_valid_day", "days_with_captures", "invalid_days")
print(json.dumps({k: d.get(k) for k in keys}, sort_keys=True))
PY
)
  state LATEST_JSON "$latest"
else
  state LATEST_JSON "NOT_FOUND ($STATUS/latest.json)"
fi

if [ -r "$STATUS/shadow_daily.json" ]; then
  shadow=$(python3 - "$STATUS/shadow_daily.json" <<'PY' 2>&1
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as exc:
    print(f"UNPARSEABLE ({type(exc).__name__})")
    raise SystemExit(0)
fee = d.get("fee") or {}
settlement = d.get("settlement") or {}
out = {k: d.get(k) for k in ("state", "exit_code", "generated_at_utc", "latest_day", "valid_days")}
out["fee"] = {k: fee[k] for k in ("schedule_id", "status", "claim_basis", "claimable") if k in fee}
out["settlement"] = {"settled": settlement.get("settled"), "pending": len(settlement.get("pending") or []),
                     "conflicts": len(settlement.get("conflicts") or []),
                     "refresh": (settlement.get("refresh") or {}).get("status")}
out["days"] = [{"target_date": day.get("target_date"), "result": day.get("result"),
                "capture_status": day.get("capture_status"), "accounts": day.get("accounts")}
               for day in (d.get("days") or [])]
print(json.dumps(out, sort_keys=True))
PY
)
  state SHADOW_DAILY "$shadow"
else
  state SHADOW_DAILY "NOT_FOUND ($STATUS/shadow_daily.json: expected before the first shadow run)"
fi

if [ -r "$STATUS/last_failure.json" ]; then
  state LAST_FAILURE "$(head -c 500 "$STATUS/last_failure.json" | tr '\n' ' ')"
else
  state LAST_FAILURE "NONE_RECORDED (no $STATUS/last_failure.json)"
fi

# --------------------------------------------------------------------------- collector states
# Each is derived from its own evidence. None is inferred from another.
known=0
for n in pfm decision recheck status; do
  systemctl cat "edgelab-$n.service" >/dev/null 2>&1 && known=$((known + 1))
done
if [ "$SYSTEMD" != yes ]; then
  state COLLECTOR_INSTALLED "$NOSD"
elif [ -r "$APP/REVISION" ] && [ "$known" -eq 4 ]; then
  state COLLECTOR_INSTALLED "YES (code revision present; 4/4 collector services known to systemd)"
elif [ ! -e "$APP/REVISION" ] && [ "$known" -eq 0 ]; then
  state COLLECTOR_INSTALLED "NO"
else
  state COLLECTOR_INSTALLED "PARTIAL (revision file readable: $([ -r "$APP/REVISION" ] && echo yes || echo no); ${known}/4 collector services known)"
fi

if [ "$SYSTEMD" = yes ]; then
  c_enabled=0; c_states=""
  for n in pfm decision recheck status; do
    s=$(systemctl is-enabled "edgelab-$n.timer" 2>/dev/null); s=${s:-not-found}
    c_states="$c_states $n=$s"; [ "$s" = enabled ] && c_enabled=$((c_enabled + 1))
  done
  state TIMERS_ENABLED "$([ "$c_enabled" -eq 4 ] && echo YES || echo NO) (collector timers:${c_states})"
else
  state TIMERS_ENABLED "$NOSD"
fi

observed() { # NAME phase: a capture is observed only as a "complete" capture receipt in the journal
  if [ "$JOURNAL" != yes ]; then
    state "$1" "$JNOTE"
    return
  fi
  lines=$(journalctl -u "edgelab-$2.service" --since -48h --no-pager -q -o short-iso 2>/dev/null | grep '"status": "complete"')
  count=$(printf '%s' "$lines" | grep -c .)
  if [ "$count" -gt 0 ]; then
    state "$1" "YES (${count} complete $2 capture(s) in the last 48h; last at $(printf '%s\n' "$lines" | tail -1 | awk '{print $1}'))"
  else
    state "$1" "NO (journal readable; no complete $2 capture in the last 48h)"
  fi
}
observed PFM_CAPTURE_OBSERVED pfm
observed DECISION_CAPTURE_OBSERVED decision
observed RECHECK_CAPTURE_OBSERVED recheck

if [ -r "$STATUS/latest.json" ]; then
  valid=$(python3 -c 'import json,sys; v=json.load(open(sys.argv[1])).get("valid_days"); print("UNKNOWN" if v is None else v)' \
          "$STATUS/latest.json" 2>/dev/null)
  case "$valid" in
    ''|UNKNOWN) state VALID_DAY_OBSERVED "UNKNOWN (latest.json has no valid_days)" ;;
    0) state VALID_DAY_OBSERVED "NO (latest.json valid_days = 0)" ;;
    *) state VALID_DAY_OBSERVED "YES (latest.json valid_days = ${valid})" ;;
  esac
else
  state VALID_DAY_OBSERVED "UNKNOWN (latest.json not readable)"
fi

# --------------------------------------------------------------------------- stores and backups
if [ ! -e "$DATA" ]; then
  state DB_SIZES "NOT_FOUND ($DATA does not exist)"
elif [ -r "$DATA/db" ] && [ -x "$DATA/db" ] && [ -r "$DATA/ledger" ] && [ -x "$DATA/ledger" ]; then
  echo "== stores"
  ls -l "$DATA/db" "$DATA/ledger" 2>&1 | detail
  state DB_SIZES "$(du -sh "$DATA/db" "$DATA/ledger" 2>/dev/null | awk '{printf "%s=%s ", $2, $1}')"
else
  state DB_SIZES "$NR ($DATA is private to edgelab)"
fi

if [ ! -e "$DATA" ]; then
  files="NOT_FOUND ($DATA does not exist)"
elif [ -r "$DATA/backups" ] && [ -x "$DATA/backups" ]; then
  echo "== newest backups"
  ls -lt "$DATA/backups" 2>&1 | head -6 | detail
  ls -lt "$DATA/backups/ledger" 2>&1 | head -6 | detail
  files="listed above"
else
  files="$NR (backup directories)"
fi
if [ "$JOURNAL" = yes ]; then
  reports=$(journalctl -u edgelab-backup.service --since -8d --no-pager -q -o short-iso 2>/dev/null \
            | grep -E '"status": "(VERIFIED_BACKUP_AND_RESTORE|SKIPPED_NO_SOURCE|BACKED_UP[A-Z_]*|FAILED[A-Z_]*)"' | tail -4)
  echo "== last backup reports (8 days)"
  printf '%s\n' "${reports:-none}" | detail
  verified=$(printf '%s' "$reports" | grep -c VERIFIED_BACKUP_AND_RESTORE)
  state BACKUPS "files: ${files}; ${verified} VERIFIED_BACKUP_AND_RESTORE among the last 4 backup reports"
else
  state BACKUPS "files: ${files}; reports: ${JNOTE}"
fi

# --------------------------------------------------------------------------- journal and resources
if [ "$JOURNAL" = yes ]; then
  state JOURNAL_WARNINGS_24H "$(journalctl -u 'edgelab-*' -p warning --since -24h --no-pager -q 2>/dev/null | grep -c .)"
  state OOM_30D "$(journalctl -k --since -30d --no-pager -q 2>/dev/null | grep -ciE 'out of memory|oom-kill')"
else
  state JOURNAL_WARNINGS_24H "$JNOTE"
  state OOM_30D "$JNOTE"
fi

echo "== memory"
free -m 2>&1 | detail
slice=$(systemctl show edgelab.slice -p MemoryCurrent -p MemoryPeak -p MemoryMax --no-pager 2>/dev/null | tr '\n' ' ')
avail=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null)
state MEMORY "MemAvailable=${avail:-?}MB; edgelab.slice ${slice:-UNKNOWN}"

state DISK "$(df -h /var/lib 2>/dev/null | awk 'NR==2 {print $4 " free of " $2 " (" $5 " used) on " $6}')"

if [ "$SYSTEMD" = yes ]; then
  brisket=""
  for u in nginx dynasty dynasty-frontend docker; do
    s=$(systemctl is-active "$u" 2>/dev/null); brisket="$brisket $u=${s:-unknown}"
  done
  state BRISKET_UNITS "${brisket# }"
else
  state BRISKET_UNITS "$NOSD"
fi

if have curl; then
  # A plain GET: no method override, no request body, no output file.
  resp=$(curl -sS -m 5 -w '\n%{http_code}' https://chaseupside.com/api/health 2>&1)
  code=$(printf '%s\n' "$resp" | tail -1)
  body=$(printf '%s\n' "$resp" | sed '$d' | tr '\n' ' ' | head -c 200)
  state API_HEALTH "HTTP ${code} ${body}"
else
  state API_HEALTH "UNKNOWN (curl not installed)"
fi

# --------------------------------------------------------------------------- summary
echo
echo "== SUMMARY (as observed at $(date -u +%Y-%m-%dT%H:%M:%SZ); nothing was changed)"
for line in "${SUMMARY[@]}"; do
  printf '  %s\n' "$line"
done
echo "One state does not imply the next. PRODUCTION_VERIFIED needs direct evidence for each state."
exit 0
