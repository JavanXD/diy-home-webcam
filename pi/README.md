# Pi runtime (`webcam-camera` + `webcam-pipeline`)

Both units run on one Raspberry Pi. Install root defaults to `/opt/home-webcam-pipeline/`.

```bash
# From your computer (after cloning this repo)
./pi/scripts/sync-to-pi.sh pi@<pi-host>
# On the Pi:
sudo ./pi/provision.sh
```

Camera LAN UI: `http://<pi-host>:8080/` · Pipeline: `http://<pi-host>:8090/`

Secrets (R2): `/etc/webcam-pipeline/env` on the Pi — never commit. Template: [`examples/pi/r2.env`](../examples/pi/r2.env).

See [docs/diy/BUILD.md](../docs/diy/BUILD.md) and [docs/PI-HOST.md](../docs/PI-HOST.md).
