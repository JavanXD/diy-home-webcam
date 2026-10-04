# Shared notes

- Camera profiles live under `cameras/<id>/`.
- Variant YAML uses normalized crop/mask coordinates (0–1) relative to the source image.
- Only `visibility: public` variants are uploaded to Cloudflare R2.
- Package version is defined in `shared/version.py` and exposed by Pi `/health` and the pipeline status API.
- `shared/repo_root.py` walks up until `cameras/` + `shared/` exist (works from `pi/pipeline/…`).
- `shared/jpeg_util.py` — JPEG downscale helpers for LAN preview responses.
- **`shared/lan_ui/`** — English LAN design system for camera `:8080` (green) and pipeline `:8090` (red).
  Import: `from shared import lan_ui`. Tokens, chrome, components, `window.lanUi` JS, shared favicon assets.
  Guide: [docs/LAN-UI.md](../docs/LAN-UI.md).
