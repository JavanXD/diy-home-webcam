# Pi host — storage, bootloader & performance (code first)

**Rule:** Anything you change on the live Pi (boot order, disks, hostname notes, Wartungsbild copy, host tuning, etc.) must land in this repo in the same session. The working tree is the copy you remigrate from — not “SSH now, maybe commit later.”

Display / product naming: [`NAMING.md`](NAMING.md). Secrets stay in `~/Projects/.secrets/` (not git).

## Camera production stance

`/etc/webcam-camera/camera.yaml` defaults to `capture_backend: picamera2` (from `pi/camera/config/camera.example.yaml`). If the camera is missing or capture fails, the appliance auto-enables Wartungsbild (`maintenance_auto`, reason `no_camera` / `capture_failed`) and keeps retrying capture. Details: [pi/camera/docs/README.md](../pi/camera/docs/README.md).

## Desired state

[`pi/host/desired.env`](../pi/host/desired.env):

| Key | Value | Meaning |
|-----|--------|---------|
| `BOOT_ORDER` | `0xf416` | NVMe → SD → USB → restart |
| `SRC_DISK` | `/dev/mmcblk0` | ~256 GB SD (Imager / fallback) |
| `DST_DISK` | `/dev/nvme0n1` | ~500 GB Kingston NVMe (OS target) |

Headless performance: [`pi/host/performance.env`](../pi/host/performance.env) (see [Host performance](#host-performance) below).

Portable network: [`pi/host/network.env`](../pi/host/network.env) (see [Portable / plug-and-play](#portable--plug-and-play) below).

## Remigrate OS to NVMe (from Mac)

```bash
set -a && source ~/Projects/.secrets/raspicam.env && set +a
KEY="${RASPICAM_SSH_KEY/#\~/$HOME}"
TARGET="${RASPICAM_SSH_USER}@${RASPICAM_HOST}"

# 1) Push code (including host scripts)
./pi/scripts/sync-to-pi.sh "$TARGET"

# 2) On Pi: must be booted from SD for migrate. If already on NVMe, skip to verify.
ssh -i "$KEY" -o IdentitiesOnly=yes "$TARGET" \
  'sudo /opt/home-webcam-pipeline/pi/scripts/remigrate-to-nvme.sh'
# Pi reboots. Wait for SSH, then:

ssh -i "$KEY" -o IdentitiesOnly=yes "$TARGET" \
  'sudo /opt/home-webcam-pipeline/pi/scripts/verify-host.sh'
```

Or step-by-step on the Pi (repo checked out / synced):

```bash
sudo ./pi/scripts/migrate-os-to-nvme.sh   # only while root is on mmcblk0
sudo ./pi/scripts/apply-bootloader.sh     # stages/commits BOOT_ORDER + EEPROM
sudo reboot
sudo ./pi/scripts/verify-host.sh
```

## Day-2 app deploy (unchanged)

```bash
./pi/camera/scripts/deploy.sh pi@home-webcam.local
./pi/pipeline/scripts/deploy.sh pi@home-webcam.local
# or full tree: ./pi/scripts/sync-to-pi.sh pi@home-webcam.local
# (prefer RASPICAM_HOST=home-webcam.local; home-webcam.local optional)
```

## Runtime data ownership (`webcam`)

Units `webcam-camera` / `webcam-pipeline` run as user `webcam` with
`ProtectSystem=strict` and `ReadWritePaths` on:

- `/opt/home-webcam-pipeline/data` (pipeline originals / variants / outbox)
- `/opt/home-webcam-pipeline/pi/{camera,pipeline}/data`
- `/var/lib/webcam-{camera,pipeline}`

After NVMe remigrate or a broad `chown` of `/opt/…` to `pi`, those paths can end up
`pi:pi` → pipeline cycles fail with `PermissionError` on `latest.jpg.tmp`.

Fix (on Pi, or via sync):

```bash
sudo /opt/home-webcam-pipeline/pi/scripts/fix-data-perms.sh
# `./pi/scripts/sync-to-pi.sh` runs this automatically after rsync
```

## LAN port redirect (`http(s)://home-webcam.local/` or `home-webcam.local/` → `:8080`)

nginx returns **301** to `http://<host>:8080…` (camera appliance). Config: `pi/host/nginx/webcam-port-redirect.conf`. Canonical client URL: WLAN `.150`.

```bash
./pi/scripts/sync-to-pi.sh "$TARGET"
ssh … 'sudo /opt/home-webcam-pipeline/pi/scripts/apply-http-redirect.sh'
```

`:443` uses a LAN self-signed cert (browser warning once), then redirects to plain `:8080`.

## Host performance

Goal: headless appliance (camera `:8080` + pipeline `:8090` + nginx + SSH + mDNS). Prefer **disable** over purge. Prefer leave network stacks alone.

Source of truth: [`pi/host/performance.env`](../pi/host/performance.env). Apply:

```bash
./pi/scripts/sync-to-pi.sh "$TARGET"
ssh -i "$KEY" -o IdentitiesOnly=yes "$TARGET" \
  'sudo /opt/home-webcam-pipeline/pi/scripts/apply-host-performance.sh'
# Optional once after first apply (clears leftover desktop session):
# ssh … 'sudo reboot'
```

### What it tunes

| Change | Value / action | Why |
|--------|----------------|-----|
| Default target | `multi-user.target` | No graphical login (was `graphical` + LightDM) |
| `vm.swappiness` | `10` (`/etc/sysctl.d/99-webcam-host.conf`) | 8 GiB RAM + NVMe + zram; avoid swapping app pages |
| journald | `SystemMaxUse=50M` | Cap log growth on appliance |
| CPU governor | leave `ondemand` | Thermal-friendly; do not force `performance` |
| zram | leave shipped rpi-swap / zram-generator | Compressed swap already present |

### Services disabled (curated allowlist)

| Unit | Reason |
|------|--------|
| `lightdm` | Desktop display manager — unused headless |
| `wayvnc-control` | Wayland VNC helper for desktop |
| `cups` (+ socket/path) | Printing unused |
| `bluetooth` | WiFi (`.150`) stays; BT unused |
| `nfs-blkmap`, `rpcbind` (+ socket) | No NFS mounts |
| `accounts-daemon` | Desktop Accounts Service |
| `glamor-test`, `rp1-test` | Pi OS display probe oneshots |

### Considered / left enabled

| Unit / stack | Why leave on |
|--------------|--------------|
| `avahi-daemon` | `home-webcam.local` mDNS (optional convenience) |
| `NetworkManager` + `wpa_supplicant` | WLAN `.150` (canonical); eth `.151` only if cable plugged in |
| `ssh`, `nginx`, `webcam-camera`, `webcam-pipeline` | Appliance core |
| `systemd-timesyncd` | Clock for timestamps / solar schedule |
| `udisks2` | SD automount under `/media/pi/…` (harmless; useful for fallback disk) |
| `cloud-init*` | Imager / first-boot path; leave for remigrate reproducibility |
| `getty` / serial getty | Local console recovery |
| `rpi-eeprom-update` | Bootloader updates |
| `polkit` | Pulled by NetworkManager / desktop leftovers; low cost |

GPU/camera overlays (`camera_auto_detect`, `vc4-kms-v3d`) stay — picamera2 needs them. Do **not** flip `BOOT_ORDER` or remigrate disks from this script.

## Current production snapshot (2026-09-29)

- Root `/` and `/boot/firmware` on `nvme0n1`
- EEPROM bootloader **2026-09-25**, `BOOT_ORDER=0xf416`
- SD may remain inserted as fallback (often automounted under `/media/pi/…`)
- Headless performance applied via `apply-host-performance.sh` (`multi-user`, swappiness 10, curated disables)
- Portable network applied via `apply-network.sh` (DHCP, Cloudflare DNS, wifi-first metrics; WiFi PSK stays on-device)

## Portable / plug-and-play

Goal: unplug Ethernet, move the Pi, power on anywhere on a known WiFi — camera `:8080` + pipeline `:8090` come up without ethernet.

Source of truth: [`pi/host/network.env`](../pi/host/network.env). Apply:

```bash
./pi/scripts/sync-to-pi.sh "$TARGET"
ssh -i "$KEY" -o IdentitiesOnly=yes "$TARGET" \
  'sudo /opt/home-webcam-pipeline/pi/scripts/apply-network.sh'
```

### What it configures

| Change | Default | Why |
|--------|---------|-----|
| IPv4 method | `auto` (DHCP) on eth + wlan | Portable across LANs; prefer a router DHCP reservation for a stable WLAN IP |
| DNS | Cloudflare `1.1.1.1` / `1.0.0.1` (+ IPv6) | Predictable internet DNS when relocating; `IGNORE_AUTO_DNS=yes` |
| WiFi autoconnect | yes, priority 10, route metric 100 | Day-to-day is wifi-only (cable unplugged) |
| Ethernet | autoconnect yes, priority 5, metric 300 | Cable optional; unplugged eth must not block boot |
| `ipv4.may-fail` / `ipv6.may-fail` | yes | `NetworkManager-wait-online` succeeds on wifi-only |

**Not in git:** WiFi SSID / password (Imager or on-device NetworkManager / netplan). Never commit PSKs.

**Setup AP (DIY first-boot):** `pi/scripts/webcam-setup-ap.sh` + `webcam-setup-ap.service` start SSID `Webcam-Setup` only when **no** home Wi-Fi client profile exists, Wi-Fi is not associated, and ethernet has no IPv4. Configured boards keep working and do not enter AP mode. Status: `sudo …/webcam-setup-ap.sh status`. Disable: `sudo touch /etc/webcam-pipeline/setup-ap.disabled`. Phone flow: [docs/diy/BUILD.md](diy/BUILD.md).

**Reachability:** use the Pi’s LAN IP or mDNS (`home-webcam.local` on the DIY image; ops hosts may use a different hostname). Avahi is optional and does not depend on Cloudflare DNS.

**systemd:** `webcam-camera` / `webcam-pipeline` use `Wants=network-online.target` (soft). With `may-fail=yes` on eth, wifi alone satisfies wait-online — no unit rewrite required.

### Power-on path (wifi primary)

1. Plug into power (Ethernet optional; day-to-day cable stays unplugged).
2. NetworkManager autoconnects saved WiFi → DHCP → DNS (Fritz → `.150`).
3. `network-online.target` (~seconds after wifi).
4. `webcam-camera` → `webcam-pipeline` → nginx / avahi.
5. LAN UI: `http://home-webcam.local:8080/` (`home-webcam.local` optional). Host uptime on Camera / Pipeline home from `/health` (`system_uptime_seconds`).

### When moving house / network

Open relocate decisions (IP strategy): [TODO.md](../TODO.md).

1. **SSID / password** — if the new network differs, update on-device (`nmcli device wifi connect "SSID" password "…"` or Setup UI / Imager). Credentials stay off git.
2. **DHCP** — leave Pi on DHCP; optionally add router reservations (document WLAN as canonical in `docs/NAMING.md`).
3. **Re-apply network IaC** — `sudo …/apply-network.sh` (Cloudflare DNS + wifi-first metrics).
4. **Pull cameras if you edited on Pi** — `./pi/scripts/pull-cameras-from-pi.sh` before any `sync-to-pi.sh --delete`.
5. **Smoke** — `curl` camera + pipeline `/health` (check `system_uptime_seconds`); open Camera home for Host uptime.
6. **Public path** — R2 / HA still need reachability to the internet / LAN as before.

Set `DNS_MODE=dhcp` in `network.env` if you prefer router DNS only (no Cloudflare).
