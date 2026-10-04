#!/usr/bin/env bash
# Apply portable network tuning (DHCP, Cloudflare DNS, wifi-first metrics).
# Idempotent. Code first: pi/host/network.env
#
# Does NOT set WiFi SSID/password (stay on-device). Does NOT disable avahi.
# Does NOT rewrite BOOT_ORDER / performance / webcam unit files.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
NET="${ROOT}/pi/host/network.env"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

if [[ ! -f "$NET" ]]; then
  echo "missing $NET" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$NET"

IPV4_METHOD="${IPV4_METHOD:-auto}"
DNS_MODE="${DNS_MODE:-cloudflare}"
DNS_V4="${DNS_V4:-1.1.1.1,1.0.0.1}"
DNS_V6="${DNS_V6:-2606:4700:4700::1111,2606:4700:4700::1001}"
IGNORE_AUTO_DNS="${IGNORE_AUTO_DNS:-yes}"
WIFI_AUTOCONNECT="${WIFI_AUTOCONNECT:-yes}"
WIFI_AUTOCONNECT_PRIORITY="${WIFI_AUTOCONNECT_PRIORITY:-10}"
ETH_AUTOCONNECT="${ETH_AUTOCONNECT:-yes}"
ETH_AUTOCONNECT_PRIORITY="${ETH_AUTOCONNECT_PRIORITY:-5}"
WIFI_ROUTE_METRIC="${WIFI_ROUTE_METRIC:-100}"
ETH_ROUTE_METRIC="${ETH_ROUTE_METRIC:-300}"
IPV4_MAY_FAIL="${IPV4_MAY_FAIL:-yes}"
IPV6_MAY_FAIL="${IPV6_MAY_FAIL:-yes}"

echo "==> host network (portable webcam appliance)"
echo "    source: $NET"

if ! command -v nmcli >/dev/null 2>&1; then
  echo "ERROR: nmcli not found (NetworkManager required)" >&2
  exit 1
fi

echo "==> before"
ip -br addr | sed 's/^/    /'
echo "    resolv.conf:"
sed 's/^/      /' /etc/resolv.conf 2>/dev/null || true

# Quiet noisy netplan "permissions too open" on shipped renderer stub (mode 644).
if [[ -f /lib/netplan/00-network-manager-all.yaml ]]; then
  chmod 600 /lib/netplan/00-network-manager-all.yaml 2>/dev/null || true
fi

# Active NM profiles for ethernet / wifi (skip loopback / unmanaged).
mapfile -t CONNS < <(
  nmcli -t -f NAME,TYPE connection show 2>/dev/null \
    | awk -F: '$2=="802-3-ethernet" || $2=="802-11-wireless" {print $1}'
)

if [[ ${#CONNS[@]} -eq 0 ]]; then
  echo "WARN: no ethernet/wifi NetworkManager connections found" >&2
fi

ignore_flag=no
if [[ "${IGNORE_AUTO_DNS}" == "yes" || "${IGNORE_AUTO_DNS}" == "1" || "${IGNORE_AUTO_DNS}" == "true" ]]; then
  ignore_flag=yes
fi

for name in "${CONNS[@]}"; do
  [[ -n "$name" ]] || continue
  type="$(nmcli -g connection.type connection show "$name" 2>/dev/null || true)"
  echo "==> connection: $name ($type)"

  # DHCP (portable)
  nmcli connection modify "$name" ipv4.method "$IPV4_METHOD" || true
  # Clear any static addresses left from experiments (method=auto ignores them, but keep clean)
  if [[ "$IPV4_METHOD" == "auto" ]]; then
    nmcli connection modify "$name" ipv4.addresses "" ipv4.gateway "" 2>/dev/null || true
  fi

  nmcli connection modify "$name" \
    ipv4.may-fail "$IPV4_MAY_FAIL" \
    ipv6.may-fail "$IPV6_MAY_FAIL" || true

  if [[ "$type" == "802-11-wireless" ]]; then
    nmcli connection modify "$name" \
      connection.autoconnect "$WIFI_AUTOCONNECT" \
      connection.autoconnect-priority "$WIFI_AUTOCONNECT_PRIORITY" \
      ipv4.route-metric "$WIFI_ROUTE_METRIC" || true
    echo "    wifi: autoconnect=$WIFI_AUTOCONNECT priority=$WIFI_AUTOCONNECT_PRIORITY metric=$WIFI_ROUTE_METRIC"
  elif [[ "$type" == "802-3-ethernet" ]]; then
    nmcli connection modify "$name" \
      connection.autoconnect "$ETH_AUTOCONNECT" \
      connection.autoconnect-priority "$ETH_AUTOCONNECT_PRIORITY" \
      ipv4.route-metric "$ETH_ROUTE_METRIC" || true
    echo "    eth:  autoconnect=$ETH_AUTOCONNECT priority=$ETH_AUTOCONNECT_PRIORITY metric=$ETH_ROUTE_METRIC"
  fi

  if [[ "$DNS_MODE" == "cloudflare" ]]; then
    nmcli connection modify "$name" \
      ipv4.dns "$DNS_V4" \
      ipv4.ignore-auto-dns "$ignore_flag" || true
    # Only set IPv6 DNS when the profile uses IPv6 (wlan may be ipv6.method=ignore)
    ipv6_method="$(nmcli -g ipv6.method connection show "$name" 2>/dev/null || echo ignore)"
    if [[ "$ipv6_method" != "ignore" && "$ipv6_method" != "disabled" ]]; then
      nmcli connection modify "$name" \
        ipv6.dns "$DNS_V6" \
        ipv6.ignore-auto-dns "$ignore_flag" || true
    fi
    echo "    dns: Cloudflare ($DNS_V4) ignore-auto-dns=$ignore_flag"
  else
    nmcli connection modify "$name" \
      ipv4.dns "" \
      ipv4.ignore-auto-dns no \
      ipv6.dns "" \
      ipv6.ignore-auto-dns no || true
    echo "    dns: DHCP / router only"
  fi
done

echo "==> reapply connections (bring online without dropping wifi hard)"
for name in "${CONNS[@]}"; do
  [[ -n "$name" ]] || continue
  # Prefer modify+up; if already active, up refreshes DNS/routes
  nmcli connection up "$name" 2>/dev/null || true
done

# Avahi must stay for raspicam.local
if ! systemctl is-active --quiet avahi-daemon; then
  echo "WARN: avahi-daemon not active — enabling (needed for .local)" >&2
  systemctl enable --now avahi-daemon 2>/dev/null || true
fi

# network-online: wifi alone is enough (may-fail on eth). Soft Wants on webcam units.
echo "==> network-online / wait-online"
systemctl is-active network-online.target NetworkManager-wait-online.service 2>/dev/null \
  | sed 's/^/    /' || true

echo "==> after"
ip -br addr | sed 's/^/    /'
echo "    resolv.conf:"
sed 's/^/      /' /etc/resolv.conf 2>/dev/null || true
echo "    DNS reachability:"
if getent hosts cloudflare.com >/dev/null 2>&1; then
  echo "      cloudflare.com → OK"
else
  echo "      WARN: cloudflare.com lookup failed" >&2
fi
if getent hosts raspicam.local >/dev/null 2>&1 || true; then
  # mDNS from getent may not always resolve on the host itself; avahi-resolve is better
  if command -v avahi-resolve >/dev/null 2>&1; then
    avahi-resolve -n raspicam.local 2>/dev/null | sed 's/^/      /' || echo "      (avahi-resolve soft-fail; clients on LAN still OK)"
  fi
fi

keep_ok=1
for must in NetworkManager.service avahi-daemon.service; do
  if ! systemctl is-active --quiet "$must"; then
    echo "WARN: expected active: $must" >&2
    keep_ok=0
  fi
done
if [[ "$keep_ok" -eq 1 ]]; then
  echo "==> keep-alive check OK (NetworkManager + avahi)"
fi

echo "==> apply-network done"
echo "    WiFi SSID/PSK unchanged (on-device only)."
echo "    Re-apply: sudo $ROOT/pi/scripts/apply-network.sh"
echo "    Moving house? Update SSID on-device (nmcli / Imager); keep DHCP; see docs/PI-HOST.md"
