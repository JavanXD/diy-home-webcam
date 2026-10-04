#!/usr/bin/env bash
# Unique per-device first-boot credentials (CRA-aligned: no shared default PSK).
#
# Sourced by webcam-setup-ap.sh and image first-boot. Can also run:
#   ./webcam-device-credentials.sh seed|psk|ssh-pass|write-card
#
# Override seed for tests: WEBCAM_DEVICE_SEED=test-serial
set -euo pipefail

# WPA2 PSK / printable password length (hex chars from SHA-256).
_WEBCAM_CRED_LEN="${WEBCAM_CRED_LEN:-16}"

webcam_device_seed() {
  if [[ -n "${WEBCAM_DEVICE_SEED:-}" ]]; then
    printf '%s' "$WEBCAM_DEVICE_SEED"
    return 0
  fi
  local s=""
  if [[ -r /sys/firmware/devicetree/base/serial-number ]]; then
    s="$(tr -d '\0\n\r' </sys/firmware/devicetree/base/serial-number)"
  fi
  if [[ -z "$s" && -r /proc/cpuinfo ]]; then
    s="$(awk -F': ' '/^[Ss]erial/ {gsub(/[ \t\r]/,"",$2); print $2; exit}' /proc/cpuinfo)"
  fi
  if [[ -z "$s" && -r /etc/machine-id ]]; then
    s="$(tr -d '[:space:]' </etc/machine-id)"
  fi
  if [[ -z "$s" ]]; then
    s="fallback-$(hostname 2>/dev/null || echo host)-$(uname -n 2>/dev/null || echo unk)"
  fi
  printf '%s' "$s"
}

# Stable hex password from seed + purpose label (openssl SHA-256).
webcam_derive_secret() {
  local purpose="$1"
  local seed="${2:-}"
  if [[ -z "$seed" ]]; then
    seed="$(webcam_device_seed)"
  fi
  if command -v openssl >/dev/null 2>&1; then
    printf '%s' "${purpose}:${seed}" | openssl dgst -sha256 -hex 2>/dev/null \
      | awk '{print $NF}' | tr -d '\n' | head -c "$_WEBCAM_CRED_LEN"
    return 0
  fi
  # Busybox / minimal fallback (weaker but still unique per seed).
  printf '%s' "${purpose}:${seed}" | sha256sum 2>/dev/null | awk '{print $1}' \
    | head -c "$_WEBCAM_CRED_LEN"
}

webcam_derive_setup_ap_psk() {
  webcam_derive_secret "webcam-setup-ap-v1" "${1:-}"
}

webcam_derive_ssh_password() {
  webcam_derive_secret "webcam-ssh-v1" "${1:-}"
}

webcam_boot_card_paths() {
  # Prefer Bookworm firmware partition; fall back to classic /boot.
  local paths=()
  if [[ -d /boot/firmware ]]; then
    paths+=(/boot/firmware/webcam-setup.txt)
  fi
  if [[ -d /boot ]]; then
    paths+=(/boot/webcam-setup.txt)
  fi
  # Always include firmware path so write can create parent when mounted.
  if [[ ${#paths[@]} -eq 0 ]]; then
    paths+=(/boot/firmware/webcam-setup.txt /boot/webcam-setup.txt)
  fi
  printf '%s\n' "${paths[@]}"
}

webcam_write_setup_card() {
  local ssid="${1:-Webcam-Setup}"
  local ap_pass="$2"
  local ssh_user="${3:-pi}"
  local ssh_pass="${4:-}"
  local gateway="${5:-10.42.0.1}"
  local seed
  seed="$(webcam_device_seed)"
  local body
  body=$(cat <<EOF
# Home webcam — credentials unique to this device
# Read after flash: mount the boot partition and open this file.
# Do not publish this file; it is not a shared default password.

SSID=${ssid}
PASSWORD=${ap_pass}
SETUP_URL=http://${gateway}:8090/setup/ui

# SSH (user ${ssh_user}). Prefer an Imager SSH public key; password auth may be
# disabled when authorized_keys is present.
SSH_USER=${ssh_user}
EOF
)
  if [[ -n "$ssh_pass" ]]; then
    body+=$'\n'"SSH_PASSWORD=${ssh_pass}"
  fi
  body+=$'\n\n'"# Device seed used for derivation (serial / machine-id): ${seed}"$'\n'

  local written=0 path parent
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    parent="$(dirname "$path")"
    if [[ ! -d "$parent" ]]; then
      mkdir -p "$parent" 2>/dev/null || true
    fi
    if [[ -d "$parent" ]] && { [[ -w "$parent" ]] || [[ -w "$path" ]]; }; then
      printf '%s' "$body" >"$path"
      chmod 644 "$path" 2>/dev/null || true
      written=1
      echo "==> credentials: wrote $path" >&2
    fi
  done < <(webcam_boot_card_paths)

  # Runtime copy for Setup UI if boot is not writable (still unique; mode 644).
  mkdir -p /var/lib/webcam-pipeline 2>/dev/null || true
  if [[ -d /var/lib/webcam-pipeline ]]; then
    printf '%s' "$body" >/var/lib/webcam-pipeline/webcam-setup.txt
    chmod 644 /var/lib/webcam-pipeline/webcam-setup.txt 2>/dev/null || true
    written=1
  fi
  [[ "$written" -eq 1 ]]
}

# Persist SETUP_AP_PASSWORD into /etc/webcam-setup-ap.env (create or update key).
webcam_persist_setup_ap_password() {
  local password="$1"
  local env_file="${WEBCAM_SETUP_AP_ENV:-/etc/webcam-setup-ap.env}"
  local repo_env="${2:-}"
  mkdir -p "$(dirname "$env_file")"
  if [[ ! -f "$env_file" ]]; then
    if [[ -n "$repo_env" && -f "$repo_env" ]]; then
      install -m 644 "$repo_env" "$env_file"
    else
      cat >"$env_file" <<'EOF'
SETUP_AP_ENABLED=yes
SETUP_AP_SSID=Webcam-Setup
SETUP_AP_PASSWORD=auto
SETUP_AP_CONNECTION=webcam-setup-ap
SETUP_AP_GATEWAY=10.42.0.1
SETUP_AP_SETTLE_SECONDS=25
EOF
      chmod 644 "$env_file"
    fi
  fi
  if grep -qE '^[[:space:]]*SETUP_AP_PASSWORD=' "$env_file"; then
    # Avoid sed -i portability issues; rewrite via temp.
    local tmp
    tmp="$(mktemp)"
    awk -v p="$password" '
      BEGIN { done=0 }
      /^[[:space:]]*SETUP_AP_PASSWORD=/ {
        print "SETUP_AP_PASSWORD=" p
        done=1
        next
      }
      { print }
      END { if (!done) print "SETUP_AP_PASSWORD=" p }
    ' "$env_file" >"$tmp"
    cat "$tmp" >"$env_file"
    rm -f "$tmp"
  else
    printf '\nSETUP_AP_PASSWORD=%s\n' "$password" >>"$env_file"
  fi
}

# True when password should be replaced with a device-unique value.
webcam_password_needs_derive() {
  local current="${1:-}"
  case "${current,,}" in
    ""|auto|generate|webcam-setup) return 0 ;;
    *) return 1 ;;
  esac
}

# Resolve AP PSK: keep operator-set secrets; derive when auto/legacy/empty.
# Echoes the password on stdout. Side effects: persist env + write card when deriving.
webcam_resolve_setup_ap_password() {
  local current="${1:-}"
  local ssid="${2:-Webcam-Setup}"
  local gateway="${3:-10.42.0.1}"
  local ssh_user="${4:-pi}"
  local repo_env="${5:-}"
  local write_ssh_pass="${6:-}" # non-empty → include SSH_PASSWORD on card
  local psk ssh_pass=""

  if webcam_password_needs_derive "$current"; then
    psk="$(webcam_derive_setup_ap_psk)"
    webcam_persist_setup_ap_password "$psk" "$repo_env"
    if [[ -n "$write_ssh_pass" ]]; then
      ssh_pass="$(webcam_derive_ssh_password)"
    fi
    webcam_write_setup_card "$ssid" "$psk" "$ssh_user" "$ssh_pass" "$gateway" || true
    printf '%s' "$psk"
    return 0
  fi
  # Operator-set password: still refresh the boot card so UX stays discoverable.
  if [[ -n "$write_ssh_pass" ]]; then
    ssh_pass="$(webcam_derive_ssh_password)"
  fi
  webcam_write_setup_card "$ssid" "$current" "$ssh_user" "$ssh_pass" "$gateway" || true
  printf '%s' "$current"
}

# CLI when executed (not only sourced).
if [[ "${BASH_SOURCE[0]:-}" == "${0}" ]]; then
  cmd="${1:-seed}"
  case "$cmd" in
    seed) webcam_device_seed; echo ;;
    psk) webcam_derive_setup_ap_psk; echo ;;
    ssh-pass) webcam_derive_ssh_password; echo ;;
    write-card)
      ssid="${SETUP_AP_SSID:-Webcam-Setup}"
      pass="$(webcam_derive_setup_ap_psk)"
      ssh_pass="$(webcam_derive_ssh_password)"
      webcam_write_setup_card "$ssid" "$pass" "${FIRST_USER_NAME:-pi}" "$ssh_pass" "${SETUP_AP_GATEWAY:-10.42.0.1}"
      ;;
    *)
      echo "usage: $0 seed|psk|ssh-pass|write-card" >&2
      exit 2
      ;;
  esac
fi
