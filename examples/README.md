# Templates

Copy these files, then change the tokens. DIY: [docs/diy/README.md](../docs/diy/README.md) · strip list: [docs/diy/BEFORE-PUBLIC.md](../docs/diy/BEFORE-PUBLIC.md) · open tasks: [TODO.md](../TODO.md).

| Token | Example value | Meaning |
|-------|---------------|---------|
| Camera id | `example` | Folder name under `cameras/`. Lowercase, hyphens ok. |
| Display name | `Example Webcam` | UI, LAN consumers (e.g. Home Assistant), placeholders. |
| Entity prefix | `webcam_example` | HA object ids. |
| Pi host | `192.168.1.50` | LAN address of the Pi. |
| Public JPEG | `live/example-live-webcam.jpg` | R2 key and Worker path. Must match. |
| Bucket | `example-webcam` | R2 bucket name. |
| Site label | `example.com` | Text burned into the public JPEG corner. |

## 1. Camera profile

```bash
cp -R examples/cameras/example cameras/my-webcam
```

Edit `cameras/my-webcam/camera.yaml`: `id`, `display_name`, storage paths, `public_live_key`, `r2_prefix_history`, `timezone`, `location`. Set `weather.url` only if you have a JSON endpoint with `current.temp_c`. The same fields (plus Wi-Fi) can be changed later at `http://<pi>:8090/setup/ui`.

Edit `variants/landscape-public.yaml`, `variants/wide-public.yaml`, and optional `variants/tower-public.yaml` (9:16 Kirchturm zoom): `site_badge.site`, and `r2_live_key` if you renamed the live object. Leave crops rough; tune them at `http://<pi>:8090/variants/ui` after the first frame.

## 2. Pipeline

On a fresh Pi, provision copies `pi/pipeline/config/pipeline.example.yaml`. **This checkout’s copy lists `example`.** Either:

- add your id next to `example` in `/etc/webcam-pipeline/pipeline.yaml`, or
- when you rename the starter camera, replace that example with [`pi/pipeline.yaml`](pi/pipeline.yaml).

Override one camera’s source without editing YAML:

```bash
export WEBCAM_MY_WEBCAM_SOURCE_URL=http://127.0.0.1:8080/raw.jpg
```

The id is uppercased and hyphens become underscores.

## 3. R2 (optional)

[`pi/r2.env`](pi/r2.env) → a secrets file outside git → `/etc/webcam-pipeline/env`.

## 4. Public site (optional)

[`webhosting/README.md`](webhosting/README.md).

## 5. Home Assistant (optional)

[`homeassistant/webcam.yaml`](homeassistant/webcam.yaml) and [`homeassistant/lovelace.yaml`](homeassistant/lovelace.yaml). Search-replace the four tokens in the header comment before you copy the file into HA.

## 6. Host disk and network (optional)

[`pi/host/`](pi/host/). The live files in `pi/host/` at the repo root describe this Pi (NVMe, Wi-Fi-first DNS). Use the examples when the hardware differs.
