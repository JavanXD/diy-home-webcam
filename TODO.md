# DIY roadmap

- [x] Hardware photos — `docs/diy/images/pi-camera-assembly.jpg`, `pi-full-setup.jpg`, `pi-nvme-hat-sd.jpg`
- [x] Visual crop editor on Variants (cyan box on full frame; yellow masks unchanged)
- [x] README / DIY docs readability — constrained image widths + Mermaid (architecture, first-boot, publish options)
- [x] LAN MJPEG Extra (`webcam-stream` `:8081`) — pulls `/raw.jpg` over HTTP for go2rtc / webrtc-camera; systemd + HA examples. *(freshness follows camera `capture.interval_seconds`; uncensored, LAN-only; provisioned 2026-10-14 — HEALTHY + `/stream.mjpg`)*
- [x] CCTV timestamp OSD on `webcam-stream` frames. *(top-left burn-in from camera `Last-Modified`; `overlay.*` in stream.yaml; default Europe/Berlin; stamped before go2rtc ffmpeg — 2026-10-14)*
- [x] go2rtc examples: ffmpeg MJPEG→H264 for WebRTC. *(bare MJPEG → JPEG codec mismatch; paste-ready pins `ffmpeg.h264`→libx264 + `#hardware=software` so HA cannot pick `h264_v4l2m2m` — 2026-10-14)*
- [x] HTTPS-safe webrtc-camera poster. *(use go2rtc stream name `webcam_example_live_snap`, not LAN `http://<pi>:8081/snapshot.jpg` — mixed content under HTTPS HA; no public uncensored still — 2026-10-15)*
- [x] Capture default **1s** for nearer-live MJPEG; pipeline poll stays **60s** (public R2 not tied to capture). *(camera.example.yaml + COST-PERF)*
- [x] **System Info** tab (`/system/ui`) — gauges (green/orange/red) + host/timing history charts, services, network, logs, power. *(moved off Pipeline home)*
- [ ] Optional: name a 27 W USB-C PD PSU in [docs/diy/SHOPPING-LIST.md](docs/diy/SHOPPING-LIST.md)

Start here: [docs/diy/README.md](docs/diy/README.md) · [examples/README.md](examples/README.md)
