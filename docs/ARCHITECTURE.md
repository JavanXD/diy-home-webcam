# Architecture

## Components

1. **`pi/camera`** — Capture appliance on `:8080`. **`GET /raw.jpg`** = always last-good live capture (pipeline acquire + aim/focus; never Wartungsbild). **`GET /feed.jpg`** = optional maintenance-aware path (Wartungsbild when maintenance on). Disk file may still be `data/image.jpg`. No privacy processing or burn-in — overlays live on `:8090`.
2. **`pi/pipeline`** — Same Raspberry Pi (second systemd unit, `:8090`). Acquires `http://127.0.0.1:8080/raw.jpg`, detects Wartungsbild via `GET /maintenance` (or `/health`), renders variants, serves private images to Home Assistant, publishes public JPEGs to Cloudflare R2. Home Assistant does not run this process.
3. **`shared/`** — Shared Python used by both services (`lan_ui` design system, `jpeg_util`, version, logging).
4. **webhosting** — Cloudflare Worker bound to R2. Serves `index.html` and the latest public JPEG. History prefixes are not publicly listed.
5. **homeassistant** — YAML package for private camera entity and health sensors.
6. **cameras/** — Declarative per-camera configuration and variant definitions.
7. **`pi/host/`** — Desired host state (NVMe boot order); apply via `pi/scripts/` — see [PI-HOST.md](PI-HOST.md).

## Data flow

```
Pi capture :8080 /raw.jpg  →  pipeline :8090  →  render private (always live)  →  LAN HTTP (HA)
  (/feed.jpg = optional)                         →  render public (Wartung if maint) →  R2 live/ + history/
                                                                      →  Worker → public HTTPS
```

**Public live publish precedence** (fixed R2 / outbox live key only):

1. Schedule offline → night/offline placeholder (even if Wartungsbild is on)
2. Else maintenance on → Wartung frame (history skipped)
3. Else normal live variant from raw original

**Private HA** always renders from the acquired `/raw.jpg` original — never schedule placeholder, never Wartungsbild.
## R2 keys

| Key pattern | Purpose |
|-------------|---------|
| `live/example-live-webcam.jpg` | **Fixed** public live object (Worker + public catalog). Which *variant* feeds it is chosen at runtime (`data/<camera>/public-live.json`); switching does **not** rename this key. |
| `live/example-wide-webcam.jpg` | Optional secondary public stream (only if a non-live variant has its own `r2_live_key` + `publish: true`) |
| `history/example/<variant>/YYYY/MM/DD/HHMMSS.jpg` | Optional. Off by default — daylight frames stay on the Pi |

Local LAN JPEG filenames are `{variant}.jpg` (e.g. `landscape.jpg`, `wide.jpg`, `private.jpg`) — independent of the fixed public live URL.

## Timelapse + retention

- LAN page `:8090/timelapse/ui` stores daylight frames under `data/<camera>/timelapse/` (about every 2 minutes while the public schedule is online) and builds an MP4 or GIF there. Those files are not uploaded. Operators can delete one History day (`POST /timelapse/<day>/delete` + confirm) — frames + that day’s exports only.
- The bucket gets the **current live JPEG** only, unless `publish.history.enabled` is set true.
- Encoder: `scripts/make-timelapse.py` (GIF or APNG from a folder of JPEGs) remains for offline use.
- Retention: `cameras/*/camera.yaml` → `timelapse.retention_days` (default **400**) plus a size budget `timelapse.max_gb` (default **40**) under `data/<camera>/timelapse/`. Oldest day folders (and their exports) are pruned when over either limit. `publish.history.retention_days` still applies if bucket history is turned on; prune with `scripts/prune-history.py`.
- Nothing from the Timelapse page is uploaded to Cloudflare; MP4/GIF exports stay on the Pi for local download.
- Bucket bootstrap: `scripts/setup-r2.sh` (requires R2 enabled on the Bollenhut Cloudflare account first).

## Multi-camera

Each camera is a directory under `cameras/`. The pipeline loads one or more camera IDs from its config. Variants remain camera-local so crops and masks can differ.

## Variant render (no stretch)

`pi/pipeline/app/render.py` crops the original, applies privacy masks / optional mild `artistic.*`, then **cover-fits** into `output.width`×`height` (uniform scale + center crop — never anisotropic resize). Overlays (timestamp, site badge, watermark) draw after fit. Wartung/Nacht maintenance frames also cover-fit, then redraw glyphs at final pixels. LAN Preview (`POST /variants/<name>/preview`) calls the same `render_one`.
