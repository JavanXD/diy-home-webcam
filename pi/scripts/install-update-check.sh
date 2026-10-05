#!/usr/bin/env bash
# Install overnight update-check timer + apply oneshot. Idempotent.
# Timer always enabled; the check script no-ops unless opt-in is on.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/home-webcam-pipeline}"
UNIT_DIR="${ROOT}/pi/host/systemd"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

echo "==> install webcam overnight update check"

mkdir -p "${INSTALL_ROOT}/pi/scripts" /var/lib/webcam-pipeline
for f in webcam-update-check.sh webcam-update-apply.sh; do
  src="${ROOT}/pi/scripts/$f"
  dst="${INSTALL_ROOT}/pi/scripts/$f"
  if [[ ! -f "$src" ]]; then
    echo "missing $src" >&2
    exit 1
  fi
  if [[ "$(readlink -f "$src" 2>/dev/null || echo "$src")" == "$(readlink -f "$dst" 2>/dev/null || echo "$dst")" ]]; then
    chmod 755 "$dst"
  else
    install -m 755 "$src" "$dst"
  fi
done

install -m 644 "${UNIT_DIR}/webcam-update-check.service" /etc/systemd/system/webcam-update-check.service
install -m 644 "${UNIT_DIR}/webcam-update-check.timer" /etc/systemd/system/webcam-update-check.timer
install -m 644 "${UNIT_DIR}/webcam-update-apply.service" /etc/systemd/system/webcam-update-apply.service

# Default prefs (opt-in off) if missing.
PREF=/var/lib/webcam-pipeline/updates.json
if [[ ! -f "$PREF" ]]; then
  cat >"$PREF" <<'EOF'
{
  "check_overnight": false,
  "ref": "main",
  "remote": "https://github.com/JavanXD/diy-home-webcam.git"
}
EOF
  chmod 644 "$PREF"
fi

# webcam user owns state so the LAN UI can toggle the checkbox.
if id webcam >/dev/null 2>&1; then
  chown webcam:webcam /var/lib/webcam-pipeline/updates.json 2>/dev/null || true
  touch /var/lib/webcam-pipeline/updates-state.json
  chown webcam:webcam /var/lib/webcam-pipeline/updates-state.json 2>/dev/null || true
  # installed-rev may be root-written on apply; readable by all.
  if [[ ! -f /var/lib/webcam-pipeline/installed-rev ]]; then
    touch /var/lib/webcam-pipeline/installed-rev
    chmod 644 /var/lib/webcam-pipeline/installed-rev
  fi
fi

systemctl daemon-reload
systemctl enable webcam-update-check.timer
systemctl start webcam-update-check.timer || true
echo "    timer enabled (check is opt-in via Pipeline home → Updates)"
