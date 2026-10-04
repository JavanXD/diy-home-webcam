#!/usr/bin/env bash
# Deploy pi/camera app to a remote Pi over SSH.
# On failed health/image checks, automatically restores the newest backup.
set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "usage: $0 pi@home-webcam.local" >&2
  echo "  tip: optional PI_SSH_KEY / PI_SSH_USER / PI_SSH_HOST (or pass the target)" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/home-webcam-pipeline}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_NAME="camera-$STAMP"
VERSION="$(python3 -c "import sys; sys.path.insert(0,'$REPO_ROOT'); from shared.version import __version__; print(__version__)")"

SSH_OPTS=(-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "${PI_SSH_KEY:-}" ]]; then
  KEY="${PI_SSH_KEY/#\~/$HOME}"
  SSH_OPTS+=(-i "$KEY")
fi
RSYNC_SSH="ssh ${SSH_OPTS[*]}"

echo "==> deploy camera version $VERSION -> $TARGET:$REMOTE_ROOT/pi/camera"
echo "==> backup name: $BACKUP_NAME"

ssh "${SSH_OPTS[@]}" "$TARGET" "bash -s" <<EOF || true
set +e
if curl -fsS http://127.0.0.1:8080/health >/tmp/webcam-health-pre.json 2>/dev/null; then
  python3 -c 'import json; h=json.load(open("/tmp/webcam-health-pre.json")); print("remote version before deploy:", h.get("version"), "status=", h.get("status"))'
else
  echo "remote version before deploy: (service not reachable)"
fi
EOF

ssh "${SSH_OPTS[@]}" "$TARGET" "mkdir -p '$REMOTE_ROOT/.deploy-backup' && \
  if [[ -d '$REMOTE_ROOT/pi/camera' ]]; then \
    cp -a '$REMOTE_ROOT/pi/camera' '$REMOTE_ROOT/.deploy-backup/$BACKUP_NAME'; \
    ls -1dt '$REMOTE_ROOT/.deploy-backup'/camera-* 2>/dev/null | tail -n +4 | xargs -r rm -rf; \
  fi"

rsync -az --delete -e "$RSYNC_SSH" \
  --exclude '.venv' --exclude 'data' --exclude '__pycache__' --exclude 'config/camera.yaml' \
  "$REPO_ROOT/pi/camera/" "$TARGET:$REMOTE_ROOT/pi/camera/"
rsync -az -e "$RSYNC_SSH" "$REPO_ROOT/shared/" "$TARGET:$REMOTE_ROOT/shared/"

ssh "${SSH_OPTS[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
REMOTE_ROOT="$REMOTE_ROOT"
BACKUP_NAME="$BACKUP_NAME"

rollback() {
  echo "==> AUTO-ROLLBACK: restoring \$BACKUP_NAME"
  if [[ ! -d "\$REMOTE_ROOT/.deploy-backup/\$BACKUP_NAME" ]]; then
    echo "ERROR: backup missing; cannot auto-rollback" >&2
    exit 2
  fi
  rm -rf "\$REMOTE_ROOT/pi/camera"
  cp -a "\$REMOTE_ROOT/.deploy-backup/\$BACKUP_NAME" "\$REMOTE_ROOT/pi/camera"
  sudo systemctl restart webcam-camera.service || true
  sleep 2
  curl -fsS http://127.0.0.1:8080/health || true
  echo
  echo "==> rollback complete (deploy failed validation)"
}

cd "\$REMOTE_ROOT/pi/camera"
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
.venv/bin/pip install -q -r requirements.txt
sudo systemctl restart webcam-camera.service

ok=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if curl -fsS http://127.0.0.1:8080/health >/tmp/webcam-health.json 2>/dev/null; then
    ok=1
    break
  fi
  sleep 1
done

if [[ "\$ok" -ne 1 ]]; then
  echo "ERROR: /health never became ready" >&2
  rollback
  exit 1
fi

if ! curl -fsS -o /tmp/webcam-image.jpg http://127.0.0.1:8080/raw.jpg; then
  echo "ERROR: /raw.jpg failed" >&2
  rollback
  exit 1
fi

if ! python3 - <<'PY'
import json, sys
h = json.load(open("/tmp/webcam-health.json"))
status = h.get("status")
if status == "UNHEALTHY" and not h.get("has_valid_image"):
    print("ERROR: unhealthy with no valid image:", h, file=sys.stderr)
    sys.exit(1)
if not (h.get("has_valid_image") or status in ("HEALTHY", "DEGRADED")):
    print("ERROR: unexpected health:", h, file=sys.stderr)
    sys.exit(1)
print("remote health ok:", status, "version=", h.get("version"),
      "system_uptime=", h.get("system_uptime_seconds"))
PY
then
  rollback
  exit 1
fi
EOF

echo "==> deploy ok (version $VERSION)"
