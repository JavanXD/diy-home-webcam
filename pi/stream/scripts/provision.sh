#!/usr/bin/env bash
# Idempotent provisioning for the LAN MJPEG Extra (go2rtc-friendly).
# Pulls frames from webcam-camera over HTTP — never opens the CSI sensor.
set -euo pipefail

APP_USER="${APP_USER:-webcam}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/home-webcam-pipeline}"
CONFIG_DIR="${CONFIG_DIR:-/etc/webcam-stream}"
DATA_DIR="${DATA_DIR:-/var/lib/webcam-stream}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PI_SRC="$REPO_ROOT/pi/stream"

echo "==> provisioning webcam-stream (LAN MJPEG Extra)"
echo "    install root: $INSTALL_ROOT/pi/stream"
echo "    repo: $REPO_ROOT"

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  sudo useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

sudo mkdir -p "$INSTALL_ROOT/pi" "$CONFIG_DIR" "$DATA_DIR"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip

sudo rsync -a --delete \
  --exclude '.venv' --exclude 'data' --exclude '__pycache__' --exclude '.pytest_cache' \
  "$PI_SRC/" "$INSTALL_ROOT/pi/stream/"
sudo rsync -a "$REPO_ROOT/shared/" "$INSTALL_ROOT/shared/"

if [[ ! -f "$CONFIG_DIR/stream.yaml" ]]; then
  sudo cp "$INSTALL_ROOT/pi/stream/config/stream.example.yaml" "$CONFIG_DIR/stream.yaml"
  echo "installed $CONFIG_DIR/stream.yaml (LAN-only uncensored MJPEG; do not port-forward)"
fi

cd "$INSTALL_ROOT/pi/stream"
sudo python3 -m venv .venv
sudo "$INSTALL_ROOT/pi/stream/.venv/bin/pip" install -r requirements.txt

sudo cp "$INSTALL_ROOT/pi/stream/systemd/webcam-stream.service" /etc/systemd/system/
sudo chown -R root:root "$INSTALL_ROOT/pi/stream"
sudo chown -R "$APP_USER:$APP_USER" "$INSTALL_ROOT/pi/stream/.venv" "$DATA_DIR"
sudo chown root:"$APP_USER" "$CONFIG_DIR/stream.yaml"
sudo chmod 640 "$CONFIG_DIR/stream.yaml"

sudo systemctl daemon-reload
sudo systemctl enable webcam-stream.service
sudo systemctl restart webcam-stream.service

sleep 2
curl -fsS "http://127.0.0.1:8081/health" | head -c 500 || {
  echo "health check failed"
  sudo journalctl -u webcam-stream -n 50 --no-pager
  exit 1
}
echo
curl -fsS http://127.0.0.1:8081/health | python3 -c '
import json, sys
h = json.load(sys.stdin)
print(
    "provision health:",
    h.get("status"),
    "enabled=",
    h.get("enabled"),
    "has_frame=",
    (h.get("frame") or {}).get("has_frame"),
)
'
echo "==> stream provision complete"
echo "    MJPEG: http://<pi>:8081/stream.mjpg"
echo "    go2rtc example: examples/homeassistant/go2rtc.yaml"
echo "    LAN-only — do not port-forward :8081"
