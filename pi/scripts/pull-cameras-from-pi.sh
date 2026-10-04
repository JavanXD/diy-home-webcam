#!/usr/bin/env bash
# Pull cameras/ from the Pi back to the Mac repo (after LAN Variants editor saves).
# Use this BEFORE sync-to-pi.sh when you tuned crops/masks on the Pi — otherwise
# sync-to-pi.sh --delete will overwrite Pi cameras/ with the Mac copy.
set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "usage: $0 pi@home-webcam.local" >&2
  echo "  tip: set -a && source ~/Projects/.secrets/raspicam.env && set +a" >&2
  echo "       $0 \${RASPICAM_SSH_USER}@\${RASPICAM_HOST}" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/home-webcam-pipeline}"

SSH_OPTS=(-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "${RASPICAM_SSH_KEY:-}" ]]; then
  KEY="${RASPICAM_SSH_KEY/#\~/$HOME}"
  SSH_OPTS+=(-i "$KEY")
fi
RSYNC_SSH="ssh ${SSH_OPTS[*]}"


echo "==> pull $TARGET:$REMOTE_ROOT/cameras/ → $REPO_ROOT/cameras/"
echo "    (Pi Variants editor writes YAML here; pull before sync-to-pi.sh --delete)"
rsync -az -e "$RSYNC_SSH" \
  --exclude '.tmp' --exclude '*.yaml.tmp' \
  "$TARGET:$REMOTE_ROOT/cameras/" "$REPO_ROOT/cameras/"

echo "==> pull ok. Review changes before committing."
