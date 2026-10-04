#!/usr/bin/env bash
# Verify Pi host matches pi/host/desired.env (root/boot on NVMe, BOOT_ORDER).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DESIRED="${ROOT}/pi/host/desired.env"
# shellcheck source=/dev/null
source "$DESIRED"

EXPECT_ROOT_DISK="${EXPECT_ROOT_DISK:-nvme0n1}"
EXPECT_BOOT_DISK="${EXPECT_BOOT_DISK:-nvme0n1}"
BOOT_ORDER="${BOOT_ORDER:-0xf416}"

fail=0
root_src="$(findmnt -no SOURCE /)"
boot_src="$(findmnt -no SOURCE /boot/firmware 2>/dev/null || findmnt -no SOURCE /boot 2>/dev/null || true)"
order="$(vcgencmd bootloader_config 2>/dev/null | awk -F= '/^BOOT_ORDER=/{print $2}' | tr -d '\r' || true)"

echo "root:        $root_src"
echo "boot:        $boot_src"
echo "BOOT_ORDER:  ${order:-unknown}"
echo "eeprom:      $(vcgencmd bootloader_version 2>/dev/null | head -1 || echo unknown)"

if [[ "$root_src" != *"$EXPECT_ROOT_DISK"* ]]; then
  echo "FAIL: root not on $EXPECT_ROOT_DISK" >&2
  fail=1
else
  echo "OK: root on $EXPECT_ROOT_DISK"
fi

if [[ -n "$boot_src" && "$boot_src" != *"$EXPECT_BOOT_DISK"* ]]; then
  echo "FAIL: /boot/firmware not on $EXPECT_BOOT_DISK" >&2
  fail=1
elif [[ -n "$boot_src" ]]; then
  echo "OK: boot on $EXPECT_BOOT_DISK"
fi

if [[ -n "$order" && "$order" != "$BOOT_ORDER" ]]; then
  echo "FAIL: BOOT_ORDER=$order (desired $BOOT_ORDER) — run apply-bootloader.sh + reboot" >&2
  fail=1
elif [[ -n "$order" ]]; then
  echo "OK: BOOT_ORDER=$order"
fi

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "==> host storage/boot matches desired.env"
