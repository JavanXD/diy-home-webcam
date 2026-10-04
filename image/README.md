# Flashable image (pi-gen)

Flash, first boot, and setup AP: **[docs/diy/BUILD.md](../docs/diy/BUILD.md)** (Path A). Security: **[docs/diy/SECURITY.md](../docs/diy/SECURITY.md)**.

- **Download:** [GitHub Releases](https://github.com/JavanXD/diy-home-webcam/releases) (`home-webcam-*.img.xz`)
- Rebuild: GitHub Actions **Build Pi image** (`.github/workflows/build-pi-image.yml`)
- Local (Docker, long): `./image/build-with-pi-gen.sh` → `image/pi-gen/deploy/` (gitignored)

## Defaults (no secrets baked in)

| Setting | Value |
|---------|--------|
| Hostname | `home-webcam` (`image/config`) |
| SSH | Prefer Imager **public key**; password auth disabled on first boot when `authorized_keys` exists |
| Credentials file | `/boot/firmware/webcam-setup.txt` — unique AP PSK + emergency SSH password (written on first boot) |
| R2 / AWS keys | Empty `/etc/webcam-pipeline/env` only |
| Setup AP | SSID `Webcam-Setup`, unique per-device PSK — only when no home Wi-Fi profile |
