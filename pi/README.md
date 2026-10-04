# Pi runtime (camera + pipeline)

Both systemd services run on the **same Raspberry Pi**. Home Assistant only imports YAML from `homeassistant/`.

| Path | Port | Unit | Role |
|------|------|------|------|
| `pi/camera/` | 8080 | `webcam-camera` | Capture + `/raw.jpg` (always live) + `/feed.jpg` (Wartungsbild) |
| `pi/pipeline/` | 8090 | `webcam-pipeline` | Render variants, private HTTP for HA, R2 publish |

```bash
# On the Pi, from the repo root
sudo ./pi/provision.sh
```

Camera-only: `pi/camera/scripts/provision.sh`  
Pipeline-only: `pi/pipeline/scripts/provision.sh`

Operator host / SSH / IPs: `Notes.txt` and [docs/NAMING.md](../docs/NAMING.md). Secrets: `~/Projects/.secrets/raspicam.env`.  
Storage / boot / network IaC: [docs/PI-HOST.md](../docs/PI-HOST.md) (`pi/host/*.env` + `pi/scripts/`).

### Code first (Mac → Pi)

```bash
set -a && source ~/Projects/.secrets/raspicam.env && set +a
./pi/scripts/sync-to-pi.sh "${RASPICAM_SSH_USER}@${RASPICAM_HOST}"
./pi/camera/scripts/deploy.sh "${RASPICAM_SSH_USER}@${RASPICAM_HOST}"   # optional service restart path
./pi/pipeline/scripts/deploy.sh "${RASPICAM_SSH_USER}@${RASPICAM_HOST}"
```

If pipeline health shows `Permission denied` under `/opt/home-webcam-pipeline/data`, restore
service-user ownership: `sudo ./pi/scripts/fix-data-perms.sh` (also run automatically by
`sync-to-pi.sh`).
