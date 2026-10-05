#!/usr/bin/env bash
# Apply appliance code from the public DIY GitHub branch tarball.
# Does NOT touch cameras/, runtime data/, /etc/webcam-*/env, or private overlays.
# Run as root (systemd oneshot). Restarts camera + pipeline afterward.
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/home-webcam-pipeline}"
PY="${INSTALL_ROOT}/pi/pipeline/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

export PYTHONPATH="${INSTALL_ROOT}/pi/pipeline:${INSTALL_ROOT}${PYTHONPATH:+:$PYTHONPATH}"
export INSTALL_ROOT

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

# Ensure rsync exists (Lite images usually have it from provision).
if ! command -v rsync >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y rsync
fi

exec "$PY" -c 'from app.updates import apply_from_tarball; import json; print(json.dumps(apply_from_tarball()))'
