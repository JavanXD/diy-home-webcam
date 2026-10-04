# Shopping list

Canonical bill of materials for **this** build (Example / DIY copy). Shop prices change. Euro amounts below are what was paid on the named invoices, not a current quote.

There is no second BOM in this repo — link here from README / DIY hub / Notes. Do not invent SKUs for unnamed roles.

## What is running (verified on the Pi)

| Role | On `raspicam` today |
|------|---------------------|
| Computer | **Raspberry Pi 5 Model B Rev 1.0**, 8 GB RAM |
| Camera | IMX477 HQ (`imx477` via libcamera / picamera2) |
| Boot disk | Kingston NVMe `SNV3SM3500G` → `/dev/nvme0n1` (~466 GB) |
| Bootstrap disk | microSD ~238 GB (`mmcblk0`; marketed 256 GB) |
| Cooling | Official Pi 5 case fan (`cooling_fan`; included with case) |
| Power health | `throttled=0x0` (no under-voltage flag when checked) |

## Paid lines (by shop)

### Kubii — order 952224959 (2026-09-19)

| Article | What it is | Qty | Paid |
|---------|------------|-----|------|
| [SC0261](https://www.raspberrypi.com/products/raspberry-pi-hq-camera/) | Official Raspberry Pi High Quality Camera (C–CS). Sony IMX477, 4056×3040. Includes the 5 mm C–CS adapter ring — not a second part. | 1 | 55.63 € |
| LN050 | Arducam CS-mount lens, 16 mm, manual focus and aperture (CS2316ZM02). ~24° horizontal on this sensor. Closest focus ~0.2 m. Max aperture ~f/1.2. | 1 | 25.78 € |
| | Shipping (Mondial Relay) | | 6.90 € |
| **Order total** | | | **88.31 €** |

### Reichelt — I-677917 (2026-09-21)

| Article | What it is | Qty | Paid |
|---------|------------|-----|------|
| RASP M.2 HAT+ C | Official Raspberry Pi M.2 HAT+ Compact (Pi 5 PCIe → M.2). Must appear as `/dev/nvme0n1` for the scripts in `pi/scripts/` as written. | 1 | 14.90 € |
| RASP CAM FPC 50 | Camera flat flex, 50 cm. On a **Pi 5**, use a cable that matches the Pi 5 CSI connector (15-pin camera ↔ 22-pin Pi). Enough length for a window-shelf mount beside the board. | 1 | 3.30 € |
| SNV3SM3/500G | Kingston NV3 PCIe 4.0 NVMe, 500 GB, M.2 **2230** | 1 | 141.50 € |
| | Shipping | | 5.95 € |
| **Order total** | | | **165.65 €** |

### Amazon — order 028-2084664-8129900 (2026-09-27)

| Article | What it is | Qty | Paid |
|---------|------------|-----|------|
| SanDisk Extreme PRO microSDXC 256 GB | Bootstrap / Imager target and fallback if NVMe is absent. A 32 GB card is enough to install; this one is larger so the OS can also live on it. | 1 | 61.80 € |

**Named goods subtotal** (camera + lens + HAT + cable + NVMe + microSD, excl. shipping): **302.91 €**.

## This deployment (roles)

| Role | Used here | Notes / price |
|------|-----------|---------------|
| Computer | [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/), 8 GB RAM | Headless. Both services on this one board. Paid line TBD (not in the invoices above). |
| OS | Raspberry Pi OS Lite, 64-bit | No desktop. Flash with [Raspberry Pi Imager](https://www.raspberrypi.com/software/). |
| Camera | SC0261 HQ, IMX477 | Remove the C–CS ring before fitting the LN050 (see below). |
| Lens | LN050, CS-mount, 16 mm | Screw onto the camera body, not onto the adapter ring. |
| Camera cable | 50 cm FPC (Reichelt RASP CAM FPC 50) | Pi 5–compatible CSI flex. |
| Boot disk (OS) | Kingston NVMe SNV3SM3/500G | Kernel name: `/dev/nvme0n1`. |
| Bootstrap / fallback | SanDisk Extreme PRO microSD 256 GB | |
| NVMe adapter | Raspberry Pi M.2 HAT+ Compact | USB enclosure as `/dev/sda` needs `DST_DISK` changes in `pi/host/desired.env`. |
| Case | [Official Raspberry Pi 5 case](https://www.raspberrypi.com/products/raspberry-pi-5-case/) | Shelf mount. Paid line TBD. |
| Cooling | Fan included with official Pi 5 case | Do **not** buy a separate Active Cooler — cooling comes with the case. |
| Network | Wi-Fi day to day, Ethernet optional | DHCP. Router reservation optional. |
| Power | Not named in the repo | Use a supply meant for a **Pi 5** (USB-C PD, typically **5 V / 5 A / 27 W** official-class). NVMe + camera brown out weak chargers. |

## Camera and lens (focus gotcha)

Bought as the Kubii pair. The lens is CS-mount. The camera arrives with a C-mount adapter ring already fitted. **Take that ring off** before you screw this lens on. Leave the ring in place and a distant subject never gets sharp; turning further unscrews the lens instead of focusing. Steps: [BUILD.md](BUILD.md) § Focus.

The 16 mm lens sees a narrow slice (church tower can fill the frame). Shorter CS lengths (8 mm / 12 mm) see more garden — those are not what this Pi uses. Focus and iris are rings on the lens; nothing in YAML sets them.

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
- JPEG stills. The pipeline never talks to the sensor itself; it downloads `http://127.0.0.1:8080/raw.jpg` and probes `GET /maintenance` for Wartungsbild.
- A missing camera does not crash the box. `/feed.jpg` switches to the maintenance placeholder and capture keeps retrying (`/raw.jpg` stays the live frame when one exists; private HA uses raw).
