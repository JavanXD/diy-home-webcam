# Security (home DIY baseline)

This appliance is built for a **trusted home LAN** and an **untrusted internet**. It is not an enterprise product: there is no login on the LAN UI on purpose. Harden the network and SSH; do not port-forward the Pi UI.

Also see the short report note at [`SECURITY.md`](../../SECURITY.md) (repo root).

## Threat model

| Actor | Assumption | What they can do |
|-------|------------|------------------|
| Someone on your home Wi‑Fi / LAN | **Trusted** (same as anyone who can open a browser on the LAN) | Use `:8080` / `:8090` — live frames, variants editor, Setup, reboot/poweroff (with confirm), Wi‑Fi join |
| Neighbor / passer-by on radio | Untrusted | May see SSID `Webcam-Setup` during first boot; published WPA2 password is in the DIY docs |
| Internet | Untrusted | Must **not** reach `:8080` / `:8090`. May fetch the **public** JPEG (and optional Worker page) if you publish |
| Compromised guest device on LAN | Semi-trusted | Same as LAN — treat guest Wi‑Fi isolation / IoT VLAN as your control |

**Trust boundary:** the home network. If you do not trust every device on that LAN, put the Pi on an IoT/guest VLAN or add your own reverse-proxy auth — this project does not ship a LAN password.

## What is exposed

| Surface | Exposure | Notes |
|---------|----------|-------|
| Camera `:8080` | LAN (binds `0.0.0.0`) | Capture, `/raw.jpg`, maintenance. No login. |
| Pipeline `:8090` | LAN (binds `0.0.0.0`) | Private variants, Setup, System power, R2 settings UI. No login. |
| Setup AP `Webcam-Setup` | Nearby Wi‑Fi, first boot only | Temp password `webcam-setup` (documented). Torn down after home Wi‑Fi join; skipped when a home profile / ethernet already exists. |
| Public JPEG (R2 / S3 / Worker) | Internet (if you enable publish) | Privacy-masked frame only — tune masks before going live. |
| SSH | As you configure | Prefer key-only; do not expose SSH to the internet without care. |

Binding to `0.0.0.0` is intentional so the setup AP gateway (`10.42.0.1`) and every LAN interface can reach the UI. Do not treat that as “open to the world” unless you port-forward.

## Recommendations

1. **SSH keys, not passwords** — In Raspberry Pi Imager, enable SSH with your **public** key. Disable password SSH after first login (`PasswordAuthentication no`). Change the image’s temporary `pi` / `webcam-setup` password immediately if you keep password login at all.
2. **Do not port-forward `:8080` or `:8090`** — Those ports can change privacy masks, maintenance, Wi‑Fi, and power. Public viewers should only see the object store / Worker URL.
3. **Rotate R2 / S3 keys** if a key may have leaked; keep them only in `/etc/webcam-pipeline/env` (mode `640`, `root:webcam`). Never commit keys. The Setup UI shows “secret set”, not the secret.
4. **After joining home Wi‑Fi** — The Pi tears down `Webcam-Setup` and will not start it again while a home Wi‑Fi profile exists. To force “never AP” (even if you delete Wi‑Fi profiles):  
   `sudo touch /etc/webcam-pipeline/setup-ap.disabled`  
   A successful Setup join also writes `/var/lib/webcam-pipeline/setup-ap.disabled` (same effect for the boot script).
5. **Keep the Pi updated** — `sudo apt update && sudo apt full-upgrade` on a schedule you trust; reboot when the kernel asks.
6. **Privacy masks before publish** — Public variants ship with placeholder rectangles. Re-check after the camera moves ([privacy-zones skill](../../.cursor/skills/privacy-zones/SKILL.md) on the ops checkout).
7. **Guest / IoT network** — Optional but good: put the webcam on a segment that cannot reach your PCs, and that the internet cannot initiate into.

## Intentionally not shipped

- **LAN login / basic auth** on `:8080` / `:8090` — decided against; network trust is the control.
- **TLS on the LAN UI** — home DIY complexity vs benefit; use VPN/VLAN if you need encryption on the wire.
- **Fail2ban / IDS / enterprise hardening** — out of scope for this appliance.

## Image defaults

Flashable images (`image/config`, pi-gen):

- No R2 keys baked in (`/etc/webcam-pipeline/env` is empty).
- Hostname `home-webcam`, user `pi`, temporary password `webcam-setup` (change it).
- Prefer Imager **SSH public key** over that password.
- Setup AP enabled only when no home Wi‑Fi is configured (see [BUILD.md](BUILD.md)).

## Reporting

Private GitHub security advisory on the repo you use, or email **mail@javan.de**. Do not open a public issue with live hostnames, tokens, or unmasked private frames.
