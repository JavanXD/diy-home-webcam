#!/usr/bin/env bash
# Deploy pi/stream Extra to a remote Pi over SSH.
set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "usage: $0 user@raspberry-pi-host" >&2
  echo "  tip: set -a && source ~/Projects/.secrets/raspicam.env && set +a" >&2
  echo "       $0 \${RASPICAM_SSH_USER}@\${RASPICAM_HOST}" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/home-webcam-pipeline}"
VERSION="$(python3 -c "import sys; sys.path.insert(0,'$REPO_ROOT'); from shared.version import __version__; print(__version__)")"

SSH_OPTS=(-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "${RASPICAM_SSH_KEY:-}" ]]; then
  KEY="${RASPICAM_SSH_KEY/#\~/$HOME}"
  SSH_OPTS+=(-i "$KEY")
fi
RSYNC_SSH="ssh ${SSH_OPTS[*]}"

echo "==> deploy stream version $VERSION -> $TARGET:$REMOTE_ROOT/pi/stream"

rsync -az --delete -e "$RSYNC_SSH" \
  --exclude '.venv' --exclude 'data' --exclude '__pycache__' --exclude 'config/stream.yaml' \
  "$REPO_ROOT/pi/stream/" "$TARGET:$REMOTE_ROOT/pi/stream/"
rsync -az -e "$RSYNC_SSH" "$REPO_ROOT/shared/" "$TARGET:$REMOTE_ROOT/shared/"

ssh "${SSH_OPTS[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
REMOTE_ROOT="$REMOTE_ROOT"
cd "\$REMOTE_ROOT/pi/stream"
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
.venv/bin/pip install -q -r requirements.txt
sudo cp "\$REMOTE_ROOT/pi/stream/systemd/webcam-stream.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart webcam-stream.service

ok=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if curl -fsS http://127.0.0.1:8081/health >/tmp/webcam-stream-health.json 2>/dev/null; then
    ok=1
    break
  fi
  sleep 1
done
if [[ "\$ok" -ne 1 ]]; then
  echo "ERROR: /health never became ready" >&2
  sudo journalctl -u webcam-stream -n 40 --no-pager || true
  exit 1
fi
python3 - <<'PY'
import json
h = json.load(open("/tmp/webcam-stream-health.json"))
print("remote stream health:", h.get("status"), "version=", h.get("version"),
      "enabled=", h.get("enabled"))
PY
EOF

echo "==> deploy ok (version $VERSION)"
