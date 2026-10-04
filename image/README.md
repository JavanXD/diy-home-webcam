# Flashable image (pi-gen)

Flash, first boot, and setup AP: **[docs/diy/BUILD.md](../docs/diy/BUILD.md)** (Path A). Security: **[docs/diy/SECURITY.md](../docs/diy/SECURITY.md)**.

- **Download:** [GitHub Releases](https://github.com/JavanXD/diy-home-webcam/releases) (`home-webcam-*.img.xz`)
- Rebuild: GitHub Actions **Build Pi image** (`.github/workflows/build-pi-image.yml`)
- Local (Docker, long): `./image/build-with-pi-gen.sh` → `image/pi-gen/deploy/` (gitignored)

## Defaults (no secrets baked in)

| Setting | Value |
|---------|--------|
| Hostname | `home-webcam` (`image/config`) |
| SSH user / temp password | `pi` / `webcam-setup` — change after first boot |
| SSH | Prefer Imager **public key**; do not bake private keys into the image |
| R2 / AWS keys | Empty `/etc/webcam-pipeline/env` only |
| Setup AP | `Webcam-Setup` / documented temp password — only when no home Wi-Fi profile |
