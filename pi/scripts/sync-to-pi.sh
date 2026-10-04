#!/usr/bin/env bash
# From the Mac: rsync monorepo runtime trees to the Pi (code-first sync).
# Does not provision systemd (use pi/provision.sh on the Pi for that).
#
# # WARNING: cameras/ is synced with --delete. If you edited crops/masks on the Pi
# via the Variants LAN UI (/variants/ui), pull first or you will lose those YAML edits:
#   ./pi/scripts/pull-cameras-from-pi.sh pi@home-webcam.local
set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "usage: $0 pi@home-webcam.local" >&2
  echo "  tip: optional PI_SSH_KEY / PI_SSH_USER / PI_SSH_HOST (or pass the target)" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/home-webcam-pipeline}"


SSH_OPTS=(-o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "${PI_SSH_KEY:-}" ]]; then
  KEY="${PI_SSH_KEY/#\~/$HOME}"
  SSH_OPTS+=(-i "$KEY")
fi
RSYNC_SSH="ssh ${SSH_OPTS[*]}"

# Run a root shell on the Pi. If PI_SSH_PASSWORD is set, prime sudo -S once
# (do not mix the password into the script stdin — NOPASSWD/cached sudo would
# otherwise execute the password as the first script line).
remote_root() {
  local script
  script="$(cat)"
  if [[ -n "${PI_SSH_PASSWORD:-}" ]]; then
    printf '%s\n' "$PI_SSH_PASSWORD" | \
      ssh "${SSH_OPTS[@]}" "$TARGET" 'sudo -S -p "" true'
  fi
  ssh "${SSH_OPTS[@]}" "$TARGET" 'sudo bash -s' <<<"$script"
}

echo "==> sync $REPO_ROOT → $TARGET:$REMOTE_ROOT"
# Make code trees writable for rsync as the SSH user — never chown runtime data/
# while services run (webcam writes image.jpg / maintenance.on / focus-region.json).
# A recursive chown on pi/ previously flipped pi/camera/data to pi:pi mid-capture →
# PermissionError + capture-loop crash until fix-data-perms ran after rsync.
remote_root <<EOF
set -euo pipefail
REMOTE_ROOT='$REMOTE_ROOT'
OWNER="\$(stat -c '%U:%G' /home/\$(logname 2>/dev/null || echo pi) 2>/dev/null || echo pi:pi)"
# Prefer the SSH login user (sudo may change id).
if [[ -n "\${SUDO_USER:-}" ]]; then
  OWNER="\${SUDO_USER}:\$(id -gn "\${SUDO_USER}")"
fi
mkdir -p "\$REMOTE_ROOT"/{pi,cameras,shared,docs}
chown "\$OWNER" "\$REMOTE_ROOT"
chown_code() {
  local root="\$1"
  [[ -e "\$root" ]] || return 0
  # Prune runtime data/, venv, deploy backups — leave webcam ownership alone.
  find "\$root" \\
    \\( -path '*/data' -o -path '*/data/*' \\
       -o -path '*/.venv' -o -path '*/.venv/*' \\
       -o -path '*/.deploy-backup' -o -path '*/.deploy-backup/*' \\) -prune -o \\
    -print0 | xargs -0 -r chown "\$OWNER"
}
chown_code "\$REMOTE_ROOT/pi"
chown_code "\$REMOTE_ROOT/cameras"
chown_code "\$REMOTE_ROOT/shared"
chown_code "\$REMOTE_ROOT/docs"
EOF

RSYNC=(rsync -azL --delete -e "$RSYNC_SSH")
"${RSYNC[@]}" \
  --exclude '.venv' --exclude 'data' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude '.deploy-backup' \
  "$REPO_ROOT/pi/" "$TARGET:$REMOTE_ROOT/pi/"
"${RSYNC[@]}" --delete "$REPO_ROOT/cameras/" "$TARGET:$REMOTE_ROOT/cameras/"
"${RSYNC[@]}" --delete --exclude '__pycache__' --exclude '*.pyc' \
  "$REPO_ROOT/shared/" "$TARGET:$REMOTE_ROOT/shared/"
rsync -az -e "$RSYNC_SSH" \
  "$REPO_ROOT/docs/PI-HOST.md" \
  "$TARGET:$REMOTE_ROOT/docs/"

ssh "${SSH_OPTS[@]}" "$TARGET" \
  "chmod +x '$REMOTE_ROOT'/pi/scripts/*.sh '$REMOTE_ROOT'/pi/provision.sh 2>/dev/null || true"

# Restore service-user ownership on write paths (sync user is pi; units run as webcam).
remote_root <<EOF
'$REMOTE_ROOT/pi/scripts/fix-data-perms.sh'
EOF

echo "==> sync ok. Next on Pi (examples):"
echo "    sudo $REMOTE_ROOT/pi/scripts/verify-host.sh"
echo "    sudo $REMOTE_ROOT/pi/scripts/apply-host-performance.sh  # headless tuning"
echo "    sudo $REMOTE_ROOT/pi/scripts/apply-network.sh           # portable DHCP/DNS"
echo "    sudo $REMOTE_ROOT/pi/provision.sh"
echo "    sudo $REMOTE_ROOT/pi/scripts/remigrate-to-nvme.sh   # only if still on SD"
