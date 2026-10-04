#!/usr/bin/env bash
# Idempotent provisioning for the camera appliance on Raspberry Pi OS Lite.
set -euo pipefail

APP_USER="${APP_USER:-webcam}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/home-webcam-pipeline}"
CONFIG_DIR="${CONFIG_DIR:-/etc/webcam-camera}"
DATA_DIR="${DATA_DIR:-/var/lib/webcam-camera}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PI_SRC="$REPO_ROOT/pi/camera"

echo "==> provisioning camera appliance"
echo "    install root: $INSTALL_ROOT/pi/camera"
echo "    repo: $REPO_ROOT"

if [[ "$(uname -m)" != "aarch64" && "$(uname -m)" != "armv7l" ]]; then
  echo "warning: expected Raspberry Pi ARM; continuing anyway ($(uname -m))"
fi

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  sudo useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

sudo mkdir -p "$INSTALL_ROOT/pi" "$CONFIG_DIR" "$DATA_DIR"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip

# Camera stack (ignore failure on non-Pi hosts)
sudo apt-get install -y python3-picamera2 libcamera-apps || true

sudo rsync -a --delete \
  --exclude '.venv' --exclude 'data' --exclude '__pycache__' \
  "$PI_SRC/" "$INSTALL_ROOT/pi/camera/"
sudo rsync -a "$REPO_ROOT/shared/" "$INSTALL_ROOT/shared/"

if [[ ! -f "$CONFIG_DIR/camera.yaml" ]]; then
  sudo cp "$INSTALL_ROOT/pi/camera/config/camera.example.yaml" "$CONFIG_DIR/camera.yaml"
  echo "installed production default config at $CONFIG_DIR/camera.yaml (capture_backend: picamera2)"
  echo "    missing camera → auto Wartungsbild"
fi

sudo mkdir -p "$INSTALL_ROOT/pi/camera/data"
cd "$INSTALL_ROOT/pi/camera"
# Need system picamera2 from apt inside the venv
sudo python3 -m venv --system-site-packages .venv
sudo "$INSTALL_ROOT/pi/camera/.venv/bin/pip" install -r requirements.txt

sudo cp "$INSTALL_ROOT/pi/camera/systemd/webcam-camera.service" /etc/systemd/system/
sudo chown -R "$APP_USER:$APP_USER" "$INSTALL_ROOT/pi/camera/data" "$DATA_DIR"
sudo chown -R root:root "$INSTALL_ROOT/pi/camera"
sudo chown -R "$APP_USER:$APP_USER" "$INSTALL_ROOT/pi/camera/data"
sudo chown root:"$APP_USER" "$CONFIG_DIR/camera.yaml"
sudo chmod 640 "$CONFIG_DIR/camera.yaml"

sudo systemctl daemon-reload
sudo systemctl enable webcam-camera.service
sudo systemctl restart webcam-camera.service

sleep 2
curl -fsS "http://127.0.0.1:8080/health" | head -c 500 || {
  echo "health check failed"
  sudo journalctl -u webcam-camera -n 50 --no-pager
  exit 1
}
echo
curl -fsS -o /tmp/webcam-provision-image.jpg "http://127.0.0.1:8080/raw.jpg" || {
  echo "/raw.jpg check failed (camera may still be warming; retry after capture)"
  sudo journalctl -u webcam-camera -n 50 --no-pager
  exit 1
}
python3 - <<'PY'
import json
h=json.load(open("/dev/stdin"))
print("provision health:", h.get("status"), "backend=", h.get("backend"), "model=", h.get("camera_model"))
PY <<< "$(curl -fsS http://127.0.0.1:8080/health)"
echo "==> camera provision complete"
