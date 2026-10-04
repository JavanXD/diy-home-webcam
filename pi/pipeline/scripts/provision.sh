#!/usr/bin/env bash
# Idempotent install of the pipeline on the same Raspberry Pi as the camera.
set -euo pipefail

APP_USER="${APP_USER:-webcam}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/home-webcam-pipeline}"
CONFIG_DIR="${CONFIG_DIR:-/etc/webcam-pipeline}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

echo "==> provisioning webcam pipeline"
echo "    install root: $INSTALL_ROOT/pi/pipeline"

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  sudo useradd --system --home-dir /var/lib/webcam-pipeline --shell /usr/sbin/nologin "$APP_USER"
fi
# Read-only journal peek on Pipeline home (/system/logs) — fixed units only.
if getent group systemd-journal >/dev/null 2>&1; then
  sudo usermod -aG systemd-journal "$APP_USER" || true
fi

sudo mkdir -p "$INSTALL_ROOT/pi" "$CONFIG_DIR" /var/lib/webcam-pipeline
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip

sudo rsync -a --delete \
  --exclude '.venv' --exclude 'data' --exclude '__pycache__' --exclude '.pytest_cache' \
  "$REPO_ROOT/pi/pipeline/" "$INSTALL_ROOT/pi/pipeline/"
sudo rsync -a "$REPO_ROOT/cameras/" "$INSTALL_ROOT/cameras/"
sudo rsync -a "$REPO_ROOT/shared/" "$INSTALL_ROOT/shared/"

if [[ ! -f "$CONFIG_DIR/pipeline.yaml" ]]; then
  sudo cp "$INSTALL_ROOT/pi/pipeline/config/pipeline.example.yaml" "$CONFIG_DIR/pipeline.yaml"
  sudo sed -i "s|repo_root: null|repo_root: $INSTALL_ROOT|" "$CONFIG_DIR/pipeline.yaml" || true
  echo "installed $CONFIG_DIR/pipeline.yaml — enable publish + R2 when ready"
fi

# Optional: copy R2 env if present on the operator machine path
if [[ -f "$HOME/Projects/.secrets/example-webcam-r2.env" ]]; then
  sudo cp "$HOME/Projects/.secrets/example-webcam-r2.env" "$CONFIG_DIR/env"
  sudo chmod 600 "$CONFIG_DIR/env"
  sudo chown root:"$APP_USER" "$CONFIG_DIR/env"
  echo "installed $CONFIG_DIR/env from secrets store"
elif [[ ! -f "$CONFIG_DIR/env" ]]; then
  sudo touch "$CONFIG_DIR/env"
  sudo chmod 600 "$CONFIG_DIR/env"
  echo "created empty $CONFIG_DIR/env — add R2 keys (see pi/pipeline/config/r2.env.example)"
fi

cd "$INSTALL_ROOT/pi/pipeline"
sudo python3 -m venv .venv
sudo "$INSTALL_ROOT/pi/pipeline/.venv/bin/pip" install -r requirements.txt

sudo mkdir -p "$INSTALL_ROOT/data" "$INSTALL_ROOT/pi/pipeline/data" /var/lib/webcam-pipeline
# Durable ownership (also called from sync-to-pi.sh after remigrate/sync)
if [[ -x "$REPO_ROOT/pi/scripts/fix-data-perms.sh" ]]; then
  APP_USER="$APP_USER" INSTALL_ROOT="$INSTALL_ROOT" "$REPO_ROOT/pi/scripts/fix-data-perms.sh"
else
  sudo chown -R "$APP_USER:$APP_USER" \
    "$INSTALL_ROOT/data" "$INSTALL_ROOT/pi/pipeline/data" /var/lib/webcam-pipeline
fi
sudo chown -R "$APP_USER:$APP_USER" "$INSTALL_ROOT/pi/pipeline/.venv"

sudo cp "$INSTALL_ROOT/pi/pipeline/systemd/webcam-pipeline.service" /etc/systemd/system/
sudo mkdir -p /etc/polkit-1/rules.d
for rules in 50-webcam-network.rules 50-webcam-system.rules; do
  if [[ -f "$INSTALL_ROOT/pi/pipeline/systemd/$rules" ]]; then
    sudo cp "$INSTALL_ROOT/pi/pipeline/systemd/$rules" "/etc/polkit-1/rules.d/$rules"
    sudo chmod 644 "/etc/polkit-1/rules.d/$rules"
  fi
done
sudo systemctl daemon-reload
sudo systemctl enable webcam-pipeline.service
sudo systemctl restart webcam-pipeline.service

sleep 2
curl -fsS "http://127.0.0.1:8090/health" | head -c 400 || {
  echo "health check failed"
  sudo journalctl -u webcam-pipeline -n 50 --no-pager
  exit 1
}
echo
echo "==> pipeline provision complete"
