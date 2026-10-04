# Security

## Report a vulnerability

Open a **private GitHub security advisory** on this repository, or on the public DIY tree:

- [New advisory — `JavanXD/diy-home-webcam`](https://github.com/JavanXD/diy-home-webcam/security/advisories/new)
- Or: this repo → **Security** → **Advisories** → **New draft security advisory**

Do not file a public issue that includes live hostnames, tokens, unpublished images, or private frames.

## Updates

- **Ops / this checkout:** pull or sync the repo, then provision/deploy on the Pi (`pi/provision.sh` / `pi/pipeline/scripts/deploy.sh`), or re-flash a newer image.
- **DIY flashable image:** new builds from GitHub Actions **Build Pi image**; download `home-webcam-*.img.xz` from [diy-home-webcam Releases](https://github.com/JavanXD/diy-home-webcam/releases) when published, or rebuild locally with `./image/build-with-pi-gen.sh`.
- **OS packages:** `sudo apt update && sudo apt full-upgrade` on a schedule you trust.
- **Support window:** this is a maintained personal/DIY project, not a commercial product SKU — security fixes land in git as they are found; there is no multi-year guaranteed support contract.

## EU Cyber Resilience Act / RED IoT — alignment goals

This section describes **practical DIY alignment goals** with the spirit of the EU Cyber Resilience Act and radio/IoT product expectations (unique defaults, disclosure, updateability). It is **not** a conformity assessment, CE marking claim, or legal advice. The project is not a certified commercial IoT product.

| Goal | What we do |
|------|------------|
| No universal default password | Setup AP PSK is **unique per device** (derived from board serial / machine-id). Written to `/boot/firmware/webcam-setup.txt` and shown on Setup UI while the AP is up — not a shared README password. |
| Vulnerability disclosure | Private GitHub security advisory only (link above). |
| Update expectation | Git pull / re-flash / Releases + apt; honest DIY support window (above). |
| Secure by default | Setup AP auto-disables after home Wi-Fi join; Imager **SSH public key** preferred; password SSH disabled on first boot when `authorized_keys` is present; unique emergency SSH password on the boot card when keys are absent. |
| Trusted LAN UI | No mandatory login on `:8080` / `:8090` — the home network is the trust boundary (CRA focus here is defaults + updateability, not LAN auth on a local appliance). |

## How this appliance is meant to be exposed

| Surface | Who should reach it |
|---------|---------------------|
| `:8080` camera and `:8090` pipeline | Your LAN only. There is no login on purpose: the home network is the trust boundary. |
| Originals and `visibility: private` variants | LAN only. They are not uploaded. |
| Public JPEG on R2 / the Worker | Anyone with the URL. |

Do not port-forward `:8080` or `:8090` to the internet. The maintenance switch and the variants editor can change what the public JPEG shows.

**DIY threat model, SSH, setup AP, and hardening checklist:** [docs/diy/SECURITY.md](docs/diy/SECURITY.md).

## Secrets

R2 credentials belong in `/etc/webcam-pipeline/env` on the Pi (mode `640`, owner `root`, group `webcam`). The template is [`examples/pi/r2.env`](examples/pi/r2.env). Never commit keys, SSH private keys, or Wi-Fi PSKs. The Setup UI reports whether a secret is set; it never returns the secret value.

The optional first-boot setup AP (`Webcam-Setup`) uses a **per-device WPA2 password** (see `/boot/firmware/webcam-setup.txt`). It starts only when no home Wi-Fi profile exists; a successful Setup join tears it down and writes `/var/lib/webcam-pipeline/setup-ap.disabled`. Operator forever-off: `/etc/webcam-pipeline/setup-ap.disabled`. Flashable images do not bake R2 keys.

## Privacy masks

Public variants ship with placeholder rectangles. Tune them on a real frame in the variants UI before you enable publish. A mask that is slightly too small still publishes the rest of the frame.
