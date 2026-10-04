# LAN pipeline

Runs on the same Raspberry Pi as the camera (`webcam-pipeline.service`, port 8090). Pulls originals from `127.0.0.1:8080`, renders variants, serves private images to Home Assistant, and publishes public JPEGs to any S3-compatible store (or a local outbox).

## Run (against local camera appliance)

Terminal 1 — Camera:

```bash
cd pi/camera && source .venv/bin/activate
python -m app.main
```

Terminal 2 — Pipeline:

```bash
cd pi/pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/pipeline.example.yaml config/pipeline.yaml
# cameras/example/camera.yaml already points at http://127.0.0.1:8080/raw.jpg
python -m app.main --once   # single pass
# or
python -m app.main          # loop + private HTTP :8090
```

Private URLs:

- http://127.0.0.1:8090/health — overall status + next_steps
- http://127.0.0.1:8090/status — per-camera stages
- http://127.0.0.1:8090/debug — checklist
- http://127.0.0.1:8090/schedule/ui — **public** livestream schedule (LAN only; HA stays live)
- http://127.0.0.1:8090/variants/ui — create/edit crop & privacy masks (writes YAML; LAN only; live JPEG URL)
- http://127.0.0.1:8090/cameras/example/variants/private.jpg
- http://127.0.0.1:8090/private/example.jpg
- `POST /refresh` — acquire + force re-render + publish (`{"camera":"example"}`)
- `POST /refresh` with `{"render_only":true}` — regenerate from stored original only
- `POST /cameras/example/refresh` — same, camera in path

**Public night schedule:** by default solar (±30 min around sunrise/sunset for your camera location). While offline, R2 live JPG is a placeholder (“Wieder da ab …”); private HA camera is unchanged. Upload a custom JPEG in the schedule UI or keep the shipped default.

**Timestamp burn-in:** variant YAML `timestamp.format` is Europe/Berlin wall clock (`%Y-%m-%d %H:%M` via `camera.yaml` `timezone`) — no `CEST`/`UTC` suffix (`%Z` avoided on purpose).

Logs show `[acquire]` → `[store]` → `[render]` → `[publish]` per cycle.  
Acquire/publish failures keep last-good local files (fail-safe).

See [docs/TROUBLESHOOTING.md](../docs/TROUBLESHOOTING.md) and `../scripts/diagnose.sh`.

## Publish (S3-compatible)

Full guide: [docs/diy/PUBLISH.md](../../docs/diy/PUBLISH.md). Setup UI: `:8090/setup/ui`.

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com   # or MinIO / AWS / …
export R2_BUCKET=example-webcam   # or S3_BUCKET=
```

```yaml
publish:
  enabled: true
  backend: s3          # s3 | r2 (alias) | local
  s3:
    bucket: example-webcam
    endpoint_url: https://s3.example.com
    region: auto
    force_path_style: false
```

Legacy `backend: r2` and nested `r2:` still work. Without remote credentials, use `backend: local` for `data/outbox/`, or `enabled: false` to skip upload.
