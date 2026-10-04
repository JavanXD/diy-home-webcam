# DIY — build your own

Copy this repo onto a Raspberry Pi, point a High Quality Camera at a view you own, keep a private JPEG on the LAN, and optionally publish one privacy-filtered public JPEG to Cloudflare R2 or any S3-compatible store.

Feature tour (LAN screenshots): [root README → Features](../../README.md#features).

| Doc | What it is |
|-----|------------|
| [SHOPPING-LIST.md](SHOPPING-LIST.md) | Canonical BOM (Pi 5, HQ camera, 16 mm CS lens, HAT, NVMe, SD) |
| [BUILD.md](BUILD.md) | Flashable image / setup AP → provision → focus → optional publish / HA |
| [PUBLISH.md](PUBLISH.md) | R2 / MinIO / AWS S3 / local outbox / publish off |
| [BEFORE-PUBLIC.md](BEFORE-PUBLIC.md) | Ops strip list / `private/` overlay (this checkout stays private) |
| [examples/README.md](../../examples/README.md) | Camera / pipeline / Worker / HA templates |

**Public DIY repo:** [JavanXD/diy-home-webcam](https://github.com/JavanXD/diy-home-webcam) (clean history). Open ops tasks: **[TODO.md](../../TODO.md)**.

Local smoke (no Pi): `make test` and `./scripts/smoke-local.sh` from the repo root.

## Photos

Files live in [`images/`](images/). Prefer LAN UI screenshots over the public website when the goal is “how to build this.” Do **not** commit neighbor windows unmasked, house numbers, or an unmasked private JPEG.

| File | Role |
|------|------|
| `images/lan-variants-masks.png` | Root README — Edit masks |
| `images/lan-camera-home.png` | Root README — live preview + focus meter |
| `images/lan-schedule.png` | Root README — solar schedule |
| `images/pi-camera-assembly.jpg` | HQ + 16 mm on stand at the window (close-up) |
| `images/pi-full-setup.jpg` | Shelf: Pi in official case + tall stand + CSI |
| `images/pi-nvme-hat-sd.jpg` | Parts flat-lay: case open, M.2 HAT+ Compact, NVMe, microSD |
| `images/public-page.png` | Optional: your own Worker landing or masked public JPEG |

![Camera close-up](images/pi-camera-assembly.jpg)

![Full window-shelf setup](images/pi-full-setup.jpg)

![NVMe HAT, SSD, and microSD](images/pi-nvme-hat-sd.jpg)
