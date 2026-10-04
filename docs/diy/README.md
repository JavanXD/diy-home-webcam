# DIY — build your own

Copy this repo onto a Raspberry Pi, point a High Quality Camera at a view you own, keep a private JPEG on the LAN, and optionally publish one privacy-filtered public JPEG to Cloudflare R2.

Feature tour (LAN screenshots): [root README → Features](../../README.md#features).

| Doc | What it is |
|-----|------------|
| [SHOPPING-LIST.md](SHOPPING-LIST.md) | Canonical BOM (Pi 5, HQ camera, 16 mm CS lens, HAT, NVMe, SD) |
| [BUILD.md](BUILD.md) | Flashable image / setup AP → provision → focus → optional R2 / HA |
| [BEFORE-PUBLIC.md](BEFORE-PUBLIC.md) | Strip list before this GitHub repo itself is public |
| [examples/README.md](../../examples/README.md) | Camera / pipeline / Worker / HA templates |

Open tasks: [TODO.md](../../TODO.md).

Local smoke (no Pi): `make test` and `./scripts/smoke-local.sh` from the repo root.

## Photos

Files live in [`images/`](images/). Prefer LAN UI screenshots over the public website when the goal is “how to build this.” Do **not** commit neighbor windows unmasked, house numbers, or an unmasked private JPEG.

| File | Role |
|------|------|
| `images/lan-variants-masks.png` | Root README — Edit masks |
| `images/lan-camera-home.png` | Root README — live preview + focus meter |
| `images/lan-schedule.png` | Root README — solar schedule |
| `images/pi-camera-assembly.jpg` | Desk shot: Pi 5 + HQ + 16 mm (see TODO.md if missing) |
| `images/public-page.png` | Optional: your own Worker landing or masked public JPEG |
