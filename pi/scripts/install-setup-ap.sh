#!/usr/bin/env bash
# Install setup-AP systemd units + env. Idempotent. Safe on configured Pis
# (ensure no-ops when a home Wi-Fi profile already exists).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_SRC="${ROOT}/pi/host/setup-ap.env"
ENV_DST="/etc/webcam-setup-ap.env"
UNIT_DIR="${ROOT}/pi/host/systemd"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/home-webcam-pipeline}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

echo "==> install webcam setup AP helper"

mkdir -p "${INSTALL_ROOT}/pi/scripts" /etc/webcam-pipeline
# When ROOT already is INSTALL_ROOT (live /opt tree), chmod in place — do not install onto self.
for f in webcam-setup-ap.sh webcam-captive-redirect.py; do
  src="${ROOT}/pi/scripts/$f"
  dst="${INSTALL_ROOT}/pi/scripts/$f"
  if [[ "$(readlink -f "$src" 2>/dev/null || echo "$src")" == "$(readlink -f "$dst" 2>/dev/null || echo "$dst")" ]]; then
    chmod 755 "$dst"
  else
    install -m 755 "$src" "$dst"
  fi
done

if [[ ! -f "$ENV_DST" ]]; then
  install -m 644 "$ENV_SRC" "$ENV_DST"
  echo "    installed $ENV_DST"
else
  echo "    keeping existing $ENV_DST"
fi

install -m 644 "${UNIT_DIR}/webcam-setup-ap.service" /etc/systemd/system/webcam-setup-ap.service
install -m 644 "${UNIT_DIR}/webcam-captive-redirect.service" /etc/systemd/system/webcam-captive-redirect.service

# Unit paths assume INSTALL_ROOT=/opt/home-webcam-pipeline (shipped service files).
systemctl daemon-reload
systemctl enable webcam-setup-ap.service
# Do not run ensure during provision — settle sleep would stall SSH installs.
# Boot (or: sudo …/webcam-setup-ap.sh ensure) starts the AP only when needed.
echo "    enabled webcam-setup-ap.service (runs ensure on next boot)"
echo "==> setup AP install done"
echo "    Disable forever: sudo touch /etc/webcam-pipeline/setup-ap.disabled"
echo "    Status: sudo ${INSTALL_ROOT}/pi/scripts/webcam-setup-ap.sh status"
