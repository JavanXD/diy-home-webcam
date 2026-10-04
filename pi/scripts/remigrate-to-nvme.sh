#!/usr/bin/env bash
# On-Pi orchestrator: clone OS to NVMe, apply bootloader desired state, reboot.
# Requires: currently booted from SRC_DISK (SD). Run as root.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DESIRED="${ROOT}/pi/host/desired.env"
# shellcheck source=/dev/null
source "$DESIRED"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

root_src="$(findmnt -no SOURCE /)"
if [[ "$root_src" == *"${EXPECT_ROOT_DISK:-nvme0n1}"* ]]; then
  echo "already on ${EXPECT_ROOT_DISK}: running verify only"
  "$HERE/verify-host.sh"
  exit 0
fi

echo "==> remigrate: migrate SD → NVMe"
"$HERE/migrate-os-to-nvme.sh"

echo "==> remigrate: apply bootloader ($BOOT_ORDER)"
"$HERE/apply-bootloader.sh"

echo "==> remigrate: reboot in 2s (NVMe-first after EEPROM applies)"
sync
sleep 2
systemctl reboot
