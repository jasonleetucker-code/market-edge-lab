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
# Read-only input overrides, for tests and for checking copied files off-host:
#   EDGE_LAB_VERIFY_STATUS_DIR       read latest.json / shadow_daily.json / last_failure.json here
#   EDGE_LAB_VERIFY_BACKUP_JOURNAL   read `journalctl -u edgelab-backup.service -o json` lines
#                                    from this file instead of the journal
# Each override is announced in the output, so an overridden report is never mistaken for
# a production one.
#
# One state does not imply the next: an enabled timer is not a capture, a capture is not a
# valid day, a backup is not a verified restore. The directive's post-deployment states
# (DEPLOYED_SHA, COLLECTOR_HEALTH, SHADOW_TIMER, SETTLEMENT_TIMER, BACKUP_EVIDENCE_DB,
# BACKUP_SHADOW_LEDGER, RESTORE_EVIDENCE_DB, RESTORE_SHADOW_LEDGER, CHASE_UPSIDE_HEALTH) are
# each reported on their own line. Procedure: docs/deploy/DAILY_SHADOW_ACTIVATION.md.
set -u

APP=/opt/market-edge-lab/app
DATA=/var/lib/market-edge-lab
STATUS=${EDGE_LAB_VERIFY_STATUS_DIR:-/var/lib/market-edge-lab-status}
BACKUP_JOURNAL=${EDGE_LAB_VERIFY_BACKUP_JOURNAL:-}
NAMES=(pfm decision recheck status backup shadow settlement)
NR=NOT_READABLE_WITHOUT_PRIVILEGE
SUMMARY=()

state() { # NAME VALUE
  printf 'STATE %s: %s\n' "$1" "$2"
  SUMMARY+=("$1: $2")
}
states_from() { # lines of NAME-tab-VALUE printed by an embedded parser
  while IFS=$'\t' read -r name value; do
    [ -n "$name" ] && state "$name" "$value"
  done <<< "$1"
}
detail() { sed 's/^/    /'; }
have() { command -v "$1" >/dev/null 2>&1; }

# --------------------------------------------------------------------------- embedded parsers
# Run as `python3 -I -B` (isolated: no user site, no environment, no bytecode written).
# They only read the file or stdin they are given and print NAME-tab-VALUE lines.

IFS= read -r -d '' PY_LATEST <<'PY' || :
import json, sys
from datetime import datetime, timezone

def emit(name, value):
    print(f"{name}\t{value}")

try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        d = json.load(stream)
    problem = None if isinstance(d, dict) else f"NOT_A_JSON_OBJECT ({type(d).__name__})"
except Exception as exc:
    d, problem = None, f"UNPARSEABLE ({type(exc).__name__})"
if problem:
    emit("LATEST_JSON", problem)
    emit("LATEST_JSON_AGE", "UNKNOWN")
    emit("COLLECTOR_HEALTH", f"UNKNOWN (latest.json {problem})")
    emit("VALID_DAY_OBSERVED", f"UNKNOWN (latest.json {problem})")
    raise SystemExit(0)
keys = ("generated_at_utc", "last_closed_target_date", "last_closed_status", "last_closed_reasons",
        "valid_days", "first_valid_day", "days_with_captures", "invalid_days")
emit("LATEST_JSON", json.dumps({k: d.get(k) for k in keys}, sort_keys=True))
generated = d.get("generated_at_utc")
try:
    at = datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
    if at.tzinfo is None:
        raise ValueError("naive")
    hours = (datetime.now(timezone.utc) - at).total_seconds() / 3600
    age = f"{hours:.1f}h (generated_at_utc {generated})"
except ValueError:
    age = "UNKNOWN (no parseable generated_at_utc)"
emit("LATEST_JSON_AGE", age)
status = d.get("last_closed_status")
if isinstance(status, str) and status:
    reasons = json.dumps(d.get("last_closed_reasons"))
    emit("COLLECTOR_HEALTH", f"{status} (last closed day {d.get('last_closed_target_date')}; reasons {reasons}; "
                             f"latest.json age {age})")
else:
    emit("COLLECTOR_HEALTH", "UNKNOWN (latest.json has no last_closed_status)")
valid = d.get("valid_days")
if isinstance(valid, bool) or not isinstance(valid, int) or valid < 0:
    emit("VALID_DAY_OBSERVED", f"UNKNOWN (latest.json valid_days is not a non-negative integer: {valid!r})")
elif valid == 0:
    emit("VALID_DAY_OBSERVED", "NO (latest.json valid_days = 0)")
else:
    emit("VALID_DAY_OBSERVED", f"YES (latest.json valid_days = {valid})")
PY

IFS= read -r -d '' PY_SHADOW <<'PY' || :
import json, sys

try:
    with open(sys.argv[1], encoding="utf-8") as stream:
        d = json.load(stream)
    problem = None if isinstance(d, dict) else f"NOT_A_JSON_OBJECT ({type(d).__name__})"
except Exception as exc:
    d, problem = None, f"UNPARSEABLE ({type(exc).__name__})"
if problem:
    print(f"SHADOW_DAILY\t{problem}")
    raise SystemExit(0)

def obj(value):
    return value if isinstance(value, dict) else {}

def seq(value):
    return value if isinstance(value, list) else []

fee, settlement = obj(d.get("fee")), obj(d.get("settlement"))
out = {k: d.get(k) for k in ("state", "exit_code", "generated_at_utc", "latest_day", "valid_days")}
out["fee"] = {k: fee[k] for k in ("schedule_id", "status", "claim_basis", "claimable") if k in fee}
out["settlement"] = {"settled": settlement.get("settled"), "pending": len(seq(settlement.get("pending"))),
                     "conflicts": len(seq(settlement.get("conflicts"))),
                     "refresh": obj(settlement.get("refresh")).get("status")}
out["days"] = [{"target_date": day.get("target_date"), "result": day.get("result"),
                "capture_status": day.get("capture_status"), "accounts": day.get("accounts")}
               for day in seq(d.get("days")) if isinstance(day, dict)]
print(f"SHADOW_DAILY\t{json.dumps(out, sort_keys=True)}")
PY

# Backup reports: edgelab-backup.service runs `edge_lab.backup create` for the evidence DB,
# then for the shadow ledger, and each prints one JSON report (indented, so one journal line
# per JSON line). The parser groups journal lines by unit invocation, reassembles the JSON
# objects and classifies each by store_kind / kind / bundle path. A FAILED report names no
# store, so it is attributed by its order within the invocation, and says so.
# BACKUP_* comes from the created bundle; RESTORE_* only from verify_backup's result (the
# temporary restore reproduced schema and row counts), never from BACKUP_*.
IFS= read -r -d '' PY_BACKUP <<'PY' || :
import json, sys
from datetime import datetime, timezone

def emit(name, value):
    print(f"{name}\t{value}")

runs, order = {}, []
for line in sys.stdin:
    try:
        entry = json.loads(line)
    except ValueError:
        continue
    if not isinstance(entry, dict) or not isinstance(entry.get("MESSAGE"), str):
        continue
    run = entry.get("_SYSTEMD_INVOCATION_ID") or entry.get("INVOCATION_ID") or "unknown"
    if run not in runs:
        runs[run] = {"t": entry.get("__REALTIME_TIMESTAMP"), "lines": []}
        order.append(run)
    runs[run]["lines"].append(entry["MESSAGE"])

decoder = json.JSONDecoder()

def reports(text):
    found, i = [], 0
    while True:
        i = text.find("{", i)
        if i == -1:
            return found
        try:
            value, end = decoder.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(value, dict) and isinstance(value.get("status"), str):
            found.append(value)
        i = end

def when(stamp):
    try:
        return datetime.fromtimestamp(int(stamp) / 1e6, timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return "UNKNOWN_TIME"

def store_of(report, position):
    for key in ("store_kind", "kind"):
        if report.get(key) in ("evidence", "ledger"):
            return report[key], ""
    bundle = report.get("bundle")
    if isinstance(bundle, str):
        return ("ledger" if "/ledger/" in bundle.replace("\\", "/") else "evidence"), ""
    if position in (0, 1):
        return ("evidence", "ledger")[position], " (store attributed by its order in the unit: evidence, then ledger)"
    return None, ""

def stamp_key(run):
    try:
        return int(runs[run]["t"])
    except (TypeError, ValueError):
        return 0

latest, total, newest_stores, newest_run = {}, 0, set(), None
for run in sorted(order, key=stamp_key):
    newest_run, newest_stores = run, set()
    for position, report in enumerate(reports("\n".join(runs[run]["lines"]))):
        total += 1
        store, note = store_of(report, position)
        if store is not None:
            latest[store] = (report, when(runs[run]["t"]), note)
            newest_stores.add(store)
emit("BACKUP_REPORTS_8D", f"{total} report(s) in {len(order)} run(s)")
for store, backup_name, restore_name in (("evidence", "BACKUP_EVIDENCE_DB", "RESTORE_EVIDENCE_DB"),
                                         ("ledger", "BACKUP_SHADOW_LEDGER", "RESTORE_SHADOW_LEDGER")):
    if store not in latest:
        emit(backup_name, "NONE_IN_WINDOW (no report for this store in the last 8 days)")
        emit(restore_name, "NONE_IN_WINDOW (no report for this store in the last 8 days)")
        continue
    report, at, note = latest[store]
    status = report["status"]
    if newest_run is not None and store not in newest_stores:
        # The newest backup run has no report for this store (for example it crashed before
        # printing one): an older result must not read as current.
        stale = f"NOT_IN_LATEST_RUN (the latest backup run, {when(runs[newest_run]['t'])}, has no {store} report); last seen: "
    else:
        stale = ""
    if isinstance(report.get("bundle"), str):
        backup = f"CREATED at {at}: {report['bundle']}{note}"
    elif status == "SKIPPED_NO_SOURCE":
        backup = f"SKIPPED_NO_SOURCE at {at} (the store did not exist yet)"
    elif status == "FAILED":
        backup = f"FAILED at {at}: {report.get('error')}{note}"
    else:
        backup = f"UNKNOWN at {at}: status {status} without a bundle{note}"
    restored = "row_counts" in report and "schema_sha256" in report
    if status == "VERIFIED_BACKUP_AND_RESTORE" and restored:
        counts = json.dumps(report["row_counts"], sort_keys=True)
        restore = f"VERIFIED at {at} (temporary restore reproduced schema and row counts {counts})"
    elif status.startswith("BACKED_UP_LEDGER_") and restored:
        restore = f"NOT_VERIFIED at {at}: {status} (the restore copy matched; the ledger itself fails its checks)"
    elif status == "SKIPPED_NO_SOURCE":
        restore = f"NOT_RUN at {at} (SKIPPED_NO_SOURCE)"
    elif status == "FAILED":
        restore = f"FAILED_OR_NOT_RUN at {at}: {report.get('error')}{note}"
    else:
        restore = f"UNKNOWN at {at}: status {status}"
    emit(backup_name, stale + backup)
    emit(restore_name, stale + restore)
PY

# --------------------------------------------------------------------------- access checks
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
[ -n "${EDGE_LAB_VERIFY_STATUS_DIR:-}" ] && echo "OVERRIDE status files read from ${STATUS} (not the production status directory)"
[ -n "$BACKUP_JOURNAL" ] && echo "OVERRIDE backup reports read from ${BACKUP_JOURNAL} (not the production journal)"

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
    line=$(systemctl show "edgelab-$n.service" -p LoadState -p ActiveState -p Result -p ExecMainStatus -p ActiveEnterTimestamp --no-pager 2>/dev/null | tr '\n' ' ')
    printf '    edgelab-%-11s %s\n' "$n" "${line:-UNKNOWN}"
  done
  failed=$(systemctl list-units 'edgelab-*' --state=failed --no-legend --plain --no-pager 2>/dev/null | awk '{print $1}' | tr '\n' ' ')
  state UNIT_RESULTS "failed units: ${failed:-none} (per-service Result/ExecMainStatus above)"
else
  state TIMERS "$NOSD"
  state UNIT_RESULTS "$NOSD"
fi

timer_state() { # NAME unit: the timer's own state and its service's last result, nothing inferred
  if [ "$SYSTEMD" != yes ]; then
    state "$1" "$NOSD"
    return
  fi
  en=$(systemctl is-enabled "$2.timer" 2>/dev/null); ac=$(systemctl is-active "$2.timer" 2>/dev/null)
  info=$(systemctl show "$2.timer" -p LastTriggerUSec -p NextElapseUSecRealtime --no-pager 2>/dev/null | tr '\n' ' ')
  res=$(systemctl show "$2.service" -p Result -p ExecMainStatus --no-pager 2>/dev/null | tr '\n' ' ')
  state "$1" "enabled=${en:-not-found} active=${ac:-unknown} ${info}last-run: ${res:-UNKNOWN}"
}
timer_state SHADOW_TIMER edgelab-shadow
timer_state SETTLEMENT_TIMER edgelab-settlement
timer_state OBSERVE_TIMER edgelab-observe
timer_state OBSERVE_CLOSE_TIMER edgelab-observe-close

# --------------------------------------------------------------------------- status files
if [ -r "$STATUS/latest.json" ]; then
  states_from "$(python3 -I -B -c "$PY_LATEST" "$STATUS/latest.json" 2>&1)"
else
  state LATEST_JSON "NOT_FOUND ($STATUS/latest.json)"
  state LATEST_JSON_AGE "UNKNOWN"
  state COLLECTOR_HEALTH "UNKNOWN (latest.json not readable)"
  state VALID_DAY_OBSERVED "UNKNOWN (latest.json not readable)"
fi

if [ -r "$STATUS/shadow_daily.json" ]; then
  states_from "$(python3 -I -B -c "$PY_SHADOW" "$STATUS/shadow_daily.json" 2>&1)"
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
  state BACKUPS "files: NOT_FOUND ($DATA does not exist)"
elif [ -r "$DATA/backups" ] && [ -x "$DATA/backups" ]; then
  echo "== newest backups"
  ls -lt "$DATA/backups" 2>&1 | head -6 | detail
  ls -lt "$DATA/backups/ledger" 2>&1 | head -6 | detail
  state BACKUPS "files: listed above"
else
  state BACKUPS "files: $NR (backup directories)"
fi

if [ -n "$BACKUP_JOURNAL" ]; then
  if [ -r "$BACKUP_JOURNAL" ]; then
    states_from "$(python3 -I -B -c "$PY_BACKUP" < "$BACKUP_JOURNAL" 2>&1)"
  else
    for s in BACKUP_REPORTS_8D BACKUP_EVIDENCE_DB BACKUP_SHADOW_LEDGER RESTORE_EVIDENCE_DB RESTORE_SHADOW_LEDGER; do
      state "$s" "UNKNOWN (override file ${BACKUP_JOURNAL} not readable)"
    done
  fi
elif [ "$JOURNAL" = yes ]; then
  states_from "$(journalctl -u edgelab-backup.service --since -8d --no-pager -q -o json 2>/dev/null | python3 -I -B -c "$PY_BACKUP" 2>&1)"
else
  for s in BACKUP_REPORTS_8D BACKUP_EVIDENCE_DB BACKUP_SHADOW_LEDGER RESTORE_EVIDENCE_DB RESTORE_SHADOW_LEDGER; do
    state "$s" "$JNOTE"
  done
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

# --------------------------------------------------------------------------- Chase Upside
brisket_active=0
if [ "$SYSTEMD" = yes ]; then
  brisket=""
  for u in nginx dynasty dynasty-frontend docker; do
    s=$(systemctl is-active "$u" 2>/dev/null); brisket="$brisket $u=${s:-unknown}"
    [ "$s" = active ] && brisket_active=$((brisket_active + 1))
  done
  state BRISKET_UNITS "${brisket# }"
else
  state BRISKET_UNITS "$NOSD"
fi

code=""
if have curl; then
  # A plain GET over https only: no method override, no request body, no output file, no curlrc.
  resp=$(curl -q --proto =https -sS -m 5 -w '\n%{http_code}' https://chaseupside.com/api/health 2>&1)
  code=$(printf '%s\n' "$resp" | tail -1)
  body=$(printf '%s\n' "$resp" | sed '$d' | tr '\n' ' ' | head -c 200)
  state API_HEALTH "HTTP ${code} ${body}"
else
  state API_HEALTH "UNKNOWN (no curl command found)"
fi

if [ "$SYSTEMD" != yes ] || [ -z "$code" ]; then
  state CHASE_UPSIDE_HEALTH "UNKNOWN (units: $([ "$SYSTEMD" = yes ] && echo "${brisket_active}/4 active" || echo unknown); /api/health: HTTP ${code:-not checked})"
elif [ "$brisket_active" -eq 4 ] && [ "$code" = 200 ]; then
  state CHASE_UPSIDE_HEALTH "HEALTHY (4/4 units active; /api/health HTTP 200)"
else
  state CHASE_UPSIDE_HEALTH "UNHEALTHY (${brisket_active}/4 units active; /api/health HTTP ${code})"
fi

# --------------------------------------------------------------------------- summary
echo
echo "== SUMMARY (as observed at $(date -u +%Y-%m-%dT%H:%M:%SZ); nothing was changed)"
for line in "${SUMMARY[@]}"; do
  printf '  %s\n' "$line"
done
echo "One state does not imply the next. PRODUCTION_VERIFIED needs direct evidence for each state."
exit 0
