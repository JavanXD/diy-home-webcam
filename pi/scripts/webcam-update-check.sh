#!/usr/bin/env bash
# Nightly / manual appliance update *check* (notify only — does not apply).
# Opt-in via /var/lib/webcam-pipeline/updates.json check_overnight=true.
# Safe to run when disabled: exits 0 after a no-op skip.
set -euo pipefail

INSTALL_ROOT="${INSTALL_ROOT:-/opt/home-webcam-pipeline}"
PY="${INSTALL_ROOT}/pi/pipeline/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

export PYTHONPATH="${INSTALL_ROOT}/pi/pipeline:${INSTALL_ROOT}${PYTHONPATH:+:$PYTHONPATH}"
export INSTALL_ROOT

# Allow "force" for Check now from a oneshot with FORCE=1
FORCE="${FORCE:-0}"
if [[ "$FORCE" == "1" ]]; then
  exec "$PY" -c 'from app.updates import run_check; import json; print(json.dumps(run_check(force=True)))'
else
  exec "$PY" -c 'from app.updates import maybe_overnight_check; import json; print(json.dumps(maybe_overnight_check()))'
fi
