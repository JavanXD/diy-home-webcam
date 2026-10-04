#!/usr/bin/env bash
# First boot on the flashable DIY image: provision camera + pipeline, keep setup AP.
# Idempotent via marker file. No secrets are created here.
set -euo pipefail

MARKER=/var/lib/webcam-pipeline/image-first-boot.done
ROOT=/opt/home-webcam-pipeline
LOG=/var/log/webcam-image-first-boot.log

mkdir -p /var/lib/webcam-pipeline /var/log
exec >>"$LOG" 2>&1

if [[ -f "$MARKER" ]]; then
  echo "$(date -Is) first-boot already done ($MARKER)"
  exit 0
fi

echo "$(date -Is) webcam image first-boot starting"

hostnamectl set-hostname home-webcam 2>/dev/null || echo home-webcam >/etc/hostname

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
