# Camera appliance

## Quick start (local)

```bash
cd pi/camera
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/camera.example.yaml config/camera.yaml
python -m app.main
```

On a machine without a camera module, `/feed.jpg` will serve auto Wartungsbild while capture keeps retrying (`/raw.jpg` returns 503 until a frame exists). Or run `./scripts/smoke-local.sh` from the repo root for a full local pass.

Endpoints:

- http://127.0.0.1:8080/raw.jpg — **always** last-good live capture (aim/focus; never Wartungsbild; no overlays)
- http://127.0.0.1:8080/feed.jpg — downstream feed: Wartungsbild when maintenance on (`X-Webcam-Maintenance: 1`), else same as raw
- http://127.0.0.1:8080/health — status, summary, next_steps, fail_safe, maintenance, live_preview
- http://127.0.0.1:8080/status — full operational dump
- http://127.0.0.1:8080/ — camera home (status, **Raw** preview, **Live preview** Start/Stop, capture, Maintenance link)
- http://127.0.0.1:8080/debug — troubleshooting checklist
- http://127.0.0.1:8080/debug/ui — Wartungsbild (Maintenance) toggle
- `POST http://127.0.0.1:8080/capture`
- `POST http://127.0.0.1:8080/maintenance/on` and `/maintenance/off`
- `GET|POST http://127.0.0.1:8080/live-preview` (+ `/live-preview/on` `/live-preview/off`) — temporary high-rate capture for aiming (~0.75s, auto-off ~5 min)

### Live preview (focus mode)

On **Camera home** (`/`), **Start live preview** switches the capture loop to a short interval (`live_preview.interval_seconds`, default **0.75s**) so `/raw.jpg` updates often enough to aim and focus. UI polls Raw ~every 750 ms while on and shows a countdown progress bar. Session **auto-offs after ~5 minutes** (`live_preview.duration_seconds`, default `300`); **Stop** ends early. Wartungsbild, public schedule, and `/feed.jpg` behaviour are unchanged — preview is Raw aiming only.

### Fail-safe

- Capture failure never overwrites a good JPEG on disk.
- With **maintenance off**: last-good may still be served on both paths (`X-Webcam-Fail-Safe: serving-last-good`).
- With **maintenance on** (manual or auto): `/feed.jpg` returns the Wartungsbild placeholder (`X-Webcam-Maintenance: 1`); `/raw.jpg` stays the true last capture for aiming. Pipeline `source.url` must use `/feed.jpg`.
- Auto-maintenance engages at startup when no camera is detected, or after `health.auto_maintenance_after_failures` consecutive capture failures. Auto clears when capture recovers. Manual maintenance is not auto-cleared.

See also [docs/TROUBLESHOOTING.md](../../../docs/TROUBLESHOOTING.md) and `../../../scripts/diagnose.sh`.

## Production install

Flash / first boot / setup AP: [docs/diy/BUILD.md](../../../docs/diy/BUILD.md). Do not put private SSH keys in this repository.

```bash
# From the repo root on the Pi — camera :8080 and pipeline :8090 together
sudo ./pi/provision.sh
# Default /etc/webcam-camera/camera.yaml uses capture_backend: picamera2
sudo systemctl restart webcam-camera webcam-pipeline
```

Camera-only install is still `pi/camera/scripts/provision.sh`. The pipeline unit starts after `webcam-camera`.

From your Mac (host/SSH: [pi/README.md](../../README.md) / `Notes.txt`):

```bash
./pi/camera/scripts/deploy.sh pi@<pi-host>
# Failed health checks auto-restore the previous backup
./pi/camera/scripts/rollback.sh pi@<pi-host>
```

## Service commands

```bash
sudo systemctl status webcam-camera
sudo systemctl enable --now webcam-camera
sudo systemctl restart webcam-camera
sudo systemctl stop webcam-camera
journalctl -u webcam-camera -f
```

### Uninstall

```bash
sudo systemctl disable --now webcam-camera
sudo rm -f /etc/systemd/system/webcam-camera.service
sudo systemctl daemon-reload
# Optional: remove app + data (keeps /etc/webcam-camera/camera.yaml unless you delete it)
sudo rm -rf /opt/home-webcam-pipeline/pi/camera
sudo userdel webcam 2>/dev/null || true
```

## Capture settings

In `camera.yaml` / `/etc/webcam-camera/camera.yaml`:

| Key | Notes |
|-----|--------|
| `capture_backend` | `picamera2` \| `rpicam` |
| `width` / `height` | Still size (default IMX477-ish 4056×3040) |
| `jpeg_quality` | Applied in picamera2 via RGB→JPEG encode; `-q` for rpicam |
| `exposure_mode` | `auto` / `off` (AeEnable) |
| `awb_mode` | `auto` / `off` / named modes when libcamera supports them |
| `interval_seconds` | Capture loop period |
| `live_preview.duration_seconds` | Focus-mode session length before auto-off (default `300` ≈ 5 min) |
| `live_preview.interval_seconds` | Capture interval while live preview is on (default `0.75`) |
| `health.auto_maintenance_after_failures` | Consecutive failures before auto Wartungsbild (default `2`; startup no-device is immediate) |

## Recovery

1. `journalctl -u webcam-camera -n 100 --no-pager`
2. `curl -sS http://127.0.0.1:8080/debug | jq .`
3. If a bad deploy left the service unhealthy, `deploy.sh` should already have auto-rolled back; otherwise `./scripts/rollback.sh user@pi`
4. Missing camera: confirm `/health` shows `maintenance.auto` / reason `no_camera` and Wartungsbild at `/feed.jpg` (`/raw.jpg` 503 until a frame exists)

## SSH for Cursor / Mac

```
Host home-webcam
  HostName home-webcam.local
  User pi
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
```

Credentials (password + key path): `your local secrets env file` (not in git).
