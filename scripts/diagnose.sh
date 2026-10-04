#!/usr/bin/env bash
# DIY diagnose: print health URLs. Site-specific ops diagnose lives only in the private ops checkout.
set -euo pipefail
HOST="${1:-127.0.0.1}"
echo "Camera:   http://${HOST}:8080/health"
echo "Pipeline: http://${HOST}:8090/health"
echo "Private:  http://${HOST}:8090/cameras/example/variants/private.jpg"
curl -sS -o /dev/null -w "camera /health → %{http_code}\n" "http://${HOST}:8080/health" || true
curl -sS -o /dev/null -w "pipeline /health → %{http_code}\n" "http://${HOST}:8090/health" || true
