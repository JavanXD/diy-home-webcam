# Cameras

One directory per camera. The pipeline loads only the ids listed in its config (`cameras:` in `pipeline.yaml`).

```
cameras/<id>/
  camera.yaml          # source URL, storage, publish keys, timezone, location
  variants/*.yaml      # crop, privacy masks, output size
```

Start from [`example/`](example/) or [`examples/cameras/example/`](../examples/cameras/example/).
