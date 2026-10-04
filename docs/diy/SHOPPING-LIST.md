# Shopping list

Canonical bill of materials. Shop prices change; **Paid** amounts are approximate what this build cost (goods only where noted), not a live quote.

There is no second BOM in this repo — link here from README / DIY hub. Do not invent SKUs for unnamed roles.

## Minimum kit (LAN-only, microSD)

Enough to see a private JPEG on your home network. Boot from microSD; skip NVMe, M.2 HAT, and the tall shelf stand until you want the reference layout.

| Role | Item | Notes | Paid |
|------|------|-------|------|
| Computer | [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/), 4 GB or 8 GB | Headless. Camera + pipeline on one board. 4 GB is enough to try; this reference Pi is 8 GB. | — |
| OS | Raspberry Pi OS Lite, 64-bit | No desktop. Prefer the flashable image, or flash with [Raspberry Pi Imager](https://www.raspberrypi.com/software/). | — |
| Boot disk | microSDXC 32 GB+ (A2 / U3 class is fine) | Imager / flashable-image target. 32 GB is enough to install; larger helps timelapse later. | — |
| Camera | [HQ Camera SC0261](https://www.raspberrypi.com/products/raspberry-pi-hq-camera/) (IMX477, C–CS) | Includes 5 mm C–CS adapter ring — remove it before fitting a CS lens. | ~56 € |
| Lens | Arducam CS-mount **16 mm** (LN050 / CS2316ZM02) *or shorter* | Manual focus + aperture. 16 mm ≈24° HFOV (distant tower). **8 mm / 12 mm** CS lenses see more garden / yard — pick for your distance. Closest focus on LN050 ~0.2 m. | ~26 € (16 mm) |
| Camera cable | Pi 5 CSI flex (15-pin camera ↔ 22-pin Pi) | 30–50 cm is typical for a window sill next to the board. | ~3 € |
| Power | [Official Raspberry Pi 5 USB-C PD PSU](https://www.raspberrypi.com/products/27w-power-supply/) (27 W class) | **5 V / 5 A / 27 W**. Official supply included with this setup. Weak phone chargers brown out under load. | — |
| Network | Wi-Fi day to day; Ethernet optional | DHCP. Router reservation optional. | — |

**You do not need** Cloudflare, a Worker, Home Assistant, NVMe, or an M.2 HAT for LAN-only use. Publish stays **Off** until you want a public JPEG ([PUBLISH.md](PUBLISH.md)).

### Camera and lens (focus gotcha)

The lens is CS-mount. The camera arrives with a C-mount adapter ring already fitted. **Take that ring off** before you screw a CS lens on. Leave the ring in place and a distant subject never gets sharp; turning further unscrews the lens instead of focusing. Steps: [BUILD.md](BUILD.md) § Focus.

Focus and iris are rings on the lens; nothing in YAML sets them.

## Reference build (this Pi)

Same camera stack as the minimum kit, plus storage/cooling/mount choices used on the live ops Pi. Treat NVMe + HAT + tall stand as **optional upgrades**, not day-one requirements.

| Role | Item | Notes | Paid |
|------|------|-------|------|
| Computer | Raspberry Pi 5, **8 GB** | Same role as minimum kit. | — |
| Boot / data | Kingston NV3 NVMe 500 GB, M.2 **2230** (SNV3SM3/500G) | Appears as `/dev/nvme0n1` for the scripts in `pi/scripts/` as written. | ~142 € |
| NVMe adapter | Raspberry Pi M.2 HAT+ Compact | Pi 5 PCIe → M.2. USB enclosure as `/dev/sda` needs `DST_DISK` changes in `pi/host/desired.env`. | ~15 € |
| Bootstrap / fallback | microSDXC 256 GB (e.g. SanDisk Extreme PRO) | Imager target and fallback if NVMe is absent. | ~62 € |
| Case | [Official Raspberry Pi 5 case](https://www.raspberrypi.com/products/raspberry-pi-5-case/) | Shelf mount. Fan included — do **not** buy a separate Active Cooler. | — |
| Cooling | Fan included with official Pi 5 case | | — |
| Mount | Tall camera stand (1/4"-20) + window shelf | Photos below. Not a specific SKU here. | — |
| Lens (reference) | Arducam CS 16 mm LN050 | Narrow FOV for a distant steeple; gardens often want 8 mm / 12 mm instead. | ~26 € |

**Named goods subtotal** for the reference extras (camera + 16 mm lens + HAT + cable + NVMe + microSD, excl. shipping): about **303 €**. Board, case, and PSU not included.

<img src="images/pi-nvme-hat-sd.jpg" alt="Pi 5 case open with M.2 HAT+ Compact, Kingston NVMe 500 GB, SanDisk Extreme PRO microSD" width="420" />

Window-shelf reference (optional tall stand):

<img src="images/pi-camera-assembly.jpg" alt="HQ camera on tall stand" width="280" />
<img src="images/pi-full-setup.jpg" alt="Pi in official case with tall stand and CSI" width="280" />

## You also need (not a specific product here)

| Role | Why |
|------|-----|
| Lens cap, and a way to set focus and aperture | HQ lenses are manual. Focus once at the window or mount, then leave it. |
| Mount | Tripod screw (1/4"-20) or a window shelf. Nothing in this repo assumes an outdoor housing. If the camera itself is outdoors, add a weather housing; the Pi can stay indoors on a longer CSI cable. |
| microSD reader | To flash the card from your computer. |
| SSH key on your computer | Preferred over password login. Do not commit the private key. |

## Optional later

| Role | Used here | Skip if |
|------|-----------|---------|
| Cloudflare account | R2 bucket + optional Worker on the Free plan | You only want the picture on your LAN, or you hotlink a public object URL without a branded page. |
| Custom domain | Branded Worker landing | You are happy with a public JPEG URL or a LAN URL. |
| Home Assistant | YAML package only, on another machine | You do not already run HA. |
| Second public crop | `wide` variant, not uploaded by default | One landscape JPEG is enough. |
| NVMe + M.2 HAT | Reference build OS disk / large timelapse archive | microSD is enough for LAN-only and light history. |

## What this software expects from the camera

- libcamera stack (`picamera2` or `rpicam`), not the legacy `raspistill` camera stack.
- JPEG stills. The pipeline never talks to the sensor itself; it downloads `http://127.0.0.1:8080/raw.jpg` and probes `GET /maintenance` for the maintenance placeholder.
- A missing camera does not crash the box. `/feed.jpg` switches to the maintenance placeholder and capture keeps retrying (`/raw.jpg` stays the live frame when one exists; private HA uses raw).
