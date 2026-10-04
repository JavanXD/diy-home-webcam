# Contributing

Thanks for taking a look. Please read the [code of conduct](CODE_OF_CONDUCT.md) first.

## Report a bug or idea

Use the issue templates. Security reports go to [SECURITY.md](SECURITY.md), not a public issue.

## Develop

```bash
make test
./scripts/smoke-local.sh
```

Camera tests are in `pi/camera/tests/`. Pipeline tests are in `pi/pipeline/tests/`.

Capture (`:8080`) and the pipeline (`:8090`) stay separate processes. Home Assistant stays a YAML import.

## Add a camera

Copy [`examples/cameras/example/`](examples/cameras/example/) to `cameras/<id>/` and follow [examples/README.md](examples/README.md). Do not commit Wi-Fi passwords, SSH keys, or R2 tokens.

New work should read `cameras/<id>/` rather than adding another site by name in Python.

## Pull requests

- Say why the change exists.
- Do not commit local `pi/camera/config/camera.yaml`, `pi/pipeline/config/pipeline.yaml`, or files from a secrets directory.
- Do not add editor or tool attribution to the commit message.
