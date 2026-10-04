#!/usr/bin/env bash
# Roll back to the newest camera deploy backup on the remote Pi.
set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "usage: $0 user@raspberry-pi-host"
  exit 1
fi

REMOTE_ROOT="${REMOTE_ROOT:-/opt/home-webcam-pipeline}"

ssh "$TARGET" "bash -s" <<EOF
set -euo pipefail
BACKUP=\$(ls -1dt $REMOTE_ROOT/.deploy-backup/camera-* 2>/dev/null | head -1 || true)
if [[ -z "\$BACKUP" ]]; then
  echo "no backup found"
  exit 1
fi
echo "restoring \$BACKUP"
rm -rf $REMOTE_ROOT/pi/camera
cp -a "\$BACKUP" $REMOTE_ROOT/pi/camera
sudo systemctl restart webcam-camera.service
sleep 2
curl -fsS http://127.0.0.1:8080/health
echo
echo "rollback complete"
EOF
