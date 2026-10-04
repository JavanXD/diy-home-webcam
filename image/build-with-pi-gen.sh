#!/usr/bin/env bash
# Local / CI helper: clone pi-gen and build with image/stage-webcam.
# Requires Docker (privileged) and a long build (often 60–120+ minutes).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_DIR="${ROOT}/image"
WORK="${IMAGE_DIR}/pi-gen"
PIGEN_REPO="${PIGEN_REPO:-https://github.com/RPi-Distro/pi-gen.git}"
# Pin to bookworm-arm64 (Pi 5). master tracks trixie/armhf and breaks RELEASE=bookworm.
PIGEN_REF="${PIGEN_REF:-bookworm-arm64}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Re-running under sudo (pi-gen docker build needs root)…"
  exec sudo -E env "PATH=$PATH" "$0" "$@"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

# pi-gen build-docker.sh requires host qemu-aarch64-static when cross-building on x86_64.
case "$(uname -m)" in
  x86_64|amd64)
    if ! command -v qemu-aarch64-static >/dev/null 2>&1; then
      echo "==> installing qemu-user-static (arm64 binfmt on x86_64 host)"
      apt-get update -qq
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        qemu-user-static binfmt-support
    fi
    ;;
esac

echo "==> pi-gen worktree: $WORK"
if [[ ! -d "$WORK/.git" ]]; then
  rm -rf "$WORK"
  git clone --depth 1 --branch "$PIGEN_REF" "$PIGEN_REPO" "$WORK"
else
  git -C "$WORK" fetch --depth 1 origin "$PIGEN_REF"
  git -C "$WORK" checkout "$PIGEN_REF"
  git -C "$WORK" pull --ff-only || true
fi

cp "${IMAGE_DIR}/config" "${WORK}/config"
rm -rf "${WORK}/stage-webcam"
cp -a "${IMAGE_DIR}/stage-webcam" "${WORK}/stage-webcam"

# Stage a lean repo payload beside 01-run.sh (pi-gen worktree is not the monorepo root).
STAGE_FILES="${WORK}/stage-webcam/00-webcam/files/repo"
rm -rf "${STAGE_FILES}"
mkdir -p "${STAGE_FILES}"
rsync -a \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '**/__pycache__' \
  --exclude '**/.pytest_cache' \
  --exclude '.tmp-preview' \
  --exclude 'image/pi-gen' \
  --exclude 'webhosting/node_modules' \
  "${ROOT}/" "${STAGE_FILES}/"

find "${WORK}/stage-webcam" -type f -name '*.sh' -exec chmod +x {} +

# Point STAGE_LIST at the in-tree stage name
sed -i 's|STAGE_LIST=.*|STAGE_LIST="stage0 stage1 stage2 stage-webcam"|' "${WORK}/config"

# Preserve work/ between CI runs when mounted as a cache.
export PRESERVE_CONTAINER=0
cd "$WORK"
./build-docker.sh

echo "==> images:"
ls -lh "${WORK}/deploy" || true
