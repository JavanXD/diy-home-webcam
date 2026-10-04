#!/usr/bin/env bash
# Ensure runtime write paths are owned by the webcam service user.
# Run on the Pi (sudo). Safe to re-run after sync/remigrate/deploy.
set -euo pipefail

APP_USER="${APP_USER:-webcam}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/home-webcam-pipeline}"

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  echo "fix-data-perms: user '$APP_USER' missing — run pi/provision.sh first" >&2
  exit 1
fi

dirs=(
  "$INSTALL_ROOT/data"
  "$INSTALL_ROOT/pi/pipeline/data"
  "$INSTALL_ROOT/pi/camera/data"
  /var/lib/webcam-pipeline
  /var/lib/webcam-camera
)

echo "==> fixing webcam data ownership ($APP_USER)"
for d in "${dirs[@]}"; do
  sudo mkdir -p "$d"
  sudo chown -R "$APP_USER:$APP_USER" "$d"
done

# Nested pipeline layout (original/variants/outbox/schedule) — created lazily by the app
sudo mkdir -p \
  "$INSTALL_ROOT/data/outbox" \
  "$INSTALL_ROOT/data/schedule"
sudo chown -R "$APP_USER:$APP_USER" "$INSTALL_ROOT/data"

# Variants LAN editor writes cameras/<id>/variants/*.yaml as $APP_USER.
# sync-to-pi.sh chowns cameras/ to the SSH user before rsync, then re-runs this script.
if [[ -d "$INSTALL_ROOT/cameras" ]]; then
  sudo mkdir -p "$INSTALL_ROOT/cameras"
  sudo chown -R "$APP_USER:$APP_USER" "$INSTALL_ROOT/cameras"
fi

echo "==> data perms ok"
ls -lad "${dirs[@]}" "$INSTALL_ROOT/cameras" 2>/dev/null || true
