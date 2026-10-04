# Shopping list

Canonical bill of materials for this reference build. Shop prices change; **Paid** amounts are approximate what this build cost (goods only where noted), not a live quote.

There is no second BOM in this repo — link here from README / DIY hub. Do not invent SKUs for unnamed roles.

## Bill of materials

| Role | Item | Notes | Paid |
|------|------|-------|------|
| Computer | [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/), 8 GB RAM | Headless. Camera + pipeline on one board. 4 GB is enough to try. | — |
| OS | Raspberry Pi OS Lite, 64-bit | No desktop. Flash with [Raspberry Pi Imager](https://www.raspberrypi.com/software/). | — |
| Camera | [HQ Camera SC0261](https://www.raspberrypi.com/products/raspberry-pi-hq-camera/) (IMX477, C–CS) | Includes 5 mm C–CS adapter ring — remove it before fitting the CS lens below. | ~56 € |
| Lens | Arducam CS-mount 16 mm (LN050 / CS2316ZM02) | Manual focus + aperture. ~24° HFOV on this sensor. Closest focus ~0.2 m. | ~26 € |
| Camera cable | Pi 5 CSI flex, 50 cm | 15-pin camera ↔ 22-pin Pi. Enough for a window-shelf mount beside the board. | ~3 € |
| Boot disk | Kingston NV3 NVMe 500 GB, M.2 **2230** (SNV3SM3/500G) | Appears as `/dev/nvme0n1` for the scripts in `pi/scripts/` as written. | ~142 € |
| NVMe adapter | Raspberry Pi M.2 HAT+ Compact | Pi 5 PCIe → M.2. USB enclosure as `/dev/sda` needs `DST_DISK` changes in `pi/host/desired.env`. | ~15 € |
| Bootstrap / fallback | microSDXC 256 GB (e.g. SanDisk Extreme PRO) | Imager target and fallback if NVMe is absent. 32 GB is enough to install. | ~62 € |
| Case | [Official Raspberry Pi 5 case](https://www.raspberrypi.com/products/raspberry-pi-5-case/) | Shelf mount. Fan included — do **not** buy a separate Active Cooler. | — |
| Cooling | Fan included with official Pi 5 case | | — |
| Power | Official-class USB-C PD for Pi 5 | Typically **5 V / 5 A / 27 W**. NVMe + camera brown out weak chargers. Not named here. | — |
| Network | Wi-Fi day to day; Ethernet optional | DHCP. Router reservation optional. | — |

**Named goods subtotal** (camera + lens + HAT + cable + NVMe + microSD, excl. shipping): about **303 €**. Board, case, and PSU not included.

## Camera and lens (focus gotcha)

The lens is CS-mount. The camera arrives with a C-mount adapter ring already fitted. **Take that ring off** before you screw this lens on. Leave the ring in place and a distant subject never gets sharp; turning further unscrews the lens instead of focusing. Steps: [BUILD.md](BUILD.md) § Focus.

The 16 mm lens sees a narrow slice (a distant tower can fill the frame). Shorter CS lengths (8 mm / 12 mm) see more garden — those are not what this reference Pi uses. Focus and iris are rings on the lens; nothing in YAML sets them.

## You also need (not a specific product here)

| Role | Why |
|------|-----|
| Lens cap, and a way to set focus and aperture | HQ lenses are manual. Focus once at the window or mount, then leave it. |
| Mount | Tripod screw (1/4"-20) or a window shelf. Nothing in this repo assumes an outdoor housing. If the camera itself is outdoors, add a weather housing; the Pi can stay indoors on a longer CSI cable. |
| microSD reader | To flash the card from your computer. |
| SSH key on your computer | Preferred over password login. Do not commit the private key. |

## Optional, same shape as this project

| Role | Used here | Skip if |
|------|-----------|---------|
| Cloudflare account | R2 bucket + Worker on the Free plan | You only want the picture on your LAN. |
| Custom domain | This deployment uses one; DIY copies use theirs | You are happy with a LAN URL. |
| Home Assistant | YAML package only, on another machine | You do not already run HA. |
| Second public crop | `wide` variant, not uploaded by default | One landscape JPEG is enough. |

## Minimum to see a picture

Pi 5 (4 GB is enough to try; this one is 8 GB), official-class USB-C PD supply, microSD, HQ camera SC0261, the LN050 16 mm CS lens with the C–CS ring removed, a Pi 5 CSI cable, and Wi-Fi or Ethernet. NVMe, official case (cooling included), Cloudflare, and Home Assistant come after `/raw.jpg` works.

## What this software expects from the camera

- libcamera stack (`picamera2` or `rpicam`), not the legacy `raspistill` camera stack.
- JPEG stills. The pipeline never talks to the sensor itself; it downloads `http://127.0.0.1:8080/raw.jpg` and probes `GET /maintenance` for the maintenance placeholder.
- A missing camera does not crash the box. `/feed.jpg` switches to the maintenance placeholder and capture keeps retrying (`/raw.jpg` stays the live frame when one exists; private HA uses raw).
