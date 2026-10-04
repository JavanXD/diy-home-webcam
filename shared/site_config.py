"""Site name and camera id from this checkout's config, not from code constants.

The running project keeps its name in ``cameras/<id>/camera.yaml`` (``display_name``).
Code falls back to "Webcam" when that file is missing.
"""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_BRAND = "Webcam"


def configured_camera_ids(repo_root: Path) -> list[str]:
    """Camera ids from the pipeline config, else folders under cameras/."""
    candidates = [
        Path("/etc/webcam-pipeline/pipeline.yaml"),
        repo_root / "pi" / "pipeline" / "config" / "pipeline.yaml",
        repo_root / "pi" / "pipeline" / "config" / "pipeline.example.yaml",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if not isinstance(raw, dict):
            continue
        ids = [str(item).strip() for item in (raw.get("cameras") or []) if str(item).strip()]
        if ids:
            return ids
    root = repo_root / "cameras"
    if not root.is_dir():
        return []
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and (p / "camera.yaml").is_file() and not p.name.startswith(".")
    )


def display_name_for(repo_root: Path, camera_id: str) -> str:
    path = repo_root / "cameras" / camera_id / "camera.yaml"
    if not path.is_file():
        return DEFAULT_BRAND
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return DEFAULT_BRAND
    if not isinstance(raw, dict):
        return DEFAULT_BRAND
    name = str(raw.get("display_name") or "").strip()
    return name or DEFAULT_BRAND


def primary_site(repo_root: Path) -> tuple[str, str]:
    """``(camera_id, display_name)`` for the first configured camera."""
    ids = configured_camera_ids(repo_root)
    if not ids:
        return "", DEFAULT_BRAND
    return ids[0], display_name_for(repo_root, ids[0])


def variant_menu_items(repo_root: Path, camera_id: str) -> list[dict[str, str]]:
    """Pipeline More-menu JPEG links from this camera's variant YAML."""
    folder = repo_root / "cameras" / camera_id / "variants"
    if not camera_id or not folder.is_dir():
        return []
    items: list[dict[str, str]] = []
    for path in sorted(folder.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or path.stem).strip() or path.stem
        filename = str((raw.get("output") or {}).get("filename") or f"{name}.jpg").strip()
        if not filename or "/" in filename:
            continue
        items.append(
            {
                "label": filename,
                "port": "8090",
                "path": f"/cameras/{camera_id}/variants/{filename}",
            }
        )
    return items
