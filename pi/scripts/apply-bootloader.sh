#!/usr/bin/env bash
# Apply pi/host/desired.env bootloader settings on the Pi (root).
# Updates rpi-eeprom package if needed, sets BOOT_ORDER, applies EEPROM config.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DESIRED="${ROOT}/pi/host/desired.env"
# shellcheck source=/dev/null
source "$DESIRED"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

BOOT_ORDER="${BOOT_ORDER:-0xf416}"

echo "==> desired BOOT_ORDER=$BOOT_ORDER"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq rpi-eeprom

TMP="$(mktemp)"
rpi-eeprom-config >"$TMP"
if grep -q '^BOOT_ORDER=' "$TMP"; then
  sed -i "s/^BOOT_ORDER=.*/BOOT_ORDER=${BOOT_ORDER}/" "$TMP"
else
  printf '\nBOOT_ORDER=%s\n' "$BOOT_ORDER" >>"$TMP"
fi
echo "--- config to apply ---"
cat "$TMP"
rpi-eeprom-config --apply "$TMP"
rm -f "$TMP"

# Also pull latest packaged EEPROM image when an update is available
rpi-eeprom-update -a || true
echo "--- status ---"
rpi-eeprom-update || true
echo
echo "Current (may need reboot to match applied config):"
vcgencmd bootloader_config 2>/dev/null | grep -E 'BOOT_ORDER|$' || true
vcgencmd bootloader_version 2>/dev/null | head -1 || true
echo "==> apply-bootloader done (reboot if UPDATE was pending or BOOT_ORDER still old)"
