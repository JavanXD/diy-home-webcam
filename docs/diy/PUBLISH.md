# Publish guide (S3-compatible)

The pipeline can upload the public live JPEG to any **S3-compatible** object store, write the same key layout to a **local outbox**, or leave publish **off**.

Configure on the Pi LAN page **Setup → Publish** (`http://<pi>:8090/setup/ui`), or by editing `/etc/webcam-pipeline/pipeline.yaml` plus `/etc/webcam-pipeline/env`.

Secrets never belong in git. The blank template is [`examples/pi/r2.env`](../../examples/pi/r2.env) (name is historical; same shape for MinIO/AWS/etc.).

## Env vars (boto3 names)

| Variable | Required for remote upload | Notes |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | yes | Access key id |
| `AWS_SECRET_ACCESS_KEY` | yes | Secret (mode `640`, `root:webcam` on the Pi) |
| `AWS_ENDPOINT_URL` | yes\* | S3 API endpoint URL |
| `R2_BUCKET` or `S3_BUCKET` | yes | Bucket name (`S3_BUCKET` preferred alias; both accepted) |
| `AWS_DEFAULT_REGION` | no | Default `auto` (fine for R2; use `us-east-1` etc. for AWS) |
| `AWS_S3_FORCE_PATH_STYLE` | no | `true` for many MinIO setups |
| `CLOUDFLARE_ACCOUNT_ID` | no | R2 helper — fills endpoint when `AWS_ENDPOINT_URL` is empty |

\*For Cloudflare R2 you can omit `AWS_ENDPOINT_URL` if `CLOUDFLARE_ACCOUNT_ID` is set; the pipeline builds `https://<account>.r2.cloudflarestorage.com`.

Install on the Pi:

```bash
sudo install -m 640 -o root -g webcam /path/to/your.env /etc/webcam-pipeline/env
sudo systemctl restart webcam-pipeline
```

## Provider presets

### Off

- Setup UI: **Off — do not upload**
- Or `publish.enabled: false` in `pipeline.yaml`
- Public variants stay on the Pi (LAN / Home Assistant still work)

### Cloudflare R2

1. Create a bucket and an **Object Read & Write** R2 API token for that bucket.
2. Setup UI: **Cloudflare R2** — account id (optional), bucket, access key, secret. Endpoint auto-fills from the account id.
3. Or copy [`examples/pi/r2.env`](../../examples/pi/r2.env), fill values, install as `/etc/webcam-pipeline/env`.
4. `publish.enabled: true` and `backend: s3` (legacy `backend: r2` still works).

Optional public site: Cloudflare Worker + R2 binding — see [BUILD.md](BUILD.md) § publish and [`examples/webhosting/`](../../examples/webhosting/).

### Custom S3 (MinIO, AWS, Wasabi, Backblaze B2, …)

Setup UI: **Custom S3-compatible**. Set:

| Field | Example |
|---|---|
| Endpoint | MinIO `http://192.168.1.10:9000` · AWS regional S3 URL · B2 `https://s3.<region>.backblazeb2.com` |
| Bucket | your bucket name |
| Region | `us-east-1` / provider region / `auto` |
| Path-style | often **on** for MinIO; usually **off** for AWS/R2 |
| Keys | provider access key + secret |

`pipeline.yaml` shape:

```yaml
publish:
  enabled: true
  backend: s3          # s3 | r2 (alias) | local
  provider: s3         # optional UI hint: r2 | s3 | local | off
  local_outbox: data/outbox
  s3:
    bucket: example-webcam
    endpoint_url: https://s3.example.com
    region: auto
    force_path_style: false
  # legacy key still read/written for older configs:
  r2:
    bucket: example-webcam
    endpoint_url: https://s3.example.com
    region: auto
```

### Local outbox only

- Setup UI: **Local outbox only**
- Or `publish.enabled: true` + `backend: local`
- Files land under `data/outbox/` with the same `live/…` and optional `history/…` keys — no cloud credentials needed

## Test connection

On Setup → Publish, **Test connection** runs `head_bucket` with the form values (or saved env). It does not print secrets. After **Save**, restart `webcam-pipeline` so the upload loop picks up new keys.

## Public object key

The live object name comes from `cameras/<id>/camera.yaml` → `publish.public_live_key` (e.g. `live/example-live-webcam.jpg`). Your website or Worker must serve that same key. Changing the live crop does not rename the object.
