#!/usr/bin/env bash
# Read-only headroom and isolation check for running Market Edge Lab's collector on the
# Chase Upside VPS (ADR 0012). Changes nothing; needs no sudo. Exit 0 = PASS.
set -u
fail=0
check() { # name ok(0/1) detail
  if [ "$2" -eq 0 ]; then printf 'PASS  %-28s %s\n' "$1" "$3"; else printf 'FAIL  %-28s %s\n' "$1" "$3"; fail=1; fi
}
echo "== host $(hostname) $(date -u +%Y-%m-%dT%H:%M:%SZ)"
avail_mb=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
total_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
check "memory available >= 1024 MB" $([ "$avail_mb" -ge 1024 ]; echo $?) "${avail_mb} of ${total_mb} MB"
# Worst case: every Brisket unit at its MemoryMax plus our 256M cap must fit in RAM.
caps=0
for u in dynasty.service dynasty-frontend.service; do
  m=$(systemctl show "$u" -p MemoryMax --value 2>/dev/null)
  case "$m" in ''|infinity) ;; *) caps=$((caps + m / 1048576));; esac
done
check "worst case fits (caps+256M)" $([ $((caps + 256 + 512)) -le "$total_mb" ]; echo $?) "brisket caps ${caps} MB + 256 + 512 reserve <= ${total_mb}"
disk_free_gb=$(df -BG --output=avail /var/lib | tail -1 | tr -dc 0-9)
check "disk free >= 5 GB" $([ "$disk_free_gb" -ge 5 ]; echo $?) "${disk_free_gb} GB on /var/lib"
inode_use=$(df --output=ipcent / | tail -1 | tr -dc 0-9)
check "inodes used < 80%" $([ "$inode_use" -lt 80 ]; echo $?) "${inode_use}%"
load1=$(cut -d' ' -f1 /proc/loadavg); cpus=$(nproc)
check "load1 < cpus" $(awk -v l="$load1" -v c="$cpus" 'BEGIN{exit !(l < c)}'; echo $?) "load ${load1} on ${cpus} cpus"
sd=$(systemctl --version | awk 'NR==1{print $2}')
check "systemd >= 235 (TZ timers)" $([ "$sd" -ge 235 ]; echo $?) "systemd ${sd}"
ntp=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)
check "clock NTP-synchronized" $([ "$ntp" = yes ]; echo $?) "NTPSynchronized=${ntp}"
check "America/New_York tzdata" $([ -e /usr/share/zoneinfo/America/New_York ]; echo $?) "/usr/share/zoneinfo/America/New_York"
pyok=$(python3 -c 'import sys; print(int(sys.version_info >= (3, 11)))' 2>/dev/null || echo 0)
check "python3 >= 3.11" $([ "$pyok" = 1 ]; echo $?) "$(python3 --version 2>&1)"
check "git available" $(command -v git >/dev/null; echo $?) "$(git --version 2>/dev/null)"
echo "== every timer's calendar (collection windows: EDT 21:45-22:20Z, EST 22:45-23:20Z)"
for t in $(systemctl list-unit-files --type=timer --no-legend 2>/dev/null | awk '{print $1}'); do
  cal=$(systemctl show "$t" -p TimersCalendar --value 2>/dev/null | grep -oE 'OnCalendar=[^;]*' | tr '
' ' ')
  [ -n "$cal" ] && printf '   %-48s %s
' "$t" "$cal"
done
if command -v sar >/dev/null; then
  echo "== sysstat: lowest available memory per day (last 7 files)"
  for f in $(ls -1 /var/log/sysstat/sa[0-9]* 2>/dev/null | tail -7); do
    LC_ALL=C sar -r -f "$f" 2>/dev/null | awk -v f="$f" 'NR>3 && $1 ~ /^[0-9]/ && $3+0>0 {if(m==""||$3+0<m){m=$3+0;t=$1}} END{if(m!="") printf "   %s min kbavail %s at %s\n", f, m, t}'
  done
fi
echo "== OOM kills in the last 30 days (visible to this user): $(journalctl -k --since -30d --no-pager 2>/dev/null | grep -ciE 'out of memory|oom-kill')"
[ "$fail" -eq 0 ] && echo "PREFLIGHT: PASS" || echo "PREFLIGHT: FAIL"
exit "$fail"
