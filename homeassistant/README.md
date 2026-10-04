# Home Assistant

Copy [`packages/webcam_example.yaml`](packages/webcam_example.yaml) into your Home Assistant `packages/` directory (or use [`examples/homeassistant/webcam.yaml`](../examples/homeassistant/webcam.yaml)). Replace the Pi host and camera id.

```yaml
# configuration.yaml
homeassistant:
  packages: !include_dir_named packages
```

Reload template entities (or restart HA). `:8080` / `:8090` stay on the LAN only.
