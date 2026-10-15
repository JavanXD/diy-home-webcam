# webcam-stream (LAN MJPEG Extra)

Optional systemd Extra on the same Pi as capture. Serves **uncensored, downscaled** multipart MJPEG for go2rtc / the Home Assistant `webrtc-camera` card.

| | |
|--|--|
| Unit | `webcam-stream` |
| Port | `8081` |
| Config | `/etc/webcam-stream/stream.yaml` |
| Stream URL | `http://<pi>:8081/stream.mjpg` |
| Snapshot | `http://<pi>:8081/snapshot.jpg` |

## How it avoids fighting the camera

This process **never opens the CSI sensor**. It polls `webcam-camera` over loopback HTTP (`/raw.jpg?w=…`), then re-emits the latest JPEG as MJPEG. Snapshot capture (`webcam-camera`) and privacy variants (`webcam-pipeline`) keep their own processes and ports.

Picture freshness follows `capture.interval_seconds` on `:8080` (default **1s**). The Extra re-emits the same frame at `stream.fps` until the next capture lands. Raising the camera interval reduces CPU/SD wear; public R2 publish still follows pipeline poll (**60s**).

## Timestamp OSD

By default the Extra burns a CCTV-style clock into each JPEG (top-left), e.g. `14/10/2026 07:14:29 WED`. The time is the **frame capture time** from the camera `Last-Modified` header (fallback: ingest time), so a stuck still keeps a frozen clock while MJPEG still ticks. Overlay runs once at fetch — `/snapshot.jpg`, `/stream.mjpg`, and go2rtc `ffmpeg`→H264 all see the same stamp.

Tune under `overlay` in `/etc/webcam-stream/stream.yaml` (`enabled`, `timezone`, `format`, `margin`, `font_scale`), then restart `webcam-stream`. Defaults: on, `Europe/Berlin`.

## LAN only

Uncensored. Do **not** port-forward `:8081`, publish to R2, or put this URL on a Worker. Public viewers use the privacy-filtered still JPEG path only.

## Install

```bash
# With the rest of the stack
sudo ./pi/provision.sh

# Or Extra only (after webcam-camera is up)
sudo ./pi/stream/scripts/provision.sh
```

Enable / tune: edit `/etc/webcam-stream/stream.yaml` (`enabled`, `source.width`, `stream.fps`, `overlay.*`, `bind_port`), then `sudo systemctl restart webcam-stream`.

## go2rtc + Lovelace

See [`examples/homeassistant/go2rtc.yaml`](../../examples/homeassistant/go2rtc.yaml) and [`examples/homeassistant/lovelace-live.yaml`](../../examples/homeassistant/lovelace-live.yaml).

WebRTC (`mode: webrtc`) needs H264. Point go2rtc at the Extra with ffmpeg
transcode, then restart go2rtc:

```yaml
ffmpeg:
  h264: "-c:v libx264 -g 50 -profile:v high -level:v 4.1 -preset:v superfast -tune:v zerolatency -pix_fmt:v yuv420p"

streams:
  webcam_example_live:
    - ffmpeg:http://<pi>:8081/stream.mjpg#video=h264#hardware=software
```

`#hardware=software` keeps go2rtc on libx264. Bare `#hardware` (or an overridden
`ffmpeg.h264`) can select `h264_v4l2m2m`, which fails on this MJPEG source.

A bare `http://…/stream.mjpg` source stays JPEG and fails WebRTC with
`codecs not matched: video:JPEG => video:VP8,…`. `mode: mjpeg` on the card
works without transcode; prefer the ffmpeg line to match other WebRTC cams.
