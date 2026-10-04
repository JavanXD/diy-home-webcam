#!/usr/bin/env bash
# First boot on the flashable DIY image: rotate unique credentials, provision,
# keep setup AP. Idempotent via marker file. No cloud secrets are created here.
set -euo pipefail

MARKER=/var/lib/webcam-pipeline/image-first-boot.done
ROOT=/opt/home-webcam-pipeline
LOG=/var/log/webcam-image-first-boot.log
CRED_LIB="$ROOT/pi/scripts/webcam-device-credentials.sh"

mkdir -p /var/lib/webcam-pipeline /var/log
exec >>"$LOG" 2>&1

if [[ -f "$MARKER" ]]; then
  echo "$(date -Is) first-boot already done ($MARKER)"
  exit 0
fi

echo "$(date -Is) webcam image first-boot starting"

hostnamectl set-hostname home-webcam 2>/dev/null || echo home-webcam >/etc/hostname

# --- Unique credentials early (before long provision) so the boot card is ready ---
if [[ -f "$CRED_LIB" ]]; then
  # shellcheck source=/dev/null
  source "$CRED_LIB"
  SSH_USER="${FIRST_USER_NAME:-pi}"
  AP_SSID="${SETUP_AP_SSID:-Webcam-Setup}"
  AP_GW="${SETUP_AP_GATEWAY:-10.42.0.1}"
  AP_PSK="$(webcam_derive_setup_ap_psk)"
  SSH_PASS="$(webcam_derive_ssh_password)"
  webcam_persist_setup_ap_password "$AP_PSK" "$ROOT/pi/host/setup-ap.env"
  webcam_write_setup_card "$AP_SSID" "$AP_PSK" "$SSH_USER" "$SSH_PASS" "$AP_GW" || true
  if id "$SSH_USER" >/dev/null 2>&1; then
    echo "${SSH_USER}:${SSH_PASS}" | chpasswd
    echo "$(date -Is) set unique password for user ${SSH_USER} (see webcam-setup.txt)"
  fi
  # Prefer key-only SSH when Imager (or the user) installed an authorized_keys file.
  auth_keys="/home/${SSH_USER}/.ssh/authorized_keys"
  if [[ -s "$auth_keys" ]]; then
    mkdir -p /etc/ssh/sshd_config.d
    cat >/etc/ssh/sshd_config.d/99-webcam-key-only.conf <<'EOF'
# DIY image: Imager SSH public key present — disable password auth (CRA default).
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
    echo "$(date -Is) PasswordAuthentication no (authorized_keys present)"
  else
    echo "$(date -Is) no authorized_keys yet — password SSH kept for emergency (unique; on boot card)"
  fi
else
  echo "WARN: missing $CRED_LIB — skipping unique credential rotation" >&2
fi

# Keep generic example camera as the active pipeline default.
if [[ ! -d "$ROOT/cameras/example" && -d "$ROOT/examples/cameras/example" ]]; then
  mkdir -p "$ROOT/cameras/example"
  rsync -a "$ROOT/examples/cameras/example/" "$ROOT/cameras/example/"
fi
if [[ ! -f /etc/webcam-pipeline/pipeline.yaml && -f "$ROOT/examples/pi/pipeline.yaml" ]]; then
  install -d -m 755 /etc/webcam-pipeline
  install -m 644 "$ROOT/examples/pi/pipeline.yaml" /etc/webcam-pipeline/pipeline.yaml
  sed -i "s|repo_root: null|repo_root: $ROOT|" /etc/webcam-pipeline/pipeline.yaml || true
fi
if [[ ! -f /etc/webcam-pipeline/env ]]; then
  install -m 600 /dev/null /etc/webcam-pipeline/env
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# Prefer system NetworkManager tools already present on Lite.

if [[ -x "$ROOT/pi/provision.sh" ]]; then
  # Provision may fail health if no camera yet — still install units.
  set +e
  "$ROOT/pi/provision.sh"
  rc=$?
  set -e
  echo "provision exit=$rc"
else
  echo "ERROR: missing $ROOT/pi/provision.sh" >&2
  exit 1
fi

if [[ -x "$ROOT/pi/scripts/install-setup-ap.sh" ]]; then
  "$ROOT/pi/scripts/install-setup-ap.sh"
fi

# Run setup-AP ensure once now (settle time applies). Safe no-op if Imager Wi-Fi exists.
if [[ -x "$ROOT/pi/scripts/webcam-setup-ap.sh" ]]; then
  SETUP_AP_SETTLE_SECONDS="${SETUP_AP_SETTLE_SECONDS:-15}" \
    "$ROOT/pi/scripts/webcam-setup-ap.sh" ensure || true
fi

touch "$MARKER"
echo "$(date -Is) webcam image first-boot complete"
systemctl disable webcam-image-first-boot.service 2>/dev/null || true
