#!/usr/bin/env bash
# Deploy pi/pipeline + cameras config to the same remote Pi over SSH.
set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "usage: $0 pi@raspicam.local" >&2
  echo "  tip: set -a && source ~/Projects/.secrets/home-webcam.env && set +a" >&2
  echo "       $0 \${WEBCAM_PI_SSH_USER}@\${WEBCAM_PI_HOST}" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/home-webcam-pipeline}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

SSH_OPTS=(-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "${WEBCAM_PI_SSH_KEY:-}" ]]; then
  KEY="${WEBCAM_PI_SSH_KEY/#\~/$HOME}"
  SSH_OPTS+=(-i "$KEY")
fi
RSYNC_SSH="ssh ${SSH_OPTS[*]}"

echo "==> deploy pipeline → $TARGET:$REMOTE_ROOT/pi/pipeline"

ssh "${SSH_OPTS[@]}" "$TARGET" "mkdir -p '$REMOTE_ROOT/.deploy-backup' && \
  if [[ -d '$REMOTE_ROOT/pi/pipeline' ]]; then \
    cp -a '$REMOTE_ROOT/pi/pipeline' '$REMOTE_ROOT/.deploy-backup/pipeline-$STAMP'; \
    ls -1dt '$REMOTE_ROOT/.deploy-backup'/pipeline-* 2>/dev/null | tail -n +4 | xargs -r rm -rf; \
  fi"

rsync -az --delete -e "$RSYNC_SSH" \
  --exclude '.venv' --exclude 'data' --exclude '__pycache__' --exclude '.pytest_cache' \
  "$REPO_ROOT/pi/pipeline/" "$TARGET:$REMOTE_ROOT/pi/pipeline/"
# cameras/ is owned by webcam after deploy so the Variants UI can write YAML.
# Hand it to the SSH user for this copy, then chown it back below.
ssh "${SSH_OPTS[@]}" "$TARGET" "sudo chown -R ${TARGET%%@*}:webcam '$REMOTE_ROOT/cameras'"
rsync -az --delete -e "$RSYNC_SSH" "$REPO_ROOT/cameras/" "$TARGET:$REMOTE_ROOT/cameras/"
rsync -az -e "$RSYNC_SSH" "$REPO_ROOT/shared/" "$TARGET:$REMOTE_ROOT/shared/"

ssh "${SSH_OPTS[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
cd "$REMOTE_ROOT/pi/pipeline"
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
.venv/bin/pip install -q -r requirements.txt
# Keep cameras/ owned by webcam (Variants UI writes YAML as that user).
sudo chown -R webcam:webcam "$REMOTE_ROOT/cameras" 2>/dev/null || true
if [[ -f /etc/webcam-pipeline/env ]]; then
  sudo chgrp webcam /etc/webcam-pipeline/env
  sudo chmod 660 /etc/webcam-pipeline/env
fi
sudo cp "$REMOTE_ROOT/pi/pipeline/systemd/webcam-pipeline.service" /etc/systemd/system/webcam-pipeline.service
sudo systemctl daemon-reload
sudo mkdir -p /etc/polkit-1/rules.d
for rules in 50-webcam-network.rules 50-webcam-system.rules; do
  if [[ -f "$REMOTE_ROOT/pi/pipeline/systemd/\$rules" ]]; then
    sudo cp "$REMOTE_ROOT/pi/pipeline/systemd/\$rules" "/etc/polkit-1/rules.d/\$rules"
    sudo chmod 644 "/etc/polkit-1/rules.d/\$rules"
  fi
done
# Journal peek (/system/logs) — webcam in systemd-journal (fixed units only).
if getent group systemd-journal >/dev/null 2>&1; then
  sudo usermod -aG systemd-journal webcam || true
fi
# Setup AP helper (ensure no-ops when home Wi-Fi profiles already exist).
if [[ -x "$REMOTE_ROOT/pi/scripts/install-setup-ap.sh" ]]; then
  sudo "$REMOTE_ROOT/pi/scripts/install-setup-ap.sh" || true
fi
sudo systemctl restart webcam-pipeline.service
for i in \$(seq 1 15); do
  if curl -fsS http://127.0.0.1:8090/health >/tmp/pipe-health.json; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:8090/health
python3 - <<'PY'
import json
h=json.load(open("/tmp/pipe-health.json"))
print("pipeline status:", h.get("status"), "version=", h.get("version"),
      "system_uptime=", h.get("system_uptime_seconds"))
assert h.get("application") == "webcam-pipeline"
assert h.get("system_uptime_seconds") is not None
PY
EOF

echo "==> deploy ok"
