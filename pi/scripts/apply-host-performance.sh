#!/usr/bin/env bash
# Apply headless host performance tuning (sysctl, journald, curated service disables).
# Idempotent. Code first: pi/host/performance.env
#
# Does NOT touch BOOT_ORDER, disks, WiFi/NetworkManager, avahi, SSH, nginx, or webcam units.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PERF="${ROOT}/pi/host/performance.env"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

if [[ ! -f "$PERF" ]]; then
  echo "missing $PERF" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$PERF"

DEFAULT_TARGET="${DEFAULT_TARGET:-multi-user.target}"
VM_SWAPPINESS="${VM_SWAPPINESS:-10}"
JOURNAL_SYSTEM_MAX_USE="${JOURNAL_SYSTEM_MAX_USE:-50M}"

# Fallback allowlist if performance.env has no array (older copy)
if ! declare -p DISABLE_SERVICES &>/dev/null || [[ ${#DISABLE_SERVICES[@]} -eq 0 ]]; then
  DISABLE_SERVICES=(
    lightdm.service
    wayvnc-control.service
    cups.service
    cups.socket
    cups.path
    bluetooth.service
    nfs-blkmap.service
    rpcbind.service
    rpcbind.socket
    accounts-daemon.service
    glamor-test.service
    rp1-test.service
  )
fi

echo "==> host performance (headless webcam appliance)"
echo "    source: $PERF"

echo "==> before"
free -h | sed 's/^/    /'
svc_before="$(systemctl list-units --type=service --state=running --no-pager --no-legend | wc -l | tr -d ' ')"
echo "    running services: $svc_before"
echo "    default target:   $(systemctl get-default 2>/dev/null || echo unknown)"
echo "    swappiness:       $(cat /proc/sys/vm/swappiness 2>/dev/null || echo unknown)"

echo "==> default target → $DEFAULT_TARGET"
systemctl set-default "$DEFAULT_TARGET"

SYSCTL_DROPIN=/etc/sysctl.d/99-webcam-host.conf
echo "==> sysctl $SYSCTL_DROPIN (vm.swappiness=$VM_SWAPPINESS)"
cat >"$SYSCTL_DROPIN" <<EOF
# Managed by pi/scripts/apply-host-performance.sh — do not edit by hand.
# Source of truth: pi/host/performance.env
vm.swappiness = ${VM_SWAPPINESS}
EOF
sysctl -p "$SYSCTL_DROPIN" >/dev/null

JOURNAL_DROPIN_DIR=/etc/systemd/journald.conf.d
JOURNAL_DROPIN="${JOURNAL_DROPIN_DIR}/99-webcam-host.conf"
echo "==> journald $JOURNAL_DROPIN (SystemMaxUse=$JOURNAL_SYSTEM_MAX_USE)"
mkdir -p "$JOURNAL_DROPIN_DIR"
cat >"$JOURNAL_DROPIN" <<EOF
# Managed by pi/scripts/apply-host-performance.sh — do not edit by hand.
# Source of truth: pi/host/performance.env
[Journal]
SystemMaxUse=${JOURNAL_SYSTEM_MAX_USE}
EOF
systemctl restart systemd-journald

echo "==> disable curated unused units (prefer disable over purge)"
for unit in "${DISABLE_SERVICES[@]}"; do
  if ! systemctl cat "$unit" &>/dev/null; then
    echo "    skip (not installed): $unit"
    continue
  fi
  systemctl stop "$unit" 2>/dev/null || true
  if systemctl is-enabled --quiet "$unit" 2>/dev/null \
    || [[ "$(systemctl is-enabled "$unit" 2>/dev/null || true)" == "enabled" ]]; then
    systemctl disable "$unit" 2>/dev/null || true
    echo "    disabled: $unit"
  else
    systemctl disable "$unit" 2>/dev/null || true
    echo "    ensured disabled: $unit"
  fi
  # Sockets/paths can stay active after disable; stop again
  systemctl stop "$unit" 2>/dev/null || true
done

if [[ -n "${CPU_GOVERNOR:-}" ]]; then
  echo "==> CPU governor → $CPU_GOVERNOR"
  for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    [[ -w "$gov" ]] || continue
    echo "$CPU_GOVERNOR" >"$gov" || true
  done
else
  echo "==> CPU governor: leave as-is ($(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo unknown))"
fi

echo "==> after"
free -h | sed 's/^/    /'
svc_after="$(systemctl list-units --type=service --state=running --no-pager --no-legend | wc -l | tr -d ' ')"
echo "    running services: $svc_after (was $svc_before)"
echo "    default target:   $(systemctl get-default)"
echo "    swappiness:       $(cat /proc/sys/vm/swappiness)"
echo "    journal disk:     $(journalctl --disk-usage 2>/dev/null | tr -d '\n')"
echo "    zram swap:        $(swapon --show --noheadings 2>/dev/null | awk '{print $1,$3}' | tr '\n' ' ' || echo none)"

# Sanity: must-keep units still up
keep_ok=1
for must in ssh.service nginx.service avahi-daemon.service NetworkManager.service \
  webcam-camera.service webcam-pipeline.service systemd-timesyncd.service; do
  if ! systemctl is-active --quiet "$must"; then
    echo "WARN: expected active: $must" >&2
    keep_ok=0
  fi
done
if [[ "$keep_ok" -eq 1 ]]; then
  echo "==> keep-alive check OK (ssh/nginx/avahi/NM/webcam-*/timesyncd)"
fi

echo "==> apply-host-performance done"
echo "    Desktop session may linger until reboot; reboot recommended once after first apply."
echo "    Re-apply anytime: sudo $ROOT/pi/scripts/apply-host-performance.sh"
