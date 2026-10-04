# Troubleshooting

Fail-safe rule for the whole system: **never replace a good image with a bad/empty one.** When something breaks, last-good files stay on disk and keep being served.

## Quick diagnose

```bash
# Defaults: Pi :8080, pipeline :8090
./scripts/diagnose.sh

# Remote (both services on the camera Pi)
PI_URL=http://home-webcam.local:8080 \
PIPE_URL=http://home-webcam.local:8090 \
  ./scripts/diagnose.sh
```

Also open:

| Service | URL |
|---------|-----|
| Pi health | `http://<pi>:8080/health` |
| Pi debug | `http://<pi>:8080/debug` |
| Pipeline health | `http://<pi>:8090/health` |
| Pipeline debug | `http://<pi>:8090/debug` |

`/health` is short (`status`, `summary`, `next_steps`).  
`/status` is the full dump.  
`/debug` adds a checklist and common failure map.

## What the logs mean

### Raspberry Pi (`camera-appliance`)

| Log prefix | Meaning |
|------------|---------|
| `[startup]` | Config, backend, existing image loaded |
| `[capture] ok` | New JPEG written atomically |
| `[capture] FAILED` | Capture error; **last good JPEG still served** |
| `[shutdown]` | Clean stop |

```bash
journalctl -u webcam-camera -f
# or local:
cd pi/camera && python -m app.main --verbose
```

### Pipeline (`pipeline`)

Each camera cycle is labeled:

```
[example] ——— cycle start ———
[example] [acquire] GET …
[example] [store] NEW original / unchanged
[example] [render] rebuilt=… cached=…
[example] [publish] landscape → live/…
[example] ——— cycle OK ——— …
```

| Stage | Fail-safe |
|-------|-----------|
| acquire fails | Keep last original + variants; skip publish |
| render fails | Keep prior variant files |
| publish fails | Keep local variants for HA; retry next cycle |

```bash
journalctl -u webcam-pipeline -f
cd pi/pipeline && python -m app.main --verbose
cd pi/pipeline && python -m app.main --once   # single cycle, then exit
```

## Common situations

### Pi `/raw.jpg` returns 503

No successful capture yet (maintenance does **not** affect `/raw.jpg`).

1. `GET /debug` → follow `next_steps`
2. `POST /capture`
3. Confirm `capture_backend: picamera2` (or `rpicam`) in `/etc/webcam-camera/camera.yaml`
4. If no camera: `/health` should show `maintenance.auto` / reason `no_camera` and `/feed.jpg` should be Wartungsbild; `/raw.jpg` stays 503 until a frame exists

### `/raw.jpg` is nearly black at night (but 200 OK)

Valid capture from the sensor with very low lux — not Wartungsbild, not simulation. Check `X-Webcam-Maintenance` is absent on **`/feed.jpg`** (raw never sets it), `/health` shows `camera_detected` + live backend, and mean luma on the JPEG. Clock/temp burn-in only appears on `:8090` variants. Wait for daylight (or add FOV light) before tuning privacy masks; forced long exposure still looks near-black when Lux≈0.

### Public image is the Wartung placeholder

The Pi is in maintenance mode (manual **or** auto) **and** the public schedule is currently online. Open `http://<pi>:8080/debug/ui` and turn **Wartungsbild** off, or `curl -X POST http://<pi>:8080/maintenance/off`. Capture keeps running; `/feed.jpg` shows the placeholder while `/raw.jpg` stays the real scene. Pipeline acquires raw and applies Wartung only to **public** variants.

If the public schedule is **offline** (night window), the public live key should show the **Nacht / Wieder da** placeholder instead — schedule offline overrides Wartung for R2/outbox live only. **Private HA always stays on the live raw frame** (never Nacht, never Wartung).
Auto Wartungsbild (`maintenance.auto: true`, reason `no_camera` / `capture_failed`) means the camera is missing or capture is failing — fix the hardware. Auto clears when capture recovers; manual stays on until you turn it off.

### Capture FAILED with Permission denied on `pi/camera/data/`

Usually a **sync race**, not a broken camera. `sync-to-pi.sh` used to `chown -R` the whole `pi/` tree (including live `data/`) to the SSH user while `webcam-camera` was still writing `image.jpg.tmp` / `maintenance.on` / `focus-region.json`. That produced `Errno 13`, and an uncaught second PermissionError when auto-Wartung tried to write the flag **killed the capture-loop thread** until the next unit restart.

**Fix (code):** sync now prunes `*/data` from the pre-rsync chown; maintenance flag persist is fail-soft; capture-loop stays alive. After an old sync mid-flight:

```bash
sudo /opt/home-webcam-pipeline/pi/scripts/fix-data-perms.sh
sudo systemctl restart webcam-camera   # only if capture-loop already died
```

Confirm `ls -ld …/pi/camera/data` is `webcam:webcam`.

### Journal spam: ConnectionReset / BrokenPipe on :8080/:8090

Browsers and HA abort mid-JPEG. Harmless. Both services use a quiet HTTP server that logs those at DEBUG only (no full traceback).

### Pipeline logs “camera maintenance ON” every minute

Expected while Wartungsbild is on; logs once per ON/OFF transition (not every poll cycle).

### R2 API error 10042 / setup-r2 fails

R2 is not enabled yet on the your Cloudflare account. Enable R2 once in the dashboard, then re-run `the Cloudflare dashboard / Wrangler`. Create `your R2 secrets env file` from `pi/pipeline/config/r2.env.example`.

### Public site shows old image / 503

1. Confirm pipeline publish: `GET /status` → `cameras.*.publish` and `publish.backend`
2. Local outbox: `ls data/outbox/live/`
3. R2: credentials in env (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL`, `R2_BUCKET`)
4. Worker: `cd webhosting && npx wrangler tail`

### Home Assistant camera / image blank or “entity not found”

1. **Entity not found:** Generic Camera YAML was removed in HA 2024.2. This package uses `image.webcam_example_private` (template image), not `camera.*`. Re-copy `homeassistant/packages/webcam_example.yaml`, reload template entities / restart HA. See [homeassistant/README.md](../homeassistant/README.md).
2. Pipeline private URL must be reachable from HA
3. `curl` the same URL HA uses: `/cameras/example/variants/private.jpg` (entity still exists on 404; run pipeline refresh after a frame exists)
4. Run one pipeline cycle after the Pi has an image
5. **Nearly black / looks empty at night:** private LAN-only stays on live `/raw.jpg`. After dark the JPEG is valid but can be almost black (sensor floor) with only the burn-in clock visible — that is not a broken URL. Check `file` / mean luminance, or wait for daylight.
6. **REST sensors OK but picture blank:** confirm Developer Tools → States → `image.webcam_example_private` is not `unavailable`, then open the Lovelace card (template images fetch on demand via `/api/image_proxy/`). Re-copy the package if the entity is missing.

## Health states (both services)

| Status | Meaning |
|--------|---------|
| HEALTHY / OK | Recent success; good image available |
| DEGRADED | Problem now, but last-good data still served |
| UNHEALTHY / FAILED | No usable image yet / fatal config |
| STARTING | Pipeline has not completed a cycle |

## Smoke test (dev machine)

```bash
./scripts/smoke-local.sh
./scripts/diagnose.sh
```
