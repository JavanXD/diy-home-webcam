#!/bin/bash -e
# Copy the monorepo into the image and install first-boot + setup-AP units.
# Runs on the build host with ${ROOTFS_DIR} pointing at the target rootfs.
#
# Repo payload is staged by image/build-with-pi-gen.sh into ./files/repo
# (next to this script) so path math does not depend on the pi-gen worktree layout.

STAGE_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="${STAGE_DIR}/files/repo"
if [[ ! -d "${REPO_ROOT}/pi" ]]; then
  echo "ERROR: missing staged repo at ${REPO_ROOT} (run image/build-with-pi-gen.sh)" >&2
  exit 1
fi
TARGET_OPT="${ROOTFS_DIR}/opt/home-webcam-pipeline"

install -d -m 755 "${TARGET_OPT}"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '**/__pycache__' \
  --exclude '**/.pytest_cache' \
  --exclude '.tmp-preview' \
  --exclude 'image/pi-gen' \
  --exclude 'webhosting/node_modules' \
  "${REPO_ROOT}/" "${TARGET_OPT}/"

# Generic DIY defaults.
install -d -m 755 "${TARGET_OPT}/cameras/example"
rsync -a "${REPO_ROOT}/examples/cameras/example/" "${TARGET_OPT}/cameras/example/"

install -d -m 755 "${ROOTFS_DIR}/etc/webcam-pipeline" "${ROOTFS_DIR}/etc/webcam-camera"
install -m 644 "${REPO_ROOT}/examples/pi/pipeline.yaml" \
  "${ROOTFS_DIR}/etc/webcam-pipeline/pipeline.yaml"
sed -i "s|repo_root: null|repo_root: /opt/home-webcam-pipeline|" \
  "${ROOTFS_DIR}/etc/webcam-pipeline/pipeline.yaml" || true
install -m 600 /dev/null "${ROOTFS_DIR}/etc/webcam-pipeline/env"
install -m 640 "${REPO_ROOT}/pi/camera/config/camera.example.yaml" \
  "${ROOTFS_DIR}/etc/webcam-camera/camera.yaml"

install -m 644 "${REPO_ROOT}/pi/host/setup-ap.env" "${ROOTFS_DIR}/etc/webcam-setup-ap.env"
install -m 644 "${REPO_ROOT}/pi/host/systemd/webcam-setup-ap.service" \
  "${ROOTFS_DIR}/etc/systemd/system/webcam-setup-ap.service"
install -m 644 "${REPO_ROOT}/pi/host/systemd/webcam-captive-redirect.service" \
  "${ROOTFS_DIR}/etc/systemd/system/webcam-captive-redirect.service"
install -m 644 "${REPO_ROOT}/image/first-boot/webcam-image-first-boot.service" \
  "${ROOTFS_DIR}/etc/systemd/system/webcam-image-first-boot.service"
install -m 755 "${REPO_ROOT}/image/first-boot/webcam-image-first-boot.sh" \
  "${ROOTFS_DIR}/usr/local/sbin/webcam-image-first-boot.sh"

# Hostname for DIY image (ops live host may differ).
echo "home-webcam" > "${ROOTFS_DIR}/etc/hostname"
if [[ -f "${ROOTFS_DIR}/etc/hosts" ]]; then
  if grep -qE 'raspberrypi|home-webcam' "${ROOTFS_DIR}/etc/hosts"; then
    sed -i 's/raspberrypi/home-webcam/g' "${ROOTFS_DIR}/etc/hosts"
  else
    echo "127.0.1.1 home-webcam" >> "${ROOTFS_DIR}/etc/hosts"
  fi
fi

on_chroot <<'EOF'
set -e
chmod +x /opt/home-webcam-pipeline/pi/scripts/*.sh \
  /opt/home-webcam-pipeline/pi/provision.sh \
  /opt/home-webcam-pipeline/pi/scripts/webcam-captive-redirect.py \
  /opt/home-webcam-pipeline/pi/scripts/webcam-device-credentials.sh \
  /usr/local/sbin/webcam-image-first-boot.sh
systemctl enable ssh
systemctl enable NetworkManager || true
systemctl enable avahi-daemon || true
systemctl enable webcam-image-first-boot.service
systemctl enable webcam-setup-ap.service
: > /etc/webcam-pipeline/env
chmod 600 /etc/webcam-pipeline/env
# Placeholder boot-card note until first-boot writes the unique PSK.
install -d -m 755 /boot/firmware
cat >/boot/firmware/webcam-setup.txt <<'CARD'
# Home webcam — unique credentials are written on first boot.
# After the Pi has booted once, remount this boot partition (or read the file
# on the running Pi) for SSID Webcam-Setup PASSWORD=… and optional SSH_PASSWORD.
# Prefer Raspberry Pi Imager SSH public key over password login.
CARD
EOF
