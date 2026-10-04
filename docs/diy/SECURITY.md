# Security (home DIY baseline)

This appliance is built for a **trusted home LAN** and an **untrusted internet**. It is not an enterprise product: there is no login on the LAN UI on purpose. Harden the network and SSH; do not port-forward the Pi UI.

Also see the short report note at [`SECURITY.md`](../../SECURITY.md) (repo root).

## EU Cyber Resilience Act / RED IoT — alignment goals

Practical DIY alignment with CRA / radio IoT expectations — **not** certification or legal advice:

| Goal | Implementation |
|------|----------------|
| No shared universal default password | Setup AP PSK unique per board (serial / machine-id). Find it in `/boot/firmware/webcam-setup.txt` after flash, or on Setup UI while connected to `Webcam-Setup`. |
| Vulnerability disclosure | Private GitHub security advisory, or **mail@javan.de**. |
| Updates | Pull/sync + deploy, or re-flash Releases / rebuild image; keep Debian packages updated. DIY project — no commercial support SLA. |
| Secure defaults | AP off after join; prefer Imager SSH **public key**; password SSH off when keys exist; unique `pi` password on the boot card for emergency console. |
| No mandatory LAN login | Trusted home network is the boundary for `:8080` / `:8090`. |

## Threat model

| Actor | Assumption | What they can do |
|-------|------------|------------------|
| Someone on your home Wi‑Fi / LAN | **Trusted** (same as anyone who can open a browser on the LAN) | Use `:8080` / `:8090` — live frames, variants editor, Setup, reboot/poweroff (with confirm), Wi‑Fi join |
| Neighbor / passer-by on radio | Untrusted | May see SSID `Webcam-Setup` during first boot; WPA2 password is **device-unique** (boot card / Setup UI), not a published global string |
| Internet | Untrusted | Must **not** reach `:8080` / `:8090`. May fetch the **public** JPEG (and optional Worker page) if you publish |
| Compromised guest device on LAN | Semi-trusted | Same as LAN — treat guest Wi‑Fi isolation / IoT VLAN as your control |

**Trust boundary:** the home network. If you do not trust every device on that LAN, put the Pi on an IoT/guest VLAN or add your own reverse-proxy auth — this project does not ship a LAN password.

## What is exposed

| Surface | Exposure | Notes |
|---------|----------|-------|
| Camera `:8080` | LAN (binds `0.0.0.0`) | Capture, `/raw.jpg`, maintenance. No login. |
| Pipeline `:8090` | LAN (binds `0.0.0.0`) | Private variants, Setup, System power, R2 settings UI. No login. |
| Setup AP `Webcam-Setup` | Nearby Wi‑Fi, first boot only | Unique WPA2 PSK in `/boot/firmware/webcam-setup.txt`. Torn down after home Wi‑Fi join; skipped when a home profile / ethernet already exists. |
| Public JPEG (R2 / S3 / Worker) | Internet (if you enable publish) | Privacy-masked frame only — tune masks before going live. |
| SSH | As you configure | Prefer key-only; do not expose SSH to the internet without care. |

Binding to `0.0.0.0` is intentional so the setup AP gateway (`10.42.0.1`) and every LAN interface can reach the UI. Do not treat that as “open to the world” unless you port-forward.

## Recommendations

1. **SSH keys, not passwords** — In Raspberry Pi Imager, enable SSH with your **public** key (required path for Path A/B). On the flashable image, first-boot disables password SSH when `authorized_keys` is present. The unique `pi` password on the boot card is for emergency console only.
2. **Do not port-forward `:8080` or `:8090`** — Those ports can change privacy masks, maintenance, Wi‑Fi, and power. Public viewers should only see the object store / Worker URL.
3. **Rotate R2 / S3 keys** if a key may have leaked; keep them only in `/etc/webcam-pipeline/env` (mode `640`, `root:webcam`). Never commit keys. The Setup UI shows “secret set”, not the secret.
4. **After joining home Wi‑Fi** — The Pi tears down `Webcam-Setup` and will not start it again while a home Wi‑Fi profile exists. To force “never AP” (even if you delete Wi‑Fi profiles):  
   `sudo touch /etc/webcam-pipeline/setup-ap.disabled`  
   A successful Setup join also writes `/var/lib/webcam-pipeline/setup-ap.disabled` (same effect for the boot script).
5. **Keep the Pi updated** — `sudo apt update && sudo apt full-upgrade` on a schedule you trust; reboot when the kernel asks. Pull newer appliance code or re-flash when you care about fixes.
6. **Privacy masks before publish** — Public variants ship with placeholder rectangles. Re-check after the camera moves ([privacy-zones skill](../../.cursor/skills/privacy-zones/SKILL.md) on the ops checkout).
7. **Guest / IoT network** — Optional but good: put the webcam on a segment that cannot reach your PCs, and that the internet cannot initiate into.

## Intentionally not shipped

- **LAN login / basic auth** on `:8080` / `:8090` — decided against; network trust is the control.
- **TLS on the LAN UI** — home DIY complexity vs benefit; use VPN/VLAN if you need encryption on the wire.
- **Fail2ban / IDS / enterprise hardening** — out of scope for this appliance.
- **CRA / RED certification** — alignment goals only; not a notified-body assessment.

## Image defaults

Flashable images (`image/config`, pi-gen):

- No R2 keys baked in (`/etc/webcam-pipeline/env` is empty).
- Hostname `home-webcam`, user `pi`.
- Bootstrap password exists only until first-boot writes a **unique** password to `/boot/firmware/webcam-setup.txt`.
- Prefer Imager **SSH public key**; password auth disabled when keys are present.
- Setup AP enabled only when no home Wi‑Fi is configured; PSK unique per device (see [BUILD.md](BUILD.md)).

## How to find the setup AP password

1. After flashing (or after first boot), mount the card’s **boot** partition and open `webcam-setup.txt` (path `/boot/firmware/webcam-setup.txt` on a running Bookworm Pi).
2. Or, while joined to `Webcam-Setup`, open Setup UI — it shows this device’s AP password once.
3. There is **no** shared password in the README.

## Reporting

Private GitHub security advisory on the repo you use, or email **mail@javan.de**. Do not open a public issue with live hostnames, tokens, or unmasked private frames.
