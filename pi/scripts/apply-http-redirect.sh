#!/usr/bin/env bash
# Install nginx 80/443 → :8080 HTTP redirects (home webcam).
# Code first: config in pi/host/nginx/webcam-port-redirect.conf
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DESIRED="${ROOT}/pi/host/desired.env"
CONF_SRC="${ROOT}/pi/host/nginx/webcam-port-redirect.conf"
# shellcheck source=/dev/null
[[ -f "$DESIRED" ]] && source "$DESIRED"

REDIRECT_TO_PORT="${REDIRECT_TO_PORT:-8080}"
SITE_NAME="${HTTP_REDIRECT_SITE:-webcam-port-redirect}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

if [[ ! -f "$CONF_SRC" ]]; then
  echo "missing $CONF_SRC" >&2
  exit 1
fi

echo "==> install nginx (redirect :80/:443 → :${REDIRECT_TO_PORT})"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx openssl

SSL_DIR=/etc/nginx/ssl
mkdir -p "$SSL_DIR"
CERT="$SSL_DIR/home-webcam-local.crt"
KEY="$SSL_DIR/home-webcam-local.key"
if [[ ! -f "$CERT" || ! -f "$KEY" ]]; then
  echo "==> self-signed cert for home-webcam.local (LAN only)"
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "$KEY" -out "$CERT" \
    -subj "/CN=home-webcam.local/O=Home webcam/OU=LAN" \
    -addext "subjectAltName=DNS:home-webcam.local,DNS:home-webcam,IP:127.0.0.1"
  chmod 640 "$KEY"
  chown root:root "$CERT" "$KEY"
fi

# Drop Debian default site so we own :80/:443
rm -f /etc/nginx/sites-enabled/default

install -m 644 "$CONF_SRC" "/etc/nginx/sites-available/${SITE_NAME}"
# Ensure port in deployed config matches desired.env (sed if different from shipped 8080)
if [[ "$REDIRECT_TO_PORT" != "8080" ]]; then
  sed -i "s/:8080/:${REDIRECT_TO_PORT}/g" "/etc/nginx/sites-available/${SITE_NAME}"
fi
ln -sfn "/etc/nginx/sites-available/${SITE_NAME}" "/etc/nginx/sites-enabled/${SITE_NAME}"

nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "==> smoke"
code80="$(curl -sS -o /dev/null -w '%{http_code}' -H 'Host: home-webcam.local' http://127.0.0.1/)"
loc80="$(curl -sS -o /dev/null -w '%{redirect_url}' -H 'Host: home-webcam.local' http://127.0.0.1/)"
code443="$(curl -skS -o /dev/null -w '%{http_code}' -H 'Host: home-webcam.local' https://127.0.0.1/)"
loc443="$(curl -skS -o /dev/null -w '%{redirect_url}' -H 'Host: home-webcam.local' https://127.0.0.1/)"
echo "  http  → $code80 $loc80"
echo "  https → $code443 $loc443"
if [[ "$code80" != "301" || "$code443" != "301" ]]; then
  echo "WARN: expected 301 from :80 and :443" >&2
fi
echo "==> apply-http-redirect done (open http://home-webcam.local/ or https://home-webcam.local/)"
