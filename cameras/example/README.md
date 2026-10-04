# Copy this camera

```bash
cp -R examples/cameras/example cameras/my-webcam
```

Then replace `example` in `cameras/my-webcam/camera.yaml` (`id`, storage paths, `public_live_key`, `r2_prefix_history`) and add `my-webcam` to the pipeline `cameras:` list. Details: [examples/README.md](../../README.md).
