#!/usr/bin/env bash
# Start or stop the first-boot setup Wi-Fi AP (NetworkManager hotspot).
#
# Safety (Schellbronn / already-configured Pis):
#   - Never starts when a non-setup Wi-Fi *client* profile exists
#   - Never starts when Wi-Fi is already associated to a home network
#   - Never starts when ethernet has an IPv4 address
#   - Never starts when /etc/webcam-pipeline/setup-ap.disabled exists
#   - Never starts when SETUP_AP_ENABLED=no
#
# Usage:
#   sudo ./pi/scripts/webcam-setup-ap.sh ensure   # boot path (default)
#   sudo ./pi/scripts/webcam-setup-ap.sh stop
#   sudo ./pi/scripts/webcam-setup-ap.sh status
#   sudo ./pi/scripts/webcam-setup-ap.sh start    # force (debug only)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
ENV_FILE="${WEBCAM_SETUP_AP_ENV:-/etc/webcam-setup-ap.env}"
REPO_ENV="${ROOT}/pi/host/setup-ap.env"
DISABLE_MARKER="${WEBCAM_SETUP_AP_DISABLE:-/etc/webcam-pipeline/setup-ap.disabled}"
CAPTIVE_UNIT="webcam-captive-redirect.service"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
elif [[ -f "$REPO_ENV" ]]; then
  # shellcheck source=/dev/null
  source "$REPO_ENV"
fi

SETUP_AP_ENABLED="${SETUP_AP_ENABLED:-yes}"
SETUP_AP_SSID="${SETUP_AP_SSID:-Webcam-Setup}"
SETUP_AP_PASSWORD="${SETUP_AP_PASSWORD:-webcam-setup}"
SETUP_AP_CONNECTION="${SETUP_AP_CONNECTION:-webcam-setup-ap}"
SETUP_AP_GATEWAY="${SETUP_AP_GATEWAY:-10.42.0.1}"
SETUP_AP_SETTLE_SECONDS="${SETUP_AP_SETTLE_SECONDS:-25}"

CMD="${1:-ensure}"

log() { echo "==> setup-ap: $*"; }
warn() { echo "WARN: setup-ap: $*" >&2; }

need_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "run as root" >&2
    exit 1
  fi
}

need_nmcli() {
  if ! command -v nmcli >/dev/null 2>&1; then
    echo "ERROR: nmcli not found (NetworkManager required)" >&2
    exit 1
  fi
}

wifi_device() {
  nmcli -t -f DEVICE,TYPE,STATE device status 2>/dev/null \
    | awk -F: '$2=="wifi" {print $1; exit}'
}

ethernet_up() {
  local line device state
  while IFS= read -r line; do
    device="$(echo "$line" | awk -F: '{print $1}')"
    state="$(echo "$line" | awk -F: '{print $3}')"
    [[ "$state" == "connected" ]] || continue
    if nmcli -g IP4.ADDRESS device show "$device" 2>/dev/null | grep -q .; then
      return 0
    fi
  done < <(nmcli -t -f DEVICE,TYPE,STATE device status 2>/dev/null | awk -F: '$2=="ethernet"')
  return 1
}

wifi_home_associated() {
  local line device state conn
  while IFS= read -r line; do
    device="$(echo "$line" | awk -F: '{print $1}')"
    state="$(echo "$line" | awk -F: '{print $3}')"
    conn="$(echo "$line" | awk -F: '{print $4}')"
    [[ "$state" == "connected" ]] || continue
    [[ "$conn" != "$SETUP_AP_CONNECTION" ]] || continue
    [[ "$conn" != "Hotspot" ]] || continue
    return 0
  done < <(nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status 2>/dev/null | awk -F: '$2=="wifi"')
  return 1
}

# Saved client Wi-Fi profiles (excludes our setup AP / generic Hotspot).
home_wifi_profiles() {
  nmcli -t -f NAME,TYPE connection show 2>/dev/null \
    | awk -F: -v ap="$SETUP_AP_CONNECTION" '
        $2=="802-11-wireless" && $1!=ap && $1!="Hotspot" {print $1}
      '
}

has_home_wifi_profile() {
  [[ -n "$(home_wifi_profiles | head -n1)" ]]
}

setup_ap_active() {
  local state
  state="$(nmcli -g GENERAL.STATE connection show "$SETUP_AP_CONNECTION" 2>/dev/null || true)"
  [[ "$state" == *activated* ]]
}

stop_captive() {
  if systemctl list-unit-files "${CAPTIVE_UNIT}" &>/dev/null; then
    systemctl stop "${CAPTIVE_UNIT}" 2>/dev/null || true
  fi
}

start_captive() {
  if systemctl list-unit-files "${CAPTIVE_UNIT}" &>/dev/null; then
    systemctl start "${CAPTIVE_UNIT}" 2>/dev/null || warn "captive redirect not started (port 80 busy?)"
  fi
}

do_stop() {
  stop_captive
  if nmcli -t -f NAME connection show 2>/dev/null | grep -Fxq "$SETUP_AP_CONNECTION"; then
    nmcli connection down "$SETUP_AP_CONNECTION" 2>/dev/null || true
    nmcli connection delete "$SETUP_AP_CONNECTION" 2>/dev/null || true
    log "removed connection $SETUP_AP_CONNECTION"
  fi
  # Clean leftover nmcli hotspot name if present
  if nmcli -t -f NAME connection show 2>/dev/null | grep -Fxq Hotspot; then
    local hs_ssid
    hs_ssid="$(nmcli -g 802-11-wireless.ssid connection show Hotspot 2>/dev/null || true)"
    if [[ "$hs_ssid" == "$SETUP_AP_SSID" ]]; then
      nmcli connection down Hotspot 2>/dev/null || true
      nmcli connection delete Hotspot 2>/dev/null || true
    fi
  fi
}

do_start() {
  local dev
  dev="$(wifi_device)"
  if [[ -z "$dev" ]]; then
    warn "no Wi-Fi device; cannot start setup AP"
    return 1
  fi

  do_stop

  log "starting AP ssid=$SETUP_AP_SSID on $dev (password is the documented temporary DIY password)"
  nmcli connection add \
    type wifi \
    ifname "$dev" \
    con-name "$SETUP_AP_CONNECTION" \
    autoconnect no \
    ssid "$SETUP_AP_SSID" \
    >/dev/null

  nmcli connection modify "$SETUP_AP_CONNECTION" \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    ipv4.method shared \
    ipv6.method ignore \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$SETUP_AP_PASSWORD"

  nmcli connection up "$SETUP_AP_CONNECTION"
  start_captive
  log "AP up. Join Wi-Fi “$SETUP_AP_SSID”, open http://${SETUP_AP_GATEWAY}:8090/setup/ui"
}

should_start() {
  if [[ -f "$DISABLE_MARKER" ]]; then
    log "disabled marker present ($DISABLE_MARKER) — skip"
    return 1
  fi
  case "${SETUP_AP_ENABLED,,}" in
    no|false|0|off) log "SETUP_AP_ENABLED=$SETUP_AP_ENABLED — skip"; return 1 ;;
  esac
  if ethernet_up; then
    log "ethernet has IPv4 — skip AP"
    return 1
  fi
  if wifi_home_associated; then
    log "Wi-Fi already associated to a home network — skip AP"
    return 1
  fi
  if has_home_wifi_profile; then
    log "saved home Wi-Fi profile(s) exist — skip AP (will not disrupt configured Pis)"
    home_wifi_profiles | sed 's/^/    profile: /'
    return 1
  fi
  return 0
}

do_status() {
  local active=no profiles
  setup_ap_active && active=yes
  profiles="$(home_wifi_profiles | tr '\n' ',' | sed 's/,$//')"
  echo "enabled=${SETUP_AP_ENABLED}"
  echo "ssid=${SETUP_AP_SSID}"
  echo "connection=${SETUP_AP_CONNECTION}"
  echo "active=${active}"
  echo "gateway=${SETUP_AP_GATEWAY}"
  echo "disable_marker=$([[ -f "$DISABLE_MARKER" ]] && echo yes || echo no)"
  echo "ethernet_up=$(ethernet_up && echo yes || echo no)"
  echo "wifi_home_associated=$(wifi_home_associated && echo yes || echo no)"
  echo "home_wifi_profiles=${profiles:-}"
}

do_ensure() {
  if [[ "$SETUP_AP_SETTLE_SECONDS" =~ ^[0-9]+$ ]] && [[ "$SETUP_AP_SETTLE_SECONDS" -gt 0 ]]; then
    log "settling ${SETUP_AP_SETTLE_SECONDS}s for Imager/cloud-init Wi-Fi…"
    sleep "$SETUP_AP_SETTLE_SECONDS"
  fi
  if should_start; then
    do_start
  else
    # If a previous boot left the AP up but we now have home Wi-Fi, tear it down.
    if setup_ap_active || nmcli -t -f NAME connection show 2>/dev/null | grep -Fxq "$SETUP_AP_CONNECTION"; then
      if has_home_wifi_profile || wifi_home_associated || ethernet_up; then
        log "tearing down leftover setup AP"
        do_stop
      fi
    fi
  fi
}

case "$CMD" in
  ensure) need_root; need_nmcli; do_ensure ;;
  start) need_root; need_nmcli; do_start ;;
  stop) need_root; need_nmcli; do_stop ;;
  status) need_nmcli; do_status ;;
  should-start)
    need_nmcli
    if should_start; then echo yes; exit 0; fi
    echo no
    exit 1
    ;;
  *)
    echo "usage: $0 ensure|start|stop|status|should-start" >&2
    exit 2
    ;;
esac
