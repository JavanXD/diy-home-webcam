# DIY home webcam

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A headless Raspberry Pi captures a still JPEG, keeps a private view on your LAN, and can optionally publish one privacy-filtered public JPEG to Cloudflare R2 or any S3-compatible store — or leave publish off.

Two systemd services on one Pi: capture on `:8080`, variants and publish on `:8090`. Originals stay on the LAN. Only a public crop you chose — with privacy masks — can leave the house.

## How it works

```mermaid
flowchart LR
  cam[HQ camera] --> capture["webcam-camera :8080"]
  capture --> pipe["webcam-pipeline :8090"]
  pipe --> private[Private JPEG on LAN]
  pipe --> public{Publish?}
  public -->|off / local| lanOnly[LAN or outbox only]
  public -->|S3 / R2| bucket[Object store]
  bucket --> worker[Optional Worker page]
  private --> ha[Home Assistant optional]
```

## Features

### Hardware on the window

HQ camera on a tall stand, Pi 5 in the official case, CSI flex to the sill. Crop and masks are software; the mount just points the lens.

<img src="docs/diy/images/pi-camera-assembly.jpg" alt="Pi HQ camera on stand at the window" width="280" />
<img src="docs/diy/images/pi-full-setup.jpg" alt="Full shelf setup — Pi case, tall stand, CSI cable" width="280" />

### Drag-to-edit crop and privacy masks

On Variants (`:8090/variants/ui`), drag a **cyan** rectangle on the full camera frame to set the crop (writes `crop` LTRB in YAML; output still cover-fits without stretching). Neighbor windows get **yellow** rectangles on the served preview — blur, pixelate, or black. Labels stay in YAML (not drawn on the JPEG). Preview, then Save.

<img src="docs/diy/images/lan-variants-masks.png" alt="Variants LAN UI — Edit masks" width="360" />

### Focus meter (sharpness score)

Manual CS lenses need a real focus aid. Camera home draws a **draggable box** on the raw preview (`/raw.jpg`). The score is the **variance of a Laplacian** on that region after a downscale to ≤480×320 — higher means crisper edges. Yellow arrow: keep turning the focus ring. Amber: turn back. Green check: near the recent peak. The published JPEG is unchanged; software does not move the lens.

<img src="docs/diy/images/lan-camera-home.png" alt="Camera home — live preview and focus meter" width="360" />

### Solar schedule for the public stream

Public live follows sunrise/sunset (with offsets), fixed clock times, or always-on. Night uploads a placeholder; the private LAN JPEG stays live.

<img src="docs/diy/images/lan-schedule.png" alt="Schedule LAN UI — solar mode" width="360" />

### Also worth knowing

- **Flashable image + setup AP** — GitHub Actions builds a Lite image; if Imager skipped Wi-Fi, join `Webcam-Setup` and finish on `:8090/setup/ui` ([docs/diy/BUILD.md](docs/diy/BUILD.md))
- **Wartungsbild** — maintenance placeholder for the public livestream while capture keeps running; private stays on raw
- **S3-compatible publish** — Cloudflare R2 preset, custom S3 (MinIO / AWS / Wasabi / B2), local outbox, or off — public object URL / hotlink without a Worker; branded Worker page optional — Setup UI + [docs/diy/PUBLISH.md](docs/diy/PUBLISH.md)
- **Find the Pi after setup AP** — Setup UI shows hostname, `*.local`, and current / last LAN IPv4 (Android often needs the IP, not mDNS)
- **Site badge + temperature** — cream burn-in (hostname · outdoor °C) on public frames
- **Cover-fit output** — visual crop + YAML crop scale into width×height without stretching
- **Home Assistant** — YAML-only package; poll the private LAN JPEG
- **Timelapse** — build MP4/GIF from saved daylight frames on the Pi

## Install

### Local smoke (no Pi)

```bash
git clone https://github.com/JavanXD/diy-home-webcam.git
cd diy-home-webcam
make test
./scripts/smoke-local.sh
```

### On a Raspberry Pi

Parts and flash steps: [docs/diy/SHOPPING-LIST.md](docs/diy/SHOPPING-LIST.md) and [docs/diy/BUILD.md](docs/diy/BUILD.md).

**Preferred:** flashable image from the **Build Pi image** workflow → boot → join home Wi-Fi (or `Webcam-Setup` AP) → open `http://home-webcam.local:8080/`.

```mermaid
flowchart TD
  flash[Flash .img.xz] --> boot[First boot / provision]
  boot --> wifi{Home Wi-Fi in Imager?}
  wifi -->|yes| lan[Open :8080 on LAN]
  wifi -->|no| ap[Join Webcam-Setup AP]
  ap --> setup[Setup UI :8090]
  setup --> home[Join home Wi-Fi]
  home --> lan
```

**Advanced:** clone on a Lite OS and run:

```bash
sudo ./pi/provision.sh
```

Start from [`examples/`](examples/) / [`cameras/example/`](cameras/example/). Field list: [examples/README.md](examples/README.md).

## Documentation

| | |
|---|---|
| [DIY hub](docs/diy/README.md) | Parts, build, photos |
| [Shopping list](docs/diy/SHOPPING-LIST.md) | Minimum SD kit first; NVMe/HAT = reference build |
| [Build](docs/diy/BUILD.md) | Flashable image, setup AP, find the Pi, optional publish / HA |
| [Publish](docs/diy/PUBLISH.md) | Public JPEG URL without Worker; R2 / S3 / outbox / off |
| [Templates](examples/README.md) | Camera, pipeline, publish env, Worker, Home Assistant |
| [Architecture](docs/ARCHITECTURE.md) | What each process owns |
| [LAN pages](docs/LAN-UI.md) | Maintenance, schedule, variants editor |
| [Pi host](docs/PI-HOST.md) | NVMe boot, headless tuning, network |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Health checks |
| [Cost](docs/COST-PERF.md) | Free-plan defaults |

## Privacy

Originals and variants marked private are served on the LAN. Only a public variant with `publish: true` and a live object key is uploaded. Credentials belong in `/etc/webcam-pipeline/env` on the Pi (`AWS_*` names). The blank file is [`examples/pi/r2.env`](examples/pi/r2.env). Do not commit tokens.

`:8080` and `:8090` have no login. Keep them off the public internet. Details: [SECURITY.md](SECURITY.md).

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Security](SECURITY.md)

## License

[MIT](LICENSE)
