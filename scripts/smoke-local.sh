#!/usr/bin/env bash
# Local smoke without a Pi: camera fixture → pipeline → private + live JPEG.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
CAM_YAML="$ROOT/cameras/example/camera.yaml"
test -f "$CAM_YAML"
export PYTHONPATH="$ROOT/pi/camera:$ROOT/pi/pipeline:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
# Prefer venvs if present
PY=python3
[[ -x pi/pipeline/.venv/bin/python ]] && PY=pi/pipeline/.venv/bin/python
echo "[smoke] cameras/example present"
make test
echo "[smoke] ok (unit tests). Full render smoke: see docs/diy/BUILD.md"
