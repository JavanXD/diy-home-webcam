#!/usr/bin/env bash
# Install both Pi services (camera :8080 + pipeline :8090).
# Home Assistant only consumes the package YAML; it does not run this code.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> camera appliance"
"$ROOT/pi/camera/scripts/provision.sh"

echo "==> pipeline (same host, :8090)"
"$ROOT/pi/pipeline/scripts/provision.sh"

echo "==> setup Wi-Fi AP helper (no-op on already-configured Wi-Fi)"
sudo "$ROOT/pi/scripts/install-setup-ap.sh"

echo "==> overnight DIY update check timer (opt-in in LAN UI; default off)"
sudo "$ROOT/pi/scripts/install-update-check.sh"

echo "==> Pi ready: :8080 capture, :8090 variants. Import examples/homeassistant/webcam.yaml (or packages/webcam_example.yaml) into HA."
echo "    First-boot without Imager Wi-Fi: join SSID Webcam-Setup (password webcam-setup) → http://10.42.0.1:8090/setup/ui"
